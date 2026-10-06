import base64
import json
import os
import secrets
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from care.abdm.fidelius import _session
from care.abdm.linking import schedule_link
from care.abdm.models import (
    AbdmCareContext,
    AbdmExchange,
    AbdmFacility,
    AbdmLinkToken,
    CareContextStatus,
    ExchangeState,
)
from care.abdm.tests.fixtures import (
    ABHA_ADDRESS,
    HIP_ID,
    give_abha,
    make_clinical_encounter,
)
from care.abdm.tests.test_abha import (
    ABDM_SETTINGS,
    FakeAbdm,
    clear_abdm_cache,
    make_response,
)
from care.abdm.tests.test_fidelius import BC_GX, BC_GY, _decode, _encode, _multiply
from care.utils.tests.base import CareAPITestBase

ACCEPTED = make_response(202)
OUTBOUND_PATHS = [
    "/api/hiecm/v3/token/generate-token",
    "/api/hiecm/hip/v3/link/carecontext",
    "/api/hiecm/hip/v3/link/context/notify",
    "/api/hiecm/user-initiated-linking/v3/patient/care-context/on-discover",
    "/api/hiecm/user-initiated-linking/v3/link/care-context/on-init",
    "/api/hiecm/user-initiated-linking/v3/link/care-context/on-confirm",
    "/api/hiecm/consent/v3/request/hip/on-notify",
    "/api/hiecm/data-flow/v3/health-information/hip/on-request",
    "/api/hiecm/data-flow/v3/health-information/notify",
]


def link_token(expires_in=3600):
    claims = {"exp": int(timezone.now().timestamp()) + expires_in}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@override_settings(**ABDM_SETTINGS)
class M2TestBase(CareAPITestBase):
    def setUp(self):
        super().setUp()
        clear_abdm_cache()
        self.addCleanup(clear_abdm_cache)
        self.fake = FakeAbdm(dict.fromkeys(OUTBOUND_PATHS, ACCEPTED))
        patcher = patch("care.abdm.client.requests.request", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        with patch("care.abdm.signals.schedule_link"):
            self.encounter = make_clinical_encounter(self)
        self.patient = self.encounter.patient
        give_abha(self.patient)
        AbdmFacility.objects.create(facility=self.encounter.facility, hip_id=HIP_ID)

    def callback(self, path, body, hip_id=HIP_ID, authorization="Bearer abdm-jwt"):
        headers = {"HTTP_REQUEST_ID": "inbound-1", "HTTP_TIMESTAMP": "now"}
        if hip_id:
            headers["HTTP_X_HIP_ID"] = hip_id
        if authorization:
            headers["HTTP_AUTHORIZATION"] = authorization
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                f"/abdm/api/v3/{path}", body, format="json", **headers
            )

    def sent(self, path):
        return self.fake.call(path)


