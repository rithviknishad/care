import base64
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from care.abdm import registry
from care.abdm.client import _find_error
from care.abdm.fhir import DocumentBuilder
from care.abdm.hiu import _requester
from care.abdm.models import AbdmFacility, AbdmHfrApplication, AbdmProfessional
from care.abdm.tests.test_abha import (
    ABDM_SETTINGS,
    PRIVATE_KEY,
    FakeAbdm,
    clear_abdm_cache,
    make_response,
)
from care.utils.tests.base import CareAPITestBase

HFR_ID = "IN3210000778"
HPR_NUMBER = "71-1234-5678-9012"
HPR_ADDRESS = "asha.doctor@hpr.abdm"
PEM = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)

HFR_FACILITY = {
    "facilityId": HFR_ID,
    "facilityName": "OHC Hospital",
    "facilityStatus": "Submitted",
    "ownership": "GOVERNMENT",
    "ownershipCode": "G",
    "facilityType": "Hospital",
    "systemOfMedicine": "Modern Medicine(Allopathy)",
    "stateName": "Kerala",
    "districtName": "Ernakulam",
    "subDistrictName": "Kochi",
    "address": "Some street",
    "pincode": "682030",
}
SEARCH_PATH = "/FacilityManagement/v1.5/facility/search"


def found(*facilities):
    return make_response(
        200,
        {
            "facilities": list(facilities),
            "totalFacilities": len(facilities),
            "numberOfPages": 1,
        },
    )


def hpr_refusal(code, message):
    return make_response(
        422,
        {
            "code": "HIS-422",
            "message": "Unable to process the current request",
            "details": [{"message": message, "code": code, "attribute": None}],
        },
    )


@override_settings(**ABDM_SETTINGS, ABDM_REGISTRY_URL="https://registry.test")
class M4TestBase(CareAPITestBase):
    def setUp(self):
        super().setUp()
        clear_abdm_cache()
        cache.delete_many(
            [
                registry.HPR_CERTIFICATE_CACHE_KEY,
                "abdm:hfr:states",
                "abdm:hpr:categories",
            ]
        )
        self.abdm = FakeAbdm({SEARCH_PATH: found(HFR_FACILITY)})
        patcher = patch("care.abdm.client.requests.request", self.abdm)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.admin = self.create_super_user()
        self.facility = self.create_facility(user=self.admin)
        self.doctor = self.create_user(first_name="Asha", last_name="Doctor")
        organization = self.create_facility_organization(facility=self.facility)
        self.attach_role_facility_organization_user(
            organization, self.doctor, self.create_role_with_permissions([])
        )
        self.client.force_authenticate(user=self.admin)

    def url(self, name, facility=None):
        return reverse(
            f"abdm-registry-{name.replace('_', '-')}",
            kwargs={"external_id": str((facility or self.facility).external_id)},
        )

    def post(self, name, body=None):
        return self.client.post(self.url(name), body or {}, format="json")


class TestRegistryErrors(CareAPITestBase):
    def test_detail_code_is_the_cause(self):
        body = {
            "code": "HIS-422",
            "message": "Unable to process",
            "details": [{"message": "Invalid HPID.", "code": "HIS-3008"}],
        }
        self.assertEqual(_find_error(body), ("HIS-3008", "Invalid HPID."))

    def test_placeholders_are_dropped(self):
        self.assertEqual(
            _find_error({"code": "HIS-500", "message": "Try again {0} {1}."}),
            ("HIS-500", "Try again."),
        )


