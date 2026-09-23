"""Frozen W05 combined synthetic challenge; no new production physics.

All crop faces/centres are compared with independent full-line quadrature.
The nested grids share coordinates, so each independent point is integrated once.
Cell-mean extrema are bracketed from *independent* centre values using a global
Green curvature bound, then every possible winning cell is integrated. This
avoids both centre-for-mean substitution and a full nested-quadrature sweep.
"""
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from atlas_tectonics import (ColumnGrid1D, ListricGeometry, MaterialCohort,
    PreparedListricExtension, ExtensionSupportPolicy, FlexureParameters,
    PreparedExtensionSupport, PreparedExtensionWorkflow)
from atlas_tectonics.extension_support import ContinuousCellMeanFlexure
from atlas_tectonics.finite_flexure import FiniteRegionFlexure, FlexureBoundary1D
from atlas_tectonics.regional import RegionalGrid1D
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from w05_reference import hanging_wall_means, footwall_means, boundary_exchanges
from w05_support_reference import smooth_listric_response, smooth_listric_cell_mean


ROOT = Path(__file__).resolve().parents[1]
FRACTIONS = np.array([.25, .75])
# The unchanged W02 arithmetic account contract, also checked by the tests.
ACCOUNT_ROUNDOFF = 128*np.finfo(np.float64).eps


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configuration():
    support_path = ROOT/'cases/w05_support.json'
    support = json.loads(support_path.read_text(encoding='utf-8'))
    motion_path = ROOT/'cases'/support['motion_case']
    if _sha(motion_path) != support['motion_case_sha256']:
        raise ValueError('frozen motion source changed; no automatic repin')
    motion = json.loads(motion_path.read_text(encoding='utf-8'))
    geometry = ListricGeometry(motion['crust_thickness_m'], motion['detachment_depth_m'],
        motion['surface_dip_rad'], motion['trace_m'], motion['case_id'])
    elastic = FlexureParameters(motion['case_id'], 'frozen W05 synthetic acceptance',
        support['young_modulus_pa'], support['elastic_thickness_m'],
        support['poisson_ratio'], support['mantle_density_kg_m3'], support['gravity_m_s2'])
    policy = ExtensionSupportPolicy(elastic, support['max_abs_displacement_m'],
        support['max_abs_slope'], support['max_bending_strain'],
        support['max_omitted_displacement_m'], motion['case_id'])
    velocity = motion['velocity_m_per_year']/motion['seconds_per_year']
    common = dict(velocity_m_s=velocity, density_kg_m3=motion['density_kg_m3'],
        width_m=motion['width_m'], cohorts=(
            MaterialCohort('a', 'crust', 'synthetic-A', -motion['seconds_per_year']),
            MaterialCohort('b', 'crust', 'synthetic-B', None)), fractions=FRACTIONS,
        time_s=0., epoch_id=motion['case_id'], datum_id='initial-flat-surface',
        source_id=motion['case_id'], backend='reference')
    # Independent algebra from input scalars, not production geometry properties.
    length = motion['detachment_depth_m']/math.tan(motion['surface_dip_rad'])
    rigidity = support['young_modulus_pa']*support['elastic_thickness_m']**3/(12*(1-support['poisson_ratio']**2))
    restoring = support['mantle_density_kg_m3']*support['gravity_m_s2']
    physics = dict(depth_m=motion['detachment_depth_m'], decay_length_m=length,
        trace_m=motion['trace_m'], density_kg_m3=motion['density_kg_m3'],
        gravity_m_s2=support['gravity_m_s2'], rigidity_n_m=rigidity,
        restoring_pa_per_m=restoring)
    return motion, support, geometry, policy, common, physics


def _grid(case, spacing, domain=None):
    left, right = case['domain_m'] if domain is None else domain
    return ColumnGrid1D(np.linspace(left, right, round((right-left)/spacing)+1),
                        frame_id=case['case_id'])


def _maxabs(values):
    return float(np.max(np.abs(values), initial=0.))


def _point_reference(case, physics):
    step = min(case['grid_spacing_m'])/2
    left, right = case['crop_m']
    points = np.linspace(left, right, round((right-left)/step)+1)
    values, uncertainties = {}, {}
    started = time.perf_counter()
    for displacement in case['output_displacements_m']:
        if displacement == 0:
            values[displacement] = np.zeros((len(points), 3))
            uncertainties[displacement] = np.zeros((len(points), 3))
        else:
            pairs = [smooth_listric_response(float(x), displacement, **physics)
                     for x in points]
            values[displacement] = np.asarray([pair[0] for pair in pairs])
            uncertainties[displacement] = np.asarray([pair[1] for pair in pairs])
    return points, values, uncertainties, time.perf_counter()-started


