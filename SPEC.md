# RelicLab Asset Format 1.0

Status: S01 implementation, pre-release. This specification defines data, not an
agent executor. It does not claim compatibility with external `SKILL.md` formats.

## Validation API

```python
from reliclab.schema import RelicError, validate_module

document = validate_module({
    "schema_version": "1.0",
    "kind": "persona",
    "id": "writing-coach",
    "version": "1.0.0",
    "name": "Writing Coach",
    "identity": "A careful editor",
})
assert document.key.id == "writing-coach"
data = document.model_dump(mode="json")
```

Public exports from `reliclab.schema` are `Persona`, `Skill`, `Memory`,
`Composition`, `ModuleDocument` (a discriminated union), `ModuleKey`,
`ModuleId`, `AssetVersion`, `ModuleRef`, `ModuleSelection`, `RenderOptions`,
`ToolRequirement`, `SkillExample`, `Diagnostic`, `RelicError`, `validate_module`,
`json_schema`, and `schema_text`.

`validate_module(data, source=None)` accepts a decoded Python object. The `kind`
field selects the model; unknown fields are forbidden at every model boundary.
String-to-number/boolean conversion is forbidden, as are boolean or floating-point
inputs for integer fields. Numbers must be finite. Optional means a field may be
omitted; only fields explicitly allowing null accept `None`.

Models are frozen against field reassignment. List input is copied to tuples;
mapping and nested JSON input is defensively copied. Mappings remain mutable on
the returned object: these DTOs are not deeply immutable execution snapshots.
Do not mutate a validated mapping and then treat it as validated. Revalidate it
before crossing a trust boundary. `model_construct` and `model_copy(update=...)`
are Pydantic escape hatches, not validation APIs. `validate_module` revalidates
model instances. JSON serialization emits arrays, not Python tuples.

## Document Envelope

Assets are intended to be UTF-8 Markdown files with YAML frontmatter delimited
by `---` on its own line. Metadata and the Markdown body together form the DTO.
The frontmatter must not declare `body`; the codec supplies it from Markdown.

```yaml
---
schema_version: '1.0'
id: writing-coach
kind: persona
version: 1.0.0
name: Writing Coach
identity: A careful editor
---
Separate observations from suggestions.
```

S01 validates decoded DTOs only. The safe production frontmatter parser, source
line mapping, YAML restrictions, and deterministic text serializer belong to
S02. `scripts/schemas.py` reads trusted repository examples for development; it
is not a production parser and must not be used for untrusted assets.

The future codec enforces a 64 KiB frontmatter limit. Models enforce a 1 MiB
UTF-8 body limit now. No filesystem access occurs during schema validation.
Storage identity is `ModuleKey(kind, id, version)`; file naming is
`{kind_directory}/{id}@{version}.md`. Catalog uniqueness is enforced by a future
Vault, not by a single-document validator. Example directories use singular
kind names and are not a production Vault layout contract.

## Common Fields

| Field | Required/default | Constraint |
|---|---|---|
| `schema_version` | Required | Exactly string `1.0` |
| `kind` | Required | `persona`, `skill`, `memory`, or `composition` |
| `id` | Required | ASCII `[a-z][a-z0-9-]{0,63}`; reserved device names rejected |
| `version` | Required | Full SemVer 2.0.0, including optional prerelease/build identifiers |
| `name` | Required | 1-120 input characters, nonblank; surrounding whitespace removed |
| `description` | `""` | At most 2,000 characters |
| `tags` | `[]` | At most 32 input strings, each at most 64 characters; first-occurrence deduplication |
| `author` | `null` | String of at most 120 characters, or null |
| `extensions` | `{}` | String keys starting with `x-`; finite JSON values only |
| `body` | `""`, except Skill | At most 1,048,576 UTF-8 bytes; kind-specific rules below |

