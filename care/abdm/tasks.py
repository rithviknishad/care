import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta

import requests
from celery import current_app, shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from care.abdm import hiu, linking
from care.abdm.client import AbdmError, abdm_time, get_gateway_token
from care.abdm.fhir import BUILDERS, available_hi_types
from care.abdm.fidelius import Encryptor, KeyMaterialError
from care.abdm.gateway import gateway_call, header_lengths
from care.abdm.models import (
    AbdmCareContext,
    AbdmConsentArtefact,
    AbdmExchange,
    AbdmFacility,
    AbdmHealthInformationRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuConsentRequest,
    CareContextStatus,
    ExchangeDirection,
    ExchangeState,
)
from care.emr.models import Encounter
from care.emr.models.patient import Patient, PatientIdentifier
from care.utils import sms

logger = logging.getLogger(__name__)

LINK_OTP_TTL_SECONDS = 600
LINK_OTP_MAX_ATTEMPTS = 3
NO_DATA = {"code": "ABDM-1001", "message": "No data found"}


@shared_task
def link_encounter(encounter_id: int):
    encounter = Encounter.objects.select_related("patient", "facility").get(
        id=encounter_id
    )
    linking.link_encounter(encounter)


@shared_task
def link_after_token(patient_id: int, hip_id: str):
    token = linking.valid_link_token(Patient.objects.get(id=patient_id), hip_id)
    if not token:
        return
    for care_context in AbdmCareContext.objects.filter(
        patient_id=patient_id,
        hip_id=hip_id,
        status=CareContextStatus.awaiting_token,
    ).select_related("patient", "encounter__facility"):
        linking.send_link(care_context, token)


# User initiated linking


def _patients_for(hip_id: str, patient: dict):
    """Patients matched on a verified ABHA identifier only, never on demographics."""
    candidates = {("ABHA_ADDRESS", patient.get("id"))}
    for identifier in patient.get("verifiedIdentifiers") or []:
        if identifier.get("type") in ("ABHA_NUMBER", "ABHA_ADDRESS"):
            candidates.add((identifier["type"], identifier.get("value")))
    systems = {
        "ABHA_ADDRESS": settings.ABDM_ABHA_ADDRESS_IDENTIFIER_SYSTEM,
        "ABHA_NUMBER": settings.ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM,
    }
    matched_by = set()
    patient_ids = set()
    for kind, value in candidates:
        if not value:
            continue
        ids = set(
            PatientIdentifier.objects.filter(
                config__config__system=systems[kind], value=value
            ).values_list("patient_id", flat=True)
        )
        if ids:
            matched_by.add(kind)
            patient_ids |= ids
    hip_facilities = AbdmFacility.objects.filter(hip_id=hip_id).values("facility_id")
    patients = Patient.objects.filter(
        id__in=patient_ids, encounter__facility_id__in=hip_facilities
    ).distinct()
    return list(patients), sorted(matched_by)


@shared_task
def answer_discovery(exchange_id: int):
    inbound = AbdmExchange.objects.get(id=exchange_id)
    body = inbound.body
    reply = {
        "transactionId": body.get("transactionId"),
        "response": {"requestId": inbound.request_id},
    }
    patients, matched_by = _patients_for(inbound.hip_id, body.get("patient") or {})
    care_contexts = []
    # More than one CARE patient on one ABHA is ambiguous; disclose nothing
    if len(patients) == 1:
        patient = patients[0]
        _, abha_address = linking.patient_abha(patient)
        for encounter in Encounter.objects.filter(
            patient=patient,
            facility__abdm__hip_id=inbound.hip_id,
        ).select_related("facility", "patient"):
            care_context = linking.ensure_care_context(
                encounter, inbound.hip_id, abha_address or body["patient"]["id"]
            )
            if care_context and care_context.status != CareContextStatus.linked:
                care_contexts.append(care_context)
    if care_contexts:
        reply["patient"] = linking.care_context_entries(
            care_contexts, lambda c: c.hi_types
        )
        reply["matchedBy"] = matched_by
    else:
        reply["error"] = {"code": "ABDM-9999", "message": "No matching records found"}
    gateway_call(
        "/api/hiecm/user-initiated-linking/v3/patient/care-context/on-discover",
        reply,
        hiu_id=inbound.hip_id,
        answers=inbound,
    )


