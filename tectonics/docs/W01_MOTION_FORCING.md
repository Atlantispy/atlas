# W01 Stage 6 — prescribed motion to regional forcing

**WORKING NON-CANON; reviewed and integrated locally on 22 September 2026.**
The source basis is the supplied dev42 + implemented/optimised Stage-5 snapshot.
This stage supplies prescribed kinematic input; it does not derive forces,
stress, uplift, temperature, damage or mantle evolution from velocity.
Stage 7 material initialisation/evolution and Stage 8 acceptance remain separate.
R4.4's acceptance requirements and held status are unchanged.

## Gap and reused components

Existing `rigid_velocity`, coordinate-frame transformations and shared-boundary
kinematics describe point velocities and their sides. `regional.py` consumes
N+1 face velocities for N cells, but it does not certify that projection of a
plate velocity is a justified one-dimensional reduction. The new
`PreparedRegionalForcing` bridges that gap. It uses existing immutable validated
`BoundaryNetwork` or `SphericalAtlas` ownership, prepared geometry indexes,
SI/epoch validation, source/callable checks, WorkBudget and ArrayStore. It does
not replace the Stage-5 geological description or sampler.

## Public definitions and entry points

- `PrescribedPlateMotion`: named plate, parent frame and epoch, snapshot time,
  planar rigid or planet-centred Euler velocity, source and explicit units.
- `PlanarRegionalSection` / `SphericalRegionalSection`: an oriented section and
  its instantaneous reference-frame velocity in the same parent axes. Directions
  use the existing normalisation convention; geometry itself is not snapped.
- `RegionalMotionDefinition`: validated ownership snapshot, exactly one motion
  per plate, source, start time and positive interval in forward SI seconds.
- `RegionalReduction`: one of the two supported spatial reductions below and
  the explicit temporal rule `frozen-at-start` and positive `reference_width_m`
  defining the fixed transverse metric normalisation. There is no ignore flag or
  user-adjustable omitted-flow tolerance.

All authored fields are immutable and included in identity. `GeologySource`
retains authored/generated/synthetic distinctions; source kind is never inferred
from numerical values. Motion descriptions contain no query-grid samples or RNG.

```python
# definition, section and reduction are explicitly constructed typed inputs.
with PreparedRegionalForcing(definition, section, reduction, budget=budget) as plan:
    samples = plan.project(
        offsets_m, frame_id=section.frame_id,
        epoch_id=definition.epoch_id, time_s=definition.start_time_s,
    )
    forcing = plan.faces(
        grid, frame_id=section.frame_id, epoch_id=definition.epoch_id,
        start_time_s=definition.start_time_s, duration_s=definition.duration_s,
    )
    forcing.validate_boundaries(left=left, right=right)
    # forcing.face_velocity_m_s has exactly grid.cells + 1 values.
    # No material is initialised or advanced by this call.
```

All velocity/rate/length units are explicit `m/s`, `rad/s`, `m`; time is `s`.
Unspecified years, cm/year, angular degrees or cross-epoch/frame guesses are
refused. Use the existing TimeAxis/EpochOffset/frame conversions before making
a prescription, with their provenance recorded in the supplied source. Section
coordinates `s` increase from the declared origin; RegionalGrid1D.origin_m is an
offset along this section, not an unrelated global Cartesian coordinate.

## Reduction, reference frames and time

### Planar columns

For a plate, `v(r) = U + omega cross (r - pivot)`. The section frame velocity is
`V + Omega cross (r - section_origin)`. Tangent, left transverse and up axes form
the local basis. All absolute, reference and relative components are returned.

Solver-ready planar reduction requires `omega - Omega == 0` and relative
translation parallel to the section with zero relative vertical velocity. Thus
there is no cross-section or vertical flux anywhere in the affine field, not
merely at the selected faces. A co-rotating frame can meet this requirement;
an unmatched planar rotation cannot. A velocity that happens to project to zero
cross-flow at one query is not sufficient. The represented quantity is column
thickness/inventory per unit transverse measure on the transect, not a finite-width
average of arbitrary laterally varying geology.

### Spherical columns

The supported section is a strictly minor great-circle arc at reference radius R.
`r(s) = R (a cos(s/R) + t0 sin(s/R))`, `t0 = pole cross a`.
Along is the oriented great-circle tangent, cross-left is its pole, and up is
radial. The reference frame may rotate about the same sphere centre, but not
translate that centre. Solver-ready output requires the relative Euler vector
to be parallel to the section pole. Its material angular motion has no radial or
meridional component. The section speed is `ds/dt = R * relative_angular_rate`.
No Cartesian chord length is substituted for arc length.

