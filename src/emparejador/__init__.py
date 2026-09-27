"""Public package surface for the emparejador (address matcher).

This package is independent of any other project: it owns its own parsing
grammar and its own scoring logic. It re-exports the small public API that
callers (the CLI, tests, or another program) are expected to use.
"""

from __future__ import annotations

from emparejador.index import AddressIndex, Candidate, LinkResult
from emparejador.matcher import (
    DEFAULT_PLATE_TOLERANCE,
    DEFAULT_THRESHOLD,
    FieldComparison,
    InvalidThresholdError,
    InvalidToleranceError,
    MatchResult,
    match,
    match_parsed,
)
from emparejador.parser import CanonicalAddress, clean_text, parse_canonical, render

__all__ = [
    "DEFAULT_PLATE_TOLERANCE",
    "DEFAULT_THRESHOLD",
    "AddressIndex",
    "Candidate",
    "CanonicalAddress",
    "FieldComparison",
    "InvalidThresholdError",
    "InvalidToleranceError",
    "LinkResult",
    "MatchResult",
    "clean_text",
    "match",
    "match_parsed",
    "parse_canonical",
    "render",
]