def _link_otp_key(reference: str) -> str:
    return f"abdm:link-otp:{reference}"


@shared_task
def answer_link_init(exchange_id: int):
    inbound = AbdmExchange.objects.get(id=exchange_id)
    body = inbound.body
    references = [
        care_context["referenceNumber"]
        for entry in body.get("patient") or []
        for care_context in entry.get("careContexts") or []
    ]
    care_contexts = list(
        AbdmCareContext.objects.filter(
            reference_number__in=references, hip_id=inbound.hip_id
        ).select_related("patient")
    )
    reply = {
        "transactionId": body.get("transactionId"),
        "response": {"requestId": inbound.request_id},
    }
    patients = {c.patient_id for c in care_contexts}
    if not care_contexts or len(patients) != 1:
        reply["error"] = NO_DATA
    else:
        patient = care_contexts[0].patient
        otp = (
            "".join(secrets.choice("0123456789") for _ in range(6))
            if settings.IS_PRODUCTION
            else "123456"
        )
        link_reference = str(uuid.uuid4())
        expires = timezone.now() + timedelta(seconds=LINK_OTP_TTL_SECONDS)
        cache.set(
            _link_otp_key(link_reference),
            {
                "otp": otp,
                "attempts": 0,
                "care_contexts": [c.id for c in care_contexts],
                "abha_address": body.get("abhaAddress"),
            },
            LINK_OTP_TTL_SECONDS,
        )
        if settings.USE_SMS and patient.phone_number:
            sms.send_text_message(
                content=f"{otp} is the OTP to link your records with your ABHA. "
                "Do not share it with anyone.",
                recipients=[patient.phone_number],
            )
        reply["link"] = {
            "referenceNumber": link_reference,
            "authenticationType": "DIRECT",
            "meta": {
                "communicationMedium": "MOBILE",
                "communicationHint": "OTP",
                "communicationExpiry": abdm_time(expires),
            },
        }
    gateway_call(
        "/api/hiecm/user-initiated-linking/v3/link/care-context/on-init",
        reply,
        answers=inbound,
    )


@shared_task
def answer_link_confirm(exchange_id: int):
    inbound = AbdmExchange.objects.get(id=exchange_id)
    confirmation = inbound.body.get("confirmation") or {}
    key = _link_otp_key(str(confirmation.get("linkRefNumber")))
    pending = cache.get(key)
    reply = {"response": {"requestId": inbound.request_id}}
    token = str(confirmation.get("token", ""))
    if not pending or pending["attempts"] >= LINK_OTP_MAX_ATTEMPTS:
        reply["error"] = {"code": "ABDM-1001", "message": "OTP expired"}
    elif not secrets.compare_digest(token, pending["otp"]):
        pending["attempts"] += 1
        cache.set(key, pending, LINK_OTP_TTL_SECONDS)
        reply["error"] = {"code": "ABDM-1001", "message": "Invalid OTP"}
    else:
        cache.delete(key)
        care_contexts = list(
            AbdmCareContext.objects.filter(
                id__in=pending["care_contexts"]
            ).select_related("patient", "encounter__facility")
        )
        AbdmCareContext.objects.filter(id__in=pending["care_contexts"]).update(
            status=CareContextStatus.linked,
            linked_at=timezone.now(),
            abha_address=pending["abha_address"],
        )
        for care_context in care_contexts:
            care_context.linked_hi_types = care_context.hi_types
            care_context.save(update_fields=["linked_hi_types"])
        reply["patient"] = linking.care_context_entries(
            care_contexts, lambda c: c.hi_types
        )
    gateway_call(
        "/api/hiecm/user-initiated-linking/v3/link/care-context/on-confirm",
        reply,
        answers=inbound,
    )


# Consent and data flow


@shared_task
def acknowledge_consent(exchange_id: int, consent_id: str):
    inbound = AbdmExchange.objects.get(id=exchange_id)
    gateway_call(
        "/api/hiecm/consent/v3/request/hip/on-notify",
        {
            "acknowledgement": {"status": "OK", "consentId": consent_id},
            "response": {"requestId": inbound.request_id},
        },
        answers=inbound,
    )


