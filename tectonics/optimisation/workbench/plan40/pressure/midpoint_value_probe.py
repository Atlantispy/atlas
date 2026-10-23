"""Source-bound midpoint value feasibility only; no production edits or timings.

AST-extracts selected rational functions; partition admission is a no-op fixture,
not resource validation. Every ambiguous derivative-dependent predicate refuses
the fast midpoint and re-evaluates the original full jet callback.
"""
from __future__ import annotations
import ast
import argparse
from collections import Counter
from contextlib import nullcontext
from contextvars import ContextVar
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import sys
import types

if sys.flags.optimize != 0:
    raise SystemExit('midpoint probe requires assertions enabled; omit -O/-OO and PYTHONOPTIMIZE')

COUPLING_REL = Path('tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_pressure_coupling.py')
OVERLAP_REL = Path('tectonics/optimisation/composed-r2/src/atlas_tectonics/integration_volume_overlap.py')
SOURCE = COUPLING_REL
PIN = '7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e'
O_SOURCE = OVERLAP_REL
O_PIN = '96f3921c2b7a8369f230dd362a28552d1f21179a5605fb183f01cfc075e68f48'
OPS = Counter()
DECISIONS = []
NAMES = {'_over', '_dyadic_outward', '_jet_outward', '_add', '_mul', '_scale', '_divide', '_sqrt',
         '_minus', '_cross2', '_angular_wedges', '_jet_constant', '_jet_is_constant', '_RadialJet',
         '_same_radial', '_jet_add', '_jet_scale', '_jet_mul', '_jet_reciprocal', '_radial_chart_jets',
         '_radial_interval_jets', '_radial_slice', '_jet_power', '_jet_extreme',
         '_positive_interval_primitive', '_donor_radial_pressure', '_integrate_radial_pressure'}


class Refused(ValueError):
    pass


class UnknownConstant(Exception):
    pass


class Value:
    __slots__ = ('value', 'constant')

    def __init__(self, value, constant=None):
        self.value = value
        self.constant = False if value[0] != value[1] else constant

    def __getitem__(self, index):
        if index != 0:
            raise AssertionError('value path requested a derivative')
        return self.value


class ValueRadial(Value):
    __slots__ = ('expression',)

    def __init__(self, jet, expression):
        super().__init__(jet[0], classify(jet, resolve=False))
        self.expression = expression


def classify(jet, resolve=True):
    if isinstance(jet, Value):
        flag = jet.constant
        if flag is None and resolve:
            raise UnknownConstant('singleton value has no derivative witness')
        return flag
    return jet[0][0] == jet[0][1] and jet[1] == (0, 0) and jet[2] == (0, 0)


def build_source():
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PIN, 'selected source changed'
    tree = ast.parse(raw)
    definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in NAMES]
    assert {n.name for n in definitions} == NAMES
    ns = dict(Q=Q, math=math, ContextVar=ContextVar, PressureCouplingRefused=Refused,
              _ZERO=Q(0), _ONE=Q(1), _HALF=Q(1, 2), _THIRD=Q(1, 3),
              _QUARTER=Q(1, 4), _MINUS_QUARTER=Q(-1, 4), _ZERO_PAIR=(Q(0), Q(0)),
              _JET_PRECISION=ContextVar('probe_precision', default=96))
    overlap_raw = O_SOURCE.read_bytes()
    assert hashlib.sha256(overlap_raw).hexdigest() == O_PIN, 'selected vector source changed'
    overlap_definitions = [node for node in ast.parse(overlap_raw).body
                           if isinstance(node, ast.FunctionDef) and node.name in ('_dot', '_cross')]
    overlap = dict(Fraction=Q)
    exec(compile(ast.Module(body=overlap_definitions, type_ignores=[]), str(O_SOURCE), 'exec'), overlap)
    ns['O'] = types.SimpleNamespace(_dot=overlap['_dot'], _cross=overlap['_cross'])
    ns['V'] = types.SimpleNamespace(_work=lambda values, budget: nullcontext(values))
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(SOURCE), 'exec'), ns)
    # Preserve the pinned source's module-level fallback before Python 3.12.
    if not hasattr(Q, '_from_coprime_ints'):
        ns['_over'] = Q
    ns['_JET_ZERO'], ns['_JET_ONE'] = ns['_jet_constant'](Q(0)), ns['_jet_constant'](Q(1))
    for name in ('_add', '_mul', '_scale', '_divide', '_dyadic_outward', '_sqrt'):
        original = ns[name]
        def counted(*args, _name=name, _fn=original, **kwargs):
            OPS[_name] += 1
            return _fn(*args, **kwargs)
        ns[name] = counted
    old_predicate = ns['_jet_is_constant']
    def observed(a):
        result = old_predicate(a)
        DECISIONS.append(result)
        return result
    ns['_jet_is_constant'] = observed
    return ns


