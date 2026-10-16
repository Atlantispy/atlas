"""Compare guarded owner arms: exactness first, then matched costs.

Usage: python -B compare_guarded_routes.py OUT.json DIR [DIR ...]
Each DIR is an R/probes/step8/owner-guarded-* run (prepare.json, owner.json and
records/*.json streamed from the committed store).

Exactness rules (exit 1 on any violation):
- every arm PASS, cleanup PASS, retained 0, committed arrays lossless, and
  the route switch took effect as labelled (payload types, settings);
- all arms share identical composition layout, compact source, fixture and
  guard bytes;
- every numeric, heat, native and committed array family, the counts, the
  graph/transport/mesh identities and the graph/transport records are equal
  across ALL arms (these do not bind the heat issuer's loaded identity);
- arms with the same captured loaded identity are equal in everything;
- across different loaded identities, each differing record is diffed field
  by field: every differing leaf must be a 64-hex identifier or lie under a
  loaded_dependencies descriptor; anything else is a violation.
Costs are then reported per arm and per route (mean and min-max over repeats,
so the repeat spread shows machine noise).
"""
import json
import re
import statistics
import sys
from pathlib import Path

ALWAYS_EQUAL = ('numeric_arrays', 'heat_arrays', 'native_arrays', 'committed_arrays', 'counts')
ROUTE_FREE_IDS = ('graph', 'transport', 'mesh')
ROUTE_FREE_RECORDS = ('graph', 'transport')
HEX64 = re.compile(r'[0-9a-f]{64}')
MAX_PATHS = 40
# The only fields allowed to differ between arms whose captured loaded
# identity differs: the provenance chain loaded identity -> heat call ->
# heat result -> collar state -> spatial state -> exchange. A 64-hex value
# differing anywhere else (for example a reordered cell row) is a violation.
PROVENANCE_PATHS = {
    'heat': ('/call_id', '/result_id', '/loaded_dependency_identity', '/checkpoint/invocation',
             '/checkpoint/metadata/bindings/[a-z_]+', '/checkpoint/metadata/result_id',
             '/checkpoint/metadata/metadata_sha256', '/checkpoint/metadata/field_payload/root_key/snapshot_key',
             '/checkpoint/metadata/ledger/root_key/snapshot_key', '/checkpoint/metadata/ledger/merkle_root',
             '/checkpoint/metadata/ledger/identity/sha256', '/checkpoint/metadata/ledger/array_bindings/digest',
             '/checkpoint/metadata/ledger/array_bindings/root_key/snapshot_key'),
    'exchange': ('/collar_state_id', '/joined_heat_id', '/result_id', '/state_id'),
    'state': ('/collar_state_id', '/state_id')}


def load(directory):
    directory = Path(directory)
    plan = json.loads((directory/'prepare.json').read_text(encoding='utf8'))
    result = json.loads((directory/'owner.json').read_text(encoding='utf8'))
    if 'settings' not in plan:
        # prepare v1 (route + small_import_bytes), before the generic switches.
        settings = ({'live_composite.ENABLED': 0, 'spatial_record_recipes.SMALL_IMPORT_BYTES': 1 << 62}
                    if plan['route'] == 'old' else {})
        if plan.get('small_import_bytes') is not None:
            settings['spatial_record_recipes.SMALL_IMPORT_BYTES'] = plan['small_import_bytes']
        plan['settings'] = settings
        plan['label'] = 'v1:'+(','.join(k+'='+str(v) for k, v in sorted(settings.items())) or 'step8-defaults')
        result.setdefault('applied_settings', settings)
    label = plan['label']
    loaded = (result.get('loaded_identity') or {}).get('identity')
    return {'dir': str(directory), 'path': directory, 'label': label, 'plan': plan, 'result': result,
            'loaded': loaded}


def leaf_diffs(a, b, path=''):
    """Yield (path, a, b) for differing leaves; structural changes are leaves."""
    if type(a) is dict and type(b) is dict:
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                yield path+'/'+key, a.get(key, '<absent>'), b.get(key, '<absent>')
            else:
                yield from leaf_diffs(a[key], b[key], path+'/'+key)
    elif type(a) is list and type(b) is list and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from leaf_diffs(x, y, path+'/'+str(index))
    elif a != b or type(a) is not type(b):
        yield path, a, b


def classify(kind, path, a, b):
    hex_pair = type(a) is str and type(b) is str and HEX64.fullmatch(a) and HEX64.fullmatch(b)
    if hex_pair and any(re.fullmatch(pattern, path) for pattern in PROVENANCE_PATHS.get(kind, ())):
        return 'loaded-identity' if path.endswith('loaded_dependencies') else 'provenance-id'
    return 'other'


