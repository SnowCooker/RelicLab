# Contributing to RelicLab

RelicLab contains the S00 engineering foundation, S01 strict asset schemas,
S02 safe Markdown codec, S03 local Vault, S04 version resolution and locks,
S05 deterministic composition IR, and S06 Core-content budgets with explicit omissions.
The Python APIs and format are documented in [SPEC.md](SPEC.md),
[VAULT.md](VAULT.md), [RESOLVE.md](RESOLVE.md), [COMPOSE.md](COMPOSE.md), and [BUDGET.md](BUDGET.md).
Only CLI version reporting and installation diagnostics are implemented in the
CLI. CLI asset management/composition, agent execution, and the Web UI are future stages.

## Development Environment

Install Python 3.11 or 3.12 and uv 0.11.7. The package metadata allows Python
3.11+, while the initial CI matrix targets Windows and Linux on 3.11/3.12.
The matrix is a test configuration, not proof that remote CI has already passed.
macOS and newer Python releases are not yet validated. Node is not required in
S00; its version and frontend toolchain will be locked when Web development starts.

From the repository root:

```sh
uv sync --all-packages --all-extras --dev --locked
uv run --no-sync relic --version
uv run --no-sync relic doctor
uv run --no-sync python scripts/check.py --stage S00 --offline
uv run --no-sync python scripts/check.py --stage S01 --offline
uv run --no-sync python scripts/check.py --stage S02 --offline
uv run --no-sync python scripts/check.py --stage S03 --offline
uv run --no-sync python scripts/check.py --stage S04 --offline
uv run --no-sync python scripts/check.py --stage S05 --offline
uv run --no-sync python scripts/check.py --stage S06 --offline
uv run --no-sync python -m scripts.schemas --check
uv run --no-sync python scripts/check.py --all --offline
uv run --no-sync python scripts/check.py --packaging
```

Use `--python 3.11` or `--python 3.12` on the sync command to select an installed
interpreter. uv may download an interpreter if it is absent. Initial sync needs
network access; subsequent checks use the installed environment. uv's cache is
project-local (`.uv-cache/`) and ignored by Git.
If `UV_CACHE_DIR` is set by your environment, prepare the packaging cache with
`uv --cache-dir .uv-cache sync --all-packages --all-extras --dev --locked`.
CI uses this explicit cache path so isolated offline installs see the same files.

`scripts/check.py` never syncs, installs dependencies, or modifies lockfiles.
Missing tools, unknown stages, empty test selections, and failing commands cause
a nonzero exit. Use `uv run --no-sync` to avoid implicit environment changes.
The `--all` mode covers registered implemented stages, not future roadmap tasks.

Offline checks block Python test sockets through pytest-socket and disable
package-index downloads for child packaging tools. This is a testing guard, not
an operating-system sandbox for arbitrary subprocesses. No current check invokes
a model provider. pytest's optional persistent cache is disabled so checks do not
depend on cache ownership across local users or CI runners.

## Package Boundaries

| Directory | Distribution | Import | Mandatory project dependencies |
|---|---|---|---|
| `packages/reliclab-core` | `reliclab-core` | `reliclab` | None; third-party schema, YAML, and filesystem-lock libraries only |
| `packages/reliclab-runtime` | `reliclab-runtime` | `reliclab_runtime` | Core |
| `apps/cli` | `reliclab` | `reliclab_cli` | Core |
| `apps/server` | `reliclab-server` | `reliclab_server` | Core |

CLI extras `runtime`, `ui`, and `all` select optional packages; Server also has
a `runtime` extra. These extras currently install package foundations only.
`relic doctor --require runtime` or `--require ui` verifies installation and
reports an actionable error when missing; it does not claim a usable runtime/UI.

Core must never import Runtime or either application. Runtime must not import
applications. Source and distribution dependency checks live in
`tests/contract/test_import_boundaries.py`. Update the explicit allowlists in
`tests/quality.toml` only with a reviewed architectural reason. The AST scanner
checks ordinary imports and literal dynamic imports, rejects unresolved dynamic
imports, and is not an adversarial code analyzer.

Runtime state will use a separate persistent SQLite database. Core assets remain
plain-text files; any Memory index is a rebuildable cache. Do not conflate these
storage lifecycles or add execution behavior to Core.

## Tests and Quality

- Write normal, boundary, and failure-path tests with each behavior change.
- Use `tests/support/clock.py` and temporary-directory fixtures instead of real
  clocks, personal files, or remote services. Fakes for runtime ports arrive later.
- `ruff check`, `ruff format --check`, and strict mypy are required.
- CLI statements/branches require at least 80%/75%; quality-harness code has its
  own 80%/75% gate. Measurements cannot be averaged across groups.
- Core now has independent 90% statement and 85% branch gates. Runtime still
  exposes metadata only; its first business implementation must add the same
  independent gates. Security-critical modules require 95% branch coverage.
- The production codec has separate 95% statement and branch gates. Hypothesis
  property tests use deterministic generation without a persistent example database;
  auxiliary Hypothesis storage lives under ignored `.artifacts/hypothesis/`.
- Vault storage has independent 95% statement/branch gates and real filesystem,
  cross-process race, Windows junction/POSIX symlink, and fault-injection tests.
  Link fixtures point only to test-owned directories; no private user data is read.
- Public tests, fixtures, and CI configuration must never read ignored `docs/`.
- Version resolution has independent 95% statement/branch gates, public selector
  vectors, deterministic permutation tests, inheritance limits, and lock replay
  tests against real file edits. It adds no new third-party dependency.
- Composition has independent 95% statement/branch gates, full-IR golden fixtures
  for four modes, repeated-input determinism, body-change properties, host trust
  validation, scalar-only templates, and explicit resource-limit failures.
- Budgeting has its own 95% statement/branch gates. Test required-content and
  tool retention, reverse optional removal, monotonicity, invalid counters,
  arithmetic report invariants, and precision across the public DTO/JSON boundary.
- A passing model-generated summary is not evidence: preserve actual commands,
  exit codes, coverage reports, artifacts, and unresolved limitations.

Check outputs are under `.artifacts/`: per-mode check records, coverage JSON,
and the packaging report/logs. The packaging check builds each sdist, builds the
wheel from that sdist, and installs five combinations into new virtual
environments. Third-party Core dependencies are exported from `uv.lock` to
`pylock.core.toml`, preserving artifact URLs and hashes, and installed offline
from the cache populated by the explicit sync. This does not require cached
registry index metadata, which a fresh locked sync does not necessarily fetch.
The pinned uv version supports this export; its experimental-feature warning is
retained in build logs. Review this behavior when upgrading uv.
Workspace wheels are then installed with `--no-index --find-links`. Missing cache
entries fail the check; checks never download packages. Imports must resolve
inside the fresh environment, and optional modules must be absent when not
selected. Core dependency metadata is allowlisted, and each installation exercises
asset validation, canonical JSON Schema, a production codec roundtrip, and real
Vault create/read/delete, catalog capture, resolution, serialized-lock replay,
and composition with provenance, default trust, and stable digest checks.
Missing optional-install guidance is
also checked. The schema contract tests enforce generated file consistency and
validate public examples and invalid fixtures without reading private documents.

Individual package builds are supported after development sync:

```sh
uv run --no-sync python -m build --no-isolation packages/reliclab-core
```

The shared [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
locks development tools together. [Hatchling](https://hatch.pypa.io/latest/config/build/)
builds independently distributable packages. Lockfile changes should be deliberate;
CI always uses `--locked`. Package names are provisional until publish-time checks;
local builds do not reserve names on PyPI.

## Scope and Language

Code comments, docstrings, identifiers, errors, CLI output, and commit messages
are English. Public documentation is English-primary; the root README is
English-first bilingual. Private planning and delivery reports remain in ignored
`docs/` and may be Chinese-primary.

Keep contributions scoped to a deliverable stage. Preserve unrelated user edits.
Do not replace absent features with fake success responses. Add API and migration
notes when changing contracts. Package publication, deployments, and releases
require separate authorization.

## Stage Delivery

The project owner authorizes an automatic commit and push at every stage
handoff. Follow the stage delivery rules in [AGENTS.md](AGENTS.md):

1. Run the stage quality gates and affected regression tests, and review the diff.
2. Update [CHANGELOG.md](CHANGELOG.md) in English with the stage ID, delivered
   functionality, compatibility or migration impact, actual verification results,
   and known limitations. Preserve detailed evidence in the private stage report.
3. Stage only intended public deliverables and create an English commit that
   identifies the stage, for example `feat(core): deliver S01 asset schemas`.
4. Push to the current branch's configured upstream without asking again. Never
   force-push, bypass branch protection, include secrets, or force-add ignored files.
5. Verify the push and report the commit hash and destination. If the push fails
   or the upstream is unclear, keep the local commit and report the blocker.

A delivery commit can trigger remote CI while the stage remains `InReview`.
Neither a successful commit nor a successful push proves acceptance: all required
checks must pass before the stage becomes `Done`. Failed or unavailable checks
must be explicitly recorded, not hidden by the automatic delivery workflow.

## Tooling Decisions

S00 uses the standard library for its bootstrap CLI and quality orchestration.
Typer is planned for the full CLI and FastAPI for the server. S01 introduces
Pydantic v2 for asset models, semver for stored versions, and jsonschema for
offline tool-schema validation. S02 promotes PyYAML (MIT) to a Core dependency for
syntax/marks only: event preflight and manual bounded node decoding never call
YAML object constructors. Typing stubs and Hypothesis remain development-only.
S03 adds filelock >=3.32.7 (MIT) for native cross-process locking with preserved
lock-file identity and disabled soft fallback. Its measured installed non-bytecode
files total 355787 bytes on Windows/Python 3.12; platform/version sizes can vary.
Using a tested lock library avoids maintaining separate Win32/Unix lock engines.
There are no new provider or database dependencies; offline use needs no network.

Pydantic and jsonschema use MIT licenses; semver uses BSD-3-Clause. Their locked
transitive dependencies use MIT or PSF-2.0 licenses. The installed runtime
dependency files before S02 totaled approximately 8.85 MiB in the measured Windows/Python 3.12
environment (package RECORD files, excluding generated bytecode); other platforms
vary; that historical measurement excludes the new PyYAML dependency. These libraries
avoid hand-written type, SemVer, JSON Schema, and YAML syntax engines.
An alternative would be bespoke validation with less dependency weight but more
compatibility and security maintenance. Core validation needs no network after
installation; locked offline packaging requires a populated dependency cache.

Development-only tools are build/Hatchling (MIT), ruff (MIT), mypy (MIT), pytest
(MIT), pytest-cov (MIT), pytest-socket (MIT), and Hypothesis (MPL-2.0). Their exact dependency graph and
hashes are recorded in `uv.lock`. They do not increase Core's installed dependency
footprint. Core's S01 dependencies and their transitive packages do increase the
installed footprint; independent installation tests cover that change. Full
license inventory and release auditing are required before a
public release.
