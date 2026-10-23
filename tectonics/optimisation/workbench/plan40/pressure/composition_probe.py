"""Bounded synthetic composition controls; no stage, timing or resource proof."""
import sys

if not __debug__:
    raise SystemExit('composition probe requires assertions enabled')

import argparse
import ast
from collections import Counter
import copy
from fractions import Fraction as Q
import hashlib
import importlib.util
import json
from pathlib import Path

SUPPORT_PIN = 'd08ad403068a7f5e8690c4e3959a038f584e50a67f836537ad356ef2e2f25f0a'
CACHE_PIN = '31b64320a5595caabc060cbb27924e1927616d666bbdc78263c790d436fcf198'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_helper(name, path, pin):
    require(digest(path) == pin, 'helper identity mismatch: ' + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def factory(cache, path, fault):
    if not fault:
        return cache.donor_callback
    tree = ast.parse(path.read_bytes())
    node = copy.deepcopy(next(n for n in tree.body
                              if isinstance(n, ast.FunctionDef) and n.name == 'donor_callback'))
    changes = 0
    for item in ast.walk(node):
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            if 'profile_key = (bottom, top, rho, ptop)' in item.value:
                item.value = item.value.replace('profile_key = (bottom, top, rho, ptop)',
                                                'profile_key = (bottom, top)').replace(
                    'profile_contribution(*profile_key)',
                    'profile_contribution(bottom, top, rho, ptop)')
                changes += 1
    require(changes == 1, 'fault did not alter exactly one profile cache key')
    namespace = dict(vars(cache))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<deliberately-incomplete-profile-key>', 'exec'), namespace)
    return namespace['donor_callback']


def selected_fixture(repo, cache, poly):
    raw = (repo / cache.SPATIAL_REL).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == cache.SPATIAL_PIN, 'spatial source changed')
    require(digest(repo / cache.DIFFERENTIAL_REL) == cache.DIFFERENTIAL_PIN,
            'differential source changed')
    branch = next(n for n in ast.walk(ast.parse(raw))
                  if isinstance(n, ast.If) and ast.unparse(n.test) == 'exact_rays or strips is not None')
    node = ast.parse('def construct(active, profiles, strips, rc, outer, gravity):\n    pass').body[0]
    node.body = copy.deepcopy(branch.body[:3]) + ast.parse('return radial_profiles, tuple(donors)').body
    namespace = dict(Q=Q)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<pinned-profile-and-donor-construction>', 'exec'), namespace)
    profile = ((Q(1), Q(20), Q(3300), Q(0)),)
    profiles, donors = namespace['construct'](
        [dict(poly=poly, weights=((0, (Q(1, 2),) * 2), (1, (Q(1, 2),) * 2)),
              density=Q(3301), radial=(Q(1), Q(20)))],
        (profile, profile), None, Q(1), Q(20), Q(7, 5))
    require(len(donors) == 2 and donors[0] == donors[1], 'selected duplicate fixture changed')
    return profiles, donors


