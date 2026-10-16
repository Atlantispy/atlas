"""WP11 key census (test-only, read-only): do exact predicate inputs recur ACROSS queries?

A query is (support, logical component, endpoint), enumerated exactly as
scripts/replay_queries.py does: every component of every support row, endpoints
('start', 'end'), skipping 'start' when the component has no parent cell. The
endpoint time is 0 for 'start' and the support's duration_s for 'end'
(RC1 integration_differential_geometry.py:4889, _component_volume_bounds_decoded).

No runtime import and no geometry. Each key is a SHA-256 over canonical JSON of
the operands that predicate reads (rational-hex pairs reduced to lowest terms,
since the runtime decodes them to Fractions; constraint dicts with sorted keys).

Query-level candidates (one key per query):
  cone_named          _common_ray_cone_zero_volume(literals, constraints, t, t, level), cell=None
                      at the leaf: ordered [name, sign] literals + those constraints + t.
                      The per-call key adds the precision level; that needs the leaf queue,
                      so queries sharing this key are an UPPER BOUND on cross-query hits.
  cone_anonymous      same without literal names (certificates carry names, so a cache keyed
                      this way would need name rewriting; shown only to size that question).
  pair_prefix         time/level/cell-free prefix of _corotating_plane_pair_zero_volume and the
                      impossibility test of _coaxial_edge_pair_zero_volume: literals + constraints.
  pair_prefix_nontrivial  pair_prefix, only where not every literal is a moving-ray-edge
                      (those short-circuit before any work charge).
  root_cell           root-only, cell-dependent: cone_zero.certificate, plane_certificate,
                      _clipped_voxel_edge_zero_volume and the cell-bound cone: voxel + literals
                      + constraints + t.
Sub-keys (one per literal or ray of each query; level-free, so also upper bounds):
  plane_literal_named plane_certificate's per-literal test: voxel, [name, sign], constraint, t.
  constraint_pose     _constraint_pose(constraint, t, t, level): constraint + t (level-free).
  snapshot_nested_pose  nested pose of a snapshot-rotated literal at its own snapshot offset
                      (endpoint-independent): nested constraint + offset.
  ray_pose            _ray_box(direction, omega, t, t, level, prior) per ray path, using
                      _constraint_edge_ray_paths' snapshot rule: direction, omega, history, t.

Replay rows (cpu_s, leaves, max_level) from an earlier endpoint replay, when given, weight
the query-level repeats. Output: one JSON file in --out (exclusive create).

Usage (PYTHONHASHSEED=0):
  wp11_key_census.py --out DIR [--shards 6] --set LABEL SUPPORTS GRID INTERVAL REPLAY_GLOB [--set ...]
"""
import argparse
import glob
import gzip
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from fractions import Fraction
from pathlib import Path

HEX = re.compile(r'-?0x[0-9a-f]+\Z', re.IGNORECASE)
QUERY_LEVEL = ('cone_named', 'cone_anonymous', 'pair_prefix', 'pair_prefix_nontrivial', 'root_cell')
SUB_KEYS = ('plane_literal_named', 'constraint_pose', 'snapshot_nested_pose', 'ray_pose')
HIST_EDGES = (1, 2, 4, 8, 16, 64, 256, 1024)


def canon(value):
    """Exact-value canonical form: rational-hex pairs in lowest terms, recursively."""
    if isinstance(value, list):
        if (len(value) == 2 and all(isinstance(x, str) and HEX.match(x) for x in value)):
            num, den = int(value[0], 16), int(value[1], 16)
            if den > 0:
                q = Fraction(num, den)
                return ['q', str(q.numerator), str(q.denominator)]
        return [canon(x) for x in value]
    if isinstance(value, dict):
        return {k: canon(v) for k, v in value.items()}
    return value


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def digest(tag, *parts):
    h = hashlib.sha256(tag.encode('ascii'))
    size = 0
    for part in parts:
        h.update(len(part).to_bytes(8, 'big'))
        h.update(part)
        size += len(part)
    return h.digest()[:16], size


def history(prior):
    return [[row['angular_velocity_rad_s'], row['duration_s']] for row in prior]


def ray_paths(constraint):
    """_constraint_edge_ray_paths (RC1 differential_geometry:3994) on canonical JSON."""
    kind = constraint['kind']
    if kind == 'moving-ray-edge':
        return [(ray['direction'], ray['angular_velocity_rad_s'], history(ray.get('prior_rotations', [])))
                for ray in constraint['rays']]
    if kind == 'snapshot-rotated':
        inner = ray_paths(constraint['constraint'])
        if inner is None:
            return None
        omega, offset = constraint['angular_velocity_rad_s'], constraint['snapshot_offset_s']
        return [(direction, omega, prior + [[old, offset]]) for direction, old, prior in inner]
    return None


