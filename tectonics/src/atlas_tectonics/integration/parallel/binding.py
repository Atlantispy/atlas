"""Exact one-shot identity for parent-owned interface and fixed-wall execution.

The trusted boundary is OwnedDispatch.submit calling the parent's own executor
with its reviewed worker callable, then consuming THAT returned Future. Tokens,
JSON and hashes alone do not authenticate arbitrary input. This is accidental
misrouting/replay protection, not protection from hostile code in either process.

The caller owns the executor/channel, unchanged numerical callable, complete
fresh source/input inventory, exact WorkBudget, live funding, transport/staging
capacity, deadline/RSS guards and stopping children before releasing funding.
Successful receipt validation is not scientific certification or adoption.

A batch binding carries an ordered list of such requests for ONE one-shot
worker. The whole list, the sources, the runtime and the limits are bound to
one token; every returned member result must still carry its own request.
"""
from concurrent.futures import Future
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
import secrets
import sys
import threading

from atlas_tectonics.integration.resources import WorkBudget
from atlas_tectonics.integration.resources import canonical_json as canonical
from atlas_tectonics.integration.resources import is_sha256 as _digest


REQUEST_FIELDS = frozenset((
    'schema', 'kind', 'support_id', 'interval_id', 'logical_cell_id', 'constraint_name',
    'other_support_id', 'other_logical_cell_id', 'start_time_s', 'end_time_s',
    'max_width_m3', 'max_leaves'))
VOLUME_SCHEMA = 'atlas.differential-component-volume.v1'
VOLUME_REQUEST_FIELDS = frozenset((
    'schema', 'support_id', 'logical_cell_id', 'endpoint', 'time_s',
    'max_width_m3', 'max_leaves'))
# This dispatch family is positive_witness=True, relative_error=None only.
# Its reviewed worker and serial-prefix hook enforce those unencoded constants.
# initpar r1 (the initial-parallel transform): the initial-query family, start endpoint, with its exact
# relative error carried; positive_witness=True as above.
INITIAL_VOLUME_REQUEST_FIELDS = VOLUME_REQUEST_FIELDS | {'relative_error'}
WALL_KIND = 'component-fixed-voxel-face'
WALL_REQUEST_FIELDS = frozenset((
    'schema', 'kind', 'support_id', 'interval_id', 'logical_cell_id', 'axis', 'end',
    'start_time_s', 'end_time_s', 'max_width_m3', 'max_leaves'))
_FIELDS = frozenset(('schema', 'request', 'execution_identity',
    'execution_runtime', 'interpreter_seed', 'child_budget', 'dispatch_token'))
_SCHEMA = 'private.parallel-job-binding.v1'
_RECEIPT = 'private.parallel-worker-completion.v1'
_BATCH_FIELDS = (_FIELDS-{'request'}) | {'requests'}
_BATCH_SCHEMA = 'private.parallel-batch-binding.v1'
_BATCH_RECEIPT = 'private.parallel-batch-completion.v1'
BATCH_LIMIT = 1024    # requests one batch binding may hold
# What a worker may answer for one member besides its measure bytes: an exact
# shortcut that the parent's own prefix decides, or no result at all.
UNANSWERED = ('decided', 'declined')

# Already-owned payload and token references are included in the outer tuple.
# The selector is one of the local constants in integration_parallel_results.
_FACT_BYTES = (sum((sys.getsizeof(value)+15) & ~15 for value in
                   ((None,)*5, (None,)*3, '0'*64, '0'*64, sys.maxsize))
               if sys.implementation.name == 'cpython' else 0)


