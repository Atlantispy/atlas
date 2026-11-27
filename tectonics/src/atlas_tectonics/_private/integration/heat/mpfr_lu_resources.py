"""Prospective installed-policy admission for the private MPFR LU only.

The frozen factor has ONE combined dictionary matrix, hence at most n*n live
entries, irrespective of pivoting/fill. CPython 3.12 general-key dictionary
tables use the Windows calculate_log2_keysize(3*n) growth, including deletion/reinsertion;
one additional row table covers a resize. A current upper-row snapshot, keys,
pivots and scalar conversion/arithmetic are separate, not n generations.

MPFR objects have one precision-sized significand, not huge rational powers
of two. The installed policy includes the gmpy2 1024-bit reusable precision
class, one allocation-size limb and object header. It is NOT an allocator/RSS
bound: previously oversized cache capacity remains the caller-owned runtime
baseline. MPFR lowering precision need not free capacity; current getsizeof
is only a logical-size audit and does not prove allocated limb capacity.

Inputs/Decimal residuals/RCM/CSR/reordering/codecs and other solver outputs are
already owned by the caller, NOT admitted here. No resource default is raised.
The explicit precision is mandatory. Frozen factor/solve arithmetic is called
unchanged and optional GMP imports occur only after the selected-backend gate.

Source derivation:
https://raw.githubusercontent.com/python/cpython/v3.12.14/Objects/dictobject.c
https://raw.githubusercontent.com/gmpy2/gmpy2/v2.3.2/src/gmpy2.c
https://raw.githubusercontent.com/gmpy2/gmpy2/v2.3.2/src/gmpy2_cache.c
https://www.mpfr.org/mpfr-4.2.2/mpfr.html#Initialization-Functions
"""
from dataclasses import dataclass
from decimal import Decimal
import importlib
import sys
from typing import cast

from atlas_tectonics._private.integration.heat import finish_arithmetic as A
from atlas_tectonics._private.integration.heat import decimal_inventory as D
from atlas_tectonics._private import private_heat_decimal_sparse_core_r1 as P

METADATA_BYTES = D.METADATA_WORK_BYTES
CACHE_PRECISION_CLASS = 1024
MPFR_HEADER_BYTES = 56
POINTER_BYTES = 8


def _size(value):
    return value


def dictionary_bytes(entries):
    """Installed combined-table bound incl. dummy slots, not heap overhead."""
    return _dictionary_bytes(entries)


