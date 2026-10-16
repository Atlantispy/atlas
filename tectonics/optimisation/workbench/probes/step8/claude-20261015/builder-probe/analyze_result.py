"""Derive scaling fits and the whole-graph projection from result.json (in place).

Reads only result.json beside this file and rewrites it with an 'analysis'
section. Every derived number is labelled measured or extrapolated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE/'result.json'
ROWS_TOTAL = 48391
CATS = ('tokens', 'nodes', 'integers', 'floats', 'ids', 'pairs', 'shapes')


def fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs)/n, sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs)
    sxy = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    slope = sxy/sxx
    intercept = my-slope*mx
    ss_tot = sum((y-my)**2 for y in ys)
    ss_res = sum((y-(intercept+slope*x))**2 for x, y in zip(xs, ys))
    return dict(slope_per_row=slope, intercept=intercept, r2=1-ss_res/ss_tot if ss_tot else 1.0, points=n)


def view(s):
    """Flatten one measured builder run (traced + untraced) into comparable numbers."""
    t, u = s['traced'], s['untraced']
    inst = t['instrument']
    req = inst['arena_requested_by_site']
    groups = t['deep_groups']
    tables = t['deep_tables']
    counts = t['counts']
    booked = {c: req.get(c, 0) for c in CATS}
    booked['initial'] = req.get('initial', 0)
    booked['arena_chunk_overhead_and_free'] = inst['arena_booked']-inst['arena_requested_total']
    booked['arena_total_held'] = inst['arena_booked']
    booked['scratch_peak_live'] = inst['scratch_peak_live']
    booked['budget_peak'] = t['budget']['peak_reserved_bytes']
    booked['budget_held_after_add'] = t['budget']['reserved_bytes']
    retained = {c: groups[c] for c in CATS}
    retained['arena_owner_objects'] = groups['arena_owners']
    retained['deep_total_new'] = tables['total_new']
    retained['tracemalloc_after_add'] = t['tracemalloc_add']['retained_after_gc']
    retained['unattributed'] = t['unattributed_retained']
    retained['temporary_encoding_work'] = t['tracemalloc_add']['temporary_encoding_work']
    retained['tracemalloc_peak_during_add'] = t['tracemalloc_add']['peak']
    pinned = (tables['token_index']['keys']['preexisting_bytes']+tables['id_index']['keys']['preexisting_bytes']
              + tables['integer_index']['keys']['preexisting_bytes'])
    out = dict(name=s['name'], rows=s['rows'], canonical_bytes=s.get('canonical_bytes'),
               refused='refusal' in t, refusal=t.get('refusal'), counts=counts, booked=booked, retained=retained,
               pinned_input_objects_bytes=pinned,
               token_index_keys=dict(shared_input_bytes=tables['token_index']['keys']['preexisting_bytes'],
                                     shared_input_objects=tables['token_index']['keys']['preexisting_objects'],
                                     new_bytes=tables['token_index']['keys']['new_bytes'],
                                     new_objects=tables['token_index']['keys']['new_objects']),
               ratio_booked_over_retained={c: (booked[c]/retained[c] if retained[c] else None) for c in CATS},
               ratio_peak_booked_over_tracemalloc=booked['budget_peak']/retained['tracemalloc_after_add'],
               ratio_held_booked_over_tracemalloc=booked['budget_held_after_add']/retained['tracemalloc_after_add'],
               per_item=dict(
                   booked_per_token=booked['tokens']/counts['tokens'] if counts['tokens'] else None,
                   retained_per_token=retained['tokens']/counts['tokens'] if counts['tokens'] else None,
                   booked_per_node=booked['nodes']/counts['nodes'] if counts['nodes'] else None,
                   retained_per_node=retained['nodes']/counts['nodes'] if counts['nodes'] else None,
                   booked_per_integer=booked['integers']/counts['integers'] if counts['integers'] else None,
                   retained_per_integer=retained['integers']/counts['integers'] if counts['integers'] else None,
                   booked_per_id=booked['ids']/counts['ids'] if counts['ids'] else None,
                   retained_per_id=retained['ids']/counts['ids'] if counts['ids'] else None,
                   booked_per_pair=booked['pairs']/counts['pairs'] if counts['pairs'] else None,
                   retained_per_pair=retained['pairs']/counts['pairs'] if counts['pairs'] else None),
               untraced=dict(add_seconds=u['add_seconds'], mem_delta_after_add=u['mem_delta_after_add'],
                             budget_peak=u['budget_after_add']['peak_reserved_bytes'],
                             budget_held=u['budget_after_add']['reserved_bytes'],
                             exact=u.get('exact'), refused='refusal' in u))
    f = t.get('finish')
    if f:
        out['finish'] = dict(array_nbytes=f['array_nbytes'], metadata_bytes=f['metadata_bytes'],
                             finish_hold_requested=f['finish_hold_requested'],
                             booked_increase=f['booked_after']-f['booked_before'],
                             budget_peak_after_finish=f['budget_peak'],
                             tracemalloc_retained=f['tracemalloc_retained'],
                             tracemalloc_peak_above_start=f['tracemalloc_peak_above_start'],
                             transient_above_end=f['transient_above_end'])
    if 'decode_charge' in s:
        out['decode'] = dict(charge=s['decode_charge'], tracemalloc=s.get('decode_traced', {}).get('retained_bytes'),
                             deep_sizeof=s['decode_deep_sizeof']['bytes'],
                             rss_delta=s['decode_untraced']['delta'].get('rss'),
                             private_delta=s['decode_untraced']['delta'].get('private'))
        if out['decode']['tracemalloc']:
            out['decode']['charge_over_tracemalloc'] = out['decode']['charge']/out['decode']['tracemalloc']
    return out


def main():
    result = json.loads(PATH.read_text(encoding='utf8'))
    runs = [s for s in result['slices']]
    literal = result.get('literal_slices')
    if isinstance(literal, list):
        runs += literal
    views = [view(s) for s in runs if 'traced' in s]
    analysis = dict(slices=views)
    a = [v for v in views if v['name'].startswith('A') and not v['refused']]
    fits = {}
    if len(a) >= 2:
        xs = [v['rows'] for v in a]
        series = dict(budget_peak=[v['booked']['budget_peak'] for v in a],
                      budget_held_after_add=[v['booked']['budget_held_after_add'] for v in a],
                      tracemalloc_retained=[v['retained']['tracemalloc_after_add'] for v in a],
                      temporary_encoding_work=[v['retained']['temporary_encoding_work'] for v in a],
                      finish_array_nbytes=[v['finish']['array_nbytes'] for v in a if 'finish' in v],
                      tokens=[v['counts']['tokens'] for v in a], nodes=[v['counts']['nodes'] for v in a],
                      integers=[v['counts']['integers'] for v in a], ids=[v['counts']['ids'] for v in a],
                      pairs=[v['counts']['pairs'] for v in a],
                      decode_charge=[v['decode']['charge'] for v in a],
                      decode_tracemalloc=[v['decode']['tracemalloc'] for v in a])
        for c in CATS:
            series['booked_'+c] = [v['booked'][c] for v in a]
            series['retained_'+c] = [v['retained'][c] for v in a]
        fits = {k: fit(xs, ys) for k, ys in series.items() if len(ys) == len(xs)}
    analysis['receipt_row_fits_A'] = dict(label='measured slopes over A slices (scalar base + first N receipts)',
                                          fits=fits)
    b = next((v for v in views if v['name'] == 'B-nonreceipt'), None)
    proj = dict(label='EXTRAPOLATED: B (measured non-receipt part) + A-slope x 48,391 receipt rows; '
                      'linear in rows, ignores cross-part dedup (slight overestimate of both booking and retention)')
    if fits and b is not None and not b['refused']:
        for key, bkey, rkey in (('budget_peak', 'budget_peak', None), ('budget_held_after_add', 'budget_held_after_add', None),
                                ('tracemalloc_retained', None, 'tracemalloc_after_add')):
            base = b['booked'][bkey] if bkey else b['retained'][rkey]
            proj[key] = base+fits[key]['slope_per_row']*ROWS_TOTAL
        proj['receipts_only_budget_held'] = fits['budget_held_after_add']['intercept']+fits['budget_held_after_add']['slope_per_row']*ROWS_TOTAL
        proj['receipts_only_tracemalloc'] = fits['tracemalloc_retained']['intercept']+fits['tracemalloc_retained']['slope_per_row']*ROWS_TOTAL
        proj['finish_array_nbytes'] = b['finish']['array_nbytes']+fits['finish_array_nbytes']['slope_per_row']*ROWS_TOTAL if 'finish' in b else None
        proj['booked_over_retained'] = proj['budget_held_after_add']/proj['tracemalloc_retained']
    elif b is not None and b['refused']:
        proj['note'] = 'B refused under the real cap; see whole_graph_uncapped for the measured whole graph'
    analysis['projection_whole_graph_extrapolated'] = proj
    whole = result.get('whole_graph_uncapped', {})
    if 'traced' in whole and 'tracemalloc_add' in whole['traced']:
        w = view(dict(name='D-whole-uncapped', rows=ROWS_TOTAL, canonical_bytes=result['input']['bytes'],
                      traced=whole['traced'], untraced=whole['untraced']))
        w['label'] = ('MEASURED with probe-only in-process MAX_BUILD_BYTES raise; booking is what the current '
                      'formulas would charge, retention is real tracemalloc/getsizeof')
        analysis['whole_graph_measured'] = w
    elif 'untraced' in whole:
        u = whole['untraced']
        analysis['whole_graph_measured'] = dict(
            label='MEASURED untraced only (probe-only cap raise); no tracemalloc retention',
            budget_peak=u['budget_after_add']['peak_reserved_bytes'], budget_held=u['budget_after_add']['reserved_bytes'],
            counts=u['counts'], exact=u.get('exact'), add_seconds=u['add_seconds'],
            mem_delta_after_add=u['mem_delta_after_add'], finish=u.get('finish'))
    d = result['decode']
    if 'full_charge' in d:
        analysis['decode_full'] = dict(charge=d['full_charge']['charge_bytes'],
                                       tracemalloc=d.get('full_traced', {}).get('retained_bytes'),
                                       rss_delta=d['full_untraced']['delta'].get('rss'),
                                       private_delta=d['full_untraced']['delta'].get('private'),
                                       deep_sizeof=d['full_deep_sizeof']['bytes'], ratios=d.get('full_ratios'))
    result['analysis'] = analysis
    tmp = PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, indent=1, sort_keys=True, default=str)+'\n', encoding='utf8')
    os.replace(tmp, PATH)
    print(json.dumps(analysis, indent=1, default=str)[:20000])


if __name__ == '__main__':
    main()
