"""CARE as HIU: asking a patient's consent manager for records other providers hold."""

import json
import logging
import secrets
import uuid
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from care.abdm.client import abdm_time
from care.abdm.fidelius import Decryptor, KeyMaterialError
from care.abdm.gateway import gateway_call
from care.abdm.linking import STALE_STEP_SECONDS
from care.abdm.models import (
    AbdmExchange,
    AbdmHiuConsentArtefact,
    AbdmHiuConsentRequest,
    AbdmHiuRecord,
    ExchangeState,
    HiuConsentStatus,
)

logger = logging.getLogger(__name__)

# The purpose enumeration consent/v3/request/init publishes
PURPOSES = {
    "CAREMGT": "Care Management",
    "BTG": "Break the Glass",
    "PUBHLTH": "Public Health",
    "HPAYMT": "Healthcare Payment",
    "DSRCH": "Disease Specific Healthcare Research",
    "PATRQT": "Self Requested",
}
PURPOSE_REF_URI = "http://terminology.hl7.org/ValueSet/v3-PurposeOfUse"
# The HI types ABDM-1006 names as the ones it accepts
HI_TYPES = (
    "Prescription",
    "DiagnosticReport",
    "OPConsultation",
    "DischargeSummary",
    "ImmunizationRecord",
    "HealthDocumentRecord",
    "WellnessRecord",
    "Invoice",
)
ENDED = (HiuConsentStatus.denied, HiuConsentStatus.expired, HiuConsentStatus.revoked)


def _parse_time(value):
    return datetime.fromisoformat(value) if value else None


def data_push_url(token: str) -> str | None:
    base = settings.ABDM_CALLBACK_BASE_URL.rstrip("/")
    return f"{base}/abdm/data-push/{token}/" if base else None


def _error(body) -> tuple[str, str]:
    error = (body or {}).get("error") or {}
    if isinstance(error, dict):
        return str(error.get("code") or "").rstrip(": "), str(
            error.get("message") or ""
        )
    return "", str(error)


def _requester(user, hiu_id: str) -> dict:
    professional = getattr(user, "abdm_professional", None)
    registration = (
        professional.hpr_id_number
        if professional
        else getattr(user, "doctor_medical_council_registration", None)
    )
    if registration:
        identifier = {
            "value": registration,
            "type": "REGNO",
            "system": settings.ABDM_HPR_IDENTIFIER_SYSTEM,
        }
    else:
        identifier = {"value": user.username, "type": "USER", "system": hiu_id}
    return {"name": user.get_full_name() or user.username, "identifier": identifier}


def _refuse(consent_request, code: str, message: str):
    consent_request.status = HiuConsentStatus.failed
    consent_request.error_code, consent_request.error_message = code, message
    consent_request.save(update_fields=["status", "error_code", "error_message"])


def send_consent_request(consent_request: AbdmHiuConsentRequest):
    consent_request.request_id = str(uuid.uuid4())
    consent_request.save(update_fields=["request_id"])
    exchange = gateway_call(
        "/api/hiecm/consent/v3/request/init",
        {
            "consent": {
                "purpose": {
                    "text": PURPOSES[consent_request.purpose],
                    "code": consent_request.purpose,
                    "refUri": PURPOSE_REF_URI,
                },
                "patient": {"id": consent_request.abha_address},
                "hiu": {"id": consent_request.hiu_id},
                "requester": _requester(
                    consent_request.requester, consent_request.hiu_id
                ),
                "hiTypes": consent_request.hi_types,
                "permission": {
                    "accessMode": "VIEW",
                    "dateRange": {
                        "from": abdm_time(consent_request.date_from),
                        "to": abdm_time(consent_request.date_to),
                    },
                    "dataEraseAt": abdm_time(consent_request.data_erase_at),
                    "frequency": {"unit": "HOUR", "value": 1, "repeats": 0},
                },
            }
        },
        hiu_id=consent_request.hiu_id,
        patient=consent_request.patient,
        request_id=consent_request.request_id,
    )
    if exchange.state == ExchangeState.refused:
        _refuse(consent_request, exchange.error_code, exchange.error_message)


