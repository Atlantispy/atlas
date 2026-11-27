"""Analytic spherical hydrostatic lifting, distinct from a discrete Q1 split.

p_h=P0+rho0*g*(R-r), grad(p_h)=rho0*g_vector. Subtracting this
KNOWN continuum solution before discretisation prevents its non-Q1 pressure
from generating Taylor--Hood velocity pollution. It does not project away
unknown anomaly loads or assert that the total pressure is hydrostatic.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction
import weakref

import numpy as np

from atlas_tectonics._validation import scalar
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RadialHydrostaticLift:
    _snapshot: RegionalMechanicalSnapshot
    _resource: object

    def __init__(self, *args, **kwargs):
        raise TypeError('radial hydrostatic lifting is issued from mapped gravity and current state')

    @property
    def lift_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(lift_id=self.lift_id, **self._snapshot.descriptor())

    def array(self, name):
        return self._snapshot.array(name)

    def bind(self, plan, parent_state_id, time_s):
        _, _ = self.descriptor(), plan.descriptor()


def radial_hydrostatic_lift(gravity, plan, *, density_kg_m3, parent_state_id, time_s, budget):
    from atlas_tectonics.regional.execution3d import SIDES
    rho = scalar(density_kg_m3, 'hydrostatic reference density', positive=True)
    time = scalar(time_s, 'hydrostatic current time', nonnegative=True)
    gd, pd = gravity.descriptor(), plan.descriptor()
    embedding, datum = gd['embedding'], gd['datum']
    decode = lambda pair: Fraction(int(pair[0], 16), int(pair[1], 16))
    basis = np.asarray([[float(decode(v)) for v in row] for row in embedding['basis']])
    origin = np.asarray([float(decode(v)) for v in embedding['origin_global_m']])
    R, g, P0 = datum['reference_radius_m'], datum['gravity_m_s2'], datum['surface_pressure_pa']
    nc, nv, np_ = plan._mesh.nc, plan._mesh.nv, plan._mesh.np
    with budget.reserve(65536+4096*(27*nc+nv+np_), category='radial-hydrostatic-lifting'):
        def pressure(local):
            xyz = origin+local@basis.T
            radius = np.linalg.norm(xyz, axis=-1)
            value = P0+rho*g*(R-radius)
            return value
        arrays = dict(pressure_pa=pressure(plan.coordinates('pressure')),
            pressure_q_pa=pressure(plan.coordinates('quadrature')),
            reference_body_force_n_m3=rho*gravity.array())
        for index, side in enumerate(SIDES):
            local = plan.coordinates(side)
            traction = np.zeros_like(local)
            traction[..., index//2] = pressure(local)*(1 if index%2 == 0 else -1)
            arrays['traction:'+side] = traction
        snapshot = RegionalMechanicalSnapshot(dict(schema='atlas.analytic-radial-hydrostatic-lift.v1',
            gravity_field_id=gravity.field_id, volume_map_id=gd['volume_map_id'],
            native={k: pd[k] for k in ('cells', 'lengths_m', 'scales', 'frame_id', 'material_source', 'boundary_types')},
            parent_state_id=parent_state_id, time_s=time,
            density_kg_m3=rho, gravity_m_s2=g, reference_radius_m=R,
            surface_pressure_pa=P0, pressure_constant_pa=P0+rho*g*R,
            physical_centre_m=[0., 0., 0.], embedding=embedding,
            law='p_h=P0+rho_ref*g*(R-|x|); grad(p_h)=rho_ref*g_vector',
            scope='known analytic pressure component, not total solved mean stress or an anomaly projection'), arrays)
        result = object.__new__(RadialHydrostaticLift)
        object.__setattr__(result, '_snapshot', snapshot)
        object.__setattr__(result, '_resource', budget)
        lease = budget.reserve(8192+2*snapshot.nbytes, category='radial-hydrostatic-retained')
        lease.__enter__()
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
