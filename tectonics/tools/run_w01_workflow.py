"""Small authored W01-to-W02 example; optionally time repeated preparation reuse.

No reference download, installation, full simulation or implicit output files.
All physical numbers below are synthetic controls, not calibrated geology.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'src'))


def example_inputs(cells=32):
    from atlas_tectonics import (
        BoundaryRegion, CohortDescription, ColumnDescription, CoolingHistory,
        FeatureGeometry, FeaturePrecedence, GeologicalCase, GeologicalLayer,
        GeologicalProvince, GeologySource, InitialConditionState, InputOrigin,
        LayerComponent, MaterialCohort, MaterialDefinition, MaterialVolumeBasis,
        PlanarGeometry, RegionalGrid1D, SurfaceSelector, ThermalInitialProfile,
        build_boundary_network, RegionalColumnSupport,
        PlanarRegionalSection, PrescribedPlateMotion, RegionalMotionDefinition,
        RegionalReduction,
    )
    source = GeologySource('example', 'synthetic',
        'Authored two-material strips for workflow verification; not Earth calibration.')
    def rectangle(a, b):
        return PlanarGeometry.polygon(((a, -1.), (b, -1.), (b, 1.), (a, 1.)),
                                      frame_id='example-plane')
    domain = rectangle(0., 3.)
    topology = build_boundary_network(domain, (BoundaryRegion('whole', 'plate', domain),))
    materials = tuple(MaterialDefinition(k, 'solid', 'example', 3000., 3., 1000.,
        0., 3e-5, 300., (0., 2000.)) for k in ('rock-a', 'rock-b'))
    cohorts = tuple(CohortDescription(MaterialCohort(k, 'rock-'+k, 'origin-'+k,
        -100. if k == 'a' else -10.), 'example') for k in ('a', 'b'))
    columns = tuple(ColumnDescription('column-'+str(i), 'continental', (
        GeologicalLayer('a', 'crust', float(i+1), (LayerComponent('a', 1.),), 0., 'example'),
        GeologicalLayer('b', 'crust', float(3-i), (LayerComponent('b', 1.),), 0., 'example')),
        4., 'initial', 'example') for i in range(3))
    case = GeologicalCase('workflow-example', topology, time_s=0., epoch_id='epoch',
        depth_reference_id='surface', source_id='example', sources=(source,),
        materials=materials, cohorts=cohorts, columns=columns,
        thermal_profiles=(ThermalInitialProfile('initial', 'example', 'constant', temperatures_k=(300.,)),),
        geometries=tuple(FeatureGeometry('stripe-'+str(i), rectangle(float(i), float(i+1)),
            'example') for i in (1, 2)),
        provinces=(GeologicalProvince('background', 'column-0', SurfaceSelector('domain'), 'example'),
            *(GeologicalProvince('stripe-'+str(i), 'column-'+str(i),
                SurfaceSelector('geometry', ('stripe-'+str(i),)), 'example') for i in (1, 2))),
        precedence=FeaturePrecedence(('stripe-2', 'stripe-1', 'background')))
    initial = InitialConditionState(case, origins=(InputOrigin('example', 'authored', 'workflow-example-v1'),),
        cooling_history=(CoolingHistory('initial', 'example', None, 'Not measured for this fixture.'),),
        material_bases=tuple(MaterialVolumeBasis(m.material_id, 'grain', 'example') for m in materials))
    units = dict(length_unit='m', velocity_unit='m/s', angular_velocity_unit='rad/s')
    motion = PrescribedPlateMotion('plate', 'example-plane', 'epoch', 0., 'planar-rigid',
        (1., 0., 0.), (0., 0., 0.), (0., 0., 0.), source, **units)
    definition = RegionalMotionDefinition(topology, (motion,), 'epoch', 0., .025, 's', source)
    section = PlanarRegionalSection('section', 'example-plane', 'epoch', 0.,
        (0., 0., 0.), (1., 0.), 3., (0., 0., 0.), (0., 0., 0.), source, **units)
    return (initial, definition, section,
        RegionalReduction('planar-columns', 'frozen-at-start', source, 2.),
        RegionalGrid1D(cells, 3.), RegionalColumnSupport('planar-strip', 0., 4., source))


def main():
    import numpy as np
    import numba
    import scipy
    import shapely
    from atlas_tectonics import MaterialBoundary, PreparedRegionalWorkflow
    from atlas_tectonics.resources import WorkBudget
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', action='store_true', help='three matched pairs of four independent branches')
    parser.add_argument('--output', type=Path, help='write evidence exclusively; refuses an existing file')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('output already exists; preserve earlier evidence')
    budget = WorkBudget(128 << 20)
    t = time.perf_counter()
    inputs = example_inputs()
    description_seconds = time.perf_counter()-t
    boundaries = dict(left=MaterialBoundary('open', {'a': 4., 'b': 0.}, 'authored-left-reservoir'),
                      right=MaterialBoundary('open', None, 'authored-right-reservoir'))
    t = time.perf_counter()
    with PreparedRegionalWorkflow(*inputs, budget=budget) as plan:
        setup_seconds = time.perf_counter()-t
        initial = plan.initialise()
        t = time.perf_counter()
        evolved = plan.advance(initial, **boundaries)
        first_advance_seconds = time.perf_counter()-t
    volume = float(np.sum(initial.initial_samples.array('phase_volume_m3')))
    if abs(volume-24.) > 1e-12:
        raise AssertionError('independent 3 x 2 x 4 metre inventory differs')
    if evolved.material.time_s != .025:
        raise AssertionError('original declared interval not covered')
    out = dict(status='PASS_SYNTHETIC_WORKFLOW_ONLY', physical_acceptance=False,
        cells=32, cohorts=2, frozen_duration_s=.025, steps=evolved.steps,
        description_setup_seconds=description_seconds, first_plan_setup_seconds=setup_seconds,
        first_advance_seconds=first_advance_seconds, initial_phase_volume_m3=volume,
        initial_material_id=initial.material.state_id, final_material_id=evolved.material.state_id,
        workflow_id=evolved.workflow_id, execution_id=evolved.execution_id,
        temperature_status=evolved.descriptor()['temperature_semantics'],
        python=sys.version, platform=platform.platform(),
        versions={m.__name__: m.__version__ for m in (np, scipy, shapely, numba)},
        threads={k: os.environ.get(k) for k in ('NUMBA_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS')})
    if args.benchmark:
        pairs = []
        for rep in range(3):
            pair = dict(repetition=rep)
            for mode in (('fresh', 'reuse') if rep % 2 == 0 else ('reuse', 'fresh')):
                results = []
                t = time.perf_counter()
                if mode == 'fresh':
                    for _ in range(4):
                        with PreparedRegionalWorkflow(*inputs, budget=budget) as plan:
                            results.append(plan.advance(plan.initialise(), **boundaries))
                else:
                    with PreparedRegionalWorkflow(*inputs, budget=budget) as plan:
                        prepared_seconds = time.perf_counter()-t
                        for _ in range(4):
                            results.append(plan.advance(plan.initialise(), **boundaries))
                elapsed = time.perf_counter()-t
                # Complete IDs bind arrays, provenance, parent and every receipt.
                if any(x.workflow_id != evolved.workflow_id for x in results):
                    raise AssertionError('reused and fresh workflow results differ')
                pair[mode+'_seconds'] = elapsed
                if mode == 'reuse':
                    pair['reuse_setup_seconds'] = prepared_seconds
                    pair['reuse_four_advances_seconds'] = elapsed-prepared_seconds
            pair['saved_seconds'] = pair['fresh_seconds']-pair['reuse_seconds']
            pair['saved_percent'] = 100.*pair['saved_seconds']/pair['fresh_seconds']
            pairs.append(pair)
        base = statistics.median(p['fresh_seconds'] for p in pairs)
        candidate = statistics.median(p['reuse_seconds'] for p in pairs)
        out['benchmark'] = dict(scope='Four identical independent initialise-and-evolve branches, 32 cells, same source/policy/results; reuse setup INCLUDED.',
            baseline='Same implementation with fresh preparation per branch; no historic S7 implementation existed.',
            timing='Initial import/description and first kernel call excluded equally; no persistent result-cache hits.',
            pairs=pairs, median_fresh_seconds=base, median_reuse_seconds=candidate,
            saved_seconds=base-candidate, saved_percent=100.*(1.-candidate/base),
            all_workflow_ids_exact=True, whole_world_speedup_measured=False)
    out['resources'] = budget.statistics()
    if budget.reserved_bytes:
        raise AssertionError('workflow reservation leak')
    rendered = json.dumps(out, indent=2, allow_nan=False)+'\n'
    # Keep completed evidence visible even if an optional destination is denied.
    print(rendered, flush=True)
    if args.output:
        with args.output.open('x', encoding='utf8') as stream:
            stream.write(rendered)


if __name__ == '__main__':
    main()
