from django_filters import rest_framework as filters
from pydantic import UUID4, BaseModel
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from care.emr.api.viewsets.base import (
    EMRBaseViewSet,
    EMRCreateMixin,
    EMRListMixin,
    EMRModelViewSet,
    EMRRetrieveMixin,
    EMRUpdateMixin,
)
from care.emr.models import (
    Encounter,
    FacilityLocation,
    FacilityLocationEncounter,
    FacilityLocationOrganization,
)
from care.emr.models.organization import FacilityOrganization, FacilityOrganizationUser
from care.emr.resources.facility_organization.spec import FacilityOrganizationReadSpec
from care.emr.resources.location.spec import (
    FacilityLocationListSpec,
    FacilityLocationModeChoices,
    FacilityLocationRetrieveSpec,
    FacilityLocationUpdateSpec,
    FacilityLocationWriteSpec,
)
from care.facility.models import Facility
from care.security.authorization import AuthorizationController


class FacilityLocationFilter(filters.FilterSet):
    parent = filters.UUIDFilter(field_name="parent__external_id")
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")


class FacilityLocationViewSet(EMRModelViewSet):
    database_model = FacilityLocation
    pydantic_model = FacilityLocationWriteSpec
    pydantic_read_model = FacilityLocationListSpec
    pydantic_retrieve_model = FacilityLocationRetrieveSpec
    pydantic_update_model = FacilityLocationUpdateSpec
    filterset_class = FacilityLocationFilter
    filter_backends = [filters.DjangoFilterBackend]

    def get_facility_obj(self):
        return get_object_or_404(
            Facility, external_id=self.kwargs["facility_external_id"]
        )

    def validate_destroy(self, instance):
        # Validate that there is no children if exists
        if FacilityLocation.objects.filter(parent=instance).exists():
            raise ValidationError("Location has active children")
        # TODO Add validation to check if patient association exists

    def validate_data(self, instance, model_obj=None):
        if not model_obj and instance.parent:
            parent = get_object_or_404(FacilityLocation, external_id=instance.parent)
            if parent.facility_id != instance.facility_id:
                raise PermissionDenied("Parent Incompatible with Location")
            if parent.mode == FacilityLocationModeChoices.instance.value:
                raise ValidationError("Instances cannot have children")

    def authorize_create(self, instance):
        facility = self.get_facility_obj()
        if instance.parent:
            parent = get_object_or_404(FacilityLocation, external_id=instance.parent)
        else:
            parent = None
        if not AuthorizationController.call(
            "can_create_facility_location_obj", self.request.user, parent, facility
        ):
            raise PermissionDenied("You do not have permission to create a location")
        if instance.organizations:
            for organization in instance.organizations:
                organization_obj = get_object_or_404(
                    FacilityOrganization, external_id=organization
                )
                self.authorize_organization(facility, organization_obj)

    def authorize_update(self, request_obj, model_instance):
        if not AuthorizationController.call(
            "can_update_facility_location_obj", self.request.user, model_instance
        ):
            raise PermissionDenied("You do not have permission to update this location")

    def authorize_destroy(self, instance):
        self.authorize_update({}, instance)

    def perform_create(self, instance):
        facility = self.get_facility_obj()
        instance.facility = facility
        return super().perform_create(instance)

    def get_queryset(self):
        facility = self.get_facility_obj()
        base_qs = FacilityLocation.objects.filter(facility=facility)
        if "mine" in self.request.GET:
            # Filter based on direct association
            organization_ids = list(
                FacilityOrganizationUser.objects.filter(
                    user=self.request.user, organization__facility=facility
                ).values_list("organization_id", flat=True)
            )
            base_qs = base_qs.filter(
                id__in=FacilityLocationOrganization.objects.filter(
                    organization_id__in=organization_ids
                ).values_list("location_id", flat=True)
            )
        return AuthorizationController.call(
            "get_accessible_facility_locations", base_qs, self.request.user, facility
        )

    @action(detail=True, methods=["GET"])
    def organizations(self, request, *args, **kwargs):
        # AuthZ is controlled from the get_queryset method, no need to repeat
        instance = self.get_object()
        encounter_organizations = FacilityLocationOrganization.objects.filter(
            location=instance
        ).select_related("organization")
        data = [
            FacilityOrganizationReadSpec.serialize(
                encounter_organization.organization
            ).to_json()
            for encounter_organization in encounter_organizations
        ]
        return Response({"results": data})

    class FacilityLocationOrganizationManageSpec(BaseModel):
        organization: UUID4

    def authorize_organization(self, facility, organization):
        if organization.facility.id != facility.id:
            raise PermissionDenied("Organization Incompatible with Location")
        if not AuthorizationController.call(
            "can_manage_facility_organization_obj", self.request.user, organization
        ):
            raise PermissionDenied("You do not have permission to given organizations")

    @action(detail=True, methods=["POST"])
    def organizations_add(self, request, *args, **kwargs):
        instance = self.get_object()
        request_data = self.FacilityLocationOrganizationManageSpec(**request.data)
        organization = get_object_or_404(
            FacilityOrganization, external_id=request_data.organization
        )
        self.authorize_update({}, instance)
        self.authorize_organization(instance.facility, organization)
        location_organization = FacilityLocationOrganization.objects.filter(
            location=instance, organization=organization
        )
        if location_organization.exists():
            raise ValidationError("Organization already exists")
        FacilityLocationOrganization.objects.create(
            location=instance, organization=organization
        )
        return Response(FacilityOrganizationReadSpec.serialize(organization).to_json())

    @action(detail=True, methods=["POST"])
    def organizations_remove(self, request, *args, **kwargs):
        instance = self.get_object()
        # self.authorize_update({}, instance)
        request_data = self.FacilityLocationOrganizationManageSpec(**request.data)
        organization = get_object_or_404(
            FacilityOrganization, external_id=request_data.organization
        )
        self.authorize_update({}, instance)
        self.authorize_organization(instance.facility, organization)
        encounter_organization = FacilityLocationOrganization.objects.filter(
            encounter=instance, organization=organization
        )
        if not encounter_organization.exists():
            raise ValidationError("Organization does not exist")
        FacilityLocationOrganization.objects.filter(
            encounter=instance, organization=organization
        ).delete()
        instance.save()  # Recalculate Metadata
        instance.cascade_changes()  # Recalculate Metadata for children as well.
        return Response({}, status=204)

    class FacilityLocationEncounterAssignSpec(BaseModel):
        encounter: UUID4

    @action(detail=True, methods=["POST"])
    def associate_encounter(self, request, *args, **kwargs):
        instance = self.get_object()
        facility = self.get_facility_obj()
        request_data = self.FacilityLocationEncounterAssignSpec(**request.data)
        encounter = get_object_or_404(Encounter, external_id=request_data.encounter)
        if instance.facility_id != encounter.facility_id:
            raise PermissionDenied("Encounter Incompatible with Location")
        if not AuthorizationController.call(
            "can_list_facility_location_obj", self.request.user, facility, instance
        ):
            raise PermissionDenied("You do not have permission to given location")
        if not AuthorizationController.call(
            "can_update_encounter_obj", self.request.user, encounter
        ):
            raise PermissionDenied("You do not have permission to update encounter")
        # TODO, Association models yet to be built


