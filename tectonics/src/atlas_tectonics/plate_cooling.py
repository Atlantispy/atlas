"""W03.1: constant-property 1-D finite-plate conduction and cooling histories.

Independent mathematical implementation; no upstream source copied. See
docs/W03_THERMAL_COLUMNS.md for equations, truncation bounds and model limits.
No timestep loop, density/subsidence law, geological-age inference or age floor.
"""
from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import CancelledError
import math

import numpy as np

from ._validation import TectonicsError, read_array, input_shape, frozen, scalar, text
from .parameters import PlateCoolingParameters, identity
from .resources import elements, select_budget
from .thermal import DEFAULT_COOLING_BATCH_ELEMENTS, _batch_count
from .stokes_execution import _factored_scale

# Method switch, not a physical age or a fitted parameter. Both sides solve the
# same PDE to well below binary64 precision in normalised temperature.
_IMAGE_LIMIT = 1. / 16.
_MODES = 9
_SQRT_PI = math.sqrt(math.pi)
_GAUSS_NODES = (-.8611363115940526, -.3399810435848563,
                .3399810435848563, .8611363115940526)
_GAUSS_WEIGHTS = (.3478548451374539, .6521451548625461,
                  .6521451548625461, .3478548451374539)


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError()


def _parameters(parameters):
    if type(parameters) is not PlateCoolingParameters:
        raise TectonicsError('explicit PlateCoolingParameters required')


def plate_cooling_work_bytes(depth_shape, age_shape, bottom_shape=None,
                            batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS):
    count = _batch_count(batch_elements)
    shapes = (depth_shape, age_shape) + (() if bottom_shape is None else (bottom_shape,))
    try:
        size = elements(np.broadcast_shapes(*shapes))
    except ValueError as exc:
        raise TectonicsError('plate cooling inputs cannot broadcast') from exc
    if not size:
        raise TectonicsError('plate cooling inputs must be nonempty')
    return 32*sum(elements(s) for s in shapes) + 24*size + 512*min(count, size) + 8192


def _fourier_age(age, parameters):
    return _factored_scale(age, (parameters.thermal.diffusivity_m2_s,),
                           (parameters.thickness_m, parameters.thickness_m), 'Fourier age')


def _erfc_mean(a, b, erfc):
    """Average erfc on [a,b], a>=0. Stable for arbitrarily thin intervals.

    For width<=.01 use Gauss4 (absolute remainder <6e-21 using |f''''''''|<1e5).
    Else integrate its analytic primitive. Cap only primitive evaluations in the
    negligible tail, not the interval width: erfc(28)<1e-342.
    """
    width = b-a
    narrow = width <= .01
    result = np.empty_like(width)
    if np.any(narrow):
        lo = a[narrow]; w = width[narrow]
        result[narrow] = 0.
        for node, weight in zip(_GAUSS_NODES, _GAUSS_WEIGHTS):
            result[narrow] += .5*weight*erfc(lo + .5*(1+node)*w)
    wide = ~narrow
    if np.any(wide):
        lo = np.minimum(a[wide], 28.); hi = np.minimum(b[wide], 28.)
        flo = lo*erfc(lo)-np.exp(-lo*lo)/_SQRT_PI
        fhi = hi*erfc(hi)-np.exp(-hi*hi)/_SQRT_PI
        result[wide] = (fhi-flo)/width[wide]
    return result


def _young_points(x, scale, erf, erfc):
    # Symmetric image pairs preserve zero at the surface, even for tiny x.
    return (erf(x/scale) + (erfc((2-x)/scale)-erfc((2+x)/scale))
            + (erfc((4-x)/scale)-erfc((4+x)/scale)))