The compatible regional conserved quantity is **volume-equivalent column
inventory divided by `(reference arc length * reference_width_m)`**, in metres.
It is NOT arbitrary raw radial layer thickness: a finite spherical layer has
radial/area metric factors. The width is an explicit fixed metric normalisation,
not permission to average an arbitrary nonuniform latitude strip. Stage 7 must
prepare a compatible material inventory using that declared metric; Stage 6
creates no material data. No
spherical finite-volume dynamics capability is implied by providing these speeds.

### Bounds and temporal interpretation

The spatial test is conservative: every plate in the supplied topology must meet
the reduction, even an unqueried plate. For local work, supply an independently
validated regional topology crop; do not hide an incompatible owner by using a
coarse query grid. Directional zero tests use a fixed 64-binary64-epsilon bound
scaled by the products in the dot/cross calculation. This accommodates only
round-off in rotated directions, not an absolute physical m/s allowance. Tiny
unrepresented transverse velocities are still refused. Returned residual
components are not clipped or replaced by zero.

`frozen-at-start` explicitly holds the start-epoch spatial prescription and
ownership in section coordinates for exactly the requested positive interval.
This is the existing regional fixed-forcing time approximation, **not exact
finite Euler rotation, moving ownership geometry or automatic frame integration**.
Changing the interval, source, motion or topology requires another prescription.
No timestep is shortened, no future flow is extrapolated, and no temporal error
bound is inferred from a kinematic snapshot. General time-dependent forcing and
moving-grid evolution are unsupported here.

## Ownership, boundaries and refusal

`project` preserves all inclusive index hits and all owner-specific components.
`selected_rows == -1` indicates different plate owners without an explicit region
selection. Same-plate seams retain their region rows but have one plate motion.
Spherical membership inherits the established index's tiny boundary-predicate
band; all reported owners are retained. No nearest-owner fallback, geometry
snapping or velocity averaging is performed.

`faces` requires whole-section domain coverage, not just successful point queries.
A shared face can have one velocity when every sided along-component is exactly
equal, while retaining its multiple owner rows. A genuinely discontinuous
**interior** face is refused even if a caller selects one side: a contact/flux law
is missing. Full-section interplate seam intersections are prepared independently
of grid faces: an interior discontinuity between faces is also refused, including
a thin plate hidden behind identical endpoint velocities. The guard applies to
the requested grid crop, so a crop wholly within a compatible plate remains usable.
Network intersections use their existing domain chart. Atlas intersections use
finite great-circle arcs, stable short-edge normals and conservative angular
bounds; an ill-conditioned, nearly coincident pair of arc planes refuses output
rather than silently declaring no intersection. Exactly coplanar overlap is checked.
A discontinuous **external** endpoint can use an explicit region only
when that region covers the full adjacent section cell. This side validation is
supported on planar/conditioned spherical BoundaryNetworks. For a multi-chart
atlas discontinuous endpoint, a separately verified regional crop is required.

Nonzero external velocities are never zeroed for a closed boundary. The existing
regional validator refuses them; incoming material remains missing until the
caller supplies an explicit TransportBoundary reservoir. Neither the adapter nor
its renderer invents exterior thickness, density or material. A velocity array
alone does not authorise a Stage-7 geological evolution.

General relative planar rotation, frame tilt, transverse/vertical flow, nonaxial
Euler reductions, small-circle sections, sphere translation, arbitrary 3-D
sections, ambiguous discontinuous fluxes, unresolvable coordinate spacing and
wrong/missing units or epochs are explicitly refused for solver-ready output.
Projection remains available for supported diagnostic geometries with nonzero
residual components, but is not marked solver-ready.

## Reuse, ownership and restoration

The prepared object holds fixed immutable basis/affine transforms and region-to-
plate lookups, plus the existing spatial index. Independent velocity calculations
and face grouping are vectorised in bounded batches. `backend='reference'` uses
clear scalar arithmetic for the same complete query/index/validation path. It is
an equivalence/performance control, not an approximate fallback. No global
scheduler, mutable query history or new cache service is added.

Every request owns scratch, checks cancellation and verifies the current source
before and after work. Close refuses active readers; results own read-only byte-
backed arrays. WorkBudget bounds admitted storage, not total interpreter/GEOS RSS.
Captured output arrays become caller-owned after the temporary query reservation
closes. Limits and batch size control resource use, not physical tolerances.

`save_regional_forcing` writes the existing self-contained topology and one atomic
forcing snapshot to ArrayStore, using its established chunk checks/dedup/cache.
Identity binds the executable source/runtime, topology, full motion/source,
frame/epoch, interval, section geometry, reduction, ownership selection, query
grid and backend. `load_regional_forcing` reconstructs typed inputs, re-evaluates
the saved bounded kinematics and requires exact metadata, identity and array
agreement. Changed policy/source or missing/corrupt data is refused rather than
rebound. This is data restoration, not a dynamics restart or finite-time advance.

