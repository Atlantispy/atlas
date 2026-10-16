"""G, part 1: exact structural growth count from saved records. READ-ONLY.

Inputs (both verified): the saved IV2 trace-input capture (the accepted IV1
partition and its 2,016 supports, sha256 e761ff8c...) and a byte-identical COPY
of the pinned IV1 store (sha256 3f70c26d...), opened mode=ro&immutable=1.

Counts, for each transition (static -> IV1 and IV1 -> IV2):
- (a) support constraints stored versus referenced by any component, entries and
  canonical bytes, by constraint family;
- (b) next-interval chart groups (prepare_interval_partition's key) whose member
  pieces all satisfy each candidate emptiness property, with their components,
  chart literals and carried-constraint bytes.
No geometry is evaluated here; no Atlas module is imported. Writes one JSON
evidence file (exclusive create) and prints a summary.
"""
from collections import Counter, defaultdict
from fractions import Fraction as Q
from hashlib import sha256
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawstore import RawStore  # noqa: E402

CAPTURE_SHA = 'e761ff8c0a030299d8bc1f666d050418cdfa8c68e670f0a26487e8551f252add'
STORE_SHA = '3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899'
ROOT = '674ef5f3fcf41cb45e4b3e2ac2543e6ab0918b03f5a25dbc951363489a81bfad'
IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'


