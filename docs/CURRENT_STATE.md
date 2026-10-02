# Atlas: current development state

**Updated: 2 October 2026. WORKING NON-CANON.** This is the single current
checkpoint: what is current now, with links to the owner documents and evidence.
It is not a progress log, scientific acceptance or a finished world dataset. The
working branch is `remake`; use `git status` and `git log`, not this page, for
commit and push state.

## Active checkpoint

**I02 is complete for the agreed supported coupled-column workflow.** Its
benchmark/restart corrections, R1 output-integrity repairs, corrected 3-D
multigrid-first automatic solver choice and R4 reliability repairs are integrated
locally. R4 closes the reviewed checkpoint corruption/race, recovery, resource,
cache and archive-input issues; fresh r6 successors record the affected controls.
The final Git-normalised integration check passed all three guards, including
759 I01/I02 tests (164.449 s; 169.6 s for the guard). These are bounded
implementations, not a connected whole-world engine or physical acceptance.

I02's tracked [plate-velocity handoff contract](../tectonics/docs/I02_WORKFLOW.md#relative-plate-velocity-handoff-contract-eps_v)
now records the owner-approved `eps_v = 0.01` (1%). I06.2/I07.2 consume this
policy and I09 enforces it; I03 does not require it. This records the decision,
not implementation or certification of those later handoffs.

