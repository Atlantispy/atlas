"""Plan40A bounded exactness/refutation probe; never a production patch or timer.

Uses complete AST definitions from the pinned public pressure source. It does
not import the scientific package, dispatch workers, or claim full-stage proof.
"""
import argparse
import ast
from contextvars import ContextVar
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from types import SimpleNamespace


SOURCES = {
    'coupling': ('tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_pressure_coupling.py',
                 '7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e'),
    'spatial': ('tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_spatial_pressure.py',
                '1f4f50ccb08eaeeab2a52c30dce033aa4b1fb07273a59ebd619d89f233c33712'),
    'overlap': ('tectonics/optimisation/composed-r2/src/atlas_tectonics/integration_volume_overlap.py',
                '96f3921c2b7a8369f230dd362a28552d1f21179a5605fb183f01cfc075e68f48'),
}
JET_NAMES = {
    '_over', '_dyadic_outward', '_jet_outward', '_add', '_mul', '_scale',
    '_divide', '_sqrt', '_minus', '_jet_constant', '_jet_is_constant',
    '_RadialJet', '_same_radial', '_jet_add', '_jet_scale', '_jet_mul',
    '_jet_reciprocal', '_radial_chart_jets', '_radial_interval_jets',
    '_radial_slice', '_jet_power', '_jet_extreme', '_positive_interval_primitive',
    '_donor_radial_pressure', '_triangle', '_cross2', '_radial_linear_mean',
}


def definitions(text, names, namespace):
    tree = ast.parse(text)
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in nodes} != names:
        raise ValueError('incomplete requested definition set')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pinned-definitions>', 'exec'), namespace)


