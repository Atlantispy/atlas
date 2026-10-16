# inv-A: class-A scientific runtime checks (composed-r2)

Read-only grep/sed inventory. Root `.../resumability-r1/composed-r2`; all paths below are relative to it.
Scope: `src/atlas_tectonics/*.py` (236 files) + `helpers/*.py` (214 files), `test_*.py` excluded (155, all in helpers).
Total 450 files, 216,934 lines. Counts are grep LINE counts over those 450 files unless stated.
"raise lines" = `\braise\s+[A-Za-z_]` on non-comment lines, so inline `if x:raise Err(..)` is included (src 8,109; helpers 2,846; total 10,955).

Caveat on helpers: 94 files are `private_heat_*_rN.py` (66 distinct names, several revisions kept side by side) and 16 are `w1ref_/w2ref_/w3ref_/xmref_/a2ref_/a3ref_/r1aref_` reference copies. Counts in helpers therefore repeat the same check 2-5 times.

## Headline

- No scientific check in these files is gated by debug, `__debug__`, `assert`-stripping, an env flag or the strict/release switch. `__debug__`: 0 uses. `assert` in src: 0 (57 in helpers, almost all accounting/test-style; one scientific pair noted in section 6).
- The only strict/release switch in the composition is `ExecutionContext.verify` (`src/atlas_tectonics/reuse.py:882-886`, no-op in release) plus `release_boundary` callers in `storage.py` (278, 470, 802, 1047). Those are identity/source checks (class B), not scientific. No scientific module under `src/atlas_tectonics` references `execution_mode`/`release_boundary`, except `integration_parallel_selection.py:576-578` (strict-only workers = a speed gate, no check dropped) and `integration_parallel_dispatch.py:182` (`require_strict_execution`, refuses release outright).
- Things that look optional are all *performance routes or caches whose declined case stays exact* (section 6).

## 1. Exact geometry predicates and exact arithmetic

Sites (patterns): `\bFraction\b` 873 lines/164 files; `gmpy2|mpz|mpq` 413/55; `orient` 205/54; `predicate` 243/58; `filtered` 47/3; `rational` 789/142. Raise lines mentioning exact/predicate/orient/rational/Fraction: 653. Raise lines in the core files: `integration_exact_gmp.py` 16, `exact_arithmetic.py` 8, `integration_filtered_predicates.py` 6, `integration_volume.py` 29, `integration_volume_bounds.py` 8, `integration_volume_overlap.py` 13, `integration_cone_zero.py` 6, `integration_moving_face_moments.py` 12, `integration_moving_interface_moments.py` 13, `integration_differential_geometry.py` 197, `integration_exterior_mesh.py` 47, `integration_dual_geometry.py` 61.
Heaviest `Fraction` files: integration_material 67, integration_thermal 51, integration_support 48, integration_regional_evolution 38, integration_transfer 37. Heaviest gmp files in helpers: private_heat_certification_kernel_r1 (49), private_heat_rank_resources_r1 (25).
No incircle/Shewchuk expansion code exists; predicates are exact rational/GMP signs or outward-rounded interval signs with exact fallback.

| File:line | What it protects |
|---|---|
| src/atlas_tectonics/integration_filtered_predicates.py:30 | refuses float filter unless IEEE binary64, gradual underflow, no FTZ/DAZ |
| src/atlas_tectonics/integration_filtered_predicates.py:52,144,167 | outward-padded ratio bounds; plane side and 2-D orientation, None means go exact |
| src/atlas_tectonics/exact_arithmetic.py:66 | gmpy2 canary: 11 exactness checks plus zero-denominator, else backend refused |
| src/atlas_tectonics/exact_arithmetic.py:180 | tested gmpy2/GMP version pair and sealed native files required, else not used |
| src/atlas_tectonics/integration_exact_gmp.py:625,638,459 | exact halfspace beyond/within and non-collinearity via integer numerators |
| src/atlas_tectonics/integration_exact_gmp.py:475 and integration_volume_bounds.py:131 | exact convex clipping; only exactly zero-volume faces vanish |
| src/atlas_tectonics/integration_differential_geometry.py:524 | certified-box determinant>0 and hemisphere>0 orientation of ray triangle |
| src/atlas_tectonics/integration_moving_face_moments.py:423,1020 | strict interior sign from monotone bound; exact start predicates, no sampled zeros |
| src/atlas_tectonics/integration_cone_zero.py:94,154 | zero-volume cone/voxel proofs from outward projections |
| src/atlas_tectonics/integration_exterior_mesh.py:164 | subtraction skipped only after group disjointness proof |
| src/atlas_tectonics/geometry.py:3,204,240 | planar features use GEOS robust float predicates, explicitly not exact |

