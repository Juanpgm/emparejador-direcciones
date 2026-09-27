"""Pairwise scoring and matching for two already-normalized cadastral addresses.

Design: weighted averages dilute as fields are added (one wrong street
letter would still score around 0.94 out of many fields), so this module
instead multiplies survival factors: ``score = round(prod(1 - p_i), 4)``
over every field that differs, and any hard veto forces ``score = 0.0``
regardless of the product. See the project plan for the full penalty
table and the proof that no reachable score lands in the (0.85, 0.9126)
dead band around the default 0.90 threshold.

Plate vetoes: a plate on only one side, a plate difference beyond
``plate_tolerance``, and a plate *letter* that differs (for example
``KR 1 # 9 - 80 A`` vs ``KR 1 # 9 - 80``: a lettered plate is a different
corner/unit, not the same parcel) are all hard vetoes.

Open-ended addresses: when both sides lack a plate, or both lack a cross
number, the verdict is unchanged (missing on both sides is agreement), but
``MatchResult.warnings`` carries ``sin_placa`` / ``sin_cruce`` so callers
can tell the comparison rested on less structure than usual.

Bad address input (``None``, empty, garbage, unparseable) never raises:
it is scored as a parse-failure veto. Bad settings (``threshold``,
``plate_tolerance``) do raise, since those are programming errors, not
user data.

Opaque complements: a complement chunk whose kind is not a registered
``COMPLEMENT_KINDS`` code (a raw cadastral tail such as ``8 C`` or
``GASS 5``) is compared for equality only. Equal on both sides is exact,
different on both sides is a veto, and present on ONE side only costs the
regular one-sided penalty (0.15) instead of the cheap 0.02, so an
unstructured tail never auto-links to the bare address. Any opaque chunk on
either side adds the warning ``complemento_no_estructurado``. A registered
kind with no usable value (``LT`` alone, ``AP NORTE``) is treated the same
way.

Zero runtime dependencies (only the standard library and this project's
own ``parser`` module).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from emparejador.parser import (
    COMPLEMENT_KINDS,
    MAX_PLATE_DIGITS,
    OPAQUE_KIND,
    QUADRANTS,
    CanonicalAddress,
    parse_canonical,
    render,
)

__all__ = [
    "DEFAULT_PLATE_TOLERANCE",
    "DEFAULT_THRESHOLD",
    "FieldComparison",
    "InvalidThresholdError",
    "InvalidToleranceError",
    "MAX_PLATE_DIGITS",
    "MatchResult",
    "match",
    "match_parsed",
]

DEFAULT_THRESHOLD = 0.90
DEFAULT_PLATE_TOLERANCE = 0

# Field names that carry a hard veto when both sides are present and differ.
_HARD_VETO_FIELDS = ("via_type", "via_number", "cross_number")

# Field names that use the "one-sided 0.15 / conflict 0.30" soft penalty.
_SOFT_STRUCTURAL_FIELDS = (
    "via_letters",
    "via_suffix",
    "via_suffix_letters",
    "via_quadrant",
    "cross_letters",
    "cross_suffix",
    "cross_suffix_letters",
    "cross_quadrant",
)

# Field names that use the "one-sided 0.15, no conflict case" boolean penalty.
_BIS_FIELDS = ("via_bis", "cross_bis")

# The ONE registry of survival penalties. ``_score`` charges every penalty by
# reading this mapping at the point of application, and the dead-band proof
# in ``tests/test_matcher_review.py`` enumerates the reachable scores from
# it. Do not add a module-level ``_*_PENALTY`` constant: a test fails for any
# penalty that is not registered here.
_PENALTIES: dict[str, float] = {
    "one_sided": 0.15,
    "conflict": 0.30,
    "cross_type_one_sided": 0.03,
    "cross_type_conflict": 0.30,
    "plate_tolerance": 0.04,
    "complement_one_sided": 0.02,
}


class InvalidThresholdError(ValueError):
    """Raised when ``threshold`` is outside [0, 1] or is NaN."""


class InvalidToleranceError(ValueError):
    """Raised when ``plate_tolerance`` is negative or not an int."""


@dataclass(frozen=True)
class FieldComparison:
    """Outcome of comparing one field between two parsed addresses."""

    field: str
    a: str | None
    b: str | None
    status: str
    penalty: float
    veto: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "a": self.a,
            "b": self.b,
            "status": self.status,
            "penalty": self.penalty,
            "veto": self.veto,
        }


@dataclass(frozen=True)
class MatchResult:
    """Outcome of comparing two addresses."""

    is_match: bool
    score: float
    threshold: float
    reason: str
    parsed_a: CanonicalAddress
    parsed_b: CanonicalAddress
    fields: tuple[FieldComparison, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "is_match": self.is_match,
            "score": self.score,
            "threshold": self.threshold,
            "reason": self.reason,
            "parsed_a": _address_to_dict(self.parsed_a),
            "parsed_b": _address_to_dict(self.parsed_b),
            "fields": [f.to_dict() for f in self.fields],
            "warnings": list(self.warnings),
        }


_ADDRESS_FIELD_NAMES = (
    "via_type",
    "via_number",
    "via_letters",
    "via_suffix",
    "via_suffix_letters",
    "via_bis",
    "via_quadrant",
    "cross_type",
    "cross_number",
    "cross_letters",
    "cross_suffix",
    "cross_suffix_letters",
    "cross_bis",
    "cross_quadrant",
    "plate",
    "complement",
)


def _address_to_dict(addr: CanonicalAddress) -> dict[str, object]:
    """Build the JSON-friendly shape for one parsed address: the original
    input, whether it parsed, its rendered canonical form (falling back to
    the raw input when parsing failed), every ``CanonicalAddress`` field,
    and the parser's notes."""
    fields: dict[str, object] = {}
    for name in _ADDRESS_FIELD_NAMES:
        value = getattr(addr, name)
        fields[name] = list(value) if name == "complement" else value
    return {
        "input": addr.raw,
        "parse_ok": addr.parse_ok,
        "canonical": render(addr),
        "fields": fields,
        "notes": list(addr.notes),
    }


