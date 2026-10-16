"""Unit tests and planted mutants for the pose width successor (design r2). Synthetic inputs only.

Usage: python -B unit_width.py frozen:<composed folder> OUT_JSON [--digest-only]

Sections (each check is exact: Fractions and ints, no binary64 in any comparison):
  T  transforms: input pin, second application and anchor counts refuse; the composed files are the
     transform outputs recorded in WIDTH_COMPOSITION.json.
  A  equality: the composed W._pose_vector and E._representative_pose equal the probe r3 reference
     (pose_round_probe_r3.py, written from the design before the transform) on every probe row,
     n = 1 to 1,000, and the rows are written in probe r3's format for check_round_mpmath_r3.py.
  B  properties, independent of the reference, on every prefix k = 1..50 of each history:
     ray (L0, L24, end pose and swept step) and quaternion steps satisfy
       added radius > 0, added**2 >= |rounded - unrounded|_2**2   (local enclosure)
       added radius < 2**(1-12) * min(delta, t_L) (ray) or delta (quaternion)   (precision bar)
       added radius >= q, the design quantum of the step (worst-case margin: covers any rounding move)
     (plus 8 single-segment quaternion rates, so the round-down case of the radius is covered)
     where unrounded = the unchanged step primitive applied to the previous rounded state; types are
     tuples of Fractions; a step with delta == 0 is untouched; end(k) == start(k+1).
  C  axis certificate: for coaxial histories (and n = 1), the rotation CartesianCell.rotated builds
     from the rounded quaternion keeps P._common_axis, _KernelPose._axis and P._pose_axis non-None at
     every prefix and at n = 1,000; for alternating histories (n >= 2) all three are None.
  D  (c) _stored_deviation: outward, < 2**-64 relative above, <= width, 0 -> 0, refuses unchecked input.
  F  determinism: the inserted source has no float literal, float(), math or int-base power outside
     Q(); a child process with another PYTHONHASHSEED reproduces the section A/B digest.
  M  planted mutants, each applied to the composed module text and exec'd into a copy of that module's
     namespace; each must be caught by at least one check above.
Exit 0 only if the clean build passes everything and every mutant is caught.
"""
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import types
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = 12                       # the design's guards; never read from the module under test
DEVIATION_BITS = 64
PREFIX_MAX = 50
BIG = 1000


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load(HERE/'pose_round_probe_r3.py', 'width_probe_r3')
pose_round = _load(HERE/'width_pose_round.py', 'width_pose_round')
deviation = _load(HERE/'width_deviation_bound.py', 'width_deviation_bound')
text = probe.text


def norm2(a, b):
    return sum((x-y)**2 for x, y in zip(a, b, strict=True))


def fractions(values):
    return type(values) is tuple and all(type(q) is Q for q in values)


class Checks:
    def __init__(self):
        self.failures = []
        self.count = 0

    def require(self, ok, *what):
        self.count += 1
        if not ok:
            self.failures.append(' '.join(map(str, what)))


# ---------------------------------------------------------------------------------------------
# The runtime and the synthetic histories (probe r3's)

def setup(runtime):
    sys.path.insert(0, str(HERE.parent/'scripts'))
    import rc1_env
    rc1_env.install(runtime)
    from atlas_tectonics import integration_differential_mesh as M
    from atlas_tectonics import integration_differential_pressure as DP
    from atlas_tectonics import integration_exterior_mesh as E
    from atlas_tectonics import integration_spatial_pressure as P
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_volume_overlap as O
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    return dict(M=M, DP=DP, E=E, P=P, V=V, B=B, O=O, W=W, budget=WorkBudget(1 << 32), rc1_env=rc1_env)


DURATION = Q(float(3.15576e13))
RAY = tuple(Q(float(v)) for v in (0.6, 0.0, 0.8))
ZERO = (Q(0),)*3


