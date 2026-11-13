"""Decimal80 linearisation and bounded Newton-direction iteration.

These helpers do not change the heat equation or its final residual gates.
They perform no allocation admission: the integrating caller must reserve
``workspace_bytes`` on its existing shared WorkBudget before constructing a
linearisation, and retain that reservation until the linearisation and Krylov
work are discarded. The estimate excludes the caller-owned local HMM entries,
factor/preconditioner and returned arrays. It is accounting, not an RSS cap.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from decimal import Decimal as D, ROUND_HALF_EVEN, localcontext
import hashlib
from pathlib import Path

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def assert_current():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise ValueError('Newton direction source changed during solve')
    return _LOADED


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise CancelledError('Decimal Newton direction cancelled')


def _vector(values, size=None):
    result = tuple(map(D, values))
    if (size is not None and len(result) != size) or any(not x.is_finite() for x in result):
        raise ValueError('finite complete Decimal vector required')
    return result


def _sign(value):
    return D(1) if value > 0 else D(-1) if value < 0 else D(0)


def workspace_bytes(size, max_basis=32):
    """Conservative simultaneous derivative/GMRES allowance, before building.

    Two bases (Arnoldi vectors and their right-preconditioned vectors), dense
    Hessenberg/rotation workspace and twenty additional full vectors. At most
    512 bytes per Decimal80 value/slot and 1024 per unknown for containers and
    local traversal temporaries. No edge table or persistent cache is built.
    """
    if type(size) is not int or size < 0 or type(max_basis) is not int or max_basis < 1:
        raise ValueError('nonnegative size and positive basis limit required')
    basis = min(size, max_basis)
    return 1024**2+512*((2*basis+20)*size+(basis+1)*basis+12*basis)+1024*size


def prepare_scheme2_derivative(local, state, fixed, *, local_faces, cancel=None):
    """Prepare a selected linearisation of K*u plus Scheme 2 graph correction.

    ``local_faces`` must be the current precision solver's original
    ``_local_faces`` operation; local entries/geometry remain caller-owned.
    State force, denominators and ratios are computed once per linearisation.
    At nonzero forces/differences this is the exact derivative formula,
    evaluated in rounded Decimal80 arithmetic. At kinks use sign(0)=0; when
    D_i=0 set r_i=dr_i=0. This is a selected linear map at such states, not a
    claim that the nonlinear action has that one-sided directional derivative.
    Fixed nodes have r_i=dr_i=0, as in the existing Scheme 2 correction; their
    output rows are not eliminated here. The caller selects its free rows.
    """
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        _cancel(cancel)
        state = _vector(state)
        size, zero = len(state), D(0)
        fixed = frozenset(fixed)
        if any(type(i) is not int or not 0 <= i < size for i in fixed):
            raise ValueError('fixed node outside Decimal state')
        force, denominator = [zero]*size, [zero]*size
        for entry in local:
            _cancel(cancel)
            ci, indexes = entry[:2]
            flux = local_faces(state, entry)
            force[ci] -= sum(flux, zero)
            for j, value in zip(indexes, flux):
                force[j] += value
            ids = (ci, *indexes)
            for at, i in enumerate(ids):
                for j in ids[at+1:]:
                    difference = abs(state[i]-state[j])
                    denominator[i] += difference
                    denominator[j] += difference
        ratio = tuple(abs(f)/d if d and i not in fixed else zero
                      for i, (f, d) in enumerate(zip(force, denominator)))
        force_sign = tuple(map(_sign, force))
        denominator = tuple(denominator)

    def action(direction):
        with localcontext() as context:
            context.prec, context.rounding = 80, ROUND_HALF_EVEN
            _cancel(cancel)
            direction = _vector(direction, size)
            dforce, ddenominator = [zero]*size, [zero]*size
            for entry in local:
                _cancel(cancel)
                ci, indexes = entry[:2]
                flux = local_faces(direction, entry)
                dforce[ci] -= sum(flux, zero)
                for j, value in zip(indexes, flux):
                    dforce[j] += value
                ids = (ci, *indexes)
                for at, i in enumerate(ids):
                    for j in ids[at+1:]:
                        difference = _sign(state[i]-state[j])*(direction[i]-direction[j])
                        ddenominator[i] += difference
                        ddenominator[j] += difference
            dratio = [(s*df-r*dd)/d if d and i not in fixed else zero
                      for i, (s, df, r, dd, d) in enumerate(
                          zip(force_sign, dforce, ratio, ddenominator, denominator))]
            result = dforce
            for entry in local:
                _cancel(cancel)
                ids = (entry[0], *entry[1])
                for at, i in enumerate(ids):
                    for j in ids[at+1:]:
                        amount = ((ratio[i]+ratio[j])*(direction[i]-direction[j])
                                  +(dratio[i]+dratio[j])*(state[i]-state[j]))
                        result[i] += amount
                        result[j] -= amount
            return result
    return action


def scheme2_derivative(local, state, direction, fixed, *, local_faces, cancel=None):
    """One-shot convenience; Krylov callers should prepare once and reuse."""
    return prepare_scheme2_derivative(local, state, fixed, local_faces=local_faces,
                                     cancel=cancel)(direction)


def gmres(action, precondition, rhs, *, cancel=None, max_basis=32, max_restarts=3,
          relative_target=D('0.1')):
    """Bounded restarted right-preconditioned GMRES, zero initial direction.

    Two-pass modified Gram-Schmidt limits loss of Arnoldi orthogonality.
    Accept a direction only using the recomputed, unpreconditioned L2 residual,
    never the small Hessenberg residual alone. ``relative_target`` controls
    only this inner direction solve. A nonconverged bounded result is returned
    explicitly so the caller can reject it; it never accepts a heat state.
    Maximum Arnoldi steps are min(size,max_basis)*(max_restarts+1), plus one
    true-residual action per completed cycle. Cancellation and callback errors
    propagate to the caller's existing resource owner.
    """
    if type(max_basis) is not int or max_basis < 1 or type(max_restarts) is not int or max_restarts < 0:
        raise ValueError('positive basis and nonnegative restart limits required')
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        _cancel(cancel)
        rhs = _vector(rhs)
        relative_target = D(relative_target)
        if not relative_target.is_finite() or not 0 < relative_target < 1:
            raise ValueError('inner relative target must be finite and between zero and one')
        zero, one, size = D(0), D(1), len(rhs)
        dot = lambda a, b: sum((x*y for x, y in zip(a, b)), zero)
        norm = lambda a: dot(a, a).sqrt()
        rhs_norm = norm(rhs)
        target = relative_target*rhs_norm
        x, residual = [zero]*size, list(rhs)
        residual_norm = rhs_norm
        steps, cycles, action_calls, precondition_calls = 0, 0, 0, 0

        def report(converged, reason):
            return dict(solution=x, converged=converged, iterations=steps,
                        restarts=max(0, cycles-1), reason=reason,
                        residual_norm_decimal=str(residual_norm),
                        relative_residual_decimal=str(residual_norm/rhs_norm if rhs_norm else zero),
                        target_norm_decimal=str(target), action_calls=action_calls,
                        precondition_calls=precondition_calls)

        if not rhs_norm:
            return report(True, 'zero rhs')
        basis_limit = min(max_basis, size)
        for _ in range(max_restarts+1):
            _cancel(cancel)
            cycles += 1
            v, z = [[value/residual_norm for value in residual]], []
            h = [[zero]*basis_limit for _ in range(basis_limit+1)]
            cosine, sine = [], []
            g = [residual_norm]+[zero]*basis_limit
            built, breakdown = 0, False
            for j in range(basis_limit):
                _cancel(cancel)
                z.append(_vector(precondition(v[j]), size))
                precondition_calls += 1
                _cancel(cancel)
                w = list(_vector(action(z[-1]), size))
                action_calls += 1
                steps += 1
                for _ in range(2):
                    for i in range(j+1):
                        _cancel(cancel)
                        coefficient = dot(v[i], w)
                        h[i][j] += coefficient
                        w = [a-coefficient*b for a, b in zip(w, v[i])]
                following_norm = norm(w)
                h[j+1][j] = following_norm
                if following_norm:
                    v.append([value/following_norm for value in w])
                for i in range(j):
                    upper, lower = h[i][j], h[i+1][j]
                    h[i][j] = cosine[i]*upper+sine[i]*lower
                    h[i+1][j] = -sine[i]*upper+cosine[i]*lower
                upper, lower = h[j][j], h[j+1][j]
                rotation_norm = (upper*upper+lower*lower).sqrt()
                if not rotation_norm:
                    breakdown = True
                    break
                cosine.append(upper/rotation_norm)
                sine.append(lower/rotation_norm)
                h[j][j], h[j+1][j] = rotation_norm, zero
                g[j+1], g[j] = -sine[j]*g[j], cosine[j]*g[j]
                built = j+1
                breakdown = not following_norm
                if abs(g[j+1]) <= target or breakdown:
                    break
            if not built:
                return report(False, 'Arnoldi breakdown')
            y = [zero]*built
            for i in range(built-1, -1, -1):
                y[i] = (g[i]-sum((h[i][j]*y[j] for j in range(i+1, built)), zero))/h[i][i]
            x = [value+sum((y[j]*z[j][i] for j in range(built)), zero) for i, value in enumerate(x)]
            _cancel(cancel)
            ax = _vector(action(x), size)
            action_calls += 1
            residual = [b-a for b, a in zip(rhs, ax)]
            residual_norm = norm(residual)
            if residual_norm <= target:
                return report(True, 'recomputed residual')
            if breakdown:
                return report(False, 'Arnoldi breakdown')
        return report(False, 'iteration limit')


