import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from care.emr.resources.charge_item_definition.spec import ChargeItemDefinitionWriteSpec
from care.emr.resources.inventory.product_knowledge.spec import (
    ProductKnowledgeWriteSpec,
)
from care.emr.resources.resource_category.spec import ResourceCategoryWriteSpec

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """ """

    help = "Script to import inventory items."

    def add_arguments(self, parser):
        parser.add_argument("--data_dir", help="Data directory")

    def handle(self, *args, **options):
        super().__init__(*args, **options)
        return
        data_dir = self.data_dir
        print(data_dir)
        # TODO: read all the json files
        return

        resource_category_instances = self.validate_datapoints(
            ResourceCategoryWriteSpec,
            [],  # TODO: replace this
        )
        product_knowledge_instances = self.validate_datapoints(
            ProductKnowledgeWriteSpec,
            [],  # TODO: replace this
        )
        charge_item_definition_instances = self.validate_datapoints(
            ChargeItemDefinitionWriteSpec,
            [],  # TODO: replace this
        )

        with transaction.atomic():
            for instance in resource_category_instances:
                instance.save()
            for instance in product_knowledge_instances:
                instance.save()
            for instance in charge_item_definition_instances:
                instance.save()

    def validate_datapoints(self, spec, datapoints):
        model_instances = []
        for datapoint in datapoints:
            instance = spec.model_validate(datapoint)
            model_instances.append(instance.de_serialize())
        return model_instances