def _dictionary_bytes(entries):
    if not entries:
        return 64
    # Exact Windows calculate_log2_keysize expression: (minsize|8)-1.
    # Replacing this by max(8,minsize)-1 underbounds tiny churned tables.
    slots = 1 << (((3*entries) | 8)-1).bit_length()
    index_bytes = 1 if slots <= 128 else 2
    # 64-byte dict+GC, 32-byte keys header, signed indices, 24-byte entries.
    return 64+32+index_bytes*slots+24*(2*slots//3)


def list_bytes(length):
    # CPython append allocation: (size + size//8 + 6) rounded to a multiple
    # of four. Add one old pointer generation for an in-progress resize.
    return (56+16*((length+(length >> 3)+6+3)//4*4))


def mpfr_slot(precision):
    bits = max(precision, CACHE_PRECISION_CLASS)
    return (MPFR_HEADER_BYTES+8*((bits+63)//64+1))


@dataclass(frozen=True)
class Envelope:
    n: int
    precision: int
    input_entries: int
    factor_nnz_bound: int
    conversion_bits: int
    components: tuple
    caller_owned_input_bytes: int
    reported_size_is_capacity_bound: bool = False
    allocator_or_rss_bound: bool = False
    whole_solver_admitted: bool = False

    @property
    def total_bytes(self):
        return sum(size for _, size in self.components)


def _runtime(cancel):
    D._check(cancel)
    G = A.exact_library()
    D._runtime(cancel)
    return G


def _decimal_bits(value):
    _, digits, low, high = D.decimal_metadata(value)
    # as_integer_ratio forms integer powers of ten before conversion to mpq.
    # Four bits per decimal digit bounds those exact intermediate integers.
    numerator = (4*max(digits, high+1, 1)+1)
    denominator = (4*max(0, -low)+1)
    return (numerator+denominator)


def _conversion_work(bits, precision, R):
    # One Decimal ratio and mpq conversion at a time: both Python integer
    # parts, temporary powers/gcd operands, exact numerator/denominator and
    # one result. There is no product of widths across unrelated entries.
    expression = (8*bits+8*precision)
    native = R.native_workspace_allowance(expression, 16)
    python_int = 24+4*((bits+29)//30)
    return (native+8*python_int+4*R.native_slot_allowance(R.RationalShape(bits, bits)))


def _factor_envelope(n, precision, entries, bits, input_bytes, R):
    fill = n*n
    slot, table = mpfr_slot(precision), _dictionary_bytes(n)
    # Each dictionary entry keeps its column key. Charge a fresh 32-byte
    # one-limb int per slot even when the immutable keys are actually shared.
    components = (
        ('combined_LU_significands', fill*slot),
        ('retained_row_tables_and_one_resize', (n+1)*table),
        ('retained_column_keys_no_alias_credit', 32*fill),
        ('matrix_row_and_pivot_lists', 2*list_bytes(n)+32*n),
        ('one_upper_row_snapshot', list_bytes(n)+n*(56+slot+32)),
        ('decimal_exact_conversion_and_scalar_work', _conversion_work(bits, precision, R)),
        ('contexts_generators_progress_result', D.CONTAINER_UNIT*32+16*slot),
    )
    result = Envelope(n, precision, entries, fill, bits, components, input_bytes)
    result.total_bytes
    return result


def _metadata(budget, cancel):
    A.exact_library()  # Gate the selected backend before importing the policy.
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    owner = R.OwnedWorkspace(budget, METADATA_BYTES,
        category='heat-mpfr-lu-metadata-private', cancelled=cancel)
    owner.__enter__()
    return R, owner


def derive(rows, *, precision, budget, cancel=None):
    """Owned envelope from already-owned finite Decimal rows, before factor()."""
    D._check(cancel)
    R, workspace = _metadata(budget, cancel)
    try:
        _runtime(cancel)
        n, count, bits, owned = len(rows), 0, 2, sys.getsizeof(rows)
        for row in rows:
            D._check(cancel)
            columns = set()
            owned += sys.getsizeof(row)
            for entry in row:
                D._check(cancel)
                j, value = entry
                columns.add(j)
                bits = max(bits, _decimal_bits(value))
                owned = (owned+sys.getsizeof(entry)+sys.getsizeof(j)+sys.getsizeof(value))
                count += 1
        plan = _factor_envelope(n, precision, count, bits, owned, R)
        return P.OwnedSolve(plan, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


class OwnedFactor(P.OwnedSolve):
    def __init__(self, factors, workspace, envelope, audit):
        super().__init__(factors, workspace)
        self.envelope, self.audit = envelope, audit


def audit_factor(factors, envelope, *, cancel=None):
    """Realised structure/logical-size check; never retroactive admission."""
    A.exact_library()
    n = envelope.n
    entries = reported = table_bytes = 0
    table_limit = slot_limit = None
    for row in factors['rows']:
        D._check(cancel)
        if table_limit is None:
            table_limit = dictionary_bytes(n)
        row_bytes = sys.getsizeof(row)
        table_bytes += row_bytes
        for j, value in row.items():
            D._check(cancel)
            if slot_limit is None:
                slot_limit = mpfr_slot(envelope.precision)
            value_bytes = sys.getsizeof(value)
            entries += 1
            reported += value_bytes
    return dict(factor_entries=entries, structural_bound=envelope.factor_nnz_bound,
        reported_logical_mpfr_bytes=reported, reported_dictionary_bytes=table_bytes,
        reported_bytes_are_not_allocated_limb_capacity=True, admitted_bytes=envelope.total_bytes,
        allocator_or_rss_bound=False, native_heat_admission=False)


def factor(rows, *, precision, budget, cancel=None, observe=None):
    """Owned unchanged factor; explicit budget and precision, no default lift."""
    metadata = derive(rows, precision=precision, budget=budget, cancel=cancel)
    plan = cast(Envelope, metadata.value)
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    try:
        if observe is not None:
            observe('mpfr-lu-inventory-ready')
        workspace = R.OwnedWorkspace(budget, plan.total_bytes,
            category='heat-mpfr-lu-factor-private', cancelled=cancel)
        workspace.__enter__()
    except BaseException:
        metadata.__exit__(*sys.exc_info())
        raise
    workspace.stack.enter_context(metadata)
    try:
        _runtime(cancel)
        method = importlib.import_module('atlas_tectonics._private.integration.heat.mpfr_lu')
        if observe is not None:
            observe('mpfr-lu-workspace-admitted')
        factors = method.factor(rows, precision=precision, cancel=cancel)
        audit = audit_factor(factors, plan, cancel=cancel)
        return OwnedFactor(factors, workspace, plan, audit)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def solve(owner, rhs, *, budget, cancel=None, observe=None):
    """One owned RHS conversion/triangular solve; factor remains separately live."""
    D._check(cancel)
    factors, plan = owner.value, owner.envelope
    R, metadata = _metadata(budget, cancel)
    try:
        _runtime(cancel)
        bits = 2
        for value in rhs:
            D._check(cancel)
            bits = max(bits, _decimal_bits(value))
        slot = mpfr_slot(plan.precision)
        # b is updated in place. Sum uses a generator and one running scalar;
        # neither n dot-product terms nor eight correction generations live.
        needed = (list_bytes(plan.n)+plan.n*slot+16*slot+
            _conversion_work(bits, plan.precision, R)+32*D.CONTAINER_UNIT)
        if observe is not None:
            observe('mpfr-solve-inventory-ready')
        workspace = R.OwnedWorkspace(budget, needed,
            category='heat-mpfr-lu-solve-private', cancelled=cancel)
        workspace.__enter__()
    except BaseException:
        metadata.__exit__(*sys.exc_info())
        raise
    workspace.stack.enter_context(P.OwnedSolve(None, metadata))
    try:
        if observe is not None:
            observe('mpfr-solve-workspace-admitted')
        method = importlib.import_module('atlas_tectonics._private.integration.heat.mpfr_lu')
        values = method.solve(factors, rhs, cancel=cancel)
        A.exact_library()
        return P.OwnedSolve(values, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise
