"""D-j (coordinator-approved, 16 Oct 2026): above two workers, rolling interface batches own the interface pass.

Source transform of atlas_tectonics/integration_parallel_selection.py, stacked AFTER
workers_six.py. In RC1 the single-contact planner opens its session whenever the profile can
reach the threshold, and an open single-contact session owns the interface pass:
open_interface_batches() attaches nothing beside it ("the budget has room for one optional
owner"). The single-contact route dispatches at most two workers, so with workers_six's 4-6
workers the interval-2 sample still ran at most two (G/evidence/workers-six-r2, IV2 arms).

This transform: when the policy asks for MORE than two workers and the rolling schedule is on
(batch_seconds is not None), the selection records a gate and does not open the single-contact
session; the interface pass is then left to the rolling interface batches, which use every
admitted worker under the same memory, core, booked-envelope and predicate cuts. At one or two
workers, with batch_seconds None, or with a per-contact floor (minimum_job_seconds, which only
the single-contact rule applies; refuter 16 Oct), nothing changes (RC1's route). Execution only: no record,
equation, tolerance or result depends on which route runs a request (parity:
G/evidence/workers-six-r3).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'f1a8957ac509d4996b0a49c1f94b7718bf40bbc16cc6d30f4ddfb25a492688d4': 'RC1 selection + workers_six (2296e269)',
}
OLD = ("        self.session = self._new_session(budget=budget, context=context, max_width_m3=max_width_m3,\n"
       "            max_leaves=max_leaves, planner=self, child_bytes=policy.child_bytes,\n"
       "            predicate_units=policy.predicate_units, timeout_seconds=policy.timeout_seconds)\n"
       "        self.observer.session = self.session\n")
NEW = ("        # D-j: above two workers the rolling interface batches own the interface pass; the\n"
       "        # single-contact planner (at most two workers) would otherwise take it and attach\n"
       "        # nothing beside itself. At one or two workers this is RC1's route unchanged.\n"
       "        # A per-contact floor (minimum_job_seconds) is a single-contact rule the rolling schedule\n"
       "        # does not apply, so a policy that sets one keeps RC1's route.\n"
       "        if not self._gate('interface-route', dict(workers=policy.workers, batch_seconds=policy.batch_seconds,\n"
       "                                                  minimum_job_seconds=policy.minimum_job_seconds),\n"
       "                          policy.workers <= 2 or policy.batch_seconds is None\n"
       "                          or policy.minimum_job_seconds is not None):\n"
       "            return self._serial('rolling interface batches',\n"
       "                'more than two workers: the single-contact planner is not opened, so the rolling '\n"
       "                'interface batches own the interface pass')\n"
       + OLD)


def transform(source, *, allow_unreviewed_input=False):
    if "'interface-route'" in source:
        raise ValueError('rolling-interfaces transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('selection input is not RC1 + workers_six; pass allow_unreviewed_input and re-run parity')
    if source.count(OLD) != 1:
        raise ValueError('rolling-interfaces anchor must occur exactly once')
    return source.replace(OLD, NEW)
