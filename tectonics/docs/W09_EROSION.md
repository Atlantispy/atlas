# W09 Step 3: finite-material erosion and hillslope transport

23 September 2026. **WORKING NON-CANON. Step 3 COMPLETE** for the fixed-receiver
river and initial strip hillslope operators in the
[frozen design](W09_SURFACE_PROCESSES.md), without changing its
[independent case register](../cases/w09_surface_processes_r1.json).

## Material-aware river incision

`w09_erosion.PreparedErosion` owns a supplied acyclic single-receiver graph,
physical link lengths/areas, basal elevations and source-linked material laws.
`initialise` accepts finite nonporous rock layers, top first, and one homogeneous
mobile alluvial layer containing identified cohorts. Rock layers can have different
erodibilities, thresholds and densities. No infinite substrate or discarded fines
fraction is supplied implicitly. SI units and m=0.5, n=1 are fixed by this model.

`advance(state, duration_s, discharge_m3_s=..., forcing_id=..., partitions=...)`
processes downstream cells before upstream cells. The newly solved receiver
height enters the same interval's local solve. Rock lowering, sediment shielding
and changing physical slope are solved together, not with frozen initial rates.
Dry, terminal and explicitly inundated cells have no river erosion. Callers must
supply physical discharge and lake classification; omission of the inundation
mask explicitly selects the uninundated operator, not an inferred water history.

The implemented reduction is a single monotone scalar backward-Euler solve.
For removed bulk cover y, H=H0-y, D=z0-z_receiver_new, ar=Kr*sqrt(Q)/L and
as=Ks*sqrt(Q)/L, eliminate rock removal x algebraically:

    e = exp(-H/Hstar)
    d = D-y
    x = dt*e*max(ar*d-cr,0)/(1+dt*e*ar)
    (1-phi)*y = dt*max(as*(d-x)-cs,0)*(-expm1(-H/Hstar)).

Safeguarded Newton iterations stay in the physical bracket; a bounded failure
refuses the candidate. Solving for removed thickness avoids subtracting nearly
equal cover heights to calculate small transfers. Bare rock has a direct n=1
update. This is an Atlas discretisation of the selected sharp-threshold law,
not a claim of copied SPACE discretisation or identical Landlab defaults.

Every rock interface triggers a candidate-sweep event search: the receiver is
recomputed at each trial time. The actual remaining donor stock is then booked,
the next identified rock layer becomes active, and the remaining interval uses
its properties. Discrete event times converge with timestep refinement; they are
not labelled exact continuous trajectories. If the last supplied rock is
exhausted, `ErosionExhaustionError.state` contains the valid endpoint and further
unspecified erosion refuses. Exponential shielding does not permit arbitrary
finite-time deletion of the last positive alluvial cover.

`prescribed_release` is the separate finite constant-mass-rate adapter/control:
E3 pays 2 kg and -200 J at 2/3 s, then refuses the unspecified continuation.
It is not the erosion rate law. All releases remain explicit per-cell/tag stocks,
including density, signed reference enthalpy, origin and formation time. They
are available for Step 4 transport; release is not yet a routed ocean export.
Porosity defines bulk volume but does not manufacture saturation or water.

The prepared river graph is an explicit frozen operator. Adverse slopes refuse;
competing receivers, changing lakes and evolved routing need the Step 4 joined
driver to rebuild the Step 2 geometry and conservatively carry water. A fixed
receiver calculation alone does not certify a dynamic catchment.

## Finite mobile-soil hillslopes

`w09_hillslope.PreparedHillslope` implements the full nonlinear Roering face law
on the initial supplied **one-dimensional strip/periodic-chain** support.
Areas, physical widths and centre/face distances are explicit. Branching supports
refuse: separate face slopes must not be misrepresented as a reconstructed 2D
gradient magnitude. This strip route matches the initial W04-compatible feedback
support; a full planar gradient implementation is still separate work.

Sparse damped Newton backward Euler evolves the physical slopes. The same
integrated shared-face transfers feed an implicit conservative cohort-mixing
solve. Each cell/tag grain-mass account and signed-enthalpy account closes.
Different cohort densities and unequal areas/porosities are supported. Material
removed at one face is delivered at the other or booked as an explicit export.
External faces are export-only fixed heights, never unlimited soil supplies.

Bare rock is immobile, including steep cliffs. Soil-covered slopes at or above
the supplied critical slope refuse the missing failure law; no denominator clamp
or blanket terrain smoothing is applied. At finite depletion a constrained
volume/time solve returns `status='DEPLETED'`, its valid state and event time;
the unadvanced remainder is explicit. Newly received soil can become a donor on
the next interval. Weathering, landslides and pore-water flow are not invented.

## Efficiency, source protection and recovery

Both operators detach immutable inputs, retain prepared geometry and source/runtime
identity, and keep only one latest complete-request cache entry. Changed forcing
or initial state computes new physics while reusing preparation. Both new modules
join the loaded-code identity; the package now has 119 Python source files under
the unchanged 128-file bound. Old reports/checkpoints are not repinned.

The river path uses ordered scalar solves rather than a general global nonlinear
matrix. The hillslope path uses sparse shared-face Jacobians and one multi-cohort
mixing solve. Native numerical work is limited to one thread. Independent tiny
controls are not routed through process-pool startup. Retained plus candidate
accounting stays within the existing shared 128 MiB budget; 256 cumulative accepted
intervals, 256 cells and 2048 connectors are unchanged. Newton/event trial
evaluations are bounded work, not accepted physical intervals.

