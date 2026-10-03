# I02.3–I02.8: accept, save, continue and inspect the first physical route

**30 September 2026. WORKING NON-CANON.** Reviewed, corrected, integrated locally
and accepted for the declared supported workflow. The owner released the review
hold and authorised the benchmark and restart corrections. This is the specialist method document for I02.3–I02.8 of the
[integration plan](INTEGRATION_PLAN.md#i02--common-state-exchange-transactions-and-accepted-time-controller);
the [common-state contract](I02_COMMON_STATE.md) covers I02.1–I02.2 and the
[reader chapter](how-it-works/06-physical-integration.md#8-accept-save-and-continue-one-evolving-state)
explains the route for non-specialists. [Current state](../../docs/CURRENT_STATE.md)
owns delivery status.

## 1. What runs, in execution order

| Stage | What happens | Owner |
| --- | --- | --- |
| Initial state | The declared layered column (I02.1) becomes the **root commit** of a ledger in the native store | [`integration_ledger`](../src/atlas_tectonics/integration_ledger.py) |
| Coupled step | One whole step of the original schedule by the package-owned core (I02.2), on the accepted head's state | [`integration_state.Continuation`](../src/atlas_tectonics/integration_state.py) |
| Checks and commit | The core's retained refusals, then one store transaction holding the new state, every account, the attached stocks, the transfers and the head change | [`integration_clock`](../src/atlas_tectonics/integration_clock.py), `integration_ledger` |
| Checkpoint and continuation | Every commit is a checkpoint; reopening rebuilds and checks it, and a fresh process continues from it | `integration_ledger`, `integration_state.restore` |
| Inspected outputs | Metadata and single physical fields with units, support, time and identity; a small command workflow | `Ledger.describe/field`, [`tools/i02_column_workflow.py`](../tools/i02_column_workflow.py) |
| Overhead | Same-workload timing of bare physics, the wrapper, commits and reopening | [`tools/measure_i02_workflow.py`](../tools/measure_i02_workflow.py) |

The supported case is [`cases/i02_column_workflow_v1.json`](../cases/i02_column_workflow_v1.json):
the reviewed layered order-8 column (32 material points) under its extension drive,
16 whole steps of 6.25e12 s over the retained 1e14 s horizon, a signed 2 K initial
departure and the reviewed inherited plastic history. Its preparation, physics and
bounds are the I01 ones, unchanged. It is a bounded control, not a generated world.

## 2. Where the accepted head lives: one store transaction

**Requirement.** The expected-parent check, the accepted head, every account and
every transfer record must change in one transaction; a check made before taking
the write lock is not enough, and a head pointer in another file is not covered.

**What the native store does.** [`ArrayStore`](../src/atlas_tectonics/storage.py)
keeps one SQLite file with the tables `settings`, `chunks` and `snapshots` and
refuses any other table set. It runs `journal_mode=DELETE` with
`synchronous=FULL`: a rollback journal, not WAL. `put()` prepares encoded chunks
outside the lock, then opens `BEGIN IMMEDIATE`, re-verifies every dependency,
compares any body already stored under the key, inserts chunks and the manifest,
calls the caller's `publication_check` and commits. A key's body is immutable: an
identical re-put is a no-op and a different one raises `StoreConflict`.

**Design chosen: the parent's key names its only possible successor.** A commit is
published under `successor_key(ledger, parent) = SHA-256("atlas.i02-ledger.v1",
"successor", ledger, parent)`. Because the store holds one immutable body per key,
publishing there is a compare-and-swap of the head: the first candidate is
accepted, an identical replay changes nothing, and any other candidate conflicts
and is rolled back with all of its chunks. The head is the end of the one chain of
successor keys from the root key, so there is no separate pointer that could
disagree with the data. The ledger's own checks (the parent manifest and its
transfer index are unchanged) run inside the same transaction through
`publication_check`. No schema changes: existing v1 stores and readers stay valid.

Alternatives considered: new `heads`/`transfers` tables would need a schema
successor with explicit v1 compatibility and more migration surface; a separate head
file or database is not covered by the same commit. The cost of the chosen design is
that finding the head, and confirming a commit before any public read, needs the
chain's manifest metadata (one indexed read per commit, at most 257 records for this
route), and a bounded label index travels with each commit. The checked chain is
reused while the store's change token (SQLite's `data_version`, which changes when
another connection commits, and this connection's count of changed rows) shows that
nothing was written since it was read. A commit takes the token inside its own
transaction, just before `COMMIT`, so nothing is read once the successor is published
and nothing can fail after it; the ledger then extends its checked chain with that
commit when nothing else was written in between. Repeated reads and a long run of
requests therefore do not re-read the growing chain. A commit itself checks only its
parent, inside the transaction. Like the store's own caches, the token does not see
schema changes made directly through the store's connection, or rows written through
that connection by the commit's own cancellation callback, which the store polls while
the commit is prepared and written (from the ledger's first token read to the one taken
inside the transaction); either can leave the reused chain stale, but a stale chain
cannot make a read accept a changed record, because every read also re-reads that
commit's record and restores it.

**Why this is atomic.** SQLite's [transaction documentation](https://www.sqlite.org/lang_transaction.html)
(section 2.2) states that `BEGIN IMMEDIATE` starts the write transaction at once
rather than at the first write, so the comparison and all inserts happen while
the write lock is held. A second writer's `BEGIN IMMEDIATE` waits for that lock for
up to the store's 5 s busy timeout. If the first commit ends in time, the second runs
against it (a candidate for the same parent then conflicts); otherwise it fails with
the store's `StoreError`, publishing nothing, and `Ledger.commit` passes that error on
unchanged, so the caller can retry (the clock retries a failed commit once, section 4).
A reader that holds a read transaction open for longer than that timeout likewise makes
the commit fail, at `COMMIT`, with `StoreError` and nothing published; the workflow's
own reads hold the read lock only while they copy the file.
The [atomic-commit description](https://www.sqlite.org/atomiccommit.html)
explains the rollback-journal sequence: original pages are journalled and flushed
before the database file changes, deleting the journal is the commit point
(section 3.11), and a journal left by a crash is "hot" and rolled back by the next
connection (section 4). Changes can reach the database file before commit when the
page cache spills (section 6.3); the journal still restores them. Atomicity covers
one database file; several files need a super-journal (section 5), which is why
nothing of a commit lives outside the ledger's file. `synchronous=FULL` flushes the
journal twice; the documentation notes that disks which ignore flushes can still
break durability (section 9.2). Both pages were consulted for this step.

**Trust boundary.** As for the store, SHA-256 detects corruption, not an attacker
who can rewrite data and identities consistently. Restoration recomputes every
identity from values, so an edited value is refused. Each successor record also
carries the SHA-256 of its parent's stored record, and every public read (`state`,
`exchange`, `describe`, `field`, `verify`) first confirms the whole chain from the
root to the head, re-reading and checking it whenever the store may have changed: a
stored commit rewritten without rewriting every later record breaks the chain and is
refused wherever it sits, and `chain()` refuses rather than return a prefix. Outside the defended model are a consistent rewrite of the head's
values and recorded identities, a commit rewritten together with every later
record's parent digest (which amounts to rewriting the head), and the head's `path`
entries, which name unstored intermediate pieces. A `Commit` object is only a handle:
before it is used, the ledger re-reads its stored record and requires every field to
match, so an edited, forged or foreign handle is refused and cannot publish a
malformed successor. A malformed body written directly under a successor key by
someone with raw access to the store is refused as not well-formed, but it occupies
that slot; the store's caller owns its directory and is not treated as hostile.