def request_fields(request):
    """Exactly one supported request shape; walls are full-interval rigid flux."""
    if type(request) is dict and request.get('schema') == 'atlas.private.pressure-wall.r1':
        # Pressure P1: the pressure-wall shape is checked by its own module.
        from atlas_tectonics.integration.coupling.pressure_walls import check_request
        return check_request(request)
    if type(request) is dict and request.get('schema') == VOLUME_SCHEMA and 'relative_error' in request:
        from atlas_tectonics.integration.parallel.results import _wall_scalar
        if (request.keys() != INITIAL_VOLUME_REQUEST_FIELDS
                or not _digest(request['support_id'])
                or not _digest(request['logical_cell_id'])
                or request['endpoint'] != 'start'
                or not _wall_scalar(request['time_s'])
                or not _wall_scalar(request['max_width_m3'])
                or request['max_width_m3'][0].startswith('-')
                or not _wall_scalar(request['relative_error'])
                or request['relative_error'][0].startswith('-')
                or type(request['max_leaves']) is not int or request['max_leaves'] < 1):
            raise ValueError('complete exact initial-volume request required')
        return INITIAL_VOLUME_REQUEST_FIELDS
    if type(request) is dict and request.get('schema') == VOLUME_SCHEMA:
        # Reuse the exact existing rational wire check. The import is lazy:
        # results imports this module, but no request is validated at import time.
        from atlas_tectonics.integration.parallel.results import _wall_scalar
        if (request.keys() != VOLUME_REQUEST_FIELDS
                or not _digest(request['support_id'])
                or not _digest(request['logical_cell_id'])
                or type(request['endpoint']) is not str
                or request['endpoint'] not in ('start', 'end')
                or not _wall_scalar(request['time_s'])
                or not _wall_scalar(request['max_width_m3'])
                or request['max_width_m3'][0].startswith('-')
                or type(request['max_leaves']) is not int or request['max_leaves'] < 1):
            raise ValueError('complete exact endpoint-volume request required')
        return VOLUME_REQUEST_FIELDS
    if type(request) is dict and request.get('kind') == WALL_KIND:
        if (request.keys() != WALL_REQUEST_FIELDS
                or type(request['axis']) is not int or request['axis'] not in (0, 1, 2)
                or type(request['end']) is not int or request['end'] not in (0, 1)):
            raise ValueError('complete fixed-wall request with exact axis/end required')
        return WALL_REQUEST_FIELDS
    if type(request) is not dict or request.keys() != REQUEST_FIELDS:
        raise ValueError('complete twelve-field interface request required')
    return REQUEST_FIELDS


def _decode(raw):
    if type(raw) is not bytes:
        raise ValueError('immutable canonical bytes required')
    record = json.loads(raw)
    if type(record) is not dict or canonical(record) != raw:
        raise ValueError('canonical JSON object required')
    return record


def interpreter_seed():
    """Read the real interpreter, not a caller-supplied seed claim.

    Setting os.environ after a randomised interpreter starts cannot clear its
    hash_randomization flag. Both checks are required in parent and child.
    """
    if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.hash_randomization != 0:
        raise RuntimeError('interpreter must START with explicit PYTHONHASHSEED=0')
    return {'PYTHONHASHSEED': '0', 'hash_randomization': 0}


def capture_runtime(context):
    seed = interpreter_seed()
    from atlas_tectonics.integration.reuse import ExecutionContext, execution_mode
    mode = getattr(context, '_mode', None)
    if (type(context) is not ExecutionContext or mode not in ('strict', 'release')
            or mode != execution_mode()):
        raise TypeError('the actual strict scientific ExecutionContext is required')
    identity = context.identity
    runtime = context._runtime
    if not _digest(identity) or type(runtime) is not dict or runtime.keys() != {'versions', 'binaries'}:
        raise ValueError('complete scientific execution identity/runtime required')
    return {'execution_identity': identity, 'execution_runtime': runtime, 'interpreter_seed': seed}


def _validate(record):
    if record.keys() != _FIELDS or record['schema'] != _SCHEMA:
        raise ValueError('complete job-binding schema required')
    request_fields(record['request'])
    _validate_envelope(record)


def _validate_batch(record):
    if (record.keys() not in (_BATCH_FIELDS, _BATCH_FIELDS | {'batch_seconds'})
            or record['schema'] != _BATCH_SCHEMA):
        raise ValueError('complete batch-binding schema required')
    requests = record['requests']
    if type(requests) is not list or not 1 <= len(requests) <= BATCH_LIMIT:
        raise ValueError('a batch holds one to %d requests' % BATCH_LIMIT)
    shapes = {request_fields(request) for request in requests}
    if (len(shapes) != 1
            or len({canonical(request) for request in requests}) != len(requests)):
        raise ValueError('a batch holds distinct requests of one kind')
    if 'batch_seconds' in record:
        _batch_seconds(record['batch_seconds'])
        if (shapes != {REQUEST_FIELDS}
                or any(request['kind'] != 'component-moving-radial-interface' for request in requests)):
            raise ValueError('a finite nonnegative body limit binds moving interfaces only')
    _validate_envelope(record)


