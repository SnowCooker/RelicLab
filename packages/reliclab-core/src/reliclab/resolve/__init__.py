"""Deterministic version selection, Persona inheritance, and composition locks."""

from reliclab.vault import CatalogSnapshot

from .engine import resolve
from .types import (
    CompositionLock,
    EffectivePersona,
    LockedModule,
    PersonaSection,
    ResolutionError,
    ResolvedGraph,
)

__all__ = [
    "CatalogSnapshot",
    "CompositionLock",
    "EffectivePersona",
    "LockedModule",
    "PersonaSection",
    "ResolvedGraph",
    "ResolutionError",
    "resolve",
]
