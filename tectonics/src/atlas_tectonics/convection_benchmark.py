"""R4.4 published-case inputs and independently reconstructed diagnostics.

SPDX-License-Identifier: AGPL-3.0-only

Tosi et al. (2015), doi:10.1002/2015GC005807, equations 11--21 and Tables
1--2. This is diagnostic/benchmark machinery, not a replacement PDE solver.
All quantities returned here are dimensionless. Published targets and the
separate acceptance record live in cases/convection_r4_4.json. No function
in this module can confer full benchmark acceptance on an isolated snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from ._validation import TectonicsError
from .constitutive import (BoussinesqMaterial, DiffusiveScales, RheologyProfile,
                           evaluate_rheology, reference_rheology)
from .resources import select_budget
from .stokes import StokesBox2D, face_force_from_density
from .thermochemical import (ThermochemicalProblem, ThermalBoundary2D, _check_fields)

_DOI = '10.1002/2015GC005807'
_METRICS = ('temperature_mean', 'Nu_top', 'Nu_bottom', 'velocity_rms',
            'surface_velocity_rms', 'surface_velocity_max', 'viscosity_min',
            'viscosity_max', 'work', 'dissipation_over_Ra')


@dataclass(frozen=True, slots=True)
class TosiCase:
    """The published family, including each separately identified 5b yield value."""
    name: str
    yield_stress: float | None = None

    def __post_init__(self):
        if self.name not in ('tosi-1', 'tosi-2', 'tosi-3', 'tosi-4', 'tosi-5a', 'tosi-5b'):
            raise TectonicsError('unknown published Tosi case')
        if self.name == 'tosi-5b':
            y = self.yield_stress
            if (isinstance(y, bool) or not isinstance(y, (float, int)) or
                    not math.isfinite(y) or not 3 <= y <= 5 or
                    abs(y * 10 - round(y * 10)) > 4e-14):
                raise TectonicsError('case 5b requires an explicit yield in 3.0..5.0, spacing 0.1')
            object.__setattr__(self, 'yield_stress', float(y))
        elif self.yield_stress is not None:
            raise TectonicsError('only case 5b takes a variable yield stress')

    def rheology(self):
        if self.name != 'tosi-5b':
            return reference_rheology(self.name)
        return RheologyProfile('tosi-5b-yield-' + format(self.yield_stress, '.1f'),
            'tosi-plastic', _DOI + ' Table 1 case 5b',
            (('contrast_T', 1e5), ('contrast_z', 10.), ('eta_star', .001),
             ('sigma_y', self.yield_stress)))

    def problem(self, cells: int):
        _grid(cells)
        scales = DiffusiveScales('r4-4-unit-scales', 1., 1., 1., 1., 1., 1.)
        material = BoussinesqMaterial('r4-4-numerical-embedding',
            'Unit Tosi equations, not an Earth material calibration',
            1., 1., 1., .01, 1., 0., 0., (1., 2.))
        return ThermochemicalProblem(
            StokesBox2D(cells, cells, 1., 1., 'r4-4-tosi-unit-box'), material,
            ThermalBoundary2D('fixed-top-bottom', 2., 1.), self.rheology(), scales,
            (0., -10000.), 'r4-4-time-origin', 'explicit-zero-passive-constituent',
            _DOI + ' equation 11/Table 1; warm-upward R3 force convention',
            mechanical_mode='variable-r4.3')


def _grid(n):
    if type(n) is not int or not 2 <= n <= 256:
        raise TectonicsError('benchmark grid must have 2..256 cells on each side')


def tosi_initial_temperature(cells: int, *, budget=None):
    """Exact finite-volume cell averages of Eq. 11, embedded as T_K=1+theta."""
    _grid(cells)
    with select_budget(budget).reserve(64 * cells * cells + 65536,
                                      category='convection-initial'):
        x = (np.arange(cells) + .5) / cells
        z = x[:, None]
        # sinc factors are integrals of each trigonometric factor over a cell.
        return 2 - z + .01 * np.sinc(.5 / cells)**2 * np.cos(np.pi*x) * np.sin(np.pi*z)


def tosi_endpoint_flow(state, prepared, *, budget=None, cancel=None):
    """Solve the accepted endpoint; an earlier RK-stage flow is not its flow."""
    problem = state.problem
    if prepared.box != problem.box or prepared.scales != problem.scales:
        raise TectonicsError('endpoint mechanics belongs to another box or scale set')
    T = state.array('temperature_k')
    C = state.array('composition')
    rho, _ = _check_fields(problem, T, C)
    fx, fz = face_force_from_density(problem.box, rho, problem.gravity_m_s2, budget=budget)
    return prepared.solve_rheology(fx, fz, T, problem.rheology,
        frame_id=problem.box.frame_id, epoch_id=problem.epoch_id,
        time_s=state.time_s, source='R4.4 accepted endpoint ' + state.state_id, cancel=cancel)


def _array(value, shape, label):
    # No mutation, clipping, silent broadcasting or nonfinite diagnostics.
    a = np.asarray(value, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise TectonicsError('finite correctly shaped ' + label + ' required')
    return a


def _wall_viscosities(profile, theta, exx, ezz, *, budget=None):
    """Free-slip boundary samples, not unobserved subcell extrema.

    Normal strains use the nearest cell-centre value at each wall (second
    order at a smooth free-slip wall); wall shear is exactly zero. Corners
    use the adjacent cell. Fixed-wall temperatures are exact, not cell
    temperatures mistaken for boundary values. Side temperatures use the
    insulated nearest-cell reconstruction. Depth is measured downwards.
    """
    n = len(theta)
    z = (np.arange(n) + .5) / n
    T = np.concatenate((np.ones(n), np.zeros(n), theta[:, 0], theta[:, -1],
                        [1., 1., 0., 0.]))
    depth = np.concatenate((np.ones(n), np.zeros(n), 1-z, 1-z, [1., 1., 0., 0.]))
    e = np.hypot(exx, ezz) / math.sqrt(2)
    rate = np.concatenate((e[0], e[-1], e[:, 0], e[:, -1],
                           [e[0, 0], e[0, -1], e[-1, 0], e[-1, -1]]))
    return evaluate_rheology(profile, T, depth, rate, budget=budget)['viscosity']


def convection_diagnostics(temperature, u, w, viscosity_cell, viscosity_vertex,
                           profile: RheologyProfile, *, budget=None):
    """Independent unit-box MAC quadratures for published Eqs. 12--21.

    theta is a cell average, u/w are normal face velocities, eta is on normal
    and shear stress supports. RMS uses dual-cell/trapezoidal MAC quadrature.
    Surface tangential velocity uses the nearest row and zero side endpoints.
    Nu is the *instantaneous* half-cell finite-volume wall flux, not the
    interval-integrated heat ledger. Raw Phi and Phi/Ra are both retained.
    """
    shape = np.shape(temperature)
    if len(shape) != 2 or shape[0] != shape[1]:
        raise TectonicsError('square unit-box cell field required')
    n = shape[0]
    _grid(n)
    if type(profile) is not RheologyProfile or profile.family not in ('tosi-linear', 'tosi-plastic'):
        raise TectonicsError('explicit Tosi rheology required')
    if profile.viscosity_bounds is not None:
        raise TectonicsError('published cases do not use numerical viscosity clipping')
    with select_budget(budget).reserve(320*n*n + 65536, category='convection-diagnostics'):
        T = _array(temperature, (n, n), 'dimensionless temperature')
        a = _array(u, (n, n+1), 'horizontal velocity')
        b = _array(w, (n+1, n), 'vertical velocity')
        c = _array(viscosity_cell, (n, n), 'cell viscosity')
        v = _array(viscosity_vertex, (n-1, n-1), 'vertex viscosity')
        if np.any((T < 0) | (T > 1)) or np.any(c <= 0) or np.any(v <= 0):
            raise TectonicsError('temperature/rheology outside published domain')
        if np.any(a[:, [0, -1]]) or np.any(b[[0, -1]]):
            raise TectonicsError('impermeable normal walls required')
        exx = np.diff(a, axis=1)*n
        ezz = np.diff(b, axis=0)*n
        gamma = (np.diff(a[:, 1:-1], axis=0) + np.diff(b[1:-1], axis=1))*n
        work = float(np.sum(T*(b[:-1]+b[1:]))/(2*n*n))
        phi = float((np.sum(2*c*(exx*exx+ezz*ezz)) + np.sum(v*gamma*gamma))/(n*n))
        wall = _wall_viscosities(profile, T, exx, ezz, budget=budget)
        scaled = phi/100.
        denominator = max(abs(work), abs(scaled))
        # Signed work is also returned. Negative work cannot pass the comparator.
        delta = 0. if denominator == 0 else 100*abs(work-scaled)/denominator
        out = {
            'temperature_mean': float(T.mean()),
            'Nu_top': float(2*n*T[-1].mean()),
            'Nu_bottom': float(2*n*(1-T[0]).mean()),
            'velocity_rms': float(np.sqrt((np.sum(a*a)+np.sum(b*b))/(n*n))),
            'surface_velocity_rms': float(np.sqrt(np.sum(a[-1]*a[-1])/n)),
            'surface_velocity_max': float(np.max(a[-1])),
            'surface_speed_max': float(np.max(np.abs(a[-1]))),
            'viscosity_min': float(min(c.min(), v.min(), wall.min())),
            'viscosity_max': float(max(c.max(), v.max(), wall.max())),
            'stress_support_viscosity_min': float(min(c.min(), v.min())),
            'stress_support_viscosity_max': float(max(c.max(), v.max())),
            'work': work, 'dissipation': phi, 'dissipation_over_Ra': scaled,
            'work_dissipation_percent': delta,
            'divergence_linf': float(np.max(np.abs(exx+ezz))),
            'temperature_min_cell': float(T.min()), 'temperature_max_cell': float(T.max()),
        }
        if not all(math.isfinite(value) for value in out.values()):
            raise TectonicsError('diagnostic arithmetic overflow')
        return out


def tosi_state_diagnostics(state, flow, *, budget=None):
    """Bind a diagnostic to the actual state, simultaneous flow and published case."""
    problem = state.problem
    desc = flow.descriptor()
    b, s = problem.box, problem.scales
    if (b.nx != b.nz or b.width_m != 1 or b.height_m != 1 or
            (s.length_m, s.diffusivity_m2_s, s.viscosity_pa_s,
             s.surface_temperature_k, s.temperature_scale_k, s.depth_scale_m) != (1.,)*6 or
            problem.gravity_m_s2 != (0., -10000.) or
            problem.boundary != ThermalBoundary2D('fixed-top-bottom', 2., 1.) or
            problem.material.density_kg_m3 != 1. or problem.material.expansion_per_k != .01 or
            problem.material.heat_capacity_j_kg_k != 1. or problem.material.conductivity_w_m_k != 1. or
            problem.material.reference_temperature_k != 1. or
            problem.material.composition_density_contrast_kg_m3 != 0.):
        raise TectonicsError('diagnostics require the declared unit numerical embedding')
    if (desc['time_s'] != state.time_s or desc['epoch_id'] != problem.epoch_id or
            desc['box'] != problem.descriptor()['box'] or
            desc['rheology']['profile_id'] != problem.rheology.profile_id or
            not np.array_equal(flow.array('temperature_k'), state.array('temperature_k'))):
        raise TectonicsError('flow is not the simultaneous state/temperature/rheology')
    if np.any(state.array('composition')) or np.any(flow.array('clipped_cell')) or np.any(flow.array('clipped_vertex')):
        raise TectonicsError('published case requires zero passive constituent and no clipping')
    rho, _ = _check_fields(problem, state.array('temperature_k'), state.array('composition'))
    fx, fz = face_force_from_density(b, rho, problem.gravity_m_s2, budget=budget)
    if not np.array_equal(fx, flow.array('force_x_n_m3')) or not np.array_equal(fz, flow.array('force_z_n_m3')):
        raise TectonicsError('flow force does not match the accepted benchmark temperature')
    out = convection_diagnostics(state.array('temperature_k')-1,
        flow.array('u_m_s'), flow.array('w_m_s'), flow.array('viscosity_cell_pa_s'),
        flow.array('viscosity_vertex_pa_s'), problem.rheology, budget=budget)
    return dict(time=state.time_s, step=state.step_index, state_id=state.state_id,
                flow_id=flow.result_id, diagnostics=out,
                convention='atlas.tosi-mac-diagnostics.v1', full_benchmark_accepted=False)


def _series(times, values):
    t = np.asarray(times, dtype=float)
    x = np.asarray(values, dtype=float)
    if (t.ndim != 1 or x.shape != t.shape or len(t) < 3 or
            not np.isfinite(t).all() or not np.isfinite(x).all() or
            np.any(np.diff(t) <= 0)):
        raise TectonicsError('finite strictly increasing times and matching samples required')
    return t, x


def steady_window(times, metrics, *, minimum_time=.1, window=.05,
                  relative_range=1e-4, absolute_range=1e-8, minimum_samples=101):
    """Conservative predeclared sample-range gate, not proof of steady flow.

    Every diagnostic in _METRICS must be supplied. The gate sees the entire
    final window, not merely coincident endpoints of an oscillation. Full
    acceptance additionally requires field, mesh, timestep and nonlinear checks.
    """
    for value in (minimum_time, window, relative_range, absolute_range):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise TectonicsError('positive finite steady-window policy required')
    if type(minimum_samples) is not int or minimum_samples < 3:
        raise TectonicsError('at least three steady samples required')
    if set(metrics) != set(_METRICS):
        raise TectonicsError('complete published steady diagnostic series required')
    t, _ = _series(times, metrics[_METRICS[0]])
    mask = t >= t[-1]-window
    enough = bool(t[-1] >= minimum_time and t[0] <= t[-1]-window and mask.sum() >= minimum_samples)
    changes = {}
    for key in _METRICS:
        _, x = _series(t, metrics[key])
        y = x[mask]
        scale = max(float(np.max(np.abs(y))), absolute_range/relative_range)
        changes[key] = float(np.ptp(y)/scale)
    return {'sufficient_history': enough, 'sample_count': int(mask.sum()),
            'relative_ranges': changes,
            'steady_samples': bool(enough and all(x <= relative_range for x in changes.values())),
            'full_benchmark_accepted': False}


def periodic_window(times, values, *, cycles=10, period_relative_range=.01,
                    extrema_relative_range=.01, minimum_relative_amplitude=.01,
                    samples_per_period=100):
    """Resolve at least the declared number of stable cycles without smoothing.

    Local peak times use a three-point parabola on a uniform sample grid;
    extrema remain actual sampled values. Peaks adjacent to an end point are
    excluded. This is a period/extrema screening gate, not automatic regime or
    field convergence. Stable Nu cycles must be cross-checked against the other
    published signals and mesh/time/nonlinear studies.
    """
    if type(cycles) is not int or cycles < 2 or type(samples_per_period) is not int or samples_per_period < 10:
        raise TectonicsError('finite multi-cycle sampling policy required')
    for z in (period_relative_range, extrema_relative_range, minimum_relative_amplitude):
        if isinstance(z, bool) or not math.isfinite(z) or not 0 < z < 1:
            raise TectonicsError('periodic relative thresholds must be in (0,1)')
    t, x = _series(times, values)
    dt = float(np.mean(np.diff(t)))
    if not np.allclose(np.diff(t), dt, rtol=1e-7, atol=16*np.finfo(float).eps*max(1., abs(t[-1]))):
        raise TectonicsError('period extraction requires uniformly sampled times')
    peaks = np.flatnonzero((x[1:-1] > x[:-2]) & (x[1:-1] >= x[2:]))+1
    if len(peaks) < cycles+1:
        return {'periodic_samples': False, 'complete_cycles': max(0, len(peaks)-1),
                'reason': 'insufficient resolved cycles', 'full_benchmark_accepted': False}
    peaks = peaks[-cycles-1:]
    den = x[peaks-1]-2*x[peaks]+x[peaks+1]
    offset = .5*(x[peaks-1]-x[peaks+1])/den
    tp = t[peaks]+dt*offset
    periods = np.diff(tp)
    lows = np.array([x[a:b+1].min() for a, b in zip(peaks[:-1], peaks[1:])])
    highs = x[peaks[1:]]
    scale = max(float(np.max(np.abs(x[peaks[0]:peaks[-1]+1]))), np.finfo(float).tiny)
    period = float(periods.mean())
    stable = (float(np.ptp(periods))/period <= period_relative_range and
              float(np.ptp(lows))/scale <= extrema_relative_range and
              float(np.ptp(highs))/scale <= extrema_relative_range and
              float((highs-lows).min())/scale >= minimum_relative_amplitude and
              period/dt >= samples_per_period)
    return {'periodic_samples': bool(stable), 'complete_cycles': cycles,
            'period': period, 'period_range_relative': float(np.ptp(periods)/period),
            'minimum': float(lows.min()), 'maximum': float(highs.max()),
            'mean_cycle_peak': float(highs.mean()), 'samples_per_period': period/dt,
            'first_cycle_time': float(tp[0]), 'last_cycle_time': float(tp[-1]),
            'full_benchmark_accepted': False}


def refinement_differences(coarse, middle, fine):
    """Diagnostic-wise changes for a *declared* ordered three-run study.

    No convergence order is invented for zero, non-monotone or roundoff-scale
    differences. The caller must supply matched case/time/phase and refinement
    metadata; these numbers alone cannot establish adequacy.
    """
    if not coarse or set(coarse) != set(middle) or set(coarse) != set(fine):
        raise TectonicsError('matching nonempty diagnostic sets required')
    result = {}
    for key in coarse:
        a, b, c = (float(obj[key]) for obj in (coarse, middle, fine))
        if not all(math.isfinite(x) for x in (a, b, c)):
            raise TectonicsError('finite refinement diagnostics required')
        d1, d2 = b-a, c-b
        scale = max(abs(c), 1e-14)
        order = None
        if d1*d2 > 0 and abs(d2) > 32*np.finfo(float).eps*max(1., scale):
            order = math.log2(abs(d1/d2))
        result[key] = {'coarse_to_middle': abs(d1)/scale, 'middle_to_fine': abs(d2)/scale,
                       'observed_order_if_ratio_two': order}
    return result