In-code statements: integration_cone_zero.py:101 "small or unresolved values never fire." integration_exact_gmp.py:109 "Performance routing only: every declined/unsupported case stays exact." exact_arithmetic.py header: "no tolerance exists". geometry.py:204/241: GEOS predicate "is not exact arithmetic" (the only float-predicate site; 51 raise lines, not an exact check).

## 2. Certificates and error/volume bounds

Sites: `certif` 1,077 lines/145 files; `certificate` 405/66; `enclos` 388/83; `error_bound|error bound` 55/22; `outward|nextafter|ulp|round up/down` 435/107; `rigorous|conservative` 227/131; raise lines with certif/enclos/unresolved/uncertain: 274; 31 `def *certif*`; classes `VolumeEnclosure`, `CertifiedGammaRow`, `CertifiedFace`, `CertifiedAssembly`, `CertifiedFact`. Heaviest: integration_differential_geometry 117, integration_regional_workflow 78, integration_thermal 42.

| File:line | What it protects |
|---|---|
| src/atlas_tectonics/integration_volume_bounds.py:441,498 | VolumeEnclosure: inner/outer rational shell-volume bounds, unresolved stays explicit |
| src/atlas_tectonics/integration_dual_geometry.py:741-754 | cached volume measurement: width, relative error <= request, bounds re-derived |
| src/atlas_tectonics/integration_differential_geometry.py:4965 | component volume certificate for moving interfaces |
| src/atlas_tectonics/integration_extremum_heat.py:130 | positive Decimal weights reproduce target within defect; stored as the certificate |
| src/atlas_tectonics/_integration_weakening.py:76 | refuses weakening law that can raise near-surface yield |
| src/atlas_tectonics/integration_differential_coupling.py:377 | certify: L2 and work error bounds, no automatic bound change |
| src/atlas_tectonics/variable_stokes_execution.py:522,535 | adaptive publication must meet the true linear residual target |
| src/atlas_tectonics/integration_regional_workflow.py:475 | saved certification records re-checked against graph/interval on restore |
| src/atlas_tectonics/integration_parallel_results.py:423 | wall-zero certificate shape check on worker results |
| helpers/private_heat_certification_kernel_r1.py:726,803,814 | inverse defect norm < 1; singleton vs enclosure; precisions exhausted refuses |
| helpers/private_heat_closed_owned_r4.py:111,207 | quadratic endpoint certificate; closed guard keeps exact low ledger |
| helpers/private_heat_finish_arithmetic_r1.py:55-60,210 | low endpoint must certify; zero-straddling sign refuses when exact fallback off |

In-code statements: integration_extremum_heat.py:135 "A float selection is never trusted for a sign." integration_differential_geometry.py:894 "the issued-object and shared-budget checks above are never bypassed." integration_parallel_results.py:424-426 (comment): worker proofs are "not by an independently restored certificate"; "full worker/source binding remains the authority".

## 3. Conservation / balance

Sites: `conserv` 258/136; `balance` 314/62; `GCL|geometric conservation` 34/16; `math.fsum` 491/86; `.closure(` 3 callers (defs integration_ledger.py:316, integration_material.py:616, integration_sphere.py:1388, integration_transfer.py:2339); raise lines on conservation/balance/mass/energy/closure/GCL/roundoff: 284 (`mass` 479 lines, `energy` 758, `ledger` 1,100 are mostly naming/identity text, not checks).

