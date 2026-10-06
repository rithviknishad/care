from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from pydantic import BaseModel, Field
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from care.abdm import hiu
from care.abdm.api.viewsets.hiu import consent_request_row
from care.abdm.client import AbdmError, _send, get_gateway_token
from care.abdm.fhir import BUILDERS, available_hi_types
from care.abdm.linking import STALE_STEP_SECONDS, link_encounter, patient_abha
from care.abdm.models import (
    AbdmCareContext,
    AbdmConsentArtefact,
    AbdmExchange,
    AbdmFacility,
    AbdmHealthInformationRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuConsentRequest,
)
from care.emr.api.viewsets.base import EMRBaseViewSet
from care.emr.models import Encounter
from care.emr.models.patient import Patient
from care.facility.models.facility import Facility
from care.security.authorization import AuthorizationController
from care.utils.shortcuts import get_object_or_404


def _require_enabled():
    if not settings.ABDM_ENABLED:
        raise NotFound("ABDM is not enabled")


def exchange_row(exchange: AbdmExchange) -> dict:
    return {
        "id": str(exchange.external_id),
        "request_id": exchange.request_id,
        "direction": exchange.direction,
        "path": exchange.path,
        "hip_id": exchange.hip_id,
        "state": exchange.state,
        "http_status": exchange.http_status,
        "error_code": exchange.error_code,
        "error_message": exchange.error_message,
        "headers": exchange.headers,
        "created_date": exchange.created_date,
        "answered_at": exchange.answered_at,
        "answered_by": exchange_row(exchange.answered_by)
        if exchange.answered_by
        else None,
    }


class HipIdSpec(BaseModel):
    hip_id: str = Field(min_length=1, max_length=64)


class AbdmFacilityViewSet(EMRBaseViewSet):
    """The HIP ID a facility publishes records as, and whether ABDM can reach it."""

    def _facility(self):
        _require_enabled()
        facility = get_object_or_404(Facility, external_id=self.kwargs["external_id"])
        if not AuthorizationController.call(
            "can_update_facility_obj", self.request.user, facility
        ):
            raise PermissionDenied("Cannot manage this facility's ABDM settings")
        return facility

    def retrieve(self, request, *args, **kwargs):
        facility = self._facility()
        hip_id = (
            AbdmFacility.objects.filter(facility=facility)
            .values_list("hip_id", flat=True)
            .first()
        )
        return Response({"hip_id": hip_id})

    def update(self, request, *args, **kwargs):
        facility = self._facility()
        data = HipIdSpec(**request.data)
        if (
            AbdmFacility.objects.filter(hip_id=data.hip_id)
            .exclude(facility=facility)
            .exists()
        ):
            raise PermissionDenied("This HIP ID belongs to another facility")
        AbdmFacility.objects.update_or_create(
            facility=facility, defaults={"hip_id": data.hip_id.strip()}
        )
        return Response({"hip_id": data.hip_id.strip()})

    @action(detail=True, methods=["GET"])
    def readiness(self, request, *args, **kwargs):
        facility = self._facility()
        hip_id = (
            AbdmFacility.objects.filter(facility=facility)
            .values_list("hip_id", flat=True)
            .first()
        )
        checks = {
            "hip_id": hip_id,
            "bridge_url": None,
            "hip_registered": False,
            "hiu_registered": False,
            # Where providers will push records this facility requests
            "callback_base_url": settings.ABDM_CALLBACK_BASE_URL or None,
        }
        try:
            bridge = _send(
                "GET",
                f"{settings.ABDM_GATEWAY_URL.rstrip('/')}/api/hiecm/gateway/v3/bridge-services",
                headers={
                    "Authorization": f"Bearer {get_gateway_token()}",
                    "X-CM-ID": settings.ABDM_CM_ID,
                },
            ).json()
        except AbdmError as e:
            checks["error"] = f"{e.code or e.status}: {e.message}"
            return Response(checks)
        checks["bridge_url"] = (bridge.get("bridge") or {}).get("url")
        checks["hip_registered"] = any(
            service.get("id") == hip_id and "HIP" in (service.get("types") or [])
            for service in bridge.get("services") or []
        )
        checks["hiu_registered"] = any(
            service.get("id") == hip_id and "HIU" in (service.get("types") or [])
            for service in bridge.get("services") or []
        )
        return Response(checks)


