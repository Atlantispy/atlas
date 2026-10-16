"""Private opt-in parallel route for the initial relative-error component queries.

enclose_initial_partition measures every exterior component of an initial
partition with one retained relative-error query (integration_dual_geometry.
measure_initial_component), serially. The queries are independent. A caller
that opens InitialParallel around the initial metrics lets one-shot workers of
the existing component session compute them ahead, in contiguous batches in
the serial order. Read-ahead starts only when a query is not a
measurement-cache hit: the parent measures that query itself while workers
take the ones after it. Positions the serial loop has passed (hits) are never
launched, and a batch it has passed is retired. At each serial position the parent still runs the unchanged
wrapper (reservation, accuracy and witness checks, its own diagnostics, the
measurement-store record) and substitutes only the DifferentialMeasure that a
source-bound worker issued for exactly that call.

Everything else is the endpoint route's machinery, unchanged: the binding of
sources, runtime and inputs; one envelope per batch; adoption only after the
worker has exited; revocation of the whole session on any worker, completion
or adoption failure. Before use, the adopted record also passes the query
checks a measurement-cache hit passes. A member without such an answer runs
the unchanged serial call at its own position, so every refusal and every
diagnostic is the parent's own. With no pass opened, active() is None and
the original code path runs.
SPDX-License-Identifier: AGPL-3.0-only
"""
import contextvars
from fractions import Fraction as Q

from . import integration_differential_geometry as G
from . import integration_parallel_dispatch as P
from .integration_component_volume_parallel import ComponentParallelSession, request_for

# ComponentParallelSession's worker bound for this family until a wider one is decided.
MAX_WORKERS = 2
BATCH_JOBS = 16
_ACTIVE: contextvars.ContextVar = contextvars.ContextVar('atlas_initial_parallel', default=None)


def active():
    """The pass the caller opened in this context, or None."""
    return _ACTIVE.get()


def initial_request(support, logical_cell_id, time_s, width, leaves, relative_error):
    """The endpoint request of a start-endpoint query plus its exact relative error."""
    request = request_for(support, logical_cell_id, 'start', time_s, width, leaves)
    request['relative_error'] = G._qtext(Q(relative_error))
    return request


def validated_initial_volume(record, request, fit):
    """Structural admission of one initial-query worker record, as for an endpoint record.

    The numbers are the source-bound child's output for this request; the
    parent's query checks (InitialParallel._certified) follow at adoption.
    """
    from .integration_parallel_binding import INITIAL_VOLUME_REQUEST_FIELDS
    from .integration_parallel_results import (VOLUME_POSES, VOLUME_RESULT_FIELDS, VOLUME_WITNESS_FIELDS,
        VOLUME_WITNESS_RULE, _wall_scalar, canonical, request_fields)
    fields = INITIAL_VOLUME_REQUEST_FIELDS | VOLUME_RESULT_FIELDS | {'relative_error_bound'}
    extra = record.keys()-fields
    if (not fields <= record.keys()
            or extra not in (set(), VOLUME_WITNESS_FIELDS, {VOLUME_POSES},
                            VOLUME_WITNESS_FIELDS | {VOLUME_POSES})):
        return False
    carried = {key: record[key] for key in INITIAL_VOLUME_REQUEST_FIELDS}
    request_fields(carried)
    if canonical(carried) != request:
        return False
    work, leaves = record['work_units'], record['leaves']
    if (type(work) is not int or work < 0 or not fit.admits_work(work)
            or type(leaves) is not int or not 1 <= leaves <= record['max_leaves']
            or type(record['met']) is not bool):
        return False
    for key in ('lower_m3', 'upper_m3', 'positive_witness_m3', 'relative_error_bound'):
        value = record[key]
        if not _wall_scalar(value) or value[0].startswith('-'):
            return False
    if VOLUME_WITNESS_FIELDS <= extra:
        point = record['positive_witness_point_m']
        if (record['positive_witness_point_rule'] != VOLUME_WITNESS_RULE
                or type(point) is not list or len(point) != 3
                or not all(_wall_scalar(value) for value in point)):
            return False
    if VOLUME_POSES in extra:
        poses = record[VOLUME_POSES]
        if (type(poses) is not list or not all(type(level) is int for level in poses)
                or poses not in ([0, 16], [0, 16, 32]) or len(poses) > leaves):
            return False
    return True


