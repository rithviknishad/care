import re
from typing import Literal

from django.conf import settings
from django.http import HttpResponse
from pydantic import UUID4, BaseModel, field_validator
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from care.abdm import crypto
from care.abdm.client import AbdmError, abha_json, abha_request
from care.abdm.journey import (
    Journey,
    recall_refresh_token,
    remember_refresh_token,
)
from care.abdm.profile import format_abha_number, to_patient_facts
from care.emr.api.viewsets.base import EMRBaseViewSet, emr_exception_handler
from care.emr.models.patient import Patient, PatientIdentifier, PatientIdentifierConfig
from care.security.authorization import AuthorizationController
from care.utils.shortcuts import get_object_or_404

ABHA_NOT_FOUND = "ABDM-1114"
ENROLMENT_CONSENT = {"code": "abha-enrollment", "version": "1.4"}
ABHA_ADDRESS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.]*[A-Za-z0-9]$")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


class MobileSpec(BaseModel):
    mobile: str

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value):
        digits = _digits(value)[-10:]
        if len(digits) != 10:  # noqa: PLR2004
            msg = "Enter a 10 digit mobile number"
            raise ValueError(msg)
        return digits


class JourneySpec(BaseModel):
    journey_id: UUID4


class LoginRequestOtpSpec(BaseModel):
    journey_id: UUID4 | None = None
    identifier_type: Literal["aadhaar", "abha_number", "mobile_index"]
    value: str
    otp_system: Literal["aadhaar", "abdm"] = "aadhaar"


class OtpSpec(JourneySpec):
    otp: str

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value):
        if not value.isdigit():
            msg = "OTP must be numeric"
            raise ValueError(msg)
        return value


class SelectAccountSpec(JourneySpec):
    abha_number: str


class EnrolRequestOtpSpec(BaseModel):
    journey_id: UUID4 | None = None
    aadhaar: str

    @field_validator("aadhaar")
    @classmethod
    def validate_aadhaar(cls, value):
        digits = _digits(value)
        if len(digits) != 12:  # noqa: PLR2004
            msg = "Enter a 12 digit Aadhaar number"
            raise ValueError(msg)
        return digits


class EnrolVerifyOtpSpec(OtpSpec, MobileSpec):
    pass


class EnrolMobileRequestOtpSpec(JourneySpec, MobileSpec):
    pass


class AbhaAddressSpec(JourneySpec):
    abha_address: str

    @field_validator("abha_address")
    @classmethod
    def validate_abha_address(cls, value):
        value = value.strip().split("@")[0]
        if not ABHA_ADDRESS_PATTERN.match(value):
            msg = (
                "ABHA address may contain letters, digits and dots, must start "
                "with a letter and cannot end with a dot"
            )
            raise ValueError(msg)
        return value


def abdm_exception_handler(exc, context):
    if not isinstance(exc, AbdmError):
        return emr_exception_handler(exc, context)
    if exc.status == 400 and not exc.code:  # noqa: PLR2004
        # A field refusal on an encrypted value is often a rotated certificate
        crypto.invalidate_certificate()
    if exc.code == ABHA_NOT_FOUND:
        status, error_type = 404, "abha_not_found"
    elif exc.status >= 500:  # noqa: PLR2004
        status, error_type = 502, "abdm_unavailable"
    else:
        status, error_type = 400, "abdm_error"
    return Response(
        {
            "errors": [
                {
                    "type": error_type,
                    "code": exc.code,
                    "msg": exc.message or "ABDM refused the request",
                    "request_id": exc.request_id,
                }
            ]
        },
        status=status,
    )


def get_identifier_config(system: str) -> PatientIdentifierConfig | None:
    return PatientIdentifierConfig.objects.filter(
        facility__isnull=True, config__system=system, status="active"
    ).first()


def _account(account: dict) -> dict:
    return {
        "index": account.get("index"),
        "abha_number": format_abha_number(account.get("ABHANumber")),
        "abha_address": account.get("preferredAbhaAddress"),
        "name": account.get("name"),
        "gender": account.get("gender"),
        "status": account.get("status"),
        "kyc_verified": str(account.get("kycVerified")).lower() == "true",
        "auth_methods": account.get("authMethods") or [],
        "photo": account.get("profilePhoto"),
    }


