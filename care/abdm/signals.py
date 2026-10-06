from django.db.models.signals import post_save
from django.dispatch import receiver

from care.abdm.linking import schedule_link
from care.emr.models import AllergyIntolerance, Condition, ServiceRequest
from care.emr.models.medication_request import MedicationRequest


@receiver(post_save, sender=MedicationRequest)
@receiver(post_save, sender=Condition)
@receiver(post_save, sender=AllergyIntolerance)
@receiver(post_save, sender=ServiceRequest)
def link_on_clinical_record(sender, instance, **kwargs):
    """A record that belongs in a shared document was added or changed on a visit."""
    if instance.encounter_id:
        schedule_link(instance.encounter_id)