def _parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def _encounter_date(encounter):
    start = (encounter.period or {}).get("start")
    return _parse_datetime(start) if start else encounter.created_date


def _hi_session_error(consent: AbdmConsentArtefact | None, hip_id: str) -> str | None:
    if not consent:
        return "Unknown consent"
    if consent.hip_id != hip_id:
        return "Consent was not issued to this HIP"
    if consent.status != "GRANTED":
        return f"Consent is {consent.status}"
    if consent.data_erase_at and consent.data_erase_at <= timezone.now():
        return "Consent has expired"
    return None


@shared_task
def serve_health_information(exchange_id: int, request_id: int):
    inbound = AbdmExchange.objects.get(id=exchange_id)
    hi_request = AbdmHealthInformationRequest.objects.select_related("consent").get(
        id=request_id
    )
    error = _hi_session_error(hi_request.consent, hi_request.hip_id)
    if not error:
        try:
            encryptor = Encryptor(hi_request.key_material)
        except (KeyMaterialError, KeyError, ValueError) as e:
            error = f"Unusable key material: {e}"

    acknowledgement = {
        "hiRequest": {
            "transactionId": hi_request.transaction_id,
            "sessionStatus": "ERRORED" if error else "ACKNOWLEDGED",
        },
        "response": {"requestId": inbound.request_id},
    }
    if error:
        acknowledgement["error"] = {"code": "ABDM-1001", "message": error}
    gateway_call(
        "/api/hiecm/data-flow/v3/health-information/hip/on-request",
        acknowledgement,
        answers=inbound,
    )
    if error:
        hi_request.session_status = "ERRORED"
        hi_request.error_message = error
        hi_request.save(update_fields=["session_status", "error_message"])
        return

    consent = hi_request.consent
    entries, statuses, shared = [], [], []
    for reference in consent.care_contexts:
        care_context = (
            AbdmCareContext.objects.filter(
                reference_number=reference.get("careContextReference"),
                hip_id=hi_request.hip_id,
            )
            .select_related("encounter__patient", "encounter__facility")
            .first()
        )
        status = {
            "careContextReference": reference.get("careContextReference"),
            "hiStatus": "ERRORED",
            "description": "Care context not found",
        }
        if care_context and str(care_context.patient.external_id) == reference.get(
            "patientReference", str(care_context.patient.external_id)
        ):
            encounter = care_context.encounter
            when = _encounter_date(encounter)
            in_range = (not hi_request.date_from or when >= hi_request.date_from) and (
                not hi_request.date_to or when <= hi_request.date_to
            )
            hi_types = [
                t for t in available_hi_types(encounter) if t in consent.hi_types
            ]
            for hi_type in hi_types if in_range else []:
                bundle = BUILDERS[hi_type](encounter, hi_request.hip_id)
                if not bundle:
                    continue
                content = json.dumps(bundle)
                checksum = hashlib.md5(content.encode()).hexdigest()  # noqa: S324
                entries.append(
                    {
                        "content": encryptor.encrypt(content),
                        "media": "application/fhir+json",
                        "checksum": checksum,
                        "careContextReference": care_context.reference_number,
                    }
                )
                shared.append(
                    {
                        "care_context_reference": care_context.reference_number,
                        "hi_type": hi_type,
                        "checksum": checksum,
                        "bundle": bundle,
                    }
                )
            status.update(
                hiStatus="DELIVERED",
                description="Data sent successfully"
                if in_range and hi_types
                else "No records in the consented range",
            )
        statuses.append(status)

    delivered = _push(hi_request, entries, encryptor.key_material(), inbound)
    if not delivered:
        for status in statuses:
            if status["hiStatus"] == "DELIVERED":
                status.update(hiStatus="ERRORED", description="Data push failed")
    hi_request.session_status = "TRANSFERRED" if delivered else "FAILED"
    hi_request.status_responses = statuses
    hi_request.shared = shared
    hi_request.save(update_fields=["session_status", "status_responses", "shared"])
    gateway_call(
        "/api/hiecm/data-flow/v3/health-information/notify",
        {
            "notification": {
                "consentId": consent.consent_id,
                "transactionId": hi_request.transaction_id,
                "doneAt": abdm_time(timezone.now()),
                "notifier": {"type": "HIP", "id": hi_request.hip_id},
                "statusNotification": {
                    "sessionStatus": hi_request.session_status,
                    "hipId": hi_request.hip_id,
                    "statusResponses": statuses,
                },
            }
        },
    )