def _batch_seconds(seconds):
    if not (type(seconds) is int and seconds >= 0 or
            type(seconds) is float and math.isfinite(seconds) and seconds >= 0):
        raise ValueError('a finite nonnegative non-boolean batch body limit is required')


def is_batch(encoded):
    """Whether binding bytes name the batch schema. Nothing is validated here: the binding
    class the worker then constructs does that, and refuses everything else as before."""
    try:
        record = json.loads(encoded)
    except (ValueError, TypeError):
        return False
    return type(record) is dict and record.get('schema') == _BATCH_SCHEMA


def _validate_envelope(record):
    limits = record['child_budget']
    if type(limits) is not dict or limits.keys() != {'max_bytes', 'max_predicate_work_units'}:
        raise ValueError('exact positive child budget and explicit predicate mode required')
    _child_limits(limits['max_bytes'], limits['max_predicate_work_units'])
    runtime = record['execution_runtime']
    if (not _digest(record['execution_identity']) or type(runtime) is not dict
            or runtime.keys() != {'versions', 'binaries'}
            or type(runtime['versions']) is not dict or not runtime['versions']
            or type(runtime['binaries']) is not dict):
        raise ValueError('complete execution identity/runtime required')
    if canonical(record['interpreter_seed']) != canonical({'PYTHONHASHSEED': '0', 'hash_randomization': 0}):
        raise ValueError('explicit deterministic interpreter seed required')
    if not _digest(record['dispatch_token']):
        raise ValueError('one-shot 256-bit dispatch token required')


def _child_limits(child_bytes, predicate_units):
    if (type(child_bytes) is not int or child_bytes <= 0 or
            predicate_units is not None and (type(predicate_units) is not int or predicate_units <= 0)):
        raise ValueError('exact positive child budget and explicit predicate mode required')


@dataclass(frozen=True, slots=True)
class JobBinding:
    """Deep immutable snapshot; record() always returns a new decoded copy."""
    encoded: bytes
    _dispatch_token: str = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        record = _decode(self.encoded)
        _validate(record)
        object.__setattr__(self, '_dispatch_token', record['dispatch_token'])

    @classmethod
    def _read(cls, encoded, record):
        """Admit the private mapped worker's own routing decode."""
        if type(encoded) is not bytes:
            raise ValueError('immutable canonical bytes required')
        if type(record) is not dict or canonical(record) != encoded:
            raise ValueError('canonical JSON object required')
        _validate(record)
        binding = object.__new__(cls)
        object.__setattr__(binding, 'encoded', encoded)
        object.__setattr__(binding, '_dispatch_token', record['dispatch_token'])
        return binding

    @classmethod
    def create(cls, *, request, context, child_bytes, predicate_units,
               dispatch_token=None):
        return cls(canonical(dict(schema=_SCHEMA, request=request,
            **capture_runtime(context), child_budget={'max_bytes': child_bytes,
            'max_predicate_work_units': predicate_units},
            dispatch_token=secrets.token_hex(32) if dispatch_token is None else dispatch_token)))

    def record(self):
        return _decode(self.encoded)

    def verify(self, *, request, context, child_bytes, predicate_units):
        wanted = JobBinding.create(request=request, context=context,
            child_bytes=child_bytes, predicate_units=predicate_units,
            dispatch_token=self._dispatch_token)
        if wanted.encoded != self.encoded:
            raise ValueError('live request/runtime/limits differ from dispatched job')


def _carried_record(raw, request, fields, expected=None):
    record = _decode(raw)
    if fields is None:
        fields = request_fields(request)
    if not fields <= record.keys():
        raise ValueError('result does not carry the exact dispatched request')
    carried = canonical({key: record[key] for key in fields})
    if expected is None:
        expected = canonical(request)
    if carried != expected:
        raise ValueError('result does not carry the exact dispatched request')
    return record, expected


def _carries(raw, request, *, _fields=None):
    _carried_record(raw, request, _fields)
    return raw


def _payload(raw, binding):
    return _carries(raw, binding.record()['request'])


def worker_complete(binding_bytes, *, context, request, child_budget, run):
    """Call the reviewed unchanged worker body only between two live checks.

    Limits come from the actual plain child ledger supplied to run(ledger),
    never caller-supplied integers. The reviewed callable must use that ledger
    and return canonical measure bytes; echoed JSON cannot establish its use.
    """
    return _worker_complete(binding_bytes, context=context,
                            request=request, child_budget=child_budget, run=run)