def give_up_if_unanswered(consent_request: AbdmHiuConsentRequest):
    """Without on-init there is no consent request id, so not even status can be asked."""
    if (
        consent_request.status == HiuConsentStatus.sending
        and (timezone.now() - consent_request.created_date).total_seconds()
        > STALE_STEP_SECONDS
    ):
        _refuse(
            consent_request,
            "",
            "ABDM accepted this request but its answer never reached this instance. "
            "Check that the bridge URL points here, then request again.",
        )


def apply_status(consent_request: AbdmHiuConsentRequest, status: str):
    if status not in HiuConsentStatus.values or status == consent_request.status:
        return
    consent_request.status = status
    consent_request.save(update_fields=["status"])


def on_init(body: dict, outbound: AbdmExchange):
    consent_request = AbdmHiuConsentRequest.objects.filter(
        request_id=outbound.request_id
    ).first()
    if not consent_request:
        return
    code, message = _error(body)
    consent_request_id = (body.get("consentRequest") or {}).get("id")
    if code or not consent_request_id:
        _refuse(consent_request, code, message or "ABDM returned no consent request id")
        return
    consent_request.consent_request_id = consent_request_id
    consent_request.status = HiuConsentStatus.requested
    consent_request.error_code = consent_request.error_message = ""
    consent_request.save(
        update_fields=["consent_request_id", "status", "error_code", "error_message"]
    )


def refresh_status(consent_request: AbdmHiuConsentRequest):
    exchange = gateway_call(
        "/api/hiecm/consent/v3/request/status",
        {"consentRequestId": consent_request.consent_request_id},
        hiu_id=consent_request.hiu_id,
        patient=consent_request.patient,
    )
    # A 200 carries the answer itself; a 202 means it comes on the callback
    if exchange.http_status == 200 and exchange.reply:  # noqa: PLR2004
        on_status(exchange.reply)


def on_status(body: dict):
    status = body.get("consentRequest") or {}
    consent_request = AbdmHiuConsentRequest.objects.filter(
        consent_request_id=status.get("id") or ""
    ).first()
    if consent_request and not _error(body)[0]:
        apply_status(consent_request, status.get("status", ""))


def on_notify(notification: dict) -> list[AbdmHiuConsentArtefact]:
    """Apply a grant, denial, expiry or revocation; return the artefacts to fetch."""
    consent_request = AbdmHiuConsentRequest.objects.filter(
        consent_request_id=notification.get("consentRequestId") or ""
    ).first()
    if not consent_request:
        return []
    status = notification.get("status", "")
    apply_status(consent_request, status)
    ids = [
        a.get("id") for a in notification.get("consentArtefacts") or [] if a.get("id")
    ]
    if status == HiuConsentStatus.granted:
        # Every artefact, one per HIP: taking the first silently drops the rest
        return [
            AbdmHiuConsentArtefact.objects.get_or_create(
                consent_id=consent_id,
                defaults={"consent_request": consent_request},
            )[0]
            for consent_id in ids
        ]
    if status in ENDED:
        artefacts = consent_request.artefacts.all()
        if ids:
            artefacts = artefacts.filter(consent_id__in=ids)
        end_artefacts(artefacts, status)
    return []


def end_artefacts(artefacts, status: str):
    """Stop using the artefacts and erase what they brought in."""
    AbdmHiuRecord.objects.filter(artefact__in=artefacts).delete()
    artefacts.update(status=status, key_secret=None, push_token="")


def fetch_artefact(
    artefact: AbdmHiuConsentArtefact,
) -> AbdmHiuConsentArtefact | None:
    consent_request = artefact.consent_request
    exchange = gateway_call(
        "/api/hiecm/consent/v3/fetch",
        {"consentId": artefact.consent_id},
        hiu_id=consent_request.hiu_id,
        patient=consent_request.patient,
    )
    if exchange.state == ExchangeState.refused:
        artefact.error_code = exchange.error_code
        artefact.error_message = exchange.error_message
        artefact.save(update_fields=["error_code", "error_message"])
        return None
    # A 200 carries the artefact itself; a 202 means it comes on the callback
    if exchange.http_status == 200 and exchange.reply:  # noqa: PLR2004
        return apply_artefact(exchange.reply)
    return None


