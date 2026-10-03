# Version Resolution and Composition Locks

Status: S04 implementation, pre-release. `reliclab.resolve` resolves a validated
Composition against immutable module bytes. It does not read files, render a
prompt, read external Memory notes, call a provider, or execute tools. Asset syntax
is defined in [SPEC.md](SPEC.md); filesystem boundaries are in [VAULT.md](VAULT.md).

## Quick Start

```python
from tempfile import TemporaryDirectory

from reliclab.resolve import CompositionLock, resolve
from reliclab.schema import Composition, validate_module
from reliclab.vault import Vault

persona = validate_module({
    "schema_version": "1.0", "kind": "persona", "id": "editor",
    "version": "1.0.0", "name": "Editor", "identity": "A careful editor",
})
request = validate_module({
    "schema_version": "1.0", "kind": "composition", "id": "review",
    "version": "1.0.0", "name": "Review",
    "modules": {"persona": "editor@1"}, "render": {"target": "plain"},
})
assert isinstance(request, Composition)
with TemporaryDirectory() as root:
    vault = Vault(root)
    vault.create(persona)
    catalog = vault.snapshot()
    graph = resolve(request, catalog)
    saved_text = graph.lock.to_json()
    lock = CompositionLock.from_json(saved_text)
    assert resolve(request, catalog, lock=lock) == graph
```

Persist the returned JSON with a host-controlled atomic writer outside the four
module directories. Lock serialization itself performs no I/O. Application APIs
must require an explicit user decision before discarding a lock and resolving
again; do not catch a lock error and silently retry without it.

## Snapshot Contract

`Vault.snapshot() -> CatalogSnapshot` scans twice under one cooperating-client
lock. A difference in keys, paths, or bytes raises `SOURCE_CHANGED`. Both scans
retain the normal Vault validation and resource bounds. The returned snapshot
does not change when files are edited later. Reload it to detect later edits.

`CatalogSnapshot(modules: tuple[ModuleSnapshot, ...])` also supports in-memory
callers. Construction validates raw-byte hashes, decoded identity, portable flat
paths, and key/path uniqueness; it copies the sequence to a sorted tuple. No
filesystem access occurs. Individual snapshot codec limits still apply; hosts
building in-memory catalogs are responsible for bounding their supplied collection.

Two scans are **not a transactional snapshot against writers bypassing the lock**.
A malicious writer can race the scans or perform an ABA change. This detects
ordinary observed changes, not every possible interleaving. Use host-controlled
roots or an isolated snapshot backend for stronger guarantees. The resolver works
on the actual captured bytes, never a fresh read during graph traversal.

## Selectors

