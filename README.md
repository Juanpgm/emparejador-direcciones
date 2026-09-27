# emparejador_direcciones

A small, independent pairwise matcher for **already-normalized** Cali cadastral
addresses. Given two canonical address strings, it answers **MATCH / NO_MATCH**
with a confidence score, so different geographic records (parcels, points,
registries) can be linked by address.

## Independence

This project is fully independent: it does not import, read, or otherwise
depend on any other project. It owns its own text-cleanup layer, its own
grammar parser, and its own alias tables. It may use *similar techniques* to
other address-normalization tools (uppercasing, accent stripping, alias
tables, structural field comparison), but the implementation here is its own.
Zero third-party runtime dependencies: only the Python standard library
(`re`, `unicodedata`, `dataclasses`, plus `csv`/`argparse`/`json` in the CLIs) is used at runtime.

## Accepted canonical grammar

```
SEGMENT := [TYPE] NUMBER [LETTER] [SUFFIX_NUMBER [SUFFIX_LETTER]] [BIS] [QUADRANT]
ADDRESS := SEGMENT_VIA "#" [SEGMENT_CROSS] ["-" [PLATE]] [COMPLEMENT...]
```

Examples: `KR 26 H 1 # 73 - 10`, `CL 72 T 1 # 26 G 11 - 70`,
`CL 12 # 48 BIS - 31`, `AV 15 OESTE # 9 OESTE - 137`,
`CL 25 NORTE # AV 6 - 30` (cross type), `CL 12 A # 52 - 60 SO 1 PQ 19`
(complement), `KR 98F # 98 - 66` (glued IDESC style).

The cadastre stores **raw** addresses, not the clean canonical form, so the
grammar also accepts these raw shapes (all present in the real base):

| Raw shape | Example | Parsed as |
|---|---|---|
| Legacy via type `K`/`C`/`D`/`T`/`A` | `K 41 # 31 B -`, `A 9 # 5 - 3` | `KR`/`CL`/`DG`/`TV`/`AV`. Only at the start of a segment; other single letters (`M`, ...) stay rejected. |
| Trailing empty plate | `C 1 # 74 -`, `A 9 W # -` | plate `None`; the dash is noise, `C 1 # 74 -` == `C 1 # 74`. The `sin_placa`/`sin_cruce` warnings cover the ambiguity. |
| Complement in the plate slot | `KR 69 # 33 - LT 20`, `CL 6 OESTE # KR 4 - BO 000101 LT 0372`, `K 47B # 55 B - Q2 T` | plate `None`, the tail is parsed as complement chunks. |
| Doubled separators | `K 125 # # 18 - 55`, `K 111 # # 15 - - 120` | adjacent `# #` and `- -` collapse to one. |
| Single-letter quadrant | `C 70 B N # 4 C - 104`, `C 1 A BIS O # 81 - 19`, `K 3 A 3 N # 71 H - 13` | `N`->`NORTE`, `S`->`SUR`, `E`->`ESTE`, `O`/`W`->`OESTE` (see below). |
| Number+letter unit after the plate | `K 49 E # 49 - 50 8 C`, `K 1 D # 46 A - 44 8BC` | opaque complement (see below). |
| Unregistered tail | `CL 9 # 51 - 46 GASS 5`, `K 8 # 22 - 48 /50 /52` | opaque complement. |

### Single-letter quadrant abbreviations

`N`, `S`, `E`, `O`, `W` are quadrants **only** when the segment already
carries a street letter, a suffix number, a suffix letter or `BIS` right
before them (`C 70 B N`, `A 1 A BIS O`, `K 3 A 3 N`). Directly after the
street number they stay street letters (`KR 41 E`, `A 9 W`), and they are
never quadrants anywhere else (in the tail, in the plate slot, after a via
type). After a suffix number a lone `E`/`N`/... that closes the segment is
read as the quadrant (`K 3 A 3 N`); when another letter follows it stays a
suffix letter (`KR 26 1 E N` = suffix letter `E`, quadrant `NORTE`).

A light cleanup layer accepts minor formatting slips before the strict
grammar runs: uppercasing, accent stripping (`Ñ` → `N`), unifying dash
variants to `-`, normalizing `Nº`/`No.`/`NRO`/`NUM` to `#`, splitting glued
letter/digit runs (`98F` → `98 F`), stripping trailing dots on tokens
(`CRA.` → `CRA`), collapsing doubled adjacent `#`/`-`, and collapsing
whitespace. It does **not** recover a missing `#`, strip city noise, repair
typos, or split multiple addresses: anything the strict grammar cannot then
consume is reported as a parse failure, never silently guessed. Digits are
matched with `[0-9]` (not the Unicode-aware `\d`), but the cleanup first
applies Unicode NFKD, which folds *compatibility* digits into ASCII:
superscript `²`, circled `②`, fullwidth `２` and subscript `₂` all read as
`2` (`KR ² # 2 - 3` equals `KR 2 # 2 - 3`). Only digits with no such
decomposition, such as Arabic-Indic `٣`, survive cleanup and are rejected as
a parse failure (`KR ٣ # 9 - 80`).

Input is expected to already be normalized (e.g. by a separate
normalization step upstream of this project). This project does not
normalize free-form addresses; it only compares two canonical ones.

### What happens after the plate

What follows the plate (or the dash, when there is no plate) is the
complement tail. Known kinds (`AP`, `TO`, `LT`, `PISO`, ...) form structured
chunks; anything else is accepted as an **opaque** chunk (next section).
The tail hygiene rules still reject junk:

- A second `#` anywhere in the tail is rejected (`multiples_direcciones`):
  it looks like a second, whole address got concatenated in
  (`KR 1 # 9 - 80 CL 5 # 3 - 2`).
- A via-type token immediately followed by a number is rejected the same
  way, even without a second `#` (`KR 1 # 9 - 80 CL 5`).
- A quadrant token (`NORTE`/`SUR`/`ESTE`/`OESTE`) right after the plate or
  the dash is rejected (`token_inesperado:<tok>`): a quadrant belongs to a
  segment, not loose after the plate (`KR 1 # 9 - 80 NORTE`).
- A `-` that does not sit strictly between two plain value tokens is
  rejected (`KR 1 # 9 - 80 - 82`); a value-internal fusion dash like
  `101-A` is still accepted.
- Only letters, digits and `/` (a separator: `/50` == `50`) are allowed in
  tail tokens; anything else is `token_inesperado:<tok>`.
- A tail longer than 40 characters (the cleaned tokens joined by single
  spaces) is rejected as `complemento_demasiado_largo`: it is prose or junk,
  not a unit. Exactly 40 is accepted.
- With no plate, a tail that would start with digits once slashes are
  dropped (`- /50`) is rejected, because the digits would be re-read as a
  plate.
- A single trailing letter still attaches to the plate as before (`80 A`
  is a different corner from `80`, not a complement, and stays a hard
  veto when it differs) — see "The complement rule" below.

### Plate digit-run cap

A plate's significant digits (after stripping leading zeros) are capped at
6. Longer runs (e.g. thousands of digits pasted into the input) are a
parse failure (`placa_invalida`), never a crash: Python itself refuses to
convert arbitrarily long digit strings to `int`, so this cap keeps every
internal plate comparison safe. Leading zeros used for padding do not
count against the cap: `- 0000080` is still equivalent to `- 80`.

## Scoring

Weighted averages dilute as fields are added (one wrong street letter would
still score close to 1.0 out of many fields). Instead, the score is a
product of survival factors over every field that differs:

```
score = round(prod(1 - penalty_i), 4)
```

Any hard veto forces `score = 0.0` regardless of the product.

