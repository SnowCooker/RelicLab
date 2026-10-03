# Core Context Budgets

S06 evaluates every successful `compose()` result against an explicit Core
content budget. It removes only whole, selected, on-demand Memory blocks in
reverse declaration order. Persona, Skill, always Memory, and all merged tool
declarations are required. If required content exceeds the budget, composition
raises `RelicError(code="CONTEXT_OVERFLOW")` without returning a partial success.

## Counting Scope

The versioned profile `core-content-v1` measures each candidate block's expanded
`text` once, then each merged tool's complete canonical JSON declaration once.
Counts are additive and cached for the removal pass. Tool descriptions, names,
and input schemas are included; tool provenance metadata is not. No separator or
provider envelope is synthesized. IR provenance, the manifest, and budget report
are bookkeeping, not prompt content, and are excluded from this token profile.

This is **not a complete provider-request budget**. Renderer framing, messages,
role wrappers, session history, and reserved output tokens are not included.
Even an exact tokenizer's independent fragment counts are not claimed to equal
the tokenization of a concatenated or provider-rendered request. Runtime must
count the actual complete request with its model adapter before sending it.

The default `Utf8ByteCounter` (`utf8-bytes-v1`) assigns one estimated unit per
UTF-8 byte. Unicode uses its encoded byte length, not character count divided by
four. This deliberately cautious offline heuristic has no tokenizer dependency
and is never advertised as an exact count or universal model-token upper bound.

## Counter Injection

The public `TokenCounter` protocol has a `counter_id: str` property and
`count(text: str) -> TokenCount`. The result contains a strict integer `value`
from 0 through 2**63-1, an `exact: bool` precision flag, and matching `counter_id`.
Pass the adapter using `compose(..., counter=adapter)` and explicitly select its
ID in `ComposeRequest(counter_id=adapter.counter_id)`.

Counter IDs are 1-128 ASCII characters, starting with a letter or digit and then
using letters, digits, `_`, `.`, `:`, or `-`. They identify semantics, not a dynamic
plugin registry. Unknown IDs do not load code. The host must include tokenizer
version/configuration in its identity and supply deterministic, offline,
side-effect-free counting code. Adapters are trusted host code, not imported
asset code and not sandboxed by Core.

An identity mismatch, changed identity during counting, invalid result type,
negative/noninteger/out-of-range count, or counter exception fails closed with
`SCHEMA_INVALID`. Exception text is redacted. There is no retry or silent fallback
to a different counter. No model SDK or paid call is included in S06.

## Reports and Precision

`BudgetReport` is available unchanged through `.data`, `.budget_report`, and
`to_json()`. Future CLI/renderers must preserve it, not turn estimates into exact
counts. Current CLI commands are still only version/installation diagnostics.

| Field | Meaning |
|---|---|
| `status` | `within_budget` on success |
| `counting_scope` | `core-content-v1`, not the full model request |
| `token_budget` | Positive limit (1..1,000,000), request override or Composition default |
| `counter_id` | Identity shared by all measurements and the manifest |
| `estimated` | True if any measured candidate/tool is estimated, including omitted candidates |
| `input_tokens` | All candidate block counts plus merged tool counts |
| `retained_tokens` | Count after whole-block removal, never above the budget on success |
| `required_tokens` | Required blocks plus all tool declarations |
| `tool_tokens` | Complete required tool-declaration subtotal |
| `block_counts` | Original-order block ID, required flag, and `TokenCount` for every candidate |
| `tool_counts` | First-seen tool name and `TokenCount` for every merged tool |
| `omissions` | Removal-order block ID, source key/hash/path, original order, count, and reason |

An empty candidate/tool set costs zero and remains conservatively
`estimated=true`; no counter call is needed. Exactness is an adapter assertion
about measured fragments, not something Core independently proves.
Report validation checks unique measurement IDs, counter identity/precision,
omission links to optional measured blocks, arithmetic reconciliation, and the
retained budget bound. DTOs and serializations remain detached from the immutable
context. Reports are not signatures or authorization to execute tools.

