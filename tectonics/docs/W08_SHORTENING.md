# W08 shortening, transform and oblique motion

Status: local implementation, 23 September 2026.
The [Step 1 design](W08_REGIMES.md) and [case register](../cases/w08_regimes.json)
remain frozen. Step 2 implements their distributed plane-strain shortening route;
it does not manufacture fault or underthrust geometry from convergence. Step 3
separately covers prescribed [transform and oblique motion](#w08-step-3--transform-and-oblique-motion).

[Shortening](#implemented-model-and-interfaces) · [Transform and oblique motion](#w08-step-3--transform-and-oblique-motion) · [Prescribed underthrusting](#prescribed-collision-and-underthrusting)

## Implemented model and interfaces

`shortening.PreparedShortening` retains a W02 `MaterialState` on `ColumnGrid1D`,
explicit per-cohort density, strike width, datum and source provenance. Optional
specific enthalpy requires its source; absent heat remains explicitly unknown.
Parcels are piecewise-constant Lagrangian material, not point samples of an
unspecified smooth profile. Formation/epoch history is preserved.

`ShorteningInterval` prescribes `v(x) = a*(x-anchor) + b`, with `a <= 0`.
Exact exponential finite maps, stable local coordinates and prepared prefix maps
evaluate any supported output directly from the reference. Intermediate queries
do not add numerical timesteps or repeatedly remap material. Conserved parcel
volume divided by its actual deformed area gives thickness: a 30 km column
becomes 37.5 km after 20% shortening, and 60 km after 50%.

`project` integrates exact sparse interval overlaps onto a fixed target grid.
It returns per-cohort volume, mass and relative enthalpy, plus separately named
left/right exterior inventories. A crop is a view, not a material deletion or a
second export. Complete compensated signed accounts use constituent magnitudes
for their roundoff scale. Unresolvable coordinate motion, nonfinite stocks,
incompatible states, cancellation and resource excess fail explicitly.

`shortening_support.PreparedShorteningSupport` constructs reference/current dry
fixed-base W04 columns on one uniform target, with explicit support height and
zero replacement density. Reference and current footprints must fit completely.
Every actual overlapping parcel must also fit vertically: diluted cell means
cannot hide a tall narrow parcel. Per-phase `rho*g*deltaH` loads feed the existing
W04 continuous uniform finite-region flexure and W05 exact cell-mean operator.
There is one support owner: downward deflection `w` produces surface change
`deltaH-w` and base change `-w`, without a second Airy correction. Continuous
displacement, slope and bending-strain bounds are enforced between samples too.
This operator supplies loading response, not compressional buckling. Transported
enthalpy does not silently create a thermal-buoyancy closure.

Prepared operators/reference loads and the latest immutable exact projection are
reused. Live source checks remain on cache hits. Existing shared 128 MiB accounted
budgets and the 256-history-interval cap are retained; accounted allocation is not
process RSS. Caller-retained older outputs need the caller's own allowance.
Persistent joined W08 restart belongs to increment 6. A supplied fault/underthrust
scenario still needs its separate structural and host-space closure; none was
invented for this distributed-shortening increment. The later
[transform/oblique route](#w08-step-3--transform-and-oblique-motion) and [joined workflow](W08_JOINED.md)
retain their own source and acceptance boundaries.

## Shared source-capture prerequisite

`reuse.py` now streams **all current package source bytes** through SHA256,
retaining canonical path/byte-count/digest records rather than duplicate raw text.
The explicit representation successor is `atlas.package-source-digests.v1`;
execution identity advances from v3 to `atlas.kernel-execution.v4`. Old checkpoint
identities refuse rather than being repinned. Loaded callable/default/constant
and runtime checks remain, including the two new shortening modules.

At this W08 checkpoint the 128-file membership limit stayed fixed; the later
[A3 repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raises it to 512 without changing the 2 MiB bound. That bound applies to the
complete encoded inventory, not raw source text; this is a representation change,
not a claim that the former raw-text limit still applies. A single 64 KiB buffer
is reused. Each invocation rereads every byte, detects source changes during
capture and does not substitute timestamps for hashing.

On an immutable 96-file, 2,097,129-byte fixture, three rotated repetitions of
capture plus comparison gave median 0.0180619 s before versus 0.0135673 s after:
0.0044946 s / 24.8844% saved, with complete source-record parity. Tracemalloc
retained/peak allocations fell from 2,109,561/2,215,469 B to 19,648/196,766 B.
These are source-capture measurements, not RSS or whole-generator timings.

## Focused verification and performance

The final two W08 test modules pass **21 tests in 7.113 s** on Windows. Coverage
includes frozen finite-strain controls, nonuniform parcels, partition invariance,
noncommuting motion, signed heat and cropped accounts, boundary-relative flux,
identity/cache/refusal/cancellation/budget cases, independent load/support
integrals, continuous physical bounds and the narrow-parcel support-height case.
Nine source-inventory and nine shared identity tests also passed in a focused
19-test run (5.367 s, including the corrected cancellation test).

The final source-bound [r2 report](../evidence/w08-shortening-r2.json) compares the
support response against independently integrated continuum loads at 17 fixed
positions. For the declared two-cohort, 100 km patch with 2% shortening:

| Target cells | Maximum sampled displacement error | RMS error |
| --- | ---: | ---: |
| 64 | 10.73903 m | 6.15117 m |
| 128 | 2.34934 m | 1.34745 m |
| 256 | 0.71808 m | 0.41154 m |

The predeclared finest-grid 1 m engineering target and decreasing RMS pass.
This is numerical reference error, not field calibration or global terrain error.
The synthetic one-second motion parameter is not a calibrated geological rate.

Three complete 64-parcel to 256-cell outputs, three rotated timing repetitions,
one native thread, identical complete output identities:

| Execution | Median elapsed time |
| --- | ---: |
| Fresh preparation for each output | 1.0531178 s |
| One prepared plan for all three | 0.5586197 s |
| Saved | **0.4944981 s / 46.9556%** |

Both include preparation, source verification, motion, projection, support,
result hashing and close; interpreter startup/imports are excluded. Peak
accounted allocation is 4,881,944 B for either route. This is a bounded W08
sequence, not a generator-wide speed-up. The earlier `w08-shortening.json`
report remains historical evidence for its own source hashes, not the final build.

Development failures were resolved without changing scientific gates: a test
passed a function instead of the existing cancellation Event contract; a source
test omitted its required cancel argument; Windows symlink creation lacked
privilege and that subcase is explicitly skipped. The first report write was
denied by the local sandbox; the authorised rerun wrote evidence successfully.
Review also corrected signed-heat cancellation scaling, retained metadata
accounting, unresolvable motion and the physical support-height gap before r2.

Reproduce from the repository root with `PYTHONPATH=tectonics/src;tectonics/tests`
on Windows (use `:` on Linux), using the configured scientific Python:

```text
python -B -m unittest test_w08_shortening test_w08_shortening_support -q
python -B tectonics/tools/check_w08_shortening.py --output <new-report-path.json>
```

The tool refuses an existing report path. No full R4.4 run, plots, CI, installation,
commit or push was needed. Required static safety: 13 maps/41 paths PASS; 31
safety tests in 0.106 s, 30 passed and one environment skip.

## Software and papers checked

- [pyGPlates StrainRate documentation](https://www.gplates.org/docs/pygplates/generated/pygplates.StrainRate.html):
  finite deformation and dilatation/shear distinctions; no spherical metric was
  copied into this Cartesian closure. Documentation read; software not executed.
- [gFlex theory and numerics](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html):
  thin-plate equations, analytical superposition and boundary assumptions informed
  reuse of Atlas's existing no-in-plane-stress W04/W05 support. Documentation read;
  external gFlex not executed or adopted as a dependency.
- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.html):
  publisher abstract/method summary checked this increment, not a new full-paper
  review. The prior equation-level review is recorded in
  [W04 finite regions](W04_COLUMN_LOADS.md#finite-region-support). Independent reference evaluation
  reuses the existing scalar SciPy quadrature helper, not the production operator.

## W08 Step 3 — transform and oblique motion

This is the full-vector horizontal kinematic increment from
the [frozen W08 design](W08_REGIMES.md), not an earthquake-cycle displacement
accumulated as geological deformation. The [challenge definition](../cases/w08_transform.json)
was written before candidate execution; the parent design and A02/A03 controls
remain unchanged.

Local implementation and bounded acceptance complete, 23 September 2026.

### Motion and material connections

Three explicit motion producers cover distinct assumptions:

- `transform.PreparedAffineMotion`: piecewise constant full 2x2 spatial velocity
  gradients and both translation components. A dimensionless homogeneous 3x3
  matrix exponential handles singular gradients without inversion; ordered prefix
  maps evaluate requested times from the reference. Pure/simple shear does not
  automatically thicken crust. True finite rigid rotation remains strain-free.
- `deformation_network.PreparedDeformationNetwork`: prescribed shared-vertex
  trajectories on a conforming triangular mesh. Interior deformation may vary,
  supporting distributed restraining/releasing bend or stepover scenarios with
  affine far-field motion. Each interval's vertex paths are linear in time; this
  is deliberately not a constant spatial-gradient field. A rotation endpoint on
  this route follows a chord, so use the affine exponential route for rigid spin.
  The initial domain must be a fully tiled convex polygon. Shared vertices close
  junctions; positive element determinants and an affine bijective boundary are
  enforced **throughout** each interval. Quadratic determinant minima detect
  temporary inversion even when both endpoints have positive orientation.
- `fault_slip.PreparedFaultSlip`: prescribed rigid translation on either side of
  a named straight transform interface. Full vectors and boundary motion are
  retained; relative normal motion must vanish. Opposing tangential motion gives
  genuine slip without artificial thickening. Normal opening/convergence requires
  a separate creation/accretion/deformation closure and refuses this route.

`transform.PreparedPlanarMaterials` connects these producers to the existing W02
cohort catalogue, formation history, explicit epoch/datum and constant reference
density. Complete parcel volume, mass and optional signed relative enthalpy stay
with the material. Thickness is reconstructed from conserved volume divided by
actual area; unknown heat is labelled unknown, not silently a physical zero.
The planar outputs do not silently flatten along-strike motion into W07's vertical
plane-strain solver or claim a general two-dimensional W04 support bridge.

`project` provides conservative views in named receiving polygons, using
`PreparedPlanarProjection`. STRtree bounding boxes prune candidates; exact GEOS
intersections determine fractions. No dense source-by-target matrix, centre
sampling, geometry repair or cropped-stock renormalisation is used. Unobserved
material remains attached to its named exterior parcels.

`exchange` reports the actual material moving from each named starting region to
each ending region, including a retained exterior row/column. Regions themselves
may move. This is an endpoint material-origin/destination account, not a count of
every intermediate crossing. Independent start/end projections must match the
transfer rows/columns. The instantaneous boundary helper uses `(v-v_boundary).n`,
not total speed. Fixed-orientation moving-frame conversion subtracts frame velocity
and retains both horizontal components.

Material views and exchange records contain geometry, cohort, motion, source,
runtime and interval identities. The full source is verified at public operation
entry and exit, including before cache reuse. All new modules participate in the
loaded-code inventory; SciPy's selected exponential binary joins the runtime
identity. Producers stamp their source/runtime identity while preparing prefix
maps; the material bridge refuses to attach a different later identity to those
already-computed maps. Existing checkpoints cannot silently acquire a new binding.

### Efficiency and bounded execution

Exact maps avoid timestep loops and repeated material remapping. Prefix history
maps, sparse geometry and the latest exact immutable result are reused where
compatible. Nested projection shares its public operation's source checks instead
of repeatedly hashing identical source inside that same call. Independent
physics are not run in parallel for these short workloads.

Default owner budgets remain 128 MiB accounted work, with at most 256 history
intervals, 4096 parcels and existing geometry limits. This is allocation admission,
not a measured RSS ceiling. Nodal output geometry owns a lease until released;
other caller-retained outputs require their documented caller allowance. No full
world run, plotting, installation, commit or push is part of this increment.

### Verification and measurement

The [final source-bound report](../evidence/w08-transform.json) passes. The bounded
bend challenge compares the supplied smooth displacement derivative against
4/8/16-subdivision piecewise-affine fields. Its dimensionless Jacobian RMS errors
are 0.06860255, 0.03570791 and 0.01804426 respectively, decreasing at every level
and meeting the predeclared finest-grid 0.02 gate. The 512-triangle case retains
positive orientation, both thickening and thinning, and complete volume, mass and
signed enthalpy totals. Peak accounted work is 13,380,058 B, below the unchanged
128 MiB budget. Numerical challenge error is not empirical terrain accuracy.

All **66 new W08 focused checks** have passing evidence: 12 material/affine
integration, 18 network, 13 sparse projection, 12 region exchange and 11 fault-slip
checks. The final integrated run contains the 12 material and 18 network checks
plus nine shared identity checks: **39 tests PASS in 12.861 s**. Unchanged worker
evidence is reused for the other modules, not redundantly rerun. Coverage includes
exact A02/A03 controls, 8/16/32 parcels, 1/2/4 history partitions, actual region
exchange, moving-frame invariance, cancellation, budgets, source drift and stale
prepared-map refusal. Required static safety: 13 maps/41 paths PASS; 31 tests in
0.106 s, 30 passed and one environment skip.

Windows/CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1, one native thread; three rotated
repeats of 64 material polygons, 168 receiving polygons and two cohorts:

| Requested sequence | Fresh preparation each time | Prepared/reused | Saved |
| --- | ---: | ---: | ---: |
| Three changing outputs | 1.5057947 s | 0.7288984 s | 0.7768963 s / **51.5938%** |
| Three identical outputs | 1.5463292 s | 0.5526403 s | 0.9936889 s / **64.2611%** |

Complete output identities match in both comparisons. These medians include
preparation, source verification, motion, conservative material projection,
materialisation and close; interpreter startup/imports are excluded. Changing-output
peak accounted work is 4,382,232 B fresh and 4,417,455 B reused; identical-output
paths both peak at 4,382,232 B. These are bounded motion/material timings, not
generator-wide speed-up percentages. The full reference/timing tool took 15.489 s.

One integration defect was found before acceptance: mapping adjoining triangle
pieces independently introduced tiny roundoff overlaps at a shared junction.
The correction keeps transfer intersections in each donor's material coordinates;
it does not relax topology or account tolerances or snap geometry to conceal it.
Its initial integrated run had nine passes and that one error; the targeted case
and final integrated run pass after correction. A new analytic zero-exterior
assertion was corrected to acknowledge 1.11e-16 static-projection roundoff, within
the unchanged 128-epsilon gate. Producer preparation additionally gained a bound
source/runtime stamp, preventing later contexts from adopting stale prefix maps;
small resource-test fixtures were enlarged to include its new 2 MiB scratch charge,
not to raise production limits.

Reproduce with the configured scientific Python and `PYTHONPATH=tectonics/src;tectonics/tests`
on Windows (`:` separator on Linux):

```text
python -B -m unittest test_w08_transform test_w08_deformation_network test_w08_planar_projection test_w08_planar_exchange test_w08_fault_slip -q
python -B tectonics/tools/check_w08_transform.py --output <new-report-path.json>
```

### Software and papers checked

- [pyGPlates StrainRate documentation](https://www.gplates.org/docs/pygplates/generated/pygplates.StrainRate.html):
  velocity gradients, dilatation, shear/spin and finite-strain distinctions. Its
  spherical coordinate terms are not copied into this Cartesian implementation.
- [SciPy `expm` documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.expm.html)
  and [Al-Mohy & Higham (2009)](https://eprints.maths.manchester.ac.uk/1442/):
  scaling/squaring, Padé evaluation and overscaling informed using the existing
  tested exponential with dimensionless local coordinates. Documentation and
  the paper's author-repository abstract were checked, not a fresh full-paper audit.
- [Shapely STRtree documentation](https://shapely.readthedocs.io/en/stable/strtree.html):
  bounding-box candidate queries and original-geometry indices informed sparse,
  deterministic intersections rather than all-pairs matrices.
- [Lipman (2014), Bijective Mappings of Meshes with Boundary](https://arxiv.org/abs/1310.0955):
  abstract's sufficient-condition distinction supports requiring a bijective
  boundary as well as orientation-preserving elements. Abstract checked; the
  author-hosted full-text fetch timed out, so no full-text review is claimed.
- [Müller et al. (2018), GPlates](https://doi.org/10.1029/2018GC007584):
  indexed deforming-network/triangulation excerpts checked; publisher fetch timed
  out. The concrete Atlas closure remains explicit, not a GPlates reproduction.

SciPy and Shapely are existing dependencies actually used. GPlates and external
geodynamic packages were not installed or executed. The later
[Step 4 subduction and computed-wedge route](W08_SUBDUCTION.md) and
[Step 6 joined workflow](W08_JOINED.md) have their own component and integration
results; this motion increment does not qualify them.

## Prescribed collision and underthrusting

Local implementation, 23 September 2026.
Tectonics continuation Step 2; this supplements, not rewrites, the frozen
[W08 regime design](W08_REGIMES.md) and its case register.

### Implemented model

`atlas_tectonics.underthrust` supplies a conservative ramp-and-flat section route.
The caller identifies the footwall and hangingwall, a fixed single-valued
descending interface, its flat detachment depth, x/z frame, vertical datum,
section azimuth, strike width and time epoch. Material parcels keep their actual
cohort/formation history, density and optional source-labelled specific enthalpy.
Motion and work histories identify their sources; no polarity or fault geometry
is inferred from a height map.

For interface height h(x), horizontal displacement s maps material as

    T_s(x,z) = (x+s, z+h(x+s)-h(x)).

Flattening to eta=z-h(x) turns this into translation. Splitting polygons at
interface knots gives exact affine pieces, with determinant one: area, fixed-width
volume and interface side are conserved. The two blocks have independently
supplied horizontal velocities, with nonnegative relative underthrusting. The
associated vertical velocity is u*h'(x). This is a prescribed vertical-shear
closure: it preserves vertical thickness, not general bed-normal thickness or
bed length. It is not a stress-selected fold or a predicted fault trajectory.
Endpoint flats continue explicitly outside the supplied knot range.

Initial material must be non-overlapping and on its stated interface side.
The maps are injective within each moving block and side-preserving between them.
Any stationary host stock is explicit; a swept-polygon check in flattened
coordinates rejects intersection throughout each full history interval, including
collisions missed by clear start and end positions. The source-labelled host-space
declaration is a caller completeness contract, not an inference that omitted
geology is empty.

Named, non-overlapping receiver polygons describe where occupied material ends up.
Sparse intersections allocate each parcel's volume, mass and signed enthalpy;
the actual polygon difference remains in a named exterior destination. Exterior
stock is retained, not deleted or counted again as an export. Unknown heat has
an explicit mask and is never asserted to be physical zero heat. No snapping,
geometry repair or size-based material deletion is used.

Boundary work is the integral of supplied generalised force Q times horizontal
slip, recorded separately for the two blocks. Gravitational change is m*g times
the actual parcel centroid change. Q is not an inferred reaction or an unstated
traction. An unclosed work/energy difference is not silently converted to heat.
This producer does not independently add uplift, flexure or sediment loads.
The [joined-history owner](EVOLVING_MECHANICS.md#tectonics-continuation-step-4-supported-dated-histories) now accepts this typed preparation
alongside the supported evolving-mechanics routes. That connection preserves the
prescribed model; it does not turn this section into general collision dynamics.

### API, bounds and efficient reuse

`UnderthrustInterface`, `UnderthrustParcel` and `UnderthrustInterval` define inputs.
`PreparedUnderthrust(...).evaluate(time_s)` returns immutable polygons, receiver
accounts, block displacements, work and gravitational changes. Its descriptor
retains source, cohort, frame, datum, epoch and execution identities.

Preparation flattens original geometry once and builds receiver indices. Changed
outputs evaluate directly from the reference, without timestep loops or cumulative
remapping. Parcels inside one affine domain avoid unnecessary intersections/unions.
Only the latest output is retained; exact repeat requests still verify live code.
Callers retaining older outputs must account for their own storage. Close releases
the prepared/latest reservations. Persistence is supplied by the
[joined-history owner](EVOLVING_MECHANICS.md#tectonics-continuation-step-4-supported-dated-histories), not by a second checkpoint codec in
this section producer.

Bounds: shared-accounted 128 MiB, 4,096 parcels, 256 intervals, 64 interface knots,
64 receivers and the existing geometry complexity limits. Nonfinite, unresolvable
and underflowing nonzero accounts refuse rather than disappear. The unchanged
128-file source limit now covers 120 production files. Live identity includes
the new defining classes and methods; existing source-bound evidence/checkpoints
are not silently rebound to changed code.
The later [A3 capacity repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raised the source limit to 512 files; the count above is this checkpoint's.

### Focused evidence and measured optimisation

Nineteen underthrust tests plus nine existing execution-identity tests pass:
28 in 6.744 s. Coverage includes independent flat/ramp geometry, parcel accounts,
signed/unknown heat, force-work versus centroid gravity, history partitioning,
mid-interval host collision, narrow material slivers, underflow refusal, source
drift, immutable outputs, cancellation and budget release.
Required static checks also pass: 13 source maps / 41 paths and 31 tests in
0.107 s (one environmental skip). No whole-world campaign was run.

[Source-bound evidence](../evidence/underthrust-r1.json) also passes an independent
six-vertex ramp control and closed-form whole-block centroid integration. It
records complete source/tool/contract hashes, literal inputs, runtime, all raw
timings and full-output hash parity. Reproduce from the repository root with a
new evidence path (the tool refuses overwrite):

```text
python -B tectonics/tools/check_underthrust.py --report <new-report-path.json>
```

On Windows, three changed outputs for a 64-parcel, eight-receiver section took
**0.8841770 s cold versus 0.4517789 s prepared**, median of three alternating
pairs: **0.4323981 s / 48.9040% saved**. Each route computes all three outputs;
there are no complete-result cache hits. Timing includes preparation, live source
verification, output materialisation/hashing, cheap conservation controls and
close. Imports, input construction and report writing are outside that comparison.
Peak shared-accounted allocation was **11,097,388 bytes**, not process RSS; all
reservations were released. The entire evidence run took 4.570 s. These are
preparation-reuse savings, not a whole-generator or dynamics-solver speedup.

### Papers and reference software inspected

- [Plotek et al. (2021), Analysis of fault bend folding kinematic models and comparison with an analog experiment](https://doi.org/10.1016/j.jsg.2021.104316):
  vertical-shear conservation and its distinction from bed-length/thickness
  conservation; analogue results caution against treating it as universally best.
  [Institutional author manuscript](https://ri.conicet.gov.ar/handle/11336/135525).
- [Connors, Hughes and Ball (2021), Forward kinematic modeling of fault-bend folding](https://doi.org/10.1016/j.jsg.2020.104252):
  velocity-domain compatibility, explicit structure and overlapping-domain hazards.
- [Cardozo/Hardy `fabefo.m` reference implementation](https://github.com/nfcd/matlabScripts/blob/main/faultBendFolding/fabefo.m):
  inspected the different simple-step fault-bend algorithm and its documented
  assumptions; it was not executed or copied and is not our numerical oracle.
- [Shapely intersection documentation](https://shapely.readthedocs.io/en/stable/reference/shapely.intersection.html):
  precision/overlay behaviour of the already installed geometry backend; no new
  dependency or snapped-grid approximation.

The mathematical map is tested independently above. These sources motivate the
chosen explicit kinematic closure; they do not empirically calibrate this supplied
footwall/hangingwall case or turn it into general collision dynamics.
