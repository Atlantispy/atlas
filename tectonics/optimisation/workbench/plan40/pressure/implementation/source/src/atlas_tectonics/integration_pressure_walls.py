"""The walls of the current pressure forcing, in order: serially here or on the batch worker route.

differential_pressure_forcing integrates every boundary segment (a "wall") against the
native box, with the density anomaly, and against each reservoir box, without it. A
wall's results are a pure function of its rays, pose and two plates and of the shared
regions, profiles, boxes and settings. Nothing computed for one wall is read by another.
wall_results yields, in the walls' order, what the serial loop computed for each wall:
(force, removed, used, cuts), cuts holding (cut, used) for each reservoir box in order.
The caller merges them with its unchanged C._add calls in that same order, so every sum,
leaf count and record equals the serial one.

Serial: the default, and whenever a gate refuses. wall_set calls the unchanged
moving_wall_integrals for the native box and then for each reservoir box, passing one
_held dict. The region preparation does not depend on the box, so it runs once per wall
instead of once per call (P2). That changes only which identical temporary reservations
are made.

Parallel: only inside parallel(policy, context), which the driver enters around the stage
with the shared InterfaceParallelPolicy (its workers is the ceiling) and the strict
reference ExecutionContext. Only wall_results reads that variable, and a worker never does.
Each gate is recorded, in order: the policy type, mode 'auto', enough walls, the
interpreter seed, strict mode, the predicate ledger, no other optional owner, the
transport envelope, then the machine probe of the rolling interface scheduler
(integration_parallel_selection._Automatic._resources: free physical cores >= workers + 1,
free memory beside the reserve, the budget fraction, predicate units). The probe may
lower the count. A PressureWallSession, a BatchParallelSession, then funds and starts
one-shot workers exactly as for interface batches. That means PARENT_STORAGE once,
child_bytes + CHILD_BASELINE for each worker on the parent's ledger, the
source/runtime/input binding, the RSS and deadline guard, and revocation. The parent
computes walls from the head. Batches of walls are cut from the tail (guided sizes) while
a worker is free. When the parent reaches a wall that a batch holds, it claims the wall
after that worker has exited and its completion has verified against the live requests,
sources and runtime. A wall the worker declined, and every remaining wall of a failed or
revoked session, is computed here by wall_set. A genuine failure is therefore raised from
real frames in the serial order.

A worker decodes the shared inputs (tagged exact encoding: the type and the value of every
int, Fraction, float, str, tuple, list and dict, in order, plus the exact Cartesian cells
and the kernel pose) and computes each wall it was given with the same wall_set under a
ledger of exactly the bound limits.

What is not the same: the parent ledger's timeline and peaks (it holds the worker
funding, and worker temporaries are on worker ledgers), the elapsed time, and which walls
run twice after a problem. No number, summation order, record, leaf count or error that
a caller can observe for a successful stage changes. reports() keeps the last few
decisions for a caller's run report; they never enter an issued record.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from fractions import Fraction
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

from . import integration_parallel_dispatch as D
from . import integration_spatial_pressure as P
from . import integration_volume as V
from . import resources as R
from .integration_parallel_binding import (BATCH_LIMIT, batch_worker_complete, canonical,
    interpreter_seed)
from .integration_parallel_owner import nodes_for
from .integration_parallel_results import SlotLease, raw_capacity

SCHEMA = 'atlas.private.pressure-wall.r1'
INPUT_SCHEMA = 'atlas.private.pressure-wall-inputs.r1'
REPORT_SCHEMA = 'atlas.private.pressure-wall-report.r1'
WALL_FIELDS = frozenset(('schema', 'wall', 'walls', 'inputs', 'max_leaves', 'test'))
MAX_CHUNKS = D.MAX_BATCH_INPUT//D.MAX_INPUT
MIN_WALLS = 4            # fewer walls stay serial: a worker's start-up would not pay
TESTS = (None, 'decline', 'crash')
KEPT_REPORTS = 8
STARTUP_SECONDS = 3.0    # a worker's fixed cost; a batch should carry about four times it
_PARALLEL = ContextVar('atlas_pressure_walls_parallel', default=None)
_REPORTS = deque(maxlen=KEPT_REPORTS)


@contextmanager
def parallel(policy, context, *, test=None):
    """Let the walls of differential_pressure_forcing calls inside this block use workers.

    test is for proofs only: {wall index: 'decline' | 'crash'} for walls a batch holds.
    It travels with this block, never in module state (the loaded-implementation
    guard binds upper-case module values), and a non-empty table is named in the
    report. Production callers never pass it.
    """
    test = {} if test is None else dict(test)
    if any(type(index) is not int or index < 0 or mode not in TESTS[1:] for index, mode in test.items()):
        raise ValueError('test table maps wall indices to decline or crash')
    token = _PARALLEL.set((policy, context, test))
    try:
        yield
    finally:
        _PARALLEL.reset(token)


def reports():
    """The last few wall decisions, newest last: execution reports, never issued state."""
    return [json.loads(json.dumps(report, default=str)) for report in _REPORTS]


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def check_request(request):
    """The one pressure-wall request shape, in the parent when binding and in the worker."""
    if (type(request) is not dict or request.keys() != WALL_FIELDS or request['schema'] != SCHEMA
            or type(request['walls']) is not int or request['walls'] < 1
            or type(request['wall']) is not int or not 0 <= request['wall'] < request['walls']
            or type(request['inputs']) is not list or not 1 <= len(request['inputs']) <= MAX_CHUNKS
            or not all(_digest(identity) for identity in request['inputs'])
            or type(request['max_leaves']) is not int or request['max_leaves'] < 1
            or not (request['test'] is None or type(request['test']) is str and request['test'] in TESTS)):
        raise ValueError('complete exact pressure-wall request required')
    return WALL_FIELDS


# Exact tagged encoding. Every value keeps its type: an int stays an int, a Fraction a
# Fraction, a tuple a tuple, and a dict keeps its key order.

def _enc(value):
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int:
        return ['i', hex(value)]
    if kind is Fraction:
        return ['q', hex(value.numerator), hex(value.denominator)]
    if kind is float:
        return ['f', value.hex()]
    if kind is str:
        return ['s', value]
    if kind is tuple:
        return ['t', [_enc(v) for v in value]]
    if kind is list:
        return ['l', [_enc(v) for v in value]]
    if kind is dict:
        if any(type(k) is not str for k in value):
            raise TypeError('pressure wall inputs: string keys only')
        return ['d', [[k, _enc(v)] for k, v in value.items()]]
    if kind is V.CartesianCell:
        return ['c', _enc(value.lower_m), _enc(value.upper_m), _enc(value.origin_m), _enc(value.basis)]
    from .integration_differential_pressure import _KernelPose
    if kind is _KernelPose:
        return ['p', _enc(value._rotation), _enc(value._error), _enc(value._plane_history)]
    raise TypeError('pressure wall inputs: unsupported type '+kind.__name__)


def _dec(value, budget, *, objects=True):
    if value is None or type(value) is bool:
        return value
    if type(value) is not list or not value or type(value[0]) is not str:
        raise ValueError('tagged exact value required')
    tag, rest = value[0], value[1:]
    if tag == 'i' and len(rest) == 1:
        return int(rest[0], 16)
    if tag == 'q' and len(rest) == 2:
        numerator, denominator = int(rest[0], 16), int(rest[1], 16)
        result = Fraction(numerator, denominator)
        if result.numerator != numerator or result.denominator != denominator:
            raise ValueError('noncanonical exact rational')
        return result
    if tag == 'f' and len(rest) == 1:
        return float.fromhex(rest[0])
    if tag == 's' and len(rest) == 1 and type(rest[0]) is str:
        return rest[0]
    if tag == 't' and len(rest) == 1 and type(rest[0]) is list:
        return tuple(_dec(v, budget, objects=objects) for v in rest[0])
    if tag == 'l' and len(rest) == 1 and type(rest[0]) is list:
        return [_dec(v, budget, objects=objects) for v in rest[0]]
    if tag == 'd' and len(rest) == 1 and type(rest[0]) is list:
        result = {}
        for pair in rest[0]:
            if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str or pair[0] in result:
                raise ValueError('ordered string-keyed pairs required')
            result[pair[0]] = _dec(pair[1], budget, objects=objects)
        return result
    if objects and tag == 'c' and len(rest) == 4:
        lower, upper, origin, basis = (_dec(v, budget, objects=False) for v in rest)
        return V.CartesianCell(lower, upper, origin, basis, budget=budget)
    if objects and tag == 'p' and len(rest) == 3:
        from .integration_differential_pressure import _KernelPose
        rotation, error, history = (_dec(v, budget, objects=False) for v in rest)
        return _KernelPose(rotation, error, history=history)
    raise ValueError('unknown tagged exact value')


def _selected(regions, left, right):
    # The serial loop's own selection, unchanged.
    return [dict(region, side=None if region['plate_id'] is None else (0 if region['plate_id'] == left else 1))
            for region in regions if region['plate_id'] in (None, left, right)]


def wall_set(rays, profiles, selected, native_box, reservoirs, pose, args):
    """One wall: the native box with density, then each reservoir box without (P2: one preparation)."""
    held = {}
    force, removed, used = P.moving_wall_integrals(*rays, profiles, selected, native_box, pose, _held=held, **args)
    cuts = []
    for box in reservoirs:
        _, cut, count = P.moving_wall_integrals(*rays, profiles, selected, box, pose,
                                                compute_density=False, _held=held, **args)
        cuts.append((cut, count))
    return force, removed, used, cuts


def _shared_inputs(walls, regions, profiles, native_box, reservoirs, args):
    """The canonical encoded inputs every batch ships, as ordered chunks within MAX_INPUT."""
    record = dict(schema=INPUT_SCHEMA, regions=_enc([_plain_planes(region) for region in regions]),
        profiles=_enc(profiles),
        native_box=_enc(native_box), reservoirs=_enc(tuple(reservoirs)),
        args=_enc({k: v for k, v in args.items() if k != 'budget'}),
        walls=_enc([(left, right, rays, pose) for left, right, rays, pose, _ in walls]))
    raw = canonical(record)
    chunks = [raw[i:i+D.MAX_INPUT] for i in range(0, len(raw), D.MAX_INPUT)]
    ids = [hashlib.sha256(chunk).hexdigest() for chunk in chunks]
    return dict(zip(ids, chunks)), ids, len(raw), _decoded_bound(raw)


class _ParentInputBudgetRefusal(ValueError):
    """An optional reservation declined before allocating its input storage."""
    def __init__(self, stage, requested_bytes):
        self.stage, self.requested_bytes = stage, requested_bytes
        super().__init__('pressure '+stage+' budget refused')


class _ParentInputSizer:
    """Count the existing encoding without constructing its tagged tree.

    Wire bytes are exact; capacity is a conservative CPython allocation envelope,
    not RSS. A tagged node gets 256 bytes plus 16 per child; dict pairs get another
    128 bytes. Generated scalar text is counted separately. Input objects remain
    caller-owned. The depth cap bounds this pass's scratch under its 64 KiB lease.
    """
    def __init__(self):
        self.raw, self.tree, self.depth = 0, 65536, 0
        self.limit = min(D.PARENT_STORAGE//4, D.MAX_BATCH_INPUT)

    def emit(self, count):
        self.raw += count
        if self.raw > self.limit:
            raise ValueError('pressure shared inputs exceed the parent raw transport bound')

    def string(self, value):
        if type(value) is not str:
            raise TypeError('pressure wall inputs: string keys only')
        self.emit(2)
        for char in value:
            code = ord(char)
            self.emit(2 if char in '"\\\b\f\n\r\t' else
                      6 if code < 32 or 127 <= code <= 65535 else
                      12 if code > 65535 else 1)

    def hex_string(self, value):
        count = 2+max(1, (value.bit_length()+3)//4)+(value < 0)
        self.tree += 64+count
        self.emit(count+2)

    def sequence(self, tag, values):
        self.emit(6)  # ["t",[ or ["l",[
        first = True
        for value in values:
            if not first:
                self.emit(1)
            first = False
            self.tree += 16
            self.encoded(value)
        self.emit(2)

    def mapping(self, items, *, plain_planes=False):
        self.emit(6)  # ["d",[
        first = True
        for key, value in items:
            if not first:
                self.emit(1)
            first = False
            self.tree += 128
            self.emit(1)
            self.string(key)
            self.emit(1)
            helper = sys.modules.get('pressure_indexed_patch') if plain_planes else None
            owned = (helper is not None and key == '_physical_planes'
                     and type(value) is getattr(helper, '_OwnedPlanes', None))
            if owned:
                # _plain_planes materialises a tuple; account it as well.
                self.tree += 256+16*len(value)
                self.sequence('t', iter(value))
            else:
                self.encoded(value)
            self.emit(1)
        self.emit(2)

    def encoded(self, value, *, plain_planes=False):
        self.depth += 1
        try:
            if self.depth > 64:
                raise ValueError('pressure input preparation depth exceeds bounded scratch')
            self.tree += 256
            kind = type(value)
            if value is None:
                self.emit(4)
            elif kind is bool:
                self.emit(4 if value else 5)
            elif kind is int:
                self.emit(5)
                self.hex_string(value)
                self.emit(1)
            elif kind is Fraction:
                self.emit(5)
                self.hex_string(value.numerator)
                self.emit(1)
                self.hex_string(value.denominator)
                self.emit(1)
            elif kind is float:
                # float.hex is bounded (including nan/inf); _enc uses the same text.
                text = value.hex()
                self.tree += 64+len(text)
                self.emit(5)
                self.string(text)
                self.emit(1)
            elif kind is str:
                self.emit(5)
                self.string(value)
                self.emit(1)
            elif kind in (tuple, list):
                self.sequence('t' if kind is tuple else 'l', value)
            elif kind is dict:
                self.mapping(value.items(), plain_planes=plain_planes)
            elif kind is V.CartesianCell:
                self.emit(5)
                for index, part in enumerate((value.lower_m, value.upper_m, value.origin_m, value.basis)):
                    if index:
                        self.emit(1)
                    self.encoded(part)
                self.emit(1)
            else:
                from .integration_differential_pressure import _KernelPose
                if kind is not _KernelPose:
                    raise TypeError('pressure wall inputs: unsupported type '+kind.__name__)
                self.emit(5)
                for index, part in enumerate((value._rotation, value._error, value._plane_history)):
                    if index:
                        self.emit(1)
                    self.encoded(part)
                self.emit(1)
        finally:
            self.depth -= 1


def _parent_input_capacity(walls, regions, profiles, native_box, reservoirs, args):
    count = _ParentInputSizer()
    # Seven outer keys; key order cannot change their canonical byte count.
    count.emit(1)
    count.string('schema')
    count.emit(1)
    count.string(INPUT_SCHEMA)
    count.emit(1)
    count.string('regions')
    count.emit(1)
    count.emit(6)
    first = True
    for region in regions:
        if not first:
            count.emit(1)
        first = False
        # Temporary region list, optional plain dict and its entry slots.
        count.tree += 256+(128*len(region) if type(region) is dict else 0)
        count.encoded(region, plain_planes=True)
    count.emit(2)
    for name, value in (('profiles', profiles), ('native_box', native_box)):
        count.emit(1)
        count.string(name)
        count.emit(1)
        count.encoded(value)
    count.emit(1)
    count.string('reservoirs')
    count.emit(1)
    count.tree += 256+16*len(reservoirs)
    count.sequence('t', reservoirs)
    count.emit(1)
    count.string('args')
    count.emit(1)
    count.tree += 256+128*len(args)
    count.mapping((key, value) for key, value in args.items() if key != 'budget')
    count.emit(1)
    count.string('walls')
    count.emit(1)
    count.tree += 256+128*len(walls)
    count.sequence('l', ((left, right, rays, pose) for left, right, rays, pose, _ in walls))
    count.emit(1)
    chunks = (count.raw+D.MAX_INPUT-1)//D.MAX_INPUT
    # Tagged tree plus canonical JSON encoder fragments, final str/bytes and
    # sliced chunk copies coexist transiently. Four wire copies are conservative;
    # per-node slack also covers the JSON encoder's fragment references.
    preparation = count.tree+4*count.raw+65536
    retained = count.raw+1024*chunks+65536
    return count.raw, preparation, retained


class _ParentSharedInputs:
    """Own preparation admission, then the raw shared input carrier's lease."""
    def __init__(self, budget, walls, regions, profiles, native_box, reservoirs, args):
        self.inputs = self.ids = None
        self.holds = ExitStack()
        try:
            with budget.try_reserve(65536, category='pressure-input-preflight') as admitted:
                if not admitted:
                    raise _ParentInputBudgetRefusal('input preflight', 65536)
                expected, self.preparation, self.retained = _parent_input_capacity(
                    walls, regions, profiles, native_box, reservoirs, args)
            admitted = self.holds.enter_context(
                budget.try_reserve(self.retained, category='pressure-input-retained'))
            if not admitted:
                raise _ParentInputBudgetRefusal('retained input', self.retained)
            with budget.try_reserve(self.preparation, category='pressure-input-preparation') as admitted:
                if not admitted:
                    raise _ParentInputBudgetRefusal('input preparation', self.preparation)
                try:
                    self.inputs, self.ids, self.size, self.decoded = _shared_inputs(
                        walls, regions, profiles, native_box, reservoirs, args)
                    if self.size != expected:
                        raise ValueError('pressure input canonical size changed during preparation')
                except BaseException as error:
                    # Drop encoder frames before releasing their allocation allowance.
                    error.__traceback__ = None
                    self.close()
                    raise
        except BaseException as error:
            error.__traceback__ = None
            self.close()
            raise

    def close(self):
        if self.inputs is not None:
            self.inputs.clear()
            self.inputs = None
        if self.ids is not None:
            self.ids.clear()
            self.ids = None
        self.holds.close()




