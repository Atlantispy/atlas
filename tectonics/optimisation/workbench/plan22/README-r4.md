# Corrected-reader L3 source selection

Status: The controlled corrected-reader comparison selects L3. This additive constructor selects the current reader in a separate 647-member source layout; it grants no runtime admission, default promotion, final-generation or scientific acceptance.

## Mechanism and receiving boundary

A view carries the same verified immutable page objects between outer batches, adopting them only after its next verified-read entry. Every use retains freshness/liveness/cancellation checks. Record close releases segment carry even if access objects remain; mesh close releases column owners and preserves repeated close and its streaming encoder. Existing page allocations fund the carry: 128 pages and 10 MiB booked/view, 32 MiB booked/process, no extra byte reservation and the existing 64 MiB cache quota.

For an outermost store-set read, carry follows the closing freshness check. A view batch nested inside another store-set verified read can carry before the enclosing closing check. An enclosing refusal can leave carry present; the next verified-read entry refuses before adoption. This is the compact-store nested-consumer boundary, not permission to refresh a changed token. Failed-frame/traceback data remain funded. Existing source/combined qualification is reused within those exact bindings.

## Carry memory, refusal and selection contract

Carry is restricted to the same view and segment; keys are(name,start), not a
global interval/offset cache. At outermost close, finish freshness checking before
carrying and trim oldest pages to view/process bounds. The nested enclosing-read
qualification above remains explicit. Optional carry stays reclaimable while the
next required entry reservation is attempted; adopt only after entry succeeds,
never serve a page before it. Failed entry closes remaining carry and propagates.

Per-use liveness/freshness/cancellation and verified-read closing checks remain.
Outside a batch _batch_pages is absent and ordinary verification runs. Close,
failed entry, uncached fallback, trim/cap refusal or scope close drops reusable
carry; exceptional exits retain no reusable outer carry, while traceback-held
data keeps its paid ownership. Evict unpinned pages first, then idle carry and
evict again if necessary; busy views are skipped with a nonblocking lock.
The deduplicated touched-page set removes evicted/closed wrappers, bounding active
batches as well as carried registries. A carried hit skips only the repeated
typed digest of the same pinned immutable object, never freshness.

| Bound | Contract |
| --- | --- |
| Pages/view | 128 |
| Booked/view | 10 MiB, trim oldest |
| Booked/process | 32 MiB, locked accounting; excess drops/refuses and is counted |
| Existing cache | 64 MiB unchanged |
| Additional reservation | None; existing registry/holder ownership funds lifetime |

Booked bytes are registry plus each holder's charged_bytes, including underlying
allocation and holder overhead, not merely carrier-only bytes. Do not add the
cache parent again. Two views may conservatively count one allocation twice.
The registry requests266,240 B before owner overhead;128*65,536 B is at most8 MiB
raw. Raw/booked bytes differ. Retained-scope, run and physical guards are unchanged.

The predeclared ABBA component rule requires both B samples beat both A samples
and mean gain exceed the larger within-arm range; every sample must preserve exact
result/five fields, source binding and zero budget after close; B misses may not
increase, required/carry refusals must be zero, and peak RSS must be<=A+48 MiB.
Regression means slowdown beyond the larger range; otherwise remain uncertain
unless every condition passes. Report raw times/ranges, misses, carried raw/booked
and pinned peaks, RSS/tree observations, trims/refusals/drops by reason.
Reduced verification count alone is not net benefit. The current constructor's
separate conservative0.2009 minimum and exact module bindings below remain binding;
the 1% opportunity gate and WP12's5% rule do not replace them.

## Historical opportunity and constructor

The count probe had65,995 lookups,57,673 hits and 8,322 misses(8,294 native/28 small),
with 57,424 cross-batch hits(31,814 small/25,610 native),7,183 outer batches on one
segment and no outside-batch lookup; identity/five fields matched. Simulated128-page
LRU was locality evidence, not retained memory/lifetime proof. Multiplying those
hits by 28.776 microseconds verifier cost gave 1.652 s/6.25% of 26.458 s: an inflated
profile-based build opportunity, not measured L3 gain or I/O-wait fraction.
The broader5.242 s/19.8% included lookup/scratch/key/pin/cursor costs. Earlier
plain-reopen46.127 s, B17 17.419 s and B17+item14 15.670 s belong to those changes.

The historical build_candidate.py still constructs a separate src/helpers layout,
authenticating Plan21/combined parent, both replacement bases and three overlays,
refusing unknown/changed members or occupied output. It executes no scientific
source. Historical SOURCE-MAP.json and source/result bytes remain unchanged;
build_selection.py below selects the corrected reader separately. Old requests
never bind a new reader by implication.

Receiving defects and their corrections remain part of the method:
- the first carry could not yield pins under pressure;
-4,096 touched wrappers(3,968 closed) escaped the 128-page registry until replaced
  by the self-pruning set;
- popping carry before required entry hid it from reclamation and could reject a
  budget the baseline admitted; leave it reclaimable until entry succeeds;
- repeated mesh close dereferenced cleared arrays; preserve existing close;
- the older mesh predated iter_legacy_json(encode=...); port the close hook onto
  the current funded encoder with separate punctuation yields.

