"""Small fixed acceptance matrix; compose existing checks, do not replay suites.

SPDX-License-Identifier: AGPL-3.0-only
Run with the declared scientific Python, -B and --output NEW_DIRECTORY.
Each phase uses a fresh process. Every attempted case and refusal is retained;
there are no seed retries, parameter reductions or historical receipt updates.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'src')]
YEAR = 365.25 * 86400.
TIMES = [0., 50000. * YEAR, 100000. * YEAR]
# Declared before any run. First pair isolates seed; last isolates plate/support
# settings with the same underlying geological field. No selection after results.
CASES = [dict(name='seed42', seed=42, plates=6, support=192),
         dict(name='seed43', seed=43, plates=6, support=192),
         dict(name='seed42-finer', seed=42, plates=12, support=512)]
JOB_ID = '7' * 32


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def read(path):
    return json.loads(path.read_bytes())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def timed(function):
    start = time.perf_counter()
    result = function()
    return result, time.perf_counter() - start


def scientific(output):
    return {k: v for k, v in output.items() if k != 'accounted_workspace_peak_bytes'}


def physical_checks(initial, outputs):
    """Independent finite-area and column-weight identities, not model callbacks."""
    import numpy as np
    n = initial['native_input']
    first = outputs[0]
    require([r['elapsed_s'] for r in outputs] == TIMES, 'Missing requested time')
    g = np.asarray(n['gradient_s'])
    rho = np.asarray(n['density_kg_m3'])[:, None]
    h0 = np.asarray(first['thickness_m'])
    max_residual = 0.
    for r in outputs:
        require(r['volume_m3'] == first['volume_m3'], 'Volume changed')
        require(r['mass_kg'] == first['mass_kg'], 'Mass changed')
        require(r['project_id'] == initial['project_id'] and
                r['initial_id'] == initial['initial_id'], 'Wrong world or initial state')
        require(not r['enthalpy_known'] and all(r[k] is None for k in
                ('enthalpy_j', 'evolved_temperature_k', 'absolute_elevation_m')), 'Unknowns lost')
        require(all(r[k] == n[k] for k in ('epoch_id', 'frame_id', 'datum_id')), 'Context changed')
        jacobian = math.exp(float(np.trace(g)) * r['elapsed_s'])
        np.testing.assert_allclose(r['area_ratio'], jacobian, rtol=1e-12, atol=0.)
        np.testing.assert_allclose(r['area_m2'], np.asarray(first['area_m2']) * jacobian,
                                   rtol=1e-12, atol=0.)
        np.testing.assert_allclose(r['thickness_m'], h0 / jacobian, rtol=1e-12, atol=0.)
        delta = np.asarray(r['thickness_m']) - h0
        # Use the independent compensation-depth weight equation (not the
        # producer's surface formula) and scale residual by the weight changes.
        residual = np.sum(rho * delta, axis=0) + n['mantle_density_kg_m3'] * np.asarray(r['base_change_m'])
        scale = np.maximum(1., np.sum(np.abs(rho * delta), axis=0))
        require(bool(np.all(np.abs(residual) <= 1e-12 * scale)), 'Column weight unbalanced')
        np.testing.assert_allclose(np.asarray(r['surface_change_m']) - r['base_change_m'],
                                   delta.sum(axis=0), rtol=1e-12, atol=1e-9)
        max_residual = max(max_residual, float(np.max(np.abs(residual))))
    end = outputs[-1]
    return dict(exact_mass_and_volume=True, finite_area_and_thickness=True,
        unknowns_and_context_preserved=True, max_weight_residual_kg_m2=max_residual,
        final_area_ratio=end['area_ratio'][0],
        mean_surface_change_m=float(np.mean(end['surface_change_m'])),
        surface_change_range_m=[min(end['surface_change_m']), max(end['surface_change_m'])],
        accounted_evolution_workspace_peak_bytes=max(r['accounted_workspace_peak_bytes'] for r in outputs))


def diversity(rows):
    require(len(rows) == len(CASES) and all(r.get('status') == 'PASS' for r in rows),
            'Incomplete matrix; refusals are not passes')
    a, b, c = [r['create']['world'] for r in rows]
    area_gap = sum(abs(x-y) for x, y in zip(a['ranked_plate_area_fractions'],
                                           b['ranked_plate_area_fractions'], strict=True))
    crust_gap = max(abs(x-y) for x, y in zip(a['sorted_crust_thickness_m'],
                                            b['sorted_crust_thickness_m'], strict=True))
    speed_gap = abs(a['boundary_rms_cm_year'] - b['boundary_rms_cm_year'])
    uplift_gap = abs(rows[0]['resume']['physics']['mean_surface_change_m'] -
                    rows[1]['resume']['physics']['mean_surface_change_m'])
    require(area_gap > .001 and crust_gap > 1. and speed_gap > 1e-6 and uplift_gap > .001,
            'Seeds differ only in labels, orientation or numerical noise')
    require(a['structure_id'] == c['structure_id'], 'Grid/plate count changed underlying geology')
    require(a['motion_id'] != c['motion_id'] and a['plate_count'] == 6 and c['plate_count'] == 12,
            'Changed settings reused stale motion or layout')
    return dict(rotation_invariant_area_l1=area_gap, max_crust_thickness_gap_m=crust_gap,
        boundary_rms_gap_cm_year=speed_gap, mean_surface_change_gap_m=uplift_gap,
        identical_geology_across_plate_and_support_change=True, changed_dependent_motion=True,
        interpretation='Finite non-noise diversity, not a calibrated planet population distribution')


def peak_process_bytes():
    if sys.platform == 'win32':
        import psutil
        return psutil.Process().memory_info().peak_wset, 'Windows peak working set including imports'
    if sys.platform.startswith('linux'):
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024, 'Linux ru_maxrss including imports'
    return None, 'Unavailable on this platform'


def worker(directory, phase, index):
    case = CASES[index]
    source = directory / 'initial.atlas'
    jobs_root = directory / 'jobs'
    job_dir = jobs_root / JOB_ID
    record = dict(status='INCOMPLETE', phase=phase)
    try:
        session_sha = digest(ROOT / 'tools/new_world_session.py')
        import new_world_job as jobs
        import new_world_evolution as model
        if phase == 'create':
            from new_world_contract import new_request
            from new_world_session import response
            settings = {k: dict(mode='fixed', value=v) for k, v in dict(
                radius_m=6371000., gravity_m_s2=9.81, plate_count=case['plates'],
                continental_fraction=.3).items()}
            request = new_request(f"{case['seed']:032x}", settings=settings,
                support_cells=case['support'], resources=dict(max_wall_seconds=120., max_work_bytes=128 << 20))
            body = json.dumps(dict(title=case['name'], request=request)).encode()
            (answer, code), seconds = timed(lambda: response(['generate', '--file', str(source)], io.BytesIO(body)))
            require(code == 0, 'Generation refused: ' + str(answer.get('error')))
            view = answer['data']
            write_new(directory / 'view.json', view)
            # The native archive is reopened in a separate process below.
            from new_world_project import load_project
            saved = load_project(source)
            atlas = saved.atlas
            areas = {p: 0. for p in atlas.plate_ids}
            for patch, area in zip(atlas.patches, atlas.patch_areas_sr, strict=True):
                areas[patch.plate_id] += float(area) / (4 * math.pi)
            record.update(create_save_view_call_s=seconds, archive_bytes=source.stat().st_size,
                archive_sha256=digest(source), world=dict(project_id=view['project_id'],
                    structure_id=saved.structure.structure_id, motion_id=saved.motion.motion_id,
                    plate_count=len(atlas.plate_ids), ranked_plate_area_fractions=sorted(areas.values()),
                    sorted_crust_thickness_m=sorted(c.crust_thickness_m for c in saved.structure.state.case.columns),
                    boundary_rms_cm_year=saved.motion.descriptor()['diagnostics']['achieved_boundary_rms_cm_year']))
        elif phase == 'evolve':
            from new_world_session import response
            (answer, code), seconds = timed(lambda: response(['read', '--file', str(source)], io.BytesIO()))
            require(code == 0 and answer['data'] == read(directory / 'view.json'), 'Reopened scientific view differs')
            jobs_root.mkdir()
            result, evolution_s = timed(lambda: jobs.submit(jobs_root, JOB_ID, source,
                options={}, schedule_s=TIMES, max_new_outputs=1))
            state = result['job']
            require(state['state'] == 'partial' and state['completed_outputs'] == 1,
                    'Partial evolution refused: ' + str(state.get('error')))
            record.update(reopen_view_call_s=seconds, exact_saved_view=True,
                partial_evolution_call_s=evolution_s, job=state,
                initial_sha256=digest(job_dir / 'initial.json'), prefix_sha256=digest(job_dir / 'output-0000.json'))
        else:
            before = read(directory / 'evolve.json')
            result, resume_s = timed(lambda: jobs.resume(jobs_root, JOB_ID))
            state = result['job']
            require(state['state'] == 'completed' and state['computed_outputs'] == 2 and
                    state['restored_outputs'] == 1 and state['timings']['prepare_s'] == 0.,
                    'Resume refused or repeated initial sampling: ' + str(state.get('error')))
            require(digest(job_dir / 'initial.json') == before['initial_sha256'] and
                    digest(job_dir / 'output-0000.json') == before['prefix_sha256'], 'Committed prefix changed')
            # Read via the authenticated public API, then compare every scientific
            # field with one direct prepared evaluation of the same initial state.
            outputs = [jobs.read_output(jobs_root, JOB_ID, i) for i in range(3)]
            initial = read(job_dir / 'initial.json')
            with model.PreparedEvolution(initial) as owner:
                for t, actual in zip(TIMES, outputs, strict=True):
                    require(scientific(owner.evaluate(t)) == scientific(actual), 'Fresh-process scientific parity failed')
            warm, warm_s = timed(lambda: jobs.resume(jobs_root, JOB_ID))
            require(warm['job']['computed_outputs'] == 0 and warm['job']['restored_outputs'] == 3 and
                    warm['job']['state'] == 'completed', 'Completed reuse recomputed physics')
            require(jobs.read_output(jobs_root, JOB_ID)['output_id'] == outputs[-1]['output_id'], 'Warm output differs')
            record.update(resume_call_s=resume_s, verified_reuse_call_s=warm_s,
                exact_fresh_process_scientific_parity=True, unchanged_committed_prefix=True,
                physics=physical_checks(initial, outputs), job=state,
                output_ids=[r['output_id'] for r in outputs],
                retained_job_bytes=sum(p.stat().st_size for p in job_dir.iterdir() if p.is_file()),
                approximation=initial['native_input']['metadata']['approximation'])
        record['sources'] = jobs._sources(model)
        require(digest(ROOT / 'tools/new_world_session.py') == session_sha, 'Session adapter changed during phase')
        record['sources']['session_sha256'] = session_sha
        record['status'] = 'PASS'
    except Exception as exc:
        record['failure'] = dict(type=type(exc).__name__, message=str(exc))
    record['process_peak_bytes'], record['process_peak_scope'] = peak_process_bytes()
    write_new(directory / (phase + '.json'), record)
    return 0 if record['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', choices=('create', 'evolve', 'resume'), help=argparse.SUPPRESS)
    parser.add_argument('--case-index', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.output, args.worker, args.case_index)
    args.output.mkdir()  # Exclusive directory claim before all scientific work.
    tool_sha = digest(Path(__file__))
    write_new(args.output / 'matrix.json', dict(cases=CASES, times_s=TIMES, options={},
        tool_sha256=tool_sha, policy='one attempt per case; all failures retained; no adaptation'))
    rows = []
    for i, case in enumerate(CASES):
        directory = args.output / case['name']
        directory.mkdir()
        row = dict(case=case, status='INCOMPLETE')
        rows.append(row)
        for phase in ('create', 'evolve', 'resume'):
            start = time.perf_counter()
            try:
                run = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                    '--output', str(directory), '--worker', phase, '--case-index', str(i)],
                    capture_output=True, timeout=330., check=False)
                elapsed = time.perf_counter() - start
                # Full error streams are local diagnostics; public summary is
                # built from structured child results, never a truncated log.
                (directory / (phase + '.stderr.txt')).write_bytes(run.stderr)
                (directory / (phase + '.stdout.txt')).write_bytes(run.stdout)
                row[phase] = read(directory / (phase + '.json'))
                row[phase]['fresh_process_wall_s'] = elapsed
                require(run.returncode == 0 and row[phase]['status'] == 'PASS', f'{phase} did not pass')
            except Exception as exc:
                row['failure'] = dict(phase=phase, type=type(exc).__name__, message=str(exc))
                break
            print(f"{case['name']} {phase}: PASS ({elapsed:.3f} s)", flush=True)
        else:
            row['status'] = 'PASS'
        write_new(directory / 'case.json', row)
    result = dict(schema='atlas.new-world-combined-acceptance.v1', status='INCOMPLETE',
        scope='initial worlds and bounded generated regional continuation', cases=rows,
        platform=platform.system(), python=platform.python_version(), tool_sha256=tool_sha,
        matrix_sha256=digest(args.output / 'matrix.json'))
    try:
        result['diversity'] = diversity(rows)
        bindings = [row[phase]['sources'] for row in rows for phase in ('create','evolve','resume')]
        require(all(b == bindings[0] for b in bindings), 'Source/runtime drift between cases or processes')
        require(digest(Path(__file__)) == tool_sha, 'Acceptance tool changed during run')
        # The session adapter is not a numerical dependency of the evolution
        # job, so record its source separately as part of this acceptance tool.
        result['session_sha256'] = digest(ROOT / 'tools/new_world_session.py')
        result['status'] = 'PASS'
    except Exception as exc:
        result['failure'] = dict(type=type(exc).__name__, message=str(exc))
    write_new(args.output / 'acceptance.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'cases'}, sort_keys=True), flush=True)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
