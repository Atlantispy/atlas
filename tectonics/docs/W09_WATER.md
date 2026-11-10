# W09 drainage, water and finite-material erosion

23 September 2026. **Step 2 COMPLETE** for the bounded
instantaneous-routing/ideal-sill model selected in the
[frozen design](W09_SURFACE_PROCESSES.md). The original design and
[case register](../cases/w09_surface_processes_r1.json) remain unchanged.

## Implemented

- `w09_drainage.prepare_drainage`: detached immutable geometry, deterministic
  steepest-downhill receivers, acyclic flat routing, complete basin/saddle
  adjacency and Priority-Flood escape levels. Physical terrain is never filled.
  Higher alternative saddle connections are retained, not discarded by taking
  only each basin's first spill. Closed components have no invented outlet.
- `w09_water.PreparedWater`: finite volume filling, internal spills, merging,
  drawdown/splitting, drying, precipitation, effective runoff, evaporation and
  infiltration. Simultaneous losses are accounted before surplus export.
  Competing dry-bed losses share only the actually available input water.
- Event integration stops at physical bed/sill/dry boundaries; a single request
  can cross those events without exposing half-applied accepted state. Current
  lake occupancy is rebuilt after drawdown; historical filled flags are not reused.
- `accumulate_runoff` exposes dry-network discharge in m3/s, stopping at pits and
  declared outlets. It does not masquerade as transient lake discharge.
- `relocate` conserves the water on unchanged indexed cells/areas while changing
  bed/connectivity. Frame/datum and physical support must agree. Water newly able
  to escape is booked as export, not deleted. Arbitrary moving-grid overlap still
  requires the Step 4 consumer adapter.
- Source-bound complete states, one latest-result cache, and explicit atomic
  ArrayStore checkpoint/restore. A restored continuation pays only remaining
  transfers. Cancellation/refusal leaves the caller's accepted state unchanged.

The water state keeps surface m3, subsurface m3, atmospheric export m3, boundary
export m3, total supplied m3 and the initial total separately. Their integrated
account must close under the frozen binary64 tolerance. No sediment, soil flow,
support displacement or pore water is silently created by this component.

## Numerical details and interface

Use metres, m2, seconds and m3. Positive-area cells hold water; explicitly
zero-area connectors can represent a saddle without adding fictitious storage.
Outlets also have zero area. Every pit's lowest plateau needs positive area.
Link lengths must be positive; duplicate/self links, non-finite values and
unconverted/bool indices refuse. Flat ties use shortest-hop routing then stable
node IDs. Outlet spill ties use lowest sill then stable basin order.

Prepared geometry stores the full spill graph. The water solver forms currently
connected lake groups from it and resolves the active ideal-sill constraints.
This is a bounded graph implementation, not copied FSM code or a claim of linear
complexity for every coupled lake event. Effective dry-land runoff is supplied;
when `rain_m_s` is omitted, the same supplied depth flux explicitly applies to
wet footprints. Separate lake rainfall can be supplied. These are model forcing
inputs, not an inferred climate.

At a cell's represented shoreline the wet/dry footprints change discontinuously.
A receding patch ceases evaporation/infiltration. If the two one-sided rates
straddle zero, a bounded wet-duration fraction balances the contact without
nudging terrain or manufacturing water. All simultaneous contacts are resolved.
This is an explicit sub-cell contact convention, not resolved shore hydraulics.

`PreparedWater(..., frame_id=..., datum_id=..., source_id=..., budget=..., store=...)`
owns the reusable geometry and execution identity. `initialise`, `add_water` and
`advance` return immutable `WaterState` values; `advance` accepts a constant
forcing interval and its `forcing_id`. Changing forcing invalidates affected
results, not geometry. New physical geometry requires a new prepared model.
`checkpoint(state)` returns an ArrayStore key; `restore(key)` verifies plan,
source/runtime, array, account and state identities before returning it.

The model owns an 8 MiB conservative allowance for context, graph/event scratch,
one output and up to 256 cached group hypsometries. Sorted cumulative area/volume
tables replace repeated height searches with binary searches. Temporary geometry
work joins the same parent budget. Cached state is bounded and released on close.
Caller-owned retained results are not an unlimited managed archive.

