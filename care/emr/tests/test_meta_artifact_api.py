from django.urls import reverse
from rest_framework import status

from care.security.permissions.encounter import EncounterPermissions
from care.security.permissions.patient import PatientPermissions
from care.utils.tests.base import CareAPITestBase


class TestMetaArtifactViewSet(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.facility = self.create_facility(user=self.user)
        self.patient = self.create_patient()
        self.organization = self.create_facility_organization(facility=self.facility)
        self.encounter = self.create_encounter(
            patient=self.patient, facility=self.facility, organization=self.organization
        )

        self.client.force_authenticate(user=self.user)
        self.base_url = reverse(
            "meta_artifacts-list",
        )

    def generate_create_data(self, **kwargs):
        return {
            "associating_type": "patient",
            "associating_id": self.patient.external_id,
            "name": "Test Meta Artifact",
            "object_type": "excalidraw",
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
            **kwargs,
        }

    def create_meta_artifact(self, **kwargs):
        from care.emr.models import MetaArtifact

        return MetaArtifact.objects.create(
            associating_type="patient",
            name="Test Meta Artifact",
            object_type="excalidraw",
            associating_external_id=self.patient.external_id,
            object_value={
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
            **kwargs,
        )

    def create_meta_artifact_encounter(self, **kwargs):
        from care.emr.models import MetaArtifact

        return MetaArtifact.objects.create(
            associating_type="encounter",
            name="Test Meta Artifact",
            object_type="excalidraw",
            associating_external_id=self.encounter.external_id,
            object_value={
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
            **kwargs,
        )

    def _get_meta_artifact_url(self, meta_artifact_id):
        """Helper to get the detail URL for a specific meta-artifact."""
        return reverse(
            "meta_artifacts-detail",
            kwargs={
                "external_id": meta_artifact_id,
            },
        )

    # LIST TESTS
    def test_list_permission_associated_to_patient(self):
        """Users with can_view_clinical_data permission can view clinical data"""
        permissions = [PatientPermissions.can_view_clinical_data.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        response = self.client.get(
            self.base_url,
            data={
                "associating_type": "patient",
                "associating_id": self.patient.external_id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_permission_associated_to_encounter(self):
        """Users with can_view_clinical_data permission can view clinical data"""
        permissions = [PatientPermissions.can_view_clinical_data.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        response = self.client.get(
            self.base_url,
            data={
                "associating_type": "encounter",
                "associating_id": self.encounter.external_id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # def test_list_meta_artifact_object_creation(self):
    #     """Users with can_view_clinical_data permission can view clinical data"""
    #     permissions = [PatientPermissions.can_view_clinical_data.name]
    #     role = self.create_role_with_permissions(permissions)
    #     self.attach_role_facility_organization_user(self.organization, self.user, role)

    #     create_data = self.create_meta_artifact()
    #     response = self.client.get(
    #         self.base_url,
    #         data={
    #             "associating_type": "patient",
    #             "associating_id": self.patient.external_id,
    #         },
    #     )

    #     self.assertContains(
    #         response,
    #         status_code=200,
    #         text=create_data.external_id,
    #     )
    #     self.assertEqual(response.status_code, status.HTTP_200_OK)

    # def test_list_meta_artifact_with_object_type(self):
    #     """Users with can_view_clinical_data permission can view clinical data"""
    #     permissions = [PatientPermissions.can_view_clinical_data.name]
    #     role = self.create_role_with_permissions(permissions)
    #     self.attach_role_facility_organization_user(self.organization, self.user, role)

    #     create_data_with_object_type = self.create_meta_artifact(
    #         object_type="excalidraw"
    #     )
    #     create_data_without_object_type = self.create_meta_artifact(object_type="")
    #     response = self.client.get(
    #         self.base_url,
    #         data={
    #             "associating_type": "patient",
    #             "associating_id": self.patient.external_id,
    #         },
    #     )

    #     self.assertContains(
    #         response,
    #         status_code=200,
    #         text=create_data.external_id,
    #     )
    #     self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_meta_artifact_without_permissions(self):
        """Users without can_view_clinical_data permission cannot view clinical data"""
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # CREATE TESTS
    def test_create_meta_artifact_permission_associated_to_patient(self):
        """Users with can_write_patient_obj permission can create meta artifact"""
        permissions = [PatientPermissions.can_write_patient.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        create_data = self.generate_create_data()
        response = self.client.post(
            self.base_url,
            create_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_meta_artifact_without_object_value(self):
        """Users with cannot create meta artifact without object_value"""
        permissions = [PatientPermissions.can_write_patient.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        response = self.client.post(
            self.base_url,
            data={
                "associating_type": "patient",
                "associating_id": self.patient.external_id,
                "name": "Test Meta Artifact",
                "object_type": "excalidraw",
            },
            format="json",
        )
        self.assertContains(response, status_code=400, text="object_value")
        self.assertContains(response, status_code=400, text="Field required")

    def test_create_meta_artifact_without_name(self):
        """Users with cannot create meta artifact without name"""
        permissions = [PatientPermissions.can_write_patient.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        create_data = self.generate_create_data(
            name="",
        )
        response = self.client.post(
            self.base_url,
            create_data,
            format="json",
        )

        self.assertContains(response, status_code=400, text="Name cannot be empty")

    def test_create_meta_artifact_permission_associated_to_encounter(self):
        """Users with can_write_patient_obj permission can create meta artifact"""
        permissions = [EncounterPermissions.can_write_encounter.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        create_data = self.generate_create_data(
            associating_type="encounter", associating_id=self.encounter.external_id
        )
        response = self.client.post(
            self.base_url,
            create_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_meta_artifact_without_permission(self):
        """Users without can_write_patient_obj permission cannot create meta artifact"""
        create_data = self.generate_create_data()
        response = self.client.post(
            self.base_url,
            create_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # UPDATE TESTS
    def test_update_meta_artifact_permission_associated_to_patient(self):
        """Users with can_write_patient_obj and can_view_clinical_data permission can update meta artifact"""
        permissions = [
            PatientPermissions.can_write_patient.name,
            PatientPermissions.can_view_clinical_data.name,
        ]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        create_meta_artifact_object = self.create_meta_artifact()
        update_data = {
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }
        update_url = self._get_meta_artifact_url(
            create_meta_artifact_object.external_id
        )
        response = self.client.put(
            update_url,
            update_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_meta_artifact_permission_associated_to_encounter(self):
        """Users with can_write_patient_obj and can_view_clinical_data permission can update meta artifact"""
        permissions = [
            EncounterPermissions.can_write_encounter.name,
            PatientPermissions.can_view_clinical_data.name,
        ]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        create_meta_artifact_object = self.create_meta_artifact_encounter()
        update_data = {
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }
        update_url = self._get_meta_artifact_url(
            create_meta_artifact_object.external_id
        )
        response = self.client.put(
            update_url,
            update_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_meta_artifact_without_permission(self):
        """Users without can_write_patient_obj permission cannot update meta artifact"""
        create_meta_artifact_object = self.create_meta_artifact()
        update_data = {
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }
        update_url = self._get_meta_artifact_url(
            create_meta_artifact_object.external_id
        )
        response = self.client.put(
            update_url,
            update_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # RETRIEVE TESTS
    def test_retrieve_meta_artifact_permission_associated_to_patient(self):
        """Users with can_view_clinical_data permission can view clinical data"""
        permissions = [PatientPermissions.can_view_clinical_data.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        create_meta_artifact_object = self.create_meta_artifact()
        retrieve_url = self._get_meta_artifact_url(
            create_meta_artifact_object.external_id
        )
        response = self.client.get(retrieve_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # def test_retrieve_meta_artifact_permission_associated_to_encounter(self):
    #     """Users with can_view_clinical_data permission can view clinical data"""
    #     permissions = [PatientPermissions.can_view_clinical_data]
    #     role = self.create_role_with_permissions(permissions)
    #     self.attach_role_facility_organization_user(self.organization, self.user, role)

    #     create_meta_artifact_object = self.create_meta_artifact_encounter()
    #     retrieve_url = self._get_meta_artifact_url(
    #         create_meta_artifact_object.external_id
    #     )
    #     response = self.client.get(retrieve_url)

    #     self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_meta_artifact_without_permission(self):
        create_meta_artifact_object = self.create_meta_artifact()
        retrieve_url = self._get_meta_artifact_url(
            create_meta_artifact_object.external_id
        )
        response = self.client.get(retrieve_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # UPSERT TEST
    def test_upsert_meta_artifact_permission_associated_to_patient(self):
        """Users with can_write_patient_obj permission can upsert meta artifact"""
        permissions = [PatientPermissions.can_write_patient.name]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        created_data = self.create_meta_artifact()
        update_data = {
            "id": created_data.external_id,
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }

        response = self.client.post(
            reverse(
                "meta_artifacts-upsert",
            ),
            {"datapoints": [self.generate_create_data(), update_data]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_upsert_meta_artifact_permission_associated_to_encounter(self):
        """Users with can_write_patient_obj permission can upsert meta artifact"""
        permissions = [
            EncounterPermissions.can_write_encounter.name,
        ]
        role = self.create_role_with_permissions(permissions)
        self.attach_role_facility_organization_user(self.organization, self.user, role)

        created_data = self.create_meta_artifact_encounter()
        update_data = {
            "id": created_data.external_id,
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }

        response = self.client.post(
            reverse(
                "meta_artifacts-upsert",
            ),
            {
                "datapoints": [
                    self.generate_create_data(
                        associating_type="encounter",
                        associating_id=self.encounter.external_id,
                    ),
                    update_data,
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_upsert_meta_artifact_without_permission(self):
        created_data = self.create_meta_artifact()
        update_data = {
            "id": created_data.external_id,
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }

        response = self.client.post(
            reverse(
                "meta_artifacts-upsert",
            ),
            {"datapoints": [self.generate_create_data(), update_data]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upsert_meta_artifact_cannot_view_object(self):
        """Users without can_view_clinical_data permission cannot view clinical data"""
        created_data = self.create_meta_artifact()
        update_data = {
            "id": created_data.external_id,
            "object_value": {
                "elements": [
                    {
                        "type": "rectangle",
                        "x": 10,
                        "y": 10,
                        "width": 100,
                        "height": 100,
                        "fillColor": "#ffffff",
                    }
                ]
            },
        }

        response = self.client.post(
            reverse(
                "meta_artifacts-upsert",
            ),
            {"datapoints": [self.generate_create_data(), update_data]},
            format="json",
        )
        self.assertContains(response, status_code=400, text="Cannot view object")
