"""Fixed-box 3D mechanics/material/heat coupling, with explicit split time steps.

SPDX-License-Identifier: AGPL-3.0-only

Reuses the declared Boussinesq material and registered constitutive laws. This
is not moving-surface, elastic, fracture or spherical evolution. Every advance
solves start mechanics, carries mass/enthalpy/scalar memory, conducts heat, then
solves endpoint mechanics from the changed material state. No hidden substeps.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import threading

import numpy as np

from ._validation import TectonicsError, scalar, frozen
from .constitutive import (BoussinesqMaterial, DiffusiveScales, RheologyProfile,
    evaluate_rheology, advance_memory, boussinesq_response)
from .regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from .regional_execution3d import (PreparedRegionalStokes3D, SIDES, _array, _cancel,
    _name, _json, _hash, _digest_array, _local_tokens)
from .regional_transport3d import PreparedRegionalTransport3D
from .regional_heat3d import PreparedRegionalHeat3D
from .resources import select_budget
from .reuse import ExecutionContext

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class RegionalEvolutionAdvance3D:
    state: RegionalMechanicalSnapshot
    initial_mechanics: RegionalMechanicalSnapshot
    mechanics: RegionalMechanicalSnapshot
    transport: object
    heat: object
    _metadata: bytes

    def descriptor(self):
        return json.loads(self._metadata)


class PreparedRegionalEvolution3D:
    """One owner; one last mechanical operator, not an accumulating history.

    Reference density/cp/k are constant as required by this Boussinesq route.
    Composition changes buoyancy, not reference mass. Temperature, depth, strain
    rate and (for BF23) carried damage determine viscosity at all Gauss points.
    Temperature and damage are cell averages, piecewise constant at those points.
    Pressure and supplied tractions are dynamic (reference hydrostatics removed).
    """

    def __setattr__(self, key, value):
        if not key.startswith('_') and hasattr(self, key):
            raise TectonicsError('prepared regional evolution definition is immutable')
        object.__setattr__(self, key, value)

    def __init__(self, cells, lengths_m, material, profile, constitutive_scales,
                 mechanical_scales, boundary_types, *, composition_values,
                 frame_id, vertical_datum, include_viscous_heating,
                 divergence_rtol, max_velocity_correction_m_s,
                 max_relative_correction, budget=None, cancel=None):
        if type(material) is not BoussinesqMaterial or type(profile) is not RheologyProfile:
            raise TectonicsError('explicit registered material and rheology required')
        if type(constitutive_scales) is not DiffusiveScales or type(mechanical_scales) is not RegionalMechanicsScales:
            raise TectonicsError('explicit constitutive and mechanical scales required')
        if type(include_viscous_heating) is not bool:
            raise TectonicsError('declare whether viscous dissipation is converted to heat')
        _name(frame_id, 'frame'); _name(vertical_datum, 'vertical datum')
        if type(boundary_types) is not dict or set(boundary_types) != set(SIDES):
            raise TectonicsError('declare all six mechanical sides')
        if any(len(v) != 3 or any(k not in ('velocity', 'traction') for k in v)
               for v in boundary_types.values()):
            raise TectonicsError('three velocity/traction components per side required')
        c = np.asarray(composition_values)
        if c.ndim != 1 or not 1 <= c.size <= 16:
            raise TectonicsError('one to sixteen component composition values required')
        c = _array(c, c.shape, 'component composition')
        if np.any((c < 0) | (c > 1)):
            raise TectonicsError('Boussinesq composition values must lie in [0,1]')
        self._closed = self._active = False
        self._owner = threading.get_ident()
        self._resource = select_budget(budget)
        self._transport = self._heat = self._mechanical = None
        self._eta = self._last = self._guard = None
        self._stats = dict(mechanical_preparations=0, mechanical_reuses=0,
                           endpoint_cache_hits=0, accepted_intervals=0)
        try:
            self._transport = PreparedRegionalTransport3D(cells, lengths_m,
                divergence_rtol=divergence_rtol,
                max_velocity_correction_m_s=max_velocity_correction_m_s,
                max_relative_correction=max_relative_correction,
                budget=self._resource, cancel=cancel)
            self.cells, self.lengths_m = tuple(cells), tuple(float(x) for x in lengths_m)
            self._n = int(np.prod(cells))
            guard = self._resource.reserve(65536+4096*self._n, category='regional-evolution3d')
            guard.__enter__()
            self._guard = guard
            self._material, self._profile, self._cs, self._ms = material, profile, constitutive_scales, mechanical_scales
            self._composition = c
            self._pattern = {k: tuple(v) for k, v in boundary_types.items()}
            self._volume = float(np.prod(np.asarray(lengths_m)/cells))
            self._mass = material.density_kg_m3*self._volume
            self._heating = include_viscous_heating
            self._frame, self._datum = frame_id, vertical_datum
            self._heat = PreparedRegionalHeat3D(cells, lengths_m,
                material.density_kg_m3*material.heat_capacity_j_kg_k,
                material.conductivity_w_m_k, budget=self._resource)
            nodes, weights = np.polynomial.legendre.leggauss(3)
            ijk = np.indices(cells).reshape(3, -1).T
            ref = np.indices((3, 3, 3)).reshape(3, -1).T
            q = (ijk[:, None, :]+(nodes[ref][None, :, :]+1)/2)*(np.asarray(lengths_m)/cells)
            self._depth = frozen((lengths_m[2]-q[..., 2])/constitutive_scales.depth_scale_m)
            self._weights = frozen(np.prod(weights[ref], axis=1)/8.)
            if np.any((self._depth < 0) | (self._depth > 1)):
                raise TectonicsError('regional depths exceed the declared constitutive depth scale')
            self._context = ExecutionContext('scipy')
            import sys
            self._tokens = _local_tokens(sys.modules[__name__])
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
                raise TectonicsError('loaded regional evolution source changed')
            self._definition = dict(schema='atlas.regional-evolution3d-plan.v1',
                cells=self.cells, lengths_m=self.lengths_m, frame_id=frame_id,
                vertical_datum=vertical_datum, material=asdict(material),
                rheology=profile.descriptor(), constitutive_scales=asdict(constitutive_scales),
                mechanical_scales=asdict(mechanical_scales), boundary_types=self._pattern,
                composition_values=c.tolist(), include_viscous_heating=include_viscous_heating,
                projection=dict(divergence_rtol=divergence_rtol,
                    max_velocity_correction_m_s=max_velocity_correction_m_s,
                    max_relative_correction=max_relative_correction),
                constitutive_log_tolerance=1e-8, constitutive_max_iterations=32,
                pressure='dynamic relative to removed reference hydrostatics',
                sampling='piecewise-constant cell temperature/composition/damage; Gauss-point depth and strain',
                execution=self._context.identity)
            self.plan_id = _hash(self._definition)
            self._verify()
        except BaseException:
            self.close()
            raise

    def _verify(self):
        import sys
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('closed or wrong-owner regional evolution plan')
        if _local_tokens(sys.modules[__name__]) != self._tokens:
            raise TectonicsError('loaded regional evolution implementation changed')
        self._context.verify()

    @contextmanager
    def _operation(self, cancel):
        self._verify(); _cancel(cancel)
        if self._active:
            raise TectonicsError('regional evolution is non-reentrant')
        self._active = True
        try:
            yield
            _cancel(cancel); self._verify()
        finally:
            self._active = False

    def descriptor(self):
        self._verify()
        return json.loads(_json(self._definition))

    def statistics(self):
        return dict(self._stats, heat=self._heat.statistics(),
                    transport=self._transport.statistics(), budget=self._resource.statistics())

    def empty_boundary_stocks(self, tracer_names=()):
        self._verify()
        return self._transport.empty_boundary_stocks(len(self._composition),
            tracer_names=('damage', 'accumulated_strain_ii', *tracer_names))

    def boundary_stock(self, *args, **kwargs):
        self._verify()
        return self._transport.boundary_stock(*args, **kwargs)

    def initial_state(self, temperature_k, fractions, damage, *, time_s,
                      state_source, scalar_histories=None):
        with self._operation(None):
            _name(state_source, 'state source')
            T = _array(temperature_k, self.cells, 'temperature', scalar_ok=True, positive=True)
            f = _array(fractions, (len(self._composition), *self.cells), 'component fractions')
            if np.any(f < 0) or np.max(np.abs(np.sum(f, axis=0)-1)) > 2e-13:
                raise TectonicsError('nonnegative component fractions must sum to one; no normalisation')
            d = _array(damage, self.cells, 'damage', scalar_ok=True)
            if np.any(d < 0) or (self._profile.family != 'bf23-memory' and np.any(d != 0)):
                raise TectonicsError('damage requires a supported memory law')
            fields = dict(component_mass_kg=f*self._mass,
                enthalpy_j=T*(self._mass*self._material.heat_capacity_j_kg_k),
                **{'tracer:damage': d*self._mass,
                   'tracer:accumulated_strain_ii': np.zeros(self.cells)})
            if scalar_histories is not None:
                if type(scalar_histories) is not dict or len(scalar_histories) > 62:
                    raise TectonicsError('at most 62 additional scalar histories supported')
                for name, value in scalar_histories.items():
                    _name(name, 'scalar history')
                    if name in ('damage', 'accumulated_strain_ii'):
                        raise TectonicsError('reserved history name')
                    fields['tracer:'+name] = _array(value, self.cells, name, scalar_ok=True)*self._mass
            result = self._state(fields, time_s, state_source, None)
            self._fields(result)
            return result

    def _state(self, fields, time_s, source, parent):
        return RegionalMechanicalSnapshot(dict(schema='atlas.regional-evolution3d-state.v1',
            plan_id=self.plan_id, frame_id=self._frame, vertical_datum=self._datum,
            time_s=scalar(time_s, 'state time', nonnegative=True), source=source,
            parent_state_id=parent, inventory='reference mass and sensible enthalpy m*cp*T',
            histories='mass-weighted scalar fields; no elastic tensor or free-surface state'), fields)

    def _fields(self, state):
        if type(state) is not RegionalMechanicalSnapshot:
            raise TectonicsError('immutable regional state required')
        meta = state.descriptor()
        if meta.get('schema') != 'atlas.regional-evolution3d-state.v1' or meta.get('plan_id') != self.plan_id:
            raise TectonicsError('state belongs to a different regional plan or runtime')
        if any(k not in ('component_mass_kg', 'enthalpy_j') and not k.startswith('tracer:')
               for k in state.array_names) or len(state.array_names) > 66:
            raise TectonicsError('unsupported state fields cannot be silently discarded')
        m = _array(state.array('component_mass_kg'), (len(self._composition), *self.cells), 'mass')
        total = np.sum(m, axis=0)
        if np.any(m < 0) or np.max(np.abs(total/self._mass-1)) > 2e-10:
            raise TectonicsError('reference density inventory incompatible with incompressible Boussinesq cells')
        E = _array(state.array('enthalpy_j'), self.cells, 'enthalpy', positive=True)
        T = E/(total*self._material.heat_capacity_j_kg_k)
        if np.any((T < self._material.temperature_range_k[0]) | (T > self._material.temperature_range_k[1])):
            raise TectonicsError('temperature outside declared material range')
        td = (T-self._cs.surface_temperature_k)/self._cs.temperature_scale_k
        if np.any((td < 0) | (td > 1)):
            raise TectonicsError('temperature outside constitutive scale; no extrapolation')
        C = np.einsum('i,i...->...', self._composition, m)/total
        histories = {name[7:]: _array(state.array(name), self.cells, name)
                     for name in state.array_names if name.startswith('tracer:')}
        if not {'damage', 'accumulated_strain_ii'} <= set(histories):
            raise TectonicsError('state is missing carried material history')
        d = histories['damage']/total
        if np.any(d < 0) or np.any(histories['accumulated_strain_ii'] < 0):
            raise TectonicsError('negative damage or accumulated strain')
        if self._profile.family != 'bf23-memory' and np.any(d != 0):
            raise TectonicsError('unsupported damage history must not be discarded')
        return m, E, total, T, td, C, d, histories

    def _law(self, td, damage, rate, cancel):
        return evaluate_rheology(self._profile, td.reshape(-1, 1), self._depth,
            rate*self._cs.time_s, damage.reshape(-1, 1), budget=self._resource, cancel=cancel)

    def _mechanics(self, state, velocity, tractions, gravity, force, source, coupling, cancel):
        m, E, mass, T, td, C, damage, histories = self._fields(state)
        response = boussinesq_response(self._material, T, C, gravity, np.zeros((*self.cells, 3)),
            budget=self._resource, cancel=cancel)
        body = force+response['body_force_n_m3'].reshape(self._n, 1, 3)
        time_s = state.descriptor()['time_s']
        key = _hash(dict(state=state.result_id, velocity=_digest_array(velocity),
            tractions={k: _digest_array(v) for k, v in tractions.items()},
            body=_digest_array(body), source=source, coupling=None if coupling is None else
            {k: (_digest_array(v) if isinstance(v, np.ndarray) else v) for k, v in coupling.items()}))
        if self._last is not None and self._last[0] == key:
            self._stats['endpoint_cache_hits'] += 1
            return self._last[1:]
        rate = np.zeros((self._n, 27))
        if self._last is not None:
            rate = self._last[3]
        for iteration in range(32):
            _cancel(cancel)
            law = self._law(td, damage, rate, cancel)
            eta = law['viscosity']*self._cs.viscosity_pa_s
            if self._eta is None or not np.array_equal(eta, self._eta):
                if self._mechanical is not None:
                    self._mechanical.close()
                self._mechanical = None
                self._eta = None
                self._mechanical = PreparedRegionalStokes3D(self.cells, self.lengths_m,
                    eta, self._pattern, scales=self._ms,
                    reference_viscosity_pa_s=self._cs.viscosity_pa_s,
                    frame_id=self._frame, vertical_datum=self._datum,
                    material_source=self.plan_id, budget=self._resource, cancel=cancel)
                self._eta = frozen(eta)
                self._stats['mechanical_preparations'] += 1
            else:
                self._stats['mechanical_reuses'] += 1
            request = dict(parent_state_id=state.result_id, epoch_id=source,
                time_s=time_s, force_source=source, boundary_source=source, cancel=cancel)
            if coupling is None:
                solved = self._mechanical.solve(body, velocity, tractions, **request)
            else:
                solved = self._mechanical.solve_force_coupled(body, velocity, tractions,
                    coupling['boundary_modes_m'], coupling['external_generalized_force_j'],
                    coupling['external_resistance_j_s'], coupling_source=coupling['source'], **request)
            grad = solved.array('velocity_gradient_s_inv')
            D = (grad+grad.swapaxes(-1, -2))/2
            newrate = np.sqrt(.5*np.sum(D*D, axis=(-2, -1)))
            updated = self._law(td, damage, newrate, cancel)
            difference = float(np.max(np.abs(np.log(updated['viscosity'])-np.log(law['viscosity']))))
            if difference <= 1e-8:
                power = 2*eta*np.sum(D*D, axis=(-2, -1))
                info = dict(iterations=iteration+1, constitutive_log_residual=difference,
                    bounded_viscosity_points=int(np.count_nonzero(law['viscosity_bound_code'])),
                    density_anomaly_min_kg_m3=float(np.min(response['density_anomaly_kg_m3'])),
                    density_anomaly_max_kg_m3=float(np.max(response['density_anomaly_kg_m3'])))
                self._last = (key, solved, frozen(power), frozen(newrate), info)
                return self._last[1:]
            rate = newrate
        raise TectonicsError('3D constitutive/mechanical iteration did not converge; no state advanced')

    def advance(self, state, duration_s, *, velocity_m_s, dynamic_traction_pa,
                gravity_m_s2, additional_body_force_n_m3, driving_source,
                heat_boundaries, heat_source_w_m3, heat_source, boundary_stocks,
                coupling=None, cancel=None):
        """One first-order split interval; returned stocks must replace old stocks.

        Driving and heat-boundary values are explicitly frozen for this interval.
        Optional finite-mode coupling uses the existing work-conjugate regional
        response, with exterior resistance only (never count the region twice).
        Rejection publishes no new state and mutates no input or exterior stock.
        """
        with self._operation(cancel), self._resource.reserve(8192*self._n+65536,
                category='regional-evolution3d-advance'):
            dt = scalar(duration_s, 'duration', positive=True)
            _name(driving_source, 'driving source'); _name(heat_source, 'heat source')
            m, E, mass, T, td, C, damage, histories = self._fields(state)
            if not np.isfinite(state.descriptor()['time_s']+dt) or state.descriptor()['time_s']+dt == state.descriptor()['time_s']:
                raise TectonicsError('endpoint time is not representable')
            nv = int(np.prod(2*np.asarray(self.cells)+1))
            velocity = _array(velocity_m_s, (nv, 3), 'velocity', scalar_ok=True)
            force = _array(additional_body_force_n_m3, (self._n, 27, 3), 'body force', scalar_ok=True)
            gravity = _array(gravity_m_s2, (3,), 'gravity')
            if type(dynamic_traction_pa) is not dict or set(dynamic_traction_pa) != set(SIDES):
                raise TectonicsError('all six dynamic traction arrays required')
            tractions = {s: _array(dynamic_traction_pa[s],
                (self._n//self.cells[i//2], 9, 3), s+' traction', scalar_ok=True)
                for i, s in enumerate(SIDES)}
            if coupling is not None:
                if type(coupling) is not dict or set(coupling) != {'boundary_modes_m', 'external_generalized_force_j', 'external_resistance_j_s', 'source'}:
                    raise TectonicsError('explicit finite-mode coupling contract required')
                _name(coupling['source'], 'coupling source')
                mode_shape = np.shape(coupling['boundary_modes_m'])
                if len(mode_shape) != 3 or not 1 <= mode_shape[0] <= 12 or mode_shape[1:] != (nv, 3):
                    raise TectonicsError('one to twelve supported boundary modes required')
                coupling = {k: v if k == 'source' else frozen(np.asarray(v, dtype=float)) for k, v in coupling.items()}
            initial, power, rates, initial_info = self._mechanics(state, velocity, tractions,
                gravity, force, driving_source, coupling, cancel)
            flow = self._transport.project_velocity(initial.array('velocity_m_s'),
                source_result_id=initial.result_id, cancel=cancel)
            cellrate = np.sum(rates*self._weights, axis=1).reshape(self.cells)
            histories = dict(histories)
            histories['accumulated_strain_ii'] = histories['accumulated_strain_ii']+mass*cellrate*dt
            if self._profile.family == 'bf23-memory':
                next_damage = advance_memory(self._profile, damage, cellrate*self._cs.time_s,
                    td, dt/self._cs.time_s, budget=self._resource, cancel=cancel)
                histories['damage'] = mass*next_damage
            # Source heating is attached to the donor material before its transport;
            # conduction then acts on the advected heat. Both are first-order split.
            source = _array(heat_source_w_m3, self.cells, 'heat source', scalar_ok=True)
            source = source+self._material.internal_heating_w_m3
            if self._heating:
                source = source+np.sum(power*self._weights, axis=1).reshape(self.cells)
            heated_E = E+source*self._volume*dt
            if not np.isfinite(heated_E).all() or np.any(heated_E <= 0):
                raise TectonicsError('source update would create nonpositive/nonfinite enthalpy')
            transported = self._transport.advect(m, heated_E, histories, flow, dt,
                boundary_stocks=boundary_stocks, cancel=cancel)
            conductive = self._heat.advance(transported.array('enthalpy_j'), dt,
                heat_boundaries, 0., source_id=heat_source, cancel=cancel)
            fields = dict(component_mass_kg=transported.array('component_mass_kg'),
                enthalpy_j=conductive.array('enthalpy_j'))
            fields.update({'tracer:'+k: transported.array('tracer:'+k) for k in histories})
            step_source = _hash(dict(initial_mechanics_id=initial.result_id,
                transport_id=transported.result_id, heat_id=conductive.result_id,
                heat_source=heat_source, volume_source_sha256=_digest_array(source)))
            next_state = self._state(fields, state.descriptor()['time_s']+dt,
                step_source, state.result_id)
            final, _, _, final_info = self._mechanics(next_state, velocity, tractions,
                gravity, force, driving_source, coupling, cancel)
            metadata = dict(schema='atlas.regional-evolution3d-advance.v1', plan_id=self.plan_id,
                parent_state_id=state.result_id, state_id=next_state.result_id, duration_s=dt,
                initial_mechanics_id=initial.result_id, mechanics_id=final.result_id,
                transformation_id=step_source, transport_id=transported.result_id,
                heat_id=conductive.result_id,
                initial_constitutive=initial_info, endpoint_constitutive=final_info,
                mechanical_source=driving_source, heat_source=heat_source,
                volume_source_energy_j=float(np.sum(source)*self._volume*dt),
                memory_source='BF23 exact frozen-coefficient update then advection' if self._profile.family == 'bf23-memory' else 'no damage evolution law',
                time_method='first-order source, donor transport, backward-Euler conduction, endpoint mechanics',
                scientific_acceptance=False,
                scope='fixed Cartesian Boussinesq evolution; no elastic tensor, moving surface, fracture or sphere')
            self._stats['accepted_intervals'] += 1
            return RegionalEvolutionAdvance3D(next_state, initial, final, transported,
                conductive, _json(metadata))

    def close(self):
        if getattr(self, '_active', False):
            raise TectonicsError('cannot close active regional evolution')
        if getattr(self, '_closed', True):
            return
        self._closed = True
        for name in ('_mechanical', '_heat', '_transport'):
            obj = getattr(self, name, None)
            if obj is not None:
                obj.close()
                setattr(self, name, None)
        self._last = self._eta = None
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self, *_):
        self.close()
