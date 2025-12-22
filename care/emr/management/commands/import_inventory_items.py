import logging

from django.core.management.base import BaseCommand

from care.emr.resources.resource_category.spec import ResourceCategoryWriteSpec

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """ """

    help = "Script to import inventory items."

    def handle(self, *args, **options):
        super().__init__(*args, **options)
        data_dir = args[1]
        # TODO: read all the json files
        pass

    def validate_data(self, resource_categories: list, product_knowledges: list):
        for resource_category in resource_categories:
            instance = ResourceCategoryWriteSpec.model_validate(resource_category)
            model_instance = instance.de_serialize()
