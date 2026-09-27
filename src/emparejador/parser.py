"""Own strict-grammar parser for already-normalized Cali cadastral addresses.

This module is deliberately independent from any other project. It only
knows about the canonical grammar described in the project plan:

    SEGMENT := [TYPE] NUMBER [LETTER] [SUFFIX_NUMBER [SUFFIX_LETTER]] [BIS] [QUADRANT]
    ADDRESS := SEGMENT_VIA "#" [SEGMENT_CROSS] ["-" [PLATE]] [COMPLEMENT...]

The cadastre stores raw addresses, so the grammar also accepts legacy
single-letter via types (``K``/``C``/``A``/``D``/``T``), a trailing empty
plate (``# 74 -``), a complement sitting in the plate slot (``- LT 20``),
single-letter quadrants after a street letter (``C 70 B N``) and opaque
complement tails that are kept as unstructured chunks.

The parser has two layers:

1. ``clean_text`` — trivial text hygiene (uppercasing, accent stripping,
   dash/marker normalization, glued-token splitting). It does not attempt
   to repair malformed input: anything the strict grammar cannot consume
   is reported as a parse failure with a note, never fixed up.
2. ``parse_canonical`` — a small hand-written tokenizer/grammar that
   consumes the cleaned text left to right and never raises on bad
   address input; failures are represented in the returned
   ``CanonicalAddress`` via ``parse_ok=False`` and ``notes``.

Only the standard library is used (``re``, ``unicodedata``, ``dataclasses``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "COMPLEMENT_KINDS",
    "MAX_PLATE_DIGITS",
    "OPAQUE_KIND",
    "QUADRANTS",
    "VIA_TYPES",
    "CanonicalAddress",
    "clean_text",
    "parse_canonical",
    "render",
]


# ---------------------------------------------------------------------------
# Alias tables (own, small, deliberately short)
# ---------------------------------------------------------------------------

# Maps every accepted spelling of a via type to its canonical two-letter code.
VIA_TYPES: dict[str, str] = {
    "CL": "CL",
    "CALLE": "CL",
    "CLL": "CL",
    "CLLE": "CL",
    "C": "CL",
    "KR": "KR",
    "CARRERA": "KR",
    "CRA": "KR",
    "KRA": "KR",
    "CR": "KR",
    "K": "KR",
    "AV": "AV",
    "AVENIDA": "AV",
    "A": "AV",
    "AC": "AC",
    "AK": "AK",
    "DG": "DG",
    "DIAGONAL": "DG",
    "D": "DG",
    "TV": "TV",
    "TRANSVERSAL": "TV",
    "T": "TV",
    "PJ": "PJ",
    "PASAJE": "PJ",
    "PS": "PS",
    "PASEO": "PS",
    "CV": "CV",
    "CIRCUNVALAR": "CV",
    "AU": "AU",
    "AUTOPISTA": "AU",
    "CT": "CT",
    "CALLEJON": "CT",
}

# "AVENIDA CALLE" / "AVENIDA CARRERA" are two-word aliases, handled specially
# in _consume_via_type below because the alias table above is single-token.
_TWO_WORD_VIA_ALIASES: dict[tuple[str, str], str] = {
    ("AVENIDA", "CALLE"): "AC",
    ("AVENIDA", "CARRERA"): "AK",
}

# Quadrant spellings. Only >=3-letter words are quadrants: single letters
# (e.g. "KR 41 E") are street letters, not quadrants.
QUADRANTS: frozenset[str] = frozenset({"NORTE", "SUR", "ESTE", "OESTE"})

# Legacy single-letter quadrant abbreviations. They are quadrants ONLY when
# the segment already carries a letter/suffix/suffix letter/BIS before them
# (``C 70 B N``); directly after the street number they stay street letters
# (``KR 41 E``).
_QUADRANT_ABBREVIATIONS: dict[str, str] = {
    "N": "NORTE",
    "S": "SUR",
    "E": "ESTE",
    "O": "OESTE",
    "W": "OESTE",
}

# Kind used for a complement tail that starts with a digit (``8 C``): there
# is no kind token to key on, so the chunk is keyed by this literal marker.
OPAQUE_KIND = "?"

# A complement tail longer than this (cleaned tokens joined by single
# spaces) is bad input, not a complement.
_MAX_TAIL_CHARS = 40

# Complement kind aliases, mapped to their canonical short code.
COMPLEMENT_KINDS: dict[str, str] = {
    "AP": "AP",
    "APTO": "AP",
    "APARTAMENTO": "AP",
    "TO": "TO",
    "TORRE": "TO",
    "LC": "LC",
    "LOCAL": "LC",
    "CA": "CA",
    "CASA": "CA",
    "ET": "ET",
    "ETAPA": "ET",
    "PISO": "PISO",
    "BLQ": "BLQ",
    "BLOQUE": "BLQ",
    "BL": "BLQ",
    "MZ": "MZ",
    "MANZANA": "MZ",
    "LT": "LT",
    "LOTE": "LT",
    "PH": "PH",
    "OF": "OF",
    "OFICINA": "OF",
    "ED": "ED",
    "EDIFICIO": "ED",
    "CONJ": "CONJ",
    "CONJUNTO": "CONJ",
    "UR": "UR",
    "URBANIZACION": "UR",
    "INT": "INT",
    "INTERIOR": "INT",
    "PQ": "PQ",
    "PARQUEADERO": "PQ",
    "GA": "GA",
    "GARAJE": "GA",
    "BG": "BG",
    "BODEGA": "BG",
    "BR": "BR",
    "BARRIO": "BR",
    "CGTO": "CGTO",
    "CORREGIMIENTO": "CGTO",
    "VDA": "VDA",
    "VEREDA": "VDA",
}


@dataclass(frozen=True, slots=True)
class CanonicalAddress:
    """Structured result of parsing one canonical address string.

    ``plate`` is ``None`` for addresses without a plate (a corner, a
    trailing ``-`` or a complement in the plate slot). ``complement`` holds
    ``(kind, value)`` chunks; a kind outside ``COMPLEMENT_KINDS`` marks an
    opaque (unstructured) chunk, with kind ``OPAQUE_KIND`` when the tail
    starts with a digit.

    ``parse_ok`` tells whether the strict grammar consumed the whole
    input. When it is ``False``, the field values may be partial or
    ``None`` and ``notes`` explains why parsing stopped.
    """

    raw: str
    parse_ok: bool
    notes: tuple[str, ...]
    via_type: str | None = None
    via_number: str | None = None
    via_letters: str | None = None
    via_suffix: str | None = None
    via_suffix_letters: str | None = None
    via_bis: bool = False
    via_quadrant: str | None = None
    cross_type: str | None = None
    cross_number: str | None = None
    cross_letters: str | None = None
    cross_suffix: str | None = None
    cross_suffix_letters: str | None = None
    cross_bis: bool = False
    cross_quadrant: str | None = None
    plate: str | None = None
    complement: tuple[tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------
# Layer 1: cleanup
# ---------------------------------------------------------------------------

_DASH_VARIANTS = re.compile(r"[‐-―−]")  # hyphen/dash variants incl. en/em dash, minus sign
_WHITESPACE = re.compile(r"\s+")
# The masculine ordinal indicator "º" decomposes (NFKD) to a plain "o"
# before this check runs, so "Nº" arrives here as the token "NO". The
# degree sign "°" has no such decomposition and survives as a symbol.
_DEGREE_SIGN = "°"


def _map_hash_marker(token: str) -> bool:
    """Return True when ``token`` is a spelling of ``Nº``/``No.``/``NRO``/``NUM``."""
    core = token[:-1] if token.endswith(".") else token
    if core in {"NO", "NRO", "NUM"}:
        return True
    if core == f"N{_DEGREE_SIGN}":
        return True
    return False


def clean_text(raw: str) -> str:
    """Apply light, own hygiene to ``raw`` so minor formatting slips are
    accepted by the strict grammar below.

    This is intentionally shallow: uppercase, strip accents, unify dash
    variants to ``-``, normalize ``Nº``/``No.``/``NRO``/``NUM`` markers to
    ``#``, split glued letter/digit runs, strip trailing dots on tokens,
    collapse doubled adjacent ``#``/``-`` separators, and collapse whitespace. It does not recover missing separators,
    strip city noise, fix typos, or split multiple addresses: those are
    left for the grammar layer to reject as parse failures.
    """
    # NFKD first, then uppercase: some compatibility decompositions produce
    # lowercase base characters (e.g. masculine ordinal indicator "º" -> "o"),
    # which must still be uppercased afterwards.
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = _DASH_VARIANTS.sub("-", text)
    # Ensure separators are surrounded by spaces so tokenization is simple.
    text = re.sub(r"\s*#\s*", " # ", text)
    text = re.sub(r"\s*-\s*", " - ", text)
    tokens = text.split()
    out_tokens: list[str] = []
    for token in tokens:
        if token in {"#", "-"}:
            out_tokens.append(token)
            continue
        if _map_hash_marker(token):
            out_tokens.append("#")
            continue
        # Strip a trailing dot on an ordinary token (e.g. "CRA." -> "CRA").
        if token.endswith(".") and len(token) > 1:
            token = token[:-1]
        out_tokens.append(_split_glued(token))
    collapsed: list[str] = []
    for token in out_tokens:
        # Doubled adjacent separators are noise: "# #" -> "#", "- -" -> "-".
        if token in {"#", "-"} and collapsed and collapsed[-1] == token:
            continue
        collapsed.append(token)
    text = " ".join(collapsed)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def _split_glued(token: str) -> str:
    """Split a single alphanumeric token into space-separated runs.

    Examples: ``98F`` -> ``98 F``; ``CL12`` -> ``CL 12``; ``1A`` -> ``1 A``.
    Only alternates once per boundary since tokens in this grammar never
    mix more than two runs (type+number, or number+letters).
    """
    # Insert a boundary between a digit run and a following letter run,
    # and between a letter run and a following digit run. [0-9] (not \d) is
    # used deliberately so non-ASCII digits are never silently accepted
    # here either (finding 9): they are rejected the same way at the
    # grammar layer below.
    result = re.sub(r"([0-9])([A-Z])", r"\1 \2", token)
    result = re.sub(r"([A-Z])([0-9])", r"\1 \2", result)
    return result


# ---------------------------------------------------------------------------
# Layer 2: strict tokenizer/grammar
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"^[0-9]+$")
_LETTER_RE = re.compile(r"^[A-Z]$")

# Real cadastral plates are a handful of digits; anything beyond this many
# significant digits (after stripping leading zeros) is not a plate, it is
# bad input. Capping here also keeps every later int() conversion on a
# plate value safe: Python refuses to convert digit strings past its own
# integer-string-conversion limit (finding 1). ``matcher`` and ``index``
# import this same constant instead of keeping their own copy.
MAX_PLATE_DIGITS = 6


class _TokenStream:
    """Small cursor over a token list, used only within this module."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._pos = 0

    def peek(self, offset: int = 0) -> str | None:
        index = self._pos + offset
        if index < len(self._tokens):
            return self._tokens[index]
        return None

    def advance(self) -> str:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    def remaining(self) -> list[str]:
        """Return the tokens not yet consumed, without advancing the cursor."""
        return self._tokens[self._pos :]


