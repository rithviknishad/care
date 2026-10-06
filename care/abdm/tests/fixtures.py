from datetime import date

from django.utils import timezone

from care.emr.models import AllergyIntolerance, Condition
from care.emr.models.medication_request import MedicationRequest
from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig

ABHA_NUMBER = "91-1234-5678-9012"
ABHA_ADDRESS = "asha@sbx"
HIP_ID = "IN3210000778"


def abha_identifier_configs():
    configs = {}
    for key, system in (
        ("number", "https://healthid.abdm.gov.in"),
        ("address", "https://abha.abdm.gov.in"),
    ):
        configs[key] = PatientIdentifierConfig.objects.create(
            status="active",
            config={
                "use": "official",
                "system": system,
                "required": False,
                "unique": True,
                "regex": "",
                "display": key,
            },
        )
    return configs


def give_abha(patient):
    configs = abha_identifier_configs()
    PatientIdentifier.objects.create(
        patient=patient, config=configs["number"], value=ABHA_NUMBER
    )
    PatientIdentifier.objects.create(
        patient=patient, config=configs["address"], value=ABHA_ADDRESS
    )


def make_clinical_encounter(test, encounter_class="amb"):
    """An outpatient visit with a complaint, a diagnosis, an allergy, a test and a medicine."""
    doctor = test.create_user(
        first_name="Meera",
        last_name="Nair",
        doctor_medical_council_registration="KMC-12345",
    )
    facility = test.create_facility(user=doctor, name="OHC Hospital")
    patient = test.create_patient(
        name="Asha Kumari",
        gender="female",
        phone_number="+919876543210",
        date_of_birth=date(1990, 3, 5),
    )
    encounter = test.create_encounter(
        patient=patient,
        facility=facility,
        organization=test.create_facility_organization(facility=facility),
        encounter_class=encounter_class,
        period={"start": timezone.now().isoformat()},
        created_by=doctor,
    )
    common = {"patient": patient, "encounter": encounter, "created_by": doctor}
    Condition.objects.create(
        category="problem_list_item",
        clinical_status="active",
        verification_status="confirmed",
        code={
            "system": "http://snomed.info/sct",
            "code": "386661006",
            "display": "Fever",
        },
        **common,
    )
    Condition.objects.create(
        category="encounter_diagnosis",
        clinical_status="active",
        verification_status="provisional",
        code={
            "system": "http://snomed.info/sct",
            "code": "6142004",
            "display": "Influenza",
        },
        **common,
    )
    AllergyIntolerance.objects.create(
        clinical_status="active",
        verification_status="confirmed",
        category="medication",
        criticality="high",
        code={
            "system": "http://snomed.info/sct",
            "code": "764146007",
            "display": "Penicillin",
        },
        **common,
    )
    test.create_service_request(
        patient=patient,
        facility=facility,
        encounter=encounter,
        created_by=doctor,
        title="Complete blood count",
        category="laboratory",
        status="active",
        intent="order",
        priority="routine",
        code={
            "system": "http://snomed.info/sct",
            "code": "26604007",
            "display": "Complete blood count",
        },
    )
    MedicationRequest.objects.create(
        status="active",
        intent="order",
        category="outpatient",
        priority="routine",
        do_not_perform=False,
        medication={
            "system": "http://snomed.info/sct",
            "code": "322236009",
            "display": "Paracetamol 500 mg oral tablet",
        },
        dosage_instruction=[
            {
                "text": "One tablet thrice daily for 3 days",
                "as_needed_boolean": False,
                "timing": {
                    "repeat": {
                        "frequency": 3,
                        "period": "1",
                        "period_unit": "d",
                        "bounds_duration": {"value": "3", "unit": "d"},
                    }
                },
                "route": {
                    "system": "http://snomed.info/sct",
                    "code": "26643006",
                    "display": "Oral route",
                },
                "dose_and_rate": {
                    "type": "ordered",
                    "dose_quantity": {
                        "value": "1",
                        "unit": {
                            "system": "http://snomed.info/sct",
                            "code": "732936001",
                            "display": "Tablet",
                        },
                    },
                },
            }
        ],
        authored_on=timezone.now(),
        requester=doctor,
        **common,
    )
    return encounter
