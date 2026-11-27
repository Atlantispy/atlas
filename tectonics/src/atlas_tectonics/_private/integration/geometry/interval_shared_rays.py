"""Uninstalled interval-scoped shared-ray candidate for bounded diagnostics.

The issuer determines trajectory and eligible material rates. This is not a
mesh implementation or a proof of source coverage or physical acceptance.
"""
from fractions import Fraction as Q


class IntervalRays:
    def __init__(self, interval, *, budget, arena, D, W, V, E):
        self.D, self.W, self.V, self.E, self.arena = D, W, V, E, arena
        self.interval = interval
        arena._retain(65536 + 4 * len(interval._json))
        self.record = interval.record()
        self.duration = W._decode(self.record['end_time_s']) - W._decode(self.record['start_time_s'])
        self.rates = frozenset(tuple(map(W._decode, rate)) for rate in
                               self.record['plate_angular_velocity_rad_s'].values())
        arena.keep(tuple(x for rate in self.rates for x in rate), objects=len(self.rates))
        self.rays = {}
        self.poses = {}

    def _pose(self, omega):
        if omega in self.poses:
            return self.poses[omega]
        V, E, arena = self.V, self.E, self.arena
        arena.work(32)
        segment = dict(angular_velocity_rad_s=[V._encoded(x) for x in omega],
                       start_time_s=V._encoded(Q(0)), end_time_s=V._encoded(self.duration))
        quat, error = E._representative_pose([segment], Q(1, 1 << 48), arena)
        matrix = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=arena.resource).rotated(
            quat, budget=arena.resource).basis
        if not omega[0] and not omega[1] and omega[2]:
            C, S = matrix[0][0], matrix[1][0]
            theta = omega[2] * self.duration
            residual = (abs(C - (1 - theta**2 / 2)) + abs(theta)**4 / 24 +
                        abs(S - (theta - theta**3 / 6)) + abs(theta)**5 / 120)
            error = min(error, residual)
        arena.keep(tuple(x for row in matrix for x in row) + (error,), objects=1)
        self.poses[omega] = (matrix, error)
        return matrix, error

    def ray(self, name):
        row = self.record['rays'][name]
        direction = tuple(map(self.W._decode, row['direction']))
        omega = tuple(map(self.W._decode, row['angular_velocity_rad_s']))
        trajectory = (direction, omega, self.duration)
        if trajectory in self.rays:
            return self.rays[trajectory]
        self.arena.work(32)
        if omega in self.rates:
            matrix, pose_error = self._pose(omega)
            with self.V._work((*direction, pose_error), self.arena.resource):
                value = tuple(sum(matrix[i][j] * direction[j] for j in range(3)) for i in range(3))
                error = pose_error * sum(map(abs, direction))
        else:
            value, error, _ = self.D._ray_box(direction, omega, self.duration, self.duration, 24, self.arena)
        self.arena.keep((*direction, *omega, self.duration, *value, error), objects=1)
        self.rays[trajectory] = (value, error)
        return value, error

    def edge(self, a, b):
        p, ep = self.ray(a)
        q, eq = self.ray(b)
        self.arena.work(64)
        with self.V._work((*p, *q, ep, eq), self.arena.resource):
            normal = self.V._cross(p, q)
            error = ep * sum(map(abs, q)) + eq * sum(map(abs, p)) + ep * eq
        literal = dict(kind='moving-ray-edge', rays=[self.record['rays'][a], self.record['rays'][b]])
        old, old_error, offset = self.D._constraint_pose(literal, self.duration, self.duration, 24, self.arena)
        if old_error == 0:
            # The issuer's exact axis can have different positive magnitudes
            # for the two input orders. Preserve its sign and canonicalise
            # its gauge so reversed incidences have identical magnitudes.
            scale = max(map(abs, old))
            normal, error = tuple(x / scale for x in old), Q(0)
        return normal, error, Q(0)