@dataclass
class _SegmentResult:
    type_: str | None = None
    number: str | None = None
    letters: str | None = None
    suffix: str | None = None
    suffix_letters: str | None = None
    bis: bool = False
    quadrant: str | None = None


def _normalize_digits(token: str) -> str:
    """Strip leading zeros, keeping at least one digit (``"080"`` -> ``"80"``)."""
    stripped = token.lstrip("0")
    return stripped if stripped else "0"


def _consume_via_type(stream: _TokenStream) -> str | None:
    """Consume an optional via-type token (single or two-word alias)."""
    first = stream.peek()
    if first is None:
        return None
    # Two-word alias: "AVENIDA CALLE" / "AVENIDA CARRERA".
    if first == "AVENIDA":
        second = stream.peek(offset=1)
        if second is not None:
            alias = _TWO_WORD_VIA_ALIASES.get((first, second))
            if alias is not None:
                stream.advance()
                stream.advance()
                return alias
    if first in VIA_TYPES:
        stream.advance()
        return VIA_TYPES[first]
    return None


def _closes_segment(stream: _TokenStream, stop_tokens: frozenset[str]) -> bool:
    """True when the token after the current one ends the segment."""
    following = stream.peek(offset=1)
    return following is None or following in stop_tokens


def _consume_segment(stream: _TokenStream, stop_tokens: frozenset[str]) -> tuple[_SegmentResult | None, str | None]:
    """Consume one SEGMENT per the grammar.

    Returns ``(segment, error_note)``. On success ``error_note`` is
    ``None``. A missing via number is reported via the note
    ``numero_via_faltante``; any leftover token before a stop token is
    reported as ``token_inesperado:<tok>``.
    """
    segment = _SegmentResult()
    segment.type_ = _consume_via_type(stream)

    number_token = stream.peek()
    if number_token is None or number_token in stop_tokens or not _NUMBER_RE.match(number_token):
        return None, "numero_via_faltante"
    stream.advance()
    segment.number = _normalize_digits(number_token)

    # Optional single LETTER token (a street letter, e.g. "KR 26 H"). "BIS"
    # can never match here since _LETTER_RE only matches one character.
    # Real addresses in this grammar carry at most one via/cross letter;
    # any further bare letter tokens are unexpected and reported below.
    token = stream.peek()
    if token is not None and token not in stop_tokens and _LETTER_RE.match(token):
        stream.advance()
        segment.letters = token

    # Optional suffix number.
    token = stream.peek()
    if token is not None and token not in stop_tokens and _NUMBER_RE.match(token):
        stream.advance()
        segment.suffix = _normalize_digits(token)
        # Optional suffix letter right after the suffix number. A lone
        # quadrant-abbreviation letter that closes the segment is the
        # quadrant, not a suffix letter (``K 3 A 3 N``).
        token = stream.peek()
        if token is not None and token not in stop_tokens and _LETTER_RE.match(token):
            closes_segment = _closes_segment(stream, stop_tokens)
            if not (token in _QUADRANT_ABBREVIATIONS and closes_segment):
                stream.advance()
                segment.suffix_letters = token

    # Optional BIS.
    token = stream.peek()
    if token is not None and token == "BIS":
        stream.advance()
        segment.bis = True

    # Optional QUADRANT: the full word anywhere, or a single-letter
    # abbreviation. A single letter directly after the street number was
    # already consumed above as the street letter (``KR 41 E``), so an
    # abbreviation can only reach this point after a letter/suffix/suffix
    # letter/BIS element (``C 70 B N``); no extra guard is needed.
    token = stream.peek()
    if token is not None and token in QUADRANTS:
        stream.advance()
        segment.quadrant = token
    elif token is not None and token in _QUADRANT_ABBREVIATIONS:
        stream.advance()
        segment.quadrant = _QUADRANT_ABBREVIATIONS[token]

    # Anything left before a stop token is unexpected.
    token = stream.peek()
    if token is not None and token not in stop_tokens:
        return segment, f"token_inesperado:{token}"

    return segment, None


