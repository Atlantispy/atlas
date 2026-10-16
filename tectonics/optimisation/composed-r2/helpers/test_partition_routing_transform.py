"""Pure text controls for the compact routing transforms; nothing is executed.

Frozen runtime-integration-r1 inputs and historical helper/control texts are
read, never written. Historical texts are compiled and AST-compared only; no
historical module is executed. The checkpoint transforms are composed through
a short staging directory, as the composer must.
"""
import ast
import difflib
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NATIVE = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
HISTORICAL = HERE.parents[3]/'heat-repair-20261007'
SHORT = HERE.parents[4]/'_t'/'w1c'
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT/'endpoint-checkpoints')]

import partition_routing_transform as RT
import patch_ale_checkpoints as AC
import patch_endpoint_scheduler as SC


# Recorded output identities of this reviewed transform text on the frozen inputs.
OUTPUTS = {
    'integration_routing_views': '8bcfb2f92c091024817f81e7c6a16718130547df7c3088f342a0578deffc032d',
    'integration_differential_ale': 'f3885ba120d83da6f1414f17583294a376510f8d3099e40317f71f8daee16dab',
    'integration_parallel_dispatch': '2545cb43b9dfac6a47b8b6c99147206c3542ea945bdde460534bf37043347782',
    'integration_parallel_selection': '536c3e3e9328db0758e6f9d1821a68e729ef2cf023d45d01d02b5cbbc446926c',
    'integration_component_volume_auto': '789f1f70d79a8c3ed66df721c017184a2a39eac767f2436dcf7bd9501a7471d9',
    'integration_differential_trace': '4519d95cdbcc3afa7053ac8813190f1987e4db64a19519eda620c512dd6fb545',
}
# routing -> ALE checkpoint (staged), routing -> transform_auto, transform_rolling(frozen).
COMPOSED = {'ale': '9d20f9f2217e23839270cca1ca3daf9530dc9a9da68f701cb185b085d41ed644',
            'auto': '72cb051ecc3a3be369891add19922e3c62f57f0367995c8dffedd2770e12c3b9',
            'rolling': '6daa2d3a84a224fe9e4724cd0212d0195c474a044440a5f6df36c9cd37c7981a'}
HELPER_OUTPUT = '3d859c53c9b731fccbba09609b9c86c3104f445cc9c5f46367f63ef6ebc144df'
DERIVED_OUTPUT = 'f97394f6d1025ca39cfd59137328f33d58fc79b2f8d7f0ee0b6139396b8654bd'
CHANGED = {
    'integration_routing_views': {'SupportRoutingRows.project', 'SupportRoutingRows.__getitem__'},
    'integration_differential_ale': {'_coincident_boundary_faces', '_route_exterior_surfaces', '_enclose'},
    'integration_parallel_dispatch': {'transport', '_request', '_wall_request', 'InterfaceParallelSession.prepare',
        'InterfaceParallelSession._select', 'InterfaceParallelSession._screen', 'InterfaceParallelSession._dispatch',
        'BatchParallelSession._support_facts', 'BatchParallelSession._bind_jobs'},
    'integration_parallel_selection': {'_Rolling._facts'},
    'integration_component_volume_auto': {'AutomaticEndpoints.bind_support'},
    'integration_differential_trace': {'PreparedDifferentialTrace._construct'},
}
# Rewritten, not merely branched: the same size predicate (transport) or the
# InputMap container. Their behaviour is checked by the runtime fixture tests.
REWRITTEN = {'InterfaceParallelSession.prepare', 'InterfaceParallelSession._select',
             'InterfaceParallelSession._dispatch', 'BatchParallelSession._bind_jobs'}
# Branch tests of compact plumbing -> the ordinary statements they guard.
ORDINARY = {
    "getattr(support, '_compact_ref', None) is not None": 'orelse',
    'compact is not None and type(self._handles.get(key)) is compact.CompactSupport': 'orelse',
    "getattr(partition, '_compact', None) is None": 'body',
    "getattr(component_partition, '_compact', None) is None": 'body',
    'type(support) is _CompactSupport': 'orelse',
    'type(support) is CompactSupport': 'orelse',
    "type(support) is CompactSupport or getattr(support, '_compact_ref', None) is not None": 'orelse',
    "getattr(partition, '_compact', None) is not None": 'orelse',
    'compact_continuation_state(partition, spatial_state)': 'orelse',
}
PLUMBING_MODULES = {'partition_routing_patch', 'partition_native_patch', 'funding_transfer'}


