"""W01: identified spherical and local Cartesian frames, with explicit SI units.

Geocentric latitude on a sphere is NOT ellipsoidal/geodetic latitude. Local ENU
positions are three-dimensional chord coordinates, not an area-preserving map or
surface arc coordinates. Velocities use vector transformations, not origin shifts.

Basis: ESA Navipedia, 'Transformations between ECEF and ENU coordinates', equations
(3)-(6), specialised to a sphere. No Earth radius, geoid or calendar is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import hashlib
import json
import math

import numpy as np

from ._validation import FloatArray, TectonicsError, frozen, input_shape, read_array, scalar
from .kinematics import Rotation
from .resources import elements, select_budget


def _label(value: str, name: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise TectonicsError(f"{name}: nonblank text of at most 256 characters required")
    return value


def _identity(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')).hexdigest()


def _batch_size(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise TectonicsError('batch_points must be a positive integer')
    return value


def _triples_shape(value: Any, name: str) -> tuple[int, ...]:
    shape = input_shape(value, name)
    if not shape or shape[-1] != 3 or not elements(shape):
        raise TectonicsError(f'{name}: nonempty (...,3) array required')
    return shape


def _map_triples(value: Any, name: str, operation: Callable, *, budget=None,
                 batch_points: int = 65_536) -> FloatArray:
    """One input capture and one result; scratch grows with batch, not world size.

    Public results have compact immutable backing. The caller owns any arrays
    retained after this reservation ends. No worker pool or disk cache is created.
    """
    batch_points = _batch_size(batch_points)
    shape = _triples_shape(value, name)
    n = elements(shape) // 3
    # Full capture + candidate + immutable publication and bounded ufunc scratch.
    work = 96*n + 512*min(n, batch_points) + 8192
    with select_budget(budget).reserve(work, category='coordinate-conversion'):
        captured = read_array(value, name)
        if captured.shape != shape:
            raise TectonicsError(f'{name}: shape changed during capture')
        source = captured.reshape(-1, 3)
        result = np.empty(shape, dtype=np.float64)
        out = result.reshape(-1, 3)
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                for start in range(0, n, batch_points):
                    operation(source[start:start+batch_points], out[start:start+batch_points])
            del source, captured, out
            return frozen(result)
        except (FloatingPointError, OverflowError) as exc:
            raise TectonicsError(f'{name}: conversion exceeds binary64 range') from exc


def _unit_factor(source: str, target: str, table: dict[str, float]) -> float:
    if type(source) is not str or type(target) is not str or source not in table or target not in table:
        raise TectonicsError('explicit supported units required: ' + ', '.join(table))
    return table[source] / table[target]


def _scale_units(value: Any, factor: float, *, budget=None) -> FloatArray:
    shape = input_shape(value, 'unit input')
    n = elements(shape)
    if not n:
        raise TectonicsError('nonempty unit input required')
    with select_budget(budget).reserve(40*n + 8192, category='unit-conversion'):
        a = read_array(value, 'unit input')
        try:
            with np.errstate(over='raise', invalid='raise', under='ignore'):
                out = a * factor
            if np.any((a != 0) & (out == 0)):
                raise TectonicsError('nonzero unit input underflows in binary64')
            return frozen(out)
        except FloatingPointError as exc:
            raise TectonicsError('unit conversion exceeds binary64 range') from exc


def convert_angles(value: Any, *, source: str, target: str, budget=None) -> FloatArray:
    """Convert 'degrees'/'radians' without wrapping; safe for angles or angular rates.

    This changes the angular unit only. A rate's time unit is a separate contract.
    """
    return _scale_units(value, _unit_factor(source, target,
                        {'radians': 1., 'degrees': math.pi/180}), budget=budget)


def convert_lengths(value: Any, *, source: str, target: str, budget=None) -> FloatArray:
    """Convert m/km explicitly; no coordinate or reference-frame transformation."""
    return _scale_units(value, _unit_factor(source, target, {'m': 1., 'km': 1000.}), budget=budget)


def _wrap(values: FloatArray, half_turn: float) -> FloatArray:
    # Reduce before subtracting the period, avoiding loss from adding pi to tiny
    # angles. Signed zero has one canonical longitude representation.
    out = np.remainder(values, 2*half_turn)
    out = np.where(out >= half_turn, out - 2*half_turn, out)
    # Negative tiny inputs otherwise round remainder to exactly the period.
    out = np.where((values >= -half_turn) & (values < half_turn), values, out)
    return np.where(out == 0, 0., out)


def _angles(unit: str) -> tuple[float, float]:
    if unit == 'radians':
        return math.pi, 1.
    if unit == 'degrees':
        return 180., math.pi/180
    raise TectonicsError('angle_unit must be radians or degrees')


@dataclass(frozen=True, slots=True)
class SphericalFrame:
    """One identified planet-centred axis convention and an explicit sphere radius.

    frame_id names the axes/reference frame, not just the planet. Two differing
    frames need an explicit rotation elsewhere; equal radii do not make them equal.
    """
    radius_m: float
    frame_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'radius_m', scalar(self.radius_m, 'radius_m', positive=True))
        _label(self.frame_id, 'frame_id')

    def descriptor(self) -> dict:
        return {'schema': 'atlas.spherical-frame.v1', 'frame_id': self.frame_id,
                'radius_m': self.radius_m, 'latitude': 'geocentric',
                'axes': 'X-lon0,Y-lon90,Z-north,right-handed', 'height': 'radial-up'}

    @property
    def identity(self) -> str:
        return _identity(self.descriptor())

    def to_cartesian(self, longitude_latitude_height: Any, *, angle_unit='radians',
                     budget=None, batch_points=65_536) -> FloatArray:
        """(..., lon,lat,height_m) -> (...,X,Y,Z) metres. No altitude datum guessing.

        Exact poles have X=Y=0 regardless of longitude. Heights must produce a
        positive, finite radius; a nonzero height lost entirely in R+h is refused.
        """
        half_turn, factor = _angles(angle_unit)
        def convert(a, out):
            if np.any(np.abs(a[:, 1]) > half_turn/2):
                raise TectonicsError('latitude outside its closed pole-to-pole range')
            lon = _wrap(a[:, 0], half_turn) * factor
            lat = a[:, 1] * factor
            radius = self.radius_m + a[:, 2]
            if np.any(radius <= 0) or np.any((a[:, 2] != 0) & (radius == self.radius_m)):
                raise TectonicsError('radial height reaches centre or is numerically unresolvable')
            c = np.cos(lat)
            c[np.abs(a[:, 1]) == half_turn/2] = 0.
            out[:, 0] = radius * c * np.cos(lon)
            out[:, 1] = radius * c * np.sin(lon)
            out[:, 2] = radius * np.sin(lat)
        return _map_triples(longitude_latitude_height, 'spherical position', convert,
                            budget=budget, batch_points=batch_points)

    def to_spherical(self, positions_m: Any, *, angle_unit='radians', budget=None,
                     batch_points=65_536) -> FloatArray:
        """XYZ -> lon,geocentric-lat,height. Longitude zero at the exact polar axis.

        No tolerance snaps near-polar points onto the pole. Latitude uses atan2,
        not asin(z/r), to preserve near-pole information. The centre is undefined.
        """
        _, factor = _angles(angle_unit)
        def convert(a, out):
            horizontal = np.hypot(a[:, 0], a[:, 1])
            radius = np.hypot(horizontal, a[:, 2])
            if np.any(radius == 0):
                raise TectonicsError('spherical coordinates are undefined at the centre')
            out[:, 0] = _wrap(np.arctan2(a[:, 1], a[:, 0]), math.pi) / factor
            out[horizontal == 0, 0] = 0.
            out[:, 1] = np.arctan2(a[:, 2], horizontal) / factor
            out[:, 2] = radius - self.radius_m
        return _map_triples(positions_m, 'Cartesian position', convert,
                            budget=budget, batch_points=batch_points)


@dataclass(frozen=True, slots=True)
class LocalCartesianFrame:
    """Static affine ENU frame with a reusable 3x3 basis and explicit polar meridian.

    axis_rotation_rad rotates local X from east towards north (CCW viewed from up);
    local Y follows to maintain a right-handed basis. Zero gives east/north/up.
    At a pole longitude is an explicit orientation choice, NOT inferred geography.
    _basis stores immutable bytes; returned arrays have private shape metadata.
    """
    sphere: SphericalFrame
    frame_id: str
    longitude_rad: float
    latitude_rad: float
    height_m: float = 0.
    axis_rotation_rad: float = 0.
    _origin: tuple[float, float, float] = field(init=False, repr=False, compare=False)
    _basis: bytes = field(init=False, repr=False, compare=False)
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.sphere) is not SphericalFrame:
            raise TectonicsError('explicit SphericalFrame required')
        _label(self.frame_id, 'local frame_id')
        for name in ('longitude_rad', 'latitude_rad', 'height_m', 'axis_rotation_rad'):
            object.__setattr__(self, name, scalar(getattr(self, name), name))
        lon = float(_wrap(np.array([self.longitude_rad]), math.pi)[0])
        turn = float(_wrap(np.array([self.axis_rotation_rad]), math.pi)[0])
        object.__setattr__(self, 'longitude_rad', lon)
        object.__setattr__(self, 'axis_rotation_rad', turn)
        origin = self.sphere.to_cartesian([lon, self.latitude_rad, self.height_m])
        lat = self.latitude_rad
        sl, cl = math.sin(lon), math.cos(lon)
        sp = math.sin(lat)
        cp = 0. if abs(lat) == math.pi/2 else math.cos(lat)
        # Columns are E,N,U in the identified Cartesian parent frame.
        basis = np.array(((-sl, -cl*sp, cl*cp), (cl, -sl*sp, sl*cp), (0., cp, sp)))
        orient = Rotation.from_axis_angle((0., 0., 1.), turn)
        basis = basis @ orient.matrix
        object.__setattr__(self, '_origin', tuple(float(v) for v in origin))
        object.__setattr__(self, '_basis', basis.tobytes())
        object.__setattr__(self, 'identity', _identity(self.descriptor()))

    def descriptor(self) -> dict:
        return {'schema': 'atlas.local-cartesian-frame.v1', 'frame_id': self.frame_id,
                'sphere': self.sphere.descriptor(), 'longitude_rad': self.longitude_rad,
                'latitude_rad': self.latitude_rad, 'height_m': self.height_m,
                'axis_rotation_rad': self.axis_rotation_rad,
                'meaning': 'static affine full-3D chord frame, not a map projection'}

    @property
    def basis(self) -> FloatArray:
        """Columns are the local axes in parent XYZ; payload is immutable (72 B)."""
        return np.frombuffer(self._basis, dtype=np.float64).reshape(3, 3)

    @property
    def origin_m(self) -> FloatArray:
        return frozen(self._origin)

    @property
    def setup_bytes(self) -> int:
        """Numerical basis payload only; Python metadata and origin are additional."""
        return len(self._basis)

    def _affine(self, values, matrix, before, after, *, budget=None, batch_points=65_536):
        def convert(a, out):
            shifted = a if before is None else a - before
            np.matmul(shifted, matrix, out=out)
            if after is not None:
                displaced = np.any(out != 0, axis=-1)
                out += after
                if np.any(displaced & np.all(out == after, axis=-1)):
                    raise TectonicsError('position increment lost at this origin; retain a nearer local frame')
        return _map_triples(values, 'frame coordinates', convert, budget=budget,
                            batch_points=batch_points)

    def positions_from_cartesian(self, positions_m, *, budget=None, batch_points=65_536):
        """Subtract the origin, THEN express the displacement in the local basis."""
        return self._affine(positions_m, self.basis, self.origin_m, None,
                            budget=budget, batch_points=batch_points)

    def positions_to_cartesian(self, local_m, *, budget=None, batch_points=65_536):
        return self._affine(local_m, self.basis.T, None, self.origin_m,
                            budget=budget, batch_points=batch_points)

    def vectors_from_cartesian(self, vectors, *, budget=None, batch_points=65_536):
        """Component rotation ONLY; vector units are preserved (e.g. m/s)."""
        return self._affine(vectors, self.basis, None, None,
                            budget=budget, batch_points=batch_points)

    def vectors_to_cartesian(self, vectors, *, budget=None, batch_points=65_536):
        return self._affine(vectors, self.basis.T, None, None,
                            budget=budget, batch_points=batch_points)

    def to_frame(self, values, target: LocalCartesianFrame, *, kind: str,
                 budget=None, batch_points=65_536):
        """Direct local-to-local conversion: compose a small matrix, no full XYZ copy.

        Only frames with the same identified spherical parent can be compared.
        kind must explicitly distinguish 'position' from a free 'vector'.
        """
        if type(target) is not LocalCartesianFrame or self.sphere != target.sphere:
            raise TectonicsError('local frames must have the same identified spherical parent')
        if kind not in ('position', 'vector'):
            raise TectonicsError('kind must explicitly be position or vector')
        matrix = self.basis.T @ target.basis
        offset = (self.origin_m - target.origin_m) @ target.basis if kind == 'position' else None
        return self._affine(values, matrix, None, offset, budget=budget, batch_points=batch_points)

    def velocity_from_cartesian(self, positions_m, velocities_m_s, *,
                                origin_velocity_m_s, angular_velocity_rad_s,
                                budget=None, batch_points=65_536):
        """Instantaneous velocity relative to a MOVING frame, with explicit rates.

        Q.T [v - v_origin - omega cross (r-r_origin)]. Rates are expressed in the
        parent Cartesian frame. This does not integrate the frame or infer rates.
        Use vectors_from_cartesian for a static component change without this term.
        """
        return self._velocity(positions_m, velocities_m_s, origin_velocity_m_s,
                              angular_velocity_rad_s, inverse=False,
                              budget=budget, batch_points=batch_points)

    def velocity_to_cartesian(self, local_positions_m, local_velocities_m_s, *,
                              origin_velocity_m_s, angular_velocity_rad_s,
                              budget=None, batch_points=65_536):
        """Inverse instantaneous velocity transform with the same explicitly given rates."""
        return self._velocity(local_positions_m, local_velocities_m_s, origin_velocity_m_s,
                              angular_velocity_rad_s, inverse=True,
                              budget=budget, batch_points=batch_points)

    def _velocity(self, positions, velocities, origin_velocity, omega, *, inverse,
                  budget, batch_points):
        batch_points = _batch_size(batch_points)
        shape = _triples_shape(positions, 'velocity position')
        if _triples_shape(velocities, 'velocity') != shape:
            raise TectonicsError('velocity and position must have exactly matching shapes')
        if input_shape(origin_velocity) != (3,) or input_shape(omega) != (3,):
            raise TectonicsError('frame velocity and angular velocity need three components')
        n = elements(shape)//3
        with select_budget(budget).reserve(128*n+512*min(n,batch_points)+8192,
                                          category='frame-velocity'):
            p = read_array(positions, 'positions').reshape(-1,3)
            v = read_array(velocities, 'velocities').reshape(-1,3)
            v0 = read_array(origin_velocity, 'origin velocity')
            w = read_array(omega, 'frame angular velocity')
            result = np.empty(shape, dtype=np.float64)
            out = result.reshape(-1,3)
            try:
                with np.errstate(over='raise', invalid='raise'):
                    for i in range(0,n,batch_points):
                        sl = slice(i,i+batch_points)
                        if inverse:
                            d = p[sl] @ self.basis.T
                            out[sl] = v[sl] @ self.basis.T
                            out[sl] += np.cross(w,d)
                            out[sl] += v0
                        else:
                            d = p[sl] - self.origin_m
                            rel = v[sl] - v0 - np.cross(w,d)
                            np.matmul(rel,self.basis,out=out[sl])
                del p,v,out
                return frozen(result)
            except FloatingPointError as exc:
                raise TectonicsError('moving-frame velocity exceeds binary64 range') from exc

    def __reduce__(self):
        # Regenerate derived operators; never trust mutable restored matrix state.
        return (type(self), (self.sphere,self.frame_id,self.longitude_rad,self.latitude_rad,
                            self.height_m,self.axis_rotation_rad))

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def east_south_up_to_enu(values, *, axial: bool = False, budget=None,
                         batch_points=65_536) -> FloatArray:
    """Explicit left-handed legacy reflection. Polar: (x,-y,z); axial: (-x,y,-z).

    Positions/ordinary velocities are polar. Rotation/angular-velocity vectors are
    axial: using the polar rule for them reverses cross-product handedness. This is
    a component conversion only, not a unit, origin or time-frame conversion.
    """
    if type(axial) is not bool:
        raise TectonicsError('axial must be an explicit Boolean')
    signs = np.array((-1.,1.,-1.) if axial else (1.,-1.,1.))
    def convert(a,out):
        np.multiply(a,signs,out=out)
    return _map_triples(values,'legacy axes',convert,budget=budget,batch_points=batch_points)


def enu_to_east_south_up(values, *, axial: bool = False, budget=None,
                         batch_points=65_536) -> FloatArray:
    """The same reflection is its own inverse; see east_south_up_to_enu."""
    return east_south_up_to_enu(values,axial=axial,budget=budget,batch_points=batch_points)
