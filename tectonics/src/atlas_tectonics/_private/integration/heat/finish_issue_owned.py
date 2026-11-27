"""Private exact r3 issuance with fixed-operation, actual-width admission.

The frozen numerical checks, record fields and their order are retained.
Method/source identities describe this successor. No native origin, native
production issue, whole-method admission or allocator/RSS bound is conferred.
The caller supplies and keeps its original exact GMP inputs owned. This owner
also charges its retained copies, all audit arrays and the complete record.
Every native arithmetic operation is admitted before execution. The final
codec envelope is derived from actual final entry widths before formatting;
one canonical encoding supplies the identity preimage and the sealed result.

The result graph and sealed bytes remain owned until normal close. Current
scalar/codec workspace settles only after the producer frame has gone.
Failed frames preserve their workspace and arrays. No static
symbolic issue-growth inventory, solver, geometry or FINISH route runs here.

The process meter covers the growing buffer and final immutable copy. The
identity hashes the canonical record with the result_id field omitted.
"""

from concurrent.futures import CancelledError
from hashlib import sha256
import math
import sys

from atlas_tectonics._private.integration.heat import correction_owned as O
from atlas_tectonics._private.integration.heat import finish_entry_arithmetic as E
from atlas_tectonics._private.integration.heat import finish_codec_inventory as C
from atlas_tectonics._private import private_heat_finish_kernel_r3 as K
from atlas_tectonics._private.integration.heat import process_meter as METER


METHOD = 'private:standalone-conservative-physical-face-finish-r7'


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
        plus, minus = [[e] for e in energy], [[b] for b in load]
        for i, j, amount in faces:
            plus[i].append(amount)
            if j is not None:
                minus[j].append(amount)
        return self.cell_sums(plus, minus)[1]


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

    This structural walk covers all actual keys/literals/identifiers,
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
            numerator_digits = C.decimal_digit_bound(shape.numerator_bits)
            denominator_digits = C.decimal_digit_bound(shape.denominator_bits)
            component = max(component, numerator_digits+1, denominator_digits)
            return C._rational_chars_from_digits(numerator_digits, denominator_digits)
        if type(value) is bool:
            return 5
        if value is None:
            return 4
        if type(value) is int:
            width = C.decimal_digit_bound(value.bit_length())+int(value < 0)
            component = max(component, width)
            return width
        if type(value) is float:
            return 32
        if type(value) in (list, tuple):
            return 2+max(0, len(value)-1)+sum(count(v) for v in value)
        if type(value) is dict:
            return 2+max(0, len(value)-1)+sum(count(k)+1+count(v) for k, v in value.items())
        raise TypeError('Unexpected fixed issue codec value')

    chars = count(record)+C.RESULT_ID_FIELD_CHARS
    return C.codec_inventory(chars, component, max(text, 64, len('result_id')))