def histories():
    for name, rate, kind, counts in probe.CASES:
        pattern = [tuple(Q(float(rate*a)) for a in probe.AXIS)]
        if kind == 'alternating':
            pattern.append(tuple(Q(float(rate*a)) for a in probe.OTHER_AXIS))
        yield name, kind, counts, pattern


def segments_of(rates, V):
    return [dict(angular_velocity_rad_s=[V._encoded(q) for q in w], start_time_s=V._encoded(Q(0)),
                 end_time_s=V._encoded(DURATION)) for w in rates]


# ---------------------------------------------------------------------------------------------
# Section B (and C at every prefix): properties against the unchanged step primitives

def ray_properties(env, fn, pattern, name, check, arena):
    W = env['W']
    for level in (0, 24):
        prev_v, prev_e = RAY, Q(0)
        for k in range(1, PREFIX_MAX+1):
            history = tuple((pattern[i % len(pattern)], DURATION) for i in range(k))
            w = history[-1][0]
            v, e = fn['pose_vector'](RAY, ZERO, DURATION, DURATION, level, arena, history)
            tag = '%s L%d k=%d' % (name, level, k)
            check.require(fractions(v) and type(e) is Q, 'ray types', tag)
            u, delta = W._rotated_normal(prev_v, w, DURATION, DURATION, level, arena)
            target = max(map(abs, prev_v))/Q(2**(32+2*level))
            local(check, 'ray', tag, v, e, u, prev_e+delta, delta and min(delta, target))
            # swept current step [0, d] after k-1 priors
            sv, se = fn['pose_vector'](RAY, w, Q(0), DURATION, level, arena, history[:-1])
            su, sdelta = W._rotated_normal(prev_v, w, Q(0), DURATION, level, arena)
            local(check, 'sweep', tag, sv, se, su, prev_e+sdelta, sdelta and min(sdelta, target))
            # end(k) through the current step at t0 = t1 = d equals start(k+1) at t0 = t1 = 0
            end = fn['pose_vector'](RAY, w, DURATION, DURATION, level, arena, history[:-1])
            start = fn['pose_vector'](RAY, pattern[k % len(pattern)], Q(0), Q(0), level, arena, history)
            check.require(end == start == (v, e), 'end(k) != start(k+1)', tag)
            prev_v, prev_e = v, e
    # delta == 0 rule at t0 = t1 = 0: the input value (an equal new tuple), radius exactly 0
    w = pattern[0]
    v, e = fn['pose_vector'](RAY, w, Q(0), Q(0), 24, arena)
    check.require(v == RAY and all(type(x) is Q for x in v) and type(e) is Q and e == 0,
                  'delta rule t0 = t1 = 0', name)


def quantum_of(scale):
    """The design quantum 2**(floor(log2 scale) - G), by repeated halving/doubling (not bit_length)."""
    k, p = 0, Q(1)
    while p > scale:
        k, p = k-1, p/2
    while p*2 <= scale:
        k, p = k+1, p*2
    return p/2**GUARD


def local(check, kind, tag, rounded, radius, unrounded, exact_radius, scale):
    """added = radius - exact_radius must enclose the move and stay under 2**(1-G)*scale.

    The worst-case margin added >= q (the design quantum of this step) is what makes the enclosure hold
    for every input: the rounding move is <= sqrt(3)/2 q (ray), <= q (quaternion, componentwise) or
    <= q/sqrt(2) (coaxial). The observed move alone can be small on a given input.
    """
    added = radius-exact_radius
    if not scale:                                    # delta == 0: nothing may change
        check.require(rounded == unrounded and added == 0, kind, 'exact step changed', tag)
        return
    check.require(added > 0 and added*added >= norm2(rounded, unrounded), kind, 'local enclosure', tag)
    check.require(added >= quantum_of(scale), kind, 'worst-case margin', tag)
    check.require(added < Q(2)**(1-GUARD)*scale, kind, 'precision bar', tag)