class TestHfr(M4TestBase):
    def test_search_by_id(self):
        response = self.post("search", {"facility_id": HFR_ID.lower()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["facility_id"], HFR_ID)
        self.assertEqual(response.data["results"][0]["name"], "OHC Hospital")
        sent = self.abdm.call(SEARCH_PATH)["json"]
        self.assertEqual(sent["facilityId"], HFR_ID)
        self.assertGreaterEqual(sent["resultsPerPage"], 10)

    def test_name_search_needs_state_and_ownership(self):
        response = self.post("search", {"name": "OHC"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.abdm.called(SEARCH_PATH))

        self.post("search", {"name": "OHC", "state_code": "32", "ownership_code": "G"})
        sent = self.abdm.call(SEARCH_PATH)["json"]
        self.assertEqual(
            (sent["facilityName"], sent["stateLGDCode"], sent["ownershipCode"]),
            ("OHC", "32", "G"),
        )

    def test_masters_trim_padded_codes(self):
        self.abdm.routes["/v1.5/facility/get-master-data"] = make_response(
            200, {"type": "OWNER", "data": [{"code": "G   ", "value": "Government  "}]}
        )
        response = self.client.get(
            self.url("masters"), {"kind": "master", "type": "OWNER"}
        )
        self.assertEqual(
            response.data["results"], [{"code": "G", "name": "Government"}]
        )
        response = self.client.get(self.url("masters"), {"kind": "secrets"})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(
            self.url("masters"), {"kind": "master", "type": "SALUTATION"}
        )
        self.assertEqual(response.status_code, 400)

    def test_register_services_as_hip_and_hiu(self):
        AbdmFacility.objects.create(facility=self.facility, hip_id=HFR_ID)
        path = "/v1/bridges/MutipleHRPAddUpdateServices"
        self.abdm.routes[path] = make_response(200, {"message": "done"})
        response = self.post("register_services")
        self.assertEqual(response.status_code, 200)
        sent = self.abdm.call(path)["json"]
        self.assertEqual(sent["facilityId"], HFR_ID)
        self.assertEqual(
            sorted((s["type"], s["bridgeId"], s["hipName"]) for s in sent["HRP"]),
            [("HIP", "client", "OHC Hospital"), ("HIU", "client", "OHC Hospital")],
        )

    def test_staff_without_facility_rights_are_refused(self):
        self.client.force_authenticate(user=self.doctor)
        self.assertEqual(self.post("search", {"facility_id": HFR_ID}).status_code, 403)
        self.assertEqual(self.client.get(self.url("professionals")).status_code, 403)


class TestOnboarding(M4TestBase):
    BODY = {
        "name": "New Clinic",
        "state_code": "32",
        "district_code": "555",
        "sub_district_code": "5660",
        "region": "U",
        "address_line1": "Street 1",
        "pincode": "682030",
        "latitude": "10.0",
        "longitude": "76.3",
        "email": "clinic@example.com",
        "phone": "+91 98765 43210",
        "ownership_code": "P",
        "ownership_sub_type_code": "P",
        "system_of_medicine_codes": ["M", "D"],
        "type_of_service_codes": ["OPD"],
        "facility_type_code": "5",
        "facility_sub_type_code": "47",
        "speciality_type_code": "SINGLE",
        "operational_status": "F",
        "timings": [{"working_days": "MON", "opening_hours": "9:00 AM - 6:00 PM"}],
    }

    def test_needs_the_submitters_hpr_login(self):
        response = self.post("onboard", self.BODY)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.abdm.called("/v1.5/facility/basic-information"))

    def test_basic_information_then_submit(self):
        registry.remember_hpr_token(self.admin.id, "hpr-token", 600)
        self.abdm.routes["/v1.5/facility/basic-information"] = make_response(
            200, {"trackingId": "80266", "status": "SUCCESS", "errorStatus": []}
        )
        self.abdm.routes["/v1.5/facility/submit-facility"] = make_response(
            200, {"facilityId": "IN3210009999", "status": "SUCCESS"}
        )
        response = self.post("onboard", self.BODY)
        self.assertEqual(response.data["hfr_id"], "IN3210009999")

        basic = self.abdm.call("/v1.5/facility/basic-information")
        self.assertEqual(basic["headers"]["x-hprid-auth"], "hpr-token")
        information = basic["json"]["facilityInformation"]
        self.assertEqual(information["systemOfMedicineCode"], "M,D")
        self.assertEqual(
            information["facilityContactInformation"]["facilityContactNumber"],
            "9876543210",
        )
        self.assertEqual(
            information["facilityAddressDetails"]["subDistrictLGDCode"], "5660"
        )
        submit = self.abdm.call("/v1.5/facility/submit-facility")
        self.assertEqual(submit["json"], {"trackingId": "80266"})
        self.assertEqual(
            AbdmFacility.objects.get(facility=self.facility).hip_id, "IN3210009999"
        )

    def test_refusal_keeps_the_tracking_id(self):
        registry.remember_hpr_token(self.admin.id, "hpr-token", 600)
        self.abdm.routes["/v1.5/facility/basic-information"] = make_response(
            200, {"trackingId": "80266"}
        )
        self.abdm.routes["/v1.5/facility/submit-facility"] = make_response(
            422, {"code": "HIS-422", "message": "Facility name already exists"}
        )
        response = self.post("onboard", self.BODY)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["error_code"], "HIS-422")
        application = AbdmHfrApplication.objects.get(facility=self.facility)
        self.assertEqual(application.tracking_id, "80266")
        self.assertEqual(application.information["name"], "New Clinic")
        self.assertFalse(AbdmFacility.objects.filter(facility=self.facility).exists())

        # The retry updates the same application rather than starting another
        self.abdm.routes["/v1.5/facility/submit-facility"] = make_response(
            200, {"facilityId": "IN3210009999"}
        )
        self.post("onboard", self.BODY)
        self.assertEqual(
            self.abdm.call("/v1.5/facility/basic-information")["json"]["trackingId"],
            "80266",
        )


