import json
import os
from pathlib import Path

from care.abdm.fhir import (
    NRCES,
    available_hi_types,
    build_op_consultation,
    build_prescription,
)
from care.abdm.tests.fixtures import HIP_ID, give_abha, make_clinical_encounter
from care.utils.tests.base import CareAPITestBase


def _references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "reference":
                yield item
            else:
                yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


class TestFhirBundles(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.encounter = make_clinical_encounter(self)
        give_abha(self.encounter.patient)

    def assert_document(self, bundle, profile):
        self.assertEqual(bundle["type"], "document")
        self.assertEqual(bundle["meta"]["profile"], [f"{NRCES}DocumentBundle"])
        composition = bundle["entry"][0]["resource"]
        self.assertEqual(composition["resourceType"], "Composition")
        self.assertEqual(composition["meta"]["profile"], [f"{NRCES}{profile}"])
        full_urls = {entry["fullUrl"] for entry in bundle["entry"]}
        for reference in _references(bundle["entry"]):
            self.assertIn(
                reference, full_urls, "reference must resolve inside the bundle"
            )
        # Opt-in dump so the bundles can be checked against the NRCES validators
        if path := os.environ.get("ABDM_DUMP_BUNDLES"):
            (Path(path) / f"{profile}.json").write_text(json.dumps(bundle, indent=1))
        return composition

    def test_available_hi_types(self):
        self.assertEqual(
            available_hi_types(self.encounter), ["OPConsultation", "Prescription"]
        )

    def test_op_consultation(self):
        bundle = build_op_consultation(self.encounter, HIP_ID)
        composition = self.assert_document(bundle, "OPConsultRecord")
        self.assertIn("encounter", composition)
        self.assertEqual(
            [s["title"] for s in composition["section"]],
            [
                "Chief complaints",
                "Allergies",
                "Investigation Advice",
                "Medications",
            ],
        )
        patient = next(
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Patient"
        )
        self.assertEqual(patient["identifier"][0]["value"], "91-1234-5678-9012")
        encounter = next(
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Encounter"
        )
        self.assertEqual(len(encounter["diagnosis"]), 1)

    def test_prescription(self):
        bundle = build_prescription(self.encounter, HIP_ID)
        composition = self.assert_document(bundle, "PrescriptionRecord")
        entries = composition["section"][0]["entry"]
        self.assertEqual(len(entries), 1)
        request = next(
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "MedicationRequest"
        )
        dosage = request["dosageInstruction"][0]
        self.assertEqual(dosage["timing"]["repeat"]["frequency"], 3)
        self.assertEqual(dosage["doseAndRate"][0]["doseQuantity"]["value"], 1.0)

    def test_inpatient_encounter_has_no_op_consultation(self):
        encounter = make_clinical_encounter(self, encounter_class="imp")
        self.assertEqual(available_hi_types(encounter), ["Prescription"])
