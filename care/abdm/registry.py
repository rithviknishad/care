"""
M4: the Health Facility Registry (HFR) and Healthcare Professionals Registry (HPR).

Every call here is synchronous; neither registry answers by callback.
"""

import base64
import re
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from django.conf import settings
from django.core.cache import cache

from care.abdm.client import registry_json, registry_request

HPR_DOMAIN = "@hpr.abdm"
# HFR refuses a search page smaller than this (HIS-4047)
SEARCH_PAGE_SIZE = 10
MASTER_TTL_SECONDS = 24 * 60 * 60
HPR_CERTIFICATE_CACHE_KEY = "abdm:hpr:public_certificate"
HPR_TOKEN_CACHE_KEY = "abdm:hpr:token:{user_id}"
# HPR's register role for professionals; 2 lists administrator categories instead
PROFESSIONAL_ROLE = 0
FACILITY_MASTER_TYPES = {
    "MEDICINE",
    "OWNER",
    "TYPE-SERVICE",
    "SPECIALITY-TYPE",
    "FAC-STATUS",
    "FACILITY-REGION",
}
# HFR publishes these in its field docs, not as master data
OWNERSHIP_SUB_TYPES = {
    "G": [
        {"code": "C", "name": "Central Government"},
        {"code": "S", "name": "State Government"},
    ],
    "P": [
        {"code": "P", "name": "Profit"},
        {"code": "NP", "name": "Non-profit"},
    ],
    "PP": [
        {"code": "P", "name": "Profit"},
        {"code": "NP", "name": "Non-profit"},
    ],
}
HPR_NUMBER_PATTERN = re.compile(r"^\d{2}-?\d{4}-?\d{4}-?\d{4}$")


def _text(value) -> str:
    # HFR pads master codes with trailing spaces
    return str(value).strip() if value is not None else ""


def _options(items, code="code", name="value") -> list[dict]:
    return [
        {"code": _text(item.get(code)), "name": _text(item.get(name))}
        for item in items or []
        if isinstance(item, dict)
    ]


def _cached(key: str, load):
    value = cache.get(key)
    if value is None:
        value = load()
        cache.set(key, value, MASTER_TTL_SECONDS)
    return value


# HFR -------------------------------------------------------------------------


def _facility_row(item: dict) -> dict:
    return {
        "facility_id": item.get("facilityId"),
        "name": item.get("facilityName"),
        "status": item.get("facilityStatus"),
        "ownership": item.get("ownership"),
        "ownership_code": item.get("ownershipCode"),
        "facility_type": item.get("facilityType"),
        "system_of_medicine": item.get("systemOfMedicine"),
        "state": item.get("stateName"),
        "district": item.get("districtName"),
        "sub_district": item.get("subDistrictName"),
        "address": item.get("address"),
        "pincode": item.get("pincode"),
    }


def search_facilities(
    *,
    facility_id: str | None = None,
    name: str | None = None,
    state_code: str | None = None,
    district_code: str | None = None,
    ownership_code: str | None = None,
    page: int = 1,
) -> dict:
    body = {"page": page, "resultsPerPage": SEARCH_PAGE_SIZE}
    if facility_id:
        body["facilityId"] = facility_id
    else:
        body.update(stateLGDCode=state_code, ownershipCode=ownership_code)
        if name:
            body["facilityName"] = name
        if district_code:
            body["districtLGDCode"] = district_code
    data = (
        registry_json("POST", "/FacilityManagement/v1.5/facility/search", json=body)
        or {}
    )
    return {
        "results": [_facility_row(item) for item in data.get("facilities") or []],
        "total": data.get("totalFacilities") or 0,
        "pages": data.get("numberOfPages") or 0,
    }


def get_facility(facility_id: str) -> dict | None:
    return next(
        (
            row
            for row in search_facilities(facility_id=facility_id)["results"]
            if row["facility_id"] == facility_id
        ),
        None,
    )


def states() -> list[dict]:
    def load():
        data = registry_json("GET", "/v1.5/facility/lgd/states") or []
        return [
            {
                "code": _text(state.get("code")),
                "name": _text(state.get("name")),
                "districts": _options(state.get("districts"), name="name"),
            }
            for state in data
        ]

    return _cached("abdm:hfr:states", load)


def sub_districts(district_code: str) -> list[dict]:
    return _cached(
        f"abdm:hfr:sub_districts:{district_code}",
        lambda: _options(
            registry_json(
                "GET",
                "/v1.5/facility/lgd/subdistricts",
                params={"districtCode": district_code},
            ),
            name="name",
        ),
    )


def master_data(master_type: str) -> list[dict]:
    if master_type not in FACILITY_MASTER_TYPES:
        msg = f"Unknown HFR master type {master_type}"
        raise ValueError(msg)
    return _cached(
        f"abdm:hfr:master:{master_type}",
        lambda: _options(
            (
                registry_json(
                    "GET",
                    "/v1.5/facility/get-master-data",
                    params={"type": master_type},
                )
                or {}
            ).get("data")
        ),
    )


