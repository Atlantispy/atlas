# W05 combined acceptance — prescribed dry regional extension

WORKING NON-CANON. This gate covers the assembled, bounded W05 mechanism, not
general tectonic evolution or empirical landscape calibration. The fresh result
is recorded in [acceptance evidence](../evidence/w05-acceptance.md); a plan or
successful component check is not itself a passing combined result.

## Exact scope and reproduction

The frozen [motion case](../cases/w05_motion.json) and [support case](../cases/w05_support.json)
retain their original bytes and thresholds. The calculation is a 400 km long,
strike-invariant dry section with 1 km prescribed horizontal displacement, not
a finite-width map or a planet. Output crop is -40 to 80 km. The four requested
displacements are 0, 250, 500 and 1000 m. Grid spacings are 500, 250 and 125 m;
the time-partition and enlarged-domain comparisons use 250 m.

```text
python -I -B tectonics/verify.py --w05
```

Use the existing declared scientific dependencies; no installation, source
repinning or long R4.4 run is implied. Set numerical thread counts explicitly
when measuring elapsed time. This selection runs only the named W05 gates,
including its separate existing ALE dilation control. Invalid names, skipped
checks, empty selections, errors and source changes cannot produce PASS.

## Acceptance coverage

| Gate | Combined evidence |
| --- | --- |
| Cohorts, accounting and geometry | Independent cell integrals and finite-domain exports, nonnegative partial thickness, fixed footwall and unchanged cohort formation histories. |
| Component isolation | Zero motion/load; motion-only geometry, independently invoked same-load support and assembled z = z_kin - w; repeated outputs cannot accumulate movement. |
| Full-crop accuracy | All crop centres/faces at all requested outputs on all three grids, not sparse probes. Finest H max <=10 m and relative L1 <=0.005; smooth-load w max <=1 m with reference uncertainty <=0.01 m. |
| Basin and shoulder | Independently averaged cell-mean basin minimum and footwall maximum; amplitude compared with the 1 m support target and locations within one finest cell, 125 m. No imposed forebulge sign. |
| Grid, output partition and domain | Decreasing smooth-load error; 32/64/128 motion partitions, final 64/128 surface change <=1 m; enlarged source-domain crop change <=0.01 m. Characteristic evolution has no hidden CFL substeps. |
| Validity | Original dry displacement, plate-slope, bending-strain and exterior-error limits, with continuous bounds rather than only sampled maxima. Fault dip is not plate slope. |
| Recovery and resources | Existing exact restart/cold-warm equality, source/definition refusal, corruption, interrupted publication and bounded allocation checks. |

The independent reference integrates the smooth load, whereas production uses
cell-mean loads. Their difference is a measured discretisation error, not a reason
to alter either reference or tolerance. The same-cell-load operator checks remain
separate. Shared reference coordinates on the nested grids are evaluated once;
equivalently averaged extrema use bounded candidate selection instead of nested
quadrature in every cell. Numerical quadrature error estimates are not rigorous
interval-arithmetic certificates.

Only test/profile machinery is added for this gate. Production physical equations
and the Step 4 workflow are unchanged. The previous matched workflow timing can
be reused only while its bound code, case, environment and configuration remain
compatible; adding a test file is not a reason to rerun that benchmark. The final
acceptance record hashes its own tests, verifier and current sources separately.

## Meaning of a passing result

`PASS_SUPPORTED_DRY_LISTRIC_1D_W05` accepts the numerical assembly of the stated
prescribed mechanism, including conservation, finite-region response, independent
accuracy and recoverability. It does not turn prescribed fault geometry into a
stress-predicted fault, claim a finite globally closed mantle reservoir, validate
an arbitrary terrain shape, or change another stage's acceptance/holds.

The support remains a total change from the initial reference, applied only to
derived surface/base/fault elevations. Material stays in its unflexed transport
frame. The local-isostatic check and the finite-rigidity synthetic basin are
different controls; neither amplitude is substituted for the other.

## Separate empirical challenge plan

This is deliberately separate from the frozen synthetic acceptance, as specified
in Step 1. No field observations or numerical uncertainty are fabricated here.

For the first kinematic challenge, the candidate source is Ellis and McClay
(1988), *Listric extensional fault systems — results of analogue model experiments*,
[publisher page](https://www.earthdoc.org/content/journals/10.1111/j.1365-2117.1988.tb00005.x).
Its abstract describes simple and ramp/flat detachments and different material
layering. Select a simple, homogeneous-sand, rigid-footwall extension case rather
than an inversion, layered-rheology or ramp/flat case that the present closure
does not represent. Only the publisher abstract was accessible in this step:
the exact experiment/figure, imposed displacement, original scales and measurement
uncertainty still require full-source extraction before this becomes an executable
physical benchmark. It is a candidate, not a calibrated input dataset.

Freeze fault geometry, imposed heave and initial section from that source before
inspecting model residuals. Fit an exponential to the independently measured
fault only if its residual fits the source's stated uncertainty; otherwise declare
the case outside this geometry's scope. Do not fit both the fault and the output
rollover. Compare normalised rollover profile, conserved section area and any
open-boundary export with predeclared digitisation/measurement uncertainty. Track
secondary faults and depth-dependent strain as model discrepancies, not features
to disguise with smoothing or clipping. The toy parcel projection supplies a
comparison reference; mixed cohort totals do not acquire invented bedding order.

Test flexure separately using independent load, density, effective-rigidity and
displacement constraints. A rigid sandbox base does not measure elastic-plate
support. Do not borrow a fitted Te from the same topographic profile and then
claim that profile independently validates Te. Until suitable data are bound,
`field_validated` remains false; no empirical score or pass threshold is inferred.

## Papers and existing software checked for this step

- [Landlab ListricKinematicExtender tutorial](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html),
  theory and Example 5: confirms the separation of transported hanging wall,
  stationary footwall and initial-reference flexural response. Documentation read;
  Landlab was not installed or executed.
- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/):
  the model-description abstract was rechecked for independent imposed-load and
  boundary-condition scope. Full-text methods had already been checked for Step 3;
  no external gFlex run or new coefficients are claimed here.
- Ellis and McClay (1988), publisher abstract above: candidate analogue design
  and reasons to keep kinematic versus flexural challenges separate. Full numerical
  experiment data were not obtained, so this is not an empirical comparison.
- Existing Atlas W05 tests, independent SciPy quadrature helpers, source-bound
  workflow and verification profiles were inspected and used directly. New
  implementation is acceptance machinery, not a replacement numerical solver.
