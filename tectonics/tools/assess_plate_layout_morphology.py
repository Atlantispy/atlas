"""Bounded new-world morphology diagnostics, never geological acceptance.

The owner supplies frozen plans and a generation callback. Every attempted plan,
including a refused seed, stays in the returned report. Native geometry and the
existing PB2002 exposure/observation-scale protocol remain authoritative. This
tool adds no generation retry, fitted score, source rebind or scientific gate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import CancelledError
from dataclasses import replace
import hashlib
import math
from pathlib import Path
import time

import numpy as np

from atlas_tectonics import Rotation, layout_metrics, plate_outline_cycles
from atlas_tectonics.geometry import GeometryError, _check_cancel
from atlas_tectonics.plate_reference_acceptance import (
    OBSERVATION_SCALES_M, compare_distributions,
    evaluation_record, record_role, reference_protocol)
from atlas_tectonics.plate_reference_dataset import (
    ReferenceDataError, multiscale_ring_measures)
from atlas_tectonics.plate_reference_use import ReferenceUsePlan
from atlas_tectonics.resources import MemoryLimitError, select_budget
from atlas_tectonics.spherical_atlas import SphericalAtlas, build_spherical_atlas


_CASE = Path(__file__).resolve().parents[1] / 'cases/w01_plate_layout_revision.json'
_ROTATION_AXIS = (1., 2., 3.)
_ROTATION_ANGLE = .8
_METRIC_KEYS = ('area_fractions', 'area_steradians', 'perimeter_radians',
                'compactness', 'neighbour_count', 'connected_components')


def _bounds():
    import json
    raw = _CASE.read_bytes()
    case = json.loads(raw)['acceptance']
    return dict(angular=case['geometry_angular_tolerance_rad'],
                area=case['geometry_area_closure_sr'],
                source_sha256=hashlib.sha256(raw).hexdigest())


def _owners(atlas, directions, *, angular_tolerance, budget, cancel):
    """Bound query scratch independently of the number of sampled seams."""
    result = []
    with atlas.index(budget=budget) as index:
        for start in range(0, len(directions), 128):
            _check_cancel(cancel)
            block = directions[start:start + 128]
            hits = index.query(block, angular_tolerance_rad=angular_tolerance,
                               budget=budget, cancel=cancel)
            owners = [set() for _ in block]
            for point, owner in hits.pairs:
                owners[int(point)].add(hits.owner_ids[int(owner)])
            result.extend(owners)
    return result


def _geometry(atlas, metrics, *, bounds, budget, cancel):
    """Independently enumerate actual half edges and owner incidence."""
    uses = defaultdict(list)
    vertex_owners = defaultdict(set)
    regions = {p.region_id: p.plate_id for p in atlas.patches}
    for patch_index, patch in enumerate(atlas.patches):
        for ring in patch.rings:
            for begin, end in zip(ring, ring[1:] + ring[:1]):
                uses[tuple(sorted((begin, end)))].append((begin, end, patch_index))
                vertex_owners[begin].add(patch.plate_id)
    incidence_issues = []
    for edge_index, (left, right) in enumerate(atlas.side_patches):
        begin, end = (atlas.vertex_ids[i] for i in atlas.edge_vertices[edge_index])
        expected = {(begin, end, int(left)), (end, begin, int(right))}
        found = uses.get((begin, end), [])
        if len(found) != 2 or set(found) != expected:
            incidence_issues.append(edge_index)
    junction_issues, junction_counts = [], Counter()
    for i, vertex_id in enumerate(atlas.vertex_ids):
        _check_cancel(cancel)
        junction = atlas.junction(i, budget=budget, cancel=cancel)
        observed = {regions[r] for r in junction.sector_region_ids}
        if observed != vertex_owners[vertex_id]:
            junction_issues.append(vertex_id)
        junction_counts[len(observed)] += 1

    points = atlas.vertex_directions
    midpoints = points[atlas.edge_vertices].sum(axis=1)
    midpoints /= np.linalg.norm(midpoints, axis=1)[:, None]
    # Explicit +/-180-degree representations and both geographic poles.
    seam = [[math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
            for lat in (-math.pi / 3, 0., math.pi / 3) for lon in (-math.pi, math.pi)]
    probes = np.array([[0., 0., 1.], [0., 0., -1.]] + seam)
    all_points = np.concatenate((points, midpoints, probes))
    hits = _owners(atlas, all_points, angular_tolerance=bounds['angular'], budget=budget, cancel=cancel)
    wanted = [vertex_owners[v] for v in atlas.vertex_ids]
    wanted += [{atlas.patches[int(i)].plate_id for i in pair} for pair in atlas.side_patches]
    ownership_issues = [i for i, (a, b) in enumerate(zip(hits, wanted)) if a != b]
    probe_hits = hits[len(wanted):]
    seam_matches = all(probe_hits[i] == probe_hits[i + 1] for i in (2, 4, 6))
    closure = abs(math.fsum(atlas.patch_areas_sr) - 4 * math.pi)
    euler = atlas.vertex_count - atlas.edge_count + sum(1 - len(p.holes) for p in atlas.patches)
    passed = (closure <= bounds['area'] and euler == 2 and len(uses) == atlas.edge_count
              and not incidence_issues and not junction_issues and not ownership_issues
              and all(probe_hits) and seam_matches
              and all(c == 1 for c in metrics['connected_components']))
    return dict(status='PASS' if passed else 'FAIL', area_closure_error_sr=closure,
                area_bound_sr=bounds['area'], euler_characteristic=euler,
                directed_edge_uses=sum(map(len, uses.values())),
                edge_ownership_discrepancies=incidence_issues,
                junction_discrepancies=junction_issues,
                junction_owner_count_histogram={str(k): v for k, v in sorted(junction_counts.items())},
                connected_components=metrics['connected_components'],
                point_ownership_discrepancies=ownership_issues,
                vertices_and_edge_midpoints_checked=len(wanted),
                pole_and_seam_owner_sets=[sorted(v) for v in probe_hits],
                longitude_seam_representations_agree=seam_matches,
                interpretation='static coverage and owner topology; no junction dynamics'), all_points, hits


def _rotation(atlas, metrics, points, owners, *, bounds, budget, cancel):
    rotation = Rotation.from_axis_angle(_ROTATION_AXIS, _ROTATION_ANGLE)
    patches = tuple(replace(p, chart=replace(p.chart, centre=tuple(rotation.apply(p.chart.centre))))
                    for p in atlas.patches)
    rotated = build_spherical_atlas(
        atlas.sphere, dict(zip(atlas.vertex_ids, rotation.apply(atlas.vertex_directions))),
        patches, budget=budget, cancel=cancel,
        angular_resolution_rad=atlas.descriptor()['angular_resolution_rad'],
        source_bindings={'diagnostic_rotation_of': atlas.atlas_id})
    measured = layout_metrics(rotated, budget=budget, cancel=cancel)
    errors = {key: float(np.max(np.abs(np.asarray(measured[key]) - metrics[key])))
              for key in _METRIC_KEYS}
    limits = {key: bounds['area'] if key == 'area_steradians' else bounds['angular']
              for key in errors}
    mismatch = [i for i, (a, b) in enumerate(zip(
        _owners(rotated, rotation.apply(points), angular_tolerance=bounds['angular'],
                budget=budget, cancel=cancel), owners)) if a != b]
    # Also rerun the actual cut algorithm on the rotated support of a new-world
    # candidate. Merely rotating a finished picture would not expose orientation
    # sensitivity in generation itself. Patch IDs/order and random seed stay fixed.
    cut_rotation = dict(status='NOT_APPLICABLE')
    binding = atlas.descriptor()['source_bindings'].get('new_world_layout')
    if binding is not None:
        from atlas_tectonics.plate_layout import _assign, _graph
        with budget.reserve(4096*len(rotated.patches)+65536, category='rotated-layout-cut'):
            labels = _assign(_graph(rotated), rotated.patch_areas_sr,
                np.asarray(binding['area_spectrum']['target_fractions']),
                int(binding['geometry_seed'], 16), cancel)
        disagreements = [i for i,p in enumerate(atlas.patches)
                         if p.plate_id != f'plate-{labels[i]:06d}']
        cut_rotation = dict(status='PASS' if not disagreements else 'FAIL',
                            changed_support_owners=disagreements,
                            interpretation='same seeded sparse cuts on globally rotated support')
    passed = (not mismatch and all(errors[k] <= limits[k] for k in errors)
              and cut_rotation['status'] != 'FAIL')
    return dict(status='PASS' if passed else 'FAIL', axis=list(_ROTATION_AXIS),
                angle_radians=_ROTATION_ANGLE, maximum_absolute_differences=errors,
                existing_numerical_bounds=limits, ownership_discrepancies=mismatch,
                owner_samples_checked=len(points),
                cut_rotation=cut_rotation,
                interpretation='rotated realised geometry, plus cut rerun where candidate inputs exist')


def _shapes(atlas, *, budget, cancel):
    rows = []
    for plate_id in atlas.plate_ids:
        _check_cancel(cancel)
        row = dict(plate_id=plate_id)
        try:
            rings = plate_outline_cycles(atlas, plate_id, budget=budget, cancel=cancel)
            if len(rings) != 1:
                row.update(status='UNSUPPORTED_MULTIRING_COMPARISON', ring_count=len(rings))
            else:
                row.update(status='MEASURED', measures=multiscale_ring_measures(
                    rings[0], atlas.sphere.radius_m, OBSERVATION_SCALES_M,
                    budget=budget, cancel=cancel))
        except (GeometryError, ReferenceDataError) as exc:
            row.update(status='UNRESOLVED_OUTLINE', error=str(exc))
        rows.append(row)
    return rows


def _outline_geometry(metrics, shapes, bounds):
    areas = dict(zip(metrics['plate_ids'], metrics['area_steradians']))
    measured = [row for row in shapes if row['status'] == 'MEASURED']
    formula = max((row['measures']['native']['area_formula_disagreement_sr']
                   for row in measured), default=None)
    atlas_error = max((abs(row['measures']['native']['area_steradians'] - areas[row['plate_id']])
                       for row in measured), default=None)
    complete = len(measured) == len(shapes)
    passed = complete and max(formula, atlas_error) <= bounds['area']
    return dict(status='PASS' if passed else 'FAIL_OR_INCOMPLETE',
        plates_attempted=len(shapes), plates_measured=len(measured),
        maximum_formula_disagreement_sr=formula,
        maximum_ring_vs_atlas_area_error_sr=atlas_error, existing_area_bound_sr=bounds['area'])


def prepare_reference(use_plan, *, include_withheld, run_id, budget=None, cancel=None):
    """Select audited eligible observations; never bypass structural exclusions.

    The caller prepares the existing ReferenceUsePlan once. Its strict numerical
    report, including unresolved source findings, has already been validated.
    Reusing those exact measurements avoids another complete reference pass.
    """
    if type(use_plan) is not ReferenceUsePlan or type(include_withheld) is not bool:
        raise ReferenceDataError('audited ReferenceUsePlan and explicit holdout choice required')
    strict, summary = use_plan.strict_report(), use_plan.summary()
    rows = []
    for observed in strict['plates']:
        _check_cancel(cancel)
        pid = observed['plate_id']
        role = record_role(observable='outline', plate_id=pid)
        row = dict(plate_id=pid, role=role, use_eligibility={})
        for use in ('ordinary_surface_morphology', 'surface_neighbour_count'):
            try:
                use_plan.require_use(use, plate_id=pid)
                row['use_eligibility'][use] = dict(eligible=True)
            except ReferenceDataError as exc:
                row['use_eligibility'][use] = dict(eligible=False, reason=str(exc))
        if role == 'WITHHELD_WITHIN_MODEL' and not include_withheld:
            row['status'] = 'NOT_SELECTED_WITHHELD'
        elif not row['use_eligibility']['ordinary_surface_morphology']['eligible']:
            row['status'] = 'EXCLUDED_BY_REFERENCE_USE_POLICY'
        else:
            row.update(status='MEASURED', measures=observed['multiscale'])
        rows.append(row)

    observations = [use_plan.observations(metric='area_fraction', split='development',
        run_id=run_id, area_basis='published_table', budget=budget, cancel=cancel)]
    for split in ('development', 'withheld'):
        if split == 'withheld' and not include_withheld:
            continue
        observations.append(use_plan.observations(metric='neighbour_count', split=split,
            run_id=run_id, budget=budget, cancel=cancel))
        scope = [r for r in rows if (r['role'] == 'WITHHELD_WITHIN_MODEL') == (split == 'withheld')]
        eligible = [r for r in scope if r['use_eligibility']['ordinary_surface_morphology']['eligible']]
        excluded = [dict(plate_id=r['plate_id'],
                        reason=r['use_eligibility']['ordinary_surface_morphology']['reason'])
                    for r in scope if not r['use_eligibility']['ordinary_surface_morphology']['eligible']]
        for si, scale in enumerate(OBSERVATION_SCALES_M):
            for pi, phase in enumerate((0., .5)):
                for metric in ('compactness', 'reflex_turning_radians', 'boundary_length_radians'):
                    observations.append(use_plan.observations(metric=metric, split=split,
                        run_id=run_id, scale_m=scale, phase=phase, budget=budget, cancel=cancel))
                # This diagnostic is derived only from eligible audited rows;
                # the plan's high-level observations API has no moment field.
                values, unresolved = _phase_population(eligible, si, pi, 'boundary_moment_ratio')
                observations.append(dict(metric='boundary_moment_ratio', split=split,
                    values=values, expected_population_count=len(scope), included_count=len(values),
                    excluded=excluded, unresolved_count=unresolved,
                    observation_scale_m=scale, sampling_phase=phase,
                    policy_id=use_plan.policy_id, strict_report_sha256=use_plan.report_id,
                    use='ordinary_surface_morphology',
                    derivation='middle/smallest boundary moment from eligible audited strict-report rows',
                    audit=evaluation_record(use_plan.dataset_id, use_plan.dataset_id,
                        split=split, run_id=run_id,
                        purpose='validation' if split == 'withheld' else 'calibration')))
    return dict(dataset=strict['dataset'], dataset_id=use_plan.dataset_id,
                protocol=reference_protocol(), include_withheld=include_withheld,
                shapes=rows, connectivity=strict['connectivity'], observations=observations,
                reference_use=summary,
                exposure_note='Registered within-model roles, not secret or independent data; prior evaluations remain exposed.')


def _phase_population(rows, scale_index, phase_index, metric):
    values, unresolved = [], 0
    for row in rows:
        if row['status'] != 'MEASURED':
            unresolved += 1
            continue
        phase = row['measures']['scales'][scale_index]['phases'][phase_index]
        if phase['status'] != 'MEASURED':
            unresolved += 1
            continue
        if metric == 'boundary_moment_ratio':
            eigen = phase['boundary_second_moment_eigenvalues']
            # Two minor moments give a documented anisotropy proxy. This is not
            # a fitted ellipse, area inertia tensor or universal elongation law.
            if eigen[0] <= 0:
                unresolved += 1
                continue
            value = eigen[1] / eigen[0]
        else:
            key = {'compactness': 'sampled_compactness',
                   'boundary_length_radians': 'sampled_perimeter_radians'}.get(metric, metric)
            value = phase[key]
        if not math.isfinite(value):
            unresolved += 1
        else:
            values.append(value)
    return values, unresolved


def _comparisons(atlas, metrics, shapes, reference, *, run_id, budget, cancel):
    result = []
    shared = dict(dataset_id=reference['dataset_id'], candidate_id=atlas.atlas_id,
                  run_id=run_id, budget=budget, cancel=cancel)
    for observation in reference['observations']:
        metric, split = observation['metric'], observation['split']
        if split == 'withheld' and not reference['include_withheld']:
            raise ReferenceDataError('unselected withheld observations cannot enter comparison')
        role_record = evaluation_record(reference['dataset_id'], atlas.atlas_id,
            split=split, run_id=run_id,
            purpose='validation' if split == 'withheld' else 'calibration')
        scale, phase = observation['observation_scale_m'], observation['sampling_phase']
        if metric in ('area_fraction', 'neighbour_count'):
            actual = metrics['area_fractions' if metric == 'area_fraction' else 'neighbour_count']
            missing = 0
        else:
            actual, missing = _phase_population(shapes, OBSERVATION_SCALES_M.index(scale),
                                               (0., .5).index(phase), metric)
        expected = observation['values']
        unknown = observation.get('unresolved_count', len(observation.get('unresolved', [])))
        if actual and expected:
            row = compare_distributions(expected, actual, metric=metric,
                split=split, reference_scale_m=scale, candidate_scale_m=scale,
                unresolved_reference=unknown, unresolved_candidate=missing, **shared)
        else:
            row = dict(status='UNRESOLVED_POPULATION_COMPARISON', metric=metric,
                split=split, observation_scale_m=scale,
                reference_count=len(expected), candidate_count=len(actual),
                unresolved_reference=unknown, unresolved_candidate=missing,
                scientific_threshold=None, evaluation=role_record)
        row.update(sampling_phase=phase,
            reference_selection={k: v for k, v in observation.items() if k != 'values'},
            excluded_reference=len(observation['excluded']),
            association='unpaired populations; no Earth-to-candidate plate correspondence')
        result.append(row)
    return result


def assess_layout(atlas, *, run_id, reference=None, budget=None, cancel=None):
    """Assess one realised layout; pass labels apply only to numerical geometry."""
    if type(atlas) is not SphericalAtlas or not isinstance(run_id, str) or not run_id.strip():
        raise GeometryError('typed atlas and named assessment run required')
    _check_cancel(cancel)
    started = time.perf_counter()
    policy, bounds = select_budget(budget), _bounds()
    with policy.reserve(4096 * (atlas.vertex_count + atlas.edge_count) + 65536,
                        category='layout-morphology-assessment'):
        metrics = layout_metrics(atlas, budget=policy, cancel=cancel)
        geometry, points, owners = _geometry(atlas, metrics, bounds=bounds, budget=policy, cancel=cancel)
        rotation = _rotation(atlas, metrics, points, owners, bounds=bounds, budget=policy, cancel=cancel)
        shapes = _shapes(atlas, budget=policy, cancel=cancel)
        comparisons = [] if reference is None else _comparisons(
            atlas, metrics, shapes, reference, run_id=run_id, budget=policy, cancel=cancel)
        return dict(schema='atlas.new-world.layout-morphology.v1',
            status='ASSESSED_NOT_GEOLOGICALLY_ACCEPTED', run_id=run_id,
            candidate_id=atlas.atlas_id, geometry_id=atlas.geometry_id,
            source_bindings=atlas.descriptor()['source_bindings'],
            geometry=geometry, global_rotation=rotation, layout_metrics=metrics,
            outline_measurements=shapes, outline_geometry=_outline_geometry(metrics, shapes, bounds),
            population_comparisons=comparisons,
            reference_status='NOT_SELECTED' if reference is None else 'DESCRIPTIVE_COMPARISON_ONLY',
            reference_protocol=None if reference is None else reference['protocol'],
            reference_provenance=None if reference is None else reference.get('dataset'),
            reference_connectivity=None if reference is None else reference['connectivity'],
            reference_use=None if reference is None else reference['reference_use'],
            reference_withheld_selected=False if reference is None else reference['include_withheld'],
            existing_case_sha256=bounds['source_sha256'],
            assessment_tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            scientific_acceptance=False, elapsed_seconds=time.perf_counter() - started,
            limitations=[
                'PB2002 areas are exposed calibration, including under a variable size prior.',
                'Registered withheld shapes are within-model and may have been evaluated previously; no new independent evidence family.',
                'Whole candidate populations are compared descriptively with each declared reference split; counts and unresolved outlines remain explicit.',
                'Boundary-moment ratio is middle/smallest uncentred boundary second moment: an anisotropy proxy, not area-based elongation.',
                'Reflex turning describes concavity at named observation scales, not continuous tectonic curvature.',
                'Junction incidence and adjacency do not establish dynamic junction stability or plate formation.',
                'No scientific threshold, best-seed selection, retry, velocity inference or geological acceptance.'])


def assess_cases(plans_sequence, *, generate, run_id, reference=None,
                 resolution_pairs=(), budget=None, cancel=None):
    """Preserve all supplied LayoutCandidate results, including rejected seeds.

    ``generate(plan)`` returns an object with ``atlas`` and ``report``. Resolution
    comparisons use explicit case-index pairs; no heuristic matching of seeds or
    source bindings and no assertion that different supports should agree.
    """
    started = time.perf_counter()
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('named assessment run required, including refused-only runs')
    if not plans_sequence:
        raise ValueError('at least one explicitly selected plan required')
    rows = []
    for index, plan in enumerate(plans_sequence):
        row = dict(case_index=index, generation=None, assessment=None)
        try:
            _check_cancel(cancel)
            candidate = generate(plan)
            row['generation'] = candidate.report
            if candidate.atlas is not None:
                row['assessment'] = assess_layout(candidate.atlas, run_id=f'{run_id}-case-{index}',
                    reference=reference, budget=budget, cancel=cancel)
        except CancelledError as exc:
            row['assessment_error'] = dict(status='CANCELLED', error=str(exc),
                                           exception=type(exc).__name__)
            rows.append(row)
            break  # Honour cancellation; retain the completed prefix and failure.
        except (GeometryError, ReferenceDataError, MemoryLimitError) as exc:
            row['assessment_error'] = dict(status='REFUSED', error=str(exc),
                                           exception=type(exc).__name__)
        rows.append(row)
    sensitivity = []
    for first, second in resolution_pairs:
        if any(type(i) is not int or i < 0 or i >= len(plans_sequence) for i in (first, second)):
            raise ValueError('resolution comparison needs existing case indices')
        if max(first, second) >= len(rows):
            sensitivity.append(dict(case_indices=[first, second], status='UNRESOLVED_UNATTEMPTED_CASE'))
            continue
        a, b = rows[first]['assessment'], rows[second]['assessment']
        record = dict(case_indices=[first, second], status='UNRESOLVED_REFUSED_CASE')
        if a is not None and b is not None:
            ma, mb = a['layout_metrics'], b['layout_metrics']
            if ma['plate_ids'] != mb['plate_ids']:
                raise ValueError('resolution comparison requires the same explicit plate population')
            record.update(status='DESCRIPTIVE_GENERATING_SUPPORT_SENSITIVITY',
                candidate_ids=[a['candidate_id'], b['candidate_id']],
                metric_differences={k: (np.asarray(mb[k]) - ma[k]).tolist() for k in _METRIC_KEYS},
                scientific_threshold=None,
                interpretation='changed generating support is a different prior, not guaranteed numerical convergence')
        sensitivity.append(record)
    return dict(schema='atlas.new-world.layout-assessment-series.v1', run_id=run_id,
        cases=rows, requested_cases=len(plans_sequence), attempted_cases=len(rows),
        unattempted_case_indices=list(range(len(rows), len(plans_sequence))),
        assessed_cases=sum(row['assessment'] is not None for row in rows),
        generated_cases=sum(row['generation'] is not None and
            (row['assessment'] is not None or 'assessment_error' in row) for row in rows),
        reference=reference,
        resolution_sensitivity=sensitivity, scientific_acceptance=False,
        elapsed_seconds=time.perf_counter() - started)
