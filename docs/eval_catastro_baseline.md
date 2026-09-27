# Baseline evaluation against the Cali cadastre

Phase 1 (measurement only). No matcher or parser code was changed.

## Methodology

- Harness: `tools/eval_catastro.py` (stdlib plus `pyarrow` for reading only). Run: `--sample 20000 --seed 42`, all other options default. Deterministic: two runs with the same seed give identical results (timings aside).
- Corpus: `catastro_docs.parquet`, 330,387 rows. Columns: `direccion`, `numero_predial_nacional`, `manzana`, `comuna`, `barrio`, `barrio_code`, `centroid_lon`, `centroid_lat`, `n_predios`, `objectid`, `x_m`, `y_m`, `doc_id`. The address column is `direccion`; the parcel id column is `numero_predial_nacional` (330,372 distinct values over 330,387 rows).
- Table A uses all 330,387 rows. Tables B, C, D, F, G use a seeded sample of 20,000 rows, of which 19,008 parse (the sample parse rate matches the full one). Table E uses the whole cadastre, with pair sampling capped at 200,000 pairs.
- Positives (C) are formatting variants of a parseable address that must score >= 0.90. Negatives (D) are one-field mutations that must score < 0.90, except adding or removing a whole complement, which is designed to match at 0.98.
- F: positives are the C variants, negatives are the D mutations expected to be NO_MATCH. Designed-match complement mutations are excluded from F. Plate tolerance is only recomputed for pairs whose plate comparison is a numeric "difiere", which is the only case tolerance can change (exact).
- Privacy: only aggregates and at most 5 example addresses per category are shown; parcel ids are never printed.
- The full plain-text harness output (tables A to G) is in the appendix and is the source of truth for all numbers below.

## Headline results

| Area | Result |
|---|---|
| A. Parse coverage | 314,107 / 330,387 = **95.07%** parse OK; 16,280 failures (4.93%) |
| B. Invariants | Self-match violations: 0 / 19,008. Symmetry violations: 0 / 332,209 pairs |
| C. Format-variant recall | 205,910 / 205,911 = **100.00%** (14 variant kinds; 1 miss) |
| D. True-difference rejection | 100% as designed for all 26 mutation kinds; scores only ever 0.0, 0.70, 0.85 (true differences) or 0.98 (designed) |
| E. False links in the cadastre | Same block face: 0 unexpected links >= 0.90 in 205,371 sampled pairs. Cross-face hard negatives: 19 of 230,816 pairs >= 0.90, all cross-type one-sided (0.97) |
| F. Thresholds | 0.90, 0.95, 1.00 identical (P = R = 1.0); 0.70 and 0.85 lose precision (0.61, 0.64); plate tolerance 1 and 2 cost precision (0.84, 0.73) |
| G. Throughput | about 23-26k `match` pairs/s single thread (about 40 us/pair); parse about 13-21 us/address |

Conclusion: the scoring logic behaves exactly as designed on real data. The measurable weakness is **parse coverage** (4.93% of the base is rejected), not matching quality.

## A. Parse failures: what the parser rejects

Failure causes (heuristic location of the grammar mismatch, `failure_cause`), 16,280 failures:

| Cause | Count | Share of failures | Share of all rows | Examples |
|---|---|---|---|---|
| plate_missing_trailing_dash | 4,722 | 29.00% | 1.43% | `C 9 W # 0 -`, `C 1 # 74 -` |
| tail_number_then_letter | 4,648 | 28.55% | 1.41% | `K 49 E # 49 - 50 8 C`, `C 65 B # 2 D - 32 12 C` |
| via_two_letters | 1,507 | 9.26% | 0.46% | `C 70 B N # 4 C - 104 38 C` |
| tail_starts_with_number | 1,323 | 8.13% | 0.40% | `K 1 D # 46 A - 44 8BC`, `K 47 B # 54 C - 89 2AC` |
| plate_slot_not_number | 1,233 | 7.57% | 0.37% | `KR 69 # 33 - LT 20`, `C 13 A 1 # 70 - T` |
| via_number_missing | 956 | 5.87% | 0.29% | `A 9 W # -`, `M # -` |
| cross_two_letters | 876 | 5.38% | 0.27% | `C 71 I # 3 C N - 13 66 C` |
| tail_no_known_kind | 623 | 3.83% | 0.19% | `CL 9 # 51 - 46 GASS 5` |
| other | 266 | 1.63% | 0.08% | `C 1 A BIS O # 81 - 19` |
| no_hash_separator | 118 | 0.72% | 0.04% | free-text addresses |
| no_plate_separator | 5 | 0.03% | 0.00% | |
| multiple_addresses | 3 | 0.02% | 0.00% | `K 125 # # 18 - 55` |