## Selection and Removal

Unselected on-demand Memory is excluded before counting and never reported as a
budget omission. Selected candidates are counted before removal. Required blocks
and tools are never truncated, dropped, or reprioritized. Equal-to-budget fits;
one unit over triggers removal of the last eligible Memory block. Zero-cost
optional blocks can be removed when encountered during an over-budget reverse
pass. Required interleaved Memory is skipped without disturbing order.

Every removal emits a source-attributed warning diagnostic with
`code="CONTEXT_OVERFLOW"`; the successful report distinguishes an omission from
a fatal required-content overflow. Remaining blocks keep their original IDs,
text, trust, and `order` values, which can have gaps. The manifest retains all
sources and original explicit selection, including removed Memory. Tools and
their source/trust records remain unchanged. No Vault or lock file is modified.

Recompose from the same captured graph when changing the budget. A trimmed IR
does not retain omitted text and is not a source for restoring removed blocks.
For deterministic nonnegative measurements, increasing the budget cannot remove
a block previously retained under a lower successful budget.

## Reproducible Example

```python
import hashlib

from reliclab.codec import serialize_module
from reliclab.compose import ComposeRequest, compose
from reliclab.resolve import resolve
from reliclab.schema import Composition, RelicError, validate_module
from reliclab.vault import CatalogSnapshot, ModuleSnapshot

memory = validate_module({
    "schema_version": "1.0", "kind": "memory", "id": "notes",
    "version": "1.0.0", "name": "Notes", "source": "inline",
    "body": "Optional notes.\n",
})
raw = serialize_module(memory).encode("utf-8")
source = ModuleSnapshot(memory.key, "memory/notes@1.0.0.md", hashlib.sha256(raw).hexdigest(), raw)
workflow = validate_module({
    "schema_version": "1.0", "kind": "composition", "id": "context",
    "version": "1.0.0", "name": "Context", "modules": {"memory": ["notes"]},
    "render": {"target": "plain"},
})
assert isinstance(workflow, Composition)
graph = resolve(workflow, CatalogSnapshot((source,)))
full = compose(graph, ComposeRequest(selected_memory_ids=("notes",), token_budget=16))
trimmed = compose(graph, ComposeRequest(selected_memory_ids=("notes",), token_budget=1))
assert len(full.blocks) == 1
assert trimmed.blocks == ()
assert trimmed.budget_report.omissions[0].tokens == 16
assert trimmed.budget_report.estimated
assert trimmed.manifest.sources == full.manifest.sources
print(trimmed.budget_report.model_dump_json())
```

For a required-content failure, make this Memory `scope="always"`, recapture its
new bytes/hash, and use budget 1. The integration test
`test_three_budgets_preserve_vault_bytes_and_locked_sources` exercises full,
trimmed, and failing results against a real temporary Vault.

## Compatibility and Verification

S06 changes pre-release IR/composer semantics to 1.1. Rebuild old 1.0 contexts from
their captured sources; do not relabel `not_evaluated` as `within_budget`.
Asset schema and composition-lock formats remain 1.0; no asset migration or new
dependency is required. Existing successful calls can now omit optional content
or fail when required content is too large. All byte-safety limits still apply
before token trimming and to the resulting serialized report.

External file/glob Memory remains unsupported when selected; S07 will capture
external notes before budgeting. No renderer, full CLI, or Runtime is delivered
by this stage. Public Core DTO/JSON contract tests preserve estimated flags and
tool pairing until those consumers are implemented.

Run `python scripts/check.py --stage S06 --offline` and the packaging gate. Budget
and composition each have independent 95% statement/branch thresholds. Tests
cover exact boundaries, required overflow, interleaved selection, Unicode,
invalid counters/reports, deterministic monotonic retention, and real Vault
immutability. CI runs Windows/Linux with Python 3.11/3.12.
