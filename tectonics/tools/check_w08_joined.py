#!/usr/bin/env python3
"""Bounded frozen W08 joined controls and five explicitly scoped timing routes.

SPDX-License-Identifier: AGPL-3.0-only
New reports only. No full subduction solve, physical recalibration or repinning.
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
from tempfile import TemporaryDirectory
from time import perf_counter


FIXTURE_SHA = '01269a9de5e3c94f7adf04f8aed5e970364af5f8af49889bd733e9f97d4395d4'
CAP = 128 * 1024**2
ROUTES = ('cold_prepare_execute_materialise', 'prepared_latest_reuse',
          'first_checkpoint_write', 'verified_restore', 'interrupted_continuation')
HISTORICAL = {
    'step2': 'tectonics/evidence/w08-shortening-r2.json',
    'step3': 'tectonics/evidence/w08-transform.json',
    'step4': 'tectonics/evidence/w08-subduction-acceptance.json',
    'step5': 'tectonics/evidence/w08-magmatism-timing.json',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def source_inventory(repo):
    package = repo / 'tectonics/src/atlas_tectonics'
    paths = [*sorted(package.glob('*.py')),
             repo / 'tectonics/tests/test_w08_workflow.py',
             repo / 'tectonics/cases/w08_joined_r1.json',
             repo / 'tectonics/cases/w08_regimes.json',
             repo / 'tectonics/docs/W08_REGIMES.md',
             repo / 'tectonics/tools/check_w08_joined.py']
    return {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def historical_evidence(repo):
    rows = []
    for stage, relative in HISTORICAL.items():
        raw = (repo / relative).read_bytes()
        record = json.loads(raw)
        rows.append(dict(stage=stage, path=relative, sha256=hashlib.sha256(raw).hexdigest(),
            recorded_schema=record.get('schema'),
            recorded_status=record.get('status', record.get('run_status')),
            treatment='Historical evidence for its own recorded source bindings; '
                      'not rerun or authenticated as acceptance of the current whole package'))
    return rows


def api_for(repo):
    sys.path[:0] = [str(repo / 'tectonics/src'), str(repo / 'tectonics/tests')]
    import numpy as np
    import scipy
    import shapely
    from threadpoolctl import threadpool_info
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.stokes_execution import _native_lease
    from atlas_tectonics.w08_workflow import PreparedW08Workflow
    from test_w08_workflow import fixture_inputs, make_workflow_fixture, open_store, signature
    return dict(np=np, scipy=scipy, shapely=shapely, WorkBudget=WorkBudget,
        native_lease=_native_lease, threadpool_info=threadpool_info,
        PreparedW08Workflow=PreparedW08Workflow, fixture_inputs=fixture_inputs,
        make_fixture=make_workflow_fixture, open_store=open_store, signature=signature)


def materialise(out, api):
    """Read every exposed numeric product and both geometry sets as exact bytes."""
    result = api['signature'](out)
    fields = dict(components=out.inventory.component_mass_kg,
        enthalpy=out.inventory.enthalpy_j, mass=out.inventory.mass_kg,
        formation=out.inventory.formation_time_s, deformation=out.deformation_gradient)
    for name in ('mass_kg', 'enthalpy_j', 'volume_m3', 'thickness_m', 'component_mass_kg',
                 'load_change_pa', 'surface_addition_m', 'basal_addition_m'):
        fields['regional_' + name] = getattr(out.regional, name)
    result['arrays'] = {name: dict(dtype=a.dtype.str, shape=list(a.shape),
        sha256=hashlib.sha256(a.tobytes(order='C')).hexdigest()) for name, a in fields.items()}
    result['geometry_wkb_sha256'] = {
        role: [hashlib.sha256(g.wkb).hexdigest() for g in polygons]
        for role, polygons in (('current', out.polygons), ('reference', out.reference_polygons))}
    result['inventory_id'] = out.inventory.inventory_id
    result['receipt_sha256'] = digest(out.descriptor())
    result['regional_descriptor_sha256'] = digest(out.regional.descriptor())
    return result


def close_account(actual, expected, multiplier, np, label):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    require(a.shape == b.shape, label + ': shape mismatch')
    scale = math.fsum(abs(float(x)) for x in a.flat) + math.fsum(abs(float(x)) for x in b.flat)
    error = float(np.max(np.abs(a-b))) if a.size else 0.
    limit = multiplier * np.finfo(float).eps * scale
    require(error <= limit, label + ': frozen extensive gate failed')
    return dict(maximum_absolute_error=error, allowed_absolute_error=limit)


def analytic_control(api, frozen, case):
    owner = api['WorkBudget'](CAP)
    inv, region, intervals, _ = api['fixture_inputs'](case=case, budget=owner)
    with api['PreparedW08Workflow'](inv, region, intervals, source_id='joined-fixture',
                                  budget=owner) as plan:
        out = plan.run()
        np = api['np']; mass = out.inventory.mass_kg
        multiplier = frozen['gates']['extensive_roundoff_multiplier']
        checks = {}
        if case == 'A07':
            expected = frozen['A07']
            require(inv.time_s == expected['initial_time_s'] and
                    [i.end_time_s for i in intervals] == [expected['cessation_time_s'], expected['end_time_s']],
                    'A07 fixture chronology differs from frozen control')
            checks['initial_crust_mantle'] = close_account(inv.mass_kg[[1, 6]],
                expected['initial_crust_mantle_kg'], multiplier, np, 'A07 initial crust/mantle')
            checks['initial_melt_reservoir_solid'] = close_account(inv.mass_kg[[7, 8, 9]],
                expected['initial_melt_reservoir_solid_kg'], multiplier, np, 'A07 initial magma')
            checks['retired_destinations'] = close_account(mass[[0, 2, 3]],
                expected['expected_destinations_kg'], multiplier, np, 'A07 destinations')
            retired = math.fsum(float(mass[i]) for i in (0, 2, 3))
            checks['retired_total'] = close_account([retired],
                [expected['expected_retired_kg']], multiplier, np, 'A07 six-kilogram transfer')
            checks['cessation_stocks'] = close_account(mass[[7, 8, 9]],
                expected['expected_melt_reservoir_solid_kg'], multiplier, np, 'A07 cessation')
        else:
            expected = frozen['joined']
            require([i.end_time_s for i in intervals] == expected['end_times_s'] and
                    [i.regime for i in intervals] == expected['regimes'],
                    'joined fixture chronology/regimes differ from frozen control')
            checks['initial_area'] = close_account([math.fsum(g.area_m2 for g in region.polygons)],
                [expected['initial_area_m2']], multiplier, np, 'joined initial area')
            checks['crust_mantle'] = close_account(mass[[1, 6]],
                expected['expected_crust_mantle_kg'], multiplier, np, 'joined crust/mantle')
            checks['magma_stocks'] = close_account(mass[[7, 8, 5, 4]],
                expected['expected_melt_reservoir_intrusion_extrusion_kg'], multiplier, np, 'joined magma')
            target = np.asarray(expected['expected_F'])
            map_error = float(np.max(np.abs(out.deformation_gradient-target)))
            require(map_error <= frozen['gates']['normalised_map_error_max'], 'joined finite-map gate failed')
            checks['finite_map'] = dict(maximum_error_unit_scale=map_error,
                limit=frozen['gates']['normalised_map_error_max'], expected_F=expected['expected_F'])
            area = math.fsum(g.area_m2 for g in out.polygons)
            checks['area'] = close_account([area], [expected['expected_area_m2']], multiplier, np, 'joined area')
        totals = lambda values: [math.fsum(values[:, j]) for j in range(values.shape[1])]
        checks['total_components'] = close_account(totals(out.inventory.component_mass_kg),
            totals(inv.component_mass_kg), multiplier, np, case + ' components')
        checks['signed_enthalpy'] = close_account([math.fsum(out.inventory.enthalpy_j)],
            [math.fsum(inv.enthalpy_j)], multiplier, np, case + ' signed enthalpy')
        result = dict(case=case, status='PASS', checks=checks, execution_id=plan.execution_id,
            signature=materialise(out, api), statistics=plan.statistics())
    result['accounted_peak_bytes'] = owner.peak_reserved_bytes
    return result


def sample(api, route, directory):
    owner = api['WorkBudget'](CAP)
    make, open_store = api['make_fixture'], api['open_store']

    def collect(plan, out):
        return dict(signature=materialise(out, api), statistics=plan.statistics(),
                    execution_id=plan.execution_id)

    def execute():
        if route == ROUTES[0]:
            started = perf_counter()
            with make(budget=owner) as plan:
                preparation = perf_counter()-started
                row = collect(plan, plan.run())
            row.update(seconds=perf_counter()-started, preparation_seconds_included=preparation)
            return row
        if route in (ROUTES[1], ROUTES[2]):
            prepared = perf_counter()
            with make(budget=owner) as plan:
                preparation = perf_counter()-prepared
                started = perf_counter(); out = plan.run()
                warmup = perf_counter()-started
                before = plan.statistics()
                if route == ROUTES[1]:
                    started = perf_counter(); row = collect(plan, plan.run())
                    row['seconds'] = perf_counter()-started
                    require(row['statistics']['latest_hits']-before['latest_hits'] == 1,
                            'prepared route did not reuse its latest output')
                else:
                    opened = perf_counter()
                    with open_store(directory, owner) as store:
                        storage_setup = perf_counter()-opened
                        started = perf_counter()
                        plan._check(); plan._validate(out)
                        arrays, metadata = plan._pack(out)
                        store.put(out.checkpoint_id, arrays, metadata, budget=owner,
                                  publication_check=plan._check)
                        row = collect(plan, out)
                        row['seconds'] = perf_counter()-started
                        require(store.metadata(out.checkpoint_id)['output_id'] == out.output_id,
                                'first write changed its scientific output identity')
                        row['storage'] = store.statistics()
                    row['store_open_seconds_excluded'] = storage_setup
                    row['checkpoint_scope'] = 'One final checkpoint written to an empty store; '
                    row['checkpoint_scope'] += 'not a complete restorable history prefix'
                require(plan.statistics()['computed_intervals'] == before['computed_intervals'],
                        'prepared reuse or checkpoint-only route repeated physics')
                row.update(preparation_seconds_excluded=preparation,
                           initial_execution_seconds_excluded=warmup,
                           measured_computed_intervals=0, measured_restored_outputs=0,
                           measured_latest_hits=plan.statistics()['latest_hits']-before['latest_hits'])
            return row
        # Seed each sample independently, then close the store to avoid reusing its
        # in-process payload attestations when measuring verified restoration.
        seeded = perf_counter()
        prefix = None if route == ROUTES[3] else 2
        with open_store(directory, owner) as store:
            with make(store=store, budget=owner) as plan:
                plan.run(through=prefix)
        seed_seconds = perf_counter()-seeded
        end_to_end = perf_counter()
        with open_store(directory, owner) as store:
            with make(store=store, budget=owner) as plan:
                preparation = perf_counter()-end_to_end
                started = perf_counter()
                out = plan.load(4) if route == ROUTES[3] else plan.run()
                require(out is not None, 'authenticated final checkpoint is absent')
                row = collect(plan, out)
                row['seconds'] = perf_counter()-started
                expected_computed = 0 if route == ROUTES[3] else 2
                require(row['statistics']['computed_intervals'] == expected_computed and
                        row['statistics']['restored_outputs'] == 1,
                        'recovery repeated completed transfers or missed the saved prefix')
                row['storage'] = store.statistics()
        row.update(end_to_end_prepare_recover_materialise_close_seconds=perf_counter()-end_to_end,
                   preparation_seconds_excluded=preparation, seed_seconds_excluded=seed_seconds,
                   seeded_through_index=4 if prefix is None else prefix)
        return row

    row = execute()
    # All route-local plan/output references have gone out of scope here.
    row.update(route=route, resource_accounting=owner.statistics(),
               resource_peak_scope='Complete sample, including any untimed preparation/seeding')
    for counter in ('computed_intervals', 'restored_outputs', 'latest_hits'):
        row.setdefault('measured_' + counter, row['statistics'][counter])
    require(owner.peak_reserved_bytes <= CAP, 'shared work budget exceeded')
    return row


def benchmark(api, report, verify):
    rows = report.setdefault('samples', [])
    matched = report['analytic_controls'][1]['signature']
    report['exact_final_signature'] = matched
    for repeat in range(3):
        order = ROUTES[repeat:] + ROUTES[:repeat]
        for position, route in enumerate(order):
            verify()
            with TemporaryDirectory(prefix='w08-joined-') as directory:
                row = sample(api, route, directory)
            require(row['signature'] == matched, 'scientific final signature differs across timing routes')
            require(row['execution_id'] == report['execution_id'], 'runtime/source identity changed across routes')
            row['signature_sha256'] = digest(row.pop('signature'))
            row.update(repeat=repeat, position=position, output_id=matched['output_id'])
            rows.append(row)
            verify()
    medians = {route: statistics.median(r['seconds'] for r in rows if r['route'] == route)
               for route in ROUTES}
    cold = medians[ROUTES[0]]
    require(cold > 0., 'invalid cold timing')
    report['medians'] = {route: dict(seconds=value, seconds_less_than_cold=cold-value,
        percent_less_than_cold=100.*(cold-value)/cold) for route, value in medians.items()}
    report['restart_including_prepare_close_medians_seconds'] = {
        route: statistics.median(r['end_to_end_prepare_recover_materialise_close_seconds']
                                 for r in rows if r['route'] == route)
        for route in ROUTES[3:]}
    report['all_five_routes_bitwise_matched'] = True


def identical_request_workload(api, report, verify):
    """Compare the same three final requests with setup and close in both routes."""
    result = report['three_identical_final_requests'] = dict(samples=[],
        scope='Three independently prepared complete cold requests versus one prepared fixture '
              'serving three identical final requests. Both include fixture creation, source '
              'checks, execution/reuse, all materialisation and close; no store or checkpoint.')
    expected = report['exact_final_signature']
    for repeat in range(3):
        order = ('cold', 'prepared') if repeat % 2 == 0 else ('prepared', 'cold')
        for position, mode in enumerate(order):
            verify()
            owner = api['WorkBudget'](CAP)
            identities, executions = [], []
            computed = hits = 0
            started = perf_counter()
            if mode == 'cold':
                for _ in range(3):
                    with api['make_fixture'](budget=owner) as plan:
                        identities.append(materialise(plan.run(), api))
                        executions.append(plan.execution_id)
                        computed += plan.statistics()['computed_intervals']
                        hits += plan.statistics()['latest_hits']
                    del plan
            else:
                with api['make_fixture'](budget=owner) as plan:
                    for _ in range(3):
                        identities.append(materialise(plan.run(), api))
                        executions.append(plan.execution_id)
                    computed = plan.statistics()['computed_intervals']
                    hits = plan.statistics()['latest_hits']
                del plan
            elapsed = perf_counter()-started
            require(all(value == expected for value in identities), 'three-request output mismatch')
            require(all(value == report['execution_id'] for value in executions),
                    'three-request execution identity mismatch')
            require((computed, hits) == ((15, 0) if mode == 'cold' else (5, 2)),
                    'three-request workload did not use its declared preparation/reuse route')
            result['samples'].append(dict(mode=mode, repeat=repeat, position=position,
                seconds=elapsed, signature_sha256=[digest(value) for value in identities],
                computed_intervals=computed, latest_hits=hits,
                resource_accounting=owner.statistics()))
            verify()
    medians = {mode: statistics.median(row['seconds'] for row in result['samples'] if row['mode'] == mode)
               for mode in ('cold', 'prepared')}
    difference = medians['cold']-medians['prepared']
    result.update(medians_seconds=medians, saved_seconds=difference,
                  saved_percent=100.*difference/medians['cold'], bitwise_matched=True,
                  interpretation='Setup-inclusive saving for this three-request synthetic workload only; '
                                 'not first-time generation or a whole-generator claim')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    require(Path(__file__).resolve() == repo / 'tectonics/tools/check_w08_joined.py',
            '--repo must own this exact tool')
    # Claim the requested new report before importing scientific dependencies.
    with args.report.open('x', encoding='utf-8') as handle:
        report = dict(schema='atlas.w08-joined-evidence.v1', source_status='WORKING NON-CANON',
            status='INCOMPLETE', scope='Frozen synthetic A07 and five-regime joined controls; '
                'matched endpoint timing only. No full subduction solve, geological calibration, '
                'whole-package physical acceptance or full-world run.',
            limits=dict(accounted_work_bytes=CAP, native_threads=1, accepted_intervals=256,
                        os_rss_measured=False),
            timing_scope={
                ROUTES[0]: 'Fixture creation, plan/source preparation, all five intervals, complete '
                           'materialisation and plan close; interpreter/imports excluded.',
                ROUTES[1]: 'Latest run hit plus materialisation; one-off fixture/plan preparation, '
                           'initial five-interval execution and close excluded and setup times reported.',
                ROUTES[2]: 'Validate and pack a prepared final output, first atomic put and materialisation; '
                           'no physics; plan/initial execution, store open/close and metadata readback excluded.',
                ROUTES[3]: 'Freshly prepared plan.load(4), authenticated prefix and materialisation; '
                           'store reopen/fixture/plan setup excluded and separately reported.',
                ROUTES[4]: 'Fresh plan.run after saved prefix 0..2: authenticated restore, only intervals '
                           '3 and 4, their checkpoint writes and materialisation; setup separately reported.',
                'comparison': 'Signed savings compare different explicitly scoped operations with cold '
                              'complete execution. Negative values retain slower paths; these are not '
                              'universal end-to-end or whole-generator speedups.',
                'restart_end_to_end': 'Also measures store reopen + new fixture/plan + recover/materialise '
                                      '+ plan/store close; previous completed prefix creation excluded.'})
        started = perf_counter()
        try:
            initial_sources = source_inventory(repo)
            report['source_sha256'] = initial_sources
            fixture_path = 'tectonics/cases/w08_joined_r1.json'
            require(initial_sources[fixture_path] == FIXTURE_SHA, 'frozen joined fixture changed')
            frozen = json.loads((repo / fixture_path).read_bytes())
            require(tuple(frozen['timing']['routes']) == ROUTES and frozen['timing']['repeats'] == 3,
                    'frozen timing contract differs from tool')
            evidence = historical_evidence(repo)
            report['historical_stage_evidence'] = evidence

            def verify():
                require(source_inventory(repo) == initial_sources, 'source/fixture/test/tool changed; no repinning')
                require(historical_evidence(repo) == evidence, 'historical evidence changed during measurement')

            api = api_for(repo)
            report['runtime'] = dict(platform=platform.platform(), python=platform.python_version(),
                numpy=api['np'].__version__, scipy=api['scipy'].__version__,
                shapely=api['shapely'].__version__)
            with api['native_lease']():
                report['runtime']['native_pools'] = [dict(
                    {k:v for k,v in p.items() if k!='filepath'},
                    library_filename=Path(p.get('filepath','')).name) for p in api['threadpool_info']()]
                require(all(p['num_threads'] == 1 for p in report['runtime']['native_pools']),
                        'native numerical thread count differs from frozen policy')
                report['analytic_controls'] = []
                for case in ('A07', 'joined'):
                    verify()
                    report['analytic_controls'].append(analytic_control(api, frozen, case))
                report['execution_id'] = report['analytic_controls'][0]['execution_id']
                require(all(r['execution_id'] == report['execution_id'] for r in report['analytic_controls']),
                        'analytic controls used different execution bindings')
                benchmark(api, report, verify)
                identical_request_workload(api, report, verify)
                require(all(p['num_threads'] == 1 for p in api['threadpool_info']()),
                        'native numerical thread count changed during measurement')
            verify()
            report['maximum_accounted_peak_bytes'] = max(
                [r['accounted_peak_bytes'] for r in report['analytic_controls']] +
                [r['resource_accounting']['peak_reserved_bytes'] for r in report['samples']] +
                [r['resource_accounting']['peak_reserved_bytes']
                 for r in report['three_identical_final_requests']['samples']])
            report['status'] = 'PASS'
        except BaseException as exc:
            report['status'] = 'FAIL'
            report['failure'] = dict(type=type(exc).__name__, message=str(exc))
        finally:
            report['elapsed_seconds'] = perf_counter()-started
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write('\n')
        print(json.dumps(dict(status=report['status'], report=str(args.report),
            completed_samples=len(report.get('samples', [])), failure=report.get('failure'),
            medians=report.get('medians')), allow_nan=False))
        return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
