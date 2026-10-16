# WP18 part 1 (endpoint cross-support batching, hardest first): design note, deferred

16 October 2026, chat "Geometry, growth and workers". Deferred by the coordinator's D-g:
"done if time and usage allow before Step 10, otherwise after interval 2". On 16 Oct the
weekly usage pace (49% about 12 h into the week) did not allow it.

## The gap (confirmed in RC1)
- `integration_component_volume_auto.py` (`AutomaticEndpoints`):
  - `bind_support` offers only the current support's jobs.
  - `_beyond()` returns the jobs left in that support.
  - The schedule's limit is 32 jobs and its horizon 64 requests.
- `integration_parallel_rolling.py`, around 455-485: `projected = sight + _beyond()*rate`
  is compared with `minimum_seconds` (120 s). For one support that projection stays far
  below 120 s, so the endpoint schedule practically never engages. Every endpoint query
  runs serially in the parent.

## Measured size of the prize
- IV2 endpoints, full candidate: 401 CPU-s serial for 37,083 queries
  (`G/evidence/final-f1/iv2-endpoints.json`).
- With 4 workers, at best about 4-5 minutes saved per interval at IV2. IV3 forecast
  about x2.
- The heat-mesh construction queries share the route, which may add a little.

## Design sketch
1. `_beyond()`: an exact count of the endpoint jobs in the REMAINING supports of the pass.
   The partition already lists components per support, and the counts need no decode, so
   the 120 s threshold sees the whole pass.
2. Cross-support offers: `bind_support` may pre-offer up to the horizon from the next
   supports, using retained compact handles. Keep the serial adoption order: workers only
   compute ahead, and the parent adopts in router order, so outputs and receipts stay
   order-independent and identical to serial.
3. Hardest first inside the lookahead window: order candidate batches by estimated cost
   (literals, partition-path length), not router order. Adoption order is unchanged.
4. Pins: `partition_routing_transform.py` (Step 8's C file) pins the scheduler sources
   by hash. Send it an exact diff for the new pins.

## 16 Oct ~12:45 re-assessment (MEASURED inputs, PROJECTED payoff)
- The query costs come from `evidence/final-f1/cand-iv2-endpoints-s*.jsonl` (full candidate, serial wall).
  - IV2: 27,004 queries, 402 s. Median 4.5 ms, mean 15 ms, p90 41 ms, max 0.67 s.
  - The top 10% of queries take 41% of the time and the top 20% take 63%. 'end' endpoints are
    347 s of the 402.
  - There are 3,502 supports, a median of 5 queries each and at most 329.
  - IV1: 7,181 queries, 91 s.
- **Hardest first is dead.** The scheduler's labels (endpoint, constraints, path length) do not
  predict cost: of 75 labels, 2 have a median of 30 ms or more, covering 365 queries and 11.5 s.
  Cost tracks work_units (correlation 0.89), which is known only afterwards.
- **The 32-job / 64-horizon endpoint clamp makes batching impossible**, not the 120 s threshold.
  - Each batch is a one-shot subprocess, and the policy books 3.0 s start-up plus 0.4 s
    transfer, so a batch must save at least 3.4 s.
  - 32 jobs at 15 ms is 0.5 s. A 64-request lookahead hides about 1 s of parent work against
    3 + 1.3 x cost of start-up, so no batch can ever pay.
- **Projection** (`scripts/project_endpoint_batches.py`): an event model over the measured
  costs in router order, where the planner knows only the parent's running mean.

  | Workers, jobs per batch, horizon | IV2 wall | IV1 wall |
  |---|---|---|
  | Today: 2, 32, 64 | 402 s (no batches) | 91 s |
  | 2, 512, 4096 (the policy's own defaults) | 217 s (1.85x) | 57 s (1.61x) |
  | 4, 256, 4096 | 170 s (2.37x) | |
  | 6, 256, 4096 | 135 s (2.97x) | |
  | 6, 512, 4096 | 148 s (2.72x) | 41 s (2.21x) |
  | 6, 512, 8192 | 129 s (3.11x) | |

- Transport is no constraint: supports average about 25 KB encoded, with a maximum of 470 KB,
  so a 512-job batch over about 66 supports is about 2 MB, far below MAX_BATCH_INPUT (64 MB).
- **What part 1 needs** (decisions first):
  - (a) Lift the endpoint clamp `min(batch_jobs, 32)` / `min(horizon, 64)` in
    `integration_component_volume_auto.py` to the policy's general bounds (512 / 4096), which
    are already reviewed for walls and interfaces. Then `self.cached` follows (2 x horizon + 64).
  - (b) A cross-support lookahead:
    - `_beyond()` = (supports left) x (jobs per support so far), the wall pass's own estimator.
    - `bind_support` keeps offering from the next supports, whose rows are projected ahead and
      handed to the ALE loop so each support is still projected once. That is a transform of
      `integration_differential_ale.py` line ~690 plus the auto module.
    - In compact mode the projection goes through Step 8's `project_compact` /
      `retain_support`, so the lookahead holds handles for about 500 supports ahead; Step 8 gets
      a diff.
  - (c) Optional: lift ComponentParallelSession's 1..2 worker bound to 6, for 2.7-3.1x instead
    of 1.85x. Its children decode one support at a time.
- A cheaper first lever may be the per-query cost itself (work_units drive the time). No profile
  of the endpoint pass exists yet; `replay_queries.py --profile --every 20` on IV2 would show
  where the 15 ms goes.

## Parity required
- Endpoint records byte-identical, serial against parallel, on IV1 all and IV2 all
  (`G/scripts/replay_queries.py` with the production batch route; PYTHONHASHSEED=0).
- Receipts identical; schedule reports differ only in timing fields.
