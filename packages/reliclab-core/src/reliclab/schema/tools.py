"""Offline validation of a deliberately small tool JSON Schema vocabulary."""

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import JsonValue


def tool_schema_definition() -> dict[str, Any]:
    """Return the recursive subset definition used by both validation paths."""
    return {
        "type": "object",
        "required": ["type"],
        "additionalProperties": False,
        "properties": {
            "type": {"enum": ["object", "array", "string", "integer", "number", "boolean", "null"]},
            "description": {"type": "string"},
            "properties": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/ToolSchema"},
            },
            "required": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            "additionalProperties": {"type": "boolean"},
            "items": {"$ref": "#/$defs/ToolSchema"},
        },
        "allOf": [
            {
                "if": {"properties": {"type": {"const": "object"}}},
                "then": {"not": {"required": ["items"]}},
                "else": {
                    "not": {
                        "anyOf": [
                            {"required": [key]}
                            for key in ("properties", "required", "additionalProperties")
                        ]
                    }
                },
            },
            {
                "if": {"properties": {"type": {"const": "array"}}},
                "then": {"required": ["items"]},
                "else": {"not": {"required": ["items"]}},
            },
        ],
    }


TOOL_META = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {"ToolSchema": tool_schema_definition()},
    "allOf": [{"$ref": "#/$defs/ToolSchema"}, {"properties": {"type": {"const": "object"}}}],
}
TOOL_VALIDATOR = Draft202012Validator(TOOL_META)


def validate_tool_schema(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if not TOOL_VALIDATOR.is_valid(value):
        raise ValueError("Use the supported Draft 2020-12 tool schema subset; see SPEC.md")
    # No input $ref is accepted, so this never resolves files or network resources.
    Draft202012Validator.check_schema(value)
    return deepcopy(value)