The stored version parser and precedence comparisons use the existing
[python-semver library](https://python-semver.readthedocs.io/en/latest/usage/compare-versions.html).
RelicLab supports only this explicit selector subset, not arbitrary npm ranges:

| Reference | Selection |
|---|---|
| `editor` | Highest stable version |
| `editor@1` | Highest stable version with major 1 |
| `editor@1.2` | Highest stable version with major 1, minor 2 |
| `editor@1.2.3` | Exact stored version string |
| `editor@1.2.3-rc.2` | Exact prerelease, explicitly requested |
| `editor@1.2.3+build` | Exact version including build identity |
| `editor@^1.2.3` | Stable versions >=1.2.3 and <2.0.0 |
| `editor@^0.2.3` | Stable versions >=0.2.3 and <0.3.0 |
| `editor@^0.0.3` | Stable versions >=0.0.3 and <0.0.4 |

An explicit prerelease caret lower bound also permits prereleases of that same
major/minor/patch tuple, at or above the lower bound. It does not admit prereleases
of later tuples. Stable versions within the same caret bounds remain eligible.
For example, `^1.0.0-rc.2` permits `1.0.0-rc.10` and `1.1.0`, not `1.1.0-rc.1`.

As required by [SemVer 2.0.0](https://semver.org/), build metadata does not affect
precedence. If multiple matching versions share the highest precedence, range or
bare-ID selection fails with `VERSION_CONFLICT`; it never uses filename order or
an arbitrary build-string tie-breaker. An exact stored version disambiguates.
Exact `1.0.0` does not mean `1.0.0+build`.

`latest`, wildcards, tildes, comparison expressions, leading-zero numbers, and
unsupported syntax are rejected by schema validation. No candidate means
`NOT_FOUND`, not fallback to an incompatible version. References are typed by
their slots; an ID found only under another kind gives `VERSION_CONFLICT`.

## Graph and Inheritance

```python
resolve(composition, catalog, *, lock=None, max_body_bytes=1048576) -> ResolvedGraph
```

Resolution revalidates the Composition and lock, including DTOs created through
unvalidated `model_copy` calls. The explicit Composition is the request; it may be
an unsaved draft and is not implicitly replaced by a catalog Composition.

The frozen result contains:

- `persona_chain`: original snapshots from oldest ancestor to selected child.
- `skills` and `memory`: snapshots in declaration order, not catalog sort order.
- `modules`: the concatenation of those three sequences.
- `persona`: an `EffectivePersona`, or `None` when no Persona was selected.
- `composition`: a freshly decoded copy of the captured Composition DTO.
- `composition_json`, `lock`, and the host's `max_body_bytes` setting.

Persona inheritance is single-parent, limited to **32 modules including the
selected child**. An exact-key repeat is `DEPENDENCY_CYCLE`; using two versions of
the same Persona ID is `VERSION_CONFLICT`, not implicit multi-version inheritance.
Repeated Skill/Memory IDs within a slot fail schema validation, even with different
selectors. The same ID in different typed slots is valid.

`EffectivePersona` contains the selected child's key, identity, and voice. Child
scalar values override parents, including an empty/default voice. Values and
constraints are merged parent-first, with exact, case-sensitive deduplication;
empty child lists do not remove parent constraints. Tags, names, descriptions,
authors, and extensions remain local metadata on the original snapshots; they
are not implicitly inherited into execution instructions.

Nonempty bodies become `PersonaSection(key, text)` records in parent-first order.
`text` retains captured newlines. The convenience `body` joins sections with two
LF characters and prefixes each with `## Persona {id}@{version}` plus two LFs.
No body text is executed or interpreted as a permission rule. The final UTF-8 body,
including headings, must fit `max_body_bytes`; overflow is `CONTEXT_OVERFLOW`.
That positive integer also bounds the request Composition body validation. Hosts
may adjust it; module content cannot. Resolution allows at most 10000 total
selected modules, including ancestors, and never returns a truncated graph.

`ResolutionError` is a `RelicError` subclass with a `chain` tuple from the
Composition through each traversed typed reference, including the failing edge.
The same chain appears in `details[].source`. Messages are English and omit asset
bodies; validation errors retain the existing field diagnostics. These chains
identify references, not a guarantee of trustworthy or non-sensitive asset IDs.

## Lock Format and Replay

`CompositionLock` version `1.0` records resolver semantics version `1.0`, a
`composition_hash`, and ordered `LockedModule(key, content_hash)` entries for the
complete dependency closure. There are no timestamps or absolute paths.

The composition hash covers its full validated DTO, including metadata, body,
variables, defaults, selections, and render options, encoded as compact JSON with
sorted mapping keys, preserved array order, ASCII escaping, and no NaN/Infinity.
It is SHA-256 of those UTF-8 bytes. This is a specified Python JSON representation,
not a claim of RFC 8785 canonicalization. Composition YAML comments/layout are not
DTO fields and are not hashed; selected module hashes cover **exact raw bytes**,
including comments, BOM, and newlines.

`lock.to_json()` uses the same JSON rules. `lock.digest` hashes that text and is
not itself embedded in it. `CompositionLock.from_json(str_or_bytes)` requires
UTF-8 JSON, rejects duplicate object members, unknown fields, unsupported versions,
invalid hashes, duplicate typed IDs, and Composition entries. Input/output are
limited to 4 MiB and 10000 entries; resolution also checks that generated locks
can serialize within the limit. Malformed serialized locks raise `SCHEMA_INVALID`.
Direct invalid model construction uses Pydantic validation errors.

With a supplied lock, each edge uses the pinned exact key and verifies both its
raw hash and compatibility with the original selector. Missing/changed modules,
changed Composition data, missing/extra/reordered lock entries, or incompatible
pins raise `SOURCE_CHANGED`. New unrelated assets or higher versions do not cause
an upgrade. Portable file renames with unchanged bytes do not invalidate the lock.

To update deliberately, capture a fresh catalog and call `resolve` without the
old lock, inspect the resulting changes, and persist the new lock. Neither mode
changes module files. A lock is **not a signature or authorization artifact**;
hosts must protect it and persist their own acceptance decisions.

## Limits and Verification

This stage does not generate composition IR or prompts, count tokens, resolve
external note content, save lock files, or add CLI/UI/runtime features. External
Memory file contents are not part of this lock; later composition and Memory
stages must snapshot and track them separately. Vault deletion remains the S03
conservative ID-based guard; adding a resolver does not silently weaken it.

Run `python scripts/check.py --stage S04 --offline` and the packaging gate.
Public selector vectors, depth/cycle and merge tests, lock-tampering regressions,
deterministic permutation properties, real Vault edit/delete/rename tests, and
all five isolated installation probes cover the API. The resolver has independent
95% statement and branch coverage requirements. Public checks never read private
planning documents.