def _plain_planes(region):
    """An indexed state's region with its _physical_planes as the legacy plain tuple (r4).

    pressure_indexed_patch keeps an indexed state's (issued constraint record, elapsed)
    pairs in a process-local _OwnedPlanes, a tuple subclass that refuses copies. The
    ordinary route builds the same pairs as tuple(physical_planes), and the helper's
    parity test holds the two equal. Only the encoded copy for the workers becomes that
    plain tuple: the parent's regions keep their owner, and each worker books the decoded
    copy with the shared inputs (r3). moving_wall_integrals uses only truth, len and
    iteration (zip) of it; the contract-plane proof script enforces that. Any other type
    is left as it is, and _enc refuses it as before.
    """
    planes = region.get('_physical_planes') if type(region) is dict else None
    if planes is None or type(planes) is tuple:
        return region
    helper = sys.modules.get('pressure_indexed_patch')
    if helper is None or type(planes) is not getattr(helper, '_OwnedPlanes', None):
        return region
    return dict(region, _physical_planes=tuple(iter(planes)))


def _decoded_bound(raw):
    """The interface route's bound on decoding raw canonical JSON (r3, P1 refuter finding 4)."""
    from .integration_routing_views import _decoded_json_capacity
    return _decoded_json_capacity(raw)+65536+4*len(raw)


