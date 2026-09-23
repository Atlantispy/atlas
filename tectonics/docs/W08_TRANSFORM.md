# W08 Step 3 — transform and oblique motion

WORKING NON-CANON. This is the full-vector horizontal kinematic increment from
the [frozen W08 design](W08_REGIMES.md), not an earthquake-cycle displacement
accumulated as geological deformation. The [challenge definition](../cases/w08_transform.json)
was written before candidate execution; the parent design and A02/A03 controls
remain unchanged.

Local implementation and bounded acceptance complete, 23 September 2026.

## Motion and material connections

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

## Efficiency and bounded execution

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

## Verification and measurement

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

## Software and papers checked

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
geodynamic packages were not installed or executed. Next: W08 Step 4, prescribed
subduction and computed wedge, beginning with its already-recorded source adapters.
