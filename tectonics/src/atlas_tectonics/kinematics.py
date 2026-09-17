"""E01/E02: proper finite rotations and oriented, prescribed boundary motion.

No plate topology, force balance or interpretation as measured fault slip is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, read_array as array, frozen, scalar, input_shape
from .resources import elements, select_budget


def _vector(value: Any, dimensions: int, name: str) -> FloatArray:
    if input_shape(value, name) != (dimensions,):
        raise TectonicsError(f"{name}: expected {dimensions} components")
    out = array(value, name, ndim=1)
    if out.shape != (dimensions,):
        raise TectonicsError(f"{name}: expected {dimensions} components")
    return out


def _unit(vector: FloatArray) -> FloatArray:
    # Scale first: a subnormal norm can round to an incorrect divisor.
    scale = float(np.max(np.abs(vector)))
    if scale == 0 or not math.isfinite(scale):
        raise TectonicsError("finite nonzero vector required")
    scaled = vector / scale
    return scaled / math.hypot(*scaled)


@dataclass(frozen=True, slots=True)
class Rotation:
    """Unit quaternion (w,x,y,z); normalisation preserves a proper rotation."""
    quaternion: tuple[float, float, float, float]
    _matrix: FloatArray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        q = _vector(self.quaternion, 4, "quaternion")
        values = tuple(float(x) for x in _unit(q))
        object.__setattr__(self, "quaternion", values)
        w, x, y, z = values
        matrix = np.array(((1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)),
                           (2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)),
                           (2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y))))
        object.__setattr__(self, "_matrix", frozen(matrix))

    @classmethod
    def from_axis_angle(cls, axis: Any, angle_rad: float) -> Rotation:
        vector = _vector(axis, 3, "axis")
        vector = _unit(vector)
        half_angle = math.remainder(scalar(angle_rad, "angle_rad"), 2 * math.pi) / 2
        return cls((math.cos(half_angle), *(vector * math.sin(half_angle))))

    def inverse(self) -> Rotation:
        w, x, y, z = self.quaternion
        return Rotation((w, -x, -y, -z))

    def then(self, following: Rotation) -> Rotation:
        """Apply this rotation first, then following (ordered Hamilton product)."""
        if not isinstance(following, Rotation):
            raise TectonicsError("following must be a Rotation")
        a, b, c, d = following.quaternion
        w, x, y, z = self.quaternion
        return Rotation((a*w-b*x-c*y-d*z, a*x+b*w+c*z-d*y,
                         a*y-b*z+c*w+d*x, a*z+b*y-c*x+d*w))

    @property
    def matrix(self) -> FloatArray:
        """Immutable 3x3 operator with a private descriptor; 72 retained data bytes."""
        return self._matrix.view()

    @property
    def setup_bytes(self) -> int:
        return self._matrix.nbytes

    def apply(self, positions_m: Any, *, budget=None, backend: str = "matrix",
              batch_vectors: int = 65_536) -> FloatArray:
        """Rotate (...,3) positions. Reused matrix batches are the default.

        reference explicitly retains the prior quaternion cross-product formula.
        Matrix multiplication changes floating-point ordering: equivalence is
        bounded, not promised bitwise. Do not substitute old cached results.
        Caller arrays are never modified; all output is published immutably.
        """
        if backend not in ("matrix", "reference"):
            raise TectonicsError("rotation backend must be matrix or reference")
        if type(batch_vectors) is not int or batch_vectors <= 0:
            raise TectonicsError("batch_vectors must be a positive integer")
        shape = input_shape(positions_m, "positions_m")
        if not shape or shape[-1] != 3 or not elements(shape):
            raise TectonicsError("positions must be nonempty with final dimension 3")
        count = elements(shape)
        required = (128 * count if backend == "reference" else
                    32 * count + 24 * min(count // 3, batch_vectors) + 8192)
        with select_budget(budget).reserve(required):
            points = array(positions_m, "positions_m")
            if points.shape != shape:
                raise TectonicsError("input shape changed during capture")
            try:
                with np.errstate(over="raise", invalid="raise"):
                    if backend == "reference":
                        w, *xyz = self.quaternion
                        twice_cross = 2 * np.cross(xyz, points)
                        result = points + w * twice_cross + np.cross(xyz, twice_cross)
                    else:
                        flat = points.reshape(-1, 3)
                        result = np.empty(points.shape, dtype=np.float64)
                        output = result.reshape(-1, 3)
                        for start in range(0, flat.shape[0], batch_vectors):
                            np.matmul(flat[start:start+batch_vectors], self._matrix.T,
                                      out=output[start:start+batch_vectors])
                        del flat, output
                del points
                return frozen(result)
            except FloatingPointError as exc:
                raise TectonicsError("rotated coordinates exceed numerical range") from exc

    def apply_batches(self, position_batches, *, budget=None, backend="matrix",
                      batch_vectors=65_536):
        """Yield one complete immutable result per input batch, without prefetch.

        Consume/discard outputs to keep total RAM bounded. Each batch is a separate
        capture; mutating not-yet-submitted inputs changes that later request.
        Closing the iterator schedules nothing further and retains no reservation.
        """
        for positions in position_batches:
            yield self.apply(positions, budget=budget, backend=backend,
                             batch_vectors=batch_vectors)
            del positions

    def __reduce__(self):
        # Do not restore mutable derived matrix state from a generic object pickle.
        return (type(self), (self.quaternion,))

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def rigid_velocity(positions_m: Any, angular_velocity_rad_s: Any, *, budget=None) -> FloatArray:
    """Instantaneous omega cross r, not a finite-interval chord velocity."""
    shape = input_shape(positions_m, "positions_m")
    if not shape or shape[-1] != 3:
        raise TectonicsError("positions must have final dimension 3")
    with select_budget(budget).reserve(64 * elements(shape)):
        points = array(positions_m, "positions_m")
        omega = _vector(angular_velocity_rad_s, 3, "angular_velocity_rad_s")
        if points.ndim < 1 or points.shape[-1] != 3:
            raise TectonicsError("positions must have final dimension 3")
        with np.errstate(over="ignore", invalid="ignore"):
            return frozen(np.cross(omega, points))


@dataclass(frozen=True, slots=True)
class BoundaryMotion:
    tangent: tuple[float, float]
    right_normal: tuple[float, float]
    relative_right_minus_left_m_s: tuple[float, float]
    opening_m_s: float
    tangential_m_s: float
    left_relative_to_boundary_m_s: tuple[float, float]
    right_relative_to_boundary_m_s: tuple[float, float]


def boundary_motion(left_m_s: Any, right_m_s: Any, tangent_xy: Any,
                    boundary_m_s: Any) -> BoundaryMotion:
    """Local EN frame: right normal=(t_y,-t_x); positive opening is separation.

    Side/trace orientation is the caller's geometry declaration. No sidedness audit
    or conversion from this velocity diagnostic to physical slip is performed.
    """
    left = _vector(left_m_s, 2, "left_m_s")
    right = _vector(right_m_s, 2, "right_m_s")
    boundary = _vector(boundary_m_s, 2, "boundary_m_s")
    tangent = _vector(tangent_xy, 2, "tangent_xy")
    tangent = _unit(tangent)
    normal = np.array((tangent[1], -tangent[0]))
    with np.errstate(over="ignore", invalid="ignore"):
        relative = frozen(right - left)
        left_local = frozen(left - boundary)
        right_local = frozen(right - boundary)
    return BoundaryMotion(tuple(tangent), tuple(normal), tuple(relative),
                          scalar(float(relative @ normal), "opening_m_s"),
                          scalar(float(relative @ tangent), "tangential_m_s"),
                          tuple(left_local), tuple(right_local))
