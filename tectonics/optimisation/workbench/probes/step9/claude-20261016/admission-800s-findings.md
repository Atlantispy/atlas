# Why route (1)'s admission takes about 800 s on composed-r2 (16 Oct 2026, 12:39 BST)

"Steps 8-9 runner and heat". Every figure was MEASURED on this machine today, read-only, on the IV1 starting state.

## Answer
- **The phase is the initial metrics.**
  - On composed-r2, route (1)'s phase "initial-physical-and-thermal-metrics" is 99.9% `initial_metrics`: 1,002.5 CPU-s.
  - The spatial owner, exterior inputs and workflow identity together take 1.3 s.
  - The timed run reproduced run A's workflow ID `9ecd96b8…`, so it repeated run A's admission exactly.
- **Inside initial_metrics, the physical bounds take nearly all the time.** That is `enclose_initial_partition`, 969 initial component queries. The thermal mesh takes about 35 s in every arm (the store's last write lands about 35 s before the end).
- **The cause is the coordinator's D1: RC1 items 11 and 15 off, r7 behaviour restored.**
  - Item 11 off: `k = depth % 3`, the r7 cyclic split axis, replaces `_component_longest_side`.
  - Item 15 off: no padded containment for inexact poses.
  - The initial queries carry a relative-error target, so they subdivide far more without these two items.
  - The IV1 endpoint replays carry no relative target, and there items 11/15 off cost no more (95-99 s against 110 s).
- **Not the cause:**
  - the helpers: composed-r1's and composed-r2's give identical leaves and times on the same native tree;
  - source handles: reuse.py `7dfdf209` is the same in composed-r2 and srchandles-r2;
  - dev-timing: checkpoint-only; the run without it was slower, because the machine was busier;
  - the work outside initial_metrics: 1.3 s;
  - WP20: it does not fire on relative-error queries;
  - WP23: gmpy2 2.3.2 is installed, so its route is the fast one.

## Evidence

| arm (native tree + helpers) | initial_metrics CPU-s | leaves (969 records) | other busy CPUs |
|---|---|---|---|
| a0: srchandles-r2 (RC1 + source handles; items 11/15 ON) + composed-r1 helpers. Same bounds_id as the geometry chat's 285 s run | 421.8 | 120,657 (p90 401, max 1,581) | 7.6 |
| a2: srchandles-r2 + composed-r2 helpers | 420.6 | 120,657 (identical) | 7.6 |
| adm1: composed-r2 (items 11/15 OFF) + composed-r2 helpers | 1,002.5 | 386,715 (p90 1,106, max 5,262) | 6.4 |
| smoke s2: run A, root reader and run B (composed-r2) | about 800 / 929 / 975 s phase | 386,715 each; same 969 keys | quieter |

- The leaf ratio is 3.2×. The CPU ratio is 2.4× under load; quiet, it is about 2.8× (800 s against geometry's 285 s).
- Today's machine load inflated the control from 285 s to 422 s (Stellaris, geometry parity, storage tests).
- Paths:
  - per-part times: `R/L/adm1/report.json` and `R/L/adm2-a0`, `R/L/adm2-a2`;
  - leaves: `measure_store_leaves.py` on each `initial-measurements.sqlite`;
  - code: `diff_by_function.py`, on srchandles-r2 against composed-r2 `integration_differential_geometry.py`.
- Arm a1 (composed-r2 native with composed-r1 helpers) cannot import: the composed-r2 native tree needs `compact_restart_patch`.

## What this means for items 7 and 10
Later-step impact (corrected 12:58):
- Route (1) pays this admission in four processes: run A, the root reader, run B and the interval-1 reader.
- Whether interval 2 and later pay it depends on the interval-2 ordinary-head path, which is not built yet. It pays only if that path re-derives the admission rather than restoring the owner from the store.
- "Later run(k)" below holds only in that case.
- **Item 7 is close to free and exact.**
  - Every route (1) process writes the identical 969 records under identical keys. The key covers the full execution identity, the support, the cell, the accuracy and the work ceiling.
  - `integration_dual_geometry.cached_initial_component` already reuses a verified ArrayStore losslessly. "A hit retains its original query/work provenance". Corrected 13:15 (review condition 8): a hit re-checks each stored field's consistency with the request; it does not certify the geometry again.
  - So a producer handed a SHA-256-pinned copy of run A's store hits on all 969 queries. Today that producer is run B (and the reopen smoke), once per lineage. A later run(k) benefits only once such a route exists and is reviewed under the same rules.
  - Estimates: mine 50-60 s, the reviewer's 80-100 s (two strict verify_boundary calls and a support-record parse per hit), against about 800 s. That leaves the thermal mesh (about 35 s), the partition (3 s) and about 969 store reads. Report the MEASURED hit-arm time from q08, not either estimate.
  - The reader still recomputes everything with a fresh store, as ruled.
- **Item 10 shrinks to phase 2.** It hides the reader's about 930 s admission behind the advance. Phases 1 and 3 overlap a producer's admission, which item 7 brings down to about 60 s.
- **For the 5-minute target:**
  - the reader's recompute (about 800-930 s) cannot hide behind a short advance;
  - the 969 initial component queries are independent and run serially;
  - a parallel initial-metrics route with the existing endpoint worker pool, exact (same queries, same assembly order), would cut every recomputing admission (run A, every reader) to about 1/6 with six workers. This is the geometry chat's code.
- **D1 itself:** re-enabling items 11/15 for the initial metrics alone would bring the queries back to about 285 s. But it changes the start-state bounds against r9 (the ledger's level 2). I do not recommend it; items 7, 10 and the parallel route recover the time without changing a number.