Character limits count Unicode code points, not grapheme clusters. Empty tag
strings are allowed by version 1.0. Reserved identifiers include `con`, `prn`,
`aux`, `nul`, `com1` through `com9`, and `lpt1` through `lpt9`. Other Windows
device spellings containing punctuation already fail the ASCII slug rule.
Extensions are data only and grant no tool, import, file, or execution capability.

`schema_version` versions this format; `version` versions the individual asset.
Package versions are independent. A future composition IR will have its own
`ir_version`; no IR type is delivered by S01. Unknown format versions, including
unrecognized minor versions, are rejected rather than silently downgraded.

## Kind-Specific Fields

### Persona

- `identity`: required nonblank string.
- `voice`: string, default empty.
- `values`, `constraints`: string arrays, default empty.
- `extends`: optional `ModuleRef`, default null.
- `body`: optional supplementary instructions.

Only Persona supports `extends`. S01 checks reference syntax, not existence,
inheritance cycles, merging, or version resolution.

### Skill

- `trigger`: string, default empty.
- `tools`: array of `ToolRequirement`, default empty.
- `examples`: array of objects with required string `input` and `output` fields,
  default empty; these are examples, not code to execute.
- `body`: required nonblank instruction text.

### Memory

- `source`: required `inline`, `file`, or `glob`.
- `root`: optional portable identifier naming a host-configured root, default null.
- `path`: optional portable relative path, default null.
- `scope`: `always` or `on-demand`, default `on-demand`.
- `depth`: integer 0 or 1, default 0; booleans are not integers here.

For `inline`, body must be nonblank and root/path must be absent or null.
For `file` and `glob`, root/path are required non-null strings and body must be
exactly empty. Paths use `/`; empty segments, `.`, `..`, backslashes, URI/drive
colons, control characters, Windows-invalid `<>|"`, trailing spaces/dots, and
reserved device basenames (including superscript 1/2/3 COM/LPT variants) are
rejected. `file` additionally rejects `*?[]`;
`glob` permits those pattern characters. Paths cannot choose a new host root.
Validation neither reads files nor establishes a symlink containment guarantee.
Pattern expansion, root resolution, and symlink checks are later responsibilities.

### Composition

- `modules`: required `ModuleSelection` object. `persona` defaults to null;
  `skills` and `memory` default to empty arrays. At least one slot must be nonempty.
- `variables`: string-keyed object, default empty. Values are strings, booleans,
  integers, finite floats, or null; arrays and objects are rejected.
- `render`: required `RenderOptions` object. `target` is required and must be
  `plain`, `openai-chat`, or `anthropic-messages`; `token_budget` defaults to 8000
  and must be an integer from 1 to 1,000,000 inclusive.
- `body`: optional human notes, not instructions injected into model context.

Persona-only, Skill-only, Memory-only, and full combinations are valid, as are
other nonempty subsets. Within each skills/memory slot, duplicate module IDs
are rejected even when selectors differ. The same ID can occur in different
typed slots. Budget fields describe future rendering requests; S01 does not
count tokens, render prompts, or call providers.

## Module References

`ModuleRef` is a string: a portable ID, optionally followed by `@selector`.
Supported selectors are a major (`@1`), major/minor (`@1.2`), full SemVer
(`@1.2.3`, including prerelease/build metadata), or caret plus full SemVer
(`@^1.2.0`, including prerelease/build metadata). Numeric identifiers have no
leading zeroes. Whitespace, tilde, comparisons, stars, empty selectors, and
arbitrary labels such as `latest` are rejected.

Version resolution is not implemented in S01. A future resolver will choose the
highest stable version for a bare ID, normally exclude prereleases from ranges,
and implement SemVer caret behavior, including the narrower `^0.2.3` range.
S01 uses the `semver` library for full-version validation rather than implementing
version ordering itself.

## Tool Schema Subset

`ToolRequirement` requires `name`, `description`, and `input_schema`. Names match
`[a-z][a-z0-9_]{0,63}`. Descriptions are strings. Input schemas use a small
Draft 2020-12 subset with an object at the root:

| Keyword | Supported value |
|---|---|
| `type` | Required single `object`, `array`, `string`, `integer`, `number`, `boolean`, or `null` |
| `description` | Optional string on any schema node |
| `properties` | Optional mapping to recursively supported schemas; object nodes only |
| `required` | Optional array of unique strings; object nodes only |
| `additionalProperties` | Optional boolean; object nodes only |
| `items` | Required supported schema on array nodes; forbidden on other types |

Every other keyword is rejected, including `$ref`, `$defs`, `$schema`, `format`,
`enum`, `default`, combinators, and bounds. Boolean schemas and type arrays are
not supported. Missing `additionalProperties` follows standard JSON Schema
semantics (additional properties allowed). `required` names need not appear in
`properties`, as allowed by JSON Schema; authors should avoid unsatisfiable
combinations with `additionalProperties: false`.

The same recursive subset definition drives model validation and generated JSON
Schema. `jsonschema` validates the subset and its Draft 2020-12 conformance.
Input references are never resolved, and no Python object is imported or tool
executed from a declaration. Runtime registration and schema compatibility are
future features, not permissions granted by this document.

## Structural and Semantic Validation

The canonical exported schemas are in `schemas/*.schema.json`. Use
`json_schema(kind=None)` to obtain a fresh dictionary or `schema_text(kind=None)`
for deterministic sorted-key JSON with a final LF. A null kind returns the
discriminated union. Direct Pydantic `model_json_schema()` output is not the
canonical export: the export adds cross-field conditions and the tool subset.

Draft 2020-12 validates shapes, primitive types, field bounds, allowed fields,
SemVer/reference syntax, nonempty selections, Memory source conflicts, and the
tool subset. The standard does not express every RelicLab rule. Consumers must
also call `validate_module` (or implement equivalent semantic checks):

- UTF-8 byte limits and valid Unicode body encoding.
- Portable path policy, reserved IDs inside references and root aliases.
- Unique module IDs across references with different selectors.
- Finite numbers and strict Python integer representation: JSON Schema treats
  `1.0` as an integer mathematically, but Python integer fields reject floats.
- Normalization of name whitespace and tag duplicates, which schemas do not do.

`x-reliclab-semantic-checks` documents these requirements; it is an annotation,
not an executable JSON Schema keyword. Invalid fixtures explicitly record whether
structural validation alone accepts them. Passing a structural schema must never
be presented as complete asset acceptance.

## Diagnostics

`validate_module` raises `RelicError` with code `SCHEMA_INVALID`, an English
message, tuple field `location`, tuple `details` of `Diagnostic`, and
`retryable=False`. Diagnostic fields are severity, code, message, source, and
location. Locations contain field names/array indices, never fabricated lines.
Cross-field failures may be located at the containing object or document root.
Only decoded field locations are available before S02.

Messages omit raw input values and validator context. The optional source is a
caller-provided label; do not place secrets in source labels or field names.
Direct Pydantic constructors raise native `ValidationError`, which can include
input values; use the public wrapper for user-facing failures. Domain codes also
reserve `PARSE_ERROR`, `SOURCE_CHANGED`, `NOT_FOUND`, `VERSION_CONFLICT`,
`DEPENDENCY_CYCLE`, `PATH_DENIED`, `CONTEXT_OVERFLOW`, and `IO_ERROR` for later stages.

## Reproducibility

```sh
uv sync --all-packages --all-extras --dev --locked
uv run --no-sync python -m scripts.schemas --check
uv run --no-sync python scripts/check.py --stage S01 --offline
uv run --no-sync python scripts/check.py --all --offline
uv run --no-sync python scripts/check.py --packaging
```

After deliberate model changes, regenerate with `python -m scripts.schemas` and
review the schema diff. Contract tests reject schema drift and validate all
examples before and after model normalization. The examples contain at least
three assets per kind, all four primary composition modes, and Chinese body text.