def frozen(name):
    return (NATIVE/(name+'.py')).read_text(encoding='utf8')


def helper_text():
    return (HISTORICAL/'private_heat_original_continuation_r1.py').read_text(encoding='utf8')


def control_text():
    return (HISTORICAL/'source'/'tectonics'/'tests'/'i04_differential_continuation_control.py').read_text(encoding='utf8')


def helper_edits(source):
    """_EDITS and _replace_exact from a helper text; pure definitions only."""
    namespace, tree = {}, ast.parse(source)
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == '_EDITS'
            for t in n.targets)) or (isinstance(n, ast.FunctionDef) and n.name == '_replace_exact')]
    if len(keep) != 2:
        raise AssertionError('helper edit definitions differ')
    exec(compile(ast.Module(keep, []), 'helper-edits', 'exec'), namespace)
    return namespace['_EDITS'], namespace['_replace_exact']


def functions(source):
    found = {}
    def walk(nodes, prefix):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix+n.name] = n
                walk(n.body, prefix+n.name+'.<locals>.')
            elif isinstance(n, ast.ClassDef):
                walk(n.body, prefix+n.name+'.')
            else:
                for f in ('body', 'orelse', 'finalbody', 'handlers'):
                    walk(getattr(n, f, None) or [], prefix)
    walk(ast.parse(source).body, '')
    return found


class Ordinary(ast.NodeTransformer):
    """Remove the compact plumbing; what remains must be the frozen statements."""
    def _statements(self, nodes):
        out, nodes = [], list(nodes)
        while nodes:
            node = nodes.pop(0)
            if isinstance(node, ast.If) and ast.unparse(node.test) in ORDINARY:
                nodes[:0] = getattr(node, ORDINARY[ast.unparse(node.test)])
                continue
            if isinstance(node, ast.ImportFrom) and node.module in PLUMBING_MODULES:
                continue
            text = ast.unparse(node)
            if text in ("compact = sys.modules.get('partition_routing_patch')",
                        'support, other = (as_native(support), as_native(other))',
                        '_funding_transfer = for_workflow(workflow)'):
                continue
            for owner, value, target, original in (
                    ('constraint_owner', 'owned_constraint(', 'constraint', None),
                    ('header_owner', 'support_header(support)', 'record', 'support.record()')):
                if text.startswith(owner+' = '+value):
                    following = ast.unparse(nodes.pop(0))
                    if following != '%s = %s.value' % (target, owner):
                        raise AssertionError('owner/value pair differs: '+following)
                    expression = original or ast.unparse(node.value.args[0])
                    node = ast.parse('%s = %s' % (target, expression)).body[0]
            out.append(self.visit(node))
        return out

    def generic_visit(self, node):
        # One pass: statement lists through _statements, everything else visited once.
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                if value and all(isinstance(n, ast.stmt) for n in value):
                    setattr(node, field, self._statements(value))
                else:
                    setattr(node, field, [self.visit(n) if isinstance(n, ast.AST) else n for n in value])
            elif isinstance(value, ast.AST):
                setattr(node, field, self.visit(value))
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        name = ast.unparse(node.func)
        if name in ('_compact_wall', '_compact_interface'):
            node.func = ast.parse('D.enclose_component_'+name.split('_')[-1]).body[0].value
        if name == '_retain_support':
            return node.args[0]
        node.keywords = [k for k in node.keywords if k.arg != '_runtime_funding_transfer']
        return node

    def visit_Subscript(self, node):
        self.generic_visit(node)
        if ast.unparse(node) == 'support_rows._handles[support.support_id]':
            return ast.Name('support', ast.Load())
        return node


def ordinary(node):
    return ast.dump(Ordinary().visit(node))


