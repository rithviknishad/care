import re

from django.conf import settings
from django.utils import timezone
from pydantic import UUID4, BaseModel, Field, field_validator, model_validator
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from care.abdm import registry
from care.abdm.api.viewsets.abha import abdm_exception_handler
from care.abdm.api.viewsets.hip import _require_enabled
from care.abdm.client import AbdmError
from care.abdm.journey import Journey
from care.abdm.models import AbdmFacility, AbdmHfrApplication, AbdmProfessional
from care.emr.api.viewsets.base import EMRBaseViewSet
from care.facility.models.facility import Facility
from care.security.authorization import AuthorizationController
from care.users.models import User
from care.utils.shortcuts import get_object_or_404

HFR_ID_PATTERN = re.compile(r"^IN\w{10}$")
MOBILE_PATTERN = re.compile(r"^\d{10}$")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


class FacilitySearchSpec(BaseModel):
    facility_id: str | None = None
    name: str | None = None
    state_code: str | None = None
    district_code: str | None = None
    ownership_code: str | None = None
    page: int = Field(default=1, ge=1)

    @field_validator("facility_id")
    @classmethod
    def validate_facility_id(cls, value):
        value = (value or "").strip().upper()
        if value and not HFR_ID_PATTERN.match(value):
            msg = "An HFR ID is IN followed by 10 characters"
            raise ValueError(msg)
        return value or None

    @model_validator(mode="after")
    def validate_criteria(self):
        # HFR needs state and ownership whenever the ID is not given
        if not self.facility_id and not (self.state_code and self.ownership_code):
            msg = "Search by HFR ID, or by state and ownership"
            raise ValueError(msg)
        return self


class MemberSpec(BaseModel):
    username: str


class JourneySpec(BaseModel):
    journey_id: UUID4


class LoginSpec(MemberSpec):
    hpr_id: str = Field(min_length=3, max_length=128)


class OtpSpec(JourneySpec):
    otp: str

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value):
        if not value.isdigit():
            msg = "OTP must be numeric"
            raise ValueError(msg)
        return value


class MobileSpec(JourneySpec):
    mobile: str

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value):
        value = _digits(value)[-10:]
        if not MOBILE_PATTERN.match(value):
            msg = "Enter a 10 digit mobile number"
            raise ValueError(msg)
        return value


class CreateHprIdSpec(JourneySpec):
    hpr_id: str = Field(min_length=4, max_length=64)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=64)
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    category: str
    sub_category: str
    state_code: str
    district_code: str

    @field_validator("hpr_id")
    @classmethod
    def validate_hpr_id(cls, value):
        return value.strip().lower().removesuffix(registry.HPR_DOMAIN)


class TimingSpec(BaseModel):
    working_days: str
    opening_hours: str


