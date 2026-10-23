"""AST-only lazy immutable chart/profile preparation feasibility; no production imports.

No timings, stage, resources/admission proof or runtime edits. The holder is local
mutable metadata; every cached value is immutable exact arithmetic. Lazy insertion
at the original expression sites preserves refusal/work order on the first use.
"""
from __future__ import annotations
import argparse
import ast
import copy
from collections import Counter
from contextvars import ContextVar
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

SOURCE_REL = Path('tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_pressure_coupling.py')
SOURCE = SOURCE_REL
PIN = '7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e'
VECTOR_REL = Path('tectonics/optimisation/composed-r2/src/atlas_tectonics/integration_volume_overlap.py')
VECTOR = VECTOR_REL
VPIN = '96f3921c2b7a8369f230dd362a28552d1f21179a5605fb183f01cfc075e68f48'
NAMES = {'_over', '_dyadic_outward', '_jet_outward', '_add', '_mul', '_scale', '_divide', '_sqrt',
         '_minus', '_jet_constant', '_jet_is_constant', '_RadialJet', '_same_radial', '_jet_add',
         '_jet_scale', '_jet_mul', '_jet_reciprocal', '_radial_chart_jets', '_jet_power',
         '_positive_interval_primitive'}
CHART = ['_minus(b, a)', 'O._dot(direction, direction)', 'O._dot(a, direction)',
         'O._dot(a, a)', 'O._cross(normal, a)', 'O._cross(normal, direction)']
PROFILE = ['(ptop+gravity*rho*top)/3', '-gravity*rho/4']


class Refused(ValueError):
    pass


class Preparation:
    """One owner/integration only; binding checked outside the scientific body."""
    def __init__(self, binding):
        self.binding = binding
        self.values = {}
        self.misses = Counter()
        self.calls = Counter()

    def get(self, key, expression):
        self.calls[key] += 1
        if key not in self.values:
            value = expression()  # Failing arithmetic is never retained.
            assert isinstance(value, (tuple, Q, int))
            self.values[key] = value
            self.misses[key] += 1
        return self.values[key]

    def bind(self, binding):
        if binding != self.binding:
            raise ValueError('preparation belongs to different exact integration inputs')


def dump(node):
    return ast.dump(node, include_attributes=False)


class Hoist(ast.NodeTransformer):
    def __init__(self, expressions):
        self.targets = {dump(ast.parse(s, mode='eval').body): i for i, s in enumerate(expressions)}
        self.matches = Counter()

    def visit(self, node):
        key = self.targets.get(dump(node))
        if key is not None:
            self.matches[key] += 1
            return ast.Call(func=ast.Attribute(value=ast.Name(id='prep', ctx=ast.Load()), attr='get', ctx=ast.Load()),
                            args=[ast.Constant(key), ast.Lambda(args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                                       kw_defaults=[], defaults=[]), body=copy.deepcopy(node))], keywords=[])
        return super().visit(node)


class Unhoist(ast.NodeTransformer):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'prep':
            return copy.deepcopy(node.args[1].body)
        return self.generic_visit(node)


def transformed(node, expressions):
    transform = Hoist(expressions)
    result = transform.visit(copy.deepcopy(node))
    assert transform.matches == Counter({i: 1 for i in range(len(expressions))})
    assert dump(Unhoist().visit(copy.deepcopy(result))) == dump(node), 'expression order changed'
    return ast.fix_missing_locations(result)


def build():
    raw, vectors = SOURCE.read_bytes(), VECTOR.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PIN
    assert hashlib.sha256(vectors).hexdigest() == VPIN
    tree = ast.parse(raw)
    definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in NAMES]
    assert {n.name for n in definitions} == NAMES
    ns = dict(Q=Q, math=math, PressureCouplingRefused=Refused,
              _ZERO=Q(0), _ONE=Q(1), _HALF=Q(1, 2), _MINUS_QUARTER=Q(-1, 4),
              _ZERO_PAIR=(Q(0), Q(0)), _JET_PRECISION=ContextVar('chart-probe', default=96))
    vec = dict(Fraction=Q)
    vecdefs = [n for n in ast.parse(vectors).body if isinstance(n, ast.FunctionDef) and n.name in ('_dot', '_cross')]
    exec(compile(ast.Module(body=vecdefs, type_ignores=[]), str(VECTOR_REL), 'exec'), vec)
    ns['O'] = SimpleNamespace(_dot=vec['_dot'], _cross=vec['_cross'])
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(SOURCE_REL), 'exec'), ns)
    if not hasattr(Q, '_from_coprime_ints'):
        ns['_over'] = Q
    ns['_JET_ZERO'], ns['_JET_ONE'] = ns['_jet_constant'](Q(0)), ns['_jet_constant'](Q(1))
    chart = next(n for n in definitions if n.name == '_radial_chart_jets')
    changed = transformed(chart, CHART)
    changed.name = '_prepared_chart'
    changed.args.args.append(ast.arg(arg='prep'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[])), '<prepared-chart>', 'exec'), ns)
    pressure = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_integrate_radial_pressure')
    lambdas = [n for n in ast.walk(pressure) if isinstance(n, ast.Lambda)]
    assert len(lambdas) == 1
    ns['primitive_ast'] = lambdas[0]
    ns['prepared_primitive_ast'] = transformed(lambdas[0], PROFILE)
    return ns


