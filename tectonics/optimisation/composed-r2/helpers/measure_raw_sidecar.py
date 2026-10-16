"""Bounded WP12 synthetic comparison; never opens an existing real store.

Three alternating fresh ordinary/mmap process pairs consume one new sealed
numeric fixture. Component and aggregate timings are not WP0b full run-path
evidence and cannot authorise production activation.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(RUNTIME), str(HERE.parent)]

import numpy as np
import psutil

from atlas_tectonics.resources import WorkBudget
from compact_contracts import LogicalIdentity
from content_cache import ChargeSpec, OwnedStream, create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import ArrayInfo, SegmentBackend
from raw_sidecar_store import RawSidecarStore

SCHEMA = 'atlas.raw-sidecar-measure.v1'
COUNT = 65536
WIDTH = 4096
READ_CYCLES = 128
AGGREGATE_PASSES = 4
NAMES = ('connectivity', 'metric', 'partition')
DTYPES = {'connectivity': '<u8', 'metric': '<f8', 'partition': '<u4'}
THREAD_ENV = {name: '1' for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
    'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}
THREAD_ENV['PYTHONHASHSEED'] = '0'
PROCESS_BUDGET = 512 << 20


def digest(path):
    value = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            value.update(block)
    return value.hexdigest()


def snapshot(paths):
    return {str(path): {'bytes': path.stat().st_size, 'sha256': digest(path)}
            for path in sorted(set(paths))}


def source_snapshot():
    paths = {Path(__file__).resolve()}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.suffix == '.py' and (path.is_relative_to(HERE) or path.is_relative_to(RUNTIME)):
                paths.add(path)
    return snapshot(paths)


def process_memory():
    fields = psutil.Process().memory_info()._asdict()
    return {name: fields.get(name) for name in ('rss', 'private', 'peak_wset', 'peak_pagefile')}


def scope_stats(scope):
    row = scope.stats()
    return {'retained_bytes': row.retained_bytes, 'peak_retained_bytes': row.peak_retained_bytes,
            'pending_bytes': row.pending_bytes, 'pinned_bytes': row.pinned_bytes,
            'evictable_bytes': row.evictable_bytes, 'purpose_bytes': dict(row.purpose_bytes),
            'purpose_peak_bytes': dict(row.purpose_peak_bytes)}


def make_scope():
    budget = WorkBudget(PROCESS_BUDGET)
    return budget, create_retained_scope(budget, process_epoch='wp12-synthetic-measure')


class NumericSource:
    def __init__(self, scope, name):
        self.scope = scope
        self.info = ArrayInfo(name, DTYPES[name], (COUNT,), COUNT * np.dtype(DTYPES[name]).itemsize)

    def blocks(self, *, max_owned_bytes):
        step = max_owned_bytes // np.dtype(self.info.dtype).itemsize

        def generate():
            for start in range(0, COUNT, step):
                stop = min(COUNT, start + step)
                size = (stop - start) * np.dtype(self.info.dtype).itemsize
                with self.scope.run_budget.reserve(8 * max_owned_bytes, category='measurement-input-scratch'):
                    indices = np.arange(start, stop, dtype=np.uint64)
                    if self.info.name == 'metric':
                        array = (((indices * 37) % 1000003) + 1).astype('<f8') / 1048576
                    elif self.info.name == 'connectivity':
                        array = ((indices * 5 + 17) % COUNT).astype('<u8')
                    else:
                        array = (indices % 64).astype('<u4')
                    with self.scope.reserve(ChargeSpec('measurement-input', size)) as reservation:
                        owned = reservation.commit(array.tobytes())
                    del indices, array
                yield owned
        return OwnedStream(generate(), scope=self.scope)


def fixture(output):
    root = output / 'fixture'
    root.mkdir()
    budget, scope = make_scope()
    stores = IntervalStoreSet.create_migration(root / 'catalog.json', workflow_id='a' * 64, scope=scope)
    candidate = stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
    identity = LogicalIdentity('wp12.synthetic.numeric.v1', sha256(b'wp12 deterministic numeric fixture v1').hexdigest(), COUNT)
    started = time.perf_counter()
    ref = SegmentBackend().publish(candidate, record_schema=identity.record_schema, identity=identity,
        metadata=b'{"source_kind":"synthetic"}', arrays=lambda: (NumericSource(scope, name) for name in NAMES),
        producer='b' * 64, representation_profile='wp12.numeric.columns.v1', scope=scope)
    sealed = candidate.seal(ref)
    stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
    elapsed = time.perf_counter() - started
    candidate.close()
    stores.close()
    scope.close()
    assert budget.reserved_bytes == 0
    return {'publication_seconds': elapsed, 'reference': ref.to_wire(),
            'original_files': snapshot(root.iterdir()), 'retained_after_close_bytes': budget.reserved_bytes}


def reads(reader):
    checksum = sha256()
    started = time.perf_counter()
    for cycle in range(READ_CYCLES):
        start = (cycle * 7919) % (COUNT - WIDTH + 1)
        for name in NAMES:
            with reader.read(name, start, start + WIDTH, max_owned_bytes=WIDTH * 8) as owned:
                assert not owned.value.flags.writeable
                checksum.update(memoryview(owned.value).cast('B'))
    return {'seconds': time.perf_counter() - started, 'sha256': checksum.hexdigest(),
            'reads': READ_CYCLES * len(NAMES), 'logical_bytes': READ_CYCLES * WIDTH * 20,
            'timing_boundary': 'read, full-byte SHA-256 consumption and borrow release'}


def aggregate(reader, budget):
    started = time.perf_counter()
    with budget.reserve(512 << 10, category='measurement-aggregate-scratch'):
        grouped = np.zeros(64, dtype='<f8')
        count = 0
        connection_sum = 0
        for unused in range(AGGREGATE_PASSES):
            for start in range(0, COUNT, WIDTH):
                stop = min(COUNT, start + WIDTH)
                with ExitStack() as stack:
                    values = {name: stack.enter_context(reader.read(name, start, stop,
                              max_owned_bytes=WIDTH * 8)).value for name in NAMES}
                    weighted = values['metric'] * (1 + values['connectivity'] % 7)
                    grouped += np.bincount(values['partition'].astype(np.intp), weights=weighted, minlength=64)
                    connection_sum += int(np.sum(values['connectivity'], dtype=np.uint64))
                    count += stop - start
                    del values, weighted
        checksum = sha256(memoryview(grouped).cast('B')).hexdigest()
        answer = {'sha256': checksum, 'rows': count, 'connection_sum': connection_sum,
                  'grouped_total': float(grouped.sum())}
        del grouped
    answer.update(seconds=time.perf_counter() - started,
        reads=AGGREGATE_PASSES * (COUNT // WIDTH) * len(NAMES),
        timing_boundary='block reads, weighted partition aggregation and connectivity reductions; no solver')
    return answer


def child(output, mode, result_path):
    result = {'schema': SCHEMA, 'mode': mode, 'status': 'INCOMPLETE', 'process_id': os.getpid(),
              'source_kind': 'synthetic', 'production_enabled': False}
    try:
        result['sources_before'] = source_snapshot()
        result['memory_start'] = process_memory()
        budget, scope = make_scope()
        started = time.perf_counter()
        stores = IntervalStoreSet.open_catalog(output / 'fixture' / 'catalog.json', scope=scope)
        view = SegmentBackend().open(stores, stores.head.head, scope=scope)
        result['sealed_open_seconds'] = time.perf_counter() - started
        enabled = mode != 'ordinary'
        started = time.perf_counter()
        reader = RawSidecarStore(view, output / 'sidecars', array_names=NAMES,
                                enabled=enabled, experimental=enabled)
        result['reader_init_verification_seconds'] = time.perf_counter() - started
        result['after_init_stats'] = reader.stats()
        result['memory_after_init'] = process_memory()
        if mode == 'build':
            started = time.perf_counter()
            reader.build()
            result['build_seconds'] = time.perf_counter() - started
        else:
            result['component'] = reads(reader)
            result['aggregate'] = aggregate(reader, budget)
        result['sidecar_stats'] = reader.stats()
        assert result['sidecar_stats']['live_mapped_bytes'] == 0
        result['scope_before_close'] = scope_stats(scope)
        result['run_budget_before_close'] = budget.statistics()
        result['memory_end_work'] = process_memory()
        reader.close()
        view.close()
        stores.close()
        result['scope_after_readers_close'] = scope_stats(scope)
        scope.close()
        result['retained_after_close_bytes'] = budget.reserved_bytes
        assert budget.reserved_bytes == 0
        result['sources_after'] = source_snapshot()
        assert result['sources_before'] == result['sources_after'], 'source changed during child'
        result['status'] = 'PASS'
    except BaseException as error:
        result.update(status='FAIL', error={'type': type(error).__name__, 'message': str(error)})
        traceback.print_exc()
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps({'mode': mode, 'status': result['status'], 'result': str(result_path)}), flush=True)
    return 0 if result['status'] == 'PASS' else 1


def run_child(output, mode, label):
    result_path = output / (label + '.json')
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', mode,
               '--output-dir', str(output), '--result', str(result_path)]
    started = time.perf_counter()
    completed = subprocess.run(command, env=dict(os.environ, **THREAD_ENV), capture_output=True,
                               text=True, timeout=180)
    (output / (label + '.stdout.log')).write_text(completed.stdout, encoding='utf8')
    (output / (label + '.stderr.log')).write_text(completed.stderr, encoding='utf8')
    print(json.dumps({'completed': label, 'returncode': completed.returncode}), flush=True)
    if completed.returncode:
        raise RuntimeError(f'{label} failed: see {result_path} and stderr log')
    row = json.loads(result_path.read_text(encoding='utf8'))
    row['fresh_process_wall_seconds'] = time.perf_counter() - started
    return row


def measure(output):
    output.mkdir(parents=True, exist_ok=False)
    result = {'schema': SCHEMA, 'status': 'INCOMPLETE', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'source_kind': 'synthetic', 'production_adoption': 'INCOMPLETE', 'production_enabled': False,
        'wp0b_representative_full_run_path': False,
        'limitations': ['Synthetic numeric fixture and aggregate arithmetic only; no WP0b real full run-path observation.',
                       'Fresh processes; OS file-cache state uncontrolled; no cold-cache claim.',
                       'OS process peaks span each whole child including imports, opening and verification.',
                       'Disk figures are file lengths, not allocated filesystem clusters.'],
        'configuration': {'elements_per_column': COUNT, 'column_dtypes': DTYPES,
            'raw_bytes': COUNT * 20, 'read_cycles': READ_CYCLES, 'read_width_elements': WIDTH,
            'aggregate_passes': AGGREGATE_PASSES, 'fresh_pairs': 3, 'run_budget_bytes': PROCESS_BUDGET,
            'process_order': ['ordinary', 'mmap', 'mmap', 'ordinary', 'ordinary', 'mmap'],
            'thread_environment': THREAD_ENV, 'seed': 'deterministic arithmetic; no RNG'},
        'environment': {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
                        'numpy': np.__version__, 'psutil': psutil.__version__}}
    try:
        result['sources_before'] = source_snapshot()
        result['fixture'] = fixture(output)
        result['build'] = run_child(output, 'build', 'build')
        result['runs'] = []
        for index, mode in enumerate(result['configuration']['process_order']):
            result['runs'].append(run_child(output, mode, f'{index + 1}-{mode}'))
        runs = result['runs']
        for phase in ('component', 'aggregate'):
            assert len({row[phase]['sha256'] for row in runs}) == 1, phase + ' checksum mismatch'
        assert len({row['aggregate']['connection_sum'] for row in runs}) == 1
        assert len({row['aggregate']['rows'] for row in runs}) == 1
        result['exact_result_parity'] = True
        result['medians'] = {}
        for mode in ('ordinary', 'mmap'):
            selected = [row for row in runs if row['mode'] == mode]
            result['medians'][mode] = {
                'sealed_open_seconds': statistics.median(row['sealed_open_seconds'] for row in selected),
                'reader_init_verification_seconds': statistics.median(row['reader_init_verification_seconds'] for row in selected),
                'component_seconds': statistics.median(row['component']['seconds'] for row in selected),
                'aggregate_seconds': statistics.median(row['aggregate']['seconds'] for row in selected),
                'fresh_process_wall_seconds': statistics.median(row['fresh_process_wall_seconds'] for row in selected),
                'peak_retained_bytes': statistics.median(row['scope_before_close']['peak_retained_bytes'] for row in selected),
                'peak_rss_bytes': statistics.median(row['memory_end_work']['peak_wset'] for row in selected)
                    if all(row['memory_end_work']['peak_wset'] is not None for row in selected) else None,
                'peak_private_commit_bytes': statistics.median(row['memory_end_work']['peak_pagefile'] for row in selected)
                    if all(row['memory_end_work']['peak_pagefile'] is not None for row in selected) else None}
            result['medians'][mode]['read_fixture_total_seconds'] = statistics.median(
                row['sealed_open_seconds'] + row['reader_init_verification_seconds'] +
                row['component']['seconds'] + row['aggregate']['seconds'] for row in selected)
        result['estimated_first_use_seconds'] = {
            'ordinary': result['medians']['ordinary']['read_fixture_total_seconds'],
            'mmap_build_then_fresh_read': result['build']['sealed_open_seconds'] +
                result['build']['reader_init_verification_seconds'] + result['build']['build_seconds'] +
                result['medians']['mmap']['read_fixture_total_seconds'],
            'meaning': 'sum of separate measured build process and median fresh read fixture; not one observed solver run'}
        result['sidecar_files'] = snapshot(path for path in (output / 'sidecars').rglob('*') if path.is_file())
        result['sidecar_bytes'] = sum(row['bytes'] for row in result['sidecar_files'].values())
        result['original_files_after'] = snapshot((output / 'fixture').iterdir())
        result['original_store_unchanged'] = result['original_files_after'] == result['fixture']['original_files']
        assert result['original_store_unchanged']
        result['sources_after'] = source_snapshot()
        assert result['sources_before'] == result['sources_after'], 'source changed during measurement'
        assert all(row['sources_before'] == result['sources_before'] for row in [result['build'], *runs]), 'child sources differ'
        result['status'] = 'PASS'
    except BaseException as error:
        result.update(status='FAIL', error={'type': type(error).__name__, 'message': str(error)})
        traceback.print_exc()
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    destination = output / 'measurement.json'
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps({'status': result['status'], 'measurement': str(destination)}), flush=True)
    return 0 if result['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='New synthetic output directory; no existing stores')
    parser.add_argument('--child', choices=('ordinary', 'mmap', 'build'))
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    if args.child:
        if args.result is None:
            parser.error('--child requires --result')
        return child(args.output_dir.resolve(), args.child, args.result.resolve())
    if args.result is not None:
        parser.error('--result is internal to child mode')
    return measure(args.output_dir.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
