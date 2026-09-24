#!/usr/bin/env python3
"""Bounded source-bound underthrust controls and cold/prepared reuse timings.

Timing includes preparation, live execution checks, evaluation, complete public
output materialisation/hashing and close. Imports and immutable fixture building
are excluded. No geological calibration, dynamics or PDE comparison is claimed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
import scipy
import shapely

from atlas_tectonics.geometry import PlanarGeometry, geometry_runtime
from atlas_tectonics.materials import MaterialCohort
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import _source_bytes
from atlas_tectonics.stokes_execution import _native_lease
from atlas_tectonics.underthrust import (
    PreparedUnderthrust, UnderthrustInterface, UnderthrustInterval,
    UnderthrustParcel,
)


BUDGET_BYTES = 128 * 1024**2
FRAME = 'underthrust-benchmark-x-z-up'
OUTPUT_TIMES_S = (2.5e12, 7.5e12, 1.e13)
ARRAY_FIELDS = ('volume_m3', 'mass_kg', 'enthalpy_j', 'boundary_work_j',
                'gravitational_change_j', 'displacement_m')
GEOMETRY_ERROR = 1.e-10
ACCOUNT_ERROR = 128. * np.finfo(np.float64).eps
ENERGY_ERROR = 1.e-10


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def bounded_error(actual, expected, tolerance, label):
    """A nonzero physical reference sets the normalisation; zero means zero."""
    actual, expected = float(actual), float(expected)
    require(math.isfinite(actual), label + ': nonfinite result')
    error = abs(actual - expected)
    scale = abs(expected)
    require(error <= tolerance * scale, label + ': error exceeds declared bound')
    return error / scale if scale else 0.


def rectangle(x0, x1, z0, z1):
    return PlanarGeometry.polygon(
        ((x0, z0), (x1, z0), (x1, z1), (x0, z1)), frame_id=FRAME)


def make_fixture():
    fault = UnderthrustInterface(((0., 0.), (20000., -10000.), (40000., -10000.)),
        interface_id='synthetic-descending-ramp-flat', frame_id=FRAME,
        datum_id='synthetic-z-zero', source_id='benchmark-supplied-interface',
        detachment_depth_m=10000., section_azimuth_deg=90.)
    cohorts = (MaterialCohort('incoming-lower', 'lower-crust', 'finite-incoming', -1.),
               MaterialCohort('overriding-upper', 'upper-crust', 'finite-overriding', None))
    edges = np.linspace(-10000., 10000., 33)
    material = []
    for role, cohort, bottom, top, density, heat in (
        ('footwall', cohorts[0], -15000., -14000., 2700., -1000.),
        ('hangingwall', cohorts[1], 2000., 3000., 2800., 2000.),
    ):
        for i, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
            material.append(UnderthrustParcel(
                f'{role}-{i:02d}', f'{role}-block', role, cohort,
                rectangle(float(left), float(right), bottom, top), density,
                heat, 'synthetic-relative-specific-enthalpy'))
    receiver_edges = np.linspace(-30000., 100000., 9)
    receivers = tuple((f'receiver-{i:02d}', rectangle(float(left), float(right),
                       -60000., 15000.))
                      for i, (left, right) in enumerate(zip(receiver_edges[:-1], receiver_edges[1:])))
    histories = (UnderthrustInterval(1.e13, 1.e-9, 0., 1.e12, 0.,
                 'synthetic-horizontal-history', 'supplied-generalised-forces'),)
    options = dict(time_s=0., epoch_id='synthetic-seconds', width_m=1000.,
                   gravity_m_s2=9.81, receiver_regions=receivers,
                   exterior_id='retained-exterior', source_id='bounded-underthrust-benchmark',
                   host_space_source_id='complete-finite-two-block-inventory')
    return fault, tuple(material), histories, options


def fixture_record(fixture):
    fault, material, histories, options = fixture
    return dict(interface=fault.descriptor(),
        parcels=[dict(p.descriptor(), polygon_wkb_hex=p.polygon.wkb.hex()) for p in material],
        histories=[asdict(h) for h in histories],
        options={key: value for key, value in options.items() if key != 'receiver_regions'},
        receivers=[dict(destination_id=name, geometry=polygon.descriptor(),
                        polygon_wkb_hex=polygon.wkb.hex())
                   for name, polygon in options['receiver_regions']],
        output_times_s=OUTPUT_TIMES_S)


def prepare(fixture, budget):
    fault, material, histories, options = fixture
    return PreparedUnderthrust(fault, material, histories, budget=budget, **options)


def complete_signature(state, budget):
    """Materialise every public scientific output, retaining only its digest."""
    with budget.reserve(4 * state.nbytes + 65536, category='benchmark-materialisation'):
        digest = hashlib.sha256()

        def append(raw):
            digest.update(len(raw).to_bytes(8, 'big'))
            digest.update(raw)

        append(json_bytes(dict(time_s=state.time_s, plan_id=state.plan_id,
            state_id=state.state_id, parcel_ids=state.parcel_ids,
            destination_ids=state.destination_ids, enthalpy_known=state.enthalpy_known,
            descriptor=state.descriptor())))
        for polygon in state.polygons:
            append(json_bytes(polygon.descriptor()))
            append(polygon.wkb)
        for name in ARRAY_FIELDS:
            values = getattr(state, name)
            append(json_bytes(dict(name=name, shape=values.shape, dtype=values.dtype.str)))
            append(values.tobytes(order='C'))
        return dict(time_s=state.time_s, state_id=state.state_id,
                    plan_id=state.plan_id, complete_output_sha256=digest.hexdigest())


def inventory_controls(state):
    """Independent rectangle totals and an integrated ramp-height oracle."""
    area_each = 625. * 1000.
    volume_each = area_each * 1000.
    area_error = max(bounded_error(p.area_m2, area_each, GEOMETRY_ERROR,
                     'parcel section area') for p in state.polygons)
    volume_error = max(bounded_error(math.fsum(row), volume_each, ACCOUNT_ERROR,
                       'parcel volume') for row in state.volume_m3)
    expected_masses = (5.4e13, 5.6e13)
    expected_heat = (-5.4e16, 1.12e17)
    measured_mass, measured_heat = [], []
    account_errors = []
    for selection, mass, heat in zip((slice(0, 32), slice(32, 64)), expected_masses, expected_heat):
        current_mass = math.fsum(state.mass_kg[selection].ravel())
        current_heat = math.fsum(state.enthalpy_j[selection].ravel())
        measured_mass.append(current_mass); measured_heat.append(current_heat)
        account_errors.append(bounded_error(current_mass, mass, ACCOUNT_ERROR, 'block mass'))
        account_errors.append(bounded_error(current_heat, heat, ACCOUNT_ERROR, 'signed block heat'))
    require(state.enthalpy_known == (True,) * 64, 'known heat mask changed')
    require(not np.any(state.volume_m3[:, -1]), 'full fixture escaped its receiver strips')
    shift = state.time_s * 1.e-9
    bounded_error(state.displacement_m[0], shift, ACCOUNT_ERROR, 'horizontal displacement')
    bounded_error(state.displacement_m[1], 0., ACCOUNT_ERROR, 'stationary overriding block')
    # For a=10000 and 0<=s<=a, the ramp is h=-x/2 on positive x.
    # Integrating h over [-a+s,a+s] minus [-a,a] gives -(2*a*s+s*s)/4;
    # dividing by width 2*a gives this exact whole-block centroid change.
    mean_dz = -shift / 4. - shift * shift / 80000.
    expected_gravity = 5.4e13 * 9.81 * mean_dz
    actual_gravity = math.fsum(state.gravitational_change_j[:32])
    gravity_error = bounded_error(actual_gravity, expected_gravity, ENERGY_ERROR,
                                  'independent integrated gravitational change')
    require(np.all(state.gravitational_change_j[:32] <= 0.), 'descending parcel gained height')
    require(not np.any(state.gravitational_change_j[32:]), 'stationary block changed gravity')
    bounded_error(state.boundary_work_j[0], 1.e12 * shift, ACCOUNT_ERROR, 'supplied Q ds')
    bounded_error(state.boundary_work_j[1], 0., ACCOUNT_ERROR, 'stationary boundary work')
    require(actual_gravity < 0. < state.boundary_work_j[0], 'work/gravity signs or ownership changed')
    return dict(status='PASS', time_s=state.time_s,
                max_relative_area_error=area_error, max_relative_volume_error=volume_error,
                max_relative_mass_heat_error=max(account_errors),
                block_mass_kg=measured_mass, block_enthalpy_j=measured_heat,
                footwall_gravitational_change_j=actual_gravity,
                analytic_footwall_gravitational_change_j=expected_gravity,
                relative_gravity_error=gravity_error,
                supplied_boundary_work_j=state.boundary_work_j.tolist(),
                exterior_volume_m3=0.)


def small_ramp_control(budget):
    fault = UnderthrustInterface(((0., 0.), (2., -2.), (4., -2.)),
        interface_id='analytic-six-vertex-ramp', frame_id=FRAME,
        datum_id='synthetic-z-zero', source_id='analytic-supplied-interface',
        detachment_depth_m=2., section_azimuth_deg=90.)
    material = (
        UnderthrustParcel('analytic-lower', 'foot-block', 'footwall',
            MaterialCohort('analytic-lower', 'lower-crust', 'synthetic-lower', -1.),
            rectangle(-1., 1., -5., -4.), 2., -5., 'analytic-relative-heat'),
        UnderthrustParcel('analytic-upper', 'hanging-block', 'hangingwall',
            MaterialCohort('analytic-upper', 'upper-crust', 'synthetic-upper', None),
            rectangle(-1., 1., 1., 2.), 4., 3., 'analytic-relative-heat'),
    )
    expected_vertices = ((1., -6.), (2., -7.), (3., -6.),
                         (3., -5.), (2., -6.), (1., -5.))
    expected = PlanarGeometry.polygon(expected_vertices, frame_id=FRAME)
    with PreparedUnderthrust(fault, material,
        (UnderthrustInterval(1., 2., 0., 7., -3., 'analytic-motion', 'analytic-force'),),
        time_s=0., epoch_id='synthetic-seconds', width_m=3., gravity_m_s2=10.,
        receiver_regions=(('whole', rectangle(-10., 20., -20., 20.)),),
        exterior_id='analytic-exterior', source_id='analytic-six-vertex-control',
        host_space_source_id='analytic-finite-inventory', budget=budget) as plan:
        state = plan.evaluate(1.)
        difference = state.polygons[0].overlay(expected, 'symmetric_difference', budget=budget).area_m2
        require(difference <= GEOMETRY_ERROR * 2., 'six-vertex analytic geometry differs')
        bounded_error(state.polygons[0].area_m2, 2., GEOMETRY_ERROR, 'analytic area')
        bounded_error(state.gravitational_change_j[0], -180., ENERGY_ERROR, 'analytic centroid gravity')
        bounded_error(state.boundary_work_j[0], 14., ACCOUNT_ERROR, 'analytic boundary work')
        signature = complete_signature(state, budget)
        execution_id = plan.execution_id
    return dict(status='PASS', expected_vertices_xz_m=expected_vertices,
                symmetric_difference_m2=difference, expected_area_m2=2.,
                expected_final_centroid_z_m=-6., expected_gravitational_change_j=-180.,
                signature=signature), execution_id


def run_sequence(fixture, prepared, owner):
    budget = WorkBudget(BUDGET_BYTES, parent=owner)
    signatures, controls, execution_ids = [], [], set()
    computed = hits = preparations = 0
    started = time.perf_counter()
    groups = (OUTPUT_TIMES_S,) if prepared else tuple((t,) for t in OUTPUT_TIMES_S)
    for times in groups:
        with prepare(fixture, budget) as plan:
            preparations += 1
            execution_ids.add(plan.execution_id)
            for output_time in times:
                state = plan.evaluate(output_time)
                signatures.append(complete_signature(state, budget))
                controls.append(inventory_controls(state))
                del state
            counts = plan.statistics()
            computed += counts['computed_outputs']; hits += counts['latest_hits']
    elapsed = time.perf_counter() - started
    require(computed == 3 and hits == 0, 'timing must compute three changed outputs without result hits')
    require(budget.reserved_bytes == 0, 'route leaked a retained reservation')
    return dict(elapsed_s=elapsed, signatures=signatures, controls=controls,
                execution_ids=sorted(execution_ids), computed_outputs=computed,
                latest_hits=hits, preparations=preparations,
                peak_accounted_bytes=budget.peak_reserved_bytes,
                final_reserved_bytes=budget.reserved_bytes)


def capture_sources():
    files = (Path(__file__).resolve(), ROOT / 'cases/w08_regimes.json',
             ROOT / 'docs/W08_REGIMES.md')
    manifest = {name: json.loads(raw) for name, raw in _source_bytes().items()}
    return dict(module_source_manifest=manifest,
        module_source_manifest_sha256=hashlib.sha256(json_bytes(manifest)).hexdigest(),
        supporting_files={path.relative_to(ROOT).as_posix():
            dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            for path in files})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError('new underthrust evidence path required')
    started = time.perf_counter()
    sources_before = capture_sources()
    owner = WorkBudget(BUDGET_BYTES)
    raw = {'cold_three_preparations': [], 'prepared_three_changed_outputs': []}
    runs, orders = [], []
    baseline = None
    execution_ids = set()
    # This explicit caller allowance covers immutable fixture geometry, records,
    # and compact retained signatures/control summaries; it is not measured RSS.
    with _native_lease():
        with owner.reserve(2 * 1024**2, category='benchmark-inputs-and-records'):
            fixture = make_fixture()
            inputs = fixture_record(fixture)
            analytic, identity = small_ramp_control(owner)
            execution_ids.add(identity)
            for repeat in range(3):
                order = (False, True) if repeat % 2 == 0 else (True, False)
                orders.append(['prepared' if value else 'cold' for value in order])
                for prepared in order:
                    key = 'prepared_three_changed_outputs' if prepared else 'cold_three_preparations'
                    result = run_sequence(fixture, prepared, owner)
                    execution_ids.update(result['execution_ids'])
                    if baseline is None:
                        baseline = result['signatures']
                    require(result['signatures'] == baseline, 'complete scientific output hash parity failed')
                    raw[key].append(result['elapsed_s'])
                    runs.append(dict(repeat=repeat + 1, route=key, **result))
    require(owner.reserved_bytes == 0, 'benchmark leaked a shared reservation')
    require(len(execution_ids) == 1, 'execution identities differ within the benchmark')
    sources_after = capture_sources()
    require(sources_after == sources_before, 'source, case, contract or tool changed during measurement')
    medians = {key: statistics.median(samples) for key, samples in raw.items()}
    cold = medians['cold_three_preparations']
    prepared = medians['prepared_three_changed_outputs']
    saved = cold - prepared
    saved_percent = 100. * saved / cold
    report = dict(schema='atlas.underthrust-check.v1', status='PASS',
        source_status='WORKING NON-CANON', execution_id=next(iter(execution_ids)),
        source_binding=sources_before, inputs=inputs,
        input_specification_sha256=hashlib.sha256(json_bytes(inputs)).hexdigest(),
        runtime=dict(python=platform.python_version(), implementation=platform.python_implementation(),
            platform=platform.platform(), numpy=np.__version__, scipy=scipy.__version__,
            shapely=shapely.__version__, geometry=geometry_runtime(),
            threadpoolctl=version('threadpoolctl'), native_threads=1,
            native_limit_owner='stokes_execution._native_lease'),
        controls=dict(status='PASS', analytic_small_ramp=analytic,
            geometry_normalised_error_bound=GEOMETRY_ERROR,
            extensive_relative_error_bound=ACCOUNT_ERROR, energy_relative_error_bound=ENERGY_ERROR,
            large_fixture= runs[0]['controls']),
        timing=dict(scope='three complete outputs of the same 64-parcel, eight-receiver supplied section',
            included='preparation, live execution checks, evaluation, all output materialisation/hashing, '
                     'cheap conservation controls, statistics and close',
            excluded='interpreter startup, imports, immutable input construction, report source snapshots and JSON writing',
            repeats_s=raw, order=orders, medians_s=medians,
            seconds_saved=saved, percent_saved=saved_percent,
            complete_output_hash_parity=True, complete_result_hits=0, runs=runs),
        resources=dict(shared_budget_bytes=BUDGET_BYTES,
            peak_accounted_bytes=owner.peak_reserved_bytes, final_reserved_bytes=owner.reserved_bytes,
            fixed_caller_input_and_record_allowance_bytes=2 * 1024**2,
            measurement='accounted allocations, not process RSS'),
        limitations='cold-versus-prepared reuse only; synthetic prescribed kinematics; '
                    'not physical validation, world-generation performance or an algorithm-versus-PDE comparison',
        measurement_wall_s=time.perf_counter() - started)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(status='PASS', controls='PASS', complete_output_hash_parity=True,
        medians_s=medians, seconds_saved=saved, percent_saved=saved_percent,
        peak_accounted_bytes=owner.peak_reserved_bytes,
        total_wall_s=time.perf_counter() - started), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