def _worker_complete(binding, *, context, request, child_budget, run, record=None):
    # Only the bounded mapped worker supplies its already admitted record.
    if (type(child_budget) is not WorkBudget
            or any(name in vars(child_budget) for name in
                   ('reserve', 'reserve_predicate_work', 'try_reserve'))):
        raise TypeError('the actual plain child WorkBudget is required')
    if record is None:
        binding = JobBinding(binding)
    def verify():
        binding.verify(request=request, context=context,
                       child_bytes=child_budget.max_bytes,
                       predicate_units=child_budget.max_predicate_work_units)
    verify()
    payload = run(child_budget)
    raw = _payload(payload, binding) if record is None else _carries(payload, record['request'])
    verify()
    return canonical({'schema': _RECEIPT, 'binding': binding.record() if record is None else record,
                      'canonical_json': raw.decode('utf8'),
                      'record_sha256': hashlib.sha256(raw).hexdigest()})


class OwnedDispatch:
    """One parent-owned submit, one result attempt; no arbitrary receipt input.

    The supplied executor and callable MUST belong to the parent. There is no
    attach_future/accept_json operation. An exception/timeout consumes this
    dispatch too; it never proves the child stopped or releases funding.
    """
    def __init__(self, binding):
        if type(binding) is not JobBinding:
            raise TypeError('immutable JobBinding required')
        self.binding = binding
        self._future = None
        self._submitted = self._consumed = False
        self._guard = threading.Lock()

    def submit(self, executor, worker_callable, *args, **kwargs):
        with self._guard:
            if self._submitted:
                raise RuntimeError('job already dispatched')
            self._submitted = True
            future = executor.submit(worker_callable, self.binding.encoded, *args, **kwargs)
            if not isinstance(future, Future):
                raise TypeError('parent-owned executor must return its Future')
            self._future = future

    def result(self, *, timeout=None, **live):
        with self._guard:
            if not self._submitted or self._future is None or self._consumed:
                raise RuntimeError('one result attempt from the dispatched Future required')
            self._consumed = True
            future = self._future
        self.binding.verify(**live)
        receipt = _decode(future.result(timeout=timeout))
        if (receipt.keys() != {'schema', 'binding', 'canonical_json', 'record_sha256'}
                or receipt['schema'] != _RECEIPT
                or canonical(receipt['binding']) != self.binding.encoded
                or type(receipt['canonical_json']) is not str):
            raise ValueError('completion is not for this exact dispatched binding/token')
        raw = receipt['canonical_json'].encode('utf8')
        if not _digest(receipt['record_sha256']) or hashlib.sha256(raw).hexdigest() != receipt['record_sha256']:
            raise ValueError('complete worker-result digest differs')
        self.binding.verify(**live)
        return _carries(raw, receipt['binding']['request'])


@dataclass(frozen=True, slots=True)
class BatchBinding:
    """JobBinding for an ordered list of requests run by one one-shot worker."""
    encoded: bytes

    def __post_init__(self):
        _validate_batch(_decode(self.encoded))

    @classmethod
    def _owned_bytes(cls, encoded):
        """Freeze an owned encoder's bytes, or this private worker's already mapped binding.

        No decoded cache: raw outsiders use the normal validating constructor.
        The dispatcher alone supplies this relationship, never a field in caller bytes.
        """
        result = object.__new__(cls)
        object.__setattr__(result, 'encoded', encoded)
        return result

    @classmethod
    def _read(cls, encoded, record=None):
        """One validated raw operation, optionally reusing its own routing decode."""
        if record is None:
            record = _decode(encoded)
        elif type(encoded) is not bytes or type(record) is not dict or canonical(record) != encoded:
            raise ValueError('immutable canonical batch bytes required')
        _validate_batch(record)
        return cls._owned_bytes(encoded), record

    @classmethod
    def _create_owned(cls, *, requests, context, child_bytes, predicate_units,
                      dispatch_token=None, batch_seconds=None):
        """Concrete interface producer only: member_request and _bind_jobs establish its requests.

        Reuse their ordered tokens/collision, count and transport decisions.
        Runtime/limits/seed/token still enter the normal canonical envelope.
        """
        if batch_seconds is not None:
            _batch_seconds(batch_seconds)
        _child_limits(child_bytes, predicate_units)
        return cls._owned_bytes(canonical(_batch_record(requests=requests,
            context=context, child_bytes=child_bytes, predicate_units=predicate_units,
            dispatch_token=dispatch_token, batch_seconds=batch_seconds)))

    @classmethod
    def create(cls, *, requests, context, child_bytes, predicate_units,
               dispatch_token=None, batch_seconds=None):
        if type(requests) is not list:
            raise ValueError('batch requests must be a list')
        return cls(canonical(_batch_record(requests=requests,
            context=context, child_bytes=child_bytes, predicate_units=predicate_units,
            dispatch_token=dispatch_token, batch_seconds=batch_seconds)))

    def record(self):
        return _decode(self.encoded)

    def verify(self, *, requests, context, child_bytes, predicate_units, batch_seconds=None):
        if type(requests) is not list:
            raise ValueError('batch requests must be a list')
        self._verify_record(self.record(), requests=requests, context=context,
            child_bytes=child_bytes, predicate_units=predicate_units, batch_seconds=batch_seconds)

    def _verify_record(self, record, *, requests, context, child_bytes, predicate_units,
                       batch_seconds=None):
        wanted = _batch_record(requests=requests, context=context,
            child_bytes=child_bytes, predicate_units=predicate_units,
            dispatch_token=record['dispatch_token'], batch_seconds=batch_seconds)
        if canonical(wanted) != self.encoded:
            raise ValueError('live requests/runtime/limits differ from dispatched batch')


