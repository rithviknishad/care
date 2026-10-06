import logging
from functools import partial

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from care.abdm import hiu, linking, tasks
from care.abdm.fidelius import KeyMaterialError
from care.abdm.gateway import record_inbound
from care.abdm.models import (
    AbdmCareContext,
    AbdmConsentArtefact,
    AbdmExchange,
    AbdmFacility,
    AbdmHealthInformationRequest,
    CareContextStatus,
    ExchangeDirection,
    ExchangeState,
)
from care.abdm.tasks import _parse_datetime

logger = logging.getLogger(__name__)


def _error(body) -> tuple[str, str]:
    error = body.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("code") or "").rstrip(": "), str(
            error.get("message") or ""
        )
    return "", str(error)


def _close(outbound: AbdmExchange, inbound: AbdmExchange):
    outbound.answered_by = inbound
    outbound.answered_at = timezone.now()
    outbound.state = ExchangeState.answered
    outbound.save(update_fields=["answered_by", "answered_at", "state"])
    inbound.patient = outbound.patient
    inbound.care_context = outbound.care_context
    inbound.error_code, inbound.error_message = _error(inbound.body)
    inbound.save(
        update_fields=["patient", "care_context", "error_code", "error_message"]
    )


def on_generate_token(inbound, body, outbound):
    _close(outbound, inbound)
    code, message = _error(body)
    awaiting = AbdmCareContext.objects.filter(
        patient=outbound.patient,
        hip_id=outbound.hip_id,
        status=CareContextStatus.awaiting_token,
    )
    if code or not body.get("linkToken"):
        awaiting.update(
            status=CareContextStatus.failed,
            error_code=code,
            error_message=message or "ABDM returned no link token",
        )
        return
    linking.store_link_token(
        outbound.patient,
        outbound.hip_id,
        body.get("abhaAddress", ""),
        body["linkToken"],
    )
    transaction.on_commit(
        partial(tasks.link_after_token.delay, outbound.patient_id, outbound.hip_id)
    )


def on_carecontext(inbound, body, outbound):
    _close(outbound, inbound)
    care_context = outbound.care_context
    if not care_context:
        return
    code, message = _error(body)
    if code:
        care_context.status = CareContextStatus.failed
        care_context.error_code, care_context.error_message = code, message
    else:
        care_context.status = CareContextStatus.linked
        care_context.linked_at = timezone.now()
        care_context.linked_hi_types = [
            entry["hiType"] for entry in (outbound.body or {}).get("patient", [])
        ]
        care_context.error_code = care_context.error_message = ""
    care_context.save()


def on_answer(inbound, body, outbound):
    _close(outbound, inbound)


def deferred(task):
    def handle(inbound, body, outbound):
        transaction.on_commit(partial(task.delay, inbound.id))

    return handle


def consent_notify(inbound, body, outbound):
    notification = body.get("notification") or {}
    detail = notification.get("consentDetail") or {}
    consent_id = notification.get("consentId") or detail.get("consentId")
    permission = detail.get("permission") or {}
    date_range = permission.get("dateRange") or {}
    defaults = {"hip_id": inbound.hip_id, "status": notification.get("status", "")}
    if detail:
        defaults.update(
            abha_address=(detail.get("patient") or {}).get("id", ""),
            care_contexts=detail.get("careContexts") or [],
            hi_types=detail.get("hiTypes") or [],
            date_from=_parse_datetime(date_range.get("from")),
            date_to=_parse_datetime(date_range.get("to")),
            data_erase_at=_parse_datetime(permission.get("dataEraseAt")),
            detail=detail,
            signature=notification.get("signature", ""),
        )
    AbdmConsentArtefact.objects.update_or_create(
        consent_id=consent_id, defaults=defaults
    )
    transaction.on_commit(
        partial(tasks.acknowledge_consent.delay, inbound.id, consent_id)
    )


def health_information_request(inbound, body, outbound):
    hi_request = body.get("hiRequest") or {}
    date_range = hi_request.get("dateRange") or {}
    record, created = AbdmHealthInformationRequest.objects.get_or_create(
        transaction_id=body.get("transactionId"),
        defaults={
            "consent": AbdmConsentArtefact.objects.filter(
                consent_id=(hi_request.get("consent") or {}).get("id")
            ).first(),
            "hip_id": inbound.hip_id,
            "data_push_url": hi_request.get("dataPushUrl", ""),
            "date_from": _parse_datetime(date_range.get("from")),
            "date_to": _parse_datetime(date_range.get("to")),
            "key_material": hi_request.get("keyMaterial") or {},
        },
    )
    if created:
        transaction.on_commit(
            partial(tasks.serve_health_information.delay, inbound.id, record.id)
        )


# CARE as HIU


def hiu_on_init(inbound, body, outbound):
    _close(outbound, inbound)
    hiu.on_init(body, outbound)


def hiu_on_status(inbound, body, outbound):
    _close(outbound, inbound)
    hiu.on_status(body)


def hiu_notify(inbound, body, outbound):
    notification = body.get("notification") or {}
    artefacts = hiu.on_notify(notification)
    consent_ids = [
        a.get("id") for a in notification.get("consentArtefacts") or [] if a.get("id")
    ]
    transaction.on_commit(
        partial(tasks.acknowledge_hiu_notify.delay, inbound.id, consent_ids)
    )
    for artefact in artefacts:
        transaction.on_commit(partial(tasks.fetch_hiu_artefact.delay, artefact.id))


