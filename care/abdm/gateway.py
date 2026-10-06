import uuid

from django.conf import settings
from django.utils import timezone

from care.abdm.client import AbdmError, _send, get_gateway_token
from care.abdm.models import AbdmExchange, ExchangeDirection, ExchangeState


def header_lengths(headers) -> dict:
    """Record which headers were present and how long they were, never their values."""
    return {name: len(str(value)) for name, value in headers.items()}


def gateway_call(
    path: str,
    body: dict,
    *,
    hip_id: str = "",
    hiu_id: str = "",
    link_token: str = "",
    answers: AbdmExchange | None = None,
    patient=None,
    care_context=None,
    request_id: str | None = None,
) -> AbdmExchange:
    """
    POST to the HIE-CM gateway and record the exchange.

    The exchange is stored before sending so a callback that beats the HTTP
    response can still find it. A 202 only means accepted; the outcome
    arrives later on a callback.
    """
    request_id = request_id or str(uuid.uuid4())
    try:
        session_token = get_gateway_token()
    except AbdmError as e:
        # Record it as refused so the caller's step fails visibly, not silently
        return AbdmExchange.objects.create(
            request_id=request_id,
            direction=ExchangeDirection.outbound,
            path=path,
            hip_id=hip_id or hiu_id,
            state=ExchangeState.refused,
            http_status=e.status,
            error_code=e.code or "",
            error_message=f"Could not open a gateway session: {e.message}",
            body=body,
            patient=patient,
            care_context=care_context,
        )
    headers = {
        "Authorization": f"Bearer {session_token}",
        "X-CM-ID": settings.ABDM_CM_ID,
        "Content-Type": "application/json",
    }
    if hip_id:
        headers["X-HIP-ID"] = hip_id
    if hiu_id:
        headers["X-HIU-ID"] = hiu_id
    if link_token:
        headers["X-LINK-TOKEN"] = link_token

    exchange = AbdmExchange.objects.create(
        request_id=request_id,
        direction=ExchangeDirection.outbound,
        path=path,
        hip_id=hip_id or hiu_id,
        state=ExchangeState.sent,
        headers=header_lengths(
            {"REQUEST-ID": request_id, "TIMESTAMP": "x" * 24, **headers}
        ),
        body=body,
        patient=patient,
        care_context=care_context,
    )
    if answers:
        answers.answered_by = exchange
        answers.answered_at = timezone.now()
        answers.state = ExchangeState.replied
        answers.save(update_fields=["answered_by", "answered_at", "state"])

    try:
        response = _send(
            "POST",
            f"{settings.ABDM_GATEWAY_URL.rstrip('/')}{path}",
            headers=headers,
            request_id=request_id,
            json=body,
        )
    except AbdmError as e:
        exchange.state = ExchangeState.refused
        exchange.http_status = e.status
        exchange.error_code = e.code or ""
        exchange.error_message = e.message
        exchange.save(
            update_fields=["state", "http_status", "error_code", "error_message"]
        )
        return exchange

    exchange.state = ExchangeState.accepted
    exchange.http_status = response.status_code
    if response.content:
        try:
            exchange.reply = response.json()
        except ValueError:
            exchange.reply = {"text": response.text[:2000]}
    exchange.save(update_fields=["state", "http_status", "reply"])
    return exchange


def record_inbound(request, body) -> AbdmExchange:
    """Store an inbound delivery whole, before anything reads a field from it."""
    return AbdmExchange.objects.create(
        request_id=request.headers.get("REQUEST-ID", ""),
        direction=ExchangeDirection.inbound,
        path=request.path,
        hip_id=request.headers.get("X-HIP-ID") or request.headers.get("X-HIU-ID") or "",
        state=ExchangeState.received,
        headers=header_lengths(dict(request.headers)),
        body=body,
    )
