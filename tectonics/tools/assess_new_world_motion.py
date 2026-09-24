"""Read-only, length-weighted diagnostics of retained initial plate motion.

SPDX-License-Identifier: AGPL-3.0-only
These diagnostics describe WORKING NON-CANON kinematics, not realism acceptance.
No world, Euler fit, time evolution or absolute-arrow comparison is produced.
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np

from new_world_contract import ContractError
from new_world_motion import (
    WorldMotion, YEAR, _arc, _opening_breaks, _opening_uncertainty,
    _speed_integral, _speed_parts, check_motion,
)

SCHEMA = 'atlas.initial-motion-assessment.v1'
def _fail(message):
    raise ContractError('MOTION_ASSESSMENT_REFUSED', message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def assess_motion(atlas, motion, *, plan=None, structure=None):
    """Assess an existing atlas and WorldMotion without solving or changing either.

    Supply BOTH original plan and structure for retained check_motion validation.
    Otherwise the caller must first admit the saved dependencies, e.g. through
    load_project; this function checks only the diagnostic inputs and coverage.
    Fractions derive from Euler differences, not unchecked saved regime labels.
    Stationary length is included in unresolved and excluded from obliquity.
    """
    if (plan is None) != (structure is None):
        _fail('Supply both original plan and structure, or neither.')
    if type(motion) is not WorldMotion:
        _fail('An existing WorldMotion is required.')
    if structure is not None:
        check_motion(plan, atlas, structure, motion)
    return _assess(atlas, motion, 'saved-motion-and-dependencies' if structure is not None
                   else 'diagnostic-inputs-only; caller must validate saved dependencies')


def _assess(atlas, motion, validation):
    record = motion.descriptor()
    radius = atlas.sphere.radius_m
    if (not _finite(radius) or radius <= 0 or record.get('atlas_id') != atlas.atlas_id
            or record.get('geometry_id') != atlas.geometry_id
            or record.get('frame_id') != atlas.sphere.frame_id
            or record.get('status') != 'WORKING NON-CANON'):
        _fail('Motion and finite native atlas geometry must match.')
    angular = record.get('angular_velocities_rad_s')
    if type(angular) is not dict or set(angular) != set(atlas.plate_ids):
        _fail('Saved rotations must cover exactly the native plates.')
    for vector in angular.values():
        if type(vector) is not list or len(vector) != 3 or not all(map(_finite, vector)):
            _fail('Saved plate rotations must be finite three-vectors.')
    angular = {p: np.asarray(w, dtype=float) for p, w in angular.items()}
    edges = {}
    normal_terms, shear_terms, full_terms, angles = [], [], [], []
    totals = {key: [] for key in ('extension', 'shortening', 'unresolved')}
    try:
        for index in atlas.interplate_edges:
            index = int(index)
            if index in edges:
                _fail('Native interplate edges must be unique.')
            edge = atlas.edge(index)
            a, b = atlas.vertex_directions[atlas.edge_vertices[index]]
            if (a.shape != (3,) or b.shape != (3,) or not np.isfinite([a, b]).all()
                    or abs(float(a @ a)-1.) > 2e-12 or abs(float(b @ b)-1.) > 2e-12):
                _fail('Native edge endpoints must be finite unit directions.')
            u, left, angle = _arc(a, b)
            delta = angular[edge.right_plate_id]-angular[edge.left_plate_id]
            basis, weights = _speed_parts(a, u, 0., angle)
            # Positive terms avoid cancellation when normal motion is tiny.
            normal_terms.append(math.fsum(w*float(delta @ v)**2
                                          for v, w in zip(basis[:2], weights[:2])))
            shear_terms.append(angle*float(delta @ left)**2)
            full_terms.append(_speed_integral(delta, a, u, 0., angle))
            angles.append(angle)
            A, B = radius*float(delta @ u), -radius*float(delta @ a)
            # A relative-rotation envelope is independent of a common frame
            # rotation. It is numerical ambiguity, not a transform speed gate.
            uncertainty = _opening_uncertainty(np.zeros(3), delta, radius, angle)
            if math.hypot(A, B) <= uncertainty:
                totals['unresolved'].append(angle)
            else:
                breaks = [0.] + _opening_breaks(A, B, angle) + [angle]
                for lo, hi in zip(breaks, breaks[1:]):
                    mid = .5*(lo+hi)
                    key = 'extension' if A*math.cos(mid)+B*math.sin(mid) > 0. else 'shortening'
                    totals[key].append(hi-lo)
            edges[index] = (edge, a, u, left, angle, delta)
        segments = record.get('segments')
        if not edges or type(segments) is not list or not 0 < len(segments) <= 256*len(edges):
            _fail('A bounded complete set of saved boundary segments is required.')
        spans, sampled, stationary, zero_midpoint = {}, [], [], []
        for segment in segments:
            index = segment['edge_index']
            lo, hi = segment['start_fraction'], segment['end_fraction']
            if (type(index) is not int or index not in edges or not _finite(lo) or not _finite(hi)
                    or not 0 <= lo < hi <= 1):
                _fail('Saved boundary interval is invalid.')
            edge, a, u, left, angle, delta = edges[index]
            if (segment['left_plate'], segment['right_plate']) != (edge.left_plate_id, edge.right_plate_id):
                _fail('Saved boundary owners disagree with the native atlas.')
            is_stationary = bool(np.all(delta == 0.))
            span_angle = (hi-lo)*angle
            spans.setdefault(index, []).append((lo, hi))
            if is_stationary:
                stationary.append(span_angle)
                continue
            mid = .5*(lo+hi)*angle
            normal = float(delta @ u)*math.cos(mid)-float(delta @ a)*math.sin(mid)
            shear = float(delta @ left)
            if math.hypot(normal, shear) == 0.:
                zero_midpoint.append(span_angle)
                continue
            sampled.append((span_angle, math.degrees(math.atan2(abs(shear), abs(normal)))))
        if set(spans) != set(edges):
            _fail('Saved motion omits native interplate edges.')
        for intervals in spans.values():
            intervals.sort()
            if (intervals[0][0] != 0. or intervals[-1][1] != 1.
                    or any(abs(a[1]-b[0]) > 2e-14 for a, b in zip(intervals, intervals[1:]))):
                _fail('Saved motion intervals leave gaps or overlaps.')
        total_angle = math.fsum(angles)
        factor = radius*YEAR*100.
        rms = {name: factor*math.sqrt(math.fsum(values)/total_angle)
               for name, values in (('normal', normal_terms), ('shear', shear_terms), ('relative', full_terms))}
        sample_angle = math.fsum(w for w, _ in sampled)
        result = dict(schema=SCHEMA, status='WORKING NON-CANON',
            scientific_status='DIAGNOSTICS_NOT_REALISM_ACCEPTANCE', motion_id=motion.motion_id,
            atlas_id=atlas.atlas_id, geometry_id=atlas.geometry_id, validation=validation,
            interplate_edge_count=len(edges), segment_count=len(segments),
            boundary_length_m=radius*total_angle,
            boundary_length_fractions={key: math.fsum(values)/total_angle for key, values in totals.items()},
            fractions_method='Exact Euler-derived normal zero crossings weighted by spherical arc length; unresolved includes stationary.',
            unresolved_method='Normal amplitude within the relative-rotation round-off envelope; not a physical transform threshold.',
            boundary_rms_cm_year=rms,
            rms_method='Analytic great-circle integrals of squared relative normal, shear and full speed; all boundary length.',
            obliquity=dict(method='MIDPOINT_APPROXIMATION_LENGTH_WEIGHTED',
                convention='0 degrees is normal motion; 90 degrees is shear; sign is discarded.',
                mean_degrees=None if not sampled else math.fsum(w*v for w, v in sampled)/sample_angle,
                sample_count=len(sampled), included_length_m=radius*sample_angle,
                excluded_stationary_segment_count=len(stationary),
                excluded_stationary_length_m=radius*math.fsum(stationary),
                excluded_zero_speed_midpoint_count=len(zero_midpoint),
                excluded_zero_speed_midpoint_length_m=radius*math.fsum(zero_midpoint)),
            limitations=[
                'Midpoint obliquity can change with segmentation; exact RMS is subdivision invariant.',
                'Saved regime and opening labels are not used; numerical unresolved classification uses relative rotation only.',
                'Only relative motion is compared; a common reference-frame rotation cancels.',
                'Descriptive initial kinematics do not establish geological realism or finite-time stability.'])
        # Refuse overflow rather than emitting a nominally successful non-finite report.
        json.dumps(result, allow_nan=False)
        return result
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        if isinstance(exc, ContractError):
            raise
        _fail('Invalid or non-finite motion assessment inputs.')


def assess_project(path):
    """Reopen one saved native project read-only; never repeat generation."""
    from new_world_project import load_project
    project = load_project(path)  # Includes retained motion/dependency admission.
    if project.motion is None:
        _fail('The saved project has no initial motion.')
    return _assess(project.atlas, project.motion, 'saved-project-load-with-motion-and-dependency-checks')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='Existing saved native world project; opened read-only.')
    args = parser.parse_args(argv)
    print(json.dumps(assess_project(args.project), sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