River `checkpoint`/`restore` uses the existing explicit ArrayStore and verifies
the complete stock, source, plan and state identity. Its restored continuation is
bit-identical and never repeats a paid release. Hillslope snapshots are immutable;
its persistent codec belongs to the joined Step 5 recovery increment. Cancellation,
invalid inputs and failed candidates leave accepted inputs unchanged.

## Focused verification

Thirteen river test methods and fourteen hillslope methods have passing Windows
evidence, plus nine existing shared-identity checks. Tests cover E1-E3/H1-H2,
updated downstream heights, changing cover, different finite rock layers, signed
heat, tiny releases, true loss of supply, dry/flooded/threshold cases, source drift,
immutability, cancellation, budget release, reuse and river checkpoint continuation.
An initial checkpoint test used an incomplete ArrayStore constructor; its explicit
limits/codec fixture was corrected and the actual restart test then passed.

E1 matches the independent backward-Euler formula and converges towards 4*exp(-t)
at 16/32/64 partitions. The two-material interface also meets the independent
piecewise-exponential temporal refinement control. H2 uses analytic **cell means**,
normalised by the decaying perturbation rather than the constant 10 m background:

| Relative error | Coarse | Middle | Fine |
| --- | ---: | ---: | ---: |
| H2 spatial 8/16/32 cells | 0.00128120279717 | 0.000335634459446 | 0.0000982408822196 |
| H2 temporal 16/32/64 intervals | 0.000302717533754 | 0.000151657407690 | 0.0000759036153402 |
| Nonlinear two-cell temporal 16/32/64 | 0.000296657 | 0.000148775 | 0.0000744996 |

Temporal H2 comparison uses the independent finite-volume eigenmode to separate
time error from spatial error; spatial comparison uses the continuum profile at
256 accepted intervals. Refinement ratios exceed 1.5 and finest errors are below
the unchanged 1% gate. The explicit Sc=1e6 low-slope control uses the same nonlinear
solver, not a substituted linear/frozen-rate implementation.

The source-bound control and matched-work timing driver is
`tectonics/tools/check_w09_erosion.py`. It refuses an existing report target or
changed source/fixture and preserves a failure report. No full-world run, plotting,
runtime installation or held R4.4 campaign is needed for this increment.

## Measured preparation reuse

[Source-bound control and timing evidence](../evidence/w09-erosion.json): all five
frozen controls and 45 numerical/account/refinement observations pass. Three
rotated cold/prepared pairs per workload include fixture construction, setup,
source checks, initialisation, full evolution, complete arrays/metadata handling,
accounts and close. Every changed request computes new physics: **zero complete-
result cache hits**, and all complete output arrays and state IDs are bit-identical.

| Three changed requests | Cold median | Prepared median | Saved |
| --- | ---: | ---: | ---: |
| Covered 256-node river, two identified rock layers/cohorts | 1.2238466 s | 0.8772547 s | 0.3465919 s / **28.3199%** |
| Closed 32-cell hillslope strip, two cohorts | 0.9545340 s | 0.5839676 s | 0.3705664 s / **38.8217%** |

The complete controls/timing run took **16.8541338 s**. Peak combined accounted
work, including evidence output allowances, was **50,331,648 bytes (48 MiB)**
under the unchanged 128 MiB cap; it is not an RSS measurement. Windows, Python
3.12.14, NumPy 2.4.6 and the existing SciPy runtime, one native thread. Source
inventory before/after matches. No Linux runtime claim or whole-world time forecast.
The earlier launch used bundled Python without SciPy and failed before any controls;
that local failure was preserved, then the existing scientific environment was used.

Reproduce with that environment, choosing a new output path:

    python -B tectonics/tools/check_w09_erosion.py --repo . --report <new-report.json>

Static coding-safety checks also pass: 13 maps/41 paths and 31 tests in 0.111 s,
with one environmental skip. No broad physical regression was repeated.

## Papers and software checked

- [Shobe, Tucker and Barnhart (2017), SPACE 1.0](https://gmd.copernicus.org/articles/10/4577/2017/):
  simultaneous rock/alluvium erosion, exponential cover and finite conservation;
  locally frozen-slope analytic updates do not themselves solve changing slope.
- [Landlab SpaceLargeScaleEroder source](https://landlab.readthedocs.io/en/latest/_modules/landlab/components/space/space_large_scale_eroder.html)
  and its sequential erosion/deposition kernel: model interfaces and reconciled
  flux/thickness accounts; its smoothed thresholds/fines defaults are not adopted.
- [FastScape documentation](https://fastscape.org/fastscapelib-fortran/) and
  [implicit SPL implementation](https://github.com/fastscape-lem/fastscapelib/blob/master/include/fastscapelib/eroders/spl.hpp):
  downstream-first implicit solves and direct n=1 elimination.
- [Roering, Kirchner and Dietrich (1999), equation 8](https://seismo.berkeley.edu/~kirchner/reprints/1999_29_Roering_nonlinear.pdf):
  nonlinear mobile-soil transport and its critical-slope domain.
- [Landlab Perron nonlinear diffusion](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.nonlinear_diffusion.Perron_nl_diffuse.html)
  and [SciPy sparse solve](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.spsolve.html):
  implicit sparse work and the existing selected sparse backend.

No third-party simulator was installed or executed as a comparator, and no source
implementation was copied. These checks do not substitute for scenario calibration.

**Next: Step 4** — tagged source-to-sink transport and deposition, stratigraphic
insertion, drained compaction, and the explicit water/material/thermal/load bridges.
