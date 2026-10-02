"""Canonical Draft 2020-12 structural schemas with explicit semantic checks."""

import json
from typing import Any

from .models import Asset, Composition, Memory, Persona, Skill
from .tools import tool_schema_definition
from .types import RESERVED
from .validation import DOCUMENT_ADAPTER

MODELS: dict[str, type[Asset]] = {
    "persona": Persona,
    "skill": Skill,
    "memory": Memory,
    "composition": Composition,
}


def json_schema(kind: str | None = None) -> dict[str, Any]:
    """Return a fresh schema; validate_module remains the semantic authority."""
    schema = DOCUMENT_ADAPTER.json_schema() if kind is None else MODELS[kind].model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["x-reliclab-semantic-checks"] = [
        "UTF-8 body byte limit and valid Unicode encoding",
        "portable path policy",
        "reserved IDs in references and root aliases",
        "unique reference IDs per selection slot",
        "finite JSON numbers",
        "strict Python integer representation",
        "name whitespace normalization and tag deduplication",
    ]
    definitions = schema.setdefault("$defs", {})
    nodes = [schema, *definitions.values()]
    for node in nodes:
        properties = node.get("properties", {})
        if "schema_version" in properties:
            properties["id"]["not"] = {"enum": sorted(RESERVED)}
        if node.get("title") == "ModuleSelection":
            node["anyOf"] = [
                {"required": ["persona"], "properties": {"persona": {"type": "string"}}},
                *[
                    {"required": [name], "properties": {name: {"minItems": 1}}}
                    for name in ("skills", "memory")
                ],
            ]
        if node.get("title") == "Memory":
            node["allOf"] = [
                {
                    "if": {"properties": {"source": {"const": "inline"}}},
                    "then": {
                        "required": ["body"],
                        "properties": {
                            "body": {"pattern": r"\S"},
                            "root": {"type": "null"},
                            "path": {"type": "null"},
                        },
                    },
                    "else": {
                        "required": ["root", "path"],
                        "properties": {
                            "root": {"type": "string"},
                            "path": {"type": "string"},
                            "body": {"const": ""},
                        },
                    },
                }
            ]
        if node.get("title") == "ToolRequirement":
            definitions["ToolSchema"] = tool_schema_definition()
            properties["input_schema"] = {
                "allOf": [
                    {"$ref": "#/$defs/ToolSchema"},
                    {"properties": {"type": {"const": "object"}}},
                ]
            }
    return schema


def schema_text(kind: str | None = None) -> str:
    return json.dumps(json_schema(kind), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
