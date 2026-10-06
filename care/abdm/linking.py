import base64
import json
import logging
import re
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from care.abdm.client import abdm_time
from care.abdm.fhir import available_hi_types
from care.abdm.gateway import gateway_call
from care.abdm.models import (
    AbdmCareContext,
    AbdmExchange,
    AbdmFacility,
    AbdmLinkToken,
    CareContextStatus,
    ExchangeState,
)
from care.emr.models.patient import PatientIdentifier

logger = logging.getLogger(__name__)

LINK_DEBOUNCE_SECONDS = 30
# A link step that has had no answer for this long may be started again
STALE_STEP_SECONDS = 600
DUPLICATE_LINK_TOKEN_REQUEST = "ABDM-1092"

GENDERS = {"male": "M", "female": "F", "transgender": "T"}
VISIT_NAMES = {
    "amb": "Outpatient visit",
    "imp": "Inpatient admission",
    "emer": "Emergency visit",
    "vr": "Teleconsultation",
    "hh": "Home visit",
    "obsenc": "Observation visit",
}


def hip_id_for(facility) -> str | None:
    return (
        AbdmFacility.objects.filter(facility=facility)
        .values_list("hip_id", flat=True)
        .first()
    )


def patient_abha(patient) -> tuple[str | None, str | None]:
    values = dict(
        PatientIdentifier.objects.filter(
            patient=patient,
            config__config__system__in=[
                settings.ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM,
                settings.ABDM_ABHA_ADDRESS_IDENTIFIER_SYSTEM,
            ],
        ).values_list("config__config__system", "value")
    )
    return (
        values.get(settings.ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM),
        values.get(settings.ABDM_ABHA_ADDRESS_IDENTIFIER_SYSTEM),
    )


def care_context_display(encounter) -> str:
    """What the patient reads in their PHR app; never a diagnosis or a result."""
    start = (encounter.period or {}).get("start") or encounter.created_date
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    visit = VISIT_NAMES.get(encounter.encounter_class, "Visit")
    return f"{visit} at {encounter.facility.name} on {start:%d %b %Y}"


def patient_display(patient, facility) -> str:
    return f"{facility.name} records for {patient.name}"


