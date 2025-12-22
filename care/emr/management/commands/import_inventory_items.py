import json
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from care.emr.models import (
    ResourceCategory,
    ProductKnowledge,
    ChargeItemDefinition,
    Product,
    DeliveryOrder,
)
from care.emr.resources.charge_item_definition.spec import ChargeItemDefinitionWriteSpec
from care.emr.resources.inventory.inventory_item.create_inventory_item import (
    create_inventory_item,
)
from care.emr.resources.inventory.inventory_item.sync_inventory_item import (
    sync_inventory_item,
)
from care.emr.resources.inventory.product.spec import ProductWriteSpec
from care.emr.resources.inventory.product_knowledge.spec import (
    ProductKnowledgeWriteSpec,
)
from care.emr.resources.inventory.supply_delivery.delivery_order import (
    SupplyDeliveryOrderWriteSpec,
    SupplyDeliveryOrderStatusOptions,
)
from care.emr.resources.inventory.supply_delivery.spec import SupplyDeliveryWriteSpec
from care.emr.resources.resource_category.spec import ResourceCategoryWriteSpec
from care.facility.models import Facility
from care.utils.shortcuts import get_object_or_404

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

        logger.info("Importing inventory items from %s", source_dir)
        with transaction.atomic():
            with open(source_dir + "/resource-categories.json") as f:
                logger.info("Importing resource categories")
                self.save_resource_categories(json.load(f))
                logger.info("Resource categories imported successfully")

            with open(source_dir + "/product-knowledges.json") as f:
                logger.info("Importing product knowledges")
                self.save_product_knowledges(json.load(f))
                logger.info("Product knowledges imported successfully")

            with open(source_dir + "/charge-item-definitions.json") as f:
                logger.info("Importing charge item definitions")
                self.save_charge_item_definitions(json.load(f))
                logger.info("Charge item definitions imported successfully")

            with open(source_dir + "/products.json") as f:
                logger.info("Importing products")
                self.save_products(json.load(f))
                logger.info("Products imported successfully")

            with open(source_dir + "/delivery-orders.json") as f:
                logger.info("Importing delivery orders")
                orders = self.save_delivery_orders(json.load(f))
                logger.info("Delivery orders imported successfully")

            with open(source_dir + "/supply-deliveries.json") as f:
                logger.info("Importing supply deliveries")
                self.save_supply_deliveries(json.load(f))
                logger.info("Supply deliveries imported successfully")

            logger.info("Completing all pending delivery orders")
            self.complete_all_delivery_orders(orders)
            logger.info("All pending delivery orders completed successfully")

    def save_resource_categories(self, datapoints: list):
        bulk = []
        for datapoint in datapoints:
            facility_external_id = datapoint.pop("$facility")
            validated = ResourceCategoryWriteSpec.model_validate(datapoint)
            instance = validated.de_serialize()
            instance.facility = get_object_or_404(
                Facility, external_id=facility_external_id
            )
            instance.slug = ResourceCategory.calculate_slug_from_facility(
                instance.facility.external_id, instance.slug
            )
            bulk.append(instance)
        ResourceCategory.objects.bulk_create(bulk, batch_size=500)

    def save_product_knowledges(self, datapoints: list):
        bulk = []
        for datapoint in datapoints:
            validated = ProductKnowledgeWriteSpec.model_validate(datapoint)
            instance = validated.de_serialize()
            if instance.facility:
                instance.slug = ProductKnowledge.calculate_slug_from_facility(
                    instance.facility.external_id, instance.slug
                )
            else:
                instance.slug = ProductKnowledge.calculate_slug_from_instance(
                    instance.slug
                )
            bulk.append(instance)
        ProductKnowledge.objects.bulk_create(bulk, batch_size=500)

    def save_charge_item_definitions(self, datapoints: list):
        bulk = []
        for datapoint in datapoints:
            facility_external_id = datapoint.pop("$facility")
            validated = ChargeItemDefinitionWriteSpec.model_validate(datapoint)
            instance = validated.de_serialize()
            instance.facility = get_object_or_404(
                Facility, external_id=facility_external_id
            )
            instance.slug = ChargeItemDefinition.calculate_slug_from_facility(
                instance.facility.external_id, instance.slug
            )
            bulk.append(instance)
        ChargeItemDefinition.objects.bulk_create(bulk, batch_size=500)

    def save_products(self, datapoints: list):
        bulk = []
        for datapoint in datapoints:
            facility_external_id = datapoint.pop("$facility")
            validated = ProductWriteSpec.model_validate(datapoint)
            instance = validated.de_serialize()
            instance.facility = get_object_or_404(
                Facility, external_id=facility_external_id
            )
            bulk.append(instance)
        Product.objects.bulk_create(bulk, batch_size=500)

    def save_delivery_orders(self, datapoints: list):
        bulk = []
        for datapoint in datapoints:
            validated = SupplyDeliveryOrderWriteSpec.model_validate(datapoint)
            instance = validated.de_serialize()
            bulk.append(instance)
        DeliveryOrder.objects.bulk_create(bulk, batch_size=500)
        return bulk

    def save_supply_deliveries(self, datapoints: list[dict]):
        for datapoint in datapoints:
            product = get_object_or_404(
                Product,
                product_knowledge__slug=datapoint.pop(
                    "$supplied_item__product_knowledge"
                ),
                charge_item_definition__slug=datapoint.pop(
                    "$supplied_item__charge_item_definition"
                ),
            )
            order = DeliveryOrder.objects.filter(
                destination__external_id=datapoint.pop("$order__destination"),
                status="pending",
            ).first()
            datapoint["supplied_item"] = product.external_id
            datapoint["order"] = order.external_id
            validated = SupplyDeliveryWriteSpec.model_validate(datapoint)
            instance = validated.de_serialize()
            if instance.supplied_item:
                instance.supplied_inventory_item = create_inventory_item(
                    instance.supplied_item, instance.order.destination
                )
            instance.save()
            if instance.supplied_inventory_item:
                sync_inventory_item(
                    location=instance.order.destination,
                    product=instance.supplied_inventory_item.product,
                )
            if instance.order.origin:
                sync_inventory_item(inventory_item=instance.supplied_inventory_item)

    def complete_all_delivery_orders(self, orders: list[DeliveryOrder]):
        for order in orders:
            order.status = SupplyDeliveryOrderStatusOptions.completed
            order.save()