Parser notes: `token_inesperado` 9,719 (59.70%), `placa_faltante` 5,373 (33.00%), `numero_via_faltante` 1,004, `falta_separador_hash` 118, `multiples_direcciones` 66. The most frequent unexpected tokens are single letters `N` (1,023), `O` (576), `W` (365), which look like abbreviated quadrants after a street letter, and bare numbers (`1`, `5`, `2`, ...) that start a unit after the plate. The top 25 shape signatures (1,497 distinct in total) are in the appendix; signature 1 (`A 9 A # 9 - 9 9 A`, 942 rows) and signature 2 (`A 9 # 9 - 9 9 A`, 724 rows) are the "number plus single letter after the plate" pattern.

Observation among addresses that DO parse: 528 have a plate letter, and the letters are dominated by `T` (323), `C` (61), `P` (25), `W` (25). Together with the failing "unit number then single letter" pattern, this suggests single letters after the plate may be unit-kind codes (for example tower, house, floor) that the parser currently absorbs as a plate letter, which then acts as a hard veto in the matcher. This is a hypothesis from the data shape only and needs confirmation with the data owner. In addition, 100 parsed rows carry unregistered complement kinds (`SO` 41, a bare number `1` 23, `PISO` 8, `SEC` 6, `SS` 3, `NIV` 2).

## C. Format-variant recall

100.00% overall. The single miss: `CL 48 # 99 - 20 P 1 PQ 20` with zero-padded complement (`P 01 PQ 020`) scores 0.0 because the parser absorbs `P` into the plate (`20P`) and treats the leading `1` as an unregistered complement kind, whose key is not digit-normalized (`1` vs `01`). It is the same root cause as the plate-letter observation above.

## D. Rejection of true differences

All 26 kinds behave as designed. Vetoes (score 0.0): via number, cross number, via type, plate +/-1 and +/-2, complement value change. Penalized: street letter add/drop 0.85, letter change 0.70, BIS add/remove 0.85, quadrant add/remove 0.85. Designed matches: complement added (17,942) and removed (1,066) score 0.98. Over 303,697 true-difference mutations: 170,228 at 0.0, 114,045 at 0.85, 19,424 at 0.70, none in [0.90, 1.0].

## E. False-link risk inside the cadastre

- 24,078 block faces (same via and cross signature) hold at least 2 records, with 3,294,176 possible pairs.
- E1 (205,371 sampled same-face pairs): different plate 198,774 pairs, 0 above 0.90. Same base with different complements 6,534, 0 above 0.90. Same base where one side lacks a complement (by design 0.98): 39 of 39 link. Identical address for different parcels: 23 of 23 link at 1.0.
- E2 (ambiguity inherent to the base): 0 raw duplicate strings, but 150 canonical (rendered) strings are shared by more than one parcel (301 rows, largest group 3), giving 152 pairs that score 1.0 for different parcels. 453 base addresses have more than one row; 305 of them have several complement variants, producing 586 bare-versus-unit pairs that link at 0.98 by design.
- E3 (different base, same plate): `same_via_same_plate_other_cross` 19 of 115,267 pairs at or above 0.90 (0.02%); `same_cross_same_plate_other_via` 0 of 115,549. All 19 differ only by cross type present versus absent (0.97), for example `CL 35 A NORTE # AV 3 - 96` vs `CL 35 A NORTE # 3 - 96`. These are the same street address written inconsistently for two parcels, so they are base ambiguity rather than a scoring defect. There is no false positive from a genuinely different plate, cross or via number.

## F and G

