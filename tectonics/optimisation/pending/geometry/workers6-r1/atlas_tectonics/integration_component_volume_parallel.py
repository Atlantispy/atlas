"""Private opt-in endpoint batches through the existing owned worker machinery.

Only positive-witness absolute-error queries are eligible. No automatic policy,
physical receipt field, numerical body, source identity or shared scheduler is
changed here. Unsupported modes remain serial at the issuer's own position.
"""
from itertools import islice
import time

from . import integration_differential_geometry as G
from . import integration_parallel_dispatch as P
from .integration_component_volume_batch import ComponentVolumeQueries
from .integration_parallel_binding import VOLUME_SCHEMA
from .integration_routing_views import _decoded_json_capacity


def request_for(support, logical_cell_id, endpoint, time_s, width, leaves):
    return dict(schema=VOLUME_SCHEMA, support_id=support.support_id,
        logical_cell_id=logical_cell_id, endpoint=endpoint, time_s=time_s,
        max_width_m3=G._qtext(width), max_leaves=leaves)


def component_answers(requests, inputs, new_ledger, room, observed):
    """Same-support decode reuse under one exact child ledger, fresh query arenas.

    The expected empty-query baseline is derived from the unchanged issued
    support charge and the helper's explicit decoded-input reservation. It is
    not captured from an arbitrary post-query balance: leaked query leases
    cannot silently become an accepted baseline. Refused queries invalidate
    the owner; their parent retries serially for its own original diagnostic.
    """
    answers, support, ledger, queries = [], None, None, None
    identity, baseline = None, None

    def finish():
        nonlocal support, ledger, queries, identity, baseline
        if queries is not None:
            queries.__exit__(None, None, None)
        if ledger is not None:
            observed['peak'] = max(observed['peak'], ledger.statistics()['peak_reserved_bytes'])
        queries = support = ledger = identity = baseline = None

    try:
        for request in requests:
            try:
                if identity is not None and ledger.reserved_bytes != baseline:
                    # A retained query graph must not coexist with a freshly
                    # funded ledger under the same envelope. The parent can
                    # do all remaining members serially after this child exits.
                    answers.extend(['declined'] * (len(requests)-len(answers)))
                    return answers
                if identity != request['support_id'] or ledger.reserved_bytes != baseline:
                    finish()
                    ledger = new_ledger()
                    support = P._support(inputs[request['support_id']], request['support_id'], ledger)
                    baseline = ledger.reserved_bytes + 4096 + _decoded_json_capacity(support._json)
                    queries = ComponentVolumeQueries(support, budget=ledger)
                    queries.__enter__()
                    identity = support.support_id
                begun = time.perf_counter()
                raw = queries.measure(request['logical_cell_id'], endpoint=request['endpoint'],
                    max_width_m3=G.W._decode(request['max_width_m3']), max_leaves=request['max_leaves'],
                    positive_witness=True)._json
                observed['body'] += time.perf_counter()-begun
                if len(raw) > P.MAX_RESULT or 2*len(raw)+256 > room:
                    answers.append('declined')
                else:
                    answers.append(raw)
                    room -= 2*len(raw)+256
            except ValueError:
                # A refused query can retain traceback-owned input/scratch.
                # Do not start another ledger while those frames may survive.
                answers.extend(['declined'] * (len(requests)-len(answers)))
                return answers
        return answers
    finally:
        finish()