def record_diff(first, arm, kind):
    a = json.loads((first['path']/'records'/(kind+'.json')).read_text(encoding='utf8'))
    b = json.loads((arm['path']/'records'/(kind+'.json')).read_text(encoding='utf8'))
    counts, paths = {}, []
    for path, x, y in leaf_diffs(a, b):
        cls = classify(kind, path, x, y)
        counts[cls] = counts.get(cls, 0)+1
        if cls == 'other' or len(paths) < MAX_PATHS:
            paths.append({'path': path, 'class': cls, 'first': repr(x)[:120], 'other': repr(y)[:120]})
    return {'counts': counts, 'paths': paths}


def stage_rows(result):
    rows = {}
    for row in result['checkpoints']:
        rows[row['stage']] = {'elapsed_seconds': row['elapsed_seconds'],
            'delta_seconds': row.get('delta', {}).get('seconds'),
            'reserved_bytes': row['ledger']['reserved_bytes'], 'peak_reserved_bytes': row['ledger']['peak_reserved_bytes'],
            'retained_bytes': row['retained']['retained_bytes'], 'peak_retained_bytes': row['retained']['peak_retained_bytes'],
            'rss_bytes': row['process']['rss_bytes'], 'private_bytes': row['process']['private_bytes'],
            'peak_wset_bytes': row['process']['peak_wset_bytes'],
            'job_peak_commit_bytes': (row.get('job') or {}).get('peak_job_commit_bytes'),
            'store_disk_bytes': row['sizes'].get('store_disk_bytes'),
            'sizes': {k: v for k, v in row['sizes'].items() if k != 'store_disk_bytes'}}
    return rows


def guardian_peaks(result):
    """Guardian samples: parent and whole-tree RSS peaks, and their phases."""
    resources = result.get('resources') or {}
    peaks = resources.get('sampled_peak_bytes') or {}
    by_phase = resources.get('sampled_peak_by_phase') or {}
    tree_phase = max(by_phase, key=lambda k: by_phase[k].get('process_tree_rss', 0), default=None)
    summary = (result.get('resource_summary') or {}).get('peaks') or {}
    return {'parent_rss_bytes': peaks.get('parent_rss'), 'process_tree_rss_bytes': peaks.get('process_tree_rss'),
            'tree_peak_phase_label': tree_phase,
            'parent_os_peak_working_set_bytes': summary.get('parent_os_peak_working_set_bytes'),
            'parent_os_peak_pagefile_bytes': summary.get('parent_os_peak_pagefile_bytes'),
            'process_tree_private_bytes_at_peak': summary.get('process_tree_private_bytes'),
            'process_count_at_peak': summary.get('process_count'),
            'least_available_ram_bytes': min((v.get('least_available_ram') for v in by_phase.values()
                                              if v.get('least_available_ram') is not None), default=None)}


def heat_workers(result):
    reports = result.get('heat_reports') or {}
    calls = (reports.get('parallel.report') or {}).get('calls') or []
    rows = []
    for call in calls:
        processes = call.get('processes') or []
        rows.append({'configured': call.get('configured'), 'faces': call.get('faces'),
                     'largest_worker_ledger_peak_bytes': call.get('largest_worker_ledger_peak_bytes'),
                     'worker_working_set_peaks_bytes': [p.get('working_set_peak_bytes') for p in processes],
                     'worker_private_peaks_bytes': [p.get('private_peak_bytes') for p in processes],
                     'worker_busy_seconds_max': max((p.get('busy_seconds') or 0 for p in processes), default=None)})
    return rows