def install_values(ns):
    def constant(value):
        return Value((value, value), True)
    def is_constant(a):
        result = classify(a)
        DECISIONS.append(result)
        return result
    def zero(a):
        return a[0] == (0, 0) and classify(a)
    def rounded(pair):
        return Value(ns['_dyadic_outward'](pair, 1 << ns['_JET_PRECISION'].get()))
    def add(a, b):
        if zero(a):
            return b
        if zero(b):
            return a
        if is_constant(a) and is_constant(b):
            return constant(a[0][0]+b[0][0])
        return rounded(ns['_add'](a[0], b[0]))
    def scale(a, q):
        if q == 0:
            return ns['_JET_ZERO']
        if q == 1:
            return a
        if is_constant(a):
            return constant(a[0][0]*q)
        return rounded(ns['_scale'](a[0], q))
    def mul(a, b):
        if is_constant(a):
            return scale(b, a[0][0])
        if is_constant(b):
            return scale(a, b[0][0])
        return rounded(ns['_mul'](a[0], b[0]))
    def reciprocal(a):
        if is_constant(a) and a[0][0] != 0:
            return constant(1/a[0][0])
        return rounded(ns['_divide'](ns['_ONE'], a[0]))
    def chart(a, b, normal, left, right, bits):
        # Same value expression, exact extrema and sqrt points as selected source.
        direction = ns['_minus'](b, a)
        dd, ad = ns['O']._dot(direction, direction), ns['O']._dot(a, direction)
        closest = max(left, min(right, -ad/dd)) if dd else left
        def radius2(t):
            point = tuple(x+t*y for x, y in zip(a, direction, strict=False))
            return ns['O']._dot(point, point)
        square = radius2(closest), max(radius2(left), radius2(right))
        if square[0] <= 0:
            raise Refused('radial angular chart reaches the origin')
        s = ns['_sqrt'](square[0], bits)[0], ns['_sqrt'](square[1], bits)[1]
        s_jet = ValueRadial(Value(s), ('sqrt-quadratic', ns['O']._dot(a, a), 2*ad, dd))
        inverse = reciprocal(s_jet)
        factor = mul(mul(inverse, inverse), inverse)
        centre_moment, derivative_moment = ns['O']._cross(normal, a), ns['O']._cross(normal, direction)
        result = []
        for x, y in zip(centre_moment, derivative_moment, strict=False):
            values = x+y*left, x+y*right
            linear = ((min(values), max(values)), (y, y), ns['_ZERO_PAIR'])
            result.append(mul(linear, factor))
        return s_jet, tuple(result)
    ns.update(_jet_constant=constant, _jet_is_constant=is_constant,
              _jet_add=add, _jet_scale=scale, _jet_mul=mul, _jet_reciprocal=reciprocal,
              _RadialJet=ValueRadial, _radial_chart_jets=chart)
    ns['_JET_ZERO'], ns['_JET_ONE'] = constant(Q(0)), constant(Q(1))


def sample_pressure(ns, a, b, profiles, donors, poly, rc, outer, gravity, bits):
    calls = []
    def capture(pieces, evaluate, coefficients, **kwargs):
        for left, right, data in pieces:
            calls.append((evaluate, ((left+right)/2,)*2+(data, bits)))
        return None
    ns['_integrate_angular'] = capture
    budget = types.SimpleNamespace(reserve=lambda *args, **kwargs: nullcontext())
    ns['_integrate_radial_pressure'](poly, a, b, profiles, donors, rc, outer, gravity,
                                    width=Q(1, 1000), max_leaves=100, budget=budget)
    return calls


def result(callback, args):
    jets, fixed = callback(*args)
    return tuple(jet[0] for jet in jets), fixed


def attempt_value(callback, args):
    """Exit the exception handler/frame before original fallback is invoked.

    The unsupported exception is neither retained nor returned. Its traceback
    must not keep the candidate call stack/temporaries alive during fallback.
    """
    try:
        return True, result(callback, args)
    except UnknownConstant:
        return False, None


