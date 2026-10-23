"""Bounded exactness controls for repeated donor work; no timings or stages."""
import argparse
import ast
import copy
from collections import Counter
from contextlib import nullcontext
from fractions import Fraction as Q
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

if sys.flags.optimize:
    raise SystemExit('assertions required')

SUPPORT_PIN = 'd08ad403068a7f5e8690c4e3959a038f584e50a67f836537ad356ef2e2f25f0a'
SPATIAL_REL = Path('tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_spatial_pressure.py')
SPATIAL_PIN = '1f4f50ccb08eaeeab2a52c30dce033aa4b1fb07273a59ebd619d89f233c33712'
DIFFERENTIAL_REL = Path('tectonics/optimisation/pending/pressure/c/full/src/atlas_tectonics/integration_differential_pressure.py')
DIFFERENTIAL_PIN = 'e01a7af268de50560f631dce4ea3b69163e1a6bcc63c436bb18001bb579c4e4b'


def donor_callback(tree, namespace, candidate):
    owner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_integrate_radial_pressure')
    callback = copy.deepcopy(next(n for n in ast.walk(owner) if isinstance(n, ast.FunctionDef) and n.name == 'evaluate'))
    if candidate:
        profile_index, profile_loop = next((i, n) for i, n in enumerate(callback.body)
                                          if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == 'profiles')
        assert len(profile_loop.body) == 5
        profile_helper = ast.parse('def profile_contribution(bottom, top, rho, ptop):\n    pass').body[0]
        profile_helper.body = copy.deepcopy(profile_loop.body[:3])
        assert isinstance(profile_helper.body[1], ast.If) and isinstance(profile_helper.body[1].body[0], ast.Continue)
        profile_helper.body[1].body = [ast.Return(value=ast.Constant(value=None))]
        profile_helper.body += ast.parse('return value, selected, ordered').body
        profile_body = ast.parse('''
profile_key = (bottom, top, rho, ptop)
if profile_key in profile_cache:
    profile_saved = profile_cache[profile_key]
    PROFILE_CACHE_COUNTS['hits'] += 1
else:
    profile_saved = profile_contribution(*profile_key)
    PROFILE_CACHE_COUNTS['misses'] += 1
    if len(profile_cache) < 8:
        profile_cache[profile_key] = profile_saved
        PROFILE_CACHE_COUNTS['peak_entries'] = max(PROFILE_CACHE_COUNTS['peak_entries'], len(profile_cache))
if profile_saved is None:
    continue
value, selected, ordered = profile_saved
''').body
        profile_loop.body = profile_body + profile_loop.body[3:]
        callback.body[profile_index:profile_index] = [profile_helper, *ast.parse('profile_cache = {}').body]
        index, loop = next((i, n) for i, n in enumerate(callback.body)
                           if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == 'rows')
        assert len(loop.body) == 6
        helper = ast.parse('def donor_contribution(entry, exit_, bottom, top):\n    pass').body[0]
        helper.body = copy.deepcopy(loop.body[:4])
        assert isinstance(helper.body[1], ast.If) and isinstance(helper.body[1].body[0], ast.Continue)
        helper.body[1].body = [ast.Return(value=ast.Constant(value=None))]
        helper.body += ast.parse('return value, selected, ordered').body
        setup = ast.parse('donor_cache = {}').body
        candidate_body = ast.parse('''
key = (entry, exit_, bottom, top)
if key in donor_cache:
    saved = donor_cache[key]
    CACHE_COUNTS['hits'] += 1
else:
    saved = donor_contribution(*key)
    CACHE_COUNTS['misses'] += 1
    if len(donor_cache) < 8:
        donor_cache[key] = saved
        CACHE_COUNTS['peak_entries'] = max(CACHE_COUNTS['peak_entries'], len(donor_cache))
if saved is None:
    continue
value, selected, ordered = saved
''').body
        loop.body = candidate_body + loop.body[4:]
        callback.body[index:index] = [helper, *setup]
    module = ast.fix_missing_locations(ast.Module(body=[callback], type_ignores=[]))
    exec(compile(module, '<pinned-donor-callback>', 'exec'), namespace)
    return namespace['evaluate']


