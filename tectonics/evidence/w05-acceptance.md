# W05 combined acceptance — 22 September 2026

**PASS_SUPPORTED_DRY_LISTRIC_1D_W05.** WORKING NON-CANON SYNTHETIC.
The prescribed dry listric-extension workflow passes its bounded numerical and
engineering gate. This is not field validation, general terrain acceptance or
completion of the held R4.4 campaign. No production physics or frozen tolerances
were changed for this acceptance increment.

## Reproduction and recorded run

From the Atlas root, using the declared scientific environment:

```text
python -I -B tectonics/verify.py --w05
```

Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1; numerical thread counts
were set to one. **37 tests passed in 31.807493 s**, no failures, errors or skips.
Source inventory before/after matched. The combined physical fixture took
16.509437 s, including 1.861759 s for the shared smooth point reference.
This turn did not execute Linux; source-portable tests are not a Linux run claim.
The [complete machine-readable record](w05-acceptance.json) contains selected
tests, source hashes, runtime identity and all per-grid/output metrics.

The frozen 400 km section, 120 km crop, four outputs and three grids are specified
in [the acceptance design](../docs/W05_COMBINED_ACCEPTANCE.md). Every crop cell
centre and face is checked, with 1,921 unique coordinates per output on the nested
grids and 5,763 nonzero smooth-load point evaluations. Zero output is analytical.

## Accuracy and consistency

Final 1 km prescribed displacement; support errors include estimated reference
uncertainty. Extrema compare equivalent cell averages, not means against points.

| Grid spacing | Maximum full-crop support error | Basin mean minimum | Footwall mean maximum |
| --- | --- | --- | --- |
| 500 m | 0.016259127 m | -739.188000 m | 180.678009 m |
| 250 m | 0.004065289 m | -751.422984 m | 181.432673 m |
| 125 m | 0.001016411 m | -757.620578 m | 181.804348 m |

Support error decreases by approximately fourfold for each spacing halving and
is below the original 1 m target at every output/grid. The fine-grid maximum is
**1.0164 mm**. This is numerical error against the stated smooth reference, not
real-world terrain accuracy. Maximum point-reference uncertainty is 1.353e-7 m,
below the original 0.01 m allowance; these are quadrature estimates, not interval
certificates. Independently integrated moving-layer means differ by at most
3.638e-12 m; maximum relative L1 difference is 9.165e-17.

Independent cell-mean basin/footwall extrema select the same locations as
production at every nonzero output/grid. At 125 m and final displacement their
amplitude differences including uncertainty are 0.7939 and 0.6570 mm. Coarser
cell-mean extrema are not interchangeable with finer means or continuum points.

All 32/64/128 motion partitions produce identical final surfaces. Enlarging the
source domain changes the crop by 6.599e-13 m; including both explicit exterior
bounds gives 3.354e-12 m, below the unchanged 0.01 m gate. The characteristic
solution needs no hidden time substeps; support is evaluated only at final output
for these partition controls.

Cohort and total inventories, finite signed export, formation history and the
stationary footwall pass independent accounting. The largest residual is 0.4636%
of the existing floating-point roundoff allowance, not 0.4636% mass loss. Same-load
standalone and assembled support match exactly. Zero motion/load, repeated
outputs, surface/base/fault identities and nonnegative material checks pass.

Continuous maximum bounds over all cases remain within the unchanged limits:

| Quantity | Largest bound | Limit |
| --- | --- | --- |
| Support displacement | 218.379417 m | 1,000 m |
| Plate slope | 0.008385350 | 0.1 |
| Bending strain | 0.002130729 | 0.01 |

The separate local-isostatic control gives 951.625820 m unflexed drop and
144.185730 m net subsidence, agreeing with the direct density-fraction identity.
This is not the finite-rigidity basin prediction in the table.

## Recovery, resources and efficiency

Selected existing tests cover exact cold/warm/restart outputs, interrupted
publication, corrupt or incompatible records, source/definition guards and
resource refusals. The combined fixture's explicit work budget peaks at
34,322,688 bytes of 134,217,728 available, with zero reservations remaining and
no refusals. This is accounted work memory, not measured process RSS.

Independent references are shared across nested grids; a conservative curvature
bound identifies all possible cell-mean extremum candidates before expensive
quadrature. The fixture runs once and its metrics feed the verification record
directly. No measured before/after timing is claimed for this new test machinery.

All bound production/tool/case hashes in the existing [Step 4 timing](w05-workflow-timing.json)
still matched, so that benchmark was reused rather than rerun. Its local
setup-inclusive no-store/warm medians remain 0.767235100/0.365163300 s:
**0.402071800 s / 52.4053% saved**. First durable execution costs 0.857438100 s
(11.7569% extra); compact encoded payload saves 39.9702%. These are the recorded
bounded-case measurements, not a fresh Step 5 speedup or whole-generator estimate.

Required static checks also passed: 13 maps/41 paths; 30 coding-safety tests
passed with one Windows symlink skip (31 reported, 0.104 s). That platform skip
belongs to the separate static suite, not the 37-test W05 acceptance profile.

## Scope and sources

This completes W05's selected mechanism, conservative motion, support, recoverable
workflow and combined numerical acceptance, with the separate analogue challenge
plan documented. Fault motion is prescribed; the model remains dry, isothermal,
constant-density, planar 1D with uniform elastic rigidity and no geometry-to-motion
feedback. The empirical challenge is **pending independently bound analogue and
support data**; no observations or uncertainty bounds have been invented.

Checked for this increment: [Landlab's listric tutorial](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html)
theory and Example 5 (documentation); [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/)
model-description abstract (full methods previously checked in Step 3); and
[Ellis and McClay (1988)](https://www.earthdoc.org/content/journals/10.1111/j.1365-2117.1988.tb00005.x)
publisher abstract for the separate analogue design. Neither external simulator
was executed, and the analogue's full experimental data were not obtained.
Existing Atlas/SciPy independent-reference code was inspected and executed.