def axis_routes(env, quaternion, error, rates):
    V, P, DP, budget = env['V'], env['P'], env['DP'], env['budget']
    rotation = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
    pose = DP._KernelPose(rotation, error, history=[(w, DURATION) for w in rates])
    return (P._common_axis(rotation, rates) is not None, pose._axis is not None,
            P._pose_axis(pose, budget) is not None)


def quat_properties(env, fn, pattern, name, kind, check, arena):
    E, O = env['E'], env['O']
    zero_segment = segments_of([ZERO], env['V'])
    goal = probe.OPERATOR_GOAL/(8*PREFIX_MAX)
    q0, d0 = E._segment_quaternion(ZERO, DURATION, goal, arena)
    check.require(q0 == (1, 0, 0, 0) and d0 == 0, 'zero segment is not the exact identity')
    rates = [pattern[i % len(pattern)] for i in range(PREFIX_MAX)]
    segments = segments_of(rates, env['V'])
    prev_q, prev_e = (Q(1), Q(0), Q(0), Q(0)), Q(0)
    for k in range(1, PREFIX_MAX+1):
        tag = '%s k=%d' % (name, k)
        rq, e4 = fn['representative_pose'](segments[:k]+zero_segment*(PREFIX_MAX-k), probe.OPERATOR_GOAL, arena)
        check.require(fractions(rq) and type(e4) is Q, 'quat types', tag)
        e = e4/4
        qseg, delta = E._segment_quaternion(rates[k-1], DURATION, goal, arena)
        local(check, 'quat', tag, rq, e, E._qmul(qseg, prev_q), (1+delta)*prev_e+delta, delta)
        coaxial = kind == 'coaxial' or k == 1
        if coaxial:
            check.require(not any(O._cross(rq[1:], rates[0])), 'quat vector part left the axis', tag)
        routes = axis_routes(env, rq, e4, rates[:k])
        check.require(routes == (coaxial,)*3, 'axis routes', routes, tag)
        prev_q, prev_e = rq, e


SPREAD = tuple(Q(17+j, 16) for j in range(8))      # rate multipliers of the 'rep' rate


def quat_spread(env, fn, check, arena):
    """Single-segment poses over 8 rates, so frac(delta/q) is not one constant per history.

    A segment's delta depends only on its rate, duration and goal, so every step of a history at one
    rate has the same frac(delta/q). The checks need a step where round-to-nearest of the radius would
    round down (frac in (0, 1/2)); coverage of that case is itself required (fail-closed).
    """
    E = env['E']
    rep = next(pattern for name, _kind, _counts, pattern in histories() if name == 'rep')[0]
    goal = probe.OPERATOR_GOAL/8
    below_half = 0
    for m in SPREAD:
        w = tuple(m*c for c in rep)
        rq, e4 = fn['representative_pose'](segments_of([w], env['V']), probe.OPERATOR_GOAL, arena)
        qseg, delta = E._segment_quaternion(w, DURATION, goal, arena)
        tag = 'spread %s' % m
        check.require(fractions(rq) and type(e4) is Q, 'quat types', tag)
        local(check, 'quat', tag, rq, e4/4, E._qmul(qseg, (Q(1), Q(0), Q(0), Q(0))), delta, delta)
        x = delta/quantum_of(delta)
        below_half += 0 < x-x.numerator//x.denominator < Q(1, 2)
    check.require(below_half > 0, 'spread coverage: no step with frac(delta/q) in (0, 1/2)')


