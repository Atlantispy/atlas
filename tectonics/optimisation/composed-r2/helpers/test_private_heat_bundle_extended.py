"""Successor heat-bundle composition controls; source level plus fresh children.

Everything is composed in memory from authenticated predecessor bytes. Two
fresh children import the composed helpers under a composed-only layout (a
temporary native root, helpers, ram and the historical tests directory; no
historical helper root and no C/R/I directories). Nothing is solved, no store
or database is opened, and nothing here is owner or scientific acceptance.
"""
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
R = HERE.parent
T = HERE.parents[4]
OPT = HERE.parents[1]
BASE = OPT/'runtime-integration-r1'
FILTERED = OPT/'filtered-exact-r1'
H = HERE.parents[3]/'heat-repair-20261007'
for _extra in (R, R/'endpoint-checkpoints'):
    if str(_extra) not in sys.path:
        sys.path.append(str(_extra))

import private_heat_bundle as B
import heat_payload_indexed_patch as PAYLOAD
import partition_routing_transform as ROUTING
import ram_context_indexed_patch as RAM_CONTEXT
import partition_workflow_transform as PWT
import continuation_transfer as CT
import funding_transfer as FT
import workflow_transfer as W
import run_prepared_restart as RUN


I_MANIFEST_SHA256 = '597c00328bb8aede225a8a936dcea2edab42d3c894eb87caeb974fdfd576979d'
CLOSURE = frozenset(['probe_heat_original_connected_r9.py']+['private_heat_'+n+'.py' for n in (
    'certification_kernel_r1 certification_kernel_r3 certification_resources_r1 checkpoint_consumer_r9 '
    'closed_owned_r4 continuation_guard_r3 continuation_support_r3 correction_owned_r1 counted_blocks_r2 '
    'decimal_inventory_r1 decimal_sparse_core_r1 decimal_sparse_core_r2 endpoint_inventory_r3 '
    'exact_face_kernel_r1 exact_functional_kernel_r2 exact_growth_r1 finish_arithmetic_r1 '
    'finish_codec_inventory_r1 finish_entry_owned_r1 finish_entry_owned_r2 finish_inventory_r1 '
    'finish_inventory_r2 finish_issue_owned_r4 finish_kernel_r1 finish_kernel_r10 finish_kernel_r2 '
    'finish_kernel_r3 forward_kernel_r13 functional_bounds_kernel_r2 functionals_kernel_r1 '
    'functionals_kernel_r5 functionals_parallel_r1 geometry_inventory_r1 geometry_inventory_r3 '
    'gmp_resources_r1 grouped_account_r1 interval_assembly_kernel_r1 interval_assembly_kernel_r2 '
    'interval_assembly_kernel_r5 interval_inventory_r1 interval_inventory_r4 issuer_resources_r1 '
    'issuer_resources_r3 issuer_resources_r4 joined_consumer_r6 loaded_identity_r1 low_geometry_kernel_r1 '
    'low_ledger_inventory_r1 low_solver_kernel_r2 low_solver_kernel_r5 mpfr_lu_r1 mpfr_lu_resources_r1 '
    'native_failure_capture_r1 native_failure_capture_r6 native_issuer_r12 native_projection_r4 '
    'native_successor_r6 original_continuation_r1 original_coverage_r1 original_coverage_r2 '
    'original_coverage_r3 original_joined_r5 original_joined_r6 original_spatial_r1 owned_value_r1 '
    'owned_value_r4 polygon_moment_inventory_r1 polygon_moment_inventory_r4 process_meter_r1 '
    'public_float_r1 rank_resources_r1 rational_decimal_kernel_r1 rational_decimal_r1 refinement_kernel_r1 '
    'restored_binding_r9 restored_binding_ram_context_r1 restored_binding_ram_recovery_r1 '
    'rounding_inventory_r1 snapshot_store_r3 sparse_resources_r1 stage_lifetime_r3 '
    'support_basis_resources_r1 support_basis_resources_r2').split()])
CHANGED = frozenset('private_heat_'+n+'.py' for n in (
    'certification_resources_r1 checkpoint_consumer_r9 correction_owned_r1 decimal_inventory_r1 '
    'decimal_sparse_core_r2 finish_inventory_r1 finish_inventory_r2 finish_issue_owned_r4 '
    'functionals_parallel_r1 geometry_inventory_r1 geometry_inventory_r3 gmp_resources_r1 '
    'grouped_account_r1 interval_assembly_kernel_r5 interval_inventory_r4 issuer_resources_r3 '
    'issuer_resources_r4 joined_consumer_r6 low_ledger_inventory_r1 low_solver_kernel_r2 '
    'low_solver_kernel_r5 mpfr_lu_resources_r1 native_issuer_r12 native_projection_r4 '
    'original_continuation_r1 original_coverage_r3 original_joined_r5 original_joined_r6 '
    'original_spatial_r1 restored_binding_r9 restored_binding_ram_context_r1 '
    'restored_binding_ram_recovery_r1').split())