def usable(artefact: AbdmHiuConsentArtefact) -> bool:
    return artefact.status == HiuConsentStatus.granted and (
        not artefact.data_erase_at or artefact.data_erase_at > timezone.now()
    )


def apply_artefact(body: dict) -> AbdmHiuConsentArtefact | None:
    """Store a fetched artefact; return it when records may be requested under it."""
    consent = body.get("consent") or {}
    detail = consent.get("consentDetail") or {}
    artefact = (
        AbdmHiuConsentArtefact.objects.filter(consent_id=detail.get("consentId") or "")
        .select_related("consent_request")
        .first()
    )
    if not artefact:
        return None
    code, message = _error(body)
    if code:
        artefact.error_code, artefact.error_message = code, message
        artefact.save(update_fields=["error_code", "error_message"])
        return None
    consent_request = artefact.consent_request
    if (detail.get("hiu") or {}).get("id") != consent_request.hiu_id or (
        detail.get("patient") or {}
    ).get("id") != consent_request.abha_address:
        artefact.error_message = "The artefact names another HIU or patient"
        artefact.save(update_fields=["error_message"])
        return None

    permission = detail.get("permission") or {}
    date_range = permission.get("dateRange") or {}
    hip = detail.get("hip") or {}
    artefact.status = consent.get("status") or artefact.status
    artefact.hip_id = hip.get("id", "")
    artefact.hip_name = hip.get("name", "")
    artefact.care_contexts = detail.get("careContexts") or []
    artefact.hi_types = detail.get("hiTypes") or []
    artefact.date_from = _parse_time(date_range.get("from"))
    artefact.date_to = _parse_time(date_range.get("to"))
    artefact.data_erase_at = _parse_time(
        permission.get("dataEraseAt") or detail.get("dataEraseAt")
    )
    artefact.detail = detail
    artefact.signature = consent.get("signature", "")
    artefact.error_code = artefact.error_message = ""
    artefact.save()
    return artefact if usable(artefact) else None


def _fail_transfer(artefact, code: str, message: str):
    artefact.session_status = "FAILED"
    artefact.key_secret = None
    artefact.push_token = ""
    artefact.error_code, artefact.error_message = code, message
    artefact.save(
        update_fields=[
            "session_status",
            "key_secret",
            "push_token",
            "error_code",
            "error_message",
        ]
    )


def request_records(artefact: AbdmHiuConsentArtefact):
    if not usable(artefact):
        return
    token = secrets.token_urlsafe(32)
    push_url = data_push_url(token)
    if not push_url:
        _fail_transfer(
            artefact,
            "",
            "ABDM_CALLBACK_BASE_URL is not set, so providers have nowhere to push records",
        )
        return
    decryptor = Decryptor()
    artefact.hi_request_id = str(uuid.uuid4())
    artefact.push_token = token
    artefact.key_secret = decryptor.secret()
    artefact.transaction_id = ""
    artefact.session_status = "REQUESTED"
    artefact.pages_received = 0
    artefact.status_responses = []
    artefact.error_code = artefact.error_message = ""
    artefact.save()

    consent_request = artefact.consent_request
    exchange = gateway_call(
        "/api/hiecm/data-flow/v3/health-information/request",
        {
            "hiRequest": {
                "consent": {"id": artefact.consent_id},
                "dateRange": {
                    "from": abdm_time(artefact.date_from or consent_request.date_from),
                    "to": abdm_time(artefact.date_to or consent_request.date_to),
                },
                "dataPushUrl": push_url,
                "keyMaterial": decryptor.key_material(),
            }
        },
        hiu_id=consent_request.hiu_id,
        patient=consent_request.patient,
        request_id=artefact.hi_request_id,
    )
    if exchange.state == ExchangeState.refused:
        _fail_transfer(artefact, exchange.error_code, exchange.error_message)


def on_records_requested(body: dict, outbound: AbdmExchange):
    artefact = AbdmHiuConsentArtefact.objects.filter(
        hi_request_id=outbound.request_id
    ).first()
    if not artefact:
        return
    code, message = _error(body)
    if code:
        _fail_transfer(artefact, code, message)
        return
    hi_request = body.get("hiRequest") or {}
    artefact.transaction_id = artefact.transaction_id or hi_request.get(
        "transactionId", ""
    )
    if artefact.session_status == "REQUESTED":
        artefact.session_status = hi_request.get("sessionStatus") or "ACKNOWLEDGED"
    artefact.save(update_fields=["transaction_id", "session_status"])


