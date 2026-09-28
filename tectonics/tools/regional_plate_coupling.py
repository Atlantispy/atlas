"""Same-time Euler plate motion <-> full-vector finite Cartesian-region work.

SPDX-License-Identifier: AGPL-3.0-only
Explicit flat-box embedding, not a spherical finite-element mesh or time step.
This adapter does not choose boundary ownership or invent external resistance.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from atlas_tectonics._validation import TectonicsError, frozen, scalar
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D
from atlas_tectonics.regional_forcing import PrescribedPlateMotion

_FILE = Path(__file__).resolve()
_SOURCE_SHA = hashlib.sha256(_FILE.read_bytes()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(a):
    return hashlib.sha256(a.tobytes()).hexdigest()


def _name(value, label):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise TectonicsError(label+' requires a nonempty bounded identifier')
    return value


def _array(value, shape, name):
    try:
        a = np.asarray(value)
        if a.dtype.kind not in 'fiu' or a.shape != shape:
            raise ValueError()
        a = np.asarray(a, dtype=float)
    except (ValueError, TypeError, OverflowError) as exc:
        raise TectonicsError(name+' requires real data of the declared shape') from exc
    if not np.all(np.isfinite(a)):
        raise TectonicsError(name+' must remain finite')
    return frozen(a)


def _source_guard():
    if hashlib.sha256(_FILE.read_bytes()).hexdigest() != _SOURCE_SHA:
        raise TectonicsError('plate coupling adapter changed; restart before execution')


@dataclass(frozen=True, slots=True)
class PlateRegionalResult3D:
    """Reuse the native snapshot without copying its large mechanical fields.

    exchange contains angular velocities, signed torques and per-plate power;
    its descriptor binds the mechanical result and the immutable mapping.
    """
    mechanical: RegionalMechanicalSnapshot
    exchange: RegionalMechanicalSnapshot


class PreparedPlateBoundary3D:
    """Prepared Euler modes for 1-4 plates on an existing regional plan.

    ``local_axes_global`` has the local x/y/z unit vectors as its COLUMNS.
    ``origin_m`` locates local (0,0,0) relative to the planet centre. Both frames
    are stationary at this instant: there is no implicit reference-plate motion.
    ``node_plate_index`` has one integer per velocity node: -1 unowned, otherwise
    an index into plate_ids. An owned node must prescribe ALL THREE components.
    Unowned fixed supports remain explicit, with separately supplied velocities.
    Max work bytes bounds this adapter's numerical buffers, not native solver/RSS.
    """
    __slots__ = ('_plan', '_owners', '_modes', '_ids',
                 '_global_frame', '_record', 'mapping_id')

    def __setattr__(self, name, value):
        raise TectonicsError('prepared plate mappings are immutable')

    def __init__(self, plan, *, global_frame_id, origin_m, local_axes_global,
                 plate_ids, node_plate_index, geometry_source, max_work_bytes):
        _source_guard()
        if type(plan) is not PreparedRegionalStokes3D:
            raise TectonicsError('an actual prepared regional 3D plan is required')
        definition = plan.descriptor()
        if (type(plate_ids) not in (tuple, list) or not 1 <= len(plate_ids) <= 4
                or any(type(p) is not str for p in plate_ids)
                or len(set(plate_ids)) != len(plate_ids)):
            raise TectonicsError('one to four distinct plate identifiers required')
        ids = tuple(_name(p, 'plate') for p in plate_ids)
        _name(global_frame_id, 'global frame'); _name(geometry_source, 'geometry source')
        n = int(np.prod(2*np.asarray(definition['cells'])+1))
        # Includes retained modes, their construction and solve input buffers.
        # The caller owns the native plan and its independently admitted budget.
        required = 8*n*(18*len(ids)+24)+16384
        if type(max_work_bytes) is not int or max_work_bytes < required:
            raise TectonicsError('plate mapping buffers exceed explicit work budget')
        origin = _array(origin_m, (3,), 'planet-centred origin')
        axes = _array(local_axes_global, (3,3), 'local frame axes')
        if (np.max(np.abs(axes.T@axes-np.eye(3))) > 1e-12
                or abs(np.linalg.det(axes)-1.) > 1e-12):
            raise TectonicsError('local axes must be orthonormal and right-handed')
        raw = np.asarray(node_plate_index)
        if (raw.shape != (n,) or raw.dtype.kind not in 'iu'
                or np.any(raw < -1) or np.any(raw >= len(ids))):
            raise TectonicsError('each node needs one valid integer owner or -1')
        owners = np.frombuffer(np.asarray(raw, dtype=np.int64).tobytes(), dtype=np.int64)
        owned = owners >= 0
        if any(not np.any(owners == i) for i in range(len(ids))):
            raise TectonicsError('every declared plate must own a velocity node')
        if not np.all(plan.velocity_mask()[owned]):
            raise TectonicsError('plate ownership requires all three prescribed velocity components')
        with np.errstate(over='ignore', invalid='ignore'):
            xyz = plan.coordinates('velocity')
            positions = _array(origin+xyz@axes.T, (n,3), 'embedded global positions')
            modes = np.zeros((3*len(ids),n,3))
            for i in range(len(ids)):
                at = owners == i
                for c in range(3):
                    modes[3*i+c,at] = np.cross(np.eye(3)[c],positions[at])@axes
            modes = _array(modes, modes.shape, 'Euler displacement modes')
        record = dict(schema='atlas.regional-plate-map.v1', regional_plan_id=plan.plan_id,
            adapter_sha256=_SOURCE_SHA, global_frame_id=global_frame_id,
            local_frame_id=definition['frame_id'], origin_m=origin.tolist(),
            local_axes_global=axes.tolist(), plate_ids=list(ids), geometry_source=geometry_source,
            node_owners_sha256=_digest(owners), modes_sha256=_digest(modes),
            embedding='stationary flat Cartesian box in planet-centred Cartesian axes',
            mode_order='plate order, then global x/y/z angular rates in rad/s',
            required_adapter_work_bytes=required, max_work_bytes=max_work_bytes)
        for key,value in dict(_plan=plan, _owners=owners, _modes=modes, _ids=ids,
                _global_frame=global_frame_id, _record=_json(record),
                mapping_id=hashlib.sha256(_json(record)).hexdigest()).items():
            object.__setattr__(self,key,value)

    def descriptor(self):
        return json.loads(self._record)

    def _base(self, unowned_velocity_m_s):
        base = _array(unowned_velocity_m_s, (len(self._owners),3), 'unowned velocity')
        if np.any(base[self._owners >= 0] != 0):
            raise TectonicsError('unowned velocity must be zero on plate-owned nodes')
        return base

    def _motion_rates(self, motions, epoch_id, time_s):
        if (type(motions) not in (tuple,list) or len(motions) != len(self._ids)
                or any(type(m) is not PrescribedPlateMotion for m in motions)
                or tuple(m.plate_id for m in motions) != self._ids):
            raise TectonicsError('one native plate motion per plate in declared order required')
        for m in motions:
            if (m.mode != 'spherical-euler' or m.frame_id != self._global_frame
                    or m.epoch_id != epoch_id or m.time_s != time_s):
                raise TectonicsError('Euler motion frame/epoch/time must match the request')
        return _array([m.angular_velocity_rad_s for m in motions], (len(self._ids),3), 'angular rates')

    def prescribed_velocity(self, motions, unowned_velocity_m_s, *, epoch_id, time_s):
        """Full local boundary trace; free-node values are not plate constraints."""
        _source_guard()
        _name(epoch_id, 'epoch'); time_s = scalar(time_s,'time')
        rates = self._motion_rates(motions,epoch_id,time_s)
        base = self._base(unowned_velocity_m_s)
        with np.errstate(over='ignore', invalid='ignore'):
            return _array(base+np.einsum('m,mij->ij', rates.ravel(),self._modes),
                          base.shape, 'mapped plate velocity')

    def _result(self, mechanical, rates, request):
        reactions = mechanical.array('velocity_constraint_reaction_n')
        with np.errstate(over='ignore', invalid='ignore'):
            # Adjoint of the SAME discrete velocity map. No stress resampling,
            # area weights, fixed-support reactions or sign reversal hidden here.
            torques = _array(np.einsum('mij,ij->m',self._modes,reactions).reshape(-1,3),
                             rates.shape, 'regional torque')
            power = _array(np.sum(torques*rates,axis=1), (len(self._ids),), 'plate work rate')
        exchange = RegionalMechanicalSnapshot(dict(mapping=self.descriptor(),
            mapping_id=self.mapping_id, mechanical_result_id=mechanical.result_id,
            request=request, torque_convention='on-region; opposite sign on plates',
            power_convention='angular_velocity dot torque_on_region; excludes unowned supports'),
            dict(angular_velocity_rad_s=rates, torque_on_region_nm=torques,
                 torque_on_plates_nm=-torques, plate_power_into_region_w=power))
        _source_guard()
        return PlateRegionalResult3D(mechanical,exchange)

    def solve_prescribed(self, motions, body_force_n_m3, unowned_velocity_m_s,
                         traction_pa, *, parent_state_id, epoch_id, time_s,
                         force_source, boundary_source, extra_stress_pa=None,
                         stress_source='explicit-zero-extra-stress', cancel=None):
        velocity = self.prescribed_velocity(motions,unowned_velocity_m_s,
                                           epoch_id=epoch_id,time_s=time_s)
        mechanical = self._plan.solve(body_force_n_m3,velocity,traction_pa,
            parent_state_id=parent_state_id,epoch_id=epoch_id,time_s=time_s,
            force_source=force_source,boundary_source=boundary_source,
            extra_stress_pa=extra_stress_pa,stress_source=stress_source,cancel=cancel)
        return self._result(mechanical,self._motion_rates(motions,epoch_id,time_s),
                            dict(mode='prescribed', motions=[m.descriptor() for m in motions]))

    def solve_torque_coupled(self, body_force_n_m3, unowned_velocity_m_s, traction_pa,
                             external_torque_nm, external_resistance_nm_s, *,
                             coupling_source, parent_state_id, epoch_id, time_s,
                             force_source, boundary_source, extra_stress_pa=None,
                             stress_source='explicit-zero-extra-stress', cancel=None):
        """Solve all three angular rates per plate; external drag excludes the box.

        Resistance is (3P,3P), ordered plate then global Cartesian axis. Existing
        flux, reciprocity, conditioning, budget and cancellation gates still apply.
        A selected subset of axes or a dropped torque component is not supported.
        """
        _source_guard()
        torque = _array(external_torque_nm, (len(self._ids),3), 'external torque')
        drag = _array(external_resistance_nm_s, (3*len(self._ids),)*2, 'external resistance')
        base = self._base(unowned_velocity_m_s)
        mechanical = self._plan.solve_force_coupled(body_force_n_m3,base,traction_pa,
            self._modes,torque.ravel(),drag,coupling_source=coupling_source,
            parent_state_id=parent_state_id,epoch_id=epoch_id,time_s=time_s,
            force_source=force_source,boundary_source=boundary_source,
            extra_stress_pa=extra_stress_pa,stress_source=stress_source,cancel=cancel)
        return self._result(mechanical,mechanical.array('generalized_rates_s_inv').reshape(-1,3),
            dict(mode='torque-coupled', external_torque_nm=torque.tolist(),
                 external_resistance_nm_s=drag.tolist(), coupling_source=coupling_source))