def _store_tokens(journey: Journey, data: dict):
    token = data.get("token")
    if not token:
        return
    journey.set_user_token(token, data.get("expiresIn"))
    journey["refresh_token"] = data.get("refreshToken")
    journey["refresh_expires_in"] = data.get("refreshExpiresIn")


def _require_user_token(journey: Journey) -> str:
    token = journey.x_token
    if not token:
        raise NotFound("ABHA session expired. Verify again.")
    return token


class AbhaViewSet(EMRBaseViewSet):
    def get_exception_handler(self):
        return abdm_exception_handler

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.action == "config":
            return
        if not settings.ABDM_ENABLED:
            raise NotFound("ABDM is not enabled")
        if self.action not in ("card", "qr_code") and not AuthorizationController.call(
            "can_create_patient", request.user
        ):
            raise PermissionDenied("Cannot register patients")

    @action(detail=False, methods=["GET"])
    def config(self, request):
        if not settings.ABDM_ENABLED:
            return Response({"enabled": False})
        number_config = get_identifier_config(
            settings.ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM
        )
        address_config = get_identifier_config(
            settings.ABDM_ABHA_ADDRESS_IDENTIFIER_SYSTEM
        )
        return Response(
            {
                "enabled": True,
                "demo_auth": settings.ABDM_DEMO_AUTH_ENABLED,
                "face_auth": settings.ABDM_FACE_AUTH_ENABLED,
                "identifier_configs": {
                    "abha_number": number_config and str(number_config.external_id),
                    "abha_address": address_config and str(address_config.external_id),
                },
            }
        )

    # Lookup and login

    @action(detail=False, methods=["POST"])
    def search(self, request):
        """Free lookup by mobile: lists the accounts it carries without sending an OTP."""
        data = MobileSpec(**request.data)
        response = abha_json(
            "POST",
            "/v3/profile/account/abha/search",
            json={"scope": ["search-abha"], "mobile": crypto.encrypt(data.mobile)},
        )
        results = response if isinstance(response, list) else [response]
        txn_id = next((r.get("txnId") for r in results if r.get("txnId")), None)
        accounts = [_account(a) for r in results for a in r.get("ABHA") or []]
        if not accounts:
            return Response(
                {"errors": [{"type": "abha_not_found", "msg": "No ABHA found"}]},
                status=404,
            )
        journey = Journey.start(request.user)
        journey["search_txn_id"] = txn_id
        journey.save()
        return Response({"journey_id": journey.id, "accounts": accounts})

    @action(detail=False, methods=["POST"])
    def login_request_otp(self, request):
        data = LoginRequestOtpSpec(**request.data)
        journey = Journey.load_or_start(data.journey_id, request.user)
        body = {"otpSystem": data.otp_system}
        if data.identifier_type == "aadhaar":
            body.update(
                scope=["abha-login", "aadhaar-verify"],
                loginHint="aadhaar",
                loginId=crypto.encrypt(_digits(data.value)),
                otpSystem="aadhaar",
            )
        elif data.identifier_type == "abha_number":
            verify = (
                "aadhaar-verify" if data.otp_system == "aadhaar" else "mobile-verify"
            )
            body.update(
                scope=["abha-login", verify],
                loginHint="abha-number",
                loginId=crypto.encrypt(format_abha_number(data.value) or data.value),
            )
        else:
            if not journey["search_txn_id"]:
                raise NotFound("Search by mobile before choosing an account")
            body.update(
                scope=["abha-login", "search-abha", "mobile-verify"],
                loginHint="index",
                loginId=crypto.encrypt(str(data.value)),
                otpSystem="abdm",
                txnId=journey["search_txn_id"],
            )
        response = abha_json("POST", "/v3/profile/login/request/otp", json=body)
        journey["txn_id"] = response.get("txnId")
        journey["login_scope"] = [s for s in body["scope"] if s != "search-abha"]
        journey.save()
        return Response({"journey_id": journey.id, "message": response.get("message")})

    @action(detail=False, methods=["POST"])
    def login_verify_otp(self, request):
        data = OtpSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        response = abha_json(
            "POST",
            "/v3/profile/login/verify",
            json={
                "scope": journey["login_scope"],
                "authData": {
                    "authMethods": ["otp"],
                    "otp": {
                        "txnId": journey["txn_id"],
                        "otpValue": crypto.encrypt(data.otp),
                    },
                },
            },
        )
        journey["txn_id"] = response.get("txnId") or journey["txn_id"]
        accounts = [_account(a) for a in response.get("accounts") or []]
        # A refreshToken means this is already the user token; without one it
        # is a transfer token that must be exchanged for the chosen account.
        if response.get("refreshToken"):
            _store_tokens(journey, response)
            login_status = "verified"
        else:
            journey["t_token"] = response.get("token")
            login_status = "select_account"
        journey.save()
        return Response(
            {"journey_id": journey.id, "status": login_status, "accounts": accounts}
        )

    @action(detail=False, methods=["POST"])
    def login_select_account(self, request):
        data = SelectAccountSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        if not journey["t_token"]:
            raise NotFound("Verify the OTP before choosing an account")
        response = abha_json(
            "POST",
            "/v3/profile/login/verify/user",
            json={
                "ABHANumber": format_abha_number(data.abha_number),
                "txnId": journey["txn_id"],
            },
            t_token=journey["t_token"],
        )
        _store_tokens(journey, response)
        journey["t_token"] = None
        journey.save()
        return Response({"journey_id": journey.id, "status": "verified"})

    @action(detail=False, methods=["GET"])
    def profile(self, request):
        data = JourneySpec(**request.query_params.dict())
        journey = Journey.load(data.journey_id, request.user)
        profile = abha_json(
            "GET", "/v3/profile/account", x_token=_require_user_token(journey)
        )
        facts = to_patient_facts(profile)
        remember_refresh_token(
            facts["abha_number"],
            journey["refresh_token"],
            journey["refresh_expires_in"],
        )
        return Response({"journey_id": journey.id, "profile": facts})

    # Enrolment by Aadhaar OTP

    @action(detail=False, methods=["POST"])
    def enrol_request_otp(self, request):
        data = EnrolRequestOtpSpec(**request.data)
        journey = Journey.load_or_start(data.journey_id, request.user)
        response = abha_json(
            "POST",
            "/v3/enrollment/request/otp",
            json={
                "txnId": "",
                "scope": ["abha-enrol"],
                "loginHint": "aadhaar",
                "loginId": crypto.encrypt(data.aadhaar),
                "otpSystem": "aadhaar",
            },
        )
        journey["txn_id"] = response.get("txnId")
        journey.save()
        return Response({"journey_id": journey.id, "message": response.get("message")})

    @action(detail=False, methods=["POST"])
    def enrol_verify_otp(self, request):
        data = EnrolVerifyOtpSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        response = abha_json(
            "POST",
            "/v3/enrollment/enrol/byAadhaar",
            json={
                "authData": {
                    "authMethods": ["otp"],
                    "otp": {
                        "txnId": journey["txn_id"],
                        "otpValue": crypto.encrypt(data.otp),
                        "mobile": data.mobile,
                    },
                },
                "consent": ENROLMENT_CONSENT,
            },
        )
        journey["txn_id"] = response.get("txnId") or journey["txn_id"]
        _store_tokens(journey, response.get("tokens") or {})
        abha_profile = response.get("ABHAProfile") or {}
        facts = to_patient_facts(abha_profile)
        remember_refresh_token(
            facts["abha_number"],
            journey["refresh_token"],
            journey["refresh_expires_in"],
        )
        journey.save()
        # Aadhaar's registered mobile differs from the one given: verify it before use
        mobile_verification_required = (
            _digits(str(abha_profile.get("mobile") or "")) != data.mobile
        )
        return Response(
            {
                "journey_id": journey.id,
                "is_new": bool(response.get("isNew")),
                "mobile_verification_required": mobile_verification_required,
                "profile": facts,
            }
        )

    @action(detail=False, methods=["POST"])
    def enrol_mobile_request_otp(self, request):
        data = EnrolMobileRequestOtpSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        response = abha_json(
            "POST",
            "/v3/enrollment/request/otp",
            json={
                "txnId": journey["txn_id"],
                "scope": ["abha-enrol", "mobile-verify"],
                "loginHint": "mobile",
                "loginId": crypto.encrypt(data.mobile),
                "otpSystem": "abdm",
            },
        )
        journey["txn_id"] = response.get("txnId") or journey["txn_id"]
        journey.save()
        return Response({"journey_id": journey.id, "message": response.get("message")})

    @action(detail=False, methods=["POST"])
    def enrol_mobile_verify_otp(self, request):
        data = OtpSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        response = abha_json(
            "POST",
            "/v3/enrollment/auth/byAbdm",
            json={
                "scope": ["abha-enrol", "mobile-verify"],
                "authData": {
                    "authMethods": ["otp"],
                    "otp": {
                        "txnId": journey["txn_id"],
                        "otpValue": crypto.encrypt(data.otp),
                    },
                },
            },
        )
        journey["txn_id"] = response.get("txnId") or journey["txn_id"]
        journey.save()
        return Response(
            {
                "journey_id": journey.id,
                "verified": response.get("authResult") == "success",
                "message": response.get("message"),
            }
        )

    @action(detail=False, methods=["GET"])
    def enrol_address_suggestions(self, request):
        data = JourneySpec(**request.query_params.dict())
        journey = Journey.load(data.journey_id, request.user)
        response = abha_json(
            "GET",
            "/v3/enrollment/enrol/suggestion",
            transaction_id=journey["txn_id"],
        )
        return Response(
            {
                "journey_id": journey.id,
                "suggestions": response.get("abhaAddressList") or [],
            }
        )

    @action(detail=False, methods=["POST"])
    def enrol_address(self, request):
        data = AbhaAddressSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        response = abha_json(
            "POST",
            "/v3/enrollment/enrol/abha-address",
            json={
                "txnId": journey["txn_id"],
                "abhaAddress": data.abha_address,
                "preferred": 1,
            },
        )
        return Response(
            {
                "journey_id": journey.id,
                "abha_number": format_abha_number(response.get("healthIdNumber")),
                "abha_address": response.get("preferredAbhaAddress"),
            }
        )

    # ABHA card and QR code

    def _card_user_token(self, request) -> str:
        if request.query_params.get("journey_id"):
            data = JourneySpec(**request.query_params.dict())
            return _require_user_token(Journey.load(data.journey_id, request.user))

        patient = get_object_or_404(
            Patient, external_id=request.query_params.get("patient")
        )
        if not AuthorizationController.call(
            "can_view_patient_obj", request.user, patient
        ):
            raise PermissionDenied("Cannot view this patient")
        identifier = PatientIdentifier.objects.filter(
            patient=patient,
            config__facility__isnull=True,
            config__config__system=settings.ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM,
        ).first()
        if not identifier:
            raise NotFound("Patient has no ABHA number")
        refresh_token = recall_refresh_token(identifier.value)
        if not refresh_token:
            return Response(
                {
                    "errors": [
                        {
                            "type": "abha_reauth_required",
                            "msg": "Verify the patient's ABHA to view the card",
                            "abha_number": identifier.value,
                        }
                    ]
                },
                status=409,
            )
        response = abha_json(
            "GET", "/v3/profile/account/request/token", r_token=refresh_token
        )
        return response["token"]

    def _proxy_image(self, request, path: str):
        token = self._card_user_token(request)
        if isinstance(token, Response):
            return token
        response = abha_request("GET", path, x_token=token)
        return HttpResponse(
            response.content,
            content_type=response.headers.get("Content-Type", "image/png"),
        )

    @action(detail=False, methods=["GET"])
    def card(self, request):
        return self._proxy_image(request, "/v3/profile/account/abha-card")

    @action(detail=False, methods=["GET"])
    def qr_code(self, request):
        return self._proxy_image(request, "/v3/profile/account/qrCode")
