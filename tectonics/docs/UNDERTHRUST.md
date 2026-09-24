# Prescribed collision and underthrusting

Local implementation, 23 September 2026. WORKING NON-CANON.
Tectonics continuation Step 2; this supplements, not rewrites, the frozen
[W08 regime design](W08_REGIMES.md) and its case register.

## Implemented model

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
Connections to evolving mechanics and joined persistent histories are the next
tectonics steps, using the existing shared components without source relocation.

## API, bounds and efficient reuse

`UnderthrustInterface`, `UnderthrustParcel` and `UnderthrustInterval` define inputs.
`PreparedUnderthrust(...).evaluate(time_s)` returns immutable polygons, receiver
accounts, block displacements, work and gravitational changes. Its descriptor
retains source, cohort, frame, datum, epoch and execution identities.

Preparation flattens original geometry once and builds receiver indices. Changed
outputs evaluate directly from the reference, without timestep loops or cumulative
remapping. Parcels inside one affine domain avoid unnecessary intersections/unions.
Only the latest output is retained; exact repeat requests still verify live code.
Callers retaining older outputs must account for their own storage. Close releases
the prepared/latest reservations. There is no new persistent checkpoint codec in
this increment; the joined-history step owns that connection.

Bounds: shared-accounted 128 MiB, 4,096 parcels, 256 intervals, 64 interface knots,
64 receivers and the existing geometry complexity limits. Nonfinite, unresolvable
and underflowing nonzero accounts refuse rather than disappear. The unchanged
128-file source limit now covers 120 production files. Live identity includes
the new defining classes and methods; existing source-bound evidence/checkpoints
are not silently rebound to changed code.

## Focused evidence and measured optimisation

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

## Papers and reference software inspected

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