| Field | Equal | Present on one side only | Both present, different |
|---|---|---|---|
| `via_type`, `via_number` | 0 | n/a | **VETO** |
| `cross_number` | 0 | **VETO** (plate counts from the cross street) | **VETO** |
| `plate` (zero-stripped digit compare; `80` == `080` → equivalent) | 0 | **VETO** (corner, not parcel) | letter differs → **VETO**; else ≤ `plate_tolerance` → 0.04, otherwise **VETO** |
| `complement` (set of `(kind, value)`) | 0 | 0.02 (0.15 when the present side has an opaque chunk) | **VETO** |
| `via_letters`, `via_suffix`, `via_suffix_letters`, `via_quadrant`, `cross_letters`, `cross_suffix`, `cross_suffix_letters`, `cross_quadrant` | 0 | 0.15 | 0.30 |
| `via_bis`, `cross_bis` | 0 | 0.15 | n/a |
| `cross_type` | 0 | 0.03 (cadastre usually omits it) | 0.30 |

Missing on both sides = agreement. Missing on only one side for
letters/BIS/quadrant counts as a disagreement: `KR 1`, `KR 1 A`, `KR 1 BIS`,
and `CL 5 OESTE` are different physical streets in Cali.

A plate's trailing letter is itself a hard veto when it differs: `KR 1 # 9
- 80 A` does not match `KR 1 # 9 - 80` — a lettered plate is a different
corner/unit, not the same parcel. Plate values are never converted to
`int` on an unbounded string: the digit part is zero-stripped and length
capped (see "Plate digit-run cap" above), and only then compared or
subtracted for tolerance.

A parse failure on either side is itself a veto, with the reason taken from
the parser's notes. There is no fuzzy-string fallback and no informational
ratio: canonical strings already encode the relevant fields, so a plain
similarity ratio would just re-measure them with the wrong weights (and
would score two unrelated placeholder values like `SIN DIRECCION` as a
perfect match).

### Warnings for open-ended addresses

When **both** sides lack a plate, or both lack a cross number, the field
table above still scores that as agreement (missing on both sides = no
disagreement). But since the comparison then rests on less structure than
usual, `MatchResult.warnings` carries `sin_placa` and/or `sin_cruce` in
that case, and the CLI prints them as `avisos: ...`. Either side carrying an
opaque complement chunk adds `complemento_no_estructurado`. Warnings are
empty whenever both addresses are fully specified and structured.

### The dead band around the default threshold (0.90)

The only three factors that can appear together with **no structural
disagreement at all** (formatting-only differences) are: plate tolerance
(0.96), one-sided `cross_type` (0.97), and one-sided complement (0.98).
Their worst-case combined product is `0.96 * 0.97 * 0.98 = 0.9126`. Any real
structural disagreement contributes a factor of at most 0.85 (one-sided
soft field or BIS) or 0.70 (a conflicting soft field or `cross_type`), so no
combination that includes one can exceed 0.85. That means **no reachable
score lands in the open interval `(0.85, 0.9126)`**, and the default
threshold `0.90` sits inside that empty gap — it is never a coin flip
between "formatting-only" and "one real disagreement". The opaque one-sided
complement reuses the 0.15 factor (a real disagreement), so it never enters
the gap either; the exhaustive dead-band test includes it.

Threshold meanings, informally: `0.90` = formatting-only differences at
most; `0.85` = also tolerates one missing element; `0.70` = also tolerates
one explicit conflict; `1.0` = exact structure required.

### The complement rule

The `complement` field (`AP`/`TO`/`LC`/`PISO`/... chunks like apartment,
tower, local, floor) is compared as a multiset of `(kind, value)` pairs (sorted
tuples: a repeated chunk counts, so `AP 1 AP 1` != `AP 1`),
order-independent and alias/zero-normalized (`AP 501 TO 3` == `TO 3 APTO
0501`). If **both** sides have a complement and they disagree on any shared
kind's value, or one side has extra kinds the other lacks, that is a hard
veto (`AP 501` vs `AP 502`, or `AP 501` vs `AP 501 TO 3`). If only **one**
side has a complement at all and the other has none, that is a soft,
one-sided penalty (0.02): the parcel-level address can still match even if
only one record specifies a unit. The veto reason is rendered as `"KIND
VALUE"` pairs (`complemento difiere (AP 501 vs AP 502)`), never as a raw
tuple.

