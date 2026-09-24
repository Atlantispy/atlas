#!/usr/bin/env python3
"""Frozen W09 W1-W4 controls and small setup-inclusive water timing.

Creates a new requested report; never rewrites fixtures or existing evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter


FIXTURE_PATH = 'tectonics/cases/w09_surface_processes_r1.json'
FIXTURE_SHA = 'ccd8cb4da78c903e1eddbc5021522233e2dd787cb0da205df15091a4296c67a2'
CAP = 128 * 1024**2
CONTROL_IDS = (
    'W09-W1-receiver-change', 'W09-W2-area-weighted-lake',
    'W09-W3-nested-fill-and-drawdown', 'W09-W4-dry-out-losses')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def source_inventory(repo):
    paths = [*sorted((repo / 'tectonics/src/atlas_tectonics').glob('*.py')),
             repo / FIXTURE_PATH, repo / 'tectonics/docs/W09_SURFACE_PROCESSES.md',
             repo / 'tectonics/tests/test_w09_water.py', Path(__file__).resolve()]
    return {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def api_for(repo):
    sys.path.insert(0, str(repo / 'tectonics/src'))
    import numpy as np
    from threadpoolctl import threadpool_info
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.stokes_execution import _native_lease
    from atlas_tectonics.w09_water import PreparedWater
    return dict(np=np, WorkBudget=WorkBudget, PreparedWater=PreparedWater,
                native_lease=_native_lease, threadpool_info=threadpool_info)


def make_plan(api, bed, areas, links, outlets, owner, *, source_id='frozen-W09-water'):
    return api['PreparedWater'](bed, areas, links, [1.] * len(links), outlets,
        frame_id='synthetic-planar-SI', datum_id='synthetic-z-up',
        source_id=source_id, budget=owner)


def measured_levels(api, plan, state):
    positive = plan.geometry.areas_m2 > 0
    return (plan.geometry.bed_m[positive] +
            state.water_m3[positive] / plan.geometry.areas_m2[positive]).tolist()


def materialise(state):
    """Complete scientific output, detached from execution-only statistics."""
    water = state.water_m3
    return dict(water_m3=water.tolist(), water_dtype=water.dtype.str,
        water_bytes_sha256=hashlib.sha256(water.tobytes(order='C')).hexdigest(),
        time_s=state.time_s, subsurface_m3=state.subsurface_m3,
        evaporated_m3=state.evaporated_m3, exported_m3=state.exported_m3,
        supplied_m3=state.supplied_m3, initial_total_m3=state.initial_total_m3,
        geometry_id=state.geometry_id, state_id=state.state_id,
        accepted_intervals=state.accepted_intervals)


def check_value(api, checks, name, actual, expected, gates):
    np = api['np']
    got = np.asarray(actual, dtype=float)
    want = np.asarray(expected, dtype=float)
    require(got.shape == want.shape, name + ': reference shape mismatch')
    require(bool(np.all(np.isfinite(got))), name + ': non-finite result')
    errors = np.abs(got-want)
    limits = gates['analytic_absolute_tolerance_in_output_SI_unit'] + \
             gates['analytic_relative_tolerance'] * np.abs(want)
    row = dict(actual=got.tolist(), expected=want.tolist(),
               maximum_absolute_error=float(np.max(errors, initial=0.)),
               passed=bool(np.all(errors <= limits)))
    checks[name] = row
    require(row['passed'], name + ': frozen numerical control failed')


def check_account(api, checks, name, state):
    terms = [*state.water_m3, state.subsurface_m3, state.evaporated_m3,
             state.exported_m3, -state.initial_total_m3, -state.supplied_m3]
    residual = math.fsum(float(value) for value in terms)
    scale = math.fsum(abs(float(value)) for value in terms)
    limit = 128 * api['np'].finfo(float).eps * scale
    checks[name] = dict(residual_m3=residual, absolute_limit_m3=limit,
                        passed=bool(abs(residual) <= limit))
    require(abs(residual) <= limit, name + ': extensive water balance failed')


def analytic_controls(api, frozen, report, verify):
    controls = {row['id']: row for row in frozen['controls']}
    gates = frozen['gates']
    rows = report['analytic_controls'] = []
    for control_id in CONTROL_IDS:
        verify()
        reference = controls[control_id]
        owner = api['WorkBudget'](CAP)
        row = dict(control_id=control_id, status='INCOMPLETE', checks={}, snapshots=[])
        rows.append(row)
        checks = row['checks']

        def check(name, actual, expected):
            check_value(api, checks, name, actual, expected, gates)

        def capture(name, state):
            check_account(api, checks, name + '_account', state)
            row['snapshots'].append(dict(name=name, **materialise(state)))

        if control_id == CONTROL_IDS[0]:
            node_index = {name: index for index, name in enumerate(reference['nodes'])}
            links = [[node_index[a], node_index[b]] for a, b in reference['links']]
            for changed in (False, True):
                bed = list(reference['elevation_m'])
                label = 'changed' if changed else 'open'
                if changed:
                    bed[node_index['O']] = reference['independent_dry_restart_changed_O_elevation_m']
                with make_plan(api, bed, reference['areas_m2'], links, [node_index['O']], owner) as plan:
                    expected_receiver = reference['expected_changed_receiver_of_B' if changed
                                                  else 'expected_initial_receiver_of_B']
                    check(label + '_receiver', int(plan.geometry.receivers[node_index['B']]),
                          node_index[expected_receiver])
                    final = plan.advance(plan.initialise(), reference['duration_s'],
                        runoff_m_s=reference['runoff_m_s'], forcing_id='W1-' + label)
                    check(label + '_export_m3', final.exported_m3,
                          reference['expected_changed_export_m3' if changed else 'expected_open_export_m3'])
                    check(label + '_physical_bed_m', plan.geometry.bed_m, bed)
                    if changed:
                        check('changed_lake_storage_m3', final.water_m3[node_index['L']],
                              reference['expected_changed_lake_storage_m3'])
                        check('changed_lake_level_m', bed[node_index['L']] +
                              final.water_m3[node_index['L']] / reference['areas_m2'][node_index['L']],
                              reference['expected_changed_lake_level_m'])
                    else:
                        check('open_discharge_m3_s', final.exported_m3 / reference['duration_s'],
                              reference['expected_open_discharge_m3_s'])
                        check('open_stored_water_m3', math.fsum(final.water_m3), 0.)
                    capture(label, final)
        elif control_id == CONTROL_IDS[1]:
            with make_plan(api, [*reference['bed_m'], reference['sill_m']],
                           [*reference['areas_m2'], 0.], [[0, 1], [1, 2]], [2], owner) as plan:
                first = plan.add_water(plan.initialise(),
                    [reference['successive_additions_m3'][0], 0., 0.], source_id='W2-first')
                check('first_levels_m', measured_levels(api, plan, first),
                      [reference['expected_first_level_m']] * 2)
                check('first_export_m3', first.exported_m3, reference['expected_first_export_m3'])
                capture('first', first)
                final = plan.add_water(first,
                    [reference['successive_additions_m3'][1], 0., 0.], source_id='W2-second')
                check('final_volume_m3', math.fsum(final.water_m3), reference['expected_final_volume_m3'])
                check('final_levels_m', measured_levels(api, plan, final),
                      [reference['expected_final_level_m']] * 2)
                check('final_export_m3', final.exported_m3, reference['expected_cumulative_export_m3'])
                capture('final', final)
        elif control_id == CONTROL_IDS[2]:
            with make_plan(api, [*reference['bed_m'], reference['connecting_saddle_m'], reference['outer_sill_m']],
                           [*reference['areas_m2'], reference['saddle_storage_area_m2'], 0.],
                           [[0, 2], [1, 2], [2, 3]], [3], owner) as plan:
                first = plan.add_water(plan.initialise(),
                    [reference['successive_additions_to_first_m3'][0], 0., 0., 0.], source_id='W3-first')
                check('first_child_volumes_m3', first.water_m3[:2], reference['expected_first_child_volumes_m3'])
                capture('first', first)
                final = plan.add_water(first,
                    [reference['successive_additions_to_first_m3'][1], 0., 0., 0.], source_id='W3-second')
                check('final_child_volumes_m3', final.water_m3[:2], reference['expected_final_child_volumes_m3'])
                check('cumulative_export_m3', final.exported_m3, reference['expected_cumulative_export_m3'])
                capture('final', final)
                draw = reference['drawdown_control']
                initial = plan.initialise([*reference['expected_first_child_volumes_m3'], 0., 0.])
                loss = [*draw['evaporation_m_s'], 0., 0.]
                # Independent event geometry: each child reaches the exposed saddle.
                split = plan.advance(initial, draw['expected_split_time_s'],
                    evaporation_m_s=loss, forcing_id='W3-draw-to-split')
                check('at_split_child_volumes_m3', split.water_m3[:2], [1., 2.])
                capture('split', split)
                dry = plan.advance(split, draw['expected_first_dry_time_s'] - draw['expected_split_time_s'],
                    evaporation_m_s=loss, forcing_id='W3-draw-to-dry')
                check('at_first_dry_child_volumes_m3', dry.water_m3[:2], [0., 2.])
                capture('first_dry', dry)
                end = plan.advance(initial, draw['duration_s'], evaporation_m_s=loss,
                                   forcing_id='W3-draw-complete')
                check('drawdown_child_volumes_m3', end.water_m3[:2], draw['expected_final_child_volumes_m3'])
                check('drawdown_evaporation_m3', end.evaporated_m3, draw['expected_evaporation_m3'])
                capture('drawdown_final', end)
        else:
            with make_plan(api, [0., 10.], [reference['area_m2'], 0.], [[0, 1]], [1], owner) as plan:
                for initial_volume in (reference['initial_volume_m3'], 0.):
                    label = 'wet_start' if initial_volume else 'dry_start'
                    final = plan.advance(plan.initialise([initial_volume, 0.]), reference['duration_s'],
                        evaporation_m_s=reference['evaporation_m_s'],
                        infiltration_m_s=reference['infiltration_m_s'], forcing_id='W4-' + label)
                    check(label + '_final_volume_m3', math.fsum(final.water_m3), reference['expected_final_volume_m3'])
                    check(label + '_evaporation_m3', final.evaporated_m3,
                          reference['expected_evaporation_m3'] if initial_volume else 0.)
                    check(label + '_subsurface_m3', final.subsurface_m3,
                          reference['expected_subsurface_transfer_m3'] if initial_volume else 0.)
                    check(label + '_export_m3', final.exported_m3, reference['expected_export_m3'])
                    capture(label, final)
        row.update(status='PASS', resource_accounting=owner.statistics())
        require(owner.peak_reserved_bytes <= CAP, 'frozen control exceeded shared budget')
        verify()
    require(tuple(row['control_id'] for row in rows) == CONTROL_IDS,
            'delivered water controls do not match expected coverage')


def timing_geometry(api):
    np = api['np']
    side = 16
    bed = np.array([2*(side-1)-row-column for row in range(side)
                    for column in range(side)], dtype=float)
    areas = np.full(side*side, 100.); areas[-1] = 0.
    links = []
    for row in range(side):
        for column in range(side):
            node = row*side+column
            if column+1 < side:
                links.append([node, node+1])
            if row+1 < side:
                links.append([node, node+side])
    return bed, areas, links, [side*side-1]


def lake_timing_geometry(api):
    """64 translated W3 basins: 128 storage cells, 64 saddles, 64 outlets.

    Each two-cell lake starts at 600 m3: 100 m2 areas and depths 2.5/3.5 m.
    Equal depth-loss rates give simultaneous independently known event times,
    retaining the declared small event budget despite the repeated geometry.
    """
    np = api['np']
    bed, areas, links, outlets = [], [], [], []
    for basin in range(64):
        base = 4*basin
        offset = float(basin)
        bed.extend([offset, offset-1., offset+1., offset+3.])
        areas.extend([100., 100., 0., 0.])
        links.extend([[base, base+2], [base+1, base+2], [base+2, base+3]])
        outlets.append(base+3)
    return np.array(bed), np.array(areas), links, outlets


def timing_sample(api, mode, request_count, fixture='sloping'):
    owner = api['WorkBudget'](CAP)
    outputs, counters = [], dict(geometry_preparations=0, computed_intervals=0, latest_hits=0)
    preparations = 0.
    started = perf_counter()
    geometry = lake_timing_geometry(api) if fixture == 'nested_lakes' else timing_geometry(api)
    source_id = 'nested-lakes-64-W3' if fixture == 'nested_lakes' else 'sloping-grid-16x16'

    def request(plan, index):
        if fixture == 'nested_lakes':
            initial = plan.initialise(api['np'].tile([250., 350., 0., 0.], 64))
            loss = api['np'].tile([(.04, .06, .1)[index], 0., 0., 0.], 64)
            final = plan.advance(initial, 60., evaporation_m_s=loss,
                                 forcing_id=f'changed-lake-loss-source-{index}')
        else:
            initial = plan.initialise()
            final = plan.advance(initial, 60., runoff_m_s=(index+1)*1e-6,
                                 forcing_id=f'changed-runoff-source-{index}')
        outputs.append(materialise(final))

    def collect(plan):
        for name in counters:
            counters[name] += plan.statistics()[name]

    if mode == 'cold':
        for index in range(request_count):
            prepared = perf_counter()
            with make_plan(api, *geometry, owner, source_id=source_id) as plan:
                preparations += perf_counter()-prepared
                request(plan, index)
                collect(plan)
    else:
        prepared = perf_counter()
        with make_plan(api, *geometry, owner, source_id=source_id) as plan:
            preparations += perf_counter()-prepared
            for index in range(request_count):
                request(plan, index)
            collect(plan)
    elapsed = perf_counter()-started
    require(counters['latest_hits'] == 0, 'timing accidentally reused a complete output')
    require(counters['geometry_preparations'] == (request_count if mode == 'cold' else 1),
            'timing did not use its declared preparation route')
    expected_intervals = sum(out['accepted_intervals'] for out in outputs)
    require(counters['computed_intervals'] == expected_intervals and
            request_count <= expected_intervals <= 256,
            'timing omitted/repeated an interval or exceeded the bounded batch event count')
    for index, out in enumerate(outputs):
        if fixture == 'nested_lakes':
            # W3 split after losing 300 m3, first child dry after 400 m3.
            # At 60 s these depth-loss rates give these independent volumes.
            expected_pair = ((130., 230.), (40., 200.), (0., 200.))[index]
            expected = api['np'].tile([*expected_pair, 0., 0.], 64)
            require(bool(api['np'].allclose(out['water_m3'], expected, rtol=1e-10, atol=1e-12)),
                    'lake timing graph failed independent child-volume account')
            require(math.isclose(out['evaporated_m3'], 64*(600.-sum(expected_pair)),
                                rel_tol=1e-10, abs_tol=1e-12),
                    'lake timing graph failed independent evaporation account')
            require(out['exported_m3'] == 0. and out['supplied_m3'] == 0. and
                    out['subsurface_m3'] == 0. and out['initial_total_m3'] == 64*600.,
                    'lake timing graph changed an inactive stock or transfer account')
        else:
            expected = 255 * 100. * (index+1)*1e-6 * 60.
            require(math.isclose(out['exported_m3'], expected, rel_tol=1e-10, abs_tol=1e-12),
                    'timing graph failed independent runoff account')
            require(all(value == 0. for value in out['water_m3']), 'sloping timing graph unexpectedly retained water')
            require(out['accepted_intervals'] == 1, 'sloping timing graph introduced unexpected events')
    require(owner.peak_reserved_bytes <= CAP, 'timing exceeded shared budget')
    return dict(mode=mode, seconds=elapsed, preparation_seconds_included=preparations,
                outputs=outputs, counters=counters, resource_accounting=owner.statistics())


def benchmark(api, report, verify):
    workloads = ((1, 'single_complete_request', 'sloping'),
                 (3, 'three_changed_complete_requests', 'sloping'),
                 (3, 'three_changed_lake_requests', 'nested_lakes'))
    for request_count, label, fixture in workloads:
        result = report[label] = dict(samples=[], request_count=request_count,
            fixture=fixture,
            scope='Fresh initial state, changed forcing values/source IDs and full 60 s evolution per '
                  'request. Cold reconstructs geometry for each request; prepared constructs it once. '
                  'Both include fixture creation, source checks, initialisation, output materialisation, '
                  'statistics and close. Imports/interpreter and outer source audit are excluded. '
                  'The same ordered request sequence is used on both routes; no complete-output hits.')
        if fixture == 'nested_lakes':
            result['fixture_description'] = dict(support_nodes=256, positive_area_cells=128,
                massless_internal_saddles=64, zero_area_outlets=64,
                basin_count=64, basis='Translated W3 two-child lakes; 100 m2 per child',
                initial_child_volumes_m3=[250., 350.],
                first_child_evaporation_m_s=[.04, .06, .1], duration_s=60.,
                expected_final_child_volumes_m3=[[130., 230.], [40., 200.], [0., 200.]],
                expected_split_times_s=[75., 50., 30.],
                expected_first_dry_times_s=[100., 200/3, 40.],
                maximum_total_accepted_intervals_per_three_requests=256)
        expected_outputs = None
        for repeat in range(3):
            order = ('cold', 'prepared') if repeat % 2 == 0 else ('prepared', 'cold')
            for position, mode in enumerate(order):
                verify()
                row = timing_sample(api, mode, request_count, fixture)
                outputs = row.pop('outputs')
                if expected_outputs is None:
                    expected_outputs = outputs
                    result['scientific_outputs'] = outputs
                require(outputs == expected_outputs, 'cold/prepared scientific arrays or metadata differ')
                row.update(repeat=repeat, position=position,
                           scientific_signatures_sha256=[digest(out) for out in outputs])
                result['samples'].append(row)
                verify()
        medians = {mode: statistics.median(row['seconds'] for row in result['samples']
                                           if row['mode'] == mode) for mode in ('cold', 'prepared')}
        difference = medians['cold']-medians['prepared']
        result.update(medians_seconds=medians, cold_minus_prepared_seconds=difference,
            cold_minus_prepared_percent=100.*difference/medians['cold'],
            scientific_outputs_bitwise_equal=True,
            interpretation=('Prepared reuse was faster on this bounded workload only.' if difference > 0
                            else 'No speed saving measured: prepared reuse was slower or equal.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    require(Path(__file__).resolve() == repo / 'tectonics/tools/check_w09_water.py',
            '--repo must own this exact checker')
    with args.report.open('x', encoding='utf-8') as handle:
        report = dict(schema='atlas.w09-water-evidence.v1', source_status='WORKING NON-CANON',
            status='INCOMPLETE', scope='Frozen synthetic W1-W4 water/lake controls and bounded '
                'geometry-reuse timing. No sediment, coupled terrain, empirical geology or whole-world acceptance.',
            limits=dict(accounted_work_bytes=CAP, native_threads=1, accepted_intervals=256,
                        timing_support_nodes=256, timing_positive_area_cells=255,
                        lake_timing_support_nodes=256, lake_timing_positive_area_cells=128,
                        timing_interval_s=60., os_rss_measured=False))
        started = perf_counter()
        try:
            source_hashes = source_inventory(repo)
            report['source_sha256'] = source_hashes
            require(source_hashes[FIXTURE_PATH] == FIXTURE_SHA, 'frozen case register changed; no repinning')
            frozen = json.loads((repo / FIXTURE_PATH).read_bytes())
            design_path = 'tectonics/' + frozen['frozen_design']['path']
            require(source_hashes[design_path] == frozen['frozen_design']['sha256'], 'frozen design changed')
            require(frozen['resource_plan']['work_budget_bytes'] == CAP and
                    frozen['resource_plan']['native_numerical_threads'] == 1 and
                    frozen['resource_plan']['max_cumulative_accepted_subintervals'] == 256,
                    'checker resource bounds differ from frozen design')

            def verify():
                require(source_inventory(repo) == source_hashes,
                        'source, fixture or checker changed during execution; no repinning')

            api = api_for(repo)
            report['runtime'] = dict(python=platform.python_version(), platform=platform.platform(),
                                     numpy=api['np'].__version__)
            with api['native_lease']():
                pools = api['threadpool_info']()
                report['runtime']['native_pools'] = [
                    {key: value for key, value in pool.items() if key != 'filepath'} for pool in pools]
                require(all(pool['num_threads'] == 1 for pool in pools), 'native thread count exceeds one')
                analytic_controls(api, frozen, report, verify)
                benchmark(api, report, verify)
                require(all(pool['num_threads'] == 1 for pool in api['threadpool_info']()),
                        'native thread count changed during execution')
            verify()
            report['maximum_accounted_peak_bytes'] = max(
                [row['resource_accounting']['peak_reserved_bytes'] for row in report['analytic_controls']] +
                [row['resource_accounting']['peak_reserved_bytes']
                 for name in ('single_complete_request', 'three_changed_complete_requests',
                              'three_changed_lake_requests')
                 for row in report[name]['samples']])
            report['status'] = 'PASS'
        except BaseException as exc:
            report['status'] = 'FAIL'
            report['failure'] = dict(type=type(exc).__name__, message=str(exc))
        finally:
            report['elapsed_seconds'] = perf_counter()-started
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write('\n')
        print(json.dumps(dict(status=report['status'], report=str(args.report),
            controls_completed=sum(row['status'] == 'PASS' for row in report.get('analytic_controls', [])),
            failure=report.get('failure'), elapsed_seconds=report['elapsed_seconds']), allow_nan=False))
        return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