class TestHprLogin(M4TestBase):
    def setUp(self):
        super().setUp()
        self.abdm.routes.update(
            {
                f"/v1/search/searchByHprId/{HPR_ADDRESS}": make_response(
                    200,
                    {
                        "hprId": HPR_ADDRESS,
                        "hprIdNumber": HPR_NUMBER,
                        "name": "Asha Doctor",
                        "authMethods": ["AADHAAR_OTP"],
                    },
                ),
                "/api/v1/auth/init": make_response(
                    200, {"transactionId": "txn-1", "mobileNumber": "******3210"}
                ),
                "/api/v1/auth/confirmWithAadhaarOtp": make_response(
                    200, {"token": "hpr-token", "expiresIn": 600}
                ),
            }
        )

    def login(self, username):
        response = self.post("login", {"username": username, "hpr_id": "asha.doctor"})
        self.assertEqual(response.status_code, 200, response.data)
        return self.post(
            "confirm_login",
            {"journey_id": response.data["journey_id"], "otp": "123456"},
        )

    def test_links_a_member_after_their_otp(self):
        response = self.login(self.doctor.username)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["hpr_id_number"], HPR_NUMBER)
        sent = self.abdm.call("/api/v1/auth/init")["json"]
        self.assertEqual(
            (sent["hprId"], sent["authMethod"]), (HPR_ADDRESS, "AADHAAR_OTP")
        )
        professional = AbdmProfessional.objects.get(user=self.doctor)
        self.assertEqual(professional.linked_by, self.admin)
        # The doctor's HPR token never signs the admin's submissions
        self.assertIsNone(registry.recall_hpr_token(self.doctor.id))
        self.assertIsNone(registry.recall_hpr_token(self.admin.id))

        listed = {
            row["username"]: row["professional"]
            for row in self.client.get(self.url("professionals")).data["results"]
        }
        self.assertEqual(listed[self.doctor.username]["hpr_id"], HPR_ADDRESS)

    def test_own_login_keeps_the_token(self):
        self.login(self.admin.username)
        self.assertEqual(registry.recall_hpr_token(self.admin.id), "hpr-token")
        me = self.client.get(self.url("detail")).data["me"]
        self.assertTrue(me["hpr_signed_in"])

    def test_one_hpr_id_per_user(self):
        self.login(self.doctor.username)
        response = self.login(self.admin.username)
        self.assertEqual(response.status_code, 403)

    def test_only_facility_members(self):
        stranger = self.create_user()
        response = self.post("login", {"username": stranger.username, "hpr_id": "x.y"})
        self.assertEqual(response.status_code, 404)

    def test_unknown_hpr_id_reports_hpr_cause(self):
        self.abdm.routes[f"/v1/search/searchByHprId/{HPR_ADDRESS}"] = hpr_refusal(
            "HIS-3008", "Invalid HPID."
        )
        response = self.post(
            "login", {"username": self.doctor.username, "hpr_id": "asha.doctor"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["code"], "HIS-3008")


class TestHprIdCreation(M4TestBase):
    ACCOUNT = {
        "hprIdNumber": "",
        "new": True,
        "firstName": "Asha",
        "lastName": "Doctor",
        "stateCode": "32",
        "districtCode": "555",
    }

    def setUp(self):
        super().setUp()
        self.abdm.routes.update(
            {
                "/aadhaar/generateLink": make_response(
                    200, {"txnId": "txn-9", "url": "https://abdm.example/auth"}
                ),
                "/aadhaar/isAuthenticated": [
                    make_response(200, body=False),
                    make_response(200, body=True),
                ],
                "/v2/registration/aadhaar/verifyOTP": make_response(
                    200, {"txnId": "txn-9", "name": "Asha Doctor"}
                ),
                "/v1/registration/aadhaar/checkHpIdAccountExist": make_response(
                    200, self.ACCOUNT
                ),
                "/v1/registration/aadhaar/hpid/suggestion": make_response(
                    200, ["asha.doctor"]
                ),
                "/v2/registration/aadhaar/demographicAuthViaMobile": make_response(
                    200, {"verified": False}
                ),
                "/v1/registration/aadhaar/generateMobileOTP": make_response(
                    200, {"txnId": "txn-9"}
                ),
                "/v1/registration/aadhaar/verifyMobileOTP": make_response(
                    200, {"txnId": "txn-9"}
                ),
                "/api/v1/auth/cert": make_response(200, PEM, content_type="text/plain"),
                "/v2/registration/aadhaar/createHprIdWithPreVerified": make_response(
                    200,
                    {
                        "hprId": HPR_ADDRESS,
                        "hprIdNumber": HPR_NUMBER,
                        "name": "Asha Doctor",
                        "token": "hpr-token",
                    },
                ),
            }
        )

    def start(self):
        response = self.post("create_start", {"username": self.doctor.username})
        self.assertEqual(response.data["url"], "https://abdm.example/auth")
        return response.data["journey_id"]

    def test_create_after_aadhaar_and_mobile(self):
        journey_id = self.start()
        self.assertFalse(
            self.post("create_status", {"journey_id": journey_id}).data["authenticated"]
        )
        status = self.post("create_status", {"journey_id": journey_id}).data
        self.assertEqual(status["suggestions"], ["asha.doctor"])
        self.assertEqual(status["prefill"]["district_code"], "555")

        details = {
            "journey_id": journey_id,
            "hpr_id": "asha.doctor@hpr.abdm",
            "email": "asha@example.com",
            "password": "Secret@1234",
            "category": "1",
            "sub_category": "1",
            "state_code": "32",
            "district_code": "555",
        }
        self.assertEqual(self.post("create_hpr_id", details).status_code, 400)

        sent = self.post(
            "create_mobile", {"journey_id": journey_id, "mobile": "9876543210"}
        )
        self.assertTrue(sent.data["otp_sent"])
        self.post("create_mobile_otp", {"journey_id": journey_id, "otp": "654321"})
        encrypted = self.abdm.call("/v1/registration/aadhaar/verifyMobileOTP")["json"]
        self.assertEqual(
            PRIVATE_KEY.decrypt(
                base64.b64decode(encrypted["otp"]), padding.PKCS1v15()
            ).decode(),
            "654321",
        )

        response = self.post("create_hpr_id", details)
        self.assertEqual(response.status_code, 200)
        created = self.abdm.call("/v2/registration/aadhaar/createHprIdWithPreVerified")
        self.assertEqual(created["json"]["hprId"], "asha.doctor")
        self.assertEqual(created["json"]["hpCategoryCode"], 1)
        self.assertEqual(
            AbdmProfessional.objects.get(user=self.doctor).hpr_id_number, HPR_NUMBER
        )

    def test_existing_hpr_id_is_linked(self):
        self.abdm.routes["/aadhaar/isAuthenticated"] = make_response(200, body=True)
        self.abdm.routes["/v1/registration/aadhaar/checkHpIdAccountExist"] = (
            make_response(
                200,
                {"hprId": HPR_ADDRESS, "hprIdNumber": HPR_NUMBER, "new": False},
            )
        )
        status = self.post("create_status", {"journey_id": self.start()}).data
        self.assertEqual(status["linked"]["hpr_id_number"], HPR_NUMBER)
        self.assertFalse(self.abdm.called("/v1/registration/aadhaar/hpid/suggestion"))


class TestHprInRecords(CareAPITestBase):
    @override_settings(ABDM_HPR_IDENTIFIER_SYSTEM="https://hpr.test")
    def test_verified_hpr_id_names_the_practitioner(self):
        doctor = self.create_user(doctor_medical_council_registration="KMC-1")
        self.assertEqual(_requester(doctor, "IN1")["identifier"]["value"], "KMC-1")
        AbdmProfessional.objects.create(
            user=doctor,
            hpr_id=HPR_ADDRESS,
            hpr_id_number=HPR_NUMBER,
            verified_at=timezone.now(),
        )
        doctor.refresh_from_db()
        self.assertEqual(
            _requester(doctor, "IN1")["identifier"],
            {"value": HPR_NUMBER, "type": "REGNO", "system": "https://hpr.test"},
        )
        builder = DocumentBuilder.__new__(DocumentBuilder)
        builder.entries, builder._references = [], {}  # noqa: SLF001
        builder.practitioner_reference(doctor)
        identifier = builder.entries[0]["resource"]["identifier"][0]
        self.assertEqual(
            (identifier["system"], identifier["value"]),
            ("https://hpr.test", HPR_NUMBER),
        )
