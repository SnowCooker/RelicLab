"""Pure typed reference resolution, inheritance, and strict lock replay."""

from pydantic import ValidationError
from semver import Version

from reliclab.schema import Composition, ModuleKey, Persona, RelicError, validate_module
from reliclab.schema.models import Kind
from reliclab.schema.validation import ErrorCode
from reliclab.vault import CatalogSnapshot, ModuleSnapshot

from .selectors import matches
from .types import (
    CompositionLock,
    EffectivePersona,
    LockedModule,
    PersonaSection,
    ResolutionError,
    ResolvedGraph,
    canonical_json,
    digest,
)

MAX_RESOLVED_MODULES = 10000


def resolve(
    composition: Composition,
    catalog: CatalogSnapshot,
    *,
    lock: CompositionLock | None = None,
    max_body_bytes: int = 1024 * 1024,
) -> ResolvedGraph:
    """Resolve afresh without a lock, or replay exact locked keys and hashes."""
    document = validate_module(composition, max_body_bytes=max_body_bytes)
    if not isinstance(document, Composition):
        raise RelicError("SCHEMA_INVALID", "Resolution requires a Composition.")
    composition_json = canonical_json(document.model_dump(mode="json"))
    composition_hash = digest(composition_json)
    root: tuple[str, ...] = (f"composition:{document.id}@{document.version}",)
    selected_count = len(document.modules.skills) + len(document.modules.memory)
    if selected_count + (document.modules.persona is not None) > MAX_RESOLVED_MODULES:
        raise ResolutionError("CONTEXT_OVERFLOW", "Resolution exceeds the module limit.", root)
    if lock is not None:
        try:
            lock = CompositionLock.model_validate(lock)
        except ValidationError:
            raise ResolutionError("SCHEMA_INVALID", "Invalid composition lock.", root) from None
        if lock.composition_hash != composition_hash:
            raise ResolutionError("SOURCE_CHANGED", "Composition differs from its lock.", root)
    pinned = {(item.key.kind, item.key.id): item for item in lock.modules} if lock else {}
    by_id: dict[tuple[str, str], list[ModuleSnapshot]] = {}
    for item in catalog.modules:
        by_id.setdefault((item.key.kind, item.key.id), []).append(item)

    def select(kind: Kind, reference: str, chain: tuple[str, ...]) -> ModuleSnapshot:
        identifier, _, selector = reference.partition("@")
        candidates = by_id.get((kind, identifier), [])
        if lock is not None:
            entry = pinned.get((kind, identifier))
            selected = next((item for item in candidates if entry and item.key == entry.key), None)
            if (
                entry is None
                or selected is None
                or selected.content_hash != entry.content_hash
                or not matches(selector, selected.key.version)
            ):
                raise ResolutionError(
                    "SOURCE_CHANGED", "Locked source is missing or changed.", chain
                )
            return selected
        matching = [item for item in candidates if matches(selector, item.key.version)]
        if not matching:
            if not candidates and any(item.key.id == identifier for item in catalog.modules):
                raise ResolutionError(
                    "VERSION_CONFLICT", "Reference exists only in another kind.", chain
                )
            raise ResolutionError("NOT_FOUND", "No version satisfies the typed reference.", chain)
        highest = max(Version.parse(item.key.version) for item in matching)
        best = [item for item in matching if Version.parse(item.key.version) == highest]
        if len(best) != 1:
            raise ResolutionError(
                "VERSION_CONFLICT",
                "Equal-precedence versions are ambiguous; pin an exact version.",
                chain,
            )
        return best[0]

    ancestors: list[ModuleSnapshot] = []
    seen: dict[str, ModuleKey] = {}
    chain = root
    reference = document.modules.persona
    while reference is not None:
        chain += (f"persona:{reference}",)
        selected = select("persona", reference, chain)
        if selected.key.id in seen:
            code: ErrorCode = (
                "DEPENDENCY_CYCLE" if seen[selected.key.id] == selected.key else "VERSION_CONFLICT"
            )
            raise ResolutionError(code, "Persona inheritance repeats a typed module ID.", chain)
        if len(ancestors) >= 32:
            raise ResolutionError(
                "VERSION_CONFLICT", "Persona inheritance exceeds 32 modules.", chain
            )
        seen[selected.key.id] = selected.key
        ancestors.append(selected)
        persona = selected.document
        assert isinstance(persona, Persona)
        reference = persona.extends
    ordered = tuple(reversed(ancestors))
    if len(ordered) + selected_count > MAX_RESOLVED_MODULES:
        raise ResolutionError("CONTEXT_OVERFLOW", "Resolution exceeds the module limit.", chain)
    effective = None
    if ordered:
        personas = [item.document for item in ordered]
        values: list[str] = []
        constraints: list[str] = []
        sections: list[PersonaSection] = []
        for parent in personas:
            assert isinstance(parent, Persona)
            values.extend(parent.values)
            constraints.extend(parent.constraints)
            if parent.body:
                sections.append(PersonaSection(parent.key, parent.body))
        leaf = personas[-1]
        assert isinstance(leaf, Persona)
        effective = EffectivePersona(
            leaf.key,
            leaf.identity,
            leaf.voice,
            tuple(dict.fromkeys(values)),
            tuple(dict.fromkeys(constraints)),
            tuple(sections),
        )
        if len(effective.body.encode("utf-8")) > max_body_bytes:
            raise ResolutionError(
                "CONTEXT_OVERFLOW", "Inherited persona body exceeds the host byte limit.", chain
            )
    skills = tuple(
        select("skill", ref, root + (f"skill:{ref}",)) for ref in document.modules.skills
    )
    memory = tuple(
        select("memory", ref, root + (f"memory:{ref}",)) for ref in document.modules.memory
    )
    generated = CompositionLock(
        composition_hash=composition_hash,
        modules=tuple(
            LockedModule(key=item.key, content_hash=item.content_hash)
            for item in ordered + skills + memory
        ),
    )
    generated.to_json()
    if lock is not None and generated != lock:
        raise ResolutionError(
            "SOURCE_CHANGED", "Lock entries do not match the ordered dependency graph.", root
        )
    return ResolvedGraph(
        composition_json, ordered, skills, memory, effective, generated, max_body_bytes
    )
