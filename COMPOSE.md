# Composition IR

Status: S05 implementation, pre-release. `reliclab.compose` turns a locked
`ResolvedGraph` into deterministic, provider-independent context blocks. This is
an **unbudgeted intermediate representation**, not a model request or executable
agent. No token count, prompt renderer, external-note reader, or tool executor is
implemented here.

## Quick Start

This example runs entirely in memory after installing `reliclab-core`:

```python
import hashlib

from reliclab.codec import serialize_module
from reliclab.compose import ComposeRequest, compose
from reliclab.resolve import resolve
from reliclab.schema import Composition, validate_module
from reliclab.vault import CatalogSnapshot, ModuleSnapshot

persona = validate_module({
    "schema_version": "1.0", "kind": "persona", "id": "editor",
    "version": "1.0.0", "name": "Editor", "identity": "Editor for {{ project }}",
    "body": "Explain proposed changes.\n",
})
content = serialize_module(persona).encode("utf-8")
source = ModuleSnapshot(
    persona.key, "personas/editor@1.0.0.md",
    hashlib.sha256(content).hexdigest(), content,
)
workflow = validate_module({
    "schema_version": "1.0", "kind": "composition", "id": "review",
    "version": "1.0.0", "name": "Review", "modules": {"persona": "editor"},
    "render": {"target": "plain", "token_budget": 8000},
})
assert isinstance(workflow, Composition)
graph = resolve(workflow, CatalogSnapshot((source,)))
context = compose(graph, ComposeRequest(variables={"project": "RelicLab"}))
assert context.blocks[0].trust == "reference"
assert context.blocks[0].source_hash == source.content_hash
assert context.budget_report.status == "not_evaluated"
assert compose(graph, ComposeRequest(variables={"project": "RelicLab"})).digest == context.digest
print(context.to_json())
```

For a local Vault, use `resolve(workflow, vault.snapshot())` instead. See
[RESOLVE.md](RESOLVE.md) for snapshot and lock replay semantics.

## API and Inputs

```python
compose(graph: ResolvedGraph, request: ComposeRequest = ComposeRequest(),
        *, limits: ComposeLimits = ComposeLimits()) -> ComposedContext
```

All functions are synchronous. Composition validates the captured bytes and
replays their existing lock in memory to reject altered graphs. It does not
recapture the filesystem, choose newer dependencies, consult environment
variables, read the clock, or call providers. Reusing an old snapshot does not
prove that current disk contents are unchanged.

`ComposeRequest` accepts:

| Field | Semantics |
|---|---|
| `variables` | Scalar mapping overriding Composition defaults; names are ASCII identifiers |
| `selected_memory_ids` | Distinct IDs declared in the graph; input order does not change output order |
| `trusted_sources` | Distinct `LockedModule(key, content_hash)` records for reviewed Persona/Skill bytes |
| `token_budget` | Optional positive override, at most 1,000,000; otherwise use Composition's budget |
| `counter_id` | Currently only `"unmeasured"`; no token counter runs |
| `renderer_version` | Currently only `"unrendered"`; no provider renderer runs |

Unknown fields, coercive types, non-finite numbers, and non-scalar variables are
rejected. Requests and limits are revalidated at the call boundary, including
mutated nested mappings. Missing or duplicate Memory IDs fail with `SCHEMA_INVALID`.
Stale, duplicate, unknown, or Memory trust records fail with `SOURCE_CHANGED`.

## Blocks and Ordering

Blocks contain `block_id`, `kind`, `text`, `source_key`, `source_hash`,
`source_relative_path`, `required`, `trust`, and zero-based `order`.
The stable ID is `kind:id@version`. Relative paths identify captured assets;
hashes cover their original bytes, not expanded text.

1. Persona ancestors precede the leaf. Leaf identity/voice override their parents.
   Merged values/constraints appear once, attributed to the earliest contributing
   source; deduplication occurs before variable expansion. Each nonempty original
   body retains its own source block. An ancestor contributing no content emits
   no block but remains in the manifest.
2. Skills follow declaration order. Each block includes its trigger when present,
   body, and ordered input/output examples.
3. Inline Memory follows declaration order. `always` is always included and
   required. `on-demand` is included only when explicitly selected and is not
   required. An entirely unselected Memory-only composition can have zero blocks.

Persona and Skill blocks are required. Sections have stable Markdown headings
inside the IR; these are not a final provider prompt format. Metadata such as
names, tags, and descriptions is not implicitly injected as instructions.

