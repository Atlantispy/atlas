"""Private I12 save/reload consumer over the EXISTING ArrayStore byte adapter.

The stored object must be an actual fixed I12 forward result. Restore requires
the independently pinned original result ID plus a separately recovered LIVE
original call, exact sources and runtime. It returns a detached data view, not
I12/native heat and not a new endpoint. No LOW/HIGH/FCT solve, native dispatch,
fixture promotion, source repinning or storage schema/limit change occurs.

With proofs on (compact_contracts.proving(); F-3), independent checks repeat exact input, physical face,
per-cell/projection, loaded-bound and stock/source/exterior equations from
stored bytes; in ordinary runs the projection step's audit of the private record
stands for them and the stored arrays' form and inputs are still tested. They do not
rerun the closed quadratic scalar selection; its original forward provenance
is retained, not converted into a fresh scientific acceptance claim.
JSON views follow resources r4: the saved identity is computed before, not
inside, this consumer's own decode of the same record, and the codec is
booked while the two small binding identities are hashed.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys

from atlas_tectonics._private.integration.heat import native_issuer as I
from atlas_tectonics._private import private_heat_issuer_resources_r4 as R
from atlas_tectonics._private.integration.heat import snapshot_store as STORE

SCHEMA = 'atlas.private.i12-detached-checkpoint-consumer.r10'
_FIELDS = ('enthalpy_j', 'input_capacity_j_k', 'input_enthalpy_j', 'input_source_w', 'temperature_k')


def _verify(cancel):
    R.check(cancel)


def _bindings(call, cancel):
    """Only current externally verified origin, never inferred from storage."""
    with I._verified_call(call, cancel) as owner, R.codec(owner, budget=call._budget, cancel=cancel):
        origin = owner.value
        return dict(call=call.call_id,
            plan=origin['plan_id'], geometry=origin['geometry_id'], state=origin['state_id'],
            runtime=R.stream_hash(origin['execution'], cancel),
            fixture_status=sha256(b'fixture' if call._fixture else b'actual-owner').hexdigest())


def _equations(ar, meta, geometry, arrays, plan, dt):
    n = len(geometry._cells)
    old, cap, source = [ar.decoded_array(arrays[name].tolist(), n)
                        for name in ('input_enthalpy_j', 'input_capacity_j_k', 'input_source_w')]
    timestep = ar.decode(float(dt))
    target = ar.decode(plan['absolute_residual_target'])
    new = ar.decoded_array(meta['exact_corrected_enthalpy_j'], n)
    public = arrays['enthalpy_j'].tolist()
    temperature = arrays['temperature_k'].tolist()
    if (public != [ar.public(v) for v in new]
            or temperature != [e/ar.public(c) for e,c in zip(public, cap, strict=True)]):
        raise ValueError('Stored public stock projection or actual E/C temperature differs')
    source_array, loaded, outward_cells = ar.array(n), ar.array(n), ar.array(n)
    for at, (e, s) in enumerate(zip(old, source, strict=True)):
        ar.put(source_array, at, ar.op('multiply', timestep, s))
        ar.put(loaded, at, ar.op('add', e, source_array[1][at]))
    source = source_array[1]
    zero = ar.G.mpq(0)
    plus, minus = [[zero] for _ in range(n)], [[] for _ in range(n)]    # outward_cells = 0 + out - in
    outward = ar.G.mpq(0)
    walls = ar.array(sum(kind == 'temperature' for kind, _ in plan['boundary'].values()))
    wall_at = 0
    encoded_faces = meta['exact_paired_face_energy_j']
    held = ar.array(len(encoded_faces))    # decoded amounts now live until the cell sums: booked
    for face, (fid, owners, encoded) in enumerate(zip(geometry._face_ids, geometry._incidence, encoded_faces,
                                                      strict=True)):
        ar.check()
        canonical = ar.decode(encoded)
        ar.put(held, face, canonical)
        for at, sign in owners:
            (plus if sign == 1 else minus)[at].append(canonical)
        if len(owners) == 1:
            at, sign = owners[0]
            amount = canonical if sign == 1 else ar.neg(canonical)
            outward = ar.op('add', outward, amount)
            kind, value = plan['boundary'].get(fid, ('power', 0.))
            if kind == 'temperature':
                ar.put(walls, wall_at, ar.decode(float(value)))
                wall_at += 1
            else:
                if not ar.equal(amount, ar.op('multiply', timestep, ar.decode(float(value)))):
                    raise ValueError('Stored prescribed outward physical transfer changed')
                ar.put(loaded, at, ar.op('subtract', loaded[1][at], amount))
    ar.cell_sums(plus, minus, into=outward_cells)
    del plus, minus    # same values as held: drop them first, then credit held at its last use
    ar.release_arrays(held[1])
    hull = ar.array(n+wall_at)
    for at, (e, c) in enumerate(zip(loaded[1], cap, strict=True)):
        ar.put(hull, at, ar.op('divide', e, c))
    for at, value in enumerate(walls[1]):
        ar.put(hull, n+at, value)
    low = high = hull[1][0]
    for value in hull[1][1:]:
        low = ar.minimum(low, value)
        high = value if ar.less(high, value) else high
    if (any(ar.less(e, ar.op('multiply', c, low)) or ar.less(ar.op('multiply', c, high), e)
            for e,c in zip(new, cap, strict=True))
            or any(ar.less(ar.decode(float(t)), low) or ar.less(high, ar.decode(float(t))) for t in temperature)):
        raise ValueError('Stored exact/public heat leaves original loaded bounds')
    for at in range(n):
        retained = ar.op('subtract', ar.op('add', ar.op('subtract', new[at], old[at]), outward_cells[1][at]), source[at])
        represented = ar.decode(float(public[at]))
        projection = ar.op('subtract', represented, new[at])
        total = ar.op('subtract', ar.op('add', ar.op('subtract', represented, old[at]), outward_cells[1][at]), source[at])
        absolute = ar.neg(retained) if ar.less(retained, 0) else retained
        if (ar.less(target, absolute)
                or not ar.equal(retained, ar.decode(meta['exact_retained_solver_residual_j'][at]))
                or not ar.equal(projection, ar.decode(meta['exact_stock_projection_residual_j'][at]))
                or not ar.equal(total, ar.decode(meta['exact_cell_storage_residual_j'][at]))
                or not ar.equal(ar.op('add', retained, projection), total)):
            raise ValueError('Stored physical-face/per-cell/projection residual does not reconcile')
    source_total = ar.total(source)
    public_total = ar.total(ar.decode(float(v)) for v in public)
    old_total = ar.total(old)
    absolute_source = ar.neg(source_total) if ar.less(source_total, 0) else source_total
    absolute_outward = ar.neg(outward) if ar.less(outward, 0) else outward
    scale = old_total
    for value in (public_total, absolute_source, absolute_outward):
        scale = value if ar.less(scale, value) else scale
    total = ar.op('add', ar.op('subtract', ar.op('subtract', public_total, old_total), source_total), outward)
    absolute = ar.neg(total) if ar.less(total, 0) else total
    if (not ar.equal(source_total, ar.decode(meta['exact_source_energy_j']))
            or not ar.equal(outward, ar.decode(meta['exact_outward_boundary_energy_j']))
            or ar.less(ar.decode(['1','100000000000']), ar.op('divide', absolute, scale))):
        raise ValueError('Stored stock/source/exterior global audit differs')


def _validate(snapshot, call, *, expected_result_id, cancel=None):
    """Independent fixed-route validation; never constructs a heat result."""
    with I._verified_call(call, cancel) as caller, _HC.ledger_access(snapshot, call._budget, cancel, R) as view:
        meta, origin = view.value, caller.value
        if (meta.get('schema') != I.SCHEMA or meta.get('method_id') != I.METHOD
                or meta.get('fixed_forward_producer') != 'private_heat_forward_kernel_r13.advance'
                or meta.get('call_id') != call.call_id or meta.get('caller_snapshot') != origin
                or meta.get('state_id') != origin['state_id'] or meta.get('duration_s') != origin['duration_s']
                or meta.get('plan_id') != sha256(call._plan).hexdigest()
                or meta.get('geometry_id') != call._geometry.geometry_id
                or meta.get('cell_ids') != origin['cell_ids'] or meta.get('face_ids') != list(call._geometry._face_ids)
                or meta.get('genuine_forward_origin') is not (not call._fixture)
                or meta.get('origin_binding_status') != ('TEST_FIXTURE_NOT_NATIVE_OWNER' if call._fixture else 'FORWARD_ACTUAL_OWNER_SNAPSHOT')
                or any(meta.get(key) is not False for key in ('native_issue_performed', 'native_resource_admitted',
                    'native_heat_dispatch_enabled', 'production_acceptance', 'whole_method_memory_inventory_certified'))
                or meta.get('endpoint_face_trace_status') != I.N.A.TRACE_STATUS):
            raise ValueError('Saved source/plan/state/geometry/runtime/fixture provenance differs')
        n, nf = len(call._geometry._cells), len(call._geometry._face_ids)
        G = R.A.exact_library()
        from atlas_tectonics._private.integration.heat import gmp_resources as GMP
        # The re-check below holds what its exact arithmetic takes where the process meter
        # supports the runtime; elsewhere, and inside a call that is metered already, the
        # calculated reservations of that arithmetic, as before.
        with R.decoded(call._plan, budget=call._budget, cancel=cancel) as plan_owner, \
                I.F.METER.scope(call._budget, ('private-heat-restored-equations',), 'restored-equations'):
            workspace = GMP.OwnedWorkspace(call._budget, 65536, category='private-heat-restored-equations', cancelled=cancel)
            workspace.__enter__()
            owner = R.O._OwnerWorkspace(workspace)
            try:
                ar = _HC.ledger_arithmetic(R)(workspace, G, GMP, n, nf, 1075, lambda: R.check(cancel))
                owner.arithmetic = ar
                arrays = {name: snapshot.array(name) for name in _FIELDS}
                for output, incoming in (('input_enthalpy_j','enthalpy_j'), ('input_capacity_j_k','capacity_j_k'), ('input_source_w','source_w')):
                    if not I.np.array_equal(arrays[output].view(I.np.uint8),
                                           call._snapshot.array(incoming).view(I.np.uint8)):
                        raise ValueError('Stored actual input arrays differ from original call')
                from atlas_tectonics._private.codecs.compact_contracts import proving
                if proving():    # F-3 (step5-6-twice s4): proofs on only
                    _equations(ar, meta, call._geometry, arrays, plan_owner.value, origin['duration_s'])
                # No arithmetic result escapes this fixed validation frame.
                ar.settle(())
                owner.__exit__(None, None, None)
            except BaseException:
                owner.__exit__(*sys.exc_info())
                raise


@dataclass(frozen=True, slots=True, init=False)
class ReloadedHeatView:
    """Private detached snapshot; borrowed only while returned owner is live."""
    _snapshot: object
    _call: object
    fixture_only: bool

    def __init__(self, *args, **kwargs):
        raise TypeError('Restore a pinned actual forward snapshot, not a heat result injection')

    @property
    def result_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        """A new caller-owned metadata copy, as in the native snapshot API."""
        return self._snapshot.descriptor()

    def array(self, name):
        if name == 'face_temperature_k':
            raise I.N.A.EndpointTraceUnavailable(I.N.A.TRACE_STATUS)
        return self._snapshot.array(name)

    def validate_live_call(self, *, cancel=None):
        _verify(cancel)
        I._verify_call(self._call, cancel)


def save(store, result, call, *, cancel=None):
    """Persist original I12 bytes through existing ArrayStore; return its receipt."""
    receipt = STORE.save(store, result._snapshot, bindings=_bindings(call, cancel), budget=call._budget, cancel=cancel)
    return receipt


def restore(store, receipt, call, *, expected_result_id, cancel=None):
    """Own detached verified data, never relabel it for native or I12 dispatch."""
    bindings = _bindings(call, cancel)
    work = R.workspace(call._budget, 65536, cancel=cancel, category='private-heat-detached-consumer')
    work.__enter__()
    try:
        saved = work.stack.enter_context(STORE.restore(store, receipt, expected_result_id=expected_result_id,
            bindings=bindings, scope=store.scope, mesh=getattr(call._geometry, '_indexed', None), budget=call._budget, cancel=cancel))
        view = object.__new__(ReloadedHeatView)
        for name, value in dict(_snapshot=saved.value, _call=call, fixture_only=call._fixture).items():
            object.__setattr__(view, name, value)
        return R.P.OwnedSolve(view, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise

from atlas_tectonics._private.integration.heat import heat_cold_patch as _HC