def _passes(score: float, threshold: float) -> bool:
    """Pure helper: does ``score`` clear ``threshold``."""
    return score >= threshold


def _validate_threshold(threshold: object) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise InvalidThresholdError(f"umbral inválido (tipo no numérico): {threshold!r}")
    value = float(threshold)
    if math.isnan(value):
        raise InvalidThresholdError("umbral inválido: NaN")
    if value < 0.0 or value > 1.0:
        raise InvalidThresholdError(f"umbral fuera de rango [0,1]: {value}")
    return value


def _validate_plate_tolerance(tolerance: object) -> int:
    if isinstance(tolerance, bool) or not isinstance(tolerance, int):
        raise InvalidToleranceError(f"tolerancia de placa inválida (debe ser entero): {tolerance!r}")
    if tolerance < 0:
        raise InvalidToleranceError(f"tolerancia de placa negativa: {tolerance}")
    return tolerance


def _compare_soft_structural(
    name: str, a: CanonicalAddress, b: CanonicalAddress
) -> FieldComparison:
    val_a = getattr(a, name)
    val_b = getattr(b, name)
    if val_a is None and val_b is None:
        return FieldComparison(name, val_a, val_b, "ausente_en_ambos", 0.0, False)
    if val_a == val_b:
        return FieldComparison(name, val_a, val_b, "igual", 0.0, False)
    if val_a is None or val_b is None:
        return FieldComparison(name, val_a, val_b, "solo_en_uno", _PENALTIES["one_sided"], False)
    return FieldComparison(name, val_a, val_b, "difiere", _PENALTIES["conflict"], False)


def _compare_bis(name: str, a: CanonicalAddress, b: CanonicalAddress) -> FieldComparison:
    val_a = bool(getattr(a, name))
    val_b = bool(getattr(b, name))
    label_a = "BIS" if val_a else None
    label_b = "BIS" if val_b else None
    if val_a == val_b:
        status = "ausente_en_ambos" if not val_a else "igual"
        return FieldComparison(name, label_a, label_b, status, 0.0, False)
    return FieldComparison(name, label_a, label_b, "solo_en_uno", _PENALTIES["one_sided"], False)


