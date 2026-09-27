# Evaluation against the Cali cadastre: after phase 2

Phase 2 (improvement), re-run after the independent review fixes (see "Independent review" below). Same corpus, sample size and seed as `docs/eval_catastro_baseline.md`: `catastro_docs.parquet`, 330,387 rows, `--sample 20000 --seed 42`, plus the new section H (`--link-sample 5000`, seed 42). Deterministic for a fixed seed (timings aside). The full harness output is in the appendix and is the source of truth.

## What changed

- Parser: legacy via types (`K`, `C`, `D`, `T`, and now `A` -> `AV`), a trailing empty plate (`# 74 -`) parses with plate `None`, a complement in the plate slot (`- LT 20`) parses with plate `None`, doubled `# #` / `- -` collapse, single-letter quadrants (`N`/`S`/`E`/`O`/`W`) after a street letter, suffix or `BIS`, opaque complements (`8 C`, `GASS 5`, `SS 3 G`), tail hygiene (letters, digits and `/` only, at most 40 characters), `PISO` registered.
- Matcher: opaque complements compare by equality; present on one side only costs 0.15 (not 0.02) so they never auto-link to the bare address; warning `complemento_no_estructurado`. No new penalty constant; the dead band is intact (the exhaustive test includes the new case).
- New: `AddressIndex` (blocking on the hard-veto fields) and `scripts/vincular.py`.
- Harness: section H, and the mutation `complement_removed` is split into `complement_removed` (known kinds, designed match at 0.98) and `complement_removed_opaque` (a true difference at 0.85).

## Before / after

| Table | Baseline (phase 1) | After (phase 2) |
|---|---|---|
| A. Parse coverage | 314,107 / 330,387 = **95.07%** (16,280 failures) | 328,628 / 330,387 = **99.47%** (1,759 failures) |
| Parseable in the 20k sample | 19,008 | 19,900 |
| B. Self-match violations | 0 / 19,008 | 0 / 19,900 |
| B. Symmetry violations | 0 / 332,209 | 0 / 346,670 |
| C. Format-variant recall | 205,910 / 205,911 = 100.00% (1 miss) | 217,171 / 217,171 = **100.00%** (0 misses; the baseline miss `P 01 PQ 020` is fixed) |
| D. True-difference kinds as designed | 26 / 26 kinds at 100% | 27 / 27 kinds at 100% (`complement_removed_opaque` added; after the review, valueless known kinds such as a bare `LC` move into it: 1,076 / 562 mutants) |
| D. True-difference scores | 0.0, 0.70, 0.85 only; none in [0.90, 1.0] (303,697) | 0.0, 0.70, 0.85 and 0.6141 (5 mutants); none in [0.90, 1.0] (317,382) |
| E1. Different plate, same face, >= 0.90 | 0 / 198,774 | 0 / 198,766 |
| E1. Same base, complements differ, >= 0.90 | 0 / 6,534 | 0 / 7,784 |
| E1. Same base, one side bare | 39 / 39 link (0.98) | 61 / 131 link (0.98, known kinds with a value); the other 70 score 0.85 (opaque or valueless known kind, by design; was 65 / 66 before the review) |
| E2. Canonical strings shared by several parcels | 150 groups (152 pairs at 1.0) | 268 groups (272 pairs at 1.0): more rows are now parseable, so more of the base's own ambiguity is visible |
| E3. Different base, same plate, >= 0.90 | 19 / 115,267 (cross type only) | 28 / 114,891 (cross type only: 27 `cross_type`, 1 `complement,cross_type`); `same_cross_same_plate_other_via` 0 / 118,397 |
| F. Threshold 0.90 / 0.95 / 1.00 | P = R = 1.0 | P = R = 1.0 (0.85: P 0.6445, 0.70: P 0.6078; tolerance 1: F1 0.9176, tolerance 2: F1 0.8481) |
| G. Throughput | 23,474 pairs/s; parse 20.8 us/address | 24,858 pairs/s (39.4 us/pair); parse 13.8 us/address |
| H. Own parcel recovered (exact) | n/a (new) | 5,000 / 5,000 (own missing 0); top-1 own 99.94% |
| H. Own parcel recovered (format variant) | n/a (new) | 5,000 / 5,000 (own missing 0); top-1 own 99.94% |
| H. Ambiguous | n/a | 11 / 5,000 = 0.22% (exact and variant); 3 of them return the own parcel second on the id tie-break |
| H. False best (not own, not a tie with own) | n/a | 0 / 5,000 in both query sets |
| H. Candidates / compared per query | n/a | 1.011 candidates, 7.00 compared on average (max block 293 vs 328,628 records) |
| H. Queries per second | n/a (all-pairs would be about 5.5e10 comparisons) | about 9,500 (exact) and 9,800 (variant) |
| H. Index build | n/a | 5.5 s including parsing 328,628 rows; 178,576 blocks; about 165 MiB working-set growth; process peak 564 MiB (includes the parquet columns held by the harness). `records indexed` now reads 328,614: it counts DISTINCT ids and 14 surplus cadastre rows share a parcel id already indexed |