def _token_expiry(token: str):
    """Read `exp` from the JWT payload; the signature is ABDM's to check, not ours."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return datetime.fromtimestamp(claims["exp"], tz=UTC)
    except (IndexError, KeyError, ValueError):
        return None


def valid_link_token(patient, hip_id) -> str | None:
    token = AbdmLinkToken.objects.filter(patient=patient, hip_id=hip_id).first()
    if not token or not token.token:
        return None
    if token.expires_at and token.expires_at <= timezone.now():
        return None
    return token.token


def store_link_token(patient, hip_id, abha_address, token):
    AbdmLinkToken.objects.update_or_create(
        patient=patient,
        hip_id=hip_id,
        defaults={
            "abha_address": abha_address,
            "token": token,
            "expires_at": _token_expiry(token),
        },
    )


def schedule_link(encounter_id: int):
    """Start linking after the transaction commits, once per burst of record saves."""
    if not settings.ABDM_ENABLED:
        return
    if not cache.add(f"abdm:link:debounce:{encounter_id}", 1, LINK_DEBOUNCE_SECONDS):
        return
    from care.abdm.tasks import link_encounter

    transaction.on_commit(
        lambda: link_encounter.apply_async(
            args=[encounter_id], countdown=LINK_DEBOUNCE_SECONDS
        )
    )


def _fail(care_context: AbdmCareContext, exchange: AbdmExchange):
    care_context.status = CareContextStatus.failed
    care_context.error_code = exchange.error_code
    care_context.error_message = exchange.error_message
    if exchange.error_code == DUPLICATE_LINK_TOKEN_REQUEST:
        first = (
            AbdmExchange.objects.filter(
                patient=care_context.patient,
                path=exchange.path,
                state=ExchangeState.refused,
            )
            .exclude(id=exchange.id)
            .exclude(error_code=DUPLICATE_LINK_TOKEN_REQUEST)
            .order_by("-created_date")
            .first()
        )
        # ABDM remembers a refused request; the earlier refusal names the cause
        care_context.error_message = (
            "ABDM refused this as a repeat of an earlier link token request."
            + (
                f" The earlier refusal was {first.error_code}: {first.error_message}"
                if first
                else ""
            )
        )
    care_context.save(update_fields=["status", "error_code", "error_message"])


def _in_flight(care_context: AbdmCareContext) -> bool:
    return (
        care_context.status
        in (CareContextStatus.awaiting_token, CareContextStatus.linking)
        and (timezone.now() - care_context.modified_date).total_seconds()
        < STALE_STEP_SECONDS
    )


def request_link_token(care_context: AbdmCareContext, abha_number: str | None):
    patient = care_context.patient
    body = {
        "abhaAddress": care_context.abha_address,
        "name": patient.name,
        "gender": GENDERS.get(patient.gender, "O"),
        "yearOfBirth": patient.year_of_birth,
    }
    if abha_number:
        body["abhaNumber"] = int(re.sub(r"\D", "", abha_number))
    exchange = gateway_call(
        "/api/hiecm/v3/token/generate-token",
        body,
        hip_id=care_context.hip_id,
        patient=patient,
        care_context=care_context,
    )
    if exchange.state == ExchangeState.refused:
        _fail(care_context, exchange)
        return
    care_context.status = CareContextStatus.awaiting_token
    care_context.error_code = care_context.error_message = ""
    care_context.save(update_fields=["status", "error_code", "error_message"])


def care_context_entries(care_contexts, hi_types_of) -> list[dict]:
    """Group care contexts into the per-hiType patient entries ABDM expects."""
    by_type: dict[str, list] = {}
    for care_context in care_contexts:
        for hi_type in hi_types_of(care_context):
            by_type.setdefault(hi_type, []).append(care_context)
    entries = []
    for hi_type, contexts in by_type.items():
        first = contexts[0]
        entries.append(
            {
                "referenceNumber": str(first.patient.external_id),
                "display": patient_display(first.patient, first.encounter.facility),
                "careContexts": [
                    {"referenceNumber": c.reference_number, "display": c.display}
                    for c in contexts
                ],
                "hiType": hi_type,
                "count": len(contexts),
            }
        )
    return entries


def send_link(care_context: AbdmCareContext, link_token: str):
    abha_number, _ = patient_abha(care_context.patient)
    body = {
        "abhaAddress": care_context.abha_address,
        "patient": care_context_entries([care_context], lambda c: c.hi_types),
    }
    if abha_number:
        body["abhaNumber"] = int(re.sub(r"\D", "", abha_number))
    exchange = gateway_call(
        "/api/hiecm/hip/v3/link/carecontext",
        body,
        hip_id=care_context.hip_id,
        link_token=link_token,
        patient=care_context.patient,
        care_context=care_context,
    )
    if exchange.state == ExchangeState.refused:
        _fail(care_context, exchange)
        return
    care_context.status = CareContextStatus.linking
    care_context.error_code = care_context.error_message = ""
    care_context.save(update_fields=["status", "error_code", "error_message"])


def notify_update(care_context: AbdmCareContext):
    exchange = gateway_call(
        "/api/hiecm/hip/v3/link/context/notify",
        {
            "notification": {
                "patient": {"id": care_context.abha_address},
                "careContext": {
                    "patientReference": str(care_context.patient.external_id),
                    "careContextReference": care_context.reference_number,
                },
                "hiTypes": care_context.hi_types,
                "date": abdm_time(timezone.now()),
                "hip": {"id": care_context.hip_id},
            }
        },
        hip_id=care_context.hip_id,
        patient=care_context.patient,
        care_context=care_context,
    )
    if exchange.state != ExchangeState.refused:
        care_context.linked_hi_types = care_context.hi_types
        care_context.notified_at = timezone.now()
        care_context.save(update_fields=["linked_hi_types", "notified_at"])


def ensure_care_context(encounter, hip_id, abha_address) -> AbdmCareContext | None:
    hi_types = available_hi_types(encounter)
    if not hi_types:
        return None
    care_context, _ = AbdmCareContext.objects.get_or_create(
        encounter=encounter,
        defaults={
            "patient": encounter.patient,
            "hip_id": hip_id,
            "abha_address": abha_address,
            "reference_number": str(encounter.external_id),
            "display": care_context_display(encounter),
        },
    )
    if care_context.hi_types != hi_types:
        care_context.hi_types = hi_types
        care_context.save(update_fields=["hi_types"])
    return care_context


def link_encounter(encounter):
    hip_id = hip_id_for(encounter.facility)
    abha_number, abha_address = patient_abha(encounter.patient)
    if not hip_id or not abha_address:
        return
    care_context = ensure_care_context(encounter, hip_id, abha_address)
    if not care_context or _in_flight(care_context):
        return
    if care_context.status == CareContextStatus.linked:
        notify_update(care_context)
        return
    token = valid_link_token(encounter.patient, hip_id)
    if token:
        send_link(care_context, token)
    else:
        request_link_token(care_context, abha_number)
