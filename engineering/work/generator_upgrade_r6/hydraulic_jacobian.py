"""Prepared analytic derivatives of the retained mixed-Richards spatial laws.

This helper imports no soil-water module. ``prepare`` snapshots validated
R6-compatible column/forcing/boundary objects; their identities remain exposed
so the calling integrator can reject a stale kernel. No geometry, coefficients,
root weights, time integration or acceptance tolerances are changed here.

Primary equation references (accessed 2026-09-10):
https://www.ars.usda.gov/pacific-west-area/riverside-ca/agricultural-water-efficiency-and-salinity-research-unit/docs/model/rosetta-hydraulic-functions/
https://doi.org/10.1029/WR026i007p01483
https://docs.scipy.org/doc/scipy-1.16.0/reference/generated/scipy.optimize.least_squares.html

VG/Mualem derivatives below are algebraically differentiated from those laws,
not fitted. The existing bounded l>=0 regime is retained; USDA's broader signed
connectivity alternatives are not silently adopted. Head>=0 selects saturated
derivatives (zero C and dK/dh). At exact atmospheric/Feddes switches we select
the imposed-flux/plateau branch derivative. These are one-sided/generalised
derivatives at nonsmooth points, not claims of classical differentiability.
"""
from dataclasses import dataclass
import math
import numpy as np


