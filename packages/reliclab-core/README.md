# reliclab-core

Composable agent identity assets and context.

Strict Persona, Skill, Memory, and Composition models are available through
`reliclab.schema`, along with `validate_module`, domain diagnostics, and canonical
Draft 2020-12 schema export. See the repository's `SPEC.md` and `examples/`.

`reliclab.codec` provides pure UTF-8 Markdown parsing, restricted YAML frontmatter,
source coordinates, host-controlled resource limits, and canonical serialization.
It does not write files or preserve YAML comments. See `SPEC.md` for exact
newline, scalar, and roundtrip semantics.

`reliclab.vault` adds database-free CRUD, fresh catalog queries, SHA-256 revision
checks, native cross-process locks, atomic publication, and original-byte backup
recovery. See the repository's `VAULT.md` for its host-managed filesystem boundary
and explicit limits with uncooperative editors.

`reliclab.resolve` adds typed SemVer selection, bounded Persona inheritance,
immutable catalog snapshots, and portable composition locks with strict replay.
See the repository's `RESOLVE.md` for selection, merge, and hash semantics.

`reliclab.compose` adds deterministic unbudgeted IR, bounded scalar substitution,
source provenance and host-provided trust, tool merging, and canonical digests.
See the repository's `COMPOSE.md`. Token-budget evaluation, external-note capture,
and provider prompt rendering are not implemented yet.

This is not an agent executor. Core has no Runtime or provider SDK dependency. Its dependencies
are Pydantic v2, semver, jsonschema, PyYAML, and filelock.

Developed in the RelicLab monorepo. This package builds independently with Hatchling and requires Python 3.11 or newer.
