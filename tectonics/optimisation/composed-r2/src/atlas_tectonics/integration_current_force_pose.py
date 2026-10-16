"""Current common-trajectory force geometry with explicit pose error accounts.

The rational representative is exactly orthogonal, but is NOT the exact
exponential trajectory. Its proved error is carried into owner predicates,
torques and virtual work. No material or thermal state is resampled here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction as Q
import hashlib
import json
import weakref

import numpy as np

from ._validation import TectonicsError
from . import integration_volume as V, integration_volume_bounds as B
from . import integration_volume_overlap as O, integration_wall_measures as W
from . import integration_exterior_mesh as E, integration_collar_geometry as F
from . import integration_support as U, integration_sphere as S
from .regional_execution import RegionalMechanicalSnapshot
from .resources import WorkBudget


def _q(value):
    if type(value) not in (Q, int):
        raise TectonicsError('an explicit exact rational numerical error budget is required')
    return Q(value)


def _enc(value):
    return V._encoded(Q(value))


def _retain(result, budget, size):
    lease = budget.reserve(size, category='current-force-pose-retained')
    lease.__enter__()
    try:
        weakref.finalize(result, lease.__exit__, None, None, None)
    except BaseException:
        lease.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class CurrentForcePose:
    _record: bytes
    _rotation: tuple
    _error: Q
    _resource: object

    def __init__(self, *args, **kwargs):
        raise TypeError('CurrentForcePose is issued from actual retained wall trajectory')

    @property
    def pose_id(self):
        return hashlib.sha256(self._record).hexdigest()

    def descriptor(self):
        return dict(pose_id=self.pose_id, **json.loads(self._record))

    def rotation(self):
        return self._rotation

    def contains(self, cells, point):
        """Prove current point in the declared original face's moved support.

        An undecidable point is refused, not snapped onto a preferred owner.
        Internal fan edges are removed when their exact convex union is proved.
        """
        point = tuple(Q(float(v)) for v in point)
        with V._work((*point, *(q for row in self._rotation for q in row), self._error), self._resource):
            inverse = tuple(sum(self._rotation[j][i]*point[j] for j in range(3)) for i in range(3))
            radius_bound = sum(map(abs, point))
            try:
                cells = (V.convex_cone_union(cells, budget=self._resource),)
            except V.VolumeError:
                pass
            for cell in cells:
                with V._work((*(v for p in cell for v in p), *inverse, radius_bound, self._error), self._resource):
                    margins = []
                    for a, b in zip(cell, cell[1:]+cell[:1]):
                        normal = O._cross(a, b)
                        value = O._dot(normal, inverse)
                        uncertainty = self._error*radius_bound*sum(map(abs, normal))
                        margins.append(value-uncertainty)
                    if all(v >= 0 for v in margins):
                        return True
            return False


def current_force_pose(sphere, funding, walls, *, max_operator_error, budget):
    """Issue the end geometry of an accepted/pending common rigid trajectory.

    The enclosing transaction binds acceptance; this read-only calculation
    cannot publish a trajectory or turn differential plate rates into one Ω.
    """
    if (type(sphere) is not S.SphereState or type(funding) is not F.FullCellFunding or
            type(walls) is not W.WallMeasures or type(budget) is not WorkBudget or
            funding._resource is not budget or walls._resource is not budget):
        raise TectonicsError('actual source, funding, trajectory and one shared budget required')
    goal = _q(max_operator_error)
    if not 0 < goal < 1:
        raise TectonicsError('pose operator budget must be strictly between zero and one')
    source, motion = funding.descriptor(), walls.descriptor()
    if (source['source']['sphere_state_id'] != sphere.state_id or
            source['source']['network_id'] != sphere.network.network_id or
            motion['source'] != source['source'] or motion['funding_id'] != funding.funding_id or
            motion['collar_plan_id'] != source['collar_plan_id']):
        raise TectonicsError('current force geometry has stale source/funding/trajectory')
    with budget.reserve(65536+8*len(walls._json), category='current-force-pose'), B._Arena(budget) as arena:
        quaternion, error = E._representative_pose(motion['trajectory']['segments'], goal, arena)
        rotation = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
        record = dict(schema='atlas.current-common-force-pose.v1', source=source['source'],
            funding_id=funding.funding_id, wall_measure_id=walls.measure_id,
            trajectory_id=motion['trajectory_id'], support_id=motion['end_support_id'],
            time_s=motion['end_time_s'], parent_state_id=motion['parent_state_id'],
            representative_quaternion=list(map(_enc, quaternion)),
            representative_rotation=[[ _enc(v) for v in row] for row in rotation],
            operator_error_bound=_enc(error), requested_operator_error=_enc(goal),
            geometry='exact composed common rigid trajectory; rational representative with proved norm error',
            scope='current geometry only; independent plate rates are not advanced as a common trajectory')
        encoded = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        result = object.__new__(CurrentForcePose)
        for name, value in (('_record', encoded), ('_rotation', rotation), ('_error', error), ('_resource', budget)):
            object.__setattr__(result, name, value)
        _retain(result, budget, 8192+8*len(encoded))
        return result


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class CurrentForceBackground:
    _snapshot: RegionalMechanicalSnapshot
    _resource: object

    def __init__(self, *args, **kwargs):
        raise TypeError('current force background is issued from the actual common pose')

    @property
    def background_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(background_id=self.background_id, **self._snapshot.descriptor())

    def array(self, name):
        return self._snapshot.array(name)


def rotated_background(pose, network, exterior, prepared, *, max_torque_error_n_m,
                       max_power_error_w, angular_rate_l2_bound_s_inv, budget):
    """Rotate source-bound force vectors/tensors; report both numerical errors.

    ||Q*-Q||<=δ implies vector error<=δ||b|| and tensor error<=2δ||M||.
    Sum-absolute norms bound the Euclidean/operator norms without a rounded
    square root. The caller's angular-rate bound converts these to watts.
    """
    from . import integration_driving as D
    if (type(pose) is not CurrentForcePose or type(network) is not S.SphereNetwork or
            type(exterior) is not D.Balance or type(prepared) is not D.Prepared or pose._resource is not budget):
        raise TectonicsError('issued current pose and actual source-bound D1 objects required')
    data = pose.descriptor()
    if (data['source']['network_id'] != network.network_id or exterior.network_id != network.network_id or
            prepared.network_id != network.network_id or exterior.prepared_id != prepared.prepared_id or
            exterior.parent_state_id != data['source']['sphere_state_id']):
        raise TectonicsError('background force source differs from the current trajectory source')
    if set(exterior.terms)-{'radial_pressure', 'gpe', 'slab_pull'}:
        raise TectonicsError('only material-attached covariant background loads can be rigidly rotated; external vectors need new current forcing')
    torque_limit, power_limit, rate_limit = map(_q, (max_torque_error_n_m, max_power_error_w, angular_rate_l2_bound_s_inv))
    if min(torque_limit, power_limit, rate_limit) < 0:
        raise TectonicsError('nonnegative force/work/rate budgets required')
    n = 3*len(network.plate_ids)
    # Each tensor entry sums nine Q*M*Q products. Product integer widths add;
    # sum widths are bounded by the sum of term widths plus carry bits. Charge
    # live rational tensors, their exact projection residuals and hex encoding
    # before allocating them. Only the encoded snapshot stays retained.
    pose_bits = max(V._bits(v) for row in pose.rotation() for v in row)
    entry_bits = 9*(2*pose_bits+2150)+64
    size = 65536+8*len(pose._record)+(n*n+n)*(2048+8*((entry_bits+7)//8))
    with budget.reserve(size, category='current-force-background'):
        rotation = pose.rotation()
        original = np.zeros((len(network.plate_ids), 3))
        for term in exterior.terms.values():
            original += term
        force = tuple(Q(float(v)) for v in original.flat)
        matrix = tuple(tuple(Q(float(v)) for v in row) for row in prepared.matrix)
        # Block-diagonal Q without a dense exact 3N-square temporary.
        vector = tuple(sum(rotation[i % 3][k]*force[i-i % 3+k] for k in range(3)) for i in range(n))
        tensor = tuple(tuple(sum(rotation[i % 3][a]*matrix[i-i % 3+a][j-j % 3+b]*rotation[j % 3][b]
            for a in range(3) for b in range(3)) for j in range(n)) for i in range(n))
        fv = np.asarray(list(map(float, vector)))
        fm = np.asarray([[float(v) for v in row] for row in tensor])
        if not np.isfinite(fv).all() or not np.isfinite(fm).all():
            raise TectonicsError('current background cannot be represented in binary64')
        vector_residual = tuple(Q(float(v))-q for v, q in zip(fv, vector))
        matrix_residual = tuple(tuple(Q(float(v))-q for v, q in zip(row, exact)) for row, exact in zip(fm, tensor))
        force_error = pose._error*sum(map(abs, force))+sum(map(abs, vector_residual))
        matrix_error = 2*pose._error*sum(abs(v) for row in matrix for v in row)+sum(abs(v) for row in matrix_residual for v in row)
        power_error = force_error*rate_limit+matrix_error*rate_limit**2
        if force_error > torque_limit or power_error > power_limit:
            raise TectonicsError('current pose exceeds declared torque or virtual-work uncertainty budget')
        snapshot = RegionalMechanicalSnapshot(dict(schema='atlas.current-force-background.v1', pose=data,
            exterior_balance_id=exterior.balance_id, exterior_prepared_id=prepared.prepared_id,
            force_error_bound_n_m=_enc(force_error), resistance_operator_error_bound_j_s=_enc(matrix_error),
            power_error_bound_w=_enc(power_error), angular_rate_l2_bound_s_inv=_enc(rate_limit),
            requested_torque_error_n_m=_enc(torque_limit), requested_power_error_w=_enc(power_limit),
            force_projection_residual_n_m=list(map(_enc, vector_residual)),
            resistance_projection_residual_j_s=[[ _enc(v) for v in row] for row in matrix_residual],
            rule='Q b and block-Q M block-Q transpose; no stale-axis basal drag'),
            dict(force_n_m=fv.reshape(-1, 3), resistance_j_s=fm))
        result = object.__new__(CurrentForceBackground)
        object.__setattr__(result, '_snapshot', snapshot)
        object.__setattr__(result, '_resource', budget)
        _retain(result, budget, 8192+2*snapshot.nbytes)
        return result