def _scalar(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(name+' requires an explicit finite scalar')
    try:
        out = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(name+' is not representable') from exc
    if not math.isfinite(out):
        raise ValueError(name+' requires finite data')
    return out


def _readonly(values):
    out = np.array(values, dtype=float, copy=True)
    out.setflags(write=False)
    return out


def _vector(value, size, name):
    raw = np.asarray(value)
    if raw.shape != (size,) or raw.dtype.kind not in 'fiu':
        raise ValueError(name+' must be a real finite vector matching all cells')
    out = np.asarray(raw, dtype=float)
    if not np.all(np.isfinite(out)):
        raise ValueError(name+' requires finite values')
    return out


@dataclass(frozen=True)
class Fluxes:
    theta: np.ndarray
    q: np.ndarray
    sink: np.ndarray
    flux_jacobian: np.ndarray
    sink_derivative: np.ndarray
    capacity: np.ndarray
    conductivity: np.ndarray
    conductivity_derivative: np.ndarray


@dataclass(frozen=True)
class Kernel:
    column: object
    forcing: object
    boundary: object
    dz: np.ndarray
    theta_r: np.ndarray
    theta_s: np.ndarray
    alpha: np.ndarray
    n: np.ndarray
    m: np.ndarray
    connectivity: np.ndarray
    ksat: np.ndarray
    surface_input: float
    potential_et: float
    weights: np.ndarray
    stress_heads: tuple | None
    bottom_kind: str
    bottom_head: float | None

    def properties(self, head):
        """Return theta, K, analytic dtheta/dh and dK/dh, all per cell.

        log(1-Se**(1/m))=-logaddexp(0,-n*log(alpha*abs(h)))
        avoids both near-saturation cancellation and dry-tail loss. Constitutive
        values implement the same law as R5; binary64 rounding need not be
        bit-identical to its scalar evaluation. Nonfinite derivatives reject.
        """
        h = _vector(head, len(self.dz), 'pressure head')
        theta, conductivity = self.theta_s.copy(), self.ksat.copy()
        capacity = np.zeros(len(h)); derivative = np.zeros(len(h))
        use = h < 0
        if np.any(use):
            try:
                with np.errstate(over='raise', invalid='raise', divide='ignore', under='ignore'):
                    a, n, m = self.alpha[use], self.n[use], self.m[use]
                    log_h = np.log(-h[use])
                    log_x = n*(np.log(a)+log_h)
                    log_one_plus_x = np.logaddexp(0., log_x)
                    log_t = -np.logaddexp(0., -log_x)  # t=x/(1+x)
                    log_se = -m*log_one_plus_x
                    se = np.exp(log_se)
                    theta[use] = self.theta_r[use]+(self.theta_s[use]-self.theta_r[use])*se
                    bracket = -np.expm1(m*log_t)
                    log_b = np.log(bracket)
                    log_a = np.log(m*n)+log_t-log_h  # dlog(Se)/dh
                    log_b_prime = np.log(m*n)+m*log_t-log_one_plus_x-log_h
                    capacity[use] = np.exp(np.log(self.theta_s[use]-self.theta_r[use])+log_se+log_a)
                    log_k = np.log(self.ksat[use])+self.connectivity[use]*log_se+2*log_b
                    conductivity[use] = np.exp(log_k)
                    # K'=Ks Se**l (l*dlogSe/dh*b**2 + 2*b*b').
                    log_sum = np.logaddexp(np.log(self.connectivity[use])+log_a+2*log_b,
                                          math.log(2.)+log_b+log_b_prime)
                    derivative[use] = np.exp(np.log(self.ksat[use])+self.connectivity[use]*log_se+log_sum)
            except FloatingPointError as exc:
                raise ValueError('unrepresentable analytic hydraulic law/derivative') from exc
        if (not all(np.all(np.isfinite(v)) for v in (theta, conductivity, capacity, derivative))
                or np.any(theta < self.theta_r) or np.any(theta > self.theta_s)
                or np.any(conductivity < 0) or np.any(conductivity > self.ksat*(1+1e-14))
                or np.any(capacity < 0) or np.any(derivative < 0)):
            raise ValueError('analytic hydraulic law/derivative outside finite admitted regime')
        return theta, conductivity, capacity, derivative

    def fluxes(self, head):
        """Same shared Darcy faces/Feddes uptake, plus analytic head derivatives."""
        h = _vector(head, len(self.dz), 'pressure head')
        theta, k, capacity, dk = self.properties(h)
        size = len(h)
        q = np.zeros(size+1); dq = np.zeros((size+1, size))
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
                top_factor = 1-h[0]/(self.dz[0]/2)
                top_cap = k[0]*top_factor
                if top_cap < self.surface_input:
                    q[0] = top_cap
                    dq[0, 0] = dk[0]*top_factor-k[0]/(self.dz[0]/2)
                else:
                    q[0] = self.surface_input
                wet_faces = (k[:-1] > 0) & (k[1:] > 0)
                left = np.flatnonzero(wet_faces)
                if len(left):
                    right = left+1
                    rl = self.dz[left]/(2*k[left]); rr = self.dz[right]/(2*k[right])
                    resistance = rl+rr
                    conductance = 1/resistance
                    distance = (self.dz[left]+self.dz[right])/2
                    q[right] = conductance*(distance-h[right]+h[left])
                    # dG/dh = G * fractional half-cell resistance * dlogK/dh.
                    dq[right, left] = conductance+q[right]*(rl/resistance)*(dk[left]/k[left])
                    dq[right, right] = -conductance+q[right]*(rr/resistance)*(dk[right]/k[right])
                if self.bottom_kind == 'free_drainage':
                    q[-1] = k[-1]; dq[-1, -1] = dk[-1]
                elif self.bottom_kind == 'fixed_head':
                    factor = 1-(self.bottom_head-h[-1])/(self.dz[-1]/2)
                    q[-1] = k[-1]*factor
                    dq[-1, -1] = dk[-1]*factor+k[-1]/(self.dz[-1]/2)
                stress, ds = np.zeros(size), np.zeros(size)
                if self.stress_heads is not None:
                    dry0, dry1, wet1, wet0 = self.stress_heads
                    stress = np.minimum(np.clip((h-dry0)/(dry1-dry0), 0, 1),
                                        np.clip((wet0-h)/(wet0-wet1), 0, 1))
                    rising = (h > dry0) & (h < dry1)
                    falling = (h > wet1) & (h < wet0)
                    ds[rising] = 1/(dry1-dry0); ds[falling] = -1/(wet0-wet1)
                sink = self.potential_et*self.weights*stress
                derivative = self.potential_et*self.weights*ds
        except FloatingPointError as exc:
            raise ValueError('unrepresentable analytic Darcy/uptake derivative') from exc
        if not all(np.all(np.isfinite(v)) for v in (q, dq, sink, derivative)):
            raise ValueError('nonfinite analytic Darcy/uptake derivative')
        return Fluxes(theta, q, sink, dq, derivative, capacity, k, dk)

    def residual_and_jacobian(self, head, theta_old, dt):
        """Mixed BE residual [m] and its dense tridiagonal Jacobian [m/m]."""
        old = _vector(theta_old, len(self.dz), 'old water fraction')
        seconds = _scalar(dt, 'implicit time step')
        if seconds <= 0 or np.any(old < self.theta_r) or np.any(old > self.theta_s):
            raise ValueError('positive time and physically bounded old water fractions required')
        state = self.fluxes(head)
        try:
            with np.errstate(over='raise', invalid='raise'):
                residual = (state.theta-old)*self.dz-seconds*(state.q[:-1]-state.q[1:]-state.sink)
                jac = -seconds*(state.flux_jacobian[:-1]-state.flux_jacobian[1:])
                diagonal = np.arange(len(self.dz))
                jac[diagonal, diagonal] += state.capacity*self.dz+seconds*state.sink_derivative
        except FloatingPointError as exc:
            raise ValueError('unrepresentable mixed residual/Jacobian') from exc
        if not np.all(np.isfinite(residual)) or not np.all(np.isfinite(jac)):
            raise ValueError('nonfinite mixed residual/Jacobian')
        return residual, jac


def prepare(column, forcing, boundary):
    """Prepare once per fixed column/forcing/boundary; no imported API cycle."""
    layers = tuple(column.layers)
    if not 1 <= len(layers) <= 128 or not all(layer.known for layer in layers):
        raise ValueError('bounded known hydraulic layers required')
    names = ('thickness_m', 'theta_r', 'theta_s', 'alpha_per_m', 'n', 'mualem_l', 'ksat_m_s')
    dz, tr, ts, alpha, n, connectivity, ksat = (
        _readonly([_scalar(getattr(layer, name), name) for layer in layers]) for name in names)
    if (np.any(dz <= 0) or np.any(tr < 0) or np.any(ts <= tr) or np.any(ts > 1)
            or np.any(alpha <= 0) or np.any(n <= 1) or np.any(connectivity < 0) or np.any(ksat < 0)):
        raise ValueError('invalid bounded hydraulic parameter range')
    surface = _scalar(forcing.surface_input_m_s, 'surface input')
    et = _scalar(forcing.potential_et_m_s, 'potential uptake')
    if surface < 0 or et < 0:
        raise ValueError('surface input and potential uptake must be nonnegative')
    if any(getattr(item, 'source_status', None) == 'UNKNOWN' for item in (column, forcing, boundary)):
        raise ValueError('UNKNOWN is not zero hydraulic forcing')
    root = column.root_boundary_index
    if type(root) is not int or not 1 <= root <= len(layers):
        raise ValueError('explicit root boundary face required')
    if forcing.uptake is None:
        if et:
            raise ValueError('positive demand requires explicit uptake law')
        weights, stress = _readonly(np.zeros(len(layers))), None
    else:
        uptake = forcing.uptake
        if getattr(uptake, 'source_status', None) == 'UNKNOWN':
            raise ValueError('UNKNOWN root law')
        weights = _readonly(_vector(uptake.weights, len(layers), 'root weights'))
        stress = tuple(_scalar(getattr(uptake, name), name) for name in
                       ('dry_zero_head_m', 'dry_full_head_m', 'wet_full_head_m', 'wet_zero_head_m'))
        if (np.any(weights < 0) or abs(math.fsum(weights)-1) > 8*math.ulp(1.)
                or np.any(weights[root:] > 0) or not stress[0] < stress[1] <= stress[2] < stress[3] <= 0):
            raise ValueError('invalid root weights/bounded stress law')
    kind, bottom = boundary.kind, boundary.head_m
    if kind == 'fixed_head':
        bottom = _scalar(bottom, 'fixed lower head')
    elif kind not in ('free_drainage', 'no_flow') or bottom is not None:
        raise ValueError('explicit supported lower boundary required')
    return Kernel(column, forcing, boundary, dz, tr, ts, alpha, n, _readonly(1-1/n),
                  connectivity, ksat, surface, et, weights, stress, kind, bottom)