def deviation_properties(stored, check):
    cases = [(Q(0), Q(1)), (Q(1, 3), Q(1)), (Q(7, 5)*Q(2)**-90, Q(1)), (Q(2)**70+Q(1, 7), Q(2)**71),
             (Q(1)-Q(1, 3**80), Q(1)), (Q(3, 2**200)+Q(1, 3**140), Q(1, 2**150)), (Q(5), Q(5)),
             (Q(1, 3), Q(1, 3)), (Q(2)**70+Q(1, 7), Q(2)**70+Q(1, 7))]   # width == a non-dyadic total: capped
    for total, width in cases:
        s = stored(total, width)
        tag = 'deviation %s/%s' % (total.numerator.bit_length(), total.denominator.bit_length())
        check.require(type(s) is Q, tag, 'type')
        check.require(s >= total, tag, 'not outward')
        check.require(s <= width, tag, 'above width')
        check.require(s-total <= total*Q(2)**-DEVIATION_BITS, tag, 'relative excess')
        check.require((total == 0) == (s == 0), tag, 'zero')
        if total and s != width:                     # a capped value is width itself
            check.require(s.denominator.bit_length() <= max(1, -total.numerator.bit_length()
                                                             + total.denominator.bit_length()+DEVIATION_BITS+2),
                          tag, 'not short')
    for bad in ((Q(2), Q(1)), (Q(-1), Q(1)), (1.0, Q(1)), (Q(1, 2), 1)):
        try:
            stored(*bad)
            check.require(False, 'deviation accepted unchecked input', bad)
        except Exception as error:      # noqa: BLE001 - the type is checked next
            check.require(type(error).__name__ == 'VolumeError', 'deviation refusal type', type(error).__name__)


def runtime_sources(env_module):
    """sha256 of every loaded .py file under the selected runtime's src and helpers, relative to its folder.

    (rc1_env.loaded_sources() names files relative to the RC1 tree, so it cannot name a frozen: folder.)
    """
    roots = (env_module.RC1_ROOT, env_module.HELPERS)
    out = {}
    for _name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and path.endswith('.py'):
            p = Path(path).resolve()
            if any(p.is_relative_to(root) for root in roots):
                out[p.relative_to(env_module.RC1_ROOT.parent).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------------------------
# Section F: static determinism scan of the inserted source

def float_free(source):
    """Problems in source: float literals, float(), math, or ** on an int literal outside Q()."""
    problems = []
    tree = ast.parse(textwrap.dedent(source))   # the check insert is an indented block
    inside_q = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Q':
            inside_q.update(id(arg) for arg in node.args)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is float:
            problems.append('float literal %r' % node.value)
        elif isinstance(node, ast.Name) and node.id in ('float', 'math'):
            problems.append('uses '+node.id)
        elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and isinstance(node.left, ast.Constant)
              and id(node) not in inside_q):
            problems.append('int-base power outside Q()')
    return problems


def inserted_sources():
    return {'b-ray': pose_round.WALL_NEW, 'b-quat': pose_round.QUAT_NEW,
            'c-helper': deviation.HELPER_NEW, 'c-check': deviation.CHECK_NEW}


# ---------------------------------------------------------------------------------------------
# Sections A and C at full length

