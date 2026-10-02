# RelicLab — Project Conventions

## Language Policy (bilingual project)

- **Code comments & docstrings**: English only.
- **Identifiers, commit messages, CLI output, error messages**: English only.
- **Everything committed to git** (code, comments, identifiers, commit messages, public docs): English-primary.
- **README.md**: bilingual, English as the default/primary language (English first, Chinese follows).
- **Internal design docs** (`docs/`, git-ignored, personal): Chinese-primary is fine — not part of the open-source release.

## Stage Delivery and Git

- At every stage handoff, automatically record changes in English in `CHANGELOG.md`, create an English commit identifying the stage, and push it to the current branch's configured upstream. This workflow is authorized by the project owner and does not require repeated confirmation.
- Before committing, run the stage quality gates and affected regression tests, review the diff, and stage only the intended deliverables. Preserve unrelated changes; never force-add ignored files, secrets, local artifacts, or private `docs/` and `CLAUDE.md`.
- Each changelog entry must identify the stage, delivered functionality, compatibility or migration impact, verification results, and known limitations. Keep private design material out of the public summary.
- A push is not acceptance. A handoff awaiting remote CI or other required checks remains `InReview`; only mark a stage `Done` when all required acceptance evidence passes. Record failed or unavailable checks explicitly.
- Verify and report the commit hash, destination branch, and push result. If pushing fails or the upstream is missing or ambiguous, preserve the local commit and report the blocker. Never force-push, rewrite shared history, or bypass branch protection.
- This authorization covers stage commits and pushes only, not package publication, deployments, releases, or paid API calls.

## Other Conventions

- Python 3.11+, Pydantic v2; ruff + mypy + pytest.
- Library-first monorepo: `reliclab-core` (import `reliclab`) owns assets and composition; optional `reliclab-runtime` (import `reliclab_runtime`) owns agent execution. Runtime may depend on Core; Core must never depend on Runtime. CLI and Web UI are thin shells.
- Plain-text first: modules are YAML frontmatter + Markdown files; Core has no mandatory database. Runtime uses separate SQLite state for sessions, events, approvals, and jobs; this state is not a disposable cache.
- Execute development stages against their contracts, unit tests, and acceptance criteria. Do not claim a stage complete without reproducible verification evidence. Internal stage specifications live in `docs/`; public tests and CI must not depend on ignored documents.
- Design docs and roadmap live in `docs/` (git-ignored, internal); the public-facing roadmap is the Roadmap section in README.md.

## Imported Claude Cowork project instructions

A modular open-source framework for managing AI agent identities — compose and reuse Personas, Skills, and Memory across any LLM workflow.
