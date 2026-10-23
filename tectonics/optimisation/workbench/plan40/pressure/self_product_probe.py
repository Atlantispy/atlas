"""Bounded source-bound Plan40A algebra probe; no scientific import or timing.

Preserves general interval multiplication even for repeated operands: a crossing
interval's self-product is not silently replaced by a tighter square enclosure.
"""
import argparse
from collections import Counter
from fractions import Fraction as Q
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys


HELPER_SHA = 'e154140c90af9b3d4d84fbe6b12a9fc8a517e6bb19ec870319dc306de1be94ba'


def load_helper():
    path = Path(__file__).with_name('arithmetic_probe.py')
    if hashlib.sha256(path.read_bytes()).hexdigest() != HELPER_SHA:
        raise ValueError('arithmetic helper identity mismatch')
    spec = importlib.util.spec_from_file_location('pressure_arithmetic_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_pair(pair):
    return type(pair) is tuple and len(pair) == 2 and all(type(q) is Q for q in pair)


def install(ns, *, candidate, fault=False):
    counts = Counter()
    # Instrument only the detached AST namespace; this is operation counting,
    # not evidence about the instrumented or original elapsed time.
    for name in ('_mul', '_add', '_scale', '_dyadic_outward'):
        original = ns[name]

        def counted(*args, _original=original, _name=name):
            counts[_name] += 1
            return _original(*args)

        ns[name] = counted
    original_mul = ns['_jet_mul']
    original_scale = ns['_scale']

    def same_operand(a, b):
        # Keep the original two constant tests and their return precedence.
        if ns['_jet_is_constant'](a):
            return ns['_jet_scale'](b, a[0][0])
        if ns['_jet_is_constant'](b):
            return ns['_jet_scale'](a, b[0][0])
        if (a is not b or type(a) not in (tuple, ns['_RadialJet'])
                or len(a) != 3 or not all(exact_pair(pair) for pair in a)):
            # Calling the original repeats cheap constant tests on fallback;
            # no claimed speedup includes that unmeasured dispatch overhead.
            counts['jet_fallback'] += 1
            return original_mul(a, b)
        counts['self_product'] += 1
        value = ns['_mul'](a[0], a[0])
        first = ns['_mul'](a[1], a[0])
        d1 = ns['_add'](first, first)
        del first
        second = ns['_mul'](a[2], a[0])
        d2 = ns['_add'](ns['_add'](second, ns['_scale'](ns['_mul'](a[1], a[1]), 2)),
                         ns['_ZERO_PAIR'] if fault else second)
        return ns['_jet_outward']((value, d1, d2))

    def negation(pair, q):
        # Built-in exact rationals only; floats, subclasses, lists and reversed
        # intervals keep the full original path and its result-type behaviour.
        if (type(q) in (int, Q) and q == -1 and exact_pair(pair)
                and pair[0] <= pair[1]):
            counts['negation'] += 1
            return -pair[1], -pair[0]
        return original_scale(pair, q)

    if candidate:
        ns['_jet_mul'] = same_operand
        ns['_scale'] = negation
    return counts


def canonical(value):
    if isinstance(value, Q):
        return ('Q', value.numerator, value.denominator)
    if isinstance(value, tuple):
        return (type(value).__name__, tuple(canonical(v) for v in value),
                canonical(getattr(value, 'expression', None)))
    if isinstance(value, list):
        return ('list', tuple(canonical(v) for v in value))
    return value


def outcome(function, *args):
    try:
        return ('value', canonical(function(*args)))
    except (ValueError, ZeroDivisionError, TypeError) as error:
        return ('error', type(error).__name__, str(error))


def require_equal(left, right, label):
    if left != right:
        raise AssertionError('exact parity failed: ' + label)


def delta(counts, before):
    return dict(sorted((key, value-before.get(key, 0)) for key, value in counts.items()
                       if value-before.get(key, 0)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inject-fault', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('new output required')
    helper = load_helper()
    reference, candidate = helper.load(args.repo), helper.load(args.repo)
    rc = install(reference, candidate=False)
    cc = install(candidate, candidate=True, fault=args.inject_fault)
    cases = Counter()
    rng = random.Random(4001)
    for precision in (8, 32, 96, 160):
        rt = reference['_JET_PRECISION'].set(precision)
        ct = candidate['_JET_PRECISION'].set(precision)
        try:
            jets = [reference['_jet_constant'](Q(n, 7)) for n in (0, 1, -1)]
            for _ in range(48):
                jets.append(tuple(tuple(sorted((Q(rng.randint(-20, 20), rng.randint(1, 17)),
                                                Q(rng.randint(-20, 20), rng.randint(1, 17)))))
                                  for _ in range(3)))
            # Nonconstant singleton, zero derivatives, reversed pairs and mixed
            # types deliberately test the applicability boundary.
            jets += [((Q(1), Q(1)), (Q(2), Q(2)), (Q(0), Q(0))),
                     ((Q(-1), Q(1)), (Q(0), Q(0)), (Q(0), Q(0))),
                     ((Q(2), Q(-1)), (Q(3), Q(-2)), (Q(1), Q(0))),
                     ((-1, 1), (Q(0), Q(1)), (0, 0))]
            for jet in jets:
                require_equal(outcome(reference['_jet_mul'], jet, jet),
                              outcome(candidate['_jet_mul'], jet, jet), 'same operand')
                cases['same_operand'] += 1
                copy = tuple(tuple(list(pair)) for pair in jet)
                require_equal(outcome(reference['_jet_mul'], jet, copy),
                              outcome(candidate['_jet_mul'], jet, copy), 'distinct equal operands')
                cases['distinct_equal_operands'] += 1
                for exponent in (2, 3, 4):
                    require_equal(outcome(reference['_jet_power'], jet, exponent),
                                  outcome(candidate['_jet_power'], jet, exponent), 'power consumer')
                    cases['power'] += 1
                require_equal(outcome(reference['_jet_reciprocal'], jet),
                              outcome(candidate['_jet_reciprocal'], jet), 'reciprocal/refusal')
                cases['reciprocal'] += 1
        finally:
            reference['_JET_PRECISION'].reset(rt)
            candidate['_JET_PRECISION'].reset(ct)
    for pair in ((Q(-2), Q(3)), (Q(0), Q(0)), (Q(3), Q(-2)),
                 (-0.0, 0.0), [Q(-2), Q(3)], (Q(-2), Q(0), Q(3))):
        for q in (-1, Q(-1), Q(2, 3)):
            require_equal(outcome(reference['_scale'], pair, q),
                          outcome(candidate['_scale'], pair, q), 'scale fallback')
            cases['scale_domain'] += 1
    # Source-bound consumer subset: separated from adversarial primitive totals.
    before_r, before_c = dict(rc), dict(cc)
    a, b, normal = (Q(2), Q(0), Q(0)), (Q(0), Q(2), Q(0)), (Q(0), Q(0), Q(4))
    entry, exit_ = (Q(1), Q(2), Q(1)), (Q(5), Q(2), Q(1))
    for bits in (32, 96, 160):
        rt = reference['_JET_PRECISION'].set(bits)
        ct = candidate['_JET_PRECISION'].set(bits)
        try:
            for left, right in ((Q(0), Q(1)), (Q(1, 4), Q(1, 2)), (Q(1, 3), Q(1, 3))):
                require_equal(outcome(reference['_radial_chart_jets'], a, b, normal, left, right, bits),
                              outcome(candidate['_radial_chart_jets'], a, b, normal, left, right, bits), 'chart')
                cases['chart'] += 1
                for bottom, top in ((Q(1), Q(4)), (Q(2), Q(3)), (Q(4), Q(4))):
                    values = (a, b, normal, left, right, entry, exit_, bottom, top, Q(1), bits)
                    require_equal(outcome(reference['_radial_slice'], *values),
                                  outcome(candidate['_radial_slice'], *values), 'shell')
                    cases['shell'] += 1
        finally:
            reference['_JET_PRECISION'].reset(rt)
            candidate['_JET_PRECISION'].reset(ct)
    consumer_counts = {'baseline': delta(rc, before_r), 'candidate': delta(cc, before_c)}
    crossing = (Q(-1), Q(1))
    if reference['_mul'](crossing, crossing) != (Q(-1), Q(1)):
        raise AssertionError('self-product refutation binding lost')
    source_pins = {name: {'relative': rel, 'sha256': sha}
                   for name, (rel, sha) in helper.SOURCES.items()}
    result = {'status': 'PASS', 'kind': 'synthetic-exactness-and-operation-counts',
              'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'helper_sha256': HELPER_SHA, 'sources': source_pins, 'cases': dict(cases),
              'consumer_counts': consumer_counts,
              'refutation': '[-1,1]*[-1,1] remains [-1,1], never replaced by [0,1]',
              'limits': ['No stage, workers, timings or whole-IV gain.',
                         'Not a production resource, admission or cancellation proof.',
                         'Do not add overlapping midpoint, power-prefix and self-product reductions.']}
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'cases': result['cases'],
                      'consumer_counts': consumer_counts}))


if __name__ == '__main__':
    if sys.flags.optimize:
        raise SystemExit('optimised Python execution is unsupported for this proof')
    main()