STAGES = {
    'private_heat_original_joined_r6.py@joined_successor_source':
        'c7239e2d1982082eeda02de67da036c776194a41560486ec89152242b5dd7498',
    'private_heat_original_continuation_r1.py@original_continuation_source':
        '3d859c53c9b731fccbba09609b9c86c3104f445cc9c5f46367f63ef6ebc144df',
    'private_heat_restored_binding_ram_context_r1.py@ram_context_indexed_patch':
        '85c9ed5fa7cc0f3b32101b99edf16f4e949d4b2e38e7becdd3e03fbc4fa196b7',
}
# Reported to the composer: the reconciled RAM helpers and the cold _BINDING_SHA.
RAM_CONTEXT_SHA256 = '3ba60e2866a9f8fbb18473db6b85eb38529ae4f7a1d2a14185a0ccdf04a71f2f'
RAM_RECOVERY_SHA256 = '71f821917cc4c5e68642133f1648b5379aa7b355f0b48958b899c7d3df8fd110'
# Wave-1 derived continuation text funding(compact(_EDITS(control))).
CONTINUATION_DERIVED_SHA256 = 'f97394f6d1025ca39cfd59137328f33d58fc79b2f8d7f0ee0b6139396b8654bd'
REVIEWED_ROUTING = 'private_heat_continuation_support_r3.py private_heat_functionals_parallel_r1.py'


def digest(raw):
    return sha256(raw if type(raw) is bytes else raw.encode()).hexdigest()


def _helper_source(name):
    for directory in (HERE, R, BASE/'helpers'):
        if (directory/name).is_file():
            return (directory/name).read_bytes()
    raise FileNotFoundError(name)


def authenticated_inputs():
    """I-pinned historical inputs; external, RAM and helper bytes as supplied."""
    raw = (BASE/'manifest.json').read_bytes()
    if digest(raw) != I_MANIFEST_SHA256:
        raise ValueError('fixture predecessor manifest changed')
    manifest = json.loads(raw)
    inputs, ram = {}, {}
    for name, pin in manifest['files'].items():
        path = T/name
        if ((path.parent == H and path.suffix == '.py' and
                (path.name.startswith('private_heat_') or path.name in B.VERBATIM_ROOTS)) or
                path.parent == BASE/'ram' and path.name in B.RAM_PINS or path.parent == BASE/'helpers'):
            content = path.read_bytes()
            if digest(content) != pin:
                raise ValueError('fixture dependency changed: '+name)
            (ram if path.parent == BASE/'ram' else inputs if path.parent == H else {})[path.name] = content
    external = {name: (H/name).read_bytes() for name in B.EXTERNAL_PINS}
    helpers = {name: _helper_source(name) for name in B.HELPER_COPIES+B.COMPANION_HELPERS}
    return manifest, inputs, external, ram, helpers


def successor():
    _, inputs, external, ram, helpers = authenticated_inputs()
    return B.construct_successor(inputs, reference_root=H, reference_pins=B.REFERENCE_PINS,
                                 external=external, ram=ram, helpers=helpers)


def write_layout(directory, helper_out, ram_out):
    """Composed-only layout: native root (I plus the exterior/mimetic seams), helpers, ram."""
    import exterior_mesh_patch as E_PATCH
    import mimetic_patch as M_PATCH
    directory = Path(directory)
    manifest = json.loads((BASE/'manifest.json').read_bytes())
    root = directory/'runtime-src'
    for name, pin in manifest['source_hashes'].items():
        raw = (BASE/'runtime-src'/name).read_bytes()
        if digest(raw) != pin:
            raise ValueError('native fixture source changed')
        if name.endswith('/integration_exterior_mesh.py'):
            raw = E_PATCH.transform(raw.decode()).encode()
        elif name.endswith('/integration_mimetic_heat.py'):
            raw = M_PATCH.mimetic_source(raw.decode()).encode()
        (root/name).parent.mkdir(parents=True, exist_ok=True)
        (root/name).write_bytes(raw)
    for folder, files in (('helpers', helper_out), ('ram', ram_out)):
        (directory/folder).mkdir()
        for name, raw in files.items():
            (directory/folder/name).write_bytes(raw)
    return root, directory/'helpers', directory/'ram'


def _spatial_workflow_transform():
    """AST-extracted require/transform; the module itself imports atlas_tectonics."""
    path = HERE/'spatial_workflow_patch.py'
    tree = ast.parse(path.read_bytes().decode('utf8'))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('require', 'transform')]
    namespace = {'X': SimpleNamespace(IndexedSpatialRefused=ValueError)}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['transform']