class LineAnchors(unittest.TestCase):
    def test_once_counts_only_whole_lines_that_start_a_line(self):
        text = 'a\n        x = 1\n            x = 1\n'
        self.assertEqual(RT._once(text, '        x = 1\n', '        y = 2\n'), 'a\n        y = 2\n            x = 1\n')
        self.assertEqual(RT._once(text, '            x = 1\n', '            z = 3\n'), 'a\n        x = 1\n            z = 3\n')
        for source, old in (('x\nx\n', 'x\n'), ('    x\n    x\n', '    x\n'), ('ab\nab\n', 'ab\n'),
                            ('a\n', 'b\n'), ('a\nb\n', 'a'), ('a\nb\n', '\nb\n')):
            with self.subTest(source=source, old=old), self.assertRaises(RT.CompactRoutingRefused):
                RT._once(source, old, 'c\n')
        # Overlapping occurrences: a line that repeats inside its own successor.
        with self.assertRaises(RT.CompactRoutingRefused):
            RT._once('x\nx\nx\n', 'x\nx\n', 'y\n')

    def test_counted_calls_and_strict_definitions(self):
        self.assertEqual(RT._calls('f(D.g(1), D.g(2))', 'D.g(', 'h(', 2), 'f(h(1), h(2))')
        for source in ('D.g(1)', 'AD.g(1) D.g(2)', 'x.D.g(1) D.g(2)'):
            with self.subTest(source=source), self.assertRaises(RT.CompactRoutingRefused):
                RT._calls(source, 'D.g(', 'h(', 2)
        text = 'class A:\n    def f(self):\n        return 1\n\n    def g(self):\n        return 2\n'
        body = '    def f(self):\n        return 1\n'
        self.assertEqual(RT._function(text, 'f', body, '    def f(self):\n        return 3\n', cls='A'),
                         text.replace('return 1', 'return 3'))
        refused = (('class A:\n    @x\n    def f(self):\n        return 1\n', 'f', 'A'),
                   (text+'\nclass A:\n    pass\n', 'f', 'A'), (text, 'missing', 'A'),
                   ('class A:\n    def f(self):\n        return 1\n    def f(self):\n        return 1\n', 'f', 'A'))
        for source, name, cls in refused:
            with self.subTest(source=source), self.assertRaises(RT.CompactRoutingRefused):
                RT._function(source, name, body, body, cls=cls)
        with self.assertRaises(RT.CompactRoutingRefused):
            RT._function(text, 'f', body.replace('1', '4'), body, cls='A')
        # A confined edit sees only its own definition.
        two = 'def a():\n    r = 1\n\n\ndef b():\n    r = 1\n'
        self.assertEqual(RT._within(two, 'b', '    r = 1\n', '    r = 2\n'), two[:-2]+'2\n')

    def test_frozen_seams_are_ambiguous_as_substrings_but_unique_as_lines(self):
        ale, dispatch = frozen('integration_differential_ale'), frozen('integration_parallel_dispatch')
        for source, old in ((ale, "        constraint = row['constraints'][name]\n"),
                            (dispatch, '    raw = support._json\n')):
            self.assertEqual(source.count(old), 2)
            self.assertEqual(sum(1 for i, line in enumerate(source.split('\n')) if line+'\n' == old), 1)
        self.assertEqual(ale.count('D.enclose_component_wall('), 2)
        self.assertEqual(ale.count('D.enclose_component_interface('), 1)


