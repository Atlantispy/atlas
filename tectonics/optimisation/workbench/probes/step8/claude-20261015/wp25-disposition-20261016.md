# WP25 (heat warm start, mixed-precision certified solves): evaluated, recommended DISABLED

16 Oct 2026, "Steps 8-9 runner and heat". Plan: COMPACT_EVERYWHERE_PLAN.md, "WP25: Heat warm start and
mixed-precision certified solves". The contract there is that certified results are unchanged and only
the work to reach them falls. The coordinator added: certified records identical, new helper files
only, first used from interval 2.

## What the heat route solves today (composed-r1 helpers, read only)

`private_heat_forward_kernel_r13` (the numerical kernel pinned by the r12/r13 issuers) runs these steps:
- `LOW.solve` (`private_heat_low_solver_kernel_r5`);
- the certified polygon reconstruction (`FUNCTIONS.reconstruct`) and its precision ladder;
- the HIGH solve (`SPARSE.solve_rounded`, `private_heat_decimal_sparse_core_r2`);
- `FINISH.finish(..., low.value, high.value, ...)`, so both solves feed the certified ledger.

The two sparse cores:
- **LOW, `private_heat_decimal_sparse_core_r1._solve`.** SuperLU (binary64) factor. The start is u0 = Decimal(LU\rhs). Up to eight corrections follow, each a residual in Decimal-80 HALF_EVEN, solved with the same binary64 factor. The first iterate whose largest residual is at most the target is accepted.
- **HIGH, `private_heat_decimal_sparse_core_r2._solve`.** The same system and acceptance rule, with a partial-pivot MPFR512 LU and exact rational-to-Decimal-80 conversion.

The LOW route is therefore already mixed-precision iterative refinement with a high-precision residual. The plan's second technique exists for LOW, and HIGH deliberately uses MPFR512.

## Why neither technique can keep the certified records identical

The accepted output is the first iterate that meets the residual target, not a unique canonical value. Many Decimal-80 vectors meet the target, and which one is accepted depends on the start and on the factor's rounding.
- **Warm start** (u0 = the previous interval's solution): a different start gives a different accepted iterate. Its temperatures, energies and face fluxes (Decimal strings) feed FINISH and hence the certified ledger, so the records change.
- **Lower-precision HIGH factor** (binary64 or lower-precision MPFR plus more corrections): u0 changes, so the accepted HIGH iterate and the certified records change.
- The diagnostic fields (refinements, residual_history) are not themselves certified. A scan of the real r9 IV1 heat record found none of them (`heat-width/scan_heat_refinements.py`, `heat-refinements-r9.json`), so the break is in the accepted values, not in a diagnostic.

An identity-preserving variant would have to reproduce the reference iterate exactly. That means a rigorous enclosure of the MPFR512 solve's rounding error, a proof that each Decimal-80 rounding is determined, and a fallback to the reference route otherwise. It is feasible in principle: the LOW/HIGH matrix C + dt·L should be an M-matrix, which gives a cheap bound on the inverse. But it is a new certified route with its own source identity and review, and its gain is bounded by the numbers below.

## Measured room for gain

Genuine W4 owner/transport/mesh call, 236 cells and 832 faces (`wp25_iteration_counts.py`). The same-call control was run on layout g13l0 under a read-only profile hook on the two `_solve` returns; it PASSES under the hook. Results: `wp25-iteration-counts-w4.json`, `wp25-control-w4.json`. Each packaging run solves once of each kind.

| solve | corrections after the start | solve time | factor | L+U nnz |
|---|---|---|---|---|
| LOW (binary64 LU + Decimal-80) | 1 | 0.011 s | (SuperLU, inside) | 11,368 |
| HIGH (MPFR512 LU) | 0 | 0.96 s | 0.71 s | 37,157 |

- A warm start can save at most LOW's one correction (milliseconds). HIGH already accepts its first solve, and its cost is the factorization, which a warm start does not touch.
- The matrix changes every interval (geometry and conductances), so no factor carries over between intervals.

IV1 split, from the r9 real run's phase start times (`heat-original-connected-20261013-r9.json`):
- heat as a whole: 2,357.8 s to 5,493.6 s, about 3,136 s;
- LOW-predictor phase: 133 s, about 4% (GEOMETRY.prepare plus LOW's exact E/C ledger plus the solve);
- certified polygon reconstruction: about 2,330 s, about 74%;
- conservative finish: 288 s;
- native projection: 279 s.

## Disposition and recommendation

- **WP25: evaluated, DISABLED.** Neither technique can reduce work while keeping the certified records identical: the warm start has essentially nothing to save, and the HIGH precision change alters the accepted iterate. No helper is built and nothing is wired into interval 2. This is an explicit disabled outcome under the plan's rule, with the measurements above.
- **Possible later option (identity-changing; Michael's decision, like the parked width options before IV4).** Redefine the certified LOW/HIGH output as the correctly rounded solution with a rigorous enclosure, after which faster factorizations become admissible. Worth revisiting only if HIGH's MPFR512 factor grows materially at IV2/IV3; its fill grows with the cell count.
- **The heat time is in the certified polygon reconstruction (74% at IV1).** That is outside WP25. Candidates for the coordinator to route:
  - cross-interval reuse of certified facts keyed by exact inputs (WP11's certified_fact_cache, if unchanged faces exist between intervals);
  - the WP24 compile gate for the reconstruction kernels.

Later-step impact: none on Step 10 (nothing composed). The disposition goes into the Step 8 close-out.
Interval 3: the LOW/HIGH factors grow with the cells (about 16x IV1 cells by IV3). Re-measure HIGH's factor share at IV2 from its diagnostics, which the run does not persist today. A run.json field for them would be a recording-only change.
