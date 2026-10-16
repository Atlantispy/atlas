"""Private issuer/projection inventories, not allocator or native acceptance.

Existing sealed inputs remain funded by their original owners. Decode sizing
counts actual JSON string spans and structural tokens without decoding/copying
them. Long decimal rational strings therefore cost their actual lengths, not
one blanket multiplier on the whole file. Rational growth is local to each
cell's actual ordered incidence; only exterior faces enter the global sum.
This is the installed 512-byte scalar/1024-byte container and GMP work policy.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import private_heat_decimal_inventory_r1 as D
import private_heat_decimal_sparse_core_r1 as P
import private_heat_low_ledger_inventory_r1 as L
import private_heat_interval_inventory_r1 as E
import private_heat_finish_arithmetic_r1 as A

UNIT = D.CONTAINER_UNIT


def check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private issuer resource scan cancelled')


def workspace(budget, count, *, cancel=None, category='private-heat-issuer-derived'):
    A.exact_library()
    import private_heat_gmp_resources_r1 as R
    return R.OwnedWorkspace(budget, L._size(count), category=category, cancelled=cancel)


@dataclass(frozen=True)
class JsonShape:
    encoded_bytes: int
    strings: int
    containers: int
    separators: int
    string_storage: int
    largest_string: int
    outside_bytes: int

    @property
    def decode_bytes(self):
        # bytes input -> temporary ASCII Unicode input; strings are separately
        # retained. Scalar/container policy covers object headers and entries.
        return L._size(65536+self.encoded_bytes+self.string_storage+
            UNIT*self.containers+D.DECIMAL80_SLOT*(self.strings+self.separators+1)+4*self.outside_bytes)

    @property
    def stream_codec_bytes(self):
        # One encoder string chunk, UTF8 copy and escape expansion; scanner
        # accounts Unicode strings at four bytes/character where applicable.
        return L._size(65536+8*self.largest_string+96*(self.strings+self.separators)+192*self.containers)


def json_shape(blob, cancel=None):
    """No JSON parse, substring copies or integer coefficient allocation.

    Only canonical ensure_ascii byte records from the fixed producers are in
    scope. Escaped quotes are recognised; unicode escapes conservatively widen
    their own string, not every unrelated rational string in the record.
    JSON.loads remains the syntax validator after prospective admission.
    """
    if type(blob) is not bytes or not blob.isascii():
        raise ValueError('Owned ensure_ascii JSON bytes required')
    strings = containers = separators = storage = largest = outside = 0
    at, size = 0, len(blob)
    while at < size:
        check(cancel)
        begin = blob.find(b'"', at)
        stop = size if begin < 0 else begin
        containers += blob.count(b'{', at, stop)+blob.count(b'[', at, stop)
        separators += blob.count(b',', at, stop)+blob.count(b':', at, stop)
        outside += stop-at
        if begin < 0:
            break
        end = begin+1
        while True:
            end = blob.find(b'"', end)
            if end < 0:
                raise ValueError('Unterminated JSON string in sealed record')
            before = end-1
            while before > begin and blob[before] == 92:
                before -= 1
            if (end-1-before) % 2 == 0:
                break
            end += 1
        length = end-begin-1
        width = 4 if blob.find(b'\\u', begin+1, end) >= 0 else 1
        storage += width*length
        largest = max(largest, width*length)
        strings += 1
        at = end+1
    return JsonShape(size, strings, containers, separators, storage, largest, outside)


def decoded(blob, *, budget, cancel=None):
    with workspace(budget, D.METADATA_WORK_BYTES, cancel=cancel,
                   category='private-heat-json-metadata'):
        shape = json_shape(blob, cancel)
    owned = workspace(budget, shape.decode_bytes+shape.stream_codec_bytes, cancel=cancel,
                      category='private-heat-json-view')
    owned.__enter__()
    try:
        value = json.loads(blob)
        check(cancel)
        return P.OwnedSolve(value, owned)
    except BaseException:
        import sys
        owned.__exit__(*sys.exc_info())
        raise


def stream_hash(value, cancel=None):
    """Same canonical JSON bytes as native/frozen private hash, one chunk live.

    Caller holds the codec inventory. No semantic keys, digits or order change.
    """
    digest = sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    for chunk in encoder.iterencode(value):
        check(cancel)
        digest.update(chunk.encode('utf-8'))
    return digest.hexdigest()


def source_hash(path, cancel=None):
    digest = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(65536):
            check(cancel)
            digest.update(block)
    return digest.hexdigest()


def verified_private(result, method, *, budget, cancel=None):
    """Exactly one funded parse, same sealed result hash and source checks."""
    if type(result) is not method.PrivateNumericalResult:
        raise TypeError('The fixed current finisher result class is required')
    blob = result._sealed
    owner = decoded(blob, budget=budget, cancel=cancel)
    try:
        record = owner.value
        identity = record.pop('result_id')
        if stream_hash(record, cancel) != identity:
            raise ValueError('Private corrected result identity changed')
        if any(source_hash(path, cancel) != digest for path, digest in record['sources'].items()):
            raise ValueError('Private corrected result source binding changed')
        record['result_id'] = identity
        if result._sealed is not blob:
            raise ValueError('Private corrected result changed while decoding')
        return owner
    except BaseException:
        import sys
        owner.__exit__(*sys.exc_info())
        raise


def pair_shape(pair, *, hexadecimal=False):
    if type(pair) not in (tuple, list) or len(pair) != 2 or any(type(v) is not str or not v for v in pair):
        raise ValueError('Owned exact rational component strings required')
    # Validation still belongs to the unchanged decoder. Four bits per input
    # character bounds either base16 or base10, including harmless prefixes.
    numerator, denominator = (L._size(4*len(v)+1) for v in pair)
    dyadic = pair[1] in ('1', '0x1')
    return E.Shape(numerator, denominator if not dyadic else 1, dyadic)


def target_bytes(value, *, budget, cancel=None):
    with workspace(budget, D.METADATA_WORK_BYTES, cancel=cancel):
        if type(value) is float:
            value = Decimal.from_float(value)
        _, digits, low, high = D._target_metadata(value, cancel)
        bits = L._size(4*(digits+max(0, -low)+max(0, high)+1)+2)
        import private_heat_gmp_resources_r1 as R
        ar = L.RationalGrowth(A.exact_library(), R, cancel)
        ar.expression_bits = 8*bits
        return L._size(ar.scalar_work(rational_slots=12)+4*D.decimal_slot(digits))


def projection_plan(record, geometry, old, cap, source, dt, target, *, budget, cancel=None):
    """Before exact decode/arithmetic; views and numerical producer stay owned."""
    n, nf = len(geometry._cells), len(geometry._face_ids)
    with workspace(budget, D.METADATA_WORK_BYTES+UNIT*16*(n+nf+1), cancel=cancel,
                   category='private-heat-projection-metadata'):
        G = A.exact_library()
        import private_heat_gmp_resources_r1 as R
        ar = L.RationalGrowth(G, R, cancel)
        def compare(left, right):
            # Rational equality/order forms two integer cross-products, not
            # a rational subtraction/result denominator or a gcd.
            check(cancel)
            bits = (left.numerator+left.denominator+right.numerator+right.denominator
                    +left.numerator+right.denominator+right.numerator+left.denominator)
            ar.expression_bits = max(ar.expression_bits, bits)
        old_s, cap_s, src_s = [[ar.binary(float(v)) for v in values] for values in (old, cap, source)]
        delta = ar.binary(float(dt))
        src_s = [ar.op('multiply', delta, s) for s in src_s]
        target_s = ar.q(target)
        # A malformed but hash-consistent private record must also be admitted
        # before its original-input equality check can refuse it. The old
        # checker decodes one complete compared array at a time.
        compared_slots = 0
        for expected, name in ((old_s, 'old_energy'), (cap_s, 'capacity'), (src_s, 'source_energy')):
            encoded = [pair_shape(value) for value in record[name]]
            if len(encoded) != n:
                raise ValueError('Complete original input coverage required before sizing')
            compared_slots = max(compared_slots, sum(ar.slot(value) for value in encoded))
            for left, right in zip(expected, encoded, strict=True):
                compare(left, right)
                ar.expression_bits = max(ar.expression_bits, 4*(right.numerator+right.denominator))
        compare(target_s, pair_shape(record['independently_supplied_absolute_residual_target']))
        new = [pair_shape(v) for v in record['corrected_energy_exact']]
        out, face_s, outward = [L.ZERO]*n, [], L.ZERO
        if len(record['physical_faces']) != nf or len(new) != n:
            raise ValueError('Complete original cell/face coverage required for sizing')
        for (i, j, pair), linked in zip(record['physical_faces'], geometry._incidence, strict=True):
            check(cancel)
            expected = (linked[0][0], linked[1][0] if len(linked) == 2 else None)
            if type(i) is not int or j is not None and type(j) is not int or (i, j) != expected:
                raise ValueError('Original face incidence required before projection sizing')
            value = pair_shape(pair)
            face_s.append(value)
            for cell, _ in linked:
                out[cell] = ar.op('add', out[cell], value)
            if j is None:
                outward = ar.op('add', outward, value)
        retained, projected, public = [], [], []
        for e, before, q, s in zip(new, old_s, out, src_s, strict=True):
            retained.append(ar.op('subtract', ar.op('add', ar.op('subtract', e, before), q), s))
            projected.append(ar.op('subtract', L.PUBLIC_BINARY64, e))
            public.append(ar.op('subtract', ar.op('add', ar.op('subtract', L.PUBLIC_BINARY64, before), q), s))
        for values, name in ((retained, 'exact_cell_residual'), (projected, 'stock_projection_residual'),
                             (public, 'public_cell_residual')):
            encoded_shapes = [pair_shape(value) for value in record[name]]
            compared_slots = max(compared_slots, sum(ar.slot(value) for value in encoded_shapes))
            for actual, encoded in zip(values, encoded_shapes, strict=True):
                compare(actual, encoded)
        for a, b, c in zip(retained, projected, public, strict=True):
            compare(ar.op('add', a, b), c)
            compare(a, target_s)
        ar.total(src_s)  # Binary64 sources*dt are proved dyadic.
        vectors = old_s+cap_s+src_s+new+out+retained+projected+public+face_s
        slots = sum(ar.slot(v) for v in vectors)
        # Max(abs(retained)) comparisons must also be funded, even if all
        # independently compared against target below. No global denominator.
        largest = E.Shape(max(v.numerator for v in retained), max(v.denominator for v in retained), False)
        for value in retained:
            compare(largest, value)
        for key in ('boundary_temperature', 'prescribed_boundary_energy'):
            boundary_slots = 0
            for value in record[key].values():
                shape = pair_shape(value)
                boundary_slots += ar.slot(shape)
                compare(shape, ar.op('multiply', L.PUBLIC_BINARY64, L.PUBLIC_BINARY64))
            compared_slots += boundary_slots
        components = (
            ('exact_live_arrays_and_current_comparison_copy', 2*slots),
            ('encoded_input_and_boundary_comparison_copies', compared_slots),
            ('local_scalar_conversion_and_compare', ar.scalar_work(rational_slots=16)),
            ('public_arrays_and_container_work', UNIT*(20*n+4*nf+64)),
        )
        total = L._size(sum(v for _, v in components))
        return dict(bytes=total, components=dict(components),
                    local_incidence_only=True, allocator_or_rss_bound=False, native_admission=False)


def projection_output_plan(groups, *, budget, cancel=None):
    """Actual reduced outputs, inspected inside the admitted arithmetic frame.

    This is a second prospective stage: no strings exist yet. There is no
    formula-bound denominator product assigned to an output known to be zero.
    Caller retains this lease through projection/issuer metadata construction.
    """
    with workspace(budget, D.METADATA_WORK_BYTES, cancel=cancel):
        import private_heat_gmp_resources_r1 as R
        ar = L.RationalGrowth(A.exact_library(), R, cancel)
        chars = count = 0
        for group in groups:
            for value in group:
                check(cancel)
                shape = ar.q(value)
                chars += R.hex_pair_char_bound(R.RationalShape(shape.numerator, shape.denominator))+4
                count += 1
                ar.expression_bits = max(ar.expression_bits, 4*(shape.numerator+shape.denominator))
        components = dict(output_hex_strings_and_pairs=L._size(chars+UNIT*(count+8)),
            output_stream_codec=L._size(3*chars+UNIT*(count+32)),
            actual_output_conversion_work=ar.scalar_work(rational_slots=8))
        return dict(bytes=L._size(sum(components.values())), components=components,
                    actual_reduced_output_widths=True)


def owner_projection_bytes(metric, graph, transport, component_count, *, budget, cancel=None):
    """Original _q/_project gathering and binary64 mass-sum*cp, no new maths."""
    n = len(metric['cells'])
    if type(component_count) is not int or component_count <= 0:
        raise ValueError('Original positive component count required')
    with workspace(budget, D.METADATA_WORK_BYTES+UNIT*(n+len(graph['cells'])+16), cancel=cancel):
        G = A.exact_library()
        import private_heat_gmp_resources_r1 as R
        ar = L.RationalGrowth(G, R, cancel)
        largest = 1
        for values in transport['exact_stocks'].values():
            for pair in values:
                check(cancel)
                shape = pair_shape(pair, hexadecimal=True)
                largest = max(largest, shape.numerator+shape.denominator)
        for row in graph['cells']:
            shape = pair_shape(row['end_volume_m3'], hexadecimal=True)
            largest = max(largest, shape.numerator+shape.denominator)
        for key in ('start_time_s', 'end_time_s'):
            shape = pair_shape(graph[key], hexadecimal=True)
            largest = max(largest, shape.numerator+shape.denominator)
        ar.expression_bits = 8*largest
        return L._size(ar.scalar_work(rational_slots=12)+UNIT*(12*n+4*len(graph['cells'])+component_count+64))