def equality_rows(env, check, arena, digest_only):
    W, E, O = env['W'], env['E'], env['O']
    cases = []
    for name, kind, counts, pattern in histories():
        rows = []
        for n in counts:
            if digest_only and n > PREFIX_MAX:
                continue
            rates = [pattern[i % len(pattern)] for i in range(n)]
            history = tuple((w, DURATION) for w in rates)
            segments = segments_of(rates, env['V'])
            tag = '%s n=%d' % (name, n)
            rq, rerr = E._representative_pose(segments, probe.OPERATOR_GOAL, arena)
            pq, perr, pref = probe.rounded_representative_pose(E, O, W, segments, probe.OPERATOR_GOAL, arena)
            check.require((rq, rerr) == (pq, perr), 'quaternion differs from the design reference', tag)
            coaxial = kind == 'coaxial' or n == 1
            routes = axis_routes(env, rq, rerr, rates)
            check.require(routes == (coaxial,)*3, 'axis routes', routes, tag)
            mq, _, _ = probe.rounded_representative_pose(E, O, W, segments, probe.OPERATOR_GOAL, arena,
                                                         keep_axis=False)
            row = dict(steps=n, quat=[text(v) for v in rq], quat_error_exact=text(rerr),
                       quat_added_share=probe.share(rerr, pref), quat_bits=probe.bits(rq),
                       quat_axis_kept=routes[0], mutant_componentwise_axis_kept=axis_routes(env, mq, perr, rates)[0])
            for level in (0, 24):
                rv, verr = W._pose_vector(RAY, ZERO, DURATION, DURATION, level, arena, history)
                ref = probe.rounded_pose_vector(W, RAY, ZERO, DURATION, DURATION, level, arena, history)
                check.require((rv, verr) == ref[:2], 'ray differs from the design reference', level, tag)
                sv, serr = W._pose_vector(RAY, rates[-1], Q(0), DURATION, level, arena, history[:-1])
                sref = probe.rounded_pose_vector(W, RAY, rates[-1], Q(0), DURATION, level, arena, history[:-1])
                check.require((sv, serr) == sref[:2], 'sweep differs from the design reference', level, tag)
                row.update({'ray%d' % level: [text(v) for v in rv], 'ray%d_error_exact' % level: text(verr),
                            'ray%d_added_share' % level: probe.share(verr, ref[2]),
                            'ray%d_bits' % level: probe.bits(rv),
                            'sweep%d' % level: [text(v) for v in sv], 'sweep%d_error_exact' % level: text(serr)})
            rows.append(row)
        cases.append(dict(name=name, kind=kind, pattern=[[text(q) for q in w] for w in pattern], rows=rows))
    return cases


def suite(env, fn, check, arena, *, sections=('ray', 'quat', 'dev', 'static'), sources=None):
    for name, kind, _counts, pattern in histories():
        if 'ray' in sections:
            ray_properties(env, fn, pattern, name, check, arena)
        if 'quat' in sections:
            quat_properties(env, fn, pattern, name, kind, check, arena)
    if 'quat' in sections:
        quat_spread(env, fn, check, arena)
    if 'dev' in sections:
        deviation_properties(fn['stored_deviation'], check)
    if 'static' in sections:
        for label, source in (sources or inserted_sources()).items():
            for problem in float_free(source):
                check.require(False, 'static', label, problem)


# ---------------------------------------------------------------------------------------------
# Section M: planted mutants

MUTANTS = (
    ('ray: no radius added', 'W', (('            error = _round_up(error+quantum, quantum)\n', ''),), 'ray'),
    ('ray: round-nearest radius', 'W', (('            error = _round_up(error+quantum, quantum)\n',
                                         '            error = round((error+quantum)/quantum)*quantum\n'),), 'ray'),
    ('ray: quantum 2**4 too coarse', 'W', (('POSE_ROUND_GUARD_RAY = 12', 'POSE_ROUND_GUARD_RAY = 8'),), 'ray'),
    ('ray: quantum from t_L alone', 'W', (('_floor_log2(min(delta, target))', '_floor_log2(target)'),), 'ray'),
    ('ray: rounds when delta == 0', 'W', (('        if delta:\n            # Round to nearest',
                                           '        if True:\n            # Round to nearest'),
                                          ('min(delta, target))-', 'min(delta or target, target))-')), 'ray'),
    ('ray: binary64 quantum', 'W', (('quantum = Q(2)**(_floor_log2(min(delta, target))-POSE_ROUND_GUARD_RAY)',
                                     'quantum = Q(2.0**(_floor_log2(min(delta, target))-POSE_ROUND_GUARD_RAY))'),),
     'static'),
    ('quat: no radius added', 'E', (('    return quaternion, W._round_up(error+quantum, quantum)\n',
                                     '    return quaternion, error\n'),), 'quat'),
    ('quat: round-nearest radius', 'E', (('    return quaternion, W._round_up(error+quantum, quantum)\n',
                                          '    return quaternion, round((error+quantum)/quantum)*quantum\n'),),
     'quat'),
    ('quat: quantum 2**4 too coarse', 'E', (('POSE_ROUND_GUARD_QUAT = 12', 'POSE_ROUND_GUARD_QUAT = 8'),), 'quat'),
    ('quat: componentwise on a coaxial history (drops the axis)', 'E',
     (('    axis = _pose_round_axis(', '    axis = None and _pose_round_axis('),), 'quat'),
    ('quat: axis scale step 2**4 too coarse', 'E',
     (('step = Q(2)**(W._floor_log2(quantum)-W._ceil_log2(', 'step = Q(2)**(W._floor_log2(quantum)+4-W._ceil_log2('),),
     'quat'),
    ('dev: stores a round-down', 'M', (('return min(-((-total)//quantum)*quantum, width)',
                                       'return min((total//quantum)*quantum, width)'),), 'dev'),
    ('dev: stored value not capped at width', 'M', (('return min(-((-total)//quantum)*quantum, width)',
                                                    'return -((-total)//quantum)*quantum'),), 'dev'),
)
FILES = {'W': 'integration_wall_measures.py', 'E': 'integration_exterior_mesh.py',
         'M': 'integration_differential_mesh.py'}


