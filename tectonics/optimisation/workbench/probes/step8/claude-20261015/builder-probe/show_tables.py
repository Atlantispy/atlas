"""Print compact tables from result.json (read-only)."""
import json
from pathlib import Path

r = json.loads((Path(__file__).resolve().parent/'result.json').read_text(encoding='utf8'))
a = r['analysis']
CATS = ('tokens', 'nodes', 'integers', 'floats', 'ids', 'pairs', 'shapes')
rows = list(a['slices'])
if 'whole_graph_measured' in a and 'booked' in a['whole_graph_measured']:
    rows.append(a['whole_graph_measured'])
print('status', r['status'], 'elapsed', round(r['elapsed_seconds_total']), 'sources_unchanged', r['sources_unchanged'],
      'peak_wset', r['process_peak_wset'])
print('input', r['input'])
print('sources', json.dumps(r['sources_before'], indent=0))
for v in rows:
    print('\n==', v['name'], 'rows', v['rows'], 'bytes', v['canonical_bytes'], 'refused', v['refused'])
    c = v['counts']
    print(' counts', {k: c[k] for k in ('nodes', 'edges', 'tokens', 'token_encoded_bytes', 'token_input_chars', 'integers',
                                        'integer_magnitude_bytes', 'floats', 'ids', 'pairs', 'shapes', 'shape_keys')})
    print(' kinds', c['node_kinds'])
    b, t = v['booked'], v['retained']
    print(' BOOKED', {k: b[k] for k in b})
    print(' RETAINED', {k: t[k] for k in t})
    print(' ratio booked/retained', {k: (round(x, 2) if x else None) for k, x in v['ratio_booked_over_retained'].items()})
    print(' peak_booked/tracemalloc', round(v['ratio_peak_booked_over_tracemalloc'], 2),
          'held/tracemalloc', round(v['ratio_held_booked_over_tracemalloc'], 2))
    print(' per item', {k: (round(x, 1) if x else None) for k, x in v['per_item'].items()})
    print(' token_index keys', v['token_index_keys'], 'pinned input bytes', v['pinned_input_objects_bytes'])
    print(' untraced', v['untraced'])
    print(' finish', v.get('finish'))
    print(' decode', v.get('decode'))
print('\nFITS')
for k, f in a['receipt_row_fits_A']['fits'].items():
    print(f' {k:28s} slope/row {f["slope_per_row"]:12.1f} intercept {f["intercept"]:14.0f} r2 {f["r2"]:.5f}')
print('\nPROJECTION', json.dumps(a['projection_whole_graph_extrapolated'], indent=0))
print('\nDECODE FULL', json.dumps(a.get('decode_full'), indent=0))
w = r['whole_graph_uncapped']
print('\nWHOLE label', w['label'], 'cap_restored', w.get('cap_restored'))
print(' untraced exact', w['untraced'].get('exact'), 'add_s', w['untraced']['add_seconds'], 'mem_delta', w['untraced']['mem_delta_after_add'])
print(' untraced finish', w['untraced'].get('finish'))
print(' untraced released', w['untraced'].get('released'))
print(' traced exact', w['traced'].get('exact'), 'released', w['traced'].get('released'))
print(' traced instrument', json.dumps(w['traced']['instrument'], indent=0))
print(' traced formula', w['traced']['formula'])
print(' traced tracemalloc', w['traced']['tracemalloc_add'])
print(' traced sites')
for s in w['traced']['retained_by_allocation_site'][:22]:
    print('   ', s)
f = w['traced'].get('finish', {})
print(' traced finish', {k: v for k, v in f.items() if k != 'per_array'})
print(' per_array', {k: v['nbytes'] for k, v in f.get('per_array', {}).items()})
print(' deep tables')
for k, v in w['traced']['deep_tables'].items():
    print('   ', k, v)