def _extremum(edges, exact_delta, point_w, point_error, actual_surface,
              indices, displacement, physics, *, minimum):
    """Independent discrete cell-mean extremum, with exhaustive exclusion.

    |G''(s)| <= sqrt(2)*exp(-|s|/alpha)/(K*alpha**3), hence
    sup|w''| <= 2*sqrt(2)*max|q|/(K*alpha**2). Taylor's integral remainder
    bounds |mean(w)-w(centre)| by dx**2*sup|w''|/24. The independent centre
    uncertainties and H quadrature comparison floor are included in the bounds.
    No production extremum selects or limits the independent candidate cells.
    """
    width = float(edges[1]-edges[0])
    alpha = (4*physics['rigidity_n_m']/physics['restoring_pa_per_m'])**.25
    peak = physics['depth_m']*physics['density_kg_m3']*physics['gravity_m_s2']*(-math.expm1(-displacement/physics['decay_length_m']))
    curvature = 2*math.sqrt(2)*peak/(physics['restoring_pa_per_m']*alpha**2)
    approximation = exact_delta-point_w
    radius = point_error+width**2*curvature/24+2e-10
    lower, upper = approximation-radius, approximation+radius
    if minimum:
        threshold = float(np.min(upper[indices]))
        candidates = indices[lower[indices] <= threshold]
    else:
        threshold = float(np.max(lower[indices]))
        candidates = indices[upper[indices] >= threshold]
    if not len(candidates):
        raise AssertionError('independent extremum has no admissible candidate')
    refined, error = [], []
    for index in candidates:
        mean, estimate = smooth_listric_cell_mean(float(edges[index]), float(edges[index+1]),
            displacement, **physics)
        refined.append(float(exact_delta[index]-mean))
        error.append(float(estimate)+2e-10)
    refined, error = np.asarray(refined), np.asarray(error)
    winner = int(np.argmin(refined) if minimum else np.argmax(refined))
    if minimum:
        possible = candidates[refined-error <= np.min(refined+error)]
        actual_index = int(indices[np.argmin(actual_surface[indices])])
    else:
        possible = candidates[refined+error >= np.max(refined-error)]
        actual_index = int(indices[np.argmax(actual_surface[indices])])
    reference_index = int(candidates[winner])
    return dict(production_height_m=float(actual_surface[actual_index]),
        reference_height_m=float(refined[winner]),
        height_error_with_uncertainty_m=float(abs(actual_surface[actual_index]-refined[winner])+max(error)),
        production_location_m=float((edges[actual_index]+edges[actual_index+1])/2),
        reference_location_m=float((edges[reference_index]+edges[reference_index+1])/2),
        location_difference_bound_m=float(max(abs(possible-actual_index))*width),
        candidates_integrated=len(candidates), cells_considered=len(indices),
        possible_reference_locations=len(possible),
        reference_uncertainty_m=float(max(error)),
        centre_to_mean_bound_m=float(width**2*curvature/24),
        curvature_bound_per_m=curvature)


def _accounts(motion, state, displacement, geometry):
    widths = motion.grid.widths_m
    before = [math.fsum(float(v*d) for v, d in zip(row, widths))
              for row in motion.initial.material.thickness_m]
    after = [math.fsum(float(v*d) for v, d in zip(row, widths))
             for row in state.material.thickness_m]
    expected = np.asarray(boundary_exchanges(float(motion.grid.edges_m[0]),
        float(motion.grid.edges_m[-1]), displacement, **geometry))
    residuals, ratios = [], []
    for b, a, exchanges in zip(before, after, state.exchange_m2):
        residual = math.fsum((a, -b, -float(exchanges[0]), -float(exchanges[1])))
        scale = max(b, a, _maxabs(exchanges), np.finfo(float).tiny)
        residuals.append(abs(residual)); ratios.append(abs(residual)/(ACCOUNT_ROUNDOFF*scale))
    total_residual = math.fsum((*after, *(-v for v in before), *(-float(v) for v in state.exchange_m2.flat)))
    total_scale = max(math.fsum(before), math.fsum(after), _maxabs(expected))
    receipt = state.material.transition_record
    receipt_matches = (receipt is None if displacement == 0 else
        receipt['initial_material'] == motion.initial.material.state_id and
        receipt['account_reference'] == 'initial_material' and
        np.array_equal(np.asarray(receipt['cumulative_cohort_accounts'])[:, 6:8], state.exchange_m2))
    return dict(max_cohort_residual_m2=max(residuals),
        max_cohort_roundoff_fraction=max(ratios), total_residual_m2=abs(total_residual),
        total_roundoff_fraction=abs(total_residual)/(ACCOUNT_ROUNDOFF*total_scale),
        max_independent_exchange_error_m2=_maxabs(state.exchange_m2-FRACTIONS[:, None]*expected),
        exchange_error_roundoff_fraction=_maxabs(state.exchange_m2-FRACTIONS[:, None]*expected)/(ACCOUNT_ROUNDOFF*max(total_scale, 1.)),
        left_exchange_is_zero=bool(np.all(state.exchange_m2[:, 0] == 0.)),
        right_exchange_is_export=bool(np.all(state.exchange_m2[:, 1] <= 0.)),
        cohort_history_unchanged=state.material.cohorts == motion.initial.material.cohorts,
        receipt_matches=bool(receipt_matches))