def _fraction(x, age, bottom, erf, erfc):
    """Batched dimensionless point values or exact-cell-integral approximations."""
    result = np.ones_like(x)
    young = (age > 0) & (age <= _IMAGE_LIMIT)
    if np.any(young):
        a = x[young]; scale = 2*np.sqrt(age[young])
        if bottom is None:
            result[young] = _young_points(a, scale, erf, erfc)
        else:
            b = bottom[young]
            total = np.empty_like(a)
            # Direct erf averages retain shallow, tiny nonzero signals which
            # 1-mean(erfc) would erase. The same Gauss4 remainder bound applies.
            narrow = (b-a)/scale <= .01
            wide = ~narrow
            if np.any(wide):
                lo = a[wide]; hi = b[wide]; s = scale[wide]
                total[wide] = (1-_erfc_mean(lo/s, hi/s, erfc)
                    + _erfc_mean((2-hi)/s, (2-lo)/s, erfc)
                    - _erfc_mean((2+lo)/s, (2+hi)/s, erfc)
                    + _erfc_mean((4-hi)/s, (4-lo)/s, erfc)
                    - _erfc_mean((4+lo)/s, (4+hi)/s, erfc))
            if np.any(narrow):
                lo = a[narrow]; width = b[narrow]-lo; s = scale[narrow]
                total[narrow] = 0.
                for node, weight in zip(_GAUSS_NODES, _GAUSS_WEIGHTS):
                    total[narrow] += .5*weight*_young_points(lo+.5*(1+node)*width, s, erf, erfc)
            result[young] = total
    old = age > _IMAGE_LIMIT
    if np.any(old):
        a = x[old]; t = age[old]
        mid = a if bottom is None else a + .5*(bottom[old]-a)
        total = mid.copy()
        for n in range(1, _MODES+1):
            # Overflow in a very old exponent correctly means zero transient.
            with np.errstate(over='ignore'):
                decay = np.exp(-(n*n*math.pi**2)*t)
            term = (2/(n*math.pi))*np.sin(n*math.pi*mid)*decay
            if bottom is not None:
                term *= np.sinc(.5*n*(bottom[old]-a))
            total += term
        result[old] = total
    if bottom is None:
        result[x == 0] = 0.
        result[x == 1] = 1.
    return result


