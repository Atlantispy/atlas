"""Endpoint scheduling through the existing automatic policy and owned workers.

Requests are offered in router order. While a worker session is open, or the schedule
asks for more to cut its first batch (up to one horizon), supports ahead of the router
are read for their component lists (WP18 part 1). Endpoint observations
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
        # WP18 part 1: the pass's supports; the next one not read yet; supports bound by the
        # router; read ones it has still to bind, as (index, support id); and the supports
        # and endpoint jobs read so far.
        self.supports, self.cursor, self.bound = None, 0, 0
        self.unbound, self.read = deque(), [0, 0]
        # r2: compact handles this pass retained, as (index, handle), so the identities memo drops
        # them once the router has passed their support; peak supports read ahead, peak handles;
        # set once a lookahead reaches its horizon with no session open (no more reading ahead
        # until one opens).
        self.handles, self.peak, self.sated = deque(), [0, 0], False
        super().__init__(parent)
        # WP18 part 1: the policy's general batch bounds (batch_jobs, horizon), as for walls
        # and interfaces. The schedule was built with them and self.cached = 2*horizon+64
        # already; one batch's shipped supports stay within D.MAX_BATCH_INPUT through the
        # schedule's capacity check.

    def _seed(self):
        # Endpoint geometry has no validated stored timing classes yet. Learn
        # only actual endpoint bodies of this source/settings/pass.
        self.exact = False

    def prepare(self, supports):
        if self.prepared or self.closed:
            raise RuntimeError('one prepare per automatic endpoint pass')
        self.prepared = True
        # Read ahead by index, one support at a time, never all at once.
        self.supports = supports

    def bind_support(self, support, row):
        if self.schedule is None or self.closed or self.schedule.stopped is not None:
            if self.schedule is not None and not self.closed:
                # Stopped by the schedule: nothing more binds, so the reading and the held
                # handles (with their memo entries) go now, not at close.
                self._drop_reading()
            return
        try:
            index, self.bound = self.bound, self.bound+1
            # Supports the router has passed: their retained handles leave the identities memo
            # (only a memo: a later lookup recomputes it), so the pass holds the handles in sight.
            while self.handles and self.handles[0][0] < index:
                self.identities.pop(id(self.handles.popleft()[1]), None)
            if self.order and self.order[0][0] < index:
                raise ValueError('previous endpoint support was not consumed in serial order')
            if index < self.cursor:
                # Read ahead already and its requests offered: the router must bind that same support.
                held = self.unbound.popleft() if self.unbound else None
                if held is None or held != (index, support.support_id):
                    raise ValueError('endpoint lookahead support differs from the router order')
            else:
                if index != self.cursor or self.jobs is not None or self.left or self.unbound:
                    raise ValueError('previous endpoint support was not consumed in serial order')
                compact = getattr(support, '_compact_ref', None) is not None
                if compact:
                    # Offer the small retained handle, not the temporary native support.
                    from partition_routing_patch import retain_support
                    support = retain_support(support)
                self._begin_support(index, support, _summary(row['components']))
                if compact:
                    self._retained(index, support)
            self._fill()
        except Exception as error:
            self.schedule._stop('endpoint lookahead error', S._text(error))
            self._drop_reading()

    def _beyond(self):
        # Jobs left in the support being read; for supports not read yet, the mean number
        # of jobs per support read so far (the wall pass's estimator). No whole-mesh decode.
        supports, jobs = self.read
        if self.supports is None or not supports:
            return self.left
        return self.left + max(0, len(self.supports)-self.cursor)*jobs/supports

    def _begin_support(self, index, support, summary):
        """The endpoint requests of support ``index`` in router order, from its (id, has parent,
        constraint count, partition path length) summary."""
        self.cursor = index+1
        self.left = sum(1 + has_parent for _, has_parent, _, _ in summary)
        self.read[0] += 1
        self.read[1] += self.left
        self.jobs = ((index, support, key, endpoint, {}, (endpoint, constraints, path))
                     for key, has_parent, constraints, path in summary for endpoint in ('start', 'end')
                     if endpoint != 'start' or has_parent) if self.left else None

    def _retained(self, index, handle):
        # Only a handle with requests to offer can enter the memo. Holding it until the router
        # passes its support keeps its id from being reused by a later handle meanwhile.
        if self.left:
            self.handles.append((index, handle))
            self.peak[1] = max(self.peak[1], len(self.handles))

    def _drop_reading(self):
        # A stopped lookahead drops the support it was reading at once; jobs already offered
        # go with the schedule at close(), which the ALE runs before the partition closes.
        if self.jobs is not None:
            self.jobs.close()
            self.jobs = None
        self.left = 0
        self.unbound.clear()
        # No support is bound after a stop, so held handles leave the memo now, not at close.
        while self.handles:
            self.identities.pop(id(self.handles.popleft()[1]), None)

    def _read_ahead(self):
        """Offer the next support's requests before the router reaches it.

        Only its component summary and the support (a retained handle if compact) are kept.
        The routing-row projector is not called ahead of its serial position.
        """
        index = self.cursor
        support = self.supports[index]
        compact = getattr(support, '_compact_ref', None) is not None
        if compact:
            # Step 8's retained handle and charged field read; the temporary native support
            # and its retained bytes die here.
            from partition_routing_patch import retain_support, support_fields
            held = retain_support(support)
            del support
            owned = support_fields(held, ('components',))
            try:
                summary = _summary(owned.value['components'])
            finally:
                del owned
            ident = held.support_id
        else:
            # One decode within the existing prepaid routing decode envelope, sequential
            # with its other users; the graph dies before this returns.
            held, ident = support, support.support_id
            summary = _summary(support.record()['components'])
        self.unbound.append((index, ident))
        self.peak[0] = max(self.peak[0], len(self.unbound))
        self._begin_support(index, held, summary)
        if compact:
            self._retained(index, held)

    def _fill(self):
        if self.schedule is None or self.closed:
            return
        schedule = self.schedule
        try:
            while schedule.hungry():
                if self.jobs is None:
                    # Read ahead only while a worker session is open, or while the schedule's plan
                    # asks the router for more to cut its first batch (offered < wanted; one
                    # support's requests never fill a batch) and no lookahead of this pass has
                    # reached its horizon without a session. A pass below its threshold or still
                    # without estimates reads nothing ahead.
                    if (self.supports is None or self.cursor >= len(self.supports) or not self.bound
                            or (schedule.session is None
                                and (self.sated or schedule.offered >= schedule._wanted))):
                        return
                    self._read_ahead()
                    continue
                item = next(self.jobs, None)
                if item is None:
                    self.jobs, self.left = None, 0
                    continue
                index, support, key, endpoint, pair, label = item
                self.left -= 1
                self.total += 1
                self.order.append((index, key, endpoint, label))
                self.schedule.offer((support, key, endpoint, pair), 0.0, label)
                if not self.left:
                    self.jobs.close()
                    self.jobs = None
            if schedule.session is None and len(schedule.ahead) >= schedule.horizon:
                # A whole horizon in sight and still no session: read no further ahead until one
                # opens, so at most one horizon of supports is read twice without a session.
                self.sated = True
        except Exception as error:
            self.schedule._stop('endpoint lookahead error', S._text(error))
            self._drop_reading()

    def _open(self):
        refusal = self._machine()
        if refusal is not None:
            # A momentary machine refusal defers the open (see _Rolling._refused).
            return self._refused(refusal)
        # Endpoint sessions keep RC1's bound of two workers (ComponentParallelSession is
        # 1..2); a larger policy count serves the wall and interface batches only.
        self.workers = min(self.workers, 2)
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
            if self.order and self.order[0][1:3] == (request['logical_cell_id'], request['endpoint']):
                _, _, _, self.label = self.order.popleft()
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
        if self.order and self.order[0][1:3] == (logical_cell_id, endpoint):
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
        self.unbound.clear()
        self.handles.clear()
        self.supports = None
        super().close()
        try:
            report = self.summary()
            report['checkpoint_hits'] = self.checkpoint_hits
            report['checkpoint_lookahead'] = 'no pre-prefix lookup; already launched mixed batches may duplicate cached members'
            report['observation_scope'] = 'current endpoint pass only'
            report['lookahead_scope'] = ('supports ahead of the router while a session is open, or while its '
                                         'first batch is being cut up to one horizon; rows projected in router order')
            report['lookahead_supports'] = self.read[0]
            report['lookahead_peak_supports'], report['lookahead_peak_handles'] = self.peak
            report['lookahead_sated'] = self.sated
            self.parent.decision['endpoint_batches'] = report
            self._promote(report, 'endpoint batches selected')
        except Exception as error:
            self.parent.decision['notes'].append('endpoint report unavailable: ' + S._text(error))
        self.finished = True


def _summary(parts):
    """(logical id, has parent, constraint count, partition path length) per component, in order."""
    return tuple((part['logical_cell_id'], part['parent_cell_id'] is not None,
                  len(part['constraints']), len(part['partition_path'])) for part in parts)


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