def main(args):
    require(not args.output.exists(), 'result must be a fresh path')
    own_pin = digest(Path(__file__))
    support_path = args.helpers / 'midpoint_value_probe.py'
    cache_path = args.helpers / 'cross_evaluator_probe.py'
    support = load_helper('composition_value_support', support_path, SUPPORT_PIN)
    cache = load_helper('composition_cache_support', cache_path, CACHE_PIN)
    support.SOURCE, support.O_SOURCE = args.repo / support.COUPLING_REL, args.repo / support.OVERLAP_REL
    tree = ast.parse(support.SOURCE.read_bytes())
    namespaces = {name: support.build_source() for name in ('original', 'cache', 'value', 'composed')}
    for name, namespace in namespaces.items():
        namespace['CACHE_COUNTS'], namespace['PROFILE_CACHE_COUNTS'] = Counter(), Counter()
        if name in ('value', 'composed'):
            support.install_values(namespace)
    callbacks = {
        name: factory(cache, cache_path, args.inject_fault and name == 'composed')(
            tree, namespace, name in ('cache', 'composed'))
        for name, namespace in namespaces.items()
    }
    original = namespaces['original']
    poly = ((Q(1), Q(1)), (Q(4), Q(1)), (Q(4), Q(3)), (Q(1), Q(3)))
    profiles, donors = selected_fixture(args.repo, cache, poly)
    left, right, entry, exit_ = original['_angular_wedges'](poly)[0]
    middle = (left + right) / 2
    rows = tuple((entry, exit_, low, high, coefficient) for _, low, high, coefficient in donors)
    different = (profiles[0], (*profiles[1][:2], Q(3302), Q(3), profiles[1][4]))
    same = (entry, exit_, Q(2), Q(12))
    fixtures = [
        ('selected-duplicates', profiles, rows),
        ('same-bounds-different-physics', different, rows),
        ('signed-duplicates', profiles, ((*same, Q(3, 7)), (*same, Q(-2, 5)))),
        ('separated-duplicates', profiles, ((*same, Q(3, 7)),
                                           (entry, exit_, Q(5), Q(6), Q(2)), (*same, Q(-2, 5)))),
        ('empty-repeated-support', profiles, ((entry, exit_, Q(100), Q(110), Q(1)),
                                             (entry, exit_, Q(100), Q(110), Q(-1)))),
        ('single-profile-and-donor', profiles[:1], rows[:1]),
        ('both-cache-capacities', tuple((Q(1+i), Q(2+i), Q(3+i), Q(i+1, 13), Q(1, i+2))
                                       for i in range(10)) + (profiles[0], profiles[0]),
         tuple((entry, exit_, Q(2+i), Q(3+i), Q(i+1)) for i in range(10))
         + ((*same, Q(1)), (*same, Q(1)))),
    ]
    geometries = {
        'general': ((Q(2), Q(1), Q(3)), (Q(-1), Q(4), Q(2))),
        'exact-root-fallback': ((Q(3)-middle, Q(4), Q(0)), (Q(4)-middle, Q(4), Q(0))),
        'origin-refusal': ((-middle, Q(0), Q(0)), (Q(1)-middle, Q(0), Q(0))),
    }
    records = []
    for bits in (32, 96, 160):
        for geometry, (a, b) in geometries.items():
            for label, bands, contributions in (fixtures if geometry == 'general' else fixtures[:1]):
                for namespace in namespaces.values():
                    namespace.update(a=a, b=b, normal=original['O']._cross(a, b), profiles=bands,
                                     rc=Q(1), outer=Q(20), gravity=Q(7, 5))
                    namespace['_JET_PRECISION'].set(bits)
                call = (middle, middle, ((entry, exit_), contributions), bits)
                expected_full, expected = None, None
                arms = {}
                for name, callback in callbacks.items():
                    support.OPS.clear()
                    support.DECISIONS.clear()
                    namespaces[name]['CACHE_COUNTS'].clear()
                    namespaces[name]['PROFILE_CACHE_COUNTS'].clear()
                    fallback = False
                    try:
                        if name in ('value', 'composed'):
                            fast, actual = support.attempt_value(callback, call)
                            if not fast:
                                fallback = True
                                actual = support.result(callbacks['original'], call)
                        else:
                            full = callback(*call)
                            actual = (tuple(jet[0] for jet in full[0]), full[1])
                            if name == 'original':
                                expected_full = full
                            else:
                                require(full == expected_full, 'complete cached jets differ')
                        actual = ('value', actual)
                    except support.Refused as error:
                        actual = ('refusal', str(error))
                    if name == 'original':
                        expected = actual
                    require(actual == expected, f'composition parity failed: {bits}/{geometry}/{label}/{name}')
                    arms[name] = dict(operations=dict(support.OPS), fallback=fallback,
                                      donor_cache=dict(namespaces[name]['CACHE_COUNTS']),
                                      profile_cache=dict(namespaces[name]['PROFILE_CACHE_COUNTS']))
                    for key in ('donor_cache', 'profile_cache'):
                        require(arms[name][key].get('peak_entries', 0) <= 8, 'cache entry cap exceeded')
                if geometry == 'exact-root-fallback':
                    require(arms['value']['fallback'] and arms['composed']['fallback'], 'fallback not exercised')
                if geometry == 'origin-refusal':
                    require(expected[0] == 'refusal', 'origin refusal not exercised')
                if label == 'both-cache-capacities':
                    require(all(arms['cache'][key].get('peak_entries') == 8
                                for key in ('profile_cache', 'donor_cache')), 'capacity control not exercised')
                records.append(dict(bits=bits, geometry=geometry, fixture=label,
                                    exact_values_and_fixed=True if expected[0] == 'value' else None,
                                    full_cached_jet_parity=True if expected[0] == 'value' else None,
                                    refusal_parity=expected[0] == 'refusal',
                                    outcome=expected[0], arms=arms))
    require(digest(Path(__file__)) == own_pin, 'probe changed during controls')
    require(digest(support_path) == SUPPORT_PIN and digest(cache_path) == CACHE_PIN, 'helper changed')
    output = dict(schema='plan40a-composition-probe-v1', verdict='PASS', synthetic_fixture=True,
                  probe_sha256=own_pin, midpoint_helper_sha256=SUPPORT_PIN, cache_helper_sha256=CACHE_PIN,
                  coupling_sha256=support.PIN, vector_sha256=support.O_PIN,
                  spatial_sha256=cache.SPATIAL_PIN, differential_sha256=cache.DIFFERENTIAL_PIN,
                  scope='27 synthetic midpoint controls only; full original fallback; no interval-stage pair, timing, resource, cancellation or production acceptance',
                  cases=records, case_count=len(records), inject_fault=bool(args.inject_fault))
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(verdict='PASS', cases=len(records), result_sha256=digest(args.output))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--helpers', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inject-fault', action='store_true')
    main(parser.parse_args())
