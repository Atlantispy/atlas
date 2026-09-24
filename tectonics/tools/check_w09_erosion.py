#!/usr/bin/env python3
"""Frozen W09 E1-E3/H1-H2 controls and bounded complete-output reuse timing.

Creates a new requested report; never replaces fixtures or existing evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter
import traceback


FIXTURE_PATH = 'tectonics/cases/w09_surface_processes_r1.json'
FIXTURE_SHA = 'ccd8cb4da78c903e1eddbc5021522233e2dd787cb0da205df15091a4296c67a2'
CAP = 128 * 1024**2
CONTROL_IDS = ('W09-E1-fixed-receiver-incision', 'W09-E2-cover-and-thresholds',
               'W09-E3-finite-source-event', 'W09-H1-nonlinear-mobile-soil-flux',
               'W09-H2-linear-limit-profile')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def source_inventory(repo):
    paths = [*sorted((repo / 'tectonics/src/atlas_tectonics').glob('*.py')),
             repo / FIXTURE_PATH, repo / 'tectonics/docs/W09_SURFACE_PROCESSES.md',
             repo / 'tectonics/tests/test_w09_erosion.py',
             repo / 'tectonics/tests/test_w09_hillslope.py', Path(__file__).resolve()]
    return {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def api_for(repo):
    sys.path.insert(0, str(repo / 'tectonics/src'))
    import numpy as np
    import scipy
    from threadpoolctl import threadpool_info, threadpool_limits
    from atlas_tectonics._validation import TectonicsError
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.w09_erosion import (PreparedErosion, ErosionTag,
        ErosionExhaustionError, cover_rates)
    from atlas_tectonics.w09_hillslope import PreparedHillslope, SoilTag, roering_flux
    return dict(np=np, scipy=scipy, threadpool_info=threadpool_info,
        threadpool_limits=threadpool_limits, TectonicsError=TectonicsError,
        WorkBudget=WorkBudget, PreparedErosion=PreparedErosion, ErosionTag=ErosionTag,
        ErosionExhaustionError=ErosionExhaustionError, cover_rates=cover_rates,
        PreparedHillslope=PreparedHillslope, SoilTag=SoilTag, roering_flux=roering_flux)


def tag(api, kind, name='A', rho=2500., heat=-100., origin=None):
    return api[kind](name, rho, heat, -1000., origin or 'synthetic-origin-'+name,
                     'synthetic-signed-reference')


def erosion_plan(api, owner, *, mass_height=4., kr=1., tags=None):
    return api['PreparedErosion']([1., 0.], [1, -1], [1., 1.], [0., 0.],
        tags or [tag(api, 'ErosionTag')], rock_erodibility=[[kr], [0.]],
        sediment_erodibility=0., porosity=0., frame_id='synthetic-planar-SI',
        datum_id='synthetic-z-up', source_id='frozen-E1-E3', budget=owner)


def soil_plan(api, owner, areas, faces, distances, widths, **kw):
    return api['PreparedHillslope'](areas, faces, distances, widths,
        diffusivity_m2_s=kw.pop('diffusivity_m2_s', .03),
        critical_slope=kw.pop('critical_slope', 1.), frame_id='synthetic-orthogonal-SI',
        datum_id='synthetic-z-up', source_id='frozen-H1-H2', budget=owner, **kw)


def array_record(array):
    return dict(values=array.tolist(), shape=list(array.shape), dtype=array.dtype.str,
                bytes_sha256=hashlib.sha256(array.tobytes(order='C')).hexdigest())


def erosion_output(plan, state):
    return dict(state_id=state.state_id, descriptor=state.descriptor(),
        tags=[asdict(t) for t in plan.tags],
        arrays={name: array_record(value) for name, value in state.arrays().items()},
        surface_m=array_record(plan.heights(state)),
        released_enthalpy_J=array_record(plan.released_enthalpy_J(state)))


def soil_output(plan, result):
    state = result.state
    return dict(state_id=state.state_id, descriptor=state.descriptor(),
        arrays={name: array_record(getattr(state, name)) for name in
                ('base_m', 'mass_kg', 'porosity', 'initial_mass_kg', 'exported_mass_kg')},
        surface_m=array_record(plan.heights(state)), enthalpy_J=array_record(state.enthalpy_J),
        state_exported_enthalpy_J=array_record(state.exported_enthalpy_J),
        face_tag_mass_kg=array_record(result.face_tag_mass_kg),
        exported_mass_kg=array_record(result.exported_mass_kg),
        exported_enthalpy_J=array_record(result.exported_enthalpy_J),
        depletion_events=[asdict(event) for event in result.depletion_events],
        requested_end_time_s=result.requested_end_time_s, status=result.status)


def check_value(api, checks, name, actual, expected, gates):
    np = api['np']
    got, want = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    require(got.shape == want.shape, name+': reference shape mismatch')
    require(bool(np.isfinite(got).all()), name+': nonfinite result')
    errors = np.abs(got-want)
    limits = gates['analytic_absolute_tolerance_in_output_SI_unit'] + \
             gates['analytic_relative_tolerance']*np.abs(want)
    checks[name] = dict(actual=got.tolist(), expected=want.tolist(),
        maximum_absolute_error=float(np.max(errors, initial=0.)), passed=bool(np.all(errors <= limits)))
    require(checks[name]['passed'], name+': frozen numerical control failed')


def balance(api, checks, name, state, erosion=False, tags=None):
    np = api['np']
    residuals, limits = [], []
    if erosion:
        for i in range(state.soil_mass_kg.shape[0]):
            for k, t in enumerate(tags):
                values = [-state.initial_mass_kg[i, k], *state.rock_mass_kg[i, :, k],
                          state.soil_mass_kg[i, k], state.released_rock_kg[i, k],
                          state.released_soil_kg[i, k]]
                for factor in (1., t.specific_enthalpy_J_kg):
                    terms = [float(v)*factor for v in values]
                    residuals.append(math.fsum(terms))
                    limits.append(128*np.finfo(float).eps*math.fsum(abs(v) for v in terms))
    else:
        for k, t in enumerate(state.tags):
            for factor in (1., t.specific_enthalpy_J_kg):
                terms = [float(state.initial_mass_kg[k])*factor,
                         -float(state.exported_mass_kg[k])*factor,
                         *(-float(v)*factor for v in state.mass_kg[:, k])]
                residuals.append(math.fsum(terms))
                limits.append(128*np.finfo(float).eps*math.fsum(abs(v) for v in terms))
    checks[name] = dict(mass_then_signed_enthalpy_per_tag_residuals=residuals,
                        absolute_limits=limits,
                        passed=all(abs(r) <= limit for r, limit in zip(residuals, limits)))
    require(checks[name]['passed'], name+': extensive tagged balance failed')


def refinement(checks, name, errors, gates):
    reductions = [a/b if b > 0 else None for a, b in zip(errors, errors[1:])]
    passed = (errors[-1] <= gates['continuum_finest_relative_L2_error_max'] and
              all(value is not None and value >= gates['refinement_error_reduction_min']
                  for value in reductions))
    checks[name] = dict(relative_errors=errors, successive_error_reductions=reductions,
                        finest_error_limit=gates['continuum_finest_relative_L2_error_max'],
                        minimum_reduction=gates['refinement_error_reduction_min'], passed=passed)
    require(passed, name+': frozen refinement gate failed')


def h2_case(api, owner, reference, n):
    np = api['np']
    length = reference['domain_length_m']
    dx = length/n
    edges = np.linspace(0., length, n+1)
    means = (np.cos(math.pi*edges[:-1]/length)-np.cos(math.pi*edges[1:]/length))/(math.pi/n)
    faces = [[i, i+1] for i in range(n-1)]+[[0, -1], [n-1, -1]]
    plan = soil_plan(api, owner, np.full(n, dx), faces, [dx]*(n-1)+[dx/2]*2,
        np.ones(n+1), diffusivity_m2_s=reference['diffusivity_m2_s'], critical_slope=1e6,
        boundary_elevations_m=np.full(n+1, 10.))
    return plan, means


def analytic_controls(api, frozen, report, verify, common):
    np = api['np']
    controls = {row['id']: row for row in frozen['controls']}
    gates = frozen['gates']
    rows = report['analytic_controls'] = []
    for control_id in CONTROL_IDS:
        verify()
        reference = controls[control_id]
        owner = api['WorkBudget'](CAP, parent=common)
        row = dict(control_id=control_id, status='INCOMPLETE', checks={}, snapshots=[])
        rows.append(row)
        checks = row['checks']

        def check(name, actual, expected):
            check_value(api, checks, name, actual, expected, gates)

        if control_id == CONTROL_IDS[0]:
            errors = []
            with erosion_plan(api, owner, kr=reference['Kr_Q_to_m_over_link_length_s_inv']) as plan:
                initial = plan.initialise([[[reference['initial_height_m']*2500.]], [[0.]]])
                for parts in (1, *frozen['resource_plan']['continuum_interval_partitions']):
                    state = plan.advance(initial, reference['duration_s'], discharge_m3_s=[1., 0.],
                        forcing_id=f'E1-partitions-{parts}', partitions=parts)
                    height = float(plan.heights(state)[0])
                    expected = reference['initial_height_m']/(1+reference['duration_s']/parts)**parts
                    check(f'discrete_{parts}_height_m', height, expected)
                    check(f'released_{parts}_mass_kg', float(state.released_rock_kg.sum()),
                          (reference['initial_height_m']-expected)*2500.)
                    balance(api, checks, f'account_{parts}', state, True, plan.tags)
                    row['snapshots'].append(dict(partitions=parts, **erosion_output(plan, state)))
                    if parts == 1:
                        check('single_backward_Euler_height_m', height, reference['expected_single_backward_Euler_height_m'])
                    else:
                        exact = reference['initial_height_m']*math.exp(-reference['duration_s'])
                        errors.append(abs(height-exact)/abs(exact))
            refinement(checks, 'time_refinement_to_continuum', errors, gates)
        elif control_id == CONTROL_IDS[1]:
            args = [reference[key] for key in ('H_m', 'Hstar_m', 'omega_rock_m_s',
                'omega_sediment_m_s', 'critical_rock_m_s', 'critical_sediment_m_s')]
            check('covered_rates_m_s', api['cover_rates'](*args),
                  [reference['expected_rock_rate_m_s'], reference['expected_sediment_rate_m_s']])
            check('bare_sediment_rate_m_s', api['cover_rates'](0., *args[1:])[1],
                  reference['bare_soil_expected_sediment_rate_m_s'])
            check('dry_rates_m_s', api['cover_rates'](*args, wet=False), [0., 0.])
            check('threshold_equality_rates_m_s', api['cover_rates'](args[0], args[1],
                  args[4], args[5], args[4], args[5]), [0., 0.])
        elif control_id == CONTROL_IDS[2]:
            t = tag(api, 'ErosionTag', heat=reference['specific_enthalpy_J_kg'], origin=reference['origin_id'])
            with erosion_plan(api, owner, tags=[t]) as plan:
                initial = plan.initialise([[[reference['source_mass_kg']]], [[0.]]])
                try:
                    plan.prescribed_release(initial, 0, reference['prescribed_transfer_rate_kg_s'],
                        reference['requested_duration_s'], source_id='frozen-E3')
                except api['ErosionExhaustionError'] as exc:
                    state = exc.state
                else:
                    raise ValueError('E3 unspecified continuation was not refused')
                check('exhaustion_time_s', state.time_s, reference['expected_exhaustion_time_s'])
                check('transferred_mass_kg', state.released_rock_kg.sum(), reference['expected_transferred_mass_kg'])
                check('transferred_enthalpy_J', plan.released_enthalpy_J(state).sum(), reference['expected_transferred_enthalpy_J'])
                check('final_source_mass_kg', state.rock_mass_kg.sum(), reference['expected_final_source_mass_kg'])
                require(plan.tags[0].origin_id == reference['origin_id'], 'E3 donor origin changed')
                try:
                    plan.prescribed_release(state, 0, reference['prescribed_transfer_rate_kg_s'],
                        1., source_id='frozen-E3-exhausted-continuation')
                except api['ErosionExhaustionError'] as exc:
                    check('continuation_cannot_pay_twice', exc.state.released_rock_kg, state.released_rock_kg)
                else:
                    raise ValueError('E3 exhausted continuation was not refused')
                balance(api, checks, 'account', state, True, plan.tags)
                row['snapshots'].append(erosion_output(plan, state))
        elif control_id == CONTROL_IDS[3]:
            q = api['roering_flux'](reference['slope'], reference['diffusivity_m2_s'], reference['critical_slope'])
            check('bulk_flux_m2_s', q, reference['expected_downslope_bulk_flux_m2_s'])
            check('solid_flux_m2_s', q*(1-reference['donor_porosity']), reference['expected_downslope_solid_flux_m2_s'])
            check('zero_slope', api['roering_flux'](0., .03, 1.), 0.)
            check('empty_mobile_donor', api['roering_flux'](40., .03, 1., mobile=False), 0.)
            try:
                api['roering_flux'](1., .03, 1.)
            except api['TectonicsError']:
                checks['critical_slope_refuses'] = dict(passed=True)
            else:
                raise ValueError('H1 critical mobile slope did not refuse')
            with soil_plan(api, owner, [1., 1.], [[0, 1]], [1.], [1.]) as plan:
                bare = plan.initial_state([40., 0.], [[0.], [0.]], [tag(api, 'SoilTag')])
                result = plan.advance(bare, 1.)
                check('bare_cliff_not_clipped', plan.heights(result.state), [40., 0.])
                check('empty_face_transfers', result.face_tag_mass_kg, [[0.]])
                covered = plan.initial_state([.5, 0.], [[1500.], [1500.]], [tag(api, 'SoilTag')])
                check('prepared_physical_face_flux', plan.face_bulk_flux_m2_s(covered), [q])
            with soil_plan(api, owner, [1.], [[0, -1]], [1.], [1.], boundary_elevations_m=[0.]) as plan:
                initial = plan.initial_state([.5], [[3.]], [tag(api, 'SoilTag')])
                result = plan.advance(initial, 1.)
                require(result.status == 'DEPLETED', 'H1 finite donor event missing')
                check('finite_donor_event_time_s', result.state.time_s, .1)
                check('finite_donor_remaining_mass_kg', result.state.mass_kg, [[0.]])
                check('finite_donor_export_mass_kg', result.exported_mass_kg, [3.])
                check('finite_donor_export_enthalpy_J', result.exported_enthalpy_J, [-300.])
                balance(api, checks, 'finite_donor_account', result.state)
                row['snapshots'].append(soil_output(plan, result))
        else:
            spatial, temporal = [], []
            row['reference_method'] = ('Analytic cell means of sin(pi*x/L); spatial comparison to '
                'the continuum at 256 time partitions. Separate 16/32/64 time refinement at '
                '32 cells compares the exact finite-volume eigenmode to isolate time error. '
                'Sc=1e6 makes nonlinear-law correction negligible for this linear-limit control.')
            for n in frozen['resource_plan']['spatial_cells_1d']:
                plan, means = h2_case(api, owner, reference, n)
                with plan:
                    initial = plan.initial_state(np.zeros(n), ((10.+.01*means)*.6*2500./n)[:, None],
                                                [tag(api, 'SoilTag')])
                    result = plan.advance(initial, reference['duration_s'], partitions=256)
                    exact = reference['final_amplitude_m']*means
                    error = float(np.linalg.norm(plan.heights(result.state)-10.-exact)/np.linalg.norm(exact))
                    spatial.append(error)
                    balance(api, checks, f'spatial_{n}_account', result.state)
                    require(result.exported_mass_kg[0] > 0., 'H2 missing open-face export')
                    row['snapshots'].append(dict(kind='spatial', cells=n, partitions=256,
                                                **soil_output(plan, result)))
            plan, means = h2_case(api, owner, reference, 32)
            with plan:
                initial = plan.initial_state(np.zeros(32), ((10.+.01*means)*.6*2500./32)[:, None],
                                            [tag(api, 'SoilTag')])
                eigenvalue = 4*32**2*math.sin(math.pi/(2*32))**2
                exact = .01*math.exp(-reference['diffusivity_m2_s']*eigenvalue*reference['duration_s'])*means
                for parts in frozen['resource_plan']['continuum_interval_partitions']:
                    result = plan.advance(initial, reference['duration_s'], partitions=parts)
                    evolved = plan.heights(result.state)-10.
                    temporal.append(float(np.linalg.norm(evolved-exact)/np.linalg.norm(exact)))
                    continuum = reference['final_amplitude_m']*means
                    require(np.linalg.norm(evolved-continuum)/np.linalg.norm(continuum) <=
                            gates['continuum_finest_relative_L2_error_max'], 'H2 continuum bound failed')
                    balance(api, checks, f'temporal_{parts}_account', result.state)
                    row['snapshots'].append(dict(kind='temporal', cells=32, partitions=parts,
                                                **soil_output(plan, result)))
            refinement(checks, 'spatial_refinement', spatial, gates)
            refinement(checks, 'time_refinement_semidiscrete', temporal, gates)
        require(owner.reserved_bytes == 0, 'control did not release prepared work')
        row.update(status='PASS', resource_accounting=owner.statistics())
        verify()
    require(tuple(row['control_id'] for row in rows) == CONTROL_IDS, 'frozen control coverage differs')


def timing_sample(api, common, mode, kind):
    np = api['np']
    owner = api['WorkBudget'](CAP, parent=common)
    outputs, counters = [], dict(preparations=0, computed_intervals=0, latest_hits=0)
    started = perf_counter()
    if kind == 'channel':
        n, area, phi = 256, 100., .4
        areas = np.full(n, area); areas[-1] = 0.
        receivers = [*range(1, n), -1]
        basal = .1*np.arange(n-1, -1, -1)-10.2; basal[-1] = 0.
        tags = [tag(api, 'ErosionTag'), tag(api, 'ErosionTag', 'B', 3000., 200.)]
        rock = np.zeros((n, 2, 2)); rock[:-1, 0, 0] = 2*area*2500.; rock[:-1, 1, 1] = 8*area*3000.
        soil = np.zeros((n, 2)); soil[:-1] = [.2*area*(1-phi)*.7*2500., .2*area*(1-phi)*.3*3000.]
        laws = np.tile([.001, .0005], (n, 1))

        def prepare():
            return api['PreparedErosion'](areas, receivers, np.full(n, 10.), basal, tags,
                rock_erodibility=laws, sediment_erodibility=.002, porosity=phi,
                frame_id='synthetic-strip-SI', datum_id='synthetic-z-up',
                source_id='timing-covered-finite-channel-256', budget=owner)

        def request(plan, index):
            initial = plan.initialise(rock, soil)
            state = plan.advance(initial, 10., discharge_m3_s=(index+1)*np.arange(1., n+1.),
                                 forcing_id=f'changed-channel-discharge-{index}')
            checks = {}; balance(api, checks, 'timing_account', state, True, plan.tags)
            require(float(state.released_rock_kg.sum()) > 0. and float(state.released_soil_kg.sum()) > 0.,
                    'covered channel workload omitted rock or soil erosion')
            return erosion_output(plan, state)
    else:
        n, dx = 32, 1.
        areas = np.full(n, dx)
        faces = [[i, i+1] for i in range(n-1)]
        x = np.arange(n, dtype=float)+.5
        tags = [tag(api, 'SoilTag'), tag(api, 'SoilTag', 'B', 3000., 200.)]

        def prepare():
            return soil_plan(api, owner, areas, faces, np.full(n-1, dx), np.ones(n-1))

        def request(plan, index):
            heights = 2.+(.1+.05*index)*np.cos(math.pi*x/n)
            solids = heights*areas*.6
            mass = np.column_stack((solids*.7*2500., solids*.3*3000.))
            initial = plan.initial_state(np.zeros(n), mass, tags)
            result = plan.advance(initial, 10., partitions=4)
            require(result.status == 'COMPLETE', 'closed-strip timing unexpectedly depleted')
            checks = {}; balance(api, checks, 'timing_account', result.state)
            require(bool(np.any(result.face_tag_mass_kg)), 'closed-strip timing omitted soil motion')
            require(bool(np.all(result.exported_mass_kg == 0.)), 'closed-strip timing exported mass')
            return soil_output(plan, result)

    def collect(plan):
        stats = plan.statistics()
        for key in counters:
            counters[key] += stats[key]

    if mode == 'cold':
        for index in range(3):
            with prepare() as plan:
                outputs.append(request(plan, index))
                collect(plan)
    else:
        with prepare() as plan:
            for index in range(3):
                outputs.append(request(plan, index))
            collect(plan)
    elapsed = perf_counter()-started
    require(counters['preparations'] == (3 if mode == 'cold' else 1), 'wrong preparation route')
    require(counters['latest_hits'] == 0, 'timing used complete-result cache')
    intervals = sum(out['descriptor']['accepted_intervals'] for out in outputs)
    require(counters['computed_intervals'] == intervals and 3 <= intervals <= 256,
            'timing omitted/repeated intervals or exceeded batch bound')
    require(owner.reserved_bytes == 0, 'timing did not close prepared resources')
    return dict(mode=mode, seconds=elapsed, outputs=outputs, counters=counters,
                resource_accounting=owner.statistics())


def benchmark(api, report, verify, common):
    for kind in ('channel', 'hillslope'):
        result = report['three_changed_'+kind+'_requests'] = dict(samples=[], request_count=3,
            cells=256 if kind == 'channel' else 32,
            scope='Three fresh initial states and changed requests. Cold prepares for every request; '
                  'prepared constructs once. Fixture creation, constructor/API source validation, '
                  'initialisation, full evolution, complete arrays/metadata materialisation, '
                  'tagged-account checks, statistics and close are included. Imports/interpreter '
                  'and outer source inventory are excluded. No complete-result reuse.',
            fixture=('256-node strip, 255 positive-area cells, 10 m receiver distances, 100 m2 '
                     'areas, 0.2 m wet cover, identified 2 m/8 m rock layers, two densities and '
                     'signed heat tags; 10 s and three discharge multipliers.' if kind == 'channel'
                     else 'Closed orthogonal 32-cell strip: 1 m length and width per cell, '
                     'two soil cohorts, three positive cosine-profile amplitudes; 10 s, four partitions.'))
        expected = None
        for repeat in range(3):
            order = ('cold', 'prepared') if repeat % 2 == 0 else ('prepared', 'cold')
            for position, mode in enumerate(order):
                verify()
                row = timing_sample(api, common, mode, kind)
                outputs = row.pop('outputs')
                if expected is None:
                    expected = outputs
                    result['scientific_outputs'] = outputs
                require(outputs == expected, kind+': complete cold/prepared arrays or state identities differ')
                row.update(repeat=repeat, position=position,
                           scientific_signatures_sha256=[digest(value) for value in outputs])
                result['samples'].append(row)
                verify()
        medians = {mode: statistics.median(row['seconds'] for row in result['samples']
                                           if row['mode'] == mode) for mode in ('cold', 'prepared')}
        difference = medians['cold']-medians['prepared']
        result.update(medians_seconds=medians, cold_minus_prepared_seconds=difference,
            cold_minus_prepared_percent=100*difference/medians['cold'],
            scientific_outputs_bitwise_equal=True,
            interpretation=('Prepared reuse was faster on this bounded workload only.' if difference > 0
                            else 'No speed saving measured: prepared reuse was slower or equal.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    require(Path(__file__).resolve() == repo/'tectonics/tools/check_w09_erosion.py',
            '--repo must own this exact checker')
    with args.report.open('x', encoding='utf-8') as handle:
        report = dict(schema='atlas.w09-erosion-evidence.v1', source_status='WORKING NON-CANON',
            status='INCOMPLETE', scope='Frozen synthetic E1-E3 and H1-H2 controls and bounded '
            'complete-output preparation timing. No tagged river transport/deposition, changing '
            'drainage, coupled structural response, empirical geology or whole-world acceptance.',
            limits=dict(accounted_work_bytes=CAP, native_threads=1, accepted_intervals=256,
                        channel_timing_nodes=256, hillslope_timing_cells=32, os_rss_measured=False))
        started = perf_counter()
        try:
            source_hashes = source_inventory(repo)
            report['source_sha256'] = source_hashes
            require(source_hashes[FIXTURE_PATH] == FIXTURE_SHA, 'frozen register changed; no repinning')
            frozen = json.loads((repo/FIXTURE_PATH).read_bytes())
            require(source_hashes['tectonics/'+frozen['frozen_design']['path']] ==
                    frozen['frozen_design']['sha256'], 'frozen design changed')
            require(frozen['resource_plan']['work_budget_bytes'] == CAP and
                    frozen['resource_plan']['native_numerical_threads'] == 1 and
                    frozen['resource_plan']['max_cumulative_accepted_subintervals'] == 256,
                    'checker resource bounds differ from frozen design')

            def verify():
                require(source_inventory(repo) == source_hashes,
                        'source, fixture, tests or checker changed during execution; no repinning')

            api = api_for(repo)
            common = api['WorkBudget'](CAP)
            report['runtime'] = dict(python=platform.python_version(), platform=platform.platform(),
                numpy=api['np'].__version__, scipy=api['scipy'].__version__)
            # Do not acquire _native_lease here: the hillslope solver owns it.
            with api['threadpool_limits'](limits=1):
                pools = api['threadpool_info']()
                report['runtime']['native_pools'] = [
                    {key: value for key, value in pool.items() if key != 'filepath'} for pool in pools]
                require(all(pool['num_threads'] == 1 for pool in pools), 'native thread count exceeds one')
                with common.reserve(16*1024**2, category='w09-evidence-fixtures-and-full-outputs'):
                    analytic_controls(api, frozen, report, verify, common)
                    benchmark(api, report, verify, common)
                require(all(pool['num_threads'] == 1 for pool in api['threadpool_info']()),
                        'native thread count changed during execution')
            verify()
            report['resource_accounting'] = common.statistics()
            require(common.reserved_bytes == 0, 'combined evidence budget not released')
            report['maximum_accounted_peak_bytes'] = common.peak_reserved_bytes
            report['status'] = 'PASS'
        except BaseException as exc:
            report['status'] = 'FAIL'
            report['failure'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
        finally:
            try:
                report['source_sha256_after'] = source_inventory(repo)
            except BaseException as exc:
                report['source_after_failure'] = dict(type=type(exc).__name__, message=str(exc),
                                                     traceback=traceback.format_exc())
                report['status'] = 'FAIL'
            report['elapsed_seconds'] = perf_counter()-started
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write('\n')
        print(json.dumps(dict(status=report['status'], report=str(args.report),
            controls_completed=sum(row['status'] == 'PASS' for row in report.get('analytic_controls', [])),
            failure=report.get('failure'), elapsed_seconds=report['elapsed_seconds']), allow_nan=False))
        return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