def run_case():
    """Run once, return compact JSON metrics; the test module retains the result."""
    started = time.perf_counter()
    case, support_case, geometry, policy, common, physics = _configuration()
    paths = [ROOT/'cases/w05_motion.json', ROOT/'cases/w05_support.json', Path(__file__),
             ROOT/'tests/w05_reference.py', ROOT/'tests/w05_support_reference.py']
    source_hashes = {p.relative_to(ROOT).as_posix(): _sha(p) for p in paths}
    reference_points, references, uncertainties, reference_seconds = _point_reference(case, physics)
    reference_step = reference_points[1]-reference_points[0]
    reference_geometry = {key: physics[key] for key in ('depth_m', 'decay_length_m', 'trace_m')}
    budget = WorkBudget(128 << 20)
    rows, final_250, domain_bounds, time_rows = [], None, [], []
    times = tuple(a/common['velocity_m_s'] for a in case['output_displacements_m'])
    with ExecutionContext('reference') as context, budget.reserve(8 << 20, category='w05-acceptance-retained-comparisons'):
        common['context'] = context
        common['budget'] = budget
        for spacing in case['grid_spacing_m']:
            grid = _grid(case, spacing)
            edges = grid.edges_m
            centres = (edges[:-1]+edges[1:])/2
            crop = (edges[:-1] >= case['crop_m'][0]) & (edges[1:] <= case['crop_m'][1])
            point_coordinates = np.linspace(edges[0], edges[-1], 2*grid.cells+1)
            point_crop = (point_coordinates >= case['crop_m'][0]) & (point_coordinates <= case['crop_m'][1])
            point_lookup = np.rint((point_coordinates[point_crop]-reference_points[0])/reference_step).astype(int)
            centre_lookup = np.rint((centres[crop]-reference_points[0])/reference_step).astype(int)
            if not np.array_equal(reference_points[point_lookup], point_coordinates[point_crop]):
                raise AssertionError('reference grid does not exactly cover all requested crop points')
            initial_h = hanging_wall_means(edges, 0., **reference_geometry)
            exact_f = footwall_means(edges, crust_thickness_m=case['crust_thickness_m'], **reference_geometry)
            with PreparedListricExtension(grid, geometry, **common) as motion:
                # This existing, separately verified solver isolates the combined
                # adapter on IDENTICAL cell q; it is not the continuum reference.
                point_operator = FiniteRegionFlexure(RegionalGrid1D(grid.cells, edges[-1]-edges[0], edges[0]),
                    policy.elastic, FlexureBoundary1D('continuous', 'continuous', case['case_id']))
                mean_operator = ContinuousCellMeanFlexure(point_operator, budget=budget)
                previous = motion.initial
                with PreparedExtensionWorkflow(motion, policy, times, budget=budget) as workflow:
                    for index, displacement in enumerate(case['output_displacements_m']):
                        checkpoint = workflow.run(through=index)
                        state, result = checkpoint.state, checkpoint.support
                        fields = result.cell_means
                        exact_h = hanging_wall_means(edges, displacement, **reference_geometry)
                        delta = exact_h-initial_h
                        actual_h = np.sum(state.material.thickness_m, axis=0)
                        h_error = abs(actual_h[crop]-exact_h[crop])
                        denominator = float(np.sum(abs(exact_h[crop])*spacing))
                        point_error = abs(result.face_centre_response[point_crop, 0]-references[displacement][point_lookup, 0])
                        point_uncertainty = uncertainties[displacement][point_lookup, 0]
                        descriptor = result.descriptor()
                        conditional_bound = (descriptor['exterior_right_bound_pa']/
                            (math.sqrt(2)*physics['restoring_pa_per_m'])*
                            math.exp(-(edges[-1]-case['crop_m'][1])/point_operator.alpha_m))
                        standalone_mean = mean_operator.solve(fields[:, 0], budget=budget)
                        standalone_points = point_operator.solve(np.r_[fields[:, 0], 0., 0.], budget=budget)
                        parent_matches = (state is previous if displacement == 0 else
                            state.material.parent_state_id == previous.material.state_id)
                        row = dict(spacing_m=spacing, cells=grid.cells, displacement_m=displacement,
                            crop_cells=int(np.sum(crop)), crop_face_centre_points=int(np.sum(point_crop)),
                            max_h_error_m=float(max(h_error)), h_relative_l1=float(np.sum(h_error)*spacing/denominator),
                            max_w_error_m=float(max(point_error)),
                            max_w_error_with_uncertainty_m=float(max(point_error+point_uncertainty)),
                            max_point_reference_uncertainty_m=float(max(point_uncertainty)),
                            max_same_q_mean_error_m=_maxabs(standalone_mean-fields[:, 1]),
                            max_same_q_point_error_m=_maxabs(standalone_points[:, 0]-result.face_centre_response[:, 0]),
                            max_q_error_as_height_m=_maxabs(fields[:, 0]/(case['density_kg_m3']*support_case['gravity_m_s2'])-delta),
                            max_footwall_reference_error_m=_maxabs(fields[:, 8]-exact_f),
                            footwall_stationary=bool(np.array_equal(fields[:, 8], motion.footwall_thickness_m)),
                            output_identity=bool(np.array_equal(fields[:, 3], fields[:, 2]-fields[:, 1]) and
                                np.array_equal(fields[:, 4], -case['crust_thickness_m']-fields[:, 1]) and
                                np.array_equal(fields[:, 5], fields[:, 8]-case['crust_thickness_m']-fields[:, 1]) and
                                np.array_equal(fields[:, 6], case['crust_thickness_m']+fields[:, 2]) and
                                np.array_equal(fields[:, 7], actual_h) and
                                np.array_equal(fields[:, 9], -spacing*case['width_m']*fields[:, 1])),
                            material_nonnegative=bool(np.all(state.material.thickness_m >= 0.)),
                            parent_history_matches=bool(parent_matches),
                            repeated_output_same_checkpoint=workflow.run(through=index).checkpoint_id == checkpoint.checkpoint_id,
                            accounts=_accounts(motion, state, displacement, reference_geometry),
                            continuous_validity_bounds=descriptor['continuous_validity_bounds'],
                            max_bending_strain_bound=descriptor['max_bending_strain_bound'],
                            omitted_response_bounds=descriptor['omitted_response_bounds'],
                            crop_exterior_displacement_bound_m=conditional_bound)
                        if displacement:
                            # Arrays outside the crop are never eligible for extrema.
                            crop_edges = edges[np.r_[crop, False] | np.r_[False, crop]]
                            cropped_centres = centres[crop]
                            for name, eligible, minimum in (
                                ('basin', np.flatnonzero(cropped_centres >= case['trace_m']), True),
                                ('footwall', np.flatnonzero(crop_edges[1:] <= case['trace_m']), False)):
                                row[name] = _extremum(crop_edges, delta[crop],
                                    references[displacement][centre_lookup, 0],
                                    uncertainties[displacement][centre_lookup, 0], fields[crop, 3],
                                    eligible, displacement, physics, minimum=minimum)
                        else:
                            row['zero_load_and_movement'] = bool(np.all(fields[:, :4] == 0.) and
                                np.all(result.face_centre_response == 0.) and np.all(state.exchange_m2 == 0.))
                        rows.append(row)
                        previous = state
                        if spacing == 250. and displacement == case['output_displacements_m'][-1]:
                            final_250 = fields[crop, 3].copy()
                            domain_bounds.append(conditional_bound)
        for intervals in case['time_intervals']:
            with PreparedListricExtension(_grid(case, 250.), geometry, **common) as motion:
                state = motion.initial
                for index in range(1, intervals+1):
                    state = motion.advance(state, time_s=times[-1]*index/intervals)
                with PreparedExtensionSupport(motion, policy) as support:
                    result = support.solve(state)  # One final support solve per partition.
                    edges = motion.grid.edges_m
                    crop = (edges[:-1] >= case['crop_m'][0]) & (edges[1:] <= case['crop_m'][1])
                    time_rows.append(dict(intervals=intervals, accepted_intervals=state.intervals,
                        final_surface=result.cell_means[crop, 3].copy(), support_evaluations=1))
        time_differences = [dict(from_intervals=a['intervals'], to_intervals=b['intervals'],
            max_surface_difference_m=_maxabs(a['final_surface']-b['final_surface']))
            for a, b in zip(time_rows[:-1], time_rows[1:])]
        for row in time_rows:
            row['difference_from_requested_outputs_m'] = _maxabs(row.pop('final_surface')-final_250)
        with PreparedListricExtension(_grid(case, 250., case['enlarged_domain_m']), geometry, **common) as motion:
            with PreparedExtensionSupport(motion, policy) as support:
                result = support.solve(motion.advance(motion.initial, time_s=times[-1]))
                edges = motion.grid.edges_m
                crop = (edges[:-1] >= case['crop_m'][0]) & (edges[1:] <= case['crop_m'][1])
                domain_difference = _maxabs(result.cell_means[crop, 3]-final_250)
                descriptor = result.descriptor()
                domain_bounds.append(descriptor['exterior_right_bound_pa']/
                    (math.sqrt(2)*physics['restoring_pa_per_m'])*
                    math.exp(-(edges[-1]-case['crop_m'][1])/support.operator.alpha_m))
        stationary = dict(common, velocity_m_s=0.)
        with PreparedListricExtension(_grid(case, 250.), geometry, **stationary) as motion:
            state = motion.advance(motion.initial, time_s=times[-1])
            with PreparedExtensionSupport(motion, policy) as support:
                result = support.solve(state)
                zero_motion = bool(np.array_equal(state.material.thickness_m, motion.initial.material.thickness_m)
                    and np.all(state.exchange_m2 == 0.) and np.all(result.cell_means[:, :4] == 0.)
                    and np.all(result.face_centre_response == 0.))
    if budget.reserved_bytes:
        raise AssertionError('acceptance fixture leaked a resource reservation')
    if source_hashes != {p.relative_to(ROOT).as_posix(): _sha(p) for p in paths}:
        raise ValueError('acceptance sources changed while running')
    drop = geometry.detachment_depth_m*(-math.expm1(-case['output_displacements_m'][-1]/physics['decay_length_m']))
    rebound = case['density_kg_m3']/support_case['mantle_density_kg_m3']*drop
    return dict(source_status='WORKING NON-CANON SYNTHETIC', backend='reference',
        coverage='all crop cell centres and faces at every frozen output on all three grids',
        grids=rows, unique_reference_points_per_output=len(reference_points),
        nonzero_reference_point_evaluations=len(reference_points)*(len(case['output_displacements_m'])-1),
        reference_quadrature_seconds=reference_seconds,
        time_partitions=time_rows, time_comparisons=time_differences,
        domain_crop_difference_m=domain_difference, domain_exterior_bounds_m=domain_bounds,
        domain_difference_with_exterior_bounds_m=domain_difference+math.fsum(domain_bounds),
        zero_motion_pass=zero_motion,
        hydrostatic_control=dict(unflexed_drop_m=drop, rebound_m=rebound,
            net_subsidence_m=drop-rebound,
            direct_density_fraction_subsidence_m=(1-case['density_kg_m3']/support_case['mantle_density_kg_m3'])*drop),
        limits=dict(h_max_m=case['finest_h_max_error_m'], h_relative_l1=case['finest_h_relative_l1'],
            smooth_w_m=support_case['smooth_reference_error_m'], reference_uncertainty_m=support_case['reference_uncertainty_m'],
            time_difference_m=case['time_surface_difference_m'], domain_difference_m=case['domain_surface_difference_m'],
            extrema_location_m=min(case['grid_spacing_m']), matched_convolution_m=support_case['matched_convolution_atol_m'],
            geometry_quadrature_m=case['quadrature_comparison_atol_m'],
            displacement_m=support_case['max_abs_displacement_m'], slope=support_case['max_abs_slope'],
            bending_strain=support_case['max_bending_strain']),
        work_budget=budget.statistics(), source_sha256=source_hashes,
        elapsed_seconds=time.perf_counter()-started,
        limitations='Independent quadrature reports numerical uncertainty estimates plus bounded Green tails; '
            'the synthetic dry prescribed-motion constant-rigidity case is not empirical landscape validation. '
            'Recovery, refusals, dilation and hydrostatic production controls are separate selected tests.')