Historical private D10 and public-current-mesh port are different compositions.
The earlier corrected reader passed 18 L3 controls, with targeted negatives for
both reader defects/pre-entry adoption; mesh close/encoder had11 inert cases and
three negatives. Eight standard-library builder controls emitted647 authenticated
files; the composed candidate passed 37 controls(18 L3/19 legacy S3) with confined
imports and unchanged source. L3 tests explicitly require compatible science
environment, selected test_item14_page_layer/test_record_tables, both import roots
and external temporary files, not ordinary discovery.

The earlier 11-module base/candidate comparison retained equal failures in compact
and segment stores, pending/recovery and mesh-v3. It was not all-green. Two long
suites passed 9/9 and 10/10 on their earlier private bytes. Historical lint had no
introduced finding in product modules and two SIM117 findings in the new test.
These observations/debt/skips are not erased by newer41-control qualification.

Earlier-reader ABBA16.266→12.864 s selected that tested reader with exact identity;
its gain mechanism remains unproven and its20.9% is not transferred. The current
reader's20.73% result below has its own authenticated request and module set.
The combined gate repairs failed-child exits, skipped coverage and an empty
changed suite; q120 PASS is limited to declared S3/L3/S1A scope. Legacy record_views
e31a3a73 remains in its historical builder; Plan21's receiving rows separately
bind e86e9882. Gate PASS is not timing/default acceptance.

WP12 stays UNBUILT/OFF: its one eligible reopen has central estimated net-3.1%;
N=2/+0.1% were sensitivity cases, not extra L3 arms. Future sidecar work would need
typed-byte authentication, cache-disabled verification, unused/truncated/extended/
wrong-file refusal, bounded resources and its separate net-of-build/open criterion.
B17/item14 inclusion and final selected generation belong to assembly; changing
record_views needs affected receiving evidence, not a rewritten old result.

## Measured comparison and limits

| Workload/conditions | Baseline mean | Current-reader mean | Reduction | Evidence |
| --- | ---: | ---: | ---: | --- |
| Sealed interval-1 ledger reopen; fresh copies; ABBA; one core; quiet/exclusive | 15.4381 s | 12.2384 s | 3.1997 s / 20.73% | MEASURED on private comparison stack |

A samples 15.4461/15.4301 s; B 12.1238/12.3530 s. Both B samples beat both A samples and the gain exceeds the larger 0.2292 s within-arm range. All seven conditions pass, unchanged originals and exact results are preserved, required/carry refusals are zero and closing budget/booked/raw carry are zero. Misses 8322 -> 8321; hits 57673 -> 247. The actual 0.2073 improvement fraction exceeds the retained 0.2009 requirement.

Each B sample carries 7183 batches / 919424 pages and adopts 7182 times, with no trim. Peak carry is 10133655 B booked / 8141346 B raw; it closes with neither booked nor raw carry. The owned payload job inside the external supervisor records 67.984 s of supervised wall time and a sampled process-tree RSS peak of 339099648 B at 250 ms intervals. It includes the inner driver, guard, bootstrap and reopen descendants, and excludes the outer supervisor, queue runner and launcher/notification processes. The separate queue-command observation is 0.36 GiB, rounded and sampled around two seconds; it includes the outer guard adapter and excludes the queue runner. Both samples can miss peaks between observations and are distinct from an OS high-water measurement; supervised wall time is separate from child reopen timing.

[Versioned evidence](RETAINED-RESULTS-r4.json) binds the exact raw result and current reader. It preserves the earlier reader's complete comparison under historical_d10 and earlier source evidence under historical_reader_r3. The old 20.9% result is not transferred. The timed and selected seven-module key sets match; exactly content_cache, interval_store_set and record_tables differ. This public/final stack was not timed; its whole-interval benefit and final L1 counters remain unproved.

## Construct and check

From the repository root, standard-library Python:

```text
python -B tectonics/optimisation/workbench/plan22/build_selection.py --repo . --output NEW_SHORT_DIRECTORY
python -B -m unittest discover -s tectonics/optimisation/workbench/plan22 -p test_build_selection.py
```

Keep a Windows output parent at most 108 characters on hosts using the 259-character path limit. Existing output is refused. The pinned additive candidate builder keeps the legacy Plan21 constructor and all legacy source/map bytes unchanged; current reader/test exports are reused from Plan21's receiving-l3-r3 paths and the existing published LF mesh is retained. Missing/changed prerequisites fail closed. Construction never executes selected scientific source.

The constructor authenticates the complete parent/candidate, the versioned comparison digest, exact reader and composition bindings, per-sample validity/accounting and conservative timing rule including the 0.2009 threshold. It requires exact selected/timed module membership and the declared three-module difference set. [Selection map](SELECTION-MAP.json), [candidate source map](SOURCE-MAP-r4.json) and [focused checks](CHECKS-r4.json) retain explicit identities. 25 final constructor controls pass; four new intended faults are rejected, without relabelling reused 47 historical mutants as a fresh 51-mutant campaign. 41 actual selected-source controls (22 L3 / 19 legacy S3) pass with 647 files authenticated and project imports confined to the selection; those private science-environment checks are not ordinary public discovery or general runtime compatibility.

Existing record, mesh and compact-store caller integration has final component acceptance. Individual L3 verification after assembly, including assembled/folded receiving and final L1 checks, was cancelled by the owner; it is not a verification pass. Assembly and fold owners still deliver and check their own outputs. The selected runtime/default, WP12 UNBUILT/OFF and other execution/scientific holds remain unchanged. See the [method explanation](../../../docs/how-it-works/03-coupling-and-reliability.md#carry-verified-pages-between-read-batches) and [historical candidate](#historical-opportunity-and-constructor).
