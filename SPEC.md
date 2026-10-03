# RelicLab Asset Format 1.0

Status: S01/S02 implementation with S03 storage integration, pre-release. This specification defines data, not an
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

`validate_module(data, source=None, max_body_bytes=1048576)` accepts a decoded Python object.
The optional positive integer body limit is host configuration, never asset metadata. The `kind`
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

S02 provides the production codec below. `scripts/schemas.py` independently reads
trusted repository examples to cross-check schemas; it is not a production parser
and must not be used for untrusted assets.

The codec defaults to 64 KiB frontmatter and 1 MiB body limits. Direct model
construction retains the 1 MiB body default. No filesystem access occurs during
validation, parsing, or serialization.
Storage identity is `ModuleKey(kind, id, version)`; file naming is
`{kind_directory}/{id}@{version}.md`. Catalog uniqueness is enforced by the S03
[Vault](VAULT.md), not by a single-document validator. Example directories use singular
kind names and are not a production Vault layout contract.

## Markdown Codec API

```python
from reliclab.codec import CodecLimits, parse_module, parse_with_source, serialize_module

text = """---
schema_version: '1.0'
id: editor
kind: persona
version: 1.0.0
name: Editor
identity: A careful editor
---
Keep observations separate from suggestions.
"""
document = parse_module(text, source="editor.md")
parsed = parse_with_source(text, source="editor.md")
assert parsed.positions[("identity",)].line == 7
canonical = serialize_module(document)
assert serialize_module(parse_module(canonical)) == canonical
limits = CodecLimits(max_frontmatter_bytes=131072, max_body_bytes=2097152)
assert parse_module(canonical.encode("utf-8"), limits=limits) == document
```

Both parse functions accept `str` or UTF-8 `bytes`, an optional source label
(default `<memory>`), and keyword-only `limits`. `parse_module` returns a
`ModuleDocument`; `parse_with_source` returns a frozen `ParsedModule` with the
document and a read-only `positions` mapping from tuple field paths to frozen
`SourcePosition(line, column)` values. Indices are zero-based in field paths;
source coordinates are one-based Unicode code-point positions, not byte offsets.
The source label is not opened or resolved. `serialize_module(document, limits=...)`
returns text and revalidates the model, including mutable nested mappings.

### Input and Resource Limits

- Exactly one optional leading UTF-8 BOM is accepted. The opening line must be
  exactly `---` followed by LF or CRLF. Whitespace and comments on that line fail.
- The first subsequent exact `---` line closes frontmatter; the closing marker
  may end at EOF. All following content, including further `---` lines, is body.
- Header line endings must be LF or CRLF. Bare CR, NEL, and Unicode line/paragraph
  separators are rejected in raw frontmatter, but may occur in escaped strings.
  Body content is opaque and preserved exactly by parsing, including newlines.
- Limits count original UTF-8 bytes: header excludes delimiters and BOM but
  includes its line endings; body starts immediately after the closing line.
  Size failures are `PARSE_ERROR`, as are invalid UTF-8 and lone surrogates.
- `CodecLimits` defaults are 65536 header bytes, 1048576 body bytes, nesting depth
  32, and 10000 nodes. Limits must be positive integers, excluding booleans.
  Depth counts root as 1 and includes scalar/key nodes; node count includes
  containers, keys, and values. Depth has a hard ceiling of 64. Hosts may raise
  byte/node limits; untrusted module fields cannot change any limits.
- Numbers must be finite and numeric tokens cannot exceed 1024 characters.
  This bound is independent of Python's integer conversion configuration.
- Callers still own bounded file reads and transport limits: this API receives
  already-allocated text/bytes and is not a streaming file reader or OS sandbox.

### Restricted YAML

The root must be a mapping with string keys. PyYAML supplies syntax parsing and
source marks; its Python object constructors are never called. An event preflight
rejects anchors, aliases (including recursive/undefined aliases), every explicit
tag (including `!!str`), directives, document start/end markers, excess depth,
and excess nodes before tree composition. Duplicate decoded keys and `<<` merge
keys are rejected recursively. Extra YAML documents cannot be smuggled into the
header using a marker with a trailing comment; separators after the actual
closing delimiter remain ordinary Markdown.

