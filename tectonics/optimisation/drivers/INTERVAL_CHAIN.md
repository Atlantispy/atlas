# Fresh-interval chain: start gate, S1 query stages and interval N (item 21)

Status: WORKING NON-CANON. Method note for the driver changes in `run_fresh_interval.py` (F),
`reopen_fresh_restart.py` (RF) and `launch_fresh_interval.py` (L). The module docstrings are the
detailed reference; this note states what the chain changes and where it refuses. This snapshot is
not runnable (see `../README.md`); the private runtime pins are not changed by these files.

## Start gate by need
- The fixed 10 GiB free-memory start requirement is replaced by `start_gate.py`. L decides the gate
  from the named stage records, or a declared booking when there are none, and admits
  it against the machine. The encoded decision rides last in the runner's and the reader's guarded
  command; each child admits it again against its own free memory.
- `--launch` refuses without a gate. The in-run guards are unchanged: 12 GiB RSS, 1 GiB free floor,
  16 GiB logical.

## S1: completed queries per guard stage (observation only)
- `F.QueryStages` records, per guard stage, the summed exact counter deltas (hits, misses, written,
  incomplete) of every completed-query owner open in that stage, the owner opens and the last
  `unflushed` reading. A stage with no live owner has null counts, never 0.
- Nothing wraps the owner, the guard or a query; phase names and order are unchanged.

## Interval N >= 2 (item 21)
- `--interval N` starts stage `interval-NNNN` from adopted interval N-1. Interval 1 keeps every path,
  label and record; the new runner-record fields appear only at N >= 2, and RF refuses them at N = 1.
- Before the catalog opens, `F.sealed_lineage` re-reads intervals 0..N-1 from the explicit adopted(N-1)
  SHA-256: each adoption, verdict, sealed and runner record at its pin, the review approval of any
  review-adopted link, and a passed width gate of the matching version for every k >= 1. At N = 2
  the root anchor follows the interval-1 producer receipt to its run record at the current profile's
  interval route, and run A's seed capture must equal run A's receipt, verdict and adoption. From
  N >= 3 every earlier link must equal the lineage recorded by runner(N-1).
- RF re-runs the same gate with runner(N)'s parent pin and requires runner(N)'s recorded lineage to
  equal the result exactly. The review-approval checks live once, in F; RF aliases them.
- L accepts a parent stage ADOPTED with a passed width gate, or a review stage whose adoption carries
  a review approval, given explicitly with `--parent-adopted-sha256`; that adoption's verdict is read
  only at its full SHA-256 pin.
- A failed width gate after interval N still adopts N and reports GATE_STOP. A stopped interval is
  never a parent; there is no override in code.
- At N >= 2 the item 7 seed comes unchanged from the root stage. Stop-before-advance (the smoke) is
  interval 1 only.

## Known limits
- The interval-1 route is computed from the current profile, so a profile repin between intervals 1
  and 2 refuses at N = 2 (fail closed). A repin therefore has to land before interval 1 or come with
  its own lineage design.
- The GATE_STOP status label keeps its interval-2 wording at every N, because changing it would change
  records.
- Older records are not re-checked at adoption; interval N+1's gate re-checks them.

## Serial reader admission overlap

The selected private Plan11 implementation starts the current producer and its
independent serial reader together over the producer-reuse and continuation
baseline. Implementation and private integration are complete. The
[combined source snapshot](../workbench/plans10-12/README.md) publishes the selected
source closure; the public files do not supply a runnable private profile.
The combined profile needs its own eligible ROOT before the later interval chain.
Current scientific and individual run holds still apply.

The reader rebuilds admission from pinned sources in its own fresh directory and
budget, with no producer values. It then waits before accessing the producer
catalog or pending store. Reader admission is recomputed at root and every interval,
including N >= 2; the producer's measurement reuse has a separate benefit scope.

Only a successfully exited producer with its clean STOPPED guard, empty process
tree, frozen receipts and store-free preflight can release the reader. An exclusive
Windows write/flush/fsync/rename publishes a closed gate binding attempt, stage,
interval, profile, producer/guard/runner/seal hashes, exact reader and launcher
PID/creation times and launcher nonce. The reader checks liveness, cancellation,
source identity and a bounded deadline while waiting. After authenticating the
gate and the unchanged producer checks, it repeats its memory admission before
opening the sealed store. Independent verification, finalise and adoption remain
mandatory; successful admission or a gate alone cannot adopt a result.

A specifically approved, once-only sequential fallback is limited to proven
non-data overlap failures. It requires a new sibling reader directory, pinned
approval and complete producer/failed-reader exit evidence. The original bytes
and failure remain inspectable. Data, identity, source or uncertain cleanup
failures refuse recovery. No next producer starts speculatively.

The first comparable arms fix ALE to serial at interval 1 and ordinary successor
intervals, separately from the retained automatic pressure policy. They establish
no parallel-ALE applicability. Reader accounting retains the parent-charged 2 GiB
allowance for four ownership purposes beside its 256 MiB retained aggregate; that
allowance supplies no producer data. The 16 GiB logical parent, 12 GiB guarded-tree
RSS and host free-memory safeguards remain distinct and unchanged.

Both arms must measure the whole producer/reader/finalise/adopt cohort with the
same observation method, comparable inputs, code, cache and queue conditions.
Sampled RAM/disk peaks and observer overhead must be labelled. The retained q46
comparison measured one original-profile ROOT pair: wall time fell from
1,701.781 to 1,172.375 seconds (31.11%), while sampled arm-tree RAM rose 74.23%.
Exact parity passed. This is a ROOT-only scheduling result; it establishes no
interval/ALE, repeated-run or whole-programme speed-up.

The separate q47 bounded producer-only reuse smoke recorded 969 measurement hits
and zero misses. It ran no reader and stopped before interval advance; it is not
an adopted interval parent. Independent reader recomputation remains required
and has separate q46 evidence. q46 and q47 retain their original profile and
receipts; neither authenticates the new combined profile's ROOT.

The combined composition includes lf3 heat (H1a/H1c, H2, L1 and physical-order
repair), with H5a, D5 and P4 disabled. Its focused qualification passed 27
orchestration tests, three native-entry cases and four heat cases. Heat seam
save/restore checks do not complete full-workflow cold recovery. Final assembly,
the held full-interval chain and full-workflow cold recovery remain Plans31/38;
final combined timing remains Plans34/35. No historical receipt was rewritten.
This explanation uses retained driver/guard/store contracts and source-bound
private checks; no external paper or new physical benchmark was consulted for
this scheduling change.
