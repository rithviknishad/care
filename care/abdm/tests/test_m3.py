import json
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from care.abdm import hiu
from care.abdm.fidelius import Encryptor
from care.abdm.models import (
    AbdmHiuConsentArtefact,
    AbdmHiuConsentRequest,
    AbdmHiuRecord,
    HiuConsentStatus,
)
from care.abdm.tests.fixtures import ABHA_ADDRESS, HIP_ID
from care.abdm.tests.test_abha import make_response
from care.abdm.tests.test_m2 import ACCEPTED, M2TestBase

PUBLIC_BASE = "https://care.test"
HIU_PATHS = [
    "/api/hiecm/consent/v3/request/init",
    "/api/hiecm/consent/v3/request/status",
    "/api/hiecm/consent/v3/request/hiu/on-notify",
    "/api/hiecm/consent/v3/fetch",
    "/api/hiecm/data-flow/v3/health-information/request",
]
BUNDLE = {"resourceType": "Bundle", "type": "document", "entry": []}
ABDM_TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"


@override_settings(ABDM_CALLBACK_BASE_URL=PUBLIC_BASE)
class M3TestBase(M2TestBase):
    def setUp(self):
        super().setUp()
        self.fake.routes.update(dict.fromkeys(HIU_PATHS, ACCEPTED))
        self.admin = self.create_super_user()

    def raise_request(self, user=None, **overrides):
        self.client.force_authenticate(user=user or self.admin)
        now = timezone.now()
        body = {
            "patient": str(self.patient.external_id),
            "facility": str(self.encounter.facility.external_id),
            "purpose": "CAREMGT",
            "hi_types": ["Prescription", "OPConsultation"],
            "date_from": (now - timedelta(days=365)).isoformat(),
            "date_to": now.isoformat(),
            "data_erase_at": (now + timedelta(days=30)).isoformat(),
            **overrides,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse("abdm-consent-request-list"), body, format="json"
            )

    def calls(self, path):
        return [c for c in self.fake.calls if c["path"] == path]

    def artefact_body(self, consent_id, request_id, hip_id="IN9999", erase_in=30):
        return {
            "consent": {
                "status": "GRANTED",
                "consentDetail": {
                    "consentId": consent_id,
                    "hip": {"id": hip_id, "name": f"Clinic {hip_id}"},
                    "hiu": {"id": HIP_ID},
                    "patient": {"id": ABHA_ADDRESS},
                    "hiTypes": ["Prescription"],
                    "careContexts": [
                        {"patientReference": "p-1", "careContextReference": "cc-1"}
                    ],
                    "permission": {
                        "accessMode": "VIEW",
                        "dateRange": {
                            "from": "2020-01-01T00:00:00.000Z",
                            "to": "2030-01-01T00:00:00.000Z",
                        },
                        "dataEraseAt": (
                            timezone.now() + timedelta(days=erase_in)
                        ).isoformat(),
                    },
                },
                "signature": "sig",
            },
            "response": {"requestId": request_id},
        }

    def granted(self):
        """A request ABDM has accepted and the patient has granted, for two HIPs."""
        self.raise_request()
        init = self.sent("/api/hiecm/consent/v3/request/init")
        self.callback(
            "hiu/consent/request/on-init",
            {
                "consentRequest": {"id": "cr-1"},
                "response": {"requestId": init["headers"]["REQUEST-ID"]},
            },
        )
        self.callback(
            "hiu/consent/request/notify",
            {
                "notification": {
                    "consentRequestId": "cr-1",
                    "status": "GRANTED",
                    "consentArtefacts": [{"id": "artefact-1"}, {"id": "artefact-2"}],
                }
            },
        )

    def fetched(self, consent_id="artefact-1"):
        fetch = next(
            c
            for c in self.calls("/api/hiecm/consent/v3/fetch")
            if c["json"]["consentId"] == consent_id
        )
        self.callback(
            "hiu/consent/on-fetch",
            self.artefact_body(consent_id, fetch["headers"]["REQUEST-ID"]),
        )
        request = self.sent("/api/hiecm/data-flow/v3/health-information/request")
        self.callback(
            "hiu/health-information/on-request",
            {
                "hiRequest": {"transactionId": "txn-1", "sessionStatus": "REQUESTED"},
                "response": {"requestId": request["headers"]["REQUEST-ID"]},
            },
        )
        return request["json"]["hiRequest"]

    def push(
        self,
        hi_request,
        entries_for,
        transaction_id="txn-1",
        authorization="Bearer hip-gateway-token",
    ):
        """The HIP's side: encrypt to the key material we offered, and post it."""
        encryptor = Encryptor(hi_request["keyMaterial"])
        entries = [
            {
                "content": encryptor.encrypt(json.dumps(BUNDLE)),
                "media": "application/fhir+json",
                "checksum": "abc",
                "careContextReference": reference,
            }
            for reference in entries_for
        ]
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                hi_request["dataPushUrl"].removeprefix(PUBLIC_BASE),
                {
                    "pageNumber": 1,
                    "pageCount": 1,
                    "transactionId": transaction_id,
                    "entries": entries,
                    "keyMaterial": encryptor.key_material(),
                },
                format="json",
                **({"HTTP_AUTHORIZATION": authorization} if authorization else {}),
            )