| File:line | What it protects |
|---|---|
| src/atlas_tectonics/integration_ledger.py:1639 | exchange accounts must close exactly or nothing is published |
| src/atlas_tectonics/integration_ledger.py:511,557 | donor holds enough; stock rounding within exact allowance |
| src/atlas_tectonics/integration_feedback.py:579 | P7 booked energies equal belt column work within derived bound |
| src/atlas_tectonics/integration_dual_measures.py:168 | before = after + residual for material quadrature account |
| src/atlas_tectonics/integration_dual_geometry.py:271-279 | min-cost flow dual certificate, primal bounds, node balances all zero |
| src/atlas_tectonics/integration_spatial_ale.py:338 | exact GCL closure of the ALE transfer graph |
| src/atlas_tectonics/integration_spatial_transport.py:368 | space-time graph exact GCL; no renormalising |
| src/atlas_tectonics/integration_spatial_reservoir.py:359; integration_exterior_state.py:548 | finite-stock graph GCL; paired exterior volume vs GCL change |
| src/atlas_tectonics/free_surface.py:310 | mass, density and volume errors <= 1e-9 per corrector step |
| src/atlas_tectonics/regional.py:307; materials.py:359 | cohort inventory residual <= 128 eps scale (fsum-based) |
| src/atlas_tectonics/execution.py:667-670 | parent recomputes ALE account from worker result, mismatch refuses |
| src/atlas_tectonics/subduction.py:471 | thermal operator must preserve a constant temperature |

In-code statements: regional.py:304 "Refuse instead of adjusting the final cell to hide drift." integration_ledger.py:555 "a violation is an implementation fault, and nothing is published." integration_mimetic_heat.py:796 "never clipped". Cost note: execution.py:640-672 re-derives each worker's conservation account in the parent (parallel batches only).

## 4. Convergence / iteration limits / step ceiling

Sites: `converge` 125/40; `max_iter|maxiter|iteration limit` 48/21; `toler` 358/122; `rtol|atol` 100/31; `not converged|did not converge|nonconverg` 50/23; raise lines on convergence/iteration/residual/halving: 213.

| File:line | What it protects |
|---|---|
| src/atlas_tectonics/integration_state.py:55 | MAX_STEPS = 256 accepted-step ceiling; 17 use sites (e.g. integration_ledger.py:74,226; integration_driving.py:764,777; integration_sphere.py:1010) |
| src/atlas_tectonics/regional_workflow.py:35,209 | _MAX_STEPS = 256, max_steps in 1..256 |
| src/atlas_tectonics/_integration_motion.py:20,90,113 | MAX_ITERATIONS 96; brentq maxiter; force balance must converge |
| src/atlas_tectonics/integration_driving.py:80-81,1270-1283 | Newton 96 iterations, 64 halvings, residual must be met |
| src/atlas_tectonics/integration_feedback.py:52,496-500 | OUTER_ITERATIONS 40; non-contracting coupling refuses |
| src/atlas_tectonics/integration_mimetic_precision.py:29,606-643,715 | _GATE 1e-11; PCG re-checks true residual before accepting convergence |
| src/atlas_tectonics/integration_extremum_heat.py:56,906,961 | 64 bounded steps; converged state must stay inside positive temperature bounds |
| src/atlas_tectonics/stokes_execution.py:157,430; stokes.py:115 | residual gate; MINRES must converge in <=128 iterations |
| src/atlas_tectonics/regional_stokes.py:117,476,504 | linear_rtol <= 1e-12; GMRES no direct fallback; algebraic residual |
| src/atlas_tectonics/variable_stokes_execution.py:171,751,816 | nonlinear record converged; Picard and Anderson envelopes fixed |
| src/atlas_tectonics/integration_strength.py:519,552,612,963 | belt bracket, rate, history residual/positivity must converge |
| src/atlas_tectonics/regional_rheology.py:176; regional_strength.py:172 | max_iterations hard cap 40 |
| src/atlas_tectonics/integration_radial_strength.py:31,413; subduction.py:37 | cap 32 and 200; non-convergence books no history or heat |

