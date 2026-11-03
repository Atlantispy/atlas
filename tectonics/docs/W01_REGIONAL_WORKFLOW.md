# W01 Stage 7: described geology to regional material evolution

22 September 2026. Local, unreleased implementation
This connects the supported S5/S6/W02 route, not whole-W01 scientific acceptance.
The subsequent [Stage-8 assessment](#stage-8-combined-acceptance) checks this
assembled route. Reopened S3C acceptance, unrestricted spherical dynamics and
R4.4 remain separate. No long simulation was run to implement this bridge.

## Public workflow

`PreparedRegionalWorkflow(initial, definition, section, reduction, grid, support)`
takes an `InitialConditionState`, the existing S6 motion records, a uniform
`RegionalGrid1D` and an explicit `RegionalColumnSupport`. It builds the cell
footprints, obtains S5 intersection inventories, constructs W02 material cohorts,
and prepares source-bound face velocities. Callers do not assemble numerical
inventory arrays. Sources, material definitions, formation times, cooling history,
unknown masks and the original geological description remain accessible through
`state.initial_samples.state`.

```python
with PreparedRegionalWorkflow(initial, motion, section, reduction, grid, support,
                              budget=budget) as plan:
    start = plan.initialise()
    end = plan.advance(start, left=left_boundary, right=right_boundary)
    save_regional_workflow(end, store, budget=budget)

restored = load_regional_workflow(store, end.workflow_id, budget=budget)
with PreparedRegionalWorkflow.from_state(restored, budget=budget) as plan:
    # Only if some of the ORIGINAL frozen forcing interval remains:
    continued = plan.advance(restored, left=left_boundary, right=right_boundary)
```

An omitted duration advances to the original S6 endpoint. A supplied positive
duration can cover a prefix. The unchanged W02 adviser determines substeps;
the default remains MUSCL/Numba, with no numerical fallback or interval extension.
Boundary reservoirs/composition must be explicit, including all required inflow.
Each accepted step retains its parent, cohort exchanges and numerical receipt.
`initialise()` always returns the original root, not the latest advanced state.

Run the complete authored example, from the repository root:

```text
python -I -B tectonics/tools/run_w01_workflow.py
python -I -B tectonics/tools/run_w01_workflow.py --benchmark --output s7-timing.json
```

The example uses two explicitly synthetic rocks, three geological strips and
32 solver cells. It verifies a 24 m3 initial inventory and evolves 0.025 seconds.
It installs/downloads nothing; `--output` refuses to overwrite existing evidence.

## Meaning of the conserved quantity

For cohort k and numerical cell i:

`q[k,i] = sum(actual S5 phase intersection volumes[k,i]) / (ds * reference_width)`.

Hence `sum(q * ds * reference_width)` is the retained volume. Stable grouping
with compensated summation preserves small mixed-fragment contributions. There
is no re-normalisation of authored fractions or implicit density/porosity law.
W02 calls q "partial thickness"; in the spherical route it is an equivalent
inventory per reference area, **not raw radial thickness**. W02 exchange receipts
are per unit reference width (m2); multiply by the declared width for m3.

Planar support is a straight strip centred on the declared section, of explicit
reference width and initial depth band. Its complete footprint must lie inside
the regional topology. Every intersecting owner must have compatible full
relative-motion coefficients, not merely the same projected speed at a centre.
S6's continuous-section discontinuity checks are still mandatory.

Spherical support is a complete north- or south-hemisphere longitude wedge about
the section's declared pole, bounded by great-circle meridians and the equator.
Axial relative Euler rotation preserves that transverse support. Surface area is
`R * ds`; shell volume is `ds/R * (r_outer^3-r_inner^3)/3`. S5 uses stable shell
arithmetic, not surface area times depth. For R=10 m, depths 0–2 m, width=10 m,
q=122/75 m, not 2 m. The two hemispheres are separate supported queries, not a
general finite-latitude strip or a two-dimensional spherical mechanics model.
Changed/unsupported owner motion anywhere inside a wedge is refused.

Explicit pore phases require `PoreFluidCohort(unit_id, cohort, source)` mappings.
Different units can share an explicitly identical fluid history or retain
different origins. No fluid age/origin is invented from a material name. Bulk
reference materials keep their declared intrinsic-pore uncertainty; this bridge
does not claim to resolve unknown true solid volume, heat or in-situ mass.

## Initial temperature is not evolved temperature

Initial profiles, source conditions, volume-weighted temperatures and validity/
known masks survive every step and restore. Their label remains **initial epoch,
not evolved heat or temperature**. No temperature advection, thermal density,
compaction, relative fluid motion or new W03 physics is implemented here. Carried
formation/cooling provenance must not be interpreted as a current thermal field.

## Reuse, restoration and bounds

One preparation is reused across consecutive steps or independent scenario
branches. Initial samples/forcing are shared immutable objects; history is a
linked sequence, not repeatedly copied into each new state. Persistent transport
reuse uses the existing `ArrayStore` and `CachePolicy`; no extra scheduler/cache
service, compression format or worker pool is added. Dependent time steps remain
sequential. Parallel workers would add overhead to the bounded example.

Snapshots save dependencies before their workflow nodes. Restoration checks
source/runtime, whole-footprint geometry and S5 plan binding, initial inventory,
every parent/time/velocity/policy binding and cohort balance receipt. It does not
re-sample geology or re-evolve the material. Existing integrity checks are not
proof against a hostile Python runtime or a substitute for scientific validation.
The new modules join the live-callable execution identity inventory. Changed
source requires a new run; historical runs are never automatically rebound.

The wrapper accepts at most 4,096 cells, 4,096 cohorts and 256 cumulative steps,
subject also to existing geometry/sampling, byte-budget and numerical limits.
These are finite engineering bounds, not a tested capacity claim. Plans admit
retained descriptions, topology, samples, velocities and execution state;
advances admit their candidate history. Returned snapshots transfer ownership to
the caller. `WorkBudget` is an allocation-admission estimate, not an RSS ceiling.
Cancellation is checked through preparation, aggregation and each substep.
Unrepresentable clocks/metrics, exhausted budgets, changed bindings, unsupported
interfaces, incomplete inflow and off-section movement are refusals, not silently
repaired outputs. A failed advance publishes no partial workflow result.

## Method references

The official [Geodynamic World Builder painting model](https://gwb.readthedocs.io/en/latest/user_manual/concepts/painting_in_the_world.html)
and [2D section documentation](https://gwb.readthedocs.io/en/latest/user_manual/basic_starter_tutorial/18_2D_models.html)
(manual 1.2.0-pre, accessed 22 September 2026) support separating source geometry,
feature precedence and numerical queries. Their point-query model is not proof
of conservative cell integration.
[ASPECT particle properties](https://aspect-documentation.readthedocs.io/en/latest/parameters/Particles.html)
(3.2.0-pre) distinguish initial composition/position/generation time from evolving
properties. [Kritsikis et al. (2017), sections 2, 3.4 and 4.3](https://gmd.copernicus.org/articles/10/425/2017/)
support intersection-based conservative spherical remapping and reuse of fixed
geometry. The shell-volume reduction above is derived for this restricted
workflow; that paper does not validate its physics. No external code/dependency
was copied or added.

Focused verification and measured timings are recorded in
[Stage-7 evidence](#obtained-stage-7-and-8-evidence-22-september-2026).

## Stage 8 combined acceptance

The 22 September 2026 assembled assessment is **PASS_SUPPORTED_WORKFLOW**, while
`whole_W01_status = INCOMPLETE` and `whole_W01_complete = false`. A successful exit
reports technical qualification of supplied geology and supported motion, not
generated geological realism. Reproduce its bounded selection with
`python -I -B tectonics/verify.py --w01`; `verify.py:W01_GATES` owns the selections
and `cases/w01_acceptance.json` the assumptions. The emitted record retains every
test, elapsed time, source hashes before/after and runtime. Failed, skipped,
empty or drifting selections cannot pass; no unrelated convection campaign runs.

The gates cover rigid/rotation/frame/epoch/pole/seam representation; shared and
reversed traces; initial thermal limits; actual mixed-cell volumes, refinement,
unknown masks and whole-fragment validity; continuous sections and complete
footprints; original frozen intervals, per-cohort conservation and exterior
accounts; and material identity independent of plate identity. A nonzero axial
transport case crosses 180 degrees and restores complete shell/reference-volume,
source, thermal and history records. Nonuniform MUSCL native/reference fields and
accounts meet unchanged material tolerances; the independent upwind witness does
not replace the default.

Cache invalidation covers changed boundary/interval/metric/geology/code. A fresh
process restores and continues; interruption after a cached substep preserves the
accepted checkpoint, without pretending a pure cache entry is an accepted state.
Assembly found preparation leases ending while their outputs remained live: staged
reservations now persist until prepared ownership takes over and release on
failure/cancellation. Handover briefly admits both scopes conservatively without
lifetime double charging. Restore enforces the existing 4,096-cell bound before
geometry allocation. `WorkBudget` remains admission accounting, not an RSS cap.

No physical kernel, material policy, tolerance, transport default or 256-step
ceiling changed. Source changes received new identities; old runs were not
rebound. All 5,819 PB2002 rows already had source/Euler consistency checks;
bounded scale-matched shape measurements describe differences rather than prove
generated dynamics. Generated plate realism remains **REOPENED**; R4.4 is held/
incomplete. R5–R9 include unimplemented process/spherical-generation capabilities,
not failed S5–S7 tests. Unrestricted spherical mechanics, W03 evolved heat/
compaction, unsupported interfaces and whole-world performance remain outside
this assessment. R4.4 is not needed to use the supported described-state route.

[Stage-8 results](#obtained-stage-7-and-8-evidence-22-september-2026) and
[bounded shape validation](#bounded-shape-validation-and-limits) retain their
original identities. The [complete original assessment](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/docs/W01_COMBINED_ACCEPTANCE.md)
retains the exact gate table and repair chronology. No new timing comparison or
multi-day simulation was made; Stage-7 timing remains bound to its own workload.

## Obtained Stage 7 and 8 evidence, 22 September 2026

Stage 7, added locally to `c8b876c92b95ad8d4bc3d3fda8b8f94de6f1b84e`, passed 38
focused Windows tests: 22 workflow in 44.798 s and sixteen geometry/shared identity
in 5.086 s. Mixed inventories, explicit fluid history, complete-cell/hidden-interface
refusals, both hemisphere shell volumes, original intervals, cumulative step budgets,
initial-temperature unknowns, cancellation/budgets and immutable outputs were covered.
Warm cache hit called no transport kernel; restoration called no S5 sampler.
Rehashed snapshots with altered support or foreign velocity histories refused.
Review repaired missing live-code registration, incomplete restore geometry/
velocity/accounts, retained-description admission and inventory-loop cancellation.
The failing live-code regression and pre-correction eighteen-test result remain
history, not added to the final count.

Three matched alternating pairs of four independent branches on the same 32-cell,
two-cohort, 0.025 s fixture measured setup reuse, with candidate setup included
and complete workflow/parent/receipt identities equal. Fresh median
3.346319300 s → shared 1.194844900 s saved 2.151474400 s (64.293757%). Shared
peak admitted estimate was 6,041,795 bytes, not RSS, and released to zero. First
native advance (3.885875400 s), authored setup and first plan were excluded equally
and recorded separately: this is **not cold one-off saving**. The final successful
comparison excluded concurrent tests. An overlapping development measurement and
a later denied output-file write were not used as timing evidence. Entry:
`python -I -B tectonics/tools/run_w01_workflow.py --benchmark --output NEW.json`.

Stage 8's `verify.py --w01` passed **71 tests in 54.571858800 s** with no failures,
errors/skips and identical before/after inventory. Counts: twenty representation/
thermal, four initial inventories, 29 workflow/geometry/recovery, six new assembled,
nine shared identity and three status. The separate development six-test run is
not added. Its axial wedge witness has R=10 m, 0–2 m shell, width 10 m,
volume 244π/3 m³ and q=122/75 m; two-cell 0.1 m/s transport for 0.25 s with inlet
2q gives `[q*(1+0.01/pi),q]` and q/4 m³ inflow. Nonuniform MUSCL compares actual
reference/native fields/accounts without demanding backend IDs coincide. Changed
inlet/interval/width cannot hit the wrong cache; cancelled cached substeps do not
masquerade as accepted workflow state. Preparation leases and restore's 4,096-cell
guard were repaired as described above, without changing kernels/gates/ceilings.

Both used Windows/Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Shapely 2.1.2,
Numba 0.65.1 and one numerical thread. The
[original Stage-7](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w01-stage7-workflow.md)
and [Stage-8 reports](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w01-stage8-acceptance.md)
retain exact commands/test IDs/source/runtime/output identities and static results.
No full suite, release, source repin, new physical law or whole-world/R4.4 campaign
is established by those technical passes.

## Bounded shape validation and limits

The later wording/driver change reused unchanged 71-test package results and
reran only the three affected status methods, not 74 distinct checks. Fixed
seeds 41/42/43, twelve area-ranked plates and 512 supports were measured without
fitting, seed selection, raised resolution or tolerance change. All 36 outlines
matched two independent spherical-area formulae/patch sums: maximum discrepancy
1.5543122344752192e−15 sr, closure 1.7763568394002505e−15 sr, versus the unchanged
2e−11 sr bound. Area L1 errors 0.00826755/0.00918161/0.00710941 were below 0.04.
A declared 52-plate/1,024-support case **refused** unresolved small plates without
a generated result. Total driver 7.116067 s and 96,041,175-byte admission estimate
are validation cost, not speed/RSS. Its deadline was cooperative 120 s/case.

Matched 100/250/500 km sampling and two phases yielded 72 paired records/scale,
not independent Earth observations. Candidate mean compactness differed
−7.6593%/−12.2353%/−14.5058%; inward-turning differences changed sign with scale.
These are descriptive mismatches, **not accuracy percentages or new thresholds**.
Largest-twelve area renormalisation was 1.0736633528442074; ~1,753–2,175 km
segments and 2–3 poorly resolved small ranks cannot acquire 100 km detail through
resampling. All records, including poor resolution, remain. Higher-resolution
behaviour is not inferred. Withheld PS is a within-PB2002 diagnostic; restricted
MS/ON/Peru geometry was not used.

All 5,819 prescribed-motion rows, including 766 withheld rows, already passed
source-derived position/normal/pole rounding checks; maximum raw component
differences 4.77449/1.94575 mm/a are not judged by the old twelve-row 0.2 mm/a
excerpt allowance. That verifies Euler reconstruction, not force-derived history
or generated realism. Whole-W01 realism stays REOPENED/incomplete; R5–R9 contain
unimplemented science, not failed tests of this described-state bridge. Entry:
`python -I -B tectonics/tools/measure_w01_plate_shapes.py`.

## Historical physical/reference corrections and bounded outcomes

The [complete bounded-validation report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w01-bounded-validation.md)
retains every original measurement, identity, source review, refusal and correction
below. These additional reduced-model results do not make W01 or R4.4 complete.

Tosi/ASPECT review supported warm-upward sign and an independent continuum
constant-viscosity velocity/pressure/work oracle. Case-5a Phi/Ra became an explicit
**derived project interpretation**, retaining printed values/labels and
`author_confirmed:false`; no author erratum was obtained. ASPECT integrates raw
dissipation/work separately then scales the former for comparison. Periodic
dissipation extrema were wired into the analyser without a second division.
The initial universal ten-contributor rule was superseded: cases1–5a retain ten,
case5b uses nine documented same-equation codes. Empty/missing/replaced/nonfinite
reference rows and changed mappings fail closed. No mature Atlas output selected
the interpretation, and no acceptance tolerance was widened.

Earlier supplement retrieval failure was resolved when Michael supplied the
30-page S1 PDF, SHA-256
817c1ebe44a5f9be45aa716416137e1f9a9d39c5840cac60e5540dba6ac09842.
Tables S14–S23/pages21–30 were extracted with pdfplumber and independently
cross-checked with pypdf; introduction/table pages were rendered/inspected.
Ten tables/626 printed min-max pairs preserve decimal strings, nulls, yield/grid
coordinates and upright-steady versus italic-periodic regime. Unequal printed
numbers do not establish periodicity (GAIA 100×100/yield3.8 is a retained steady
counterexample); code disagreements are not pooled. MC3D data remain excluded
from same-equation comparison, and ELEFANT rows are not invented. Select each
code's finest published exact-yield column with no missing-grid fallback;
SOURCE_ABSENT is not zero. Independent Atlas mesh/time/nonlinear/regime studies
and ten-complete-cycle minimum/maximum averaging remain required, with the original
0.5% envelope margin. Runtime needs only bound 25,270-byte JSON/stdlib, not PDFs.
The runner sibling-import seam was fixed and subprocess-tested. Final reference
verification passed 57 focused plus two four-step 4×4 driver checks; empty
preflight still reports INCOMPLETE_R4_4 rather than mature acceptance.

Windows raw export first gained explicit RAW_DATA_ONLY/NOT_RENDERED, preserving
actual fields/history and source/state metadata without plotting imports. Missing
plot dependencies refuse before run reading/output creation; mocked six-plot
calls were not a real render. The later Matplotlib3.11.2 installation preserved
existing solver versions/execution identity, and five real Agg checks produced
six decoded/hash-matched images plus exact raw-array parity. Three figures were
directly inspected for readable consistent axes/data. All images alone still do
not grant visual/scientific acceptance; suite visual acceptance requires raw plus
all six plots and actual inspection. Display is nearest-neighbour original arrays,
not one pixel/cell. Corrected-source Linux rendering remained unverified. Commands
are the existing visual_convection_r4_4.py with explicit new output, optionally
--raw-only; these historical installations supply no new install authority.

The later mechanical correction applies compatible MAC solenoidal reconstruction
only when constant-viscosity MINRES relative divergence exceeds four binary64 eps
(internal trigger, not relaxed acceptance). Cross modes retain circulation, axis
compressible modes are removed and p_new=p_old−Dv preserves momentum. Direct/
variable-viscosity solvers, genuine tiny-flow/compressible refusal and published
gates remain. Two old analytic tests expecting bit-exact normal MINRES values were
corrected to the actual two-ULP/four-eps independent oracle; subnormal/underflow
contracts did not loosen. Compaction/material transport separately introduced
cohort-partial-thickness-regional-v2, jointly limiting component slopes against
scalar total at both SSP-RK2 stages, with conservative per-component flux and no
post-update normalisation. Single-cohort/upwind and ALE/remap remain separate.
Workspace/compiled identity includes both stages and the new helper; old history
is not silently rebound.

Fresh predeclared three-case Windows controls then passed in 12.249925 s, including
compilation/I/O/plots/source checks but excluding imports/setup. Manufactured
variable-viscosity mechanics refined at ratios 4.005–4.164 within original 3.7–4.5;
work errors 0.970146/0.241899/0.060435%. Hydrostatic 20×10 km cooling with 80 K sine
perturbation reached 5e12 s on 16×8/32×16/64×32 grids: RMS 0.217176/0.0546381/
0.0136811 K, finest max 0.01932463 K, timestep difference 2.27374e−13 K, heat ledger
relative residual 4.06e−17. Conservative two-cohort transport closed 13/11 m³ within
1.78e−15 m³ and total thickness within 5.55e−16. Front mean errors decreased
0.164554/0.099247/0.059953 m (orders ~0.73), while maximum jump errors increased:
no discontinuous pointwise shape acceptance or misapplied smooth second-order gate.
Plots retain visible smearing. Twenty-one snapshots/raw fields/ledgers/manifest
were retained locally; lossless store 299,008 bytes restored final IDs, admitted
peak 75,992,824 bytes/final zero (not RSS). The unavailable earlier chat ZIP was
not authenticated or replayed. These analytic Windows controls do not establish
empirical geology, mature convection, terrain realism, Linux or whole-world scope.