def _transport_fits(size, decoded, child_bytes):
    """The transport envelope (r5): the parent holds only the raw inputs, a worker their decoding.

    As the interface route: raw bytes within the parent storage share and the batch input cap,
    and the decoding bound within the child ledger that _open_ledger books it on (the interface
    worker books each decoded support on its child budget). r3/r4 compared the decoding bound
    with the parent share, a per-support rule, which refused every real input.
    """
    return size <= D.PARENT_STORAGE//4 and size <= D.MAX_BATCH_INPUT and decoded <= child_bytes


def _decode_shared(inputs, ids, budget):
    raw = b''.join(inputs[identity] for identity in ids)
    record = json.loads(raw)
    if type(record) is not dict or canonical(record) != raw or record.get('schema') != INPUT_SCHEMA:
        raise ValueError('canonical pressure-wall inputs required')
    shared = {name: _dec(record[name], budget) for name in
              ('regions', 'profiles', 'native_box', 'reservoirs', 'args', 'walls')}
    if type(shared['args']) is not dict or set(shared['args']) != {
            'gravity', 'support_radius', 'radius', 'width', 'max_leaves'}:
        raise ValueError('complete pressure-wall settings required')
    return shared


def _open_ledger(new_ledger, holds, inputs, ids, decoded):
    """A fresh child ledger with the shared inputs decoded on it (r3, P1 refuter finding 4).

    The decoding bound is booked first and held by holds until the batch's run ends,
    so every wall computed on this ledger sees it as used. A ledger too small raises:
    the wall is declined and the parent computes it.
    """
    ledger = new_ledger()
    holds.enter_context(ledger.reserve(decoded, category='pressure-wall-inputs'))
    return ledger, _decode_shared(inputs, ids, ledger)