class NativeTransforms(unittest.TestCase):
    def test_six_transforms_apply_once_to_authenticated_frozen_inputs(self):
        self.assertEqual(set(RT.BASES), set(OUTPUTS))
        for name, expected in OUTPUTS.items():
            with self.subTest(name=name):
                raw = (NATIVE/(name+'.py')).read_bytes()
                self.assertNotIn(b'\r', raw)
                self.assertEqual(sha256(raw).hexdigest(), RT.BASES[name])
                source = raw.decode('utf8')
                result = RT.transform(name+'.py', source)
                self.assertEqual(result, RT.transform(name, source))
                compile(result, name, 'exec')
                self.assertEqual(sha256(result.encode()).hexdigest(), expected)
                for bad in (source+'\n', source.replace('\n', '\r\n'), result, source.encode()):
                    with self.assertRaises(RT.CompactRoutingRefused):
                        RT.transform(name, bad)
        with self.assertRaises(RT.CompactRoutingRefused):
            RT.transform('integration_parallel_rolling', frozen('integration_parallel_rolling'))

    def test_only_the_intended_definitions_change_and_module_order_is_kept(self):
        for name, changed in CHANGED.items():
            with self.subTest(name=name):
                source = frozen(name)
                result = RT.transform(name, source)
                old, new = functions(source), functions(result)
                self.assertEqual(set(old), set(new))
                self.assertEqual({k for k in old if ast.dump(old[k]) != ast.dump(new[k])}, changed)
                before, after = ast.parse(source).body, ast.parse(result).body
                self.assertEqual([type(n).__name__+getattr(n, 'name', '') for n in before],
                                 [type(n).__name__+getattr(n, 'name', '') for n in after[:len(before)]])
                for a, b in zip(before, after[:len(before)], strict=True):
                    if not isinstance(a, (ast.FunctionDef, ast.ClassDef)):
                        self.assertEqual(ast.dump(a), ast.dump(b))
                tail = after[len(before):]
                self.assertTrue(all(isinstance(n, ast.ImportFrom) for n in tail))
                self.assertTrue({n.module for n in tail} <= {'partition_routing_patch', 'integration_routing_views'})
                # New module names never shadow an existing global.
                defined = {getattr(n, 'name', None) for n in before} | {
                    (a.asname or a.name) for n in before if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names} | {
                    t.id for n in before if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
                added = {(a.asname or a.name) for n in tail for a in n.names}
                self.assertFalse(added & defined)
        self.assertIn('import sys\n', frozen('integration_routing_views'))

    def test_without_compact_plumbing_the_ordinary_statements_are_frozen(self):
        for name, changed in CHANGED.items():
            old, new = functions(frozen(name)), functions(RT.transform(name, frozen(name)))
            for qualified in sorted(changed-REWRITTEN):
                with self.subTest(name=name, function=qualified):
                    self.assertEqual(ordinary(new[qualified]), ast.dump(old[qualified]))

    def test_partition_field_selections_cover_every_read(self):
        def reads(node, variable):
            found = set()
            for n in ast.walk(node):
                if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == variable
                        and isinstance(n.slice, ast.Constant)):
                    found.add(n.slice.value)
                if (isinstance(n, ast.Call) and ast.unparse(n.func) == variable+'.get' and n.args
                        and isinstance(n.args[0], ast.Constant)):
                    found.add(n.args[0].value)
            return found
        ale = functions(frozen('integration_differential_ale'))['_enclose']
        comprehension = next(n for n in ast.walk(ale) if isinstance(n, ast.DictComp) and ast.unparse(n.value) == 'p[k]')
        keys = set(ast.literal_eval(comprehension.generators[0].iter))
        self.assertEqual(reads(ale, 'p') | keys, set(RT.ALE_FIELDS))
        trace = frozen('integration_differential_trace')
        construct, endpoint = functions(trace)['PreparedDifferentialTrace._construct'], functions(trace)['_partition_endpoint']
        self.assertEqual(reads(construct, 'partition') | reads(endpoint, 'partition'), set(RT.TRACE_FIELDS))


class Composition(unittest.TestCase):
    def setUp(self):
        SHORT.mkdir(parents=True, exist_ok=True)
        self.staging = tempfile.TemporaryDirectory(prefix='st-', dir=SHORT)

    def tearDown(self):
        self.staging.cleanup()

    def staged(self, text):
        (Path(self.staging.name)/'integration_differential_ale.py').write_text(text, encoding='utf8', newline='\n')
        return AC.candidate_source(self.staging.name)

    def test_routing_precedes_checkpoint_and_scheduler_transforms(self):
        ale, auto, rolling = (frozen(n) for n in ('integration_differential_ale', 'integration_component_volume_auto',
                                                  'integration_parallel_rolling'))
        routed_ale = RT.transform('integration_differential_ale', ale)
        routed_auto = RT.transform('integration_component_volume_auto', auto)
        composed = {'ale': self.staged(routed_ale), 'auto': SC.transform_auto(routed_auto),
                    'rolling': SC.transform_rolling(rolling)}
        for label, text in composed.items():
            with self.subTest(label=label):
                compile(text, label, 'exec')
        self.assertIn('_endpoint_checkpoints=None', composed['ale'])
        self.assertIn('_compact_wall(', composed['ale'])
        self.assertIn('def checkpoint_consumed(', composed['auto'])
        self.assertIn('retain_support(support)', composed['auto'])
        # The reverse order is refused by the routing pin, not silently merged.
        with self.assertRaises(RT.CompactRoutingRefused):
            RT.transform('integration_differential_ale', self.staged(ale))
        with self.assertRaises(RT.CompactRoutingRefused):
            RT.transform('integration_component_volume_auto', SC.transform_auto(auto))
        # The edits are disjoint: with the pin re-pointed only here, the
        # reverse order would give the same bytes.
        for name, first, second in (
                ('integration_differential_ale', self.staged(ale), composed['ale']),
                ('integration_component_volume_auto', SC.transform_auto(auto), composed['auto'])):
            with mock.patch.dict(RT.BASES, {name: sha256(first.encode()).hexdigest()}):
                self.assertEqual(RT.transform(name, first), second)
        self.assertEqual({k: sha256(v.encode()).hexdigest() for k, v in composed.items()}, COMPOSED)