In-code statements: integration_mimetic_heat.py:796 "an unconverged or out-of-range state is refused, never clipped". integration_mimetic_precision.py:617-620: a solve that converges on its last permitted iteration is still accepted. w03_workflow.py:458: intermediate loads "cannot be skipped without losing hysteresis" (every step is evaluated). The 256 ceiling carries the comment "_integration_heat.policy_limits's literal ceiling" (integration_state.py:55).

## 5. Physical-validity refusals

raise lines: 10,955 (src 8,109; helpers 2,846). Statement-start by class: TectonicsError 3,153; ValueError 1,628; V.VolumeError 558; ContractError 447; GeometryError 310; TypeError 297; RegionalOwnerRefused 284; GeologyError 280; RuntimeError 167; TransferRefused 152; SphereError 150; LedgerError 149; ReferenceDataError 124; TransportRefused 123; StoreError 99.
Validity-keyword raises (finite/positive/negative/nonnegative/monotone/admissib/range/NaN/singular/out of): 1,318 (src 1,087; helpers 231). Finite 685, positive/negative 594, monotone/ordered 63, range/bounds/exceed/outside 1,041. `isfinite|isnan|isinf` 668 lines/214 files; `np.errstate(...raise...)` 55 lines/34 files; `_validation.py` (scalar/array/text/snapshot) is imported by 188 files with ~637 `scalar(` and ~1,053 array-type calls (`src/atlas_tectonics/_validation.py:19-148`).
Contrast, identity/budget/schema/owner raises (class B-like): about 1,668 raise lines; so only roughly 12 percent of raises are validity-keyword.

Top 25 files by raise lines (total / validity-keyword subset / identity-keyword subset; keyword subsets overlap, rough):

| Raises | Valid. | Ident. | File | Nature |
|---|---|---|---|---|
| 197 | 52 | 84 | src/atlas_tectonics/integration_differential_geometry.py | mixed geometry + issued-object |
| 172 | 28 | 44 | src/atlas_tectonics/integration_transfer.py | transfer admissibility |
| 170 | 14 | 87 | src/atlas_tectonics/integration_regional_workflow.py | mostly owner/identity |
| 154 | 32 | 60 | src/atlas_tectonics/integration_sphere.py | mixed |
| 144 | 19 | 31 | src/atlas_tectonics/integration_material.py | mixed |
| 134 | 29 | 48 | src/atlas_tectonics/integration_state.py | mixed |
| 133 | 25 | 30 | src/atlas_tectonics/integration_driving.py | mixed, Newton refusals |
| 119 | 8 | 33 | src/atlas_tectonics/thermochemical_execution.py | mixed |
| 119 | 20 | 23 | helpers/interval_store_set.py | store/contract (class B) |
| 116 | 13 | 54 | src/atlas_tectonics/integration_ledger.py | ledger closure + identity |
| 114 | 18 | 28 | src/atlas_tectonics/storage.py | store/identity (class B) |
| 113 | 20 | 16 | src/atlas_tectonics/variable_stokes_execution.py | solver residual gates |
| 113 | 23 | 52 | src/atlas_tectonics/integration_regional_evolution.py | mixed |
| 109 | 28 | 72 | src/atlas_tectonics/integration_spatial_owner.py | mostly identity |
| 104 | 32 | 35 | src/atlas_tectonics/material_library.py | reference data (103 MaterialLibraryError) |
| 99 | 10 | 25 | src/atlas_tectonics/reuse.py | execution identity (class B) |
| 99 | 3 | 35 | helpers/workflow_transfer.py | transfer wrapper (class B) |
| 98 | 21 | 35 | src/atlas_tectonics/spherical_atlas.py | geometry validity |
| 94 | 19 | 28 | src/atlas_tectonics/regional_collar3d.py | mixed |
| 92 | 47 | 35 | src/atlas_tectonics/integration_regional_inventory.py | inventory validity |
| 89 | 39 | 13 | src/atlas_tectonics/integration_thermal.py | thermal validity + certificates |
| 85 | 27 | 13 | src/atlas_tectonics/precursor_sampling.py | physical input validity |
| 80 | 15 | 43 | src/atlas_tectonics/w07_workflow.py | workflow |
| 78 | 16 | 33 | src/atlas_tectonics/geological_case.py | case admissibility |
| 75 | 37 | 33 | src/atlas_tectonics/boundaries.py | boundary-condition validity |

