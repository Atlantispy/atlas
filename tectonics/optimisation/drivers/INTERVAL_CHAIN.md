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