Notes on D: the 5 mutants at 0.6141 (0.85^3) are `via_bis_remove` on `K 1 A 5 E BIS # ...`. Removing `BIS` leaves `... 5 E #`, where the lone `E` that now closes the segment is read as the quadrant `ESTE` instead of a suffix letter (the disambiguation rule for `K 3 A 3 N`). The mutation changes the meaning of the neighbouring token, so three fields differ; the score is still far below the threshold.

## Acceptance criteria

| # | Criterion | Result | Numbers |
|---|---|---|---|
| 1 | Parse coverage >= 99.0% | **PASS** | 99.47% (328,628 / 330,387); baseline 95.07% |
| 2 | B: 0 self-match and 0 symmetry violations | **PASS** | 0 / 19,900 and 0 / 346,670 |
| 3 | C variant recall >= 99.99% | **PASS** | 100.00% (217,171 / 217,171) |
| 4 | D: every kind as designed; no true difference in [0.90, 1.0] | **PASS** | 27 / 27 kinds at 100% as designed; 0 of 317,382 true-difference mutations at or above 0.90 |
| 5 | E1 different-plate false links 0; no new E3 class beyond cross-type inconsistency | **PASS** | E1 different plate: 0 / 198,766. E3: 28 pairs >= 0.90, all differ only by cross type present versus absent (27) or that plus a complement (1); `same_cross_same_plate_other_via` 0 |
| 6 | Dead-band test with the new penalty case; full suite green | **PASS** | `test_dead_band_is_empty_and_max_sub_threshold_is_085` (now in `tests/test_matcher_review.py`) enumerates the penalties from the `matcher._PENALTIES` registry the matcher applies and fails for any unregistered `_*_PENALTY` constant; suite: `717 passed` |
| 7 | H: own parcel recovered for 100% of parseable sample rows | **PASS** | 5,000 / 5,000 exact and 5,000 / 5,000 variant; ambiguity 0.22%, false best 0.00% (reported honestly above) |

Extra verification outside the harness (not part of the acceptance table): (a) `parse_canonical(render(parse_canonical(x)))` was checked on all 328,628 parseable rows; the single violation found (`CL 45 # 93 - 36 1103A-1`, where the glued form `1103A1` re-reads `A 1` as a via type) is fixed by emitting the fusion dash in `render` and covered by tests. (b) `AddressIndex.find` was compared with a brute-force `match` scan over all 328,628 rows for 16 real queries (exact and variant, plate tolerance 0 and 1): identical candidate sets and scores in 16 / 16.

## Independent review (after phase 2)

A blind adversarial review found no critical issue. Its main measurement: **0 structural false links out of 368,383 queries whose address is absent from the base** (every candidate returned for an absent address differs from the query only in ways the design accepts on purpose). The links that do exist against an absent address are by design and come from two rules:

- **One-sided known complement (0.98).** A query without a complement links to a unit of the same building that has a known complement (`AP 5`), and vice versa.
- **Cross-type variant (0.97).** `CL 25 NORTE # AV 6 - 30` links to `CL 25 NORTE # 6 - 30` because the cadastre usually omits the cross type.

Findings applied, with the effect on the numbers above:

| Finding | Change | Effect on this evaluation |
|---|---|---|
| W1 | `LinkResult.near_ambiguous` and `alternatives` (another distinct id also at or above the threshold, e.g. a 1.0 with a 0.98 unit behind it); `ambiguous` unchanged; shown by `vincular` | none (the harness reports `ambiguous`, unchanged at 0.22%) |
| W2 | `vincular` plain output prints `avisos:` for the best candidate and per candidate in the `--top` list | none |
| S1 | dead quadrant-abbreviation guard and two always-true plate checks removed; one shared `MAX_PLATE_DIGITS` | none (parse coverage identical, 99.47%) |
| S2 | tests that kill the blocking-key and BOM mutants | none |
| S3 | penalties live in one registry (`matcher._PENALTIES`) that the matcher reads; the dead-band test enumerates it and rejects unregistered `_*_PENALTY` constants | none (scores unchanged) |
| S4 | a known complement kind with an empty value (`LT`, `AP`) or only quadrant words (`AP NORTE`) is opaque: one-sided cost 0.15 and the warning `complemento_no_estructurado`; equal on both sides is still exact | 6 `complement_removed` mutants (bare `LC`/`GA`) now score 0.85 and are classified `complement_removed_opaque` (1,082 -> 1,076 designed matches, 556 -> 562 designed non-matches); 4 base pairs in E1 `same_base_one_side_bare` move from 0.98 to 0.85 (65 -> 61 link) |
| S5 | complement chunks compare as sorted tuples: `AP 1 AP 1` != `AP 1` | none in the sample |
| S6 | README states what NFKD really does with non-ASCII digits (compatibility digits fold to ASCII, only undecomposable digits are rejected) and tests pin it | none |
| S7 | `len(index)` and `stats()["records"]` count distinct ids; `vincular` skips and reports rows with an empty id | `records indexed` 328,628 -> 328,614 (14 surplus rows share a parcel id) |
| S8 | `vincular` parses the CSV strictly (unterminated quote, garbage after a quote, wrong delimiter, row with extra fields: exit 2) | none |
| S9 | optional `max_block_scan` on `AddressIndex.find` and `--max-block-scan` on `vincular`; `truncated` flag; default unchanged | none (default has no cap) |

Design left untouched, as requested: the scoring constants, the complement veto (both present and different) and the 0.02 known one-sided cost, the defaults (threshold 0.90, plate tolerance 0) and the dead band. Acceptance criteria 1-7 above were re-checked with the same settings (`--sample 20000 --seed 42 --link-sample 5000`) and still pass.

## What is still unparsed (1,759 rows, 0.53%)

| Cause | Count | Share of failures | Examples |
|---|---|---|---|
| `via_unexpected_token` | 599 | 34.05% | `K 7CC 8 4 # -`, `K 110 1 9 T # -`, `K 941 W 2 7 # -` |
| `via_two_letters` (letters that are not a quadrant) | 562 | 31.95% | `C 114 2 8 D C 1 # 3 T -`, `K 83A 4 8 A T # -` |
| `cross_two_letters` | 183 | 10.40% | `KR 24 # 9 C B - 47`, `CL 82 # 7 H B - 100` |
| `tail_via_type_then_number` (kept as designed) | 142 | 8.07% | `K 63 # 45 - 29 M40 A5T`, `CL 22A # 112 - 35 CA C102` |
| `no_hash_separator` (free text) | 118 | 6.71% | `K 459 O 2 2 0 T`, `CALLE 11 OESTE Y CALLE 12 OESTE ...` |
| `via_number_missing` (unknown type `M`, `U`, bare `A`) | 90 | 5.12% | `M # -`, `A # -`, `U # -` |
| `cross_unexpected_token` | 49 | 2.79% | `CL 35 BIS # BIS - LT 24`, `C 14 W # T -` |
| `tail_unexpected_token` (misplaced dashes) | 9 | 0.51% | `C 71 D # 3 C N - 16 - 41 C`, `C 30 # 17 - 1- 38` |
| `no_plate_separator` | 4 | 0.23% | `KR 2 D # 13 OESTE 65/97 SS PQ 101/102` |
| `tail_too_long` (prose, more than 40 characters) | 2 | 0.11% | `CARRERA 5 #16-38 LA UNIDAD AQUIDESCRITA ES UN LOCAL COMERCIAL ...` |
| `multiple_addresses` | 1 | 0.06% | `KR 83 A # 2 0 R - 6T # -` |