def _compute(shared, index, budget):
    left, right, rays, pose = shared['walls'][index]
    return wall_set(rays, shared['profiles'], _selected(shared['regions'], left, right),
                    shared['native_box'], shared['reservoirs'], pose, dict(shared['args'], budget=budget))


def _check_result(result, reservoirs):
    def pairs(value):
        return (type(value) is tuple and len(value) == 3 and all(
            type(pair) is tuple and len(pair) == 2 and all(type(q) in (int, Fraction) for q in pair)
            for pair in value))
    if (type(result) is not tuple or len(result) != 4 or not pairs(result[0]) or not pairs(result[1])
            or type(result[2]) is not int or result[2] < 0 or type(result[3]) is not list
            or len(result[3]) != reservoirs or not all(
                type(row) is tuple and len(row) == 2 and pairs(row[0]) and type(row[1]) is int and row[1] >= 0
                for row in result[3])):
        raise ValueError('complete wall result required')
    return result


def batch_worker(directory, process, binding_bytes, requests):
    """integration_parallel_dispatch._batch_worker for pressure walls (worker process only).

    Every input chunk is read mapped and checked against its digest, the shared inputs
    are decoded under a child ledger of exactly the bound limits, and each wall is
    computed by wall_set between the two live checks of batch_worker_complete. A wall
    that raises is answered 'declined' (the parent then computes it itself); after one,
    the next wall gets a fresh ledger and a fresh decoding.
    """
    from .reuse import ExecutionContext
    directory = Path(directory)
    for request in requests:
        check_request(request)
    first = requests[0]
    ids = first['inputs']
    if any((r['inputs'], r['walls'], r['max_leaves']) != (ids, first['walls'], first['max_leaves'])
           for r in requests):
        raise ValueError('one batch shares one input set')
    inputs, size = {}, 0
    for identity in ids:
        if identity in inputs:
            continue
        raw = D._mapped_read(directory/'inputs'/(identity+'.json'), D.MAX_INPUT)
        if hashlib.sha256(raw).hexdigest() != identity:
            raise ValueError('pressure-wall input digest differs')
        size += len(raw)
        if size > D.MAX_BATCH_INPUT:
            raise ValueError('batch inputs exceed the optional transport envelope')
        inputs[identity] = raw
    observed = dict(body=0.0, peak=0)
    decoded = _decoded_bound(b''.join(inputs[identity] for identity in ids))
    with ExecutionContext('reference') as context:
        def run(new_ledger):
            with ExitStack() as holds:
                return _answer(new_ledger, holds)

        def _answer(new_ledger, holds):
            answers, room = [], D.MAX_RECEIPT-2*len(binding_bytes)-65536
            ledger = shared = baseline = None
            for request in requests:
                if request['test'] == 'crash':
                    os._exit(3)    # proof scripts only: a worker that ends without a completion
                try:
                    if request['test'] == 'decline':
                        raise ValueError('Pressure proof: declined wall')
                    if ledger is None or ledger.reserved_bytes != baseline:
                        if ledger is not None:
                            observed['peak'] = max(observed['peak'], ledger.statistics()['peak_reserved_bytes'])
                            # r5 (P1 refuter note): as the interface worker, drop the old decoding first.
                            ledger = shared = None
                            gc.collect()
                        ledger, shared = _open_ledger(new_ledger, holds, inputs, ids, decoded)
                        baseline = ledger.reserved_bytes
                        if (len(shared['walls']) != first['walls']
                                or shared['args']['max_leaves'] != first['max_leaves']):
                            raise ValueError('pressure-wall request and inputs differ')
                    begun = time.perf_counter()
                    # Only this process-local serial worker owns this root ledger.
                    from . import pressure_midpoint_values as MV
                    with MV.worker_custody(ledger):
                        result = _compute(shared, request['wall'], ledger)
                    observed['body'] += time.perf_counter()-begun
                    raw = canonical(dict(request, result=_enc(result)))
                    if len(raw) > D.MAX_RESULT or 2*len(raw)+256 > room:
                        answers.append('declined')    # the bounded completion has no room for it
                    else:
                        answers.append(raw)
                        room -= 2*len(raw)+256
                except Exception:
                    answers.append('declined')
                    if ledger is not None:
                        observed['peak'] = max(observed['peak'], ledger.statistics()['peak_reserved_bytes'])
                    ledger = shared = None
            if ledger is not None:
                observed['peak'] = max(observed['peak'], ledger.statistics()['peak_reserved_bytes'])
            return answers
        receipt = batch_worker_complete(binding_bytes, context=context,
            read_bindings=lambda: D._inventory(inputs), requests=requests, run=run)
        if len(receipt) > D.MAX_RECEIPT:
            raise ValueError('receipt exceeds optional wire envelope')
        with (directory/'result.json').open('xb') as stream:
            stream.write(receipt)
    try:
        D._resource_report(directory, process, observed['body'], observed['peak'])
    except Exception:
        pass    # as for the interface batches: the completion is already verified


