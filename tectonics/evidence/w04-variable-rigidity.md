# W04 step 4 — variable rigidity: implementation and bounded evidence

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.
No commit/push, installation, checkpoint repin, full terrain or R4.4 run.

## Delivered scope

`variable_flexure.py` implements fixed, source-linked E/Te/nu profiles and the
conservative `(D w'')''+K w=q` operator using source-aligned C1 Hermite elements.
Sharp rigidity interfaces, periodic seams, free/clamped physical ends and exact
constant-material exterior half-lines are supported. Consistent element/foundation
integration, scaled banded Cholesky, polynomial extrema, one-sided interface
strain and explicit mesh-change gates are included. No smoothed-D uniform stencil.

`PreparedW04Support` and its one-shot helper connect the route to actual stationary
W01-W03 sources, preserving physical inventory loads, exclusive thermal ownership,
total-reference outputs, compatible frame/datum/epoch and exact source/cache IDs.
Existing uniform periodic/finite algorithms remain unchanged. Verified persistent
reuse is through the existing store; reusable factors have bounded request-owned
lifetimes. This adds no duplicate cache/history infrastructure.

Limits: fixed-in-time D, positive constant K, small-deflection planar 1D support,
transversely invariant loading. Continuing variable-D support requires exactly
declared exterior loads; nonzero omitted-pressure uncertainty refuses rather than
misusing the uniform tail bound. Mesh changes are estimates, not rigorous error
certificates. Third derivatives are diagnostic only. No 2D/planetary treatment,
evolving rigidity, material/thermal/water feedback or field calibration is claimed.
General assembled W04 acceptance remains the next separately scoped step.
See the [contract and reviewed sources](../docs/W04_VARIABLE_RIGIDITY.md).

## Focused verification actually run

Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, existing environment.
Single BLAS/OMP/Numba threads; `PYTHONPATH=tectonics/src;tectonics/tests`, Python `-B`.

Final **41 distinct focused tests passed**:

- `python -B -m unittest test_w04_variable_flexure -q`: 8 PASS, **0.033 s**.
  Independent arbitrary-D uniform equilibrium; two-material eight-coefficient
  continuum oracle and curvature jump; tighter convergence against analytical
  uniform Green response; periodic translation/nonzero mean; reflection and
  explicit exterior extension; same-D/different-Te strain; invalid material/load,
  numerical range and unresolved-mesh refusals; immutability, factor reuse,
  close, composed budget and cancellation controls.
- `python -B -m unittest test_w04_variable_workflow test_w04_regional_workflow
  test_w04_workflow test_execution_reuse.IdentityTests -q`: 33 PASS, **39.012 s**.
  Five new actual-source integration tests include all boundary modes, halos,
  source/frame/grid refusal, unchanged total-reference response, exact cache hits,
  W03 restore, one-shot equivalence and lifetime cleanup. Six retained finite,
  thirteen retained periodic and nine execution/source-identity controls passed.

Review corrections were made before final measurement:

1. Curvature converged more slowly than displacement. Per-level diagnostics showed
   the expected approximately fourfold error reduction per mesh doubling. The
   initial four-refinement default was insufficient for selected controls; the
   default allows six, still within the declared element/resource ceiling. A
   tight 1e-4 oracle policy explicitly allowed seven. Acceptance tolerances were
   not relaxed; unresolved cases still refuse. The separate third-derivative
   oracle used a stronger first-three-field gate, not a looser comparison.
2. An even-subdivision centre originally selected only the right internal FE
   trace, breaking reflection of derivatives. Centre traces are now averaged;
   true source/material interfaces remain one-sided.
3. Far pressures now receive the same nonzero-underflow checks as interior loads.
4. Construction and retained-factor admission overlap correctly; owner/per-call
   budgets compose. Cancellation is forwarded through fresh/cache compute paths
   and checked between meshes, with cleanup tested.

`python -B tools/check_coding_safety.py`: PASS, 13 maps/41 paths, static only.
`python -B -m unittest discover -s tests -p test_coding_safety.py -q`:
30 PASS, one Windows symlink skip, **0.106 s**. `git diff --check`: PASS apart from
the existing informational LF/CRLF warning. No unrelated full suite or Linux
execution was performed. The unchanged uniform finite kernel hash is recorded
below; its earlier independent quadrature tests were not needlessly repeated.

