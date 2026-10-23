"""Plan40B explicit public spatial-transport source binding.

Private fixed-route LOW join; no native issue, saved solve or probe import.

The exact LOW geometry rows are caller-owned, already prepared from issued
geometry. Exact singleton intervals feed the standalone assembler, then the
fixed Decimal-80 sparse core. L5's exact E/C ledger, bounds, target, constant
path and global gate are unchanged. No high-order/material accuracy is claimed.

Exact-ledger inventory remains a private caller declaration. Exact endpoint
assembly and sparse Decimal inventories are derived from the owned operands;
these accounted policies are NOT a whole-method or OS-RSS guarantee.
The returned OwnedSolve keeps the LOW workspace, assembly and sparse owners
charged together. Borrowed values
must not outlive that owner; failures retain leases with error AND traceback.
Module import is stdlib/private-stdlib only; selected exact backend and optional
numerical/runtime dependencies are loaded only at invocation.
"""
from concurrent.futures import CancelledError
from decimal import Decimal as D, localcontext
from fractions import Fraction as Q
import hashlib
import math
from pathlib import Path
import sys

import private_heat_low_geometry_kernel_r1 as L
import private_heat_interval_assembly_kernel_r1 as M
import private_heat_decimal_sparse_core_r1 as P
import private_heat_decimal_inventory_r1 as INVENTORY
import private_heat_interval_inventory_r1 as ENDPOINT_INVENTORY
import private_heat_finish_arithmetic_r1 as A
from atlas_tectonics import integration_spatial_transport as SPATIAL_TRANSPORT

PUBLIC_GLOBAL_GATE = Q(1, 10**11)
HERE = Path(__file__).resolve().parent
_SOURCE_PATHS = (__file__, L.__file__, M.__file__, P.__file__, A.__file__,
                 INVENTORY.__file__, INVENTORY.POLICY_PATH,
                 ENDPOINT_INVENTORY.__file__,
                 SPATIAL_TRANSPORT.__file__,
                 HERE/'private_heat_gmp_resources_r1.py', HERE/'private_heat_sparse_resources_r1.py')
_SOURCES = {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in _SOURCE_PATHS}