class ContinuationHelper(unittest.TestCase):
    def test_helper_transform_is_pinned_and_changes_three_lines_only(self):
        source = helper_text()
        self.assertEqual(sha256(source.encode()).hexdigest(), RT.HELPER_SHA256)
        result = RT.original_continuation_source(source)
        self.assertEqual(sha256(result.encode()).hexdigest(), HELPER_OUTPUT)
        compile(result, 'helper', 'exec')
        changed = [(tag, i1, i2) for tag, i1, i2, _, _ in difflib.SequenceMatcher(
            None, source.split('\n'), result.split('\n'), autojunk=False).get_opcodes() if tag != 'equal']
        self.assertEqual([(i1+1, i2) for _, i1, i2 in changed], [(88, 88), (91, 91), (96, 96)])
        self.assertIn("\n_SOURCE = _HERE/'source'/'tectonics'/'tests'/'i04_differential_continuation_control.py'\n", result)
        self.assertIn('\nfrom partition_routing_transform import continuation_control_source as _compact_continuation\n'
            'from funding_transfer import continuation_control_source_after_limits as _funding_continuation\n'
            '_DERIVED_TEXT = _funding_continuation(_compact_continuation(_replace_exact(_ORIGINAL_TEXT, _EDITS)))\n', result)
        derivation = functions(result)['derivation']
        keyword = next(k for n in ast.walk(derivation) if isinstance(n, ast.Call) for k in n.keywords if k.arg == 'changes')
        self.assertEqual(ast.literal_eval(keyword.value.right), list(RT.COMPACT_CHANGES))
        for bad in (source+'\n', result, source.replace('\n', '\r\n')):
            with self.assertRaises(RT.CompactRoutingRefused):
                RT.original_continuation_source(bad)

    def test_derived_text_compiles_and_strips_to_the_original_limit_edits(self):
        import funding_transfer as X
        edits, replace_exact = helper_edits(RT.original_continuation_source(helper_text()))
        self.assertEqual(edits, helper_edits(helper_text())[0])
        control = control_text()
        expected = replace_exact(control, edits)
        self.assertEqual(sha256(expected.encode()).hexdigest(), RT.DERIVED_CONTROL_SHA256)
        derived = X.continuation_control_source_after_limits(RT.continuation_control_source(expected))
        compile(derived, 'derived', 'exec')
        self.assertEqual(sha256(derived.encode()).hexdigest(), DERIVED_OUTPUT)
        self.assertEqual(ast.dump(Ordinary().visit(ast.parse(derived))), ast.dump(ast.parse(expected)))
        tree = functions(derived)
        calls = sorted(ast.unparse(n.func) for n in ast.walk(tree['continuation_pressure_force'])
                       if isinstance(n, ast.Call) and any(k.arg == '_runtime_funding_transfer' for k in n.keywords))
        self.assertEqual(calls, ['P.differential_pressure_forcing', 'P.prescribe_reservoir_pressure'])
        # The early compact return precedes the size sum outside the diagnostic try.
        body = [ast.unparse(n) for n in tree['_retain_trace_inputs'].body]
        early = next(i for i, text in enumerate(body) if text.startswith("if getattr(partition, '_compact', None) is not None"))
        size = next(i for i, text in enumerate(body) if text.startswith('size = len(partition._json)'))
        self.assertLess(early, size)
        for bad in (derived, control, expected+'\n', X.continuation_control_source_after_limits(expected)):
            with self.assertRaises(RT.CompactRoutingRefused):
                RT.continuation_control_source(bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