def hiu_on_fetch(inbound, body, outbound):
    _close(outbound, inbound)
    artefact = hiu.apply_artefact(body)
    if artefact:
        transaction.on_commit(partial(tasks.request_hiu_records.delay, artefact.id))


def hiu_on_request(inbound, body, outbound):
    _close(outbound, inbound)
    hiu.on_records_requested(body, outbound)


# Callback path (relative to the bridge URL) -> (handler, answers one of our calls)
CALLBACKS = {
    "hip/token/on-generate-token": (on_generate_token, True),
    "link/on_carecontext": (on_carecontext, True),
    "links/context/on-notify": (on_answer, True),
    "patients/sms/on-notify": (on_answer, True),
    "hip/patient/care-context/discover": (deferred(tasks.answer_discovery), False),
    "hip/link/care-context/init": (deferred(tasks.answer_link_init), False),
    "hip/link/care-context/confirm": (deferred(tasks.answer_link_confirm), False),
    "consent/request/hip/notify": (consent_notify, False),
    "hip/health-information/request": (health_information_request, False),
    "hiu/consent/request/on-init": (hiu_on_init, True),
    "hiu/consent/request/on-status": (hiu_on_status, True),
    "hiu/consent/request/notify": (hiu_notify, False),
    "hiu/consent/on-fetch": (hiu_on_fetch, True),
    "hiu/health-information/on-request": (hiu_on_request, True),
}


class AbdmCallbackView(APIView):
    """
    Every inbound ABDM callback. Each is checked before any handler reads it:
    a bearer token is present, it is addressed to a facility this instance
    serves, and an answer answers a request this instance actually sent.
    """

    authentication_classes = []
    permission_classes = []

    def _reject(self, request, status, reason):
        exchange = record_inbound(request, None)
        exchange.state = ExchangeState.rejected
        exchange.http_status = status
        exchange.error_message = reason
        exchange.save(update_fields=["state", "http_status", "error_message"])
        logger.warning("ABDM callback %s rejected: %s", request.path, reason)
        return Response({"error": reason}, status=status)

    def post(self, request, callback):  # noqa: PLR0911
        if not settings.ABDM_ENABLED:
            return Response(status=404)
        if callback not in CALLBACKS:
            # Recorded, so a callback on a path nobody expected is still visible
            return self._reject(request, 404, "No handler for this callback path")
        handler, is_answer = CALLBACKS[callback]
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) <= 7:  # noqa: PLR2004
            return self._reject(request, 401, "Missing bearer token")

        hip_id = request.headers.get("X-HIP-ID") or request.headers.get("X-HIU-ID")
        if hip_id and not AbdmFacility.objects.filter(hip_id=hip_id).exists():
            return self._reject(request, 403, f"{hip_id} is not served here")
        body = request.data if isinstance(request.data, dict) else {}

        outbound = None
        if is_answer:
            request_id = (body.get("response") or {}).get("requestId")
            outbound = AbdmExchange.objects.filter(
                direction=ExchangeDirection.outbound, request_id=request_id
            ).first()
            if not outbound:
                return self._reject(request, 403, "Answers no request sent from here")
        elif not hip_id:
            return self._reject(request, 403, "Not addressed to a facility")

        with transaction.atomic():
            inbound = record_inbound(request, body)
            if outbound and outbound.answered_by_id:
                # A repeat delivery changes nothing
                inbound.error_message = "Duplicate delivery"
                inbound.save(update_fields=["error_message"])
            else:
                try:
                    handler(inbound, body, outbound)
                except (KeyError, TypeError, ValueError, KeyMaterialError) as e:
                    logger.exception("ABDM callback %s could not be handled", callback)
                    inbound.error_message = f"Could not handle: {e}"
                    inbound.save(update_fields=["error_message"])
        return Response(status=202)


class AbdmDataPushView(APIView):
    """
    Records a provider pushes for a consent this instance asked for. The URL
    carries a single-use token, and content only lands if it decrypts with
    the key this instance offered for that transfer.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request, token):
        if not settings.ABDM_ENABLED:
            return Response(status=404)
        body = request.data if isinstance(request.data, dict) else {}
        entries = [e for e in body.get("entries") or [] if isinstance(e, dict)]
        exchange = record_inbound(
            request,
            # Never store the records themselves, even encrypted
            {
                **body,
                "entries": [
                    {k: v for k, v in e.items() if k != "content"} for e in entries
                ],
            },
        )
        exchange.path = "/abdm/data-push/"
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) <= 7:  # noqa: PLR2004
            exchange.state = ExchangeState.rejected
            exchange.http_status = 401
            exchange.error_message = "Missing bearer token"
            exchange.save(
                update_fields=["path", "state", "http_status", "error_message"]
            )
            return Response({"error": "Missing bearer token"}, status=401)
        try:
            artefact = hiu.receive_push(token, {**body, "entries": entries})
        except hiu.PushRefusedError as e:
            exchange.state = ExchangeState.rejected
            exchange.http_status = e.status
            exchange.error_message = str(e)
            exchange.save(
                update_fields=["path", "state", "http_status", "error_message"]
            )
            logger.warning("ABDM data push rejected: %s", e)
            return Response({"error": str(e)}, status=e.status)
        exchange.hip_id = artefact.hip_id
        exchange.patient_id = artefact.consent_request.patient_id
        exchange.http_status = 202
        exchange.save(update_fields=["path", "hip_id", "patient", "http_status"])
        if not artefact.push_token:
            transaction.on_commit(partial(tasks.notify_hiu_received.delay, artefact.id))
        return Response(status=202)