def composed_native_sources(test):
    """Every plan section-2 native chain on frozen I bytes, stage digests asserted."""
    import native_transfer as N
    import spatial_transfer as S
    import spatial_indexed_patch as X
    import partition_native_patch as PN
    import geometry_transfer as G
    import patch_endpoint_seam as SEAM
    import patch_endpoint_scheduler as SC
    import patch_ale_checkpoints as ALE
    import exterior_mesh_patch as EMP
    import mimetic_patch as MP
    import pressure_indexed_patch as PRESS
    manifest = json.loads((BASE/'manifest.json').read_bytes())
    frozen = {}
    for name, pin in manifest['source_hashes'].items():
        raw = (BASE/'runtime-src'/name).read_bytes()
        test.assertEqual(digest(raw), pin)
        frozen[name.removeprefix('atlas_tectonics/')] = raw.decode('utf8')
    out = dict(frozen)
    out['regional_execution.py'] = N.retained_snapshot_source(frozen['regional_execution.py'])
    owner = S.spatial_owner_source(frozen['integration_spatial_owner.py'])
    test.assertEqual(digest(owner), X.TRANSFER_SOURCE_SHA256)
    out['integration_spatial_owner.py'] = X.transform(owner)
    with tempfile.TemporaryDirectory(prefix='hbn-', dir=T) as stage:
        stage = Path(stage)
        for name, text in (('integration_differential_geometry.py', PN.transform(frozen['integration_differential_geometry.py'])),
                           ('integration_component_volume_batch.py', frozen['integration_component_volume_batch.py']),
                           ('integration_differential_ale.py',
                            ROUTING.transform('integration_differential_ale', frozen['integration_differential_ale.py']))):
            (stage/name).write_text(text, encoding='utf8', newline='\n')
        seam = SEAM.candidate_sources(stage)
        out['integration_differential_ale.py'] = ALE.candidate_source(stage)
    test.assertEqual(digest(seam['integration_differential_geometry.py']),
                     '213d1ebb5ef4d072f65ae3c08b99a4537f61985e46fe802e54c58a1b6ac471fd')
    out['integration_differential_geometry.py'] = G.transform(seam['integration_differential_geometry.py'], compact=True)
    out['integration_component_volume_batch.py'] = seam['integration_component_volume_batch.py']
    out['integration_endpoint_checkpoints.py'] = seam['integration_endpoint_checkpoints.py']
    out['integration_differential_coupling.py'] = CT.coupling_source(
        PN.transform_coupling(frozen['integration_differential_coupling.py']))
    for name in ('integration_routing_views', 'integration_parallel_selection', 'integration_differential_trace',
                 'integration_parallel_dispatch'):
        out[name+'.py'] = ROUTING.transform(name, frozen[name+'.py'])
    out['integration_component_volume_auto.py'] = SC.transform_auto(
        ROUTING.transform('integration_component_volume_auto', frozen['integration_component_volume_auto.py']))
    out['integration_parallel_rolling.py'] = SC.transform_rolling(frozen['integration_parallel_rolling.py'])
    out['integration_regional_workflow.py'] = PWT.transform(_spatial_workflow_transform()(
        W.nonzero_cursor_source(frozen['integration_regional_workflow.py'])))
    out['integration_private_heat_cold.py'] = PWT.cold_source(W.private_heat_cold_source(frozen['integration_private_heat_cold.py']))
    out['integration_exterior_mesh.py'] = EMP.transform(frozen['integration_exterior_mesh.py'])
    out['integration_mimetic_heat.py'] = MP.mimetic_source(frozen['integration_mimetic_heat.py'])
    out['integration_extremum_heat.py'] = MP.extremum_source(frozen['integration_extremum_heat.py'])
    out['integration_differential_pressure.py'] = FT.pressure_source(PRESS.transform(frozen['integration_differential_pressure.py']))
    for name in ('integration_exact_gmp.py', 'integration_filtered_predicates.py', 'integration_volume_bounds.py'):
        out[name] = (FILTERED/'native-src'/'atlas_tectonics'/name).read_bytes().decode('utf8')
    for name, expected in (
            ('integration_differential_geometry.py', 'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253'),
            ('integration_differential_coupling.py', '05f2414de10b89217f362da70966718f69a3a1aeb1e3c3a8a3895ce85d389779'),
            ('integration_differential_ale.py', '9d20f9f2217e23839270cca1ca3daf9530dc9a9da68f701cb185b085d41ed644'),
            ('integration_component_volume_auto.py', '72cb051ecc3a3be369891add19922e3c62f57f0367995c8dffedd2770e12c3b9'),
            ('integration_parallel_rolling.py', '6daa2d3a84a224fe9e4724cd0212d0195c474a044440a5f6df36c9cd37c7981a'),
            ('integration_regional_workflow.py', PWT.WORKFLOW_OUTPUT_SHA256),
            ('integration_private_heat_cold.py', PWT.COLD_OUTPUT_SHA256),
            ('integration_differential_pressure.py', '8d3d8f3dd11d632ce6a75380a17fdcd19b281fafa03b68401a2726d228c02a33')):
        test.assertEqual(digest(out[name]), expected, name)
    return out