The store, and a saved project, are therefore **trusted local input**. A record that
is well-formed, linked to its parent's stored record, inside the admitted ranges and
consistent with the retained step relations is restored, continued, loaded and
admitted whoever wrote it, including one appended through `ArrayStore.put` rather
than by the clock; a test records this boundary. Restoration refuses values that
contradict those relations, which establish consistency, not authorship, and
`Ledger.commit` applies the same relations to every state before it publishes it, so
the engine never publishes a state that breaks them (restoration's range checks and
record reproduction are not repeated at commit). Every relation follows from what the
engine enforces on each step, and the check cites the engine lines
(`integration_state._consistent`); only the power cap adds a margin beyond them:

- the displacement is the width's change `w0(λ − 1)` (to 1e-9 of the width), and the
  booked log-strain quadrature does not exceed the log-strain path (equal for a
  monotone history; a 1e-12 relative slack);
- a zero drive is exact rest: stretch 1, and no displacement, path, stage account,
  start velocity, start force or force and power residual;
- under a nonzero drive, the start velocity has the drive's sign and the displacement
  does not oppose it; the balanced column force (creep plus plastic resistance) has
  the drive's sign too and is no larger than the drive within twice the motion
  solver's force tolerance; every work account is nonnegative; and the first step
  alone moves the edge by at least `dt |v_start| / (1 + lo⁻²)` and books the force
  times that as drive work (a bound that vanishes only where it would underflow);
- the drive work is the force times the displacement; drive, drag, creep and plastic
  work balance within `2e-10 + 8 TOL` of the drive work (3.6e-10 with the retained
  stress tolerance `TOL` of 2e-11), and the recorded power residual lies within that
  bound. 2e-10 is the motion solver's enforced power bound, which a stage's recorded
  residual meets whenever its heat re-evaluation reproduces the motion's stresses: it
  starts from them and stops at its first evaluation, and verification found no stage
  that did otherwise (about 3,900 randomised stage solves and every measured history).
  `8 TOL` is a margin, not a derived bound, for a stage where it does not, which the
  engine counts but does not bound; a genuine state could exceed the cap only through
  such a stage, and `Ledger.commit` would then refuse it rather than publish it. Creep
  plus plastic work lies within `2 TOL` of the column work, and heat plus stored work
  is creep plus plastic work, with heat the declared fractions of them;
- the thermal change is the capacity-weighted change of the recorded temperatures
  from the initial departure, `w0 Σ C (θ − θ0)`; the radiogenic heat and the
  reference outflow are the column's steady radiogenic production `P` over the whole
  steps and over the thermal clock, `n w0 P dt` and `w0 P τ`; and the reference
  surface loss and basal gain are the steady reference's boundary flows `q` over the
  thermal clock, `w0 q τ`, with `q` evaluated on the carried reference by the runner's
  own expressions (conductivity over distance to the boundary, times the steady
  departure from the boundary temperature); and no departure heat crosses an insulated
  boundary;
- the force residual never exceeds the motion solver's tolerance, and the power,
  source and dissipation extrema are nonnegative.