def _column_grid(x, age, bottom, output, parameters, batch, cancel, erf, erfc):
    """Common age-column x depth-grid route: prepare modal depth factors once.

    Separate age and depth factors avoid repeating exp/sin for every output.
    Nine outer products keep the ordinary summation order and need no BLAS pool.
    Scratch is bounded in both axes; no age x depth x mode tensor is retained.
    """
    thermal = parameters.thermal
    for z0 in range(0, x.size, max(1, batch//_MODES)):
        z = x[z0:z0+max(1, batch//_MODES)]
        b = None if bottom is None else bottom[z0:z0+len(z)]
        mid = z if b is None else z+.5*(b-z)
        modes = np.empty((_MODES, len(z)))
        for n in range(1, _MODES+1):
            modes[n-1] = (2/(n*math.pi))*np.sin(n*math.pi*mid)
            if b is not None:
                modes[n-1] *= np.sinc(.5*n*(b-z))
        rows = max(1, batch//len(z))
        for i in range(0, age.size, rows):
            _cancel(cancel)
            f = age[i:i+rows]; target = output[i:i+len(f), z0:z0+len(z)]
            old = f > _IMAGE_LIMIT
            if np.any(old):
                values = np.broadcast_to(mid, (int(np.sum(old)), len(z))).copy()
                for n in range(1, _MODES+1):
                    with np.errstate(over='ignore'):
                        weight = np.exp(-(n*n*math.pi**2)*f[old])
                    values += weight[:, None]*modes[n-1]
                if b is None:
                    values[:, z == 0] = 0.; values[:, z == 1] = 1.
                target[old] = values
            if np.any(~old):
                shape = (int(np.sum(~old)), len(z))
                a = np.broadcast_to(z, shape).reshape(-1)
                t = np.broadcast_to(f[~old, None], shape).reshape(-1)
                ends = None if b is None else np.broadcast_to(b, shape).reshape(-1)
                target[~old] = _fraction(a, t, ends, erf, erfc).reshape(shape)
            target *= thermal.mantle_temperature_k-thermal.surface_temperature_k
            target += thermal.surface_temperature_k


def finite_plate_temperature(depth_m, age_s, parameters, *, cell_bottom_m=None,
                             budget=None, batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS,
                             cancel=None):
    """Point temperatures, or cell means if cell_bottom_m is supplied (SI units).

    Depth is positive downward in [0,L]. A cell spans [depth_m,cell_bottom_m].
    Inputs broadcast. At age zero the interior and every positive-width cell are
    at basal temperature; the surface point is at the prescribed surface value.
    Ages are elapsed cooling time, never formation age. Full output is admitted;
    only scratch is chunked. Results are immutable; caller data are detached.
    """
    _parameters(parameters); _cancel(cancel)
    ds = input_shape(depth_m); ts = input_shape(age_s)
    bs = None if cell_bottom_m is None else input_shape(cell_bottom_m)
    required = plate_cooling_work_bytes(ds, ts, bs, batch_elements)
    with select_budget(budget).reserve(required, category='plate-cooling'):
        try:
            from scipy.special import erf, erfc
        except ImportError as exc:
            raise TectonicsError('plate cooling requires the declared SciPy dependency') from exc
        depth = read_array(depth_m, 'depth_m', nonnegative=True)
        age = read_array(age_s, 'age_s', nonnegative=True)
        bottom = None if bs is None else read_array(cell_bottom_m, 'cell_bottom_m', nonnegative=True)
        if depth.shape != ds or age.shape != ts or (bottom is not None and bottom.shape != bs):
            raise TectonicsError('plate cooling input shape changed during capture')
        length = parameters.thickness_m
        if np.any(depth > length) or (bottom is not None and np.any(bottom > length)):
            raise TectonicsError('depth outside the finite plate; no implicit mantle extension')
        x = _factored_scale(depth, (), (length,), 'normalised depth')
        fo = _fourier_age(age, parameters)
        b = None if bottom is None else _factored_scale(bottom, (), (length,), 'normalised cell bottom')
        inputs = [x, fo] + ([] if b is None else [b])
        shape = np.broadcast_shapes(*(v.shape for v in inputs))
        output = np.empty(shape)
        # Pure execution specialisation: same PDE, endpoints and cell integrals.
        # General broadcasting/strides continue through the bounded iterator.
        column_grid = (fo.ndim == 2 and fo.shape[1] == 1 and
                       (x.ndim == 1 or (x.ndim == 2 and x.shape[0] == 1)) and
                       (b is None or b.shape == x.shape))
        if column_grid:
            if b is not None and np.any(b <= x):
                raise TectonicsError('cell depths must be ordered and numerically distinct')
            _column_grid(x.reshape(-1), fo.reshape(-1), None if b is None else b.reshape(-1),
                         output, parameters, batch_elements, cancel, erf, erfc)
            return frozen(output)
        with np.nditer(inputs+[output], flags=['external_loop', 'buffered'],
                op_flags=[['readonly']]*len(inputs)+[['writeonly', 'no_broadcast']],
                order='C', buffersize=min(batch_elements, elements(shape))) as iterator:
            for buffers in iterator:
                _cancel(cancel)
                top, t = buffers[:2]; end = None if b is None else buffers[2]
                if end is not None and np.any(end <= top):
                    raise TectonicsError('cell depths must be ordered and numerically distinct')
                fraction = _fraction(top, t, end, erf, erfc)
                th = parameters.thermal
                buffers[-1][:] = th.surface_temperature_k + (th.mantle_temperature_k-th.surface_temperature_k)*fraction
        return frozen(output)


def plate_cooling_heat(age_s, parameters, *, budget=None,
                       batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS, cancel=None):
    """Cumulative outward heat at top/base since age zero, final axis=(top,base).

    Units J/m2. Base heat is negative (inflow). No instantaneous age-zero flux is
    fabricated: it is singular, while these integrated accounts are finite.
    Effective constant volumetric heat capacity is conductivity/diffusivity.
    """
    _parameters(parameters); _cancel(cancel)
    shape = input_shape(age_s); size = elements(shape)
    batch = _batch_count(batch_elements)
    if not size:
        raise TectonicsError('nonempty ages required')
    with select_budget(budget).reserve(96*size+256*min(size, batch)+8192, category='plate-heat'):
        from scipy.special import erfcx
        age = read_array(age_s, 'age_s', nonnegative=True)
        if age.shape != shape:
            raise TectonicsError('age shape changed during capture')
        if parameters.thermal.mantle_temperature_k == parameters.thermal.surface_temperature_k:
            return frozen(np.zeros(shape+(2,)))
        fo = _fourier_age(age, parameters).reshape(-1)
        output = np.zeros((size, 2))
        for start in range(0, size, batch):
            _cancel(cancel)
            f = fo[start:start+batch]; out = output[start:start+batch]
            young = (f > 0) & (f <= _IMAGE_LIMIT)
            if np.any(young):
                root = np.sqrt(f[young]); base = root/_SQRT_PI
                top = 2*base; lower = np.zeros_like(root)
                def image_integral(a):
                    u = a/root; value = np.zeros_like(u); active = u < 12.
                    v = u[active]
                    value[active] = base[active]*np.exp(-v*v)*(1-_SQRT_PI*v*erfcx(v))
                    return value
                for m in (1., 2.):
                    top += 4*image_integral(m)
                for m in (.5, 1.5):
                    lower -= 4*image_integral(m)
                out[young, 0] = top; out[young, 1] = lower
            old = f > _IMAGE_LIMIT
            if np.any(old):
                t = f[old]; top = t+1/3; lower = -t+1/6
                for n in range(1, _MODES+1):
                    with np.errstate(over='ignore'):
                        term = (2/(n*n*math.pi**2))*np.exp(-(n*n*math.pi**2)*t)
                    top -= term; lower += (-1)**n*term
                out[old, 0] = top; out[old, 1] = lower
        thermal = parameters.thermal
        output = _factored_scale(output, (parameters.volumetric_heat_capacity_j_m3_k,
            thermal.mantle_temperature_k-thermal.surface_temperature_k, parameters.thickness_m), (), 'plate heat')
        return frozen(output.reshape(shape+(2,)))


@dataclass(frozen=True, slots=True)
class ThermalAgeColumns:
    """Derived model columns. Never an in-place replacement of W01 temperatures."""
    source_state_id: str
    epoch_id: str
    time_s: float
    profile_ids: tuple[str, ...]
    history_source_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    depth_edges_m: np.ndarray
    cooling_age_s: np.ndarray
    mean_temperature_k: np.ndarray
    outward_heat_j_m2: np.ndarray


def plate_cooling_columns(initial_state, models, depth_edges_m, *, time_s, epoch_id,
                          store=None, budget=None, context=None, controller=None,
                          cache_policy=None, cancel=None):
    """Join explicit finite-plate model choices to source-bound cooling histories.

    models maps selected existing profile IDs to PlateCoolingParameters. Selection
    is explicit: unknown/unselected histories are never invented or inferred from
    cohort birth. Existing initial thermal descriptions are NOT asserted to match
    this newly selected ridge-cooling model and are not overwritten. The result
    retains parent state, history sources and model identities for later assembly.
    time_s uses the named case epoch; no implicit year/epoch conversion.
    """
    from .precursor import PrecursorState
    from .reuse import cached_plate_temperature
    from .storage import ArrayStore
    if not isinstance(initial_state, PrecursorState):
        raise TectonicsError('source-bound PrecursorState required')
    _cancel(cancel); text(epoch_id, 'epoch_id')
    if epoch_id != initial_state.case.epoch_id:
        raise TectonicsError('cooling workflow epoch mismatch')
    time_s = scalar(time_s, 'time_s')
    if time_s < initial_state.case.time_s:
        raise TectonicsError('evaluation predates the source state')
    if type(models) is not dict or not models:
        raise TectonicsError('explicit nonempty profile-to-model dictionary required')
    histories = {h.profile_id: h for h in initial_state.cooling_history}
    if any(type(k) is not str or k not in histories for k in models):
        raise TectonicsError('unknown cooling profile selected')
    selected = tuple(sorted(models.items()))
    ages = []; sources = []; ids = []
    for key, model in selected:
        _parameters(model); history = histories[key]
        if history.start_time_s is None:
            raise TectonicsError('unknown cooling history: '+key+'; '+history.unknown_reason)
        ages.append(scalar(time_s-history.start_time_s, 'cooling age', nonnegative=True))
        sources.append(history.source_id); ids.append(identity(model))
    edge_shape = input_shape(depth_edges_m)
    if len(edge_shape) != 1 or edge_shape[0] < 2:
        raise TectonicsError('one-dimensional depth edges required')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    resource = select_budget(budget)
    # Retain only the requested snapshot, never a growing trajectory in a plan.
    with resource.reserve(64*len(selected)*edge_shape[0]+32*edge_shape[0]+8192, category='thermal-age-columns'):
        edges = read_array(depth_edges_m, 'depth_edges_m', nonnegative=True)
        if edges.shape != edge_shape or np.any(np.diff(edges) <= 0):
            raise TectonicsError('strictly increasing depth edges required')
        temperatures = np.empty((len(selected), len(edges)-1))
        heat = np.empty((len(selected), 2))
        groups = {}
        for i, model_id in enumerate(ids):
            groups.setdefault(model_id, []).append(i)
        for indices in groups.values():
            _cancel(cancel)
            model = selected[indices[0]][1]
            if edges[0] != 0 or edges[-1] != model.thickness_m:
                raise TectonicsError('column edges must span exactly the selected plate')
            group_ages = np.array([ages[i] for i in indices])
            temperatures[indices] = cached_plate_temperature(edges[:-1], group_ages[:, None], model,
                cell_bottom_m=edges[1:], store=store, budget=resource, context=context,
                controller=controller, cache_policy=cache_policy, cancel=cancel)
            heat[indices] = plate_cooling_heat(group_ages, model, budget=resource, cancel=cancel)
        return ThermalAgeColumns(initial_state.state_id, epoch_id, time_s,
            tuple(k for k, _ in selected), tuple(sources), tuple(ids), frozen(edges),
            frozen(ages), frozen(temperatures), frozen(heat))