class AbdmCareContextViewSet(EMRBaseViewSet):
    """Where an encounter's ABDM link has got to, read from the record."""

    def _encounter(self):
        _require_enabled()
        encounter = get_object_or_404(
            Encounter.objects.select_related("patient", "facility"),
            external_id=self.kwargs["external_id"],
        )
        if not AuthorizationController.call(
            "can_view_clinical_data", self.request.user, encounter.patient
        ):
            raise PermissionDenied("Cannot view this encounter")
        return encounter

    def retrieve(self, request, *args, **kwargs):
        encounter = self._encounter()
        care_context = AbdmCareContext.objects.filter(encounter=encounter).first()
        if not care_context:
            return Response({"status": None})
        exchanges = care_context.exchanges.filter(direction="outbound").select_related(
            "answered_by"
        )
        return Response(
            {
                "status": care_context.status,
                "reference_number": care_context.reference_number,
                "display": care_context.display,
                "abha_address": care_context.abha_address,
                "hi_types": care_context.hi_types,
                "linked_hi_types": care_context.linked_hi_types,
                "linked_at": care_context.linked_at,
                "error_code": care_context.error_code,
                "error_message": care_context.error_message,
                "modified_date": care_context.modified_date,
                "stale_after_seconds": STALE_STEP_SECONDS,
                "exchanges": [exchange_row(e) for e in exchanges[:20]],
            }
        )

    @action(detail=True, methods=["GET"])
    def preview(self, request, *args, **kwargs):
        """The records a consent for this visit would send, built from it now."""
        encounter = self._encounter()
        care_context = AbdmCareContext.objects.filter(encounter=encounter).first()
        hip_id = care_context.hip_id if care_context else ""
        records = []
        for hi_type in available_hi_types(encounter):
            bundle = BUILDERS[hi_type](encounter, hip_id)
            if bundle:
                records.append({"hi_type": hi_type, "bundle": bundle})
        return Response({"records": records})

    @action(detail=True, methods=["POST"])
    def link(self, request, *args, **kwargs):
        encounter = self._encounter()
        if not AuthorizationController.call(
            "can_write_patient_obj", request.user, encounter.patient
        ):
            raise PermissionDenied("Cannot link this encounter")
        link_encounter(encounter)
        return self.retrieve(request, *args, **kwargs)


class AbdmExchangeViewSet(EMRBaseViewSet):
    """The integrator's view: every call and callback, joined by request id."""

    def list(self, request, *args, **kwargs):
        _require_enabled()
        if not request.user.is_superuser:
            raise PermissionDenied("Only administrators can view ABDM exchanges")
        queryset = AbdmExchange.objects.select_related("answered_by").filter(
            # A callback is shown inside the call it answers
            answers__isnull=True,
        )
        if direction := request.query_params.get("direction"):
            queryset = queryset.filter(direction=direction)
        if state := request.query_params.get("state"):
            queryset = queryset.filter(state=state)
        if search := request.query_params.get("search"):
            queryset = queryset.filter(path__icontains=search) | queryset.filter(
                request_id=search
            )
        limit = min(int(request.query_params.get("limit", 50)), 200)
        offset = int(request.query_params.get("offset", 0))
        return Response(
            {
                "count": queryset.count(),
                "results": [exchange_row(e) for e in queryset[offset : offset + limit]],
            }
        )


def _consent_row(consent: AbdmConsentArtefact) -> dict:
    detail = consent.detail or {}
    return {
        "consent_id": consent.consent_id,
        "status": consent.status,
        "hip_id": consent.hip_id,
        "requester": (detail.get("hiu") or {}).get("name")
        or (detail.get("requester") or {}).get("name"),
        "purpose": (detail.get("purpose") or {}).get("text"),
        "hi_types": consent.hi_types,
        "care_context_references": [
            c.get("careContextReference") for c in consent.care_contexts
        ],
        "date_from": consent.date_from,
        "date_to": consent.date_to,
        "data_erase_at": consent.data_erase_at,
        "created_date": consent.created_date,
        "modified_date": consent.modified_date,
        "transfers": [
            {
                "transaction_id": transfer.transaction_id,
                "session_status": transfer.session_status,
                "status_responses": transfer.status_responses,
                "error_message": transfer.error_message,
                "created_date": transfer.created_date,
                "record_count": len(transfer.shared),
            }
            for transfer in AbdmHealthInformationRequest.objects.filter(
                consent=consent
            ).order_by("-created_date")
        ],
    }


