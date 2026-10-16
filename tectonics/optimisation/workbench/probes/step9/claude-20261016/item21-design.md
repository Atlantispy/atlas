# Item 21 design: fresh interval N >= 2 from the adopted interval N-1 head

16 Oct 2026, "Runner pipeline and final integration". Decisions received (section at the end);
implementation tests-first. Item 11's commit-window stages (FD f328f314) also go into D's
ordinary branch; the migrated branch keeps its six.
Read: D = prepared_interval_driver.py c4f5c4fb, F = run_fresh_interval.py 8e825d29,
G = reopen_fresh_restart.py c36ad987, L = launch_fresh_interval.py ecefde9a,
FD = fresh_interval_driver.py 40a84061, width_gate.py 039ae75a; map S/item21-map.md;
approved route S/design-route1-steps2-3.md ("Interval 2 and interval 3 runs use the run-B
pattern (open, then advance) from their promoted head").

## Shape (option A of the map)

Interval N is run B one interval further, in its own process:

1. preflight (L): stage N-1 ADOPTED (not the width-gate stop), adopted(N-1) pinned by SHA.
2. runner (F, mode `interval`, new explicit `interval=N`): the item 7 seed (from the root
   stage, unchanged), the same deterministic admission, `open_catalog`, then the **sealed-lineage
   gate** (below), `start_next_interval`, FD opens the workflow (native `_refresh` walks
   root -> N-1), D advances once through r9's continuation seam (`continuation_pressure_force`,
   the same step the migrated successor runs at sequence 2), bounded pre-seal, seal without
   promotion, runner/sealed records, exit.
3. reader (G, generalised to N), finalise, adopt (`adopt_and_promote`), exactly as interval 1.

Interval 1 is untouched (FD.advance_first_interval, initial pressure/force check). N = 1
keeps every current path, label and record; new fields appear only for N >= 2.

## The sealed-lineage gate (new; refuse on any mismatch, no fallback)

What it protects: interval N may start only from the head the independent reader passed and
the adopter promoted, never from a store whose catalog or records were changed, re-sealed or
belong to another lineage. Cost: reading 4N small JSON records and one catalog hash.

In F, before `start_next_interval` (generalises `require_promoted_root`, F:386-405):
- `--parent-adopted-sha256` (explicit argument, like the item 7 pins): adopted(N-1) is read with
  that SHA. Never derived by the runner from the directory.
- for every k = 0..N-1: runner(k), sealed(k), verdict(k), adopted(k) by schema;
  sealed.runner_record_sha256 == sha(runner(k)); verdict PASS for mode(k), interval k, same
  runner SHA and entry; adopted status ADOPTED, interval k, same entry,
  verdict_sha256 == sha(verdict(k)), runner_record_sha256 == sha(runner(k)).
- links, k >= 1: runner(k).root_runner_record_sha256 == sha(runner(0)); same workflow_id;
  previous_endpoint.head == parent head (root key at k = 1, runner(k-1).advanced_endpoint.head
  after); previous.intervals == k-1, advanced.intervals == k;
  sealed(k).expected_catalog_digest == adopted(k-1).catalog_digest (interval k was sealed against
  exactly the catalog that had k-1 adopted); k >= 2 also runner(k).parent_runner_record_sha256 ==
  sha(runner(k-1)) and runner(k).parent_adopted_sha256 == file hash of adopted(k-1) (new fields).
- catalog: file hash == adopted(N-1).catalog_sha256 BEFORE open; after open
  store_set.catalog_digest == adopted(N-1).catalog_digest, head == sealed(N-1).entry,
  head.head == runner(N-1).head, store.workflow_id == runner(0).workflow_id.
- output: a `lineage` record (schema atlas.fresh-interval-lineage.v1: interval N-1, workflow_id,
  root_key, head_key, catalog digest and SHA, per-k runner/verdict/adopted SHAs and file SHAs),
  written to run.json and passed down.

In D, at the start of the advance (before any physical work), the live workflow equals the
lineage: workflow_id, root key, head key, head kind 'successor', head sequence ==
inspect()['intervals'] == N-1. F binds records to the catalog; D binds them to the opened head.

## Per-file changes

D (shared with the migrated route; its SourceShape pins stay true):
- new keyword-only `lineage=None, joined_module=None`; RUN's bind (RUN:794-799) and every
  migrated check stay byte-for-byte in the `base is not None` branch (the pinned texts at
  test_prepared_interval_driver.py:56-64 keep their order before `record.update(original_target=`).