class PressureWallSession(D.BatchParallelSession):
    """The interface batch session for pressure-wall requests.

    Unchanged: open, launch (funding, binding, start), claim, receive (completion
    verified against the live requests, sources and runtime after the worker has
    exited), finish, stop, close. Jobs are complete wall requests that share the
    session's encoded inputs. A member's answer is decoded under a funded result slot
    and checked for shape. A decline leaves the wall to the parent. A failed adoption
    revokes the session, as for interfaces.
    """
    wall_inputs = None
    reservoirs = None

    _shared_inputs_hold = None

    def _release_shared_inputs(self):
        held = self._shared_inputs_hold
        if held is not None:
            self.wall_inputs = None
            held.close()
            self._shared_inputs_hold = None

    def _stop(self):
        super()._stop()
        self._release_shared_inputs()

    def close(self):
        super().close()
        self._release_shared_inputs()

    def _bind_jobs(self, jobs):
        requests = []
        for request in jobs:
            check_request(request)
            requests.append(request)
        if not requests or len(requests) > BATCH_LIMIT:
            raise ValueError('batch exceeds the optional transport envelope')
        tokens = [canonical(request) for request in requests]
        if len(set(tokens)) != len(tokens) or any(token in self.members for token in tokens):
            raise ValueError('duplicate optional request')
        return requests, tokens, dict(self.wall_inputs)

    def _adopt(self, batch, index, request, budget, answer):
        begun = time.perf_counter()
        slot = None
        try:
            slot = SlotLease.attempt(R, self.budget, raw_capacity(len(answer)))
            if slot is None:
                raise ValueError('optional result slot refused')
            record = json.loads(answer)
            if type(record) is not dict or canonical(record) != answer or record.keys() != WALL_FIELDS | {'result'}:
                raise ValueError('complete canonical wall answer required')
            result = _check_result(_dec(record['result'], self.budget, objects=False), self.reservoirs)
            self.stats['adopted'] += 1
            batch['adopted'] += 1
            return result
        except Exception as error:
            error.__traceback__ = None
            self.last_error = str(error)[:4096]
            self.cause = self.cause or 'adoption declined'
            self.stats['declined'] += 1
            batch['declined'] += 1
            return None
        finally:
            if slot is not None:
                slot.close()
            self.seconds['adopt'] += time.perf_counter()-begun


