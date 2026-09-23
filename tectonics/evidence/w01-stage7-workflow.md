# W01 Stage 7: local implementation evidence

22 September 2026. WORKING NON-CANON. Local working-tree addition to commit
`c8b876c92b95ad8d4bc3d3fda8b8f94de6f1b84e`; not a release or scientific acceptance.
Existing W02/W03 local corrections were preserved. No commit/push, R4.4 campaign,
whole-world simulation, historical source repin or new physics was performed.

## Focused verification

Environment: Windows 11 10.0.26200; CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
Shapely 2.1.2, Numba 0.65.1. Numerical thread controls were all one
(`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMBA_NUM_THREADS`).
Use the compatible environment, with `tectonics/src` and `tectonics/tests` on
`PYTHONPATH`:

```text
python -B -m unittest test_w01_workflow -v
python -B -m unittest test_w01_workflow_geometry test_execution_reuse.IdentityTests -v
```

- Workflow: **22 passed, 44.798 s**, no skips.
- Geometry and affected shared execution identity: **16 passed, 5.086 s**, no skips.
- Total final focused coverage: **38 passed**. No unrelated full suite repeated.
- `git diff --check` passed. Git warned only about its configured LF-to-CRLF conversion.

Independent checks cover mixed material inventories, open-boundary cohort accounts,
refinement, spherical shell volumes in both hemispheres, complete-cell ownership,
hidden-interface refusals, exact interval composition, cumulative step budgets,
thermal unknown/provenance semantics, explicit pore-fluid history, memory refusal,
cancellation, immutable outputs, reuse, source mutation, persistent-cache parity,
and fresh-interpreter restore/continuation. The warm transport cache hit made zero
calls to the transport kernel; fields and identities matched direct calculation.
Restoration did not call the S5 sampling kernel. Consistently rehashed snapshots
with changed support or a valid material step from different velocities refused.

Review found and fixed omitted live-code identity registration, incomplete restore
geometry/velocity/account binding, missing retained-description admission and
inventory-loop cancellation checks. The added live-code test initially failed,
then passed after the fix; this was not hidden as a passing first attempt.
The earlier 18-test pass was pre-correction and is not added to the final count.

## Measured preparation reuse

Command (with numerical thread controls above):

```text
python -I -B tectonics/tools/run_w01_workflow.py --benchmark --output s7-timing.json
```

Three alternating matched pairs, each completing **four independent branches**
of the same 32-cell, two-cohort, 0.025-second authored workflow. Baseline prepares
the same implementation afresh for each branch. Candidate prepares once, then
initialises/evolves four times. **Candidate setup is included.** No persistent
result-cache hits, changed accuracy, omitted provenance, altered forcing or lower
precision. Every final workflow identity matched, including parent and receipts.
There was no previous S7 implementation to compare against; these are measured
reuse savings, not a historic release or whole-generator speedup.

| Pair | Fresh preparations + four advances (s) | One preparation + four advances (s) | Candidate setup (s) | Saved (s) | Less time |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.544315600 | 1.194844900 | 0.660447900 | 2.349470700 | 66.2884% |
| 2 | 3.292547400 | 1.195852300 | 0.673458600 | 2.096695100 | 63.6800% |
| 3 | 3.346319300 | 1.192093000 | 0.658110200 | 2.154226300 | 64.3760% |

Difference of medians: **3.346319300 → 1.194844900 s**, saving
**2.151474400 s / 64.293757%**. Three pairs are a bounded observation, not a
statistical capacity guarantee. Timings do not predict long-run tectonic cost.

Excluded equally from paired measurements, and recorded separately: authored
description setup **0.003828600 s**, first plan **0.671959300 s**, first advance
including first-process native initialisation **3.885875400 s**. Therefore the
64.29% figure must not be quoted as cold-start one-off savings. Candidate warm
four-advance totals excluding setup: **0.534397000, 0.522393700, 0.533982800 s**.
Peak admitted allocation estimate **6,041,795 bytes** within a 128 MiB budget;
all reservations returned to zero. This is not measured peak RSS.

Measured execution identity:
`db1ed18191acdd25be0a6b0383af63ba5ae72ed85c83b8dd80e613f65460ca19`.
Final material identity:
`95d8e74cf17d0036308f62d9b2b78161df4621d370137bab9729dfdf903e2418`.
Final workflow identity:
`1231b34b8d1ac263aaa7f52e2535088ab77dbef77f69f2cfdd71d50ba7d81547`.

The first development measurement overlapped verification and is not the timing
claim above. An attempted subsequent evidence-file write was denied by the local
filesystem sandbox after computation; no file was created and its unavailable
timings are not reported. The driver now prints completed evidence before optional
file publication. The retained final comparison ran without concurrent agent
tests and saved successfully in the authorised engineering workspace.

## Completion boundary

Implemented and locally verified for the explicit supported reductions in
[W01_REGIONAL_WORKFLOW.md](../docs/W01_REGIONAL_WORKFLOW.md). Initial temperature
is retained, not evolved. Arbitrary spherical dynamics, unsupported plate
interfaces/events, relative pore flow and W03 thermal/compaction physics are not
silently supplied. Stage 8 combined acceptance and reopened S3C realism remain.
The consumer settings and held R4.4 scientific questions are unchanged.