class Tally:
    """Total vs distinct keys, first-occurrence scope, group sizes and replay weights."""

    def __init__(self, shards):
        self.count = Counter()
        self.first_support = {}
        self.shard_seen = [set() for _ in range(shards)]
        self.shards = shards
        self.total = self.within_support = 0
        self.by_endpoint = {'start': [0, 0], 'end': [0, 0]}
        self.operand_bytes = []
        self.weights = Counter()

    def add(self, key, size, support, endpoint, replay=None):
        self.total += 1
        self.by_endpoint[endpoint][0] += 1
        self.shard_seen[support % self.shards].add(key)
        repeat = key in self.count
        self.count[key] += 1
        if repeat:
            self.by_endpoint[endpoint][1] += 1
            if self.first_support[key] == support:
                self.within_support += 1
        else:
            self.first_support[key] = support
            self.operand_bytes.append(size)
        if replay is not None:
            cpu, leaves, max_level = replay
            levels = min(leaves, max_level + 1)
            self.weights['joined'] += 1
            self.weights['cpu_s_all'] += cpu
            self.weights['leaves_all'] += leaves
            self.weights['decline_levels_ub_all'] += levels
            if repeat:
                self.weights['cpu_s_repeat'] += cpu
                self.weights['leaves_repeat'] += leaves
                self.weights['decline_levels_ub_repeat'] += levels
        return repeat

    def report(self):
        distinct = len(self.count)
        hist = Counter()
        for n in self.count.values():
            edge = next((e for e in HIST_EDGES if n <= e), 'more')
            hist['<=%s' % edge if edge != 'more' else '>%d' % HIST_EDGES[-1]] += 1
        sizes = sorted(self.operand_bytes)
        shard_distinct = sum(len(s) for s in self.shard_seen)
        out = dict(total=self.total, distinct=distinct, repeats=self.total - distinct,
                   repeat_fraction=round((self.total - distinct) / self.total, 4) if self.total else None,
                   repeats_within_same_support=self.within_support,
                   repeats_only_across_supports=self.total - distinct - self.within_support,
                   repeats_with_private_cache_per_shard=self.total - shard_distinct,
                   by_endpoint={k: dict(total=v[0], repeats=v[1]) for k, v in self.by_endpoint.items()},
                   group_size_histogram=dict(sorted(hist.items())),
                   max_group=max(self.count.values()) if self.count else 0,
                   key_operand_bytes=dict(
                       mean=round(sum(sizes) / len(sizes), 1) if sizes else None,
                       median=sizes[len(sizes) // 2] if sizes else None,
                       max=sizes[-1] if sizes else None))
        if self.weights:
            out['replay_weights'] = {k: (round(v, 4) if isinstance(v, float) else v)
                                     for k, v in sorted(self.weights.items())}
        return out


def load_replay(pattern):
    rows, files = {}, sorted(glob.glob(pattern)) if pattern and pattern != '-' else []
    for path in files:
        with open(path, encoding='utf8') as f:
            for line in f:
                row = json.loads(line)
                if 'cpu_s' not in row:
                    continue
                key = (row['support_index'], row['full_cell'], row['endpoint'])
                rows[key] = (row['support_id'], float(row['cpu_s']), int(row.get('leaves') or 0),
                             int(row.get('max_level') or 0), row.get('status'))
    return files, rows


def census(label, supports, grid, interval, replay_glob, shards):
    t0 = time.process_time()
    partition = json.loads(gzip.decompress(Path(grid).read_bytes()))['partition']
    step = json.loads(gzip.decompress(Path(interval).read_bytes()))['interval']
    replay_files, replay = load_replay(replay_glob)
    tallies = {name: Tally(shards) for name in QUERY_LEVEL + SUB_KEYS}
    stats = Counter()
    literal_counts, kinds, statuses = Counter(), Counter(), Counter()
    duration_mismatch, interval_mismatch, replay_identity_mismatch = 0, 0, 0
    step_duration = dumps(canon(step['duration_s']))
    with gzip.open(supports, 'rt', encoding='utf8') as f:
        header = json.loads(f.readline())
        if header.get('interval_id') != step.get('interval_id'):
            interval_mismatch += 1
        for index, line in enumerate(f):
            record = json.loads(line)
            stats['supports'] += 1
            constraints = {name: canon(c) for name, c in record['constraints'].items()}
            cjson = {name: dumps(c) for name, c in constraints.items()}
            for c in constraints.values():
                kinds[c['kind']] += 1
            voxel_b = dumps(canon(record['voxel']))
            end_b = dumps(canon(record['duration_s']))
            if end_b != step_duration:
                duration_mismatch += 1
            support_id = header['support_ids'][index]
            for part in record['components']:
                stats['components'] += 1
                lits = [[name, sign] for name, sign in part['constraints']]
                literal_counts[len(lits)] += 1
                lits_b = dumps(lits)
                signs_b = dumps([sign for _, sign in lits])
                cons_b = b'[' + b','.join(cjson[name] for name, _ in lits) + b']'
                trivial = all(constraints[name]['kind'] == 'moving-ray-edge' for name, _ in lits)
                for endpoint in ('start', 'end'):
                    if endpoint == 'start' and part['parent_cell_id'] is None:
                        continue
                    stats['queries'] += 1
                    stats['queries_' + endpoint] += 1
                    time_b = b'"zero"' if endpoint == 'start' else end_b
                    row = replay.get((index, part['logical_cell_id'], endpoint))
                    weight = None
                    if row is not None:
                        if row[0] != support_id[:16]:
                            replay_identity_mismatch += 1
                        else:
                            weight = row[1:4]
                            statuses[row[4]] += 1
                    elif replay:
                        stats['replay_missing'] += 1
                    tallies['cone_named'].add(*digest('cone', lits_b, cons_b, time_b), index, endpoint, weight)
                    tallies['cone_anonymous'].add(*digest('cone', signs_b, cons_b, time_b), index, endpoint, weight)
                    pair = digest('pair', lits_b, cons_b)
                    tallies['pair_prefix'].add(*pair, index, endpoint, weight)
                    if not trivial:
                        tallies['pair_prefix_nontrivial'].add(*pair, index, endpoint, weight)
                    tallies['root_cell'].add(*digest('root', voxel_b, lits_b, cons_b, time_b), index, endpoint, weight)
                    for name, sign in lits:
                        c = constraints[name]
                        if sign in (-1, 1):
                            tallies['plane_literal_named'].add(
                                *digest('plane', voxel_b, dumps([name, sign]), cjson[name], time_b), index, endpoint)
                        tallies['constraint_pose'].add(*digest('cpose', cjson[name], time_b), index, endpoint)
                        if c['kind'] == 'snapshot-rotated':
                            nested = digest('npose', dumps(c['constraint']), dumps(c['snapshot_offset_s']))
                            tallies['snapshot_nested_pose'].add(*nested, index, endpoint)
                        for direction, omega, prior in ray_paths(c) or ():
                            tallies['ray_pose'].add(
                                *digest('ray', dumps(direction), dumps(omega), dumps(prior), time_b), index, endpoint)
    return dict(
        label=label,
        inputs=dict(supports=str(supports), grid=str(grid), interval=str(interval),
                    replay_glob=replay_glob, replay_files=len(replay_files)),
        checks=dict(interval_id_matches_supports_header=interval_mismatch == 0,
                    support_duration_differs_from_interval=duration_mismatch,
                    replay_rows=len(replay), replay_support_identity_mismatch=replay_identity_mismatch,
                    replay_statuses=dict(sorted((str(k), v) for k, v in statuses.items())),
                    native_cells=len(partition['native_cells']),
                    grid_lines=[len(a) for a in partition['grid_lines']]),
        counts=dict(sorted(stats.items())),
        literal_count_histogram={str(k): v for k, v in sorted(literal_counts.items())},
        constraint_kinds_per_support_sum=dict(sorted(kinds.items())),
        candidates={name: tallies[name].report() for name in QUERY_LEVEL + SUB_KEYS},
        cpu_s=round(time.process_time() - t0, 2))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', required=True, help='new evidence folder (wp11-census-r1)')
    ap.add_argument('--shards', type=int, default=6, help='round-robin shard count for the private-cache proxy')
    ap.add_argument('--set', nargs=5, action='append', required=True,
                    metavar=('LABEL', 'SUPPORTS', 'GRID', 'INTERVAL', 'REPLAY_GLOB'))
    args = ap.parse_args()
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise SystemExit('set PYTHONHASHSEED=0, as production does')
    out = Path(args.out)
    target = out / 'census.json'
    if len(str(target.resolve())) >= 259:
        raise SystemExit('output path would reach MAX_PATH')
    out.mkdir(parents=True, exist_ok=True)
    started = time.strftime('%Y-%m-%d %H:%M:%S')
    results = [census(label, s, g, i, r, args.shards) for label, s, g, i, r in args.set]
    document = dict(schema='atlas.wp11-key-census.v1', started=started,
                    finished=time.strftime('%Y-%m-%d %H:%M:%S'), python=sys.version.split()[0],
                    hash_seed=os.environ.get('PYTHONHASHSEED'), shards=args.shards,
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    sets=results)
    with target.open('x', encoding='utf8', newline='\n') as sink:
        json.dump(document, sink, indent=1, sort_keys=True)
        sink.write('\n')
    for result in results:
        print('==', result['label'], result['counts'], 'cpu %.1fs' % result['cpu_s'])
        for name, c in result['candidates'].items():
            w = c.get('replay_weights', {})
            print('  %-24s total %8d distinct %8d repeats %8d (%.1f%%) same-support %8d  cpu_rep %s/%s' % (
                name, c['total'], c['distinct'], c['repeats'], 100 * (c['repeat_fraction'] or 0),
                c['repeats_within_same_support'], w.get('cpu_s_repeat', '-'), w.get('cpu_s_all', '-')))
    print('wrote', target)


if __name__ == '__main__':
    main()
