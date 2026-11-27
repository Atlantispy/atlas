"""Plan40B explicit public LOW source pin; no historical receipt is rebound.

Two-stage prospective LOW ledger inventory; accounted policy, not RSS.

The original prepared geometry and caller arrays are already owned. Stage one
covers the unchanged binary64-to-exact load/bounds and singleton preparation.
Stage two inspects the sparse owner's actual Decimal energies (or the already
computed constant lower bound) BEFORE exact energy/temperature/face/residual
construction. Each cell accumulates only its incident faces in physical order.
Only the actual exterior faces enter the separate paired-global audit bound.

Shape bits are mathematical bounds, including virtual dyadic denominators.
CPython Fraction/int storage plus the existing GMP recycled-slot/work policy
are charged simultaneously, without alias or early-release credit. These are
accounting conventions, not proofs of GMP scratch, allocator capacity or RSS.
No reconstruction, sparse factor, runtime-import or native origin is admitted.
Imports are stdlib-safe; the selected GMP backend is gated only at invocation.
"""

from concurrent.futures import CancelledError
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import sys
from typing import Any, cast

from atlas_tectonics._private.integration.heat import decimal_inventory as D
from atlas_tectonics._private import private_heat_decimal_sparse_core_r1 as P
from atlas_tectonics._private.integration.heat import finish_arithmetic as A
from atlas_tectonics._private.integration.heat import endpoint_assembly as M
from atlas_tectonics._private.integration.heat import endpoint_assembly_inventory as I

CONTAINER_UNIT = D.CONTAINER_UNIT
ZERO = I.Shape(1, 1, True)
# Every finite binary64 lies on the 2**-1074 lattice and has magnitude <2**1024.
PUBLIC_BINARY64 = I.Shape(2098, 1075, True)
# L1: a Fraction's fixed __slots__ instance size, which slot() used to measure on every call.
_FRACTION_ZERO_SIZE = sys.getsizeof(Fraction(0))


