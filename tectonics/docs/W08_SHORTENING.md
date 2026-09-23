# W08 Step 2 — finite shortening and load/support

Status: WORKING NON-CANON, local implementation, 23 September 2026.
The [Step 1 design](W08_REGIMES.md) and [case register](../cases/w08_regimes.json)
remain frozen. This increment implements their distributed plane-strain shortening
route; it does not manufacture fault or underthrust geometry from convergence.

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
invented for this distributed-shortening increment. Next: transform/oblique motion.

## Shared source-capture prerequisite

`reuse.py` now streams **all current package source bytes** through SHA256,
retaining canonical path/byte-count/digest records rather than duplicate raw text.
The explicit representation successor is `atlas.package-source-digests.v1`;
execution identity advances from v3 to `atlas.kernel-execution.v4`. Old checkpoint
identities refuse rather than being repinned. Loaded callable/default/constant
and runtime checks remain, including the two new shortening modules.

The 128-file membership limit stays fixed. The 2 MiB bound now applies to the
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
  [W04 finite regions](W04_FINITE_REGIONS.md). Independent reference evaluation
  reuses the existing scalar SciPy quadrature helper, not the production operator.
