"""Bounded right-preconditioned GMRES for symmetric Taylor-Hood saddle blocks.

K v + G p = f; G.T v = g. Optional positive mean weights impose w.T p = 0.
The pressure-mass input is the caller's integral of phi_i*phi_j/eta. No physical
matrix is shifted. Symmetric equilibration balances the iterative solve;
original-unit block equations accept the returned fields. One driving/native
thread is owned by the enclosing workflow.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
import hashlib
import math

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import reverse_cuthill_mckee
from scipy.sparse.linalg import LinearOperator, gmres, splu

from ._validation import TectonicsError, input_shape, read_array, frozen
from .constitutive import _cancel
from .resources import WorkBudget, select_budget


_CAP = 128*1024**2
_RESTART = 60
_ITERATIONS = 1200
_TOLERANCE = 1e-10


def _csr(value, name):
    if not sparse.issparse(value) or value.format != 'csr' or value.dtype != np.dtype('float64'):
        raise TectonicsError(name+' requires binary64 CSR storage')
    if (len(value.shape) != 2 or min(value.shape) < 1 or max(value.shape) > 65536 or value.nnz > 2000000 or
        len(value.indptr) != value.shape[0]+1 or value.indptr[0] != 0 or value.indptr[-1] != len(value.data) or
        len(value.indices) != len(value.data) or np.any(np.diff(value.indptr) < 0) or
        np.any(value.indices < 0) or np.any(value.indices >= value.shape[1]) or not value.has_canonical_format or
        not np.isfinite(value.data).all()):
        raise TectonicsError(name+' has invalid or excessive sparse support')
    return value


def _bytes(matrix):
    return sum(a.nbytes for a in (matrix.data, matrix.indices, matrix.indptr))


def _positive_symmetric(matrix, name):
    diagonal = matrix.diagonal()
    if np.any(diagonal <= 0.):
        raise TectonicsError(name+' requires positive diagonal')
    difference = matrix-matrix.T
    if difference.nnz and np.max(np.abs(difference.data)) > 1e-12*np.max(np.abs(matrix.data)):
        raise TectonicsError(name+' must be symmetric')
    return 1./np.sqrt(diagonal)


def _scaled_csc(matrix, scale):
    result = matrix.tocsc(copy=True)
    result.data *= np.repeat(scale, np.diff(result.indptr))*scale[result.indices]
    if not np.isfinite(result.data).all():
        raise TectonicsError('scaled saddle factor is nonfinite')
    return result


class _VelocityFactor:
    """Solve the original scaled equation through a symmetric graph ordering."""
    def __init__(self, factor, permutation):
        self.factor, self.permutation = factor, permutation

    def solve(self, rhs):
        result = np.empty_like(rhs)
        result[self.permutation] = self.factor.solve(rhs[self.permutation])
        return result


def _factor(matrix, scale, velocity, owner, stack, cancel):
    n = matrix.shape[0]
    # Phase-local gradients release headroom; the enclosing 128MiB cap still
    # admits the combined work. This internal envelope is not the overall cap.
    # Retained nonlinear history can consume otherwise unused envelope space.
    # Cap the reservation by ancestry-aware headroom, never the realised guards.
    allowance = (min(72*1024**2,160*matrix.nnz+256*n+1024**2,owner.available_bytes) if velocity else
                 int(20*n**1.5+64*matrix.nnz+1024**2))
    category = 'subduction-velocity-block-lu' if velocity else 'subduction-bfbt-poisson-lu'
    retained_bound = (2*allowance+2)//3
    # Reserve retained capacity first: there is never an unaccounted transfer
    # from the construction lease to live native factors and cached SciPy L/U.
    stack.enter_context(owner.reserve(retained_bound, category=category))
    with owner.reserve(allowance-retained_bound, category=category+'-build'):
        # Scaling/symmetric slicing hold at most three sparse payloads. SciPy
        # RCM has linear-size degree/order/argsort work, bounded here by 64*n.
        ordering_work = 3*_bytes(matrix)+64*n+4096 if velocity else 0
        if ordering_work > allowance:
            raise TectonicsError('velocity ordering workspace exceeds admission')
        _cancel(cancel); scaled = _scaled_csc(matrix, scale); factor = None
        permutation = None; permutation_bytes = 0
        try:
            if velocity:
                permutation = reverse_cuthill_mckee(matrix, symmetric_mode=True)
                permutation_bytes = permutation.nbytes
                scaled = scaled[permutation, :][:, permutation].tocsc()
            try:
                factor = splu(scaled, permc_spec='MMD_AT_PLUS_A', diag_pivot_thresh=0., options={'SymmetricMode': True})
            except RuntimeError as exc:
                raise TectonicsError('saddle block factor failed; no direct saddle fallback') from exc
            actual = _bytes(factor.L)+_bytes(factor.U)
            overhead = 2*permutation_bytes+4096 if velocity else 0
            construction = 3*actual+_bytes(scaled)+overhead
            retained = 2*actual+16*n+overhead  # native/cached factors, permutations and wrapper
            name = 'velocity' if velocity else 'BFBT pressure'
            if construction > allowance:
                raise TectonicsError(f'{name} factor exceeds admitted realised fill: {construction} > {allowance} bytes; n={n}, nnz={matrix.nnz}')
            if retained > retained_bound:
                raise TectonicsError(f'{name} retained footprint exceeds admission: {retained} > {retained_bound} bytes')
            if np.any(factor.U.diagonal() <= 0.):
                raise TectonicsError('saddle block has nonpositive factor pivots')
            _cancel(cancel)
            diagnostics = dict(admitted_bytes=allowance, retained_factor_bytes=actual,
                realised_accounted_bytes=construction, retained_admitted_bytes=retained_bound,
                retained_accounted_bytes=retained, factor_nnz=factor.L.nnz+factor.U.nnz,
                ordering='RCM-MMD_AT_PLUS_A' if velocity else 'MMD_AT_PLUS_A',
                ordering_workspace_bytes=ordering_work, permutation_bytes=permutation_bytes)
            if velocity:
                diagnostics['permutation_sha256'] = hashlib.sha256(permutation.tobytes()).hexdigest()
                factor = _VelocityFactor(factor, permutation)
        except BaseException:
            factor = None
            raise
        finally:
            del scaled
    return factor, diagnostics


def _relative(residual, scale):
    return float(np.max(np.abs(residual)/np.maximum(scale, np.finfo(float).tiny)))


def _bfbt(k, g, c, gauge, owner, stack, cancel):
    """Equation (8), Rudi/Stadler/Ghattas 2017, arxiv.org/abs/1607.03936.

    C=D is supplied positive weighted velocity mass, or explicitly diag(K).
    Form only L=G.T C^-1 G; apply the middle G.T C^-1 K C^-1 G matrix-free.
    A temporary pressure pin in L solves its compatible constant-null quotient;
    it never changes a physical equation or the requested pressure mean.
    """
    n = g.shape[1]; inverse_c = 1./c
    if not np.isfinite(inverse_c).all():
        raise TectonicsError('BFBT inverse weights are outside finite range')
    if gauge and n == 1:
        return lambda load: np.zeros(1), dict(admitted_bytes=0, retained_factor_bytes=0,
            realised_accounted_bytes=0, factor_nnz=0, poisson_nnz=0)
    degree = np.diff(g.indptr).astype(np.int64)
    support = min(n*n, int(degree@degree))
    if support > 2000000:
        raise TectonicsError('BFBT pressure product exceeds sparse support admission')
    work = 3*(12*support+4*(n+1))+2*_bytes(g)+32*(g.shape[0]+n)
    with owner.reserve(work, category='subduction-bfbt-product'):
        _cancel(cancel)
        weighted = g.copy(); weighted.data *= np.repeat(inverse_c, degree)
        poisson = (g.T@weighted).tocsr(); poisson.sort_indices()
        if gauge:
            poisson = poisson[1:, 1:].tocsr()
        scaling = _positive_symmetric(poisson, 'BFBT pressure Poisson')
        factor, fill = _factor(poisson, scaling, False, owner, stack, cancel)
        fill['poisson_nnz'] = poisson.nnz

    def inverse_poisson(load):
        if gauge:
            compatible = load-float(np.sum(load))/n
            result = np.r_[0., scaling*factor.solve(scaling*compatible[1:])]
            return result-float(np.mean(result))
        return scaling*factor.solve(scaling*load)

    def inverse_schur(load):
        _cancel(cancel)
        first = inverse_poisson(load)
        velocity = inverse_c*(g@first)
        middle = g.T@(inverse_c*(k@velocity))
        return inverse_poisson(middle)
    return inverse_schur, fill


def solve_stokes(k_freevelocity, g_freevelocity_pressure, velocity_rhs, pressure_rhs, *,
                 pressure_mass, pressure_mean_weights=None, velocity_mass_sqrt_eta=None, budget=None, cancel=None):
    """Return immutable (v, p, diagnostics); borrow inputs only during this call.

    Separate exact velocity and BFBT pressure-Poisson LU factors form an upper
    block-triangular right preconditioner. velocity_mass_sqrt_eta supplies the
    positive sqrt(eta)-weighted velocity mass diagonal on free degrees of freedom;
    absent weights select the distinct diag(K)-BFBT method, not weighted-mass BFBT.
    pressure_mass is retained for original-unit symmetric equilibration only.
    At most two true-defect corrections share the 1200-inner-iteration ceiling;
    corrections stop once the equilibrated defect reaches its roundoff scale.
    These are not tolerance or solver fallbacks; full saddle LU is never formed.
    Returned storage belongs to the caller; all factor/work leases end on return.
    """
    _cancel(cancel)
    k = _csr(k_freevelocity, 'velocity stiffness'); g = _csr(g_freevelocity_pressure, 'velocity-pressure coupling')
    m = _csr(pressure_mass, 'inverse-viscosity pressure mass')
    nv, npres = g.shape; gauge = pressure_mean_weights is not None; size = nv+npres+int(gauge)
    if k.shape != (nv, nv) or m.shape != (npres, npres) or size > 65536:
        raise TectonicsError('saddle block dimensions disagree or exceed admission')
    if input_shape(velocity_rhs) != (nv,) or input_shape(pressure_rhs) != (npres,):
        raise TectonicsError('saddle right-hand-side dimensions disagree')
    if gauge and input_shape(pressure_mean_weights) != (npres,):
        raise TectonicsError('pressure mean weights require pressure-node support')
    if velocity_mass_sqrt_eta is not None and input_shape(velocity_mass_sqrt_eta) != (nv,):
        raise TectonicsError('BFBT weights require free-velocity support')
    owner = WorkBudget(_CAP, parent=select_budget(budget))
    scratch = 2*sum(_bytes(a) for a in (k, g, m))+8*32*size+262144
    with ExitStack() as stack:
        stack.enter_context(owner.reserve(scratch, category='subduction-saddle-work'))
        f = read_array(velocity_rhs, 'velocity rhs'); h = read_array(pressure_rhs, 'pressure rhs')
        sk = _positive_symmetric(k, 'velocity stiffness'); sm = _positive_symmetric(m, 'pressure mass')
        c = (k.diagonal() if velocity_mass_sqrt_eta is None else
             read_array(velocity_mass_sqrt_eta, 'BFBT weighted velocity mass'))
        if np.any(c <= 0.):
            raise TectonicsError('BFBT weighted velocity mass must be positive')
        q = None; weight_norm = 1.
        if gauge:
            weights = read_array(pressure_mean_weights, 'pressure mean weights')
            if np.any(weights <= 0.):
                raise TectonicsError('pressure mean weights must be positive')
            weight_norm = float(np.linalg.norm(weights))
            if not math.isfinite(weight_norm) or weight_norm == 0.:
                raise TectonicsError('pressure mean weight norm is outside finite range')
            q = weights/weight_norm
        constant = g@np.ones(npres); constant_scale = np.asarray(abs(g).sum(axis=1)).ravel()
        constant_null = np.max(np.abs(constant)) <= 1e-11*max(float(constant_scale.max()), np.finfo(float).tiny)
        if constant_null != gauge:
            raise TectonicsError('explicit pressure gauge does not match the constant nullspace')
        rhs = np.r_[f, h, [0.]] if gauge else np.r_[f, h]
        rhs_norm = float(np.linalg.norm(rhs))
        if not math.isfinite(rhs_norm):
            raise TectonicsError('saddle right-hand-side norm is nonfinite')
        iterations = 0; applications = 0
        global_correction_v = 0.; global_pressure_shift = 0.; global_before = 0.

        def physical(value):
            _cancel(cancel); v, p = value[:nv], value[nv:nv+npres]
            a, b = k@v+g@p, g.T@v
            return np.r_[a, b+q*value[-1], q@p] if gauge else np.r_[a, b]

        def assess(value, scaling=1.):
            if not np.isfinite(value).all():
                raise TectonicsError('GMRES returned nonfinite physical fields')
            v, p = value[:nv], value[nv:nv+npres]
            rv, rp = k@v+g@p-f, g.T@v-h
            sv = abs(k)@np.abs(v)+abs(g)@np.abs(p)+np.abs(f)
            sp = abs(g.T)@np.abs(v)+np.abs(h)
            # Separate original-unit block backward errors cannot let the
            # high-viscosity momentum scale conceal a continuity defect. Keep
            # rowwise errors diagnostic: zero-flow rows have no relative scale.
            momentum = _relative(rv, float(sv.max()))
            continuity = _relative(rp, float(sp.max()))
            mean = 0. if not gauge else abs(float(q@p))/max(float(np.abs(q)@np.abs(p)), np.finfo(float).tiny)
            relative = float(np.linalg.norm(np.r_[rv, rp]))/max(rhs_norm, np.finfo(float).tiny)
            residual = np.r_[rv, rp+q*value[-1], q@p] if gauge else np.r_[rv, rp]
            magnitude = np.r_[sv, sp+abs(q*value[-1]), np.abs(q)@np.abs(p)] if gauge else np.r_[sv, sp]
            equilibrated = float(np.linalg.norm(scaling*residual))
            roundoff = float(np.finfo(float).eps*np.linalg.norm(scaling*magnitude))
            return dict(linear_residual=max(momentum, continuity, mean), momentum_residual=momentum,
                continuity_residual=continuity, pressure_mean_residual=mean, relative_residual=relative,
                equilibrated_residual=equilibrated, equilibrated_roundoff_scale=roundoff,
                refinement_at_roundoff=equilibrated <= roundoff,
                componentwise_momentum_residual=_relative(rv, sv), componentwise_continuity_residual=_relative(rp, sp),
                global_continuity_residual=math.fsum(rp),
                global_continuity_before_correction=global_before,
                global_continuity_correction_velocity_inf=global_correction_v,
                global_continuity_pressure_shift=global_pressure_shift,
                gauge_multiplier=0. if not gauge else float(value[-1]/weight_norm))

        if rhs_norm == 0.:
            _cancel(cancel)
            return frozen(np.zeros(nv)), frozen(np.zeros(npres)), dict(assess(np.zeros(size)),
                iterations=0, corrections=0, preconditioner_applications=0, method='zero physical rhs')
        # Form the pressure product before holding the larger velocity factor.
        # Both are independent; the temporary product bound need not overlap LU.
        inverse_schur, pressure_fill = _bfbt(k, g, c, gauge, owner, stack, cancel)
        velocity_lu, velocity_fill = _factor(k, sk, True, owner, stack, cancel)
        def inverse_velocity(load):
            return sk*velocity_lu.solve(sk*load)
        global_velocity = None if gauge else inverse_velocity(constant)
        global_denominator = 1. if gauge else math.fsum(constant*global_velocity)
        if not math.isfinite(global_denominator) or global_denominator <= 0.:
            raise TectonicsError('natural-boundary global-continuity mode is not positive')

        def precondition(load):
            nonlocal applications
            _cancel(cancel); applications += 1
            pressure_load = load[nv:nv+npres]; multiplier = 0.
            if gauge:
                multiplier = float(np.sum(pressure_load))/float(q.sum())
                p = -inverse_schur(pressure_load-q*multiplier)
                p += (load[-1]-float(q@p))/float(q.sum())
            else:
                p = -inverse_schur(pressure_load)
            v = inverse_velocity(load[:nv]-g@p)
            result = np.r_[v, p, multiplier] if gauge else np.r_[v, p]
            if not np.isfinite(result).all():
                raise TectonicsError('saddle preconditioner returned nonfinite values')
            return result

        # D A D z = D b, x = D z: balance both equations and unknowns, not
        # merely the factors. The transformed right inverse is
        # D^-1 P^-1 D^-1, giving D A P^-1 D^-1 for outer GMRES.
        equilibration = np.r_[sk, sm, [1./np.linalg.norm(sm*q)]] if gauge else np.r_[sk, sm]
        if not np.isfinite(equilibration).all() or np.any(equilibration <= 0.):
            raise TectonicsError('saddle equation equilibration is outside finite range')
        # Defect corrections must not request another twelve digits below the
        # round-off scale of the original equilibrated equations.
        absolute_target = np.finfo(float).eps*float(np.linalg.norm(equilibration*rhs))
        right = LinearOperator((size, size),
            matvec=lambda y: equilibration*physical(precondition(y/equilibration)), dtype=np.float64)
        def callback(_):
            nonlocal iterations
            iterations += 1; _cancel(cancel)
            if iterations > _ITERATIONS:
                raise TectonicsError('saddle GMRES exceeded 1200 total inner iterations')
        # Arnoldi basis is allocated by GMRES, not by block factorisation.
        stack.enter_context(owner.reserve(8*_RESTART*size, category='subduction-gmres-basis'))
        solution = np.zeros(size); info = 0
        for correction in range(3):
            _cancel(cancel)
            remaining = _ITERATIONS-iterations
            if remaining <= 0:
                break
            defect = equilibration*(rhs-physical(solution))
            answer, info = gmres(right, defect, rtol=1e-12, atol=absolute_target, restart=_RESTART,
                maxiter=remaining, callback=callback, callback_type='legacy')
            solution += precondition(answer/equilibration)
            if gauge:
                # Remove only the constant null mode, including when true p=0.
                pressure = solution[nv:nv+npres]
                pressure -= float(q@pressure)/float(q.sum())
            else:
                # K dv + G dp = 0 for dv=-K^-1 G 1*a, dp=1*a.
                # Enforce the aggregate physical continuity equation without
                # changing momentum, then repeat once for floating-point error.
                for projection in range(2):
                    delta = math.fsum(g.T@solution[:nv]-h)
                    if projection == 0:
                        global_before = delta
                    shift = delta/global_denominator
                    change = -global_velocity*shift
                    solution[:nv] += change
                    solution[nv:nv+npres] += shift
                    global_correction_v += float(np.max(np.abs(change)))
                    global_pressure_shift += shift
            diagnostics = assess(solution, equilibration)
            # A small normwise backward error need not resolve tiny pressure
            # cells. Recompute the true equilibrated defect and refine only
            # above eps*||D (|A||x|+|b|)||, using the already admitted factors.
            # This is a refinement trigger, not a new physical acceptance gate;
            # all corrections remain inside the original iteration/pass bounds.
            refine = not diagnostics['refinement_at_roundoff'] and correction < 2 and iterations < _ITERATIONS
            if (diagnostics['linear_residual'] <= _TOLERANCE and diagnostics['relative_residual'] <= _TOLERANCE
                    and not refine):
                _cancel(cancel)
                return frozen(solution[:nv]), frozen(solution[nv:nv+npres]), dict(diagnostics,
                    iterations=iterations, corrections=correction, gmres_info=int(info),
                    preconditioner_applications=applications, restart=_RESTART, iteration_limit=_ITERATIONS,
                    method='equilibrated right upper-block GMRES; exact velocity LU; '+
                        ('diag(K)-BFBT' if velocity_mass_sqrt_eta is None else 'supplied sqrt(eta)-weighted-mass BFBT'),
                    velocity_factor=velocity_fill, pressure_factor=pressure_fill,
                    peak_accounted_bytes=owner.peak_reserved_bytes)
            if info != 0:
                break
        raise TectonicsError('saddle GMRES failed original physical equations within its fixed iteration/correction budget: '+
            str(dict(diagnostics, iterations=iterations, gmres_info=int(info), corrections=correction)))
