import logging
import re
import uuid
from datetime import UTC, datetime

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

GATEWAY_TOKEN_CACHE_KEY = "abdm:gateway:access_token"
# Renew the gateway token this many seconds before ABDM says it expires
GATEWAY_TOKEN_RENEW_MARGIN = 60

ERROR_CODE_PATTERN = re.compile(r"(ABDM-\d+|\b\d{6}\b)")
AUTH_FAILURE_CODES = {"900900", "900901", "900902"}
PLACEHOLDER_PATTERN = re.compile(r"\s*\{\d+\}")


class AbdmError(Exception):
    def __init__(self, status: int, code: str | None, message: str, request_id: str):
        super().__init__(f"{status} {code or ''} {message}".strip())
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id

    def has_code(self, code: str) -> bool:
        return self.code == code


def abdm_time(value: datetime) -> str:
    """The one timestamp form ABDM accepts: UTC, milliseconds, trailing Z."""
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _timestamp() -> str:
    return abdm_time(datetime.now(UTC))


def _find_error(body) -> tuple[str | None, str]:
    """Pull an error code and message out of the several shapes ABDM refuses with."""
    if isinstance(body, list) and any(isinstance(item, dict) for item in body):
        errors = [_find_error(item) for item in body if isinstance(item, dict)]
        code = next((code for code, _ in errors if code), None)
        return code, "; ".join(message for _, message in errors if message)
    if not isinstance(body, dict):
        text = str(body or "")
        match = ERROR_CODE_PATTERN.search(text)
        return (match.group(1) if match else None), text

    details = body.get("details")
    if isinstance(details, list) and any(isinstance(item, dict) for item in details):
        # The registries wrap the real cause (HIS-3008 Invalid HPID) in a generic HIS-422
        code, message = _find_error(details)
        if code or message:
            return code, message

    nested = body.get("error") if isinstance(body.get("error"), dict) else {}
    raw_code = str(
        body.get("code") or body.get("errorCode") or nested.get("code") or ""
    )
    match = ERROR_CODE_PATTERN.search(raw_code)
    code = match.group(1) if match else (raw_code or None)
    message = body.get("message") or nested.get("message") or body.get("details")
    if not message:
        # A field-level refusal names the field rather than carrying a message
        message = "; ".join(
            f"{key}: {value}" for key, value in body.items() if isinstance(value, str)
        )
    # The registries leave format placeholders in their 500 messages
    return code, PLACEHOLDER_PATTERN.sub("", str(message or ""))


def _parse_error(response: requests.Response, request_id: str) -> AbdmError:
    body = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = response.text
    code, message = _find_error(body)
    return AbdmError(response.status_code, code, message, request_id)


def _send(
    method: str, url: str, headers: dict, request_id: str | None = None, **kwargs
) -> requests.Response:
    request_id = request_id or str(uuid.uuid4())
    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": _timestamp(),
        **headers,
    }
    logger.info("ABDM %s %s request_id=%s", method, url, request_id)
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=settings.ABDM_REQUEST_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as e:
        logger.warning(
            "ABDM %s %s request_id=%s failed: %s", method, url, request_id, e
        )
        raise AbdmError(503, None, "ABDM is unreachable", request_id) from e
    logger.info(
        "ABDM %s %s request_id=%s status=%s",
        method,
        url,
        request_id,
        response.status_code,
    )
    if not response.ok:
        error = _parse_error(response, request_id)
        if error.code in AUTH_FAILURE_CODES:
            # Drop the cached token so the next call starts a fresh session
            cache.delete(GATEWAY_TOKEN_CACHE_KEY)
        raise error
    return response


def get_gateway_token() -> str:
    token = cache.get(GATEWAY_TOKEN_CACHE_KEY)
    if token:
        return token
    response = _send(
        "POST",
        f"{settings.ABDM_GATEWAY_URL.rstrip('/')}/api/hiecm/gateway/v3/sessions",
        headers={"X-CM-ID": settings.ABDM_CM_ID, "Content-Type": "application/json"},
        json={
            "clientId": settings.ABDM_CLIENT_ID,
            "clientSecret": settings.ABDM_CLIENT_SECRET,
            "grantType": "client_credentials",
        },
    )
    data = response.json()
    token = data["accessToken"]
    ttl = int(data.get("expiresIn", 0)) - GATEWAY_TOKEN_RENEW_MARGIN
    if ttl > 0:
        cache.set(GATEWAY_TOKEN_CACHE_KEY, token, ttl)
    return token


def abha_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    x_token: str | None = None,
    t_token: str | None = None,
    r_token: str | None = None,
    transaction_id: str | None = None,
) -> requests.Response:
    headers = {"Authorization": f"Bearer {get_gateway_token()}"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    if x_token:
        headers["X-token"] = f"Bearer {x_token}"
    if t_token:
        headers["T-token"] = f"Bearer {t_token}"
    if r_token:
        headers["R-token"] = f"Bearer {r_token}"
    if transaction_id:
        headers["TRANSACTION_ID"] = transaction_id
    return _send(
        method,
        f"{settings.ABDM_ABHA_URL.rstrip('/')}/{path.lstrip('/')}",
        headers=headers,
        json=json,
    )


def abha_json(method: str, path: str, **kwargs):
    response = abha_request(method, path, **kwargs)
    if not response.content:
        return {}
    return response.json()


def registry_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    hpr_token: str | None = None,
    verifier_token: str | None = None,
) -> requests.Response:
    """A call to the facility and professional registries (HFR, HPR)."""
    headers = {"Authorization": f"Bearer {get_gateway_token()}"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    if hpr_token:
        headers["x-hprid-auth"] = hpr_token
    if verifier_token:
        headers["x-hprid-auth-verifier"] = verifier_token
    return _send(
        method,
        f"{settings.ABDM_REGISTRY_URL.rstrip('/')}/{path.lstrip('/')}",
        headers=headers,
        json=json,
        params=params,
    )


def registry_json(method: str, path: str, **kwargs):
    response = registry_request(method, path, **kwargs)
    if not response.content:
        return None
    return response.json()
