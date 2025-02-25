from enum import Enum

from pydantic import UUID4, field_validator

from care.emr.models import MetaArtifact
from care.emr.resources.base import EMRResource


class MetaArtifactAssociatingTypeChoices(str, Enum):
    patient = "patient"
    encounter = "encounter"


class MetaArtifactObjectTypeChoices(str, Enum):
    excalidraw = "excalidraw"


class MetaArtifactBaseSpec(EMRResource):
    __model__ = MetaArtifact

    id: UUID4 | None = None
    object_value: dict | list | None = None


class MetaArtifactUpdateSpec(MetaArtifactBaseSpec):
    pass


class MetaArtifactListSpec(MetaArtifactBaseSpec):
    associating_type: MetaArtifactAssociatingTypeChoices
    associating_id: UUID4
    object_type: MetaArtifactObjectTypeChoices
    name: str


class MetaArtifactRetrieveSpec(MetaArtifactBaseSpec):
    associating_type: MetaArtifactAssociatingTypeChoices
    associating_id: UUID4
    object_type: MetaArtifactObjectTypeChoices
    name: str


class MetaArtifactCreateSpec(MetaArtifactBaseSpec):
    associating_type: MetaArtifactAssociatingTypeChoices
    associating_id: UUID4
    object_type: MetaArtifactObjectTypeChoices
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str):
        if not name.strip():
            raise ValueError("Name cannot be empty")
        return name

    def perform_extra_deserialization(self, is_update, obj):
        obj.associating_external_id = self.associating_id