Reference-data refusals: ReferenceDataError in plate_reference_dataset.py 68, plate_reference_use.py 46, plate_reference_acceptance.py 21.

## 6. Anything optional, disable-able or debug-like (most important)

No check here says "debug only". The following are the ones a reader could mistake for optional; each keeps the exact/true answer when skipped or declined.

| File:line | Item | Status |
|---|---|---|
| src/atlas_tectonics/integration_exact_gmp.py:109-110,386-388 | binary64 sign filters (FILTER_PLANE_BITS=1024, FILTER_CAP_POINT_BITS=12288) | comment: performance routing only; removing costs time, not accuracy; declines fall to exact GMP |
| src/atlas_tectonics/integration_filtered_predicates.py:30-38 | filter unavailable on non-IEEE/FTZ hosts | silently uses exact GMP; accuracy-neutral |
| src/atlas_tectonics/exact_arithmetic.py:180-219 | `ATLAS_EXACT_ARITHMETIC=python` skips GMP and canary | env switch; both routes exact; `gmpy2` mode refuses on failure |
| helpers/private_heat_finish_arithmetic_r1.py:68-69 | bare `assert upper-lower == 2**-64` and `assert predicate(lower)` | the only scientific asserts; stripped by `python -O`; helpers/launch_monitored_interval.py:51 refuses PYTHONOPTIMIZE for monitored launches, nothing else does |
| helpers/private_heat_finish_arithmetic_r1.py:210 | `exact_fallback` flag | off means refuse (UnresolvedQuadraticSign), not skip |
| src/atlas_tectonics/integration_feedback.py:704-715 | `step(..., verified=token)` skips `verify_driving` replay | skip allowed only for the issued Verified token matching head key/text (provenance trust) |
| src/atlas_tectonics/extension_workflow.py:171-173 | cache hit accepted by cheap geometry/load contracts and bounds | comment: "never rerun either Green convolution to accept a hit"; checksum-authenticated, partial physical re-check by design |
| src/atlas_tectonics/integration_dual_geometry.py:741-745 | cached measurement validated by query/precision meaning, storage authenticates bytes | re-derives error, width, bounds on every hit |
| helpers/certified_fact_cache.py:1-5 | certified-fact cache, `enabled=` flag | docstring: opt-in, no runtime hook; only test_certified_fact_cache.py uses it, dormant |
| helpers/content_cache.py:662-678,752,770 | opt-in LRU with verifier on insert and hit | disabling it recomputes; verifier mandatory when enabled |
| src/atlas_tectonics/reuse.py:882-886 | `ExecutionContext.verify` no-op in release | identity check (class B); `verify_boundary` 888 stays full in both modes |
| src/atlas_tectonics/integration_exterior_mesh.py:164-170 | subtraction skipped for matched parts | only after disjointness proof; not a switch |
| src/atlas_tectonics/execution.py:640-672 | worker ALE result re-verified in parent | cost per parallel batch; correctness-bearing, no off switch |

Comments naming a cost or a must-not-skip: integration_differential_geometry.py:2131 "This cheap proof precedes polyhedral clipping" (order, not optional). helpers/private_heat_closed_owned_r4.py:40 "allowances MUST NOT be removed" (resource slots, class B). regional_forcing.py:584 message "cannot be skipped by face sampling".

## Method notes and limits

- Pure grep/sed/wc; nothing executed. Keyword subsets in section 5 are heuristic (message text), not semantic.
- `budget` (6,681 lines), `residual` (1,346) and `256` are too noisy to count as check sites; budget raises are resource checks (class B, covered by inv-CDE).
- Not looked at: inside `integration_differential_geometry.py` beyond the cited ranges (5,722 lines, 197 raises).