The drive-work, heat, thermal-change, steady-production and reference-flow relations
are exact up to rounding, allowed `32 (n+2)` units of roundoff of their terms for `n`
steps (for the thermal change, of the capacity-weighted distance to the temperature
window); the power balance and work partition add that allowance to their stated
tolerances, and the other relations use their stated tolerances alone. The energy and
flow closure identities of the retained checks are not used: the engine records their
residual but never enforces it, and it grows as the step shortens, so a check on them
refused genuine short-step and zero-drive histories in the second candidate (the
coordinator's restore-relations-1). Without those identities, the departure surface
loss and basal gain are related to nothing else beyond vanishing at an insulated
boundary: they need the thermal solve's boundary values, which a state does not carry.
Restoration also requires the stage counter to be the reference balance plus two
stages per accepted step, and bounds the restress mismatches and each point's yield
stages by it; the motion evaluation and iteration counters are only range-checked,
because a zero drive books none.

Genuine histories measured in the scratch candidate, each with a cold restart halfway
unless it stopped before, were: a zero drive over 16 steps lasting 1e5 s to 1e14 s in
all, and over 256 steps; the extending drive over 16 steps lasting 1e5 s, 1e7 s,
1e11 s and 1e14 s, and over 256 steps; the compressing drive over 16 steps lasting
1e9 s to 1e14 s, and over 256 steps; other heat fractions, drive and drag values and
widths; and two narrow windows (the extending one stopped at the window after 7
steps). The quadrature bound holds with equality, as it must for a monotone history.
No other relation used more than 0.99 of its tolerance: the largest were 0.988 for the
column force, which nearly equals the drive when drag is small, and 0.95 for the force
residual; the recorded power residual used at most 0.26 of its bound (9.5e-11), and
the exact relations at most 0.017 of their rounding allowance; every state passed the
commit check. Tests restore every step of twelve such 16-step schedules; reopen,
verify, describe and continue a zero-drive ledger and a ledger on a 256-step schedule;
and compare the reference flows with the runner's for other conductivities and an
insulated top or base. Some other short-step or stiffer inputs do not complete: the retained
step raises `plastic history exceeds twice the accumulated log-strain path` for the
extending drive over 16 steps lasting 1e9 s (with heat fractions (0, 0) after 5
accepted steps, which pass the commit check) and the compressing drive over 16 steps
lasting 1e7 s or 1e5 s, a halved compressing drive exhausts the stress resolution, and
a doubled drive or a tenth of the drag is refused at the first step by the
temperature-step guard. These come from the retained step, which this candidate does
not change.

Where receipt-bound I01 documents say that I02 owns authenticated state (for example
`I01_RIDGE_JUNCTION.md`), they name the planned responsibility; this route establishes
consistency, not authorship, and those sentences are left for their documents' next
re-capture, since editing them would unbind current receipts.

**Only computed physics is committed.** Every state carries a provenance mark,
*declared* (an initial state), *computed* (a `Continuation` step) or *restored* (read
back from a store); it records how the object was issued and is not part of its
identity. A commit accepts only computed pieces that continue the accepted parent's
state, so a restored or declared state, however well-formed, cannot be appended as new
physics, and a restored state cannot start a new ledger. The mark governs what a
process commits; it cannot see a record written into the store by other means (the
trust boundary above).

## 3. Finite exchanges

A `Transfer` names a producer, a label, a donor and a receiver, one nonnegative
whole-stock mass per component (kg) and a signed enthalpy (J) in the stocks' declared
basis. It moves positive mass or, without mass, positive heat from donor to receiver.
The label is an ASCII token (letters, digits and `._:/@+-`) compared exactly, so no
Unicode spelling, space or look-alike character can pass as a new label. Every
quantity must lie within a finite accounting range (magnitude at most 2^960, so sums of
up to 2^63 such terms stay finite). Values are captured as plain floats when the
proposal is made, so later edits to caller arrays cannot reach it, and a proposal is
validated again when it is used, however it was built. Each transfer declares the
interval `(start_step, end_step]` of whole global steps it was produced for. The
interval is part of the proposal's content and of its record, so of its `transfer_id`
(the record's SHA-256), and `Ledger.commit` refuses a transfer whose declared interval
differs from the commit's. Every refusal of a proposal itself (declaration, interval,
support, availability, label or resolution, an emptied stock left holding enthalpy, or
a stock or account the proposal would push out of the finite accounting range) raises
`ExchangeRefused`, a `LedgerError`; the clock reports only those as `REFUSED_EXCHANGE`,
and any other failure of a commit (of the ledger or its store) propagates. A stored
transfer that no longer applies when stocks are restored is such a store failure, not a
refused exchange. Its parent is thereby
named by the ledger and the interval's start: the accepted commit at `start_step`. The
parent's state identity cannot be known before the interval is computed; the commit
binds it through the ledger's hash chain, since the transfer record names the parent
key and the commit record carries the SHA-256 of the parent's stored record.

Finite stocks are the native [W08 inventory](../src/atlas_tectonics/w08_inventory.py)
attached to the root envelope. The envelope keeps them as its initial payload, as it
keeps the initial temperature departure; the ledger's exchange accounts own the
current stocks (a copy rebuilt and identity-checked by the ledger), dated at each
commit's time. Named exteriors are declared once when the ledger is created, each a
source or a sink with an ASCII-token name that differs, even ignoring case, from every
stock node and material cohort; they are bound into the ledger identity. Checked for
every transfer, in order, before anything is written:

- units are whole kg and J (per-metre strip quantities cannot enter), the basis is the
  stocks' own, and the component set is the inventory's;
- donor and receiver are stock nodes or declared exteriors; a column material cohort
  is refused (the closed strip exchanges no material); exterior-to-exterior, a sink
  that supplies and a source that receives are refused;
- finite availability, in exact arithmetic: no component of a donor stock may go
  below zero at any point in the sequence; an emptied stock may not keep enthalpy (the
  W08 constructor's own rule);
- the label is new in this history (a ledger-wide index of label digests travels with
  each commit), including within the same commit.

**Exact bookkeeping.** Balances run in exact rational arithmetic. At the end of a
commit each changed stock is rounded **once**, from its exact new value, into a new
native `W08Inventory`, so a large flow through a stock cannot absorb a small stock or a
small later flow. A stock whose exact change is nonzero but too small to alter its
stored binary64 value is refused rather than silently dropped. The accounts that are
not W08 arrays are kept exactly, as canonical dyadic fractions in the commit record:
the root totals, what each exterior has supplied (negative when received) and the
**rounding account**, the exact difference between each stored stock and its exact
value. The closure identity `sum(stocks) = initial + sum(supplied) + rounding` therefore
holds exactly for every component and for signed enthalpy (`Exchange.closure()` reports
it).

What rounding leaves is reported, not made negligible. A change that would round to no
change of a stored value is refused. Otherwise each stored stock value is within half a
unit in the last place of its exact value after each commit that changes it, and at a
large stock that can be comparable to a small transfer. Exterior accounts are exact:
moving 10 t from a stock of 1e20 kg (whose unit in the last place is 16,384 kg) to a
declared sink books exactly 10 t in the sink's account, while the stock's stored value
falls by 16,384 kg; the 6,384 kg difference is in the rounding account, and moving 5 t
there would round to no change and is refused (both checked with the candidate). The
rounding account's bound is kept exactly as well: each commit adds at most half a unit
in the last place per changed stock value, a history has at most 256 commits, and the
allowance grows only for the values a commit changes (and so rounds); nothing is
published if the rounding account ever exceeded it. This replaced the first candidate's
gate of 128 unit roundoffs of the participating magnitudes, which independent
verification by the implementing session showed a large transient flow could widen
enough to hide a real loss.

Replaying the identical proposal on the same parent is idempotent; changing anything
(quantity, producer, label) refuses as a stale-parent conflict; reusing a label later
refuses as a second application. Quantities are the producer's declarations: nothing
here is a transport or rate law.

## 4. One accepted clock

`Clock(ledger)` prepares one continuation at the accepted head and advances it one
whole step at a time: each piece is the package core's own step with its retained
stretch-window, temperature-window, temperature-step, constitutive and deadline
refusals. A request names a positive number of whole steps or an end time that is a
whole step of the original schedule (`dt = duration/steps`, never recomputed).
Savepoints are global step indices divisible by `savepoint_steps`, prescribed
savepoint events and both ends of every declared transfer interval; the end of a
request is always committed. The cumulative step index, its ceiling (at most 256), the
1e14 s horizon, the windows and the 5 K guard belong to the settings and cannot be
changed or reset by a request, a failure, a new clock or a new ledger (a ledger
refuses a non-initial root; a clock refuses to start anywhere but the head).

The event calendar is declared once, with the ledger, and bound into its identity, so
every clock honours it; a request may add savepoints only. Every declared event lies
within the fixed schedule, a savepoint exactly on a whole step, and the schedule's step
boundaries must all be distinct at the epoch's time resolution, so no declaration can
leave a clock unable to plan. Any event other than a savepoint stops the clock at the
last whole step not after it and reports `REFUSED_UNSUPPORTED_EVENT`: this route
represents no event physics, so it neither invents one nor steps past it, and the
ledger independently refuses a commit that would. `Clock.check()` validates a request
exactly as `advance()` would without running anything, except that it does not look
for a head another writer has advanced: `advance()` reports that as
`REFUSED_STALE_PARENT`.

**Transfer intervals.** A request's transfers each declare their interval (section 3).
The clock makes both ends savepoints and commits each interval in one commit with its
transfers, so an interval's steps are committed together with its exchange or not at
all. Before any work it refuses an interval that starts before the head (an earlier
commit would split it), ends after the request, overlaps another, contains a savepoint
event of the request or of the ledger calendar, or ends after an unsupported event
stops the clock; `savepoint_steps` multiples inside an interval are skipped. A refused
exchange (`REFUSED_EXCHANGE`) commits none of its interval's steps and leaves the head
at the interval's start, and so does a stop or an exception inside the interval; the
reason, or the exception's note, says so. A record of the same steps published by
another writer with other transfers is adopted as the head, and the reason names the
other transfers: at a savepoint commit the status is `REFUSED_EXCHANGE`; after an
early stop, including one at an unsupported event, the stop's own status (for example
`CANCELLED` or `REFUSED_UNSUPPORTED_EVENT`) is kept; and if that writer has also
continued the history, the status is `REFUSED_STALE_PARENT` with both reasons. At an
unsupported-event stop the event's status is reported only when the head reaches the
stop, through this clock's commit or an adopted record; an exchange refused there
leaves the head at the interval's start and is reported as `REFUSED_EXCHANGE`.

**Stops and failures.** Cancellation (polled between steps), a retained refusal or an
expired budget commits the whole steps already accepted (outside an unfinished
interval) and reports the last accepted time; what stopped the request decides its
status. Both commit sites, at a savepoint and after an early stop, use one helper that
retries a failed commit once: a failure the retry recovers from changes nothing, and a
retry that meets the clock's own record, published by an attempt interrupted after
`COMMIT`, adopts it instead of treating the clock as overtaken. What a failed commit
left is read from the accepted chain after the clock's own head, so a record the clock
published is recognised even when another writer has since continued from it (the
steps are then reported as committed, and the clock as stale). When both attempts
fail, or the failure was an interrupt, the exception propagates with a note saying
whether the steps were committed, and as which commit, or that this could not be read;
in that last case the clock's next request settles it first, adopting the clock's own
record if it was published; a record of the same steps with other transfers is not its
own, so the clock is then stale and the request refused. An exception during the steps,
including an interrupt,
likewise commits the accepted steps before it propagates, with the same kind of note,
and an interrupt between steps says what the request had committed. If another
writer's commit overtakes the head, the candidate is refused (`REFUSED_STALE_PARENT`,
keeping the stop reason) and the clock becomes stale.

Consecutive single-step pieces continue the continuation's warm endpoint exactly as
one uninterrupted run, so every request pattern reproduces the uninterrupted history
bitwise inside one clock, with the reference balance solved once and two stages per
accepted step. Savepoint spacing does not change the accepted states: it decides which
of them are recorded as commits, and so where a history can later be continued (and,
with transfers, their intervals are declared rather than chosen by the spacing). A new
clock (in a new process, or after `Clock.continuation` was advanced directly) re-solves
the head's endpoint cold, and so does the request after one whose accepted steps could
not be committed (a refused exchange, a stop inside a transfer interval or a failed
commit), because the warm entry is then ahead of the head. A history continued that way
agrees with an uninterrupted one within the retained parity (section 5), not bitwise.
Bitwise identity therefore depends on where process boundaries fall, including where a
time budget stops a run.

### Relative plate-velocity handoff contract (`eps_v`)

**Owner-approved numerical policy: `eps_v = 0.01` (dimensionless, 1%).**
Approved on 1 October 2026 and recorded here on 2 October 2026. I02 owns this
declaration; I06.2 and I07.2 consume it, and I09 enforces it when accepting a
coupled-to-replacement handoff. I03 does not require it. The current I02 column
workflow does not perform that regional/global handoff; recording the policy is
not a claim that its future certificate or enforcement is implemented.

Use the comparison defined in [I01's separation decision, section 4](I01_SEPARATION_DECISION.md):
the coupled branch C and replacement R share their parent, forcing, source
accounts, exterior conditions, physical support A, material correspondence and
declared window `[t0,t0+H]`. Apply the same permitted rigid-frame gauge to both,
preserving normal and tangential motion. Admit replacement only when a supported
whole-window bound establishes

```text
E_v = sup_(A, time) ||v_C - v_R||_2 / V_ref <= eps_v = 0.01
V_ref = sup_(A, time) ||v_R||_2 > 0
```

The reference speed must be established on that same support, window and gauge.
Sample maxima or endpoint agreement alone are not a certificate. If the reference
speed is zero or unavailable, this relative criterion is unavailable: refuse it
rather than insert a hidden speed floor. The declared validity window must not be
shortened to hide an error, and the certificate must be revalidated on expiry.
For the [linear zero-intercept rift control only](I01_TRANSITIONS.md), this gives
`Pi_c = eps_v / (1 - eps_v) = 1/99`, approximately `0.01010101`. Nonlinear,
history-dependent or plastic belts still need the actual error certificate.

The value is the owner's fixed model-replacement accuracy budget, not a geological
constant. Existing regional L2 benchmark gates supplied scale context, not proof
of this maximum-norm bound or a universal 1% solver accuracy claim. This does not
replace force, energy, conservation, iteration, mesh or timestep checks, or grant
a 1% error allowance independently to every coupling operation. I09 must account
for the combined error of the accepted replacement. Record the policy and
comparison support/window in the consuming run and handoff identities.
Do not relax the value to obtain a pass or to fit the unchanged 256-step ceiling.

Receipt-bound I01 case files that contain `"eps_v": null` remain unchanged as
records of their earlier specification. This declaration resolves the missing
production value; it does not retroactively certify those cases. No new paper or
external benchmark was used to record the owner's decision.

## 5. Saving, reopening and continuing

Saving is the commit. The root stores the reference, initial history and native
material (and stock) payloads once. A successor stores only its current departure,
raw history and yield counts, its stocks and transfer index, and small metadata: the
column record, lineage (parent state and the path of pieces) and transfer records.
Content-addressed chunks share every unchanged payload. Prepared operators are never
stored.

`Ledger.open(store, ledger_id, source_id=…, runtime_id=…)` requires the identities its
caller declares to equal those recorded with the history (a check only as good as that
declaration: the workflow declares the identities it computes, and `restored()` below
does not repeat it), then rebuilds the root
through `ColumnReference`, `ColumnSettings`, the material restorer, the W08
constructor and `initial_state`, which recompute every fingerprint and cross-check;
the root's identity must reproduce. A successor is rebuilt by the engine-owned
`integration_state.restore`: its scalars, accounts, counters, extrema and arrays must
lie inside the admitted history (the bounds `resume()` applies) and satisfy the
retained step relations (section 2), its column record must be reproduced by its
values, and its state identity and lineage must equal the recorded ones. Stocks are
restored by applying the recorded transfers to the parent's
stored stocks again; the result must reproduce the stored identity and label index.
A `Continuation` then rebuilds operators from the pinned inputs and re-solves the
head's endpoint cold (operational work, never booked), so a fresh process continues
without re-running the accepted prefix. For the supported case its results agree with
the uninterrupted run within the retained warm/cold parity (`1e-8`), with identical
booked-stage counts and yield counts. Review found a restart-dependent failure in
the local constitutive solve: near a stiff plastic branch, adjacent representable
log-stress values could both miss the unchanged residual tolerance. The solver
now finishes in direct stress when that coordinate stalls, inside the same bracket
and original iteration budget. This is a numerical precision correction, not a
new material law or a looser acceptance test. Restart checks include the previously
failing insulated-top column, compression with a hundredfold drag, and retry after
a failed checkpoint write. Unsupported constitutive states still refuse; a valid
saved state does not promise that every later physical step is supported.

**Finite admission.** The finite-admission tool now has an engine-owned restoration
path, [`restored(evolution, ledger, commit)`](../tools/check_i01_finite_admission.py):
the ledger re-reads the commit on its chain and restores its state as above, and the
tool issues a `State` only when that state is exactly the evolution's history
(reference and thermal fingerprints, law, drive, fractions, step, window, guard,
policy, initial departure and history, production solver). A common state, a
fingerprint, a raw output, a `Commit` object edited after it was issued or a commit of
another ledger is refused. A consistent record appended to a trusted store by other
means is restored and admitted like a computed one (section 2). The tool binds, and
checks that it imports, every package module that `restored()` executes (section 8).

**Inspection.** `describe(commit)` and `field(commit, name)` first re-read the chain's
manifest metadata, then restore and validate the commit's state (reading only the
root's and this commit's snapshots and, with stocks, the parent's) and answer from it:
time, schedule, accounts and identities, or one field as a read-only copy with units,
support, owner, accepted time and identities. Derived fields (`temperature_k`,
`current_depth_m`) are computed on read. Neither runs physics. `verify_chain()`
restores every commit from the root to the head in one pass.

## 6. The command workflow

`tools/i02_column_workflow.py` exposes `create`, `advance`, `status`, `inspect`,
`cancel`, `save` and `load` for the supported case, one JSON line per command,
including argument errors. It reuses the managed-job seams of
[`tectonics_job.py`](../tools/tectonics_job.py): the one-byte process lock, atomic JSON
files and error codes. Run outcomes are `completed`, `partial` (time budget
exhausted), `cancelled`, `refused`, `failed` or `interrupted`; the history is
`initial`, `partial` or `complete`.

- **advance** runs attached, under the project's worker lock, with single-threaded
  BLAS for reproducible physics. The request is validated completely (`Clock.check`)
  before an attempt is claimed, so an invalid request changes nothing; attempts are
  capped. The status file records the head by its key and by its state identity (a key
  alone names only a position, which every ledger of the same case shares), and a
  project whose ledger no longer holds that commit (a replaced, older or other
  project's ledger file) is not continued. The start and the outcome of a run are
  written patiently (for up to about ten seconds while a reader holds the status file
  on Windows); progress is written as each commit lands but skipped at once when the
  file is held, because the ledger head is authoritative. A reader holding the file for
  longer at the end of a run makes `advance` report `STATUS_UNWRITTEN`: every accepted
  step is committed, but the outcome is not recorded, and status shows the run as
  `interrupted` at the committed head. Any exception after the run starts is recorded
  as `failed` or `interrupted` with the committed head. The answer is built before the
  worker lock is released, so it describes this attempt even when another advance,
  waiting for the lock, starts at once; its capabilities are those at the release. An
  advance arriving while a run holds the lock waits up to two seconds for it and is
  otherwise refused with `RUN_BUSY`. A run whose ledger another writer advanced
  outside the worker lock fails with `INVALID_STATE`; the steps it computed after its
  last commit are not kept.
- **cancel** writes a request naming the project and the running attempt; the worker
  polls it between steps and keeps every accepted step. A request file left over for a
  new attempt's number is removed before that attempt starts, and while it runs only a
  well-formed request for this project and attempt counts: a malformed, oversized,
  foreign or non-regular file is ignored, never fatal. `cancel` replaces an oversized
  file at the request path and reports anything that is not a file there (a directory
  there blocks cancellation until it is removed). The answer says whether a request was
  written.
- **status** and **inspect** read a consistent snapshot: a read-only connection (URI
  parameter `mode=ro`, [URI filenames](https://www.sqlite.org/uri.html) section 3.3)
  copies the ledger into a temporary file with SQLite's online backup in one step, which
  holds the source's read lock throughout, so the copy is the database as it was when
  copying began ([backup API](https://www.sqlite.org/backup.html)); the ledger is then
  opened on that copy. They never write the project or create a missing store. A
  read-only connection cannot roll back a journal left by a crash and refuses with
  `SQLITE_READONLY_ROLLBACK` ([result codes](https://www.sqlite.org/rescode.html)); only
  then is the native store opened once, which rolls the journal back to the previous
  complete head. A running worker is recognised by its lock, probed through a read-only
  handle and held on two probes 50 ms apart, so status also works on a read-only
  project. A running run's progress, and a run whose worker exited without reporting
  (shown as `interrupted`), are reported from the committed head. The capabilities
  offer `advance` only when it can run (identity, remaining steps, attempt limit, a
  free request path, and a ledger holding the recorded head). Each read copies the
  ledger file, so its cost follows the file's size (for the supported case about 45 KB
  at creation and 140 KB once all 16 steps are saved one by one).
- **save** is a consistent online backup plus the project record, built in a staging
  directory and published with one rename. **load** accepts only a project record
  exactly as `save` writes it (fields, case, case identity, root key), refuses a saved
  store holding records that are not commits of its ledger, checks that every commit
  restores consistently (identities, chain, states and stocks, within their ranges and
  relations; a saved project is trusted input, so this is not a check of who wrote it)
  from a read-only snapshot, and publishes a new
  project with one rename; `create` is staged the same way. The root's lock is held
  only for that final check and rename. Unreferenced chunk rows in a saved store are
  not refused (they cost space and copy time, not correctness). A create, load or save
  killed mid-way can leave a hidden `.i02-*` staging directory (and a read may leave an
  `atlas-i02-read-*` copy in the temporary directory); nothing is published from them,
  they block nothing and can be deleted.
- On Windows, every path the workflow writes must stay under the classic 260-character
  limit; a projects root, save destination or saved project too long for the longest
  file written or read there (a request file's temporary name, or the store's journal)
  is refused up front with `INVALID_PATH`. Errors are specific: malformed project files
  (including text JSON cannot decode, deep nesting and oversized integers) are
  `INVALID_STATE`, and an interrupted run records `INTERRUPTED`.
- **Exit codes.** Every command prints one JSON line. It exits 0 with status `ok` when
  the command did its work, including an advance that stopped early (`partial`), was
  cancelled or was refused by a retained check; otherwise it exits 2 with status
  `error`. An advance whose run failed answers with its project and the error, and an
  interrupted command still prints its line (`INTERRUPTED`). If the answer itself
  cannot be built after a run, the command reports that error, and status then shows
  the recorded outcome.

On Windows a reader holding `status.json` blocks its replacement, and an open during a
replacement is refused; both are transient. The coordinator's review reported this for
the shared job seams (infra-code-1), it was reproduced here (runs recorded as failed
while another process polled), and `tectonics_job._atomic` and `read_tectonics._read_json`
now retry such denials for about one second on Windows only; POSIX behaviour is
unchanged.

Independent verification by the implementing session found two more defects in shared
seams, both fixed at their cause. A reservation
lease is often returned by a garbage-collection finalizer, which runs in whatever
thread triggered the collection, possibly while that thread holds the same budget's
lock inside another reservation; the return then waited for that lock forever. Ledger
commits create and drop several W08 inventories, which made this permanent hang
reachable. [`resources.py`](../src/atlas_tectonics/resources.py) now never waits in a
return: it queues it and applies it at once when the lock is free, otherwise the lock's
next holder applies it before using the account; admission stays atomic. And the
store's link check read a rollback journal caught mid-deletion (no remaining link) as a
hard-linked database; such a journal is now absent, like one that has already gone. The
check reads each path once with `lstat` and treats a path as absent exactly where
`pathlib`'s `exists()` does (missing, under a regular file, a symbolic-link loop or an
unusable name); any other error still refuses. Status snapshots open the live store for
recovery only on `SQLITE_READONLY_ROLLBACK`; every other error propagates.

**Why these seams.** The command workflow reuses `tectonics_job.py`'s lock, atomic JSON
files and error codes rather than the W12 assembly and publication route because that
route cannot carry this state: [`assembly.publish_workflow_output`](../src/atlas_tectonics/assembly.py)
describes its input through [`workflow_ports.describe_workflow_output`](../src/atlas_tectonics/workflow_ports.py),
which accepts only the typed W01–W08 and tectonic-history outputs and refuses any other
type. A ledger commit is none of them, and adding a port for it belongs to the I10
project route, not here. The job seams are process-level and type-free, so they fit.

The source identity binds the workflow's own files and the case inputs; the runtime
identity is the package's `ExecutionContext` identity. A changed identity refuses
continuation and load but still allows inspection. Timings stay in status files and
are never recorded in a state, but a deadline stop or a separate request ends a
process, and the next request re-solves its starting stage cold (section 4). This is
not the I10 project/UI route.

## 7. Checks, coverage and measured overhead

**Recorded I02 acceptance checkpoint, 30 September 2026 (before R4):**
the integrated files passed **758 I01/I02 tests on Windows/CPython 3.12.14**
in 149.794 s on 30 September 2026. The before-commit guard checked Git-normalised
candidate bytes: all three guards passed in 154.1 s, including the current-evidence
register and LF-digest checks. Nothing was staged or committed. Eight affected
I01 controls were freshly captured in dependency order; unchanged evidence and
the shared job/storage checks below were reused. This accepts the declared I02
workflow, not the entire tectonics generator. Linux is not covered.

R4 and its follow-up reliability/resource fixes are now integrated. Their
[focused Windows checks](../../docs/CURRENT_EVIDENCE.md#integration-checks) and
the r6 captures below cover the changed boundaries. The final Git-normalised
integration guard passed all three checks in 169.6 s, including 759 I01/I02 tests
in 164.449 s with no failures or skips. The following per-module counts are retained
from the earlier I02 checkpoint.

| Plan step and its "done when" | Checks | Result |
| --- | --- | --- |
| I02.3 two-reservoir transfer and multi-component failures prove conservation, exactly-once, rollback, stale-parent refusal | `test_i02_exchange.py` | 24 pass |
| I02.4 requests keep one clock and one numerical path; failures report the last accepted time and cannot reset limits; transfer intervals commit whole; both commit sites retry alike; what a failed commit left is read from the chain; a rival record adopted at a stop keeps the stop's status, and an exchange refused at an event stop stays refused | `test_i02_clock.py` | 36 pass |
| I02.5 fresh process resumes to the uninterrupted result without repeating the prefix; interruption shows old or new, never mixed; the trusted-store boundary; the engine-enforced step relations on genuine short-step and zero-drive histories and a 256-step schedule, and against records the engine could not have written | `test_i02_persistence.py` | 21 pass |
| I02.6 one command-level create → advance → save → load → continue → inspect sequence; cancellation keeps accepted progress; every run outcome's JSON line and exit code | `test_i02_workflow.py` | 28 pass |
| I02.7 direct vs workflow, chunked vs uninterrupted, fresh-process continuation on fields and accounts; measured overhead | `test_i02_joined.py`, `measure_i02_workflow.py` | 7 pass; timings below |
| Shared job seams under Windows concurrent polls | `test_tectonics_job.py` | 16 pass |
| Budget returns from garbage-collection finalizers | `test_combined_resources.py` | 28 pass |
| Store paths absent exactly where `pathlib` says so; zero-link sidecars | `test_memory_storage.py` | 44, of which 1 skipped (no symbolic-link privilege) |
| Cold restart, failed-save recovery and the existing 256-step limit | `test_i02_restart_regressions.py` | 4 pass |
| Cold/warm/reopened equality, malformed or changed results and source-drift refusal | `test_i02_measurement.py` | 5 pass |
| I02.8 method text, reader chapter, coverage and acceptance commands | this document, reader chapter section 8 | updated for the reviewed, integrated route |

The failure checks inject errors after every row is written but before `COMMIT`,
between chunk batches, through cancellation and through invalid proposals; kill a
writer inside its commit after forcing a cache spill (the database file grows by
several megabytes before the kill, the hot journal is rolled back, the file returns to
its size and `PRAGMA integrity_check` passes), kill it after commit and kill a
committing loop at random moments. Two processes racing on one parent publish
exactly one successor. Checks added after independent verification by the
implementing session cover edited, forged, swapped and rewritten records (including a
middle commit read directly); a consistent record appended through `put()` (recorded
as the trust boundary) and records contradicting the step relations; fabricated or restored
states offered as new physics; interrupts and store failures while a commit with
transfers is written; calendars that could never be planned; Windows status polls
and a reader holding the status file while an advance commits; leftover, malformed,
foreign and non-regular cancellation files; status, inspection and load leaving every
byte and modification time unchanged; and saved projects with an edited record or
one flipped payload byte in an earlier commit's chunk.

The timing harness separately checks cold and warm outputs and the reopened
physical history and energy accounts. Negative regressions deliberately change a
cold temperature or a reopened account: neither may publish a timing comparison.
It refuses an existing output file, a missing output folder or an
invalid request before it runs or creates anything, creates its record exclusively once
the measurement has finished, and records `FAILED_EQUALITY` with every timing withheld
when any mode (including the fresh-process reopening) did not compute the same accepted
history.

**Current source-bound measurement:** [i02-workflow-timing-r10](../evidence/i02-workflow-timing-r10.json),
3 October 2026; Windows AMD64, CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
one BLAS thread. It was captured after the I03 N1 change to
`integration_transfer.py`, which followed the K1–K5 repairs, without a concurrent
Atlas test campaign. The harness ran five
repetitions of the same supported 16-step, 32-material-point case, saving every
four steps and reopening at step eight. All seven checks passed, including
cold/warm physical equality, reopened accounts and unchanged sources. The record
binds 156 source files and records the execution identity; hashing is outside the
measured regions. This is a fresh bounded-column receipt, not a 3-D speedup
measurement: the column workflow does not use the 3-D solvers or spherical motion, and the new
record exists because the package sources it binds changed. Its warm medians are
**0.07044400 s** for bare evolution, **0.07009810 s** for in-memory continuation
(-0.49%, within small-run variation), and **0.10774630 s** for the stored workflow
(+52.95%, or 0.03730230 s, against bare evolution), of which **0.01942420 s** is
four commits. Cold root/head/operator reopening totals **0.12080310 s**;
the receipt retains every sample and growth
measurement. These tiny-case costs are not a general overhead or speedup claim.

**Historical r5 measurement, 30 September 2026:** the table and interpretation
below describe the unchanged [r5 receipt](../evidence/i02-workflow-timing-r5.json),
not the current checkout. Earlier timings from the harness with incomplete
equality checks are not current acceptance evidence. Warm medians of the four
later r5 repetitions unless marked cold:

| Mode | Seconds | Relative |
| --- | --- | --- |
| Bare physics: the retained evolve, operators reused | 0.06942225 | reference |
| Bare physics including preparation and the eigensystem | 0.07055135 (cold 0.07200920) | |
| Common-state continuation of the same steps, in memory | 0.06916625 | -0.37% |
| Stored workflow: new ledger, accepted clock, 4 commits in a fresh store | 0.10483610 (cold 0.25231910) | +0.03541385 s / +51.01% |
| of which the 4 commits | 0.01962780 | 18.72% of the workflow |
| of which ledger creation | 0.00720425 (cold 0.15538810) | |
| Reopening in a fresh process at step 8: root, head restore, operators (cold) | 0.11811750 (0.11099510 + 0.00416610 + 0.00295630) | |
| then the remaining 8 steps, cold | 0.04678690 | uninterrupted warm remainder: 0.03418340 |
| Importing the package in that fresh process | 0.76603600 | |

The continuation difference is only -0.00025600 s on this tiny case (r2 recorded
+0.00027305 s); it does not establish a meaningful speed gain or a general
overhead percentage. Durable saving
has a measurable cost here. This is an overhead measurement, not an optimisation
speedup claim, and the cold remainder is not a matched warm comparison.

The store holds 45,056 bytes after the root and grows by 6,144 bytes per successor
commit (69,632 bytes after 4): 25 unique chunks, 4,290 encoded payload bytes, and 3,072
bytes of arrays per successor against 18,320 bytes for a whole state.

Commits are dominated by SQLite's durable-commit flushes; savepoint spacing is the
caller's trade-off between commit cost and work at risk. Reopening cost is mostly
first-use cost in a new process: the root's first open takes 0.111 s cold.
Unchanged reference, initial and material payloads are
stored once; each successor adds its three current arrays and metadata. Nothing is
parallelised: the steps are one sequential feedback chain. This measures the wrapper
around one small column, not a whole-generator speed.

## 8. Evidence effects

New package modules (`integration_ledger`, `integration_clock`) and the edited
`integration_state`, `storage` and `resources` change the package's execution identity.
The refreshed finite-admission control binds its restoration dependencies; the
current timing record also binds the complete package and workflow sources.

**Paused and saved jobs of other routes.** This integration changes what earlier
W12 and New World jobs recorded, so they refuse to continue, by design (nothing is
rebound):

- A managed W12 job records its worker sources and the package execution identity; a
  job started before the integration refuses `resume` with `SOURCE_MISMATCH`, and a
  saved W12 result, read through `read_tectonics.py` or the view adapter, reports
  `VERIFICATION_FAILED`: `assembly.read_product` requires the product's recorded
  execution identity to be the current one.
- A New World job records its adapters (including `tectonics_job.py` and
  `read_tectonics.py`) and the package execution identity: `resume` and its regional
  output export refuse with `SOURCE_MISMATCH`, and so does saving a bundle with such a
  job. Bundles already saved stay inspectable, reporting `continuation_compatible:
  false` with `continuation_refusal: SOURCE_MISMATCH`. Saved New World worlds with
  initial structure and motion still load and can be inspected, but starting a new
  evolution job from them, generating motion from a saved structure and re-saving them
  with structure and motion refuse with `SOURCE_MISMATCH`, because those records carry
  the old execution identity. New World project plans bind the contract source and
  Python runtime only and are unaffected.
- Any other saved state that records the package execution identity (for example
  W03, W04 and regional workflow states) likewise refuses continuation or
  publication. This follows from every package change, not from I02 in particular.
- The package modules alone cause this, since the execution identity covers the whole
  package; the Windows retries in `tectonics_job.py` and `read_tectonics.py` are a
  second cause. The view adapter's own identity also includes `read_tectonics.py`, so
  its view identifiers change.

The finite-admission tool gained `restored()` and now binds, and checks that it
imports, every package module `restored()` executes: the ledger, its store and the
restorer (`integration_ledger`, `storage`, `integration_state`) with the helpers they
call (`_validation`, `materials`, `resources`, `timebase`, and `w08_inventory` with
`constitutive` when stocks are attached), and `mesh`, which the `Ledger.open` it relies
on executes; the retained owners it already bound (`integration_evolution` and the
`_integration_*` modules) are executed too. Its own file and the bound method document
[`docs/I01_FINITE_ADMISSION.md`](I01_FINITE_ADMISSION.md) changed as well, so
`i01-finite-admission-r3` no longer matches the implementation. It is now
**superseded** by the freshly captured passing `i01-finite-admission-r4`, without
rewriting its bytes. The stress-coordinate correction also required seven upstream
or dependent captures: weakening r4, column heat r5, motion coupling r3, column
admission r3, thermomechanical motion r4, finite strain r5 and breakup closure r4.
All eight passed; unchanged column r2 was reused. The [evidence guide](../../docs/CURRENT_EVIDENCE.md)
records the dependency order. These source-bound controls retain their existing
cases and scientific tolerances.

R1 then changed `timebase` and `w08_inventory`, and strengthened whole-package
loaded-code/data identity. Fresh finite-admission r5 passed all five controls and
supersedes r4; timing r2 passed all seven equivalence checks and supersedes r1.
Their valid prerequisites were reused. Prior receipt bytes remain unchanged.

The 3-D solver scaling (the matrix-free multigrid method and the automatic
gmres/multigrid choice) then rewrote three 3-D package modules and added two. No
I01 or I02 control reads them, but timing r2 binds every package source. Timing
r3 was captured on a first version of the choice that was never committed. Timing
r4 on the multigrid-first version passed all seven checks with 151 bindings and
superseded r3, which superseded r2. The subsequent 3-D evolution restart-admission
correction changed package sources again. Fresh timing r5 passed all seven checks
over five repetitions with 151 bindings and supersedes r4; r1-r4 remain unchanged.
This successor checks the bounded column workflow, not 3-D solver speed. No other
current record binds the changed files.

R4 and its follow-up fixes are integrated locally, changing `storage`,
`tectonic_history`, `tectonic_history_codec`, `reuse`, resource/solver accounting
and `tools/tectonics_job.py`. Timing r5 (whole package and `tectonics_job.py`) and
finite-admission r5 (restoration dependencies) are now superseded by fresh
[timing r6](../evidence/i02-workflow-timing-r6.json) and
[finite-admission r6](../evidence/i01-finite-admission-r6.json). All seven timing
checks and all five admission controls passed with unchanged sources; valid
upstream receipts were reused. The old receipts were not edited. Final
Git-normalised integration verification passed as recorded in section 6 above.
`tectonics_job.py` is one of this workflow's sources, so column-workflow projects saved
before it refuse `advance` and `load` with `SOURCE_MISMATCH`. Its control files are now
written as compact JSON; they are read as JSON, so the format alone refuses nothing.
The ledger's store now also reports a lock that is already held when a `put` starts
preparing as `StoreError` (previously a raw SQLite error), matching the commit
contract above.

R7 and its follow-up corrections change the shared package identity again.
[Timing r7](../evidence/i02-workflow-timing-r7.json) supersedes r6 after passing all
seven checks over five repetitions; 151 source bindings are renewed without
rewriting an earlier receipt. Finite-admission r6 and the other unchanged current
records remain valid and were reused. Earlier saved execution-bound states must
still satisfy their exact source/runtime contracts; no silent migration is added.
The current integration checks are in [the evidence guide](../../docs/CURRENT_EVIDENCE.md#integration-checks).

I03's ledger/clock integration and junction extension then required finite-admission
r7 and timing r8. The final K1–K5 repairs supersede those receipts with
[finite-admission r8](../evidence/i01-finite-admission-r8.json) and
[timing r9](../evidence/i02-workflow-timing-r9.json): all five admission controls
and all seven timing checks passed, with unchanged prerequisite receipts.
The I03 N1 change to `integration_transfer.py` then superseded timing r9 with
[timing r10](../evidence/i02-workflow-timing-r10.json), whose seven checks also
passed; finite-admission r8 does not bind that file and stays current.
Earlier receipts retain their original bytes. These successors renew the bounded
column's affected source bindings; they do not measure spherical or 3-D solver
performance, establish whole-world acceptance or migrate saved execution-bound
states. The repaired candidate is integrated locally; final promotion checks are
recorded in the evidence guide.

## 9. Acceptance commands after review

The patch and corrections are integrated. These commands identify the relevant
checks for subsequent changes; do not rerun all of them merely for reassurance.
The 30 September closeout reused unchanged shared-system results and ran the final
normalised I01/I02 guard once successfully after the affected captures. Run selected
commands from the repository root with the tested interpreter:

```text
python -B -m unittest discover -s tectonics/tests -p test_combined_resources.py
python -B -m unittest discover -s tectonics/tests -p test_storage_profiles.py
python -B -m unittest discover -s tectonics/tests -p test_memory_storage.py
python -B -m unittest discover -s tectonics/tests -p test_execution_reuse.py
python -B -m unittest discover -s tectonics/tests -p test_kernel_batches.py
python -B -m unittest discover -s tectonics/tests -p test_source_inventory.py
python -B -m unittest discover -s tectonics/tests -p test_i02_common_state.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_evolution.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_exchange.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_clock.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_persistence.py -v
python -B -m unittest discover -s tectonics/tests -p test_i01_finite_admission.py -v
python -B -m unittest discover -s tectonics/tests -p test_tectonics_job.py
python -B -m unittest discover -s tectonics/tests -p test_view_tectonics.py
python -B -m unittest discover -s tectonics/tests -p test_w12_job_worker.py
python -B -m unittest discover -s tectonics/tests -p test_new_world_job.py
python -B -m unittest discover -s tectonics/tests -p test_i02_workflow.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_joined.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_restart_regressions.py -v
python -B -m unittest discover -s tectonics/tests -p test_i02_measurement.py -v
python -B -m unittest discover -s tectonics/tests -p "test_i0[12]_*.py"
python -B tectonics/tools/measure_i02_workflow.py --output <new file outside the repository>
python -B tools/check_current_evidence.py
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
python -B tools/check_before_commit.py
```

A Linux run of the same focused modules is still needed for platform coverage.

## 10. Sources

Newly consulted for these steps: SQLite's [transactions](https://www.sqlite.org/lang_transaction.html)
and [atomic commit](https://www.sqlite.org/atomiccommit.html) pages (WAL is not used,
so its page was not needed), and, for the read-only snapshots added in the third
verification round, its [URI filenames](https://www.sqlite.org/uri.html),
[online backup](https://www.sqlite.org/backup.html) and
[result codes](https://www.sqlite.org/rescode.html) pages. Inspected: the package
`storage`, `integration_state`, `integration_evolution`, `materials`, `w08_inventory`,
`timebase`, `reuse`, `resources`, `_validation`, `assembly` and `workflow_ports`
modules; the `tectonics_job`, `read_tectonics`, `view_tectonics`, `w12_job_worker`,
`new_world_job`, `new_world_bundle`, `new_world_project`, `new_world_contract`,
`new_world_evolution`, finite-strain and finite-admission tools; and the I01 case
files. The physics and its references are the I01 finite-strain and finite-admission
methods, reused unchanged and not re-read here. The 30 September correction
inspected the existing constitutive residual, its bracketed Newton iteration and
the engine-owned restart path; it changes numerical coordinates at stagnation,
not the physical equations. No new physical paper, external solver or calibration
was introduced for that repair.

## 11. Limits and what remains

One bounded case: a closed strip with no inflow, extraction, births or events, and no
transfers produced by physics (the exchange machinery is exercised with declared
proposals). The store is trusted local state (section 2), and enthalpy moved with
mass is the producer's declaration. No elastic, melt, elevation, spherical or lateral state. The accepted
clock admits no event physics; adaptive or event-localising schedules need their own
admitted policy. Linux coverage remains outstanding; review, corrections and
affected successor captures are complete. I03–I09 still own the evolving sphere, causal motion, transport and melt,
transitions, support and their coupled acceptance; I10 owns the world-project and UI
route. Whole-planet evolution remains the goal; this workflow does not provide it.