def main(args):
    assert hashlib.sha256(args.support_probe.read_bytes()).hexdigest() == SUPPORT_PIN
    spec = importlib.util.spec_from_file_location('cross_evaluator_support', args.support_probe)
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    support.SOURCE = args.repo / support.COUPLING_REL
    support.O_SOURCE = args.repo / support.OVERLAP_REL
    baseline, candidate = support.build_source(), support.build_source()
    tree = ast.parse(support.SOURCE.read_bytes())
    a, b = (Q(2), Q(1), Q(3)), (Q(-1), Q(4), Q(2))
    normal = baseline['O']._cross(a, b)
    profiles = ((Q(1), Q(4), Q(3, 7), Q(2, 3), Q(1, 2)),
                (Q(4), Q(20), Q(5, 11), Q(1, 13), Q(1, 2)))
    for ns in (baseline, candidate):
        ns.update(a=a, b=b, normal=normal, profiles=profiles, rc=Q(1), outer=Q(20), gravity=Q(7, 5))
    counts = Counter()
    profile_counts = Counter()
    candidate['CACHE_COUNTS'] = counts
    candidate['PROFILE_CACHE_COUNTS'] = profile_counts
    old = donor_callback(tree, baseline, False)
    new = donor_callback(tree, candidate, True)
    poly = ((Q(1), Q(1)), (Q(4), Q(1)), (Q(4), Q(3)), (Q(1), Q(3)))
    spatial_raw = (args.repo / SPATIAL_REL).read_bytes()
    assert hashlib.sha256(spatial_raw).hexdigest() == SPATIAL_PIN
    assert hashlib.sha256((args.repo / DIFFERENTIAL_REL).read_bytes()).hexdigest() == DIFFERENTIAL_PIN
    donor_branch = next(n for n in ast.walk(ast.parse(spatial_raw))
                        if isinstance(n, ast.If) and ast.unparse(n.test) == 'exact_rays or strips is not None')
    construction = ast.parse('def construct(active, profiles, strips, rc, outer, gravity):\n    pass').body[0]
    construction.body = copy.deepcopy(donor_branch.body[:3]) + ast.parse('return radial_profiles, tuple(donors)').body
    construct_ns = dict(Q=Q)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[construction], type_ignores=[])),
                 '<pinned-spatial-donor-construction>', 'exec'), construct_ns)
    # D passes (profile, profile), one mantle band. A native crossing voxel
    # has side=None and exact half-weights on both sides; see source proof.
    selected_profile = ((Q(1), Q(20), Q(3300), Q(0)),)
    selected_profiles, selected_donors = construct_ns['construct'](
        [dict(poly=poly, weights=((0, (Q(1, 2),)*2), (1, (Q(1, 2),)*2)),
              density=Q(3301), radial=(Q(1), Q(20)))],
        (selected_profile, selected_profile), None, Q(1), Q(20), Q(7, 5))
    assert len(selected_donors) == 2 and selected_donors[0] == selected_donors[1]
    wedges = baseline['_angular_wedges'](poly)
    summaries = []
    totals_old, totals_new = Counter(), Counter()
    for bits in ((96,) if args.selected_only else (96, 160)):
        baseline['_JET_PRECISION'].set(bits)
        candidate['_JET_PRECISION'].set(bits)
        for wi, (left, right, entry, exit_) in enumerate(wedges[:1] if args.selected_only else wedges):
            same = (entry, exit_, Q(2), Q(12))
            cases = {
                'selected-native-two-sides': tuple((entry, exit_, low, high, coefficient)
                                                   for _, low, high, coefficient in selected_donors),
                'duplicate-opposite-coefficients': ((*same, Q(3, 7)), (*same, Q(-3, 7))),
                'separated-duplicate': ((*same, Q(3, 7)), (entry, exit_, Q(5), Q(6), Q(2)), (*same, Q(-2, 5))),
                'bounded-overflow': tuple((entry, exit_, Q(2+i), Q(3+i), Q(i+1)) for i in range(10)) + ((*same, Q(1)),),
                'empty-repeated': ((entry, exit_, Q(100), Q(110), Q(1)), (entry, exit_, Q(100), Q(110), Q(-1))),
            }
            for label, rows in cases.items():
                if args.selected_only and label != 'selected-native-two-sides':
                    continue
                baseline['profiles'] = candidate['profiles'] = selected_profiles if label == 'selected-native-two-sides' else profiles
                for midpoint in (False, True):
                    lo, hi = ((left+right)/2,)*2 if midpoint else (left, right)
                    call = (lo, hi, ((entry, exit_), rows), bits)
                    support.OPS.clear()
                    expected = old(*call)
                    original_ops = support.OPS.copy()
                    support.OPS.clear()
                    actual = new(*call)
                    new_ops = support.OPS.copy()
                    assert actual == expected, (bits, wi, label, midpoint)
                    totals_old.update(original_ops)
                    totals_new.update(new_ops)
                    summaries.append(dict(bits=bits, wedge=wi, case=label, midpoint=midpoint,
                                          fixed=actual[1], exact_full_jets=True,
                                          baseline_operations=dict(original_ops), candidate_operations=dict(new_ops)))
    if args.selected_only:
        # A deliberate same-bounds/different-physics control: the cache key
        # must retain both rho and ptop, even when radial geometry is equal.
        changed_profiles = (selected_profiles[0], (*selected_profiles[1][:2], Q(3302), Q(3), selected_profiles[1][4]))
        baseline['profiles'] = candidate['profiles'] = changed_profiles
        hits_before = profile_counts['hits']
        assert old(*call) == new(*call)
        assert profile_counts['hits'] == hits_before
        # Refute merging the two equal weights: it removes outward rounds.
        baseline['_JET_PRECISION'].set(3)
        witness = ((Q(1, 8), Q(1, 8)), (Q(1), Q(1)), (Q(0), Q(0)))
        separate = baseline['_jet_add'](baseline['_jet_scale'](witness, Q(1, 2)),
                                        baseline['_jet_scale'](witness, Q(1, 2)))
        merged = baseline['_jet_scale'](witness, Q(1))
        assert separate[0] == (Q(0), Q(1, 4)) and merged[0] == (Q(1, 8), Q(1, 8))
        result = dict(schema='plan40a-cross-evaluator-selected-v1', verdict='PASS', synthetic_fixture=True,
                      source_sha256=support.PIN, spatial_source_sha256=SPATIAL_PIN,
                      differential_source_sha256=DIFFERENTIAL_PIN, support_probe_sha256=SUPPORT_PIN,
                      scope='two counted full-jet callbacks plus unequal-profile and coefficient-merging controls; no timing, stage or resource acceptance',
                      cases=summaries, bounded_donor_cache=dict(counts), bounded_profile_cache=dict(profile_counts),
                      same_bounds_different_rho_ptop_control=True,
                      coefficient_merging_refuted=dict(separate=list(map(str, separate[0])), merged=list(map(str, merged[0]))))
        args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
        return
    assert counts['hits'] > 0 and counts['peak_entries'] == 8
    # Fault: omitted radial bound would alias distinct integrals. Both pairs
    # share polygon edges but use different shell bounds and must stay distinct.
    ns = baseline
    left, right, entry, exit_ = wedges[0]
    middle = (left+right)/2
    s, _ = ns['_radial_chart_jets'](a, b, normal, middle, middle, 160)
    rlo, rhi, _, _ = ns['_radial_interval_jets'](s, middle, middle, entry, exit_, Q(1), Q(20))
    samples = []
    for low, high in ((Q(2), Q(12)), (Q(5), Q(6))):
        x, y, _, _ = ns['_radial_interval_jets'](s, middle, middle, entry, exit_, low, high)
        samples.append(ns['_donor_radial_pressure'](rlo, rhi, x, y))
    assert samples[0] != samples[1], 'fault fixture must reject edges-only key'
    # Two receivers, repeated donor shape across signed profile bands: reuse
    # only exact wedge tuples, retaining original event insertion/row ordering.
    donors = tuple((poly, Q(2+i), Q(3+i), Q((-1)**i, i+2)) for i in range(4))
    other = ((Q(1), Q(1)), (Q(2), Q(1)), (Q(2), Q(2)), (Q(1), Q(2)))
    prepared = []
    wedge_counts = []
    for cached in (False, True):
        ns = support.build_source()
        raw_wedges = ns['_angular_wedges']
        saved_wedges, count = {}, Counter()
        def get_wedges(shape):
            if cached and shape in saved_wedges:
                count['hits'] += 1
                return saved_wedges[shape]
            count['evaluations'] += 1
            value = raw_wedges(shape)
            if cached and len(saved_wedges) < 4:
                saved_wedges[shape] = value
            return value
        ns['_angular_wedges'] = get_wedges
        pieces = []
        def capture(rows, evaluate, coefficients, **kwargs):
            pieces.append((rows, tuple(coefficients(data) for _, _, data in rows)))
            return None
        ns['_integrate_angular'] = capture
        budget = types.SimpleNamespace(reserve=lambda *a, **kw: nullcontext())
        for receiver in (poly, other):
            ns['_integrate_radial_pressure'](receiver, a, b, profiles, donors, Q(1), Q(20), Q(7, 5),
                                            width=Q(1, 1000), max_leaves=100, budget=budget)
        prepared.append(pieces)
        wedge_counts.append(dict(count))
    assert prepared[0] == prepared[1]
    result = dict(schema='plan40a-cross-evaluator-probe-v1', verdict='PASS', synthetic_fixture=True,
                  source_sha256=support.PIN, vector_source_sha256=support.O_PIN, support_probe_sha256=SUPPORT_PIN,
                  spatial_source_sha256=SPATIAL_PIN, differential_source_sha256=DIFFERENTIAL_PIN,
                  selected_source_construction=dict(donor_rows=2, equal_rows=True, coefficient=str(selected_donors[0][3]),
                                                    scenario='native crossing voxel with nonzero anomaly and two identical mantle profiles'),
                  scope='full-jet donor callback and ordered partition exactness only; no timing, stage, resource or cancellation acceptance',
                  cases=len(summaries), cases_detail=summaries, bounded_donor_cache=dict(counts),
                  bounded_profile_cache=dict(profile_counts),
                  baseline_operations=dict(totals_old), candidate_operations=dict(totals_new),
                  deliberately_incomplete_edges_only_key_rejected=True,
                  paired_partition_exact=True, original_wedge_calls=wedge_counts[0], cached_wedge_calls=wedge_counts[1])
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases_detail'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--support-probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selected-only', action='store_true')
    main(parser.parse_args())
