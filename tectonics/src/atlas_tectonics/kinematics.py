"""E01/E02: proper finite rotations and oriented, prescribed boundary motion.

No plate topology, force balance or interpretation as measured fault slip is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, array, frozen, scalar


def _vector(value: Any, dimensions: int, name: str) -> FloatArray:
    out = array(value, name, ndim=1)
    if out.shape != (dimensions,):
        raise TectonicsError(f"{name}: expected {dimensions} components")
    return out


@dataclass(frozen=True, slots=True)
class Rotation:
    """Unit quaternion (w,x,y,z); normalisation preserves a proper rotation."""
    quaternion: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        q = _vector(self.quaternion, 4, "quaternion")
        norm = math.hypot(*q)
        if not math.isfinite(norm) or norm == 0:
            raise TectonicsError("finite nonzero quaternion norm required")
        object.__setattr__(self, "quaternion", tuple(float(x / norm) for x in q))

    @classmethod
    def from_axis_angle(cls, axis: Any, angle_rad: float) -> Rotation:
        vector = _vector(axis, 3, "axis")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise TectonicsError("finite nonzero rotation axis required")
        half_angle = math.remainder(scalar(angle_rad, "angle_rad"), 2 * math.pi) / 2
        return cls((math.cos(half_angle), *(vector / norm * math.sin(half_angle))))

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

    def apply(self, positions_m: Any) -> FloatArray:
        """Rotate a vector or an array (...,3); output is detached and immutable."""
        points = array(positions_m, "positions_m")
        if points.ndim < 1 or points.shape[-1] != 3:
            raise TectonicsError("positions must have final dimension 3")
        w, *xyz = self.quaternion
        try:
            with np.errstate(over="raise", invalid="raise"):
                twice_cross = 2 * np.cross(xyz, points)
                return frozen(points + w * twice_cross + np.cross(xyz, twice_cross))
        except FloatingPointError as exc:
            raise TectonicsError("rotated coordinates exceed numerical range") from exc


def rigid_velocity(positions_m: Any, angular_velocity_rad_s: Any) -> FloatArray:
    """Instantaneous omega cross r, not a finite-interval chord velocity."""
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
    norm = math.hypot(*tangent)
    if not math.isfinite(norm) or norm == 0:
        raise TectonicsError("nonzero finite tangent required")
    tangent = tangent / norm
    normal = np.array((tangent[1], -tangent[0]))
    with np.errstate(over="ignore", invalid="ignore"):
        relative = frozen(right - left)
        left_local = frozen(left - boundary)
        right_local = frozen(right - boundary)
    return BoundaryMotion(tuple(tangent), tuple(normal), tuple(relative),
                          scalar(float(relative @ normal), "opening_m_s"),
                          scalar(float(relative @ tangent), "tangential_m_s"),
                          tuple(left_local), tuple(right_local))