class TestConsentRequest(M3TestBase):
    def test_init_carries_the_request(self):
        response = self.raise_request()
        self.assertEqual(response.status_code, 201)
        init = self.sent("/api/hiecm/consent/v3/request/init")
        consent = init["json"]["consent"]
        self.assertEqual(consent["patient"], {"id": ABHA_ADDRESS})
        self.assertEqual(consent["hiu"], {"id": HIP_ID})
        self.assertEqual(consent["purpose"]["text"], "Care Management")
        self.assertEqual(consent["hiTypes"], ["Prescription", "OPConsultation"])
        self.assertTrue(consent["permission"]["dataEraseAt"].endswith("Z"))
        self.assertEqual(init["headers"]["X-HIU-ID"], HIP_ID)

        self.callback(
            "hiu/consent/request/on-init",
            {
                "consentRequest": {"id": "cr-1"},
                "response": {"requestId": init["headers"]["REQUEST-ID"]},
            },
        )
        consent_request = AbdmHiuConsentRequest.objects.get()
        self.assertEqual(consent_request.status, HiuConsentStatus.requested)
        self.assertEqual(consent_request.consent_request_id, "cr-1")

    def test_refusal_carries_abdm_message(self):
        self.fake.routes["/api/hiecm/consent/v3/request/init"] = make_response(
            400, {"error": {"code": "ABDM-1009", "message": "Invalid patient"}}
        )
        self.raise_request()
        consent_request = AbdmHiuConsentRequest.objects.get()
        self.assertEqual(consent_request.status, HiuConsentStatus.failed)
        self.assertEqual(consent_request.error_code, "ABDM-1009")
        self.assertEqual(consent_request.error_message, "Invalid patient")

    def test_unanswered_request_stops_waiting(self):
        self.raise_request()
        AbdmHiuConsentRequest.objects.update(
            created_date=timezone.now() - timedelta(hours=1)
        )
        overview = self.client.get(
            reverse(
                "abdm-patient-detail", kwargs={"external_id": self.patient.external_id}
            )
        ).json()
        row = overview["consent_requests"][0]
        self.assertEqual(row["status"], HiuConsentStatus.failed)
        self.assertIn("bridge URL", row["error_message"])

    def test_requires_write_access(self):
        response = self.raise_request(user=self.create_user())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AbdmHiuConsentRequest.objects.exists())

    def test_range_ending_later_today_is_sent_as_now(self):
        self.raise_request(date_to=(timezone.now() + timedelta(hours=10)).isoformat())
        sent_to = self.sent("/api/hiecm/consent/v3/request/init")["json"]["consent"][
            "permission"
        ]["dateRange"]["to"]
        self.assertLessEqual(sent_to, hiu.abdm_time(timezone.now()))

    def test_list_shaped_refusal_carries_abdm_message(self):
        self.fake.routes["/api/hiecm/consent/v3/request/init"] = make_response(
            400,
            [
                {
                    "error": {
                        "code": "ABDM-9999: ",
                        "message": "Invalid from/to date",
                    }
                }
            ],
        )
        self.raise_request()
        consent_request = AbdmHiuConsentRequest.objects.get()
        self.assertEqual(consent_request.error_code, "ABDM-9999")
        self.assertEqual(consent_request.error_message, "Invalid from/to date")

    def test_rejects_unknown_record_type(self):
        response = self.raise_request(hi_types=["XRay"])
        self.assertEqual(response.status_code, 400)