_TAIL_TOKEN_RE = re.compile(r"^[A-Z0-9]+$")


def _split_tail_slashes(tokens: list[str]) -> list[str]:
    """Treat ``/`` inside tail tokens as a separator (``/50`` -> ``50``).

    Stand-alone slashes disappear; ``-`` tokens are kept untouched because
    the tail validation reasons about them.
    """
    out: list[str] = []
    for token in tokens:
        if token == "-":
            out.append(token)
            continue
        out.extend(part for part in token.split("/") if part)
    return out


def _validate_complement_tail(tokens: list[str], has_plate: bool = True) -> str | None:
    """Reject tokens after the plate that look like junk rather than a
    complement. Returns an error note, or ``None`` when acceptable.

    An unstructured tail (no known complement kind) is accepted as an
    opaque chunk, but its hygiene is checked. Rejected shapes:
    - a tail longer than ``_MAX_TAIL_CHARS`` characters once the cleaned
      tokens are joined by single spaces (``complemento_demasiado_largo``);
    - a second ``#`` anywhere (looks like another whole address);
    - a quadrant token as the first tail token (``... - 80 NORTE``);
    - a via-type token immediately followed by a number (looks like the
      start of another address, e.g. ``... - 80 CL 5``);
    - a ``-`` that does not sit strictly between two plain value tokens
      (a value-internal fusion dash like ``101-A`` is fine);
    - any token with characters other than letters and digits;
    - without a plate, a tail that starts with a digit once slashes are
      dropped (``- /50``): re-reading it would turn the digits into a plate.
    """
    if not tokens:
        return None
    if "#" in tokens:
        return "multiples_direcciones"
    if len(" ".join(tokens)) > _MAX_TAIL_CHARS:
        return "complemento_demasiado_largo"
    pieces = _split_tail_slashes(tokens)
    if not pieces:
        return None
    if pieces[0] in QUADRANTS:
        return f"token_inesperado:{pieces[0]}"
    if not has_plate and pieces[0][0].isdigit():
        return f"token_inesperado:{tokens[0]}"
    for index, token in enumerate(pieces[:-1]):
        if token in VIA_TYPES and _NUMBER_RE.match(pieces[index + 1]):
            return "multiples_direcciones"
    for index, token in enumerate(pieces):
        if token != "-":
            continue
        prev_token = pieces[index - 1] if index > 0 else None
        next_token = pieces[index + 1] if index + 1 < len(pieces) else None
        prev_ok = prev_token is not None and prev_token not in COMPLEMENT_KINDS and prev_token != "-"
        next_ok = next_token is not None and next_token not in COMPLEMENT_KINDS and next_token != "-"
        if not (prev_ok and next_ok):
            return "token_inesperado:-"
    for token in pieces:
        if token != "-" and not _TAIL_TOKEN_RE.match(token):
            return f"token_inesperado:{token}"
    return None