def mutated_namespace(module, source, edits):
    """A copy of module's namespace with every top-level definition the edits change re-executed."""
    mutated = source
    for old, new in edits:
        if mutated.count(old) != 1:
            raise ValueError('mutant anchor must occur exactly once: '+old.strip()[:60])
        mutated = mutated.replace(old, new)
    before = {name: segment for name, segment in _top_level(source)}
    changed = [segment for name, segment in _top_level(mutated) if before.get(name) != segment]
    if not changed:
        raise ValueError('mutant changed no definition')
    namespace = dict(module.__dict__)
    exec(compile('\n\n'.join(changed), '<mutant %s>' % module.__name__, 'exec'), namespace)
    # Rebind every unchanged module-level function to the copy, so a caller of a mutated helper or
    # constant (e.g. _representative_pose -> _pose_round) runs the mutant, not the original.
    for name, value in list(namespace.items()):
        if isinstance(value, types.FunctionType) and value.__globals__ is module.__dict__:
            clone = types.FunctionType(value.__code__, namespace, value.__name__, value.__defaults__,
                                       value.__closure__)
            clone.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = clone
    return namespace, '\n\n'.join(changed)


def _top_level(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            name = node.name if isinstance(node, ast.FunctionDef) else ast.unparse(node.targets[0])
            yield name, ast.get_source_segment(source, node)


def run_mutants(env, clean_fn, arena, clean_failures):
    package = Path(env['W'].__file__).resolve().parent
    results = []
    for label, key, edits, section in MUTANTS:
        module = env[key]
        namespace, changed = mutated_namespace(module, (package/FILES[key]).read_text(encoding='utf8'), edits)
        fn = dict(clean_fn)
        if key == 'W':
            fn['pose_vector'] = namespace['_pose_vector']
        elif key == 'E':
            fn['representative_pose'] = namespace['_representative_pose']
        else:
            fn['stored_deviation'] = namespace['_stored_deviation']
        check, raised = Checks(), None
        try:
            suite(env, fn, check, arena, sections=(section,), sources={'mutant': changed})
        except Exception as error:      # noqa: BLE001 - an exception is a catch only if it is a refusal
            raised = error
        # only failures the clean build does not also have count as a catch
        new = [f for f in check.failures if f not in clean_failures]
        first = sorted(set(f.split(' k=')[0] for f in new))[:4]
        if raised is not None:
            first.append('raised %s: %s' % (type(raised).__name__, raised))
        caught = bool(new) or type(raised).__name__ == 'VolumeError'
        results.append(dict(mutant=label, section=section, caught=caught, first_failures=first,
                            failing_checks=len(new), checks=check.count))
        print('MUTANT %-58s %s %s' % (label, 'CAUGHT' if caught else 'MISSED', first[:2]), flush=True)
    return results


# ---------------------------------------------------------------------------------------------
# Section T: the transforms themselves

def transform_checks(env, check, runtime):
    package = Path(env['W'].__file__).resolve().parent
    folder = package.parents[1]
    manifest = json.loads((folder/'WIDTH_COMPOSITION.json').read_text(encoding='utf8'))
    for entry in manifest['transforms']:
        data = (package/Path(entry['file']).name).read_bytes()
        check.require(hashlib.sha256(data).hexdigest() == entry['output_sha256'], 'composed file differs',
                      entry['file'])
    for module, transforms in ((pose_round, pose_round.TRANSFORMS), (deviation, deviation.TRANSFORMS)):
        for name, transform in transforms.items():
            applied = (package/name).read_text(encoding='utf8')
            for label, source in (('second application', applied),
                                  ('unpinned input', applied.replace(module.MARKER if isinstance(module.MARKER, str)
                                                                     else module.MARKER[name], 'X_UNPINNED'))):
                try:
                    transform(source)
                    check.require(False, 'transform accepted', label, name)
                except ValueError:
                    check.require(True)


def main():
    runtime, out, digest_only = sys.argv[1], Path(sys.argv[2]), '--digest-only' in sys.argv[3:]
    env = setup(runtime)
    fn = dict(pose_vector=env['W']._pose_vector, representative_pose=env['E']._representative_pose,
              stored_deviation=env['M']._stored_deviation)
    check = Checks()
    with env['B']._Arena(env['budget']) as arena:
        cases = equality_rows(env, check, arena, digest_only)
        suite(env, fn, check, arena)
        digest = hashlib.sha256(json.dumps(dict(cases=[dict(c, rows=[r for r in c['rows'] if r['steps'] <= PREFIX_MAX])
                                                       for c in cases]), sort_keys=True).encode()).hexdigest()
        if digest_only:
            print('DIGEST', digest)
            raise SystemExit(1 if check.failures else 0)
        transform_checks(env, check, runtime)
        print('clean build: %d checks, %d failures' % (check.count, len(check.failures)), flush=True)
        for failure in check.failures[:20]:
            print('  FAIL', failure)
        child = subprocess.run([sys.executable, '-B', '-I', __file__, runtime, os.devnull, '--digest-only'],
                               capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED='1'))
        child_digest = next((line.split()[1] for line in child.stdout.splitlines() if line.startswith('DIGEST')), None)
        check.require(child.returncode == 0 and child_digest == digest, 'determinism: child digest', child_digest)
        mutants = run_mutants(env, fn, arena, set(check.failures))
    missed = [m['mutant'] for m in mutants if not m['caught']]
    out.write_text(json.dumps(dict(duration=text(DURATION), ray=[text(q) for q in RAY],
                                   operator_goal=text(probe.OPERATOR_GOAL), guard_ray=GUARD, guard_quat=GUARD,
                                   delta_rule=not any('delta rule' in f for f in check.failures),
                                   failures=check.failures, cases=cases, digest=digest, child_digest=child_digest,
                                   mutants=mutants, checks=check.count,
                                   loaded_sources=runtime_sources(env['rc1_env'])), indent=1), encoding='utf8')
    print('determinism digest %s child %s' % (digest[:16], (child_digest or '-')[:16]))
    print('UNIT WIDTH %s: %d checks, %d failures; mutants caught %d/%d%s' % (
        'PASS' if not check.failures and not missed else 'FAIL', check.count, len(check.failures),
        len(mutants)-len(missed), len(mutants), (' MISSED %r' % missed) if missed else ''))
    raise SystemExit(1 if check.failures or missed else 0)


if __name__ == '__main__':
    main()
