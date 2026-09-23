#!/usr/bin/env python3
"""W05.3 bounded load/support checks and matched-output timing, no terrain run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
import numpy as np
from atlas_tectonics import (ColumnGrid1D, ListricGeometry, MaterialCohort,
    PreparedListricExtension, ExtensionSupportPolicy, PreparedExtensionSupport, FlexureParameters)
from atlas_tectonics.extension_support import _cell_mean_weights
from atlas_tectonics._validation import frozen, read_array
from w05_support_reference import smooth_listric_response, smooth_listric_cell_mean


def pair(first, second, calls=1):
    samples = [[], []]
    for repeat in range(3):
        for index in ([0, 1] if repeat%2 == 0 else [1, 0]):
            start = time.perf_counter()
            for _ in range(calls):
                (first, second)[index]()
            samples[index].append(time.perf_counter()-start)
    a, b = map(statistics.median, samples)
    return dict(calls_per_repeat=calls, baseline_seconds=samples[0], prepared_seconds=samples[1],
        baseline_median_seconds=a, prepared_median_seconds=b, saved_seconds=a-b,
        saved_percent=100*(a-b)/a, speedup=a/b)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    case_path = ROOT/'cases/w05_support.json'
    c = json.loads(case_path.read_text())
    motion_path = ROOT/'cases'/c['motion_case']
    if hashlib.sha256(motion_path.read_bytes()).hexdigest() != c['motion_case_sha256']:
        raise ValueError('motion case source changed; no automatic repin')
    m = json.loads(motion_path.read_text())
    geometry = ListricGeometry(m['crust_thickness_m'], m['detachment_depth_m'],
                              m['surface_dip_rad'], m['trace_m'], m['case_id'])
    elastic = FlexureParameters(m['case_id'], 'step-1 frozen synthetic case', c['young_modulus_pa'],
        c['elastic_thickness_m'], c['poisson_ratio'], c['mantle_density_kg_m3'], c['gravity_m_s2'])
    policy = ExtensionSupportPolicy(elastic, c['max_abs_displacement_m'], c['max_abs_slope'],
        c['max_bending_strain'], c['max_omitted_displacement_m'], m['case_id'])
    u = m['velocity_m_per_year']/m['seconds_per_year']
    a = m['output_displacements_m'][-1]
    common = dict(velocity_m_s=u, density_kg_m3=m['density_kg_m3'], width_m=m['width_m'],
        cohorts=(MaterialCohort('a', 'crust', 'synthetic-A', None),
                 MaterialCohort('b', 'crust', 'synthetic-B', None)), fractions=(.25, .75),
        time_s=0., epoch_id=m['case_id'], datum_id='initial-flat-surface', source_id=m['case_id'],
        backend='reference')
    physics = dict(depth_m=geometry.detachment_depth_m, decay_length_m=geometry.decay_length_m,
        trace_m=geometry.trace_m, density_kg_m3=m['density_kg_m3'], gravity_m_s2=c['gravity_m_s2'],
        rigidity_n_m=elastic.rigidity_n_m, restoring_pa_per_m=elastic.restoring_pa_per_m)
    def grid(dx, domain=None):
        l, r = m['domain_m'] if domain is None else domain
        return ColumnGrid1D(np.linspace(l, r, round((r-l)/dx)+1), frame_id=m['case_id'])
    accuracy, domain_reference = [], None
    for dx in m['grid_spacing_m']:
        g = grid(dx)
        with PreparedListricExtension(g, geometry, **common) as motion:
            state = motion.advance(motion.initial, time_s=a/u)
            with PreparedExtensionSupport(motion, policy) as support:
                result = support.solve(state)
                points = np.linspace(g.edges_m[0], g.edges_m[-1], 2*g.cells+1)
                crop = np.flatnonzero((points >= m['crop_m'][0]) & (points <= m['crop_m'][1]))
                # Explicit bounded probes for this component step, not an
                # assertion of completed global coupled acceptance.
                indices = np.unique(np.r_[crop[np.linspace(0, len(crop)-1, 81).astype(int)],
                    crop[np.argmin(result.face_centre_response[crop, 0])],
                    np.argmin(abs(points)), np.argmin(abs(points-a))])
                errors, uncertainties = [], []
                for i in indices:
                    reference, estimate = smooth_listric_response(float(points[i]), a, **physics)
                    errors.append(abs(float(result.face_centre_response[i, 0])-reference[0]))
                    uncertainties.append(estimate[0])
                centres = (g.edges_m[1:]+g.edges_m[:-1])/2
                mean_indices = np.unique([np.argmin(abs(centres-x))
                    for x in (-40000., -20000., -5000., 0., 1000., 5000., 10000., 40000., 79000.)])
                mean_errors, mean_uncertainty = [], []
                for i in mean_indices:
                    reference, estimate = smooth_listric_cell_mean(g.edges_m[i], g.edges_m[i+1], a, **physics)
                    mean_errors.append(abs(float(result.cell_means[i, 1])-reference))
                    mean_uncertainty.append(estimate)
                if (max(errors+mean_errors) > c['smooth_reference_error_m'] or
                        max(uncertainties+mean_uncertainty) > c['reference_uncertainty_m']):
                    raise ValueError('independent smooth support component gate failed')
                means = result.cell_means
                np.testing.assert_array_equal(means[:, 3], means[:, 2]-means[:, 1])
                # Direct finite-load prediction independently recovers its
                # expected material density sign without a second mantle load.
                expected_q = m['density_kg_m3']*c['gravity_m_s2']*means[:, 2]
                np.testing.assert_allclose(means[:, 0], expected_q, rtol=1e-10, atol=2e-7)
                accuracy.append(dict(dx_m=dx, cells=g.cells, point_probes=len(indices),
                    max_point_w_error_m=max(errors), mean_probes=len(mean_indices),
                    max_mean_w_error_m=max(mean_errors), max_reference_uncertainty_m=max(uncertainties+mean_uncertainty),
                    surface_min_m=float(np.min(means[:, 3])), surface_max_m=float(np.max(means[:, 3])),
                    max_mean_vs_centre_difference_m=float(np.max(abs(means[:, 1]-result.face_centre_response[1::2, 0]))),
                    exterior_right_bound_pa=result.descriptor()['exterior_right_bound_pa'],
                    omitted_response_bounds=result.descriptor()['omitted_response_bounds'],
                    continuous_validity_bounds=result.descriptor()['continuous_validity_bounds'],
                    max_bending_strain_bound=result.descriptor()['max_bending_strain_bound']))
                if dx == 250.:
                    mask = (centres >= m['crop_m'][0]) & (centres <= m['crop_m'][1])
                    domain_reference = means[mask, 3].copy()
    g = grid(250., m['enlarged_domain_m'])
    with PreparedListricExtension(g, geometry, **common) as motion:
        state = motion.advance(motion.initial, time_s=a/u)
        with PreparedExtensionSupport(motion, policy) as support:
            values = support.solve(state).cell_means
            centres = (g.edges_m[:-1]+g.edges_m[1:])/2
            mask = (centres >= m['crop_m'][0]) & (centres <= m['crop_m'][1])
            domain_difference = float(np.max(abs(values[mask, 3]-domain_reference)))
            if domain_difference > m['domain_surface_difference_m']:
                raise ValueError('enlarged-domain surface sensitivity failed')

    g = grid(125.)
    with PreparedListricExtension(g, geometry, **common) as motion:
        states = [motion.advance(motion.initial, time_s=x/u) for x in m['output_displacements_m'][1:]]
        start = time.perf_counter()
        with PreparedExtensionSupport(motion, policy) as prepared:
            setup = time.perf_counter()-start
            expected = [prepared.solve(s) for s in states]
            load = expected[-1].cell_means[:, 0]
            weights = _cell_mean_weights(g.cells, 125., prepared.operator.alpha_m, elastic.restoring_pa_per_m)
            def direct():
                with motion._budget.reserve(1024*g.cells+8192, category='direct-mean-control'):
                    captured = read_array(load, 'load')
                    return frozen(np.convolve(captured, weights)[g.cells-1:2*g.cells-1])
            def fft():
                return prepared.mean_operator.solve(load, budget=motion._budget)
            convolution_error = float(np.max(abs(direct()-fft())))
            if convolution_error > c['matched_convolution_atol_m']:
                raise ValueError('FFT and direct same-cell mean mismatch')
            kernel_times = pair(direct, fft, calls=12)
            def rebuilt():
                results = []
                for state in states:
                    with PreparedExtensionSupport(motion, policy) as fresh:
                        results.append(fresh.solve(state))
                return results
            def reused():
                return [prepared.solve(state) for state in states]
            if [r.result_id for r in rebuilt()] != [r.result_id for r in expected]:
                raise ValueError('rebuilt and reused projection identity mismatch')
            workflow_times = pair(rebuilt, reused)
            retained = prepared.operator.setup_bytes+prepared.mean_operator.setup_bytes
    paths = [case_path, motion_path, Path(__file__), ROOT/'tests/w05_support_reference.py',
             ROOT/'src/atlas_tectonics/extension_support.py', ROOT/'src/atlas_tectonics/reuse.py',
             ROOT/'src/atlas_tectonics/extension.py', ROOT/'src/atlas_tectonics/finite_flexure.py',
             ROOT/'src/atlas_tectonics/column_loads.py']
    record = dict(status='PASS_W05_STEP_3_COMPONENTS', platform=platform.platform(),
        python=sys.version.split()[0], numpy=np.__version__, numerical_threads=1,
        accuracy=accuracy, domain_crop_surface_difference_m=domain_difference,
        direct_fft_max_mean_error_m=convolution_error, cell_mean_kernel_timing=kernel_times,
        three_output_projection_timing=workflow_times, one_support_preparation_seconds=setup,
        reused_sequence_plus_one_setup_seconds=workflow_times['prepared_median_seconds']+setup,
        retained_operator_bytes=retained,
        scope='Three frozen grids with 81-84 point and 9 mean probes each; full-domain validity envelopes. Matched cell means compare identical cell-constant loads, exact precomputed weights, direct versus linear FFT. Projection compares rebuilding with reusing support geometry on identical three material states; load snapshots, identity and budget checks included. Common material-generation cost excluded. No external package or field validation; combined W05 acceptance remains a later step.',
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    payload = json.dumps(record, indent=2, allow_nan=False)
    print(payload, flush=True)
    if args.output:
        args.output.write_text(payload+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