class OnboardSpec(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    state_code: str
    district_code: str
    sub_district_code: str
    region: str
    address_line1: str = Field(min_length=1)
    address_line2: str = ""
    pincode: str
    latitude: str
    longitude: str
    email: str
    phone: str
    website: str = ""
    ownership_code: str
    ownership_sub_type_code: str
    ownership_sub_type_code2: str = ""
    system_of_medicine_codes: list[str] = Field(min_length=1)
    type_of_service_codes: list[str] = []
    facility_type_code: str
    facility_sub_type_code: str = ""
    speciality_type_code: str
    operational_status: str
    timings: list[TimingSpec] = []

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value):
        if not re.fullmatch(r"\d{6}", value.strip()):
            msg = "Enter a 6 digit pincode"
            raise ValueError(msg)
        return value.strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        value = _digits(value)[-10:]
        if not MOBILE_PATTERN.match(value):
            msg = "Enter a 10 digit contact number"
            raise ValueError(msg)
        return value

    def facility_information(self) -> dict:
        """The basic-information body, in the shape HFR publishes."""
        return {
            "facilityName": self.name,
            "facilityAddressDetails": {
                "country": "India",
                "stateLGDCode": self.state_code,
                "districtLGDCode": self.district_code,
                "subDistrictLGDCode": self.sub_district_code,
                "facilityRegion": self.region,
                "villageCityTownLGDCode": "",
                "addressLine1": self.address_line1,
                "addressLine2": self.address_line2,
                "pincode": self.pincode,
                "latitude": self.latitude,
                "longitude": self.longitude,
            },
            "facilityContactInformation": {
                "facilityEmailId": self.email,
                "facilityContactNumber": self.phone,
                "websiteLink": self.website,
                "facilityLandlineNumber": "",
                "facilityStdCode": "",
            },
            "ownershipCode": self.ownership_code,
            "ownershipSubTypeCode": self.ownership_sub_type_code,
            "ownershipSubTypeCode2": self.ownership_sub_type_code2,
            "systemOfMedicineCode": ",".join(self.system_of_medicine_codes),
            "typeOfServiceCode": ",".join(self.type_of_service_codes),
            "facilityTypeCode": self.facility_type_code,
            "specialityTypeCode": self.speciality_type_code,
            "facilityUploads": {
                "facilityBoardPhoto": {"name": "", "value": ""},
                "facilityBuildingPhoto": {"name": "", "value": ""},
            },
            "facilitySubType": self.facility_sub_type_code,
            "facilityOperationalStatus": self.operational_status,
            "timingsOfFacility": [
                {"workingDays": t.working_days, "openingHours": t.opening_hours}
                for t in self.timings
            ],
            "abdmCompliantSoftware": [],
        }


def professional_row(professional: AbdmProfessional | None) -> dict | None:
    if not professional:
        return None
    return {
        "hpr_id": professional.hpr_id,
        "hpr_id_number": professional.hpr_id_number,
        "name": professional.name,
        "verified_at": professional.verified_at,
    }


def application_row(application: AbdmHfrApplication | None) -> dict | None:
    if not application:
        return None
    return {
        "tracking_id": application.tracking_id,
        "hfr_id": application.hfr_id,
        "submitted_at": application.submitted_at,
        "information": application.information,
        "error_code": application.error_code,
        "error_message": application.error_message,
        "modified_date": application.modified_date,
    }


def _refusals(body: dict) -> str:
    """HFR answers some refusals with a 200 that lists them under errorStatus."""
    return "; ".join(
        str(item.get("message") or item.get("errorMessage") or item)
        for item in body.get("errorStatus") or []
        if item
    )


def _link(user, professional: dict, linked_by, token=None, expires_in=None):
    if not professional.get("hpr_id_number"):
        raise ValidationError("HPR did not return an HPR ID number")
    taken = (
        AbdmProfessional.objects.filter(hpr_id_number=professional["hpr_id_number"])
        .exclude(user=user)
        .exists()
    )
    if taken:
        raise PermissionDenied("This HPR ID is linked to another CARE user")
    link, _ = AbdmProfessional.objects.update_or_create(
        user=user,
        defaults={
            "hpr_id": professional.get("hpr_id") or professional["hpr_id_number"],
            "hpr_id_number": professional["hpr_id_number"],
            "name": professional.get("name") or "",
            "verified_at": timezone.now(),
            "linked_by": linked_by,
        },
    )
    if token:
        # Only kept for the professional themself; it signs their HFR submissions
        registry.remember_hpr_token(
            user.id, token, expires_in or settings.ABDM_JOURNEY_TTL_SECONDS
        )
    return link