def imports(text):
    names = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.split('.')[0])
    return names


def literal_edits(text, names):
    """Call-free module constants and _replace_exact of a derivative helper; the module is not run."""
    namespace, body, defined = {}, [], set()
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == '_replace_exact':
            body.append(node)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and not any(isinstance(n, ast.Call) for n in ast.walk(node.value))
                and {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)} <= defined):
            body.append(node)
            defined.add(node.targets[0].id)
    if not set(names) <= defined:
        raise AssertionError('derivative edit constants missing: '+repr(set(names)-defined))
    exec(compile(ast.Module(body=body, type_ignores=[]), '<derivative-edits>', 'exec'), namespace)
    return namespace


def derived_texts(helpers):
    """The runtime derivations in their reviewed order: transfer/compact/funding wrap the edited ORIGINAL."""
    joined = literal_edits(helpers['private_heat_original_joined_r6.py'].decode(),
                           {'_EDITS', '_PARTITION_EDITS', '_RESTART_EDITS'})
    control = (H/'source/tectonics/tests/i04_differential_joined_control.py').read_text(encoding='utf8')
    continuation = literal_edits(helpers[B.CONTINUATION].decode(), {'_EDITS'})
    text = (H/'source/tectonics/tests/i04_differential_continuation_control.py').read_text(encoding='utf8')
    edited = continuation['_replace_exact'](text, continuation['_EDITS'])
    return dict(joined=joined, joined_control=control, continuation=continuation, continuation_control=text,
                continuation_edited=edited,
                private_heat_original_joined_r6=joined['_replace_exact'](CT.joined_control_source(control), joined['_EDITS']),
                private_heat_original_continuation_r1=FT.continuation_control_source_after_limits(
                    ROUTING.continuation_control_source(edited)))


_CHILD = r'''
import importlib, json, sys
from pathlib import Path
root, helpers, ram, tests, control = sys.argv[1:6]
sys.path[:0] = [root, helpers, ram, tests]
before = list(sys.path)
names = sorted(p.stem for folder in (helpers, ram) for p in Path(folder).glob('*.py'))
for name in names:
    importlib.import_module(name)
from atlas_tectonics.reuse import ExecutionContext
with ExecutionContext('scipy'):
    pass
derived = {name: importlib.import_module(name).derivation()['derived_text_sha256']
           for name in ('private_heat_original_joined_r6', 'private_heat_original_continuation_r1')}
joined = importlib.import_module('private_heat_original_joined_r6')
derived['joined_contract'] = ['_ALE_COMPUTE_CONTEXT' in vars(joined),
                              'endpoint_checkpoints' in joined._advance_current_interval.__kwdefaults__]
if control:
    import importlib.util
    spec = importlib.util.spec_from_file_location('historical_gmp_resources_control', control)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
files = {name: getattr(module, '__file__', None) for name, module in tuple(sys.modules.items())}
print(json.dumps(dict(before=before, after=list(sys.path), derived=derived, prefix=sys.prefix,
                      names=names, files={k: v for k, v in files.items() if v})))
'''