def _batch_record(*, requests, context, child_bytes, predicate_units,
                  dispatch_token=None, batch_seconds=None):
    record = dict(schema=_BATCH_SCHEMA, requests=requests,
        **capture_runtime(context), child_budget={'max_bytes': child_bytes,
        'max_predicate_work_units': predicate_units},
        dispatch_token=secrets.token_hex(32) if dispatch_token is None else dispatch_token)
    if batch_seconds is not None:
        record['batch_seconds'] = batch_seconds
    return record


def batch_worker_complete(binding_bytes, *, context, requests, run):
    """Call the reviewed unchanged bodies of one batch only between two live checks.

    run(new_ledger) answers every request in order: the canonical measure
    bytes of that request, 'decided' or 'declined'. new_ledger() mints a
    plain child WorkBudget of exactly the bound limits, never caller-supplied
    integers; each body must run under one of them. One member's result can
    never stand for another: each must carry its own request.
    """
    if type(requests) is not list:
        raise ValueError('batch requests must be a list')
    binding, record = BatchBinding._read(binding_bytes)
    return _batch_worker_complete(binding, record, context=context,
                                  requests=requests, run=run)


def _batch_worker_complete(binding, record, *, context, requests, run):
    """Invocation-local binding/record, already validated or issued by the owned private route."""
    limits, seconds = record['child_budget'], record.get('batch_seconds')
    def verify():
        binding._verify_record(record, requests=requests, context=context,
                       child_bytes=limits['max_bytes'],
                       predicate_units=limits['max_predicate_work_units'], batch_seconds=seconds)
    def new_ledger():
        return WorkBudget(limits['max_bytes'], max_predicate_work_units=limits['max_predicate_work_units'])
    verify()
    answers = run(new_ledger)
    if type(answers) is not list or len(answers) != len(requests):
        raise ValueError('one answer per batch request required')
    results, returning = [], False
    for answer, request in zip(answers, requests, strict=True):
        if returning and answer != 'returned':
            raise ValueError('returned members form an unstarted suffix')
        if type(answer) is bytes:
            raw = answer    # the parent checks it carries its request; the receipt binds its digest
            results.append({'outcome': 'result', 'canonical_json': raw.decode('utf8'),
                            'record_sha256': hashlib.sha256(raw).hexdigest()})
        elif type(answer) is str and (answer in UNANSWERED or answer == 'returned' and seconds is not None):
            if answer == 'returned':
                if not results:
                    raise ValueError('a batch starts its first member before returning a suffix')
                returning = True
            results.append({'outcome': answer})
        else:
            raise ValueError('a batch answer is measure bytes, decided or declined')
    verify()
    return canonical({'schema': _BATCH_RECEIPT, 'binding': record, 'results': results})