Implicit scalar conversion is deliberately JSON-like: lowercase `true`, `false`,
`null`, an empty unquoted value, and JSON decimal numbers become their corresponding
Python values. Other plain scalars remain strings: `yes`, `on`, `~`, dates, `.inf`,
hex/octal spellings, and sexagesimal numbers have no YAML 1.1 special meaning.
Quoted/block scalars remain strings. Quote string-valued numbers such as
`schema_version: '1.0'`. Valid JSON surrogate-pair escapes decode to one Unicode
character; unpaired surrogate escapes fail. No imports, file/process operations,
template evaluation, or network calls occur during decoding.

### Canonical Output and Roundtrip

Canonical frontmatter is indented JSON, a YAML-compatible subset. This intentional
choice preserves scalar types without relying on a dumper's implicit resolvers.
Top-level keys follow model declaration order; nested mapping keys sort by Unicode
code point. Defaults are included, array order is preserved, and metadata Unicode
is escaped. Body is not duplicated in metadata. Output uses LF, no BOM, and one
required final newline if absent; existing trailing body newlines are preserved.
CRLF and bare CR in body normalize to LF. Empty body stays empty.

Semantic roundtrip means equality after schema normalization and that documented
body newline normalization, not byte-for-byte source equality. Canonical output is
idempotent. YAML comments, quoting, key order, and layout are not preserved. The
codec never writes or silently rewrites files; a future editor/Vault must compare
source and proposed output and apply its own conflict/atomic-write contract.

Serialization re-parses its output under the same limits before returning. A
document accepted in compact form may require higher host limits for expanded
canonical metadata or an appended body newline. Encoding failures use domain
errors, not partially returned output. No persistent asset migration is performed.

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
| `body` | `""`, except Skill | Default limit 1,048,576 UTF-8 bytes; host-configurable; kind-specific rules below |

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
`retryable=False`. Diagnostic fields are severity, code, message, source, location,
optional positive `line`/`column`, and `exact` (default false). Locations contain
field names/array indices. Schema-only validation leaves coordinates unset.

The codec maps schema failures to actual YAML value starts and body failures to
the start of the body (including the actual EOF position for an empty body).
Missing fields fall back to frontmatter start `(2, 1)` with `exact=False`; a field
path is still provided. Cross-field failures may locate the containing object or
root rather than one field. YAML syntax errors use parser marks. Encoding/reader
failures without reliable marks use a documented start-of-input/header fallback
with `exact=False`, not a claimed exact offending-byte position. `PARSE_ERROR`
denotes envelope, syntax, subset, or codec resource failures; `SCHEMA_INVALID`
denotes model validation or canonical JSON encoding failures.

Messages omit raw input values and validator context. The optional source is a
caller-provided label; do not place secrets in source labels or field names.
Direct Pydantic constructors raise native `ValidationError`, which can include
input values; use the public wrapper for user-facing failures. Domain codes also
reserve `SOURCE_CHANGED`, `NOT_FOUND`, `VERSION_CONFLICT`,
`DEPENDENCY_CYCLE`, `PATH_DENIED`, `CONTEXT_OVERFLOW`, and `IO_ERROR` for later stages.

## Reproducibility

```sh
uv sync --all-packages --all-extras --dev --locked
uv run --no-sync python -m scripts.schemas --check
uv run --no-sync python scripts/check.py --stage S01 --offline
uv run --no-sync python scripts/check.py --stage S02 --offline
uv run --no-sync python scripts/check.py --all --offline
uv run --no-sync python scripts/check.py --packaging
```

After deliberate model changes, regenerate with `python -m scripts.schemas` and
review the schema diff. Contract tests reject schema drift and validate all
examples before and after model normalization. The examples contain at least
three assets per kind, all four primary composition modes, and Chinese body text.
Codec contracts roundtrip all examples, reject invalid schema fixtures, and compare
four checked-in golden outputs. Deterministic Hypothesis tests exercise recursive
JSON/Unicode roundtrips and malformed text/bytes; security tests block constructors,
file/process effects, unsafe YAML features, and resource-limit bypasses.
