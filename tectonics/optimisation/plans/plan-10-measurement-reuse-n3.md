# Plan 10: initial measurement reuse N3 / backlog item 7

**Status:** WORKING NON-CANON. q08 passed; final-chain integration remains pending. This plan incorporates the room consensus in general507-508; acceptance of this document is not implementation or run clearance.  
**Owner:** Runner. Codex's assignment here is the plan correction only.  
**Completion condition:** carry the existing producer-only, same-lineage reuse route through the selected final composition, retaining all eight Item 7 trust conditions, source-bound evidence and independent reader recomputation. q08 alone does not prove that integration.

## 1. Scope, status and measured benefit

The relevant stage is `initial_metrics`: the retained proof exercised 969 initial component measurement queries/snapshots. This is not a cache of invented planetary ocean, geodetic or crustal tables, nor a new generic cache subsystem.

The current Runner record reports:

| q08 arm / check | Retained result |
| --- | --- |
| Miss admission | 910.92 s; 8 checks, all true |
| Hit admission | 64.38 s; 21 checks, all true |
| Store comparison | Both stores byte-identical to the historical `e337fc20...` pin |
| Identity comparison | `bounds_id`, `geometry_id` and `workflow_id` equal; Run-A workflow `9ecd96b8...` |
| Reported peak | 0.31 GiB |
| Conditions | MEASURED under gaming load; indicative only |

The measured difference is approximately 846.54 seconds for this comparison, not a promised future duration or timing pass threshold. It benefits the producer admission/reopen route once per lineage. Interval 2+ producer continuation restores the spatial owner from the sealed, pinned lineage without `initial_metrics`; savings must not be multiplied by the number of intervals or added to overlapping admission improvements. The independent reader still performs its legitimate full measurement recomputation.

The owner explicitly recorded no separate quiet re-time ticket: later authorised fresh runs measure the integrated route in place. q08 is retained evidence, not authority to release those runs.

## 2. Actual implementation and evidence

Path aliases:

- `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`
- `WT = A/.claude/worktrees/rv/tectonics/optimisation`
- `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `S = R/probes/step9/claude-20261016`

| Primary source | Relevant contract or observation |
| --- | --- |
| `A/.atlas-dev/plan-status-20261016.md`, Drivers, admission and proof tools | N3/q08 passed; preserve trust conditions and include in final chain; live R and frozen composition are not established as swapped |
| `A/.atlas-dev/review-item7-item10-20261016.md`, complete Item 7 section | Accepted conditions 1-8; distinguish its earlier findings from later repaired code and accepted q08 evidence |
| `A/.atlas-dev/coordinator-handoff-20261016.md`, section 4 | Item 7 conditions; Item 10 phase 2 only after Item 7; interval 2+ restores sealed lineage |
| `R/probes/step8/claude-20261015/STATE-NOTE.md`, LIVE 17:38 section | q08 results and later acceptance; no quiet re-time ticket |
| `WT/drivers/run_fresh_interval.py` | `measurement_composition`, `measurement_record`, `_copy_pinned`, `seed_initial_measurements` (line 716 at review), `reuse_outcome`, and refusal recording |
| `WT/drivers/launch_fresh_interval.py` | `initial_measurement_seed`: obtain recorded pins from the adopted root stage |
| `WT/drivers/reopen_fresh_restart.py` | `require_fresh_measurement_store`: reject seed inputs and pre-existing store/sidecars before reader admission |

The reviewed worktree has this plumbing. Its existence does not establish a live R or frozen-composition swap, completed final-chain integration, or unchanged code at a later deployment. Runner must identify the actual selected composition and its successor receipts. Review-time full source hashes and selected evidence scope are retained in [Codex's Plan 10 discussion record](../discussions/atlas-plans-39-review-20261017/codex-plan-10-turn-02.md); the frozen independent review stays unchanged.

## 3. Preserve the eight accepted trust conditions

### Condition 1: record the closed store, then pass its recorded pin

Run A records `initial-measurements.sqlite` only after admission closes, in `run.json` alongside its composition and counts. `measurement_record` binds the closed store to the FreshProfile/source information and interpreter seed.

The launcher passes the receipt SHA and store SHA recorded by that root. It must not hash the store at launch to manufacture a new pin. This does not prohibit the producer's required integrity checks before and after copying.

### Condition 2: authenticate the same-lineage origin and exact composition

The launcher's root-stage record must be ADOPTED with successful runner, reader, finalise and adopt steps. It checks the recorded receipt and adoption hashes and obtains the store pin from that pinned receipt.

The producer rechecks the exact root runner, reader verdict and adoption record. The reader must have passed the same sealed root and producer receipt; the adoption must follow that exact verdict. The pinned receipt must describe a clean sealed root of the same profile, with matching producer PID and workflow, and name the pinned measurement store.

`measurement_composition` must match field-for-field across the union of keys: profile SHA, source proof, advance-driver SHA, every helper SHA and interpreter seed. Preserve `PYTHONHASHSEED=0` and `hash_randomization=0`. A cache key alone does not bind imported helpers or the interpreter hash seed. Neither a hash of world parameters nor a hard-coded store digest authenticates this origin.

The historical `e337fc20...` digest is a proof fixture, not a universal cache key for other worlds or compositions.

### Condition 3: producer-only copying, independent reader, explicit successor identity

Copy in `run_fresh_interval`, outside the shared `FRESH.admission` used by the reader. The default is no seed. The independent reader performs a full recomputation in a fresh reader directory and actively refuses:

- any argument starting with `--seed`;
- the `ATLAS_INITIAL_MEASUREMENT_SEED` environment variable;
- an existing `initial-measurements.sqlite` or any `-wal`, `-journal` or `-shm` sidecar before admission.

The producer also refuses the seed environment variable: seeds are explicit arguments only. Do not share a populated producer store with the reader or prohibit its legitimate initial-measurement work.

Actual changes to the fresh driver or runners require a new profile, source/advance-driver pins and a new receipt. Preserve the old s2 receipts unchanged. A document correction is not a source repin or a deployed successor.

### Condition 4: copy a closed pinned file; refuse invalid seeds before admission

Preserve the implemented checks and their order:

1. Require the closed ordinary source store with none of `-wal`, `-journal`, `-shm`; require destination and its sidecars to be absent.
2. Hash the source against the recorded pin before copying.
3. Create the destination exclusively, hash the copied stream, flush and fsync.
4. Require the stream hash to match; re-digest source and destination against the pin and check source-sidecar absence again.

Seed validation or copy errors record `REFUSED_BEFORE_ADMISSION`, save the refusal and re-raise. A wrong pin, missing source, sidecar, existing target, changed copy, unauthenticated receipt or mismatched composition must not silently fall back to fresh generation. Do not turn refusal into a successful admission.

Keep the pinned source and historical receipts untouched. Any tamper case uses disposable copies; no mutation or chmod of the golden store is part of this plan.

### Condition 5: distinguish invalid seeds from valid misses

Record `reused_initial_cache` with source, pinned SHA, receipt/verdict/adoption bindings, copy details, hit/miss counts and the store SHA after admission. `reuse_outcome` derives misses from new snapshots and hits from the remaining queries, and checks count/byte consistency.

- `FULL_REUSE`: zero misses and after-SHA equal to the pin, meaning no new stored measurements.
- `MISSES_MEASURED`: ordinary misses after a valid seed are recorded as a milestone; they are not automatically a failure or an invalid-seed fallback.
- `COUNTS_DISAGREE_WITH_BYTES`: retain the inconsistency as such; do not report successful reuse.

The q08 full-hit proof requires unchanged bytes. That requirement must not erase the production route's legitimate reporting of valid misses.

### Condition 6: retain fail-closed proof and its actual scope

For the retained proof, `S/time_admission_parts.py` must return non-zero if any required compared field is absent or false. Preserve comparisons of `bounds.bounds_id`, `mesh.geometry_id`, `workflow_id`, `store_unchanged_from_seed=True`, empty `store_sidecars`, both store hashes against the historical pin, and the recorded Run-A workflow/bounds identities. Matching only fields that happen to be present is insufficient.

The earlier Item 7 review diagnosed missing plumbing and a proof script that always exited zero. Later worktree implementation and accepted q08 results supersede those historical findings where repaired; do not describe them as current failures without new evidence. Conversely, the bench result does not prove all production or final-composition boundaries. Retain the exact evidence scope and source identity for each claim. An authorised heavy miss arm belongs in the existing queue; this plan creates no new timing run.

### Condition 7: use focused production evidence

Runner carries adequate, unchanged evidence for wrong SHA, journal/sidecar presence, existing destination, missing path, profile or seed mismatch, and reader seed rejection. The production route also needs the accepted bounded Run-B smoke that stops before interval advance and demonstrates reuse through the real runner and root identity comparison.

Reuse recorded checks while their relevant source, profile, configuration and input identities remain valid. If integration changes those boundaries or leaves a coverage gap, perform only the necessary authorised checks under the existing queue and refutation requirements. Do not substitute a new three-interval scientific sequence, rerun q08 for reassurance or treat the plan's acceptance as permission to start tests.

### Condition 8: state what a hit proves

A hit checks stored-field consistency with the request and stored record. It does not re-certify the geometry. `ROOT_IDENTITY` against the sealed root and the independent reader's full recomputation provide the separate backstop. Preserve those boundaries and report actual measured hit time with its conditions. Extend a benefit claim to another route only when that route exists and has been reviewed under these same rules.

## 4. Integration boundary and holds

Runner retains implementation and integration ownership. The selected final chain must preserve the contracts above alongside the continuation route in [Plan 29](plan-29-runner-integration-n5.md), with [Plan 09](plan-09-parallel-admission-ip9.md) coordinated where admission composition changes. Stage-overlap phase 2 follows Item 7 under [Plan 11](plan-11-stage-overlap-phase2.md); its approval does not extend to phases 1 or 3.

Apply C1-C5: exact field/number parity with only explicitly approved identity translations and the bounded N9 exception; the real projected width gate with a 1 MiB integer bound (8,388,608 bits), without a fixed 25% ceiling; measured/projected and built/integrated/accepted status kept distinct; existing owners, authority and holds preserved; primary sources govern mechanisms and status. Keep the 12 GiB tree-RSS, 1 GiB free floor, 16 GiB logical, 256 MiB scope and 256 accepted-step limits. No numerical tolerance, loaded-code check, environment or historical pin is relaxed.

Fresh full intervals remain held until the required optimisation, assembly and integration work and specific run authority are in place. N9 remains PAUSED BY USER and individual job holds remain in force. This plan authorises no implementation, benchmark, queue action, runtime swap or publication.

## 5. Completion evidence still required

These boxes describe remaining integration evidence, not unfinished q08 measurements:

- [ ] Runner identifies the selected final composition and carries all eight trust conditions into it with current source/profile/receipt bindings; old s2 evidence remains unchanged.
- [ ] Authenticated origin, exclusive copy and refusal behaviour are supported by adequate source-bound production checks, including reader isolation and the bounded Run-B smoke.
- [ ] Reuse records correctly distinguish full reuse, measured misses, invalid seeds and count/byte inconsistencies; root identity and independent reader checks remain effective.
- [ ] The final chain has its required integration evidence, with new profile/pins/receipt for actual driver changes; q08 and worktree code existence are not used as substitutes.
- [ ] The owner record retains the once-per-lineage timing scope, remaining dependencies and run holds, with no separate quiet re-time or held scientific sequence added.
