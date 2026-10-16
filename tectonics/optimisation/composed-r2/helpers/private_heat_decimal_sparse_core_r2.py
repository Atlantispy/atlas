"""Owned MPFR512 successor of the standalone Decimal80 sparse core.

Numerics match the frozen MPFR diagnostic: ascending Decimal matrix columns,
structural RCM, identical partial-pivot MPFR512 factor/solve, exact rational to
Decimal80 conversion, original residual, at most eight corrections and ordered
physical-face transfers. No experiment imports, output files or method origin.

Decimal inventory is derived from typed immutable caller-owned inputs. CSR/RCM
and reordered references are separately counted; MPFR factors/solves have their
own prospective owners. Returned exponents size exact conversion BEFORE mpq is
constructed. One resizable conversion/work owner retains the maximum concurrent
workset, not nine correction generations. The result retains every outer lease
until close. Imports are stdlib-safe; the selected GMP backend gates execution.

These are installed accounting policies, NOT allocator/RSS/whole-heat admission.
Pre-existing input/import/cache baseline, reconstruction, certificate validity,
caller callbacks and downstream codec/ledger/finisher remain caller-owned.
Frozen LU inherits ambient MPFR controls apart from precision. Invocation
therefore requires the original nearest/default exponent/nontrapping controls;
different controls refuse rather than silently changing either the context or
the arithmetic. Status flags and ambient precision do not affect that route.
RCM allocation counts follow scipy1.17.1 _reordering.pyx: A+A.T, order/degree,
two argsort index arrays and one degree scratch array. The existing sparse
ordering policy (64*n+4096) also covers its linear native ordering work:
https://raw.githubusercontent.com/scipy/scipy/v1.17.1/scipy/sparse/csgraph/_reordering.pyx
"""
from decimal import Decimal as D, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

import private_heat_decimal_sparse_core_r1 as P
import private_heat_decimal_inventory_r1 as I
import private_heat_mpfr_lu_resources_r1 as M

RoundedSystem, RoundedFace, OwnedSolve = P.RoundedSystem, P.RoundedFace, P.OwnedSolve
context_signature, boundary_signature = P.context_signature, P.boundary_signature
HERE = Path(__file__).resolve().parent
PINS = {
    'private_heat_decimal_sparse_core_r1.py': 'e07a1230b0dcc586175ea989392d1a82304c5bcf0c79201ab0d4e033cb7ed81f',
    'private_heat_decimal_inventory_r1.py': 'ded95d895acd84dc3d6e858054a7b21d5a58cb45c9f07790b676c2ad926a02b5',
    'private_heat_mpfr_lu_resources_r1.py': '8ba39a3b47991315af8c2a368a6dd9d3fef4b0b906cec71a7aa57a9a9adb7b58',
    'private_heat_rational_decimal_r1.py': 'c21d1ec5163e5c5b18da637823d70a86d76ab6818a87ab2634ade044456df112',
    'private_heat_sparse_resources_r1.py': 'a517c62f73b6fb7528f649457b31de9cd8801c132204c8ab27a91ab8913b4247',
}
_SOURCES = {str(Path(path).resolve()): sha256(Path(path).read_bytes()).hexdigest()
            for path in (__file__, *(HERE/name for name in PINS))}
PRECISION = 512


def _require_mpfr_context(G):
    context = G.get_context()
    expected = {'round': G.RoundToNearest, 'emax': 1073741823, 'emin': -1073741823,
                'subnormalize': False, 'trap_underflow': False, 'trap_overflow': False,
                'trap_inexact': False, 'trap_invalid': False, 'trap_erange': False,
                'trap_divzero': False, 'allow_complex': False, 'rational_division': False}
    if any(getattr(context, name) != value for name, value in expected.items()):
        raise ValueError('Original MPFR nearest/default exponent/nontrapping context required')