def span(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {'mean': statistics.fmean(values), 'min': min(values), 'max': max(values), 'n': len(values)}


def check_arm(arm, problems):
    result = arm['result']
    if result.get('status') != 'PASS' or result.get('cleanup') != 'PASS' or result.get('retained_after_close_bytes') != 0:
        problems.append(arm['dir']+': not a clean PASS')
    if result.get('committed_arrays_lossless') is not True:
        problems.append(arm['dir']+': committed arrays not lossless')
    settings = result.get('route_settings', {})
    stages = {row['stage']: row['sizes'] for row in result.get('checkpoints', [])}
    graph_type = stages.get('closed-graph', {}).get('graph_payload')
    exchange_type = stages.get('joined-finish', {}).get('exchange_payload')
    composite = arm['plan']['settings'].get('live_composite.ENABLED', 1) == 1
    expected = 'LiveRecord' if composite else 'CompactRecord'
    applied = result.get('applied_settings', {})
    if settings.get('live_composite_enabled') != composite or graph_type != expected or \
            exchange_type != expected or set(applied) != set(arm['plan']['settings']):
        problems.append(arm['dir']+': switches not as labelled '+repr((applied, settings, graph_type, exchange_type)))


def compare_pair(first, arm, problems, diffs):
    for key in ('layout_hashes', 'c_source_sha256', 'fixture', 'guard_sha256'):
        if arm['plan'][key] != first['plan'][key]:
            problems.append(arm['dir']+': '+key+' differs from '+first['dir'])
    for key in ALWAYS_EQUAL:
        a, b = first['result'].get(key), arm['result'].get(key)
        if a != b:
            names = sorted(k for k in set(a or {}) | set(b or {}) if (a or {}).get(k) != (b or {}).get(k))
            problems.append(arm['dir']+': '+key+' differs '+repr(names[:12]))
    ids_a, ids_b = first['result']['identities'], arm['result']['identities']
    records_a, records_b = first['result']['logical_records'], arm['result']['logical_records']
    same_identity = first['loaded'] == arm['loaded']
    for name in sorted(set(ids_a) | set(ids_b)):
        if ids_a.get(name) != ids_b.get(name) and (same_identity or name in ROUTE_FREE_IDS):
            problems.append(arm['dir']+': identity '+name+' differs')
    for kind in sorted(set(records_a) | set(records_b)):
        if records_a.get(kind) == records_b.get(kind):
            continue
        if same_identity or kind in ROUTE_FREE_RECORDS:
            problems.append(arm['dir']+': record '+kind+' differs')
        diff = record_diff(first, arm, kind)
        diffs.append({'first': first['dir'], 'other': arm['dir'], 'kind': kind, **diff})
        if diff['counts'].get('other'):
            problems.append(arm['dir']+': record '+kind+' has non-identifier differences')


def main():
    out, directories = sys.argv[1], sys.argv[2:]
    arms = [load(d) for d in directories]
    problems, diffs = [], []
    for arm in arms:
        check_arm(arm, problems)
    for arm in arms[1:]:
        compare_pair(arms[0], arm, problems, diffs)
    report = {'arms': [{'dir': a['dir'], 'label': a['label'], 'loaded_identity': a['loaded'],
                        'measured_seconds': a['result'].get('measured_seconds'),
                        'reread_seconds': a['result'].get('reread_seconds'),
                        'descriptors_v2': {k: v['v2'] for k, v in a['result'].get('descriptors', {}).items()},
                        'store_disk_bytes': a['result'].get('store_disk_bytes'),
                        'ledger_after_close': a['result'].get('ledger_after_close'),
                        'guardian': guardian_peaks(a['result']), 'heat_workers': heat_workers(a['result']),
                        'stages': stage_rows(a['result'])} for a in arms],
              'exactness_problems': problems, 'record_field_diffs': diffs,
              'rules': {'always_equal': ALWAYS_EQUAL, 'route_free_identities': ROUTE_FREE_IDS,
                        'route_free_records': ROUTE_FREE_RECORDS}}
    labels = sorted({a['label'] for a in arms})
    names = [row['stage'] for row in arms[0]['result']['checkpoints']]
    by_route = {}
    for label in labels:
        group = [a for a in report['arms'] if a['label'] == label]
        route = {'repeats': len(group), 'measured_seconds': span([a['measured_seconds'] for a in group]),
                 'reread_seconds': span([a['reread_seconds'] for a in group]),
                 'guardian_parent_rss_bytes': span([a['guardian']['parent_rss_bytes'] for a in group]),
                 'guardian_process_tree_rss_bytes': span([a['guardian']['process_tree_rss_bytes'] for a in group]),
                 'parent_os_peak_pagefile_bytes': span([a['guardian']['parent_os_peak_pagefile_bytes'] for a in group]),
                 'final_store_disk_bytes': span([sum((a['store_disk_bytes'] or {}).values()) for a in group]),
                 'stages': {}}
        for name in names:
            route['stages'][name] = {field: span([a['stages'].get(name, {}).get(field) for a in group])
                                     for field in ('delta_seconds', 'reserved_bytes', 'peak_reserved_bytes',
                                                   'retained_bytes', 'peak_retained_bytes', 'private_bytes',
                                                   'peak_wset_bytes', 'job_peak_commit_bytes', 'store_disk_bytes')}
        by_route[label] = route
    report['by_route'] = by_route
    Path(out).write_text(json.dumps(report, indent=1, sort_keys=True), encoding='utf8')
    print('exactness problems:', len(problems))
    for problem in problems:
        print('  ', problem)
    for diff in diffs:
        print('record diff', diff['kind'], Path(diff['other']).name, diff['counts'])
    for label, route in by_route.items():
        m = route['measured_seconds']
        p, t = route['guardian_parent_rss_bytes'], route['guardian_process_tree_rss_bytes']
        print(label, 'repeats', route['repeats'], 'measured s mean %.3f [%.3f, %.3f]' % (m['mean'], m['min'], m['max'])
              if m else '', 'parent rss peak %.1f MB' % (p['mean']/1e6) if p else '',
              'tree rss peak %.1f MB' % (t['mean']/1e6) if t else '')
    print('stage'.ljust(30), *[label.rjust(26) for label in labels])
    for name in names:
        cells = []
        for label in labels:
            row = by_route[label]['stages'][name]
            d, p, r = row['delta_seconds'], row['peak_reserved_bytes'], row['retained_bytes']
            cells.append(('%.3fs' % d['mean'] if d else '-').rjust(8)+(' %6.1fMB' % (p['mean']/1e6) if p else '').rjust(10)
                         +(' %6.2fMB' % (r['mean']/1e6) if r else '').rjust(9))
        print(name.ljust(30), *[c.rjust(26) for c in cells])
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