- ordinary branch (`base is None`): CollarWorkflow, `getattr(workflow, '_migration', None) is None`,
  same budget and query-checkpoint ownership tests; the lineage gate; an InitialWorkloadState
  case refuses (a frozen migrated workload never enters an ordinary lineage); duration ==
  workflow._head['advance']['duration_s'] (the parent's own advance record, which the native
  `_refresh` checked against the stored clocks; the migrated rule reads the same field from the
  base endpoint's head).
- joined: the migrated branch keeps `import private_heat_original_joined_r6 as joined`; the
  ordinary branch binds `joined = joined_module`, which must be private_heat_original_joined_r8
  (the module interval 1 ran). DECISION D8 below. The single `with` keeps `joined=joined`.
- `record['lineage_gate']` added; everything else unchanged.

FD: new `advance_successor_interval(m, *, store, expected_root, lineage, ...)`: same admission,
`Workflow.open`, ROOT_IDENTITY vs run A, head == lineage head, capture before/parent/root_bytes,
open `query_checkpoints(a.heat_execution)`, call D (base=None, lineage, joined_module=m.joined),
then `finish(...)` with the workflow open. It does not open the observer or the thread limit
(D's single `with` does).

F: explicit `interval` (N >= 1; output `run-interval` for 1, `run-interval-%04d` for N >= 2);
the lineage gate; `_advance` seals interval N; runner record extra for N >= 2 adds
parent_runner_record_sha256, parent_adopted_sha256 and `lineage`.

G: interval-N checks: completed sequence == N; previous/advanced intervals N-1/N; previous.head
== the lineage head; `_successor` parent key/digest from the parent head's metadata, sequence N;
`validate_fresh_lineage` parent clock from the parent head (root_is_parent ->
parent_is_adopted_head); producer_inputs re-runs the F lineage gate (shared function);
`adoption_inputs` maps interval -> mode without `MODES[interval]` (IndexError at N = 2 today);
reader output `reopen-interval-%04d` for N >= 2.

L: `--interval N` for the interval stage; stage record `stage-interval-%04d.json` for N >= 2;
preflight requires stage N-1 status ADOPTED (ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2 refuses:
"interval 2 then needs the coordinator and Michael") and passes adopted(N-1)'s SHA from that
stage's adopt step.

## Tests first (refusals before the passing case)

D: ordinary head + lineage accepted by stand-ins; refusals: base and lineage both or neither,
`_migration` on an ordinary call, each lineage field wrong, InitialWorkloadState on ordinary,
joined_module not r8, duration differing from the head's advance. Existing D tests unchanged.
F: each broken link (runner, sealed, verdict, adopted tampered; wrong expected_catalog_digest;
catalog hash; head != sealed(N-1) entry; wrong pin), N = 1 records unchanged. G: interval-N
receipt, parent and adoption mapping. L: N-1 ADOPTED requirement, gate-stop refusal, pins passed.
No real run in this item: a real interval 2 needs fresh intervals 0 and 1 first (tickets, go).

## Decisions (coordinator, 16 Oct 2026: "Build with the recommended choices")

- D8, joined module for N >= 2: r8 (approved; "switching to r6 would change the lineage's
  identity for no gain"). The fresh lineage runs one joined code for every interval.
- Width gate after interval N >= 2 (approved): the same linear rule one step on, from the
  parent's verdict widths: W(N+1) = 2W(N) - W(N-1) <= 50% and W(N+2) = 3W(N) - 2W(N-1) <= 100%
  of the 1 MiB limit; stop before N+1 if either fails. It can only refuse, never pass more.
  Projection on the watch numbers (W2 about 43-49%, W3 62-73%, W4 80-98%, so W1 about 24-25%):
  before IV2, W2 43-49% <= 50% and W3 62-73% <= 100%: passes (1-7 points of margin on W2).
  Before IV3, projected W3 62-73% > 50%: STOPS, so interval 2 runs and interval 3 does not
  start (nor IV4). It passes only if the measured W2 is at most (50% + W1)/2, about 37%; the
  100% half (W4 = 3W2 - 2W1) would allow W2 up to about 49%. So, on these numbers, Michael's
  width options are needed before interval 3, not interval 5 (W5 about 100-120% is where the
  1 MiB limit itself would be crossed).
- Review-adopted parent (approved: allowed and recorded, on two conditions):
  (1) the approval is inside the hash-pinned lineage the gate checks, and any mismatch refuses.
  adopted(k).review_approval_sha256 pins approval(k). adopted(k) is itself pinned: k = N-1 by
  the explicit argument, k < N-1 by runner(k+1).parent_adopted_sha256. The gate re-reads approval(k)
  at that SHA and re-runs the reader's review_approval checks: the sealed file SHA, the verdict
  SHA, an approver, cause 'checker-defect', and the diagnosis file hash. runner(k) and sealed(k)
  may carry REVIEW_STATUS only then, and without the field they must carry the ordinary sealed
  status. The lineage record carries per-k approval and diagnosis SHAs.
  (2) No reliance on an identity boundary at compact seal_and_promote/adopt. The Release-mode
  thread's gap B13 (H/compact_restart_store.py:616/631) is that none exists there. Every binding
  is re-checked by the gate itself, from the records and the opened catalog: file hash before
  open; digest, head and workflow ID after.

Later-step impact: interval 3 is the same code with N = 3; item 10 phase 2 and item 9 are
untouched. Interval 3: no new route; its start gate follows the measured IV1/IV2 peaks.