def _compare_hard_veto(name: str, a: CanonicalAddress, b: CanonicalAddress) -> FieldComparison:
    val_a = getattr(a, name)
    val_b = getattr(b, name)
    if val_a is None and val_b is None:
        return FieldComparison(name, val_a, val_b, "ausente_en_ambos", 0.0, False)
    if val_a == val_b:
        return FieldComparison(name, val_a, val_b, "igual", 0.0, False)
    if val_a is None or val_b is None:
        # cross_number missing on one side means "no cross street given",
        # which is itself a structural mismatch for this grammar.
        return FieldComparison(name, val_a, val_b, "solo_en_uno", 0.0, True)
    return FieldComparison(name, val_a, val_b, "difiere", 0.0, True)


def _compare_cross_type(a: CanonicalAddress, b: CanonicalAddress) -> FieldComparison:
    val_a = a.cross_type
    val_b = b.cross_type
    if val_a is None and val_b is None:
        return FieldComparison("cross_type", val_a, val_b, "ausente_en_ambos", 0.0, False)
    if val_a == val_b:
        return FieldComparison("cross_type", val_a, val_b, "igual", 0.0, False)
    if val_a is None or val_b is None:
        return FieldComparison(
            "cross_type", val_a, val_b, "solo_en_uno", _PENALTIES["cross_type_one_sided"], False
        )
    return FieldComparison(
        "cross_type", val_a, val_b, "difiere", _PENALTIES["cross_type_conflict"], False
    )


# The parser already rejects plates with more than ``MAX_PLATE_DIGITS``
# significant digits (finding 1); the same shared constant is checked again
# in ``_compare_plate`` in case a hand-built ``CanonicalAddress`` reaches it
# unchecked, so this module never converts an unbounded digit string to int.


def _compare_plate(
    a: CanonicalAddress, b: CanonicalAddress, plate_tolerance: int
) -> FieldComparison:
    val_a = a.plate
    val_b = b.plate
    if val_a is None and val_b is None:
        return FieldComparison("plate", val_a, val_b, "ausente_en_ambos", 0.0, False)
    if val_a is None or val_b is None:
        # A plate on only one side means one address is a corner (no
        # parcel), not the same parcel: hard veto.
        return FieldComparison("plate", val_a, val_b, "solo_en_uno", 0.0, True)
    if val_a == val_b:
        return FieldComparison("plate", val_a, val_b, "igual", 0.0, False)
    digits_a, letter_a = _split_plate(val_a)
    digits_b, letter_b = _split_plate(val_b)
    if letter_a != letter_b:
        # A plate letter marks a different corner/unit, not the same
        # parcel (e.g. "80" vs "80 A"): hard veto (finding 4/10).
        return FieldComparison("plate", val_a, val_b, "difiere", 0.0, True)
    if digits_a == digits_b:
        return FieldComparison("plate", val_a, val_b, "equivalente", 0.0, False)
    if (
        len(digits_a) > MAX_PLATE_DIGITS
        or len(digits_b) > MAX_PLATE_DIGITS
    ):
        return FieldComparison("plate", val_a, val_b, "difiere", 0.0, True)
    diff = abs(int(digits_a) - int(digits_b))
    if diff <= plate_tolerance:
        return FieldComparison(
            "plate", val_a, val_b, "dentro_tolerancia", _PENALTIES["plate_tolerance"], False
        )
    return FieldComparison("plate", val_a, val_b, "difiere", 0.0, True)


def _split_plate(plate: str) -> tuple[str, str]:
    """Split a plate token into its zero-stripped digit part and its
    optional trailing letter, without ever calling ``int()`` on a
    potentially unbounded digit string (finding 1)."""
    if plate and plate[-1].isalpha():
        digits, letter = plate[:-1], plate[-1]
    else:
        digits, letter = plate, ""
    stripped = digits.lstrip("0") or "0"
    return stripped, letter


def _is_opaque_chunk(kind: str, value: str) -> bool:
    """True when a chunk carries no usable structure.

    That is an unregistered kind, or a registered kind whose value is empty
    (``LT`` alone) or made only of quadrant words (``AP NORTE``): the value
    says nothing about which unit the chunk names, so it must not link to the
    bare address at the cheap known-complement price.
    """
    if kind not in COMPLEMENT_KINDS:
        return True
    return value == "" or all(part in QUADRANTS for part in value.split("/"))