def _ordering_inventory(n, k, resources):
    """Payload capacities plus installed Python slots, before CSR construction.

    Three approximate CSR/CSC generations + incoming int64 arrays; structural
    CSR and its transpose conversion; A+A.T output can allocate 2*k entries
    before compression even when canonical support is <=n*n. A second 2*k
    buffer covers addition/copy work. No SuperLU factor policy is used here.
    """
    M._dimensions(n, PRECISION)
    if type(k) is not int or not 0 <= k <= n*n:
        raise ValueError('Canonical bounded support required')
    compressed = resources.compressed_payload(n, k)
    components = (
        ('approximate_generations', 3*compressed+resources.compressed_payload(n, k, index_bytes=8)),
        ('structure_transpose_sum_and_copy', 2*compressed+2*(24*k+4*(n+1))),
        ('structure_input_arrays', resources.compressed_payload(n, k, index_bytes=8)),
        ('rcm_arrays_and_native_work_policy', 64*n+4096),
        ('reordered_rows_pairs_and_indices', I.CONTAINER_UNIT*(n+8)+I.DECIMAL80_SLOT*(k+5*n)),
        ('structure_python_inputs', 3*I.CONTAINER_UNIT+I.DECIMAL80_SLOT*(k+n+1)),
        ('array_headers_and_resource_metadata', 64*I.CONTAINER_UNIT),
    )
    I._sum(*(v for _, v in components))
    return components


def _conversion_shape(value, G):
    """Inspect fixed-size MPFR metadata only, never numerator/denominator.

    x=m*2**(e-p), |m|<2**p. Reduction only decreases widths. A large exponent
    is not a large significand but DOES require a large rational power of two.
    """
    if type(value) is not G.mpfr or not G.is_finite(value) or value.precision != PRECISION:
        raise ValueError('Owned finite MPFR512 solved value required')
    if not value:
        return 1, 1
    exponent = G.get_exp(value)
    return I._count(max(PRECISION, exponent), 'conversion numerator bits'), I._count(max(0, PRECISION-exponent)+1, 'conversion denominator bits')