class AbdmRegistryViewSet(EMRBaseViewSet):
    """
    M4 for one facility: find or onboard it in HFR, serve it from this bridge,
    and link its staff to their HPR IDs. Facility admins only.
    """

    def get_exception_handler(self):
        return abdm_exception_handler

    def _facility(self) -> Facility:
        _require_enabled()
        facility = get_object_or_404(Facility, external_id=self.kwargs["external_id"])
        if not AuthorizationController.call(
            "can_update_facility_obj", self.request.user, facility
        ):
            raise PermissionDenied("Cannot manage this facility's ABDM registration")
        return facility

    def _member(self, facility: Facility, username: str) -> User:
        user = User.objects.filter(username=username, is_active=True).first()
        is_member = (
            user
            and User.objects.filter(
                id=user.id,
                facilityorganizationuser__organization__facility=facility,
            ).exists()
        )
        if user and (user == self.request.user or is_member):
            return user
        raise NotFound("No such user in this facility")

    def _hip_id(self, facility):
        return (
            AbdmFacility.objects.filter(facility=facility)
            .values_list("hip_id", flat=True)
            .first()
        )

    def retrieve(self, request, *args, **kwargs):
        facility = self._facility()
        hip_id = self._hip_id(facility)
        hfr, hfr_error = None, None
        if hip_id:
            try:
                hfr = registry.get_facility(hip_id)
            except AbdmError as e:
                hfr_error = f"{e.code or e.status}: {e.message}"
        return Response(
            {
                "hip_id": hip_id,
                "hfr": hfr,
                "hfr_error": hfr_error,
                "application": application_row(
                    AbdmHfrApplication.objects.filter(facility=facility).first()
                ),
                "me": {
                    "username": request.user.username,
                    "professional": professional_row(
                        AbdmProfessional.objects.filter(user=request.user).first()
                    ),
                    "hpr_signed_in": bool(registry.recall_hpr_token(request.user.id)),
                },
            }
        )

    # HFR ----------------------------------------------------------------------

    @action(detail=True, methods=["POST"])
    def search(self, request, *args, **kwargs):
        self._facility()
        data = FacilitySearchSpec(**request.data)
        return Response(
            registry.search_facilities(
                facility_id=data.facility_id,
                name=data.name,
                state_code=data.state_code,
                district_code=data.district_code,
                ownership_code=data.ownership_code,
                page=data.page,
            )
        )

    @action(detail=True, methods=["GET"])
    def masters(self, request, *args, **kwargs):
        self._facility()
        params = request.query_params
        kind = params.get("kind")
        loaders = {
            "states": registry.states,
            "sub_districts": lambda: registry.sub_districts(params["district"]),
            "master": lambda: registry.master_data(params["type"]),
            "facility_types": lambda: registry.facility_types(
                params["ownership"], params["medicine"]
            ),
            "facility_sub_types": lambda: registry.facility_sub_types(params["type"]),
            "ownership_sub_types": lambda: registry.ownership_sub_types(
                params["ownership"]
            ),
            "owner_sub_types": lambda: registry.owner_sub_types(
                params["ownership"], params["sub_type"]
            ),
            "hpr_categories": registry.categories,
        }
        if kind not in loaders:
            msg = f"kind must be one of {', '.join(loaders)}"
            raise ValidationError(msg)
        try:
            return Response({"results": loaders[kind]()})
        except (KeyError, ValueError) as e:
            msg = f"Missing or unknown parameter: {e}"
            raise ValidationError(msg) from e

    @action(detail=True, methods=["POST"])
    def register_services(self, request, *args, **kwargs):
        """Serve this facility's HFR ID from this bridge, as HIP and HIU."""
        facility = self._facility()
        hip_id = self._hip_id(facility)
        if not hip_id:
            raise ValidationError("Set this facility's HFR ID first")
        hfr = registry.get_facility(hip_id)
        if not hfr:
            msg = f"HFR has no facility {hip_id}"
            raise ValidationError(msg)
        result = registry.register_services(hip_id, hfr["name"] or facility.name)
        return Response({"hip_id": hip_id, "message": result.get("message") or ""})

    @action(detail=True, methods=["POST"])
    def onboard(self, request, *args, **kwargs):
        """Create this facility in HFR, signed by the requesting user's HPR login."""
        facility = self._facility()
        data = OnboardSpec(**request.data)
        token = registry.recall_hpr_token(request.user.id)
        if not token:
            raise ValidationError(
                "Sign in to HPR as yourself first; HFR records who submitted the facility"
            )
        application, _ = AbdmHfrApplication.objects.get_or_create(facility=facility)
        if application.hfr_id:
            msg = f"This facility was already submitted as {application.hfr_id}"
            raise ValidationError(msg)
        application.information = data.model_dump()
        application.error_code, application.error_message = "", ""
        try:
            saved = registry.save_basic_information(
                data.facility_information(), application.tracking_id, token
            )
            application.tracking_id = str(
                saved.get("trackingId") or application.tracking_id
            )
            refused = _refusals(saved)
            if refused or not application.tracking_id:
                application.error_message = refused or "HFR issued no tracking ID"
            else:
                submitted = registry.submit_facility(application.tracking_id, token)
                application.error_message = _refusals(submitted)
                if submitted.get("facilityId"):
                    application.hfr_id = submitted["facilityId"]
                    application.submitted_at = timezone.now()
                    application.submitted_by = request.user
                elif not application.error_message:
                    application.error_message = (
                        submitted.get("message") or "HFR returned no facility ID"
                    )
        except AbdmError as e:
            # Kept, not raised: a raised error would roll the tracking ID back
            application.error_code = e.code or str(e.status)
            application.error_message = e.message or "HFR refused the request"
        application.save()
        if (
            application.hfr_id
            and not AbdmFacility.objects.filter(hip_id=application.hfr_id)
            .exclude(facility=facility)
            .exists()
        ):
            AbdmFacility.objects.update_or_create(
                facility=facility, defaults={"hip_id": application.hfr_id}
            )
        return Response(application_row(application))

    # HPR ----------------------------------------------------------------------

    @action(detail=True, methods=["GET"])
    def professionals(self, request, *args, **kwargs):
        facility = self._facility()
        users = (
            User.objects.filter(
                facilityorganizationuser__organization__facility=facility,
                is_active=True,
            )
            .select_related("abdm_professional")
            .distinct()
            .order_by("first_name", "last_name", "username")
        )
        return Response(
            {
                "results": [
                    {
                        "username": user.username,
                        "name": user.get_full_name() or user.username,
                        "professional": professional_row(
                            getattr(user, "abdm_professional", None)
                        ),
                    }
                    for user in users
                ]
            }
        )

    @action(detail=True, methods=["POST"])
    def login(self, request, *args, **kwargs):
        """Send an Aadhaar OTP to the professional behind an HPR ID."""
        facility = self._facility()
        data = LoginSpec(**request.data)
        user = self._member(facility, data.username)
        hpr_id = registry.hpr_address(data.hpr_id)
        professional = registry.find_professional(hpr_id)
        started = registry.start_login(professional["hpr_id"] or hpr_id)
        journey = Journey.start(request.user)
        journey["kind"] = "hpr_login"
        journey["username"] = user.username
        journey["txn_id"] = started["txn_id"]
        journey["professional"] = professional
        journey.save()
        return Response(
            {
                "journey_id": journey.id,
                "mobile": started["mobile"],
                "name": professional["name"],
            }
        )

    @action(detail=True, methods=["POST"])
    def confirm_login(self, request, *args, **kwargs):
        facility = self._facility()
        data = OtpSpec(**request.data)
        journey = Journey.load(data.journey_id, request.user)
        if journey["kind"] != "hpr_login":
            raise NotFound("HPR session expired. Start again.")
        user = self._member(facility, journey["username"])
        confirmed = registry.confirm_login(journey["txn_id"], data.otp)
        link = _link(
            user,
            journey["professional"],
            request.user,
            confirmed["token"] if user == request.user else None,
            confirmed["expires_in"],
        )
        return Response(professional_row(link))

    @action(detail=True, methods=["POST"])
    def unlink(self, request, *args, **kwargs):
        facility = self._facility()
        user = self._member(facility, MemberSpec(**request.data).username)
        AbdmProfessional.objects.filter(user=user).delete()
        return Response({"username": user.username, "professional": None})

    # HPR ID creation, Aadhaar-verified on ABDM's own page

    @action(detail=True, methods=["POST"])
    def create_start(self, request, *args, **kwargs):
        facility = self._facility()
        user = self._member(facility, MemberSpec(**request.data).username)
        started = registry.start_aadhaar_link()
        journey = Journey.start(request.user)
        journey["kind"] = "hpr_create"
        journey["username"] = user.username
        journey["txn_id"] = started["txn_id"]
        journey.save()
        return Response({"journey_id": journey.id, "url": started["url"]})

    def _creation(self, journey_id) -> tuple[Journey, User]:
        facility = self._facility()
        journey = Journey.load(journey_id, self.request.user)
        if journey["kind"] != "hpr_create":
            raise NotFound("HPR session expired. Start again.")
        return journey, self._member(facility, journey["username"])

    @action(detail=True, methods=["POST"])
    def create_status(self, request, *args, **kwargs):
        """Whether the professional has finished on ABDM's Aadhaar page, and what HPR knows."""
        journey, user = self._creation(JourneySpec(**request.data).journey_id)
        txn_id = journey["txn_id"]
        if not registry.aadhaar_authenticated(txn_id):
            return Response({"authenticated": False})
        if not journey["account"]:
            # HPR's order: the Aadhaar-verified details, then the account check
            registry.aadhaar_details(txn_id)
            journey["account"] = registry.existing_account(txn_id)
            journey.save()
        account = journey["account"]
        if not account["new"] and account["hpr_id_number"]:
            # Aadhaar already proved who this is; link the HPR ID they hold
            link = _link(
                user,
                account,
                request.user,
                account["token"] if user == request.user else None,
            )
            return Response({"authenticated": True, "linked": professional_row(link)})
        return Response(
            {
                "authenticated": True,
                "linked": None,
                "mobile_verified": bool(journey["mobile_verified"]),
                "suggestions": registry.suggestions(txn_id),
                "prefill": {
                    key: account[key]
                    for key in (
                        "first_name",
                        "middle_name",
                        "last_name",
                        "email",
                        "state_code",
                        "district_code",
                    )
                },
            }
        )

    @action(detail=True, methods=["POST"])
    def create_mobile(self, request, *args, **kwargs):
        data = MobileSpec(**request.data)
        journey, _ = self._creation(data.journey_id)
        if registry.mobile_matches_aadhaar(journey["txn_id"], data.mobile):
            journey["mobile_verified"] = True
            journey.save()
            return Response({"mobile_verified": True, "otp_sent": False})
        registry.send_mobile_otp(journey["txn_id"], data.mobile)
        return Response({"mobile_verified": False, "otp_sent": True})

    @action(detail=True, methods=["POST"])
    def create_mobile_otp(self, request, *args, **kwargs):
        data = OtpSpec(**request.data)
        journey, _ = self._creation(data.journey_id)
        registry.verify_mobile_otp(journey["txn_id"], data.otp)
        journey["mobile_verified"] = True
        journey.save()
        return Response({"mobile_verified": True})

    @action(detail=True, methods=["POST"])
    def create_hpr_id(self, request, *args, **kwargs):
        data = CreateHprIdSpec(**request.data)
        journey, user = self._creation(data.journey_id)
        if not journey["mobile_verified"]:
            raise ValidationError("Verify the professional's mobile number first")
        created = registry.create_hpr_id(
            journey["txn_id"], data.model_dump(exclude={"journey_id"})
        )
        link = _link(
            user,
            created,
            request.user,
            created["token"] if user == request.user else None,
        )
        return Response(professional_row(link))