All content defaults to `reference`. Only an exact host-supplied trust record can
mark a Persona/Skill block `instruction`. Memory always remains `reference`.
Do not generate trust records automatically from arbitrary imported assets:
review the exact bytes and retain their key/hash as host policy. These labels
neither prevent prompt injection nor grant filesystem, network, or tool rights.
Natural-language constraints are content, not enforceable permissions.

## Variables and Tools

Only `{{ identifier }}` is supported, with optional spaces/tabs around the name.
Persona identity, voice, values, constraints, and body, plus Skill trigger, body,
and example input/output fields, are expanded. Memory, metadata, tool names,
tool descriptions, and tool schemas are never templated.

Strings are inserted verbatim; booleans, numbers, and null use JSON scalar text.
Inserted strings are not parsed again. Missing values, attribute/index access,
calls, filters, loops, includes, comments, and malformed double-brace templates
fail closed with source/field diagnostics. No general template engine or Python
evaluation runs. Single braces remain ordinary text.

Tool requirements keep first-seen order. Equal names merge only when their
entire validated declarations have equal canonical JSON, including descriptions
and schemas. Dictionary key order is irrelevant; array order and descriptions
remain significant. This is conservative structural equality, not a claim that
arbitrary JSON Schemas have been proved semantically equivalent.
Conflicts raise `VERSION_CONFLICT` with both source paths and the tool name.
Merged tools list every distinct contributor and are `instruction` only when
all contributors are trusted. Tools remain declarations; nothing executes them.

## Manifest and Digest

IR and composer semantics are versioned `1.0`. The manifest contains the existing
composition lock, all dependency keys/raw hashes/relative paths (even unselected
Memory and empty ancestors), merged variables, canonical selection/trust order,
host byte limits, and schema/renderer/counter versions. It contains no external
note content or note hashes because this stage never captures external notes.

`ComposedContext` stores authoritative canonical JSON privately. `.data`,
`.blocks`, `.tools`, `.manifest`, `.diagnostics`, and `.budget_report` return
detached DTOs; modifying their nested mappings cannot alter the result or digest.
Create contexts through `compose`, not the internal serialized-data constructor;
this API does not authenticate arbitrary imported JSON.

Canonical JSON uses sorted dictionary keys, compact separators, ASCII escapes,
finite numbers, and preserved array order. `digest` is SHA-256 over that UTF-8
payload **without** its digest field; `to_json()` adds the digest field, with no
trailing newline. This is not RFC 8785, a signature, or an authorization token.

Any captured dependency-byte change affects the digest, even when its body is
not included. Relative-path renames affect this IR digest, although they need
not affect the resolver lock. Variables (including unused ones), trust, limits,
selection, and requested budget are also part of the result. Absolute machine
paths and nondeterministic timestamps are not synthesized; caller-supplied text
and variables are still caller data. Avoid embedding secrets in a manifest you
plan to publish or log.

## Limits and Future Stages

Default limits are 1 MiB per block, 16 MiB across block text and for the final
serialized context, 64 KiB per variable value, and 256 merged variables. Limits
count UTF-8 bytes; serialized ASCII escapes and metadata also count toward the
final JSON cap. Expansion and multi-field assembly are checked incrementally.
Limits are explicit positive integers and recorded in the manifest. Oversized
results fail with `CONTEXT_OVERFLOW`; nothing is silently truncated.

`budget_report.status` is always `not_evaluated`, with the requested token budget
and `counter_id="unmeasured"`. A successful composition is **not** evidence that
the model context window fits. S06 will implement actual budget evaluation and
explicit omissions; S07 will capture external notes; later renderers and Runtime
must validate complete provider requests separately.

Selected `file`/`glob` Memory fails explicitly with `SCHEMA_INVALID`; unselected
on-demand external Memory is not read and emits no block. There is no silent
empty-note success. Asset schema `1.0` and resolver lock `1.0` remain unchanged;
no migration, new dependency, or lockfile update is required by S05.

Run `python scripts/check.py --stage S05 --offline` and the packaging gate.
Public tests include full-IR goldens for four modes, 100-repeat determinism per
mode, body-change properties, trust/template/resource failure paths, and real
Vault snapshot-to-IR integration. The compose group has independent 95%
statement and 95% branch gates. Remote matrix acceptance is tracked by CI.