class AbdmPatientViewSet(EMRBaseViewSet):
    """Everything this instance has published to ABDM for one patient."""

    def _patient(self):
        _require_enabled()
        patient = get_object_or_404(Patient, external_id=self.kwargs["external_id"])
        if not AuthorizationController.call(
            "can_view_clinical_data", self.request.user, patient
        ):
            raise PermissionDenied("Cannot view this patient")
        return patient

    @staticmethod
    def _consents(patient, abha_address):
        consent_filter = Q(
            care_contexts__contains=[{"patientReference": str(patient.external_id)}]
        )
        if abha_address:
            consent_filter |= Q(abha_address=abha_address)
        return AbdmConsentArtefact.objects.filter(consent_filter)

    @action(
        detail=True,
        methods=["GET"],
        url_path=r"transfer/(?P<transaction_id>[^/]+)",
    )
    def transfer(self, request, *args, **kwargs):
        """The records one transfer sent, exactly as they were built."""
        patient = self._patient()
        _, abha_address = patient_abha(patient)
        transfer = get_object_or_404(
            AbdmHealthInformationRequest.objects.select_related("consent"),
            transaction_id=kwargs["transaction_id"],
            consent__in=self._consents(patient, abha_address),
        )
        displays = dict(
            AbdmCareContext.objects.filter(patient=patient).values_list(
                "reference_number", "display"
            )
        )
        return Response(
            {
                "transaction_id": transfer.transaction_id,
                "session_status": transfer.session_status,
                "created_date": transfer.created_date,
                "requester": _consent_row(transfer.consent)["requester"],
                "records": [
                    {**record, "display": displays[record["care_context_reference"]]}
                    for record in transfer.shared
                    # A consent may span patients; show only this patient's records
                    if record["care_context_reference"] in displays
                ],
            }
        )

    def retrieve(self, request, *args, **kwargs):
        patient = self._patient()
        abha_number, abha_address = patient_abha(patient)
        care_contexts = (
            AbdmCareContext.objects.filter(patient=patient)
            .select_related("encounter__facility")
            .order_by("-created_date")
        )
        consents = self._consents(patient, abha_address).order_by("-created_date")
        return Response(
            {
                "abha_number": abha_number,
                "abha_address": abha_address,
                "care_contexts": [
                    {
                        "encounter": str(c.encounter.external_id),
                        "facility": str(c.encounter.facility.external_id),
                        "facility_name": c.encounter.facility.name,
                        "reference_number": c.reference_number,
                        "display": c.display,
                        "hip_id": c.hip_id,
                        "abha_address": c.abha_address,
                        "status": c.status,
                        "hi_types": c.hi_types,
                        "linked_hi_types": c.linked_hi_types,
                        "linked_at": c.linked_at,
                        "notified_at": c.notified_at,
                        "error_code": c.error_code,
                        "error_message": c.error_message,
                        "modified_date": c.modified_date,
                    }
                    for c in care_contexts
                ],
                "consents": [_consent_row(c) for c in consents],
                "consent_requests": [
                    consent_request_row(c)
                    for c in AbdmHiuConsentRequest.objects.filter(patient=patient)
                    .select_related("facility", "requester")
                    .prefetch_related("artefacts")
                    .order_by("-created_date")
                ],
            }
        )

    @action(
        detail=True,
        methods=["GET"],
        url_path=r"received/(?P<consent_id>[^/]+)",
    )
    def received(self, request, *args, **kwargs):
        """Records other providers sent under one artefact, while it is in force."""
        patient = self._patient()
        artefact = get_object_or_404(
            AbdmHiuConsentArtefact,
            consent_id=kwargs["consent_id"],
            consent_request__patient=patient,
        )
        if artefact.data_erase_at and artefact.data_erase_at <= timezone.now():
            hiu.erase_expired()
        return Response(
            {
                "consent_id": artefact.consent_id,
                "hip_name": artefact.hip_name,
                "data_erase_at": artefact.data_erase_at,
                "records": [
                    {
                        "care_context_reference": record.care_context_reference,
                        "checksum": record.checksum,
                        "bundle": record.bundle,
                        "created_date": record.created_date,
                    }
                    for record in artefact.records.order_by("created_date")
                ],
            }
        )
