# Atlas: current development state

**Updated: 26 September 2026. WORKING NON-CANON.** This is the current
development summary, not scientific acceptance or a finished world dataset.
The active repair checkout is `remake`; the changes below are local and not yet
committed or pushed. Check the actual checkout before continuing.

## Active checkpoint

Work follows [the completion roadmap](ATLAS_ROADMAP.md): repair reliability and
evidence, then correct tectonics realism before expanding the other modules.

| Work | Current delivery status | Detail |
| --- | --- | --- |
| A1: review repairs | First repair batch implemented and checked: W12 export/surface policy, bundle inspection/staging and line-ending digest corrections. | [Repair record and exact checks](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md) |
| A2: evidence status | Checker and bounded register integrated. Historical runs are not relabelled as current numerical acceptance. | [Evidence guide](CURRENT_EVIDENCE.md) |
| A3: source capacity | Limit raised from 128 to 512 Python files, retaining complete hashing and the 2 MiB inventory bound; focused regressions pass. | [Capacity repair](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md#a3-follow-on-bounded-source-inventory-capacity) |
| A4: public paths | Three W07 historical reports redacted with explicit old/new digest provenance and a regression guard. | [Publication repair](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md#a4-follow-on-public-path-redaction) |
| A5: tested environment | Windows AMD64 CPython 3.12.14 pins and clean-install evidence reviewed and integrated: all 39 packages install, metadata/dependency checks and ten environment tests pass, and compiled-library/basic rendering smoke checks succeed. Linux and an Atlas visual workflow remain unverified. | [Environment guide](TECTONICS_ENVIRONMENT.md) |
| A6: status and change granularity | One current summary replaces the accumulated status log; no separate archive copy. Scoped delivery and evidence-impact guidance recorded. | [Change procedure](CODING_SAFETY.md#5-source-only-check-and-change-procedure) |
| B1: matched boundary diagnostics | Tool integrated; one retained original/prototype comparison at 100/250/500 km against PB2002 development. Portable inputs, signed components and declared exclusions retained. Prototype motion is not refitted; this is not realism acceptance. | [Method and measured checkpoint](../tectonics/docs/NEW_WORLD_MOTION.md#matched-boundary-diagnostics-roadmap-b1) |
| B2: causal-generation diagnosis | Code trace and a bounded two-candidate experiment completed. New World saves initial conditions; crust does not affect its plate layout. No producer fix implemented. | [Causes and research](../tectonics/docs/NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design) |
| Complete tectonics integration | Full I01–I12 plan now covers missing physics, conservative transfers, feedback, global generation, W12/New World/UI/consumer lifecycle, resources and acceptance. Planning only; all integration increments remain open. | [Integration plan](../tectonics/docs/INTEGRATION_PLAN.md) |

Claude's A5 follow-up is now integrated. It installed into a separate ignored
environment without modifying the scientific environment. The retained receipt
establishes a Windows installation and library smoke check, not native restart
compatibility or scientific acceptance. Linux was unavailable and none was installed.
The owner rejected post-generation fairing as the realism fix, even
when applied to native geometry. Its integration was stopped before source edits.
The owner requested the complete integration plan before implementation. Next
implementation scope is **I01: end-to-end contracts and physical closure choices**;
I02 then supplies the common state/transaction layer. The prior narrow B2 ordering
is superseded. Starting crust, ocean history, thermal/mechanical feedback and
vertical response must share the evolved world. W12's limited column assembly
and exports do not establish completion. No tectonics implementation, simulation,
commit or push was started by the plan or installation-evidence review.

## Evidence: what the results establish

The [registered evidence](../tectonics/evidence/current-evidence.json) currently
classifies **13 records: three current, nine historical and one superseded**.
Current items are the Step 7 r2 *case matrix* and the B1 diagnostic tool/input
bindings, plus the Windows installation receipt bound to its package-version record;
none establishes physical simulation acceptance. W01-W12 records outside that
bounded register remain unclassified,
not implicitly accepted. The checker verifies declared bindings, not physics or
every transitive dependency.

Step 7 r2, bundle r2 and the complete motion-frame r2 receipt are historical after
native or unbound integration dependencies changed. Their measurements remain
evidence for the original snapshots. Preserve the original receipts and runtime
identities; do not silently repin them. Focused repair checks and their exact
scope are in the repair record above. No new simulation is implied by this page.

## Latest route

- **Scientific reader guide:** [How tectonics is made](../tectonics/docs/HOW_TECTONICS_IS_MADE.md)
  explains individual methods within W01-W12, seeded worlds and the separate
  experimental dynamics route. It connects plain-English explanations to research,
  code and scoped evidence; documentation does not renew numerical acceptance.
- **Native tectonics and new-world adapters:** substantial W01-W12 implementation,
  supported regional evolution, saved-result inspection and project/bundle
  handling. Use the [tectonics ownership and implementation plan](../tectonics/docs/TECTONICS_PLAN.md)
  and the [active code-route map](CODING_SAFETY.md), not a historical "next step".
- **Wider generator:** implementations through `engineering/work/generator_upgrade_r31/`,
  with component entry points across 18 categories. That is not 18 complete or
  scientifically accepted systems. See [category scope](../README.md#the-18-modelling-categories).
- **Execution and retained terrain:** runtime R12 and retained connected scheduling;
  native terrain R5 is the bounded storage/session route retaining R1-R4, not the
  entire generator or a new general solver. Shared histories are dependencies.
- **Public component development:** [independent development](INDEPENDENT_DEVELOPMENT.md)
  uses explicit new public bindings and selected fixtures, not historical native
  restart or a full world-generation demonstration.

The retained R5 branch/storage measurement was 3.696854 to 0.680990 seconds and
7,996,951 to 879,786 added bytes, across three matched already-loaded branch
comparisons. Ordinary interval timing was 0.60% slower. This remains a recorded
branch/storage result, not a new timing run, solver speedup or world-scale forecast.

## Boundaries

Generated-world tectonics realism is still open: grid-shaped boundaries,
restrictive starting-crust shapes and an ocean-age field needing explicit history.
The saved boundary helper remains a prototype, not integrated acceptance.
Mountain/terrain realism and a complete whole-world/whole-year run are not accepted.

R4.4 remains held and incomplete. No broad scientific campaign, change to physical
tolerances, removal of source/runtime guards or increase to the retained native
terrain 256-interval ceiling is authorised here. Do not add or multiply unrelated
historical speedup ratios into a whole-generator claim.

Read-only inspection and exact native continuation have different requirements.
Private inputs, codecs and runtime dependencies are not supplied by a public
source snapshot; byte recovery alone is not a restart. Diadem canon, local
integration, Git commit and publication remain separate states.

## Maintaining the current view

The [product and scale contract](PRODUCT_AND_SCALE_CONTRACT.md) remains the product
direction, not a completed capability inventory.

Update this page in place. Do not keep dated copies or accumulate superseded
status updates; Git history can retain committed document versions. Keep method
details and necessary test receipts in their existing records, not duplicate
status archives. Older code still imported by the active route is not redundant.
Make small descriptive commits only when authorised, with their evidence impact
stated; see the change procedure. No old result becomes current just because this
summary changes.
