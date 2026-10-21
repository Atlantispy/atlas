"""Focused marker-source controls, delivered unrun.

Only pinned source is read. Disposable, unregistered loaded-module stand-ins
exercise function-entry observation; no Atlas import, geometry, heat, worker,
store, interval, production sys.monitoring slot or scientific acceptance.
Future owned check: P -B -s -P -m unittest discover -s THIS_DIRECTORY
    -p test_projection_marker_r1.py -v
"""
import ast
import hashlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest


HERE = Path(__file__).resolve().parent
TASK = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
JOINT = TASK / 'ac/p13c14w-r1/helpers'
PARENT = JOINT / 'fresh_interval_driver.py'
PARENT_SHA = '709f65d3d44662f04a8283ccd0265a9f0575f688ec6e96f3019fcd80328f9943'
CANDIDATE = HERE / 'candidate/helpers/fresh_interval_driver.py'
CANDIDATE_SHA = 'c6df7b959ec9309d7b7ab12f2e763c5e111138fbb2cf2d736b4c616d24132895'
PROJECTION_SHA = '7fb40186f8b2e58426f269bef8fc034e42954d937b5a09331f903c50ce550616'
PREPARED_SHA = '8dd8720cbb4a96b89dbbb78a742eb75d01e811441ab63d63fe02b2b01ee665f7'
PREFIX = ('actual-differential-geometry', 'actual-composed-heat-forward', 'heat-low-predictor',
    'heat-certified-polygon-reconstruction', 'heat-conservative-finish', 'heat-finish-correction',
    'heat-finish-closed-guard', 'heat-finish-issue', 'heat-native-projection',
    'heat-projection-decode', 'heat-projection-exact')
TICKS = ('component_volume_queries', 'heat_faces', 'heat_faces_collected',
    'metric_identity_calls', 'closed_guard_certificates', 'closed_guard_admissible_tests')
PROJECTION_STAGES = PREFIX[8:]


def pinned(path, pin):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise AssertionError('Source differs: ' + str(path))
    return raw


def loaded(name, source, filename):
    module = ModuleType(name)
    module.__file__ = str(filename)
    # No registration/removal in sys.modules; these modules are test-owned.
    exec(compile(source, str(filename), 'exec'), vars(module))
    return module


def noop(*args, **kwargs):
    return None


def guard_scan():
    def certificate(value):
        return value
    def admissible(value):
        return value
    return certificate, admissible


def model(*, n5=True, r3=True):
    original = loaded('private_heat_issuer_resources_r3',
        "def calculate():\n    return 'legacy-exact'\n", '<controlled-R3>')
    resources = loaded('private_heat_issuer_resources_r4',
        "def verified_private():\n    return 'decoded'\n", '<controlled-R4>')
    resources.calculate = original.calculate  # historical N4 alias
    numerical = loaded('private_heat_projection_numerics_r4',
        "def calculate():\n    return 'N5-exact'\n", '<controlled-Q>')
    projection = ModuleType('private_heat_native_projection_r5' if n5 else 'private_heat_native_projection_r4')
    projection.R = resources
    if n5:
        projection.NUMERICS = numerical
    receiver = 'NUMERICS' if n5 else 'R'
    exec(compile("def project():\n    R.verified_private()\n    return " + receiver +
        ".calculate()\n", '<controlled-projection>', 'exec'), vars(projection))
    finish = SimpleNamespace(finish=noop, C=SimpleNamespace(correct=noop),
        Q=SimpleNamespace(closed_guard=noop, _guard=guard_scan), I=SimpleNamespace(issue=noop))
    functions = SimpleNamespace(reconstruct=noop, _face=noop, PARALLEL=SimpleNamespace(completed=noop))
    issuer = SimpleNamespace(N=projection, F=SimpleNamespace(LOW=SimpleNamespace(solve=noop),
        FUNCTIONS=functions, FINISH=finish), INDEXED=SimpleNamespace(metric_identity=noop),
        HEAT_LEDGER=SimpleNamespace(package_result=noop))
    joined = SimpleNamespace(forward=noop, I=issuer, CAS=SimpleNamespace(save=noop), finish=noop)
    workflow = SimpleNamespace(_publish=noop)
    if r3:
        workflow._r3_after_heat_checkpoint = noop
    return SimpleNamespace(J=joined, G=SimpleNamespace(enclose_differential_ale=noop,
        component_volume_bounds=noop), Workflow=workflow)


def observed_calls(stages, project):
    codes = {function.__code__: name for function, name in stages}
    if len(codes) != 3:
        raise AssertionError('Three distinct projection function entries required')
    events = []
    previous = sys.getprofile()
    def observe(frame, event, argument):
        if event == 'call' and frame.f_code in codes:
            events.append(codes[frame.f_code])
    try:
        sys.setprofile(observe)
        result = project()
    finally:
        sys.setprofile(previous)
    if tuple(events) != PROJECTION_STAGES:
        raise AssertionError('Actual controlled calls missed/reordered markers: ' + repr(events))
    return result