class ComponentParallelSession(P.BatchParallelSession):
    """Existing bounded transfer, adoption, revocation and stop implementation."""

    def __init__(self, *, workers=1, **kwargs):
        if type(workers) is not int or not 1 <= workers <= 6:
            raise ValueError('one to six component workers required')
        self._read_ahead = None
        super().__init__(wall=False, workers=workers, **kwargs)

    def _stop(self):
        # The iterator can retain one decoded support inside PARENT_STORAGE.
        # Revoke may come directly from a mandatory budget call, not from the
        # pass's close(): discard this graph BEFORE inherited storage release.
        # Child inputs/bindings remain owned by the unchanged batch lifecycle.
        if self._read_ahead is not None:
            try:
                self._read_ahead.close()
            except BaseException as failure:
                # A still-live iterator forbids inherited storage release, but
                # must not prevent any sibling from receiving its stop call.
                # This is only the non-releasing phase of the base contract.
                # Preserve its precedence: true uncertainty stays FAILED;
                # cancellation alone permits an explicit cleanup retry.
                interrupted = failure if isinstance(failure, (KeyboardInterrupt, SystemExit)) else None
                unconfirmed = None if interrupted is failure else failure
                for batch in self.batches:
                    try:
                        batch['child'].stop()
                    except BaseException as error:
                        if isinstance(error, (KeyboardInterrupt, SystemExit)):
                            interrupted = interrupted or error
                        else:
                            unconfirmed = unconfirmed or error
                if unconfirmed is not None:
                    if interrupted is not None:
                        raise unconfirmed from interrupted
                    raise unconfirmed
                raise interrupted
            self._read_ahead = None
        super()._stop()

    def member_request(self, support, key, endpoint, pair):
        if pair or endpoint not in ('start', 'end'):
            raise ValueError('an endpoint job requires only its explicit start/end selector')
        _, _, start, end, _ = self._support_facts(support)
        return request_for(support, key, endpoint, start if endpoint == 'start' else end,
                           G.W._decode(self._width_text), self.leaves)


class EndpointBatchPass:
    """Explicit small lookahead; at most two batches, never the whole mesh.

    This is an opt-in prototype pass, not a new automatic-selection policy.
    Caller owns the actual strict context; this pass closes only its workers.
    No later pass shares an active endpoint session.
    """

    def __init__(self, *, session, context, batch_jobs=16):
        if type(session) is not ComponentParallelSession:
            raise TypeError('the reviewed component session is required')
        if type(batch_jobs) is not int or not 1 <= batch_jobs <= 32:
            raise ValueError('one to 32 endpoint requests per bounded batch required')
        self.session, self.context = session, context
        self.batch_jobs, self.jobs = batch_jobs, None
        self.prepared = self.closed = False

    def prepare(self, supports):
        if self.prepared or self.closed:
            raise RuntimeError('one prepare per endpoint pass')
        self.prepared = True
        if not self.session.open(self.context):
            return

        def jobs():
            for support in supports:
                # Never call the mandatory routing-row projector ahead of its
                # serial position. This optional graph fits the existing
                # prepaid transport/decode envelope and dies with the iterator.
                if P.transport(support) is None:
                    return
                row = support.record()
                for part in row['components']:
                    for endpoint in ('start', 'end'):
                        if endpoint != 'start' or part['parent_cell_id'] is not None:
                            yield support, part['logical_cell_id'], endpoint, {}
        self.jobs = jobs()
        self.session._read_ahead = self.jobs
        self._fill()

    def _fill(self):
        if self.jobs is None or self.closed:
            return
        # Completed but unclaimed batches still count: their receipt and
        # envelope remain funded. Thus polling cannot accumulate output history.
        for _ in range(self.session.workers):
            if (not self.session.check()
                    or len(self.session.batches) >= self.session.workers):
                return
            try:
                jobs = list(islice(self.jobs, self.batch_jobs))
            except Exception:
                # Malformed/unsupported speculative input is not a scientific
                # failure at an earlier position. Original validation follows.
                self.jobs.close()
                self.jobs = None
                return
            if not jobs:
                self.jobs.close()
                self.jobs = None
                return
            if self.session.launch(jobs, timeout=self.session.timeout) is None:
                # This bounded group stays serial. Stop read-ahead on any
                # admission refusal instead of repeatedly consuming the mesh.
                self.jobs.close()
                self.jobs = None
                return

    def claim(self, request, budget):
        if self.closed:
            return None
        result = self.session.claim(request, budget)
        self._fill()
        return result

    def close(self):
        if self.closed:
            return
        # An unconfirmed stop keeps the session funded and this pass open for
        # explicit cleanup. Its optional read-ahead graph is already discarded.
        self.session.close()
        if self.jobs is not None:
            self.jobs.close()
            self.jobs = None
        self.context = None
        self.closed = True