### Opaque complements

Real cadastral tails are often not made of known kinds (`8 C`, `12 C`,
`8BC`, `GASS 5`, `SS 3 G`, `DP 4`, `BO 000101`). Rejecting them would leave
those parcels unable to match themselves, so an unrecognized tail is kept
as one **opaque chunk**, keyed as follows:

- the first tail token is alphabetic: the chunk kind is that token and the
  value the normalized rest (`SO 1` -> `(SO, 1)`, `BO 000101 LT 0372` ->
  `(BO, 101)` and `(LT, 372)`);
- the tail starts with a digit: the kind is the literal `?` and the value
  the whole normalized tail (`8 C` == `8C` == `08C` -> `(?, 8C)`).

Value keys follow the usual rules: digit runs lose leading zeros, a digit
run fuses with the following letter run, two digit runs stay separated
(`50 52` == `/50 /52` != `5052`). Only one opaque chunk can exist, and it
always sits at the start of the tail (it is emitted first by `render`, a
`?` chunk as its bare value, so re-parsing yields identical fields).

Because the tail is not understood, opaque chunks are scored with a
stricter rule than known kinds. A chunk is opaque when its kind is not in
`COMPLEMENT_KINDS`:

| Situation | Known kinds | Any opaque chunk on the side that has a complement |
|---|---|---|
| Equal on both sides | 1.0 | 1.0 (warning `complemento_no_estructurado`) |
| Both present, different | **VETO** | **VETO** |
| One side only | 0.02 (links) | **0.15** (`solo_en_uno`, does NOT auto-link to the bare address) |

A known kind is also treated as opaque when it carries no usable value: an
empty value (`C 1 # 74 - LT`, `KR 1 # 2 - 3 AP`) or a value made only of
quadrant words (`AP NORTE`). Such a chunk names no unit, so it must not link
to the bare address at the cheap 0.02 price: it costs 0.15 like any other
opaque chunk. Equal on both sides is still exact.

The warning `complemento_no_estructurado` is emitted whenever either side
carries an opaque chunk. No new penalty constant is involved: 0.15 is the
existing one-sided factor, so the dead band below is unchanged.
`SO`, `BO`, `GASS`, ... are deliberately **not** registered kinds (`PISO`
is).

Within one complement value, a digit run only fuses with an immediately
following letter run (`101-A` == `101 A` == `101A`), matching the glued
style seen elsewhere in the grammar. Two digit runs never fuse: `LOTE 1-2`
and `LOTE 1 2` are the same value, but neither equals the literally joined
`LOTE 12` — and the same applies without a dash at all (`AP 1 2` != `AP
12`). This applies per complement kind, independent of the kind label
itself.

## Non-features

- No free-form address normalization (expects already-canonical input).
- No fuzzy string matching / edit-distance fallback.
- No missing-separator recovery, city-noise stripping, typo repair, or
  multi-address splitting (`;` in the input is a parse failure).
- No runtime dependency on any other project or third-party package.

## Public API

```python
from emparejador import match, MatchResult, FieldComparison, CanonicalAddress, render

result: MatchResult = match(
    "KR 1 # 9 - 80",
    "kr 1 #9-80",
    threshold=0.90,        # DEFAULT_THRESHOLD
    plate_tolerance=0,     # DEFAULT_PLATE_TOLERANCE
)
result.is_match   # bool
result.score      # float, 0.0..1.0
result.warnings   # tuple[str, ...]: "sin_placa" / "sin_cruce" / "complemento_no_estructurado"
result.to_dict()  # JSON-serializable dict

render(result.parsed_a)  # re-emit the canonical spaced form, e.g. "KR 1 # 9 - 80"
```