def load(repo):
    texts = {}
    for name, (relative, expected) in SOURCES.items():
        raw = (repo / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('source identity mismatch: ' + relative)
        texts[name] = raw.decode('utf-8')
    overlap = {'Fraction': Q}
    definitions(texts['overlap'], {'_dot', '_cross'}, overlap)
    namespace = dict(Q=Q, math=math, O=SimpleNamespace(**overlap),
                     PressureCouplingRefused=type('PressureCouplingRefused', (ValueError,), {}),
                     _JET_PRECISION=ContextVar('probe_precision', default=128))
    for name, value in zip(('_ZERO', '_ONE', '_HALF', '_THIRD', '_QUARTER', '_MINUS_QUARTER'),
                           (Q(0), Q(1), Q(1, 2), Q(1, 3), Q(1, 4), Q(-1, 4)), strict=True):
        namespace[name] = value
    namespace['_ZERO_PAIR'] = (Q(0), Q(0))
    definitions(texts['coupling'], JET_NAMES, namespace)
    # Same module-level compatibility branch as the pinned source.
    if not hasattr(Q, '_from_coprime_ints'):
        namespace['_over'] = Q
    namespace['_JET_ZERO'] = namespace['_jet_constant'](Q(0))
    namespace['_JET_ONE'] = namespace['_jet_constant'](Q(1))
    definitions(texts['spatial'], {'_cone_status'}, namespace)
    return namespace


def primitive(reference, jet, first, second, *, shared):
    power = reference['_jet_power']
    cube = power(jet, 3)
    # Keep the constant path's direct exact exponentiation. For a nonconstant
    # jet this is the identical left-fold prefix and last rounded operation.
    fourth = (power(jet, 4) if not shared or reference['_jet_is_constant'](jet)
              else reference['_jet_mul'](cube, jet))
    return reference['_jet_add'](reference['_jet_scale'](cube, first),
                                 reference['_jet_scale'](fourth, second))


def dyadic_reuse(reference, pair, denominator):
    if (type(pair) is tuple and len(pair) == 2 and
            all(type(q) is Q and denominator % q.denominator == 0 for q in pair)):
        return pair
    return reference['_dyadic_outward'](pair, denominator)


def mul_zero(reference, first, second):
    if (type(first) is tuple and type(second) is tuple and len(first) == len(second) == 2
            and all(type(q) is Q for q in (*first, *second))
            and (first == (0, 0) or second == (0, 0))):
        return (Q(0), Q(0))
    return reference['_mul'](first, second)


def cone_hoist(reference, cone, points):
    status = 1
    for a, b in zip(cone, cone[1:] + cone[:1], strict=True):
        normal = reference['O']._cross(a, b)
        values = [reference['O']._dot(normal, p) for p in points]
        if max(values) < 0:
            return 0
        if min(values) < 0:
            status = -1
    return status


def local_vector_candidates(repo, reference):
    text = (repo / SOURCES['coupling'][0]).read_text(encoding='utf-8')
    replacements = [
        ('        minimum = min(minimum, O._dot(tuple(v+t*w for v, w in zip(x, d)),\n'
         '                                    tuple(v+t*w for v, w in zip(x, d))))',
         '        nearest = tuple(v+t*w for v, w in zip(x, d))\n'
         '        minimum = min(minimum, O._dot(nearest, nearest))'),
        ('sum(O._dot(_minus(p, centre), _minus(p, centre)) for p in points)',
         'sum(O._dot(offset, offset) for offset in (_minus(p, centre) for p in points))'),
    ]
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError('local expression source mismatch')
        text = text.replace(old, new)
    candidate = dict(reference)
    definitions(text, {'_triangle', '_radial_linear_mean'}, candidate)
    return candidate


def outcome(function, *args, **kwargs):
    try:
        return ('result', function(*args, **kwargs))
    except (ValueError, ZeroDivisionError) as error:
        return ('error', type(error).__name__, str(error))


def encode(value):
    if isinstance(value, Q):
        return [value.numerator, value.denominator]
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inject-fault', choices=('power',))
    args = parser.parse_args()
    reference = load(args.repo)
    rng = random.Random(40)
    counts = dict(power_prefix=0, dyadic_reuse=0, interval_zero=0, cone_hoist=0,
                  radial_consumers=0, refusal=0, triangle_vector=0, radial_vector=0)
    witness = None
    for precision in (8, 16, 96, 128):
        token = reference['_JET_PRECISION'].set(precision)
        try:
            jets = [reference['_jet_constant'](Q(n, 7)) for n in (0, 1, -1, 13)]
            for _ in range(100):
                pairs = []
                for _ in range(3):
                    a, b = (Q(rng.randrange(-12, 30), rng.randrange(1, 17)) for _ in range(2))
                    pairs.append((min(a, b), max(a, b)))
                jets.append(tuple(pairs))
            for jet in jets:
                old = primitive(reference, jet, Q(17, 3), Q(-11, 4), shared=False)
                new = primitive(reference, jet, Q(17, 3), Q(-11, 4), shared=True)
                if args.inject_fault == 'power':
                    new = reference['_JET_ZERO']
                assert old == new, 'power-prefix mismatch'
                counts['power_prefix'] += 1
                fourth = reference['_jet_power'](jet, 4)
                square = reference['_jet_mul'](jet, jet)
                regrouped = reference['_jet_mul'](square, square)
                if witness is None and fourth != regrouped:
                    witness = dict(precision=precision, jet=encode(jet),
                                   reference=encode(fourth), regrouped=encode(regrouped))
                for pair in jet:
                    denominator = 1 << precision
                    assert dyadic_reuse(reference, pair, denominator) == reference['_dyadic_outward'](pair, denominator)
                    rounded = reference['_dyadic_outward'](pair, denominator)
                    assert dyadic_reuse(reference, rounded, denominator) == reference['_dyadic_outward'](rounded, denominator)
                    counts['dyadic_reuse'] += 2
                    for zero_first in (True, False):
                        first, second = ((Q(0), Q(0)), pair) if zero_first else (pair, (Q(0), Q(0)))
                        assert mul_zero(reference, first, second) == reference['_mul'](first, second)
                        counts['interval_zero'] += 1
            for pair in ((0, 1), (Q(3, 2), Q(-5, 7)), [Q(0), Q(1)]):
                assert dyadic_reuse(reference, pair, 1 << precision) == reference['_dyadic_outward'](pair, 1 << precision)
                counts['dyadic_reuse'] += 1
            # Direct selected radial callers, both span intervals and midpoint
            # evaluations, plus equal-expression and clamped shell cases.
            a, b, normal = (Q(2), Q(0), Q(0)), (Q(0), Q(2), Q(0)), (Q(0), Q(0), Q(4))
            for left, right in ((Q(0), Q(1)), (Q(1, 4), Q(1, 2)), (Q(1, 3), Q(1, 3))):
                s, factors = reference['_radial_chart_jets'](a, b, normal, left, right, precision)
                assert len(factors) == 3
                low, high, _, _ = reference['_radial_interval_jets'](
                    s, left, right, (Q(1), Q(2), Q(1)), (Q(5), Q(2), Q(1)), Q(1), Q(4))
                for jet in (s, low, high, *factors):
                    assert primitive(reference, jet, Q(3), Q(-2), shared=False) == primitive(reference, jet, Q(3), Q(-2), shared=True)
                    counts['radial_consumers'] += 1
                same = reference['_donor_radial_pressure'](low, low, low, high)
                assert same[0] == reference['_JET_ZERO']
            for interval in ((Q(-1), Q(1)), (Q(0), Q(0))):
                try:
                    reference['_jet_reciprocal']((interval, (Q(1), Q(1)), (Q(0), Q(0))))
                except reference['PressureCouplingRefused']:
                    counts['refusal'] += 1
                else:
                    raise AssertionError('zero-crossing refusal lost')
        finally:
            reference['_JET_PRECISION'].reset(token)
    assert witness is not None, 'regrouping refutation missing'
    cone = ((Q(1), Q(0), Q(0)), (Q(0), Q(1), Q(0)), (Q(0), Q(0), Q(1)))
    for _ in range(100):
        points = tuple(tuple(Q(rng.randrange(-3, 4), 7) for _ in range(3)) for _ in range(3))
        assert cone_hoist(reference, cone, points) == reference['_cone_status'](cone, points)
        counts['cone_hoist'] += 1
    for selected_cone, points in (((), ()), (cone, ()), (cone, ((Q(0),) * 3,) * 3),
                                 (cone, ((Q(1),) * 3,) * 3), (cone, ((Q(-1),) * 3,) * 3)):
        assert outcome(cone_hoist, reference, selected_cone, points) == outcome(reference['_cone_status'], selected_cone, points)
        counts['cone_hoist'] += 1
    candidate = local_vector_candidates(args.repo, reference)
    triangles = [((Q(0), Q(0)), (Q(0), Q(0)), (Q(0), Q(0))),
                 ((Q(1), Q(0)), (Q(0), Q(1)), (Q(1), Q(1)))]
    triangles += [tuple(tuple(Q(rng.randrange(-9, 10), 11) for _ in range(2)) for _ in range(3))
                  for _ in range(64)]
    for triangle in triangles:
        args_ = (triangle, (Q(2), Q(0), Q(0)), (Q(0), Q(3), Q(0)), 96)
        before, after = outcome(reference['_triangle'], *args_), outcome(candidate['_triangle'], *args_)
        assert before == after, 'triangle duplicate-vector mismatch'
        counts['triangle_vector'] += 1
        if before[0] == 'result':
            points, radial, _, _ = before[1]
            for core in (Q(0), Q(1, 7)):
                args_ = (points, radial, (Q(0), Q(0), Q(6)))
                assert outcome(reference['_radial_linear_mean'], *args_, rc=core) == outcome(candidate['_radial_linear_mean'], *args_, rc=core)
                counts['radial_vector'] += 1
    # Identity mutation must fail before extracting any function.
    assert reference['_JET_PRECISION'].get() == 128
    result = dict(status='PASS', scope='pinned extracted helper feasibility; no whole-stage/runtime/performance claim',
                  source_pins={name: dict(path=p, sha256=h) for name, (p, h) in SOURCES.items()},
                  checks=counts, reassociation_refutation=witness,
                  limits=['No performance timings or production-width survey.',
                          'No resource allocator, process cancellation or full-consumer integration proof.',
                          'Fixtures are bounded exact rational controls, not saved production operands.'])
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=result['status'], checks=counts)))


if __name__ == '__main__':
    if sys.flags.optimize:
        raise SystemExit('Refused: acceptance assertions require a non-optimised interpreter')
    main()