def _has_opaque_chunk(chunks: tuple[tuple[str, str], ...]) -> bool:
    """True when any chunk is opaque (see ``_is_opaque_chunk``)."""
    return any(_is_opaque_chunk(kind, value) for kind, value in chunks)


def _render_complement_chunks(chunks: tuple[tuple[str, str], ...]) -> str | None:
    """Render complement chunks as ``"KIND VALUE"`` pairs, joined by ``, ``,
    for human-readable comparisons and veto reasons (finding 10) instead
    of a raw tuple repr."""
    if not chunks:
        return None
    return ", ".join(
        (value if kind == OPAQUE_KIND else f"{kind} {value}").strip() for kind, value in sorted(chunks)
    )


def _compare_complement(a: CanonicalAddress, b: CanonicalAddress) -> FieldComparison:
    """Compare complement chunk multisets.

    The parser already normalizes each side's complement (aliases resolved,
    leading zeros stripped, chunks sorted), so chunks are compared as sorted
    tuples: order does not matter but a repeated chunk (``AP 1 AP 1``)
    counts. Only four cases remain: both empty (agreement); exactly equal (agreement); one
    side empty (a soft one-sided penalty, since a parcel can still match
    even if only one record specifies a unit; 0.15 instead of 0.02 when
    the present side has an opaque chunk); or anything else (a hard
    veto — a differing value for a shared kind and an extra kind on only
    one side both mean the two sides disagree about what complement the
    parcel has, so both collapse to the same "difiere" outcome).
    """
    set_a = tuple(sorted(a.complement))
    set_b = tuple(sorted(b.complement))
    rendered_a = _render_complement_chunks(a.complement)
    rendered_b = _render_complement_chunks(b.complement)
    if not set_a and not set_b:
        return FieldComparison("complement", rendered_a, rendered_b, "ausente_en_ambos", 0.0, False)
    if set_a == set_b:
        return FieldComparison("complement", rendered_a, rendered_b, "igual", 0.0, False)
    if not set_a or not set_b:
        present = a.complement or b.complement
        penalty = _PENALTIES["one_sided"] if _has_opaque_chunk(present) else _PENALTIES["complement_one_sided"]
        return FieldComparison("complement", rendered_a, rendered_b, "solo_en_uno", penalty, False)
    return FieldComparison("complement", rendered_a, rendered_b, "difiere", 0.0, True)


def _parse_failure_result(
    a: CanonicalAddress, b: CanonicalAddress, threshold: float
) -> MatchResult:
    notes: list[str] = []
    if not a.parse_ok:
        notes.append(f"dirección A no canónica ({', '.join(a.notes) or 'inválida'})")
    if not b.parse_ok:
        notes.append(f"dirección B no canónica ({', '.join(b.notes) or 'inválida'})")
    reason = "veto: " + "; ".join(notes)
    return MatchResult(
        is_match=False,
        score=0.0,
        threshold=threshold,
        reason=reason,
        parsed_a=a,
        parsed_b=b,
        fields=(),
        warnings=(),
    )


def match(
    a: object,
    b: object,
    threshold: float = DEFAULT_THRESHOLD,
    plate_tolerance: int = DEFAULT_PLATE_TOLERANCE,
) -> MatchResult:
    """Compare two (ideally already-normalized) address strings.

    Never raises on bad address input: unparseable input on either side
    is scored as a veto (score 0.0, no match). Raises
    ``InvalidThresholdError`` / ``InvalidToleranceError`` for bad settings.
    """
    validated_threshold = _validate_threshold(threshold)
    validated_tolerance = _validate_plate_tolerance(plate_tolerance)
    return _score(parse_canonical(a), parse_canonical(b), validated_threshold, validated_tolerance)


def match_parsed(
    a: CanonicalAddress,
    b: CanonicalAddress,
    threshold: float = DEFAULT_THRESHOLD,
    plate_tolerance: int = DEFAULT_PLATE_TOLERANCE,
) -> MatchResult:
    """Same as ``match`` for addresses that are already parsed.

    Lets callers that compare one address against many (see
    ``emparejador.index``) parse each address once. Settings are validated
    exactly like ``match``.
    """
    validated_threshold = _validate_threshold(threshold)
    validated_tolerance = _validate_plate_tolerance(plate_tolerance)
    return _score(a, b, validated_threshold, validated_tolerance)


