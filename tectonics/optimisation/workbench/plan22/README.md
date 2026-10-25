# Plan22: optional bounded page carry

**WORKING NON-CANON. The current reader meets its private selection rule; final-runtime receiving remains open. Issue #48 remains open.** An earlier reader measured a 20.9% mean reopen reduction in a real interval-1 A/B ABBA comparison. That measurement does not qualify the newer port or final/public composition. The current receiving port has passed q120's declared combined S3/L3/S1A qualification and its separate admitted private corrected-reader comparison. Actual selected private final-generation/IV qualification and final integrated-outcome acceptance remain outstanding. The private result does not establish a measured public/final stack or promote a runtime default.

L3 keeps verified immutable page pins between outer read batches of the same view. Adoption happens only after the next verified read has entered; per-access freshness and cancellation and the closing check remain. Carry is bounded to 128 pages and 10 MiB booked per view, with a 32 MiB process bound. The existing 64 MiB page-cache quota remains. Unpinned pages are evicted first; idle carry yields when those pages are insufficient. Close, failed entry, fallback and exceptional exit release reusable carry without leaving traceback-owned data unfunded.

The [plan](../../plans/plan-22-storage-l3.md) defines the full memory contract and the predeclared selection rule. [SOURCE-MAP.json](SOURCE-MAP.json) records public and private source identities separately; [RETAINED-RESULTS.json](RETAINED-RESULTS.json) scopes the checks.

## Receiving repairs

The first candidate's carried pins could not be evicted; an existing storage test caught that regression. The second candidate added a reclaimer and passed its 15 L3 controls and 13 planted-fault controls. Receiving review then found further defects:

- The touched-page list retained wrappers after they left the 128-page registry. A 4,096-page synthetic batch retained 4,096 touched wrappers, including 3,968 closed owners, while the logical reservation stayed unchanged. A deduplicated set now removes closed pages.
- Popping the carry before the required batch-entry reservation hid it from the pressure reclaimer. A budget that admitted the original reader could then refuse the candidate. Optional carry now remains reclaimable until verified entry succeeds; adoption still happens only afterwards.
- The mesh close hook dereferenced cleared arrays on repeated close. It now preserves the existing repeated-close behaviour and still checks outstanding borrows before releasing anything.
- The proposed mesh snapshot predated the capture writer's `iter_legacy_json(encode=...)` interface. The public port adds the corrected close hook to the current mesh implementation, preserving its funded encoder and separate punctuation yields.

The private D10 candidate preserves its original comparison base and has its own source identity. The public candidate composes the current combined source and Plan21 lazy rows. Its mesh is an explicit port onto that current base, not a byte-identical export of the older private mesh. Historical measurements do not automatically transfer across these compositions.

## Construct a separate source candidate

From the repository root, using Python with the standard library:

```text
python -B tectonics/optimisation/workbench/plan22/build_candidate.py --repo . --output NEW_DIRECTORY
```

The constructor authenticates the existing Plan21 and combined-source chain, checks both replacement bases and all three overlay members, and produces a new `src` / `helpers` layout plus its source manifest. It refuses changed pins, unexpected members and an occupied output. No scientific source is executed during construction. The original selection and installed package are unchanged; the manifest grants no runtime, interval, default or scientific authority.

The L3 test imports the selected `test_item14_page_layer` and `test_record_tables` helpers and requires the compatible science environment. It belongs in an explicit synthetic fixture with both selected import roots and temporary files outside the source tree. It is not ordinary public-suite discovery. The source-only builder tests use the standard library.

## Corrected-source checks

- The corrected reader passes 18/18 private-base L3 controls; targeted negative controls reject the two reader defects and pre-entry adoption.
- Mesh close/encoder methods pass 11 bounded cases across the private and combined ports; three negative controls reject the old defects. These use inert ownership fixtures.
- Eight standard-library builder controls pass. The actual constructor emits 647 authenticated source files.
- The complete public candidate passes all 37 composed controls: 18 L3 and 19 Plan21 S3, including sealed-segment refusal and funding. All imported project modules resolve inside that candidate; its source files remain unchanged.

## Evidence limits and remaining work

The original 11-module comparison had equal base/candidate results, including shared failures in compact-store, segment-store, pending/recovery and mesh-v3 tests. It was not an all-green run. The two long suites passed 9/9 and 10/10 on the earlier private candidate; that evidence remains attached to those bytes. Historical lint introduced no findings in the two product modules, while the new test file had two SIM117 findings. The public results record distinguishes those observations from corrected-source checks.

The profile-based 6.25% opportunity is an estimate. The later measured comparison reduced mean reopen time from 16.266 s to 12.864 s for its tested earlier reader, with exact result identity preserved; the cause of the larger gain remains unproven. The prior B17/item14 speed measurements are separate. A corrected-reader comparison must use an authenticated request for the exact candidate tested; an older request is not rebound to a successor. Final-generation B17/item14 inclusion and final runtime selection remain open with their respective work. WP12 remains UNBUILT/OFF.

## Qualification-gate repair

The [combined gate successor](gate/README.md) integrates the receiving repairs
for failed child exits, skipped coverage and an empty changed suite. Its explicit
location configuration retains code-owned source and port pins, including the
corrected guarded-read component. Its portable fault controls test the actual
gate functions. The retained q120 result documented there is PASS for the declared
S3/L3/S1A scope. The historical public builder, [SOURCE-MAP.json](SOURCE-MAP.json)
and `record_views.py` (`e31a3a73`) above remain unchanged. The [current receiving
rows](../plan21/L3-SOURCE-MAP-r3.json) separately bind `record_views.py` `e86e9882`
and its companion rows. The separate source-bound private timing condition is
now met. Actual selected private final-generation/IV qualification and final
integrated-outcome acceptance remain outstanding; gate PASS alone does not
select a runtime default or establish a timing gain.