## Focused checks and compatibility witness

Run only the Stage-6 and affected selected tests documented in the review packet.
The new file is `tectonics/tests/test_w01_regional_forcing.py`. It contains
independent translation/rotation/frame/covariance controls, planar/spherical seams,
unit/epoch/refusal tests, grid/order reproducibility, unchanged geological
features, memory/cancellation/source checks and fresh-process restoration.

A direct synthetic witness supplies u=1 on all four faces of a three-cell grid,
cell width 1, dt=0.25, H=[1,2,3], and left incoming H=4. Existing upwind transport
returns H=[1.75,1.75,2.75], inflow 1 and outflow 0.75, in both reference and Numba
backends. This witness is not automatic Stage-7 initialisation, scientific
validation of a plate history or an R4.4 simulation.

## Local integration review and timing — 22 September 2026

Only the second chat candidate (`PreparedRegionalForcing`) was reviewed and
integrated. The first candidate was withdrawn, not layered underneath it. Parent
review found that the original face-only interface check accepted a coarse grid
which hid a discontinuity; the continuous-section guard above closes that gap.
Six focused regressions cover coarse/narrow plate interfaces, conditioned and
global spherical sections, coplanar ambiguity and a short rotated seam. Existing
atlas sum/difference normals and half-angle distances avoid cancellation there.
These changes are AI-assisted implementation work, not independent validation
of the selected geological model.

**200 distinct focused tests passed, no failures, errors or skips:** 50 Stage-6
tests in 24.419303 s; 150 selected dependency/Stage-5 checks in 10.497688 s. The
dependency checks preceded the final local arc-normal refinement; that change
was covered by the final 50-test Stage-6 run. The initial uncorrected 44-test
candidate also passed, demonstrating why those tests alone did not catch the gap.
No full Atlas suite, long simulation, Stage-7 run or R4.4 acceptance was attempted.

Reproduce the focused set from the repository root in PowerShell (configured
Python with the existing tectonics dependencies; no installation required):

```powershell
$env:PYTHONPATH="$PWD/tectonics/src;$PWD/tectonics/tests"
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMBA_NUM_THREADS='1'
python -B -m unittest test_w01_regional_forcing test_w01_coordinates.LocalFrameTests test_w01_coordinates.TimeTests test_foundations.RotationTests test_w01_boundaries.SharedPlanarTests test_w01_boundaries.SharedSphericalTests test_w01_spherical_atlas.AtlasQueries test_regional_transport.RegionalDefinitionTests test_regional_transport.RegionalMathematicsTests test_w01_initial_sampling.RegionalInitialSampling
```

The included benchmark compares the scalar and vectorised complete `faces()`
paths in this same implementation. It has eight ownership strips, 4,095 cells /
4,096 faces, 512-row velocity batches and a co-rotating frame. The corrected
fixture gives every plate the same admissible translation: unequal strip speeds
from the submitted benchmark would hide unsupported internal interfaces. Hence
the submitted 51.8% Linux result is not adopted as local integration evidence.

Five alternating pairs on Windows/CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
Shapely 2.1.2 and Numba 0.65.1, with one native numerical thread:

| Complete prepared query | Median seconds | Observed range seconds |
|---|---:|---:|
| Scalar arithmetic reference | 0.114567900 | 0.108651100–0.122100900 |
| Default vectorised arithmetic | 0.083489400 | 0.081923900–0.085701300 |

**0.031078500 s saved per query; 27.1267% less time (1.3722x).** Ranges did
not overlap. Every published numerical array matched exactly in all five pairs;
independent velocity and ownership expectations passed. Backend-bound IDs remain
different by design. Raw pairs, scalar/vectorised seconds respectively:
0.108651100/0.083489400, 0.111673700/0.083402800,
0.114567900/0.085424200, 0.122100900/0.085701300,
0.121746900/0.081923900.

Definition/geometry setup was 0.006441400 s and prepared-plan setup 0.173405900 s,
separate from queries. First scalar/vectorised calls were 0.113010500/0.082699100 s;
this adapter has no JIT. Peak admitted storage was 39,795,149 bytes and all
reservations were released; that is not measured process RSS. No earlier
production Stage-6 adapter exists for comparison. These are bounded adapter
savings, **not whole-generator or R4.4 speed-ups**.

```text
python -I -B tectonics/tools/benchmark_w01_forcing.py --source . --output FRESH_RESULT.json
```

Use a fresh result path. The driver records raw timings, runtime/source identities,
setup, array equivalence and resource accounting; it does not run a simulation.
