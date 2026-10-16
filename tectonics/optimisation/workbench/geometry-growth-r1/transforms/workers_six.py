"""WP18 (coordinator-approved, 16 Oct 2026): allow 1-6 rolling-batch workers; every memory/core cut unchanged.

Source transform of atlas_tectonics/integration_parallel_selection.py. RC1 refuses any
InterfaceParallelPolicy with more than two workers (`_whole(self.workers, 1, 2)`), so the
measured 4- and 6-worker interval-2 schedules cannot run. This accepts 1..6.

Audit of what was sized for at most two workers, and its disposition here:
- InterfaceParallelPolicy.__post_init__ `_whole(self.workers, 1, 2)` -> 1..6 (no higher until
  measured). Docstring updated.
- `schedule()` (the single-contact planner, pure) tries EVERY combination of up to `workers`
  positions in a lookahead of up to 64 contacts: about 2e3 sets at 2, about 7.5e7 at 6, per
  decision. It also feeds a dispatcher whose thread pool is fixed at 2
  (integration_parallel_dispatch.py `ThreadPoolExecutor(max_workers=2)` for the single-
  contact route). The single-contact planner therefore keeps its exact old bound:
  `workers=min(self.workers, 2)`. Unchanged at 1 and 2; at 4 and 6 the rolling batches use
  the extra workers.
- `_resources()` (cores: parent + n free physical cores; RAM: n x (child_bytes + baseline) +
  ram_reserve within free physical memory; booked: within budget_fraction of the run budget;
  predicate units): loops n down from the policy until every cut fits. UNCHANGED, so the
  count is still clamped by measured memory and free cores at launch. Docstring only.
- Rolling schedule (integration_parallel_rolling.py): lanes = workers + 1, at most `workers`
  running and 2 x workers batches outstanding: scales as written; unchanged.
- BatchParallelSession (integration_parallel_dispatch.py): validates workers >= 1, its pool is
  `max_workers=self.workers`, and each launch re-checks the booked envelope
  (`held + child + baseline <= fraction x available`): scales; unchanged.
- ComponentParallelSession (integration_component_volume_parallel.py) refuses more than two
  endpoint workers and the automatic endpoint route takes its count from the same policy:
  companion transform `workers_six_endpoint_clamp.py` clamps that route's count to 2 after
  its machine gates (no endpoint parity above 2; endpoint batching is WP18 part 1, deferred).
  The session itself keeps RC1's 1..2. (`workers_six_endpoints.py`, which widened the
  session, is superseded and must not be composed.)
- Observer/profile: `contention` (1.3) and `parent_slowdown` are estimates for scheduling
  only; record bytes do not depend on them. The runner's process-tree guard is not in this
  package (Steps 8-9 own it): its own worker clamp must be lifted there for more than two
  workers to be selected in production.
Records: the selection only chooses execution; adopted results are byte-identical
(parity: G/evidence/workers-six-r2, with the peak number of live batch workers recorded).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '536c3e3e9328db0758e6f9d1821a68e729ef2cf023d45d01d02b5cbbc446926c': 'RC1 composed-r1 runtime-src',
}
MAX_WORKERS = 6

EDITS = (
    ("    earlier rule). workers is 1 or 2. A class needs minimum_samples integrator\n",
     "    earlier rule). workers is 1 to 6 (rolling batches; the single-contact\n"
     "    planner still dispatches at most 2). A class needs minimum_samples integrator\n"),
    ("        if (not _whole(self.workers, 1, 2) or not _whole(self.lookahead, 1, D.SCAN_LIMIT)\n",
     "        if (not _whole(self.workers, 1, 6) or not _whole(self.lookahead, 1, D.SCAN_LIMIT)\n"),
    ("            raise ValueError('one or two workers, a lookahead within the scan limit and a positive sample count required')\n",
     "            raise ValueError('one to six workers, a lookahead within the scan limit and a positive sample count required')\n"),
    ('        """Machine and ledger hints for one or two workers; nothing is reserved."""\n',
     '        """Machine and ledger hints for the policy\'s workers, cut down until all fit; nothing is reserved."""\n'),
    ("        found = schedule(costs, eligible, workers=self.workers, startup=startup, transfer=policy.transfer_seconds,\n",
     "        # The single-contact planner's exhaustive search and its 2-thread dispatcher keep\n"
     "        # their old bound; extra workers serve the rolling batches.\n"
     "        found = schedule(costs, eligible, workers=min(self.workers, 2), startup=startup, transfer=policy.transfer_seconds,\n"),
    # The single-contact plan reports the count it actually plans with.
    ("        plan.update(startup_seconds=startup, serial_seconds=found['serial_seconds'], saving=found['saving'],\n",
     "        plan.update(workers=min(self.workers, 2), startup_seconds=startup, serial_seconds=found['serial_seconds'],\n"
     "                    saving=found['saving'],\n"),
)


def transform(source, *, allow_unreviewed_input=False):
    if '_whole(self.workers, 1, 6)' in source:
        raise ValueError('workers-six transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('selection input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('workers-six anchor must occur exactly once: ' + old[:60])
        source = source.replace(old, new)
    return source
