"""
NRCES document bundles built from CARE's EMR records.

Codes are carried over from CARE's own codings; nothing is invented. A value
CARE holds only as text travels as text.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from care.emr.models import (
    AllergyIntolerance,
    Condition,
    Encounter,
    ServiceRequest,
)
from care.emr.models.medication_request import MedicationRequest
from care.emr.models.patient import PatientIdentifier

NRCES = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/"
SNOMED = "http://snomed.info/sct"
UCUM = "http://unitsofmeasure.org"

OP_CONSULTATION = "OPConsultation"
PRESCRIPTION = "Prescription"

EXCLUDED_STATUSES = ("entered_in_error", "draft")

ENCOUNTER_STATUS = {
    "planned": "planned",
    "in_progress": "in-progress",
    "on_hold": "onleave",
    "discharged": "finished",
    "completed": "finished",
    "cancelled": "cancelled",
    "discontinued": "cancelled",
    "entered_in_error": "entered-in-error",
}
MEDICATION_REQUEST_STATUS = {"ended": "completed"}
SERVICE_REQUEST_STATUS = {"ended": "completed"}
PATIENT_GENDER = {"male": "male", "female": "female"}

OP_SECTIONS = {
    "ChiefComplaints": ("Chief complaints", "422843007", "Chief complaint section"),
    "Allergies": ("Allergies", "722446000", "Allergy record"),
    "MedicalHistory": ("Medical History", "371529009", "History and physical report"),
    "InvestigationAdvice": ("Investigation Advice", "721963009", "Order document"),
    "Medications": ("Medications", "721912009", "Medication summary document"),
}


def _code(value: str | None, mapping: dict | None = None) -> str | None:
    if not value:
        return None
    return (mapping or {}).get(value, value.replace("_", "-"))


def _concept(coding: dict | None, text: str | None = None) -> dict | None:
    if coding and coding.get("code"):
        concept = {
            "coding": [
                {
                    key: coding[key]
                    for key in ("system", "code", "display")
                    if coding.get(key)
                }
            ]
        }
        if coding.get("display") or text:
            concept["text"] = coding.get("display") or text
        return concept
    return {"text": text} if text else None


def _status_concept(system: str, code: str | None) -> dict | None:
    if not code:
        return None
    return {"coding": [{"system": system, "code": code.replace("_", "-")}]}


def _quantity(value, unit: dict | None) -> dict:
    quantity = {"value": float(Decimal(str(value)))}
    if unit:
        quantity["unit"] = unit.get("display") or unit.get("code")
        if unit.get("system"):
            quantity["system"] = unit["system"]
        if unit.get("code"):
            quantity["code"] = unit["code"]
    return quantity


def _timing_quantity(value: dict) -> dict:
    return {
        "value": float(value["value"]),
        "unit": value["unit"],
        "system": UCUM,
        "code": value["unit"],
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _clean(resource: dict) -> dict:
    return {
        key: value for key, value in resource.items() if value not in (None, [], {})
    }


class DocumentBuilder:
    def __init__(self, encounter: Encounter, hip_id: str):
        self.encounter = encounter
        self.patient = encounter.patient
        self.facility = encounter.facility
        self.hip_id = hip_id
        self.entries: list[dict] = []
        self._references: dict = {}

    def _add(self, key, resource_type: str, resource: dict) -> dict:
        if key in self._references:
            return self._references[key]
        resource_id = str(uuid.uuid4())
        reference = f"urn:uuid:{resource_id}"
        self.entries.append(
            {
                "fullUrl": reference,
                "resource": _clean(
                    {
                        "resourceType": resource_type,
                        "id": resource_id,
                        "meta": {"profile": [f"{NRCES}{resource_type}"]},
                        **resource,
                    }
                ),
            }
        )
        self._references[key] = {"reference": reference}
        return self._references[key]

    # Participants

    def patient_reference(self) -> dict:
        identifiers = []
        abha_number = (
            PatientIdentifier.objects.filter(
                patient=self.patient,
                config__config__system=settings.ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM,
            )
            .values_list("value", flat=True)
            .first()
        )
        if abha_number:
            identifiers.append(
                {
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                "code": "MR",
                                "display": "Medical record number",
                            }
                        ]
                    },
                    "system": "https://healthid.ndhm.gov.in",
                    "value": abha_number,
                }
            )
        gender = PATIENT_GENDER.get(self.patient.gender, "other")
        return self._add(
            ("Patient", self.patient.id),
            "Patient",
            {
                "identifier": identifiers,
                "name": [{"text": self.patient.name}],
                "gender": gender,
                "birthDate": _iso(self.patient.date_of_birth),
                "telecom": [
                    {
                        "system": "phone",
                        "value": self.patient.phone_number,
                        "use": "home",
                    }
                ]
                if self.patient.phone_number
                else None,
            },
        )

    def practitioner_reference(self, user) -> dict:
        identifiers = []
        # A verified HPR ID outranks a self-declared council registration
        professional = getattr(user, "abdm_professional", None)
        registration = (
            professional.hpr_id_number
            if professional
            else user.doctor_medical_council_registration
        )
        if registration:
            identifiers.append(
                {
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                "code": "MD",
                                "display": "Medical License number",
                            }
                        ]
                    },
                    "system": settings.ABDM_HPR_IDENTIFIER_SYSTEM,
                    "value": registration,
                }
            )
        return self._add(
            ("Practitioner", user.id),
            "Practitioner",
            {
                "identifier": identifiers,
                "name": [{"text": user.get_full_name() or user.username}],
            },
        )

    def organization_reference(self) -> dict:
        return self._add(
            ("Organization", self.facility.id),
            "Organization",
            {
                "identifier": [
                    {
                        "type": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                    "code": "PRN",
                                    "display": "Provider number",
                                }
                            ]
                        },
                        "system": "https://facility.ndhm.gov.in",
                        "value": self.hip_id,
                    }
                ],
                "name": self.facility.name,
            },
        )

    def encounter_reference(self, diagnoses: list[dict]) -> dict:
        period = self.encounter.period or {}
        return self._add(
            ("Encounter", self.encounter.id),
            "Encounter",
            {
                "identifier": [
                    {
                        "system": "urn:ietf:rfc:3986",
                        "value": f"urn:uuid:{self.encounter.external_id}",
                    }
                ],
                "status": ENCOUNTER_STATUS.get(self.encounter.status, "unknown"),
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": (self.encounter.encounter_class or "amb").upper(),
                },
                "subject": self.patient_reference(),
                "period": _clean(
                    {"start": period.get("start"), "end": period.get("end")}
                ),
                "diagnosis": [{"condition": reference} for reference in diagnoses],
            },
        )

    def authors(self, users) -> list[dict]:
        users = [user for user in users if user] or [self.encounter.created_by]
        return [self.practitioner_reference(user) for user in users if user]

    # Clinical resources

    def condition(self, condition: Condition) -> dict:
        return self._add(
            ("Condition", condition.id),
            "Condition",
            {
                "clinicalStatus": _status_concept(
                    "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    condition.clinical_status,
                ),
                "verificationStatus": _status_concept(
                    "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    condition.verification_status,
                ),
                "code": _concept(condition.code),
                "subject": self.patient_reference(),
                "recordedDate": _iso(condition.created_date),
                "note": [{"text": condition.note}] if condition.note else None,
            },
        )

    def allergy(self, allergy: AllergyIntolerance) -> dict:
        return self._add(
            ("AllergyIntolerance", allergy.id),
            "AllergyIntolerance",
            {
                "clinicalStatus": _status_concept(
                    "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    allergy.clinical_status,
                ),
                "verificationStatus": _status_concept(
                    "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                    allergy.verification_status,
                ),
                "category": [allergy.category] if allergy.category else None,
                "criticality": _code(allergy.criticality),
                "code": _concept(allergy.code),
                "patient": self.patient_reference(),
                "recordedDate": _iso(allergy.created_date),
            },
        )

    def service_request(self, request: ServiceRequest) -> dict:
        return self._add(
            ("ServiceRequest", request.id),
            "ServiceRequest",
            {
                "status": _code(request.status, SERVICE_REQUEST_STATUS),
                "intent": _code(request.intent) or "order",
                "code": _concept(request.code, request.title),
                "subject": self.patient_reference(),
                "authoredOn": _iso(request.created_date),
                "requester": self.authors([request.created_by])[0]
                if request.created_by
                else None,
            },
        )

    def dosage(self, instruction: dict) -> dict:
        timing = None
        repeat = (instruction.get("timing") or {}).get("repeat")
        if repeat:
            timing = {
                "repeat": _clean(
                    {
                        "frequency": repeat.get("frequency"),
                        "period": float(repeat["period"])
                        if repeat.get("period") is not None
                        else None,
                        "periodUnit": repeat.get("period_unit"),
                        "boundsDuration": _timing_quantity(repeat["bounds_duration"])
                        if repeat.get("bounds_duration")
                        else None,
                    }
                ),
                "code": _concept((instruction.get("timing") or {}).get("code")),
            }
        dose = (instruction.get("dose_and_rate") or {}).get("dose_quantity")
        return _clean(
            {
                "sequence": instruction.get("sequence"),
                "text": instruction.get("text"),
                "additionalInstruction": [
                    _concept(coding)
                    for coding in instruction.get("additional_instruction") or []
                ],
                "patientInstruction": instruction.get("patient_instruction"),
                "timing": _clean(timing) if timing else None,
                "asNeededBoolean": instruction.get("as_needed_boolean")
                if not instruction.get("as_needed_for")
                else None,
                "asNeededCodeableConcept": _concept(instruction.get("as_needed_for")),
                "site": _concept(instruction.get("site")),
                "route": _concept(instruction.get("route")),
                "method": _concept(instruction.get("method")),
                "doseAndRate": [
                    {"doseQuantity": _quantity(dose["value"], dose.get("unit"))}
                ]
                if dose
                else None,
            }
        )

    def medication_request(self, request: MedicationRequest) -> dict:
        product_name = (
            request.requested_product.name if request.requested_product else None
        )
        return self._add(
            ("MedicationRequest", request.id),
            "MedicationRequest",
            {
                "status": _code(request.status, MEDICATION_REQUEST_STATUS),
                "intent": _code(request.intent) or "order",
                "medicationCodeableConcept": _concept(request.medication, product_name),
                "subject": self.patient_reference(),
                "authoredOn": _iso(request.authored_on),
                "requester": self.authors([request.requester or request.created_by])[0],
                "dosageInstruction": [
                    self.dosage(instruction)
                    for instruction in request.dosage_instruction or []
                ],
                "note": [{"text": request.note}] if request.note else None,
            },
        )

    # Documents

    def document(
        self,
        *,
        profile: str,
        type_code: tuple[str, str],
        title: str,
        sections: list[dict],
        authors: list[dict],
        encounter: dict | None,
    ) -> dict:
        now = timezone.now().isoformat()
        composition_id = str(uuid.uuid4())
        composition = {
            "fullUrl": f"urn:uuid:{composition_id}",
            "resource": _clean(
                {
                    "resourceType": "Composition",
                    "id": composition_id,
                    "meta": {
                        "versionId": "1",
                        "lastUpdated": now,
                        "profile": [profile],
                    },
                    "language": "en-IN",
                    "identifier": {
                        "system": "urn:ietf:rfc:3986",
                        "value": f"urn:uuid:{composition_id}",
                    },
                    "status": "final",
                    "type": {
                        "coding": [
                            {
                                "system": SNOMED,
                                "code": type_code[0],
                                "display": type_code[1],
                            }
                        ],
                        "text": type_code[1],
                    },
                    "subject": self.patient_reference(),
                    "encounter": encounter,
                    "date": now,
                    "author": authors,
                    "title": title,
                    "custodian": self.organization_reference(),
                    "section": sections,
                }
            ),
        }
        bundle_id = str(uuid.uuid4())
        return {
            "resourceType": "Bundle",
            "id": bundle_id,
            "meta": {
                "versionId": "1",
                "lastUpdated": now,
                "profile": [f"{NRCES}DocumentBundle"],
            },
            "identifier": {
                "system": "urn:ietf:rfc:3986",
                "value": f"urn:uuid:{bundle_id}",
            },
            "type": "document",
            "timestamp": now,
            "entry": [composition, *self.entries],
        }


def _section(title: str, code: tuple[str, str], entries: list[dict]) -> dict:
    return {
        "title": title,
        "code": {"coding": [{"system": SNOMED, "code": code[0], "display": code[1]}]},
        "entry": entries,
    }


def _medication_requests(encounter):
    return (
        MedicationRequest.objects.filter(encounter=encounter)
        .exclude(status__in=EXCLUDED_STATUSES)
        .select_related("requester", "created_by", "requested_product")
    )


def build_op_consultation(encounter: Encounter, hip_id: str) -> dict | None:
    builder = DocumentBuilder(encounter, hip_id)
    conditions = Condition.objects.filter(encounter=encounter).exclude(
        verification_status="entered_in_error"
    )
    symptoms = [
        builder.condition(c) for c in conditions if c.category == "problem_list_item"
    ]
    history = [
        builder.condition(c) for c in conditions if c.category == "chronic_condition"
    ]
    diagnoses = [
        builder.condition(c) for c in conditions if c.category == "encounter_diagnosis"
    ]
    allergies = [
        builder.allergy(a)
        for a in AllergyIntolerance.objects.filter(encounter=encounter).exclude(
            verification_status="entered_in_error"
        )
    ]
    investigations = [
        builder.service_request(s)
        for s in ServiceRequest.objects.filter(encounter=encounter).exclude(
            status__in=EXCLUDED_STATUSES
        )
    ]
    medications = [
        builder.medication_request(m) for m in _medication_requests(encounter)
    ]

    sections = [
        _section(OP_SECTIONS[name][0], OP_SECTIONS[name][1:], entries)
        for name, entries in (
            ("ChiefComplaints", symptoms),
            ("Allergies", allergies),
            ("MedicalHistory", history),
            ("InvestigationAdvice", investigations),
            ("Medications", medications),
        )
        if entries
    ]
    if not sections:
        return None
    return builder.document(
        profile=f"{NRCES}OPConsultRecord",
        type_code=("371530004", "Clinical consultation report"),
        title="Consultation Report",
        sections=sections,
        authors=builder.authors([]),
        encounter=builder.encounter_reference(diagnoses),
    )


def build_prescription(encounter: Encounter, hip_id: str) -> dict | None:
    builder = DocumentBuilder(encounter, hip_id)
    requests = list(_medication_requests(encounter))
    if not requests:
        return None
    entries = [builder.medication_request(m) for m in requests]
    return builder.document(
        profile=f"{NRCES}PrescriptionRecord",
        type_code=("440545006", "Prescription record"),
        title="Prescription record",
        sections=[
            _section(
                "Prescription record", ("440545006", "Prescription record"), entries
            )
        ],
        authors=builder.authors({m.requester or m.created_by for m in requests}),
        encounter=None,
    )


BUILDERS = {OP_CONSULTATION: build_op_consultation, PRESCRIPTION: build_prescription}
OUTPATIENT_CLASSES = ("amb", "vr", "hh", "emer", "obsenc")
# Diagnoses travel on Encounter.diagnosis, so alone they fill no section
SECTION_CONDITION_CATEGORIES = ("problem_list_item", "chronic_condition")


def available_hi_types(encounter: Encounter) -> list[str]:
    """The record types this encounter has data for."""
    hi_types = []
    if encounter.encounter_class in OUTPATIENT_CLASSES and (
        Condition.objects.filter(
            encounter=encounter, category__in=SECTION_CONDITION_CATEGORIES
        ).exists()
        or AllergyIntolerance.objects.filter(encounter=encounter).exists()
        or ServiceRequest.objects.filter(encounter=encounter).exists()
        or _medication_requests(encounter).exists()
    ):
        hi_types.append(OP_CONSULTATION)
    if _medication_requests(encounter).exists():
        hi_types.append(PRESCRIPTION)
    return hi_types