def _issue(ar, old, cap, new, faces, face_ids, source, retained, target, fixed, powers, sealed_output):
    check = ar.check
    if not math.isfinite(ar.public(target)) or not ar.less(0, target):
        raise ValueError('An independently supplied positive finite absolute residual target is required')
    cap_public = [ar.public(c) for c in cap]
    if any(not ar.equal(ar.represented(c), exact)
           for c, exact in zip(cap_public, cap, strict=True)):
        raise ValueError('This caloric adapter requires the actual represented binary64 capacities')
    stocks = [ar.public(e) for e in new]
    temperatures = [e/c for e, c in zip(stocks, cap_public, strict=True)]
    exterior = {f for f, (_, j, _) in enumerate(faces) if j is None}
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
    public_bounds = all(not ar.less(t, bounds[0]) and not ar.less(bounds[1], t)
                        for t in map(ar.represented, temperatures))
    load = ar.array(len(old))
    for i, (e, s) in enumerate(zip(old, source, strict=True)):
        ar.put(load, i, ar.op('add', e, s))
    exact_residual = ar.loaded_residual(new, faces, load[1])
    residual_max = ar.maximum(ar.absolute(r) for r in exact_residual)
    public_stocks = ar.array(len(stocks))
    for i, value in enumerate(stocks):
        ar.put(public_stocks, i, ar.represented(value))
    stock_projection = ar.array(len(new))
    for i, (p, e) in enumerate(zip(public_stocks[1], new, strict=True)):
        ar.put(stock_projection, i, ar.op('subtract', p, e))
    # F-2 (step5-6-twice s4 row 8): public - load + faces = (new - load + faces) + (public - new), exactly; the
    # projection step recomputes all three from the record and tests the identity.
    public_residual = ar.array(len(new))
    for i, (r, p) in enumerate(zip(exact_residual, stock_projection[1], strict=True)):
        ar.put(public_residual, i, ar.op('add', r, p))
    public_residual = public_residual[1]
    # Same exact paired-global sequence: stock-load deltas, exterior amounts,
    # then their sum. Interior denominators never enter this global reduction.
    total = ar.total(ar.op('subtract', energy, b)
                     for energy, b in zip(public_stocks[1], load[1], strict=True))
    outward = ar.G.mpq(0)
    for i, j, amount in faces:
        check()
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
    # Record scalars must also remain owned if the external caller settles the
    # transient scalar envelope after this numerical producer frame has gone.
    ar.copy((target, residual_max, source_total, boundary_energy, global_total, relative))
    record = dict(schema=K.SCHEMA, private_only=True, production_acceptance=False,
        production_issue_called=False,
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
        sealed = _seal_record(record, check)
        result = K.PrivateNumericalResult(sealed)
        if sealed_output is not None:
            sealed_output.append(sealed)
        return result


def _seal_record(record, check):
    """Encode the fixed issue schema, whose result_id sorts after capacity."""
    encoder = K._encoder()
    record['result_id'] = '0'*64
    data = bytearray(b'{')
    for index, key in enumerate(sorted(record)):
        check()
        field_start = len(data)
        if index:
            data.extend(b',')
        data.extend(encoder.encode(key).encode('ascii'))
        data.extend(b':')
        for chunk in encoder.iterencode(record[key]):
            check()
            data.extend(chunk.encode('ascii'))
        if key == 'result_id':
            omitted_start, omitted_end = field_start, len(data)
    data.extend(b'}')
    digest = sha256()
    with memoryview(data) as view:
        for first, last in ((0, omitted_start), (omitted_end, len(data))):
            for offset in range(first, last, 1024*1024):
                check()
                digest.update(view[offset:min(last, offset+1024*1024)])
    check()
    result_id = digest.hexdigest()
    data[omitted_end-65:omitted_end-1] = result_id.encode('ascii')
    record['result_id'] = result_id
    return bytes(data)


def issue(old, cap, new, faces, face_ids, source, retained, target, fixed, powers,
          check, *, budget, _sealed_output=None):
    """Own sealed native-free numerical result; borrowed values expire on close."""
    def checkpoint():
        if check is not None and check():
            raise CancelledError('Fixed incremental heat issue cancelled')
        return False

    checkpoint()
    G = K.A.exact_library()
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    n, nf = len(old), len(faces)
    if not n or any(len(v) != n for v in (cap, new, source, retained)) or len(face_ids) != nf:
        raise ValueError('Complete original issue arrays required')
    for values in (old, cap, new, source, retained, (target,),
                   (q for _, _, q in faces), fixed.values(), powers.values()):
        for value in values:
            checkpoint()
    text = sum(len(fid) for fid in face_ids)
    # Additional issue graphs, copied key arrays and metadata strings.
    # Byte counts NEVER become rational bit-width estimates.
    fixed_bytes = 1024*(192+48*n+24*nf)+32*text
    workspace = R.OwnedWorkspace(budget, 65536, category='heat-fixed-issue-incremental', cancelled=checkpoint)
    workspace.__enter__()
    owned = O._OwnerWorkspace(workspace)
    try:
        ar = _IssueArithmetic(workspace, G, R, n, nf, 1, checkpoint,
                              extra_fixed_bytes=fixed_bytes)
        owned.arithmetic = ar
        old, cap, new, source, retained = [ar.copy(values)[1]
                                         for values in (old, cap, new, source, retained)]
        faces = ar.copy(faces)[1]
        fixed, powers = dict(fixed), dict(powers)
        ar.copy(fixed.values())
        ar.copy(powers.values())
        result = _issue(ar, old, cap, new, faces, face_ids, source, retained,
                        target, fixed, powers, _sealed_output)
        # The numerical/encoder producer frame is gone. The complete exact
        # record and sealed immutable bytes stay owned, but bytearray/chunk
        # buffers no longer exist. Exceptions never take this return credit.
        ar.containers -= ar.codec.work_bytes
        ar.settle(ar.retained_record)
        return IssueOwner(result, owned)
    except BaseException:
        owned.__exit__(*sys.exc_info())
        raise
