"""Admitted selected-J sparse right preconditioner, never the heat equation.

The caller supplies the SAME fixed-bound active tuples retained by the
selected derivative, including exact adjacent-region selection when used.
Decimal80 assembly precedes two-sided positive max-norm equilibration and
binary conversion. Pivoted general LU approximates B=Dr*J*Dc; applying its
right inverse returns Dc*B^-1*Dr*r. Decimal GMRES's original action/residual
and the nonlinear physical gates remain authoritative.

If binary LU cannot retain a small mode, an explicitly admitted optional
Decimal160 no-pivot LU reuses this assembly and the frozen factor's symmetric
ordering. Its symbolic fill bound comes from the symmetric-union graph.
No-pivot safety is NOT guaranteed for this nonsymmetric Jacobian: zero or
nonfinite pivots refuse it without shifting the equation. The higher precision
applies to the preconditioner only; its result is rounded to Decimal80.

All leases end before the returned context exits. The native model is an
allocation envelope, not an RSS cap. No physical diagonal shift, drop rule,
matrix cache, new Krylov limit or residual tolerance is introduced.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from contextlib import contextmanager, ExitStack
from decimal import Decimal as D, DecimalException, ROUND_HALF_EVEN, localcontext
import hashlib
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

from .resources import WorkBudget, MemoryLimitError
from .regional_multigrid3d import _native_factor_bytes

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def assert_current():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise ValueError('selected-J preconditioner source changed during solve')
    return _LOADED


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel,'is_set') else cancel()):
        raise CancelledError('selected-J preconditioner cancelled')


class _Unavailable(Exception):
    """Numerical preconditioner limitation, not permission to alter J."""


class _Factor:
    def __init__(self, factor, dr, dc, fallback, cancel, source_check, evidence):
        self.factor, self.dr, self.dc = factor, dr, dc
        self.fallback, self.cancel, self.source_check = fallback, cancel, source_check
        self.evidence, self.closed = evidence, False

    def close(self):
        self.closed = True
        self.factor = self.dr = self.dc = self.fallback = self.source_check = None

    def __call__(self, values):
        if self.closed:
            raise ValueError('selected-J preconditioner used after release')
        assert_current(); self.source_check(); _cancel(self.cancel)
        if len(values) != len(self.dr) or any(not value.is_finite() for value in values):
            raise ValueError('finite complete selected-J load required')
        try:
            with localcontext() as context:
                context.prec, context.rounding = 80, ROUND_HALF_EVEN
                weighted = [scale*value for scale,value in zip(self.dr,values)]
                magnitude = max(map(abs,weighted),default=D(0))
                if not magnitude:
                    return [D(0)]*len(values)
                scaled = np.asarray([float(value/magnitude) for value in weighted])
                if not np.isfinite(scaled).all():
                    raise _Unavailable('unrepresentable scaled selected-J load')
                answer = self.factor.solve(scaled)
                if not np.isfinite(answer).all():
                    raise _Unavailable('nonfinite selected-J factor action')
                result = [scale*D.from_float(float(value))*magnitude
                          for scale,value in zip(self.dc,answer)]
                if any(not value.is_finite() for value in result):
                    raise _Unavailable('unrepresentable selected-J result')
        except (DecimalException, _Unavailable, RuntimeError) as exc:
            self.evidence['action_fallbacks'] += 1
            self.evidence['last_action_fallback'] = str(exc)
            result = self.fallback(values)
        assert_current(); self.source_check(); _cancel(self.cancel)
        return result


def _build(local, blocks, capacity, dt, free, size, active, held, budget,
           fallback, cancel, source_check, evidence, *, precision=80,
           permutation=None, symbolic_fill=None):
    # Existing N admission owns the active tuple and Krylov vectors. These
    # charges cover dictionary assembly, simultaneous COO/CSC conversions,
    # scales, application temporaries and the separately admitted native LU.
    pairs = sum((len(entry[1])+1)**2 for entry in local)
    per_entry, per_node = (768,4096) if precision==80 else (1024,8192)
    assembly_bytes = 1024**2+per_entry*(pairs+4*len(active)+len(capacity))+per_node*size
    phase = dict(precision=precision,assembly_requested_bytes=assembly_bytes)
    evidence.setdefault('phase_records',[]).append(phase)
    held.enter_context(budget.reserve(assembly_bytes,category='mimetic-selected-j-assembly'))
    evidence['assembly_admitted_bytes'] = assembly_bytes
    phase['assembly_admitted_bytes'] = assembly_bytes
    positions = {j:i for i,j in enumerate(free)}
    if len(positions)!=len(free) or any(type(j) is not int or not 0<=j<size for j in free):
        raise ValueError('unique free selected-J nodes required')
    if len(local)!=len(blocks) or len(capacity)!=len(local):
        raise ValueError('complete selected-J base blocks/capacities required')
    rows = [{} for _ in free]
    zero = D(0)
    def add(i,j,value):
        a,b = positions.get(i),positions.get(j)
        if a is not None and b is not None:
            rows[a][b] = rows[a].get(b,zero)+value
    with localcontext() as context:
        context.prec, context.rounding = precision, ROUND_HALF_EVEN
        if not dt.is_finite() or dt<=0:
            raise ValueError('positive finite selected-J timestep required')
        for ci,(entry,block) in enumerate(zip(local,blocks)):
            _cancel(cancel)
            ids = (entry[0],*entry[1])
            if entry[0]!=ci or any(type(i) is not int or not 0<=i<size for i in ids):
                raise ValueError('valid selected-J local node coverage required')
            if len(block)!=len(ids) or any(len(row)!=len(ids) for row in block):
                raise ValueError('square complete selected-J base block required')
            for a,i in enumerate(ids):
                for b,j in enumerate(ids):
                    value = block[a][b]
                    if not value.is_finite():
                        raise ValueError('finite selected-J base coefficient required')
                    add(i,j,dt*value)
        for i,value in enumerate(capacity):
            if not value.is_finite() or value<=0:
                raise ValueError('positive finite selected-J capacity required')
            add(i,i,value)
        for i,j,d,branch,k,gamma in active:
            _cancel(cancel)
            if (any(type(a) is not int or not 0<=a<size for a in (i,j)) or i==j
                    or branch not in (1,2) or k is not None
                    or not d.is_finite() or d<=0 or not gamma.is_finite() or gamma<0):
                raise ValueError('fixed-bound selected derivative coefficients required')
            # Same correction derivative as L, not a frozen symmetric weight.
            left = d*(1+gamma) if branch==1 else d
            right = d*(1+gamma) if branch==2 else d
            add(i,i,dt*left); add(i,j,-dt*right)
            add(j,i,-dt*left); add(j,j,dt*right)
        for row in rows:
            for j in tuple(row):
                if not row[j]:del row[j]
        dr = []
        for row in rows:
            _cancel(cancel)
            largest = max(map(abs,row.values()),default=zero)
            if not largest:raise _Unavailable('zero selected-J free row')
            dr.append(1/largest)
        column_max = [zero]*len(free)
        for scale,row in zip(dr,rows):
            for j,value in row.items():
                column_max[j] = max(column_max[j],abs(scale*value))
        if any(not value for value in column_max):
            raise _Unavailable('zero selected-J free column')
        dc = [1/value for value in column_max]
        if any(not value.is_finite() or value<=0 for value in (*dr,*dc)):
            raise _Unavailable('unrepresentable selected-J positive scales')
        # Keep these diagnostics even if conversion or binary LU then fails.
        phase.update(matrix_nnz=sum(map(len,rows)),
            capacity_range_decimal=[str(min(capacity)),str(max(capacity))],
            row_scale_range_decimal=[str(min(dr)),str(max(dr))],
            column_scale_range_decimal=[str(min(dc)),str(max(dc))],
            coefficient_magnitude_range_decimal=[str(min(abs(v) for row in rows for v in row.values())),
                                                 str(max(abs(v) for row in rows for v in row.values()))])
        if precision==160:
            return _build_decimal(rows,dr,dc,permutation,symbolic_fill,held,budget,
                                  fallback,cancel,source_check,evidence,phase)
        rr,cc,vv = [],[],[]
        for i,(scale,row) in enumerate(zip(dr,rows)):
            _cancel(cancel)
            for j,value in row.items():
                number = float(scale*value*dc[j])
                if not np.isfinite(number) or not number:
                    raise _Unavailable('unrepresentable nonzero equilibrated selected-J coefficient')
                rr.append(i);cc.append(j);vv.append(number)
        matrix = sparse.coo_matrix((vv,(rr,cc)),shape=(len(free),len(free))).tocsc()
        del rows,positions,rr,cc,vv,column_max
        n,nnz = len(free),matrix.nnz
        fill_envelope = min(n*(n+1),30*nnz)
        native_bytes = 1024**2+_native_factor_bytes(n,nnz,fill_envelope)
        held.enter_context(budget.reserve(native_bytes,category='mimetic-selected-j-native'))
        evidence['native_admitted_bytes'] = native_bytes
        phase['native_admitted_bytes'] = native_bytes
        assert_current(); source_check(); _cancel(cancel)
        try:
            factor = splu(matrix,permc_spec='COLAMD',diag_pivot_thresh=1.,
                          options={'Equil':False,'SymmetricMode':False})
        except RuntimeError as exc:
            raise _Unavailable('selected-J general LU failed: '+str(exc)) from exc
        _cancel(cancel); assert_current(); source_check()
        factor_nnz = factor.L.nnz+factor.U.nnz
        realised = 1024**2+_native_factor_bytes(n,nnz,factor_nnz)
        if realised>native_bytes:
            raise MemoryLimitError('selected-J realised native fill exceeds admitted envelope')
        pivots = factor.U.diagonal()
        if not np.isfinite(pivots).all() or np.any(pivots==0):
            raise _Unavailable('invalid selected-J general LU pivots')
        evidence.update(status='selected-j',matrix_nnz=int(nnz),factor_nnz=int(factor_nnz),
            native_realised_accounted_bytes=int(realised),
            minimum_absolute_pivot=float(min(abs(pivots))),maximum_absolute_pivot=float(max(abs(pivots))),
            row_scale_range_decimal=[str(min(dr)),str(max(dr))],
            column_scale_range_decimal=[str(min(dc)),str(max(dc))])
        phase.update(status='selected-j',factor_nnz=int(factor_nnz),
                     native_realised_accounted_bytes=int(realised))
        return _Factor(factor,dr,dc,fallback,cancel,source_check,evidence)


class _DecimalFactor(_Factor):
    def __init__(self, rows, order, dr, dc, fallback, cancel, source_check, evidence):
        super().__init__(None,dr,dc,fallback,cancel,source_check,evidence)
        self.rows,self.order = rows,order

    def close(self):
        self.rows = self.order = None
        super().close()

    def __call__(self, values):
        if self.closed:
            raise ValueError('selected-J preconditioner used after release')
        assert_current(); self.source_check(); _cancel(self.cancel)
        if len(values)!=len(self.dr) or any(not value.is_finite() for value in values):
            raise ValueError('finite complete selected-J load required')
        try:
            with localcontext() as context:
                context.prec,context.rounding = 160,ROUND_HALF_EVEN
                y = [D(0)]*len(values)
                for at,k in enumerate(self.order):y[k] = self.dr[at]*values[at]
                for k,row in enumerate(self.rows):
                    _cancel(self.cancel)
                    y[k] -= sum((value*y[j] for j,value in row.items() if j<k),D(0))
                for k in range(len(y)-1,-1,-1):
                    _cancel(self.cancel)
                    row = self.rows[k]
                    y[k] = (y[k]-sum((value*y[j] for j,value in row.items() if j>k),D(0)))/row[k]
                result = [self.dc[at]*y[k] for at,k in enumerate(self.order)]
                context.prec = 80
                result = [+value for value in result]
                if any(not value.is_finite() for value in result):
                    raise _Unavailable('unrepresentable Decimal160 selected-J result')
        except (DecimalException,_Unavailable) as exc:
            self.evidence['action_fallbacks'] += 1
            self.evidence['last_action_fallback'] = str(exc)
            result = self.fallback(values)
        assert_current(); self.source_check(); _cancel(self.cancel)
        return result


def _build_decimal(rows,dr,dc,permutation,symbolic_fill,held,budget,
                   fallback,cancel,source_check,evidence,phase):
    """Fixed-order LU fill is contained in symmetric-union elimination fill.

    A directed elimination update i<-k->j requires undirected edges i-k and
    k-j, so its i-j fill edge is in symmetric symbolic elimination. Induction
    over the SAME order gives <=n+2*F stored L/U coefficients (one U diagonal,
    implicit unit L diagonal). No pivot exchanges are permitted under this
    bound. This is a storage proof, not numerical no-pivot stability.
    """
    n = len(rows)
    order = tuple(map(int,permutation))
    if (len(order)!=n or any(a!=b for a,b in zip(order,permutation))
            or sorted(order)!=list(range(n))):
        raise ValueError('complete frozen selected-J permutation required')
    above = [set() for _ in rows]
    for i,row in enumerate(rows):
        _cancel(cancel)
        for j in row:
            if i!=j:
                low,high = sorted((order[i],order[j]))
                above[high].add(low)
    _cancel(cancel)
    fill = symbolic_fill(above)
    _cancel(cancel); assert_current(); source_check()
    if type(fill) is not int or not 0<=fill<=n*(n-1)//2:
        raise ValueError('valid symmetric-union symbolic fill count required')
    del above
    bound = n+2*fill
    factor_bytes,scratch_bytes = 1024*bound,1024**2+8192*n
    held.enter_context(budget.reserve(factor_bytes,category='mimetic-selected-j-decimal'))
    held.enter_context(budget.reserve(scratch_bytes,category='mimetic-selected-j-decimal-scratch'))
    phase.update(symbolic_union_lower_nnz=fill,symbolic_lu_bound=bound,
                 factor_admitted_bytes=factor_bytes,scratch_admitted_bytes=scratch_bytes)
    # Reordering/scaling initial coefficients precedes elimination but is
    # already covered by the assembly lease. Factor/fill leases are now live.
    factors = [{} for _ in rows]
    for i,row in enumerate(rows):
        _cancel(cancel)
        for j,value in row.items():
            number = dr[i]*value*dc[j]
            if not number.is_finite() or not number:
                raise _Unavailable('unrepresentable Decimal160 selected-J scaled coefficient')
            factors[order[i]][order[j]] = number
    rows.clear()
    stored = sum(map(len,factors))
    if stored>bound:
        raise MemoryLimitError('selected-J initial pattern exceeds symbolic LU bound')
    columns = [set() for _ in factors]
    for i,row in enumerate(factors):
        for j in row:
            if j<i:columns[j].add(i)
    zero = D(0)
    minimum,maximum = None,zero
    for k,row in enumerate(factors):
        _cancel(cancel)
        pivot = row.get(k,zero)
        if not pivot.is_finite() or not pivot:
            phase.update(refused_pivot=k,pivot_decimal=str(pivot))
            raise _Unavailable('Decimal160 selected-J no-pivot LU has zero/nonfinite pivot')
        magnitude = abs(pivot)
        minimum = magnitude if minimum is None else min(minimum,magnitude)
        maximum = max(maximum,magnitude)
        upper = tuple((j,value) for j,value in row.items() if j>k and value)
        for i in sorted(columns[k]):
            _cancel(cancel)
            target = factors[i]
            value = target[k]
            if not value:continue
            multiplier = value/pivot
            target[k] = multiplier
            for j,value in upper:
                updated = target.get(j,zero)-multiplier*value
                if j not in target:
                    if not updated:continue
                    if stored==bound:
                        raise MemoryLimitError('selected-J realised Decimal LU fill exceeds symbolic bound')
                    stored += 1
                    if j<i:columns[j].add(i)
                target[j] = updated
        columns[k].clear()
    del columns
    assert_current(); source_check(); _cancel(cancel)
    phase.update(status='selected-j-decimal160',factor_nnz=stored,
                 minimum_absolute_pivot_decimal=str(minimum),maximum_absolute_pivot_decimal=str(maximum))
    evidence.update(status='selected-j-decimal160',
        method='Decimal160 assembled/scaled no-pivot LU; frozen symmetric order; Decimal80 output',
        factor_nnz=stored,factor_precision=160,output_precision=80)
    evidence.pop('fallback_type',None); evidence.pop('fallback_reason',None)
    return _DecimalFactor(factors,order,dr,dc,fallback,cancel,source_check,evidence)


@contextmanager
def preconditioner(local, blocks, capacity, dt, free, size, active, *, budget,
                   fallback, source_check, cancel=None, permutation=None, symbolic_fill=None):
    """Yield (right inverse, evidence); numerical/admission refusal falls back.

    Invalid input, source changes and cancellation propagate. The fallback
    already belongs to the heat caller; this helper never releases it.
    """
    assert_current(); source_check(); _cancel(cancel)
    if type(budget) is not WorkBudget or type(size) is not int or size<1 or not free:
        raise ValueError('shared budget and nonempty selected-J geometry required')
    if (permutation is None)!=(symbolic_fill is None):
        raise ValueError('complete frozen ordering and symbolic fill callback required')
    evidence = dict(status='fallback',method='Decimal80 assembled; Dr J Dc general pivoted binary64 LU',
        source_sha256=_LOADED,active_edges=len(active),action_fallbacks=0)
    owner = None
    with ExitStack() as held:
        try:
            owner = _build(local,blocks,capacity,dt,free,size,active,held,budget,
                           fallback,cancel,source_check,evidence)
        except (MemoryLimitError,DecimalException,_Unavailable) as exc:
            # No refused candidate storage remains live during fallback GMRES.
            held.close()
            evidence.update(fallback_type=type(exc).__name__,fallback_reason=str(exc))
            if evidence.get('phase_records'):
                evidence['phase_records'][-1].update(status='refused',reason=str(exc),type=type(exc).__name__)
        if owner is None and permutation is not None:
            try:
                owner = _build(local,blocks,capacity,dt,free,size,active,held,budget,
                    fallback,cancel,source_check,evidence,precision=160,
                    permutation=permutation,symbolic_fill=symbolic_fill)
            except (MemoryLimitError,DecimalException,_Unavailable) as exc:
                held.close()
                evidence.update(fallback_type=type(exc).__name__,fallback_reason=str(exc))
                if evidence.get('phase_records'):
                    evidence['phase_records'][-1].update(status='refused',reason=str(exc),type=type(exc).__name__)
        try:
            yield owner if owner is not None else fallback,evidence
        finally:
            if owner is not None:owner.close()
    assert_current(); source_check(); _cancel(cancel)


def solve_direction(local, blocks, capacity, dt, free, size, active, *,
                    action, rhs, relative_target, budget, fallback, source_check,
                    cancel=None, permutation=None, symbolic_fill=None):
    """Solve one selected system, with one residual-triggered Decimal160 retry.

    The caller retains the same active tuple, action, load and target and holds
    N.workspace_bytes(size) throughout. Its additional-vector allowance covers
    both candidate directions and the true-residual checks; factor admission is
    separate. A successful binary build can still lose a mode in its action.
    Only a measured failure with that binary factor permits the retry, after
    its complete context has released. Never repeat an exhausted Decimal path,
    an action fallback or a resource refusal. This returns a direction only;
    the caller's literal nonlinear/flux/energy/bounds gates remain unchanged.
    """
    from . import integration_mimetic_newton as N

    def check():
        assert_current(); N.assert_current(); source_check(); _cancel(cancel)

    check()
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        rhs = N._vector(rhs, len(free))
        relative_target = D(relative_target)
        if not relative_target.is_finite() or not 0 < relative_target < 1:
            raise ValueError('unchanged finite inner relative target required')
        rhs_norm = sum((x*x for x in rhs), D(0)).sqrt()
        target = relative_target*rhs_norm

        def solve(inverse, evidence):
            answer = N.gmres(action, inverse, rhs, cancel=cancel,
                             max_restarts=1, relative_target=relative_target)
            check()
            values = N._vector(answer['solution'], len(free))
            applied = N._vector(action(values), len(free))
            error = sum(((a-b)**2 for a, b in zip(applied, rhs)), D(0)).sqrt()
            if not error.is_finite():
                raise ValueError('nonfinite actual selected-J inner residual')
            # The literal supplied action, not a factor/Hessenberg estimate,
            # decides both retry eligibility and which direction is retained.
            answer.update(converged=error <= target,
                          residual_norm_decimal=str(error),
                          relative_residual_decimal=str(error/rhs_norm if rhs_norm else D(0)),
                          target_norm_decimal=str(target),
                          actual_residual_action_calls=1,
                          selected_preconditioner=evidence)
            return answer, error

        with preconditioner(local, blocks, capacity, dt, free, size, active,
                budget=budget, fallback=fallback, source_check=source_check,
                cancel=cancel, permutation=permutation,
                symbolic_fill=symbolic_fill) as (inverse, evidence):
            answer, error = solve(inverse, evidence)
        # The original factor and assembly reservations have ended here.
        eligible = (error > target and evidence.get('status') == 'selected-j'
                    and type(inverse) is _Factor and inverse.closed
                    and evidence.get('action_fallbacks') == 0
                    and permutation is not None and symbolic_fill is not None)
        if not eligible:
            check()
            return answer

        retry = dict(status='refused', binary_storage_released=True,
                     equation_load_and_target_unchanged=True, maximum_attempts=1,
                     initial={k: v for k, v in answer.items() if k != 'solution'})
        retry_evidence = dict(status='unavailable',
            method='one Decimal160 retry after actual binary inner residual failure',
            source_sha256=_LOADED, active_edges=len(active), action_fallbacks=0)
        retry['selected_preconditioner'] = retry_evidence

        def unavailable(_):
            raise _Unavailable('Decimal160 retry action unavailable; no further fallback')

        owner = None
        with ExitStack() as held:
            try:
                check()
                owner = _build(local, blocks, capacity, dt, free, size, active,
                    held, budget, unavailable, cancel, source_check, retry_evidence,
                    precision=160, permutation=permutation, symbolic_fill=symbolic_fill)
                candidate, candidate_error = solve(owner, retry_evidence)
                retry['linear'] = {k: v for k, v in candidate.items()
                                   if k not in ('solution', 'selected_preconditioner')}
                if candidate_error < error:
                    answer = candidate
                    retry['status'] = 'improved-direction'
                else:
                    retry['status'] = 'retained-initial-direction'
            except (MemoryLimitError, DecimalException, _Unavailable) as exc:
                retry.update(refusal_type=type(exc).__name__, refusal_reason=str(exc))
            finally:
                if owner is not None:
                    owner.close()
        retry['factor_released'] = True
        answer['decimal160_residual_retry'] = retry
        check()
        return answer
