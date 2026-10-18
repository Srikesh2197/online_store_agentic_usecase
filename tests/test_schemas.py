from arl.env.tools import FIND_CUSTOMER_SCHEMA, TOOLS, generate_schema, tool_schemas


def test_hand_written_schema_matches_generated():
    find_customer = next(tool for tool in TOOLS if tool.name == "find_customer")
    assert generate_schema(find_customer) == FIND_CUSTOMER_SCHEMA


def test_one_schema_per_tool():
    assert [s["name"] for s in tool_schemas()] == [tool.name for tool in TOOLS]


def _objects(schema: dict):
    """Every object schema nested inside `schema`."""
    if schema.get("type") == "object":
        yield schema
    for sub in schema.get("properties", {}).values():
        yield from _objects(sub)
    for sub in schema.get("anyOf", []):
        yield from _objects(sub)


def test_schemas_meet_strict_mode_rules():
    for schema in tool_schemas():
        assert schema["type"] == "function"
        assert schema["strict"] is True
        assert len(schema["description"]) > 40
        for obj in _objects(schema["parameters"]):
            assert obj["additionalProperties"] is False
            assert obj["required"] == list(obj["properties"])
            for prop in obj["properties"].values():
                assert "description" in prop
                assert "title" not in prop and "default" not in prop


def test_optional_field_is_nullable_and_required():
    list_orders = next(s for s in tool_schemas() if s["name"] == "list_orders")
    params = list_orders["parameters"]
    assert "limit" in params["required"]
    assert {"type": "null"} in params["properties"]["limit"]["anyOf"]
