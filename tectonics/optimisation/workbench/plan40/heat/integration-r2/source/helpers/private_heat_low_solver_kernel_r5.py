"""Plan40B explicit public spatial-transport source binding.

Private fixed-route LOW join; no native issue, saved solve or probe import.

The exact LOW geometry rows are caller-owned, already prepared from issued
geometry. Exact singleton intervals feed the standalone assembler, then the
fixed Decimal-80 sparse core. L5's exact E/C ledger, bounds, target, constant
path and global gate are unchanged. No high-order/material accuracy is claimed.

Exact-ledger inventory is derived in two admitted stages from original inputs
and then the actual owned sparse result or constant lower bound. Endpoint and
sparse Decimal inventories are also derived. These accounted policies are NOT
a whole-method or OS-RSS guarantee.
The returned OwnedSolve keeps the LOW workspace, assembly and sparse owners
charged together. Borrowed values
must not outlive that owner; failures retain leases with error AND traceback.

R4 keeps those owners alive together, as R3 does, but no longer keeps each at
its worst case. When a sub-stage has returned (the initial inventory, the
assembly with its rounded view, the sparse solve, the ledger inventory), what
it produced exists and is counted (counted blocks r1), and its reservation
falls to that before the next sub-stage is admitted. A result this count does
not know, or another runtime, leaves the reservation as R3 has it. Every
inventory is derived and admitted exactly as before; no arithmetic differs.

R5 counts by counted blocks r2. That module also refuses an interpreter with a
debug or replaced allocator and one that is tracing, so every reservation stays
as R3 has it there as well. It counts a block that may have shrunk from the C
heap at the C-heap figure, and a settle adds that module's allowance for every
record instance with a dictionary that it meets, up to what all the early
instances of one class can hold. A settle now stops as soon as its count
reaches the reservation, which it could not lower then; that also bounds its
walk on a graph with a cycle.
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
import private_heat_low_ledger_inventory_r1 as LEDGER_INVENTORY
import private_heat_counted_blocks_r2 as COUNT
from atlas_tectonics import integration_spatial_transport as SPATIAL_TRANSPORT

PUBLIC_GLOBAL_GATE = Q(1, 10**11)
HERE = Path(__file__).resolve().parent
_SOURCE_PATHS = (__file__, L.__file__, M.__file__, P.__file__, A.__file__,
                 INVENTORY.__file__, INVENTORY.POLICY_PATH,
                 ENDPOINT_INVENTORY.__file__, LEDGER_INVENTORY.__file__,
                 HERE/'private_heat_low_solver_kernel_r2.py',
                 SPATIAL_TRANSPORT.__file__,
                 HERE/'private_heat_gmp_resources_r1.py', HERE/'private_heat_sparse_resources_r1.py',
                 COUNT.__file__)
_SOURCES = {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in _SOURCE_PATHS}


def _cancel(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Sparse-backed linear low predictor cancelled')


def _observe(observe, phase):
    if observe is not None:
        observe(phase)


SETTLED_OWNER = 8192
SETTLED_VISITS = 1 << 26


def _settle(owner, graph, cancel):
    """Hold a returned sub-stage at what its result occupies.

    The sub-stage has returned, so its temporaries are gone and ``graph`` is
    what it left for this owner to hold: the owner's value and any view built
    from it. Each object is counted at its own blocks, aliases each time.
    Anything this count does not know, a cycle, or another runtime or
    interpreter mode leaves the reservation alone. What the interpreter and
    gmpy2 keep for reuse once the temporaries are freed (free lists, the
    object cache) is in no graph and is not counted here.

    The walk stops as soon as its count reaches the reservation. Every
    container is counted at more than the references it puts on the walk's
    stack, and none is put there after the count has reached the reservation,
    so the references waiting there take less than the reservation, and the
    stack's list with its spare room at most about nine eighths of it. The
    reservation is still held in full while the walk runs.
    """
    from dataclasses import fields, is_dataclass
    G = A.exact_library()
    if G is None or not COUNT.supported(G):
        return
    numpy = sys.modules.get('numpy')
    total, visits, pending = SETTLED_OWNER, 0, [graph]
    # Read before the walk: a count that reaches this cannot lower it.
    limit, classes = owner._workspace.lease.count, {}
    while pending:
        item = pending.pop()
        _cancel(cancel)
        visits += 1
        if visits > SETTLED_VISITS:
            return
        kind = type(item)
        if kind in (dict, list, tuple, str, bytes, int, bool, float, D, Q, G.mpq, G.mpz, type(None)):
            total += COUNT.own_bytes(item, G)
            if total >= limit:
                return
            if kind is dict:
                for key, child in item.items():
                    pending.append(key)
                    pending.append(child)
            elif kind in (list, tuple):
                pending.extend(item)
            elif kind is Q:
                pending.append(item.numerator)
                pending.append(item.denominator)
        elif is_dataclass(item) and not isinstance(item, type):
            keyed = hasattr(item, '__dict__')
            # An early instance of a class holds more than its dictionary reports.
            total += COUNT.block(sys.getsizeof(item))+(COUNT.record_instance(kind, classes) if keyed else 0)
            if total >= limit:
                return
            if keyed:
                pending.append(item.__dict__)
            else:
                pending.extend(getattr(item, field.name) for field in fields(item))
        elif (numpy is not None and kind is numpy.ndarray and item.dtype == numpy.dtype('float64')
                and item.ndim == 1 and item.flags.owndata):
            total += COUNT.array_bytes(sys.getsizeof(item), item.nbytes)
        elif numpy is not None and kind is numpy.float64:
            total += COUNT.block(sys.getsizeof(item))
        else:
            return
    work = owner._workspace
    if total < work.lease.count:
        work.resize_before_allocation_or_after_drop(total)


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
          source_bindings=None, cancel=None, observe=None):
    """Return P.OwnedSolve; value expires on close, with full retained charge.

    No arbitrary solver callback or already-solved state is accepted. Inputs
    and import/runtime baseline need caller admission before this operation.
    Ledger loads/bounds are prospectively admitted first. The actual owned
    sparse energy or constant lower bound then supplies a separate ledger plan
    before exact E/C, physical transfers, residuals and public audit allocation.
    Assembly and sparse allowances remain separately charged and retained;
    all metadata owners are retained too. No whole-method admission is claimed.
    """
    _cancel(cancel)
    A.exact_library()  # Gate before importing the GMP-dependent resource helper.
    import private_heat_gmp_resources_r1 as resources
    initial_owner = LEDGER_INVENTORY.admit_initial(prepared, old, capacity, dt, source, target,
        source_bindings=_SOURCES, additional_bindings=source_bindings, budget=budget, cancel=cancel)
    try:
        workspace = resources.OwnedWorkspace(budget, initial_owner.value.inventory.total(),
            category='heat-low-joined-private', cancelled=cancel)
        workspace.__enter__()
    except BaseException:
        initial_owner.__exit__(*sys.exc_info())
        raise
    workspace.stack.enter_context(initial_owner)
    try:
        _settle(initial_owner, initial_owner.value, cancel)
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
        ledger_plan = _admit_ledger(workspace, prepared, old, capacity, dt, source, target,
            bindings, budget, constant_lower=lower, cancel=cancel, observe=observe)
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
        _settle(assembly, (assembly.value, rounded), cancel)
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
        _settle(solved, state, cancel)
        ledger_plan = _admit_ledger(workspace, prepared, old, capacity, dt, source, target,
            bindings, budget, returned=state, cancel=cancel, observe=observe)
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
    diagnostics['ledger_inventory'] = dict(derived_in_two_stages=True,
        input_bytes=ledger_plan.inventory.input_bytes, work_bytes=ledger_plan.inventory.work_bytes,
        result_bytes=ledger_plan.inventory.result_bytes, allocator_or_rss_bound=False,
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
                      target_preserved=True, method='private:standalone-linear-positive-physical-face-low-r3'))



def _admit_ledger(workspace, prepared, old, capacity, dt, source, target, bindings, budget,
                  *, returned=None, constant_lower=None, cancel, observe):
    import private_heat_gmp_resources_r1 as resources
    plan_owner = workspace.stack.enter_context(LEDGER_INVENTORY.admit_ledger(
        prepared, old, capacity, dt, source, target, source_bindings=bindings,
        budget=budget, returned=returned, constant_lower=constant_lower, cancel=cancel))
    plan = plan_owner.value
    _settle(plan_owner, plan, cancel)
    _observe(observe, 'low-ledger-inventory-ready')
    workspace.stack.enter_context(resources.OwnedWorkspace(budget, plan.inventory.total(),
        category='heat-low-exact-ledger-private', cancelled=cancel))
    _observe(observe, 'low-ledger-workspace-admitted')
    return plan