def decode_capture(value, namespace):
    """Decode pressure_survey's bounded exact encoding, preserving raw types."""
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is not dict:
        raise ValueError('tagged captured value required')
    kind = value['type']
    if kind in ('int', 'Fraction'):
        numerator, denominator = int(value['n']), int(value['d'])
        if denominator <= 0 or max(abs(numerator).bit_length(), denominator.bit_length()) > 4096:
            raise ValueError('captured rational exceeds canonical bounded input')
        q = Q(numerator, denominator)
        if (q.numerator, q.denominator) != (numerator, denominator):
            raise ValueError('noncanonical captured rational')
        if kind == 'int':
            if denominator != 1:
                raise ValueError('captured integer has a denominator')
            return numerator
        return q
    if kind in ('tuple', 'list', '_RadialJet'):
        items = [decode_capture(item, namespace) for item in value['items']]
        if kind == 'list':
            return items
        if kind == '_RadialJet':
            return namespace['_RadialJet'](tuple(items), decode_capture(value['expression'], namespace))
        return tuple(items)
    raise ValueError('unsupported capture tag '+str(kind))


def captured_callback(namespace, entry):
    kind = entry['function']
    if kind not in ('pressure_evaluate', 'shell_evaluate'):
        raise ValueError('not a supported nested midpoint capture')
    parent = '_integrate_radial_pressure' if kind == 'pressure_evaluate' else '_integrate_radial_shell'
    names = ('a', 'b', 'normal', 'profiles', 'rc', 'outer', 'gravity') if kind == 'pressure_evaluate' else (
        'a', 'b', 'normal', 'bottom', 'top', 'rc')
    if set(entry['closure']) != set(names):
        raise ValueError('complete exact callback closure required')
    namespace.update({key: decode_capture(value, namespace) for key, value in entry['closure'].items()})
    tree = ast.parse(SOURCE.read_bytes())
    owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == parent)
    callback = next(node for node in ast.walk(owner) if isinstance(node, ast.FunctionDef) and node.name == 'evaluate')
    exec(compile(ast.Module(body=[callback], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    args = decode_capture(entry['arguments'], namespace)
    expected_names = ['left', 'right', 'data' if kind == 'pressure_evaluate' else 'edges', 'bits']
    if entry['argument_names'] != expected_names or len(args) != 4 or args[0] != args[1]:
        raise ValueError('exact midpoint callback arguments required')
    precision = entry['precision']
    if type(precision) is not int or not 1 <= precision <= 4096 or args[3] != precision:
        raise ValueError('captured jet precision differs from callback sqrt precision')
    namespace['_JET_PRECISION'].set(precision)
    return namespace['evaluate'], args


def replay(capture_path, output_path, capture_source_sha256=None):
    """No stage or package import: actual captured arithmetic closure only.

    Runtime source pin comes from the survey owner's actual module file hash.
    """
    raw = capture_path.read_bytes()
    if len(raw) > 8*1024*1024:
        raise ValueError('survey report exceeds bounded replay input')
    report = json.loads(raw)
    synthetic = report.get('synthetic_fixture') is True
    if not synthetic and report.get('verdict') != 'PASS':
        raise ValueError('actual capture report is not PASS')
    actual_pin = report['source_pins']['coupling']['sha256']
    if actual_pin != PIN or capture_source_sha256 not in (None, PIN):
        raise ValueError('capture/source identity mismatch')
    captures = [row for row in report['captures'] if row['function'] in ('pressure_evaluate', 'shell_evaluate')]
    if not captures:
        raise ValueError('no actual midpoint captures; absence is not a pass')
    if len(captures) > 32 or any(len(json.dumps(row).encode()) > 16384 for row in captures):
        raise ValueError('midpoint capture set exceeds survey bounds')
    rows = []
    totals_base, totals_candidate = Counter(), Counter()
    for index, entry in enumerate(captures):
        if entry['angular_context'] != 'midpoint':
            raise ValueError('nonmidpoint capture supplied')
        baseline, candidate = build_source(), build_source()
        install_values(candidate)
        old_fn, old_args = captured_callback(baseline, entry)
        new_fn, new_args = captured_callback(candidate, entry)
        retained = decode_capture(entry['expected'], baseline)
        OPS.clear(); DECISIONS.clear()
        full = old_fn(*old_args)
        assert full == retained, ('captured full jet differs from source replay', index)
        expected = tuple(jet[0] for jet in full[0]), full[1]
        base_counts, base_decisions = dict(OPS), list(DECISIONS)
        OPS.clear(); DECISIONS.clear()
        supported, actual = attempt_value(new_fn, new_args)
        fallback = not supported
        if fallback:
            actual = result(old_fn, old_args)
        assert actual == expected, ('midpoint value differs', index)
        if not fallback:
            assert DECISIONS == base_decisions, ('shortcut decision differs', index)
        counts = dict(OPS)
        totals_base.update(base_counts); totals_candidate.update(counts)
        rows.append(dict(index=index, function=entry['function'], call_index=entry['call_index'],
                         full_capture_parity=True, value_parity=True, fallback=fallback,
                         fast_constant_trace_parity=True if not fallback else None,
                         baseline_operations=base_counts, candidate_operations_including_fallback=counts))
    result_record = dict(schema='plan40a-midpoint-capture-replay-v1', source_sha256=PIN,
                         capture_sha256=hashlib.sha256(raw).hexdigest(), capture_source_sha256=actual_pin,
                         synthetic_fixture=synthetic,
                         scope=('synthetic capture-transport fixture only' if synthetic else
                                'actual captured midpoint arithmetic only')+'; no timing, full-stage or resource acceptance',
                         cases=len(rows), fast_cases=sum(not row['fallback'] for row in rows),
                         fallback_cases=sum(row['fallback'] for row in rows),
                         baseline_operations=dict(totals_base), candidate_operations_including_fallback=dict(totals_candidate),
                         cases_detail=rows)
    output_path.write_text(json.dumps(result_record, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result_record.items() if k != 'cases_detail'}, indent=2))


def selftest_replay(workdir, output_path):
    """Only transport/closure replay checks; never label these actual captures."""
    released = []
    class LifetimeMarker:
        def __del__(self):
            released.append(True)
    def unsupported(*_args):
        _marker = LifetimeMarker()
        raise UnknownConstant('lifetime fault control')
    assert attempt_value(unsupported, ()) == (False, None)
    assert released == [True], 'candidate traceback retained temporary past attempt'
    ns = build_source()
    def encode(value):
        if value is None or type(value) in (bool, str):
            return value
        if type(value) in (int, Q):
            return dict(type='int' if type(value) is int else 'Fraction', n=str(value.numerator), d=str(value.denominator))
        if isinstance(value, ns['_RadialJet']):
            return dict(type='_RadialJet', items=[encode(v) for v in value], expression=encode(value.expression))
        if type(value) in (tuple, list):
            return dict(type=type(value).__name__, items=[encode(v) for v in value])
        raise ValueError(type(value))
    a, b = (Q(2), Q(1), Q(3)), (Q(-1), Q(4), Q(2))
    poly = ((Q(1), Q(0)), (Q(3), Q(0)), (Q(0), Q(3)), (Q(0), Q(1)))
    profiles = ((Q(1), Q(20), Q(3, 7), Q(2, 3), Q(1, 2)),)
    old_fn, old_args = sample_pressure(ns, a, b, profiles, (), poly, Q(1), Q(20), Q(7, 5), 96)[0]
    closure = {name: cell.cell_contents for name, cell in zip(old_fn.__code__.co_freevars, old_fn.__closure__, strict=True)}
    expected = old_fn(*old_args)
    first = dict(function='pressure_evaluate', angular_context='midpoint', precision=96, call_index=0,
                 argument_names=['left', 'right', 'data', 'bits'], arguments=encode(old_args),
                 closure={key: encode(closure[key]) for key in ('a','b','normal','profiles','rc','outer','gravity')},
                 expected=encode(expected))
    edge = ns['_angular_wedges'](poly)[0]
    t = (edge[0]+edge[1])/2
    shell_args = t, t, (edge[2], edge[3]), 96
    shell_closure = dict(a=a, b=b, normal=ns['O']._cross(a,b), bottom=Q(1), top=Q(20), rc=Q(1))
    expected = ns['_radial_slice'](a,b,shell_closure['normal'],t,t,*shell_args[2],Q(1),Q(20),Q(1),96)
    second = dict(function='shell_evaluate', angular_context='midpoint', precision=96, call_index=1,
                  argument_names=['left', 'right', 'edges', 'bits'], arguments=encode(shell_args),
                  closure={key: encode(value) for key,value in shell_closure.items()}, expected=encode(expected))
    fixture = dict(synthetic_fixture=True, source_pins=dict(coupling=dict(path=COUPLING_REL.as_posix(),sha256=PIN)), captures=[first,second])
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir/'midpoint-value-replay-fixture.json'
    path.write_text(json.dumps(fixture,indent=2)+'\n',encoding='utf-8')
    replay(path,output_path)
    try:
        replay(path,workdir/'midpoint-value-replay-invalid-output.json','0'*64)
    except ValueError as error:
        assert str(error) == 'capture/source identity mismatch'
    else:
        raise AssertionError('source mismatch accepted')
    fixture['synthetic_fixture'], fixture['verdict'] = False, 'UNVALIDATED'
    refused_path = workdir/'midpoint-value-replay-unvalidated-fixture.json'
    refused_path.write_text(json.dumps(fixture)+'\n',encoding='utf-8')
    try:
        replay(refused_path,workdir/'midpoint-value-replay-invalid-output.json')
    except ValueError as error:
        assert str(error) == 'actual capture report is not PASS'
    else:
        raise AssertionError('unvalidated actual capture accepted')


def main(output_path):
    baseline, candidate = build_source(), build_source()
    install_values(candidate)
    rows = []
    aggregate_base, aggregate_candidate = Counter(), Counter()
    def check(label, old_callback, new_callback, args, new_args=None):
        OPS.clear(); DECISIONS.clear()
        try:
            expected = result(old_callback, args)
            failure = None
        except Exception as error:
            expected, failure = None, (type(error).__name__, str(error))
        base_counts, base_decisions = dict(OPS), list(DECISIONS)
        OPS.clear(); DECISIONS.clear()
        fallback = False
        try:
            supported, actual = attempt_value(new_callback, args if new_args is None else new_args)
            fallback = not supported
            if fallback:
                actual = result(old_callback, args)
            actual_failure = None
        except Exception as error:
            actual, actual_failure = None, (type(error).__name__, str(error))
        counts, decisions = dict(OPS), list(DECISIONS)
        assert (expected, failure) == (actual, actual_failure), (label, expected, actual, failure, actual_failure)
        if not fallback and failure is None:
            assert decisions == base_decisions, (label, 'constant shortcut decisions differ')
        aggregate_base.update(base_counts); aggregate_candidate.update(counts)
        rows.append(dict(label=label, equal=True, fallback=fallback, refusal=failure,
                         baseline_operations=base_counts, candidate_operations_including_fallback=counts))
    shapes = [((Q(1), Q(0)), (Q(3), Q(0)), (Q(0), Q(3)), (Q(0), Q(1))),
              ((Q(1, 3), Q(1, 7)), (Q(5, 2), Q(1, 7)), (Q(5, 2), Q(7, 3)), (Q(1, 3), Q(7, 3)))]
    ray_pairs = [((Q(3), Q(0), Q(0)), (Q(0), Q(4), Q(0))),
                 ((Q(2), Q(1), Q(3)), (Q(-1), Q(4), Q(2)))]
    for bits in (32, 96, 160):
        baseline['_JET_PRECISION'].set(bits); candidate['_JET_PRECISION'].set(bits)
        for ri, (a, b) in enumerate(ray_pairs):
            normal = baseline['O']._cross(a, b)
            for si, poly in enumerate(shapes):
                for wi, (left, right, entry, exit_) in enumerate(baseline['_angular_wedges'](poly)):
                    for bottom, top, rc in ((Q(1), Q(20), Q(1)), (Q(2), Q(7), Q(1)), (Q(4), Q(5), Q(2))):
                        middle = (left+right)/2
                        args = a, b, normal, middle, middle, entry, exit_, bottom, top, rc, bits
                        check(f'shell/{bits}/{ri}/{si}/{wi}/{bottom}-{top}', baseline['_radial_slice'], candidate['_radial_slice'], args)
                profile = ((Q(1), Q(4), Q(3, 7), Q(2, 3), Q(1, 2)),
                           (Q(4), Q(20), Q(5, 11), Q(1, 13), Q(1, 2)))
                for donor_case in ((), ((poly, Q(2), Q(10), Q(2, 7)),),
                                   ((poly, Q(1), Q(20), Q(-3, 11)), (shapes[1-si], Q(3), Q(7), Q(5, 13)))):
                    args = a, b, profile, donor_case, poly, Q(1), Q(20), Q(7, 5), bits
                    old = sample_pressure(baseline, *args)
                    new = sample_pressure(candidate, *args)
                    assert len(old) == len(new)
                    for wi, ((old_fn, old_args), (new_fn, new_args)) in enumerate(zip(old, new, strict=True)):
                        check(f'pressure/{bits}/{ri}/{si}/{len(donor_case)}/{wi}', old_fn, new_fn, old_args, new_args)
    # Refusal and branch controls: exact sqrt leads to conservative fallback;
    # origin must preserve the source refusal; same radial expression metadata
    # must remain a certificate even when value intervals overlap.
    baseline['_JET_PRECISION'].set(96); candidate['_JET_PRECISION'].set(96)
    a, b = (Q(3), Q(0), Q(0)), (Q(0), Q(4), Q(0))
    normal = baseline['O']._cross(a, b)
    for t in (Q(0), Q(1), Q(1, 2)):
        args = a, b, normal, t, t, None, (Q(10), Q(1), Q(0)), Q(1), Q(20), Q(1), 96
        check(f'exact-root/{t}', baseline['_radial_slice'], candidate['_radial_slice'], args)
    args = a, tuple(-v for v in a), (Q(0),)*3, Q(1, 2), Q(1, 2), None, (Q(10), Q(1), Q(0)), Q(1), Q(20), Q(1), 96
    check('origin-refusal', baseline['_radial_slice'], candidate['_radial_slice'], args)
    # Deliberate shortcut counterexample: point value alone is not constancy.
    full = ((Q(1, 3), Q(1, 3)), (Q(1), Q(1)), (Q(0), Q(0)))
    correct = baseline['_jet_scale'](full, Q(1, 3))[0]
    naive = baseline['_jet_scale']((full[0], (Q(0), Q(0)), (Q(0), Q(0))), Q(1, 3))[0]
    assert correct != naive
    unresolved_refused = False
    try:
        candidate['_jet_scale'](Value(full[0]), Q(1, 3))
    except UnknownConstant:
        unresolved_refused = True
    assert unresolved_refused
    # Equal value enclosures are not radial expression identity. Retained
    # expression tags must distinguish the two, including negative edge scale.
    sample_jet = ((Q(1), Q(2)), (Q(3), Q(4)), (Q(5), Q(6)))
    expression = ('radial-edge', ('sqrt-quadratic', Q(4), Q(-2), Q(3)), Q(2), Q(-3))
    other_expression = (*expression[:-1], Q(-4))
    identity_controls = []
    for same in (True, False):
        expr = expression if same else other_expression
        old_a, old_b = baseline['_RadialJet'](sample_jet, expression), baseline['_RadialJet'](sample_jet, expr)
        new_a, new_b = ValueRadial(Value(sample_jet[0]), expression), ValueRadial(Value(sample_jet[0]), expr)
        old = baseline['_same_radial'](old_a, old_b)
        new = candidate['_same_radial'](new_a, new_b)
        assert old == new == same
        identity_controls.append(dict(same_expression=same, equal_value_intervals=True, result=new))
    singleton_refusals = []
    for value in (Q(0), Q(1), Q(1, 3)):
        try:
            candidate['_jet_is_constant'](Value((value, value)))
        except UnknownConstant:
            singleton_refusals.append(str(value))
        else:
            raise AssertionError('unknown cancellation/zero/identity did not refuse')
    output = dict(schema='plan40a-midpoint-value-probe-v1', source_sha256=PIN, vector_source_sha256=O_PIN,
                  scope='synthetic source-bound exactness and primitive counts; no timing, production, resource or full-stage acceptance',
                  cases=len(rows), fast_cases=sum(not r['fallback'] and r['refusal'] is None for r in rows),
                  fallback_cases=sum(r['fallback'] for r in rows),
                  refused_cases=sum(r['refusal'] is not None for r in rows),
                  baseline_operations=dict(aggregate_base), candidate_operations_including_fallback=dict(aggregate_candidate),
                  naive_zero_derivative_counterexample=dict(reference=list(map(str, correct)), naive=list(map(str, naive)),
                                                            conservative_unknown_refused=unresolved_refused),
                  radial_identity_controls=identity_controls,
                  unknown_singleton_refusals=singleton_refusals, cases_detail=rows)
    output_path.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in output.items() if k != 'cases_detail'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--capture-source-sha256')
    parser.add_argument('--selftest-replay', action='store_true')
    args = parser.parse_args()
    SOURCE = args.repo / COUPLING_REL
    O_SOURCE = args.repo / OVERLAP_REL
    if args.capture:
        if args.output is None:
            parser.error('capture replay requires --output')
        replay(args.capture, args.output, args.capture_source_sha256)
    elif args.selftest_replay:
        if args.work is None:
            parser.error('replay selftest requires --work')
        selftest_replay(args.work, args.output)
    else:
        main(args.output)