def _score(
    parsed_a: CanonicalAddress,
    parsed_b: CanonicalAddress,
    validated_threshold: float,
    validated_tolerance: int,
) -> MatchResult:
    if not parsed_a.parse_ok or not parsed_b.parse_ok:
        return _parse_failure_result(parsed_a, parsed_b, validated_threshold)

    comparisons: list[FieldComparison] = []
    for name in _HARD_VETO_FIELDS:
        comparisons.append(_compare_hard_veto(name, parsed_a, parsed_b))
    comparisons.append(_compare_plate(parsed_a, parsed_b, validated_tolerance))
    comparisons.append(_compare_complement(parsed_a, parsed_b))
    for name in _SOFT_STRUCTURAL_FIELDS:
        comparisons.append(_compare_soft_structural(name, parsed_a, parsed_b))
    for name in _BIS_FIELDS:
        comparisons.append(_compare_bis(name, parsed_a, parsed_b))
    comparisons.append(_compare_cross_type(parsed_a, parsed_b))

    # Open-ended addresses (finding 8): missing on both sides is scored as
    # agreement, per the field table, but it is still worth flagging that
    # the comparison rests on less structure than usual.
    by_field = {c.field: c for c in comparisons}
    warnings: list[str] = []
    if by_field["plate"].status == "ausente_en_ambos":
        warnings.append("sin_placa")
    if by_field["cross_number"].status == "ausente_en_ambos":
        warnings.append("sin_cruce")
    if _has_opaque_chunk(parsed_a.complement) or _has_opaque_chunk(parsed_b.complement):
        warnings.append("complemento_no_estructurado")
    result_warnings = tuple(warnings)

    vetoed_fields = [c for c in comparisons if c.veto]
    if vetoed_fields:
        reason = "veto: " + "; ".join(_veto_reason(c) for c in vetoed_fields)
        return MatchResult(
            is_match=False,
            score=0.0,
            threshold=validated_threshold,
            reason=reason,
            parsed_a=parsed_a,
            parsed_b=parsed_b,
            fields=tuple(comparisons),
            warnings=result_warnings,
        )

    score = 1.0
    for comparison in comparisons:
        score *= 1.0 - comparison.penalty
    score = round(score, 4)

    is_match = _passes(score, validated_threshold)
    reason = _build_reason(score, validated_threshold, comparisons, is_match)

    return MatchResult(
        is_match=is_match,
        score=score,
        threshold=validated_threshold,
        reason=reason,
        parsed_a=parsed_a,
        parsed_b=parsed_b,
        fields=tuple(comparisons),
        warnings=result_warnings,
    )


def _veto_reason(comparison: FieldComparison) -> str:
    label = _FIELD_LABELS.get(comparison.field, comparison.field)
    if comparison.status == "solo_en_uno":
        return f"{label} presente solo en un lado"
    return f"{label} difiere ({comparison.a} vs {comparison.b})"


_FIELD_LABELS: dict[str, str] = {
    "via_type": "tipo de vía",
    "via_number": "número de vía",
    "cross_number": "número de vía generadora",
    "plate": "placa",
    "complement": "complemento",
}


def _build_reason(
    score: float, threshold: float, comparisons: list[FieldComparison], is_match: bool
) -> str:
    # Only fields with an actual, nonzero penalty should show up as
    # "differences" in the reason text: status "equivalente" (e.g. plate
    # "80" vs "080") carries zero penalty and must still read as an exact
    # match, since it does not affect the score at all.
    differing = [c for c in comparisons if c.penalty > 0.0]
    if not differing:
        return "coincidencia exacta"
    if is_match:
        names = ", ".join(c.field for c in differing)
        return f"coincide; diferencias menores: {names}"
    names = ", ".join(_describe_difference(c) for c in differing)
    return f"puntaje {score:.4f} < umbral {threshold:g}: {names}"


def _describe_difference(comparison: FieldComparison) -> str:
    if comparison.status == "solo_en_uno":
        return f"{comparison.field} solo en un lado"
    return f"{comparison.field} difiere"
