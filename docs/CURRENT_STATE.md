# Atlas: current development state

**Updated: 29 September 2026. WORKING NON-CANON.** This is the single current
checkpoint: what is current now, with links to the owner documents and evidence.
It is not a progress log, scientific acceptance or a finished world dataset. The
working branch is `remake`; use `git status` and `git log`, not this page, for
commit and push state.

## Active checkpoint

The three repository defects from the 28 September review of `577c044` are
corrected and their focused checks pass on Windows. The changes are local;
no commit, push or new full-suite run is claimed:

1. Six I01 receipt writers wrote CRLF text on Windows, so 13 receipts were
   registered by the digest of a CRLF rendering that no checkout contains. The
   writers now write LF, and the recorded values are corrected through an
   explicit [correction trail](CURRENT_EVIDENCE.md#line-ending-digest-correction-r2).
2. I02.2a moved the I01 solver into package modules, so nine receipts bind an
   earlier tool layout, and the writer fix changes tools that seven more records
   bind. Fifteen new passing receipts were captured, reviewed and registered in
   [dependency order](CURRENT_EVIDENCE.md#successor-capture-after-i022a-and-the-writer-correction).
   Both stale-evidence test failures are resolved; old receipts were not repinned.
3. One finite-admission test expected Python 3.12's exception type. Python 3.13
   raises `TypeError` for the same refused replacement; the test now accepts either
   while still proving that the field cannot be replaced.

A [before-commit guard](CODING_SAFETY.md#before-every-commit) runs the evidence
checks on Git-normalised candidate bytes rather than on the working copy.

**I02:** I02.1 (shared state) is reviewed. I02.2a (one package-owned solver) is
accepted as an ownership refactor, not as new campaign evidence. I02.2b
(continuation) and its prepared-runner ownership correction are now accepted
for the bounded in-memory route. Inspected and caller-owned objects cannot alter
later pieces; reuse and split-run parity pass. I02.3 has not started. Work is
stopped at the owner's I02.2 boundary, not authorised through the remaining I02 steps.
See the [I02 shared-state contract](../tectonics/docs/I02_COMMON_STATE.md).

**Next action:** await owner direction before I02.3. The desktop build's missing
UI snapshot remains a separate delivery dependency. Work follows the
[completion roadmap](ATLAS_ROADMAP.md); planning is not execution authority.

## Current status

| Area | Status | Owner document and evidence |
| --- | --- | --- |
| Evidence register | Each listed receipt is current, historical, superseded or invalid; `python -B tools/check_current_evidence.py` prints the live counts. Current means the declared byte bindings match, not physics, runtime or platform. Unlisted receipts, including all W01–W12 records, are unclassified. | [Evidence guide](CURRENT_EVIDENCE.md), [register](../tectonics/evidence/current-evidence.json) |
| First review-repair batch (A1–A6) | W12 export and surface policy, bundle inspection and staging, line-ending digest corrections, 512-file source capacity, public-path redaction, a tested Windows environment and one status page. | [Repair record](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md), [environment](TECTONICS_ENVIRONMENT.md) |
| I01 physical integration | Method choices, input and ownership contracts and bounded feasibility are selected for all seven MC items. The controls check the code against analytical cases, refinement, conservation and warm/cold parity; they are not independent physical validation, calibration or generated-world acceptance. Full events remain with their I02–I09 owners. | [Closure matrix](../tectonics/docs/I01_CLOSURE_MATRIX.md), [physical contract](../tectonics/docs/I01_PHYSICAL_CONTRACT.md), [reader chapter](../tectonics/docs/how-it-works/06-physical-integration.md) |
| I01 evidence | Fifteen affected controls have passing, current successor receipts, including G25 in the installed pinned Julia/MAGEMin environment. Previous receipts remain intact and superseded. The old separation performance comparison remains historical. | [Coverage today](CURRENT_EVIDENCE.md#coverage-today) |
| I02 common state and continuation | I02.1 and I02.2 reviewed and accepted for their bounded scope, including the ownership correction. No exchange transaction, persisted restart, accepted-time controller or event is implemented by this acceptance. Stopped before I02.3. | [I02 contract](../tectonics/docs/I02_COMMON_STATE.md), [integration plan](../tectonics/docs/INTEGRATION_PLAN.md#i02--common-state-exchange-transactions-and-accepted-time-controller) |
| 3D regional mechanics and evolution | Fixed-box Q2/Q1 full-stress Stokes with first-order donor-cell transport and conduction. At the default 256 MiB budget the largest admitted cube is about 7x7x7 cells, where first-order transport is strongly diffusive. Receipts are historical after package membership changed. | [Mechanics](../tectonics/docs/REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse), [evolution](../tectonics/docs/REGIONAL_EVOLUTION_3D.md) |
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