class SuccessorComposition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers, cls.ram, cls.report = successor()

    def test_closure_changed_set_stage_digests_and_report(self):
        report, helpers, ram = self.report, self.helpers, self.ram
        self.assertEqual(set(report['original']), CLOSURE)
        self.assertEqual(set(report['changed']), CHANGED)
        self.assertEqual(report['stage_digests'], STAGES)
        self.assertEqual(report['roots'], list(B.ROOTS))
        self.assertTrue(set(B.ROOTS) <= CLOSURE)
        self.assertEqual(report['ram_helpers'], {'private_heat_restored_binding_ram_context_r1.py': RAM_CONTEXT_SHA256,
                                                 'private_heat_restored_binding_ram_recovery_r1.py': RAM_RECOVERY_SHA256})
        self.assertEqual((report['ram_recovery_sha256'], report['cold_binding_sha256']),
                         (RAM_RECOVERY_SHA256, dict(predecessor=B.RAM_PINS[B.RAM_RECOVERY], successor=RAM_RECOVERY_SHA256)))
        # Layout: RAM helpers only in ram/, no duplicate basenames, guard left to the composer.
        self.assertEqual(set(ram), set(B.RAM_PINS))
        self.assertFalse(set(ram) & set(helpers))
        self.assertEqual(set(helpers), (CLOSURE-set(B.RAM_PINS)-{B.GUARD}) | set(B.HELPER_COPIES+B.COMPANION_HELPERS))
        self.assertEqual(report['composer_supplied'], {B.GUARD: B.SUCCESSOR_GUARD_SHA})
        self.assertEqual(report['successor'], {name: digest(raw) for name, raw in {**helpers, **ram}.items()
                                               if name in CLOSURE})
        for name in B.HELPER_COPIES+B.COMPANION_HELPERS:
            self.assertEqual(helpers[name], _helper_source(name), name)
        self.assertEqual(digest(helpers[B.OBSERVER]), B.OBSERVER_SHA)
        # Probe r9 is a verbatim root; private_heat_mesh_patch's issuer_source is never applied.
        self.assertEqual(helpers['probe_heat_original_connected_r9.py'], (H/'probe_heat_original_connected_r9.py').read_bytes())
        self.assertNotIn('prepare_indexed_mesh_inputs', helpers['private_heat_native_issuer_r12.py'].decode())
        self.assertEqual(report['external_imports'], {
            'composer_supplied': ['private_heat_continuation_guard_r3', 'workflow_transfer'],
            'historical_tests': sorted(B.EXTERNAL_IMPORTS['historical_tests']),
            'off_route': sorted(B.EXTERNAL_IMPORTS['off_route']),
            'runtime': sorted(B.EXTERNAL_IMPORTS['runtime'])})
        self.assertEqual({(r['module'], r['scope']) for r in report['reviewed_path_mutations']}, set(B.REVIEWED_PATH_MUTATIONS))
        self.assertEqual(report['worker_runtime_helpers'], list(PAYLOAD.WORKER_RUNTIME_HELPERS))
        self.assertFalse(report['checkpoint_admission'] or report['numerical_algorithm_changed'])
        self.assertEqual(json.loads(json.dumps(report)), report)
        # Deterministic: a second composition gives identical bytes.
        again = successor()
        self.assertEqual((again[0], again[1]), (helpers, ram))

    def test_refusals_leave_no_partial_composition(self):
        _, inputs, external, ram, helpers = authenticated_inputs()
        def compose(**changes):
            arguments = dict(inputs=inputs, external=external, ram=ram, helpers=helpers)
            arguments.update(changes)
            return B.construct_successor(arguments.pop('inputs'), reference_root=H,
                                         reference_pins=B.REFERENCE_PINS, **arguments)
        name = 'private_heat_original_coverage_r1.py'
        ram_name = 'private_heat_restored_binding_ram_context_r1.py'
        for changes in (dict(external=dict(external, **{name: external[name]+b'\n'})),
                        dict(external={k: v for k, v in external.items() if k != name}),
                        dict(ram=dict(ram, **{ram_name: ram[ram_name]+b'\n'})),
                        dict(helpers={k: v for k, v in helpers.items() if k != 'continuation_transfer.py'}),
                        dict(helpers=dict(helpers, **{'workflow_transfer.py': b''})),
                        dict(helpers=dict(helpers, **{B.OBSERVER: helpers[B.OBSERVER]+b'\n'})),
                        dict(helpers=dict(helpers, **{'heat_payload_indexed_patch.py': b'# other\n'})),
                        dict(helpers=dict(helpers, **{'partition_routing_transform.py': b'# other\n'})),
                        dict(inputs=dict(inputs, **{name: external[name]})),
                        dict(inputs={k: v for k, v in inputs.items() if k != 'probe_heat_original_connected_r9.py'}),
                        dict(inputs=dict(inputs, **{B.CONTINUATION: inputs[B.CONTINUATION]+b'\n'}))):
            with self.assertRaises(ValueError):
                compose(**changes)
        with self.assertRaises(ValueError):
            B.construct_successor(inputs, reference_root=H, reference_pins=dict(B.REFERENCE_PINS, extra='0'*64),
                                  external=external, ram=ram, helpers=helpers)
        with self.assertRaises(ValueError):
            B.cold_binding_source(PWT.COLD_OUTPUT_SHA256, dict(cold_binding_sha256=dict(predecessor='0'*64,
                                                                                      successor='1'*64)))

    def test_no_residual_relative_sources_and_relocated_references(self):
        everything = {**self.helpers, **self.ram}
        for name, raw in everything.items():
            text = raw.decode()
            self.assertNotIn("_HERE/'source'", text, name)
            self.assertNotIn("_HERE / 'source'", text, name)
        # The only HERE-relative source tree left names <helpers>/source, never H.
        residual = {name for name, raw in everything.items() if b"HERE/'source'" in raw}
        self.assertEqual(residual, {'private_heat_native_successor_r6.py'})
        successor_r6 = everything['private_heat_native_successor_r6.py'].decode()
        self.assertEqual(successor_r6.count("HERE/'source'"), 1)
        # Its reviewed sys.path inserts name these two HERE-relative trees only.
        for line in ("CLONE = HERE/'native-composed-r7'/'tectonics'/'src'\n",
                     "TESTS = HERE/'source'/'tectonics'/'tests'\n", "HERE = Path(__file__).resolve().parent\n"):
            self.assertEqual(successor_r6.count('\n'+line), 1, line)
        continuation = self.helpers[B.CONTINUATION].decode()
        control = H/'source/tectonics/tests/i04_differential_continuation_control.py'
        self.assertEqual(continuation.count('_SOURCE = _Path('+repr(str(control))+')'), 1)
        self.assertEqual(self.report['preserved_accounting_references'],
                         {str(H/name): pin for name, pin in B.REFERENCE_PINS.items()})
        for path, pin in self.report['preserved_accounting_references'].items():
            self.assertEqual(digest(Path(path).read_bytes()), pin)
        # The historical package insert is removed once, before relocation: no H
        # path of any kind and no import-path mutation remain in that helper.
        gmp = self.helpers[B.GMP_RESOURCES].decode()
        self.assertEqual((gmp.count(B.GMP_NEUTRAL), gmp.count('sys.path')), (1, 0))
        self.assertNotIn(str(H), gmp)
        original = (H/B.GMP_RESOURCES).read_bytes()
        self.assertEqual(B.path_mutations(B.GMP_RESOURCES, original),
                         [('<module>', "sys.path.insert(0, str(HERE / 'source' / 'tectonics' / 'src'))")])
        self.assertEqual(B.path_mutations(B.GMP_RESOURCES, self.helpers[B.GMP_RESOURCES]), [])
        with self.assertRaises(ValueError):
            B._reference_paths({B.GMP_RESOURCES: self.helpers[B.GMP_RESOURCES]}, reference_root=H,
                               reference_pins=B.REFERENCE_PINS)
        with self.assertRaises(ValueError):
            B._reference_paths({}, reference_root=Path('relative'), reference_pins=B.REFERENCE_PINS)

    def test_import_path_mutation_scan_is_alias_aware_and_strict(self):
        cases = {
            'import sys as _s\n_s.path.insert(0, "x")\n': [('<module>', "_s.path.insert(0, 'x')")],
            'from sys import path as p\ndef f():\n    p.append("x")\n': [('f', "p.append('x')")],
            'import sys\nsys.path[:0] = ["x"]\n': [('<module>', "sys.path[:0] = ['x']")],
            'import sys\nsys.path = []\n': [('<module>', 'sys.path = []')],
            'import site\nsite.addsitedir("x")\n': [('<module>', "site.addsitedir('x')")],
            'import sys\nclass A:\n    def m(self):\n        sys.meta_path.insert(0, self)\n':
                [('A.m', 'sys.meta_path.insert(0, self)')],
            'import sys\nx = sys.path.index("x") + len(sys.path)\nif "x" in sys.path:\n    pass\n': [],
        }
        for source, expected in cases.items():
            self.assertEqual(B.path_mutations('fixture.py', source.encode()), expected, source)
        self.assertEqual(B._reviewed_path_mutations({}), [])
        with self.assertRaises(ValueError):
            B._reviewed_path_mutations({'fixture.py': b'import sys\ndef f():\n    sys.path.insert(0, "x")\n'})
        reviewed = 'private_heat_functionals_parallel_r1.py'
        with self.assertRaises(ValueError):
            B._reviewed_path_mutations({reviewed: self.helpers[reviewed]+b'\nimport sys\nsys.path.append("x")\n'})

    def test_ram_context_pins_and_cold_binding(self):
        helpers, ram = self.helpers, self.ram
        context = ram['private_heat_restored_binding_ram_context_r1.py'].decode()
        tree = ast.parse(context)
        pins = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], 'id', None) == '_PINS')
        self.assertEqual(pins, {name: digest(helpers[name]) for name in pins})
        changed = {name for name, pin in pins.items() if pin != self.report['original'][name]}
        self.assertEqual(changed, {'private_heat_checkpoint_consumer_r9.py', 'private_heat_native_issuer_r12.py',
            'private_heat_issuer_resources_r4.py', 'private_heat_grouped_account_r1.py',
            'private_heat_joined_consumer_r6.py'})
        recovery = ram[B.RAM_RECOVERY].decode()
        self.assertEqual(recovery.count("_BINDING_SHA = '"+RAM_CONTEXT_SHA256+"'\n"), 1)
        self.assertEqual(digest(ram['private_heat_restored_binding_ram_context_r1.py']), RAM_CONTEXT_SHA256)
        # Composed ram_context is the indexed transform with only its pins reconciled.
        transformed = RAM_CONTEXT.transform((BASE/'ram'/RAM_CONTEXT.NAME).read_text(encoding='utf8'))
        for edit in self.report['dependency_pin_changes']:
            if edit['consumer'] == RAM_CONTEXT.NAME:
                transformed = transformed.replace(edit['predecessor'], edit['successor'])
        self.assertEqual(transformed, context)
        # The composer's cold reader rewrite, exact once on the reviewed cold output.
        frozen = (BASE/'runtime-src/atlas_tectonics/integration_private_heat_cold.py').read_text(encoding='utf8')
        cold = PWT.cold_source(W.private_heat_cold_source(frozen))
        bound = B.cold_binding_source(cold, self.report)
        self.assertEqual(bound.count("_BINDING_SHA = '"+RAM_RECOVERY_SHA256+"'\n"), 1)
        self.assertNotIn(B.RAM_PINS[B.RAM_RECOVERY], bound)
        self.assertEqual(bound.replace(RAM_RECOVERY_SHA256, B.RAM_PINS[B.RAM_RECOVERY]), cold)
        with self.assertRaises(ValueError):
            B.cold_binding_source(bound, self.report)

    def test_coverage_same_directory_placement(self):
        helpers = self.helpers
        names = ('private_heat_original_coverage_r1.py', 'private_heat_original_coverage_r2.py',
                 'private_heat_original_coverage_r3.py', 'private_heat_issuer_resources_r1.py',
                 'private_heat_issuer_resources_r3.py', 'probe_heat_original_connected_r9.py')
        self.assertTrue(set(names) <= set(helpers))
        self.assertFalse(set(names) & set(self.ram))
        self.assertEqual(digest(helpers['private_heat_original_coverage_r1.py']),
                         B.EXTERNAL_PINS['private_heat_original_coverage_r1.py'])
        r3 = helpers['private_heat_original_coverage_r3.py'].decode()
        self.assertEqual(r3.count("_REPAIR_SOURCE_SHA = '"+digest(helpers['private_heat_original_coverage_r2.py'])+"'"), 1)
        self.assertEqual(r3.count("_REPAIR_FACADE_SHA = '"+digest(helpers['private_heat_issuer_resources_r3.py'])+"'"), 1)
        self.assertNotEqual(digest(helpers['private_heat_issuer_resources_r3.py']),
                            '90dbe4c6f86abab15cafa72ad852ba2e8cf156cca188d20c4e85fb40e00529d5')
        r2 = helpers['private_heat_original_coverage_r2.py'].decode()
        for name in ('private_heat_original_coverage_r1.py', 'private_heat_issuer_resources_r1.py'):
            self.assertIn("'"+digest(helpers[name])+"'", r2)

    def test_joined_and_continuation_text_chain_orders(self):
        helpers = self.helpers
        joined = helpers['private_heat_original_joined_r6.py'].decode()
        self.assertEqual((joined.count(B.JOINED_TRANSFER), joined.count('\n'+B.JOINED_DERIVED)), (1, 0))
        original = (H/'private_heat_original_joined_r6.py').read_text(encoding='utf8')
        with self.assertRaises(ValueError):
            B.joined_successor_source(B.joined_successor_source(original))
        chain = derived_texts(helpers)
        edits, control = chain['joined'], chain['joined_control']
        self.assertIn('_runtime_transfer=parent_geometry_transfer(workflow, parent)',
                      chain['private_heat_original_joined_r6'])
        self.assertEqual(len(edits['_EDITS']), 16)
        # Reverse order: the transfer after the helper edits is refused by its exact base pin.
        with self.assertRaises(CT.ContinuationTransferRefused):
            CT.joined_control_source(edits['_replace_exact'](control, edits['_EDITS']))
        continuation = helpers[B.CONTINUATION].decode()
        historical = (H/B.CONTINUATION).read_text(encoding='utf8')
        self.assertEqual(digest(ROUTING.original_continuation_source(historical)), B.CONTINUATION_SHA)
        relocated = {B.CONTINUATION: historical.encode()}
        B._reference_paths(relocated, reference_root=H, reference_pins=B.REFERENCE_PINS)
        # Bundle order: after relocation, after composition or twice is refused.
        for wrong in (relocated[B.CONTINUATION].decode(), continuation,
                      ROUTING.original_continuation_source(historical)):
            with self.assertRaises(ROUTING.CompactRoutingRefused):
                ROUTING.original_continuation_source(wrong)
        self.assertEqual(digest(chain['private_heat_original_continuation_r1']), CONTINUATION_DERIVED_SHA256)
        text, edited = chain['continuation_control'], chain['continuation_edited']
        for wrong in (lambda: ROUTING.continuation_control_source(text),
                      lambda: ROUTING.continuation_control_source(FT.continuation_control_source_after_limits(edited))):
            with self.assertRaises(ValueError):
                wrong()

    def test_worker_runtime_helpers_cover_composed_native_import_graph(self):
        natives = composed_native_sources(self)
        composed = {Path(name).stem: raw.decode() for name, raw in {**self.helpers, **self.ram}.items()}
        universe = dict(composed)
        for directory in (R, HERE, R/'endpoint-checkpoints', BASE/'helpers'):
            for path in directory.glob('*.py'):
                if not path.stem.startswith('test_'):
                    universe.setdefault(path.stem, path.read_text(encoding='utf8'))
        pending, seen = set().union(*map(imports, natives.values())), set()
        while pending:
            name = pending.pop()
            if name in universe and name not in seen:
                seen.add(name)
                pending |= imports(universe[name])-seen
        required = {name for name in seen if not name.startswith(('private_heat_', 'probe_heat_'))}
        direct = {name for name in set().union(*map(imports, natives.values())) if name in universe
                  and not name.startswith('private_heat_')}
        self.assertTrue({'spatial_workflow_patch', 'partition_workflow_patch', 'partition_routing_patch',
                         'pressure_indexed_patch', 'funding_transfer', 'continuation_transfer'} <= direct)
        self.assertEqual(required-set(PAYLOAD.WORKER_RUNTIME_HELPERS), set())
        self.assertEqual(len(set(PAYLOAD.WORKER_RUNTIME_HELPERS)), len(PAYLOAD.WORKER_RUNTIME_HELPERS))
        tree = ast.parse(self.helpers['private_heat_functionals_parallel_r1.py'])
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], 'id', None) == '_INDEXED_RUNTIME_HELPERS')
        self.assertEqual(ast.literal_eval(node.value.args[0]), PAYLOAD.WORKER_RUNTIME_HELPERS)

    def test_import_path_neutrality_fresh_process(self):
        chain = derived_texts(self.helpers)
        expected = {name: digest(chain[name]) for name in ('private_heat_original_joined_r6',
                                                            'private_heat_original_continuation_r1')}
        # The driver's joined contract: ALE compute context and the query-store keyword.
        expected['joined_contract'] = [True, True]
        with tempfile.TemporaryDirectory(prefix='hb-', dir=T) as directory:
            root, helpers, ram = write_layout(directory, self.helpers, self.ram)
            tests = H/'source/tectonics/tests'
            results = []
            for control in ('', str(H/B.GMP_RESOURCES)):
                done = subprocess.run([sys.executable, '-B', '-I', '-c', _CHILD, str(root), str(helpers),
                                       str(ram), str(tests), control], capture_output=True, text=True,
                                      cwd=directory, timeout=600)
                self.assertEqual(done.returncode, 0, done.stderr[-4000:])
                results.append(json.loads(done.stdout.strip().splitlines()[-1]))
            clean, polluted = results
            self.assertEqual(clean['names'], sorted(Path(n).stem for n in {**self.helpers, **self.ram}))
            self.assertEqual(clean['after'], clean['before'])
            self.assertEqual([p for p in clean['after'] if RUN.historical_import_path(T, p)], [])
            layout = [Path(p).resolve() for p in (root, helpers, ram, tests)]
            environment = Path(clean['prefix']).resolve()
            for name, file in clean['files'].items():
                path = Path(file).resolve()
                if name == 'atlas_tectonics' or name.startswith('atlas_tectonics.'):
                    self.assertTrue(path.is_relative_to(Path(root).resolve()), name)
                elif path.is_relative_to(T.resolve()) and not path.is_relative_to(environment):
                    self.assertTrue(any(path.is_relative_to(p) for p in layout), name)
            for name in clean['names']:
                self.assertIn(Path(clean['files'][name]).resolve().parent, (Path(helpers).resolve(), Path(ram).resolve()))
            # The imported helpers derived exactly the reviewed-order texts.
            self.assertEqual(clean['derived'], expected)
            # Control: the historical helper's own bytes do insert the old package
            # root, which the runner's predicate recognises. The composed copy does not.
            added = [p for p in polluted['after'] if p not in polluted['before']]
            self.assertEqual(added, [str(H/'source'/'tectonics'/'src')])
            self.assertTrue(RUN.historical_import_path(T, added[0]))
            self.assertTrue(Path(polluted['files']['atlas_tectonics']).resolve().is_relative_to(Path(root).resolve()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