See the appendix. Precision at thresholds 0.90, 0.95 and 1.00 is identical because every negative score is at most 0.85 and every positive is 1.0; any threshold in (0.85, 0.98] gives the same result, so 0.90 sits in a wide empty gap. If the designed-match complement mutations were counted as positives, threshold 1.00 would lose them (mean score 0.98). Plate tolerance 1 admits 37,907 false links and tolerance 2 admits 75,653 in this sample, because neighbouring plates are different parcels.

## Ranked recommended improvements

1. **Parse a unit given as "number plus letter" after the plate** (`- 50 8 C`, `- 44 8BC`, `- 89 2AC`, `S7M 53T`). Evidence: `tail_number_then_letter` 4,648 plus `tail_starts_with_number` 1,323 = 5,971 failures (36.7% of failures, 1.81% of all rows). First confirm the meaning of the trailing letters with the data owner. Fixing this also removes the plate-letter absorption risk (528 parsed rows, 323 with `T`) that can turn a unit letter into a hard plate veto.
2. **Accept a trailing empty plate** (`# 74 -`) as "no plate" (a corner). Evidence: 4,722 failures (29.0% of failures, 1.43% of rows). Tradeoff: the matcher already vetoes plate-on-one-side, so behaviour stays conservative.
3. **Accept single-letter quadrant abbreviations** (`N`, `S`, `E`, `O`/`W`) after a street letter. Evidence: `via_two_letters` 1,507 plus `cross_two_letters` 876 = 2,383 failures (14.6%, 0.72% of rows); unexpected-token counts N 1,023, O 576, W 365. Tradeoff: `E`, `N`, `S`, `O` are also street letters, so accept only after another letter.
4. **Accept a complement directly after the dash without a plate** (`- LT 20`, `- T`). Evidence: `plate_slot_not_number` 1,233 (7.6%, 0.37% of rows).
5. **Handle unknown single-letter via types** (`A ...`, `M ...`). Evidence: `via_number_missing` 956 (5.9%). Confirm the intended type first; do not guess.
6. **Tolerate unregistered complement kinds** (`SO`, `PISO`, `SEC`, `SS`, `NIV`, `GASS`, `DP`) and register `PISO`. Evidence: `tail_no_known_kind` 623 (3.8%) plus 100 parsed rows with unregistered kinds. Tradeoff: the current rejection exists to avoid a fabricated one-sided complement scoring 0.98, so any relaxation should keep such tails as warnings or a lower-trust flag.
7. **Normalize digits in unregistered complement keys** (`1` vs `01`). Evidence: the single recall miss (1 of 1,057). Very small, but it is a correctness gap.
8. **Handle ambiguity at the consumer level.** Evidence: 150 canonical strings shared by several parcels (152 pairs at 1.0) and 586 bare-versus-unit pairs at 0.98. A matcher that answers pairwise cannot resolve these; the linker should return all candidates or an "ambiguous" flag. Use blocking by block face: all-pairs over 330,387 rows is about 5.5e10 comparisons, while same-face blocking leaves 3.29M.
9. **Keep the defaults** (threshold 0.90, plate tolerance 0). Evidence: F shows precision and recall of 1.0 in this benchmark; tolerance 1 drops F1 to 0.9157 and tolerance 2 to 0.8448. Lowering the threshold to 0.85 or 0.70 admits street-letter, BIS and quadrant differences (precision 0.64 and 0.61).

Upper bound if items 1 to 5 were fully recovered: 15,265 of the 16,280 failures, which would raise coverage from 95.07% to at most about 99.69%.

## Limitations

- Positives and negatives are synthetic, built from the cadastre's own addresses; recall on real citizen-typed variants is not measured here.
- `failure_cause` is heuristic and independent of the parser notes.
- The cadastre rows are already normalized by an upstream step, so its failures show grammar gaps, not typos.
- E1 samples about 205k of 3.29M same-face pairs; E3 samples about 115k pairs per group type.
- Throughput varies by about 10% between runs (23-26k pairs/s observed).

## Appendix: full harness output