class TestFetchAndReceive(M3TestBase):
    def test_grant_fetches_every_artefact(self):
        self.granted()
        ack = self.sent("/api/hiecm/consent/v3/request/hiu/on-notify")["json"]
        self.assertEqual(
            [a["consentId"] for a in ack["acknowledgement"]],
            ["artefact-1", "artefact-2"],
        )
        self.assertEqual(
            sorted(
                c["json"]["consentId"]
                for c in self.calls("/api/hiecm/consent/v3/fetch")
            ),
            ["artefact-1", "artefact-2"],
        )

    def test_records_arrive_decrypted_and_are_reported(self):
        self.granted()
        hi_request = self.fetched()
        self.assertTrue(hi_request["dataPushUrl"].startswith(f"{PUBLIC_BASE}/abdm/"))
        self.assertEqual(hi_request["consent"], {"id": "artefact-1"})
        # The sandbox refuses anything but UTC milliseconds with a trailing Z
        self.assertRegex(
            hi_request["keyMaterial"]["dhPublicKey"]["expiry"], ABDM_TIMESTAMP
        )
        self.assertTrue(
            hi_request["keyMaterial"]["dhPublicKey"]["keyValue"].startswith(
                "MIIBMTCB6gYHKoZIzj0CAT"
            )
        )

        response = self.push(hi_request, ["cc-1", "cc-not-consented"])
        self.assertEqual(response.status_code, 202)
        record = AbdmHiuRecord.objects.get()
        self.assertEqual(record.bundle, BUNDLE)
        self.assertEqual(record.care_context_reference, "cc-1")

        notify = self.sent("/api/hiecm/data-flow/v3/health-information/notify")
        status = notify["json"]["notification"]["statusNotification"]
        self.assertRegex(notify["json"]["notification"]["doneAt"], ABDM_TIMESTAMP)
        self.assertEqual(status["sessionStatus"], "RECEIVED")
        self.assertEqual(
            {
                s["careContextReference"]: s["hiStatus"]
                for s in status["statusResponses"]
            },
            {"cc-1": "OK", "cc-not-consented": "ERRORED"},
        )
        self.assertEqual(
            notify["json"]["notification"]["notifier"], {"type": "HIU", "id": HIP_ID}
        )

        artefact = AbdmHiuConsentArtefact.objects.get(consent_id="artefact-1")
        self.assertIsNone(artefact.key_secret)
        # The URL was single use
        self.assertEqual(self.push(hi_request, ["cc-1"]).status_code, 404)

        self.client.force_authenticate(user=self.admin)
        overview = self.client.get(
            reverse(
                "abdm-patient-detail", kwargs={"external_id": self.patient.external_id}
            )
        ).json()
        artefacts = overview["consent_requests"][0]["artefacts"]
        self.assertEqual(len(artefacts), 2)
        self.assertEqual(
            next(a for a in artefacts if a["consent_id"] == "artefact-1")[
                "record_count"
            ],
            1,
        )
        received = self.client.get(
            reverse(
                "abdm-patient-received",
                kwargs={
                    "external_id": self.patient.external_id,
                    "consent_id": "artefact-1",
                },
            )
        ).json()
        self.assertEqual(received["records"][0]["bundle"], BUNDLE)

    def test_revocation_erases_what_arrived(self):
        self.granted()
        self.push(self.fetched(), ["cc-1"])
        self.assertEqual(AbdmHiuRecord.objects.count(), 1)
        self.callback(
            "hiu/consent/request/notify",
            {
                "notification": {
                    "consentRequestId": "cr-1",
                    "status": "REVOKED",
                    "consentArtefacts": [{"id": "artefact-1"}],
                }
            },
        )
        self.assertFalse(AbdmHiuRecord.objects.exists())
        self.assertEqual(
            AbdmHiuConsentArtefact.objects.get(consent_id="artefact-1").status,
            HiuConsentStatus.revoked,
        )

    def test_records_are_erased_when_the_consent_ends(self):
        self.granted()
        self.push(self.fetched(), ["cc-1"])
        AbdmHiuConsentArtefact.objects.filter(consent_id="artefact-1").update(
            data_erase_at=timezone.now() - timedelta(minutes=1)
        )
        hiu.erase_expired()
        self.assertFalse(AbdmHiuRecord.objects.exists())

    def test_push_after_expiry_is_refused(self):
        self.granted()
        hi_request = self.fetched()
        AbdmHiuConsentArtefact.objects.filter(consent_id="artefact-1").update(
            data_erase_at=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(self.push(hi_request, ["cc-1"]).status_code, 403)
        self.assertFalse(AbdmHiuRecord.objects.exists())

    def test_push_without_bearer_is_refused(self):
        self.granted()
        hi_request = self.fetched()
        self.assertEqual(
            self.push(hi_request, ["cc-1"], authorization=None).status_code, 401
        )
        self.assertFalse(AbdmHiuRecord.objects.exists())
        # The transfer is still open for the real push
        self.assertEqual(self.push(hi_request, ["cc-1"]).status_code, 202)

    def test_push_for_another_transaction_is_refused(self):
        self.granted()
        hi_request = self.fetched()
        response = self.push(hi_request, ["cc-1"], transaction_id="someone-else")
        self.assertEqual(response.status_code, 400)

    def test_artefact_for_another_patient_is_not_used(self):
        self.granted()
        fetch = self.calls("/api/hiecm/consent/v3/fetch")[0]
        body = self.artefact_body(
            fetch["json"]["consentId"], fetch["headers"]["REQUEST-ID"]
        )
        body["consent"]["consentDetail"]["patient"]["id"] = "someone@sbx"
        self.callback("hiu/consent/on-fetch", body)
        self.assertFalse(
            self.fake.called("/api/hiecm/data-flow/v3/health-information/request")
        )

    def test_synchronous_fetch_answer_is_used(self):
        self.fake.routes["/api/hiecm/consent/v3/fetch"] = [
            make_response(200, self.artefact_body("artefact-1", "x")),
            ACCEPTED,
        ]
        self.granted()
        request = self.sent("/api/hiecm/data-flow/v3/health-information/request")
        self.assertEqual(request["json"]["hiRequest"]["consent"], {"id": "artefact-1"})

    def test_no_public_url_fails_the_transfer_visibly(self):
        with override_settings(ABDM_CALLBACK_BASE_URL=""):
            self.granted()
            fetch = self.calls("/api/hiecm/consent/v3/fetch")[0]
            self.callback(
                "hiu/consent/on-fetch",
                self.artefact_body(
                    fetch["json"]["consentId"], fetch["headers"]["REQUEST-ID"]
                ),
            )
        artefact = AbdmHiuConsentArtefact.objects.get(
            consent_id=fetch["json"]["consentId"]
        )
        self.assertEqual(artefact.session_status, "FAILED")
        self.assertIn("ABDM_CALLBACK_BASE_URL", artefact.error_message)