def facility_types(ownership_code: str, system_of_medicine_code: str) -> list[dict]:
    return _cached(
        f"abdm:hfr:types:{ownership_code}:{system_of_medicine_code}",
        lambda: _options(
            (
                registry_json(
                    "POST",
                    "/v1.5/facility/fetch-facility-type",
                    json={
                        "ownershipCode": ownership_code,
                        "systemOfMedicineCode": system_of_medicine_code,
                    },
                )
                or {}
            ).get("data")
        ),
    )


def facility_sub_types(facility_type_code: str) -> list[dict]:
    return _cached(
        f"abdm:hfr:sub_types:{facility_type_code}",
        lambda: _options(
            (
                registry_json(
                    "POST",
                    "/v1.5/facility/fetch-facility-Sub-type",
                    json={"facilityTypeCode": facility_type_code},
                )
                or {}
            ).get("data")
        ),
    )


def ownership_sub_types(ownership_code: str) -> list[dict]:
    if ownership_code not in OWNERSHIP_SUB_TYPES:
        msg = f"Unknown ownership {ownership_code}"
        raise ValueError(msg)
    return OWNERSHIP_SUB_TYPES[ownership_code]


def owner_sub_types(ownership_code: str, owner_sub_type_code: str) -> list[dict]:
    return _cached(
        f"abdm:hfr:owner_sub_types:{ownership_code}:{owner_sub_type_code}",
        lambda: _options(
            (
                registry_json(
                    "POST",
                    "/v1.5/facility/get-owner-subtype",
                    json={
                        "ownershipCode": ownership_code,
                        "ownerSubtypeCode": owner_sub_type_code,
                    },
                )
                or {}
            ).get("data")
        ),
    )


def register_services(facility_id: str, facility_name: str) -> dict:
    """Serve an HFR facility from this bridge, as both HIP and HIU."""
    return (
        registry_json(
            "POST",
            "/v1/bridges/MutipleHRPAddUpdateServices",
            json={
                "facilityId": facility_id,
                "facilityName": facility_name,
                "HRP": [
                    {
                        # The bridge id is the client id ABDM issued this deployment
                        "bridgeId": settings.ABDM_CLIENT_ID,
                        "hipName": facility_name,
                        "type": service_type,
                        "active": True,
                    }
                    for service_type in ("HIP", "HIU")
                ],
            },
        )
        or {}
    )


def save_basic_information(facility_information: dict, tracking_id: str, hpr_token):
    return (
        registry_json(
            "POST",
            "/v1.5/facility/basic-information",
            json={
                "trackingId": tracking_id or "",
                "facilityInformation": facility_information,
            },
            hpr_token=hpr_token,
        )
        or {}
    )


def submit_facility(tracking_id: str, hpr_token: str) -> dict:
    return (
        registry_json(
            "POST",
            "/v1.5/facility/submit-facility",
            json={"trackingId": tracking_id},
            hpr_token=hpr_token,
        )
        or {}
    )


# HPR -------------------------------------------------------------------------


def hpr_address(value: str) -> str:
    """The HPR ID as HPR looks it up: a 14 digit number, or a name@hpr.abdm address."""
    value = value.strip().lower()
    if HPR_NUMBER_PATTERN.match(value) or "@" in value:
        return value
    return f"{value}{HPR_DOMAIN}"


def _professional(data: dict) -> dict:
    return {
        "hpr_id": data.get("hprId") or "",
        "hpr_id_number": data.get("hprIdNumber") or "",
        "name": data.get("name") or "",
    }


def find_professional(hpr_id: str) -> dict:
    data = (
        registry_json("GET", f"/v1/search/searchByHprId/{quote(hpr_id, safe='@')}")
        or {}
    )
    return {
        **_professional(data),
        "auth_methods": data.get("authMethods") or [],
    }


def start_login(hpr_id: str) -> dict:
    data = (
        registry_json(
            "POST",
            "/api/v1/auth/init",
            json={
                "idType": "hpr_id",
                "domainName": HPR_DOMAIN,
                "authMethod": "AADHAAR_OTP",
                "hprId": hpr_id,
            },
        )
        or {}
    )
    return {"txn_id": data["transactionId"], "mobile": data.get("mobileNumber")}


def confirm_login(txn_id: str, otp: str) -> dict:
    data = (
        registry_json(
            "POST",
            "/api/v1/auth/confirmWithAadhaarOtp",
            json={"otp": otp, "txnId": txn_id},
        )
        or {}
    )
    return {"token": data["token"], "expires_in": data.get("expiresIn")}


def remember_hpr_token(user_id: int, token: str, expires_in):
    """Kept server-side; the facility submission sends it as x-hprid-auth."""
    if token and expires_in:
        cache.set(HPR_TOKEN_CACHE_KEY.format(user_id=user_id), token, int(expires_in))


