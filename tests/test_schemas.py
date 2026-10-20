from arl.env.tools import FIND_CUSTOMER_PARAMETERS, TOOLS, strict_parameters, tool_specs
from arl.llm.openai_adapter import tool_to_wire


def tool_schemas():
    """The OpenAI `tools` array, as Phase 0 sent it."""
    return [tool_to_wire(spec) for spec in tool_specs()]


def test_hand_written_schema_matches_generated():
    find_customer = next(tool for tool in TOOLS if tool.name == "find_customer")
    assert strict_parameters(find_customer) == FIND_CUSTOMER_PARAMETERS


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


# Anthropic's strict mode: same schemas, extra limits.
# https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations
ANTHROPIC_UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                         "multipleOf", "minLength", "maxLength"}


def _nodes(schema: dict):
    yield schema
    for sub in schema.get("properties", {}).values():
        yield from _nodes(sub)
    for sub in schema.get("anyOf", []):
        yield from _nodes(sub)
    if isinstance(schema.get("items"), dict):
        yield from _nodes(schema["items"])


def test_anthropic_wire_shape():
    from arl.llm.anthropic_adapter import tool_to_wire as anthropic_tool

    for spec in tool_specs():
        wire = anthropic_tool(spec)
        assert set(wire) == {"name", "description", "input_schema", "strict"}
        assert wire["input_schema"] is spec.parameters


def test_schemas_meet_anthropic_strict_limits():
    specs = tool_specs()
    assert len(specs) <= 20   # strict tools per request
    union_params = 0
    for spec in specs:
        for node in _nodes(spec.parameters):
            assert not ANTHROPIC_UNSUPPORTED & set(node), (spec.name, node)
        union_params += sum("anyOf" in p for p in spec.parameters["properties"].values())
    assert union_params <= 16


def test_removed_constraints_move_into_the_description():
    create_return = next(s for s in tool_specs() if s.name == "create_return")
    quantity = create_return.parameters["properties"]["quantity"]
    assert quantity == {"type": "integer", "description":
                        "How many of that item are being returned. Must be at least 1."}