## Matched time savings

Reproduce: `python -B tectonics/tools/benchmark_w04_variable_rigidity.py --output
tectonics/evidence/w04-variable-timing.json` from the repository root.

Synthetic 512-cell, 400-km transect; three thickness regions (1, 2, 4 km), twelve
different pressure fields, three alternating repetitions. These are timing
inputs, not geological calibration. Both routes include cold preparation, all
refinement solves, validation, diagnostics, byte admission, immutable output and
close. A pre-run native-library warm-up is shared; neither receives prebuilt
factors. The optimised batch keeps one prepared profile across changing loads.

| Metric | Rebuild each load | Reuse profile factors |
| --- | ---: | ---: |
| Median, 12 loads | 0.039662400028 s | 0.020635399967 s |
| Per load, batch average | 0.003305200002 s | 0.001719616664 s |

Saved **0.019027000060 s per twelve loads**, **47.97238706%**, **1.92205628x**.
Per-load saving: **0.001585583338 s**. All responses and mesh-gate metadata were
**bitwise identical** across both algorithms and all repetitions. Accepted meshes
used 2-8 subcells per source cell, with no accuracy reduction. Maximum retained
factor capacity was 1,352,512 bytes; maximum accounted peak was 18,465,600 bytes
(not measured RSS). All lifetime reservations returned to zero.

Raw timings and source hashes: [w04-variable-timing.json](w04-variable-timing.json).
These short timings describe this new kernel's setup reuse, not an old-release,
whole-generator or full-terrain gain. There are no result-cache hits, worker
processes or W03 evolution/source-context costs in the timed comparison. The
existing uniform FFT remains appropriate for its different, uniform-D problem.

## Sources reviewed before method selection

- [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/): full-text
  variable-rigidity equation and boundary meanings.
- [TU Delft Euler-Bernoulli chapter](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html):
  weak form and C1 Hermite element derivation.
- [Wieckowski and Swiatkiewicz (2021)](https://mdpi-res.com/d_attachment/materials/materials-14-00460/article_deploy/materials-14-00460.pdf):
  independent full-section check of Winkler support and Hermite formulation.
- SciPy [cholesky_banded](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cholesky_banded.html)
  and [cho_solve_banded](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cho_solve_banded.html)
  documentation: compact factorisation/repeated solves.

Paper/docs review, not external gFlex execution/source audit or empirical terrain
validation. The detailed physical/numerical rationale is in the linked contract.

## Final source identities

- `src/atlas_tectonics/variable_flexure.py`:
  `174baa0a339d5c472fb1b6d3174c6be246eaa4034cf24e4b9743d4704e9eb634`
- `src/atlas_tectonics/w04_workflow.py`:
  `5a4ae192b9a0796a136195561ab125625b8ad060bbc28e0f5e6e8af350dc2606`
- `src/atlas_tectonics/reuse.py`:
  `4d49fa9701e43f7b401502539ab6d6bc4b4db7ed4bc958ae05c8a812bd0dbb5d`
- Unchanged `src/atlas_tectonics/finite_flexure.py`:
  `b29bae72b5e587c846a5735e100fd2a5d5ada07e38cffcd3cc7005c6cacaba66`
- `tests/test_w04_variable_flexure.py`:
  `6c8da85bc8933b24e785635b4671b19326f0a4be0af69f1e9eb3fd6ea9ca257e`
- `tests/test_w04_variable_workflow.py`:
  `b5e67e48d1cb35f4d5b699ae499cdddaa36cacc9c5ed4b51cf49ad61a51c5caf`
- `evidence/w04-variable-timing.json`:
  `4c25d1e89bb36e61e5a7d71bf89cb9c1bab424e79f20df5e1b95f23ea1876ee3`

The new module participates in execution/source identity; old bindings are not
silently repinned. Passing these controls establishes this bounded implementation,
not publication, canon adoption or general W04/terrain acceptance.
