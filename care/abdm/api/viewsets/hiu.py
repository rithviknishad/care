from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import UUID4, BaseModel, Field, model_validator
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from care.abdm import hiu, tasks
from care.abdm.linking import hip_id_for, patient_abha
from care.abdm.models import (
    AbdmHiuConsentArtefact,
    AbdmHiuConsentRequest,
    HiuConsentStatus,
)
from care.emr.api.viewsets.base import EMRBaseViewSet
from care.emr.models.organization import FacilityOrganizationUser
from care.emr.models.patient import Patient
from care.facility.models.facility import Facility
from care.security.authorization import AuthorizationController
from care.utils.shortcuts import get_object_or_404


def _artefact_row(artefact: AbdmHiuConsentArtefact) -> dict:
    return {
        "consent_id": artefact.consent_id,
        "status": artefact.status,
        "hip_id": artefact.hip_id,
        "hip_name": artefact.hip_name,
        "hi_types": artefact.hi_types,
        "care_context_count": len(artefact.care_contexts),
        "date_from": artefact.date_from,
        "date_to": artefact.date_to,
        "data_erase_at": artefact.data_erase_at,
        "session_status": artefact.session_status,
        "status_responses": artefact.status_responses,
        "error_code": artefact.error_code,
        "error_message": artefact.error_message,
        "record_count": artefact.records.count(),
        "modified_date": artefact.modified_date,
    }


def consent_request_row(consent_request: AbdmHiuConsentRequest) -> dict:
    hiu.give_up_if_unanswered(consent_request)
    requester = consent_request.requester
    return {
        "id": str(consent_request.external_id),
        "status": consent_request.status,
        "purpose": consent_request.purpose,
        "hi_types": consent_request.hi_types,
        "date_from": consent_request.date_from,
        "date_to": consent_request.date_to,
        "data_erase_at": consent_request.data_erase_at,
        "hiu_id": consent_request.hiu_id,
        "facility_name": consent_request.facility.name,
        "requester": (requester.get_full_name() or requester.username)
        if requester
        else None,
        "error_code": consent_request.error_code,
        "error_message": consent_request.error_message,
        "created_date": consent_request.created_date,
        "artefacts": [_artefact_row(a) for a in consent_request.artefacts.all()],
    }


class ConsentRequestSpec(BaseModel):
    patient: UUID4
    facility: UUID4
    purpose: str
    hi_types: list[str] = Field(min_length=1)
    date_from: datetime
    date_to: datetime
    data_erase_at: datetime

    @model_validator(mode="after")
    def check(self):
        if self.purpose not in hiu.PURPOSES:
            msg = f"Purpose must be one of {', '.join(hiu.PURPOSES)}"
            raise ValueError(msg)
        if unknown := set(self.hi_types) - set(hiu.HI_TYPES):
            msg = f"Unknown record types: {', '.join(sorted(unknown))}"
            raise ValueError(msg)
        # ABDM refuses a range that ends in the future, which "up to today" does
        self.date_to = min(self.date_to, timezone.now())
        if self.date_from >= self.date_to:
            msg = "The record range must start before it ends"
            raise ValueError(msg)
        if self.data_erase_at <= timezone.now():
            msg = "Access must last into the future"
            raise ValueError(msg)
        return self


class AbdmConsentRequestViewSet(EMRBaseViewSet):
    """Requests for a patient's records held by other providers."""

    def _consent_request(self):
        hiu_enabled()
        consent_request = get_object_or_404(
            AbdmHiuConsentRequest.objects.select_related("patient", "facility"),
            external_id=self.kwargs["external_id"],
        )
        self._authorize(consent_request.patient, consent_request.facility)
        return consent_request

    def _authorize(self, patient, facility):
        user = self.request.user
        if not AuthorizationController.call("can_write_patient_obj", user, patient):
            raise PermissionDenied("Cannot request records for this patient")
        if not (
            user.is_superuser
            or FacilityOrganizationUser.objects.filter(
                user=user, organization__facility=facility
            ).exists()
        ):
            raise PermissionDenied("Requests are made on behalf of your own facility")

    def create(self, request, *args, **kwargs):
        hiu_enabled()
        data = ConsentRequestSpec(**request.data)
        patient = get_object_or_404(Patient, external_id=data.patient)
        facility = get_object_or_404(Facility, external_id=data.facility)
        self._authorize(patient, facility)
        hiu_id = hip_id_for(facility)
        if not hiu_id:
            raise ValidationError("This facility has no ABDM ID")
        _, abha_address = patient_abha(patient)
        if not abha_address:
            raise ValidationError("The patient has no ABHA address")
        consent_request = AbdmHiuConsentRequest.objects.create(
            patient=patient,
            facility=facility,
            requester=request.user,
            hiu_id=hiu_id,
            abha_address=abha_address,
            purpose=data.purpose,
            hi_types=data.hi_types,
            date_from=data.date_from,
            date_to=data.date_to,
            data_erase_at=data.data_erase_at,
        )
        transaction.on_commit(
            lambda: tasks.send_consent_request.delay(consent_request.id)
        )
        return Response(consent_request_row(consent_request), status=201)

    @action(detail=True, methods=["POST"])
    def refresh(self, request, *args, **kwargs):
        """Ask ABDM where the request has got to."""
        consent_request = self._consent_request()
        if consent_request.consent_request_id:
            transaction.on_commit(
                lambda: tasks.refresh_consent_status.delay(consent_request.id)
            )
        return Response(consent_request_row(consent_request))

    @action(detail=True, methods=["POST"])
    def fetch(self, request, *args, **kwargs):
        """Request the records again under every artefact still in force."""
        consent_request = self._consent_request()
        if consent_request.status != HiuConsentStatus.granted:
            raise ValidationError("The patient has not granted this request")
        for artefact in consent_request.artefacts.all():
            if hiu.usable(artefact) and artefact.hip_id:
                transaction.on_commit(
                    lambda a=artefact: tasks.request_hiu_records.delay(a.id)
                )
            elif not artefact.hip_id:
                transaction.on_commit(
                    lambda a=artefact: tasks.fetch_hiu_artefact.delay(a.id)
                )
        return Response(consent_request_row(consent_request))


def hiu_enabled():
    if not settings.ABDM_ENABLED:
        raise NotFound("ABDM is not enabled")
