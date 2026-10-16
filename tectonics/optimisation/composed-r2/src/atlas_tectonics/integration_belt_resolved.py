"""Resolved local Newtonian transform belt, with work-conjugate force coupling.

WORKING NON-CANON. A fixed Cartesian material snapshot, not the spherical mapper,
nonlinear rheology or a material/history step. See I04_REDUCTION_FULL_STRESS.md.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from ._validation import TectonicsError, frozen, input_shape, scalar, snapshot
from .regional_execution import RegionalMechanicalSnapshot
from .regional_execution3d import PreparedRegionalStokes3D, SIDES
from .resources import WorkBudget


SCHEMA = 'atlas.resolved-newtonian-transform-belt.v1'
WORK_RELATIVE = 5e-9          # retained regional mechanical-work gate
FORCE_RELATIVE = 5e-8        # retained regional finite-mode force gate


def _name(value, label):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise TectonicsError(label+' must be a bounded nonempty identifier')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _ownership(values, cells, available_bytes):
    """One actual (material patch, sublayer) pair for each native Gauss point; no implicit averaging."""
    if type(values) not in (tuple, list) or len(values) != cells:
        raise TectonicsError('one material-ownership row per belt element is required')
    rows, encoded_bytes = [], 2
    for row in values:
        if type(row) not in (tuple, list) or len(row) != 27:
            raise TectonicsError('27 material owners per belt element are required')
        owners = []
        encoded_bytes += 2+bool(rows)
        for owner in row:
            if type(owner) not in (tuple, list) or len(owner) != 2:
                raise TectonicsError('each Gauss point needs its actual material patch and sublayer identifiers')
            pair = tuple(_name(v, label) for v, label in zip(owner, ('material patch', 'sublayer')))
            encoded_bytes += len(_json(pair))+bool(owners)
            if 8*encoded_bytes > available_bytes:
                raise TectonicsError('resolved belt owner metadata exceeds the explicit work budget')
            owners.append(pair)
        rows.append(tuple(owners))
    return tuple(rows), encoded_bytes


@dataclass(frozen=True, slots=True)
class ResolvedTransformResult:
    mechanical: RegionalMechanicalSnapshot
    exchange: RegionalMechanicalSnapshot


class PreparedResolvedTransformBelt:
    """A same-time fixed-Newtonian-viscosity anti-plane belt on an explicit box.

    Coordinates are x=strike, y=across width, z=vertical. Viscosity is supplied at
    the regional solver's Gauss points and must be exactly invariant along x.
    Material ownership is supplied at every point; provenance binds the actual
    patch/layer/temperature-derived material state. This class does not derive or
    average that field from P2, nor infer a temperature-dependent constitutive law.

    Transverse velocities are zero on every wall. Across-width walls prescribe
    ux = +/- delta_v/2. Other walls prescribe zero x traction, giving free top/base
    anti-plane shear and a strike-invariant solution. Normal/ridge/trench flow,
    body force, extra stress, plasticity and elasticity are not this contract.
    The caller supplies the native solver budget and a separate bound on wrapper
    storage; neither is a process RSS guarantee. There is no growing result cache.
    """
    __slots__ = ('_plan', '_eta', '_definition', '_modes', '_walls', '_weights',
                 '_width', '_length', 'belt_id')

    def __setattr__(self, name, value):
        raise TectonicsError('prepared resolved belts are immutable')

    def __init__(self, cells, lengths_m, viscosity_pa_s, *, quadrature_owners,
                 material_state_id, support_id, scales, reference_viscosity_pa_s,
                 frame_id, vertical_datum, material_source, max_work_bytes,
                 method='auto', budget=None, cancel=None):
        if (type(cells) not in (tuple, list) or len(cells) != 3
                or any(type(v) is not int or not 2 <= v <= 24 for v in cells)):
            raise TectonicsError('resolved belt needs three cell counts in [2,24]')
        if type(lengths_m) not in (tuple, list) or len(lengths_m) != 3:
            raise TectonicsError('explicit strike length, width and depth are required')
        lengths = tuple(scalar(v, 'belt dimension', positive=True) for v in lengths_m)
        nc, nv = math.prod(cells), math.prod(2*v+1 for v in cells)
        if not isinstance(budget, WorkBudget):
            raise TectonicsError('resolved belt needs an explicit native WorkBudget')
        # Retained eta, quadrature volume, mode/wall arrays and peak result-derived
        # strain/heating arrays; native snapshots/solver storage have their own budget.
        fixed_bytes = 8*(nc*27*40+nv*15)+16384
        if type(max_work_bytes) is not int or max_work_bytes < fixed_bytes:
            raise TectonicsError('resolved belt buffers exceed the explicit work budget')
        owners, ownership_bytes = _ownership(quadrature_owners, nc, max_work_bytes-fixed_bytes)
        required = fixed_bytes+8*ownership_bytes
        if input_shape(viscosity_pa_s, 'resolved viscosity') != (nc, 27):
            raise TectonicsError('resolved viscosity needs one real value per Gauss point, not a cell mean')
        eta = snapshot(viscosity_pa_s, 'resolved viscosity')
        if not np.isfinite(eta).all() or np.any(eta <= 0.):
            raise TectonicsError('resolved viscosity must be finite and positive')
        shaped = eta.reshape(tuple(cells)+(3, 3, 3))
        if not np.array_equal(shaped, np.broadcast_to(shaped[0, :, :, 0, :, :][None, :, :, None, :, :],
                                                     shaped.shape)):
            raise TectonicsError('this transform closure requires strike-invariant viscosity')
        for value, label in ((material_state_id, 'material state'), (support_id, 'support')):
            _name(value, label)
        boundary = {side: ('traction', 'velocity', 'velocity') for side in SIDES}
        boundary['y0'] = boundary['y1'] = ('velocity',)*3
        plan = PreparedRegionalStokes3D(cells, lengths, eta, boundary, scales=scales,
            reference_viscosity_pa_s=reference_viscosity_pa_s, frame_id=frame_id,
            vertical_datum=vertical_datum, material_source=material_source,
            method=method, budget=budget, cancel=cancel)
        try:
            xyz = plan.coordinates('velocity')
            modes = np.zeros((1, nv, 3))
            modes[0, :, 0] = xyz[:, 1]-lengths[1]/2
            walls = (xyz[:, 1] == 0., xyz[:, 1] == lengths[1])
            if not all(np.any(wall) for wall in walls):
                raise TectonicsError('regional coordinates do not contain both declared belt walls')
            _, weights = np.polynomial.legendre.leggauss(3)
            indices = np.indices((3, 3, 3)).reshape(3, -1).T
            volumes = np.prod(weights[indices], axis=1)*math.prod(lengths)/(8*nc)
            definition = dict(schema=SCHEMA, plan_id=plan.plan_id, support_id=support_id,
                material_state_id=material_state_id, quadrature_owners=owners,
                rheology='fixed Newtonian viscosity at actual material Gauss points',
                coordinates='x strike; y across width; z vertical',
                kinematics='anti-plane; zero transverse wall velocities; free top/base shear',
                work_conjugacy='mode ux=y-width/2; delta_v=width*rate; generalized_force=width*shear_force',
                declared_wrapper_work_bytes=required)
            values = dict(_plan=plan, _eta=eta, _definition=_json(definition),
                          _modes=frozen(modes),
                          _walls=tuple(np.frombuffer(w.tobytes(), dtype=np.bool_) for w in walls),
                          _weights=frozen(np.broadcast_to(volumes, (nc, 27))), _width=lengths[1],
                          _length=lengths[0], belt_id=hashlib.sha256(_json(definition)).hexdigest())
            for name, value in values.items():
                object.__setattr__(self, name, value)
        except BaseException:
            plan.close()
            raise

    def descriptor(self):
        self._plan.descriptor()       # native source/closed-plan guard
        return json.loads(self._definition)

    def coordinates(self, site='quadrature'):
        return self._plan.coordinates(site)

    def statistics(self):
        return self._plan.statistics()

    def solve(self, shear_force_n, exterior_drag_n_s_m=0., *, parent_state_id,
              epoch_id, time_s, coupling_source, cancel=None):
        """Force is the total across the declared strike extent; exterior drag excludes this box."""
        force = scalar(shear_force_n, 'relative shear force')
        drag = scalar(exterior_drag_n_s_m, 'exterior shear drag', nonnegative=True)
        mechanical = self._plan.solve_force_coupled(0., 0., {side: 0. for side in SIDES}, self._modes,
            np.array([force*self._width]), np.array([[drag*self._width**2]]),
            parent_state_id=parent_state_id, epoch_id=epoch_id, time_s=time_s,
            coupling_source=coupling_source, force_source='explicit-zero-body-force',
            boundary_source='resolved-transform-symmetric-shear-mode', cancel=cancel)
        rate = float(mechanical.array('generalized_rates_s_inv')[0])
        speed = rate*self._width
        reaction = mechanical.array('velocity_constraint_reaction_n')
        wall_forces = np.array([np.sum(reaction[wall], axis=0) for wall in self._walls])
        gradient = mechanical.array('velocity_gradient_s_inv')
        strain = (gradient+gradient.swapaxes(-1, -2))/2
        heating = 2*self._eta*np.einsum('eqij,eqij->eq', strain, strain)
        integrated = float(np.sum(heating*self._weights))
        native_power = mechanical.descriptor()['power_w']['viscous_dissipation']
        scale = max(abs(integrated), abs(native_power))
        if not np.isfinite(heating).all() or (scale and abs(integrated-native_power) > WORK_RELATIVE*scale):
            raise TectonicsError('resolved belt quadrature heat does not close the native viscous work')
        shear = float(mechanical.array('generalized_regional_force_j')[0])/self._width
        wall_scale = max(abs(shear), abs(wall_forces[0, 0]), abs(wall_forces[1, 0]))
        if wall_scale and max(abs(wall_forces[0, 0]+shear), abs(wall_forces[1, 0]-shear)) > FORCE_RELATIVE*wall_scale:
            raise TectonicsError('resolved belt wall forces do not close their work-conjugate force')
        exchange = RegionalMechanicalSnapshot(dict(schema=SCHEMA, belt_id=self.belt_id,
            support=json.loads(self._definition), mechanical_result_id=mechanical.result_id,
            power_w=dict(material_viscous_heat=integrated, exterior_drag=drag*speed**2,
                         driving=force*speed),
            force_convention='wall forces on region; opposite signs on surroundings',
            heat_convention='2 eta symgrad(u):symgrad(u), owned once at each declared material Gauss point',
            scope='instantaneous local transform; no spherical mapping, material/history transport or phase law',
            scientific_acceptance=False),
            dict(relative_velocity_m_s=np.array([speed]), shear_force_on_region_n=np.array([shear]),
                 wall_forces_on_region_n=wall_forces, wall_forces_on_surroundings_n=-wall_forces,
                 heat_rate_w_m3=heating, quadrature_volume_m3=self._weights))
        return ResolvedTransformResult(mechanical, exchange)

    def close(self):
        self._plan.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
