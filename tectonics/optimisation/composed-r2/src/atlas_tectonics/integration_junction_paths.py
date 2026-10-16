"""Explicit analytic junction histories and their bounded polyline representation (I03).

This is supplied kinematics, not a rule selecting an oblique ridge direction. In one declared reference frame,
plate, carrier and junction angular velocities are constant. The generated carrier-local end trace is
q(s)=exp(-s C) exp(s J) x. Its exact tangent defines the normal-velocity closure at every s, not just at samples.
The initial tangent must agree with the stored boundary tangent; the exact final tangent is retained separately
from the sampled chord. Areas belong to the represented closed minor-arc partition, without area corrections.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
import math

import numpy as np

from . import integration_sphere as S
from .geometry import _check_cancel
from .integration_ledger import LedgerError
from .kinematics import Rotation, _restore_rotation
from .materials import _name
from .spherical_atlas import _ANGULAR_RESOLUTION


CONVENTION = 'common_reference_exponential_v1'
# Existing C1 criterion, cases/i01_transitions_v1.json control_policy.algebra_relative. Kept in this lower-level
# module so integration_transfer can expose the same named value without a circular import.
ALGEBRA_RELATIVE = 1e-11


@dataclass(frozen=True, slots=True)
class JunctionPath:
    """One supplied junction rotation in the stored axes of the Motion's common reference plate.

    max_deviation_rad bounds the curve-to-minor-arc representation, independently of algebra/coordinate gates.
    max_segments is a per-record-end execution ceiling, not an accuracy override. Deterministic bisection uses
    powers of two only, so a non-power-of-two ceiling admits at most its greatest lower power of two. Neither
    accuracy nor ceiling has a default. Accuracy is strictly between the coordinate band and pi/2; these bounds
    restrict the supported representation, not physical velocity or force laws.
    """
    junction_id: str
    reference_plate_id: str
    relative_rotation: Rotation
    max_deviation_rad: float
    max_segments: int

    def __post_init__(self):
        _name(self.junction_id, 'junction ID')
        _name(self.reference_plate_id, 'reference plate ID')
        if type(self.relative_rotation) is not Rotation:
            raise LedgerError('a junction path needs a typed relative Rotation')
        if (type(self.max_deviation_rad) not in (int, float) or not math.isfinite(self.max_deviation_rad)
                or not S.ATTACHMENT_BAND_RAD < self.max_deviation_rad < math.pi/2):
            raise LedgerError('junction curve accuracy must exceed coordinate roundoff and be less than pi/2')
        if type(self.max_segments) is not int or self.max_segments < 1:
            raise LedgerError('a junction path needs a positive whole segment ceiling')

    def record(self):
        return dict(junction_id=self.junction_id, reference_plate_id=self.reference_plate_id,
                    relative_rotation=list(self.relative_rotation.quaternion),
                    max_deviation_rad=self.max_deviation_rad, max_segments=self.max_segments)

    @classmethod
    def from_record(cls, value):
        return cls(value['junction_id'], value['reference_plate_id'],
                   _restore_rotation(tuple(value['relative_rotation'])), value['max_deviation_rad'],
                   value['max_segments'])


def vector(rotation):
    q = np.asarray(rotation.quaternion)
    if q[0] < 0:
        q = -q
    length = float(np.linalg.norm(q[1:]))
    return q[1:]*(2*math.atan2(length, q[0])/length) if length else np.zeros(3)


def exponential(value):
    angle = float(np.linalg.norm(value))
    return Rotation.from_axis_angle(tuple(value/angle), angle) if angle else _restore_rotation((1., 0., 0., 0.))


def sample(carrier, junction, point, accuracy, ceiling, cancel):
    """Sample the analytic trace with a certified Euclidean chord bound, then normalise its chords.

    q'' = w' x q + w x (w x q), |w|=|J-C|, |w'|=|C x J|. Therefore |q''| <= M below.
    Linear interpolation error is <= M h^2/8. Its normalisation differs from q by at most twice that distance,
    hence the conservative angular bound 2 asin(M h^2/8). The normalised chord traverses the same minor arc.
    Exact commuting, equatorial rotations require only their endpoints unless an edge would violate the existing
    chart/atlas conditioning limits. Bisection is deterministic and uses only powers of two. A declared ceiling
    of three therefore admits at most two segments; this routine never silently raises it to four.
    """
    difference = junction-carrier
    commutator = float(np.linalg.norm(np.cross(carrier, junction)))
    bound = float(difference @ difference)+commutator
    exact = commutator == 0. and float(difference @ point) == 0.
    span = float(np.linalg.norm(difference))
    # This retained path-family bound is distinct from conditioning any one emitted minor-arc edge.
    if span >= math.pi:
        raise LedgerError('a supplied generated trace spans pi or more; subdivide the supplied history')
    count = 1
    # |q'| <= |J-C| bounds each emitted chord's angular length by span/count. A chart at that chord's midpoint
    # has endpoint cosine cos(theta/2). Reuse the existing chart minimum and atlas antipodal band, including for
    # exact great circles; no new angular cutoff or allowance is introduced. Whole-face validation still follows.
    while (span/count >= math.pi-_ANGULAR_RESOLUTION
           or math.cos(span/(2*count)) < S.CHART_MIN_COSINE
           or (not exact and (bound/(8*count*count) >= 1 or
                              2*math.asin(bound/(8*count*count)) > accuracy))):
        _check_cancel(cancel)
        count *= 2
        if count > ceiling:
            raise LedgerError('the supplied junction trace exceeds its declared segment ceiling')
    points = []
    for s in np.linspace(0., 1., count+1):
        _check_cancel(cancel)
        points.append(S._placed(exponential(-s*carrier), S._placed(exponential(s*junction), point)[0])[0])
    points = np.asarray(points)
    angles = 2*np.arctan2(np.linalg.norm(points[1:]-points[:-1], axis=1),
                          np.linalg.norm(points[1:]+points[:-1], axis=1))
    if np.any(angles <= _ANGULAR_RESOLUTION) or np.any(angles >= math.pi-_ANGULAR_RESOLUTION):
        raise LedgerError('a supplied trace has a zero, unresolved or antipodal edge at the existing atlas resolution')
    return points


def prepare(network, motion, cancel, fail):
    """Carrier stages, final junctions, generated end traces, analytic endpoint poles and C1 diagnostics."""
    paths = {p.junction_id: p for p in motion.junction_paths}
    junctions = {j.junction_id: j for j in network.junctions}
    if not paths.keys() <= junctions.keys():
        raise fail('a supplied path names no junction of this network')
    reference = motion.junction_paths[0].reference_plate_id
    if reference not in network.plate_ids:
        raise fail('the common path reference plate is absent')
    stages = dict(motion.rotations)
    frame = dict(network._layout.frames)[reference]
    later = frame.then(stages[reference])
    # D_p = F0^-1 L^-1 R_p F0; paths and all plate rates share these stored local axes.
    rates = {p: vector(frame.then(r).then(stages[reference].inverse()).then(frame.inverse()))
             for p, r in motion.rotations}
    carrier, rotations = {}, {}
    records = {b.boundary_id: b for b in network.boundaries}
    for b in network.boundaries:
        if b.kind == S.RIDGE:
            carrier[b.boundary_id] = (1-b.accretion_fraction)*rates[b.left_plate_id]+b.accretion_fraction*rates[b.right_plate_id]
        else:
            keeper = S._carrier(b)
            if type(keeper) is not str:
                raise fail('the supplied path convention needs an explicit plate carrier for every non-ridge')
            carrier[b.boundary_id] = rates[keeper]
        rotations[b.boundary_id] = frame.inverse().then(exponential(carrier[b.boundary_id])).then(later)
    targets, traces, poles, diagnostics = {}, {}, {}, {}
    lookup = {name: k for k, name in enumerate(network.vertex_ids)}
    stored = dict(network._layout.poles)
    oldframes = dict(network._layout.frames) | {(S.RIDGE, b): r for b, r in network._layout.ridges}
    for key, path in paths.items():
        _check_cancel(cancel)
        junction = junctions[key]
        if any(records[b].kind != S.RIDGE for b, _ in junction.boundary_ends):
            raise fail('supplied analytic paths currently require all-ridge junctions; no physical ownership is inferred')
        here = network.vertex_direction[lookup[junction.vertex_id]]
        local = S._placed(frame.inverse(), here)[0]
        rate = vector(path.relative_rotation)
        finish = S._placed(path.relative_rotation, local)[0]
        targets[junction.vertex_id] = S._placed(later, finish)[0]
        plates = sorted({p for b, _ in junction.boundary_ends
                         for p in (records[b].left_plate_id, records[b].right_plate_id)})
        scale = max(float(np.linalg.norm(np.cross(rates[a]-rates[b], local)))
                    for i, a in enumerate(plates) for b in plates[i+1:])
        residuals, normals, normal_bounds = [], [], []
        for end in junction.boundary_ends:
            b, role = end
            c = carrier[b]
            d = rate-c
            tangent = np.cross(d, local)
            speed = float(np.linalg.norm(tangent))
            normal = S._placed(frame.inverse(), S._placed(oldframes[S._carrier(records[b])], stored[end])[0])[0]
            # C1 on the declared analytic tangent: n_i . ((J-C_i) x x0), scaled below by the largest relative
            # plate speed at x0. Normalise the assembled residual, not each row by a separate local speed.
            residuals.append(float(normal @ tangent))
            chain = records[b].vertex_ids
            neighbour = chain[1] if role == 'start' else chain[-2]
            beside = S._placed(frame.inverse(), network.vertex_direction[lookup[neighbour]])[0]
            if float(tangent @ (beside-local)) >= 0 or speed <= S.ATTACHMENT_BAND_RAD:
                raise fail('supplied ridge end history retracts or has no generated tangent; this path family only extends')
            # For x(s)=exp(sJ)x0, |d x x(s)| >= speed-|d||J| = lower. The unnormalised normal is
            # d-(d.x)x and its derivative is bounded by 2|d||J|. Dividing by lower bounds the unit normal's
            # drift over the full unit interval; C4 below subtracts both members' bounds from each initial sine.
            lower = speed-float(np.linalg.norm(d))*float(np.linalg.norm(rate))
            if lower <= 0:
                raise fail('supplied path cannot certify a nonzero end tangent throughout its interval')
            n = np.cross(local, tangent)/speed
            normals.append(n)
            normal_bounds.append(2*float(np.linalg.norm(d))*float(np.linalg.norm(rate))/lower)
            try:
                trace = sample(c, rate, local, path.max_deviation_rad, path.max_segments, cancel)
            except LedgerError as exc:
                raise fail(str(exc)) from exc
            # Carrier-endpoint placement of the emitted history in common local coordinates.
            placed = S._placed(exponential(c).then(later), trace)
            traces[junction.vertex_id, b, role] = placed
            endnormal = -np.cross(finish, np.cross(d, finish))
            endnormal /= np.linalg.norm(endnormal)
            newframe = oldframes[(S.RIDGE, b)].then(rotations[b])
            poles[end] = tuple(S._placed(newframe.inverse(), S._placed(later, endnormal)[0])[0])
        residual = float(np.linalg.norm(residuals))/scale if scale else math.inf
        if residual > ALGEBRA_RELATIVE:
            raise fail('supplied junction history disagrees with the stored initial tangents above C1 %g'
                       % ALGEBRA_RELATIVE)
        if not any(float(np.linalg.norm(np.cross(a, b)))-normal_bounds[i]-normal_bounds[j] >= 1/16
                   for i, a in enumerate(normals) for j, b in enumerate(normals) if j > i):
            raise fail('supplied history cannot certify conditioned normal closure throughout its interval (C4)')
        diagnostics[junction.vertex_id] = residual
    return rotations, targets, traces, poles, diagnostics
