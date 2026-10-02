# reliclab-core

Composable agent identity assets and context.

Strict Persona, Skill, Memory, and Composition models are available through
`reliclab.schema`, along with `validate_module`, domain diagnostics, and canonical
Draft 2020-12 schema export. See the repository's `SPEC.md` and `examples/`.

This is not an agent executor. File codecs, Vault operations, reference resolution,
and prompt rendering are not implemented yet. Core has no Runtime or provider SDK
dependency. Its validation dependencies are Pydantic v2, semver, and jsonschema.

Developed in the RelicLab monorepo. This package builds independently with Hatchling and requires Python 3.11 or newer.
