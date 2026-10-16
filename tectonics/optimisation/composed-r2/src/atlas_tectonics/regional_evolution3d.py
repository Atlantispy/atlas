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
from .regional_caloric import component_sum as _component_sum

from ._validation import TectonicsError, scalar, frozen, input_shape
from .constitutive import (BoussinesqMaterial, DiffusiveScales, RheologyProfile,
    evaluate_rheology, advance_memory, boussinesq_response)
from .regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from .regional_execution3d import (PreparedRegionalStokes3D, SIDES, _array, _cancel,
    _name, _json, _hash, _digest_array, _local_tokens, _selection, _checked_traction_binding)
from .regional_solver_selection3d import POLICY as _SELECTION_POLICY
from .regional_transport3d import PreparedRegionalTransport3D
from .regional_heat3d import PreparedRegionalHeat3D
from . import regional_i01_creep
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
    source_audit: RegionalMechanicalSnapshot | None = None

    def descriptor(self):
        return json.loads(self._metadata)


@dataclass(frozen=True)
class RegionalDonorStage3D:
    inventory: RegionalMechanicalSnapshot
    driving: RegionalMechanicalSnapshot
    initial_mechanics: RegionalMechanicalSnapshot
    flow: object
    source_audit: RegionalMechanicalSnapshot
    radial_gravity: object = None

    @property
    def result_id(self):
        return _hash({name: getattr(self, name).result_id for name in
                      ('inventory', 'driving', 'initial_mechanics', 'flow', 'source_audit')})

    def mechanical_arguments(self):
        d = self.driving
        coupling = d.descriptor()['coupling']
        if coupling is not None:
            coupling.update({k.removeprefix('coupling:'): d.array(k)
                             for k in d.array_names if k.startswith('coupling:')})
        return (d.array('velocity_m_s'), {s: d.array('traction:'+s) for s in SIDES},
                d.array('gravity_m_s2') if self.radial_gravity is None else self.radial_gravity,
                d.array('additional_body_force_n_m3'), coupling)


@dataclass(frozen=True)
class RegionalSourceEndpoint3D:
    state: RegionalMechanicalSnapshot
    mechanics: RegionalMechanicalSnapshot
    _metadata: bytes

    def descriptor(self):
        return json.loads(self._metadata)


