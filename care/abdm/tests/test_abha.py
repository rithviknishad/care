import base64
import json
from unittest.mock import patch

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from care.abdm import crypto
from care.abdm.client import GATEWAY_TOKEN_CACHE_KEY, _find_error
from care.abdm.journey import forget_refresh_token
from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig
from care.security.permissions.patient import PatientPermissions
from care.utils.tests.base import CareAPITestBase

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
).decode()
OAEP_SHA1 = "RSA/ECB/OAEPWithSHA-1AndMGF1Padding"
ABHA_NUMBER = "91-1234-5678-9012"

ABDM_SETTINGS = {
    "ABDM_ENABLED": True,
    "ABDM_GATEWAY_URL": "https://gateway.test",
    "ABDM_ABHA_URL": "https://abha.test/abha/api",
    "ABDM_CLIENT_ID": "client",
    "ABDM_CLIENT_SECRET": "secret",
}


def clear_abdm_cache():
    cache.delete_many([GATEWAY_TOKEN_CACHE_KEY, crypto.CERTIFICATE_CACHE_KEY])
    forget_refresh_token(ABHA_NUMBER)


def decrypt(value: str) -> str:
    return PRIVATE_KEY.decrypt(
        base64.b64decode(value),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),  # noqa: S303
            algorithm=hashes.SHA1(),  # noqa: S303
            label=None,
        ),
    ).decode()


def make_response(status, body=None, content_type="application/json"):
    response = requests.Response()
    response.status_code = status
    if isinstance(body, bytes):
        response._content = body  # noqa: SLF001
    else:
        response._content = json.dumps(body).encode() if body is not None else b""  # noqa: SLF001
    response.headers["Content-Type"] = content_type
    return response


class FakeAbdm:
    """Routes outbound ABDM calls by path and records them."""

    def __init__(self, routes=None, algorithm=OAEP_SHA1):
        self.calls = []
        self.routes = {
            "/api/hiecm/gateway/v3/sessions": make_response(
                200, {"accessToken": "gateway-token", "expiresIn": 1200}
            ),
            "/v3/profile/public/certificate": make_response(
                200, {"publicKey": PUBLIC_KEY_B64, "encryptionAlgorithm": algorithm}
            ),
            **(routes or {}),
        }

    def __call__(self, method, url, headers=None, json=None, timeout=None, params=None):
        path = (
            url.split("abha/api")[-1] if "abha/api" in url else url.split(".test")[-1]
        )
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": headers,
                "json": json,
                "params": params,
            }
        )
        route = self.routes[path]
        return route.pop(0) if isinstance(route, list) else route

    def call(self, path):
        return next(c for c in reversed(self.calls) if c["path"] == path)

    def called(self, path):
        return any(c["path"] == path for c in self.calls)


class TestErrorParsing(CareAPITestBase):
    def test_code_with_separator(self):
        self.assertEqual(
            _find_error({"code": "ABDM-1114: ", "message": "User not found"}),
            ("ABDM-1114", "User not found"),
        )

    def test_nested_error(self):
        self.assertEqual(
            _find_error({"error": {"code": "ABDM-1204", "message": "Invalid OTP"}}),
            ("ABDM-1204", "Invalid OTP"),
        )

    def test_field_refusal_and_empty_body(self):
        self.assertEqual(
            _find_error({"loginId": "LoginId is invalid"}),
            (None, "loginId: LoginId is invalid"),
        )
        self.assertEqual(_find_error(None), (None, ""))


@override_settings(**ABDM_SETTINGS)
class TestCrypto(CareAPITestBase):
    def setUp(self):
        super().setUp()
        clear_abdm_cache()
        self.addCleanup(clear_abdm_cache)

    def test_encrypts_with_published_algorithm(self):
        with patch("care.abdm.client.requests.request", FakeAbdm()):
            self.assertEqual(decrypt(crypto.encrypt("123412341234")), "123412341234")

    def test_refuses_unknown_algorithm(self):
        with (
            patch("care.abdm.client.requests.request", FakeAbdm(algorithm="AES/GCM")),
            self.assertRaises(crypto.UnsupportedEncryptionAlgorithmError),
        ):
            crypto.encrypt("123412341234")


