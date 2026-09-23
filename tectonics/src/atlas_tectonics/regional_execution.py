"""W07 source-bound regional mechanical snapshots and prepared reuse.

SPDX-License-Identifier: AGPL-3.0-only
Explicit SI inputs, no geological force inference or time integration. This is
the public execution boundary; regional_stokes is the numerical implementation.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, asdict
import hashlib
import json
import threading

import numpy as np

from ._validation import TectonicsError, scalar, text, input_shape, read_array, frozen
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext
from .constitutive import _cancel, _json
from .stokes_execution import _native_lease, _factored_scale


def _name(value, name):
    text(value, name)
    if len(value) > 512:
        raise TectonicsError(name+' exceeds the metadata envelope')
    return value


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _array_hash(value):
    return hashlib.sha256(value.tobytes(order='C')).hexdigest()


@dataclass(frozen=True, slots=True)
class RegionalMechanicsScales:
    """Explicit length and velocity scales; viscosity supplies the stress scale."""
    length_m: float
    velocity_m_s: float

    def __post_init__(self):
        for key in ('length_m', 'velocity_m_s'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))


@dataclass(frozen=True, slots=True)
class RegionalReferencePressure:
    """P_ref(z)=top_pressure_pa+density_times_gravity_n_m3*(height-z)."""
    top_pressure_pa: float
    density_times_gravity_n_m3: float
    source: str

    def __post_init__(self):
        object.__setattr__(self, 'top_pressure_pa', scalar(self.top_pressure_pa, 'reference top pressure'))
        object.__setattr__(self, 'density_times_gravity_n_m3', scalar(
            self.density_times_gravity_n_m3, 'reference density times gravity', nonnegative=True))
        _name(self.source, 'reference pressure source')


class RegionalMechanicalSnapshot:
    """Immutable steady outputs; accepted snapshots are not evolving checkpoints."""
    __slots__ = ('_metadata', '_fields', 'result_id')

    def __init__(self, metadata, arrays):
        encoded = _json(metadata)
        fields = tuple((key, tuple(value.shape), frozen(value).tobytes())
                       for key, value in sorted(arrays.items()))
        object.__setattr__(self, '_metadata', encoded)
        object.__setattr__(self, '_fields', fields)
        object.__setattr__(self, 'result_id', _hash({'metadata': metadata,
            'arrays': {key: {'shape': shape, 'sha256': hashlib.sha256(raw).hexdigest()}
                       for key, shape, raw in fields}}))

    def __setattr__(self, name, value):
        raise TectonicsError('regional mechanical snapshots are immutable')

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def array_names(self):
        return tuple(key for key, _, _ in self._fields)

    @property
    def nbytes(self):
        return sum(len(raw) for _, _, raw in self._fields)+len(self._metadata)

    def array(self, name):
        for key, shape, raw in self._fields:
            if key == name:
                return np.frombuffer(raw, dtype=np.float64).reshape(shape)
        raise TectonicsError('unknown regional mechanical field')


class PreparedRegionalStokes2D:
    """One-thread, source-bound rectangular Newtonian mechanical plan.

    Boundary values are sampled arrays, not persisted Python callbacks. Pattern,
    scales, material and pressure convention bind the prepared operator. Changed
    loads reuse its factors; a single identical latest request reuses its verified
    immutable output. No unbounded field/history cache is created.
    """
    def __init__(self, nx, nz, width_m, height_m, viscosity_pa_s, boundary_types, *,
                 scales, frame_id, vertical_datum, material_source,
                 physical_mean_pressure_pa=None, reference_pressure=None,
                 rigid_constraints=None, method='gmres', budget=None, cancel=None,
                 viscosity_center_pa_s=None, viscosity_vertex_pa_s=None,
                 material_sampling=None):
        from .regional_stokes import prepare_mac
        for value, name in ((nx, 'nx'), (nz, 'nz')):
            if type(value) is not int or not 2 <= value <= 64:
                raise TectonicsError(name+' requires an integer from 2 to 64 for this regional implementation')
        width_m = scalar(width_m, 'width', positive=True)
        height_m = scalar(height_m, 'height', positive=True)
        viscosity_pa_s = scalar(viscosity_pa_s, 'viscosity', positive=True)
        if type(scales) is not RegionalMechanicsScales:
            raise TectonicsError('explicit RegionalMechanicsScales required')
        for value, name in ((frame_id, 'frame'), (vertical_datum, 'vertical datum'),
                            (material_source, 'material source')):
            _name(value, name)
        if reference_pressure is not None and type(reference_pressure) is not RegionalReferencePressure:
            raise TectonicsError('typed reference pressure required')
        pattern = self._pattern(boundary_types)
        gauge = all(pattern[side][component] == 'velocity'
                    for side, component in (('left', 'u'), ('right', 'u'), ('bottom', 'w'), ('top', 'w')))
        if physical_mean_pressure_pa is not None:
            physical_mean_pressure_pa = scalar(physical_mean_pressure_pa, 'physical mean pressure')
            if not gauge:
                raise TectonicsError('normal traction already fixes pressure; additional datum forbidden')
        if gauge and reference_pressure is not None and physical_mean_pressure_pa is None:
            raise TectonicsError('velocity-only reference pressure requires an explicit physical mean datum')
        if method not in ('gmres', 'direct'):
            raise TectonicsError('regional method must be gmres or explicit direct')
        upper = 3*nx*nz+4*(nx+nz)+16
        retained = 8*1024**2+4096*upper+(64*upper**2 if method == 'direct' else 0)
        object.__setattr__(self, '_closed', False)
        self._active = False
        self._invalid = False
        self._lock = threading.Lock()
        self._owner = threading.get_ident()
        self._context = self._core = self._latest = None
        self._latest_key = None
        self._stats = {'solves': 0, 'latest_result_hits': 0}
        self._upper = upper
        self._retained_allowance = retained
        self._resource = WorkBudget(128*1024**2, parent=select_budget(budget))
        self._guard = self._resource.reserve(retained, category='regional-mechanics-prepared')
        self._guard.__enter__()
        try:
            _cancel(cancel)
            self._definition = {'schema': 'atlas.regional-mechanics-plan.v1',
                'nx': nx, 'nz': nz, 'width_m': width_m, 'height_m': height_m,
                'viscosity_pa_s': viscosity_pa_s, 'boundary_types': pattern,
                'scales': asdict(scales), 'frame_id': frame_id, 'vertical_datum': vertical_datum,
                'material_source': material_source, 'physical_mean_pressure_pa': physical_mean_pressure_pa,
                'reference_pressure': None if reference_pressure is None else asdict(reference_pressure),
                'rigid_constraints': rigid_constraints, 'method': method,
                'coordinates': 'Cartesian x-right z-up; bottom z=0', 'units': 'SI',
                'pressure_gauge_required': gauge}
            # Private JSON freezes all caller-owned dictionaries before preparation.
            self._definition = json.loads(_json(self._definition))
            ec,ev,sampling=self._capture_viscosity(viscosity_center_pa_s,
                viscosity_vertex_pa_s,material_sampling,nx,nz)
            self._viscosity=(ec,ev)
            self._definition['stress_site_viscosity']=None if ec is None else {
                'centre_sha256':_array_hash(ec),'vertex_sha256':_array_hash(ev),
                'sampling':sampling,'units':'Pa s'}
            self._context = ExecutionContext('scipy')
            self._context_id = self._context.identity
            self._plan_id = _hash({'definition': self._definition, 'context': self._context_id})
            zero_boundary = {side: {c: (kind, 0.) for c, kind in components.items()}
                             for side, components in pattern.items()}
            dimension = _factored_scale(np.array([width_m, height_m]), (), (scales.length_m,), 'scaled dimensions')
            with _native_lease():
                self._core = prepare_mac(nx, nz, float(dimension[0]), float(dimension[1]),
                    1. if ec is None else None, zero_boundary, pressure_mean=0. if gauge else None,
                    **({} if ec is None else dict(
                        eta_center=_factored_scale(ec,(),(viscosity_pa_s,),'scaled centre viscosity'),
                        eta_vertex=_factored_scale(ev,(),(viscosity_pa_s,),'scaled vertex viscosity'))),
                    rigid_constraints=rigid_constraints, method=method,
                    linear_rtol=1e-12, max_iterations=1200, restart=60, cancel=cancel)
            _cancel(cancel)
            self._context.verify()
        except BaseException:
            self._context = self._core = None
            self._closed = True
            self._guard.__exit__(None, None, None)
            raise

    @staticmethod
    def _capture_viscosity(centre,vertex,sampling,nx,nz):
        if centre is None and vertex is None:
            if sampling is not None:
                raise TectonicsError('sampling without explicit stress-site viscosity')
            return None,None,None
        if input_shape(centre)!=(nz,nx) or input_shape(vertex)!=(nz+1,nx+1):
            raise TectonicsError('both centre and shear-vertex viscosity arrays required')
        _name(sampling,'material sampling law')
        ec=read_array(centre,'centre viscosity');ev=read_array(vertex,'vertex viscosity')
        if np.any(ec<=0) or np.any(ev<=0):
            raise TectonicsError('positive stress-site viscosity required')
        return frozen(ec),frozen(ev),sampling

    def update_viscosity(self,centre_pa_s,vertex_pa_s,*,material_source,material_sampling,cancel=None):
        """Refill current coefficients, retaining geometry; never retain stale physics.

        Identical values may retain factors; changed provenance still changes the
        plan and latest-result identity. A failed refill invalidates result reuse.
        """
        _name(material_source,'material source')
        d=self._definition
        with self._operation(cancel),self._resource.reserve(self._retained_allowance,
                                                           category='regional-viscosity-refill'):
            ec,ev,sampling=self._capture_viscosity(centre_pa_s,vertex_pa_s,material_sampling,d['nx'],d['nz'])
            if ec is None:raise TectonicsError('explicit coefficients required for refill')
            oldc,oldv=self._viscosity
            same=(oldc is not None and np.array_equal(oldc,ec) and np.array_equal(oldv,ev))
            if not same:
                nc=_factored_scale(ec,(),(d['viscosity_pa_s'],),'scaled centre viscosity')
                nv=_factored_scale(ev,(),(d['viscosity_pa_s'],),'scaled vertex viscosity')
                self._invalid=True
                self._core.refill_viscosity(eta_center=nc,eta_vertex=nv,cancel=cancel)
                self._stats['coefficient_refills']=self._stats.get('coefficient_refills',0)+1
            else:
                self._stats['coefficient_reuse_hits']=self._stats.get('coefficient_reuse_hits',0)+1
            self._context.verify();_cancel(cancel)
            updated=dict(d,material_source=material_source,stress_site_viscosity={
                'centre_sha256':_array_hash(ec),'vertex_sha256':_array_hash(ev),
                'sampling':sampling,'units':'Pa s'})
            unchanged = same and updated == d
            self._definition=updated;self._viscosity=(ec,ev)
            self._plan_id=_hash({'definition':updated,'context':self._context_id})
            if not unchanged:
                self._latest_key=self._latest=None
            self._invalid=False
        return self._plan_id

    @staticmethod
    def _pattern(boundary_types):
        if not isinstance(boundary_types, dict) or set(boundary_types) != {'left', 'right', 'bottom', 'top'}:
            raise TectonicsError('all four regional boundaries are required')
        out = {}
        for side in ('left', 'right', 'bottom', 'top'):
            components = boundary_types[side]
            if not isinstance(components, dict) or set(components) != {'u', 'w'}:
                raise TectonicsError('one condition for each boundary component required')
            out[side] = {}
            for c in ('u', 'w'):
                if components[c] not in ('velocity', 'traction'):
                    raise TectonicsError('component condition must be velocity or traction')
                out[side][c] = components[c]
        return out

    @property
    def plan_id(self):
        return self._plan_id

    def descriptor(self):
        return json.loads(_json(self._definition))

    def statistics(self):
        return dict(self._stats, budget=self._resource.statistics())

    def coordinates(self, location):
        from .regional_stokes import boundary_coordinates
        d = self._definition
        with self._operation(None), self._resource.reserve(64*(d['nx']+d['nz']+4), category='regional-coordinates'):
            if isinstance(location, tuple) and len(location) == 2:
                x, z = boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], *location)
                return frozen(x), frozen(z)
            if location not in ('u', 'w', 'p'):
                raise TectonicsError('regional location must be u, w, p or (side,component)')
            x = (np.arange(d['nx']+1) if location == 'u' else np.arange(d['nx'])+.5)*d['width_m']/d['nx']
            z = (np.arange(d['nz']+1) if location == 'w' else np.arange(d['nz'])+.5)*d['height_m']/d['nz']
            return frozen(x), frozen(z)

    @contextmanager
    def _operation(self, cancel):
        with self._lock:
            if self._closed or self._invalid or self._active or self._owner != threading.get_ident():
                raise TectonicsError('closed/active regional plan or wrong driving thread')
            self._active = True
        try:
            _cancel(cancel)
            self._context.verify()
            with _native_lease():
                yield
            _cancel(cancel)
            self._context.verify()
        except BaseException:
            # A failed final cancellation/source check cannot leave a newly
            # accepted latest-result entry available to the next invocation.
            self._latest_key = self._latest = None
            raise
        finally:
            with self._lock:
                self._active = False

    def __enter__(self):
        if self._closed:
            raise TectonicsError('regional plan is closed')
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._active or self._owner != threading.get_ident():
                raise TectonicsError('join regional work and close on the driving thread')
            self._closed = True
        try:
            self._context.close()
        finally:
            self._core = self._latest = self._context = None
            self._guard.__exit__(None, None, None)

    def solve(self, force_u_n_m3, force_w_n_m3, boundary_values, *,
              frame_id, epoch_id, time_s, force_source, boundary_source, cancel=None):
        """Solve supplied steady forces/motion exactly once, in their named frame.

        Body forces occupy full staggered faces, including half-volume boundary
        faces. Boundary normal components use face centres plus two corner trace
        values; tangential components use vertices. Use ``coordinates`` to sample
        these supports. Material/time evolution is not inferred by this snapshot.
        """
        from .regional_stokes import boundary_coordinates
        d = self._definition
        if frame_id != d['frame_id']:
            raise TectonicsError('regional forcing frame mismatch')
        for value, name in ((epoch_id, 'epoch'), (force_source, 'force source'),
                            (boundary_source, 'boundary source')):
            _name(value, name)
        time_s = scalar(time_s, 'snapshot time')
        if input_shape(force_u_n_m3) != (d['nz'], d['nx']+1) or input_shape(force_w_n_m3) != (d['nz']+1, d['nx']):
            raise TectonicsError('regional body forces require full staggered face shapes')
        if not isinstance(boundary_values, dict) or set(boundary_values) != set(d['boundary_types']):
            raise TectonicsError('all regional boundary values required')
        with self._operation(cancel), self._resource.reserve(1024*self._upper+262144,
                                                            category='regional-mechanics-solve'):
            fx = read_array(force_u_n_m3, 'regional horizontal force')
            fz = read_array(force_w_n_m3, 'regional vertical force')
            boundary = {}
            for side, components in d['boundary_types'].items():
                given = boundary_values[side]
                if not isinstance(given, dict) or set(given) != {'u', 'w'}:
                    raise TectonicsError('complete component values required')
                boundary[side] = {}
                for component, kind in components.items():
                    x, z = boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], side, component)
                    shape = input_shape(given[component])
                    if shape == ():
                        value = np.full(x.shape, scalar(given[component], 'boundary value'))
                    elif shape == x.shape:
                        value = read_array(given[component], 'boundary '+side+' '+component)
                    else:
                        raise TectonicsError('boundary samples do not match declared supports')
                    boundary[side][component] = value
            request = {'plan_id': self._plan_id, 'epoch_id': epoch_id, 'time_s': time_s,
                'force_source': force_source, 'boundary_source': boundary_source,
                'forces': {'u': _array_hash(fx), 'w': _array_hash(fz)},
                'boundary': {side: {c: _array_hash(value) for c, value in parts.items()}
                             for side, parts in boundary.items()}}
            key = _hash(request)
            if key == self._latest_key:
                self._stats['latest_result_hits'] += 1
                return self._latest
            length, velocity = d['scales']['length_m'], d['scales']['velocity_m_s']
            eta = d['viscosity_pa_s']
            reference = d['reference_pressure']
            top, rho_g = (0., 0.) if reference is None else (
                reference['top_pressure_pa'], reference['density_times_gravity_n_m3'])
            def pref(z):
                with np.errstate(over='raise', invalid='raise'):
                    try:
                        value = top+rho_g*(d['height_m']-z)
                    except FloatingPointError as exc:
                        raise TectonicsError('reference pressure is outside binary64') from exc
                if not np.isfinite(value).all():
                    raise TectonicsError('nonfinite reference pressure')
                return value
            with np.errstate(over='raise', invalid='raise'):
                try:
                    effective_fz = fz+rho_g
                except FloatingPointError as exc:
                    raise TectonicsError('effective body force outside binary64') from exc
            nu = _factored_scale(fx, (length, length), (eta, velocity), 'scaled horizontal force')
            nw = _factored_scale(effective_fz, (length, length), (eta, velocity), 'scaled vertical force')
            normalised_boundary = {}
            normals = {'left': (-1., 0.), 'right': (1., 0.), 'bottom': (0., -1.), 'top': (0., 1.)}
            for side, parts in boundary.items():
                normalised_boundary[side] = {}
                for component, value in parts.items():
                    kind = d['boundary_types'][side][component]
                    if kind == 'velocity':
                        scaled = _factored_scale(value, (), (velocity,), 'scaled boundary motion')
                    else:
                        _, z = boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], side, component)
                        normal = normals[side][0 if component == 'u' else 1]
                        effective = value+normal*pref(z)
                        scaled = _factored_scale(effective, (length,), (eta, velocity), 'scaled boundary traction')
                    normalised_boundary[side][component] = (kind, scaled)
            raw = self._core.solve(nu, nw, boundaries=normalised_boundary, cancel=cancel)
            _cancel(cancel)
            arrays = {'force_u_n_m3': fx, 'force_w_n_m3': fz,
                      'u_m_s': _factored_scale(raw['u'], (velocity,), (), 'published u'),
                      'w_m_s': _factored_scale(raw['w'], (velocity,), (), 'published w'),
                      'dynamic_pressure_pa': _factored_scale(raw['p'], (eta, velocity), (length,), 'published pressure')}
            if self._viscosity[0] is not None:
                arrays['viscosity_center_pa_s'],arrays['viscosity_vertex_pa_s']=self._viscosity
            # Re-evaluate the current equations using exactly the published
            # dimensional values, not merely the pre-conversion Krylov iterate.
            published = {name: _factored_scale(arrays[field], numerator, denominator, 'returned '+name)
                for name, field, numerator, denominator in (
                    ('u', 'u_m_s', (), (velocity,)), ('w', 'w_m_s', (), (velocity,)),
                    ('p', 'dynamic_pressure_pa', (length,), (eta, velocity)))}
            physical_vector = _factored_scale(raw['velocity_vector'], (velocity,), (), 'published velocity traces')
            returned_vector = _factored_scale(physical_vector, (), (velocity,), 'returned velocity traces')
            checked = self._core.evaluate(returned_vector, published['p'], nu, nw,
                                           boundaries=normalised_boundary, cancel=cancel)
            if not np.array_equal(checked['u'], published['u']) or not np.array_equal(checked['w'], published['w']):
                raise TectonicsError('published face and trace velocity conversion disagrees')
            diagnostics = {name: value.tolist() if isinstance(value, np.ndarray) else
                           value.item() if isinstance(value, np.generic) else value
                           for name, value in checked['diagnostics'].items()}
            if diagnostics.get('gates_passed') is not True:
                raise TectonicsError('returned regional fields failed the frozen mechanics gates')
            diagnostics['linear_residual'] = float(raw['diagnostics']['linear_residual'])
            if diagnostics['linear_residual'] > 1e-12:
                raise TectonicsError('regional true algebraic residual exceeds 1e-12')
            dimensional = {}
            for name in ('dissipation', 'body_work', 'prescribed_traction_work',
                         'reaction_work', 'total_boundary_work', 'work_residual'):
                dimensional[name+'_w_per_m'] = float(_factored_scale(np.asarray(diagnostics[name]),
                    (eta, velocity, velocity), (), 'dimensional mechanical power'))
            dimensional['net_boundary_flux_m2_s'] = float(_factored_scale(
                np.asarray(diagnostics['net_boundary_flux']), (velocity, length), (), 'dimensional boundary flux'))
            dimensional['net_force_n_per_m'] = _factored_scale(
                np.asarray(diagnostics['net_force']), (eta, velocity), (), 'dimensional net force').tolist()
            dimensional['net_torque_n'] = float(_factored_scale(
                np.asarray(diagnostics['net_torque']), (eta, velocity, length), (), 'dimensional torque'))
            dimensional['max_free_force_residual_n_per_m'] = float(_factored_scale(
                np.asarray(diagnostics['max_free_force_residual']), (eta, velocity), (), 'dimensional force residual'))
            dimensional['max_divergence_s_1'] = float(_factored_scale(
                np.asarray(diagnostics['max_divergence']), (velocity,), (length,), 'dimensional divergence'))
            arrays['effective_boundary_reaction_force_n_per_m'] = _factored_scale(
                checked['boundary_reactions'], (eta, velocity), (), 'dimensional boundary reactions')
            arrays['reaction_coordinates_m'] = _factored_scale(
                checked['reaction_coordinates'], (length,), (), 'dimensional reaction coordinates')
            arrays['reaction_measures_m'] = _factored_scale(
                checked['reaction_measures'], (length,), (), 'dimensional reaction measures')
            zc = (np.arange(d['nz'])+.5)*d['height_m']/d['nz']
            reference_p = np.broadcast_to(pref(zc[:, None]), raw['p'].shape)
            datum = d['physical_mean_pressure_pa']
            offset = 0. if datum is None else datum-float(np.mean(reference_p))
            known_pressure = not d['pressure_gauge_required'] or datum is not None
            total_p = arrays['dynamic_pressure_pa']+reference_p+offset
            if known_pressure:
                arrays['physical_pressure_pa'] = total_p
            for axis in ('xx', 'zz', 'xz'):
                arrays['strain_'+axis+'_s_1'] = _factored_scale(checked['e'+axis], (velocity,), (length,), 'published strain')
                arrays['deviatoric_stress_'+axis+'_pa'] = _factored_scale(checked['tau_'+axis], (eta, velocity), (length,), 'published stress')
                pressure = 0. if axis == 'xz' else total_p
                arrays['stress_'+axis+'_pa'] = arrays['deviatoric_stress_'+axis+'_pa']-pressure
            arrays['stress_yy_pa'] = -total_p
            for side, parts in boundary.items():
                for component, value in parts.items():
                    suffix = side+'_'+component
                    arrays['boundary_input_'+suffix] = value
                    arrays['boundary_velocity_'+suffix+'_m_s'] = _factored_scale(
                        checked['boundary_velocities'][side][component], (velocity,), (), 'published boundary velocity')
                    _, z = boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], side, component)
                    normal = normals[side][0 if component == 'u' else 1]
                    effective_t = _factored_scale(checked['boundary_tractions'][side][component],
                                                 (eta, velocity), (length,), 'published boundary traction')
                    arrays['boundary_traction_'+suffix+'_pa'] = effective_t-normal*(pref(z)+offset)
            metadata = {'schema': 'atlas.regional-mechanical-snapshot.v1', 'source_status': 'WORKING NON-CANON',
                'definition': d, 'request': request, 'request_id': key, 'context_id': self._context_id,
                'physical_pressure_defined': known_pressure,
                'stress_pressure_convention': 'physical' if known_pressure else 'declared-zero-mean-gauge',
                'field_support': {'u': 'vertical faces', 'w': 'horizontal faces',
                    'pressure_normal_strain_stress': 'cell centres', 'shear_strain_stress': 'vertices',
                    'boundaries': 'normal: corners+face centres; tangential: vertices',
                    'effective_boundary_reaction_force': 'full trace ordering: u[z=0,centres,H;x=vertices], then w[z=vertices;x=0,centres,W]; split-pressure equation'},
                'diagnostics': diagnostics, 'diagnostics_units': 'dimensionless core coordinates and explicit normalisations',
                'dimensional_diagnostics': dimensional,
                'diagnostic_force_work_convention': 'split-pressure equation, per unit strike width',
                'iterations': int(raw['iterations']),
                'steady_snapshot': True, 'time_advanced': False}
            result = RegionalMechanicalSnapshot(metadata, arrays)
            _cancel(cancel)
            self._context.verify()
            self._stats['solves'] += 1
            self._latest_key, self._latest = key, result
            return result