`render` re-emits a parsed address in its canonical spaced form (plate
zero-padded to at least 2 digits, complement chunks as `KIND VALUE`, a
plate-less complement after a bare `-`, an opaque `?` chunk as its bare
value); it falls back to the original raw input when the address failed to
parse. `parse_canonical(render(parse_canonical(x)))` always has identical
fields to `parse_canonical(x)` for any address the grammar accepts (plates
compared by identity, ignoring zero padding).
`match_parsed(a, b, threshold, plate_tolerance)` is `match` for two
`CanonicalAddress` values that are already parsed.

- Bad **address** input never raises: `None`, `""`, or garbage input on
  either side scores `0.0` / `NO_MATCH`.
- Bad **settings** raise `ValueError` subclasses: `InvalidThresholdError`
  (threshold outside `[0, 1]` or `NaN`) and `InvalidToleranceError`
  (negative or non-integer `plate_tolerance`).

### Linking one address against a whole base: `AddressIndex`

`match` is pairwise. To find which record of a large base (for example the
330,387-row cadastre) an address belongs to, build an index once and query it:

```python
from emparejador import AddressIndex

index = AddressIndex.from_records(
    ((row["id"], row["address"]) for row in rows),
    plate_tolerance=0,
)
index.rejected      # records whose address did not parse (not indexed)
len(index)          # DISTINCT record ids indexed
index.stats()       # {"records", "blocks", "rejected", "max_block_size"}

result = index.find("K 41 # 31 B", threshold=0.90)
result.candidates   # list[Candidate(record_id, score, result)], best first
result.best         # top Candidate or None
result.ambiguous    # True when >1 DISTINCT record ties at the top score
result.near_ambiguous  # True when ANY other distinct record is also >= threshold
result.alternatives    # how many other distinct ids are >= threshold
result.truncated    # True when max_block_scan cut a block short
result.n_compared   # records actually scored (blocking keeps this small)
result.parse_ok     # False for an unparseable query; result.reason says why
```

- `add(record_id, address) -> bool` returns `False` (and counts `rejected`)
  for an unparseable address. Ids must be hashable (int or str both work);
  an unhashable id raises `TypeError`.
- Blocking loses nothing: records are filed by the fields that are hard
  vetoes in the matcher (via type, via number, cross number, plate as an
  integer). With `plate_tolerance > 0` the lookup covers every plate within
  the tolerance. Addresses with no plate/cross use `None` in that slot and
  still meet each other. Every candidate is scored by the real matcher, so
  the result equals a brute-force `match` scan over the same records (a
  randomized property test and a check on the real cadastre enforce it).
- `candidates` holds only records at or above the threshold, sorted by score
  descending then record id (deterministic, mixed int/str ids allowed). The
  same id added twice is one record (best score kept).
- `ambiguous` flags cases the base itself cannot resolve: several parcels
  sharing one canonical address, or several units tying at the same score.
  Decide at the caller (return all candidates, or refuse to link).
- `near_ambiguous` / `alternatives` are the wider signal: a perfect `1.0` can
  still have a different parcel right behind it (a known-complement unit of
  the same building scores 0.98, a cross-type variant 0.97) without any exact
  tie. `alternatives` counts the other distinct ids at or above the
  threshold; `near_ambiguous` is `alternatives > 0`. `ambiguous` keeps its
  exact-tie meaning.
- Record ids are compared as Python compares them (equality plus hash), so
  `1`, `1.0` and `True` are ONE id while `1` and `"1"` are two. `len(index)`
  and `stats()["records"]` count distinct ids; `stats()["blocks"]` and
  `max_block_size` count entries (an id added twice is one record filed twice).
- `find(query, threshold, max_block_scan=None)`: by default every record of a
  block is scored. With `max_block_scan=N`, a block with more than `N` records
  is scanned only up to `N` and the result is flagged `truncated=True` (a
  better candidate may be missing). `N` must be an int `>= 1`.
- `find` never raises on bad query input (empty result plus the parse
  reason); a bad `threshold` raises like `match` does.

