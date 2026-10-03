"""Pure provenance-preserving composition; no provider, filesystem, or clock I/O."""

from reliclab.resolve import ResolvedGraph, resolve
from reliclab.resolve.types import canonical_json
from reliclab.schema import Diagnostic, Memory, Persona, RelicError, Skill
from reliclab.vault import CatalogSnapshot, ModuleSnapshot

from .budget import DEFAULT_COUNTER, TokenCounter, evaluate_budget
from .template import TextBuilder, substitute
from .types import (
    ComposedContext,
    ComposedTool,
    ComposeLimits,
    ComposeRequest,
    CompositionManifest,
    ContextBlock,
    ContextData,
    ModuleSource,
)

DEFAULT_REQUEST = ComposeRequest()
DEFAULT_LIMITS = ComposeLimits()


def source_of(snapshot: ModuleSnapshot) -> ModuleSource:
    return ModuleSource(
        key=snapshot.key, content_hash=snapshot.content_hash, relative_path=snapshot.relative_path
    )


def compose(
    graph: ResolvedGraph,
    request: ComposeRequest = DEFAULT_REQUEST,
    *,
    limits: ComposeLimits = DEFAULT_LIMITS,
    counter: TokenCounter = DEFAULT_COUNTER,
) -> ComposedContext:
    """Build budget-checked Core IR from locked bytes and explicit host input."""
    try:
        request = ComposeRequest.model_validate(request)
        limits = ComposeLimits.model_validate(limits)
        composition = graph.composition
        merged = ComposeRequest(variables={**composition.variables, **request.variables})
    except (ValueError, AssertionError):
        raise RelicError(
            "SCHEMA_INVALID", "Invalid composition request, variables, or limits."
        ) from None
    verified = resolve(
        composition,
        CatalogSnapshot(graph.modules),
        lock=graph.lock,
        max_body_bytes=graph.max_body_bytes,
    )
    if verified != graph:
        raise RelicError("SOURCE_CHANGED", "Resolved graph differs from its locked source bytes.")
    variables = merged.variables
    if len(variables) > limits.max_variables:
        raise RelicError("CONTEXT_OVERFLOW", "Composition exceeds its variable count limit.")
    for value in variables.values():
        try:
            size = len((value if isinstance(value, str) else canonical_json(value)).encode("utf-8"))
        except UnicodeError:
            raise RelicError("SCHEMA_INVALID", "Variables must be valid UTF-8.") from None
        if size > limits.max_variable_bytes:
            raise RelicError("CONTEXT_OVERFLOW", "Variable exceeds its byte limit.")
    selected = set(request.selected_memory_ids)
    available = {item.key.id for item in graph.memory}
    if len(selected) != len(request.selected_memory_ids) or not selected.issubset(available):
        raise RelicError("SCHEMA_INVALID", "Select each declared Memory ID at most once.")
    trusted = {item.key: item.content_hash for item in request.trusted_sources}
    eligible = {item.key: item.content_hash for item in graph.persona_chain + graph.skills}
    if len(trusted) != len(request.trusted_sources) or any(
        eligible.get(key) != value for key, value in trusted.items()
    ):
        raise RelicError(
            "SOURCE_CHANGED", "Trust records must match distinct resolved instruction sources."
        )
    blocks: list[ContextBlock] = []
    tools: dict[str, ComposedTool] = {}
    used_bytes = 0

    def add(snapshot: ModuleSnapshot, text: str, *, required: bool) -> None:
        nonlocal used_bytes
        size = len(text.encode("utf-8"))
        used_bytes += size
        if size > limits.max_block_bytes or used_bytes > limits.max_context_bytes:
            raise RelicError("CONTEXT_OVERFLOW", "Composed blocks exceed the host byte limit.")
        kind = snapshot.key.kind
        assert kind != "composition"
        blocks.append(
            ContextBlock(
                block_id=f"{kind}:{snapshot.key.id}@{snapshot.key.version}",
                kind=kind,
                text=text,
                source_key=snapshot.key,
                source_hash=snapshot.content_hash,
                source_relative_path=snapshot.relative_path,
                required=required,
                trust="instruction" if snapshot.key in trusted else "reference",
                order=len(blocks),
            )
        )

    def expand(snapshot: ModuleSnapshot, text: str, field: str) -> str:
        return substitute(
            text,
            variables,
            source=snapshot.relative_path,
            location=(field,),
            max_bytes=limits.max_block_bytes,
        )

    if graph.persona is not None:
        remaining_values = set(graph.persona.values)
        remaining_constraints = set(graph.persona.constraints)
        for snapshot in graph.persona_chain:
            persona = snapshot.document
            assert isinstance(persona, Persona)
            parts = TextBuilder(limits.max_block_bytes)
            if snapshot.key == graph.persona.key:
                parts.append(
                    "## Identity\n\n" + expand(snapshot, graph.persona.identity, "identity")
                )
                if graph.persona.voice:
                    parts.append("## Voice\n\n" + expand(snapshot, graph.persona.voice, "voice"))
            for title, entries, remaining in (
                ("Values", persona.values, remaining_values),
                ("Constraints", persona.constraints, remaining_constraints),
            ):
                lines = TextBuilder(limits.max_block_bytes, "\n")
                for entry in entries:
                    if entry in remaining:
                        remaining.remove(entry)
                        lines.append("- " + expand(snapshot, entry, title.lower()))
                if lines.parts:
                    parts.append(f"## {title}\n\n" + lines.text())
            sections = [
                section.text for section in graph.persona.sections if section.key == snapshot.key
            ]
            if sections:
                parts.append("## Instructions\n\n" + expand(snapshot, sections[0], "body"))
            if parts.parts:
                add(snapshot, parts.text(), required=True)
    for snapshot in graph.skills:
        skill = snapshot.document
        assert isinstance(skill, Skill)
        parts = TextBuilder(limits.max_block_bytes)
        if skill.trigger:
            parts.append("## Trigger\n\n" + expand(snapshot, skill.trigger, "trigger"))
        parts.append("## Instructions\n\n" + expand(snapshot, skill.body, "body"))
        for index, example in enumerate(skill.examples):
            parts.append(
                f"## Example {index + 1}\n\nInput:\n"
                + expand(snapshot, example.input, "examples")
                + "\n\nOutput:\n"
                + expand(snapshot, example.output, "examples")
            )
        add(snapshot, parts.text(), required=True)
        for requirement in skill.tools:
            source = source_of(snapshot)
            current = tools.get(requirement.name)
            if current is not None:
                if canonical_json(current.requirement.model_dump(mode="json")) != canonical_json(
                    requirement.model_dump(mode="json")
                ):
                    message = "Conflicting declarations for the same tool name."
                    raise RelicError(
                        "VERSION_CONFLICT",
                        message,
                        details=tuple(
                            Diagnostic(
                                code="VERSION_CONFLICT",
                                message=message,
                                source=item.relative_path,
                                location=("tools", requirement.name),
                            )
                            for item in current.sources + (source,)
                        ),
                    )
                sources = (
                    current.sources if source in current.sources else current.sources + (source,)
                )
            else:
                sources = (source,)
            tools[requirement.name] = ComposedTool(
                requirement=requirement,
                sources=sources,
                trust="instruction"
                if all(item.key in trusted for item in sources)
                else "reference",
            )
    for snapshot in graph.memory:
        memory = snapshot.document
        assert isinstance(memory, Memory)
        if memory.scope == "on-demand" and memory.id not in selected:
            continue
        if memory.source != "inline":
            message = (
                "External Memory requires a captured-note adapter; only inline Memory is supported."
            )
            raise RelicError(
                "SCHEMA_INVALID",
                message,
                details=(
                    Diagnostic(
                        code="SCHEMA_INVALID",
                        message=message,
                        source=snapshot.relative_path,
                        location=("source",),
                    ),
                ),
            )
        add(snapshot, memory.body, required=memory.scope == "always")
    manifest = CompositionManifest(
        composition_lock=graph.lock,
        sources=tuple(source_of(item) for item in graph.modules),
        variables=variables,
        selected_memory_ids=tuple(item.key.id for item in graph.memory if item.key.id in selected),
        trusted_sources=tuple(item for item in graph.lock.modules if item.key in trusted),
        limits=limits,
        counter_id=request.counter_id,
    )
    decision = evaluate_budget(
        tuple(blocks),
        tuple(tools.values()),
        token_budget=request.token_budget or composition.render.token_budget,
        counter_id=request.counter_id,
        counter=counter,
    )
    data = ContextData(
        blocks=decision.blocks,
        tools=tuple(tools.values()),
        manifest=manifest,
        budget_report=decision.report,
        diagnostics=decision.diagnostics,
    )
    context = ComposedContext(canonical_json(data.model_dump(mode="json")))
    if len(context.to_json().encode("utf-8")) > limits.max_context_bytes:
        raise RelicError("CONTEXT_OVERFLOW", "Serialized context exceeds the host byte limit.")
    return context
