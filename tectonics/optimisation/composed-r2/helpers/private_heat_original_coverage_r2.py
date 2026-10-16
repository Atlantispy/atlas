"""Sequential owned coverage inspection; the pinned R1 decisions are unchanged.

The full mesh dies before graph decoding. Its selected JSON fields survive only
under a separately admitted compact owner. Actual string lengths, integer widths
and rational input widths enter admission; 512 bytes is never an unbounded scalar
allowance. These are conservative ledger inventories, not allocator/RSS bounds.

The returned detached primitive report is caller-owned diagnostic output, as in
R1. Its long-lived allocation is outside this scientific-work ownership proof.
It contains no graph, mesh, owner or traceback aliases.
"""
from hashlib import sha256 as _sha256
from pathlib import Path as _Path
import sys as _sys

_ROOT = _Path(__file__).resolve().parent
_PINS = {
    'private_heat_original_coverage_r1.py':
        '90113110a3c7a37c70ea16df6de6166d61ed728d2bc974f6e2e3dbd49409c688',
    'private_heat_issuer_resources_r1.py':
        'f46aefd332c97c5e7fd6ddd9de3a0783d7608d3820a9b440483bf0fee36d7318',
}
_SELF_SHA = _sha256(_Path(__file__).read_bytes()).hexdigest()


def source_bindings():
    pins = {str(_ROOT / name): expected for name, expected in _PINS.items()}
    pins[str(_Path(__file__).resolve())] = _SELF_SHA
    for path, expected in pins.items():
        if _sha256(_Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Coverage successor source changed: ' + path)
    return pins


source_bindings()
_PRIOR_BYTES = (_ROOT / 'private_heat_original_coverage_r1.py').read_bytes()
if _sha256(_PRIOR_BYTES).hexdigest() != _PINS['private_heat_original_coverage_r1.py']:
    raise ValueError('Pinned coverage source changed while loading')
# Additive exact copy: physical_coverage, save_operands and cache helpers retain
# their original code/defaults. Only inspect_preadvance is replaced below.
exec(compile(_PRIOR_BYTES, str(_ROOT / 'private_heat_original_coverage_r1.py'), 'exec'), globals())
physical_coverage = globals()['physical_coverage']
save_operands = globals()['save_operands']

_ENDPOINTS = ('funding_id', 'support_id', 'grid_id', 'trajectory_id', 'time_s')
_UNIT = 1024


def _value_bytes(value, check):
    """Prospective copied JSON storage, including arbitrarily long primitives."""
    check()
    if type(value) is str:
        return 512 + 4 * (len(value) + 1)
    if type(value) is int:
        return 512 + _sys.int_info.sizeof_digit * (
            (value.bit_length() + _sys.int_info.bits_per_digit - 1) // _sys.int_info.bits_per_digit)
    if value is None or type(value) in (bool, float):
        return 512
    if type(value) is list:
        return _UNIT + 64 * len(value) + sum(_value_bytes(v, check) for v in value)
    if type(value) is dict:
        return _UNIT + 256 * len(value) + sum(
            _value_bytes(k, check) + _value_bytes(v, check) for k, v in value.items())
    raise TypeError('Decoded JSON primitives required for compact coverage')


def _copy_value(value, check):
    check()
    if type(value) is str:
        # Do not leave report strings aliasing a decoded graph's storage.
        return (value + '\0')[:-1]
    if type(value) is list:
        return [_copy_value(v, check) for v in value]
    if type(value) is dict:
        return {_copy_value(k, check): _copy_value(v, check) for k, v in value.items()}
    if value is None or type(value) in (bool, int, float):
        return value
    raise TypeError('Decoded JSON primitives required for compact coverage')


def _projection_bytes(mesh, check):
    count = 32 * _UNIT
    for key in _ENDPOINTS:
        if key in mesh:
            count += _value_bytes(mesh[key], check)
    rule = mesh.get('booked_cell_rule', {})
    if type(rule) is dict:
        if 'closed_graph_id' in rule:
            count += _value_bytes(rule['closed_graph_id'], check)
    else:
        count += _value_bytes(rule, check)
    for rows, keys in (('cells', ('cell_id', 'logical_cell_id')), ('faces', ('face_id',))):
        count += _UNIT + 64 * len(mesh[rows])
        for row in mesh[rows]:
            check()
            count += _UNIT + 256 * len(keys)
            for key in keys:
                if key in row:
                    count += _value_bytes(row[key], check)
    count += _value_bytes(mesh['required_thermal_boundary_faces'], check)
    # Both copy generation and its largest temporary Unicode generation fit.
    return 2 * count


def _project_mesh(mesh, check):
    result = {key: _copy_value(mesh[key], check) for key in _ENDPOINTS if key in mesh}
    rule = mesh.get('booked_cell_rule', {})
    result['booked_cell_rule'] = (
        {key: _copy_value(rule[key], check) for key in ('closed_graph_id',) if key in rule}
        if type(rule) is dict else _copy_value(rule, check))
    for rows, keys in (('cells', ('cell_id', 'logical_cell_id')), ('faces', ('face_id',))):
        result[rows] = [{key: _copy_value(row[key], check) for key in keys if key in row}
                        for row in mesh[rows]]
    result['required_thermal_boundary_faces'] = _copy_value(mesh['required_thermal_boundary_faces'], check)
    return result


def _compact_mesh(blob, resources, budget, cancel, observe_counts):
    check = lambda: resources.check(cancel)
    with resources.decoded(blob, budget=budget, cancel=cancel) as decoded:
        if observe_counts is not None:
            observe_counts(dict(cells=len(decoded.value['cells']), faces=len(decoded.value['faces'])))
        # The observer runs before compact admission and before graph decoding.
        with resources.workspace(budget, 65536 + 4096 * _sys.getrecursionlimit(), cancel=cancel,
                                 category='private-original-coverage-sizing'):
            count = _projection_bytes(decoded.value, check)
        workspace = resources.workspace(budget, count, cancel=cancel,
                                        category='private-original-coverage-compact')
        workspace.__enter__()
        try:
            value = _project_mesh(decoded.value, check)
            owner = resources.P.OwnedSolve(value, workspace)
            del value
        except BaseException:
            workspace.__exit__(*_sys.exc_info())
            raise
    # decoded.value has expired before an owner can escape this function.
    return owner


def _coverage_bytes(mesh, graph, resources, cancel):
    """Fund the unchanged lists/sets, retained Fractions and local comparison work."""
    import private_heat_gmp_resources_r1 as native_resources
    arithmetic = resources.L.RationalGrowth(resources.A.exact_library(), native_resources, cancel)
    slots = largest_encoded = 0
    for row in graph['cells']:
        resources.check(cancel)
        pair = row['end_volume_m3']
        shape = resources.pair_shape(pair, hexadecimal=True)
        slots += arithmetic.slot(shape)
        largest_encoded = max(largest_encoded, sum(len(v) for v in pair))
        # Covers int conversion/gcd, canonical hex conversion and cross-products
        # in Fraction min/order comparisons, without a global denominator sum.
        arithmetic.expression_bits = max(arithmetic.expression_bits,
                                          8 * (shape.numerator + shape.denominator))
    containers = _UNIT * (16 * len(graph['cells']) + 8 * len(mesh['cells'])
                          + 8 * len(mesh['faces']) + 8 * len(mesh['required_thermal_boundary_faces']) + 128)
    return containers + 2 * slots + arithmetic.scalar_work(rational_slots=16) + 16 * largest_encoded


def check_saved(mesh_blob, graph_blob, graph_id, resources, budget, cancel=None, observe_counts=None):
    """Check immutable saved operands without issuing native objects or writing.

    A report proves the existing physical-coverage predicates only. It does not
    prove that saved bytes are a current live owner, an accepted endpoint, or
    historically the same mesh. The caller must bind their source/provenance.
    """
    source_bindings()
    if type(mesh_blob) is not bytes or type(graph_blob) is not bytes:
        raise TypeError('Immutable saved mesh and graph bytes required')
    if observe_counts is not None and not callable(observe_counts):
        raise TypeError('Optional count observer must be callable')
    from atlas_tectonics.integration_mimetic_heat import _q
    with _compact_mesh(mesh_blob, resources, budget, cancel, observe_counts) as compact:
        with resources.decoded(graph_blob, budget=budget, cancel=cancel) as decoded:
            with resources.workspace(budget, 65536 + 4096 * _sys.getrecursionlimit(), cancel=cancel,
                                     category='private-original-coverage-sizing'):
                count = _coverage_bytes(compact.value, decoded.value, resources, cancel)
            with resources.workspace(budget, count, cancel=cancel,
                                     category='private-original-coverage-check'):
                def decode(pair):
                    resources.check(cancel)
                    return _q(pair)
                result = physical_coverage(compact.value, decoded.value, graph_id, decode)
                result['minimum_positive_booked_volume_m3'] = _copy_value(
                    result['minimum_positive_booked_volume_m3'], lambda: resources.check(cancel))
                resources.check(cancel)
    return result


def inspect_preadvance(mesh, graph, bounds, resources, budget, cancel, artifacts, record, save):
    source_bindings()
    record['preadvance_operands'] = save_operands(artifacts, mesh=mesh._json,
        closed_graph=graph._json, bounds=bounds._json)
    save()
    def observe_counts(counts):
        record['observed_preadvance_counts'] = counts
        save()
    result = check_saved(mesh._json, graph._json, graph.geometry_id, resources, budget,
                         cancel=cancel, observe_counts=observe_counts)
    record['current_physical_coverage'] = result
    save()
    return result
