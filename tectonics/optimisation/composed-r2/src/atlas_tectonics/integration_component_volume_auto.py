"""Endpoint scheduling through the existing automatic policy and owned workers.

Only the current, already funded routing row is offered. Endpoint observations
are transient within this pass: no interface profile is borrowed or repinned.
The numerical issuer, mandatory prefix and source-bound adoption are unchanged.
"""
from collections import deque
from time import perf_counter

from . import integration_parallel_selection as S
from .integration_component_volume_parallel import ComponentParallelSession


class AutomaticEndpoints(S._Rolling):
    family, adoption = 'endpoint-volume', 1.0

    def __init__(self, parent, width):
        self.width = width
        self.order, self.jobs, self.left = deque(), None, 0
        self.label = self.started = None
        self.prepared = False
        self.checkpoint_hits = 0
        super().__init__(parent)
        if self.schedule is not None:
            # Preserve the reviewed endpoint transport bounds and keep the
            # current support's metadata lookahead small.
            self.schedule.limit = min(self.policy.batch_jobs, 32)
            self.schedule.horizon = min(self.policy.horizon, 64)
            self.cached = 2*self.schedule.horizon + 64

    def _seed(self):
        # Endpoint geometry has no validated stored timing classes yet. Learn
        # only actual endpoint bodies of this source/settings/pass.
        self.exact = False

    def prepare(self, supports):
        if self.prepared or self.closed:
            raise RuntimeError('one prepare per automatic endpoint pass')
        self.prepared = True

    def bind_support(self, support, row):
        if self.schedule is None or self.closed or self.schedule.stopped is not None:
            return
        try:
            if self.order or self.left:
                raise ValueError('previous endpoint support was not consumed in serial order')
            if getattr(support, '_compact_ref', None) is not None:
                # Offer the small retained handle, not the temporary native support.
                from partition_routing_patch import retain_support
                support = retain_support(support)
            parts = row['components']
            self.left = sum(1 + (part['parent_cell_id'] is not None) for part in parts)
            self.jobs = ((support, part['logical_cell_id'], endpoint, {},
                          (endpoint, len(part['constraints']), len(part['partition_path'])))
                         for part in parts for endpoint in ('start', 'end')
                         if endpoint != 'start' or part['parent_cell_id'] is not None)
            self._fill()
        except Exception as error:
            self.schedule._stop('endpoint lookahead error', S._text(error))

    def _beyond(self):
        # No whole-mesh decode or estimate of unseen supports.
        return self.left

    def _fill(self):
        if self.jobs is None or self.schedule is None or self.closed:
            return
        try:
            while self.schedule.hungry():
                item = next(self.jobs, None)
                if item is None:
                    self.jobs, self.left = None, 0
                    return
                support, key, endpoint, pair, label = item
                self.left -= 1
                self.total += 1
                self.order.append((key, endpoint, label))
                self.schedule.offer((support, key, endpoint, pair), 0.0, label)
                if not self.left:
                    self.jobs.close()
                    self.jobs = None
                    return
        except Exception as error:
            self.schedule._stop('endpoint lookahead error', S._text(error))

    def _open(self):
        refusal = self._machine()
        if refusal is not None:
            self.notes.append('%s: %s' % refusal)
            return None
        policy = self.policy
        session = ComponentParallelSession(budget=self.parent.budget,
            max_width_m3=self.width, max_leaves=self.parent.leaves, workers=self.workers,
            child_bytes=policy.child_bytes, predicate_units=policy.predicate_units,
            timeout_seconds=policy.timeout_seconds, budget_fraction=policy.budget_fraction)
        self.schedule.workers = self.workers
        self.session = session
        if not session.open(self.parent.context):
            self.notes.append('session: %s' % (session.plan.get('funding') or
                S._public(session.last_error or 'not opened')))
            return None
        return session

    def claim(self, request, budget):
        self.label = self.started = None
        schedule = self.schedule
        if schedule is not None and not self.closed:
            if self.order and self.order[0][:2] == (request['logical_cell_id'], request['endpoint']):
                _, _, self.label = self.order.popleft()
                schedule.reached()
            else:
                schedule.unlisted()
            self._fill()
            schedule.advance()
        self._begin()
        result = super().claim(request, budget)
        # Selection/transfer time is not learnt as endpoint numerical work.
        self.started = perf_counter()
        return result

    def checkpoint_consumed(self, logical_cell_id, endpoint):
        """Advance the restored query, without starting speculative work."""
        self.label = self.started = self._mark = None
        self.checkpoint_hits += 1
        schedule = self.schedule
        if schedule is None or self.closed:
            return
        if self.order and self.order[0][:2] == (logical_cell_id, endpoint):
            self.order.popleft()
            schedule.checkpoint_consumed()
            self._fill()
        else:
            schedule.unlisted()
            if self.order:
                schedule._stop('checkpoint order mismatch',
                    'restored endpoint does not match the next offered request')
        # Deliberately no advance(), _begin(), claim() or observed(): a cache
        # hit must not launch its own duplicate or teach disk time as geometry.
        # A later miss still uses the unchanged automatic selection path.

    def observed(self):
        if self.label is None or self.started is None or self.closed:
            return
        try:
            self._paid(self.label, True, max(0.0, perf_counter() - self.started))
        except Exception as error:
            if self.schedule is not None:
                self.schedule._stop('endpoint observation error', S._text(error))
        self.label = self.started = None

    def close(self):
        if self.finished:
            return
        # Drop iterator references to the funded routing row before stopping
        # workers or releasing optional storage. Failed stops remain retryable.
        if self.jobs is not None:
            self.jobs.close()
            self.jobs = None
        self.order.clear()
        super().close()
        try:
            report = self.summary()
            report['checkpoint_hits'] = self.checkpoint_hits
            report['checkpoint_lookahead'] = 'no pre-prefix lookup; already launched mixed batches may duplicate cached members'
            report['observation_scope'] = 'current endpoint pass only'
            report['lookahead_scope'] = 'current funded support only'
            self.parent.decision['endpoint_batches'] = report
            self._promote(report, 'endpoint batches selected')
        except Exception as error:
            self.parent.decision['notes'].append('endpoint report unavailable: ' + S._text(error))
        self.finished = True


def open_automatic_endpoints(parent, width):
    """Use the enclosure's policy; optional setup failures retain serial work."""
    if parent is None or parent.policy is None or parent.policy.mode == 'off':
        return None
    try:
        width = S.G.W._q(width)
        if width < 0:
            return None
        return AutomaticEndpoints(parent, width)
    except Exception as error:
        parent.decision['notes'].append('endpoint selection unavailable: ' + S._text(error))
        return None


def bind_support(controller, support, row):
    if type(controller) is AutomaticEndpoints:
        controller.bind_support(support, row)


def measure_endpoint(queries, controller, *args, **kwargs):
    result = queries.measure(*args, **kwargs)
    if type(controller) is AutomaticEndpoints:
        checkpoint = kwargs.get('_checkpoint')
        completed = None if checkpoint is None else checkpoint.last_completed
        eligible = kwargs.get('positive_witness', False) is True and kwargs.get('relative_error') is None
        if eligible and completed is not None and completed[1] is True:
            key = args[0] if args else kwargs['logical_cell_id']
            controller.checkpoint_consumed(key, kwargs['endpoint'])
        else:
            controller.observed()
    return result