class FacilityLocationEncounterFilter(filters.FilterSet):
    encounter = filters.UUIDFilter(field_name="encounter__external_id")


class FacilityLocationEncounterViewSet(
    EMRCreateMixin, EMRRetrieveMixin, EMRUpdateMixin, EMRListMixin, EMRBaseViewSet
):
    """
    TODO Authz for encounter creates
    TODO Update encounter model when creates are done
    TODO check for conflicts in datetime
    TODO Add locks when a bed is occupied
    TODO detect end dates added to encounter and remove association with encounter
    TODO encounter lists must also check the location based access now
    """

    database_model = FacilityLocationEncounter
    pydantic_model = None
    pydantic_read_model = None
    pydantic_retrieve_model = None
    pydantic_update_model = None
    filterset_class = FacilityLocationEncounterFilter
    filter_backends = [filters.DjangoFilterBackend]

    def get_facility_obj(self):
        return get_object_or_404(
            Facility, external_id=self.kwargs["facility_external_id"]
        )

    def get_location_obj(self):
        return get_object_or_404(
            FacilityLocation, external_id=self.kwargs["location_external_id"]
        )

    def get_queryset(self):
        location = self.get_location_obj()
        facility = self.get_facility_obj()
        if not AuthorizationController.call(
            "can_list_facility_location_obj", self.request.user, facility, location
        ):
            raise PermissionDenied("You do not have permission to given location")
        return FacilityLocationEncounter.objects.filter(location=location)