def recall_hpr_token(user_id: int) -> str | None:
    return cache.get(HPR_TOKEN_CACHE_KEY.format(user_id=user_id))


def _hpr_certificate() -> str:
    certificate = cache.get(HPR_CERTIFICATE_CACHE_KEY)
    if not certificate:
        # A bare PEM, not JSON
        certificate = registry_request("GET", "/api/v1/auth/cert").text.strip()
        cache.set(
            HPR_CERTIFICATE_CACHE_KEY,
            certificate,
            settings.ABDM_CERTIFICATE_TTL_SECONDS,
        )
    return certificate


def encrypt(value: str) -> str:
    # The HPR certificate is RSA; HPR names no padding, PKCS#1 v1.5 is what it takes
    public_key = load_pem_public_key(_hpr_certificate().encode())
    return base64.b64encode(
        public_key.encrypt(value.encode(), padding.PKCS1v15())
    ).decode()


def categories() -> list[dict]:
    def load():
        data = (
            registry_json(
                "GET", "/hpid/get/categories", params={"role": PROFESSIONAL_ROLE}
            )
            or []
        )
        return [
            {
                "code": _text(category.get("code")),
                "name": _text(category.get("name")),
                "sub_categories": _options(category.get("subCategories"), name="name"),
            }
            for category in data
        ]

    return _cached("abdm:hpr:categories", load)


def start_aadhaar_link() -> dict:
    """ABDM's own page takes the Aadhaar number; CARE only holds the txnId."""
    data = (
        registry_json(
            "POST",
            "/aadhaar/generateLink",
            json={"scopes": ["nhpr-register"], "source": "NHPR"},
        )
        or {}
    )
    return {"txn_id": data["txnId"], "url": data["url"]}


def aadhaar_authenticated(txn_id: str) -> bool:
    return (
        registry_json("POST", "/aadhaar/isAuthenticated", json={"txnId": txn_id})
        is True
    )


def aadhaar_details(txn_id: str) -> dict:
    data = (
        registry_json(
            "POST", "/v2/registration/aadhaar/verifyOTP", json={"txnId": txn_id}
        )
        or {}
    )
    return {"name": data.get("name") or "", "mobile": data.get("mobileNumber") or ""}


def existing_account(txn_id: str) -> dict:
    data = (
        registry_json(
            "POST",
            "/v1/registration/aadhaar/checkHpIdAccountExist",
            json={"txnId": txn_id, "preverifiedCheck": True},
        )
        or {}
    )
    return {
        **_professional(data),
        "new": bool(data.get("new")),
        "token": data.get("token"),
        "first_name": data.get("firstName") or "",
        "middle_name": data.get("middleName") or "",
        "last_name": data.get("lastName") or "",
        "state_code": _text(data.get("stateCode")),
        "district_code": _text(data.get("districtCode")),
        "email": data.get("email") or "",
    }


def suggestions(txn_id: str) -> list[str]:
    data = registry_json(
        "POST", "/v1/registration/aadhaar/hpid/suggestion", json={"txnId": txn_id}
    )
    return [item for item in data or [] if isinstance(item, str)]


def mobile_matches_aadhaar(txn_id: str, mobile: str) -> bool:
    data = (
        registry_json(
            "POST",
            "/v2/registration/aadhaar/demographicAuthViaMobile",
            json={"txnId": txn_id, "mobileNumber": mobile},
        )
        or {}
    )
    return bool(data.get("verified"))


def send_mobile_otp(txn_id: str, mobile: str):
    registry_json(
        "POST",
        "/v1/registration/aadhaar/generateMobileOTP",
        json={"txnId": txn_id, "mobile": mobile},
    )


def verify_mobile_otp(txn_id: str, otp: str):
    registry_json(
        "POST",
        "/v1/registration/aadhaar/verifyMobileOTP",
        json={"txnId": txn_id, "otp": encrypt(otp)},
    )


def create_hpr_id(txn_id: str, details: dict) -> dict:
    data = (
        registry_json(
            "POST",
            "/v2/registration/aadhaar/createHprIdWithPreVerified",
            json={
                "idType": "hpr_id",
                "domainName": HPR_DOMAIN,
                "txnId": txn_id,
                "hprId": details["hpr_id"],
                "email": details["email"],
                "password": details["password"],
                "firstName": details.get("first_name") or "",
                "middleName": details.get("middle_name") or "",
                "lastName": details.get("last_name") or "",
                "sourceType": "AADHAAR",
                "hpCategoryCode": int(details["category"]),
                "hpSubCategoryCode": int(details["sub_category"]),
                "stateCode": details["state_code"],
                "districtCode": details["district_code"],
                "council": False,
                "role": PROFESSIONAL_ROLE,
            },
        )
        or {}
    )
    return {**_professional(data), "token": data.get("token")}