class PreparedRegionalEvolution3D:
    """One owner; one last mechanical operator, not an accumulating history.

    Reference density/cp/k are constant as required by this Boussinesq route.
    Composition changes buoyancy, not reference mass. Temperature, depth, strain
    rate and (for BF23) carried damage determine viscosity at all Gauss points.
    Temperature and damage are cell averages, piecewise constant at those points.
    Depth is the distance down from the box top divided by ``depth_scale_m``, so
    the top face is depth zero; ``vertical_datum`` is recorded only and does not
    move that origin. There is no top-depth input.
    Pressure and supplied tractions are dynamic (reference hydrostatics removed).
    Every mechanical solve starts its constitutive iteration from zero strain
    rate (recorded as ``constitutive_start``): a result depends on its state and
    driving, never on what this plan solved before or on a refused advance.
    ``mechanics_method='auto'`` (the default) lets each prepared Stokes operator
    choose multigrid or gmres. The definition then records the request and the
    selection policy and admitted-method mask, so a state continues only under a
    plan with the same routing context. The admission choices are pinned; later
    shared-budget pressure refuses work rather than silently rerouting it.
    Explicit methods are recorded and honoured unchanged.
    """

    def __setattr__(self, key, value):
        if not key.startswith('_') and hasattr(self, key):
            raise TectonicsError('prepared regional evolution definition is immutable')
        object.__setattr__(self, key, value)

    def __init__(self, cells, lengths_m, material, profile, constitutive_scales,
                 mechanical_scales, boundary_types, *, composition_values,
                 frame_id, vertical_datum, include_viscous_heating,
                 divergence_rtol, max_velocity_correction_m_s,
                 max_relative_correction, budget=None, cancel=None,
                 mechanics_method='auto', transport_method='donor-cell', i01_creep_law=None,
                 radial_constitutive=None, physical_mean_pressure_pa=None,
                 pressure_reference_pa=None, pressure_reference_source=None, pressure_load_partition=None,
                 max_components=16, pressure_space='q1'):
        if type(material) is not BoussinesqMaterial:
            raise TectonicsError('explicit registered material and rheology required')
        if radial_constitutive is None and any(v is not None for v in
                (pressure_reference_pa, pressure_reference_source, pressure_load_partition)):
            raise TectonicsError('pressure reference requires explicit radial constitutive physics')
        if radial_constitutive is not None:
            from . import integration_radial_strength as radial
            if pressure_reference_pa is not None and pressure_load_partition != 'full':
                raise TectonicsError('automatic radial evolution requires full physical loads; the exact reference split is native')
            if profile is not None or i01_creep_law is not None:
                raise TectonicsError('radial constitutive source is exclusive with other rheology routes')
            rheology = radial.native_descriptor(radial_constitutive)
            target = dict(reference_density_kg_m3=material.density_kg_m3,
                heat_capacity_j_kg_k=material.heat_capacity_j_kg_k,
                conductivity_w_m_k=material.conductivity_w_m_k,
                alpha_per_k=material.expansion_per_k, radiogenic_w_m3=material.internal_heating_w_m3)
            if (any(row != target for row in radial_constitutive.descriptor()['thermophysical']) or
                    material.composition_density_contrast_kg_m3 != 0.):
                raise TectonicsError('native thermal/reference material must match every actual radial source layer')
            if physical_mean_pressure_pa is not None:
                physical_mean_pressure_pa = scalar(physical_mean_pressure_pa, 'physical mean pressure')
        elif physical_mean_pressure_pa is not None:
            raise TectonicsError('physical pressure datum requires the explicit full-stress radial route')
        elif i01_creep_law is None:
            if type(profile) is not RheologyProfile:
                raise TectonicsError('explicit registered rheology required')
            rheology = profile.descriptor()
        else:
            if profile is not None:
                raise TectonicsError('I01 creep and a rheology profile are mutually exclusive; select profile=None')
            rheology = regional_i01_creep.descriptor(i01_creep_law)
        if type(constitutive_scales) is not DiffusiveScales or type(mechanical_scales) is not RegionalMechanicsScales:
            raise TectonicsError('explicit constitutive and mechanical scales required')
        if type(include_viscous_heating) is not bool:
            raise TectonicsError('declare whether viscous dissipation is converted to heat')
        if mechanics_method not in ('auto', 'gmres', 'direct', 'multigrid'):
            raise TectonicsError('mechanics method must be auto, gmres, direct or multigrid')
        if pressure_space not in ('q1', 'q1-p0') or (pressure_space == 'q1-p0' and
                mechanics_method not in ('direct', 'gmres')):
            raise TectonicsError('q1-p0 pressure requires an explicit assembled direct or gmres method')
        _name(frame_id, 'frame'); _name(vertical_datum, 'vertical datum')
        if type(boundary_types) is not dict or set(boundary_types) != set(SIDES):
            raise TectonicsError('declare all six mechanical sides')
        if any(len(v) != 3 or any(k not in ('velocity', 'traction') for k in v)
               for v in boundary_types.values()):
            raise TectonicsError('three velocity/traction components per side required')
        if type(max_components) is not int or not 1 <= max_components <= 256:
            raise TectonicsError('explicit component capacity must lie within the existing transport limit 1..256')
        component_shape = input_shape(composition_values)
        if len(component_shape) != 1 or not 1 <= component_shape[0] <= max_components:
            raise TectonicsError('component composition count exceeds the explicitly admitted capacity')
        resource = select_budget(budget)
        with resource.reserve(4096+32*component_shape[0], category='regional-component-admission'):
            c = _array(composition_values, component_shape, 'component composition')
        if np.any((c < 0) | (c > 1)):
            raise TectonicsError('Boussinesq composition values must lie in [0,1]')
        self._closed = self._active = False
        self._owner = threading.get_ident()
        self._resource = resource
        self._transport = self._heat = self._mechanical = None
        self._eta = self._last = self._guard = None
        self._method = mechanics_method
        self._pressure_space = pressure_space
        self._mechanics_selection_bytes = None
        self._stats = dict(mechanical_preparations=0, mechanical_reuses=0,
                           mechanical_geometry_reuses=0, endpoint_cache_hits=0, accepted_intervals=0,
                           mechanical_methods={}, mechanical_method_switches=0)
        try:
            self._transport = PreparedRegionalTransport3D(cells, lengths_m,
                divergence_rtol=divergence_rtol,
                max_velocity_correction_m_s=max_velocity_correction_m_s,
                max_relative_correction=max_relative_correction,
                budget=self._resource, cancel=cancel, transport_method=transport_method)
            self.cells, self.lengths_m = tuple(cells), tuple(float(x) for x in lengths_m)
            self._n = int(np.prod(cells))
            # Source-audit arrays and their immutable copies: fewer than 80
            # binary64 values/cell, with four-copy construction allowance.
            self._advance_work_bytes = (8192+4096)*self._n+65536
            # The reusable donor stage also freezes material/history and driving
            # arrays. Charge four construction copies of at most 64 histories,
            # 81 body-force values/cell and 12 three-vector Q2 boundary modes.
            # This is an allocation admission, not a larger resource limit.
            nv = int(np.prod(2*np.asarray(cells)+1))
            # One optional material-quadrature scalar travels with these fields.
            self._advance_work_bytes += 32*((len(composition_values)+64+81+1)*self._n+39*nv+144)
            # Radial-law audit adds six quadrature fields and two cell fields;
            # four live binary64 copies fit within 8192 bytes/cell. The full
            # source declaration is retained separately, not hidden in this count.
            if radial_constitutive is not None:
                self._advance_work_bytes += 8192*self._n
            declaration_bytes = 0 if radial_constitutive is None else 4*len(_json(rheology))
            guard = self._resource.reserve(65536+4096*self._n+declaration_bytes+
                32*max(0, len(c)-16), category='regional-evolution3d')
            guard.__enter__()
            self._guard = guard
            self._material, self._profile, self._cs, self._ms = material, profile, constitutive_scales, mechanical_scales
            self._i01_creep = i01_creep_law
            self._radial_constitutive = radial_constitutive
            self._physical_mean_pressure_pa = physical_mean_pressure_pa
            self._pressure_reference_args = {}
            if pressure_reference_pa is not None:
                _name(pressure_reference_source, 'reference pressure source')
                if pressure_load_partition not in ('full', 'incremental'):
                    raise TectonicsError('declare full or incremental reference-pressure inputs')
                reference = _array(pressure_reference_pa, (int(np.prod(np.asarray(cells)+1)),), 'reference pressure')
                self._pressure_reference_args = dict(pressure_reference_pa=frozen(reference),
                    pressure_reference_source=pressure_reference_source, pressure_load_partition=pressure_load_partition)
            elif pressure_reference_source is not None or pressure_load_partition is not None:
                raise TectonicsError('reference source/partition without actual Q1 pressure field')
            if pressure_space != 'q1':
                self._pressure_reference_args['pressure_space'] = pressure_space
            self._last_radial = None
            self._rheology_family = rheology['family']
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
            self._depth = frozen((lengths_m[2]-q[..., 2])/constitutive_scales.depth_scale_m
                if radial_constitutive is None else radial_constitutive.array('depth_m')/constitutive_scales.depth_scale_m)
            self._weights = frozen(np.prod(weights[ref], axis=1)/8.)
            if radial_constitutive is None and np.any((self._depth < 0) | (self._depth > 1)):
                raise TectonicsError('regional depths exceed the declared constitutive depth scale')
            self._context = ExecutionContext('scipy')
            import sys
            self._tokens = _local_tokens(sys.modules[__name__])
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
                raise TectonicsError('loaded regional evolution source changed')
            self._definition = dict(schema='atlas.regional-evolution3d-plan.v1',
                cells=self.cells, lengths_m=self.lengths_m, frame_id=frame_id,
                vertical_datum=vertical_datum, material=asdict(material),
                rheology=rheology, constitutive_scales=asdict(constitutive_scales),
                mechanical_scales=asdict(mechanical_scales), boundary_types=self._pattern,
                mechanics_method=mechanics_method,
                transport_method=transport_method,
                transport_plan_id=self._transport.plan_id,
                composition_values=c.tolist(), include_viscous_heating=include_viscous_heating,
                projection=dict(divergence_rtol=divergence_rtol,
                    max_velocity_correction_m_s=max_velocity_correction_m_s,
                    max_relative_correction=max_relative_correction),
                constitutive_log_tolerance=1e-8, constitutive_max_iterations=32,
                constitutive_start='zero strain rate at every mechanical solve',
                pressure='dynamic relative to removed reference hydrostatics',
                sampling='piecewise-constant cell temperature/composition/damage; Gauss-point depth and strain',
                depth='distance down from box top / depth_scale_m; vertical_datum is recorded only',
                execution=self._context.identity)
            if max_components != 16:
                self._definition['max_components'] = max_components
            if pressure_space != 'q1':
                self._definition['pressure_space'] = pressure_space
            if radial_constitutive is not None:
                if (radial_constitutive.descriptor()['cells'] != list(self.cells) or
                        radial_constitutive.descriptor()['lengths_m'] != list(self.lengths_m) or
                        radial_constitutive.descriptor()['frame_id'] != self._frame):
                    raise TectonicsError('radial constitutive geometry/frame differs from the native box')
                self._definition.update(physical_mean_pressure_pa=physical_mean_pressure_pa,
                    pressure='full physical mean from datum or natural traction; full gravity and traction',
                    constitutive_start='declared reference viscosity at every solve; no carried iteration state',
                    sampling='current cell T and engineering plastic history; actual contained radial layer source',
                    depth='actual radius-bound physical source quadrature depth; no box-top unit-domain rheology',
                    incremental_plastic_history='radial_plastic_kappa')
                if pressure_reference_pa is not None:
                    self._definition['pressure_reference'] = dict(source=pressure_reference_source,
                        pressure_sha256=_digest_array(reference), load_partition=pressure_load_partition,
                        full_reaction='reference plus increment; exterior coupling uses increment only')
            if mechanics_method == 'auto':
                self._definition['mechanics_selection_policy'] = _SELECTION_POLICY
                # Reservations depend on this fixed geometry and boundary pattern,
                # not viscosity. Pin their admission mask, not transient byte counts:
                # distinct budgets with the same choices remain restart-compatible.
                self._mechanics_selection_bytes = max(
                    0, self._resource.available_bytes-self._advance_work_bytes)
                selection = _selection(self.cells, self.lengths_m, self._ms, self._pattern,
                                       1., self._mechanics_selection_bytes)
                self._definition['mechanics_selection_admission'] = {
                    method: item['admitted'] for method, item in selection['admission'].items()}
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
        return dict(self._stats, mechanical_methods=dict(self._stats['mechanical_methods']),
                    heat=self._heat.statistics(),
                    transport=self._transport.statistics(), budget=self._resource.statistics())

    def empty_boundary_stocks(self, tracer_names=()):
        self._verify()
        return self._transport.empty_boundary_stocks(len(self._composition),
            tracer_names=('damage', 'accumulated_strain_ii', *tracer_names))

    def boundary_stock(self, *args, **kwargs):
        self._verify()
        return self._transport.boundary_stock(*args, **kwargs)

    def initial_state(self, temperature_k, fractions, damage, *, time_s,
                      state_source, scalar_histories=None, material_quadrature_m3=None):
        with self._operation(None):
            _name(state_source, 'state source')
            T = _array(temperature_k, self.cells, 'temperature', scalar_ok=True, positive=True)
            f = _array(fractions, (len(self._composition), *self.cells), 'component fractions')
            if np.any(f < 0) or np.max(np.abs(np.sum(f, axis=0)-1)) > 2e-13:
                raise TectonicsError('nonnegative component fractions must sum to one; no normalisation')
            d = _array(damage, self.cells, 'damage', scalar_ok=True)
            if np.any(d < 0) or (self._rheology_family != 'bf23-memory' and np.any(d != 0)):
                raise TectonicsError('damage requires a supported memory law')
            quadrature = None
            reference_mass = self._mass
            if material_quadrature_m3 is not None:
                # Explicit fresh admission only. Continuations carry this
                # measure as stock; Cartesian geometry remains self._volume.
                quadrature = _array(self._volume if material_quadrature_m3 is True else material_quadrature_m3,
                    self.cells, 'material quadrature', scalar_ok=True)
                if np.any(quadrature < 0):
                    raise TectonicsError('negative material quadrature')
                if np.any(quadrature == 0):
                    raise TectonicsError('zero material quadrature has no native caloric state')
                reference_mass = self._material.density_kg_m3*quadrature
            fields = dict(component_mass_kg=f*reference_mass,
                enthalpy_j=T*(reference_mass*self._material.heat_capacity_j_kg_k),
                **{'tracer:damage': d*reference_mass,
                   'tracer:accumulated_strain_ii': np.zeros(self.cells)})
            if quadrature is not None:
                fields['material_quadrature_m3'] = quadrature
            if scalar_histories is not None:
                if type(scalar_histories) is not dict or len(scalar_histories) > 62:
                    raise TectonicsError('at most 62 additional scalar histories supported')
                for name, value in scalar_histories.items():
                    _name(name, 'scalar history')
                    if name in ('damage', 'accumulated_strain_ii'):
                        raise TectonicsError('reserved history name')
                    fields['tracer:'+name] = _array(value, self.cells, name, scalar_ok=True)*reference_mass
            if self._radial_constitutive is not None:
                expected = self._radial_constitutive.array('plastic_kappa')[:, 0].reshape(self.cells)*reference_mass
                if 'tracer:source_kappa' in fields and not np.array_equal(fields['tracer:source_kappa'], expected):
                    raise TectonicsError('initial plastic history differs from the actual radial source')
                if 'tracer:radial_plastic_kappa' in fields and np.any(fields['tracer:radial_plastic_kappa'] != 0):
                    raise TectonicsError('fresh radial incremental plastic history must be explicitly zero')
                fields['tracer:source_kappa'] = expected
                fields['tracer:radial_plastic_kappa'] = np.zeros(self.cells)
                if not np.array_equal(T.ravel(), self._radial_constitutive.array('temperature_k')[:, 0]):
                    raise TectonicsError('initial temperature differs from the actual radial source')
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
        dual = 'material_quadrature_m3' in state.array_names
        if any(k not in ('component_mass_kg', 'enthalpy_j', 'material_quadrature_m3') and not k.startswith('tracer:')
               for k in state.array_names) or len(state.array_names) > 66+int(dual):
            raise TectonicsError('unsupported state fields cannot be silently discarded')
        m = _array(state.array('component_mass_kg'), (len(self._composition), *self.cells), 'mass')
        total = np.sum(m, axis=0)
        reference_mass = self._mass
        if dual:
            quadrature = _array(state.array('material_quadrature_m3'), self.cells, 'material quadrature')
            if np.any(quadrature < 0):
                raise TectonicsError('negative material quadrature')
            empty = quadrature == 0
            if np.any(empty):
                if np.any(m[:, empty] != 0) or any(np.any(state.array(k)[empty] != 0)
                        for k in state.array_names if k == 'enthalpy_j' or k.startswith('tracer:')):
                    raise TectonicsError('zero material quadrature retains native stock')
                raise TectonicsError('zero material quadrature has no native caloric state')
            reference_mass = self._material.density_kg_m3*quadrature
        if np.any(m < 0) or np.max(np.abs(total/reference_mass-1)) > 2e-10:
            raise TectonicsError('reference density inventory incompatible with incompressible Boussinesq cells')
        E = _array(state.array('enthalpy_j'), self.cells, 'enthalpy', positive=True)
        T = E/(_component_sum(m)*self._material.heat_capacity_j_kg_k)
        if np.any((T < self._material.temperature_range_k[0]) | (T > self._material.temperature_range_k[1])):
            raise TectonicsError('temperature outside declared material range')
        td = (T-self._cs.surface_temperature_k)/self._cs.temperature_scale_k
        if self._radial_constitutive is None and np.any((td < 0) | (td > 1)):
            raise TectonicsError('temperature outside constitutive scale; no extrapolation')
        C = np.einsum('i,i...->...', self._composition, m)/total
        histories = {name[7:]: _array(state.array(name), self.cells, name)
                     for name in state.array_names if name.startswith('tracer:')}
        if not {'damage', 'accumulated_strain_ii'} <= set(histories):
            raise TectonicsError('state is missing carried material history')
        d = histories['damage']/total
        if np.any(d < 0) or np.any(histories['accumulated_strain_ii'] < 0):
            raise TectonicsError('negative damage or accumulated strain')
        if self._rheology_family != 'bf23-memory' and np.any(d != 0):
            raise TectonicsError('unsupported damage history must not be discarded')
        if self._radial_constitutive is not None:
            if (not {'source_kappa', 'radial_plastic_kappa'} <= set(histories) or
                    np.any(histories['source_kappa'] < 0) or np.any(histories['radial_plastic_kappa'] < 0)):
                raise TectonicsError('radial constitutive state needs nonnegative original/incremental plastic histories')
        return m, E, total, T, td, C, d, histories

    def _law(self, td, damage, rate, cancel, *, temperature_k=None):
        if self._i01_creep is not None:
            eta = regional_i01_creep.viscosity_pa_s(self._i01_creep, temperature_k.reshape(-1, 1),
                                                   budget=self._resource, cancel=cancel)
            return dict(viscosity_pa_s=np.broadcast_to(eta, (self._n, 27)),
                        viscosity_bound_code=np.zeros((self._n, 27), dtype=np.int8))
        return evaluate_rheology(self._profile, td.reshape(-1, 1), self._depth,
            rate*self._cs.time_s, damage.reshape(-1, 1), budget=self._resource, cancel=cancel)

    def _mechanics(self, state, velocity, tractions, gravity, force, source, coupling, cancel):
        if self._radial_constitutive is not None:
            return self._radial_mechanics(state, velocity, tractions, gravity, force, source, coupling, cancel)
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
        # Declared start: zero strain rate, never the rate of an earlier solve. The
        # result is then a function of this state and driving alone, so a reused
        # endpoint and a restart on a new plan publish what a fresh solve would.
        rate = np.zeros((self._n, 27))
        for iteration in range(32):
            _cancel(cancel)
            law = self._law(td, damage, rate, cancel, temperature_k=T)
            eta = (law['viscosity_pa_s'] if self._i01_creep is not None
                   else law['viscosity']*self._cs.viscosity_pa_s)
            if self._eta is None or not np.array_equal(eta, self._eta):
                previous, self._mechanical, self._eta = self._mechanical, None, None
                if previous is None:
                    self._mechanical = PreparedRegionalStokes3D(self.cells, self.lengths_m,
                        eta, self._pattern, scales=self._ms,
                        reference_viscosity_pa_s=self._cs.viscosity_pa_s,
                        frame_id=self._frame, vertical_datum=self._datum,
                        material_source=self.plan_id, method=self._method,
                        pressure_space=self._pressure_space,
                        budget=self._resource, cancel=cancel,
                        _selection_available_bytes=self._mechanics_selection_bytes)
                else:
                    # Same box, boundary pattern and scales: only viscosity changed.
                    # The old operators are released first; the new plan reuses the
                    # viscosity-independent geometry unless auto changed its method.
                    before = previous.method
                    self._mechanical = previous.with_viscosity(eta, material_source=self.plan_id,
                        cancel=cancel, release=True)
                    self._stats['mechanical_geometry_reuses'] += int(self._mechanical._reused)
                    self._stats['mechanical_method_switches'] += int(self._mechanical.method != before)
                self._eta = frozen(eta)
                methods = self._stats['mechanical_methods']
                methods[self._mechanical.method] = methods.get(self._mechanical.method, 0)+1
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
            updated = self._law(td, damage, newrate, cancel, temperature_k=T)
            eta_key = 'viscosity_pa_s' if self._i01_creep is not None else 'viscosity'
            difference = float(np.max(np.abs(np.log(updated[eta_key])-np.log(law[eta_key]))))
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

    def _radial_mechanics(self, state, velocity, tractions, gravity, force, source, coupling, cancel):
        """Current owned state, full physical gravity/pressure, one actual solve path."""
        from . import integration_radial_strength as radial
        from .integration_pressure_coupling import RadialGravityField
        gravity_field = gravity if type(gravity) is RadialGravityField else None
        if gravity_field is not None:
            if gravity_field._resource is not self._resource or gravity_field.descriptor()['native_plan_id'] != self.plan_id:
                raise TectonicsError('analytic radial gravity is from another native plan/budget')
            gravity = gravity_field.array()
        _, _, _, T, _, C, _, _ = self._fields(state)
        if gravity.shape == (3,):
            thermal = boussinesq_response(self._material, T, C, gravity, np.zeros((*self.cells, 3)),
                                         budget=self._resource, cancel=cancel)
            body = force+thermal['body_force_n_m3'].reshape(self._n, 1, 3)
        else:
            thermal = boussinesq_response(self._material, T.reshape(self._n, 1), C.reshape(self._n, 1),
                gravity, np.zeros_like(gravity), budget=self._resource, cancel=cancel)
            body = force+thermal['body_force_n_m3']
        # An arbitrary declared Q1 gradient need not balance rho_ref*g. Supply
        # the whole physical body; the native weak form removes its exact
        # reference terms, rather than silently discarding reference gravity.
        residual_body = body
        body = residual_body+self._material.density_kg_m3*gravity
        key = _hash(dict(state=state.result_id, velocity=_digest_array(velocity),
            tractions={k: _digest_array(v) for k, v in tractions.items()},
            body=_digest_array(body), source=source, coupling=None if coupling is None else
            {k: (_digest_array(v) if isinstance(v, np.ndarray) else v) for k, v in coupling.items()}))
        if gravity_field is not None:
            key = _hash(dict(base=key, analytic_gravity=gravity_field.field_id))
        if self._last is not None and self._last[0] == key:
            self._stats['endpoint_cache_hits'] += 1
            return self._last[1:]
        current = radial.refresh_radial_strength(self._radial_constitutive, state, self, budget=self._resource)
        if self._mechanical is None:
            self._mechanical = PreparedRegionalStokes3D(self.cells, self.lengths_m,
                self._cs.viscosity_pa_s, self._pattern, scales=self._ms,
                reference_viscosity_pa_s=self._cs.viscosity_pa_s, frame_id=self._frame,
                vertical_datum=self._datum, material_source=self.plan_id, method=self._method,
                physical_mean_pressure_pa=self._physical_mean_pressure_pa,
                budget=self._resource, cancel=cancel,
                _selection_available_bytes=self._mechanics_selection_bytes, **self._pressure_reference_args)
            self._stats['mechanical_preparations'] += 1
        hydrostatic = {}
        if gravity_field is not None:
            from .regional_radial_hydrostatic import radial_hydrostatic_lift
            hydrostatic = dict(hydrostatic_lift=radial_hydrostatic_lift(gravity_field, self._mechanical,
                density_kg_m3=self._material.density_kg_m3, parent_state_id=state.result_id,
                time_s=state.descriptor()['time_s'], budget=self._resource),
                residual_body_force_n_m3=residual_body)
        result = radial.solve_radial_strength(self._mechanical, current, body, velocity, tractions,
            parent_state_id=state.result_id, epoch_id=current.descriptor()['epoch_id'],
            time_s=state.descriptor()['time_s'], force_source=source, boundary_source=source,
            coupling=coupling, cancel=cancel, **hydrostatic)
        self._last_radial = result.constitutive
        power = result.constitutive.array('dissipation_w_m3')
        rates = result.constitutive.array('strain_rate_ii_s_1')
        info = dict(iterations=result.iterations, constitutive_log_residual=result.constitutive_log_residual,
                    constitutive_result_id=result.constitutive.result_id, bounded_viscosity_points=0,
                    density_anomaly_min_kg_m3=float(np.min(thermal['density_anomaly_kg_m3'])),
                    density_anomaly_max_kg_m3=float(np.max(thermal['density_anomaly_kg_m3'])))
        self._last = (key, result.mechanics, power, rates, info)
        return self._last[1:]

    def source_stage(self, state, duration_s, *, velocity_m_s, dynamic_traction_pa,
                gravity_m_s2, additional_body_force_n_m3, driving_source,
                heat_source_w_m3, heat_source, coupling=None, cancel=None):
        """Solve initial mechanics and book donor sources, without transport/heat.

        The immutable typed stage is shared by ordinary evolution and a declared
        enlarged-grid consumer. It does not publish a successor or heat twice.
        """
        with self._operation(cancel), self._resource.reserve(self._advance_work_bytes,
                category='regional-evolution3d-source-stage'):
            return self._prepare_source_stage(state, duration_s, velocity_m_s=velocity_m_s, dynamic_traction_pa=dynamic_traction_pa,
                gravity_m_s2=gravity_m_s2, additional_body_force_n_m3=additional_body_force_n_m3,
                driving_source=driving_source, heat_source_w_m3=heat_source_w_m3,
                heat_source=heat_source, coupling=coupling, cancel=cancel)

    def _prepare_source_stage(self, state, duration_s, *, velocity_m_s, dynamic_traction_pa,
                gravity_m_s2, additional_body_force_n_m3, driving_source,
                heat_source_w_m3, heat_source, coupling=None, cancel=None):
        dt = scalar(duration_s, 'duration', positive=True)
        _name(driving_source, 'driving source'); _name(heat_source, 'heat source')
        m, E, mass, T, td, C, damage, histories = self._fields(state)
        if not np.isfinite(state.descriptor()['time_s']+dt) or state.descriptor()['time_s']+dt == state.descriptor()['time_s']:
            raise TectonicsError('endpoint time is not representable')
        nv = int(np.prod(2*np.asarray(self.cells)+1))
        velocity = _array(velocity_m_s, (nv, 3), 'velocity', scalar_ok=True)
        force = _array(additional_body_force_n_m3, (self._n, 27, 3), 'body force', scalar_ok=True)
        from .integration_pressure_coupling import RadialGravityField
        gravity_binding = None
        if type(gravity_m_s2) is RadialGravityField:
            gravity_binding = gravity_m_s2.descriptor()
            if (self._radial_constitutive is None or gravity_binding['native_plan_id'] != self.plan_id or
                    gravity_m_s2._resource is not self._resource):
                raise TectonicsError('radial quadrature gravity requires its actual radial-constitutive native plan')
            gravity = _array(gravity_m_s2.array(), (self._n, 27, 3), 'physical radial gravity')
        else:
            gravity = _array(gravity_m_s2, (3,), 'gravity')
        if type(dynamic_traction_pa) is not dict or set(dynamic_traction_pa) != set(SIDES):
            raise TectonicsError('all six dynamic traction arrays required')
        tractions = {s: _array(dynamic_traction_pa[s],
            (self._n//self.cells[i//2], 9, 3), s+' traction', scalar_ok=True)
            for i, s in enumerate(SIDES)}
        if coupling is not None:
            coupling_keys = {'boundary_modes_m', 'external_generalized_force_j', 'external_resistance_j_s', 'source'}
            if self._radial_constitutive is not None:
                coupling_keys.add('pressure_reference_id')
            if type(coupling) is dict and 'natural_traction_binding' in coupling:
                if self._radial_constitutive is None:
                    raise TectonicsError('full reservoir traction binding requires the radial physical-pressure route')
                coupling_keys.add('natural_traction_binding')
            if type(coupling) is not dict or set(coupling) != coupling_keys:
                raise TectonicsError('explicit finite-mode coupling contract required')
            if 'natural_traction_binding' in coupling:
                _checked_traction_binding(coupling['natural_traction_binding'], tractions, self._pattern)
            _name(coupling['source'], 'coupling source')
            mode_shape = np.shape(coupling['boundary_modes_m'])
            if len(mode_shape) != 3 or not 1 <= mode_shape[0] <= 12 or mode_shape[1:] != (nv, 3):
                raise TectonicsError('one to twelve supported boundary modes required')
            coupling = {k: (json.loads(json.dumps(v)) if k == 'natural_traction_binding' else v)
                        if k in ('source', 'pressure_reference_id', 'natural_traction_binding') else frozen(np.asarray(v, dtype=float))
                        for k, v in coupling.items()}
        initial, power, rates, initial_info = self._mechanics(state, velocity, tractions,
            gravity if gravity_binding is None else gravity_m_s2, force, driving_source, coupling, cancel)
        flow = self._transport.project_velocity(initial.array('velocity_m_s'),
            source_result_id=initial.result_id, cancel=cancel)
        cellrate = np.sum(rates*self._weights, axis=1).reshape(self.cells)
        histories = dict(histories)
        prior_strain = histories['accumulated_strain_ii']
        histories['accumulated_strain_ii'] = histories['accumulated_strain_ii']+mass*cellrate*dt
        radial_audit = {}
        if self._radial_constitutive is not None:
            local = self._last_radial
            if local.descriptor()['mechanical_result_id'] != initial.result_id:
                raise TectonicsError('radial source law is not from the actual initial mechanical solve')
            plastic_rate = local.array('plastic_kappa_rate_s_1')
            before_plastic = histories['radial_plastic_kappa']
            histories['radial_plastic_kappa'] = (before_plastic+mass*
                np.sum(plastic_rate*self._weights, axis=1).reshape(self.cells)*dt)
            radial_audit = dict(plastic_kappa_rate_s_1=plastic_rate,
                plastic_history_before_kg=before_plastic,
                plastic_history_after_sources_kg=histories['radial_plastic_kappa'],
                creep_dissipation_w_m3=local.array('creep_power_w_m3'),
                plastic_dissipation_w_m3=local.array('plastic_power_w_m3'),
                physical_mean_pressure_pa=local.array('physical_mean_pressure_pa'),
                numerical_volumetric_viscous_work_w_m3=local.array('numerical_volumetric_viscous_work_w_m3'))
        if self._rheology_family == 'bf23-memory':
            next_damage = advance_memory(self._profile, damage, cellrate*self._cs.time_s,
                td, dt/self._cs.time_s, budget=self._resource, cancel=cancel)
            histories['damage'] = mass*next_damage
        # Source heating is attached to the donor material before its transport;
        # conduction then acts on the advected heat. Both are first-order split.
        external_source = _array(heat_source_w_m3, self.cells, 'heat source', scalar_ok=True)
        source = external_source+self._material.internal_heating_w_m3
        viscous_source = np.zeros(self.cells)
        if self._heating:
            viscous_source = np.sum(power*self._weights, axis=1).reshape(self.cells)
            source = source+viscous_source
        source_energy = source*self._volume*dt
        heated_E = E+source_energy
        if not np.isfinite(heated_E).all() or np.any(heated_E <= 0):
            raise TectonicsError('source update would create nonpositive/nonfinite enthalpy')
        source_audit = RegionalMechanicalSnapshot(dict(
            schema='atlas.regional-evolution3d-source-audit.v1', plan_id=self.plan_id,
            cells=self.cells, lengths_m=self.lengths_m,
            parent_state_id=state.result_id, initial_mechanics_id=initial.result_id,
            start_time_s=state.descriptor()['time_s'], duration_s=dt,
            rheology_family=self._rheology_family, rheology=self._definition['rheology'],
            include_viscous_heating=self._heating,
            mechanical_source=driving_source, heat_source=heat_source,
            order='donor source update; then transport; then conduction',
            viscous_work=('actual 3D deviatoric creep/plastic law from initial mechanics; numerical volumetric work excluded'
                if self._radial_constitutive is not None else
                '2 eta symgrad(u):symgrad(u) from the initial mechanical solve only'),
            exclusion='exterior drag, boundary heat and conduction are not volume-source heat',
            rounding='requested energy and actual before/after enthalpy are retained separately',
            **({} if self._radial_constitutive is None else
               dict(constitutive_result_id=local.result_id))),
            dict(viscous_dissipation_w_m3=power, strain_rate_ii_s_inv=rates,
                quadrature_fraction=self._weights,
                cell_volume_m3=np.full(self.cells, self._volume),
                external_heat_source_w_m3=external_source,
                material_heat_source_w_m3=np.full(self.cells, self._material.internal_heating_w_m3),
                viscous_heat_source_w_m3=viscous_source,
                total_heat_source_w_m3=source, requested_source_energy_j=source_energy,
                enthalpy_before_sources_j=E, enthalpy_after_sources_j=heated_E,
                strain_history_before_kg=prior_strain,
                strain_history_after_sources_kg=histories['accumulated_strain_ii'], **radial_audit))
        carried_quadrature = ({'material_quadrature_m3': state.array('material_quadrature_m3')}
                              if 'material_quadrature_m3' in state.array_names else {})
        inventory = RegionalMechanicalSnapshot(dict(
            schema='atlas.regional-donor-stage.v1', plan_id=self.plan_id,
            parent_state_id=state.result_id, start_time_s=state.descriptor()['time_s'],
            duration_s=dt, driving_source=driving_source, heat_source=heat_source,
            initial_constitutive=initial_info),
            dict(component_mass_kg=m, enthalpy_j=heated_E, **carried_quadrature,
                 **{'tracer:'+name: value for name, value in histories.items()}))
        driving_arrays = dict(velocity_m_s=velocity, additional_body_force_n_m3=force,
                              gravity_m_s2=gravity, **{'traction:'+s: v for s, v in tractions.items()})
        driving_record = dict(source=driving_source, coupling=None)
        if gravity_binding is not None:
            driving_record['radial_gravity'] = gravity_binding
        if coupling is not None:
            driving_record['coupling'] = {k: v for k, v in coupling.items()
                                           if k in ('source', 'pressure_reference_id', 'natural_traction_binding')}
            driving_arrays.update({'coupling:'+k: v for k, v in coupling.items()
                                   if k not in ('source', 'pressure_reference_id', 'natural_traction_binding')})
        return RegionalDonorStage3D(inventory, RegionalMechanicalSnapshot(driving_record, driving_arrays),
                                    initial, flow, source_audit,
                                    None if gravity_binding is None else gravity_m_s2)

    def endpoint_from_sources(self, stage, fields, *, transport_id, heat_id, cancel=None):
        """Refresh actual interior endpoint mechanics after one external FV step."""
        with self._operation(cancel), self._resource.reserve(self._advance_work_bytes,
                category='regional-evolution3d-source-endpoint'):
            return self._endpoint_from_sources(stage, fields, transport_id=transport_id,
                                               heat_id=heat_id, cancel=cancel)

    def _endpoint_from_sources(self, stage, fields, *, transport_id, heat_id, cancel):
        if type(stage) is not RegionalDonorStage3D or stage.inventory.descriptor().get('plan_id') != self.plan_id:
            raise TectonicsError('donor source stage belongs to another native plan')
        _name(transport_id, 'transport identity'); _name(heat_id, 'heat identity')
        meta = stage.inventory.descriptor()
        if ('material_quadrature_m3' in fields) != ('material_quadrature_m3' in stage.inventory.array_names):
            raise TectonicsError('native endpoint cannot add or discard carried material quadrature')
        audit = stage.source_audit
        if (audit.descriptor()['parent_state_id'] != meta['parent_state_id'] or
                audit.descriptor()['initial_mechanics_id'] != stage.initial_mechanics.result_id):
            raise TectonicsError('donor source audit/parent/mechanics mismatch')
        step_source = _hash(dict(initial_mechanics_id=stage.initial_mechanics.result_id,
            transport_id=transport_id, heat_id=heat_id, heat_source=meta['heat_source'],
            volume_source_sha256=_digest_array(audit.array('total_heat_source_w_m3')),
            source_audit_id=audit.result_id))
        next_state = self._state(fields, meta['start_time_s']+meta['duration_s'],
                                 step_source, meta['parent_state_id'])
        velocity, tractions, gravity, force, coupling = stage.mechanical_arguments()
        final, _, _, final_info = self._mechanics(next_state, velocity, tractions,
            gravity, force, meta['driving_source'], coupling, cancel)
        return RegionalSourceEndpoint3D(next_state, final, _json(final_info))

    def advance(self, state, duration_s, *, velocity_m_s, dynamic_traction_pa,
                gravity_m_s2, additional_body_force_n_m3, driving_source,
                heat_boundaries, heat_source_w_m3, heat_source, boundary_stocks,
                coupling=None, cancel=None):
        """One first-order split interval; returned stocks must replace old stocks.

        Donor source arithmetic is shared with the typed enlarged-grid consumer.
        Rejection publishes no new state and mutates no input or exterior stock.
        """
        with self._operation(cancel), self._resource.reserve(self._advance_work_bytes,
                category='regional-evolution3d-advance'):
            if type(state) is RegionalMechanicalSnapshot and 'material_quadrature_m3' in state.array_names:
                raise TectonicsError('material quadrature requires the joined spatial transport and mass-capacity heat route')
            stage = self._prepare_source_stage(state, duration_s, velocity_m_s=velocity_m_s,
                dynamic_traction_pa=dynamic_traction_pa, gravity_m_s2=gravity_m_s2,
                additional_body_force_n_m3=additional_body_force_n_m3, driving_source=driving_source,
                heat_source_w_m3=heat_source_w_m3, heat_source=heat_source, coupling=coupling, cancel=cancel)
            dt = stage.inventory.descriptor()['duration_s']
            initial, flow, source_audit = stage.initial_mechanics, stage.flow, stage.source_audit
            initial_info = stage.inventory.descriptor()['initial_constitutive']
            source = source_audit.array('total_heat_source_w_m3')
            m, heated_E = stage.inventory.array('component_mass_kg'), stage.inventory.array('enthalpy_j')
            histories = {k.removeprefix('tracer:'): stage.inventory.array(k)
                         for k in stage.inventory.array_names if k.startswith('tracer:')}
            transported = self._transport.advect(m, heated_E, histories, flow, dt,
                boundary_stocks=boundary_stocks, cancel=cancel)
            conductive = self._heat.advance(transported.array('enthalpy_j'), dt,
                heat_boundaries, 0., source_id=heat_source, cancel=cancel)
            fields = dict(component_mass_kg=transported.array('component_mass_kg'),
                enthalpy_j=conductive.array('enthalpy_j'))
            fields.update({'tracer:'+k: transported.array('tracer:'+k) for k in histories})
            endpoint = self._endpoint_from_sources(stage, fields, transport_id=transported.result_id,
                heat_id=conductive.result_id, cancel=cancel)
            next_state, final = endpoint.state, endpoint.mechanics
            final_info = endpoint.descriptor()
            step_source = next_state.descriptor()['source']
            metadata = dict(schema='atlas.regional-evolution3d-advance.v2', plan_id=self.plan_id,
                parent_state_id=state.result_id, state_id=next_state.result_id, duration_s=dt,
                initial_mechanics_id=initial.result_id, mechanics_id=final.result_id,
                transformation_id=step_source, transport_id=transported.result_id,
                heat_id=conductive.result_id,
                source_audit_id=source_audit.result_id,
                initial_constitutive=initial_info, endpoint_constitutive=final_info,
                mechanical_source=driving_source, heat_source=heat_source,
                volume_source_energy_j=float(np.sum(source)*self._volume*dt),
                memory_source=('engineering plastic rate from initial full-stress solve, then conservative advection'
                    if self._radial_constitutive is not None else
                    'BF23 exact frozen-coefficient update then advection' if self._rheology_family == 'bf23-memory' else 'no damage evolution law'),
                time_method=('first-order source/transport/conduction splitting; '+
                    self._transport.transport_method+' transport; backward-Euler conduction; endpoint mechanics'),
                scientific_acceptance=False,
                scope='fixed Cartesian Boussinesq evolution; no elastic tensor, moving surface, fracture or sphere')
            self._stats['accepted_intervals'] += 1
            return RegionalEvolutionAdvance3D(next_state, initial, final, transported,
                conductive, _json(metadata), source_audit)

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
        self._last = self._eta = self._last_radial = None
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self, *_):
        self.close()