def _join_complement_value(value_tokens: list[str]) -> str:
    """Join the tokens of one complement value into a single string.

    A digit run fuses with an immediately following letter run with no
    separator (``101`` + ``A`` -> ``101A``, matching the glued style),
    but two digit runs keep a separator (``/``) so ``LOTE 1-2`` stays
    distinguishable from the literally joined ``LOTE 12`` (finding 3).
    Any literal ``-`` token (a value-internal fusion dash, e.g.
    ``101-A``) carries no meaning of its own once tokenized and is
    dropped; the separator, if any, is re-derived purely from the digit
    vs. letter shape of its neighbors.
    """
    parts: list[str] = []
    prev_is_digit: bool | None = None
    for token in value_tokens:
        if token == "-":
            continue
        is_digit = token.isdigit()
        current = _normalize_digits(token) if is_digit else token
        if parts and prev_is_digit is not None and is_digit == prev_is_digit:
            parts.append("/")
        parts.append(current)
        prev_is_digit = is_digit
    return "".join(parts)


def _parse_complement(tokens: list[str]) -> tuple[tuple[str, str], ...]:
    """Group remaining tokens into ``(kind, value)`` complement chunks.

    A chunk starts at each recognized complement kind token; the value is
    the following tokens until the next known kind. A leading run of
    tokens before any known kind is one opaque chunk: keyed by its first
    token when that is alphabetic, or by ``OPAQUE_KIND`` (the run then
    being all value) when it starts with a digit. Callers must validate
    the tail with ``_validate_complement_tail`` first.
    """
    tokens = _split_tail_slashes(tokens)
    if not tokens:
        return ()

    chunks: list[tuple[str, list[str]]] = []
    idx = 0
    # Leading opaque chunk, if the first token is not a known kind.
    if tokens[0] not in COMPLEMENT_KINDS:
        if tokens[0][0].isdigit():
            key = OPAQUE_KIND
            value_tokens: list[str] = [tokens[0]]
        else:
            key = tokens[0]
            value_tokens = []
        idx = 1
        while idx < len(tokens) and tokens[idx] not in COMPLEMENT_KINDS:
            value_tokens.append(tokens[idx])
            idx += 1
        chunks.append((key, value_tokens))

    while idx < len(tokens):
        kind = COMPLEMENT_KINDS.get(tokens[idx], tokens[idx])
        idx += 1
        value_tokens = []
        while idx < len(tokens) and tokens[idx] not in COMPLEMENT_KINDS:
            value_tokens.append(tokens[idx])
            idx += 1
        chunks.append((kind, value_tokens))

    result = [(kind, _join_complement_value(value_tokens)) for kind, value_tokens in chunks]
    return tuple(sorted(result))


