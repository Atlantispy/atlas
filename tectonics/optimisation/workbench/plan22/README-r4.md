# Corrected-reader L3 source selection

Status: WORKING NON-CANON. The controlled corrected-reader comparison selects L3. This additive constructor selects the current reader in a separate 647-member source layout; it grants no runtime admission, default promotion, final-generation or scientific acceptance.

## Mechanism and receiving boundary

A view carries the same verified immutable page objects between outer batches, adopting them only after its next verified-read entry. Every use retains freshness/liveness/cancellation checks. Record close releases segment carry even if access objects remain; mesh close releases column owners and preserves repeated close and its streaming encoder. Existing page allocations fund the carry: 128 pages and 10 MiB booked/view, 32 MiB booked/process, no extra byte reservation and the existing 64 MiB cache quota.

For an outermost store-set read, carry follows the closing freshness check. A view batch nested inside another store-set verified read can carry before the enclosing closing check. An enclosing refusal can leave carry present; the next verified-read entry refuses before adoption. This is the compact-store nested-consumer boundary, not permission to refresh a changed token. Failed-frame/traceback data remain funded. Existing source/combined qualification is reused within those exact bindings.

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

Existing record, mesh and compact-store caller integration has final component acceptance. Individual L3 verification after assembly, including assembled/folded receiving and final L1 checks, was cancelled by the owner; it is not a verification pass. Assembly and fold owners still deliver and check their own outputs. The selected runtime/default, WP12 UNBUILT/OFF and other execution/scientific holds remain unchanged. See the [method explanation](../../../docs/how-it-works/03-coupling-and-reliability.md#carry-verified-pages-between-read-batches) and [historical candidate](README.md).