The biggest buckets (`via_unexpected_token`, `via_two_letters`, `cross_two_letters`, 1,344 rows, 76%) are garbled via segments such as `K 118 1 1 A Z V # 2 T -` or `C 907 T S B 0 5 # -`: several stray digits and letters that look like a corrupted rural or complex-unit code, not a grammar gap that can be closed without guessing. `tail_via_type_then_number` is the deliberate rule that keeps a via type followed by a number out of the tail (it protects against concatenated addresses); `A` joining the via types added a few rows there (`M40 A5T`). Unknown single-letter types (`M`, `U`) stay rejected on purpose.

## Residual risks and observations

- `?` opaque chunks appear in 6,894 parsed rows (2.1% of the base), `BO` in 715, `DP` in 114. They link only to identical tails; the same address without the tail scores 0.85 (no automatic link), by design.
- Plate letters remain part of the plate identity. Among parsed rows the letters are `S` 584, `T` 425, `B` 322, `M` 243, `A` 226, `C` 140, `P` 136, `J` 124, ... Whether a letter after the plate is a unit code or a real plate suffix still needs confirmation with the data owner.
- The disambiguation of a lone `E`/`N`/`S`/`O`/`W` after a suffix number (quadrant when it closes the segment) is a heuristic; it did not create a single failing case in the sample but it is a design choice, documented in the README.
- Ambiguity is inherent to the base (268 canonical strings shared by several parcels). `AddressIndex.find` exposes it (`ambiguous`, all candidates) instead of hiding it.
- E1 `same_base_one_side_bare` is now split: 61 pairs at 0.98 (known kinds with a value link) and 70 at 0.85 (opaque or valueless known kind, do not link).

## Appendix: full harness output