def _push(hi_request, entries, key_material, inbound) -> bool:
    """POST the encrypted records straight to the HIU, not through the gateway."""
    request_id = str(uuid.uuid4())
    body = {
        "pageNumber": 1,
        "pageCount": 1,
        "transactionId": hi_request.transaction_id,
        "entries": entries,
        "keyMaterial": key_material,
    }
    headers = {"Content-Type": "application/json", "REQUEST-ID": request_id}
    try:
        # health-information/transfer makes the gateway session token mandatory
        headers["Authorization"] = f"Bearer {get_gateway_token()}"
    except AbdmError as e:
        logger.warning("ABDM data push without a gateway session: %s", e.message)
    exchange = AbdmExchange.objects.create(
        request_id=request_id,
        direction=ExchangeDirection.outbound,
        path=hi_request.data_push_url,
        hip_id=hi_request.hip_id,
        state=ExchangeState.sent,
        headers=header_lengths(headers),
        # Never store the records themselves, even encrypted
        body={
            **body,
            "entries": [
                {k: v for k, v in entry.items() if k != "content"} for entry in entries
            ],
        },
    )
    if "Authorization" not in headers:
        exchange.state = ExchangeState.refused
        exchange.error_message = "Could not open a gateway session for the push"
        exchange.save(update_fields=["state", "error_message"])
        return False
    try:
        response = requests.post(
            hi_request.data_push_url,
            json=body,
            headers=headers,
            timeout=settings.ABDM_REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        exchange.state = ExchangeState.refused
        exchange.error_message = str(e)[:500]
        exchange.save(update_fields=["state", "error_message"])
        return False
    exchange.http_status = response.status_code
    exchange.state = ExchangeState.accepted if response.ok else ExchangeState.refused
    if not response.ok:
        exchange.error_message = response.text[:500]
    exchange.save(update_fields=["http_status", "state", "error_message"])
    logger.info(
        "ABDM data push transaction=%s status=%s",
        hi_request.transaction_id,
        response.status_code,
    )
    return response.ok


# CARE as HIU


@shared_task
def send_consent_request(consent_request_id: int):
    hiu.send_consent_request(
        AbdmHiuConsentRequest.objects.select_related("patient", "requester").get(
            id=consent_request_id
        )
    )


@shared_task
def refresh_consent_status(consent_request_id: int):
    hiu.refresh_status(AbdmHiuConsentRequest.objects.get(id=consent_request_id))


@shared_task
def acknowledge_hiu_notify(exchange_id: int, consent_ids: list[str]):
    inbound = AbdmExchange.objects.get(id=exchange_id)
    gateway_call(
        "/api/hiecm/consent/v3/request/hiu/on-notify",
        {
            "acknowledgement": [
                {"status": "OK", "consentId": consent_id} for consent_id in consent_ids
            ],
            "response": {"requestId": inbound.request_id},
        },
        hiu_id=inbound.hip_id,
        answers=inbound,
    )


@shared_task
def fetch_hiu_artefact(artefact_id: int):
    artefact = AbdmHiuConsentArtefact.objects.select_related(
        "consent_request__patient"
    ).get(id=artefact_id)
    if hiu.fetch_artefact(artefact):
        hiu.request_records(artefact)


@shared_task
def request_hiu_records(artefact_id: int):
    hiu.request_records(
        AbdmHiuConsentArtefact.objects.select_related("consent_request__patient").get(
            id=artefact_id
        )
    )


@shared_task
def notify_hiu_received(artefact_id: int):
    hiu.notify_received(
        AbdmHiuConsentArtefact.objects.select_related("consent_request__patient").get(
            id=artefact_id
        )
    )


@shared_task
def erase_expired_hiu_records():
    hiu.erase_expired()


@current_app.on_after_finalize.connect
def setup_abdm_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        3600, erase_expired_hiu_records.s(), name="erase_expired_hiu_records"
    )
