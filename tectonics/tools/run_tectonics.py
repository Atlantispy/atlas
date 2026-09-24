"""Run/resume the public W12 column assembly through the real Atlas graph.

SPDX-License-Identifier: AGPL-3.0-only
Source checkout entry point. No private data, downloads or historical checkpoints.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'examples')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True, help='new run directory, or exact existing directory with --resume')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--cells', type=int, help='5..64 synthetic columns; defaults to 8 for a new run')
    parser.add_argument('--stop-after', type=int, choices=(0,1,2), help='commit only this declared output index; no full graph until final')
    args = parser.parse_args()
    from atlas_tectonics.assembly import PreparedColumnAssembly
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    from w12_column_case import make_column_case
    from w12_graph import run_graph
    import numpy as np
    import scipy
    import blosc2
    import numba
    import shapely

    directory = args.directory.resolve()
    binding = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__).resolve(), ROOT/'examples/w12_column_case.py')}
    config_path = directory/'case.json'
    if args.resume:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if (set(config) != {'schema','cells','example_sources'} or
                config['schema'] != 'atlas.w12-public-run.v1' or config['example_sources'] != binding):
            raise ValueError('case/source binding differs; do not edit or repin the saved run')
        if args.cells is not None and args.cells != config['cells']:
            raise ValueError('resume cannot change the source grid')
    else:
        config = dict(schema='atlas.w12-public-run.v1', cells=8 if args.cells is None else args.cells,
                      example_sources=binding)
        if type(config['cells']) is not int or not 5 <= config['cells'] <= 64:
            raise ValueError('cells must be between 5 and 64')
        directory.mkdir(parents=False, exist_ok=False)
        with config_path.open('x', encoding='utf-8') as stream:
            json.dump(config, stream, indent=2, allow_nan=False)
            stream.write('\n')
    budget = WorkBudget(128 << 20)
    started = time.perf_counter()
    case = make_column_case(cells=config['cells'], budget=budget)
    source = case['provenance']
    context = dict(world_id='public-synthetic-control', snapshot_id='w12-columns-v1',
        calendar_id=source['epoch']['id'], spatial_frame_id=source['frame']['id'],
        vertical_reference=source['frame']['depth_reference_id'], scenario_id='stationary-cooling-compaction-support')
    limits = StoreLimits(4096, 8<<20, 32<<20, decoded_cache_bytes=65536,
                        max_manifest_bytes=1<<20, verified_cache_entries=32, sqlite_cache_bytes=65536)
    report = dict(schema='atlas.w12-public-run-report.v1', status='INCOMPLETE',
        source_status='WORKING NON-CANON', public_example=source, configuration=config,
        runtime=dict(python=sys.version, platform=platform.platform(), numpy=np.__version__,
                     scipy=scipy.__version__, blosc2=blosc2.__version__, numba=numba.__version__, shapely=shapely.__version__),
        limits=dict(accounted_bytes=128<<20, store_bytes=32<<20, accepted_output_count=3,
                    process_rss_measured=False), physical_acceptance=False, whole_world_generation=False)
    with ArrayStore(directory/'native.sqlite', limits=limits, budget=budget) as store:
        with PreparedColumnAssembly(case['initial'], case['initial_surface'], case['support_policy'],
                case['schedule'], store=store, context=context, source_id=source['source_id'],
                reservoir_weights=np.full(config['cells'], 1./config['cells']),
                external_pressure_pa=np.zeros(config['cells']), budget=budget) as plan:
            if args.stop_after is not None and args.stop_after < 2:
                product = plan.run(args.stop_after)
                plan.verify_product(product)
                report['execution_path'] = 'committed native prefix; graph final output not requested'
                report['product'] = product
            else:
                report['graph_result'] = run_graph(plan, graph_cache_root=directory/'graph-cache')
                report['product'] = report['graph_result']['product']
                report['execution_path'] = 'captured R11 contract / R24 executor / R12 graph cache'
            report['plan_statistics'] = plan.statistics()
        report['storage'] = store.statistics()
    if budget.reserved_bytes:
        raise AssertionError('assembly resource reservation leak')
    report.update(status=('PASS_SUPPORTED_NATIVE_PREFIX' if args.stop_after is not None and args.stop_after < 2
                          else 'PASS_SUPPORTED_SYNTHETIC_ASSEMBLY'),
                  seconds=time.perf_counter()-started,
                  timing_scope='case construction, native/graph execution, verification and store close; excludes interpreter/import startup and report serialisation',
                  released_resources=budget.statistics())
    for number in range(1, 10001):
        destination = directory/('run-%05d.json' % number)
        try:
            with destination.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write('\n')
            break
        except FileExistsError:
            continue
    else:
        raise ValueError('run-report limit reached')
    print(json.dumps(dict(status=report['status'], report=str(destination), seconds=report['seconds'],
        product_id=report['product']['product_id'], plan_statistics=report['plan_statistics'],
        peak_accounted_bytes=report['released_resources']['peak_reserved_bytes']), indent=2))


if __name__ == '__main__':
    main()