def parse_canonical(raw: object) -> CanonicalAddress:
    """Parse ``raw`` against the strict canonical grammar.

    Never raises: any input that is not a usable string, or that the
    grammar cannot fully consume, yields ``parse_ok=False`` with an
    explanatory note in ``notes``. This function never repairs input; it
    only recognizes the canonical grammar described in the module
    docstring.
    """
    raw_repr = raw if isinstance(raw, str) else str(raw)

    if not isinstance(raw, str):
        return CanonicalAddress(raw=raw_repr, parse_ok=False, notes=("entrada_no_texto",))

    if raw.strip() == "":
        return CanonicalAddress(raw=raw, parse_ok=False, notes=("entrada_vacia",))

    if ";" in raw:
        return CanonicalAddress(raw=raw, parse_ok=False, notes=("multiples_direcciones",))

    cleaned = clean_text(raw)
    if cleaned == "":
        return CanonicalAddress(raw=raw, parse_ok=False, notes=("entrada_vacia",))

    if ";" in cleaned:
        return CanonicalAddress(raw=raw, parse_ok=False, notes=("multiples_direcciones",))

    if "#" not in cleaned:
        return CanonicalAddress(raw=raw, parse_ok=False, notes=("falta_separador_hash",))

    tokens = cleaned.split()
    stream = _TokenStream(tokens)

    via_segment, via_error = _consume_segment(stream, stop_tokens=frozenset({"#"}))
    if via_error is not None:
        return CanonicalAddress(raw=raw, parse_ok=False, notes=(via_error,))

    if stream.peek() != "#":
        return CanonicalAddress(raw=raw, parse_ok=False, notes=("falta_separador_hash",))
    stream.advance()  # consume "#"

    cross_segment: _SegmentResult | None = None
    if stream.peek() is not None and stream.peek() != "-":
        cross_segment, cross_error = _consume_segment(stream, stop_tokens=frozenset({"-"}))
        if cross_error is not None:
            return CanonicalAddress(raw=raw, parse_ok=False, notes=(cross_error,))

    plate: str | None = None
    if stream.peek() == "-":
        stream.advance()
        plate_token = stream.peek()
        if plate_token is not None and _NUMBER_RE.match(plate_token):
            significant_digits = plate_token.lstrip("0") or "0"
            if len(significant_digits) > MAX_PLATE_DIGITS:
                return CanonicalAddress(raw=raw, parse_ok=False, notes=("placa_invalida",))
            stream.advance()
            plate = plate_token
            # Optional single trailing letter attached to the plate.
            next_token = stream.peek()
            # A single letter can never be a quadrant word or a complement
            # kind (both are longer), so it always belongs to the plate.
            if next_token is not None and _LETTER_RE.match(next_token):
                stream.advance()
                plate = plate + next_token
        # Otherwise the dash is either a trailing empty plate (nothing
        # follows) or a complement sitting in the plate slot: the plate is
        # None and whatever remains is parsed as the complement tail.

    tail_tokens = stream.remaining()
    tail_error = _validate_complement_tail(tail_tokens, has_plate=plate is not None)
    if tail_error is not None:
        return CanonicalAddress(raw=raw, parse_ok=False, notes=(tail_error,))
    complement = _parse_complement(tail_tokens)

    return CanonicalAddress(
        raw=raw,
        parse_ok=True,
        notes=(),
        via_type=via_segment.type_ if via_segment else None,
        via_number=via_segment.number if via_segment else None,
        via_letters=via_segment.letters if via_segment else None,
        via_suffix=via_segment.suffix if via_segment else None,
        via_suffix_letters=via_segment.suffix_letters if via_segment else None,
        via_bis=via_segment.bis if via_segment else False,
        via_quadrant=via_segment.quadrant if via_segment else None,
        cross_type=cross_segment.type_ if cross_segment else None,
        cross_number=cross_segment.number if cross_segment else None,
        cross_letters=cross_segment.letters if cross_segment else None,
        cross_suffix=cross_segment.suffix if cross_segment else None,
        cross_suffix_letters=cross_segment.suffix_letters if cross_segment else None,
        cross_bis=cross_segment.bis if cross_segment else False,
        cross_quadrant=cross_segment.quadrant if cross_segment else None,
        plate=plate,
        complement=complement,
    )