class TestHipInitiatedLinking(M2TestBase):
    def test_link_token_then_care_context(self):
        from care.abdm.linking import link_encounter

        link_encounter(self.encounter)
        request = self.sent("/api/hiecm/v3/token/generate-token")
        self.assertEqual(request["headers"]["X-HIP-ID"], HIP_ID)
        self.assertEqual(request["json"]["abhaAddress"], ABHA_ADDRESS)
        self.assertEqual(request["json"]["abhaNumber"], 91123456789012)
        self.assertEqual(request["json"]["gender"], "F")
        care_context = AbdmCareContext.objects.get(encounter=self.encounter)
        self.assertEqual(care_context.status, CareContextStatus.awaiting_token)
        self.assertNotIn("Asha", care_context.display.split(" records")[0])

        response = self.callback(
            "hip/token/on-generate-token",
            {
                "abhaAddress": ABHA_ADDRESS,
                "linkToken": link_token(),
                "response": {"requestId": request["headers"]["REQUEST-ID"]},
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(AbdmLinkToken.objects.filter(patient=self.patient).exists())

        link = self.sent("/api/hiecm/hip/v3/link/carecontext")
        self.assertTrue(link["headers"]["X-LINK-TOKEN"].startswith("header."))
        self.assertEqual(
            sorted(entry["hiType"] for entry in link["json"]["patient"]),
            ["OPConsultation", "Prescription"],
        )
        care_context.refresh_from_db()
        self.assertEqual(care_context.status, CareContextStatus.linking)

        self.callback(
            "link/on_carecontext",
            {
                "abhaAddress": ABHA_ADDRESS,
                "status": "Successfully Linked care context",
                "response": {"requestId": link["headers"]["REQUEST-ID"]},
            },
        )
        care_context.refresh_from_db()
        self.assertEqual(care_context.status, CareContextStatus.linked)
        self.assertEqual(
            sorted(care_context.linked_hi_types), ["OPConsultation", "Prescription"]
        )

        # The call and its callback read as one exchange
        outbound = AbdmExchange.objects.get(request_id=link["headers"]["REQUEST-ID"])
        self.assertEqual(outbound.state, ExchangeState.answered)
        self.assertIsNotNone(outbound.answered_by)
        self.assertNotIn(link_token(), json.dumps(outbound.headers))

    def test_refused_then_duplicate_points_at_first_cause(self):
        from care.abdm.linking import link_encounter

        self.fake.routes["/api/hiecm/v3/token/generate-token"] = [
            make_response(
                400, {"error": {"code": "ABDM-9999", "message": "User not found"}}
            ),
            make_response(
                400,
                {
                    "error": {
                        "code": "ABDM-1092",
                        "message": "Duplicate link token request",
                    }
                },
            ),
        ]
        link_encounter(self.encounter)
        care_context = AbdmCareContext.objects.get(encounter=self.encounter)
        self.assertEqual(care_context.status, CareContextStatus.failed)
        self.assertEqual(care_context.error_code, "ABDM-9999")

        link_encounter(self.encounter)
        care_context.refresh_from_db()
        self.assertEqual(care_context.error_code, "ABDM-1092")
        self.assertIn("ABDM-9999: User not found", care_context.error_message)

    def test_linked_care_context_sends_update_notification(self):
        from care.abdm.linking import link_encounter

        AbdmCareContext.objects.create(
            encounter=self.encounter,
            patient=self.patient,
            hip_id=HIP_ID,
            abha_address=ABHA_ADDRESS,
            reference_number=str(self.encounter.external_id),
            display="Outpatient visit",
            status=CareContextStatus.linked,
            linked_hi_types=["Prescription"],
        )
        link_encounter(self.encounter)
        notification = self.sent("/api/hiecm/hip/v3/link/context/notify")["json"]
        self.assertEqual(
            notification["notification"]["hiTypes"], ["OPConsultation", "Prescription"]
        )

    def test_new_record_schedules_link_once(self):
        cache.delete(f"abdm:link:debounce:{self.encounter.id}")
        with (
            patch("care.abdm.tasks.link_encounter.apply_async") as apply_async,
            self.captureOnCommitCallbacks(execute=True),
        ):
            schedule_link(self.encounter.id)
            schedule_link(self.encounter.id)
        self.assertEqual(apply_async.call_count, 1)

    def test_gateway_session_failure_fails_the_step(self):
        from care.abdm.client import AbdmError
        from care.abdm.linking import link_encounter

        with patch(
            "care.abdm.gateway.get_gateway_token",
            side_effect=AbdmError(500, "303001", "Runtime Error", "r"),
        ):
            link_encounter(self.encounter)
        care_context = AbdmCareContext.objects.get(encounter=self.encounter)
        self.assertEqual(care_context.status, CareContextStatus.failed)
        self.assertEqual(care_context.error_code, "303001")
        self.assertIn("gateway session", care_context.error_message)


class TestCallbackAuthenticity(M2TestBase):
    def test_missing_bearer_is_rejected_without_storing_the_body(self):
        response = self.callback(
            "hip/patient/care-context/discover",
            {"patient": {"id": ABHA_ADDRESS}},
            authorization=None,
        )
        self.assertEqual(response.status_code, 401)
        exchange = AbdmExchange.objects.get(direction="inbound")
        self.assertEqual(exchange.state, ExchangeState.rejected)
        self.assertIsNone(exchange.body)

    def test_other_facilities_are_rejected(self):
        response = self.callback(
            "consent/request/hip/notify", {"notification": {}}, hip_id="SOMEONE_ELSE"
        )
        self.assertEqual(response.status_code, 403)

    def test_answer_to_unknown_request_is_rejected(self):
        response = self.callback(
            "link/on_carecontext", {"response": {"requestId": "never-sent"}}
        )
        self.assertEqual(response.status_code, 403)


class TestUserInitiatedLinking(M2TestBase):
    def test_discovery_matches_only_verified_abha(self):
        self.callback(
            "hip/patient/care-context/discover",
            {
                "transactionId": "txn-1",
                "patient": {
                    "id": ABHA_ADDRESS,
                    "name": "Someone Else",
                    "gender": "M",
                    "yearOfBirth": 1950,
                },
            },
        )
        reply = self.sent(
            "/api/hiecm/user-initiated-linking/v3/patient/care-context/on-discover"
        )
        self.assertEqual(reply["headers"]["X-HIU-ID"], HIP_ID)
        self.assertEqual(reply["json"]["response"]["requestId"], "inbound-1")
        self.assertEqual(reply["json"]["matchedBy"], ["ABHA_ADDRESS"])
        self.assertEqual(
            reply["json"]["patient"][0]["careContexts"][0]["referenceNumber"],
            str(self.encounter.external_id),
        )

    def test_discovery_without_abha_match_discloses_nothing(self):
        self.callback(
            "hip/patient/care-context/discover",
            {
                "transactionId": "txn-1",
                "patient": {
                    "id": "nobody@sbx",
                    "verifiedIdentifiers": [
                        {"type": "MOBILE", "value": "+919876543210"}
                    ],
                },
            },
        )
        reply = self.sent(
            "/api/hiecm/user-initiated-linking/v3/patient/care-context/on-discover"
        )["json"]
        self.assertNotIn("patient", reply)
        self.assertIn("error", reply)

    def test_init_and_confirm_with_otp(self):
        self.callback(
            "hip/patient/care-context/discover",
            {"transactionId": "txn-1", "patient": {"id": ABHA_ADDRESS}},
        )
        reference = str(self.encounter.external_id)
        self.callback(
            "hip/link/care-context/init",
            {
                "transactionId": "txn-1",
                "abhaAddress": ABHA_ADDRESS,
                "patient": [
                    {
                        "referenceNumber": str(self.patient.external_id),
                        "careContexts": [{"referenceNumber": reference}],
                        "hiType": "Prescription",
                    }
                ],
            },
        )
        init = self.sent(
            "/api/hiecm/user-initiated-linking/v3/link/care-context/on-init"
        )["json"]
        link_reference = init["link"]["referenceNumber"]

        self.callback(
            "hip/link/care-context/confirm",
            {"confirmation": {"linkRefNumber": link_reference, "token": 111111}},
        )
        self.assertIn(
            "error",
            self.sent(
                "/api/hiecm/user-initiated-linking/v3/link/care-context/on-confirm"
            )["json"],
        )

        self.callback(
            "hip/link/care-context/confirm",
            {"confirmation": {"linkRefNumber": link_reference, "token": 123456}},
        )
        confirm = self.sent(
            "/api/hiecm/user-initiated-linking/v3/link/care-context/on-confirm"
        )["json"]
        self.assertNotIn("error", confirm)
        self.assertEqual(
            AbdmCareContext.objects.get(reference_number=reference).status,
            CareContextStatus.linked,
        )


class TestConsentAndDataFlow(M2TestBase):
    def test_consent_then_encrypted_push(self):
        from care.abdm.linking import ensure_care_context

        care_context = ensure_care_context(self.encounter, HIP_ID, ABHA_ADDRESS)
        self.callback(
            "consent/request/hip/notify",
            {
                "notification": {
                    "status": "GRANTED",
                    "consentId": "consent-1",
                    "consentDetail": {
                        "consentId": "consent-1",
                        "patient": {"id": ABHA_ADDRESS},
                        "careContexts": [
                            {
                                "patientReference": str(self.patient.external_id),
                                "careContextReference": care_context.reference_number,
                            }
                        ],
                        "hiTypes": ["Prescription"],
                        "permission": {
                            "dateRange": {
                                "from": "2000-01-01T00:00:00.000Z",
                                "to": "2100-01-01T00:00:00.000Z",
                            },
                            "dataEraseAt": "2100-01-01T00:00:00.000Z",
                        },
                    },
                    "signature": "sig",
                }
            },
        )
        ack = self.sent("/api/hiecm/consent/v3/request/hip/on-notify")["json"]
        self.assertEqual(
            ack["acknowledgement"], {"status": "OK", "consentId": "consent-1"}
        )

        hiu_private = secrets.randbelow(2**252)
        hiu_nonce = os.urandom(32)
        pushed = {}

        def push(url, json=None, headers=None, timeout=None):
            pushed.update(url=url, body=json, headers=headers)
            return make_response(202)

        with patch("care.abdm.tasks.requests.post", push):
            self.callback(
                "hip/health-information/request",
                {
                    "transactionId": "transfer-1",
                    "hiRequest": {
                        "consent": {"id": "consent-1"},
                        "dataPushUrl": "https://hiu.test/data/push",
                        "dateRange": {
                            "from": "2000-01-01T00:00:00.000Z",
                            "to": "2100-01-01T00:00:00.000Z",
                        },
                        "keyMaterial": {
                            "cryptoAlg": "ECDH",
                            "curve": "curve25519",
                            "dhPublicKey": {
                                "keyValue": base64.b64encode(
                                    _encode(_multiply(hiu_private, (BC_GX, BC_GY)))
                                ).decode()
                            },
                            "nonce": base64.b64encode(hiu_nonce).decode(),
                        },
                    },
                },
            )

        on_request = self.sent(
            "/api/hiecm/data-flow/v3/health-information/hip/on-request"
        )["json"]
        self.assertEqual(on_request["hiRequest"]["sessionStatus"], "ACKNOWLEDGED")
        self.assertEqual(pushed["url"], "https://hiu.test/data/push")
        # health-information/transfer requires the gateway session token
        self.assertEqual(pushed["headers"]["Authorization"], "Bearer gateway-token")
        entries = pushed["body"]["entries"]
        self.assertEqual(len(entries), 1)

        material = pushed["body"]["keyMaterial"]
        hip_public = _decode(
            base64.b64decode(material["dhPublicKey"]["keyValue"])[-65:]
        )
        # A requester that sent a bare point still gets the X.509 form back
        self.assertTrue(material["dhPublicKey"]["keyValue"].startswith("MIIBMTCB6g"))
        shared_x = _multiply(hiu_private, hip_public)[0].to_bytes(32, "big")
        cipher, iv = _session(shared_x, hiu_nonce, base64.b64decode(material["nonce"]))
        bundle = json.loads(
            cipher.decrypt(iv, base64.b64decode(entries[0]["content"]), None)
        )
        self.assertEqual(bundle["entry"][0]["resource"]["title"], "Prescription record")

        notify = self.sent("/api/hiecm/data-flow/v3/health-information/notify")["json"]
        self.assertRegex(
            notify["notification"]["doneAt"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
        )
        status = notify["notification"]["statusNotification"]
        self.assertEqual(status["sessionStatus"], "TRANSFERRED")
        self.assertEqual(status["statusResponses"][0]["hiStatus"], "DELIVERED")

        push_exchange = AbdmExchange.objects.get(path="https://hiu.test/data/push")
        self.assertNotIn("content", json.dumps(push_exchange.body))

        # The patient's record shows exactly the bundle the HIU decrypted
        self.client.force_authenticate(user=self.create_super_user())
        detail = self.client.get(
            reverse(
                "abdm-patient-transfer",
                kwargs={
                    "external_id": self.patient.external_id,
                    "transaction_id": "transfer-1",
                },
            )
        ).json()
        self.assertEqual(len(detail["records"]), 1)
        self.assertEqual(detail["records"][0]["bundle"], bundle)
        self.assertEqual(detail["records"][0]["checksum"], entries[0]["checksum"])

    def test_request_without_consent_is_errored(self):
        self.callback(
            "hip/health-information/request",
            {
                "transactionId": "transfer-2",
                "hiRequest": {
                    "consent": {"id": "unknown"},
                    "dataPushUrl": "https://hiu.test/data/push",
                    "keyMaterial": {},
                },
            },
        )
        on_request = self.sent(
            "/api/hiecm/data-flow/v3/health-information/hip/on-request"
        )["json"]
        self.assertEqual(on_request["hiRequest"]["sessionStatus"], "ERRORED")


class TestDeskApis(M2TestBase):
    def test_care_context_status_and_exchange_log(self):
        from care.abdm.linking import link_encounter

        link_encounter(self.encounter)
        admin = self.create_super_user()
        self.client.force_authenticate(user=admin)
        response = self.client.get(
            reverse(
                "abdm-care-context-detail",
                kwargs={"external_id": self.encounter.external_id},
            )
        )
        self.assertEqual(response.json()["status"], CareContextStatus.awaiting_token)
        self.assertEqual(len(response.json()["exchanges"]), 1)

        log = self.client.get(reverse("abdm-exchange-list")).json()
        self.assertGreaterEqual(log["count"], 1)
        row = next(r for r in log["results"] if "generate-token" in r["path"])
        self.assertIn("Authorization", row["headers"])
        self.assertIsInstance(row["headers"]["Authorization"], int)

    def test_exchange_log_is_for_administrators(self):
        self.client.force_authenticate(user=self.create_user())
        self.assertEqual(
            self.client.get(reverse("abdm-exchange-list")).status_code, 403
        )

    def test_patient_overview_lists_care_contexts_and_consents(self):
        from care.abdm.linking import ensure_care_context
        from care.abdm.models import (
            AbdmConsentArtefact,
            AbdmHealthInformationRequest,
        )

        care_context = ensure_care_context(self.encounter, HIP_ID, ABHA_ADDRESS)
        consent = AbdmConsentArtefact.objects.create(
            consent_id="consent-1",
            hip_id=HIP_ID,
            status="GRANTED",
            care_contexts=[
                {
                    "patientReference": str(self.patient.external_id),
                    "careContextReference": care_context.reference_number,
                }
            ],
            hi_types=["Prescription"],
            detail={
                "hiu": {"name": "City Clinic"},
                "purpose": {"text": "Care Management"},
            },
        )
        AbdmHealthInformationRequest.objects.create(
            transaction_id="transfer-1",
            consent=consent,
            hip_id=HIP_ID,
            data_push_url="https://hiu.test/push",
            session_status="TRANSFERRED",
        )
        AbdmConsentArtefact.objects.create(
            consent_id="someone-else", hip_id=HIP_ID, status="GRANTED"
        )

        self.client.force_authenticate(user=self.create_super_user())
        body = self.client.get(
            reverse(
                "abdm-patient-detail", kwargs={"external_id": self.patient.external_id}
            )
        ).json()
        self.assertEqual(body["abha_address"], ABHA_ADDRESS)
        self.assertEqual(
            [c["reference_number"] for c in body["care_contexts"]],
            [care_context.reference_number],
        )
        self.assertEqual([c["consent_id"] for c in body["consents"]], ["consent-1"])
        self.assertEqual(body["consents"][0]["requester"], "City Clinic")
        self.assertEqual(
            body["consents"][0]["transfers"][0]["session_status"], "TRANSFERRED"
        )

    def test_patient_overview_requires_clinical_access(self):
        self.client.force_authenticate(user=self.create_user())
        response = self.client.get(
            reverse(
                "abdm-patient-detail", kwargs={"external_id": self.patient.external_id}
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_transfer_of_another_patient_is_not_found(self):
        from care.abdm.models import (
            AbdmConsentArtefact,
            AbdmHealthInformationRequest,
        )

        consent = AbdmConsentArtefact.objects.create(
            consent_id="someone-else", hip_id=HIP_ID, status="GRANTED"
        )
        AbdmHealthInformationRequest.objects.create(
            transaction_id="transfer-other",
            consent=consent,
            hip_id=HIP_ID,
            data_push_url="https://hiu.test/push",
        )
        self.client.force_authenticate(user=self.create_super_user())
        response = self.client.get(
            reverse(
                "abdm-patient-transfer",
                kwargs={
                    "external_id": self.patient.external_id,
                    "transaction_id": "transfer-other",
                },
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_visit_preview_builds_its_records(self):
        self.client.force_authenticate(user=self.create_super_user())
        body = self.client.get(
            reverse(
                "abdm-care-context-preview",
                kwargs={"external_id": self.encounter.external_id},
            )
        ).json()
        self.assertEqual(
            sorted(r["hi_type"] for r in body["records"]),
            ["OPConsultation", "Prescription"],
        )
        self.assertEqual(body["records"][0]["bundle"]["type"], "document")
