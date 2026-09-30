# Atlas: current development state

**Updated: 30 September 2026. WORKING NON-CANON.** This is the single current
checkpoint: what is current now, with links to the owner documents and evidence.
It is not a progress log, scientific acceptance or a finished world dataset. The
working branch is `remake`; use `git status` and `git log`, not this page, for
commit and push state.

## Active checkpoint

**I02 is complete for the agreed supported workflow.** The reviewed candidate and
its benchmark/restart corrections are integrated locally. One real coupled column
now runs through create, advance, atomic save, reopen, continue and inspect without
replaying its accepted history. No I03 work, commit, push or new full-suite run was
performed during this closeout.

**3-D solver scaling and automatic solver choice are reviewed and corrected
locally.** The reviewed matrix-free multigrid method is in the working tree, together
with a multigrid-first `auto` choice between it and the assembled GMRES route. `auto`
is now the default for new 3-D plans and evolution runs. It uses multigrid wherever
multigrid has been shown to converge (contrast up to 1e5 in bricks up to 2:1, or up
to 1e3 in bricks up to 4:1, at least 4 cells per axis) and GMRES elsewhere. On 29
measured workloads it took 176.8 s against 752.8 s for GMRES alone. Explicit
`gmres`, `direct` and `multigrid` requests are unchanged and publish bitwise the same
results as the reviewed candidate. Auto evolution now binds its admitted solver set
to the saved-state identity: changed admission refuses continuation, and temporary
memory contention refuses rather than silently rerouting. All 22 selector tests
and 9 evolution tests pass. The performance wording now also discloses the separate
edge probes (up to +1.40 s / +144% on a measured small solve). Fresh workflow-timing r5
passes seven parity checks and supersedes r4; this is not a new 3-D speed measurement.
The two review findings are closed. No commit or push was made
([rule and measurements](../tectonics/docs/REGIONAL_MECHANICS_3D.md#automatic-choice-between-gmres-and-multigrid-methodauto)).

**R1 output-integrity repairs are now integrated locally**, including the reviewed
NumPy dtype identity correction and the I02-compatible landing updates. The 56
execution/reuse tests pass. Fresh finite-admission r5 and workflow-timing r2
receipts passed all five and seven controls respectively; their predecessors
remain unchanged and superseded. The final Git-normalised integration guard
passed all 758 I01/I02 tests, all three line-ending tests and 445 recorded source
digests (169.1 s total). Nothing has been committed or pushed; I03 remains outside
this work. The earlier 2,478-test R1 candidate result was reused, not rerun as a
full-suite claim for this integration.

The three repository defects from the 28 September review of `577c044` were
corrected before this integration and remain covered:

1. Six I01 receipt writers wrote CRLF text on Windows, so 13 receipts were
   registered by the digest of a CRLF rendering that no checkout contains. The
   writers now write LF, and the recorded values are corrected through an
   explicit [correction trail](CURRENT_EVIDENCE.md#line-ending-digest-correction-r2).
2. I02.2a moved the I01 solver into package modules, so nine receipts bind an
   earlier tool layout, and the writer fix changes tools that seven more records
   bind. Fifteen new passing receipts were captured, reviewed and registered in
   [dependency order](CURRENT_EVIDENCE.md#successor-capture-after-i022a-and-the-writer-correction)
   Eight of that set now have fresh successors for the I02 restoration path and
   numerical correction; the other seven are unchanged and reused.
   Both stale-evidence test failures are resolved; old receipts were not repinned.
3. One finite-admission test expected Python 3.12's exception type. Python 3.13
   raises `TypeError` for the same refused replacement; the test now accepts either
   while still proving that the field cannot be replaced.

A [before-commit guard](CODING_SAFETY.md#before-every-commit) runs the evidence
checks on Git-normalised candidate bytes rather than on the working copy.

The 30 September review corrections separately check cold and warm benchmark
outputs and reopened physical accounts, refusing timings on disagreement. A
direct-stress refinement fixes precision stalls in the constitutive solve without
changing its equations, residual tolerance or iteration limit. Cold continuation
and failed-save recovery pass, including the existing 256-step limit.

The final Git-normalised check passed all 758 I01/I02 tests, current-evidence
bindings and LF-digest checks. Eight affected physical controls were freshly
captured; the corrected timing record checks equivalent work and binds its sources.
See the [workflow method](../tectonics/docs/I02_WORKFLOW.md#7-checks-coverage-and-measured-overhead)
for scope, test results and measured time/storage overhead. This is Windows
coverage, not a new full-suite or cross-platform pass.

**Next action:** stop before I03 and await the owner's next instruction. The
Saturday review hold was released on 30 September. The desktop build's missing
UI snapshot remains a separate delivery dependency. Work follows the
[completion roadmap](ATLAS_ROADMAP.md); planning is not execution authority.

## Current status

| Area | Status | Owner document and evidence |
| --- | --- | --- |
| Evidence register | Each listed receipt is current, historical, superseded or invalid; `python -B tools/check_current_evidence.py` prints the live counts. Current means the declared byte bindings match, not physics, runtime or platform. Unlisted receipts, including all W01–W12 records, are unclassified. | [Evidence guide](CURRENT_EVIDENCE.md), [register](../tectonics/evidence/current-evidence.json) |
| First review-repair batch (A1–A6) | W12 export and surface policy, bundle inspection and staging, line-ending digest corrections, 512-file source capacity, public-path redaction, a tested Windows environment and one status page. | [Repair record](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md), [environment](TECTONICS_ENVIRONMENT.md) |
| I01 physical integration | Method choices, input and ownership contracts and bounded feasibility are selected for all seven MC items. The controls check the code against analytical cases, refinement, conservation and warm/cold parity; they are not independent physical validation, calibration or generated-world acceptance. Full events remain with their I02–I09 owners. | [Closure matrix](../tectonics/docs/I01_CLOSURE_MATRIX.md), [physical contract](../tectonics/docs/I01_PHYSICAL_CONTRACT.md), [reader chapter](../tectonics/docs/how-it-works/06-physical-integration.md) |
| I01 evidence | Fifteen affected controls have current passing successors, including G25 in the pinned Julia/MAGEMin environment. Eight were refreshed for the final I02 numerical/restoration changes; seven unchanged controls were reused. Finite-admission r5 was freshly captured after R1 integration and passed all five controls with its unchanged prerequisites reused. Old receipts remain intact; the old separation performance comparison remains historical. | [Coverage today](CURRENT_EVIDENCE.md#coverage-today) |
| I02 common state, exchanges, clock and restart | I02.1–I02.8 reviewed, corrected, integrated locally and accepted for the declared coupled-column workflow. Atomic state/exchange commits, one accepted clock, save/reopen/fresh-process continuation, cancellation, inspection and measured overhead are connected. Linux coverage remains open. The new execution identity intentionally makes earlier W12/New World jobs refuse continuation or verification; saved bundles remain inspectable, without rebinding ([compatibility effects](../tectonics/docs/I02_WORKFLOW.md#8-evidence-effects)). | [I02 contract](../tectonics/docs/I02_COMMON_STATE.md), [I02 workflow](../tectonics/docs/I02_WORKFLOW.md), [integration plan](../tectonics/docs/INTEGRATION_PLAN.md#i02--common-state-exchange-transactions-and-accepted-time-controller) |
| 3D regional mechanics and evolution | Fixed-box Q2/Q1 full-stress Stokes with first-order donor-cell transport and conduction. The reviewed matrix-free multigrid method (I07.2 solver scaling) and the corrected automatic `auto` choice between it and the assembled GMRES route are integrated locally; `auto` is the default for new runs. Under the default 256 MiB budget the assembled route alone refused every 7x7x7 cube; `auto` uses multigrid wherever it has been shown to converge and fits (up to about 11x11x11), and GMRES outside that range. Auto restart binds the admitted solver set; temporary memory pressure refuses rather than rerouting. Same equations, gates and outputs; explicit methods are unchanged. First-order transport remains strongly diffusive at these resolutions. Workflow-timing r5 supersedes r4. | [Mechanics](../tectonics/docs/REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse), [multigrid](../tectonics/docs/REGIONAL_MECHANICS_3D.md#matrix-free-multigrid-candidate-i072-solver-scaling), [automatic choice](../tectonics/docs/REGIONAL_MECHANICS_3D.md#automatic-choice-between-gmres-and-multigrid-methodauto), [evolution](../tectonics/docs/REGIONAL_EVOLUTION_3D.md) |
| Repair batch R1 (output integrity) | Integrated locally: scale-invariant 3D Stokes acceptance gates, a free-surface relaxation timestep gate and shared interval ends, thread-safe prepared geometry, a New World column envelope, no fabricated case 1a pressure, membership-derived execution identity including dtype layouts/metadata, and gauge-aware plate torques and port masks. Fresh workflow-timing r2 and finite-admission r5 supersede the affected receipts without rewriting them. No tolerance was relaxed and the step ceiling is unchanged. | [3D mechanics](../tectonics/docs/REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse), [W07 surface](../tectonics/docs/W07_SURFACE_STRENGTH.md), [New World evolution](../tectonics/docs/NEW_WORLD_EVOLUTION.md) |
| New World, steps 1–7 | Seeded request, plate layout, crust, motion, regional evolution, save/load and portable bundles are implemented. The Step 7 r2 and bundle r2 receipts are historical; the Step 7 case matrix is current. | [Combined acceptance](../tectonics/docs/NEW_WORLD_ACCEPTANCE.md), [bundle](../tectonics/docs/NEW_WORLD_BUNDLE.md) |
| B1 boundary diagnostics | One matched original/prototype comparison against PB2002 development at 100/250/500 km. Descriptive, not realism acceptance; the prototype's motion was not refitted. | [Method and checkpoint](../tectonics/docs/NEW_WORLD_MOTION.md#matched-boundary-diagnostics-roadmap-b1), [receipt](../tectonics/evidence/boundary-kinematics-r1.json) |
| B2 causal generation | Diagnosis only: saved worlds keep their initial conditions and crust does not shape the plate layout. No producer fix; the owner rejected post-generation fairing as the realism fix. | [Diagnosis](../tectonics/docs/NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design) |
| W01–W12 components | Implemented components with dated method records. Their receipts describe the runs they record; many bound sources have changed since. | [Reader guide](../tectonics/docs/HOW_TECTONICS_IS_MADE.md), [plan status](../tectonics/docs/TECTONICS_PLAN.md#current-implementation), [validation](../tectonics/docs/W10_VALIDATION.md) |
| Full test suite | No current full-suite pass is claimed on any platform; see below. | [Environment and `verify.py`](../tectonics/README.md#environment) |
| Tested environment | Windows AMD64 CPython 3.12.14 pins and a clean-install receipt are current. Linux and Python 3.13 are not recorded environments. | [Environment guide](TECTONICS_ENVIRONMENT.md) |
| Windows desktop | Atlas Desktop 0.1.0 (unsigned) was built and checked on Windows. A rebuild needs the UI owner's 33-file snapshot, which is not in this repository. | [Desktop README](../desktop/README.md) |
| Wider generator and runtime | R31 connected generator, R12 runtime and the bounded native terrain R5 storage/session route; the 18 categories have entry points, not accepted systems. The retained R5 branch/storage measurement (3.696854 to 0.680990 s and 7,996,951 to 879,786 added bytes over three matched branch comparisons; ordinary intervals 0.60% slower) is a recorded result, not a new run. | [Code route map](CODING_SAFETY.md), [R5 operations](R5_OPERATIONS.md), [independent development](INDEPENDENT_DEVELOPMENT.md), [categories](../README.md#the-18-modelling-categories) |
| Other modules | Scopes for the 17 non-tectonics categories are planning only. | [Module scopes](MODULE_SCOPES.md), [product contract](PRODUCT_AND_SCALE_CONTRACT.md) |

## Full-suite status

The latest full run is the external review's Linux, CPython 3.13.13 run of
`tectonics/verify.py` at `577c044` on 28 September: 4,591 tests, 26 failures and 3
errors. The review attributes one failure and two errors to its own omitted W12
demo `--resume` step; those tests passed in a focused rerun after that step. The
remaining 25 failures and 1 error are the three defects above. No second
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
