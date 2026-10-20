"""Summarise existing replay telemetry; no runtime imports or sampling overhead.

Usage: python -B -I parity_measurements.py OUTPUT_DIR full|smoke
This is a measurement companion, not a replacement for gpy_parity_check.py.
"""
import json
import math
import sys
from functools import lru_cache
from pathlib import Path


def number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{label}: missing/invalid non-negative measurement')
    return value


@lru_cache(maxsize=4)
def source_size(runtime):
    if not runtime.startswith('test:'):
        raise ValueError('unexpected runtime')
    root = Path(runtime[5:])
    return sum(p.stat().st_size for p in root.rglob('*.py'))+(root/'TEST_COMPOSITION.json').stat().st_size


def shard(path):
    done = None
    count = 0
    cpu = wall = 0.0
    statuses = {}
    with path.open(encoding='utf8') as stream:
        for line in stream:
            row = json.loads(line)
            if done is not None:
                raise ValueError(f'{path.name}: content after done')
            if row.get('done'):
                done = row
            elif 'job_counts' not in row:
                count += 1
                cpu += number(row.get('cpu_s'), 'cpu_s')
                wall += number(row.get('wall_s'), 'wall_s')
                status = row.get('status', 'missing')
                statuses[status] = statuses.get(status, 0)+1
    if done is None or done.get('queries') != count:
        raise ValueError(f'{path.name}: missing/inconsistent done')
    if path.with_suffix('.exit').read_text(encoding='utf8').strip() != '0':
        raise ValueError(f'{path.name}: nonzero exit')
    memory = done.get('process_memory', {})
    runtime = done['runtime']
    if not runtime.startswith('test:'):
        raise ValueError(f'{path.name}: unexpected runtime')
    source_bytes = source_size(runtime)
    return dict(
        file=path.name, runtime=runtime, package_digest=done['package_digest'],
        queries=count, statuses=statuses, query_cpu_seconds=cpu, query_wall_seconds=wall,
        replay_elapsed_seconds=number(done.get('seconds'), 'done.seconds'),
        peak_working_set_bytes=number(memory.get('peak_working_set_bytes'), 'peak_working_set_bytes'),
        peak_commit_bytes=number(memory.get('peak_commit_bytes'), 'peak_commit_bytes'),
        final_rss_bytes=number(memory.get('rss_bytes'), 'rss_bytes'),
        output_logical_bytes=sum(p.stat().st_size for p in (
            path, path.with_suffix('.log'), path.with_suffix('.exit'))),
        runtime_source_logical_bytes=source_bytes)


def main(directory, mode):
    if mode not in ('full', 'smoke'):
        raise ValueError('mode must be full or smoke')
    out = Path(directory)
    report = dict(
        scope='Component surface-query replay only; not whole-interval performance or acceptance.',
        mode=mode,
        limitations=[
            'Replay elapsed excludes interpreter/import and input setup before the replay timer.',
            'Sum of shard elapsed times is process-seconds, not concurrent arm wall-clock time.',
            'Process memory peaks include process setup; maxima are per process, not concurrent tree RAM.',
            'Sum of process peaks is an upper bound, not a measured simultaneous peak.',
            'Disk figures are logical source and output bytes, not allocated filesystem space.',
            'Capped runs are censored; assess matching completed coverage before timing comparisons.',
        ], stages={}, errors=[])
    for stage in ('iv1-surfaces', 'iv2-sample', 'iv2-extra', 'iv2-deep'):
        if stage == 'iv2-extra':
            extra = out/'iv2-sample-extra-list.jsonl'
            if extra.is_file() and extra.stat().st_size == 0:
                report['stages'][stage] = {'status': 'not required; empty extra list'}
                continue
        report['stages'][stage] = {}
        for arm in ('base', 'gpy'):
            try:
                rows = [shard(p) for p in sorted(out.glob(f'{stage}-{arm}-s*.jsonl'))]
                if not rows:
                    raise ValueError(f'{stage}-{arm}: no shards')
                if len({r['runtime'] for r in rows}) != 1 or len({r['package_digest'] for r in rows}) != 1:
                    raise ValueError(f'{stage}-{arm}: mixed runtime identity')
                summary = dict(shards=rows)
                for field in ('queries', 'query_cpu_seconds', 'query_wall_seconds',
                              'replay_elapsed_seconds', 'output_logical_bytes'):
                    summary['sum_'+field] = sum(r[field] for r in rows)
                for field in ('peak_working_set_bytes', 'peak_commit_bytes'):
                    summary['max_process_'+field] = max(r[field] for r in rows)
                    summary['sum_process_'+field+'_upper_bound'] = sum(r[field] for r in rows)
                summary['runtime_source_logical_bytes'] = rows[0]['runtime_source_logical_bytes']
                report['stages'][stage][arm] = summary
            except (OSError, ValueError, KeyError, TypeError) as exc:
                report['errors'].append(f'{stage}-{arm}: {exc}')
    report['complete_measurements'] = not report['errors']
    (out/'measurements.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf8')
    print('Measurements:', 'PASS' if not report['errors'] else 'FAIL', out/'measurements.json')
    return bool(report['errors'])


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
