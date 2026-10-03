"""Small validated assets shared by storage tests and process workers."""

from typing import Any

from reliclab.schema import ModuleDocument, validate_module


def asset(kind: str = "persona", **changes: Any) -> ModuleDocument:
    required: dict[str, dict[str, Any]] = {
        "persona": {"identity": "Editor"},
        "skill": {"body": "Review the changes.\n"},
        "memory": {"source": "inline", "body": "Project notes.\n"},
        "composition": {"modules": {"skills": ["sample"]}, "render": {"target": "plain"}},
    }
    return validate_module(
        {
            "schema_version": "1.0",
            "id": "sample",
            "kind": kind,
            "version": "1.0.0",
            "name": "Sample",
            **required[kind],
            **changes,
        }
    )
