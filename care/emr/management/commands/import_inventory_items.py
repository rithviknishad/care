import json
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
        parser.add_argument(
            "source_dir",
            type=str,
            help="Directory which contains all the transformed data JSONs",
        )

    def handle(self, *args, **options):
        source_dir = options["source_dir"]

        with open(source_dir + "/resource_category.json") as f:
            resource_category_datapoints = json.load(f)
        with open(source_dir + "/product_knowledge.json") as f:
            product_knowledge_datapoints = json.load(f)
        with open(source_dir + "/charge_item_definition.json") as f:
            charge_item_definition_datapoints = json.load(f)
        with open(source_dir + "/product.json") as f:
            inventory_item_datapoints = json.load(f)

        resource_category_instances = self.validate_datapoints(
            ResourceCategoryWriteSpec,
            resource_category_datapoints,
        )
        product_knowledge_instances = self.validate_datapoints(
            ProductKnowledgeWriteSpec,
            product_knowledge_datapoints,
        )
        charge_item_definition_instances = self.validate_datapoints(
            ChargeItemDefinitionWriteSpec,
            charge_item_definition_datapoints,
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