class InitialParallelSession(ComponentParallelSession):
    """The component session for start-endpoint queries with one exact relative error."""

    def __init__(self, *, workers=1, relative_error, **kwargs):
        if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
            raise ValueError('one to %d initial workers required' % MAX_WORKERS)
        if type(relative_error) not in (int, Q) or not 0 <= relative_error < 1:
            raise ValueError('explicit exact relative error below one required')
        # ComponentParallelSession's own initialisation, under this family's bound.
        self._read_ahead = None
        P.BatchParallelSession.__init__(self, wall=False, workers=workers, **kwargs)
        self._relative_text = G._qtext(Q(relative_error))

    def member_request(self, support, key, endpoint, pair):
        if pair or endpoint != 'start':
            raise ValueError('an initial job is one start-endpoint query')
        request = super().member_request(support, key, endpoint, pair)
        request['relative_error'] = self._relative_text
        return request


class InitialParallel:
    """Context-scoped opt-in around the initial metrics; see the module docstring.

    workers run at most `workers` batches of `batch_jobs` contiguous queries at
    once; at most `outstanding` launched batches are not yet fully claimed, so
    a slow early batch does not stop later workers. Nothing here estimates or
    reorders: batches follow the serial order exactly.
    """

    def __init__(self, *, workers, budget, context, batch_jobs=BATCH_JOBS, outstanding=None,
                 child_bytes=128 << 20, predicate_units=1 << 34, timeout_seconds=1800, budget_fraction=1.0):
        if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
            raise ValueError('one to %d initial workers required' % MAX_WORKERS)
        if type(batch_jobs) is not int or not 1 <= batch_jobs <= 64:
            raise ValueError('one to 64 queries per batch required')
        outstanding = 3*workers if outstanding is None else outstanding
        if type(outstanding) is not int or not workers <= outstanding <= 8*workers:
            raise ValueError('between one and eight batches per worker outstanding required')
        self.workers, self.budget, self.context = workers, budget, context
        self.batch_jobs, self.outstanding = batch_jobs, outstanding
        self.options = dict(child_bytes=child_bytes, predicate_units=predicate_units,
                            timeout_seconds=timeout_seconds, budget_fraction=budget_fraction)
        self.session = self.token = None
        # Serial positions of this partition's queries; the next position to launch;
        # launched batches with the last position each holds.
        self.order, self.positions, self.cursor, self.held = None, None, 0, []
        self.started = self.closed = False
        self.report: dict = dict(workers=workers, batch_jobs=batch_jobs, outstanding=outstanding, opened=False,
                           batches=0, offered=0, unshipped=0, skipped=0, retired=0, adopted=0, serial=0,
                           refused=0, first_launch=None, note=None)

    def __enter__(self):
        if self.token is not None or self.closed:
            raise RuntimeError('one entry per initial pass')
        if _ACTIVE.get() is not None:
            # One pass per context: a nested pass would take over its outer pass's queries.
            raise RuntimeError('an initial pass is already open in this context')
        self.token = _ACTIVE.set(self)
        return self

    def __exit__(self, kind, error, tb):
        try:
            self.close()
        finally:
            _ACTIVE.reset(self.token)
        return False

    def start(self, partition, *, budget, relative_error, max_width_m3, max_leaves):
        """Open the session for this partition's queries: self, or None for the serial route.

        Nothing is launched here: the first claim (the first query that is not a
        measurement-cache hit) starts the read-ahead after its own position.
        """
        if self.started or self.closed or budget is not self.budget:
            return None
        self.started = True
        try:
            # The caller has just decoded every support for its component count.
            order = [(support, part['logical_cell_id']) for support in partition.supports
                     for part in support.record()['components']]
            positions = {(support.support_id, cell): index for index, (support, cell) in enumerate(order)}
        except Exception as error:
            # Malformed input is the serial body's to refuse at its own position.
            self.report['note'] = 'positions: %s' % str(error)[:512]
            return None
        if len(positions) != len(order):
            # A repeated query would make "passed" ambiguous; stay serial.
            self.report['note'] = 'positions: repeated support and component'
            return None
        try:
            session = InitialParallelSession(budget=budget, max_width_m3=max_width_m3, max_leaves=max_leaves,
                                             workers=self.workers, relative_error=relative_error, **self.options)
        except Exception as error:
            self.report['note'] = 'session: %s' % str(error)[:512]
            return None
        context = self.context
        if not session.open(lambda: context):
            self.report['note'] = 'session: %s' % str(session.plan.get('funding') or session.last_error
                                                       or 'not opened')[:512]
            return None
        self.session, self.order, self.positions = session, order, positions
        self.report['opened'] = True
        session.on_wait = self._fill
        return self

    def _fill(self):
        session, order = self.session, self.order
        if session is None or order is None or self.closed:
            return
        try:
            while (self.cursor < len(order) and session.check() and session.running() < session.workers
                   and len(session.batches) < self.outstanding):
                begin = self.cursor
                taken = order[begin:begin+self.batch_jobs]
                self.cursor = begin+len(taken)
                # A support too large for the optional transport stays at its serial position.
                jobs, last = [], None
                for offset, (support, cell) in enumerate(taken):
                    if session.shippable(support):
                        jobs.append((support, cell, 'start', {}))
                        last = begin+offset
                self.report['unshipped'] += len(taken)-len(jobs)
                if not jobs:
                    continue
                batch = session.launch(jobs, timeout=session.timeout)
                if batch is None:
                    # As the endpoint pass: on any refusal the rest stays serial.
                    self.report['note'] = 'launch: %s' % str(session.last_error or 'refused')[:512]
                    self._stop_reading()
                    return
                self.held.append((batch, last))
                if self.report['first_launch'] is None:
                    self.report['first_launch'] = begin
                self.report['batches'] += 1
                self.report['offered'] += len(jobs)
        except Exception as error:
            # Malformed or unsupported read-ahead is not a failure at an earlier
            # position: the serial body meets the same input at its own.
            self.report['note'] = 'read-ahead: %s' % str(error)[:512]
            self._stop_reading()

    def _stop_reading(self):
        self.order = None

    def _passed(self, position):
        """The serial loop is at `position`: earlier positions will not be claimed."""
        if self.order is not None and self.cursor <= position:
            # Not launched: the parent measures this one now while workers take the next.
            self.report['skipped'] += position-self.cursor
            self.cursor = position+1
        keep = []
        for batch, last in self.held:
            if last >= position:
                keep.append((batch, last))
            elif any(held is batch for held in self.session.batches):
                # Its unclaimed members were cache hits: stop and return it now.
                self.session.retire(batch)
                self.report['retired'] += 1
        self.held = keep

    def claim(self, support, logical_cell_id, record, *, max_width_m3, max_leaves, relative_error, budget):
        """The adopted measure of exactly this query at its serial position, or None."""
        session = self.session
        if session is None or self.closed or budget is not self.budget:
            return None
        position = self.positions.get((support.support_id, logical_cell_id))
        if position is None:
            self.report['serial'] += 1
            return None
        self._passed(position)
        self._fill()
        request = initial_request(support, logical_cell_id, record['start_time_s'],
                                  max_width_m3, max_leaves, relative_error)
        funded = session.claim(request, budget)
        self._fill()
        if funded is None:
            self.report['serial'] += 1
            return None
        # As the endpoint issuer: the validated token becomes the measure, taking over its charge.
        from .integration_parallel_results import adopt
        measure, funded = adopt(G.DifferentialMeasure, funded, budget), None
        if not self._certified(measure.record(), support, logical_cell_id, record,
                               max_width_m3, max_leaves, relative_error):
            # An adopted answer that a cache hit would fail is a defect: stop the whole route.
            self.report['refused'] += 1
            self.report['note'] = 'adopted answer failed the query checks at %s' % logical_cell_id
            measure = None
            self.close()
            return None
        self.report['adopted'] += 1
        return measure

    @staticmethod
    def _certified(query, support, logical_cell_id, record, width, max_leaves, relative_error):
        """The query checks of a measurement-cache hit (integration_dual_geometry), on the adopted record."""
        W = G.W
        try:
            low, high = W._decode(query['lower_m3']), W._decode(query['upper_m3'])
            r, width = Q(relative_error), Q(width)
            error = (high-low)/low if low else Q(0)
            return bool(
                query['support_id'] == support.support_id and query['logical_cell_id'] == logical_cell_id
                and query['endpoint'] == 'start' and query['time_s'] == record['start_time_s']
                and W._decode(query['relative_error']) == r and W._decode(query['max_width_m3']) == width
                and query['met'] is True and query['max_leaves'] == max_leaves
                and type(query['leaves']) is int and 1 <= query['leaves'] <= max_leaves
                and 0 <= low <= high and not (high > 0 and low == 0) and high-low <= width
                and W._decode(query['relative_error_bound']) == error and error <= r
                and (high == 0 or (0 < W._decode(query['positive_witness_m3']) <= low
                                   and query.get('positive_witness_point_m')
                                   and len(query['positive_witness_point_m']) == 3)))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return False

    def finish(self):
        """After the serial loop: return every optional admission now."""
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._stop_reading()
        self.positions, self.held = None, []
        session, self.session = self.session, None
        if session is not None:
            try:
                session.close()
            finally:
                # Scheduling observations for the caller's report; never part of a record.
                self.report.update(stats=dict(session.stats), cause=session.cause, log=list(session.log),
                                   seconds={k: round(v, 3) for k, v in session.seconds.items()},
                                   last_error=None if session.last_error is None else str(session.last_error)[:512])
