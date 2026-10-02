# Changelog

Stage handoffs are recorded here in English. Entries describe delivered behavior,
compatibility or migration impact, verification results, and known limitations.
A recorded handoff does not imply that all acceptance checks have passed.

## Unreleased

### S02 - Safe Markdown Codec (2026-10-02)

- Add pure `parse_module`, `parse_with_source`, and `serialize_module` APIs with
  UTF-8/BOM handling, preserved input bodies, read-only source maps, and canonical
  JSON-compatible YAML frontmatter with normalized output newlines.
- Reject unsafe YAML tags, anchors, aliases, duplicate/merge keys, directives,
  multiple documents, invalid encodings, and excessive bytes, nesting, or nodes
  without calling YAML object constructors or executing file/process operations.
- Add host-controlled codec limits and optional diagnostic line/column/exactness
  metadata. Missing fields use an explicitly approximate frontmatter position.
- Add four golden fixture pairs, example/invalid-fixture codec contracts,
  deterministic Hypothesis tests, security regressions, and independent codec
  statement/branch gates of 95%. Exercise the codec in every isolated install.
- Compatibility: PyYAML is now a Core runtime dependency; Hypothesis remains
  development-only. Existing schema APIs retain their default 1 MiB body limit
  and gain a host-only override. Format version remains `1.0`; no files are
  automatically rewritten and no persisted-data migration is required.
- Verification: Windows/Python 3.11.15 and 3.12.14 pass 420 tests, strict mypy,
  ruff, formatting, schema-drift checks, and four sdist-to-wheel builds with five
  isolated installation combinations per interpreter. Core and codec statement
  and branch coverage are 100%. Remote matrix acceptance is tracked separately
  by the Quality workflow; pushing is not acceptance.
- Limitations: canonical serialization does not preserve YAML comments/layout;
  expanded output or a final body newline may require larger host limits. The
  codec performs no file reads/writes, conflict handling, Vault operations,
  reference resolution, agent execution, or UI work. See `SPEC.md` for the
  restricted scalar subset and exact roundtrip rules.

### S01 - Strict Asset Schemas (2026-10-02)

- Add strict Persona, Skill, Memory, and Composition models, typed references,
  portable path checks, render options, tool declarations, and value-free domain
  diagnostics in `reliclab.schema`.
- Add the English format specification, five canonical Draft 2020-12 schemas,
  15 valid Markdown examples, 11 invalid fixtures, and schema drift checks.
- Define the supported tool JSON Schema subset and document the semantic checks
  required in addition to structural JSON Schema validation.
- Add independent Core coverage gates and locked, hash-verified offline dependency
  installs; validate the schema API in all five wheel-installation combinations.
- Fix clean-runner offline packaging by exporting artifact URLs and hashes through
  `pylock.core.toml`; a requirements-only export incorrectly depended on cached
  registry index metadata. The first remote run passed all quality gates but
  exposed this packaging failure. Follow-up matrix results are recorded by the
  Quality workflow, separately from Git delivery.
- Compatibility: introduces format `1.0` and Pydantic v2, semver, and jsonschema
  runtime dependencies. No existing persisted-data migration is required. Package
  version remains the unpublished `0.1.0a1` development version.
- Verification: Windows/Python 3.11.15 and 3.12.14 pass 272 tests, strict mypy,
  ruff, and format checks. Core statement and branch coverage are both 100%.
  Independent sdist/wheel builds and five installation combinations pass on
  both Python versions. Remote Windows/Linux results are tracked by the Quality
  workflow; a successful push alone does not imply acceptance.
- Limitations: no production Markdown codec, Vault, version resolver, renderer,
  agent runtime, or connected Web UI. Structural schema validation alone is not
  sufficient; consult `SPEC.md` for required semantic validation.

### S00 - Engineering Foundation (2026-10-02)

- Include the previously uncommitted foundation needed by S01: four independent
  distributions, a locked uv workspace, CLI version/installation diagnostics,
  architecture boundary tests, offline checks, packaging checks, and CI.
- Verification before S01: 52 tests and five isolated installation combinations
  passed on Windows/Python 3.11.15 and 3.12.14. The expanded S01 suite now also
  covers this foundation. Remote matrix acceptance is tracked separately by CI.
- Compatibility: new pre-release package layout; no database or asset migration.
  Runtime and Server packages still expose foundations, not executable features.

### Development Workflow

- Authorize automatic stage-scoped commits and pushes at each stage handoff.
- Require English changelog entries and commit messages with explicit verification
  results and unresolved limitations.
- Keep acceptance status separate from Git delivery; pending required checks
  prevent a stage from being marked complete.
- No runtime behavior or data format changes; no migration is required.