## CLI

Compare two addresses:

```
python scripts/emparejar.py <direccion_a> <direccion_b> [--umbral/--threshold N] [--tolerancia-placa/--plate-tolerance N] [--json]
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | MATCH |
| 1 | NO_MATCH (including unparseable input) |
| 2 | usage error (bad arguments, invalid threshold/tolerance) |

Plain output (the `A:`/`B:` lines show the *rendered* canonical form, not
the raw input, falling back to the raw input only when parsing failed; the
threshold is formatted with `{:g}`, so `0.90` prints as `0.9` and `0.8501`
prints in full):

```
MATCH  puntaje=1.0000  umbral=0.9
A: KR 1 # 9 - 80
B: KR 1 # 9 - 80
motivo: coincidencia exacta
```

When either address is open-ended (missing plate or cross number on both
sides) or carries an opaque complement, an extra line lists the warnings:

```
avisos: sin_placa
```

`--json` prints one JSON object with keys: `match`, `resultado`, `score`,
`threshold`, `plate_tolerance`, `reason`, `a`, `b`, `fields`, `warnings`.
Each of `a`/`b` is `{input, parse_ok, canonical, fields: {...every
CanonicalAddress field...}, notes}`, where `canonical` is the rendered
form (falling back to the raw input when parsing failed).

Link one address against a CSV base (csv module only):

```
python scripts/vincular.py --base base.csv --id-column ID --address-column ADDR \
    [--encoding utf-8] [--umbral N] [--tolerancia-placa N] [--top N] [--json] "direccion"
```

It indexes every parseable row, then prints the candidates (best first, at
most `--top`, default 5). Exit codes: `0` when a best candidate exists at or
above the threshold, `1` when there is none (including an unparseable
query), `2` on usage errors (unreadable or empty file, unknown encoding,
missing column, threshold outside `[0, 1]`, `--top < 1`, `--max-block-scan < 1`, malformed
CSV). Plain output starts with `MATCH` or `SIN_COINCIDENCIA` and flags
`AMBIGUO` when several records tie at the top score and `TRUNCADO` when
`--max-block-scan` cut a block short. When there is a best candidate it also
prints `alternativas: N` (other distinct parcels at or above the threshold,
with a Spanish `nota:` when `N > 0`) and an `avisos:` line with the best
candidate's warnings (`sin_placa`, `sin_cruce`, `complemento_no_estructurado`);
the `--top` list appends `[avisos: ...]` to any candidate that has warnings.
`--json` prints `consulta`, `canonica`, `parse_ok`, `motivo`, `umbral`,
`tolerancia_placa`, `n_comparados`, `n_candidatos`, `ambiguo`, `casi_ambiguo`,
`alternativas`, `truncado`, `mejor`, `candidatos` (`id`, `puntaje`,
`canonica`, `avisos`), `registros`, `rechazados` and `ids_vacios`.

CSV handling: a leading UTF-8 BOM is skipped; rows whose id is empty or only
whitespace are skipped and counted (`aviso: N filas sin id omitidas` on
stderr, `ids_vacios` in JSON); a short row has no address and counts as
rejected. The CSV is parsed strictly, so an unterminated quote, text after a
closing quote, a wrong delimiter (the header collapses to one column) or a row
with more non-empty fields than the header (typically an unquoted comma inside
the address) exits `2` with a Spanish error instead of being indexed wrong.
Quoted fields may contain commas and newlines.
`--max-block-scan N` (alias `--max-bloque`) caps how many records of one
block are scored (default: no cap).

## Tests

This project follows strict TDD: every behavior above is covered by a
parametrized test before the corresponding code was written. Run the full
suite with:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

Test files:

- `tests/test_parser.py` — cleanup hygiene, grammar happy paths, number
  normalization, complement chunking (including the digit-run separator
  rule), junk-after-plate rejection, the plate digit-run cap, parse
  failures (never raising), a 3000-iteration ASCII random-string fuzz test
  plus a second fuzz test over accented Latin/`ñ`/fullwidth `＃`/NBSP/
  Arabic-Indic digits/emoji up to length 200, and render-based idempotency.
- `tests/test_parser_phase2.py` — the raw cadastral shapes: doubled
  separators, trailing empty plate, complement in the plate slot, opaque
  tails (including the 40/41-character boundary, 10k-character junk,
  4301-digit numbers, `#`/via types inside tails), single-letter quadrants
  in every wrong position, legacy via type `A` vs street letter `A`, and
  render idempotency (fixed cases plus a randomized test).
