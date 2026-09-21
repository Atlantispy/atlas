# Current scoped package: 0.1.0.dev40

## Current dev40 candidate — thermal accuracy and benchmark assessment

The reviewed adaptive-inner optimisation is also available on NEW nonlinear runs
with `--adaptive-inner`, optionally combined with `--nonlinear-solver anderson
--nonlinear-start previous-stage1 --preconditioner-max-uses 4`. It relaxes only
intermediate linear solves, then requires fresh strict final certification.
The default remains unchanged. The bounded Windows dev40 comparison saved 26.06 ms
per prepared timestep (8.42%); this is not a full-campaign or whole-generator claim.
See [adaptive-inner review and measurements](evidence/r4-4-dev40-adaptive-inner.md).

The remake review repairs add append-only recovery of cancelled endpoint
diagnostics, cross-chart spherical-network stitching, represented-duration checks
for material transport, and translation-stable reference remapping. The retained
generator also verifies species source files on fresh execution and cached/resumed
acceptance. See [review-fix scope and verification](../docs/REMAKE_REVIEW_FIXES.md).

Fixed-temperature walls now inform bounded thermal advection reconstruction;
insulated walls, composition transport, conservation and Courant limits are
unchanged. Courant refusals report the failing RK stage, measured limit and an
advisory same-velocity timestep ceiling. SciPy is constrained to `<1.18`, matching
the authenticated FFT backend (1.18 changed it).

Periodic maturity must extend to the actual endpoint. Periodic mesh/time/nonlinear
studies now compare authenticated final-cycle temperature fields as well as scalars;
absent or undersampled fields are INCOMPLETE. The existing campaign tool's
`--preflight` reads configurations and known reference blockers without opening run
arrays. New schedules must include a uniformly sampled final endpoint; short
explicit diagnostic schedules remain allowed but warn when they cannot mature.

`tools/probe_convection_r4_4.py` isolates frozen-field resolution effects without
claiming coupled convergence. See revision 44 of the maintained documents and
[bounded evidence](evidence/r4-4-dev40-numerical-assessment.md).
**R4.4/R4 remain IN_PROGRESS.** No old checkpoint is rebound to changed source.
This is a local review candidate, not a published release or complete campaign.

## Current dev39 — guarded request-local preconditioner reuse

New nonlinear runs can select:

```text
--nonlinear-solver anderson --nonlinear-start previous-stage1 --preconditioner-max-uses 4
```

The equations and pressure approximation stay current. Only the approximate velocity
ILU can be reused, with age, viscosity-change and linear-work guards. Reuse stays
inside each nonlinear request; known strain-independent laws bypass it. Defaults
remain unchanged. Source and policy changes cannot silently resume old trajectories.
See revision 43 of the two maintained documents and `cases/preconditioner_reuse_r4_4.json`.
R4.4/R4 remain IN_PROGRESS; this is not mature convection acceptance.

## Current dev38 — explicit cross-timestep starting guesses

Use `--nonlinear-solver anderson --nonlinear-start previous-stage1` on a NEW run
to combine Anderson with the checkpoint-owned previous second-stage starting guess.
The existing Picard/zero-rate defaults and intra-step `rk-stage0` option are unchanged.
Initial stage 0 remains cold. All subsequent first stages use the exact seed saved
with the previous accepted step; both stages still solve their current equations.
Checkpoint, failure and identity contracts are in revision 42 of the two maintained
documents. Old-source runs are not silently migrated. R4.4/R4 remain IN_PROGRESS.

## Current — dev37 / plan revision 41

Safeguarded Anderson acceleration is now an explicit production solver option.
Picard remains the default. New benchmark runs opt in with
`--nonlinear-solver anderson`; `--nonlinear-start rk-stage0` independently selects
the existing intra-step guess. Mixing history is local to each request; restart
retains no hidden solver history. Physical equations and all convergence gates
are unchanged. R4.4/R4 remain IN_PROGRESS; this is not mature benchmark acceptance.

See the current headings of `docs/TECTONICS_PLAN.md` and
`docs/OPTIMISATION_REFERENCE.md`, and `cases/anderson_r4_4.json`.
Use the exact dev36 Sparse Structure baseline for the incremental patch, not the
separate same-version Sparse Layout build. Changed-source continuation is refused.


## Current dev36: exact sparse velocity-template reuse

Optimisation item 4 reuses only the viscosity-independent CSC sparsity and contribution
ordering of the variable-Stokes velocity block. Every matrix call still reads the current
cell/vertex viscosity, constructs fresh numerical data, and rebuilds the ILU whenever the
existing coefficient identity requires it. The explicit sparse-direct reference keeps the
predecessor SciPy assembly and does not use this template.

The retained template reproduces dev35 sparse-matrix values exactly on the tested grids and
matched physical fields remain byte-identical. It primarily reduces repeated nonlinear
assembly cost; initial 64/128-grid whole-step timings do not show a dependable gain. Read the
revision-40 headings of `docs/TECTONICS_PLAN.md` and `docs/OPTIMISATION_REFERENCE.md`.
R4.4/R4 remain IN_PROGRESS. Apply either the reviewed dev35-based patch or a complete merge,
never both; do not resume dev35 trajectories under changed dev36 source.

### Retained dev35 and earlier history

# Current scoped package: 0.1.0.dev35

## Current dev35: cheaper exact source verification

Optimisation item 3 avoids rebuilding discarded callable inventories during each
live verification. All current-source reads, membership checks, function/code
identity, mutable-default/constant/native-option checks and original verification
call sites remain. The physical solver and existing opt-in warm-start policy are
unchanged. Read the revision-39 headings of `docs/TECTONICS_PLAN.md` and
`docs/OPTIMISATION_REFERENCE.md`; lower "current" headings are retained release
history, not today's source authority. R4.4/R4 remain IN_PROGRESS. Use exactly one
dev34-based patch or a reviewed source merge; do not resume dev34 trajectories
under changed dev35 source.

### Retained dev34 and earlier history

## Previous dev34: explicit intra-step nonlinear guesses (opt-in)

The isolated second optimisation adds `nonlinear_start='rk-stage0'` to
`PreparedThermochemical2D` and `--nonlinear-start rk-stage0` to new R4.4 runner
invocations. The default remains cold `zero-rate`. Only stage 1 is initialised
from the current step's stage-0 solution; both stages still solve their own
unchanged equations and meet all existing convergence checks. No hidden
cross-step state, tolerance relaxation or automatic failure fallback is added.

Standalone current-source constant/Tosi solves may explicitly pass
`initial_guess=NonlinearStokesGuess(previous_solution)` to `solve_rheology`.
The immutable starting fields and provenance are stored with the result. Saved
physical states remain self-contained, and restarting with another source or
starting policy is refused. `mechanical_snapshot` remains cold and independent.

See the revision-38 sections of the two maintained documents and the new
`cases/nonlinear_start_r4_4.json` verification contract. This implements item 2,
not mature convection/mesh/time/nonlinear campaign acceptance; R4.4/R4 remain
IN_PROGRESS. Apply one dev33-based patch or a reviewed source merge, not both.

Dev33 compiles the existing variable-stress GMRES matrix-vector action without fast-math or disk JIT caching. NumPy residual checks and the explicit sparse-direct reference remain independent. See the revision-37 headings of `docs/TECTONICS_PLAN.md` and `docs/OPTIMISATION_REFERENCE.md`. This is the isolated mechanical-kernel optimisation, not nonlinear warm starts or R4.4 benchmark completion.