```text
EVALUATION AGAINST THE CADASTRE
rows=330387 sample_rows=20000 (requested=20000) parseable_in_sample=19008 seed=42

== A. Parse coverage (all rows) ==
parse_ok: 314107 / 330387 = 95.07%
parse_fail: 16280 = 4.93%

Failure notes (family):
family                 count  share_of_failures
---------------------  -----  -----------------
token_inesperado       9719   59.70%           
placa_faltante         5373   33.00%           
numero_via_faltante    1004   6.17%            
falta_separador_hash   118    0.72%            
multiples_direcciones  66     0.41%            

Failure notes (exact, top 20):
note                  count
--------------------  -----
placa_faltante        5373 
token_inesperado:N    1023 
numero_via_faltante   1004 
token_inesperado:1    706  
token_inesperado:O    576  
token_inesperado:5    422  
token_inesperado:2    415  
token_inesperado:W    365  
token_inesperado:6    352  
token_inesperado:7    276  
token_inesperado:3    232  
token_inesperado:4    229  
token_inesperado:8    218  
token_inesperado:11   170  
token_inesperado:B    162  
token_inesperado:101  157  
token_inesperado:9    151  
token_inesperado:12   147  
token_inesperado:10   133  
falta_separador_hash  118  

Failure causes (heuristic location of the grammar mismatch):
cause                        count  share   examples                                                                                                                     
---------------------------  -----  ------  -----------------------------------------------------------------------------------------------------------------------------
plate_missing_trailing_dash  4722   29.00%  C 9 W # 0 - | C 1 # 74 - | K 7CC 8 4 # -                                                                                     
tail_number_then_letter      4648   28.55%  K 49 E # 49 - 50 8 C | C 65 B # 2 D - 32 12 C | C 122 B # 28 D 2 - 16 S7M 53T                                                
via_two_letters              1507   9.26%   C 3 A O # K 90 - | C 70 B N # 4 C - 104 38 C | C 114 2 8 D C 1 # 3 T -                                                       
tail_starts_with_number      1323   8.13%   K 1 D # 46 A - 44 8BC | K 47 B # 54 C - 89 2AC | K 47 B # 54 C - 37 8BC                                                      
plate_slot_not_number        1233   7.57%   K 47B # 55 B - Q2 T | KR 69 # 33 - LT 20 | C 13 A 1 # 70 - T                                                                 
via_number_missing           956    5.87%   A 9 W # - | M # - | A 9 A N # 54 N - 65 T                                                                                    
cross_two_letters            876    5.38%   C 71 I # 3 C N - 13 66 C | K 46 # 20 B O - | KR 24 # 9 C B - 47                                                              
tail_no_known_kind           623    3.83%   CL 9 # 51 - 46 GASS 5 | K 125 # 19 - 58 SS 3 G | CL 34 A NORTE # 2 B - 120 DP 4                                              
other                        266    1.63%   C 1 A BIS O # 81 - 19 | C 2 A BIS O # 82 - 16 | K 80 # 2 A BIS O - 17                                                        
no_hash_separator            118    0.72%   K 459 O 2 2 0 T | CALLE 11 OESTE Y CALLE 12 OESTE -CARRERAS 24A Y 24B SECTOR EL MORTI/AL DE LA COMUNA 19 | C 13A Y 13BIS K 78
no_plate_separator           5      0.03%   CALLE 16 A CON CARRERA 115 LOTE #5 | KR 2 D # 13 OESTE 65/97 SS PQ 101/102 | CL 15 # 121 C 150 CA 7                          
multiple_addresses           3      0.02%   KR 83 A # 2 0 R - 6T # - | K 125 # # 18 - 55 | K 111 # # 15 - - 120                                                          

Failing shape signatures (top 25 of 1497):
#   count  share  signature                 examples                                                      
--  -----  -----  ------------------------  --------------------------------------------------------------
1   942    5.79%  A 9 A # 9 - 9 9 A         K 49 E # 49 - 50 8 C | K 7 U # 72 - 24 2 G                    
2   724    4.45%  A 9 # 9 - 9 9 A           K 114 # 9 - 50 2 C | K 83 # 18 - 05 1 C                       
3   692    4.25%  A 9 A # 9 -               C 9 W # 0 - | K 42 C # 2 -                                    
4   655    4.02%  A 9 # 9 -                 C 1 # 74 - | C 18 # 122 -                                     
5   518    3.18%  A 9 A # 9 A - 9 9 A       C 65 B # 2 D - 32 12 C | C 3 O # 24 B - 31 2 P                
6   508    3.12%  A 9 # 9 A - 9 9 A         C 63 # 2 E - 1 327 C | C 62 # 2 E - 1 219 C                   
7   479    2.94%  A 9 A # 9 A -             K 9 N # 72 I - | C 7 W # 40 B -                               
8   438    2.69%  A 9 # 9 A -               K 41 # 31 B - | K 24 # 112 A -                                
9   235    1.44%  A 9 A A # 9 A - 9 9 A     C 70 B N # 4 C - 104 38 C | K 3 B N # 71 F - 19 100 C         
10  215    1.32%  A 9 A # 9 A A - 9 9 A     C 71 I # 3 C N - 13 66 C | C 71 F # 3 C N - 21 61 C           
11  186    1.14%  A 9 A # 9 A 9 - 9 A9A 9A  C 122 B # 28 D 2 - 16 S7M 53T | C 122 E # 28 D 2 - 21 S6M 513T
12  184    1.13%  A 9 # 9 A - 9 A 9 A       K 103 # 12 C - 50 J 8 C | K 103 # 12 B - 106 BJ 4 C           
13  176    1.08%  A 9 # 9 - 9 9             C 111 # 28 - 4 19 | K 93 # 4 - 50 68                          
14  157    0.96%  A 9 A A # 9 A A - 9       A 9 A O # 19 C O - 13 | A 3 A N # 23 D N - 59                 
15  147    0.90%  CL 9 # - LT 9             CL 35 # - LT 39 | CL 34 # - LT 25                             
16  135    0.83%  A 9 9 # 9 A A - 9         K 94 1 # 1 B O - 03 | C 72 2 # 3 A N - 41                     
17  134    0.82%  A 9 A A # 9 A BIS - 9     C 2 B O # 73 B BIS - 31 | C 18 A O # 8 A BIS - 87             
18  127    0.78%  A 9 A # -                 A 9 W # - | C 40 O # -                                        
19  124    0.76%  A 9 A 9 # 9 A A - 9 9 A   C 71 I 2 # 3 A N - 23 21 C | C 71 I 2 # 3 E N - 65 14 C       
20  122    0.75%  A 9 A # 9 A - 9 9A A      C 54 E # 47 C - 29 12A C | C 54 B # 48 B - 36 19A C           
21  117    0.72%  A 9 A 9 # 9 A - 9 A9A 9A  K 28 D 3 # 121 B - 32 S7M 88T | K 28 D 6 # 124 A - 20 S6M 316T
22  108    0.66%  CL 9 # 9 A A - 9          CL 82 # 7 H B - 100 | CL 89 # 7 S B - 09                      
23  107    0.66%  A 9 A A # 9 -             A 2 A N # 52 - | C 1 A W # 67 -                               
24  106    0.65%  A 9 A A # 9 A -           C 6 A W # 39 A - | A 4 A W # 22 B -                           
25  105    0.64%  A 9 # 9 A 9 -             C 55 # 41 D 1 - | K 72 # 45 A 55 -                            

Among PARSED addresses: plate letters [('T', 323), ('C', 61), ('P', 25), ('W', 25), ('B', 21), ('G', 18), ('A', 18), ('D', 11), ('J', 6), ('F', 5), ('E', 4), ('N', 3)]; unregistered complement kinds [('SO', 41), ('1', 23), ('PISO', 8), ('SEC', 6), ('2', 4), ('SS', 3), ('101', 2), ('NIV', 2), ('302', 1), ('3', 1), ('7', 1), ('LA', 1), ('SUBT', 1), ('PR', 1), ('201', 1)]

== B. Self-match and symmetry ==
check                                                        total   violations
-----------------------------------------------------------  ------  ----------
match(a, a) is MATCH with score 1.0                          19008   0         
match(a, b) == match(b, a) (mutations + random cross pairs)  332209  0         

== C. Recall on format variants (score >= 0.9) ==
variant              n      hits   recall   miss_unparseable  mean_score
-------------------  -----  -----  -------  ----------------  ----------
accent_marks         19008  19008  100.00%  0                 1.0000    
alias_dotted         18440  18440  100.00%  0                 1.0000    
alias_long           18440  18440  100.00%  0                 1.0000    
complement_alias     1066   1066   100.00%  0                 1.0000    
complement_reorder   92     92     100.00%  0                 1.0000    
complement_zero_pad  1057   1056   99.91%   0                 0.9991    
extra_whitespace     19008  19008  100.00%  0                 1.0000    
glued                14752  14752  100.00%  0                 1.0000    
glued_type           19008  19008  100.00%  0                 1.0000    
hash_no_dot          19008  19008  100.00%  0                 1.0000    
hash_ordinal         19008  19008  100.00%  0                 1.0000    
hash_tight           19008  19008  100.00%  0                 1.0000    
lowercase            19008  19008  100.00%  0                 1.0000    
plate_zero_pad       19008  19008  100.00%  0                 1.0000    
overall: 205910 / 205911 = 100.00%
  miss[complement_zero_pad]: 'CL 48 # 99 - 20 P 1 PQ 20' -> 'CL 48 # 99 - 20 P 01 PQ 020' score=0.0 (veto: complemento difiere (1, PQ 20 vs 01, PQ 20))

== D. Rejection of true differences (correct = score < 0.9; designed-match kinds correct = score >= threshold) ==
mutation                 expected  n      as_designed  rate     veto(0.0)  penalized  passed>=0.90  mean_score
-----------------------  --------  -----  -----------  -------  ---------  ---------  ------------  ----------
complement_added         match     17942  17942        100.00%  0          0          17942         0.9800    
complement_removed       match     1066   1066         100.00%  0          0          1066          0.9800    
complement_value_change  no_match  1061   1061         100.00%  1061       0          0             0.0000    
cross_bis_add            no_match  18723  18723        100.00%  0          18723      0             0.8500    
cross_bis_remove         no_match  284    284          100.00%  0          284        0             0.8500    
cross_letter_add         no_match  10647  10647        100.00%  0          10647      0             0.8500    
cross_letter_change      no_match  8360   8360         100.00%  0          8360       0             0.7000    
cross_letter_drop        no_match  8360   8360         100.00%  0          8360       0             0.8500    
cross_number_minus1      no_match  18413  18413        100.00%  18413      0          0             0.0000    
cross_number_plus1       no_match  19007  19007        100.00%  19007      0          0             0.0000    
cross_quadrant_add       no_match  17212  17212        100.00%  0          17212      0             0.8500    
cross_quadrant_remove    no_match  1795   1795         100.00%  0          1795       0             0.8500    
plate_minus1             no_match  18899  18899        100.00%  18899      0          0             0.0000    
plate_minus2             no_match  18738  18738        100.00%  18738      0          0             0.0000    
plate_plus1              no_match  19008  19008        100.00%  19008      0          0             0.0000    
plate_plus2              no_match  19008  19008        100.00%  19008      0          0             0.0000    
via_bis_add              no_match  18422  18422        100.00%  0          18422      0             0.8500    
via_bis_remove           no_match  586    586          100.00%  0          586        0             0.8500    
via_letter_add           no_match  7944   7944         100.00%  0          7944       0             0.8500    
via_letter_change        no_match  11064  11064        100.00%  0          11064      0             0.7000    
via_letter_drop          no_match  11064  11064        100.00%  0          11064      0             0.8500    
via_number_minus1        no_match  18078  18078        100.00%  18078      0          0             0.0000    
via_number_plus1         no_match  19008  19008        100.00%  19008      0          0             0.0000    
via_quadrant_add         no_match  17289  17289        100.00%  0          17289      0             0.8500    
via_quadrant_remove      no_match  1719   1719         100.00%  0          1719       0             0.8500    
via_type_change          no_match  19008  19008        100.00%  19008      0          0             0.0000    
score distribution over true-difference mutations (n=303697): bins={'0.00': 170228, '0.01-0.89': 133469, '0.90-0.99': 0, '1.00': 0} top_values=[[0.0, 170228], [0.85, 114045], [0.7, 19424]]
designed-match complement_added: top scores=[[0.98, 17942]]
designed-match complement_removed: top scores=[[0.98, 1066]]

== E. False-link risk inside the cadastre ==
block faces with >=2 records: 24078; pairs available: 3294176; sampled: 205371; skipped (same parcel id): 1
E1. Pairs on the same block face, different parcel ids:
category                      note               pairs   >=0.90  share    score_bins                                                 
----------------------------  -----------------  ------  ------  -------  -----------------------------------------------------------
different_plate               should be veto     198774  0       0.00%    {'0.00': 198774, '0.01-0.89': 0, '0.90-0.99': 0, '1.00': 0}
same_base_complements_differ  should be veto     6534    0       0.00%    {'0.00': 6534, '0.01-0.89': 0, '0.90-0.99': 0, '1.00': 0}  
same_base_one_side_bare       by design (0.98)   39      39      100.00%  {'0.00': 0, '0.01-0.89': 0, '0.90-0.99': 39, '1.00': 0}    
same_base_same_complement     identical address  23      23      100.00%  {'0.00': 0, '0.01-0.89': 0, '0.90-0.99': 0, '1.00': 23}    
E2. Ambiguity inherent to the base:
metric                                         value             
---------------------------------------------  ------------------
have_parcel_ids                                True              
raw_string_duplicates                          0                 
rendered_groups_with_multiple_parcels          150               
rows_in_those_groups                           301               
largest_group                                  3                 
group_size_histogram                           {'2': 149, '3': 1}
pairs_scoring_1_0_but_different_parcels        152               
base_groups_with_more_than_one_row             453               
base_groups_with_multiple_complement_variants  305               
base_pairs_identical_complement_or_both_bare   152               
base_pairs_one_side_bare_designed_match_0_98   586               
E3. Different base address (same plate, different cross or via), pairs scoring >= 0.90 are false positives:
group                            pairs   >=0.90  share  score_bins                                                      
-------------------------------  ------  ------  -----  ----------------------------------------------------------------
same_via_same_plate_other_cross  115267  19      0.02%  {'0.00': 102813, '0.01-0.89': 12435, '0.90-0.99': 19, '1.00': 0}
same_cross_same_plate_other_via  115549  0       0.00%  {'0.00': 96215, '0.01-0.89': 19334, '0.90-0.99': 0, '1.00': 0}  
  differing fields among false positives [same_via_same_plate_other_cross]: [('cross_type', 18), ('complement,cross_type', 1)]
  false positive [same_via_same_plate_other_cross]: 'CL 13 B # 68 - 70' vs 'C 13 B # K 68 - 70' score=0.97
  false positive [same_via_same_plate_other_cross]: 'CL 35 A NORTE # AV 3 - 96' vs 'CL 35 A NORTE # 3 - 96' score=0.97
  false positive [same_via_same_plate_other_cross]: 'D 26 P 9 # T 105 A - 13' vs 'DG 26 P 9 # 105 A - 13' score=0.97
  false positive [same_via_same_plate_other_cross]: 'CL 39 NORTE # AV 2 A - 47' vs 'CL 39 NORTE # 2 A - 47' score=0.97
  false positive [same_via_same_plate_other_cross]: 'CL 54 NORTE # AV 9 A - 55' vs 'CL 54 NORTE # 9 A - 55' score=0.97

== F. Threshold sensitivity (positives = C variants, negatives = D true differences) ==
threshold  plate_tol  tp      fp      fn  tn      precision  recall  f1    
---------  ---------  ------  ------  --  ------  ---------  ------  ------
0.70       0          205910  133469  1   170228  0.6067     1.0000  0.7552
0.85       0          205910  114045  1   189652  0.6436     1.0000  0.7831
0.90       0          205910  0       1   303697  1.0000     1.0000  1.0000
0.95       0          205910  0       1   303697  1.0000     1.0000  1.0000
1.00       0          205910  0       1   303697  1.0000     1.0000  1.0000
0.90       1          205910  37907   1   265790  0.8445     1.0000  0.9157
0.90       2          205910  75653   1   228044  0.7313     1.0000  0.8448

== G. Throughput (single thread) ==
metric                        value 
----------------------------  ------
match pairs timed             20000 
match pairs/second            23474 
mean match time (us)          42.6  
addresses parsed (all rows)   330387
mean parse time (us/address)  20.8  

wall time: 92.4s
```