- `tests/test_matcher.py` — exact/equivalent matches, every hard veto
  (including the plate-letter veto), every soft penalty for every soft
  field (one-sided *and* conflicting), plate tolerance, symmetry, threshold
  boundaries and validation, warnings, human-readable field comparisons and
  veto reasons (the dead-band proof moved to `tests/test_matcher_review.py`,
  derived from the `matcher._PENALTIES` registry the matcher itself reads).
- `tests/test_matcher_phase2.py` — opaque complements (equal, different,
  one-sided, mixed with known kinds, symmetry, threshold boundary), plate-
  less addresses, abbreviated quadrants, legacy `A`, and `match_parsed`.
- `tests/test_index_review.py`, `tests/test_matcher_review.py`,
  `tests/test_parser_review.py`, `tests/test_vincular_review.py` — the
  independent review findings: near-ambiguity signal, hidden CLI warnings,
  blocking-strength (`n_compared`) checks, the penalty registry proof of the
  dead band, valueless known complements, multiset complements, digit
  folding, distinct-id bookkeeping, strict CSV parsing and `max_block_scan`.
- `tests/test_index.py` — `AddressIndex`: empty index, unparseable records,
  duplicates, ambiguity, plate tolerance neighbours and boundaries,
  `None` plate/cross/type blocks, huge blocks, deterministic ordering,
  int/str ids, bad queries, and a randomized property test proving the
  index equals a brute-force `match` scan.
- `tests/test_cli.py` and `tests/test_vincular_cli.py` — subprocess-level
  exit codes, output shape, `--json`, encodings and usage errors.
- `tests/test_eval_helpers.py` — the pure helpers of the evaluation
  harness, including section H, without pyarrow or the data.

## Evaluation against the cadastre

`tools/eval_catastro.py` measures the matcher against a large real corpus of
already-normalized addresses (the Cali cadastral base, a parquet file that is
read as **data only** and referenced by path; it is never copied into this
repository). It reports parse coverage, self-match/symmetry, recall on format
variants, rejection of one-field mutations, false-link risk inside the base,
threshold sensitivity, throughput, and (section H) linking a sample of rows
back to their own parcel through an `AddressIndex` built over the whole base.
Results and findings: `docs/eval_catastro_baseline.md` (before the raw-shape
grammar) and `docs/eval_catastro_after.md` (after, with a before/after
comparison).

The runtime stays dependency-free. Use a separate venv for the harness:

```
py -3.12 -m venv ..\eval-venv
..\eval-venv\Scripts\python -m pip install -r requirements-dev.txt
..\eval-venv\Scripts\python tools\eval_catastro.py --catastro <path\to\catastro_docs.parquet> --json-out result.json
```

`--catastro` can also be given through the `CATASTRO_PARQUET` environment
variable. Defaults: `--sample 20000 --seed 42` for B-G and `--link-sample
5000` for H; use `--full` for every row (slow) and `--max-pairs` to cap the
pairs sampled for the false-link analysis. Runs are deterministic for the
same seed. The pure helpers are unit tested without pyarrow or the data in
`tests/test_eval_helpers.py`.

## Ground truth (independent evaluation)

`tools/build_groundtruth.py` and `tools/eval_groundtruth.py` build and score a
labeled pair set that does not depend on the matcher's own grammar. See
`docs/groundtruth.md`.