R4.4 published-case/diagnostic/trajectory/acceptance machinery is implemented and
the benchmark execution path has a measured solver optimisation pass, but **R4.4
and R4 remain IN_PROGRESS**. Mature published-case reproduction and the full
adequacy/campaign gates have not been demonstrated. The current authorities
are revision 37 of [the scientific plan](docs/TECTONICS_PLAN.md#3cr4-4-native-mechanics)
and [the execution reference](docs/OPTIMISATION_REFERENCE.md#3cr4-4-native-execution).
Read those current headings before retained historical status text below.
No R5, spherical dynamics or Earth/Diadem observational validation is claimed.
The release application instructions and evidence distinguish new final-source
verification from original dev30 results and incomplete attempts.

---

# Atlas tectonics remake

## Current remake delivery: R4.3 (`0.1.0.dev30`)

The variable-viscosity/yielding stress-divergence solver and its explicit two-stage
heat/composition coupling are delivered within the
[revision-34 scope](docs/TECTONICS_PLAN.md#3cr4-3-variable-mechanics).
**R4 is IN_PROGRESS. R4.4 full convection benchmarks and combined acceptance
remain outstanding.** This is not global plate dynamics or Diadem terrain.

`PreparedVariableStokes2D` uses the existing R3 profiles, native sparse/block
preconditioned GMRES, true nonlinear convergence and returned-SI diagnostics.
The small independently assembled direct reference is explicit, not a fallback.
Use `ThermochemicalProblem(..., mechanical_mode='variable-r4.3')` and optional
`nonlinear_policy=NonlinearStokesPolicy(...)` for constant/Tosi evolving coupling.
The historical default stays `constant-r4.2`; BF needs explicit frozen damage in
a separate snapshot and is not silently enabled in two-field evolution.

The [execution reference](docs/OPTIMISATION_REFERENCE.md#3cr4-3-execution) records
optimisation, limits, source-safe restart and the exact test/visual commands.
New evidence is in `evidence/3cr4-3-tests.json` and
`evidence/3cr4-3-measurements.json`; prior results are historical, not overwritten.
Actual-code visual QA uses `tools/visual_variable_stokes_r4_3.py`.


## Current R4.2 review — version 0.1.0.dev29

The constant-property thermal/binary evolution component now uses reference-
independent insulated diffusion, conditioned short-step exponentials and safe
source products. Published time intervals are checked against the integrated
duration before evolution; old snapshots decode unchanged without a source
rebind. Unused insulated time-average transforms are eliminated. See the
[scientific review](docs/TECTONICS_PLAN.md#3cr4-2-review) and
[execution review](docs/OPTIMISATION_REFERENCE.md#3cr4-2-review-execution).

**R4 remains in progress. R4.3 is next; R4.4 benchmarks/acceptance remain open.**
New results are in `evidence/3cr4-2-review-tests.json` and
`evidence/3cr4-2-review-measurements.json`. Earlier numerical cases, evidence and
third-party bytes remain unchanged. This is not a calibrated Earth/Diadem model.


## Current development: R4.2 delivered within scope; R4 remains in progress

**`0.1.0.dev28` / plan revision 32.** The reviewed mechanical core now drives
constant-property heat and binary-composition evolution in the closed uniform
2D Boussinesq box. Temperature and material fraction are actually advanced;
buoyancy velocity is solved at both transport RK stages. No first-order fallback,
field clipping or automatic timestep reduction is used.

The normal route uses a prepared discrete thermal exponential and fused native
MC/SSPRK2 face transport. Conductive boundary heat, internal/external heating,
constituent inventory and shared-face balances are checked on returned fields.
Same-source saved endpoints restore and continue exactly through the existing
lossless store. This is not yet a complete cohort-history/world adapter.

**Next: R4.3 variable-viscosity/yielding mechanics. R4.4 full benchmark/combined
acceptance remains outstanding.** R4 and W03/W07 are not declared complete.
See the [current numerical contract](docs/TECTONICS_PLAN.md#3cr4-2-thermochemical),
[execution reference](docs/OPTIMISATION_REFERENCE.md#3cr4-2-execution) and
[progress table](docs/TECTONICS_PLAN.md#3cr4-progress).

```sh
# Complete software regression, not a global simulation.
python -I -B tectonics/verify.py
# Finite component references and same-equation timing.
python -I -B tectonics/tests/check_thermochemical_r4_2.py
# Optional Matplotlib extra: real authored-start / evolved-endpoint comparison.
python -I -B tectonics/tools/visual_thermochemical_r4_2.py --output /path/to/new/r4-2-visuals
```

The visual example advances 40 explicit steps on a 48-by-48, 1,000-km box.
Initial fields are authored cell averages; final fields are solver results.
The separately plotted endpoint velocity is recomputed from that accepted endpoint,
not borrowed from an operator-split intermediate. No calibrated Earth/Diadem state,
full Tosi convection reproduction, spherical evolution or platform acceptance is
implied. The first mechanical example below remains useful as a steady control;
its historical limitations/next-step sentences describe R4.1, not current R4.2.


## Historical R4.1 development and retained mechanical example

**`0.1.0.dev27` / plan revision 31 — R4.1 mechanical core with reviewed SI publication.**
Atlas now solves steady velocity and dynamic pressure in a uniform 2D free-slip,
impermeable box. This is the first component of R4, **not completion of R4**.
The next increment is **R4.2: heat evolution and conservative composition transport**;
variable viscosity/yielding and applicable full convection benchmarks follow.
See the [maintained progress table](docs/TECTONICS_PLAN.md#3cr4-progress).

The [R4.1 review correction](docs/TECTONICS_PLAN.md#3cr4-1-publication-review)
checks residuals against the actual returned SI fields, not only the internal
normalised solution. It prevents unit-scale distortion and refuses inadequate
subnormal output rounding without relaxing tolerances. The physical model,
solver/preconditioner and pending R4 increments are unchanged.


The ordinary solver is matrix-free preconditioned MINRES with a separable native
velocity inverse; a small explicit sparse direct solve is retained for comparison.
Inputs use a named Cartesian x-right/z-up frame, R3 constant rheology and explicit
SI scales. Inward-depth R2 data are not silently renamed. No temperature evolution,
plate motion, variable law or terrain is invented by a steady mechanical solve.

```python
import numpy as np
from atlas_tectonics import (
    StokesBox2D, DiffusiveScales, reference_rheology, PreparedStokes2D,
)
box = StokesBox2D(32, 32, 1.0, 1.0, "analytical-x-right-z-up")
scales = DiffusiveScales("declared-unit-SI", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
# Uniform downward body force: a hydrostatic pressure response, no circulation.
fx = np.zeros((box.nz, box.nx - 1))
fz = np.full((box.nz - 1, box.nx), -1.0)
with PreparedStokes2D(box, reference_rheology("constant"), scales) as plan:
    result = plan.solve(fx, fz, frame_id=box.frame_id,
                        epoch_id="analytical-steady", time_s=0.0,
                        source="Authored hydrostatic verification case")
pressure_pa = result.array("pressure_pa")
```

In the separately documented tectonics environment, run
`python -I -B tectonics/tests/check_stokes_r4_1.py` for bounded numerical/timing
evidence and `python -I -B tectonics/tools/visual_stokes_r4_1.py --output /new/path`
for actual solved velocity/pressure, residuals, and the separately labelled
**authored** temperature input. The visual tool requires the optional visual extra.
Use new output paths; raw numerical fields and provenance are retained.

Older dated sections below describe their delivery-time state. The latest plan
and current progress table take precedence; previous evidence remains unchanged.

**Branch: `remake`. WORKING NON-CANON. Mathematical verification, not accepted terrain.**
Vibe-coded with OpenAI ChatGPT/Codex under Michael's direction.

This isolated package follows the [tectonics plan](docs/TECTONICS_PLAN.md) and
[consolidated optimisation reference](docs/OPTIMISATION_REFERENCE.md). It imports
neither `engineering/work` nor `shared_generator`. Historical bindings, numerical
limits, checkpoints, `main` and the original Windows installation remain separate.


## Current R3 — version `0.1.0.dev25`, plan revision 29

The [R3 arithmetic correction](docs/TECTONICS_PLAN.md#3cr3-stress-hardening)
fixes premature underflow/overflow in stress and viscous heating without changing
the physical equations. Non-zero unrepresentable outputs now fail explicitly;
finite subnormals and exact zero-strain responses remain supported. The actual
review convention is to fix verified in-stage defects, test the result and supply
a Git changelog, rather than stop at reporting the issue. Historical source-bound
reports remain intact; fresh results are `evidence/3cr3-hardening-tests.json` and
`evidence/3cr3-hardening-measurements.json`.

The [R3 local physical closure](docs/TECTONICS_PLAN.md#3cr3-physical-closure) is
implemented: constant and Tosi benchmark rheology, one sourced BF2023 memory/
healing model with a damage-free control, explicit thermochemical force/heat
accounting, and a separately declared 1D fixed-length regularisation primitive.
**R4 is next and has not started.** A local viscosity or healing curve is not a
convection solution, localisation acceptance or geologically accepted world.
R1/R2 and their source restrictions remain unchanged. Historical delivery
paragraphs below describe their dated scope.

```python
from atlas_tectonics import PreparedRheology, reference_rheology

# Named dimensionless local reference; initial damage is deliberately supplied.
with PreparedRheology(reference_rheology("bf23-memory")) as law:
    response = law.evaluate(temperature=[0.0, 0.5, 1.0], depth=0.1,
                            strain_rate_ii=1.0, damage=0.0)
    memory = law.advance(damage=20.0, strain_rate_ii=0.0,
                         temperature=0.0, elapsed=1.0)
viscosity = response.array("viscosity")  # immutable result, not mantle calibration
healed_damage = memory.array("damage_after")
```

T and depth must be in [0,1]. SI input requires a named `DiffusiveScales` with
**separate diffusive length and depth normalisation**; outputs remain explicitly
scaled and retain that conversion record. Do not pass kelvin/metres as if they
were dimensionless. Pressure is not a hidden yield-law input. Numerical
viscosity bounds are optional, explicit and diagnosed, not measured strength.
The 1D length operator is an Atlas extension, not an unlabelled change to the
published model or evidence of mesh-independent coupled shear bands.

The normal evaluator uses native buffered serial operations; threaded evaluation
is available through the existing bounded execution policy. The finite measured
workloads did not justify threading by default. Full inputs, profile, outputs,
scales and source identity can be saved/restored with the existing lossless store.
See [execution and evidence](docs/OPTIMISATION_REFERENCE.md#3cr3-execution).

From the repository root in the declared environment, the new bounded checks are:

```sh
python -I -B tectonics/tests/check_constitutive_r3.py
python -I -B tectonics/tools/visual_r3.py --output r3-visuals
```

The second command needs the existing optional `visual` extra and a new output
directory. It renders actual local-law, healing, buoyancy and fixed-length curves
with their numerical data and source identities; inspection is a separate step.
Every implementation delivery includes a copy-ready Git changelog in its response.

## Historical cleanup — version `0.1.0.dev23`, plan revision 27

The R2 initial-state/sampling and optimisation scope is unchanged. This cleanup
fixes linked-interpreter portability, consolidates engineering methods, improves
delivery/evidence hygiene and corrects source-derived diagnostic plots. R1's
scoped acceptance and strict discrepancy failure remain separate. **R3 has not
started.** Older delivery paragraphs below are dated history, not current setup.

Atlas aims to investigate whether and how the Diadem's authored geography could
arise, not to make random worlds reproduce it. A failed explanation, unusual
explicit event or unresolved mechanism remains a legitimate result. No geography
is an answer key for tuning general physics. Visual QA uses actual code/data after
each meaningful stage; it is separate from numerical and physical acceptance.

<a id="environment"></a>

## Tectonics environment

Use a separate Python 3.12 or 3.13 environment for this package, **not** the old
source-only `tools/develop.py` environment. Dependencies and version ranges live
in `tectonics/pyproject.toml`; only Numba is exact-pinned there. A passing run must
record its actual versions, not claim all dependencies are pinned. The optional
`visual` extra supplies Matplotlib for the diagnostic tool, not the physical core.
The commands below install dependencies only when you explicitly run them.

From the repository root on Linux/macOS:

```sh
python3.13 -m venv tectonics/.venv
tectonics/.venv/bin/python -m pip install -e 'tectonics[visual]'
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  tectonics/.venv/bin/python -I -B tectonics/verify.py > fresh-tests.json
```

From the repository root in Windows PowerShell:

```powershell
py -3.13 -m venv tectonics\.venv
& .\tectonics\.venv\Scripts\python.exe -m pip install -e ".\tectonics[visual]"
$env:OPENBLAS_NUM_THREADS="1"; $env:OMP_NUM_THREADS="1"; $env:MKL_NUM_THREADS="1"
& .\tectonics\.venv\Scripts\python.exe -I -B .\tectonics\verify.py > fresh-tests.json
```

No activation or shell-policy change is necessary. Normal interpreter links and
copied interpreters are both supported; `--copies` is no longer required as an
Atlas workaround. Source/data/extension symlink guards remain. Use `-B` for local
source imports: the verifier intentionally refuses pre-existing local bytecode.
Do not delete an existing working tree to get a pass; investigate it or use a clean
copy. Do not use `--system-site-packages` for a fresh independent installation;
the cleanup test harness used it only to reuse already installed dependencies
without downloading/installing anything. Linux execution is verified by this
delivery; Windows/macOS instructions alone are not platform acceptance. Full verification
also exercises real filesystem symlinks; a host unable to create those fixtures
has not completed that part of verification. Skips are not counted as a full pass.

Primary environment reference: [Python's venv documentation](https://docs.python.org/3.13/library/venv.html).

## Reproducible diagnostic visuals

```sh
# Use the environment's Python as above. The destination must not already exist.
python -I -B tectonics/tools/visual_qa.py --output tectonics/visual_output/review
```

This runs the unchanged authored R2 example and a fixed seed-41 plate-layout
candidate, loads the existing pinned PB2002 bytes offline, and records identities
and provenance next to the PNGs. It adds no physics and changes no source data.
The source-data inventory is read/verified, not reacquired or requalified.
Formation ages come from sampled unit/cohort records; cooling age is separate.
PB2002 segment symbols mean left/right subduction or **non-subducting**, not a
blanket transform classification. Raw source curves remain separate and are not
converted into certified morphology. Rendering clips the antimeridian and globe
limbs; six globe views include both poles. Optional Matplotlib absence fails
clearly without affecting ordinary numerical use of Atlas.

A visual check records what was inspected and any problems; generating a PNG is
not automatic approval. No landform, velocity or thermal-evolution result is
implied. The two earlier chat plots with hard-coded ages and a wrong `-` legend
are withdrawn as evidence; the corrected plots supersede them.

## Delivery, evidence and licence

Merge a full snapshot into the named `remake` baseline without deleting unrelated
or newer files. Review the supplied change manifest (old/new hashes) and grouped
patches first. An update-only bundle must be explicitly labelled and must never
be run as a standalone package. Michael handles commits/pushes manually.
Routine new `.log` transcripts are ignored; structured JSON and unique diagnostic
evidence are retained. Already tracked historical logs and source records remain
unchanged. Optional visual PNGs stay in the ignored output directory by default.

**Atlas-owned code is licensed AGPL-3.0-only**, as selected by the owner on
19 September 2026. See [the complete licence](LICENSE) and
[project scope](../LICENSING.md). PB2002 and other third-party material retain
their existing licences; see [third-party notices](THIRD_PARTY_NOTICES.md). The
earlier unapplied Apache proposal is superseded, not an alternative grant.


## Current cleanup evidence

- [Linked-interpreter full suite](evidence/review-cleanup-linked-tests.json):
  1,512 tests, no failures, errors or skips.
- [Copied-interpreter full suite](evidence/review-cleanup-copied-tests.json):
  the same 1,512 tests, no failures, errors or skips.
- [Cleanup scope and preservation](evidence/review-cleanup.json) and
  [actual-code visual inspection](evidence/review-cleanup-visual-qa.json).

The environment reuses already available dependency installations; a fresh pip
installation, macOS and Windows execution were not performed. The tests are
implementation/numerical checks, not physical realism or release acceptance.

## Historical R2 implementation and execution delivery


**Version `0.1.0.dev22`, 18 September 2026. R3 is next; it has not started.**
R2 adds geological starting states **without requiring or producing final plate
labels**. It does not generate realistic plate shapes, solve mechanics or evolve
heat. R1's reviewed uses and deliberately failing strict consistency gate remain
unchanged. The two maintained plans and the new
[`precursor_r2.json`](cases/precursor_r2.json) govern the exact scope.

Revision 26 adds conservative spherical candidate indexing and connects the sampler
to the existing admitted executor. Large indexed point queries automatically use
bounded threads; small/unindexed queries and cell workloads remain serial where
threading was not beneficial in the registered comparisons. Threaded cells remain
an explicit tested route, not an unimplemented feature. Whole-request overlaps,
row/hit/work limits, binary64 accuracy, immutable results and cancellation/drain
semantics are preserved. See the current [execution contract](docs/OPTIMISATION_REFERENCE.md#3cr2-scaling-execution)
and [`precursor_r2_scaling.json`](cases/precursor_r2_scaling.json).


| Delivered interface | Meaning |
|---|---|
| `GeologicalDomain` and existing `GeologicalCase` | Plate-independent planar/spherical support with immutable sourced materials, formation cohorts, columns, provinces and inherited features. |
| `PrecursorState` | Explicit input origins, separate cooling histories, source-bound volume conventions, named priors, prescribed/unresolved scalar fields and bounded slab/mantle initial inputs. |
| `PreparedPrecursor.sample_points` | Indexed point material/temperature queries; retains all province matches and exact inherited weak-zone memberships. |
| `PreparedPrecursor.sample_cells` | Mixed polygon-prism or shell-sector initial inventories and supported mean temperatures; no centre-point substitution or hidden double counting. |
| `save/load_precursor_state`, `save/load_initial_samples` | Existing lossless, verified, deduplicated `ArrayStore` snapshots with actual geometry, library dependencies and source/history identities. |

The Earth-material catalogue is reused, not re-entered per cell. Numerical values
remain reference-condition knowledge, not hot/high-pressure laws. Bulk, matrix,
true solid, explicit pore and source-reference mass quantities are separately
labelled. Unknown fields have explicit masks, and normal accessors refuse unknown
values. A thermal cell mean is not an energy inventory. Slab/mantle records are
supplied footprint/depth-band inputs, not predictions of dipping 3D geometry.

From the repository root, using the [tectonics environment](#environment):

```sh
# Build an authored two-province example offline; output only, no simulation.
python -I -B tectonics/tools/prepare_precursor_example.py > initial-example.json
# Explicitly create a new self-contained result store; existing files are refused.
python -I -B tectonics/tools/prepare_precursor_example.py --save-store initial-example.db
# Full regression and the separate bounded R2 execution card.
python -I -B tectonics/verify.py > 3cr2-tests.json
python -I -B tectonics/tests/check_precursor_r2.py > 3cr2-sampling-evidence.json
```

The example's geometry, temperatures and history are labelled authored
assumptions, not a validated Earth-like default. The optional store contains one
result snapshot; load by its reported `sample_id`, then access `.state`.
No dependencies, reference data or historical checkpoints are downloaded.

**Limits that remain explicit:** constant-depth column/body descriptions, not
general 3D/dipping geometry; spherical point priors but no spherical cell average
of a Cartesian spectral prior; no automatic disjoint-mesh certification across
incompatible charts. Such overlap checks fail rather than snap boundaries, and
explicitly overlapping queries are marked non-additive. General remaining W01
sampling, motion-to-regional forcing, W01-to-W02 evolution integration and the
combined W01 acceptance gate are not complete. No R3/W03 implementation or
physical plate-formation acceptance is included.

Tests/evidence: [`3cr2-tests.json`](evidence/3cr2-tests.json),
[`3cr2-tests.log`](evidence/3cr2-tests.log), and
[`3cr2-sampling-evidence.json`](evidence/3cr2-sampling-evidence.json).
Scientific details are in [the plan](docs/TECTONICS_PLAN.md#3cr2-initial-state);
normal execution, memory ownership and measured costs are in
[the optimisation reference](docs/OPTIMISATION_REFERENCE.md#3cr2-initial-execution).
Test results are software/numerical evidence, not production/Windows acceptance.

**Applying the historical revision-25 delivery:** merge its `tectonics/` files into the local `remake`
checkout based on `e79bf94ea5285a36bbce18b503234a8df56e3910`. Review newer local
edits rather than overwriting them, and preserve unrelated/historical files.
Do not replace the whole repository or delete the destination folder. Michael
owns application, commit and push; sandbox files do not change his PC.

## Retained 3C-R1 delivery (revision 24)

**18 September 2026:** source acquisition, offline processing and the bounded
reference-use review are complete. This is **scoped use of PB2002 evidence**, not
a claim that its raw records form a perfect two-owner mesh or that generated
tectonics are geologically accepted. The complete distribution includes all eight
unchanged, attributed source files; it needs no further reference download.

Two deliberately different offline commands run from the repository root:

```sh
# Original strict consistency: exit 1, with every discrepancy still reported.
python -I -B tectonics/tools/prepare_plate_reference.py --verify-only > 3cr1-strict.json
# Reviewed permitted uses: exit 0 only for the exact audited dataset and findings.
python -I -B tectonics/tools/prepare_plate_reference.py --verify-only --assess-use > 3cr1-use.json
python -I -B tectonics/verify.py
```

`--assess-use` does not waive or rewrite strict checks. Both commands return exit 2
for unavailable/changed inputs. Unknown findings prevent a scoped-use approval.
The default command remains strict; dependencies are never installed automatically.

| Source issue | Enforced treatment |
|---|---|
| ON published area versus outline | Publication confirms the stored 0.00802 sr. Table and computed outline values remain separately labelled; no substitution, averaging or relaxed rounding check. The discrepancy's cause is not established. |
| MS coincident/retraced branch | Documented subsurface representation, not an ordinary simple surface ring. Retain original boundary kinematics; exclude MS ordinary morphology at **all** scales and phases. |
| Three polygon-only connectors | Preserve the finite gaps and refuse the affected surface-edge uses, including the approximately 2 m connector; do not invent motion rows. |
| Peru open deformation outline | Retain the raw 49-point trace; refuse closed-polygon metrics and a complete recomputed deformation mask. Original source-provided flags are not recomputed from an incomplete mask. |

All 52 labelled area records and 5,819 individual source-motion rows remain
available for their stated uses. Ordinary plate morphology has **51 eligible
records** before scale-dependent unresolved cases; **12 of 13** deformation
outlines support closed-polygon diagnostics. Conservative surface-neighbour
statistics exclude all nine owners touching an incidence discrepancy, retaining
43 of 52. These populations are not interchangeable or complete global coverage.

`plate_reference_use.prepare_reference_use(data_directory)` verifies sources,
recomputes the unchanged strict report, and prepares immutable shared indexes.
`observations()` requires a named split/run and a physical scale **and** phase for
shape metrics; area observations require an explicit table or outline basis.
`compare()` adds candidate identity, expected population and unresolved counts.
Selections include every eligible record in their registered split and disclose
all restrictions/unresolved records. No caller-selected mask, subset-area
renormalisation or aggregate realism pass is provided. Raw diagnostic APIs remain
available as raw evidence, not an alternative route to qualified approval.

The policy is a pinned, versioned **post-source-audit** decision in
[cases/plate_reference_use_policy.json](cases/plate_reference_use_policy.json).
It does not alter the original preregistered split or numerical case. All 52 areas
remain previously exposed calibration; ten morphology holdouts remain reserved.
Historical reconstructions and an external model are still unavailable later-stage
validation requirements. **R2, W03 and the plate-generation algorithms are untouched.**

See [scope and evidence](evidence/3cr1-reference-use-assessment.json),
[coverage by scale](evidence/3cr1-reference-use-coverage.json),
[unchanged strict report](evidence/3cr1-complete-reference-checks.json),
and [fresh regression](evidence/3cr1-reference-use-tests.json).
**Verification:** all 1,298 implementation tests passed (1,254 retained plus 44
new), with zero failures, errors or skips. The 93 recorded source/test/case/tool
hashes were unchanged during the run. This does not change the strict gate.

The earlier incomplete-import incident was running an update-only ZIP without
its baseline, corrected in the preceding complete delivery. Sources, previous
test files, numerical kernels/tolerances and historical evidence remain intact.

## Initial plate layouts: corrected scientific status (18 September 2026)

The nearest-seed generator is a **geometry fixture**, not a demonstrated Earth-like
plate-layout model. Its API and old mathematical tests remain unchanged.
A reference-conditioned alternative now uses shared support cells grouped into
connected, unequal, potentially concave plates. **This is a candidate:** its size
spectrum is calibrated against PB2002, while global outline morphology and dynamic
history are not accepted. Generated records explicitly distinguish those gates.

```python
from atlas_tectonics import SphericalFrame, PlateLayoutSettings, generate_plate_layout
# Radius is an explicit world input. Settings below specify a statistical trial,
# not an accepted Earth reconstruction or a prediction of mantle-driven plates.
atlas = generate_plate_layout(
    SphericalFrame(6_371_000., "example-world"),
    PlateLayoutSettings(plate_count=12, seed=41, support_cells=512),
)
```

The offline reference contains 52 published areas, one complete previously exposed Cocos
outline, and 12 original AF/AN boundary-motion rows with signed Euler poles.
Tests include spherical shape measures and exact rigid-motion area integrals;
these do not turn a matched area spectrum into geological validation.
`require_geological_layout_acceptance(atlas)` refuses that unsupported claim.
See [current scientific scope and remaining acceptance](docs/OPTIMISATION_REFERENCE.md#plate-layout-science-correction).
The corrected increment passes **1,134 tests**: 1,091 retained tests plus 43 new
checks, without failures/errors/skips. See [tests](evidence/plate-layout-tests.json)
and [the actual comparisons](evidence/plate-layout-comparisons.json). This is
mathematical/data/engineering verification, NOT a new geological acceptance.
No W03 implementation or GitHub publication is included.


## W01 stage 4B — sourced Earth-material reference library (17 September 2026)

`earth_material_library()` now supplies **67 named reference profiles**: 39 bulk
rock profiles, 25 constituent minerals/endmembers, fresh water, seawater and ice.
Seven named sediment/regolith matrix recipes are explicitly illustrative starting
compositions, not measured universal sediment types. All porosities and pore fluids
remain explicit. This completes the bounded reference-library increment, not a
pressure-temperature equation of state or W03/W07 constitutive modelling.

- Covers felsic/intermediate/mafic igneous rocks, ultramafic mantle samples,
  siliciclastic/carbonate/evaporite/organic sedimentary rocks and main metamorphic
  families. Material names do not claim one universal composition or pore state.
- Each property retains its source, table/section, original units, reported range,
  selection rule and reference conditions. A selected range midpoint is a declared
  representative, not a measured mean or a statistically calibrated distribution.
- Reference completeness is checked per requested quantity AND condition. At the
  nominal 293.15 K coordinate, **44 profiles** have compatible density, specific
  heat and conductivity values. Some records deliberately retain data at other
  temperatures or only a subset of properties. No missing heat source becomes zero.
- **30 profiles have interval-mean expansion references**, not instantaneous
  expansion laws. They are excluded from ordinary scalar-alpha exports/gathers.
  No hot-mantle density law, pressure model, elastic tensor or phase transition is
  inferred. A request beyond the supplied reference is refused, not extrapolated.
- `mix_materials()` distinguishes mass and volume fractions, conserves additive
  volume/heat inventory and requires explicit fluid for pores. Already-bulk rock
  references cannot receive a second porosity correction. Conductivity defaults
  to scalar harmonic/arithmetic bounds; series/parallel arrangements and a geometric
  approximation require explicit selection. No thermal-expansion mixture is guessed.
- `RadiogenicAssay` converts explicit elemental U/Th/K concentrations using a named
  present-day natural-isotope reference equation. It does not infer composition,
  oxide conversion, formation age, secular equilibrium or radioactive evolution.
- `definitions()` exports normal stage-4 records with binding identities and the
  full property-evidence statement. `resolve_geological_layer()` checks that the
  geological case uses those exact definitions and resolves its cohort mixture
  without changing origins, formation dates or thicknesses.
- `PreparedMaterialTable` shares one immutable numerical table and mask, then uses
  native bounded integer-index gathers. Unknown placeholders cannot leak through
  the ordinary gather interface. Metadata and citations are not repeated per cell.
- The existing source/instruction identities include the library implementation
  and raw data. Complete libraries save through the existing Zstd/deduplicated
  store and restore without a network query or dependence on the installed version.

Example (reference selection, not a thermal simulation):

```python
from atlas_tectonics import earth_material_library, sediment_matrix

library = earth_material_library()
materials, evidence = library.definitions((
    "rock.granite", "rock.basalt", "rock.peridotite", "fluid.fresh_water"))
# Attach the returned records/evidence to the existing GeologicalCase description.
# The initial geometry, layer order and material origins still belong to the case.

matrix = sediment_matrix("quartz_sand_or_silt_matrix", porosity=0.30,
                         pore_fluid="fluid.fresh_water")
# matrix.conductivity_bounds_w_m_k is a range, NOT an invented exact conductivity.
# matrix.heat_production_w_m3 remains None without an explicit source assumption.
```

**Verification:** 1,091 checks pass (1,005 prior + 86 new) on the recorded Linux
runtime, including independent source anchors and mixture arithmetic, malformed
inputs, condition/porosity refusals, exact binding, memory/cancellation, immutable
restoration, source-change invalidation, fresh-process and independent-backup reuse.
See [case](cases/w01_earth_materials.json),
[test evidence](evidence/w01-earth-materials-tests.json) and
[coverage/retained-size record](evidence/w01-earth-materials-coverage.json).
These are reference-data/numerical checks, not physical calibration. No prior
numerical test, tolerance, equation or historical evidence has been replaced.

**Next is W01 stage 5, geological sampling.** Reference-only properties must not be
silently applied at a different temperature/pressure; selected W03/W07 laws remain
separate responsibilities. W01 stages 5–8 remain; W03 implementation is paused.

## W01 stage 4 — initial geological descriptions (17 September 2026)

`GeologicalCase` now attaches a compact, validated initial geological description
to a stage-3 regional `BoundaryNetwork` or the stage-3B/3C `SphericalAtlas`.
It preserves topology/generation provenance but does not sample or evolve it.
**Stage 4 is the description/validation layer; stages 5–8 remain. W03 is paused.**

- Shared material reference properties use explicit SI quantities, sources and
  optional validity intervals. Unknown properties remain `None` with reasons.
- W02 cohorts retain distinct material, origin and formation identities. Ordered
  `ColumnDescription` stacks define sediment, crust and lithospheric mantle with
  bulk thickness, porosity and solid-volume mixtures. Sediments count as crust;
  a layer's solid fractions are not mass fractions and are never silently normalised.
- Known/unknown, constant, tabulated and half-space `ThermalInitialProfile` records
  describe initial conditions. Cooling-start time is independent of formation
  time. Tables have explicit linear interpolation/no extrapolation; no W03 solver
  runs. Tabulated profiles must cover their assigned column's full depth.
- Provinces can follow plates/regions or independent geographic pieces. Exactly
  one explicitly supplied domain background closes the description; it can
  describe unknown geology. Explicit precedence replaces a whole column, not an
  implicit merge of overlapping layer stacks. Candidate receipts retain all hits.
- Directed fault traces have declared dip side, dip and depth bounds. Weak zones
  are area/depth extents or finite-width trace corridors with declared strength
  factors (or explicit unknowns). Intersections do not create slip/forces, and
  overlapping weakness factors are not silently multiplied.
- `save_geological_case` / `load_geological_case` use one self-contained, checked
  ArrayStore snapshot. The canonical definition itself is a compressed/chunked
  byte dataset; shared geometry is included once. Native indexes are rebuilt and
  verified on restore, not trusted from pickle. Backups need no original database.

All descriptive records are immutable. Catalogues and ranks are prepared once;
resolution works on supplied candidates rather than scanning all world features.
Definitions, geometry and native execution checks use the existing shared
budgets, identities and persistence. No new numerical backend or dependency is
introduced. Owner-retained topology/geometry/case metadata remains a separate RAM
responsibility; admission estimates are not a process-wide RSS cap.

**Supported initial representation:** surface-relative, piecewise constant bulk
layer thicknesses by province, ordered flat stacks and explicitly homogeneous
solid mixtures. Fault ribbons are descriptions, not meshed fault surfaces. Detailed
variable interfaces, point/cell sampling, spatial thermal evaluation, deformation,
compaction and physically calibrated rock laws are not claimed by these records.
Stage 5 must calculate membership, mixed-cell integrals and relevant depth/property
validity before constructing simulation arrays; returning one point winner is not
permission to assign an entire mixed cell to it.

**Verification:** all **1,005 checks passed** (915 prior + 90 new), with no failures,
errors or skips, on Linux/CPython 3.13.5. Earlier test sources and fixtures remain
unchanged. Windows and geological calibration are unverified.

[Case and acceptance](cases/w01_geological_description.json) ·
[Test evidence](evidence/w01-stage4-tests.json) ·
[Existing scientific notes](docs/FOUNDATIONS.md#w01-geological-description) ·
[Implementation decisions](docs/OPTIMISATION_REFERENCE.md#w01-stage4-delivery)

## W01 stage 3C — automatic initial planetary partitions (17 September 2026)

`generate_planetary_partition()` creates a whole-sphere ownership partition from
an explicit sphere, plate count and seed. Shared vertices, edges, junctions and
working patches are generated together; **native generation needs no manual seam
bindings**. Stage 3B independently checks the assembled geometry before returning it.

```python
from atlas_tectonics import (SphericalFrame, PlanetPartitionSettings,
    generate_planetary_partition)

# Example radius is deliberately synthetic; supply the actual case's radius/frame.
world = generate_planetary_partition(
    SphericalFrame(1_000_000., "example-planet"),
    PlanetPartitionSettings(plate_count=12, seed=42),
)
areas_m2 = world.areas()
neighbours = world.adjacency()
# Existing world.index(), save_spherical_atlas() and load_spherical_atlas() apply.
```

The explicit initialisation prior is **unweighted spherical Voronoi ownership**:
nearest angular site, not a geological plate-size distribution or force solution.
One-, two- and three-site cases have exact whole-sphere/hemisphere/lune constructions.
For four or more sites, one native convex hull produces the shared dual topology.
Candidates must surround the sphere centre and avoid unresolved degeneracy; a
bounded whole-candidate retry records rejected reasons and the accepted attempt.
No site jitter, boundary snapping or repair hides a failed geometric check.

`prepare_planetary_partition(sphere, sites)` accepts named authored site directions,
without resampling them. Unsupported/non-spanning/degenerate authored diagrams are
refused. Existing hand-authored stage-3B atlases are still accepted by their original
API; this generator never overwrites them with random geometry.

`PlanetaryPartitionPlan.build()` reuses prepared topology. The default `auto`
layout retains a whole cell when a conditioned chart supports it; otherwise it
uses interior fan patches. Explicit `triangles` changes the working representation,
not plate geometry. `repatch_planetary_partition()` uses stored sites, not a new
random draw. The intrinsic partition identity and interplate edges survive this
change; extra fan spokes are computational seams, never new tectonic boundaries.

Native hull/tree routines, linear-size incidence structures, shared definitions,
shared memory admission, cancellation and existing Zstd/deduplicated persistence
are used. There is no dense site-by-site distance matrix, per-plate worker pool or
new cache/codec framework. Prepared definitions and returned atlases are owner-side
retained-memory costs; native allocation estimates are not a total-process RAM cap.

**Verification: 915 tests passed (847 prior + 68 new), no failures/errors/skips.**
Independent nearest-site scores, symmetry/lune areas, closure, patch invariance,
authored inputs, deterministic repeats, cancellation, budgets, corruption and
fresh-process/backup restoration are covered. No old fixture or tolerance changed.
[Tests](evidence/w01-stage3c-tests.json), [bounded measurements](evidence/w01-stage3c-measurements.json),
[scientific contract](docs/FOUNDATIONS.md#w01-stage3c),
[optimisation decisions](docs/OPTIMISATION_REFERENCE.md#w01-stage3c-delivery).

This is an initial geometry generator, **not** generated velocities, crust/layers,
a validated tectonic history, global W02 transport or a finished world generator.
Repeatability is qualified by recorded site bytes and runtime, not promised across
unverified backend upgrades. Windows is unverified. W01 stages **4–8** remain;
W03 stays paused. Copy-ready files are delivered for manual review/commit/push;
no changes to the PC or remote repository are made by this delivery.

## W01 stage 3B — closed spherical patch atlas (17 September 2026)

A complete **static planetary geometry** can now be represented without requiring
one hemisphere-wide working map. `SphericalPatch` connects an oriented local face
to shared global vertex IDs; `build_spherical_atlas()` validates a closed spherical
partition and returns a `SphericalAtlas`. Individual charts remain conditioned
local views. A single region/plate may span many charts, exceed a hemisphere,
contain holes/disconnected pieces, or cover the whole sphere.

- Every shared edge has two opposite, geometrically consistent uses. A geometric
  vertex-link test checks that neighbourhood ownership closes once around each
  vertex. Connectedness, Euler characteristic and area closure are checked too;
  summing areas to 4*pi alone is NOT used to excuse gaps or overlaps.
- Regional/plate names do not become patch IDs. Artificial subdivisions inside an
  owner contribute neither new plate boundaries nor extra physical perimeter.
- `stitch_spherical_networks()` accepts existing stage-3 networks with explicit
  bindings to a shared vertex registry. It does not guess matching vertices by
  distance. Projected copies must agree with the supplied registry within the
  fixed round-off attachment band; actual discrepancies remain in provenance.
- Authoritative unit directions are preserved across restoration/reattachment.
  Working-chart changes do not alter the canonical edge coordinates, metrics or
  geometry identity. Changing a patch subdivision can change representation IDs,
  but must preserve the represented owner/area/boundary answers within tolerance.
- `atlas.index()` is a caller-owned reusable native spatial index with tight,
  radius-bucketed spherical caps, bounded queries and the existing final local
  geometry predicates. It returns **all** boundary owners. Same-owner patch hits
  collapse into one owner, not an arbitrary first-hit or nearest-owner choice.
- Frames, adjacency, junctions and prescribed boundary-motion diagnostics now work
  across the entire atlas. This is NOT a global material or force solver.
- Definitions save through existing Zstd/deduplicated `ArrayStore` snapshots.
  Restoration rebuilds and verifies geometry/connectivity rather than unpickling
  native indexes. Index reservations last until close; returned state remains
  caller-owned, and the shared WorkBudget is not a whole-process RAM cap.

**Input boundary:** the supplied mesh must be conforming, with matching seam
subdivisions and shared vertex identities. Unpaired seams, crossed/ambiguous
edges, wrong sidedness, unsupported charts and conflicting owners are refused.
No automatic polygon repair, nearest-neighbour welding or silent snapping occurs.
This removes the prior global-coverage limitation for such explicitly defined
atlases; it is not an arbitrary polygon-soup repair or planet-generation feature.

**Verification:** 847 tests passed (756 previous + 91 new), no failures/errors/skips.
[Fresh test record](evidence/w01-stage3b-tests.json). The focused whole-sphere query
comparison returned identical ownership through indexed and exhaustive paths.
All earlier test sources, fixtures and numerical tolerances remain unchanged.

[Case and invariants](cases/w01_spherical_atlas.json),
[implementation details](docs/FOUNDATIONS.md#w01-stage3b),
[optimisation and evidence](docs/OPTIMISATION_REFERENCE.md#w01-stage3b-delivery).
W01 stages **4–8 remain outstanding**. No W03 work is included. Windows execution,
global evolving plate/material dynamics and geological realism are not established.

## W01 stage 3 — shared boundaries, verified sides and junctions

**17 September 2026.** The corrected stage-2 geometry now feeds a static shared
boundary network. **W01 remains incomplete: stages 4–8 remain.** W03 is not part
of this delivery. This is not a moving whole-planet plate model or a W01→W02
forcing adapter; that adapter remains stage 6/7 work.

- `BoundaryRegion` separates region identity from plate identity. The declared
  domain must be covered exactly once by polygon interiors; gaps, overlaps and
  out-of-domain regions are refused, never snapped, clipped or repaired.
- `build_boundary_network` orients occupied interiors to the left, nodes the ring
  linework and stores each shared atomic segment once. Neighbours reference the
  same segment in opposite directions. Point contacts are not edge adjacency.
- `BoundaryNetwork` retains compact vertex/edge/left-right/incidence arrays and a
  reusable native edge index. `junction()` reports counter-clockwise incident
  rays, verified intervening owners and point-only contacts. Ordinary polygon
  corners are not automatically labelled tectonic triple junctions.
- `edge()` exposes verified sides and reversal; `frames()` batches tangents,
  right normals, lengths and positions. Spherical frames use actual great-circle
  geometry and radius, not projected distances. No epsilon-offset owner guessing.
- `motion()` associates supplied plate velocities with those sides and projects
  opening/shear diagnostics, checked against the existing boundary-motion formula.
  It does not infer motion, slab polarity or a fault law. Spherical radial relative
  motion is reported rather than silently discarded.
- Same-plate region joins are explicit `patch-seam` edges, excluded from normal
  interplate adjacency/motion selection. `validate_trace()` checks an authored
  directed trace against the network and its declared owners, without moving it.
- Self-contained save/load uses the existing Zstd/deduplicated `ArrayStore`; native
  indexes rebuild from verified definitions. Derived connectivity participates in
  identity. These content IDs are not permanent geological boundary labels.

**Spherical boundary:** one declared, conditioned open-hemisphere domain chart is
required. Input regions can have compatible different charts only when exact
reprojection/coverage checks succeed. Tiny reprojection gaps are refused, not
hidden by a tolerance. Arbitrary whole-sphere patch stitching is NOT supplied.

```python
from atlas_tectonics import PlanarGeometry, BoundaryRegion, build_boundary_network

def rectangle(x0, x1):
    return PlanarGeometry.polygon(
        [[x0, 0], [x1, 0], [x1, 1], [x0, 1]], frame_id="example-plane")

network = build_boundary_network(rectangle(0, 2), (
    BoundaryRegion("west", "plate-a", rectangle(0, 1)),
    BoundaryRegion("east", "plate-b", rectangle(1, 2)),
))
edge = network.edge(network.interplate_edges[0])
assert edge.left_region_id == "west" and edge.right_region_id == "east"
motion = network.motion({"plate-a": [0, 0], "plate-b": [2, 0]}, [0, 0])
assert motion.opening_m_s[0] == 2
```

The owner accounts for retained geometry/network data and native-index allowances
outside individual calls. Build/query operations use the existing shared budget;
this remains an allocation estimate, not a GEOS/process heap cap. No scheduler,
new dependency or automatic source migration is introduced.

See [case notes](docs/FOUNDATIONS.md#w01-boundaries),
[implementation and measurements](docs/OPTIMISATION_REFERENCE.md#w01-stage3-delivery),
and [fresh tests](evidence/w01-stage3-tests.json). The copy-ready delivery includes
stages 1 and 2 with their targeted fixes on the pushed `ecac085f…` baseline. No
files require deletion. Linux verification does not establish Windows or geological
acceptance. Nothing is published or written to the owner's PC by this delivery.

## W01 stage 2 — plate and geological-feature geometry


### Targeted stage-2 corrections — 17 September 2026

This delivery corrects the four defects exposed by the independent double-check;
it is not W03 or a new geometry backend. Short spherical arcs use a stable
sum/difference plane normal with scaled normalisation. Imported traces and polygon
rings use the same zero-edge sequence checks as direct construction, including
multipart/nested definitions. Unrepresentable metre distances are refused before
publication. Empty spherical classification honours cancellation.

The original angular tolerance, finite-arc endpoint behaviour, conditioned
hemisphere scope and accuracy-first compiled defaults are unchanged. No geometry
repair, corridor widening, schema migration or new dependency is introduced.
The package version is `0.1.0.dev13`; valid geometry definition IDs remain stable,
while changed source participates in the existing execution identity.

See [fresh regression evidence](evidence/w01-stage2-corrections-tests.json) and
[the focused correction record](evidence/w01-stage2-corrections.json). The previous
646-test record is retained as historical evidence, not overwritten. Windows and
geological realism remain unverified. At that delivery, stages 3–8 were outstanding;
the current stage-3 section above updates that status.


**17 September 2026.** Stage 2 adds an immutable native-backed geometry layer:
Cartesian polygons (including concavity, holes and multipart overlay results),
zero-width feature/fault traces, and spherical minor-great-circle patches.
**Historical stage-2 status:** stages 3–8 were not supplied by geometric predicates;
shared-boundary support is now supplied by the stage-3 section above.

- `PlanarGeometry` supplies membership, boundary classification, metres/m² metrics,
  finite-trace distances/corridors and intersection/union/difference operations.
- `SphericalChart` and `SphericalGeometry` use a conditioned gnomonic chart only for
  topology. Arc distances and solid-angle areas are evaluated on the actual sphere.
  Longitude-seam and polar cases work. A feature must fit an explicit open-hemisphere
  chart; horizon/antipodal ambiguity and operations without a supported common chart
  are refused. This is not an arbitrary full-sphere polygon/Boolean engine.
- `GeometryIndex` reuses native STRtrees and immutable feature definitions. It returns
  all hits in stable feature-ID order, including both sides of a shared boundary.
  It never selects plate ownership by the first hit. Spherical indexes group charts.
- `audit_coverage` reports explicit gaps, out-of-domain area, positive-area overlaps
  and zero-area contacts. It does not move boundaries or delete material to obtain
  coverage. Stage 3 supplies supported domain-patch junctions; arbitrary global
  patch stitching is not claimed.
- `save_geometry`/`load_geometry` reuse the existing compressed/deduplicated store.
  Bounded 2D WKB definitions are checked before native parsing; prepared objects and
  indexes rebuild on restoration. No pickle-based native-object cache is introduced.
- Native double precision is normal. No snapping, `make_valid`, lossy simplification,
  automatic precision reduction or spherical-to-flat metric substitution occurs.
  Optional boundary bands report uncertainty, not repaired geometry or ownership.

```python
from atlas_tectonics import (PlanarGeometry, GeometryFeature, GeometryIndex,
    SphericalFrame, SphericalChart, SphericalGeometry)
region = PlanarGeometry.polygon([[0, 0], [2, 0], [2, 2], [0, 2]],
                                frame_id="synthetic-plane")
with GeometryIndex((GeometryFeature("region-a", region),)) as index:
    hits = index.query([[1, 1], [2, 1], [3, 1]])
    print(hits.pairs)  # all matching (query index, feature index) pairs
sphere = SphericalFrame(2., "synthetic-sphere")  # not an Earth calibration
chart = SphericalChart(sphere, (1., 1., 1.))
octant = SphericalGeometry.polygon([[1, 0, 0], [0, 1, 0], [0, 0, 1]], chart=chart)
print(octant.area_m2)  # pi/2 steradians times radius squared
```

**New normal dependency:** Shapely `>=2.1,<3` (tested 2.1.2, GEOS 3.13.1).
Nothing is auto-installed and there is no lower-accuracy fallback if it is absent.
The existing Numba requirement supplies the finite-arc distance kernel; importing
reference-only calculations does not import that compiler eagerly.

See [scientific notes](docs/FOUNDATIONS.md#w01-geometry),
[optimisation decisions](docs/OPTIMISATION_REFERENCE.md#w01-stage2-delivery),
[test evidence](evidence/w01-stage2-tests.json), and
[bounded query measurements](evidence/w01-stage2-measurements.json).
The copy-ready delivery includes local stage 1 on top of `ecac085f…`. No deletions,
publication, Windows execution or geometric-to-tectonic physical acceptance occur.

## W01 stage 1 — coordinates, reference frames and model time

**17 September 2026.** `SphericalFrame`, `LocalCartesianFrame` and `TimeAxis`
complete stage 1 of the W01 catch-up sequence. **W01 as a whole remains partial:**
At that delivery, plate/feature geometry and the remaining stages were outstanding.
The current stage-3 section above supersedes that status; stages 4–8 remain. W03 implementation follows
that work; this increment does not create polygons, plate histories or a new solver.

- Spherical inputs explicitly specify longitude/latitude units, geocentric latitude,
  radial height and a named planet-centred frame with an explicit radius.
- Full three-dimensional Cartesian/ENU conversions distinguish positions, vectors
  and moving-frame velocities. Local X can be rotated explicitly from east towards
  north. At a pole, the supplied longitude selects the local frame's meridian.
- Geographic longitude is canonical across the seam. The inverse assigns longitude
  zero only on the exact polar axis; it does not snap nearby points to the pole.
- Local coordinates are **3D chord coordinates, not a map projection**. Dropping
  their up component or treating planar distance as surface distance is not allowed
  by this contract. Ellipsoids/geodetic datums are not silently treated as spheres.
- Legacy east/south/up axes have an explicit reflection, with a distinct axial-vector
  rule for angular velocity. Metre/kilometre and degree/radian conversions are named.
- Internal time is forward SI seconds in a named epoch. A `before` axis explicitly
  reverses timestamp/rate orientation, not positive durations. Cross-epoch conversion
  requires a supplied `EpochOffset`. Julian years are available only when selected;
  there is no implicit year length or civil-time/calendar conversion.
- All bulk paths use existing array validation, immutable outputs and shared memory
  admission. Frames reuse a 72-byte numerical basis. Direct local-to-local conversion
  composes a small operator rather than materialising another complete XYZ array.
  Source/callable verification now includes the new modules and named time units.

```python
from atlas_tectonics import (SphericalFrame, LocalCartesianFrame,
    TimeAxis, SECOND, JULIAN_MEGAYEAR)

# Synthetic example radius, not Earth calibration.
sphere = SphericalFrame(radius_m=6_400_000., frame_id="example-planet-axes")
xyz = sphere.to_cartesian([[30., 45., 100.]], angle_unit="degrees")
region = LocalCartesianFrame(sphere, "example-region", longitude_rad=0., latitude_rad=0.)
local = region.positions_from_cartesian(xyz)
velocity = region.vectors_from_cartesian([[1., 2., 3.]])  # no origin subtraction
ago = TimeAxis("example-epoch", JULIAN_MEGAYEAR, 0., "before")
formation_time_s = float(ago.to_seconds(10.))  # negative forward-time timestamp
```

Run `python -I -B tectonics/verify.py` for the complete regression suite. The
[new case](cases/w01_coordinates.json), [scientific notes](docs/FOUNDATIONS.md#w01-coordinates)
and [optimisation decisions](docs/OPTIMISATION_REFERENCE.md#w01-stage1-delivery)
state the numerical range and ownership limits. The obtained test record is
[evidence/w01-stage1-tests.json](evidence/w01-stage1-tests.json).
No dependencies, historical bindings, numerical tolerances or Windows files change.

## W02 regional completion — remapping, moving boundaries and plate events

**17 September 2026.** W02's data/transport/event capabilities are now implemented
for the existing **1D regional, common-density, prescribed-kinematics model**.
This completes the outstanding regional remap/motion/ownership work; it is not
planetary topology, predictive tectonic forces or geological acceptance.

- `ColumnGrid1D` stores explicit nonuniform edges and an identified coordinate
  frame. `to_column_state` is an explicit inventory-preserving bridge from the
  previous uniform representation; older numerical APIs remain unchanged.
- `RemapPlan` uses a linear-size overlap sweep, reusable independently of material
  fields. `remap_materials` integrates limited linear reconstructions conservatively.
  Domain cropping or filling is refused; coarsening is not falsely reversible.
- `advect_ale` separates physical velocity **u** from mesh velocity **w** and evolves
  **thickness times cell width**, with relative flux **(u-w)H**. Compiled MC-MUSCL /
  SSP-RK2 remains normal. Closed moving faces require u=w, not u=0. Crossings,
  unsafe stages and known interior events are refused, never repaired by clipping.
- `PlateTopology1D` defines complete interval coverage, shared boundary sides and
  distinct plate/block/material IDs. Splits, merges, membership changes, boundary
  activation/deactivation and polarity changes retain parent and retired IDs.
- `advance_plate_state` moves aligned ownership/control-volume faces together;
  each shared flux reconciles neighbouring block/cohort inventories with opposite
  signs. Material birth/addition/removal reuses the existing prescribed transfers.
- `MaterialMarkers1D` supports an explicit material-following piecewise-affine map,
  accumulated log stretch and unchanged material identifiers. An arbitrary moving
  numerical mesh is not assumed to carry the material with it.
- Existing budgets, native executor, verified input/result identities, cache
  admission and Zstd/deduplicated snapshots are reused. State/marker snapshots
  restore without a chain of prior manifests. No new cache or scheduler is added.

Example with deliberately synthetic values, not Earth calibration:

```python
import numpy as np
from atlas_tectonics import (ColumnGrid1D, MaterialCohort, MaterialState,
    MaterialBoundary, remap_materials, advect_ale)

mesh = ColumnGrid1D(np.linspace(0, 1, 65), frame_id="synthetic-region")
state = MaterialState(mesh, (MaterialCohort("a", "rock", "origin", 0.),),
                      np.ones((1, 64)), time_s=0., epoch_id="example")
finer = ColumnGrid1D(np.linspace(0, 1, 129), frame_id="synthetic-region")
state = remap_materials(state, finer)
velocity = 0.1 * state.grid.edges_m
result = advect_ale(state, velocity, velocity, 0.5,
                    left=MaterialBoundary("closed"),
                    right=MaterialBoundary("closed"))
# The domain stretches by 5%; inventory is conserved and thickness falls.
# Save or consume result before reusing/releasing its owner's memory allowance.
```

**Verification:** all **488 tests (410 existing + 78 new)** passed without failures,
errors or skips in the tested Linux environment. Independent overlap/flux, geometric
conservation, refinement, event/history, cold restore, cache and concurrency cases
are in [the case](cases/w02_completion.json), [test evidence](evidence/w02-completion-tests.json)
and [measurements](evidence/w02-completion-measurements.json). Current reference and
native ALE outputs agree within unchanged tolerance, not necessarily bit-for-bit.

The plan and optimisation reference remain the two maintained authorities.
**Current next work is W01 stages 2–8**, then W03 thermal/compaction and W04
load construction before W05. The earlier W04-first suggestion is superseded. Future 2D/spherical junctions,
variable-density mechanics and physical creation/recycling laws need their own
geometry and process extensions; no global or Windows sign-off is implied.

## W02 material cohorts and formation history (17 September 2026)

Accuracy remains the default: compiled MC-MUSCL/SSP-RK2, not automatic upwind
selection when a lower-order method is quicker. The new `advect_materials` API
transports each nonnegative cohort partial thickness under the same prescribed
face velocity. Total thickness is derived; material IDs and formation times are
metadata, not floating fields that can be interpolated or averaged away.

- `MaterialCohort`: stable material/origin/formation identity; unknown time is None.
- `MaterialState`: immutable compact cohort×cell thickness, forward-time epoch,
  parent identity and detached last-transition receipt. `ages_s()`,
  `total_thickness()` and `fractions()` derive views; empty fractions need the mask.
- `MaterialBoundary`: explicit incoming cohort composition and reservoir. Missing
  inflow refuses; closed-boundary velocities must be zero.
- `advect_materials`: per-cohort mean flux and before/after/in/out accounts,
  positive candidates, native default, independent reference, no renormalisation.
  `material_timestep_limit` advises a safe interval without changing the scheme.
- `register_cohorts`: explicit zero-inventory catalogue additions, no relabelling.
- `apply_material_event`: parent-bound birth/add/remove amounts at the exact current
  time. Birth sets the actual formation event; addition preserves prior age;
  removal keeps the cohort record even when its inventory becomes zero.
- `cached_material_transport` (in `reuse.py`) and `save_material_state` /
  `load_material_state` use the existing verified cache and deduplicated Zstd store.
- `KernelExecutor.material_transports` reuses bounded serial/thread/spawn execution
  for independent velocity scenarios, never adjacent tiles or sequential times.

Example (synthetic values, not geological calibration):

```python
import numpy as np
from atlas_tectonics import (RegionalGrid1D, MaterialCohort, MaterialState,
    MaterialBoundary, advect_materials)

cohorts = (MaterialCohort("old", "basalt", "source-A", -100.0),
           MaterialCohort("young", "basalt", "source-B", -10.0))
state = MaterialState(RegionalGrid1D(16, 16.0), cohorts,
    np.array([[1.0] * 16, [2.0] * 16]), time_s=0.0, epoch_id="synthetic-seconds")
inflow = MaterialBoundary("open", {"old": 1.0, "young": 2.0}, "west")
outflow = MaterialBoundary("open", None, "east")
result = advect_materials(state, np.ones(17), 0.2, left=inflow, right=outflow)
# result.state.ages_s() == (100.2, 10.2); histories were not blended.
```

Volume is m² per unit width under the common constant-density approximation,
not an unqualified mass ledger. Events prescribe transfers; they do not predict
magmatic productivity or subduction rates. No variable-density/momentum coupling,
continuous thermal/exhumation path, conservative remapping, moving grid or plate
ownership/split/merge logic is supplied. Those remain separately tested W02 work.
The last receipt and self-contained state are persisted; retaining every earlier
receipt is the caller's history policy, not an implicit growing in-memory list.

**Verification:** 410 tests passed (331 prior + 79 new), with no failures, errors
or skips on Linux. Smooth-cohort refinement approaches second-order convergence.
The native and reference measurements solve the same higher-order problem; their
measured partial-thickness outputs were identical. Windows is not verified.

[Scientific contract](docs/FOUNDATIONS.md#w02-cohorts),
[implementation and memory decisions](docs/OPTIMISATION_REFERENCE.md#w02-materials-delivery),
[test evidence](evidence/w02-material-tests.json) and
[bounded measurements](evidence/w02-material-measurements.json) describe the scope.
No old tests/tolerances or prior numerical kernels changed; no publication,
dependency installation, Windows integration or geological acceptance is implied.

## W02 regional transport increment (17 September 2026)

`advect_regional` now transports constant-density crustal thickness on a fixed
one-dimensional regional grid with **N cells and N+1 faces**. The existing periodic
API and its implementation remain unchanged. This is the open-boundary part of
W02, not completion of material cohorts, plate topology or crust production.

- Both ends explicitly select open or closed boundaries. Inflow requires supplied
  exterior face thickness; outflow uses the interior donor. Reversal requires new
  valid incoming data. A closed boundary rejects a nonzero supplied velocity.
- The normal backend is compiled Numba. The default numerical profile is limited
  **MUSCL/SSP-RK2**; `scheme="upwind"` selects the cheaper first-order scheme and
  `backend="reference"` independently checks either calculation. Numerical scheme
  selection is explicit: it is not a silent change to the old periodic method.
- The sufficient outgoing-fraction limits are 1/2 (MUSCL) and 1 (upwind), including
  both external faces. `transport_timestep_limit` advises a safe interval; the
  caller still chooses it. No clipping, automatic substeps or guessed inflow.
- Results include immutable thickness, interval-mean face flux, signed left/right
  exchange and nonnegative inflow/outflow totals. Inventory is **m² per unit width**,
  not kg. The RK2 boundary account uses its stage-averaged flux, not endpoint flux.
- `cached_regional_transport` and `KernelExecutor.regional_transports` reuse the
  existing cache, resource and worker infrastructure. Source, compiler, scheme,
  boundaries, interval and typed inputs participate in identity. Automatic cache
  admission still avoids persisting cheap steps. Whole independent cases can use
  explicit threads/spawn; auto currently retains serial compiled regional batches
  because outer threading was slower in the bounded end-to-end comparison.

```python
import numpy as np
from atlas_tectonics import (RegionalGrid1D, TransportBoundary,
                            advect_regional, transport_timestep_limit)

grid = RegionalGrid1D(cells=128, length_m=128.0)
left = TransportBoundary("open", exterior_thickness_m=2.0,
                         material_id="synthetic-external-reservoir")
right = TransportBoundary("open")
h = np.ones(grid.cells)                     # synthetic thickness, m
u = np.full(grid.cells + 1, 0.25)            # prescribed velocity, m/s
limit = transport_timestep_limit(u, grid, left=left, right=right)
step = advect_regional(h, u, grid, 0.5, left=left, right=right)
# step.balance_residual_m2 checks after - before - left_exchange - right_exchange.
```

All **331 checks passed** (280 prior + 51 new) on the tested Linux environment.
The new tests cover independent rational flux balances, inflow/outflow/reversal,
closed boundaries, variable-speed thinning, refinement and sharp fronts, compiled
versus independent reference, native/thread/spawn agreement, cancellation,
immutable restoration, cache identities, corruption and deduplicated payload reuse.
[Recorded tests](evidence/w02-regional-tests.json) and
[accuracy/cost measurements](evidence/w02-regional-measurements.json) retain their
actual scopes. Timings are noisy bounded synthetic comparisons, not world forecasts.
Windows, moving grids, geological validation and full evolving-world recovery remain
unverified. No source/dependency installation, publication or old-history migration
is part of this delivery. See [the existing scientific case notes](docs/FOUNDATIONS.md#w02-regional)
and [optimisation decisions](docs/OPTIMISATION_REFERENCE.md#w02-regional-delivery).

## Combined resource acceptance — item 12 (17 September 2026)

The normal optimised backends and storage profiles are retained. Executors, cache
wrappers and stores now share byte admission rather than each assuming its own
full allowance. `WorkBudget(max_bytes, parent=...)` supports related component
limits; a reservation charges shared ancestors once. Store cache/page-capacity
allowances stay reserved until close. Codec, decoding, staging, retained manifests
and pending results have separate lifetimes. Resource estimates remain distinct
from measured total process memory.

```python
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.execution import KernelExecutor
from atlas_tectonics.storage import ArrayStore, StoreLimits

# Example execution envelope, not an Earth parameter or owner hardware estimate.
run_budget = WorkBudget(256 * 1024**2)
# Pass budget=run_budget to the executor/store/standalone calls in the same run.
# Kernels keep pure numerical interfaces; no disk paths enter their equations.
```

Default-constructed stores and executors join the same process-local default
budget. An explicitly store-bound cache wrapper inherits that store's budget even
when automatic admission decides to recalculate. Distinct independently launched
programs are not collectively capped by this Python object. Caller-retained inputs,
outputs and operators must have explicit run reservations; shared immutable bytes
should be counted once by their owner, not once per view.

Pool capacity is coordinated across executors. Spawn workers have an explicit
96 MiB per-worker baseline allowance, held until shutdown in addition to their job
reservations; it is not a worker RSS limit. Cancelling a stream drains running calls
before release. Active store preparation cannot be closed underneath its writer.
Under shared memory pressure an executor refuses or drains pending work rather
than spinning because another component holds its remaining capacity.

**Obtained verification:** 280 tests passed (254 prior + 26 new), no failures, errors
or skips, on Linux/CPython 3.13.5. The combined drill additionally passed three
fresh-process profiles: serial/raw, automatic/balanced Zstd, and spawn/compact Zstd.
Each runs first use and five warm cycles combining native transport, cooling,
rotations, complete flexure domains, forced cache round trips, incremental branches
and an isolated backup. Output bytes agree between those profiles; original physical
fixtures and tolerances are unchanged. See the [acceptance record](evidence/combined-resource-acceptance.json)
and the [method/resource boundaries](docs/OPTIMISATION_REFERENCE.md#combined-acceptance).

```sh
# The usual complete regression checks (no telemetry dependency needed).
python -I -B tectonics/verify.py
# Complete regression + bounded process-tree resource/platform acceptance.
# psutil is the explicit acceptance extra; this command never installs anything.
python -I -B tectonics/verify.py --acceptance > item12-local.json
```

The latter command is also the local Windows acceptance route. **Windows remains
unverified until it actually passes there.** Missing dependencies, failed checks
and unsupported permissions/platform behaviour fail explicitly. No Windows pass,
power-loss guarantee or real-world tectonic validation is inferred from Linux or
from a spawn test. Item 1 remains skipped; no broad baseline/tuning programme ran.


## Current storage defaults (items 9–11)

The normal storage path now uses Zstd level 1 with byte shuffle and exact
categorical selection. No opt-in is needed; raw storage remains explicitly
selectable. Missing Blosc2 is an error, not a silent slower fallback. Blosc2 is
included in normal package requirements; no installer runs during computation.

`storage_profile("fast"|"balanced"|"compact")` supplies versioned starting profiles
with 16/64/256 KiB chunk suggestions. Existing stores keep their chunk size.
Packed 1/2/4/8-bit indices and run-length encoding preserve integer/Boolean data
exactly. Existing raw, uniform, palette8 and Zstd snapshots remain readable.

```python
# Snapshot IDs are supplied full scientific invocation identities (SHA-256).
from atlas_tectonics.storage import ArrayStore, StoreLimits, storage_profile
profile = storage_profile("balanced")
limits = StoreLimits(profile.chunk_bytes, max_array_bytes=16*1024**2,
                     max_store_bytes=64*1024**2, decoded_cache_bytes=1024**2)
with ArrayStore("existing-directory/fields.sqlite", limits, profile.compression) as store:
    store.put(parent_id, {"material": material, "temperature": temperature}, metadata)
    # Share the parent's unchanged data; replace only COMPLETE named chunks.
    store.put_incremental(child_id, parent_id,
                          {"temperature": {0: replacement_chunk}}, child_metadata)
```

Encoding and one-time round-trip checks now happen before the writer transaction,
using a bounded memory/disk spool. Dependency checks, batched insertion and final
publication remain transactional. Warm reads reuse verified chunks only inside a
stable database view, with invalidation for same/other-connection changes.

All **254 checks passed**. Repeated reads and unchanged snapshots were faster in
bounded measurements; first writes can be slower. Dictionaries and queued reads
did not justify automatic use in the tested cases. No codec tuning is a global
performance guarantee, and item 12 is not completed by this increment.

Read the [implementation, measurement and resource boundaries](docs/OPTIMISATION_REFERENCE.md#storage-profiles-delivery)
and [test record](evidence/storage-profiles-tests.json). Numerical kernels,
scientific tolerances and prior evidence remain unchanged. No publication,
Windows integration, physical simulation or dependency installation was performed.

## Current execution and reuse defaults (items 6–8)

The latest local delivery adds `KernelExecutor` for bounded independent cooling,
rotation and flexure batches, reusable `ExecutionContext`/`PreparedInput` identity
preparation, and automatic persistent-cache admission with same-request
coordination. The SciPy, Numba and matrix numerical defaults are unchanged.
Small jobs and matrix rotations remain serial when threading is not beneficial;
large eligible cooling/FFT batches use up to two threads under the automatic
profile. A persistent spawn-process path was tested and is not the default.

```python
from atlas_tectonics.execution import KernelExecutor
# requests yields (depth_array, age_array_or_scalar) pairs.
with KernelExecutor() as executor:
    for temperatures in executor.temperatures(requests, thermal_parameters):
        consume(temperatures)  # caller controls retained output memory
```

Cache wrappers now use automatic admission: they avoid caching cheap products and
learn measured compute/write/restore costs. `CachePolicy(mode="always")` explicitly
requests persistence; `mode="off"` disables store access. Supplying an immutable
`PreparedInput` lets repeated calls reuse its digest rather than rehash the payload.
Context reuse still compares exact current source bytes; it does not replace
verification with timestamps. Creator failure, wait cancellation, corruption and
source changes remain explicit errors. The existing transaction checks cancellation
and source state immediately before committing an admitted result.

See the [single maintained optimisation reference](docs/OPTIMISATION_REFERENCE.md#execution-reuse-delivery)
for policies, use boundaries and the measured decisions. The full verifier passed
**216 checks, with no failures/errors/skips**, including the original 169 and 47
new checks. [Test record](evidence/execution-reuse-tests.json) and
[measurements](evidence/execution-reuse-measurements.json) are scoped numerical and
execution evidence, not physical validation. `threadpoolctl>=3.6,<4` is now a normal
requirement. No dependencies were installed in this delivery; Windows/macOS and
other native builds were not run. No files have been pushed to origin.

## Implemented calculations

| Component | Capability | Boundary |
| --- | --- | --- |
| Rotations and boundary motion | Finite quaternions with reused immutable matrix application by default; ordered composition, inverse, bounded batches, streaming and scale-safe normalisation | No generated plates, force balance or geometric sidedness audit |
| Thickness transport | Conservative, positivity-preserving periodic 1D upwind update; compiled Numba update and exact positive-sum accounting by default; explicit NumPy/`math.fsum` reference | No open boundaries, material birth or subduction |
| Half-space cooling | Analytical temperature with explicit depth/age/parameters; SciPy array backend by default; explicit scalar reference | No evolving thermal PDE or calibrated material profile |
| Periodic flexure | Uniform 1D centred-difference operator solved with FFT; immutable setup reuse and scaled extreme-range arithmetic | Not continuous spectral k^4, variable rigidity, open edges or the cause of uplift |
| Parameter records | Immutable typed SI values and identities, without hidden Earth/Diadem defaults | No user customisation UI or new scientific calibration |

These do not complete W01-W04 or supply the W05 coupled extension experiment.
Physical validation and production integration remain outstanding.

## Memory and persistence increment (17 September 2026)

- Masked numerical inputs are refused before their missing-value information can
  be discarded. Shapes and projected array work are checked before bulk allocation.
- `WorkBudget` bounds estimated simultaneous kernel allocations, including shared
  reservations across threads. The default local envelope is 256 MiB; callers can
  supply a different explicit budget. This is **not a total process RSS cap**:
  caller-owned inputs, retained outputs and native allocator overhead remain separate.
- Transport reuses private donor/scratch arrays without mutating the input or
  changing the shared-face update. Accurate budget summations are retained.
- `backend="scipy"` is the default bulk error-function evaluation. It is numerically
  compared, not claimed bit-identical to `math.erf`. Missing dependencies cause an
  explicit error, never a silent backend substitution.
- Flexure restoration rebuilds its immutable coefficients from the typed definition.
  The method identity is versioned for range handling. Transport-result restoration
  also re-establishes immutable array backing; generic NumPy pickle is not a storage contract.
- `ArrayStore` provides typed, immutable array snapshots in a **local SQLite file**,
  with chunk deduplication, exact uniform encoding, optional integer palettes,
  optional Zstd via Blosc2, and byte/bit/no-shuffle choices. Compression uses one
  thread per call. Encoding records name codec/filter/version; raw storage is used
  when it is smaller. This is a declared encoding choice, not missing-dependency fallback.
- A repeated snapshot reuses unchanged chunks; one changed chunk stores one new
  payload. Each manifest references chunks directly, without long temporal delta
  chains. There is no automatic deletion or history migration.
- Reads validate stored and logical hashes, lengths, shape and dtype. Arrays restore
  with immutable byte backing. A bounded decoded-chunk LRU, direct chunk reads and
  streaming avoid requiring a complete decoded snapshot in RAM.
- SQLite transactions coordinate writers and publish complete snapshots. Conflicting
  results for one identity, corrupt records, missing chunks and exceeded limits are
  errors. `backup_to()` makes a consistent independent copy to a new file.
- `cached_temperature` and `cached_flexure` are optional wrappers outside the physics.
  Keys include typed input bytes, resolved parameters, selected backend, package
  source, loaded Python instructions and selected runtime binary identities.
  Profiles and input descriptors remain in the stored manifest, not just a filename.
  Source/instruction identity is rechecked before publication.

SHA-256 here detects corruption and supports identity; it is not a signature or a
security boundary against an attacker controlling the process or database. The
local directory must be owned/trusted. Binary runtime files are assumed immutable
for the lifetime of a process. This is not a recursively sealed historical runtime.

### Example: optional persistent cooling

Use an existing compatible environment; no command here installs dependencies.
The directory must already exist. Values below are **synthetic test values**, not
an Earth profile. The storage limits are example execution limits, not owner budgets.

```python
from pathlib import Path
import numpy as np
from atlas_tectonics.parameters import ThermalParameters
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
from atlas_tectonics.reuse import cached_temperature

limits = StoreLimits(chunk_bytes=32768, max_array_bytes=8*1024**2,
                     max_store_bytes=32*1024**2, decoded_cache_bytes=128*1024)
profile = ThermalParameters("synthetic", "example only", 300., 1300., 1.)
with ArrayStore(Path("existing-cache-directory") / "fields.sqlite", limits,
                Compression(codec="zstd", level=3, shuffle="byte")) as store:
    temperature = cached_temperature(np.linspace(0, 10, 4096), 1., profile,
        store=store, backend="scipy", budget=WorkBudget(32*1024**2))
```

The same call with `store=None` computes without persistent I/O. Imports use the
`tectonics/src` layout; use a declared environment or a separately prepared editable
installation. Normal requirements include NumPy, SciPy and `numba==0.65.1`.
Blosc2 remains the explicit `storage` extra. No package auto-installs.
Use `backend="reference"` explicitly for a diagnostic reference calculation.
Blosc2's level 0-9 scale is not the direct Zstd level scale.

### Memory/storage limits

Storage chunks are flat C-order pieces of a typed array, not physical boundaries.
Non-native byte order is losslessly normalised to little endian. Shapes, signed
zeros and categorical values are retained; masked/object/nonfinite arrays are
refused. A mask can be a separately identified boolean dataset only when its
scientific consumer actually supports that policy.

`max_array_bytes` limits individual writes and complete snapshot materialisation;
use `read_chunk()`/`iter_chunks()` for partial reads. `max_store_bytes` bounds
retained database pages/records; provision **up to another database-sized rollback
journal**, plus backups. SQLite cache and codec workspace are separate costs.
Input arrays must not be mutated during a store write. Returned data can outlive
an LRU entry, so caller-held arrays must still be counted in the application's RAM.

This is result persistence, not a demonstrated restart of an evolving world. No
Zstd dictionaries, global voxel engine, automatic GC, lossy history, GPU solver,
distributed mechanics or old R5 conversion is introduced.

## Optimised defaults (17 September 2026 follow-up)

Normal calls use the tested accelerated implementation: `advect_thickness` selects
Numba, while `half_space_temperature` and `cached_temperature` select SciPy.
The explicit reference routes remain for independent verification. Missing
dependencies cause an error, not silent fallback. The normal package requirements
include these backends; no setup command runs or installs packages automatically.
First-use compilation remains; compiler flags and numerical tolerances are unchanged.

The default-selection change passed 82 focused checks (53 explicit reference,
21 native and eight default/dependency checks) on Linux/Python 3.13.5.
The complete storage/reuse suite was not rerun for this follow-up; the cache-wrapper
default was checked structurally. Earlier full-suite records below remain historical.
No benchmark, simulation, Windows run or remote publication accompanied this change.

## Verification and evidence

```sh
# Existing NumPy environment: original 53 mathematical cases
python -I -B tectonics/verify.py --core
# Full suite, including compiled transport, with normal requirements and storage extra
python -I -B tectonics/verify.py
```

The verifier refuses local `.pyc` files: `-B` alone prevents writes, not reads.
It writes test details to stderr and a fresh versioned record to stdout. Missing
required dependencies block full verification rather than silently skipping it.

The 17 September delivery passed **93 tests (53 existing + 40 new), no failures,
errors or skips**, on Linux/CPython 3.13.5/NumPy 2.3.5, with SciPy 1.17.0,
Blosc2 4.3.3 and its Zstd 1.5.7. See
[evidence](https://github.com/Atlantispy/atlas/blob/0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40/tectonics/evidence/memory-storage-tests.json). Tests include independent numerical
references, masked/range regressions, allocation refusal, immutable restore,
fresh-process cache reuse, changed-input identities, Zstd/palette round trips,
concurrent writers, corruption/oversized decoding, rollback, and isolated backup.

[Bounded measurements](https://github.com/Atlantispy/atlas/blob/0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40/tectonics/evidence/memory-storage-measurements.json) compare synthetic
65,536-element kernels and a 1,179,648-byte three-field storage sample. They are not
world-scale forecasts or physical validation. Transport reduced tracked peak
allocations by about 22%, without a demonstrated timing improvement. The opt-in
cooling backend was faster in warmed comparisons; its results were not bit-identical.
Compression/deduplication gains depend on the field and must not be extrapolated.

Windows/macOS, Python 3.12, other dependency builds, power-loss behaviour on other
filesystems, large-world memory and geological realism were not verified here.
The [first delivery record](evidence/DELIVERY.md) remains historical and unchanged.

## Next development gate

Continue with **W01 stage 5: sample the geological description** onto explicit
point/cell supports without moving features, guessing unknowns or treating a
point-wise winner as a conservative mixed-cell integral. Stages 1–4 (including
3B/3C) supply geometry and description infrastructure; stages 5–8 remain before
W01 completion. W03 stays paused until the required initialisation and supported
W01-to-W02 link are complete. Reuse the existing W02 regional implementation,
accuracy-first defaults, storage and resource controls; no broad rewrite is needed.


## Optimisations 4 and 5 — cooling and geometric batches

The optimised defaults remain enabled: SciPy cooling and compiled Numba transport.
Rotation now defaults to a reused immutable matrix (`backend="reference"` preserves
its earlier formula). Cooling computes age-dependent lengths before broadcasting,
then uses bounded sample batches. Flexure retains its verified FFT operator and
fast contiguous path, adding bounded independent-load grouping and lazy batch
consumption rather than an unproven backend replacement.

```python
# Ordinary calls use the selected optimisations without opt-in switches.
temperature = half_space_temperature(depth_m, age_s, parameters)
rotated = rotation.apply(points_m)
deflection = operator.solve(loads_pa)   # (..., grid.cells), independent leading cases

# These consume separate complete requests, not independent spatial solver tiles.
for rotated_batch in rotation.apply_batches(point_batches, budget=budget):
    consume(rotated_batch)
for deflection_batch in operator.solve_batches(load_batches, budget=budget):
    consume(deflection_batch)
```

`consume` represents the caller's chosen output handling, not a new Atlas function.
Discard processed batches to keep total output retention bounded. No disk write,
worker pool or background activity is started by these iteration APIs. The full
array-returning methods still require memory for the entire returned array.

[Decisions, limitations and obtained measurements](docs/OPTIMISATION_REFERENCE.md#delivered-optimisations-4-5)
are maintained in the existing reference. The new tests are included by
`python -I -B tectonics/verify.py`; no dependencies are installed by verification.
No other optimisation-list item or physical mechanism is implemented here.