def _cancel(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Sparse-backed linear low predictor cancelled')


def _observe(observe, phase):
    if observe is not None:
        observe(phase)


def _verify_sources(bindings, cancel):
    for path, digest in bindings.items():
        _cancel(cancel)
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('Standalone LOW source binding changed; no repin')


def _bindings(incoming, cancel):
    values = dict(_SOURCES)
    for path, digest in (incoming or {}).items():
        key = str(Path(path).resolve())
        if key in values and values[key] != digest:
            raise ValueError('LOW source binding conflicts with fixed internal implementation')
        values[key] = digest
    _verify_sources(values, cancel)
    return values


def _residual(energy, faces, load):
    values = [e-b for e, b in zip(energy, load, strict=True)]
    for i, j, amount in faces:
        values[i] += amount
        if j is not None:
            values[j] -= amount
    return values


def singleton_rows(prepared, *, cancel=None):
    """Retain exact coefficient and observation order, without rounding."""
    rows = []
    if list(prepared['face_ids']) != [row['face_id'] for row in prepared['rows']]:
        raise ValueError('Original LOW face ordering changed')
    for row in prepared['rows']:
        _cancel(cancel)
        keys = [tuple(key) for key, _ in row['weights']]
        if len(set(keys)) != len(keys):
            raise ValueError('LOW observation keys must be unique before singleton assembly')
        rows.append(dict(face_id=row['face_id'], owners=row['owners'], ordered_keys=keys,
            bounds={tuple(key): (value, value) for key, value in row['weights']}))
    return rows


def existing_target(prepared, old, capacity, dt, source, reference):
    """Existing X stock-scaled target, without executing its nonlinear solve.

    This reproduces X._run's Decimal-80 arithmetic and its hybrid unknown count
    (cells plus faces not prescribed-temperature). It requires positive old
    stocks, as that inherited target policy does. A caller with an already
    established target should pass that target straight to solve instead.
    """
    with localcontext() as context:
        context.prec = 80
        decimal = lambda value: D.from_float(float(value))
        e0, cap, src = [list(map(decimal, values)) for values in (old, capacity, source)]
        delta, ref = decimal(dt), decimal(reference)
        load = [e+delta*s for e, s in zip(e0, src, strict=True)]
        for row in prepared['rows']:
            if row['kind'] == 'power':
                load[row['owners'][0][0]] -= delta*decimal(prepared['boundary'][row['face_id']][1])
        rhs_max = max(abs(b-c*ref) for b, c in zip(load, cap, strict=True))
        free = prepared['cells']+len(prepared['rows'])-sum(row['kind'] == 'temperature' for row in prepared['rows'])
        stock_target = D('1e-11')*min(e0)/free
        target = min(D('1e-11')*rhs_max, stock_target) if rhs_max else stock_target
        if target <= 0:
            raise ValueError('Existing stock-scaled target requires strictly positive old stocks')
        return str(target)


def solve(prepared, old, capacity, dt, source, *, target, budget,
          ledger_inventory,
          source_bindings=None, cancel=None, observe=None):
    """Return P.OwnedSolve; value expires on close, with full retained charge.

    No arbitrary solver callback or already-solved state is accepted. Inputs
    and import/runtime baseline need caller admission before this operation.
    The ledger inventory must cover all live prepared/input/converted/result
    Fraction/GMP/JSON/Python arrays, not just the output. Assembly and sparse
    allowances are charged in addition and retained until the outer owner dies.
    Binary64 tuple snapshots are built inside the admitted ledger allowance;
    their exact values then determine the derived sparse Decimal inventory.
    """
    _cancel(cancel)
    if type(ledger_inventory) is not M.DiagnosticInventory:
        raise ValueError('Explicit LOW exact-ledger diagnostic inventory required')
    amount = ledger_inventory.total()
    A.exact_library()  # Gate before importing the GMP-dependent resource helper.
    import private_heat_gmp_resources_r1 as resources
    workspace = resources.OwnedWorkspace(budget, amount, category='heat-low-joined-private', cancelled=cancel)
    workspace.__enter__()
    try:
        bindings = _bindings(source_bindings, cancel)
        _observe(observe, 'low-workspace-admitted')
        value = _solve(prepared, old, capacity, dt, source, target=target, budget=budget,
            workspace=workspace,
            bindings=bindings, cancel=cancel, observe=observe)
        return P.OwnedSolve(value, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def _solve(prepared, old, capacity, dt, source, *, target, budget, workspace,
           bindings, cancel, observe):
    """r1 result contract with sparse backend and a cooperative cancel callback.

    Numerical output fields retain r1 semantics. Diagnostic spectrum values
    are None (not computed). Exact evidence values stay rational in memory.
    Target remains mandatory; failed bounds/residuals refuse without clipping.
    """
    import numpy as np
    from threadpoolctl import threadpool_limits

    _cancel(cancel)
    nc = prepared['cells']
    if not (len(old) == len(capacity) == len(source) == nc):
        raise ValueError('Stock, capacity and source lengths must match actual cells')
    e0, cap, src = [list(map(L._binary, values)) for values in (old, capacity, source)]
    delta, absolute_target = L._binary(dt), Q(target)
    if delta <= 0 or any(c <= 0 for c in cap) or absolute_target <= 0:
        raise ValueError('Strict positive timestep, capacities and unchanged target required')
    load = [e+delta*s for e, s in zip(e0, src, strict=True)]
    loaded = load[:]
    for row in prepared['rows']:
        if row['kind'] == 'power':
            loaded[row['owners'][0][0]] -= delta*Q(prepared['boundary'][row['face_id']][1])
    loaded = [value/c for value, c in zip(loaded, cap, strict=True)]
    walls = [Q(value) for kind, value in prepared['boundary'].values() if kind == 'temperature']
    lower, upper = min(loaded+walls), max(loaded+walls)
    constant = lower == upper
    _cancel(cancel)
    if constant:
        energy = [c*lower for c in cap]
        diagnostics = dict(refinements=0, residual='0', exact_constant_path=True)
    else:
        rows = singleton_rows(prepared, cancel=cancel)
        _observe(observe, 'low-singletons-ready')
        witness = dict(kind='EXACT_LOW_COEFFICIENT_SINGLETONS', geometry_id=prepared['geometry_id'],
                       original_face_order_preserved=True, native_origin_bound=False)
        assembly_plan = ENDPOINT_INVENTORY.derive(rows, nc, prepared['boundary'],
            witness=witness, source_bindings=bindings, budget=budget, cancel=cancel)
        assembly = workspace.stack.enter_context(M.assemble(rows, nc, prepared['boundary'],
            witness=witness, source_bindings=bindings, budget=budget,
            inventory=assembly_plan.inventory, cancel=cancel))
        rounded = assembly.rounded_system(prepared['boundary'], cancel=cancel)
        _observe(observe, 'low-rounded-system-ready')
        # This is the same binary64 input conversion used by the frozen core.
        # Snapshot storage is covered by the already admitted ledger workspace.
        old64, capacity64, source64 = (tuple(map(float, values)) for values in (old, capacity, source))
        dt64 = float(dt)
        sparse_plan = INVENTORY.derive(rounded, old64, capacity64, dt64, source64,
            prepared['boundary'], str(target), budget=budget, cancel=cancel)
        with threadpool_limits(1):
            solved = workspace.stack.enter_context(P.solve_rounded(rounded, old64, capacity64, dt64, source64,
                prepared['boundary'], str(target), budget=budget, inventory=sparse_plan.inventory,
                cancel=cancel, observe=observe))
        state = solved.value
        energy = list(map(Q, state['energy']))
        diagnostics = {key: state[key] for key in ('refinements', 'residual',
                       'symmetric_part_minimum_eigenvalue', 'minimum_real_eigenvalue')}
        diagnostics['exact_constant_path'] = False
        diagnostics['sparse_backend'] = state['sparse_diagnostics']
        diagnostics['assembly_inventory'] = dict(derived_from_owned_inputs=True,
            input_bytes=assembly_plan.inventory.input_bytes, work_bytes=assembly_plan.inventory.work_bytes,
            result_bytes=assembly_plan.inventory.result_bytes, allocator_or_rss_bound=False,
            whole_method_admission=False)
        diagnostics['sparse_inventory'] = dict(derived_from_immutable_inputs=True,
            input_bytes=sparse_plan.inventory.input_bytes, work_bytes=sparse_plan.inventory.work_bytes,
            result_bytes=sparse_plan.inventory.result_bytes, allocator_or_rss_bound=False,
            whole_method_admission=False)
    _cancel(cancel)
    temperature = [e/c for e, c in zip(energy, cap, strict=True)]
    _observe(observe, 'low-before-physical-ledger')
    raw, faces = L.ledger(prepared, temperature, delta, cancel=cancel)
    balance = _residual(energy, faces, load)
    if max(map(abs, balance)) > absolute_target:
        raise ValueError('Reconstructed physical ledger failed unchanged algebraic target')
    if not all(lower <= value <= upper for value in temperature):
        raise ValueError('Exact low stock temperature outside loaded bounds; no clipping')
    _cancel(cancel)
    public_energy = list(map(float, energy))
    public_temperature = [e/float(c) for e, c in zip(public_energy, cap, strict=True)]
    if not all(math.isfinite(value) and lower <= Q(value) <= upper for value in public_temperature):
        raise ValueError('Actual public stock/capacity outside exact loaded bounds; no clipping')
    public_balance = _residual(list(map(Q, public_energy)), faces, load)
    source_energy = delta*sum(src)
    global_balance = A.paired_global_balance(list(map(Q, public_energy)), load, faces, cancel=cancel)
    outward = Q(global_balance['outward'])
    scale = max(sum(map(abs, e0)), sum(map(abs, map(Q, public_energy))), abs(source_energy), abs(outward))
    relative = Q(abs(global_balance['total']))/scale if scale else Q(0)
    if relative > PUBLIC_GLOBAL_GATE:
        raise ValueError('Actual public stock ledger failed existing global heat gate')
    _cancel(cancel)
    _observe(observe, 'low-ledger-accepted')
    _verify_sources(bindings, cancel)
    return dict(staging=dict(native_origin_bound=False, production_resource_admitted=False,
            inventory_coverage_certified=False, production_acceptance=False,
            retained_owner_required=True, source_bindings=bindings), energy=energy, temperature=np.asarray(public_temperature),
        absolute_temperature=np.asarray(public_temperature), public_energy=public_energy,
        exact_temperature=temperature, loaded_temperature=loaded, bounds_exact=(lower, upper),
        raw=raw, faces=faces, residual_exact=balance, public_residual_exact=public_balance,
        exact_bounds_pass=True, public_bounds_pass=True, public_global_relative=float(relative),
        public_global_gate_pass=True, exact_pair_defect=Q(0), source_energy=source_energy,
        outward_boundary_energy=outward, diagnostics=diagnostics,
        evidence=dict(absolute_target_decimal=str(target), raw_outward_energy_decimal=raw,
                      energy_exact=energy[:], physical_face_ids=prepared['face_ids'],
                      exact_values='Fraction objects in memory; explicit rational_hex for persistence',
                      global_sum='Exact paired stock/source/exterior-transfer identity; per-cell audits retained',
                      target_preserved=True, method='private:standalone-linear-positive-physical-face-low-r2'))
