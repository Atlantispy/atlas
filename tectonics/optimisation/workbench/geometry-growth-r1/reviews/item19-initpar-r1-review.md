# Item 19 (initpar r1) — code-owner review, 16 Oct 2026

Reviewed: `T/ck/transforms/initpar_r1.py` (sha 3799958b…), `T/ck/initpar/integration_initial_parallel.py`
(sha d1214c54…), the built outputs on workers6-r6 and the unchanged code they call
(`integration_parallel_dispatch.BatchParallelSession.claim/_member/_receive/_finish`,
`ComponentParallelSession.__init__`).

## Stacking on gg/workers6-r6: clean
Built with `T/ck/initpar/build_runtime.py` into `T/gg/ipw6-r1/src` (manifest `T/gg/ipw6-r1/INITPAR_MANIFEST.json`).
Only the five files and the new module change. Every hunk is identical to its composed-r2 → ck/ip4 counterpart.

| file | workers6-r6 → ipw6-r1 |
|---|---|
| integration_dual_geometry.py | a48347c0 → f9ebdd64 |
| integration_differential_geometry.py | b4d95389 → f0bce411 |
| integration_parallel_binding.py | 70db056a → 4eb627dc |
| integration_parallel_results.py | f48cda05 → 73091fd3 |
| integration_component_volume_parallel.py | fafc76fb → a4785573 |
| integration_initial_parallel.py (new) | d1214c54 |

## Findings
1. **P2, efficiency and memory, warm store only. Records are not affected.**
   - What happens: `cached_initial_component` calls `claim` only on a miss, so a store hit never claims its member. That batch's `left` never reaches 0, `_finish` never runs, and the batch stays in `session.batches` until close. It keeps its envelope (`fit`) and the job tuples' supports.
   - Consequence: once `outstanding` (6 at two workers) such batches have piled up, `_fill`'s `len(session.batches) < self.outstanding` stops all launches. The rest of the pass runs serial without a note, and the workers' answers for the hits were wasted CPU.
   - Fix, either of:
     - (a) the read-ahead skips members whose store key already hits (a read-only lookup before shipping);
     - (b) a hit consumes its member, e.g. `_volume.skip(support, cell_id, raw, …)`, which removes it from `members`, decrements `left` and finishes the batch at 0 once its child has exited.
   - Proof: add a warm-store arm (seeded measurement store) if the runner passes a store, because warm reopen is the Step 8 path.
2. **P3: no try/finally around `prefetch.finish()`** (differential `enclose_initial_partition`).
   - What happens: if a component raises (accuracy unmet), the session stays open until the caller's `with InitialParallel` exits.
   - Consequence: if a caller catches the error and retries inside the same pass, `start()` returns None (`started`). The retry runs serial while the stale session holds its admission for up to its 1800 s timeout.
   - Fix: `try: <loop> finally: prefetch.finish()`. `close()` is idempotent, so this is safe.
3. **Note: an honest unmet answer also closes the route.**
   - `_certified` refuses any `met` False, error > r or width miss and then closes the route. That is correct: the serial call that follows raises the same VolumeError.
   - The report note says "failed the query checks" and could be read as a defect. Distinguish "unmet" from "inconsistent".
4. **Note, compact mode.**
   - `_jobs` makes a third pass of `partition.supports`, after `count` and before the loop: every support is materialised and issued one more time.
   - Up to `outstanding × batch_jobs` = 96 issued supports are held in job tuples.
   - Runner pipeline's V2 rule applies: every borrowed ref must be gone before the partition closes. Confirm that the `with InitialParallel` exits before the partition's close.
   - WP18 used retained handles (`retain_support`) for the same reason.

## Checked and fine
- **Request match.**
  - `query(width)` runs once (declared_max_queries 1) with target = local_width = the session's `max_width_m3`.
  - `time_s` comes from `raw['start_time_s']`, the parent's own `support.record()`, which is checked static.
  - `relative_error` is the same Q.
- **Order.**
  - `_jobs` and the serial loop cover the same components of the same supports in the same order.
  - `claim` is keyed by the canonical request (`members[canonical(request)]`), with no position dependence.
- **Session class.** `InitialParallelSession.__init__` is `ComponentParallelSession.__init__` with this family's bound.
- **Context lifecycle.**
  - Nesting and re-entry are refused.
  - `close()` is idempotent and records stats.
  - The context var is reset in `finally`.
- **Adoption.** The adopted measure takes over the funded charge, and `measure = None` on refusal drops it.
- **Admission.** `validated_initial_volume` checks the request fields, work, leaves, met, nonnegative scalars, the witness and the poses, as for an endpoint record.
