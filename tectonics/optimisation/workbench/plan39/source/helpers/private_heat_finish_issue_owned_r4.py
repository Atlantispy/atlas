"""Private exact r3 issuance with fixed-operation, actual-width admission.

The frozen numerical checks, record fields and their order are retained.
Method/source identities describe this successor. No native origin, native
production issue, whole-method admission or allocator/RSS bound is conferred.
The caller supplies and keeps its original exact GMP inputs owned. This owner
also charges its retained copies, all audit arrays and the complete record.
Every native arithmetic operation is admitted before execution. The final
codec envelope is derived from actual final entry widths before formatting;
the two sequential encodings use the unchanged frozen encoder.

The result graph and sealed bytes remain owned until normal close. Current
scalar/codec workspace settles only after the producer frame has gone.
Failed frames preserve their workspace and arrays. No static
symbolic issue-growth inventory, solver, geometry or FINISH route runs here.

R4 is R3 with one addition. The record is encoded twice, each time into one
growing buffer and then one whole copy, and the copy has no safe point inside
it. Where the caller's forward call is metered (process meter r1) the two
encodings keep the codec inventory's own figure reserved across them as a
declared single step: one buffer at its largest capacity and one whole copy,
which also covers the two blocks a buffer holds while it is moved to a larger
one. Without a meter the statement does nothing. Every check, field, figure
and byte of the record is R3's.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
import math
from pathlib import Path
import sys

import private_heat_correction_owned_r1 as O
import private_heat_finish_entry_owned_r2 as E
import private_heat_finish_codec_inventory_r1 as C
import private_heat_finish_kernel_r3 as K
import private_heat_process_meter_r1 as METER


HERE = Path(__file__).resolve().parent
METHOD = 'private:standalone-conservative-physical-face-finish-r7'
PINS = {
    'private_heat_correction_owned_r1.py': '446945e8a0e411102e177412dc7ac32c7dafabe043e9f4ab0ab7af4447cfdae4',
    'private_heat_finish_codec_inventory_r1.py': '6ecc5c68266db6a29dd98518ba16705705a1c7a167ac43bf673caa63fb52d793',
    'private_heat_finish_kernel_r3.py': 'e3d36778f4514991e893af5970ff0eeceb5cfa28b16ec82d32b290900a79f9a0',
}
_SOURCES = dict(E._SOURCES, **{str(HERE/name): pin for name, pin in PINS.items()})
_SOURCES[str(Path(__file__).resolve())] = sha256(Path(__file__).read_bytes()).hexdigest()


class _IssueArithmetic(E.Arithmetic):
    def absolute(self, value):
        return self.neg(value) if self.less(value, 0) else value

    def maximum(self, values):
        iterator = iter(values)
        result = next(iterator)
        for value in iterator:
            if self.less(result, value):
                result = value
        return result

    def total(self, values):
        result = 0
        for value in values:
            result = self.op('add', result, value)
        return result

    def represented(self, value):
        self.reserve(max(self.peak_bits, 1075))
        return self.G.mpq(value)

    def native_float(self, value):
        shape = self.shape(value)
        self.reserve(max(shape.numerator_bits, shape.denominator_bits, 1075))
        return float(value)

    def loaded_residual(self, energy, faces, load):
        result = self.array(len(energy))
        for at, (e, b) in enumerate(zip(energy, load, strict=True)):
            self.put(result, at, self.op('subtract', e, b))
        for i, j, amount in faces:
            self.put(result, i, self.op('add', result[1][i], amount))
            if j is not None:
                self.put(result, j, self.op('subtract', result[1][j], amount))
        return result[1]


class IssueOwner(O.OwnedSolve):
    @property
    def inventory(self):
        self.value
        ar = self._workspace.arithmetic
        return dict(route='FIXED_ISSUE_ACTUAL_WIDTHS_AND_SEQUENTIAL_CODEC',
            operations=ar.operations, retained_array_bytes=ar.live,
            scalar_peak_bits=ar.peak_bits, scalar_slots=64,
            reserved_bytes=ar.workspace.lease.count,
            codec_chars=ar.codec.json_chars, codec_bytes=ar.codec.total_bytes,
            whole_record_buffers=ar.codec.whole_record_buffers,
            allocator_or_rss_bound=False, native_origin_bound=False)


def _codec_plan(record, ar):
    """Count the complete already-owned record without formatting any value.

    This structural walk covers all actual keys/literals/identifiers/bindings,
    avoiding a source-size proxy for fixed metadata. It funds escaped text as
    text, exact rationals by their current bit widths, and public floats by the
    fixed binary64 repr bound. Containers/frames were admitted separately.
    """
    component = text = 0

    def count(value):
        nonlocal component, text
        ar.check()
        if type(value) is str:
            text = max(text, len(value))
            return C.json_text_chars(len(value))
        if type(value) is ar.G.mpq:
            shape = ar.shape(value)
            component = max(component, C.decimal_digit_bound(shape.numerator_bits)+1,
                            C.decimal_digit_bound(shape.denominator_bits))
            return C.rational_json_chars(shape.numerator_bits, shape.denominator_bits)
        if type(value) is bool:
            return 5
        if value is None:
            return 4
        if type(value) is int:
            width = C.decimal_digit_bound(value.bit_length())+int(value < 0)
            component = max(component, width)
            return width
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError('Out of range float values are not JSON compliant')
            return 32
        if type(value) in (list, tuple):
            return 2+max(0, len(value)-1)+sum(count(v) for v in value)
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise TypeError('Fixed issue record requires string mapping keys')
            return 2+max(0, len(value)-1)+sum(count(k)+1+count(v) for k, v in value.items())
        raise TypeError('Unexpected fixed issue codec value')

    chars = count(record)+C.RESULT_ID_FIELD_CHARS
    return C.codec_inventory(chars, component, max(text, 64, len('result_id')))


def _issue(ar, old, cap, new, faces, face_ids, source, retained, target, fixed, powers, bindings):
    check = ar.check
    if not math.isfinite(ar.public(target)) or not ar.less(0, target):
        raise ValueError('An independently supplied positive finite absolute residual target is required')
    if any(not ar.less(0, e) for e in new):
        raise ValueError('Positive capacities and corrected enthalpies required')
    cap_public = [ar.public(c) for c in cap]
    if any(not ar.equal(ar.represented(c), exact)
           for c, exact in zip(cap_public, cap, strict=True)):
        raise ValueError('This caloric adapter requires the actual represented binary64 capacities')
    stocks = [ar.public(e) for e in new]
    temperatures = [e/c for e, c in zip(stocks, cap_public, strict=True)]
    exterior = {f for f, (_, j, _) in enumerate(faces) if j is None}
    if (not set(fixed).issubset(exterior) or not set(powers).issubset(exterior)
            or set(fixed) & set(powers) or any(not ar.less(0, t) for t in fixed.values())):
        raise ValueError('Consistent positive Dirichlet or prescribed-energy exterior declarations required')
    for f in exterior-set(fixed):
        if not ar.equal(faces[f][2], powers.get(f, 0)):
            raise ValueError('An exterior prescribed transfer changed or an undeclared face is non-insulated')
    loaded = ar.array(len(old))
    for i, (e, s) in enumerate(zip(old, source, strict=True)):
        ar.put(loaded, i, ar.op('add', e, s))
    for f in exterior-set(fixed):
        i = faces[f][0]
        ar.put(loaded, i, ar.op('subtract', loaded[1][i], faces[f][2]))
    hull = ar.array(len(old)+len(fixed))
    for i, (e, c) in enumerate(zip(loaded[1], cap, strict=True)):
        ar.put(hull, i, ar.op('divide', e, c))
    for i, value in enumerate(fixed.values(), start=len(old)):
        ar.put(hull, i, value)
    bottom = hull[1][0]
    for value in hull[1][1:]:
        bottom = ar.minimum(bottom, value)
    bounds = bottom, ar.maximum(hull[1])
    exact_bounds = all(not ar.less(e, ar.op('multiply', c, bounds[0]))
                       and not ar.less(ar.op('multiply', c, bounds[1]), e)
                       for c, e in zip(cap, new, strict=True))
    public_bounds = all(not ar.less(ar.represented(t), bounds[0])
                        and not ar.less(bounds[1], ar.represented(t)) for t in temperatures)
    if not exact_bounds or not public_bounds:
        raise ValueError('Corrected state leaves its declared loaded/prescribed/Dirichlet convex hull')
    load = ar.array(len(old))
    for i, (e, s) in enumerate(zip(old, source, strict=True)):
        ar.put(load, i, ar.op('add', e, s))
    exact_residual = ar.loaded_residual(new, faces, load[1])
    if any(not ar.equal(a, b) for a, b in zip(exact_residual, retained, strict=True)):
        raise ValueError('Corrected result changed the declared exact per-cell ledger residual')
    residual_max = ar.maximum(ar.absolute(r) for r in exact_residual)
    if ar.less(target, residual_max):
        raise ValueError('Retained exact cell residual exceeds the independently supplied absolute residual target')
    public_stocks = ar.array(len(stocks))
    for i, value in enumerate(stocks):
        ar.put(public_stocks, i, ar.represented(value))
    public_residual = ar.loaded_residual(public_stocks[1], faces, load[1])
    stock_projection = ar.array(len(new))
    for i, (p, e) in enumerate(zip(public_stocks[1], new, strict=True)):
        ar.put(stock_projection, i, ar.op('subtract', p, e))
    if any(not ar.equal(ar.op('add', r, p), measured)
           for r, p, measured in zip(exact_residual, stock_projection[1], public_residual, strict=True)):
        raise ArithmeticError('Stock projection audit does not reconcile')
    # Same exact paired-global sequence: stock-load deltas, exterior amounts,
    # then their sum. Interior denominators never enter this global reduction.
    total = ar.total(ar.op('subtract', energy, b)
                     for energy, b in zip(public_stocks[1], load[1], strict=True))
    outward = ar.G.mpq(0)
    for i, j, amount in faces:
        check()
        if not isinstance(i, int) or not 0 <= i < len(old) or j is not None and (
                not isinstance(j, int) or not 0 <= j < len(old) or j == i):
            raise ValueError('Single shared physical face owners are invalid')
        if j is None:
            outward = ar.op('add', outward, amount)
    global_total = ar.op('add', total, outward)
    boundary_energy = outward if exterior else 0
    source_total = ar.total(source)
    scale = ar.maximum((ar.total(ar.absolute(e) for e in old),
                        ar.total(ar.absolute(e) for e in public_stocks[1]),
                        ar.absolute(source_total), ar.absolute(boundary_energy)))
    relative = ar.op('divide', ar.absolute(global_total), scale)
    if ar.less(ar.G.mpq(1, 10**11), relative):
        raise ValueError('Private booked-ledger global residual exceeds the existing 1e-11 energy gate')
    sources = dict(K._CORE_SOURCES)
    for incoming in (K._SOURCES, _SOURCES, bindings):
        for path, digest in incoming.items():
            check()
            key = str(Path(path).resolve())
            if key in sources and sources[key] != digest:
                raise ValueError('Input source binding conflicts with a core adapter/helper binding')
            sources[key] = digest
    for path, digest in sources.items():
        check()
        if sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('Private adapter input source binding changed')
    # Record scalars must also remain owned if the external caller settles the
    # transient scalar envelope after this numerical producer frame has gone.
    ar.copy((target, residual_max, source_total, boundary_energy, global_total, relative))
    record = dict(schema=K.SCHEMA, private_only=True, production_acceptance=False,
        production_issue_called=False, sources=sources,
        native_origin_bound=False, production_resource_admitted=False,
        method_id=METHOD, state_semantics='Authoritative extensive enthalpy and represented capacity; public T=stored E/C is a caloric point representative, not an exact continuum cell mean.',
        endpoint_face_trace_status=K.TRACE_STATUS,
        transfer_semantics='One exact step-integrated outward energy per supplied physical face; opposite owner receives its exact negative. Not an endpoint constitutive flux.',
        face_geometry_certified_by_adapter=False, face_ids=list(face_ids), physical_faces=faces,
        old_energy=old, capacity=cap, source_energy=source, corrected_energy_exact=new,
        enthalpy_j=stocks, temperature_k=temperatures,
        boundary_temperature={str(f): t for f, t in fixed.items()},
        prescribed_boundary_energy={str(f): q for f, q in powers.items()}, derived_loaded_bounds=bounds,
        exact_bounds_pass=exact_bounds, actual_public_bounds_pass=public_bounds,
        exact_cell_residual=exact_residual, stock_projection_residual=stock_projection[1],
        independently_supplied_absolute_residual_target=target,
        exact_cell_residual_max=residual_max, exact_cell_residual_target_pass=True,
        public_cell_residual=public_residual, projection_audit_reconciles_exactly=True,
        exact_global_source_energy=source_total, exact_global_outward_energy=boundary_energy,
        public_global_relative=ar.native_float(relative), optional_supply=dict(status='NOT_REQUESTED_NOT_AN_ADMISSION_REQUIREMENT'),
        exact_public_global_residual=global_total,
        global_balance_evaluation='exact stock/source/exterior identity after all per-cell and projection checks')
    ar.retained_record = record
    ar.codec = _codec_plan(record, ar)
    ar.containers += ar.codec.total_bytes
    ar.reserve(ar.peak_bits)
    # A declared single step of a metered call, at the codec inventory's own figure.
    with METER.burst(ar.workspace.lease.budgets[0], ar.codec.total_bytes):
        record['result_id'] = sha256(K._encoded(record, check)).hexdigest()
        return K.PrivateNumericalResult(K._encoded(record, check))


def issue(old, cap, new, faces, face_ids, source, retained, target, fixed, powers,
          bindings, check, *, budget):
    """Own sealed native-free numerical result; borrowed values expire on close."""
    def checkpoint():
        if check is not None and check():
            raise CancelledError('Fixed incremental heat issue cancelled')
        return False

    checkpoint()
    G = K.A.exact_library()
    import private_heat_gmp_resources_r1 as R
    n, nf = len(old), len(faces)
    if not n or any(len(v) != n for v in (cap, new, source, retained)) or len(face_ids) != nf:
        raise ValueError('Complete original issue arrays required')
    for values in (old, cap, new, source, retained, (target,),
                   (q for _, _, q in faces), fixed.values(), powers.values()):
        for value in values:
            checkpoint()
            if type(value) is not G.mpq:
                raise TypeError('Exact owned GMP issue inputs required')
    maps = (K._CORE_SOURCES, K._SOURCES, _SOURCES, bindings)
    paths, text, source_size = 0, sum(len(fid) for fid in face_ids), 0
    for mapping in maps:
        for path, digest in mapping.items():
            checkpoint()
            paths += 1
            text += len(path)+len(digest)+len(str(HERE))
            source_size = max(source_size, Path(path).stat().st_size)
    # Additional issue graphs, copied key arrays, metadata strings and source
    # read/hash buffers. Byte counts NEVER become rational bit-width estimates.
    fixed_bytes = 1024*(192+48*n+24*nf+8*paths)+32*text+2*source_size
    workspace = R.OwnedWorkspace(budget, 65536, category='heat-fixed-issue-incremental', cancelled=checkpoint)
    workspace.__enter__()
    owned = O._OwnerWorkspace(workspace)
    try:
        ar = _IssueArithmetic(workspace, G, R, n, nf, 1, checkpoint,
                              extra_fixed_bytes=fixed_bytes)
        owned.arithmetic = ar
        for path, pin in _SOURCES.items():
            checkpoint()
            if sha256(Path(path).read_bytes()).hexdigest() != pin:
                raise ValueError('Fixed issue implementation source changed')
        old, cap, new, source, retained = [ar.copy(values)[1]
                                         for values in (old, cap, new, source, retained)]
        faces = ar.copy(faces)[1]
        fixed, powers = dict(fixed), dict(powers)
        ar.copy(fixed.values())
        ar.copy(powers.values())
        result = _issue(ar, old, cap, new, faces, face_ids, source, retained,
                        target, fixed, powers, bindings)
        # The numerical/encoder producer frame is gone. The complete exact
        # record and sealed immutable bytes stay owned, but bytearray/chunk
        # buffers no longer exist. Exceptions never take this return credit.
        ar.containers -= ar.codec.work_bytes
        ar.settle(ar.retained_record)
        return IssueOwner(result, owned)
    except BaseException:
        owned.__exit__(*sys.exc_info())
        raise