class _Run:
    """One stage's walls: gates, session, head/tail schedule and report."""

    def __init__(self, settings, walls, regions, profiles, native_box, reservoirs, args):
        self.count, self.budget = len(walls), args['budget']
        self.session, self.held, self.tail, self.head = None, {}, self.count, 0
        self.test = {} if settings is None else settings[2]
        self.workers, self.timeout, self.ids, self.walls_seconds = 0, None, None, []
        self.t0 = time.perf_counter()
        self.report = dict(schema=REPORT_SCHEMA, walls=self.count, reservoirs=len(reservoirs),
            route='serial', reason=None, detail=None, gates=[], policy=None, ceiling=None, workers=0,
            input_bytes=None, batches=[], refused_launches=0, adopted=0, parent_walls=0, recomputed=[],
            parent_wall_seconds=[], test={} if settings is None else dict(settings[2]),
            seconds=dict(open=0.0, claim=0.0, parent=0.0, total=0.0), session=None)
        _REPORTS.append(self.report)
        if settings is None:
            self._serial('no parallel context', 'the stage was not called inside parallel(policy, context)')
            return
        begun = time.perf_counter()
        try:
            self._open(*settings[:2], walls, regions, profiles, native_box, reservoirs, args)
        except Exception as error:
            self._serial('open failure', '%s: %s' % (type(error).__name__, str(error)[:2048]))
            self.close()
        except BaseException:
            self.close()
            raise
        finally:
            self.report['seconds']['open'] = round(time.perf_counter()-begun, 3)

    def _gate(self, name, value, passed):
        self.report['gates'].append(dict(gate=name, value=value, passed=bool(passed)))
        return passed

    def _serial(self, reason, detail):
        self.report.update(route='serial', reason=reason, detail=detail)
        return False

    def _open(self, policy, context, walls, regions, profiles, native_box, reservoirs, args):
        from . import integration_parallel_selection as S
        from . import reuse
        budget = self.budget
        if not self._gate('policy', type(policy).__name__, type(policy) is S.InterfaceParallelPolicy):
            return self._serial('policy', 'the shared InterfaceParallelPolicy is required')
        self.report['policy'] = dict(mode=policy.mode, workers=policy.workers, child_bytes=policy.child_bytes,
            predicate_units=policy.predicate_units, timeout_seconds=policy.timeout_seconds,
            ram_reserve_bytes=policy.ram_reserve_bytes, budget_fraction=policy.budget_fraction)
        self.report['ceiling'] = policy.workers
        if not self._gate('mode', policy.mode, policy.mode == 'auto'):
            return self._serial('mode', 'policy mode %r never dispatches' % policy.mode)
        if not self._gate('walls', dict(walls=self.count, minimum=MIN_WALLS), self.count >= MIN_WALLS):
            return self._serial('walls', 'too few walls for a worker to pay')
        try:
            interpreter_seed()
            seeded = True
        except RuntimeError:
            seeded = False
        if not self._gate('seed', os.environ.get('PYTHONHASHSEED'), seeded):
            return self._serial('seed', 'the interpreter did not start with PYTHONHASHSEED=0')
        mode = reuse.execution_mode()
        strict = mode == 'strict' and type(context) is reuse.ExecutionContext and context._mode == 'strict'
        if not self._gate('strict-mode', mode, strict):
            return self._serial('strict-mode', 'workers require the strict reference execution context')
        ledger = type(budget) is R.WorkBudget and budget._predicate_work is not None
        if not self._gate('ledger', 'predicate' if ledger else 'bytes', ledger):
            return self._serial('ledger', 'the legacy byte-charged work ledger cannot fund a worker')
        registered = any(node._revoker is not None for node in nodes_for((budget, budget._predicate_work)))
        if not self._gate('owner', registered, not registered):
            return self._serial('owner', 'another optional owner is registered on this budget ancestry')
        try:
            shared = _ParentSharedInputs(budget, walls, regions, profiles, native_box, reservoirs, args)
        except _ParentInputBudgetRefusal as error:
            self._gate('parent-input-budget', dict(stage=error.stage,
                requested_bytes=error.requested_bytes), False)
            return self._serial('budget', str(error))
        try:
            ids, size, decoded = shared.ids, shared.size, shared.decoded
            self.report['parent_input_accounting'] = dict(preflight_bytes=65536,
                preparation_bound=shared.preparation, retained_bound=shared.retained)
            self.report['input_bytes'] = size
            fits = _transport_fits(size, decoded, policy.child_bytes)
            if not self._gate('transport', dict(bytes=size, decoded_bound=decoded, child_bytes=policy.child_bytes,
                                                chunks=len(ids)), fits):
                return self._serial('transport', 'the shared wall inputs exceed the optional transport envelope')
            probe = S._Automatic()
            probe.policy, probe.budget = policy, budget
            probe.workers = policy.workers
            admitted = probe._resources()
            self.report['gates'].extend(probe.decision['gates'])
            if not admitted:
                return self._serial(probe.decision['reason'], probe.decision['detail'])
            session = PressureWallSession(budget=budget, max_width_m3=args['width'], max_leaves=args['max_leaves'],
                wall=False, workers=probe.workers, child_bytes=policy.child_bytes,
                predicate_units=policy.predicate_units, timeout_seconds=policy.timeout_seconds,
                budget_fraction=policy.budget_fraction)
            session.wall_inputs, session.reservoirs = shared.inputs, len(reservoirs)
            session._shared_inputs_hold, shared = shared, None
            self.session = session
            if not session.open(lambda: context):
                self.session = None
                return self._serial('session', session.plan.get('funding') or (session.last_error or 'not opened'))
            session.on_wait = self._on_wait
            self.workers, self.timeout, self.ids = probe.workers, policy.timeout_seconds, ids
            self.max_leaves = args['max_leaves']
            self.report.update(route='parallel', workers=probe.workers)
            self.top_up(0)
            return True
        finally:
            if shared is not None:
                shared.close()

    def _request(self, index):
        return dict(schema=SCHEMA, wall=index, walls=self.count, inputs=list(self.ids),
                    max_leaves=self.max_leaves, test=self.test.get(index))

    def _size(self, free):
        size = math.ceil(free/(2*(self.workers+1)))
        if self.walls_seconds:
            typical = sorted(self.walls_seconds)[len(self.walls_seconds)//2]
            if typical > 0:
                size = max(size, math.ceil(4*STARTUP_SECONDS/typical))
        return max(1, min(free, size))

    def top_up(self, head):
        """Start batches from the tail while a worker is free; never the parent's next wall."""
        session = self.session
        if session is None or not session.check():
            return
        while session.running() < self.workers:
            free = self.tail-(head+1)
            if free < 1:
                return
            size = self._size(free)
            first = self.tail-size
            requests = [self._request(index) for index in range(first, self.tail)]
            batch = session.launch(requests, self.timeout)
            if batch is None:
                self.report['refused_launches'] += 1
                return
            for index, request in zip(range(first, self.tail), requests):
                self.held[index] = request
            self.report['batches'].append(dict(index=batch['index'], first=first, walls=size,
                started_s=round(time.perf_counter()-self.t0, 3)))
            self.tail = first

    def _on_wait(self):
        self.top_up(self.head)

    def claim(self, index):
        """This wall's adopted worker answer, or None for the parent to compute it."""
        self.head = index
        request = self.held.pop(index, None)
        if request is None or self.session is None:
            if request is not None:
                self.report['recomputed'].append(index)
            return None
        begun = time.perf_counter()
        result = self.session.claim(request, self.budget)
        self.report['seconds']['claim'] += time.perf_counter()-begun
        if result is None:
            self.report['recomputed'].append(index)
        else:
            self.report['adopted'] += 1
        return result

    def parent_wall(self, seconds):
        self.walls_seconds.append(seconds)
        self.report['parent_walls'] += 1
        self.report['seconds']['parent'] += seconds
        if len(self.report['parent_wall_seconds']) < 4096:
            self.report['parent_wall_seconds'].append(round(seconds, 3))

    def close(self):
        # Keep the session reachable until shutdown has confirmed every child stop.
        # An interrupted close must remain retryable by wall_results' finally.
        session = self.session
        if session is not None:
            try:
                session.close()
            finally:
                self.report['session'] = dict(stats=dict(session.stats), seconds=dict(session.seconds),
                    log=list(session.log), cause=session.cause, last_error=session.last_error,
                    waits=session.waits)
        self.session = None
        self.report['seconds']['total'] = round(time.perf_counter()-self.t0, 3)


def wall_results(walls, regions, profiles, native_box, reservoirs, args):
    """(force, removed, used, cuts) for each wall, in the walls' order (see the module text)."""
    run = _Run(_PARALLEL.get(), walls, regions, profiles, native_box, reservoirs, args)
    try:
        for index, (left, right, rays, pose, _) in enumerate(walls):
            result = run.claim(index)
            if result is None:
                begun = time.perf_counter()
                result = wall_set(rays, profiles, _selected(regions, left, right), native_box,
                                  reservoirs, pose, args)
                run.parent_wall(time.perf_counter()-begun)
            if index == len(walls)-1:
                run.close()    # before the caller's last merge: nothing outlives the stage
            else:
                run.top_up(index+1)
            yield result
    finally:
        run.close()