class OwnedBatchDispatch:
    """OwnedDispatch for one batch: one submit, one result attempt, no receipt input.

    result() returns one answer per bound request, in order: verified measure
    bytes carrying that request, 'decided', 'declined', or a timed batch's
    unstarted 'returned' suffix.
    """
    def __init__(self, binding):
        if type(binding) is not BatchBinding:
            raise TypeError('immutable BatchBinding required')
        self.binding = binding
        self._future = None
        self._submitted = self._consumed = False
        self._guard = threading.Lock()

    def submit(self, executor, worker_callable, *args, **kwargs):
        with self._guard:
            if self._submitted:
                raise RuntimeError('batch already dispatched')
            self._submitted = True
            future = executor.submit(worker_callable, self.binding.encoded, *args, **kwargs)
            if not isinstance(future, Future):
                raise TypeError('parent-owned executor must return its Future')
            self._future = future

    def result(self, *, timeout=None, **live):
        return self._result(None, None, timeout, live)

    def _interface_result(self, tokens, batch_digest, *, timeout=None, **live):
        return self._result(tokens, batch_digest, timeout, live)

    def _receipt_for(self, index, payload, token, batch_digest):
        receipts = self._consumed
        if type(receipts) is list and 0 <= index < len(receipts):
            entry = receipts[index]
            if entry is not None and entry[0] is payload and entry[1] == token and entry[4] == batch_digest:
                return entry
        return None

    def _result(self, tokens, batch_digest, timeout, live):
        with self._guard:
            if not self._submitted or self._future is None or self._consumed:
                raise RuntimeError('one result attempt from the dispatched Future required')
            self._consumed = True
            future = self._future
        if type(live.get('requests')) is not list:
            raise ValueError('batch requests must be a list')
        record = self.binding.record()
        self.binding._verify_record(record, **live)
        receipt = _decode(future.result(timeout=timeout))
        requests, returned = record['requests'], record.get('batch_seconds') is not None
        if (receipt.keys() != {'schema', 'binding', 'results'} or receipt['schema'] != _BATCH_RECEIPT
                or canonical(receipt['binding']) != self.binding.encoded
                or type(receipt['results']) is not list or len(receipt['results']) != len(requests)):
            raise ValueError('completion is not for this exact dispatched batch/token')
        answers, returning = [], False
        for index, (row, request) in enumerate(zip(receipt['results'], requests, strict=True)):
            if type(row) is not dict or type(row.get('outcome')) is not str:
                raise ValueError('complete batch member outcome required')
            if returning and row['outcome'] != 'returned':
                raise ValueError('returned members form an unstarted suffix')
            if (row['outcome'] in UNANSWERED or returned and row['outcome'] == 'returned') and row.keys() == {'outcome'}:
                if row['outcome'] == 'returned':
                    if not answers:
                        raise ValueError('a batch starts its first member before returning a suffix')
                    returning = True
                answers.append(row['outcome'])
                continue
            if (row['outcome'] != 'result' or row.keys() != {'outcome', 'canonical_json', 'record_sha256'}
                    or type(row['canonical_json']) is not str):
                raise ValueError('complete batch member outcome required')
            raw = row.pop('canonical_json').encode('utf8')
            if not _digest(row['record_sha256']) or hashlib.sha256(raw).hexdigest() != row['record_sha256']:
                raise ValueError('complete worker-result digest differs')
            # tokens[index] is canonical(requests[index]), made by the dispatch from the same list.
            member, expected = _carried_record(raw, request, request.keys(), None if tokens is None else tokens[index])
            answer = raw
            if tokens is not None and tokens[index] == expected:
                from atlas_tectonics.integration.parallel.results import _interface_facts
                # On CPython the two tuples, two ASCII digests and bounded work int
                # take at most these rounded allocation sizes. The discarded receipt
                # string funds staging. The spent request dict funds the retained facts.
                if (sys.implementation.name == 'cpython' and len(raw) >= _FACT_BYTES + 256
                        and type(live['requests'][index]) is dict
                        and sys.getsizeof(live['requests'][index]) >= _FACT_BYTES):
                    facts = _interface_facts(member)
                    if facts is None or (facts[0] <= sys.maxsize and
                            (facts[2] is None or len(facts[2]) == 64 and facts[2].isascii())):
                        answer = (raw, tokens[index], row['record_sha256'], facts, batch_digest)
                    del facts
            del member, expected
            answers.append(answer)
        self.binding._verify_record(record, **live)
        if tokens is not None:
            # The second binding check has consumed these private per-member dicts.
            # Keep the list's extent for accounting. Staging remains local on a failed stop.
            for index in range(len(answers)):
                live['requests'][index] = None
        return answers