# ---------------------------------------------------------------------------
# Rendering: re-emit the canonical spaced form of a parsed address
# ---------------------------------------------------------------------------


def _render_segment(
    type_: str | None,
    number: str | None,
    letters: str | None,
    suffix: str | None,
    suffix_letters: str | None,
    bis: bool,
    quadrant: str | None,
) -> str:
    tokens: list[str] = []
    if type_ is not None:
        tokens.append(type_)
    if number is not None:
        tokens.append(number)
    if letters is not None:
        tokens.append(letters)
    if suffix is not None:
        tokens.append(suffix)
        if suffix_letters is not None:
            tokens.append(suffix_letters)
    if bis:
        tokens.append("BIS")
    if quadrant is not None:
        tokens.append(quadrant)
    return " ".join(tokens)


def _render_plate(plate: str) -> str:
    """Re-emit a plate zero-padded to at least 2 digits, keeping any
    trailing letter (e.g. ``9`` -> ``09``, ``080`` -> ``80``, ``80A`` stays
    ``80A``)."""
    if plate and plate[-1].isalpha():
        digits, letter = plate[:-1], plate[-1]
    else:
        digits, letter = plate, ""
    digits = digits.lstrip("0") or "0"
    if len(digits) < 2:
        digits = digits.zfill(2)
    return digits + letter