The table below identifies each implementation and its remaining limits. Detailed
checks, measured overhead and compatibility effects belong in the
[I02 workflow](../tectonics/docs/I02_WORKFLOW.md#7-checks-coverage-and-measured-overhead),
[3-D solver method](../tectonics/docs/REGIONAL_MECHANICS_3D.md#automatic-choice-between-gmres-and-multigrid-methodauto)
and [evidence guide](CURRENT_EVIDENCE.md). Historical receipts remain unchanged;
passing focused checks is not a new full-suite or cross-platform pass. The
[before-commit guard](CODING_SAFETY.md#before-every-commit) checks Git-normalised
candidate bytes, not only the working copy.

**Next action:** stop before I03 and await the owner's next instruction. The
Saturday review hold was released on 30 September. The desktop package now
includes accepted I01/I02 and R7 sources at `c856236`; its UI snapshot is available
locally from the accepted build but remains absent from a public clone. Work follows the
[completion roadmap](ATLAS_ROADMAP.md); planning is not execution authority.

## Current status

| Area | Status | Owner document and evidence |
| --- | --- | --- |
| Development workflow | Focused regression selections and a narrow documentation-only commit check are implemented. Full verification remains available and remains the default; no scientific coverage, numerical implementation or receipt was removed. Repeated status/results prose has one owning location. | [Test selections](../tectonics/README.md#focused-regression-selections), [commit checks](CODING_SAFETY.md#before-every-commit) |
| Evidence register | Each listed receipt is current, historical, superseded or invalid; `python -B tools/check_current_evidence.py` prints the live counts. Current means the declared byte bindings match, not physics, runtime or platform. Unlisted receipts, including all W01–W12 records, are unclassified. | [Evidence guide](CURRENT_EVIDENCE.md), [register](../tectonics/evidence/current-evidence.json) |
| First review-repair batch (A1–A6) | W12 export and surface policy, bundle inspection and staging, line-ending digest corrections, 512-file source capacity, public-path redaction, a tested Windows environment and one status page. | [Repair record](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md), [environment](TECTONICS_ENVIRONMENT.md) |
| I01 physical integration | Method choices, input and ownership contracts and bounded feasibility are selected for all seven MC items. The controls check the code against analytical cases, refinement, conservation and warm/cold parity; they are not independent physical validation, calibration or generated-world acceptance. Full events remain with their I02–I09 owners. | [Closure matrix](../tectonics/docs/I01_CLOSURE_MATRIX.md), [physical contract](../tectonics/docs/I01_PHYSICAL_CONTRACT.md), [reader chapter](../tectonics/docs/how-it-works/06-physical-integration.md) |
| I01 evidence | Fifteen affected controls have current passing successors, including G25 in the pinned Julia/MAGEMin environment. Eight were refreshed for the I02 numerical/restoration changes; seven unchanged controls were reused. Finite-admission r6 passed all five controls after R4 and its restoration fix, reusing unchanged prerequisites and superseding r5. Old receipts remain intact; the old separation performance comparison remains historical. | [Coverage today](CURRENT_EVIDENCE.md#coverage-today) |
| I02 common state, exchanges, clock and restart | I02.1–I02.8 reviewed, corrected, integrated locally and accepted for the declared coupled-column workflow. Atomic state/exchange commits, one accepted clock, save/reopen/fresh-process continuation, cancellation, inspection and measured overhead are connected. Linux coverage remains open. The new execution identity intentionally makes earlier W12/New World jobs refuse continuation or verification; saved bundles remain inspectable, without rebinding ([compatibility effects](../tectonics/docs/I02_WORKFLOW.md#8-evidence-effects)). | [I02 contract](../tectonics/docs/I02_COMMON_STATE.md), [I02 workflow](../tectonics/docs/I02_WORKFLOW.md), [integration plan](../tectonics/docs/INTEGRATION_PLAN.md#i02--common-state-exchange-transactions-and-accepted-time-controller) |
| 3D regional mechanics and evolution | Fixed-box Q2/Q1 full-stress Stokes with first-order donor-cell transport and conduction. The reviewed matrix-free multigrid method (I07.2 solver scaling) and corrected automatic `auto` choice between it and assembled GMRES are integrated locally; `auto` is the default for new runs. Resource admission and memory accounting are repaired. Auto restart binds the admitted solver set; temporary memory pressure refuses rather than rerouting. Same equations, gates and outputs; explicit methods are retained. First-order transport remains strongly diffusive at these resolutions. Workflow-timing r7 renews the shared package bindings, not a 3-D speed measurement. | [Mechanics](../tectonics/docs/REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse), [multigrid](../tectonics/docs/REGIONAL_MECHANICS_3D.md#matrix-free-multigrid-candidate-i072-solver-scaling), [automatic choice](../tectonics/docs/REGIONAL_MECHANICS_3D.md#automatic-choice-between-gmres-and-multigrid-methodauto), [evolution](../tectonics/docs/REGIONAL_EVOLUTION_3D.md) |
| Repair batch R1 (output integrity) | Integrated locally: scale-invariant 3D Stokes acceptance gates, a free-surface relaxation timestep gate and shared interval ends, thread-safe prepared geometry, a New World column envelope, no fabricated case 1a pressure, membership-derived execution identity including dtype layouts/metadata, and gauge-aware plate torques and port masks. Its workflow-timing r2 and finite-admission r5 captures are retained as superseded records after later integration. No tolerance was relaxed and the step ceiling is unchanged. | [3D mechanics](../tectonics/docs/REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse), [W07 surface](../tectonics/docs/W07_SURFACE_STRENGTH.md), [New World evolution](../tectonics/docs/NEW_WORLD_EVOLUTION.md) |
| Repair batch R4 (reliability and bounded resources) | Integrated locally with follow-up fixes: checkpoint corruption and concurrent restore guards, retryable never-started jobs without resampling, resource/cache accounting and locking, and structured ZIP/input refusals. Focused regressions passed; finite-admission r6 and workflow-timing r6 supersede their r5 records. Final Git-normalised verification passed all three guards, including 759 I01/I02 tests. | [Evidence and focused checks](CURRENT_EVIDENCE.md#integration-checks), [workflow effects](../tectonics/docs/I02_WORKFLOW.md#8-evidence-effects), [job recovery](../tectonics/docs/NEW_WORLD_EVOLUTION.md), [bundle guards](../tectonics/docs/NEW_WORLD_BUNDLE.md) |
| Repair batch R7 (remaining review defects) | **Reviewed, corrected and integrated locally.** Geometry overlap rules, executor ownership, interrupted viscosity rebuilds, deterministic 3-D starts, W07 heat provenance and versioned W06/plate ports are repaired. Follow-up fixes add temperature-consistent zero-latent source admission, interior-based heat-boundary reconstruction, flexure precision estimates, native LU allocation accounting and shared exact layer/thermal edges. Zero starts retain restart determinism at the documented extra nonlinear cost. All 211 focused follow-up checks pass; adequate unchanged R7 evidence was reused. The final Git-normalised guard passed all three checks, including 759 I01/I02 tests. Fresh workflow-timing r7 replaces r6. No physical tolerance, default memory budget or step ceiling increased. Earlier execution-bound results are not silently migrated. Windows/CPython 3.12.14 coverage. | [Integration checks](CURRENT_EVIDENCE.md#integration-checks), [phase admission](../tectonics/docs/W08_MAGMATISM.md), [heat boundaries](../tectonics/docs/W07_HETEROGENEOUS_THERMAL.md), [flexure precision](../tectonics/docs/W04_VARIABLE_RIGIDITY.md), [3-D resources](../tectonics/docs/REGIONAL_MECHANICS_3D.md), [3-D evolution](../tectonics/docs/REGIONAL_EVOLUTION_3D.md), [initial structure](../tectonics/docs/NEW_WORLD_STRUCTURE.md) |
| New World, steps 1–7 | Seeded request, plate layout, crust, motion, regional evolution, save/load and portable bundles are implemented. The Step 7 r2 and bundle r2 receipts are historical; the Step 7 case matrix is current. | [Combined acceptance](../tectonics/docs/NEW_WORLD_ACCEPTANCE.md), [bundle](../tectonics/docs/NEW_WORLD_BUNDLE.md) |
| B1 boundary diagnostics | One matched original/prototype comparison against PB2002 development at 100/250/500 km. Descriptive, not realism acceptance; the prototype's motion was not refitted. | [Method and checkpoint](../tectonics/docs/NEW_WORLD_MOTION.md#matched-boundary-diagnostics-roadmap-b1), [receipt](../tectonics/evidence/boundary-kinematics-r1.json) |
| B2 causal generation | Diagnosis only: saved worlds keep their initial conditions and crust does not shape the plate layout. No producer fix; the owner rejected post-generation fairing as the realism fix. | [Diagnosis](../tectonics/docs/NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design) |
| W01–W12 components | Implemented components with dated method records. Their receipts describe the runs they record; many bound sources have changed since. | [Reader guide](../tectonics/docs/HOW_TECTONICS_IS_MADE.md), [plan status](../tectonics/docs/TECTONICS_PLAN.md#current-implementation), [validation](../tectonics/docs/W10_VALIDATION.md) |
| Full test suite | No current full-suite pass is claimed on any platform; see below. | [Environment and `verify.py`](../tectonics/README.md#tectonics-environment) |
| Tested environment | Windows AMD64 CPython 3.12.14 pins and a clean-install receipt are current. Linux and Python 3.13 are not recorded environments. | [Environment guide](TECTONICS_ENVIRONMENT.md) |
| Windows desktop | Updated on 2 October from accepted commit `c856236`, including I01/I02 and R7, excluding unfinished I03. Real New/Save/Load and installed fresh-process reopen passed in an isolated profile; the user's projects were untouched and the previous build retained. All 380 native payload files matched the snapshot. The unchanged 33-file UI now has a tracked digest pin; its content remains outside the public repository. This does not add I02 whole-world UI integration. | [Desktop build and checks](../desktop/README.md) |
| Wider generator and runtime | R31 connected generator, R12 runtime and the bounded native terrain R5 storage/session route; the 18 categories have entry points, not accepted systems. R5 performance figures are historical original-workspace measurements. The recovery runbook changed at `18dfb1d`; no fresh public performance receipt is claimed. | [Code route map](CODING_SAFETY.md), [R5 operations](R5_OPERATIONS.md), [historical R5 evidence](R5_OPERATIONS_EVIDENCE.md), [independent development](INDEPENDENT_DEVELOPMENT.md), [categories](../README.md#the-18-modelling-categories) |
| Other modules | Scopes for the 17 non-tectonics categories are planning only. | [Module scopes](MODULE_SCOPES.md), [product contract](PRODUCT_AND_SCALE_CONTRACT.md) |

## Full-suite status

The latest full run is the external review's Linux, CPython 3.13.13 run of
`tectonics/verify.py` at `577c044` on 28 September: 4,591 tests, 26 failures and 3
errors. The review attributes one failure and two errors to its own omitted W12
demo `--resume` step; those tests passed in a focused rerun after that step. The
remaining 25 failures and 1 error were attributed to the subsequently corrected
line-ending bindings, moved I01 solver source bindings and Python-version-specific
finite-admission exception expectation; see the [correction trail](CURRENT_EVIDENCE.md#line-ending-digest-correction-r2)
and [successor evidence](CURRENT_EVIDENCE.md#successor-capture-after-i022a-and-the-writer-correction). No second
full-suite run has been made, and no full-suite run of this checkout is recorded
on Windows.

## Boundaries

- Generated-world tectonics realism is open: grid-shaped boundaries, restrictive
  starting-crust shapes and an ocean-age field that needs explicit history.
  Mountain/terrain realism and a complete whole-world, whole-year run are not
  accepted.
- R4.4 remains held. No broad campaign, change to physical tolerances, removal of
  source/runtime guards or increase of the retained 256-interval ceiling is
  authorised here. Unrelated historical speedup ratios are not multiplied into a
  whole-generator claim.
- Read-only inspection and exact native continuation differ: a public source
  snapshot does not supply private inputs, codecs or runtime, and byte recovery
  is not a restart. Diadem canon, local integration, Git commit and publication are
  separate states.

## Maintaining this page

Update this page in place: one table of what is current, each row pointing at its
owner document and evidence. Measurements, test counts and method detail belong in
those records, not here. Git history keeps earlier versions of this page. No old
result becomes current because this page changes.
