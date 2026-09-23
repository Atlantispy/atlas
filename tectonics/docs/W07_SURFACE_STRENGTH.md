# W07 Step 4 — material surface and dry strength

23 September 2026. WORKING NON-CANON. Implementation and focused acceptance
record; the frozen [Step 1 design](W07_REGIONAL_MECHANICS.md) and
[case register](../cases/w07_mechanics.json) are not edited or silently repinned.

## Implemented model

`DryStrengthProfile`, `evaluate_dry_strength` and `solve_regional_strength`
implement the dry, plane-strain C01 law

`tau_y = C cos(phi) + (P - P_pore) sin(phi)`;
`eta = min(eta_creep, tau_y/(2 eII))`, with `eII = sqrt(D:D/2)`.

Cohesion, friction, creep viscosity, viscosity validity, tensile strength and
zero pore pressure are explicit, source-labelled inputs. Exact zero rate uses
creep viscosity. There is no invented rate floor, viscosity clipping, damage,
softening or tensile repair. Negative effective pressure, excessive tensile
principal stress, unsupported dilation and invalid viscosity refuse. Physical
pressure, including its declared datum, drives strength; removing a numerical
gauge cannot change it. Full plane-strain principal stress includes the y axis.
The regional iteration checks the returned fields under the **current** law,
not just the prior linear operator. Stress-site tensor/pressure reconstruction
is explicit; averaging final viscosities is not substituted for this law.

`PreparedFreeSurface2D` supplies a source-bound homogeneous, incompressible,
isothermal material-surface evolution. The surface is real body-fitted Q2
geometry. The finite-element alternative assessed in Steps 1–2 is now adopted
for this deformed branch: Q2 velocity/geometry and discontinuous **physical** P1
pressure, mapped gradients, paired stress/divergence operators, and natural
traction using the actual surface normal. The existing flat MAC route is
unchanged. This is an Atlas implementation, not an installed pTatin framework.

The top obeys `h_t = w - u h_x` in a conservative continuous-Q2 weak projection.
The projection preserves integrated normal volume flux and reports its pointwise
representation error; it does not pretend pointwise equality. Harmonic vertical
mesh motion fixes the bottom and allows tangential vertical sliding on the
straight sides. Horizontal coordinates remain fixed. Physical flow and mesh
motion are distinct; homogeneous inventory moves using **physical minus mesh**
oriented face flux. Independent face integrals check geometric/material volume.
SSP-RK2 advances the surface and inventory together, without post-hoc volume
correction or artificial surface traction. The pressure reference is the
physical top traction, not an arbitrary zero-mean gauge.

Exact element Jacobian minima, linear/independent mechanical gates, cell fluxes,
volume and mass are checked under the existing tolerances. Finite-element
continuity is weak/element-integrated; pointwise divergence is separately
reported rather than relabelled as exact incompressibility. Public inputs,
source identity, cancellation, one native thread, 128 MiB shared accounted
admission and cumulative 256 accepted intervals remain bounded. The accounted
memory limit is not an operating-system RSS cap.

The supported graph has bottom z=0, no-slip bottom, free-slip sides and explicit
external top pressure. Moving heterogeneous phases/heat need their own compatible
deformed-mesh transfer; this interface does not accept stale rectangular fields.
Step 5 owns source-bound geological assembly and recovery. No physical shear-band
length or mesh-independent localisation is inferred from perfect yielding.

## Focused verification

**Step 4 complete.** [B09 evidence](../evidence/w07-surface.json) passes all
13 report checks. [Isolated timing](../evidence/w07-surface-timing.json) passes
its matched-output check. Both retain exact production/case/helper hashes.

C01: eight focused methods passed in 6.112 s, including zero/creep/yield branches,
full principal stress, dimensional extremes, tensile/validity/source refusals,
homogeneous 4/8 grids, gauge-invariant physical P=10, and response to physical
P=20. Maximum recorded regional momentum residual 2.388e-11, work residual
1.774e-13, current-law log-viscosity change 1.25e-11. Linear/zero cases took one
iteration and yielded cases two. Peak shared accounted memory 19,341,824 bytes.

The independent B09 reference solves the no-slip-bottom biharmonic boundary-value
problem and checks the closed finite-depth rate and thin/deep limits. For W=2,
H=1, eta=rho*g=1 and k=pi, decay rate is 0.14424591716886523. Surface amplitudes
1e-4 and 5e-5, observations at scaled times 0, 0.25, 0.5 and 1, and 16/32/64
accepted intervals retain the frozen case. The mesh sequence is 4x2, 8x4, 16x8
**Q2 elements**, not a claim that these equal MAC cell counts. Identical finest
trajectories are shared between the spatial/time comparisons, not rerun.

## Efficiency choices and measurements

The strength evaluator batches physical points, with a logarithmic yield test
that avoids intermediate trial-stress overflow. One bounded 1,024-point
comparison returned all ten fields exactly equal to scalar-per-point calls.
Three rotating samples (seconds):

| Path | Samples | Median |
| --- | --- | --- |
| Scalar calls | 0.080678600003, 0.079298199969, 0.077141600079 | 0.079298199969 |
| Batched call | 0.000225899974, 0.000196899986, 0.000150099979 | 0.000196899986 |

Saving: **0.079101299983 s / 99.7516968%** for this point-evaluation workload,
not a solver, evolving-world or whole-generator speedup.

The mapped solver reuses connectivity and one current metric set; new geometry
rebuilds its metrics/operator. Its block pressure-mass/velocity preconditioner
does not reuse stale forces or coefficients. The surface projection factors its
fixed-width banded mass matrix once, with O(nx) solves as geometry moves. The
public workflow keeps one latest mechanical snapshot and current RK states;
it does not accumulate full field histories or duplicate them for archiving.
Identical source-bound state requests reuse the verified snapshot. A separate
three-output measurement includes setup, source checks, output hashing and close.