def _conversion_inventory(nbits, dbits, plan, R):
    """One current exact conversion plus subsequent Decimal work, no global sum.

    Decimal log10 magnitude is bounded by nbits+dbits. Guard/sticky conversion
    adds <=precision+4 decimal places; four bits/decimal place bounds power10.
    Include original rational/getters/abs, powers, scaled operands, quotient,
    remainder and divmod/gcd work via the unchanged native GMP work policy.
    Clamp fallback's Python integers and wide Decimal integer copies are also
    covered. Actual-result exponent extends downstream Decimal alignment and
    formatted result allowances beyond the binary64 input-only inventory.
    """
    bits = I._sum(nbits, dbits)
    power_bits = I._sum(4*(bits+84), 1)
    expression_bits = I._sum(8*bits, 6*power_bits)
    scalar = R.native_workspace_allowance(expression_bits, 32)
    qslots = 8*R.native_slot_allowance(R.RationalShape(nbits+power_bits, dbits+power_bits))
    integers = 8*(24+4*((bits+power_bits+29)//30))
    # Three-factor face expressions, exact float source and up to eight rounded
    # iterate additions; the input plan already covers its own full span.
    digits = I._sum(plan.scalar_work_digit_bound, 3*(2*bits+80+8))
    decimal_work = 12*I.decimal_slot(digits)+4*I.decimal_slot(bits)
    counts = dict(plan.counts)
    exponent_chars = len(str(bits+digits+1))
    result_strings = (2*counts['owner_entries']+counts['cells']+32)*(88+exponent_chars)
    return I._sum(scalar, qslots, integers, decimal_work, result_strings)


def _runtime(cancel):
    G = M._runtime(cancel)
    _require_mpfr_context(G)
    for name, expected in PINS.items():
        if I._sha(HERE/name, cancel) != expected:
            raise ValueError('Reviewed MPFR sparse dependency changed')
    for path, expected in _SOURCES.items():
        if I._sha(Path(path), cancel) != expected:
            raise ValueError('MPFR sparse source changed since import')
    import scipy
    if scipy.__version__ != '1.17.1':
        raise RuntimeError('RCM policy requires reviewed scipy1.17.1')
    return G


def solve_rounded(system, old, capacity, dt, source, boundary, target, *,
                  budget, cancel=None, observe=None, spectrum=False):
    """Return OwnedSolve; immutable binary64 tuples and explicit budget required.

    No manual sparse allowance, physical target substitution or automatic
    budget increase. A staged refusal leaves already allocated inputs owned
    by their caller; failed frames preserve admitted work under native policy.
    """
    P._checkpoint(cancel, observe, 'admission-start')
    if spectrum:
        raise ValueError('Spatial spectrum is not certified by this rounded core')
    M.A.exact_library()
    import private_heat_sparse_resources_r1 as resources
    plan = I.derive(system, old, capacity, dt, source, boundary, target,
                    budget=budget, cancel=cancel)
    components = _ordering_inventory(system.cells, dict(plan.counts)['system_support_bound'], resources)
    needed = I._sum(plan.inventory.total(), *(v for _, v in components))
    P._checkpoint(cancel, observe, 'decimal-inventory-ready')
    workspace = resources.R.OwnedWorkspace(budget, needed,
        category='heat-mpfr-sparse-decimal-private', cancelled=cancel)
    workspace.__enter__()
    try:
        G = _runtime(cancel)
        dynamic = resources.R.OwnedWorkspace(budget, 0,
            category='heat-mpfr-sparse-conversion-private', cancelled=cancel)
        workspace.stack.enter_context(dynamic)
        with localcontext() as context:
            context.prec, context.rounding = 80, ROUND_HALF_EVEN
            P._validate(system, old, capacity, dt, source, boundary, target, context, cancel)
            value = _solve(system, old, capacity, dt, source, boundary, target,
                budget=budget, plan=plan, components=components, workspace=workspace,
                dynamic=dynamic, resources=resources, G=G, cancel=cancel, observe=observe)
        return OwnedSolve(value, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def _solve(system, old, capacity, dt, source, boundary, target, *, budget, plan,
           components, workspace, dynamic, resources, G, cancel, observe):
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import reverse_cuthill_mckee
    import private_heat_rational_decimal_r1 as RD
    began, nc = perf_counter(), len(old)
    P._checkpoint(cancel, observe, 'start')
    op = [dict(row) for row in system.operator]
    wall, rows = system.wall, system.rows
    P._checkpoint(cancel, observe, 'exact-operator-ready')
    c = [D.from_float(float(x)) for x in capacity]
    delta = D.from_float(float(dt))
    rhs = [D.from_float(float(e))+delta*(D.from_float(float(s))-b)
           for e, s, b in zip(old, source, wall, strict=True)]
    dm, data, indices, indptr = [], [], [], [0]
    for i, row in enumerate(op):
        P._checkpoint(cancel, None, 'decimal-row-assembly')
        entries = []
        for j in sorted(set(row) | {i}):
            value = delta*row.get(j, D(0))+(c[i] if i == j else D(0))
            if value:
                entries.append((j, value))
                approximate = float(value)
                if approximate:
                    indices.append(j)
                    data.append(approximate)
        dm.append(entries)
        indptr.append(len(data))
    decimal_nnz = sum(map(len, dm))
    P._checkpoint(cancel, observe, 'decimal-system-ready')
    approximate = csr_matrix((np.asarray(data, dtype=float), np.asarray(indices), np.asarray(indptr)),
                             shape=(nc, nc)).tocsc()
    approximate.sort_indices()
    del data, indices, indptr, wall
    k = dict(plan.counts)['system_support_bound']
    if decimal_nnz > k or approximate.nnz > k:
        raise ValueError('Realised matrix exceeds its prospective support')
    P._checkpoint(cancel, observe, 'before-factorisation')
    structure = csr_matrix((np.ones(decimal_nnz), [j for row in dm for j, _ in row],
                             np.cumsum([0]+[len(row) for row in dm])), shape=(nc, nc))
    permutation = list(map(int, reverse_cuthill_mckee(structure, symmetric_mode=False)))
    inverse = {old: new for new, old in enumerate(permutation)}
    reordered = [[(inverse[j], v) for j, v in dm[i]] for i in permutation]
    _require_mpfr_context(G)
    factor = M.factor(reordered, precision=PRECISION, budget=budget, cancel=cancel, observe=observe)
    workspace.stack.enter_context(factor)
    _require_mpfr_context(G)
    factor_nnz = factor.audit['factor_entries']

    def correction(values):
        _require_mpfr_context(G)
        with M.solve(factor, [values[i] for i in permutation], budget=budget,
                     cancel=cancel, observe=observe) as solved:
            _require_mpfr_context(G)
            ordered = [None]*nc
            for i, value in zip(permutation, solved.value, strict=True):
                P._checkpoint(cancel, None, 'before-exact-solution-conversion')
                nbits, dbits = _conversion_shape(value, G)
                charge = _conversion_inventory(nbits, dbits, plan, resources.R)
                if charge > dynamic.lease.count:
                    dynamic.resize_before_allocation_or_after_drop(charge)
                P._checkpoint(cancel, observe, 'exact-solution-conversion-admitted')
                ordered[i] = RD.dec(G.mpq(value), cancelled=cancel)
            # No borrowed MPFR value survives successful release of its owner.
            del value
            return ordered

    P._checkpoint(cancel, observe, 'after-factorisation')
    u = correction(rhs)
    P._checkpoint(cancel, observe, 'after-initial-solve')
    residual_history = []
    for iteration in range(9):
        P._checkpoint(cancel, observe, 'residual-check-'+str(iteration))
        residual = []
        for row, b in zip(dm, rhs, strict=True):
            P._checkpoint(cancel, None, 'residual-row')
            residual.append(b-sum((a*u[j] for j, a in row), D(0)))
        absolute = max(map(abs, residual))
        residual_history.append(str(absolute))
        if absolute <= D(target):
            break
        if iteration == 8:
            error = ValueError('MPFR512 high predictor failed unchanged algebraic residual target')
            error.numerical_diagnostics = dict(residual_history=residual_history, temperatures=list(map(str, u)),
                target=target, factor_nnz=factor_nnz, worst_cell=max(range(nc), key=lambda i: abs(residual[i])))
            raise error
        P._checkpoint(cancel, observe, 'before-correction-'+str(iteration+1))
        update = correction(residual)
        P._checkpoint(cancel, observe, 'after-correction-'+str(iteration+1))
        u = [t+d for t, d in zip(u, update, strict=True)]
    P._checkpoint(cancel, observe, 'before-face-fluxes')
    fluxes = []
    for row in rows:
        P._checkpoint(cancel, None, 'face-flux-row')
        value = delta*sum((w*(u[key] if kind == 'cell' else D.from_float(float(boundary[key][1])))
                           for (kind, key), w in row.weights), D(0))
        fluxes.append([(i, sign, str(sign*value)) for i, sign in row.owners])
    P._checkpoint(cancel, observe, 'after-face-fluxes')
    P._checkpoint(cancel, observe, 'complete')
    return dict(temperature=np.asarray(list(map(float, u))), energy=[a*b for a, b in zip(c, u, strict=True)],
        residual=str(absolute), refinements=iteration, symmetric_part_minimum_eigenvalue=None,
        minimum_real_eigenvalue=None, raw=fluxes,
        evidence={'absolute_target_decimal': target, 'raw_outward_energy_decimal': fluxes},
        sparse_diagnostics=dict(cells=nc, exact_operator_nnz=system.exact_operator_nnz,
            decimal_system_nnz=decimal_nnz, approximate_system_nnz=approximate.nnz,
            factor_L_plus_U_nnz=factor_nnz, factor_precision_bits=PRECISION,
            residual_history=residual_history, factor_seconds=factor.value['seconds'],
            mpfr_context='NEAREST_DEFAULT_EXPONENT_NONTRAPPING_CHECKED',
            spectrum_computed=False, native_workbudget_admitted=False, seconds=perf_counter()-began),
        coefficient_diagnostics=dict(validity='CALLER_WITNESSED_NOT_REPROVED_BY_NUMERICAL_CORE',
            source_bindings=dict(system.source_bindings), witness_json=system.witness_json,
            exact_sum_then_round_certified_by_core=False),
        resource_diagnostics=dict(decimal_inventory_derived=True,
            decimal_inventory_bytes=plan.inventory.total(), ordering_components=dict(components),
            dynamic_exact_conversion_bytes=dynamic.lease.count, factor_audit=factor.audit,
            retained_solver_lease_bytes=workspace.lease.count+dynamic.lease.count+
                factor._workspace.lease.count+M.METADATA_BYTES,
            source_bindings=dict(_SOURCES), allocator_or_rss_bound=False,
            whole_heat_inventory_certified=False, dependency_import_baseline_admitted_by_core=False,
            high_spatial_coercivity_claimed=False,
            resource_route='PRIVATE_DERIVED_ACCOUNTED_POLICY_NOT_WHOLE_METHOD_ADMISSION'))
