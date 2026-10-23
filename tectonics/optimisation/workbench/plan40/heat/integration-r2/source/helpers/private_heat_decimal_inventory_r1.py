"""Plan40B explicit public Decimal policy receiving binding.

The policy is the actually imported selected module, pinned to its public bytes.
All runtime gates and accounting formulae are retained. This new binding does
not authenticate historical private runtime identities.

Prospective accounted inventory for the Decimal sparse core.

This is an installed-runtime ACCOUNTING POLICY, not an allocator/RSS bound.
It derives every variable term from typed, already-owned inputs and the live
generations of that core. No factor arrays/fill are included: keep the existing
sparse envelope. No exact GMP, MPFR or interval-assembly admission is implied.

CPython 3.12.14 dec_sizeof includes dynamic mpdecimal coefficient allocation;
its CONFIG_64 limbs hold 19 decimal digits. Hence 19*(owned_size//8) safely
overbounds owned coefficient digits, including inline storage. This uses size
only to inspect ALREADY allocated objects, never as a prospective allocator cap.
No as_tuple/string conversion of a Decimal occurs during metadata inspection.
References: https://github.com/python/cpython/blob/v3.12.14/Modules/_decimal/_decimal.c
and Modules/_decimal/libmpdec/mpdecimal.h in the same pinned source release.

The native N.workspace_bytes policy supplies 512 bytes/Decimal80 value+slot,
1024 bytes/container traversal unit and 1 MiB fixed workspace. Wider operands
are conservatively charged in complete 80-digit blocks. Explicit scalar work
also covers unreduced products and full decimal alignment spans; this is a
policy extension, NOT a proof of internal libmpdec allocator/scratch capacity.
Inputs may be large if their derived accounted envelope can be admitted.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from decimal import Decimal as D, ROUND_HALF_EVEN
import decimal
from hashlib import sha256
import math
from pathlib import Path
import struct
import sys

import private_heat_decimal_sparse_core_r1 as P
from atlas_tectonics import integration_mimetic_newton as _POLICY

HERE = Path(__file__).resolve().parent
CORE_SHA256 = 'e07a1230b0dcc586175ea989392d1a82304c5bcf0c79201ab0d4e033cb7ed81f'
POLICY_SHA256 = 'ef0f3b48ec1c992f2887f53b21c054d69439e58be2d3d445069162f29a51a0f0'
# Existing low-solver source closures consume this public path constant too.
POLICY_PATH = Path(_POLICY.__file__).resolve()
DECIMAL80_SLOT = 512
CONTAINER_UNIT = 1024
METADATA_WORK_BYTES = 1 << 20
FLOAT_DIGITS = 1075
GENERATED_DIGITS = 80
MAX_DECIMAL_EXPONENT = 999999999999999999


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private Decimal inventory cancelled')


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name+' must be a nonnegative integer')
    if value > sys.maxsize:
        raise OverflowError(name+' exceeds addressable accounting')
    return value


def _sum(*values):
    result = sum(values)
    return _count(result, 'combined storage/count')


def decimal_slot(digits):
    """Native Decimal80 value/slot policy, scaled in whole precision blocks."""
    _count(digits, 'digits')
    return _count(DECIMAL80_SLOT*max(1, (digits+79)//80), 'Decimal policy slot')


def _sha(path, cancel):
    digest = sha256()
    with path.open('rb') as stream:
        while block := stream.read(65536):
            _check(cancel)
            digest.update(block)
    return digest.hexdigest()


def _runtime(cancel):
    if (sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 12, 14)
            or decimal.__libmpdec_version__ != '2.5.1' or struct.calcsize('P') != 8
            or sys.float_info.mant_dig != 53 or sys.float_info.max_exp != 1024
            or sys.float_info.min_exp != -1021 or D.__basicsize__ != 104):
        raise RuntimeError('Decimal inventory requires the reviewed CPython/libmpdec/binary64 runtime')
    from atlas_tectonics import integration_mimetic_newton as POLICY
    if Path(POLICY.__file__).name != 'integration_mimetic_newton.py':
        raise RuntimeError('Unexpected Decimal accounting policy module')
    if (_sha(Path(P.__file__), cancel) != CORE_SHA256
            or _sha(Path(POLICY.__file__).resolve(), cancel) != POLICY_SHA256):
        raise RuntimeError('Sparse core or native Decimal accounting policy source changed')


def decimal_metadata(value):
    """Constant-size inspection of an already-owned exact Decimal object."""
    if type(value) is not D or not value.is_finite():
        raise ValueError('Finite exact Decimal object required')
    size = sys.getsizeof(value)
    digits = _count(19*(size//8), 'owned Decimal digit upper bound')
    adjusted = value.adjusted()
    low = adjusted-digits+1
    if abs(adjusted) > 2*MAX_DECIMAL_EXPONENT or abs(low) > sys.maxsize:
        raise OverflowError('Decimal exponent metadata outside reviewed signed range')
    return size, digits, low, adjusted


def _target_metadata(value, cancel):
    if type(value) is D:
        result = decimal_metadata(value)
        if value <= 0:
            raise ValueError('Positive original target required')
        return result
    if type(value) is not str or not value:
        raise ValueError('Original target must be a finite positive Decimal or canonical decimal string')
    # Parse only bounded counters; never construct a giant coefficient integer,
    # Decimal, regex group, sliced string or digit tuple during inspection.
    start = int(value[0] == '+')
    digits = fractional = exponent = 0
    dot = exp_mode = exp_sign_seen = nonzero = False
    exponent_sign, exponent_digits = 1, 0
    for at in range(start, len(value)):
        if at % 256 == 0:
            _check(cancel)
        char = value[at]
        if not exp_mode:
            if '0' <= char <= '9':
                digits += 1
                fractional += int(dot)
                nonzero |= char != '0'
            elif char == '.' and not dot:
                dot = True
            elif char in ('e', 'E') and digits:
                exp_mode = True
            else:
                raise ValueError('Unsupported target representation; no target value is substituted')
        elif char in ('+', '-') and not exp_sign_seen and not exponent_digits:
            exp_sign_seen = True
            exponent_sign = -1 if char == '-' else 1
        elif '0' <= char <= '9':
            exponent_digits += 1
            exponent = exponent*10+ord(char)-48
            if exponent > MAX_DECIMAL_EXPONENT:
                raise OverflowError('Target exponent exceeds reviewed Decimal representation')
        else:
            raise ValueError('Malformed target exponent')
    if not digits or not nonzero or (exp_mode and not exponent_digits):
        raise ValueError('Finite positive original target required')
    low = exponent_sign*exponent-fractional
    return sys.getsizeof(value), _count(digits, 'target digits'), low, low+digits-1


@dataclass(frozen=True)
class InventoryPlan:
    inventory: P.CallerInventory
    components: tuple
    counts: tuple
    max_owned_digit_bound: int
    scalar_work_digit_bound: int
    face_decimal_string_chars: int
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    whole_method_admission: bool = False


class _Scan:
    """Fixed-size scalar metadata, not a tree copy or deduplication cache."""
    def __init__(self):
        self.bytes = 0
        self.metadata_bytes = 0
        self.digits = FLOAT_DIGITS
        self.low, self.high = -1074, 308

    def owned(self, value, *, metadata=False):
        size = sys.getsizeof(value)
        self.bytes = _sum(self.bytes, size)
        if metadata:
            self.metadata_bytes = _sum(self.metadata_bytes, size)

    def dec(self, value):
        size, digits, low, high = decimal_metadata(value)
        self.bytes = _sum(self.bytes, size)
        self.digits = max(self.digits, digits)
        self.low, self.high = min(self.low, low), max(self.high, high)

    def string(self, value):
        if type(value) is not str:
            raise ValueError('Exact string metadata required')
        self.owned(value, metadata=True)

    def pair(self, value):
        if type(value) is not tuple or len(value) != 2:
            raise ValueError('Immutable pairs required')
        self.owned(value)


def derive(system, old, capacity, dt, source, boundary, target, *, budget, cancel=None):
    """Derive P.CallerInventory without matrix/list/Decimal-digit construction.

    Only exact P.RoundedSystem/Face, nested tuples and exact Decimal fields;
    stock/capacity/source are tuples of exact finite Python binary64 floats.
    Boundary is a plain dict of string -> (temperature/power, finite float).
    Arbitrary __float__, lazy iterators and mutable array representations refuse;
    callers may form admitted immutable snapshots without changing their values.
    Pre-existing inputs and imports are caller-owned. A fixed native-policy
    metadata lease covers this streaming inspection/source check; no large
    result is constructed, only scalar counts and a bounded plan record.
    Observe/cancel callback allocations remain caller-owned.
    """
    _check(cancel)
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.integration_spatial_transport import _workspace
    if type(budget) is not WorkBudget:
        raise TypeError('Native caller WorkBudget required for metadata inspection')
    with _workspace(budget, METADATA_WORK_BYTES, category='heat-decimal-inventory-metadata'):
        _runtime(cancel)
        return _derive(system, old, capacity, dt, source, boundary, target, cancel)


def _derive(system, old, capacity, dt, source, boundary, target, cancel):
    if type(system) is not P.RoundedSystem or type(system.cells) is not int or system.cells <= 0:
        raise ValueError('Typed immutable positive-cell RoundedSystem required')
    scan = _Scan()
    scan.owned(system)
    scan.owned(system.__dict__)
    n = _count(system.cells, 'cells')
    scan.owned(n)
    if (type(system.context_signature) is not tuple or len(system.context_signature) != 5
            or type(system.context_signature[0]) is not int or type(system.context_signature[1]) is not str
            or system.context_signature[0:2] != (80, ROUND_HALF_EVEN)):
        raise ValueError('Decimal80 HALF_EVEN context metadata required')
    prec, rounding, emin, emax, clamp = system.context_signature
    if (type(emin) is not int or type(emax) is not int or type(clamp) is not int
            or not -MAX_DECIMAL_EXPONENT <= emin <= 0 <= emax <= MAX_DECIMAL_EXPONENT
            or clamp not in (0, 1)):
        raise ValueError('Supported Decimal exponent/clamp metadata required')
    scan.owned(system.context_signature)
    for item in (prec, rounding, emin, emax, clamp):
        scan.owned(item)
    for values in (old, capacity, source):
        if type(values) is not tuple or len(values) != n:
            raise ValueError('Original ordered arrays must be immutable binary64 tuples')
        scan.owned(values)
        for value in values:
            _check(cancel)
            if type(value) is not float or not math.isfinite(value):
                raise ValueError('Exact finite binary64 float inputs required')
            scan.owned(value)
    if any(value <= 0 for value in capacity) or type(dt) is not float or not math.isfinite(dt) or dt <= 0:
        raise ValueError('Original positive finite capacities/timestep required')
    scan.owned(dt)
    if type(boundary) is not dict:
        raise ValueError('Plain already-owned boundary dictionary required')
    scan.owned(boundary)
    for key, entry in boundary.items():
        _check(cancel)
        scan.string(key)
        scan.pair(entry)
        kind, value = entry
        scan.string(kind)
        if kind not in ('temperature', 'power') or type(value) is not float or not math.isfinite(value):
            raise ValueError('Declared boundary kind and exact finite binary64 value required')
        scan.owned(value)
    if type(system.boundary_signature) is not tuple or len(system.boundary_signature) != len(boundary):
        raise ValueError('Complete immutable numerical boundary signature required')
    scan.owned(system.boundary_signature)
    previous = None
    for entry in system.boundary_signature:
        _check(cancel)
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError('Immutable boundary signature triples required')
        scan.owned(entry)
        key, kind, value = entry
        scan.string(key)
        scan.string(kind)
        scan.dec(value)
        if (previous is not None and key <= previous or key not in boundary
                or boundary[key][0] != kind or value != D.from_float(boundary[key][1])):
            raise ValueError('Canonical boundary signature changed from numerical inputs')
        previous = key
    if type(system.operator) is not tuple or len(system.operator) != n or type(system.wall) is not tuple or len(system.wall) != n:
        raise ValueError('Complete immutable operator/wall required')
    scan.owned(system.operator)
    scan.owned(system.wall)
    nnz = max_row = 0
    for row, wall in zip(system.operator, system.wall, strict=True):
        _check(cancel)
        scan.dec(wall)
        if type(row) is not tuple:
            raise ValueError('Immutable operator rows required')
        scan.owned(row)
        previous_column = -1
        max_row = max(max_row, len(row)+1)
        for entry in row:
            _check(cancel)
            scan.pair(entry)
            column, value = entry
            if type(column) is not int or not previous_column < column < n:
                raise ValueError('Ascending unique bounded operator columns required')
            previous_column = column
            scan.owned(column)
            scan.dec(value)
            nnz += 1
    if type(system.exact_operator_nnz) is not int or system.exact_operator_nnz != nnz:
        raise ValueError('Operator count metadata mismatch')
    scan.owned(nnz)
    if type(system.rows) is not tuple:
        raise ValueError('Immutable physical face rows required')
    scan.owned(system.rows)
    faces, weights, owners, max_weights = len(system.rows), 0, 0, 0
    for row in system.rows:
        _check(cancel)
        if type(row) is not P.RoundedFace or type(row.owners) is not tuple or type(row.weights) is not tuple:
            raise ValueError('Typed immutable face/owner/observation rows required')
        scan.owned(row)
        scan.owned(row.__dict__)
        scan.string(row.face_id)
        scan.owned(row.owners)
        scan.owned(row.weights)
        if len(row.owners) not in (1, 2):
            raise ValueError('One or two face owners required')
        for owner in row.owners:
            scan.pair(owner)
            i, sign = owner
            if type(i) is not int or not 0 <= i < n or type(sign) is not int or sign not in (-1, 1):
                raise ValueError('Typed in-range owner and integer orientation required')
            scan.owned(i)
            scan.owned(sign)
        owners += len(row.owners)
        max_weights = max(max_weights, len(row.weights))
        for entry in row.weights:
            _check(cancel)
            scan.pair(entry)
            key, value = entry
            scan.pair(key)
            kind, index = key
            scan.string(kind)
            if kind == 'cell':
                if type(index) is not int or not 0 <= index < n:
                    raise ValueError('Bounded cell observation index required')
            elif (kind not in ('wall', 'power') or type(index) is not str or index not in boundary
                    or boundary[index][0] != ('temperature' if kind == 'wall' else 'power')):
                raise ValueError('Matching declared wall/power observation required')
            scan.owned(index)
            scan.dec(value)
            weights += 1
    if type(system.source_bindings) is not tuple or not system.source_bindings:
        raise ValueError('Immutable nonempty source bindings required')
    scan.owned(system.source_bindings)
    for binding in system.source_bindings:
        _check(cancel)
        scan.pair(binding)
        for value in binding:
            scan.string(value)
    scan.string(system.witness_json)
    size, target_digits, target_low, target_high = _target_metadata(target, cancel)
    scan.bytes = _sum(scan.bytes, size)
    scan.digits = max(scan.digits, target_digits)
    scan.low, scan.high = min(scan.low, target_low), max(scan.high, target_high)

    # No Decimal division occurs in this core. The largest expression degree
    # is three (dt*weight*u), with exact binary64 conversion <=1075 digits.
    # Rounded sums cannot lower their inputs' minimum coefficient exponent.
    # Allow one carry per summed term and per each of eight iterate updates.
    additions = max(n, max_row, max_weights)+8+4
    low, high = 3*min(scan.low, -1074), 3*max(scan.high, 308)+additions
    scratch_digits = _count(max(2*scan.digits, high-low+1, FLOAT_DIGITS+80), 'scalar arithmetic digits')
    chars = _count(80+8+len(str(max(abs(low), abs(high)))), 'returned Decimal string chars')
    k = min(n*n, nnz+n)
    float_slot, generated_slot = decimal_slot(FLOAT_DIGITS), decimal_slot(80)

    # Existing native slot/container units, with explicit live object counts.
    # Summing phases is conservative; aliases are not credited as free memory.
    components = (
        ('operator_dict_copy', CONTAINER_UNIT*(n+1)+generated_slot*nnz),
        ('decimal_matrix_rows', CONTAINER_UNIT*(n+1)+generated_slot*k),
        ('python_sparse_lists', 3*CONTAINER_UNIT+generated_slot*(2*k+n+1)),
        ('sorted_column_temporaries', 3*CONTAINER_UNIT+generated_slot*3*max_row),
        ('capacity_dt_and_initial_iterate', float_slot*(2*n+1)),
        ('rhs_residual_and_new_iterate', generated_slot*3*n),
        ('rhs_float_list_and_headers', CONTAINER_UNIT*6+generated_slot*n),
        ('boundary_signature_validation', CONTAINER_UNIT*3+(float_slot+generated_slot)*len(boundary)),
        ('validation_sets', CONTAINER_UNIT*4+generated_slot*(faces+max_weights+2)),
        # Twelve scalar slots cover both operands, product/alignment result,
        # accumulator/new accumulator, binary conversion, target conversion,
        # absolute residual, sign product, formatter operand and spare return.
        ('scalar_arithmetic_and_conversion', 12*decimal_slot(scratch_digits)),
        ('target_parse_copy', 4*sys.getsizeof(target)+decimal_slot(target_digits)),
        ('fixed_native_policy_work', METADATA_WORK_BYTES),
    )
    work_bytes = _sum(*(value for _, value in components))
    # Two raw ledger generations conservatively charge the shared evidence/raw
    # reference twice. Strings are ASCII; 8 chars covers sign/dot/E/exponent sign
    # and the general-format fixed-point leading-zero case.
    ledger = (CONTAINER_UNIT*(1+faces)+owners*(generated_slot+sys.getsizeof('')+chars))
    result_bytes = _sum(generated_slot*n, 8*n, 2*ledger,
        CONTAINER_UNIT*12, generated_slot*(64+len(system.source_bindings)),
        2*scan.metadata_bytes, sys.getsizeof(target), CONTAINER_UNIT)
    counts = (('cells', n), ('operator_nnz', nnz), ('system_support_bound', k), ('faces', faces),
              ('face_weights', weights), ('owner_entries', owners), ('max_row', max_row),
              ('max_face_weights', max_weights), ('refinement_live_generations', 2))
    # Plan + inventory object/dict pairs and their two outer tuples (six units),
    # followed by every component/count pair. No uncharged returned plan tree.
    input_bytes = _sum(scan.bytes, CONTAINER_UNIT*(6+len(components)+len(counts)))
    inventory = P.CallerInventory(input_bytes, work_bytes, result_bytes,
        'Derived CPython3.12.14/libmpdec2.5.1 Decimal80 accounted policy; '
        'typed immutable metadata, exact binary64 conversions <=1075 digits, '
        'single refinement workset, retained results; not allocator/RSS or whole-GMP admission.')
    inventory.total()
    _check(cancel)
    return InventoryPlan(inventory, components, counts,
        scan.digits, scratch_digits, chars)
