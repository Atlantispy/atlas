# N12 final-assembly manifest (draft r1, for the Step 21 freeze; ACCEPTED as the draft 17:3x, decisions in section 6)

Amended 17:41: WP12 figures (q04smoke3) and the q04 v3b proof on B17/I14, from Storage.
Written 16 Oct 2026, 17:30-17:37 BST, read-only (no runs). Sources: the owners' STATE/HANDOFF files, the optimisation
backlog, the Step 10 freeze list (REVIEW/fixes/step10/FREEZE-LIST.md) and live sha256 read at 17:30. Anything not
in those sources is marked **unknown**. Every SHA is sha256[:8].

Aliases: T = task root; R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1;
C = R/composed-r2/helpers; CG = R/compact-geometry-r1; G = R/geometry-growth-r1;
REVIEW = T/fidelity-integration-20261005/claude-review-steps1-7-20261015.
Lane folders: T/so (Small), T/hs (Heat), T/ck (Kernels), T/ps (Pressure), T/gg (Geometry extras), T/rm (Release).
Module short names: DG = integration_differential_geometry, MFM = integration_moving_face_moments,
MIM = integration_moving_interface_moments, W = integration_wall_measures, E = integration_exterior_mesh,
M = integration_differential_mesh.

Composition effect (the freeze list's key):
- H = helper only.
- S = transform stage: stage digests change, so a new d3 dry run with geometry parity is needed.
- L = heat layout: the compact successor's emitted helpers change, and EXPECTED_HEAT/COLD are re-derived from the
  heat owner's reviewed layout.
- I = identity record: caches regenerate.
- P = package reconciliation on remake, outside the composition.

## 1. Candidates

### Runner (integrates in R)
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| R1 | item 21 driver | R/prepared_interval_driver.py c4f5c4fb -> **6fb4ab6d (live)** | test fb62dac8 green | - | on | H |
| R2 | item 11 fresh driver | R/fresh_interval_driver.py 45a8bea8 (r2 pin) -> **f328f314 (live)** | unknown | - | on | H |
| R3 | other runner drift | launch_fresh_interval 6736b35c -> **ecefde9a (live)**; run_fresh_interval e3d5c342 -> **8e825d29 (live)**; 5 tests (freeze list) | unknown which item | - | on | H |
| R4 | S8 producer (Small, integrated 14:44) | reopen_prepared_restart d93fe9c2 -> **5b7f13bf (live)**; reopen_fresh_restart 59138100 (r2 pin; S8 base c36ad987) -> **f06f4fe0 (live)**; test_s8_producer 50d7c960 (new) | S8 tests + mutants | - | on | H |
| R5 | item 7 reuse start-up measurements | R/run_fresh_interval.py + driver, reader and launcher. **Candidate SHAs unknown.** The owner names run 97137ce5, driver 820ebc0e, reader 55265495 and launcher 7dd02819; whether these are code or test SHAs is unknown. Stores e337fc20. Live run_fresh_interval is still 8e825d29. | tests PASS 95 | q08 HELD | on | H |
| R6 | item 10 phase 2 (after item 7) | unknown | unknown | - | on | H |
| R7 | H4/q01 and q09 review fixes | unknown | done | q01 | on | H |

### Small (Runner integrates)
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| S1 | per-stage query counts | R/run_fresh_interval.py 8e825d29 -> 066a7079; test d93ed6b7 | r4 complete: tests, mutants, refuter | none (exact) | on | H |
| S2 | WP16 pre-advance capture, r7 (= the freeze list's "WP16 wiring") | R/compact_restart_patch.py 9d076c80 -> 301845b1; R/ledger_fresh_interval.py cd89718b -> f303d402; a route-check line in R/prepared_interval_driver.py 6fb4ab6d (local check copy f4f2ccc3, not for application) and in R/fresh_interval_driver.py f328f314 -> 228ddffb; tests in T/so/s2/r7 | r7 tests; 25/25 mutants killed. Still outstanding: ruff, the refuter's r5->r7 delta check, INTEGRATION r7 | q15 HELD (timing) | on | H |
| S3 | item 12, D1-B lazy rows | C/spatial_validation_patch.py 556f2242 -> **not built** | design only | none planned (D-b fixture check) | - | H. Only composition.json pins it, so the freeze list's "transform stage" should read helper. |
| S9 | heat indexed-runtime seal reuse | C/private_heat_indexed_runtime.py 997277d8 -> ec170fc4; test_s9_seal_reuse 341ae911 | tests; 17/17 summary mutants; refuter delta PASS | q20 + smoke HELD (timing) | on | H (composition.json pin only) |

S4 is under Geometry (G9).

### Storage
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| B17 | rev4 binding directory | CG/segment_store.py 1f503604 (live) -> a90ef8f3; CG/storage_codec_integration_patch.py 5102778b (live) -> 39d71ed0; test_b17_binding_directory 25e7339b; test_s1 54edda3f | VERIFIED (marker 16:18); ruff C408x2 + I001 (style only); q04 v3b: 12/12 precondition mutants refused, refuter hardening applied; re-smoke q04smoke4 running | q04 (hold) | on | H |
| I14 | item 14 page fix | CG/record_views.py e0a2a845 (live) -> a6bbb81d; test_item14_page_layer abd3bbd4 | focused r3 PASS; 9/9 mutants; q04 v3b: 12/12 precondition mutants refused, refuter hardening applied; re-smoke q04smoke4 running | joins q04 | on | H |
| WP17 | completed query store | code present | durability PASS (12 kills) | - | **off** (section 5) | H |

### Geometry (G/transforms; base is the RC1 runtime-src)
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| G1 | DG chain 1-5: growth_successor ca41e251, wp20_zero_certificate 11afd37b, items_11_15_off 4cd9a685, wp23_rotation a2e05da2, complementary_cut r3 077aefc1 | DG -> output **unknown** (in Geometry's handoff) | final parity f2 (run_final_parity.sh 88fed7e9) | - | on | S |
| G2 | 5b complementary_cut_adopt 9a7093ad | integration_parallel_results.py -> f48cda05 (the "cpadopt" that item 19 takes as input) | f2 | - | on | S |
| G3 | 6 q2_zero_test a24f3c22 | integration_q2_directed.py -> unknown | **UNVERIFIED until jets-r2** | - | on | S |
| G4 | 7 jets_convolution 696c9d63 | MFM -> c5f2a123 (final-f2 output) | **UNVERIFIED until jets-r2** | - | on | S |
| G5 | progress_hooks ff93181f + geometry_progress 463e1463 | unknown | unknown | - | optional | S |
| G6 | source_handles r2 1d827171 | reuse.py 96e2092c -> 7dfdf209 (already in composed-r2/src) | D-b accepted | - | on | I |
| G7 | workers_six 2296e269; workers_six_endpoint_clamp 82684257; workers6rolling c3fb0b5f | integration_parallel_selection.py (workers 1..6); rolling's file **unknown** | D-j: IV1 w4 305 s / w6 310 s vs 546 s serial; IV2 w4 569 s vs 946 s; IV2 w6 VOID-ENVIRONMENT | q21 re-arm HELD | on | S |
| G8 | WP18 r2: clamp 512/4096 + lookahead | integration_component_volume_auto.py; r1 ae1cd127; r2 output **unknown** (T/gg/wp18-r2) | unknown | q18 HELD | on | S |
| G9 | S4 (Small -> Geometry) | s4roll: rolling module 6daa2d3a -> c6c8a702; s4sel: selection 7d4d4037 -> a0d90167; s4auto: auto fa0cbcaf -> 092dca7c (hunk in `_open` only; goes after WP18) | accepted by Geometry | next package generation | on | S |
| G10 | Step 7 D1 + D2 | D1: contains() in MIM (148 s). D2: _rotated() in MFM (34 s). Outputs **unknown**. | APPROVED; test_d1_d2.py not yet written | - | on | S |
| G11 | D3, D4 | **unknown** | approved | - | on | S |

### Heat (T/hs/transforms; layouts lw -> ld3 -> le3 -> lf3 -> lh)
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| H1a | r3 | exact_growth 94dfc016 -> 750d24ab (transform 9132c9d7) | unknown | in q10a | on | L |
| H1c | r3, stacked on H1a | exact_growth 750d24ab -> 35e77650 (transform c789aae7) | refuter NOT REFUTED | q10a (job c0ffada4, proof lw ld3 le3 lf3 lh; rebooked 12 min) HELD | on | L |
| H2 | | cert_kernel 370b6ec1 -> 3be44650; certification_resources c9bcb788 -> 8b451aa8 | unknown | - | on | L |
| L1 | r4 (transform 21e96aa0) | low_ledger_inventory 42054fb2 -> 462bf6a2. Pinners: certification_resources 8b451aa8 -> fadac10d; finish_inventory_r1 a35505b0 -> 4e6c3a7f; finish_inventory_r2 71ff7d79 -> cdb1028c; geometry_inventory_r1 55216dd5 -> 43d680cf; geometry_inventory_r3 8d7b435c -> f16501d7 | refuter NOT REFUTED; T/hs/evidence/l1-generation-note-r4.md | - | on | L |
| H5a | transform df6905a5, generator e8b7e277 | functionals_kernel_r5 85991687 -> e4c007dd; forward_kernel_r13 5c9ad737 -> 081aac58. Pinners: checkpoint_consumer_r10 aa4a3f8e -> 1e417215; joined_consumer_r6 86c30c5c -> ca752013; restored_binding_r10 53bd2c58 -> 38bb756e; ram_context_r1 a1aab4a7 -> 56a70af2; ram_recovery_r1 ff51b665 -> d4c1b8c4; runtime-src integration_private_heat_cold 6dad6f06 -> 9035d2c4; control.json | tests r3 12/12. **Refuter OWED** (fail-closed): the backlog's NOT REFUTED counts only once Heat shows the refuter record. W4 D-b r14 vs r13 still owed. | - | on | L (pin cascade once; Runner folds it in) |
| r4c | full ABBA | job 51016996 | dry PASS | HELD | - | - |
| N6 | item 11: finish 288 s + project/commit 279 s | **unknown** | unknown | - | on | L (likely) |
| RC7 | seven overridden root copies (freeze list A) | checkpoint_consumer_r10, restored_binding_r10, functionals_parallel_r1, joined_consumer_r6, native_projection_r4, two restored_binding_ram_* | - | - | - | each needs "emitted wins" in N12, or removal by Heat |

### Kernels (T/ck)
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| H3 | r2, stacked on H2 | cert_kernel 3be44650 -> d94fb79b; certification_resources 8b451aa8 -> 1c557e98; new helper 62c100cf (gmpy2; MPFR DLL b81a548e) | refuter fixes applied; q06 CLEAN (q06p2 21/21) | ARMS 4, 100 min / 3.5 GiB, HELD | on | L + I |
| GPY | G-PY r3 (transform f863d0e2) | MFM c5f2a123 -> 3e82a2be | refuter REFUTED, then fixed in r2/r3; q11 CLEAN (q11p4 41/41, smoke s5) | 25 min / 1.0 GiB, HELD | on | S + I |
| I19 | item 19 ip8 r2.2: parallel start-up | new module integration_initial_parallel.py 5ffc7fb2. Transforms (ip3 values; ip8 differs only in the module): dual_geometry 520887ce, differential_geometry 436e170c, parallel_binding 70db056a (binding -> 4eb627dc), parallel_results 73091fd3 (input f48cda05), component_volume_parallel a4785573 | refuter D1 fixed; delta 0 DEFECT | q19 = job_initpar.sh r1 proof 2; status unknown | on | S. The freeze list puts it under Runner; the integrator is **unknown**. |
| D5 | Fraction -> mpq in the W / volume_overlap fallback; T1 is the native _rotated_normal twin | output **not built**; design T/ck/d5/DESIGN.md 0cbff168 | bench1 PASS; ~42 s, about 3.9 % (PROJECTED); in progress | - | on | S |
| L4 | identity pins (approved) | In reuse.py `_runtime_record` (+ `_loaded_binary`, exact_arithmetic.runtime()), pin: `_decimal.pyd` with its libmpdec version (2.5.1 now, unrecorded); python312.dll (sys.dllhandle, unhashed today); the stdlib arithmetic sources (fractions.py, and decimal.py/_pydecimal.py as used). Spec: T/rm/LANGUAGES.md section 6 L4. | **not built; owner: Kernels** (decided 17:3x) | - | on | I: bundle it (section 2, X1) |

### Pressure (T/ps)
| # | Item | Files: base -> output | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| P1 | r5 | new module runtime/integration_pressure_walls.py 61d2019e. Transforms (r2 era): p1_binding 0c8fe3be, p1_dispatch ba949b37, p1_loop 0928d1ad. c/full3 outputs: binding 7300089c, dispatch ff68c80a. Compositions c/full6 and c/w6f5. | r5 gate APPROVED; sm7 serial 56.1 s -> auto1 45.9 s | proof waits on q02; harness ab_pressure_r4 2e6aa2f5 | on | S |
| P2 | r2 | p2_spatial b498c170 -> spatial 1f4f50cc, diff_pressure e01a7af2 | refuter HOLD | - | held | S |
| P3 | r2 | p3_coupling ba828fd9 -> coupling 7c2c3b99 | refuter HOLD | - | held | S |
| P4 | | **unknown** | unknown | - | - | - |
| N9 | width r2, an identity successor (must land before the fresh runs; Geometry integrates) | Planned transforms: width_pose_round.py, covering (b-ray) W._pose_vector and (b-quat) E._representative_pose; width_deviation_bound.py, covering (c) M l.675/954. Outputs **not built**. | DESIGN T/ps/width/DESIGN.md f6e6dc64 (r1 eb90a5e8 was refuted; r2 fixes applied); probe r3 5e7af4ad PASS; check_round_mpmath_r3 f17927be ENCLOSURE PASS; awaiting the coordinator's design review | one replay ticket after the P1 proof | on | S + I; Runner's width-gate baseline must be re-pinned |

N9 file mismatch: Geometry's note names W, current_geometry_from_interval and M. The design names W, E and M. Pressure's DESIGN r2 is authoritative for WHAT is rounded; Geometry's note only for WHERE it is integrated. Neither is assumed until the two reconcile (section 4).

### Package (remake)
| # | Item | Files | Proof | Ticket | On | Effect |
|---|---|---|---|---|---|---|
| PK1 | remake 836a815, "Bind reuse.py in the I02 restoration inventory" | tectonics/tools/check_i01_finite_admission.py adds src/atlas_tectonics/reuse.py to RESTORATION (now bound and import-checked); remake's reuse.py at 836a815 is 3ff31f65 | committed; by design, check_current_evidence fails until the successor receipts are captured (commit message) | - | on | P |

Measured 17:30, with CR stripped. Remake's reuse.py 3ff31f65 is two hunks behind the runtime copy 96e2092c (the RC1 runtime-src and every endpoint candidate):
1. the canonical-bytes `{"bytes":..,"sha256":..}` record, written without the JSON encoder;
2. exact_arithmetic.runtime() versions and binaries in the runtime record.

composed-r2/src reuse.py 7dfdf209 is 96e2092c plus source_handles r2 (172 diff lines). Reconciliation chain:
3ff31f65 -> 96e2092c -> 7dfdf209 -> plus L4. Then one new restore-inventory digest is recorded under 836a815's binding, through its successor receipts.

## 2. Conflict matrix

| # | File | Candidates, in stacking order | Kind | Resolution |
|---|---|---|---|---|
| C1 | DG | G chain 1-5 -> I19 differential_geometry 436e170c (+ dual_geometry 520887ce) | stacked | confirm that I19 anchors on the f2 output (its base is **unknown**) |
| C2 | integration_parallel_results.py | G2 (-> f48cda05) -> I19 parallel_results 73091fd3 | stacked, anchored | fixed: I19 takes f48cda05 as input |
| C3 | integration_parallel_binding.py | I19 (-> 4eb627dc) -> P1 p1_binding (its docstring-line anchor pins both) -> 7300089c | stacked, anchored | fixed |
| C4 | MFM | G4 jets (-> c5f2a123) -> D2 _rotated() -> G-PY (pinned on c5f2a123) | stacked; the G-PY pin goes stale once D2 lands | Geometry composes G-PY after D2: G-PY's anchor moves to D2's output, then parity |
| C5 | MIM | D1 contains(); N9 relies on D._ray_box here | same call path | D1/D2 parity on one base before N9 |
| C6 | W | D5 (mpq fallback) + N9 (b-ray, `_pose_vector`) | same file, text-disjoint | either order; one parity |
| C7 | E or current_geometry_from_interval | N9 (b-quat) | single | confirm the file (see N9) |
| C8 | M | N9 (c) l.675/954 | single | - |
| C9 | integration_parallel_selection.py | workers_six -> endpoint_clamp -> S4 s4sel (base 7d4d4037) | stacked | confirm s4sel's base is the workers_six + clamp output; otherwise rebase |
| C10 | rolling module | workers6rolling c3fb0b5f + S4 s4roll (6daa2d3a -> c6c8a702) | same file? (rolling's file is **unknown**) | Geometry to confirm |
| C11 | integration_component_volume_auto.py | WP18 r2 -> S4 s4auto (`_open` only) | stacked | s4auto after WP18 (agreed) |
| C12 | reuse.py | source_handles r2 (in composed-r2) -> L4 -> package (C12b) | stacked, identity | one reuse.py revision, one cache generation |
| C12b | remake reuse.py + check_i01_finite_admission.py | PK1 + the two RC1 hunks + C12 | package | reconcile once, after acceptance; then successor receipts |
| C13 | cert_kernel | H2 -> H3 | stacked, anchored | fixed |
| C14 | certification_resources | H2 (-> 8b451aa8), then both L1 (-> fadac10d, line 26 repin) and H3 (-> 1c557e98; its transform pins 8b451aa8) | **CONFLICT**: H3's transform refuses lf3's resources | Order H2 -> L1 -> H3, with H3's resources pin moved to fadac10d (one line); the new output is **unknown**. Heat and Kernels choose; one generation either way. |
| C15 | heat pin cascade | H1a/H1c + H2 + L1 + H3 + H5a (+ N6) | emitted helpers | one generation note; Runner folds it once (layout lh); EXPECTED_HEAT/COLD re-derived |
| C16 | exact_growth | H1a -> H1c | stacked | fixed |
| C17 | composition.json pins | S3 (spatial_validation_patch), S9 (private_heat_indexed_runtime) | helpers | independent; no stage digests |
| C18 | R/run_fresh_interval.py | item 7 (**unknown**) and S1 (8e825d29 -> 066a7079) | **same file** | Runner lands item 7 first. S1's build refuses moved seams, so re-run it on item 7's output. |
| C19 | R/prepared_interval_driver.py | item 21 (live 6fb4ab6d) -> S2 line; item 7 "driver" and item 10 phase 2 are **unknown** | stacked | S2's line already sits on 6fb4ab6d; re-check if item 7 or item 10 moves it |
| C20 | R/fresh_interval_driver.py | item 11 (live f328f314) -> S2 line (228ddffb); item 7 driver **unknown** | stacked | as C19 |
| C21 | CG storage | B17 (segment_store, codec patch) + I14 (record_views) | disjoint files | q04 jointly |
| C22 | root copies | RC7 | override | N12 lists each as "emitted wins", or Heat removes it |

### Notes and bundles
- X1: bundle the identity changes so caches regenerate once. Carry H3, G-PY, N9 and L4 in one identity generation if their timing allows. Otherwise L4 rides the first of H3/G-PY to land, as approved.
- X2: N9 turns the WP18 and P1 bookings into over-bookings. Re-measure them; do not keep them. Runner's width-gate baseline is re-pinned.
- X3: The q tickets HELD for timing are not run in this window: q15, q20, q10a, q06, q11, q18, q21, q08 and r4c.

## 3. Proposed composition order (inside step 1 of the freeze list's section D)

1. Runner/Small helpers (H): item 7 -> S1 (rebased if its seams moved) -> S2 r7 (CRP, ledger and the two driver lines) -> item 10 phase 2. Then S3 and S9 (composition.json pins).
2. Storage (H): B17 rev4 + I14, after q04.
3. Geometry stages (S), with one d3 dry run at the end:
   - G1-G4 (f2; G3/G4 after jets-r2), then D1/D2;
   - G-PY, rebased on D2;
   - workers_six, clamp and rolling (q21), then WP18 r2 (q18);
   - S4: s4roll and s4sel, then s4auto after WP18;
   - I19 (q19), then P1 (q02 proof), then P2/P3 if their refuters clear;
   - D5, then N9 (replay ticket after the P1 proof; Runner width-gate re-pin);
   - then d3 with geometry parity.
4. Heat layout (L):
   - H1a -> H1c (q10a) -> H2 -> L1 -> H3 (C14 repin; q06) -> H5a (W4 D-b owed) -> N6;
   - one generation (lh), with Runner folding the cascade once;
   - EXPECTED_HEAT/COLD from the reviewed layout;
   - the RC7 decisions.
5. Identity (I): one reuse.py revision (source_handles r2 + L4), landing in the same generation as H3/G-PY (X1).
6. Then the freeze list's section D, steps 2-6: freeze N12 and publish its sha; assemble_r3 --pin; d3; compose R/composed-f1 frozen; ACCEPTANCE.json.
7. Package (P), after acceptance: the remake reuse.py reconciliation (C12b) and 836a815's successor receipts. Not before the fresh runs.

## 4. Unknowns (owners to fill in)
- Item 7 candidate SHAs, and whether 97137ce5/820ebc0e/55265495/7dd02819 are code or tests.
- Item 10 phase 2 files.
- Which items moved launch_fresh_interval and run_fresh_interval (R3).
- DG, q2_directed and parallel_selection outputs after the G chain.
- WP18 r2 output.
- D1/D2 outputs; D3/D4 files.
- The workers6rolling file, and the s4roll/s4sel bases (C9, C10).
- N6 files.
- P4.
- I19's integrator and the status of q19.
- L4 SHAs (owner: Kernels).
- The N9 outputs; Pressure and Geometry to reconcile E vs current_geometry_from_interval.
- The H5a refuter record (Heat): OWED until shown.
- The new certification_resources SHA after C14.

## 5. Switched-off items to re-test at the final reprofile (19r)

| Item | Why it was switched off (measured) | What could change that after integration | Existing A/B harness | Off switch |
|---|---|---|---|---|
| WP17 query store | Reopen 0.67 -> 0.004 s, but writes 2.77 -> 6.28 s and hits 2.0 -> 4.3 ms. Durability PASS (12 kills). | S1's per-stage counts on the fresh runs show few writes/hits and many reopens. | R/endpoint-checkpoints/measure_compact_query_store.py + wp17_crash_durability.py; REVIEW/fixes/backlog/wp17 | completed_query_store = 'files'; WP17 enabled flag off |
| WP12 mapped reads | Gate: at least 5 % of read time. Latest smoke q04smoke3 (B17 rev4 profile, 48.05 s own; untimed small lane, not timing evidence): 14.81 % before, 9.31 % after the item 14 page fix, so item14_compare says BOTH (page fix first) (item14-pagefix/compare-smoke3.json, wp12-smoke3.json). The older 5.64/4.37 % came from pre-B17 smokes c14b/q64c. Run paths read 0 chunks (caveat stands). | q04 decides: a profile where chunk reads reach the gate on run paths. | REVIEW/fixes/backlog/scripts/wp12_gate.py + item14_compare.py on q04 pstats | unknown (owner) |
| 13A decoded-support LRU | At most 0.15 % of any stage (pressure admission: 2,061 issues, 0.17 s). Below the WP11 rule (hit rate > 50 % or at least 5 %, against a 128 MiB cache). | A fresh profile shows support issue above about 2 %. | scripts/item13_profile_scan.py (item13-design.md section A) | not built |
| WP15 compact worker payloads | Exact, but slower: geometry +44.85 %, endpoint +57.52 %, heat +5.64 %. RAM only -1.2 to -8.3 %. Prep 0.35 -> 1.16 s (fsync + auth). | A combined workload where payload handoff dominates (heat prep/handoff 1.821 -> 0.152 s). | R/worker-payloads/measure_payloads.py (wp15-result.json, wp15-disposition-20261016.json) | unknown (owner) |
| WP25 heat warm start | Cannot keep the certified records identical. Room measured: LOW, 1 correction, 0.011 s; HIGH, 0 corrections, 0.96 s (factor 0.71 s). | HIGH needs corrections at IV2/IV3 (cells about 16x by IV3) AND an identity-preserving variant exists (Michael's call). | wp25_iteration_counts.py (wp25-disposition-20261016.md); IV2 needs persisted diagnostics | not adopted |
| WP10 compression | int.bytes is 99 % incompressible (ratio 1.000). No class reaches the 42,949,673 B gate; the best per-class saving is 32,919 B (0.02 %). Composing with no rules cost +0.36 % (fixed in follow-up b). | Final stores have a different byte mix (re-run the codec table on them). | REVIEW/fixes/wp0c/scripts (wp0c_codecs, decide, table, run.sh) | codec_policy = null |
| delta+zstd | Michael's exception needs at least 20 % less than zstd byte/1. It saves 0 % on int.bytes and enables nothing; time not measured. | As WP10, on the final stores. | the same wp0c scripts + codec_tradeoff.py | codec_policy = null |
| shared-denominator | 1 of 8,730 rationals is dyadic; the 7,790 denominators are almost all distinct. Best case is under about 1 MB (0.6 %) against 42.9 MB. | Final stores show many repeated denominators. | wp10-followups scripts/wp10f_rational_study.py + wp10f_rational_factors.py | not built |
| 1c batched measurement-store writes | ArrayStore.put store work is about 4.1 s, 0.4 % of 1,053 s (sqlite 1.75 s, flush 0.67 s), so it saves 1-2 s at most. It needs a storage.py commit-timing change. D-i: "tested by profile, not built". | Fresh-run put time grows well beyond 0.4 % (store growth about 4x per interval). | G/evidence/admission-profile-r1 profile | not built |

Not re-tested, by design:
- Item 6 / WP11: structural zero (0.0 s).
- 019 BVH: structural (no pair enumeration; the endpoint/wall confirmation is still pending with Geometry).
- 017 packed keys: excluded for safety (about 0.3 % of geometry; risks the D-l cell order).
- H5b: excluded for safety (2.5-8 GB at IV1 breaks the 12 GiB guard).
- S10: excluded for safety (withdrawn by Michael: verify every call).

## 6. Coordinator decisions (16 Oct, 17:3x)
- C14 approved: H2 -> L1 -> H3, with H3's one-line repin 8b451aa8 -> fadac10d, all in one heat generation.
- Stacked pins approved: G-PY rebases onto D2's output. Item 7 lands before S1, and S1's build must refuse unless its
  seams re-apply cleanly. No hand-merge.
- Package chain approved as the order: 3ff31f65 -> 96e2092c -> 7dfdf209 -> L4, then 836a815's successor receipts.
- X1: one identity generation for H3 + G-PY + N9 + L4 if timing allows; otherwise L4 rides the first of H3/G-PY.
  **L4 owner: Kernels**, which builds the next identity generation anyway.
- Discrepancies stay fail-closed until resolved:
  - H5a refuter: OWED until Heat shows the record.
  - N9: DESIGN r2 says what is rounded; Geometry's note says where it is integrated; reconcile (section 4).
  - S3: the code wins, so it is helper-only, and the freeze-list row is for Storage to correct.
- Section 4 unknowns go to their owners in a batch at RESUME; nobody chases them now.