def encoded(value):
    if isinstance(value, tuple):
        result = {'type': type(value).__name__, 'items': [encoded(x) for x in value]}
        if hasattr(value, 'expression'):
            result['expression'] = encoded(value.expression)
        return result
    if isinstance(value, Q):
        return {'type': 'Fraction', 'n': str(value.numerator), 'd': str(value.denominator)}
    if type(value) is int:
        return {'type': 'int', 'n': str(value), 'd': '1'}
    return value


def outcome(fn, *args):
    try:
        return ('value', encoded(fn(*args)))
    except (Refused, ZeroDivisionError, ValueError) as error:
        return ('error', type(error).__name__, str(error))


def chart_compare(ns, a, b, normal, left, right, bits, prep):
    prep.bind((a, b, normal))
    ns['_JET_PRECISION'].set(bits)
    original = outcome(ns['_radial_chart_jets'], a, b, normal, left, right, bits)
    candidate = outcome(ns['_prepared_chart'], a, b, normal, left, right, bits, prep)
    assert original == candidate
    return original


def decode(value, ns, _remaining=None, _depth=0):
    if _remaining is None:
        _remaining = [256]
    _remaining[0] -= 1
    if _remaining[0] < 0 or _depth > 32:
        raise ValueError('captured value exceeds structural bounds')
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is not dict or type(value.get('type')) is not str:
        raise ValueError('tagged captured value required')
    kind = value['type']
    if kind in ('Fraction', 'int'):
        if set(value) != {'type', 'n', 'd'} or any(type(value[k]) is not str or len(value[k]) > 1235 for k in ('n', 'd')):
            raise ValueError('invalid captured rational fields')
        numerator, denominator = int(value['n']), int(value['d'])
        if str(numerator) != value['n'] or str(denominator) != value['d']:
            raise ValueError('noncanonical captured integer text')
        if denominator <= 0 or max(abs(numerator).bit_length(), denominator.bit_length()) > 4096:
            raise ValueError('captured rational exceeds canonical bounded input')
        result = Q(numerator, denominator)
        if (result.numerator, result.denominator) != (numerator, denominator):
            raise ValueError('noncanonical captured rational')
        if kind == 'int' and denominator != 1:
            raise ValueError('captured integer has a denominator')
        return numerator if kind == 'int' else result
    if kind not in ('tuple', 'list', '_RadialJet'):
        raise ValueError('unsupported capture tag')
    expected_keys = {'type', 'items', 'expression'} if kind == '_RadialJet' else {'type', 'items'}
    if set(value) != expected_keys or type(value['items']) is not list:
        raise ValueError('invalid captured sequence fields')
    items = [decode(x, ns, _remaining, _depth+1) for x in value['items']]
    if kind == '_RadialJet':
        return ns['_RadialJet'](tuple(items), decode(value['expression'], ns, _remaining, _depth+1))
    return tuple(items) if kind == 'tuple' else items