def enc(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def dq(pair):
    return Q(int(pair[0], 16), int(pair[1], 16))


def family(name):
    return name.split(':', 1)[0] if not name.startswith('carried:') else 'carried'


def depth(c):
    d = 0
    while c.get('kind') == 'snapshot-rotated':
        d += 1
        c = c['constraint']
    return d


def file_sha(path):
    h = sha256()
    with open(path, 'rb') as f:
        while block := f.read(1 << 22):
            h.update(block)
    return h.hexdigest()


def constraint_census(supports):
    """(a): stored vs referenced constraint entries and canonical bytes."""
    out = dict(supports=0, components=0, stored_entries=0, referenced_entries=0,
               support_record_bytes=0, support_record_bytes_without_unreferenced=0,
               constraint_bytes=0, referenced_constraint_bytes=0,
               unreferenced_by_family=Counter(), referenced_by_family=Counter(),
               unreferenced_bytes_by_family=Counter(), supports_with_unreferenced=0,
               max_stored_per_support=0, max_referenced_per_support=0)
    distinct_all, distinct_ref = set(), set()
    for s in supports:
        out['supports'] += 1
        out['components'] += len(s['components'])
        cons = s['constraints']
        used = {n for c in s['components'] for n, _ in c['constraints']}
        missing = used - set(cons)
        if missing:
            raise ValueError('component references a constraint the support does not store')
        out['stored_entries'] += len(cons)
        out['referenced_entries'] += len(used)
        out['max_stored_per_support'] = max(out['max_stored_per_support'], len(cons))
        out['max_referenced_per_support'] = max(out['max_referenced_per_support'], len(used))
        full = enc(s)
        out['support_record_bytes'] += len(full)
        trimmed = dict(s, constraints={k: v for k, v in cons.items() if k in used})
        out['support_record_bytes_without_unreferenced'] += len(enc(trimmed))
        if len(used) < len(cons):
            out['supports_with_unreferenced'] += 1
        for name, value in cons.items():
            e = enc(value)
            digest = sha256(e.encode()).digest()
            distinct_all.add(digest)
            out['constraint_bytes'] += len(e)
            fam = family(name)
            if name in used:
                out['referenced_constraint_bytes'] += len(e)
                out['referenced_by_family'][fam] += 1
                distinct_ref.add(digest)
            else:
                out['unreferenced_by_family'][fam] += 1
                out['unreferenced_bytes_by_family'][fam] += len(e)
    out['distinct_constraint_values'] = len(distinct_all)
    out['distinct_referenced_values'] = len(distinct_ref)
    for k in ('unreferenced_by_family', 'referenced_by_family', 'unreferenced_bytes_by_family'):
        out[k] = dict(sorted(out[k].items()))
    return out


def group_census(supports, cell_rows, carried_ids, label):
    """(b): next-interval chart groups and member emptiness properties."""
    groups = {}
    for s in supports:
        cons = s['constraints']
        layer = enc(s['radial_layer'])
        for c in s['components']:
            key = (s['source_chart_id'], tuple(map(str, c['partition_path'])), s['plate_id'], layer)
            g = groups.get(key)
            if g is None:
                lits = c['constraints']
                g = groups[key] = dict(members=[], literals=len(lits),
                    literal_bytes=sum(len(enc(cons[n])) for n, _ in lits),
                    depth=Counter(depth(cons[n]) + 1 for n, _ in lits), voxels=set())
            g['members'].append(c['logical_cell_id'])
            g['voxels'].add(tuple(s['voxel_index']))
    props = ('inactive', 'true_end_zero', 'true_start_zero', 'true_both_zero', 'booked_both_zero',
             'not_carried')
    tally = {p: Counter() for p in props}
    unknown = 0
    for key, g in groups.items():
        flags = {p: True for p in props}
        for cid in g['members']:
            row = cell_rows.get(cid)
            if row is None:
                unknown += 1
                flags = {p: False for p in props}
                break
            te = dq(row['true_end_volume_bounds_m3'][1])
            ts = dq(row['true_start_volume_bounds_m3'][1])
            be = dq(row['end_volume_bounds_m3'][1]) if 'end_volume_bounds_m3' in row else None
            flags['inactive'] &= row['_inactive']
            flags['true_end_zero'] &= te == 0
            flags['true_start_zero'] &= ts == 0
            flags['true_both_zero'] &= te == 0 and ts == 0
            flags['booked_both_zero'] &= dq(row['start_volume_m3']) == 0 and dq(row['end_volume_m3']) == 0
            flags['not_carried'] &= cid not in carried_ids
            del be
        for p in props:
            if flags[p]:
                t = tally[p]
                t['groups'] += 1
                t['members'] += len(g['members'])
                t['chart_literals'] += g['literals']
                t['chart_literal_bytes'] += g['literal_bytes']
                t['voxel_slots'] += len(g['voxels'])
    total = Counter()
    for g in groups.values():
        total['groups'] += 1
        total['members'] += len(g['members'])
        total['chart_literals'] += g['literals']
        total['chart_literal_bytes'] += g['literal_bytes']
        total['voxel_slots'] += len(g['voxels'])
    depths = Counter()
    for g in groups.values():
        depths.update(g['depth'])
    return dict(label=label, totals=dict(total), next_literal_depths=dict(sorted(depths.items())),
                by_property={p: dict(t) for p, t in tally.items()}, unmatched_groups=unknown,
                member_histogram=dict(sorted(Counter(len(g['members']) for g in groups.values()).items())))


def main():
    capture, store_path, out_path = map(Path, sys.argv[1:4])
    started = time.time()
    if out_path.exists():
        raise SystemExit('evidence output already exists')
    blob = capture.read_bytes()
    if sha256(blob).hexdigest() != CAPTURE_SHA:
        raise SystemExit('capture sha256 differs')
    data = json.loads(gzip.decompress(blob))
    del blob
    if file_sha(store_path) != STORE_SHA:
        raise SystemExit('store copy sha256 differs')
    store = RawStore(store_path)
    snaps = store.snapshots()
    iv1_partition_bytes = store.record_bytes(snaps[IV1], snaps[IV1]['metadata']['differential_partition']['record_blobs']['partition'])
    iv1_from_store = json.loads(iv1_partition_bytes)
    # The capture's partition/supports must be the store's accepted IV1 partition.
    # The store record carries one extra key, its own partition_id.
    same = (iv1_from_store['supports'] == data['supports'] and
            {k: v for k, v in iv1_from_store.items() if k not in ('supports', 'partition_id')} ==
            data['partition'])
    if not same:
        raise SystemExit('capture differs from the store IV1 partition')
    iv1_partition_id = iv1_from_store['partition_id']
    del iv1_from_store, iv1_partition_bytes
    graph = store.record(snaps[IV1], snaps[IV1]['metadata']['exterior_advance']['record_blobs']['graph'])
    if graph['partition_id'] != iv1_partition_id:
        raise SystemExit('IV1 graph belongs to another partition')
    cell_rows = {}
    for row in graph['cells']:
        cell_rows[row['cell_id']] = dict(row, _inactive=False)
    for row in graph['inactive_zero_measure_cells']:
        cell_rows[row['cell_id']] = dict(row, _inactive=True)
    graph_meta = dict(graph_id=graph.get('graph_id'), partition_id=graph['partition_id'],
                      interval_id=graph['interval_id'], cells=len(graph['cells']),
                      inactive=len(graph['inactive_zero_measure_cells']))
    del graph
    state = store.record(snaps[IV1], snaps[IV1]['metadata']['exterior_state']['record_blobs']['state'])
    carried_ids = {c['cell_id'] for c in state['cells']}
    del state
    static = store.record(snaps[ROOT], snaps[ROOT]['metadata']['differential_partition']['record_blobs']['partition'])
    store.close()

    iv1_supports = data['supports']
    result = dict(schema='atlas.private.geometry-growth-count.r1', scope='READ-ONLY structural census; no geometry evaluated',
                  capture_sha256=CAPTURE_SHA, store_copy_sha256=STORE_SHA, iv1_graph=graph_meta,
                  iv1_carried_state_cells=len(carried_ids))
    # Pieces per IV1 component classification (whole-IV1 view).
    cls = Counter()
    for cid, row in cell_rows.items():
        te = dq(row['true_end_volume_bounds_m3'][1]); ts = dq(row['true_start_volume_bounds_m3'][1])
        tel = dq(row['true_end_volume_bounds_m3'][0]); tsl = dq(row['true_start_volume_bounds_m3'][0])
        cls['inactive' if row['_inactive'] else 'active'] += 1
        cls['true_end_upper_zero'] += te == 0
        cls['true_start_upper_zero'] += ts == 0
        cls['true_both_upper_zero'] += te == 0 and ts == 0
        cls['true_end_lower_positive'] += tel > 0
        cls['true_start_lower_positive'] += tsl > 0
        cls['inactive_and_true_end_zero'] += row['_inactive'] and te == 0
        cls['inactive_and_true_both_zero'] += row['_inactive'] and te == 0 and ts == 0
        cls['carried_state'] += cid in carried_ids
    result['iv1_piece_classes'] = dict(cls)
    # (a) on IV1 supports (produced by static -> IV1).
    result['a_iv1_supports'] = constraint_census(iv1_supports)
    # (a) on the static partition supports (start state; reference only).
    result['a_static_supports_reference'] = constraint_census(static['supports'])
    # (b) IV1 -> IV2: chart groups from IV1 pieces.
    result['b_iv1_to_iv2'] = group_census(iv1_supports, cell_rows, carried_ids, 'IV1 pieces seeding IV2 charts')
    # (b) static -> IV1: static pieces seed IV1 charts. A static piece's start
    # region is its identity child's start region; use the child's true start.
    child_of = {r['parent_cell_id']: r['cell_id'] for r in data['partition']['identity_start_cells']}
    static_rows = {}
    for s in static['supports']:
        for c in s['components']:
            child = child_of.get(c['logical_cell_id'])
            row = cell_rows.get(child)
            if row is None:
                continue
            ts = row['true_start_volume_bounds_m3']
            static_rows[c['logical_cell_id']] = dict(true_end_volume_bounds_m3=ts, true_start_volume_bounds_m3=ts,
                start_volume_m3=row['start_volume_m3'], end_volume_m3=row['start_volume_m3'],
                _inactive=dq(row['start_volume_m3']) == 0)
    result['static_pieces'] = dict(total=sum(len(s['components']) for s in static['supports']),
        with_identity_child=len(static_rows),
        start_upper_zero=sum(dq(r['true_start_volume_bounds_m3'][1]) == 0 for r in static_rows.values()),
        start_booked_zero=sum(dq(r['start_volume_m3']) == 0 for r in static_rows.values()))
    result['b_static_to_iv1'] = group_census(static['supports'], static_rows, set(),
        'static pieces seeding IV1 charts (start region only; static has no interval)')
    result['seconds'] = round(time.time() - started, 3)
    with out_path.open('x', encoding='utf8', newline='\n') as f:
        json.dump(result, f, indent=1, sort_keys=True)
        f.write('\n')
    print(json.dumps(result, indent=1, sort_keys=True)[:12000])


if __name__ == '__main__':
    main()
