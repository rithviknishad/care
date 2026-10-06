from django.conf import settings
from django.core.management.base import BaseCommand

from care.emr.models.patient import PatientIdentifierConfig
from care.emr.resources.patient_identifier.spec import (
    IdentifierConfig,
    PatientIdentifierStatus,
    PatientIdentifierUse,
)

IDENTIFIERS = [
    {
        "system_setting": "ABDM_ABHA_NUMBER_IDENTIFIER_SYSTEM",
        "use": PatientIdentifierUse.official,
        "display": "ABHA Number",
        "description": "Ayushman Bharat Health Account number",
        "regex": r"^\d{2}-\d{4}-\d{4}-\d{4}$",
    },
    {
        "system_setting": "ABDM_ABHA_ADDRESS_IDENTIFIER_SYSTEM",
        "use": PatientIdentifierUse.secondary,
        "display": "ABHA Address",
        "description": "Ayushman Bharat Health Account address",
        "regex": "",
    },
]


class Command(BaseCommand):
    help = "Create the instance-level patient identifier configs ABDM uses"

    def handle(self, *args, **options):
        for identifier in IDENTIFIERS:
            system = getattr(settings, identifier["system_setting"])
            existing = PatientIdentifierConfig.objects.filter(
                facility__isnull=True, config__system=system
            ).first()
            if existing:
                self.stdout.write(f"{identifier['display']}: exists ({system})")
                continue
            config = IdentifierConfig(
                use=identifier["use"],
                description=identifier["description"],
                system=system,
                required=False,
                unique=True,
                regex=identifier["regex"],
                display=identifier["display"],
            )
            PatientIdentifierConfig.objects.create(
                status=PatientIdentifierStatus.active.value,
                config=config.model_dump(mode="json"),
            )
            self.stdout.write(
                self.style.SUCCESS(f"{identifier['display']}: created ({system})")
            )