Bounds remain 256 nodes, 2048 connectors, 128 MiB shared accounted work and 256
cumulative accepted subintervals. No ceiling was increased. Source membership is
now 117 Python files, below the unchanged 128-file cap; both W09 modules join the
existing loaded-code/source identity. Old checkpoint identities are not repinned.
The later [A3 capacity repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raised that cap to 512 files; the count above is this checkpoint's.

## Verification and measured efficiency

Six new drainage tests and sixteen water tests have passing Windows evidence.
They cover frozen W1-W4, nested drawdown, disjoint forcing footprints, event
partitioning, newly dry shores, multiple simultaneous shoreline contacts,
finite loss allocation, conservative bed changes, read-only snapshots, invalid
inputs, cancellation, shared-budget cleanup, interval limits, result reuse and
exact checkpoint continuation. The latest complete water suite took 8.337 s;
the subsequently added accumulation assertion and nine existing identity tests
took 3.737 s together. No broad physical campaign was repeated.

A targeted numerical check found that resolving only the first of two independent
shore contacts could conserve total water while drying the second incorrectly.
The active-set loop was corrected and that exact two-basin case is now a test.
The first evidence write exposed a NumPy-bool JSON serialisation error; the checker
was corrected, the incomplete local file preserved, and a new complete report
produced. These were fixed failures, not accepted exceptions.

[Source-bound evidence](../evidence/w09-water.json) records all four frozen water
controls (41 numerical/account observations), every timing sample, output hashes,
runtime and budgets. The complete control/timing run took **16.3237191 s**.
Three rotated cold/prepared pairs per workload include preparation, source checks,
fresh initial states, changed forcing, complete evolution, output materialisation
and close. There were no full-output cache hits in these comparisons.

| Workload | Cold median | Prepared median | Saved |
| --- | ---: | ---: | ---: |
| One fresh 256-node drainage request | 0.3407067 s | 0.3407240 s | No meaningful change; 0.0000173 s slower |
| Three changed drainage requests | 1.0249139 s | 0.6155989 s | 0.4093150 s / **39.9365%** |
| Three changed lake requests, 64 two-child systems | 1.0894821 s | 0.7501048 s | 0.3393773 s / **31.1503%** |

All complete output arrays and state identities were bit-identical between
routes. The lake fixture includes split/dry events, not only open drainage.
Peak shared accounted work was **9,158,656 bytes**; this is not process RSS.
Python 3.12.14, NumPy 2.4.6, Windows 11; both measured native pools had one thread.
These are reuse savings on stated workloads, not a whole-world time prediction.

Reproduce with the existing scientific environment:

    python -B tectonics/tools/check_w09_water.py --repo . --report <new-report.json>

The report target must not exist. The tool fixes the reference hash, checks source
stability and preserves failure status; it does not update thresholds or fixtures.
Static coding-safety checks pass (13 maps/41 paths;31 tests, one environmental
skip). Linux execution was not repeated in this increment; no OS-specific water
solver path or new runtime installation was introduced.

## Papers and software used

- [Barnes et al. (2014), Priority-Flood](https://richard.science/sci/2014_depressions.pdf):
  depression/escape preparation and deterministic priority ordering.
- [Barnes, Callaghan and Wickert (2021), Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/):
  hierarchical filling and area-weighted lake levels; its equilibrium snapshot is
  distinct from the explicit Atlas loss/event integration implemented here.
- [Landlab LakeMapperBarnes](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.lake_fill.lake_fill_barnes.html)
  and [FlowAccumulator](https://landlab.readthedocs.io/en/latest/tutorials/flow_direction_and_accumulation/the_FlowAccumulator.html):
  separation of routing geometry, lake capacity and accumulated supplied runoff.
  No third-party simulator was installed or claimed as an executed comparator.

The later [Step 3 implementation](#finite-material-erosion) supplies material-aware
bedrock/alluvium erosion and finite-supply hillslope transport. Joined
sediment/thermal/load feedback remains Step 4.

<a id="finite-material-erosion"></a>

## Finite-material erosion and hillslope transport

23 September 2026. **Step 3 COMPLETE** for the fixed-receiver
river and initial strip hillslope operators in the
[frozen design](W09_SURFACE_PROCESSES.md), without changing its
[independent case register](../cases/w09_surface_processes_r1.json).

The Step-1 design is retained byte-for-byte as a frozen case input. Its pending
implementation wording describes the design capture; the water component above and
this Step 3 document the implemented components. The joined Step-4/5 route remains
outside these component results.

### Material-aware river incision

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
A release that crosses layers ends exactly at the requested duration under the
shared end-time rule (`timebase.interval_end`): before 30 September 2026 (review
s16) `elapsed+(duration-elapsed)` could round below the duration, so a
0.0203 kg first layer followed by 100 kg, released for 0.3 s at 1 kg/s, raised a
false exhaustion at 0.29999999999999993 s.

The prepared river graph is an explicit frozen operator. Adverse slopes refuse;
competing receivers, changing lakes and evolved routing need the Step 4 joined
driver to rebuild the Step 2 geometry and conservatively carry water. A fixed
receiver calculation alone does not certify a dynamic catchment.

### Finite mobile-soil hillslopes

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
the unadvanced remainder is explicit. A completed advance ends exactly at the
requested end (shared end-time rule; previously its last partition could land one
ulp away), and a continuation may pass the original end as `end_time_s`. Newly received soil can become a donor on the next interval. Weathering, landslides and pore-water flow are not invented.

### Efficiency, source protection and recovery

Both operators detach immutable inputs, retain prepared geometry and source/runtime
identity, and keep only one latest complete-request cache entry. Changed forcing
or initial state computes new physics while reusing preparation. Both new modules
joined the loaded-code identity; the package then had 119 Python source files under
the 128-file bound. Old reports/checkpoints are not repinned.
The later [A3 capacity repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raised that bound to 512 files; the count above is this checkpoint's.

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

### Focused verification

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

### Measured preparation reuse

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

### Papers and software checked

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
