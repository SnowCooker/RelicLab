"""Export schemas or verify public examples without the future production codec."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from reliclab.schema import RelicError, json_schema, schema_text, validate_module

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("persona", "skill", "memory", "composition")


def example_data(path: Path) -> dict[str, Any]:
    """Read repository-owned fixtures only, not arbitrary user asset files."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Example is missing frontmatter")
    end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    metadata = yaml.safe_load("".join(lines[1:end]))
    if not isinstance(metadata, dict) or "body" in metadata:
        raise ValueError("Example frontmatter must be an object without body")
    return {**metadata, "body": "".join(lines[end + 1 :])}


def verify(root: Path) -> None:
    validators = {kind: Draft202012Validator(json_schema(kind)) for kind in KINDS}
    for validator in validators.values():
        Draft202012Validator.check_schema(validator.schema)
    for kind in KINDS:
        paths = sorted((root / "examples" / kind).glob("*.md"))
        if len(paths) < 3:
            raise ValueError(f"Expected at least three {kind} examples")
        for path in paths:
            data = example_data(path)
            validators[kind].validate(data)
            document = validate_module(data, source=path.name)
            validators[kind].validate(document.model_dump(mode="json"))
    fixtures = sorted((root / "tests/fixtures/invalid").glob("*.json"))
    if not fixtures:
        raise ValueError("Invalid fixtures are missing")
    for path in fixtures:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        try:
            validate_module(fixture["document"])
        except RelicError as error:
            if error.code != "SCHEMA_INVALID":
                raise
        else:
            raise ValueError(f"Expected invalid document: {path.name}")
        structural_valid = Draft202012Validator(json_schema()).is_valid(fixture["document"])
        if structural_valid != fixture["structural_valid"]:
            raise ValueError(f"Unexpected structural validation result: {path.name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    for kind in (*KINDS, None):
        path = ROOT / "schemas" / f"{kind or 'module'}.schema.json"
        expected = schema_text(kind)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                print(f"Schema drift: {path.name}; run python -m scripts.schemas")
                return 1
        else:
            path.parent.mkdir(exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    verify(ROOT)
    print("Schemas, public examples, and invalid fixtures verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
