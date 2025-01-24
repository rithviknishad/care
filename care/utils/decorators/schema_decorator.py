from drf_spectacular.utils import extend_schema, extend_schema_view


def generate_swagger_schema_decorator(cls):
    schema_dict = {}
    for name in ["create", "update", "list", "retrieve"]:
        if name == "create":
            schema_dict["create"] = extend_schema(
                request=cls.pydantic_model,
                responses={200: cls.pydantic_read_model or cls.pydantic_model},
            )
        elif name == "update":
            schema_dict["update"] = extend_schema(
                request=cls.pydantic_retrieve_model
                or cls.pydantic_read_model
                or cls.pydantic_model,
                responses={200: cls.pydantic_read_model or cls.pydantic_model},
            )
        elif name in ["list", "retrieve"]:
            schema_dict[name] = extend_schema(
                responses={200: cls.pydantic_read_model or cls.pydantic_model}
            )

    return extend_schema_view(**schema_dict)(cls)