@override_settings(**ABDM_SETTINGS)
class TestAbhaApi(CareAPITestBase):
    def setUp(self):
        super().setUp()
        clear_abdm_cache()
        self.addCleanup(clear_abdm_cache)
        self.user = self.create_user()
        organization = self.create_organization(org_type="govt")
        role = self.create_role_with_permissions(
            permissions=[
                PatientPermissions.can_create_patient.name,
                PatientPermissions.can_list_patients.name,
            ]
        )
        self.attach_role_organization_user(organization, self.user, role)
        self.client.force_authenticate(user=self.user)

    def url(self, name):
        return reverse(f"abdm-abha-{name.replace('_', '-')}")

    def post(self, name, data, fake):
        with patch("care.abdm.client.requests.request", fake):
            return self.client.post(self.url(name), data, format="json")

    def get(self, name, params, fake):
        with patch("care.abdm.client.requests.request", fake):
            return self.client.get(self.url(name), params)

    def test_config_when_disabled(self):
        with override_settings(ABDM_ENABLED=False):
            response = self.client.get(self.url("config"))
            self.assertEqual(response.json(), {"enabled": False})
            response = self.client.post(self.url("search"), {"mobile": "9999999999"})
            self.assertEqual(response.status_code, 404)

    def test_requires_create_patient_permission(self):
        self.client.force_authenticate(user=self.create_user())
        response = self.post("search", {"mobile": "9999999999"}, FakeAbdm())
        self.assertEqual(response.status_code, 403)

    def test_aadhaar_without_abha_is_not_found(self):
        fake = FakeAbdm(
            {
                "/v3/profile/login/request/otp": make_response(
                    404, {"code": "ABDM-1114: ", "message": "User not found"}
                )
            }
        )
        response = self.post(
            "login_request_otp",
            {"identifier_type": "aadhaar", "value": "1234 1234 1234"},
            fake,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["errors"][0]["type"], "abha_not_found")
        sent = fake.call("/v3/profile/login/request/otp")
        self.assertEqual(decrypt(sent["json"]["loginId"]), "123412341234")
        self.assertTrue(sent["headers"]["REQUEST-ID"])
        self.assertTrue(sent["headers"]["TIMESTAMP"].endswith("Z"))
        self.assertEqual(sent["headers"]["Authorization"], "Bearer gateway-token")

    def test_aadhaar_login_uses_token_directly(self):
        fake = FakeAbdm(
            {
                "/v3/profile/login/request/otp": make_response(
                    200, {"txnId": "txn-1", "message": "OTP sent to ******1234"}
                ),
                "/v3/profile/login/verify": make_response(
                    200,
                    {
                        "txnId": "txn-2",
                        "token": "user-token",
                        "expiresIn": 1800,
                        "refreshToken": "refresh-token",
                        "refreshExpiresIn": 1296000,
                        "accounts": [{"ABHANumber": ABHA_NUMBER, "name": "Asha"}],
                    },
                ),
                "/v3/profile/account": make_response(
                    200,
                    {
                        "ABHANumber": ABHA_NUMBER,
                        "preferredAbhaAddress": "asha@sbx",
                        "firstName": "Asha",
                        "lastName": "Kumari",
                        "gender": "F",
                        "dayOfBirth": "5",
                        "monthOfBirth": "3",
                        "yearOfBirth": "1990",
                        "mobile": "9876543210",
                        "pincode": "682001",
                    },
                ),
            }
        )
        response = self.post(
            "login_request_otp",
            {"identifier_type": "aadhaar", "value": "123412341234"},
            fake,
        )
        self.assertEqual(response.status_code, 200)
        journey_id = response.json()["journey_id"]

        response = self.post(
            "login_verify_otp", {"journey_id": journey_id, "otp": "123456"}, fake
        )
        self.assertEqual(response.json()["status"], "verified")
        self.assertEqual(
            decrypt(
                fake.call("/v3/profile/login/verify")["json"]["authData"]["otp"][
                    "otpValue"
                ]
            ),
            "123456",
        )
        self.assertFalse(fake.called("/v3/profile/login/verify/user"))

        response = self.get("profile", {"journey_id": journey_id}, fake)
        profile = response.json()["profile"]
        self.assertEqual(profile["name"], "Asha Kumari")
        self.assertEqual(profile["gender"], "female")
        self.assertEqual(profile["date_of_birth"], "1990-03-05")
        self.assertEqual(profile["phone_number"], "+919876543210")
        self.assertEqual(profile["abha_address"], "asha@sbx")
        self.assertEqual(
            fake.call("/v3/profile/account")["headers"]["X-token"], "Bearer user-token"
        )

    def test_mobile_lookup_then_exchange_transfer_token(self):
        fake = FakeAbdm(
            {
                "/v3/profile/account/abha/search": make_response(
                    200,
                    [
                        {
                            "txnId": "search-txn",
                            "ABHA": [
                                {
                                    "index": 1,
                                    "ABHANumber": "xx-xxxx-xxxx-9012",
                                    "name": "A",
                                },
                                {
                                    "index": 2,
                                    "ABHANumber": "xx-xxxx-xxxx-3456",
                                    "name": "B",
                                },
                            ],
                        }
                    ],
                ),
                "/v3/profile/login/request/otp": make_response(
                    200, {"txnId": "otp-txn"}
                ),
                "/v3/profile/login/verify": make_response(
                    200,
                    {
                        "txnId": "otp-txn",
                        "token": "transfer-token",
                        "accounts": [{"ABHANumber": ABHA_NUMBER}],
                    },
                ),
                "/v3/profile/login/verify/user": make_response(
                    200, {"token": "user-token", "expiresIn": 1800, "refreshToken": "r"}
                ),
            }
        )
        response = self.post("search", {"mobile": "+91 98765 43210"}, fake)
        self.assertEqual(len(response.json()["accounts"]), 2)
        self.assertEqual(
            decrypt(fake.call("/v3/profile/account/abha/search")["json"]["mobile"]),
            "9876543210",
        )
        journey_id = response.json()["journey_id"]

        self.post(
            "login_request_otp",
            {"journey_id": journey_id, "identifier_type": "mobile_index", "value": "2"},
            fake,
        )
        sent = fake.call("/v3/profile/login/request/otp")["json"]
        self.assertEqual(sent["txnId"], "search-txn")
        self.assertEqual(sent["loginHint"], "index")
        self.assertEqual(decrypt(sent["loginId"]), "2")

        response = self.post(
            "login_verify_otp", {"journey_id": journey_id, "otp": "123456"}, fake
        )
        self.assertEqual(response.json()["status"], "select_account")
        self.assertNotIn(
            "search-abha", fake.call("/v3/profile/login/verify")["json"]["scope"]
        )

        response = self.post(
            "login_select_account",
            {"journey_id": journey_id, "abha_number": "91123456789012"},
            fake,
        )
        self.assertEqual(response.json()["status"], "verified")
        exchange = fake.call("/v3/profile/login/verify/user")
        self.assertEqual(exchange["headers"]["T-token"], "Bearer transfer-token")
        self.assertEqual(exchange["json"]["ABHANumber"], ABHA_NUMBER)

    def test_journey_is_bound_to_its_user(self):
        fake = FakeAbdm(
            {"/v3/profile/login/request/otp": make_response(200, {"txnId": "t"})}
        )
        response = self.post(
            "login_request_otp",
            {"identifier_type": "aadhaar", "value": "123412341234"},
            fake,
        )
        journey_id = response.json()["journey_id"]
        other = self.create_user()
        organization = self.create_organization(org_type="govt")
        role = self.create_role_with_permissions(
            permissions=[PatientPermissions.can_create_patient.name]
        )
        self.attach_role_organization_user(organization, other, role)
        self.client.force_authenticate(user=other)
        response = self.post(
            "login_verify_otp", {"journey_id": journey_id, "otp": "123456"}, fake
        )
        self.assertEqual(response.status_code, 404)

    def test_enrolment_by_aadhaar_otp(self):
        fake = FakeAbdm(
            {
                "/v3/enrollment/request/otp": [
                    make_response(200, {"txnId": "enrol-txn", "message": "sent"}),
                    make_response(200, {"txnId": "enrol-txn"}),
                ],
                "/v3/enrollment/enrol/byAadhaar": make_response(
                    200,
                    {
                        "txnId": "enrol-txn",
                        "tokens": {"token": "user-token", "expiresIn": 1800},
                        "ABHAProfile": {
                            "firstName": "Ravi",
                            "dob": "01-02-1985",
                            "gender": "M",
                            "mobile": "9000000000",
                            "ABHANumber": ABHA_NUMBER,
                        },
                        "isNew": True,
                    },
                ),
                "/v3/enrollment/enrol/suggestion": make_response(
                    200, {"abhaAddressList": ["ravi.1985", "ravi85"]}
                ),
                "/v3/enrollment/enrol/abha-address": make_response(
                    200,
                    {
                        "healthIdNumber": ABHA_NUMBER,
                        "preferredAbhaAddress": "ravi85@sbx",
                    },
                ),
            }
        )
        response = self.post("enrol_request_otp", {"aadhaar": "1234-1234-1234"}, fake)
        journey_id = response.json()["journey_id"]

        response = self.post(
            "enrol_verify_otp",
            {"journey_id": journey_id, "otp": "123456", "mobile": "9876543210"},
            fake,
        )
        body = response.json()
        self.assertTrue(body["is_new"])
        self.assertTrue(body["mobile_verification_required"])
        self.assertEqual(body["profile"]["date_of_birth"], "1985-02-01")
        enrol = fake.call("/v3/enrollment/enrol/byAadhaar")["json"]
        self.assertEqual(
            enrol["consent"], {"code": "abha-enrollment", "version": "1.4"}
        )

        self.post(
            "enrol_mobile_request_otp",
            {"journey_id": journey_id, "mobile": "9876543210"},
            fake,
        )
        self.assertEqual(
            fake.call("/v3/enrollment/request/otp")["json"]["scope"],
            ["abha-enrol", "mobile-verify"],
        )

        response = self.get(
            "enrol_address_suggestions", {"journey_id": journey_id}, fake
        )
        self.assertEqual(response.json()["suggestions"], ["ravi.1985", "ravi85"])
        self.assertEqual(
            fake.call("/v3/enrollment/enrol/suggestion")["headers"]["TRANSACTION_ID"],
            "enrol-txn",
        )

        response = self.post(
            "enrol_address",
            {"journey_id": journey_id, "abha_address": "ravi85@sbx"},
            fake,
        )
        self.assertEqual(response.json()["abha_address"], "ravi85@sbx")
        self.assertEqual(
            fake.call("/v3/enrollment/enrol/abha-address")["json"]["abhaAddress"],
            "ravi85",
        )

    def test_abha_address_rules(self):
        for address in ("1ravi", ".ravi", "ravi.", "9876543210", "ravi_kumar"):
            response = self.post(
                "enrol_address",
                {
                    "journey_id": "4f1c8b8e-6f0e-4a8e-9a43-0c7e2f6f2b11",
                    "abha_address": address,
                },
                FakeAbdm(),
            )
            self.assertEqual(response.status_code, 400, address)

    def test_card_requires_reverification_without_refresh_token(self):
        config = PatientIdentifierConfig.objects.create(
            status="active",
            config={
                "use": "official",
                "system": "https://healthid.abdm.gov.in",
                "required": False,
                "unique": True,
                "regex": "",
                "display": "ABHA Number",
            },
        )
        patient = self.create_patient()
        PatientIdentifier.objects.create(
            patient=patient, config=config, value=ABHA_NUMBER
        )
        self.client.force_authenticate(user=self.create_super_user())
        response = self.get("card", {"patient": str(patient.external_id)}, FakeAbdm())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"][0]["type"], "abha_reauth_required")