_VALUE_RUN_RE = re.compile(r"[0-9]+|[A-Z]+")


def _render_value_part(part: str) -> str:
    """Re-emit one ``/``-free value part.

    A part is normally emitted fused (``101A``). The exception is a letter
    run that is also a via type directly followed by digits (``A`` + ``1``
    from a dash-fused ``A-1``): glued as ``A1`` it would be re-read as the
    start of another address, so it is emitted as ``A - 1``, the dash form
    the tail grammar accepts and drops again.
    """
    runs = _VALUE_RUN_RE.findall(part)
    needs_dash = any(
        run in VIA_TYPES and index + 1 < len(runs) and runs[index + 1].isdigit()
        for index, run in enumerate(runs)
    )
    if not needs_dash:
        return part
    out: list[str] = []
    for index, run in enumerate(runs):
        out.append(run)
        if run in VIA_TYPES and index + 1 < len(runs) and runs[index + 1].isdigit():
            out.append("-")
    return " ".join(out)


def _render_complement_value(value: str) -> str:
    """Re-emit a joined complement value as separate tokens where needed.

    ``_join_complement_value`` keeps two digit runs apart with ``/``; that
    needs to become whitespace again so re-parsing recovers the same two
    tokens (a fused digit+letter value like ``101A`` needs no such split:
    ``clean_text``'s glued-token splitting recovers ``101 A`` on its own).
    """
    if not value:
        return ""
    return " ".join(_render_value_part(part) for part in value.split("/"))


def render(addr: CanonicalAddress) -> str:
    """Re-emit the canonical spaced form of a parsed address.

    Falls back to the original raw input when ``addr.parse_ok`` is
    ``False``, since there is no canonical structure to render. Any
    complement chunk whose kind is not a registered ``COMPLEMENT_KINDS``
    code (the opaque leading chunk, e.g. ``SO 1`` or the digit-led ``?``
    chunk, rendered as its bare value) is emitted first, because the
    grammar can only recognize such a chunk at the very start of the tail;
    reparsing the rendered string must recover exactly the same fields (see the idempotency
    test in ``tests/test_parser.py``).
    """
    if not addr.parse_ok:
        return addr.raw

    parts: list[str] = [
        _render_segment(
            addr.via_type,
            addr.via_number,
            addr.via_letters,
            addr.via_suffix,
            addr.via_suffix_letters,
            addr.via_bis,
            addr.via_quadrant,
        ),
        "#",
    ]
    if addr.cross_number is not None:
        parts.append(
            _render_segment(
                addr.cross_type,
                addr.cross_number,
                addr.cross_letters,
                addr.cross_suffix,
                addr.cross_suffix_letters,
                addr.cross_bis,
                addr.cross_quadrant,
            )
        )
    if addr.plate is not None:
        parts.append("-")
        parts.append(_render_plate(addr.plate))
    elif addr.complement:
        # A complement without a plate must sit after a dash, otherwise
        # re-parsing would read it as trailing junk of the cross segment.
        parts.append("-")

    unknown_chunks = [(k, v) for k, v in addr.complement if k not in COMPLEMENT_KINDS]
    known_chunks = [(k, v) for k, v in addr.complement if k in COMPLEMENT_KINDS]
    for kind, value in unknown_chunks + known_chunks:
        if kind != OPAQUE_KIND:
            parts.append(kind)
        rendered_value = _render_complement_value(value)
        if rendered_value:
            parts.append(rendered_value)

    return " ".join(parts)
