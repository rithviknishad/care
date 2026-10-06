import re
from datetime import date

GENDERS = {"M": "male", "F": "female", "T": "transgender"}
ABHA_NUMBER_PATTERN = re.compile(r"^\d{2}-\d{4}-\d{4}-\d{4}$")


def format_abha_number(value: str | None) -> str | None:
    """ABDM validates an ABHA number with its dashes; restore them if missing."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) != 14:  # noqa: PLR2004
        return value
    return f"{digits[:2]}-{digits[2:6]}-{digits[6:10]}-{digits[10:]}"


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_of_birth(profile: dict) -> tuple[str | None, int | None]:
    day = _to_int(profile.get("dayOfBirth"))
    month = _to_int(profile.get("monthOfBirth"))
    year = _to_int(profile.get("yearOfBirth"))
    dob = profile.get("dob") or profile.get("dateOfBirth")
    if dob and not (day and month and year):
        parts = re.split(r"[-/]", str(dob))
        if len(parts) == 3:  # noqa: PLR2004
            # ABHA returns DD-MM-YYYY; an ISO date has the year first
            if len(parts[0]) == 4:  # noqa: PLR2004
                year, month, day = (_to_int(p) for p in parts)
            else:
                day, month, year = (_to_int(p) for p in parts)
    if day and month and year:
        try:
            return date(year, month, day).isoformat(), year
        except ValueError:
            pass
    return None, year


def _phone_number(mobile: str | None) -> str | None:
    if not mobile:
        return None
    digits = re.sub(r"\D", "", str(mobile))
    # A masked number cannot fill the form
    if len(digits) != 10 or re.search(r"[*xX]", str(mobile)):  # noqa: PLR2004
        return None
    return f"+91{digits}"


def _abha_address(profile: dict) -> str | None:
    address = profile.get("preferredAbhaAddress") or profile.get("healthId")
    if not address:
        phr_addresses = profile.get("phrAddress") or []
        address = phr_addresses[0] if phr_addresses else None
    return address


def to_patient_facts(profile: dict) -> dict:
    """Map an ABHA profile, in any of the shapes ABDM returns it, onto CARE's patient fields."""
    name = profile.get("name") or " ".join(
        part
        for part in (
            profile.get("firstName"),
            profile.get("middleName"),
            profile.get("lastName"),
        )
        if part
    )
    date_of_birth, year_of_birth = _date_of_birth(profile)
    pincode = _to_int(profile.get("pincode") or profile.get("pinCode"))
    return {
        "abha_number": format_abha_number(
            profile.get("ABHANumber") or profile.get("healthIdNumber")
        ),
        "abha_address": _abha_address(profile),
        "name": name or None,
        "gender": GENDERS.get(str(profile.get("gender") or "").upper()),
        "date_of_birth": date_of_birth,
        "year_of_birth": year_of_birth,
        "phone_number": _phone_number(profile.get("mobile")),
        "address": profile.get("address") or None,
        "pincode": pincode,
        "state_name": profile.get("stateName") or None,
        "district_name": profile.get("districtName") or None,
        "photo": profile.get("profilePhoto") or profile.get("photo") or None,
        "kyc_verified": str(profile.get("kycVerified")).lower() == "true",
    }