def without_projection(raw):
    tree = ast.parse(raw)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name == '_projection_stages']
    if len(functions) != 1:
        raise AssertionError('Unique projection marker function required')
    function = functions[0]
    lines = raw.splitlines(keepends=True)
    return b''.join(lines[:function.lineno - 1] + lines[function.end_lineno:])


class ProjectionMarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent_raw = pinned(PARENT, PARENT_SHA)
        cls.candidate_raw = pinned(CANDIDATE, CANDIDATE_SHA)
        cls.driver = loaded('controlled_candidate_fresh_driver', cls.candidate_raw, CANDIDATE)

    def test_n5_observes_loaded_Q_and_preserves_R_decode(self):
        m = model(n5=True)
        N = m.J.I.N
        stages = self.driver._projection_stages(m)
        self.assertEqual(tuple(name for _, name in stages), PROJECTION_STAGES)
        self.assertIs(stages[0][0], N.project)
        self.assertIs(stages[1][0], N.R.verified_private)
        self.assertIs(stages[2][0], N.NUMERICS.calculate)
        self.assertIsNot(stages[2][0], N.R.calculate)
        self.assertEqual(observed_calls(stages, N.project), 'N5-exact')

    def test_legacy_n4_keeps_original_R3_alias_and_three_calls(self):
        m = model(n5=False)
        N = m.J.I.N
        stages = self.driver._projection_stages(m)
        self.assertIs(stages[2][0], N.R.calculate)
        self.assertEqual(stages[2][0].__module__, 'private_heat_issuer_resources_r3')
        self.assertEqual(observed_calls(stages, N.project), 'legacy-exact')

    def test_actual_old_joint_stale_R_target_mutation_is_detected(self):
        stale = loaded('controlled_stale_driver', self.parent_raw, PARENT)
        m = model(n5=True)
        with self.assertRaisesRegex(AssertionError, 'missed/reordered'):
            observed_calls(stale._projection_stages(m), m.J.I.N.project)

    def test_dropped_exact_marker_mutation_is_detected(self):
        m = model(n5=True)
        with self.assertRaisesRegex(AssertionError, 'Three distinct'):
            observed_calls(self.driver._projection_stages(m)[:-1], m.J.I.N.project)

    def test_present_invalid_NUMERICS_refuses_instead_of_old_R_fallback(self):
        m = model(n5=True)
        m.J.I.N.NUMERICS = SimpleNamespace()
        with self.assertRaises(AttributeError):
            self.driver._projection_stages(m)

    def test_prefix_11_six_ticks_and_totals_16_15_preserved(self):
        for n5 in (False, True):
            for r3 in (False, True):
                with self.subTest(n5=n5, r3=r3):
                    m = model(n5=n5, r3=r3)
                    stages, ticks = self.driver._stages(m), self.driver._ticks(m)
                    self.assertEqual(tuple(name for _, name in stages[:11]), PREFIX)
                    self.assertEqual(len(stages), 16 if r3 else 15)
                    self.assertEqual(tuple(name for _, name in ticks), TICKS)
                    certificate, admissible = guard_scan()
                    self.assertIs(ticks[4][0].__code__, certificate.__code__)
                    self.assertIs(ticks[5][0].__code__, admissible.__code__)

    def test_only_projection_marker_function_bytes_change(self):
        self.assertEqual(without_projection(self.parent_raw), without_projection(self.candidate_raw))

    def test_actual_pinned_N5_calls_NUMERICS_not_R_calculate(self):
        raw = pinned(JOINT / 'private_heat_native_projection_r5.py', PROJECTION_SHA)
        tree = ast.parse(raw)
        imports = {alias.asname: alias.name for node in tree.body if isinstance(node, ast.Import)
            for alias in node.names}
        self.assertEqual(imports['NUMERICS'], 'private_heat_projection_numerics_r4')
        self.assertEqual(imports['R'], 'private_heat_issuer_resources_r4')
        project = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'project')
        calls = [(node.func.value.id, node.func.attr) for node in ast.walk(project)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)]
        self.assertEqual(calls.count(('NUMERICS', 'calculate')), 1)
        self.assertEqual(calls.count(('R', 'calculate')), 0)
        self.assertEqual(calls.count(('R', 'verified_private')), 1)

    def test_prepared_ordinary_keeps_the_same_shared_stage_tick_functions(self):
        raw = pinned(JOINT / 'prepared_interval_driver.py', PREPARED_SHA)
        tree = ast.parse(raw)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name == 'advance_prepared_interval')
        shared = [node for node in ast.walk(function) if isinstance(node, ast.If)
            and any(isinstance(statement, ast.ImportFrom) and statement.module == 'fresh_interval_driver'
                for statement in node.body)]
        self.assertEqual(len(shared), 1)
        self.assertEqual(ast.unparse(shared[0].test), 'ordinary')
        imported = [node for node in shared[0].body if isinstance(node, ast.ImportFrom)]
        self.assertEqual(len(imported), 1)
        self.assertEqual([(alias.name, alias.asname) for alias in imported[0].names],
            [('_stages', None), ('_ticks', None)])
        expressions = [ast.unparse(node) for node in shared[0].body]
        self.assertIn('stages, ticks = (_stages(shared), _ticks(shared))', expressions)


if __name__ == '__main__':
    unittest.main()
