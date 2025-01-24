from drf_spectacular.utils import extend_schema, extend_schema_view


def generate_swagger_schema_decorator(cls):
    actions = {
        "create": {
            "request": cls.pydantic_model,
            "responses": {200: cls.pydantic_read_model or cls.pydantic_model},
        },
        "update": {
            "request": cls.pydantic_retrieve_model
            or cls.pydantic_read_model
            or cls.pydantic_model,
            "responses": {200: cls.pydantic_read_model or cls.pydantic_model},
        },
        "list": {"responses": {200: cls.pydantic_read_model or cls.pydantic_model}},
        "retrieve": {"responses": {200: cls.pydantic_read_model or cls.pydantic_model}},
    }

    schema_dict = {
        name: extend_schema(**params)
        for name, params in actions.items()
        if hasattr(cls, name) and callable(getattr(cls, name))
    }

    return extend_schema_view(**schema_dict)(cls)