Isolated 16x8 three-output timings, rotating fresh/retained order:

| Path | Samples (s) | Median (s) |
| --- | --- | --- |
| Fresh preparation/output | 0.8533954, 0.8141800, 0.8324291 | 0.8324291 |
| Verified latest-state reuse | 0.3776219, 0.3642451, 0.3899600 | 0.3776219 |

Saving: **0.4548072 s / 54.63615%**, with every output field byte-identical.
This is identical-state reuse, not a claim to reuse a changing surface operator.
The initial combined report's timing may have overlapped source-identity tests;
it is preserved but not used for the headline saving. Only the approximately
four-second timing check was repeated in isolation; acceptance was not rerun.

### Acceptance results and execution record

| Q2 element mesh | Maximum amplitude error, a=1e-4 |
| --- | --- |
| 4x2 | 0.9973676% |
| 8x4 | 0.03901025% |
| 16x8 | **0.003687644%** |

Half-amplitude finest error is 0.003687560%. Successive timestep differences
decrease by factors 4.11201/4.11201, consistent with second-order time accuracy.
The normalised full/half amplitude difference is 3.09647e-10; second-harmonic
amplitude falls by a factor of four when the initial amplitude halves. The
finest full-amplitude trajectory's maximum total-volume relative drift is
5.99520e-15; maximum per-cell homogeneous density discrepancy is 3.60595e-12.
The independent BVP/closed-rate discrepancy is at most 1.86518e-14.

All ten unique trajectories pass. Finest 64-step trajectories took
**2.5490270 s / 2.6320338 s**, including plan setup and source-bound operations.
They each used 129 mechanical solves and three retained endpoint hits. No
multi-day benchmark or long geological campaign was needed. The complete report
peak accounted memory was 21,349,888 bytes, including its caller allowance;
zero refusals and zero retained reservations at completion. Native execution:
Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, one numerical thread.
Linux execution is not claimed by this Windows run.

Twenty-six new focused methods have passing evidence: eight strength, eight
mapped mechanics, two geometry and eight public surface methods. The mapped
affine shear fixtures initially omitted side shear traction; the physical input
was corrected, not the solver tolerance. Their affected checks passed. Four
mechanical cases affected by added independent stress/work gates passed in
0.038 s. Public tests initially had seven passes and a cancellation fixture
using a callable rather than the retained Event contract; its corrected test
alone passed in 0.360 s, with production bytes unchanged. Public coverage
includes a real 256-step continuation, non-unit SI, invalid states, source
changes, exact between-node Jacobian inversion, cancellation and resources.
Nine shared source-identity methods passed in 1.823 s. Static coding safety:
13 source maps/41 paths passed; 31 tests ran in 0.106 s, one Windows symlink
skip. Passed tests were not duplicated merely because another worker ran them.
One report-open permission refusal occurred before the authorised acceptance
execution; no simulation had started in that failed invocation.

Report SHA-256: `dd64cd16bde01bfbef42bf4f75773f63bd199e5fbacac4518957619b021cc055`.
Isolated timing SHA-256: `043c35a5972dca04605efb149bc19c7a0750d6a62e33a926408eb9646c03fe67`.

## Papers and software actually checked

- [ASPECT 3.0 ALE method documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/arbitrary-le-implementation.html):
  normal mesh/material agreement, Laplacian mesh extension and physical-minus-mesh
  advection. Relevant method text read; ASPECT was not executed.
- [ASPECT 3.0 free-surface stabilisation documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/stabilization.html):
  reviewed its Kaus-et-al-based quasi-implicit traction approach. Not enabled;
  explicit timestep refinement is used here. This is not a claim of a separate
  full Kaus-paper review this turn.
- [ASPECT ViscoPlastic documentation](https://aspect-documentation.readthedocs.io/en/latest/doxygen/classaspect_1_1MaterialModel_1_1ViscoPlastic.html)
  and [DruckerPrager documentation](https://aspect.geodynamics.org/doc/doxygen/classaspect_1_1MaterialModel_1_1Rheology_1_1DruckerPrager.html):
  detailed 2D strength and effective viscosity formulas checked. The frozen C01
  perfect-min/refusal envelope is retained, not ASPECT regularisation/clipping.
- [May, Brown and Le Pourhiet (2014), pTatin3D, Section II](https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf):
  selected full-text method section checked for Q2/P1-discontinuous elements,
  physical-coordinate pressure and mapped Stokes treatment. No external code
  copied or framework installed/executed.
- [Pogosian et al. (2015), Section 3.1 and supporting sections](https://www.intechopen.com/chapters/47551):
  selected full text read for finite-depth viscous surface relaxation, solid
  no-slip bottom and thin/deep limits. A printed sign inconsistency is not copied:
  the independent traction BVP and positive decay convention establish the sign.
  The paper's COMSOL comparison is not an Atlas COMSOL execution or source review.

## Files and reproduction

New production modules: `regional_strength.py`, `regional_surface_stokes.py`,
`surface_geometry.py`, `free_surface.py` under `src/atlas_tectonics/`. Public
exports and live execution identity include the new production modules.

Run with the existing scientific environment, from `tectonics`:

```text
python -I -B tools/check_w07_surface.py --report evidence/w07-surface.json
```

The runner creates a **new** report exclusively and preserves failures. It never
overwrites historical evidence or changes tolerances after a failure. Focused
test sources are `test_w07_regional_strength.py`, `test_regional_surface_stokes.py`,
`test_w07_surface_geometry.py` and `test_w07_free_surface.py`. No package install,
held R4.4/whole-world campaign, commit or push is part of this increment.