class PushRefusedError(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status


def _receive_entry(artefact, decryptor, key_material, entry, allowed) -> dict:
    reference = entry.get("careContextReference")
    status = {"careContextReference": reference, "hiStatus": "ERRORED"}
    if reference not in allowed:
        return {**status, "description": "Care context is not in the consent"}
    if not entry.get("content"):
        return {**status, "description": "Only inline content is supported"}
    try:
        bundle = json.loads(decryptor.decrypt(entry["content"], key_material))
    except KeyMaterialError as e:
        return {**status, "description": str(e)}
    except ValueError:
        return {**status, "description": "Content is not JSON"}
    # AES-GCM already authenticates the content; the checksum's algorithm is not published
    AbdmHiuRecord.objects.create(
        artefact=artefact,
        care_context_reference=reference,
        checksum=str(entry.get("checksum") or "")[:64],
        bundle=bundle,
    )
    return {
        "careContextReference": reference,
        "hiStatus": "OK",
        "description": "Data received successfully",
    }


def receive_push(token: str, body: dict) -> AbdmHiuConsentArtefact:
    """Decrypt and store one page; the artefact's session ends with its last page."""
    artefact = (
        AbdmHiuConsentArtefact.objects.select_for_update()
        .filter(push_token=token, key_secret__isnull=False)
        .first()
    )
    if not token or not artefact:
        raise PushRefusedError(404, "No transfer is waiting at this URL")
    transaction_id = body.get("transactionId") or ""
    if artefact.transaction_id and transaction_id != artefact.transaction_id:
        raise PushRefusedError(400, "transactionId does not match this transfer")
    if not usable(artefact):
        end_artefacts(
            AbdmHiuConsentArtefact.objects.filter(id=artefact.id),
            artefact.status if artefact.status in ENDED else HiuConsentStatus.expired,
        )
        raise PushRefusedError(403, "The consent no longer allows these records")

    decryptor = Decryptor(artefact.key_secret)
    allowed = {c.get("careContextReference") for c in artefact.care_contexts}
    statuses = {s["careContextReference"]: s for s in artefact.status_responses}
    for entry in body.get("entries") or []:
        status = _receive_entry(
            artefact, decryptor, body.get("keyMaterial") or {}, entry, allowed
        )
        previous = statuses.get(status["careContextReference"])
        # One failed entry leaves its care context errored
        if not previous or previous["hiStatus"] != "ERRORED":
            statuses[status["careContextReference"]] = status

    artefact.transaction_id = artefact.transaction_id or transaction_id
    artefact.status_responses = list(statuses.values())
    artefact.pages_received += 1
    if artefact.pages_received >= int(body.get("pageCount") or 1):
        received = any(s["hiStatus"] == "OK" for s in statuses.values())
        artefact.session_status = "RECEIVED" if received else "FAILED"
        artefact.key_secret = None
        artefact.push_token = ""
    artefact.save()
    return artefact


def notify_received(artefact: AbdmHiuConsentArtefact):
    consent_request = artefact.consent_request
    gateway_call(
        "/api/hiecm/data-flow/v3/health-information/notify",
        {
            "notification": {
                "consentId": artefact.consent_id,
                "transactionId": artefact.transaction_id,
                "doneAt": abdm_time(timezone.now()),
                "notifier": {"type": "HIU", "id": consent_request.hiu_id},
                "statusNotification": {
                    "sessionStatus": artefact.session_status,
                    "hipId": artefact.hip_id,
                    "statusResponses": artefact.status_responses,
                },
            }
        },
        hiu_id=consent_request.hiu_id,
        patient=consent_request.patient,
    )


def erase_expired():
    expired = AbdmHiuConsentArtefact.objects.filter(
        data_erase_at__lte=timezone.now()
    ).exclude(status__in=ENDED)
    count = AbdmHiuRecord.objects.filter(artefact__in=expired).count()
    end_artefacts(expired, HiuConsentStatus.expired)
    if count:
        logger.info("ABDM erased %s records past their consent", count)
