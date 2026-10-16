"""Private, certification-independent extraction of the sparse Decimal core.

No reconstruction, geometry admission, exact assembly, LOW ledger, method
dispatch or experiment imports. A caller supplies already rounded coefficients
and owns their exact-sum-then-round/source/boundary proof. This core validates
the numerical data, NOT that proof. Decimal-80 HALF_EVEN, ascending columns,
SuperLU defaults and the original eight corrections are preserved.

Importing this module is stdlib-only. At method invocation the selected native
exact backend gates the existing GMP-dependent resource helper. No backend is
changed. Sparse/native storage follows that helper's conservative policy;
unprovided Decimal/Python/input/result inventories explicitly refuse. Declared
caller charges are not independently certified or an allocator/RSS guarantee.
The returned owner retains the ENTIRE workspace charge until close, including
conservative transient over-reservation. Borrowed values must not outlive it.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from decimal import Decimal as D, ROUND_HALF_EVEN, localcontext
import math
import sys
from time import perf_counter


@dataclass(frozen=True)
class RoundedFace:
    face_id: str
    owners: tuple
    weights: tuple


@dataclass(frozen=True)
class RoundedSystem:
    cells: int
    operator: tuple
    wall: tuple
    rows: tuple
    exact_operator_nnz: int
    context_signature: tuple
    boundary_signature: tuple
    source_bindings: tuple
    witness_json: str


@dataclass(frozen=True)
class CallerInventory:
    """All three declarations are required, positive, and caller-justified.

    input_bytes: supplied arrays/system/metadata still live during execution.
    work_bytes: simultaneous Python containers, Decimal operands/results and
    intermediates, ndarray headers and callbacks. Dependency/runtime baseline
    imports are caller-owned outside this operation, not admitted retroactively.
    result_bytes: retained output arrays/Decimals/strings/containers/metadata.
    These are charged together; no aliasing or early-release credit is taken.
    Dynamic exact/MPFR/reconstruction storage is outside this solver and must
    have separate live admission if retained by the caller.
    """
    input_bytes: int
    work_bytes: int
    result_bytes: int
    justification: str

    def total(self):
        counts = (self.input_bytes, self.work_bytes, self.result_bytes)
        if any(type(value) is not int or value <= 0 for value in counts):
            raise ValueError('Explicit positive input, Decimal/Python work and result inventories required')
        if type(self.justification) is not str or not self.justification.strip():
            raise ValueError('Caller inventory justification required')
        value = sum(counts)
        if value > sys.maxsize:
            raise OverflowError('Caller inventory exceeds addressable storage')
        return value


def context_signature(context):
    return (context.prec, context.rounding, context.Emin, context.Emax, context.clamp)


def boundary_signature(boundary):
    """Numerical binary64 observation binding, NOT original exact identity.

    The external certified assembler/caller must also preserve its exact input
    binding. This numerical core evaluates boundary values through float, as
    the frozen algorithm does, and makes no stronger provenance assertion.
    """
    return tuple((key, kind, D.from_float(float(value)))
                 for key, (kind, value) in sorted(boundary.items()))


class OwnedSolve:
    """Dedicated result owner; all borrowed data expire when close is called."""
    def __init__(self, value, workspace):
        self._value, self._workspace = value, workspace

    @property
    def value(self):
        if self._workspace is None:
            raise RuntimeError('Sparse result owner is closed')
        return self._value

    def close(self):
        if self._workspace is not None:
            workspace, self._workspace = self._workspace, None
            self._value = None
            workspace.__exit__(None, None, None)

    def __enter__(self):
        self.value
        return self

    def __exit__(self, kind, error, traceback):
        if error is None:
            self.close()
            return False
        workspace, self._workspace = self._workspace, None
        self._value = None
        if workspace is not None:
            # A caller's escaping frame may contain a borrowed result. Preserve
            # its admission with that error/traceback under native policy.
            return workspace.__exit__(kind, error, traceback)
        return False

    def __del__(self):
        self.close()


def _checkpoint(cancel, observe, phase):
    if observe is not None:
        observe(phase)
    if cancel is not None and cancel():
        raise CancelledError('Private sparse Decimal solve cancelled at '+phase)


def _finite(value):
    return type(value) is D and value.is_finite()


def _validate(system, old, capacity, dt, source, boundary, target, context, cancel):
    n = system.cells
    if (system.context_signature != context_signature(context)
            or type(system.operator) is not tuple or len(system.operator) != n
            or type(system.wall) is not tuple or len(system.wall) != n
            or type(system.rows) is not tuple
            or len(old) != n or len(capacity) != n or len(source) != n):
        raise ValueError('Matching immutable Decimal-80 system and ordered cell arrays required')
    if system.boundary_signature != boundary_signature(boundary):
        raise ValueError('Numerical prescribed observations changed after assembly')
    if any(kind not in ('temperature', 'power') or not math.isfinite(float(value))
           for kind, value in boundary.values()):
        raise ValueError('Finite physical boundary observations required')
    if (not math.isfinite(float(dt)) or float(dt) <= 0
            or not D(target).is_finite() or D(target) <= 0
            or any(not math.isfinite(float(x)) for x in old)
            or any(not math.isfinite(float(x)) for x in source)
            or any(not math.isfinite(float(x)) or float(x) <= 0 for x in capacity)
            or any(not _finite(x) for x in system.wall)):
        raise ValueError('Finite original inputs and positive capacity/dt/target required')
    count = 0
    for row in system.operator:
        _checkpoint(cancel, None, 'validate-operator-row')
        if type(row) is not tuple:
            raise ValueError('Immutable ordered operator rows required')
        previous = -1
        for j, value in row:
            if type(j) is not int or not previous < j < n or not _finite(value):
                raise ValueError('Finite ascending unique operator columns required')
            previous = j
            count += 1
    if type(system.exact_operator_nnz) is not int or count != system.exact_operator_nnz:
        raise ValueError('Exact assembled support count changed')
    faces = set()
    for row in system.rows:
        _checkpoint(cancel, None, 'validate-face-row')
        if (type(row) is not RoundedFace or type(row.face_id) is not str or not row.face_id
                or row.face_id in faces or type(row.owners) is not tuple
                or type(row.weights) is not tuple or len(row.owners) not in (1, 2)):
            raise ValueError('Unique immutable physical face rows required')
        faces.add(row.face_id)
        indices, signs = set(), []
        for i, sign in row.owners:
            if (type(i) is not int or not 0 <= i < n or i in indices
                    or type(sign) is not int or sign not in (-1, 1)):
                raise ValueError('Valid distinct physical owners and exact orientation required')
            indices.add(i)
            signs.append(sign)
        if len(signs) == 2 and sum(signs) != 0:
            raise ValueError('Interior face owners must have opposite orientation')
        keys = set()
        for (kind, key), value in row.weights:
            if (kind, key) in keys or not _finite(value):
                raise ValueError('Finite unique ordered observation weights required')
            keys.add((kind, key))
            if kind == 'cell':
                if type(key) is not int or not 0 <= key < n:
                    raise ValueError('Cell observation index outside declared ordered arrays')
            elif kind not in ('wall', 'power') or key not in boundary:
                raise ValueError('Unsupported or missing prescribed observation')
            elif boundary[key][0] != ('temperature' if kind == 'wall' else 'power'):
                raise ValueError('Prescribed observation kind changed')
    if (type(system.source_bindings) is not tuple or not system.source_bindings
            or type(system.witness_json) is not str or not system.witness_json.strip()):
        raise ValueError('Explicit caller source bindings and witness record required')
    names = set()
    for name, digest in system.source_bindings:
        if (type(name) is not str or not name or name in names or type(digest) is not str
                or len(digest) != 64 or any(x not in '0123456789abcdef' for x in digest)):
            raise ValueError('Unique caller source names and SHA256 bindings required')
        names.add(name)


def solve_rounded(system, old, capacity, dt, source, boundary, target, *,
                  budget, inventory, cancel=None, observe=None, spectrum=False):
    """Return OwnedSolve; caller must keep it alive while any value is borrowed.

    The caller must configure the native package import path. No geometry or
    backend setup occurs here. Input construction and certificate validity are
    outside this function; pre-existing inputs must already be admitted by the
    caller. Their declared charge is conservatively repeated while solving.
    Dependency import/allocator baseline needs separately established caller
    headroom; this narrow arithmetic reservation is not a process memory cap.
    No original target substitution, regularisation or extra correction occurs.
    """
    _checkpoint(cancel, observe, 'admission-start')
    if type(system) is not RoundedSystem or type(system.cells) is not int or system.cells <= 0:
        raise ValueError('Positive immutable rounded system required')
    if type(inventory) is not CallerInventory:
        raise ValueError('Caller workset inventory is mandatory, not inferred')
    other = inventory.total()
    if spectrum:
        raise ValueError('Exact-rational spectrum is not certified by a rounded numerical core')
    # Gate BEFORE importing resource helpers which themselves depend on GMP.
    from atlas_tectonics import exact_arithmetic
    if exact_arithmetic.library() is None:
        raise RuntimeError('This private resource route requires the selected GMP backend')
    import private_heat_sparse_resources_r1 as resources
    n = system.cells
    # Worst structural support avoids an uncharged speculative matrix/set.
    plan = resources.sparse_lu_envelope(n, n*n, binary64_vectors=6, other_live_bytes=other)
    workspace = resources.R.OwnedWorkspace(budget, plan.total_bytes,
                                         category='heat-sparse-decimal-private', cancelled=cancel)
    workspace.__enter__()
    try:
        with localcontext() as context:
            context.prec, context.rounding = 80, ROUND_HALF_EVEN
            _validate(system, old, capacity, dt, source, boundary, target, context, cancel)
            value = _solve(system, old, capacity, dt, source, boundary, target,
                           cancel=cancel, observe=observe, resources=resources,
                           plan=plan, workspace=workspace)
        return OwnedSolve(value, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def _solve(system, old, capacity, dt, source, boundary, target, *, cancel, observe,
           resources, plan, workspace):
    # These numerical operations intentionally match frozen certified S in
    # both order and coercions. Resource audits do not mutate the operands.
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.linalg import splu
    began = perf_counter()
    nc = len(old)
    _checkpoint(cancel, observe, 'start')
    op = [dict(row) for row in system.operator]
    wall, rows = system.wall, system.rows
    exact_nnz = system.exact_operator_nnz
    _checkpoint(cancel, observe, 'exact-operator-ready')
    c = [D.from_float(float(x)) for x in capacity]
    delta = D.from_float(float(dt))
    rhs = [D.from_float(float(e))+delta*(D.from_float(float(s))-b)
           for e, s, b in zip(old, source, wall, strict=True)]
    dm, data, indices, indptr = [], [], [], [0]
    for i, row in enumerate(op):
        _checkpoint(cancel, None, 'decimal-row-assembly')
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
    _checkpoint(cancel, observe, 'decimal-system-ready')
    approximate = csr_matrix((np.asarray(data, dtype=float), np.asarray(indices), np.asarray(indptr)),
                             shape=(nc, nc)).tocsc()
    approximate.sort_indices()
    del data, indices, indptr, wall
    resources.audit_sparse_input(approximate, plan, workspace=workspace)
    _checkpoint(cancel, observe, 'before-factorisation')
    factor = splu(approximate)
    factor_audit = resources.audit_factor(factor, plan, workspace=workspace)
    factor_nnz = factor.L.nnz+factor.U.nnz
    _checkpoint(cancel, observe, 'after-factorisation')
    u = [D.from_float(float(v)) for v in factor.solve(np.asarray(list(map(float, rhs))))]
    _checkpoint(cancel, observe, 'after-initial-solve')
    for iteration in range(9):
        _checkpoint(cancel, observe, 'residual-check-'+str(iteration))
        residual = []
        for row, b in zip(dm, rhs, strict=True):
            _checkpoint(cancel, None, 'residual-row')
            residual.append(b-sum((a*u[j] for j, a in row), D(0)))
        absolute = max(map(abs, residual))
        if absolute <= D(target):
            break
        if iteration == 8:
            raise ValueError('High predictor failed unchanged algebraic residual target')
        _checkpoint(cancel, observe, 'before-correction-'+str(iteration+1))
        update = factor.solve(np.asarray(list(map(float, residual))))
        _checkpoint(cancel, observe, 'after-correction-'+str(iteration+1))
        u = [t+D.from_float(float(d)) for t, d in zip(u, update, strict=True)]
    _checkpoint(cancel, observe, 'before-face-fluxes')
    fluxes = []
    for row in rows:
        _checkpoint(cancel, None, 'face-flux-row')
        value = delta*sum((w*(u[key] if kind == 'cell' else D.from_float(float(boundary[key][1])))
                           for (kind, key), w in row.weights), D(0))
        fluxes.append([(i, sign, str(sign*value)) for i, sign in row.owners])
    _checkpoint(cancel, observe, 'after-face-fluxes')
    _checkpoint(cancel, observe, 'complete')
    return dict(temperature=np.asarray(list(map(float, u))), energy=[a*b for a, b in zip(c, u, strict=True)],
        residual=str(absolute), refinements=iteration,
        symmetric_part_minimum_eigenvalue=None, minimum_real_eigenvalue=None,
        raw=fluxes, evidence={'absolute_target_decimal': target, 'raw_outward_energy_decimal': fluxes},
        sparse_diagnostics=dict(cells=nc, exact_operator_nnz=exact_nnz, decimal_system_nnz=decimal_nnz,
            approximate_system_nnz=approximate.nnz, factor_L_plus_U_nnz=factor_nnz,
            spectrum_computed=False, native_workbudget_admitted=False, seconds=perf_counter()-began),
        coefficient_diagnostics=dict(validity='CALLER_WITNESSED_NOT_REPROVED_BY_NUMERICAL_CORE',
            source_bindings=dict(system.source_bindings), witness_json=system.witness_json,
            exact_sum_then_round_certified_by_core=False),
        resource_diagnostics=dict(factor_audit, caller_inventory_independently_certified=False,
            caller_other_live_bytes=plan.other_live_bytes,
            retained_result_lease_bytes=plan.total_bytes,
            dependency_import_baseline_admitted_by_core=False,
            resource_route='PRIVATE_ACCOUNTED_POLICY_NOT_WHOLE_METHOD_ADMISSION'))
