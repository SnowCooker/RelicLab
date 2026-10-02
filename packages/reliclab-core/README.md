# reliclab-core

Composable agent identity assets and context.

Strict Persona, Skill, Memory, and Composition models are available through
`reliclab.schema`, along with `validate_module`, domain diagnostics, and canonical
Draft 2020-12 schema export. See the repository's `SPEC.md` and `examples/`.

`reliclab.codec` provides pure UTF-8 Markdown parsing, restricted YAML frontmatter,
source coordinates, host-controlled resource limits, and canonical serialization.
It does not write files or preserve YAML comments. See `SPEC.md` for exact
newline, scalar, and roundtrip semantics.

This is not an agent executor. Vault operations, reference resolution, and prompt
rendering are not implemented yet. Core has no Runtime or provider SDK dependency.
Its dependencies are Pydantic v2, semver, jsonschema, and PyYAML.

Developed in the RelicLab monorepo. This package builds independently with Hatchling and requires Python 3.11 or newer.