```text
EVALUATION AGAINST THE CADASTRE
rows=330387 sample_rows=20000 (requested=20000) parseable_in_sample=19900 seed=42

== A. Parse coverage (all rows) ==
parse_ok: 328628 / 330387 = 99.47%
parse_fail: 1759 = 0.53%

Failure notes (family):
family                       count  share_of_failures
---------------------------  -----  -----------------
token_inesperado             1367   77.71%           
multiples_direcciones        143    8.13%            
numero_via_faltante          129    7.33%            
falta_separador_hash         118    6.71%            
complemento_demasiado_largo  2      0.11%            

Failure notes (exact, top 20):
note                   count
---------------------  -----
token_inesperado:B     180  
token_inesperado:1     147  
multiples_direcciones  143  
numero_via_faltante    129  
token_inesperado:2     127  
falta_separador_hash   118  
token_inesperado:8     79   
token_inesperado:5     77   
token_inesperado:4     66   
token_inesperado:3     52   
token_inesperado:C     52   
token_inesperado:T     50   
token_inesperado:6     47   
token_inesperado:0     42   
token_inesperado:V     39   
token_inesperado:9     34   
token_inesperado:I     30   
token_inesperado:D     29   
token_inesperado:7     28   
token_inesperado:A     27   

Failure causes (heuristic location of the grammar mismatch):
cause                      count  share   examples                                                                                                                     
-------------------------  -----  ------  -----------------------------------------------------------------------------------------------------------------------------
via_unexpected_token       599    34.05%  K 7CC 8 4 # - | K 110 1 9 T # - | K 941 W 2 7 # -                                                                            
via_two_letters            562    31.95%  C 114 2 8 D C 1 # 3 T - | K 83A 4 8 A T # - | K 941 A W 3 7 # -                                                              
cross_two_letters          183    10.40%  KR 24 # 9 C B - 47 | C 61 N # 3 B J - 14 T | CL 82 # 7 H B - 100                                                             
tail_via_type_then_number  142    8.07%   K 63 # 45 - 29 M40 A5T | CL 22A # 112 - 35 CA C102 | K 121 # 10 - 46 CAS A1                                                  
no_hash_separator          118    6.71%   K 459 O 2 2 0 T | CALLE 11 OESTE Y CALLE 12 OESTE -CARRERAS 24A Y 24B SECTOR EL MORTI/AL DE LA COMUNA 19 | C 13A Y 13BIS K 78
via_number_missing         90     5.12%   M # - | A # - | U # -                                                                                                        
cross_unexpected_token     49     2.79%   CL 35 BIS # BIS - LT 24 | C 14 W # T - | CL 35 BIS # BIS - LT 13                                                             
tail_unexpected_token      9      0.51%   C 71 D # 3 C N - 16 - 41 C | C 30 # 17 - 1- 38 | C 101 # 28 - - 3 - 22                                                       
no_plate_separator         4      0.23%   KR 2 D # 13 OESTE 65/97 SS PQ 101/102 | CL 15 # 121 C 150 CA 7 | A 5 C # 23 D NORTE 65                                       
tail_too_long              2      0.11%   KR 42 C # 54 C - Calle 54C entre Carrera 42D y Carrera 42D | CARRERA 5 #16-38 LA UNIDAD AQUIDESCRITA ES UN LOCAL COMERCIAL 21
multiple_addresses         1      0.06%   KR 83 A # 2 0 R - 6T # -                                                                                                     

Failing shape signatures (top 25 of 594):
#   count  share  signature              examples                                               
--  -----  -----  ---------------------  -------------------------------------------------------
1   107    6.08%  CL 9 # 9 A A - 9       CL 82 # 7 H B - 100 | CL 89 # 7 S B - 09               
2   63     3.58%  A 9 A 9 9 # -          K 941 W 2 7 # - | K 751 B 0 9 # -                      
3   50     2.84%  A 9A 9 A 9 9 # -       K 74C 1 B 3 4 # - | K 78A 2 D 5 3 # -                  
4   29     1.65%  A 9A 9 9 A # -         K 26G 8 8 T # - | C 15A 3 9 C # -                      
5   24     1.36%  KR 9 A 9 9 # 9 - 9     KR 1 D 2 2 # 56 - 55 | KR 1 D 2 2 # 57 - 43            
6   23     1.31%  A 9 A A 9 9 # -        K 941 A W 3 7 # - | K 941 A W 5 1 # -                  
7   23     1.31%  A 9A 9 9 A A 9 # 9 -   K 94A 1 1 A W 2 # 6 - | K 94A 2 1 A W 6 # 6 -          
8   21     1.19%  A 9A 9 9 A 9 A # -     K 85A 2 0 W 1 T # - | K 76A 2 2 B 4 T # -              
9   20     1.14%  A 9 # 9 - 9 A9 A9A     K 63 # 45 - 29 M40 A5T | K 59 # 45 - 12 M40 A18T       
10  20     1.14%  A 9 9 9 A # -          K 110 1 9 T # - | C 201 2 1 T # -                      
11  19     1.08%  A 9 A # 9 A A - 9 A    C 61 N # 3 B J - 14 T | C 14 B # 56 Z V - 6 A          
12  19     1.08%  A 9A 9 9 9 9 9 # -     K 1AH 5 9 1 6 7 # - | K 1AH 5 9 1 7 9 # -              
13  17     0.97%  A 9A 9 9 A A # -       K 83A 4 8 A T # - | C 13C 7 0 Z V # -                  
14  16     0.91%  A 9 A A A 9 9 # -      C 907 T S B 0 5 # - | C 907 T S B 5 1 # -              
15  15     0.85%  A 9 A 9 # -            K 23 TR 2 # - | K 23 TR 1 # -                          
16  15     0.85%  A 9A 9 9 9 9 # -       K 1IF 5 1 1 2 # - | C 4NW 4 6 4 9 # -                  
17  15     0.85%  A 9A 9 A 9 9 9 # -     K 74C 1 B 1 1 2 # - | K 74C 1 B 1 2 4 # -              
18  15     0.85%  CL 9 BIS # BIS - LT 9  CL 35 BIS # BIS - LT 24 | CL 35 BIS # BIS - LT 13      
19  14     0.80%  A 9 # 9 A 9 - 9 A9A 9  C 124 # 28 D 1 - 52 S5T 12 | C 124 # 28 D 1 - 88 S5T 21
20  14     0.80%  A 9 9 A 9 9 9 # A -    C 167 3 A 1 2 7 # T - | K 425 4 D 8 3 0 # T -          
21  14     0.80%  A 9 9 A A # -          K 181 8 A T # - | C 911 4 Z V # -                      
22  14     0.80%  A 9A 9 9 9 A # -       C 11A 1 1 6 T # - | K 26G 5 9 0 T # -                  
23  13     0.74%  A # -                  M # - | A # -                                          
24  13     0.74%  A 9 9 A 9 A # -        K 881 6 B 1 T # - | K 501 1 D 4 L # -                  
25  13     0.74%  A 9A 9 9 A 9 9 # A -   K 47D 5 4 P 8 2 # T - | C 48A 9 0 C 1 1 # T -          

Among PARSED addresses: plate letters [('S', 584), ('T', 425), ('B', 322), ('M', 243), ('A', 226), ('C', 140), ('P', 136), ('J', 124), ('G', 87), ('H', 61), ('N', 50), ('D', 44)]; unregistered complement kinds [('?', 6894), ('BO', 715), ('DP', 114), ('T', 100), ('GASS', 72), ('GAS', 72), ('SO', 60), ('PQS', 30), ('SS', 22), ('PQSS', 21), ('BA', 21), ('BB', 18), ('B', 17), ('BJ', 15), ('BC', 15)]

== B. Self-match and symmetry ==
check                                                        total   violations
-----------------------------------------------------------  ------  ----------
match(a, a) is MATCH with score 1.0                          19900   0         
match(a, b) == match(b, a) (mutations + random cross pairs)  346670  0         

== C. Recall on format variants (score >= 0.9) ==
variant              n      hits   recall   miss_unparseable  mean_score
-------------------  -----  -----  -------  ----------------  ----------
accent_marks         19900  19900  100.00%  0                 1.0000    
alias_dotted         19900  19900  100.00%  0                 1.0000    
alias_long           19900  19900  100.00%  0                 1.0000    
complement_alias     1305   1305   100.00%  0                 1.0000    
complement_reorder   92     92     100.00%  0                 1.0000    
complement_zero_pad  1618   1618   100.00%  0                 1.0000    
extra_whitespace     19900  19900  100.00%  0                 1.0000    
glued                15489  15489  100.00%  0                 1.0000    
glued_type           19900  19900  100.00%  0                 1.0000    
hash_no_dot          19900  19900  100.00%  0                 1.0000    
hash_ordinal         19900  19900  100.00%  0                 1.0000    
hash_tight           19900  19900  100.00%  0                 1.0000    
lowercase            19900  19900  100.00%  0                 1.0000    
plate_zero_pad       19567  19567  100.00%  0                 1.0000    
overall: 217171 / 217171 = 100.00%

== D. Rejection of true differences (correct = score < 0.9; designed-match kinds correct = score >= threshold) ==
mutation                   expected  n      as_designed  rate     veto(0.0)  penalized  passed>=0.90  mean_score
-------------------------  --------  -----  -----------  -------  ---------  ---------  ------------  ----------
complement_added           match     18262  18262        100.00%  0          0          18262         0.9800    
complement_removed         match     1076   1076         100.00%  0          0          1076          0.9800    
complement_removed_opaque  no_match  562    562          100.00%  0          562        0             0.8500    
complement_value_change    no_match  1624   1624         100.00%  1624       0          0             0.0000    
cross_bis_add              no_match  19532  19532        100.00%  0          19532      0             0.8500    
cross_bis_remove           no_match  318    318          100.00%  0          318        0             0.8500    
cross_letter_add           no_match  11073  11073        100.00%  0          11073      0             0.8500    
cross_letter_change        no_match  8777   8777         100.00%  0          8777       0             0.7000    
cross_letter_drop          no_match  8777   8777         100.00%  0          8777       0             0.8500    
cross_number_minus1        no_match  19210  19210        100.00%  19210      0          0             0.0000    
cross_number_plus1         no_match  19850  19850        100.00%  19850      0          0             0.0000    
cross_quadrant_add         no_match  17986  17986        100.00%  0          17986      0             0.8500    
cross_quadrant_remove      no_match  1864   1864         100.00%  0          1864       0             0.8500    
plate_minus1               no_match  19425  19425        100.00%  19425      0          0             0.0000    
plate_minus2               no_match  19251  19251        100.00%  19251      0          0             0.0000    
plate_plus1                no_match  19567  19567        100.00%  19567      0          0             0.0000    
plate_plus2                no_match  19567  19567        100.00%  19567      0          0             0.0000    
via_bis_add                no_match  19284  19284        100.00%  0          19284      0             0.8500    
via_bis_remove             no_match  616    616          100.00%  0          616        0             0.8481    
via_letter_add             no_match  8335   8335         100.00%  0          8335       0             0.8500    
via_letter_change          no_match  11565  11565        100.00%  0          11565      0             0.7000    
via_letter_drop            no_match  11565  11565        100.00%  0          11565      0             0.8500    
via_number_minus1          no_match  18934  18934        100.00%  18934      0          0             0.0000    
via_number_plus1           no_match  19900  19900        100.00%  19900      0          0             0.0000    
via_quadrant_add           no_match  18028  18028        100.00%  0          18028      0             0.8500    
via_quadrant_remove        no_match  1872   1872         100.00%  0          1872       0             0.8500    
via_type_change            no_match  19900  19900        100.00%  19900      0          0             0.0000    
score distribution over true-difference mutations (n=317382): bins={'0.00': 177228, '0.01-0.89': 140154, '0.90-0.99': 0, '1.00': 0} top_values=[[0.0, 177228], [0.85, 119807], [0.7, 20342], [0.6141, 5]]
designed-match complement_added: top scores=[[0.98, 18262]]
designed-match complement_removed: top scores=[[0.98, 1076]]

== E. False-link risk inside the cadastre ==
block faces with >=2 records: 25171; pairs available: 3434494; sampled: 206779; skipped (same parcel id): 2
E1. Pairs on the same block face, different parcel ids:
category                      note               pairs   >=0.90  share    score_bins                                                 
----------------------------  -----------------  ------  ------  -------  -----------------------------------------------------------
different_plate               should be veto     198766  0       0.00%    {'0.00': 198766, '0.01-0.89': 0, '0.90-0.99': 0, '1.00': 0}
same_base_complements_differ  should be veto     7784    0       0.00%    {'0.00': 7784, '0.01-0.89': 0, '0.90-0.99': 0, '1.00': 0}  
same_base_one_side_bare       by design (0.98)   131     61      46.56%   {'0.00': 0, '0.01-0.89': 70, '0.90-0.99': 61, '1.00': 0}   
same_base_same_complement     identical address  96      96      100.00%  {'0.00': 0, '0.01-0.89': 0, '0.90-0.99': 0, '1.00': 96}    
E2. Ambiguity inherent to the base:
metric                                         value             
---------------------------------------------  ------------------
have_parcel_ids                                True              
raw_string_duplicates                          0                 
rendered_groups_with_multiple_parcels          268               
rows_in_those_groups                           538               
largest_group                                  3                 
group_size_histogram                           {'2': 266, '3': 2}
pairs_scoring_1_0_but_different_parcels        272               
base_groups_with_more_than_one_row             973               
base_groups_with_multiple_complement_variants  718               
base_pairs_identical_complement_or_both_bare   272               
base_pairs_one_side_bare_designed_match_0_98   1084              
E3. Different base address (same plate, different cross or via), pairs scoring >= 0.90 are false positives:
group                            pairs   >=0.90  share  score_bins                                                      
-------------------------------  ------  ------  -----  ----------------------------------------------------------------
same_via_same_plate_other_cross  114891  28      0.02%  {'0.00': 102526, '0.01-0.89': 12337, '0.90-0.99': 28, '1.00': 0}
same_cross_same_plate_other_via  118397  0       0.00%  {'0.00': 100965, '0.01-0.89': 17432, '0.90-0.99': 0, '1.00': 0} 
  differing fields among false positives [same_via_same_plate_other_cross]: [('cross_type', 27), ('complement,cross_type', 1)]
  false positive [same_via_same_plate_other_cross]: 'D 15 # K 71 A -' vs 'D 15 # 71 A -' score=0.97
  false positive [same_via_same_plate_other_cross]: 'K 80 # 48 -' vs 'K 80 # C 48 -' score=0.97
  false positive [same_via_same_plate_other_cross]: 'CL 13 B # 68 - 70' vs 'C 13 B # K 68 - 70' score=0.97
  false positive [same_via_same_plate_other_cross]: 'KR 26 # 29 - 42' vs 'KR 26 # TV 29 - 42' score=0.97
  false positive [same_via_same_plate_other_cross]: 'C 56 # K 1 B -' vs 'C 56 # 1 B -' score=0.97

== F. Threshold sensitivity (positives = C variants, negatives = D true differences) ==
threshold  plate_tol  tp      fp      fn  tn      precision  recall  f1    
---------  ---------  ------  ------  --  ------  ---------  ------  ------
0.70       0          217171  140149  0   177233  0.6078     1.0000  0.7560
0.85       0          217171  119807  0   197575  0.6445     1.0000  0.7838
0.90       0          217171  0       0   317382  1.0000     1.0000  1.0000
0.95       0          217171  0       0   317382  1.0000     1.0000  1.0000
1.00       0          217171  0       0   317382  1.0000     1.0000  1.0000
0.90       1          217171  38992   0   278390  0.8478     1.0000  0.9176
0.90       2          217171  77810   0   239572  0.7362     1.0000  0.8481

== G. Throughput (single thread) ==
metric                        value 
----------------------------  ------
match pairs timed             20000 
match pairs/second            25391 
mean match time (us)          39.4  
addresses parsed (all rows)   330387
mean parse time (us/address)  14.0  

== H. Linking against the full cadastre (AddressIndex, sample=5000) ==
index metric                                 value 
-------------------------------------------  ------
records indexed                              328614
distinct parcel ids among them               328614
blocks                                       178576
largest block                                293   
build time incl. parsing (s)                 5.54  
index build memory delta (MiB, working set)  165.3 
process peak working set (MiB)               563.9 

queries         n     top1_own  own_missing%  own_missing  ambiguous  tie_wrong_first  false_best  no_best  unparseable  avg_cand  avg_compared  max_compared  queries/s
--------------  ----  --------  ------------  -----------  ---------  ---------------  ----------  -------  -----------  --------  ------------  ------------  ---------
exact address   5000  99.94%    0.00%         0            0.22%      3                0           0        0            1.011     7.00          293           9963     
format variant  5000  99.94%    0.00%         0            0.22%      3                0           0        0            1.011     7.00          293           9807     

wall time: 88.5s
```