def replay(path, ns):
    assert path.stat().st_size <= 16*1024*1024
    report = json.loads(path.read_text())
    assert report['verdict'] == 'PASS', 'unvalidated observation cannot support actual replay'
    assert report['source_pins']['coupling']['sha256'] == PIN
    rows = [row for row in report['captures'] if row['function'] == '_radial_chart_jets']
    if not rows:
        raise ValueError('no chart captures: absence is not a replay pass')
    assert len(rows) <= 16
    groups = {}
    for row in rows:
        assert len(json.dumps(row).encode()) <= 16384
        assert row['argument_names'] == ['a', 'b', 'normal', 'left', 'right', 'bits']
        args = decode(row['arguments'], ns)
        assert type(args) is tuple and len(args) == 6
        assert all(type(v) is tuple and len(v) == 3 and all(type(q) in (int, Q) for q in v) for v in args[:3])
        assert all(type(q) in (int, Q) for q in args[3:5])
        assert type(args[-1]) is int and 1 <= args[-1] <= 4096
        assert type(row['precision']) is int
        assert row['precision'] == args[-1]
        prep = groups.setdefault(args[:3], Preparation(args[:3]))
        result = chart_compare(ns, *args, prep)
        assert result == ('value', encoded(decode(row['expected'], ns)))
    return {'captures': len(rows), 'bindings': len(groups),
            'synthetic_fixture': report.get('synthetic_fixture', False),
            'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    if sys.flags.optimize != 0:
        raise SystemExit('refused: assertions must remain enabled for acceptance checks')
    global SOURCE, VECTOR
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--captures', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    SOURCE, VECTOR = args.repo/SOURCE_REL, args.repo/VECTOR_REL
    ns = build()
    if args.captures:
        result = dict(status='PASS', scope='bounded captured chart arithmetic replay only; no lifetime or performance acceptance',
                      source_sha256=PIN, vector_sha256=VPIN,
                      adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      actual_replay=replay(args.captures, ns))
        args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result))
        return
    counts = Counter()
    cases = [((1, 0, 0), (0, 1, 0)), ((1, 2, 3), (1, 2, 3)),
             ((1, 0, 0), (-1, 0, 0)), ((0, 0, 0), (0, 1, 0)),
             ((Q(2, 3), Q(-3, 7), 2), (Q(9, 5), Q(1, 11), -1)),
             ((Q(2**140+1, 2**137+3), 1, 0), (1, Q(2**130+9, 7), 2))]
    intervals = [(Q(0), Q(1)), (Q(1, 4), Q(3, 4)), (Q(1, 3), Q(1, 3)),
                 (Q(0), Q(0)), (Q(1), Q(1)), (Q(-1), Q(2))]
    totals = Counter()
    for av, bv in cases:
        a, b = tuple(map(Q, av)), tuple(map(Q, bv))
        for normal in (ns['O']._cross(a, b), (Q(2), Q(-1), Q(3))):
            prep = Preparation((a, b, normal))
            for bits in (32, 96, 160):
                for left, right in intervals:
                    result = chart_compare(ns, a, b, normal, left, right, bits, prep)
                    counts['chart_'+result[0]] += 1
                    counts['midpoint' if left == right else 'interval'] += 1
            totals.update({str(k): v for k, v in prep.misses.items()})
    # Explicit origin refusal computes only the original prefix: no eager aa/cross.
    a, b, normal = (Q(1), Q(0), Q(0)), (Q(-1), Q(0), Q(0)), (Q(0), Q(0), Q(1))
    prep = Preparation((a, b, normal))
    assert chart_compare(ns, a, b, normal, Q(0), Q(1), 96, prep)[0] == 'error'
    assert set(prep.values) == {0, 1, 2}
    # A corrupt expression witness can leave numeric jets unchanged: compare it too.
    assert chart_compare(ns, a, b, normal, Q(0), Q(0), 96, prep)[0] == 'value'
    prep.values[3] += 1
    try:
        chart_compare(ns, a, b, normal, Q(0), Q(0), 96, prep)
    except AssertionError:
        counts['corrupt_expression_detected'] += 1
    else:
        raise AssertionError('corrupt exact radial expression was missed')
    try:
        prep.bind((b, a, normal))
    except ValueError:
        counts['binding_refusal'] += 1
    else:
        raise AssertionError('cross-integration reuse accepted')
    # Per-profile coefficients inserted only where original primitive uses them.
    for rho in (Q(0), Q(2, 7), Q(-3)):
        for top in (Q(2), Q(11, 3)):
            for gravity in (Q(0), Q(9, 7)):
                env = dict(ns, ptop=Q(5, 9), rho=rho, top=top, gravity=gravity)
                prep = Preparation((rho, top, gravity, env['ptop']))
                env['prep'] = prep
                plain = eval(compile(ast.Expression(ns['primitive_ast']), '<original-profile>', 'eval'), env)
                changed = eval(compile(ast.Expression(ns['prepared_primitive_ast']), '<prepared-profile>', 'eval'), env)
                zero, one = ns['_jet_constant'](Q(0)), ns['_jet_constant'](Q(1))
                assert outcome(ns['_positive_interval_primitive'], one, zero, plain) == outcome(ns['_positive_interval_primitive'], one, zero, changed)
                assert not prep.values, 'empty branch eagerly prepared coefficients'
                for value in (zero, one, ((Q(1), Q(2)), (Q(-1), Q(1)), (Q(0), Q(2)))):
                    assert outcome(plain, value) == outcome(changed, value)
                    counts['profile_primitive'] += 1
                assert prep.misses == {0: 1, 1: 1}
    # Observer-independent bounded fault: failed lazy expression must not cache.
    prep = Preparation(())
    def fault():
        raise Refused('injected preparation fault')
    assert outcome(prep.get, 0, fault) == ('error', 'Refused', 'injected preparation fault')
    assert not prep.values and prep.get(0, lambda: Q(3)) == 3
    result = dict(status='PASS', scope='AST synthetic feasibility; no production/stage/timing/resource acceptance',
                  source_sha256=PIN, vector_sha256=VPIN, adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  comparisons=dict(counts), chart_preparation_misses=dict(totals),
                  ast_roundtrip_expression_order=True, origin_refusal_lazy_prefix=True,
                  empty_profile_no_preparation=True, failed_expression_not_cached=True,
                  chart_per_complete_preparation=dict(rational_multiply=21, rational_add=9, rational_subtract=9),
                  profile_per_pair=dict(rational_multiply=3, rational_add=1, rational_divide=2, rational_negate=1),
                  actual_replay='NOT RUN: no actual survey captures supplied')
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