def _py_int(bits):
    # L1: slot()'s per-call lambda, unchanged, defined once.
    return sys.getsizeof(0)+sys.int_info.sizeof_digit*((bits+sys.int_info.bits_per_digit-1)//sys.int_info.bits_per_digit)


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('LOW exact-ledger inventory cancelled')


def _size(value):
    return value


@dataclass(frozen=True)
class InventoryPlan:
    inventory: M.DiagnosticInventory
    stage: str
    components: tuple
    counts: tuple
    cell_residual_bits: tuple = ()
    face_transfer_bits: tuple = ()
    global_audit_bits: tuple = ()
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    whole_method_admission: bool = False


def _footprint(values, gmp, cancel):
    """Typed owned objects only; no rational getters or numerical copies."""
    import numpy as np
    total = count = largest = 0
    def visit(value, depth=0):
        nonlocal total, count, largest
        _check(cancel)
        size = sys.getsizeof(value)
        total, count, largest = (total+size), (count+1), max(largest, size)
        if type(value) is dict:
            for key, item in value.items():
                visit(key, depth+1)
                visit(item, depth+1)
        elif type(value) in (tuple, list):
            for item in value:
                visit(item, depth+1)
        elif type(value) is Fraction:
            visit(value.numerator, depth+1)
            visit(value.denominator, depth+1)
        elif type(value) is np.ndarray:
            # Count backing payload again even when getsizeof already includes it.
            total = (total+value.nbytes)
            count = (count+value.size)
        elif type(value) not in (str, int, float, bool, type(None), Decimal, gmp.mpq, gmp.mpz, np.float64):
            raise ValueError('Unsupported LOW owned input object: '+type(value).__name__)
    for value in values:
        visit(value)
    return total, count, largest


class RationalGrowth:
    """Reusable metadata arithmetic, NOT an automatically admitted workset.

    Caller must hold its own metadata/getter lease and supply the selected GMP
    library and reviewed resource policy. q/op/choice/slot can size other exact
    algorithms, but their live generations must be independently inventoried.
    divisor_power_two is a caller proof about the actual positive divisor;
    an arbitrary numerator bit upper bound is not that proof.
    """
    def __init__(self, gmp, resources, cancel):
        self.gmp, self.resources, self.cancel = gmp, resources, cancel
        self.expression_bits = 1

    def q(self, value):
        _check(self.cancel)
        if type(value) is Decimal:
            _, digits, low, high = D.decimal_metadata(value)
            # 10**d < 2**(4*d). No as_tuple/str/as_integer_ratio allocation.
            if value.is_zero():
                return ZERO
            if low >= 0:
                return I.Shape((4*(high+1)+1), 1, True)
            return I.Shape((4*max(digits, high+1, 1)+1), (-4*low+1), False)
        if type(value) is float:
            n, d = value.as_integer_ratio()
        elif type(value) is Fraction or type(value) is self.gmp.mpq:
            n, d = value.numerator, value.denominator
        elif type(value) is int:
            n, d = value, 1
        else:
            raise ValueError('Exact owned rational or finite Decimal required')
        return I.Shape(max(1, n.bit_length()), d.bit_length(), d.bit_count() == 1)

    def binary(self, value):
        return self.q(float(value))

    def op(self, operation, left, right, *, divisor_power_two=False):
        _check(self.cancel)
        # L1: R.RationalShape validation and R.operation_growth, written out (gmp_resources_r1 5ada7b86).
        a, b = left.numerator, left.denominator
        c, d = right.numerator, right.denominator
        if operation in ('add', 'subtract'):
            ad = 0 if a == 0 or d == 0 else a+d
            cb = 0 if c == 0 or b == 0 else c+b
            numerator = max(ad, cb)+(1 if ad and cb else 0)
            denominator = b+d
            widths = ad+cb+numerator+denominator
        elif operation == 'multiply':
            numerator, denominator = (0 if a == 0 or c == 0 else a+c), b+d
            widths = numerator+denominator
        elif operation == 'divide':
            numerator, denominator = (0 if a == 0 or d == 0 else a+d), b+c
            widths = numerator+denominator
        else:
            raise ValueError('operation must be add, subtract, multiply or divide')
        total = (a+b)+(c+d)+widths+(numerator+denominator)
        self.expression_bits = max(self.expression_bits, total)
        if operation in ('add', 'subtract'):
            return I.add_shape(left, right)
        if operation == 'multiply':
            return I.multiply_shape(left, right)
        if left.dyadic and divisor_power_two:
            # right is an ACTUAL positive power of two, not a numerator upper bound.
            exponent = left.denominator-1+right.numerator-right.denominator
            return I.Shape(left.numerator+max(0, -exponent), max(0, exponent)+1, True)
        return I.Shape(numerator, denominator, False)

    def total(self, values):
        result = ZERO
        for value in values:
            result = self.op('add', result, value)
        return result

    def choice(self, values):
        # A maximum/minimum selects ONE value; it does not sum denominators.
        denominator = max(s.denominator for s in values)
        dyadic = all(s.dyadic for s in values)
        numerator = max(s.numerator+(denominator-s.denominator if dyadic else 0) for s in values)
        result = I.Shape(numerator, denominator, dyadic)
        for value in values:
            self.op('subtract', result, value)  # exact comparison products
        return result

    def slot(self, value):
        # All possible Fraction and mpq generations charged, not alias-deduced.
        # L1: the same reads of value and self.resources, in the same order and number, as the
        # original; Fraction(0)'s size is a process constant and py_int is defined once.
        python = _FRACTION_ZERO_SIZE+_py_int(value.numerator)+_py_int(value.denominator)
        R = self.resources
        n, d = value.numerator, value.denominator
        if type(n) is int and type(d) is int and n >= 0 and d >= 1:
            # RationalShape(n, d) cannot refuse these widths. The policy check still runs on
            # every call; then native_slot_allowance's formula, literally.
            R._installed_policy()
            native = 160+8*(max(64, (n+63)//64+2)+max(64, (d+63)//64+2))
        else:
            native = R.native_slot_allowance(R.RationalShape(n, d))
        return (python+native)

    def scalar_work(self, *, rational_slots=12):
        bits = self.expression_bits
        return (self.resources.native_workspace_allowance(bits, rational_slots)
                     +rational_slots*self.slot(I.Shape(bits, bits, False)))


def _base(prepared, old, capacity, dt, source, target, ar):
    n = prepared.get('cells')
    e0, cap, src = [[ar.binary(v) for v in values] for values in (old, capacity, source)]
    delta = ar.binary(dt)
    power_two = []
    for value in capacity:
        numerator, _ = float(value).as_integer_ratio()
        power_two.append(numerator.bit_count() == 1)
    _, digits, low, high = D._target_metadata(target, ar.cancel)
    target_shape = I.Shape((4*max(digits, high+1, 1)+1), (4*max(0, -low)+1), low >= 0)
    load = [ar.op('add', e, ar.op('multiply', delta, s)) for e, s in zip(e0, src, strict=True)]
    loaded = load[:]
    boundary = prepared['boundary']
    face_ids = prepared.get('face_ids')
    owner_count = 0
    for fid, row in zip(face_ids, prepared['rows'], strict=True):
        _check(ar.cancel)
        owner_count += len(row['owners'])
        for i, sign in row['owners']:
            if type(i) is not int or not 0 <= i < n or type(sign) is not int or sign not in (-1, 1):
                raise ValueError('Original integer owner index and orientation required')
        if row['kind'] == 'power':
            i = row['owners'][0][0]
            loaded[i] = ar.op('subtract', loaded[i], ar.op('multiply', delta, ar.q(boundary[fid][1])))
    loaded_temperature = [ar.op('divide', b, c, divisor_power_two=p)
        for b, c, p in zip(loaded, cap, power_two, strict=True)]
    walls = [ar.q(value) for kind, value in boundary.values() if kind == 'temperature']
    bounds = ar.choice(loaded_temperature+walls)
    return dict(n=n, e0=e0, cap=cap, src=src, delta=delta, target=target_shape,
        load=load, loaded=loaded, loaded_temperature=loaded_temperature, walls=walls,
        bounds=bounds, power_two=power_two, owners=owner_count)


def _plan(prepared, old, capacity, dt, source, target, returned, constant_lower,
          *, stage, footprint, object_count, ar):
    base = cast('dict[str, Any]', _base(prepared, old, capacity, dt, source, target, ar))
    n, rows = base['n'], prepared['rows']
    count = len(rows)
    bslots = sum(ar.slot(s) for name in ('e0', 'cap', 'src', 'load', 'loaded', 'loaded_temperature', 'walls')
                 for s in base[name])+sum(ar.slot(base[name]) for name in ('delta', 'target', 'bounds'))
    if stage == 'initial':
        # singleton_rows: row dict + key list/set + bounds dict/pairs; the exact
        # values are already owned but are charged again per copied occurrence.
        singleton_slots = sum(ar.slot(ar.q(weight))*2 for row in rows for _, weight in row['weights'])
        units = 32+18*n+8*count+5*base['owners']+object_count
        components = (('initial_exact_arrays', bslots), ('singleton_value_copies', singleton_slots),
            ('containers_and_binary_snapshots', CONTAINER_UNIT*units),
            ('scalar_arithmetic_and_conversions', ar.scalar_work()),
            ('target_parse_codec', 4*sys.getsizeof(target)))
        result_bytes = CONTAINER_UNIT*(24+len(components))
        cells = faces = global_bits = ()
    else:
        if returned is None:
            lower = ar.q(constant_lower)
            energy = [ar.op('multiply', c, lower) for c in base['cap']]
        else:
            values = returned.get('energy')
            energy = list(map(ar.q, values))
        temperature = [ar.op('divide', e, c, divisor_power_two=p)
            for e, c, p in zip(energy, base['cap'], base['power_two'], strict=True)]
        residual = [ar.op('subtract', e, b) for e, b in zip(energy, base['load'], strict=True)]
        public_residual = [ar.op('subtract', PUBLIC_BINARY64, b) for b in base['load']]
        transfers, exterior = [], []
        face_slots = 0
        for row in rows:
            _check(ar.cancel)
            i = row['owners'][0][0]
            kind, fid = row['kind'], row['face_id']
            if kind == 'interior':
                j = row['owners'][1][0]
                difference = ar.op('subtract', temperature[i], temperature[j])
            elif kind == 'temperature':
                j = None
                difference = ar.op('subtract', temperature[i], ar.q(prepared['boundary'][fid][1]))
            elif kind == 'power':
                j, difference = None, None
            else:
                raise ValueError('Original LOW face kind required')
            amount = (ar.op('multiply', ar.op('multiply', base['delta'], ar.q(row['conductance'])), difference)
                if difference is not None else ar.op('multiply', base['delta'], ar.q(prepared['boundary'][fid][1])))
            transfers.append(amount)
            # faces, raw owner entries, repeated evidence raw; no alias credit.
            face_slots += (1+2*len(row['owners']))*ar.slot(amount)
            residual[i] = ar.op('add', residual[i], amount)
            public_residual[i] = ar.op('add', public_residual[i], amount)
            if j is None:
                exterior.append(amount)
            else:
                residual[j] = ar.op('subtract', residual[j], amount)
                public_residual[j] = ar.op('subtract', public_residual[j], amount)
        for exact, public, r in zip(temperature, public_residual, residual, strict=True):
            ar.op('subtract', exact, base['bounds'])
            ar.op('subtract', PUBLIC_BINARY64, base['bounds'])
            ar.op('subtract', r, base['target'])
            ar.op('subtract', public, base['target'])
        source_total = ar.op('multiply', base['delta'], ar.total(base['src']))
        # Match paired_global_balance: validate interiors, but NEVER accumulate
        # their denominators. Stocks/source are binary64 dyadics by construction.
        stock_delta = ar.total(ar.op('subtract', PUBLIC_BINARY64, b) for b in base['load'])
        outward = ar.total(exterior)
        total = ar.op('add', stock_delta, outward)
        scale = ar.choice([ar.total(base['e0']), ar.total(PUBLIC_BINARY64 for _ in range(n)), source_total, outward])
        relative = ar.op('divide', total, scale)
        ar.op('subtract', relative, ar.q(Fraction(1, 10**11)))
        global_shapes = (source_total, stock_delta, outward, total, scale, relative)
        exact_slots = sum(ar.slot(s) for s in energy+temperature+residual+public_residual)+face_slots
        # Independent public-E and public-T Fraction generations, evidence energy
        # list, converted global operands, and exact min/max/result scalars.
        public_slots = 4*n*ar.slot(PUBLIC_BINARY64)+sum(ar.slot(s) for s in energy)+sum(ar.slot(s)*2 for s in global_shapes)
        units = 64+30*n+9*count+6*base['owners']
        components = (('initial_exact_arrays_retained', bslots), ('exact_ledger_and_residuals', exact_slots),
            ('public_projection_and_global_audit', public_slots),
            ('containers_and_result_views', CONTAINER_UNIT*units),
            ('scalar_arithmetic_and_conversions', ar.scalar_work()), ('public_numpy_payloads', 16*n))
        # Result is in-memory rationals, not a JSON/hex serialization. Only target
        # strings/binding metadata are copied here; no unexecuted codec is claimed.
        result_bytes = exact_slots+public_slots+CONTAINER_UNIT*(64+20*n+8*count+6*base['owners'])+4*sys.getsizeof(target)
        cells = tuple((s.numerator, s.denominator) for s in residual)
        faces = tuple((s.numerator, s.denominator) for s in transfers)
        global_bits = tuple((s.numerator, s.denominator) for s in global_shapes)
    work = sum(value for _, value in components)
    inventory = M.DiagnosticInventory(max(1, footprint), work, result_bytes,
        'Derived staged LOW incident-face rational growth plus installed Fraction/GMP/container policy; '
        'not allocator/RSS, reconstruction or whole-method admission.')
    inventory.total()
    return InventoryPlan(inventory, stage, components,
        (('cells', n), ('faces', count), ('owners', base['owners']), ('exterior_faces', sum(len(row['owners']) == 1 for row in rows))),
        cells, faces, global_bits)


def _admit(prepared, old, capacity, dt, source, target, *, budget,
           returned=None, constant_lower=None, stage, cancel):
    _check(cancel)
    gmp = A.exact_library()
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    values = (prepared, old, capacity, dt, source, target, returned, constant_lower)
    footprint, objects, largest = _footprint(values, gmp, cancel)
    # Only scalar sizes/counts above; all rational getters, shape lists/maps and
    # Decimal/target metadata are admitted below.
    scan_bytes = (R.native_workspace_allowance(8*max(1, largest), objects)
                      +CONTAINER_UNIT*(objects+1))
    workspace = R.OwnedWorkspace(budget, scan_bytes, category='heat-low-ledger-inventory-metadata', cancelled=cancel)
    workspace.__enter__()
    try:
        D._runtime(cancel)
        ar = RationalGrowth(gmp, R, cancel)
        plan = _plan(prepared, old, capacity, dt, source, target, returned,
            constant_lower, stage=stage, footprint=footprint, object_count=objects, ar=ar)
        _check(cancel)
        return P.OwnedSolve(plan, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def admit_initial(prepared, old, capacity, dt, source, target, *, budget, cancel=None):
    """Owned plan for the initial LOW stage; keep until its work lease exists."""
    return _admit(prepared, old, capacity, dt, source, target, budget=budget, stage='initial', cancel=cancel)


def admit_ledger(prepared, old, capacity, dt, source, target, *, budget,
                 returned=None, constant_lower=None, cancel=None):
    """Owned second-stage plan; reserve its inventory BEFORE E/C or ledger work."""
    return _admit(prepared, old, capacity, dt, source, target,
        budget=budget, returned=returned, constant_lower=constant_lower, stage='ledger', cancel=cancel)
