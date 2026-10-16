"""Source-only composer controls (schema v2): no store, solver, checkpoint or launch.

construct() is checked against the reviewed-inputs record: chain order and
stage digests (delivered package digests included), the F delta applied last
and untouched, the heat/guard/cold bindings, the WORKER_RUNTIME_HELPERS cover,
reverse chain orders and wrong input digests refused, two dry constructions
identical, exclusive writes only to scratch targets, and the successor guard
importing its companions from its own directory in fresh processes.
"""
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import assemble_resumable as A

SCRATCH = A.WORKSPACE/'_t'/'w3'
GEOMETRY = 'atlas_tectonics/integration_differential_geometry.py'
ROUTED = ('integration_routing_views', 'integration_parallel_selection', 'integration_differential_trace',
          'integration_parallel_dispatch')
EXPECTED_CHAINS = {
    GEOMETRY: ['input', 'partition_native_patch.transform', 'patch_endpoint_seam.candidate_sources',
               'geometry_transfer.transform(compact=True)'],
    'atlas_tectonics/integration_component_volume_batch.py': ['input', 'patch_endpoint_seam.candidate_sources'],
    'atlas_tectonics/integration_endpoint_checkpoints.py': ['patch_endpoint_seam.companion'],
    'atlas_tectonics/integration_differential_coupling.py': ['input', 'partition_native_patch.transform_coupling',
                                                             'continuation_transfer.coupling_source'],
    'atlas_tectonics/integration_differential_ale.py': ['input', 'partition_routing_transform.transform',
                                                        'patch_ale_checkpoints.candidate_source'],
    'atlas_tectonics/integration_component_volume_auto.py': ['input', 'partition_routing_transform.transform',
                                                             'patch_endpoint_scheduler.transform_auto'],
    'atlas_tectonics/integration_parallel_rolling.py': ['input', 'patch_endpoint_scheduler.transform_rolling'],
    'atlas_tectonics/integration_differential_pressure.py': ['input', 'pressure_indexed_patch.transform',
                                                             'funding_transfer.pressure_source'],
    'atlas_tectonics/integration_regional_workflow.py': ['input', 'workflow_transfer.nonzero_cursor_source',
                                                         'spatial_workflow_patch.transform',
                                                         'partition_workflow_transform.transform'],
    'atlas_tectonics/integration_private_heat_cold.py': ['input', 'workflow_transfer.private_heat_cold_source',
                                                         'partition_workflow_transform.cold_source',
                                                         'private_heat_bundle.cold_binding_source'],
    'atlas_tectonics/regional_execution.py': ['input', 'native_transfer.retained_snapshot_source'],
    'atlas_tectonics/integration_spatial_owner.py': ['input', 'spatial_transfer.spatial_owner_source',
                                                     'spatial_indexed_patch.transform'],
    'atlas_tectonics/integration_exterior_mesh.py': ['input', 'exterior_mesh_patch.transform'],
    'atlas_tectonics/integration_mimetic_heat.py': ['input', 'mimetic_patch.mimetic_source'],
    'atlas_tectonics/integration_extremum_heat.py': ['input', 'mimetic_patch.extremum_source'],
    **{'atlas_tectonics/'+name+'.py': ['input', 'partition_routing_transform.transform'] for name in ROUTED},
    **{name: ['filtered_exact_delta'] for name in A.FILTER_DELTA},
    'helpers/private_heat_original_joined_r6.py': ['private_heat_bundle.joined_successor_source'],
    'helpers/private_heat_original_continuation_r1.py': ['partition_routing_transform.original_continuation_source'],
    'ram/private_heat_restored_binding_ram_context_r1.py': ['ram_context_indexed_patch.transform', 'output'],
    'ram/private_heat_restored_binding_ram_recovery_r1.py': ['output'],
    'helpers/private_heat_continuation_guard_r3.py': ['input', 'resource_guard_patch.transform'],
    'runtime.py': ['input', 'workspace-depth-and-import-roots'],
    'composition': ['outputs'],
}


def digest(raw):
    return sha256(raw if type(raw) is bytes else raw.encode('utf8')).hexdigest()


def frozen_text(name):
    prior = json.loads((A.BASE/'manifest.json').read_bytes())
    return A.read(A.BASE/'runtime-src'/name, prior['source_hashes'][name]).decode('utf8')


def authenticated_blobs(document):
    return {name: A.read(A.HERE/name, pin) for name, pin in document['files'].items()}


class Composer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document, cls.sha = A.reviewed_document()
        cls.composition = A.construct(cls.document)

    def test_chain_order_and_stage_digests(self):
        c, document = self.composition, self.document
        self.assertEqual({path: [label for label, _ in chain] for path, chain in c.chains.items()}, EXPECTED_CHAINS)
        self.assertEqual(c.stage_digests, document['stage_digests'])
        self.assertTrue(set(A.PACKAGE_DIGESTS.items()) <= set(c.stage_digests.items()))
        prior = json.loads((A.BASE/'manifest.json').read_bytes())
        for path, chain in c.chains.items():
            if path.startswith('atlas_tectonics/'):
                self.assertEqual(chain[-1][1], digest(c.native[path]), path)
                if chain[0][0] == 'input':
                    self.assertEqual(chain[0][1], prior['source_hashes'][path], path)
        changed = {n for n in c.native if prior['source_hashes'].get(n) != digest(c.native[n])}
        self.assertEqual(changed, {p for p in c.chains if p.startswith('atlas_tectonics/')})
        # The F delta is applied last and nothing else touched its three files.
        for name in A.FILTER_DELTA:
            self.assertEqual(c.native[name], (A.FILTERED/'native-src'/name).read_bytes())
            self.assertEqual(c.chains[name], [['filtered_exact_delta', digest(c.native[name])]])
        self.assertEqual(len(c.native), len(prior['source_hashes'])+2)
        outputs = {'runtime-src/'+n: digest(r) for n, r in c.native.items()}
        outputs.update({'helpers/'+n: digest(r) for n, r in c.helpers.items()})
        outputs.update({'ram/'+n: digest(r) for n, r in c.ram.items()})
        outputs['runtime.py'] = digest(c.runtime_py)
        self.assertEqual(c.stage_digests['composition@outputs'], sha256(A.canonical(outputs)).hexdigest())
        for raw in (*c.native.values(), *c.helpers.values(), *c.ram.values(), c.runtime_py):
            compile(raw, '<composed>', 'exec', dont_inherit=True)

    def test_heat_guard_cold_and_reference_bindings(self):
        c = self.composition
        guard = digest(c.helpers['private_heat_continuation_guard_r3.py'])
        admission = c.helpers['historical_admission.py'].decode('utf8')
        patch = (A.HERE/'resource_guard_patch.py').read_text(encoding='utf8')
        self.assertEqual({guard, c.guard_sha256, A.literal(admission, 'GUARD_PIN'), A.literal(patch, 'SUCCESSOR_PIN')},
                         {'9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772'})
        self.assertEqual(digest(c.helpers['windows_workload_job.py']), A.literal(admission, 'JOB_PIN'))
        self.assertEqual(digest(c.helpers['private_heat_resource_diagnostics_r1.py']),
                         A.literal(admission, 'DIAGNOSTICS_PIN'))
        recovery = c.ram['private_heat_restored_binding_ram_recovery_r1.py']
        context = c.ram['private_heat_restored_binding_ram_context_r1.py']
        self.assertEqual(digest(recovery), '71f821917cc4c5e68642133f1648b5379aa7b355f0b48958b899c7d3df8fd110')
        cold = c.native['atlas_tectonics/integration_private_heat_cold.py'].decode('utf8')
        self.assertEqual(cold.count("_BINDING_SHA = '"+digest(recovery)+"'\n"), 1)
        self.assertNotIn('84a7a048e73073f6cb41f5b5d50b5dcb0aacb9c5403dda99b8c5aa3b1ef7f592', cold)
        self.assertEqual(A.literal(recovery.decode('utf8'), '_BINDING_SHA'), digest(context))
        pins = A.literal(context.decode('utf8'), '_PINS')
        self.assertEqual(pins, {name: digest(c.helpers[name]) for name in pins})
        # The private_heat_mesh_patch issuer transform is never applied; it is a copy only.
        self.assertNotIn('prepare_indexed_mesh_inputs', c.helpers['private_heat_native_issuer_r12.py'].decode('utf8'))
        self.assertEqual(c.helpers['private_heat_mesh_patch.py'],
                         (A.HERE/'compact-geometry-r1'/'private_heat_mesh_patch.py').read_bytes())
        # M13: validators executed from H, never shipped; no helper shadows a historical test.
        self.assertFalse(set(A.HISTORICAL_VALIDATORS) & (set(c.helpers) | set(c.ram)))
        self.assertFalse((set(c.helpers) | set(c.ram)) & {p.name for p in A.HISTORICAL_TESTS.glob('*.py')})
        # All 8 preserved references bound: imported ones importable, the rest data-only.
        refs = {A.workspace_relative(Path(p)): pin
                for p, pin in c.heat_report['preserved_accounting_references'].items()}
        self.assertEqual(len(refs), 8)
        for name, pin in refs.items():
            self.assertEqual((c.historical_tests if name in A.IMPORTED_REFERENCES else c.data_only)[name], pin)
        self.assertFalse(set(c.historical_tests) & set(c.data_only))
        # Every REQUIRED_MODULE resolves to one shipped runtime file.
        names = set(c.helpers) | set(c.ram) | {Path(n).name for n in c.historical_tests}
        for name in c.required_modules:
            self.assertIn(name+'.py', names)
        self.assertEqual(len(c.required_modules), 41)

    def test_worker_runtime_helpers_cover_composed_native_import_graph(self):
        c = self.composition
        universe = {Path(n).stem: raw for n, raw in {**c.helpers, **c.ram}.items()}
        direct = {m.split('.')[0] for raw in c.native.values() for m, level in A.python_imports(raw) if not level}
        pending, seen = set(direct), set()
        while pending:
            name = pending.pop()
            if name in universe and name not in seen:
                seen.add(name)
                pending |= {m.split('.')[0] for m, level in A.python_imports(universe[name]) if not level}-seen
        required = {n for n in seen if not n.startswith(('private_heat_', 'probe_heat_'))}
        tuple_ = A.literal(c.helpers['heat_payload_indexed_patch.py'].decode('utf8'), 'WORKER_RUNTIME_HELPERS')
        self.assertTrue({'spatial_workflow_patch', 'partition_workflow_patch', 'partition_routing_patch',
                         'pressure_indexed_patch', 'funding_transfer', 'continuation_transfer'} <= direct)
        self.assertEqual(required-set(tuple_), set())

    def test_reverse_chain_orders_and_wrong_input_digests_refused(self):
        c, document = self.composition, self.document
        frozen = {name: frozen_text('atlas_tectonics/'+name+'.py') for name in (
            'integration_differential_geometry', 'integration_differential_ale', 'integration_component_volume_auto',
            'integration_differential_coupling', 'integration_regional_workflow', 'integration_private_heat_cold',
            'integration_differential_pressure', 'integration_parallel_rolling', 'integration_spatial_owner',
            'integration_exterior_mesh', 'integration_mimetic_heat', 'regional_execution')}
        composed = lambda name: c.native['atlas_tectonics/'+name+'.py'].decode('utf8')
        with A.authenticated_modules(authenticated_blobs(document)) as M:
            PN, G, R, CT, W = (M.partition_native_patch, M.geometry_transfer, M.partition_routing_transform,
                               M.continuation_transfer, M.workflow_transfer)
            PWT, B, FT, SC, X = (M.partition_workflow_transform, M.private_heat_bundle, M.funding_transfer,
                                 M.patch_endpoint_scheduler, M.spatial_indexed_patch)
            with tempfile.TemporaryDirectory(prefix='w3-ale-') as stage:
                (Path(stage)/'integration_differential_ale.py').write_text(frozen['integration_differential_ale'],
                                                                          encoding='utf8', newline='\n')
                checkpointed_ale = M.patch_ale_checkpoints.candidate_source(stage)
            joined = (A.HISTORICAL/'private_heat_original_joined_r6.py').read_text(encoding='utf8')
            guard = (A.HISTORICAL/'private_heat_continuation_guard_r3.py').read_bytes()
            refusals = {
                'PN after seam and G (old order)': lambda: PN.transform(composed('integration_differential_geometry')),
                'PN twice': lambda: PN.transform(PN.transform(frozen['integration_differential_geometry'])),
                'G(compact) before PN': lambda: G.transform(frozen['integration_differential_geometry'], compact=True),
                'routing after ALE checkpoints': lambda: R.transform('integration_differential_ale', checkpointed_ale),
                'routing after scheduler auto': lambda: R.transform(
                    'integration_component_volume_auto', SC.transform_auto(frozen['integration_component_volume_auto'])),
                'routing twice': lambda: R.transform('integration_differential_ale', R.transform(
                    'integration_differential_ale', frozen['integration_differential_ale'])),
                'transform_coupling after coupling_source': lambda: PN.transform_coupling(
                    CT.coupling_source(frozen['integration_differential_coupling'])),
                'coupling_source twice': lambda: CT.coupling_source(composed('integration_differential_coupling')),
                'partition workflow before spatial workflow': lambda: PWT.transform(
                    W.nonzero_cursor_source(frozen['integration_regional_workflow'])),
                'nonzero cursor after composition': lambda: W.nonzero_cursor_source(
                    composed('integration_regional_workflow')),
                'cold_source before private_heat_cold_source': lambda: PWT.cold_source(
                    frozen['integration_private_heat_cold']),
                'cold binding twice': lambda: B.cold_binding_source(composed('integration_private_heat_cold'),
                                                                    c.heat_report),
                'pressure consumer after funding': lambda: M.pressure_indexed_patch.transform(
                    FT.pressure_source(frozen['integration_differential_pressure'])),
                'rolling twice': lambda: SC.transform_rolling(composed('integration_parallel_rolling')),
                'indexed spatial owner on frozen owner': lambda: X.transform(frozen['integration_spatial_owner']),
                'exterior twice': lambda: M.exterior_mesh_patch.transform(composed('integration_exterior_mesh')),
                'mimetic twice': lambda: M.mimetic_patch.mimetic_source(composed('integration_mimetic_heat')),
                'retained snapshot twice': lambda: M.native_transfer.retained_snapshot_source(
                    composed('regional_execution')),
                'joined successor twice': lambda: B.joined_successor_source(B.joined_successor_source(joined)),
                'guard transform twice': lambda: M.resource_guard_patch.transform(
                    M.resource_guard_patch.transform(guard)),
                'guard with a foreign job': lambda: M.resource_guard_patch.successor_files(
                    guard, guard, c.helpers['private_heat_resource_diagnostics_r1.py']),
            }
            for label, action in refusals.items():
                with self.subTest(refusal=label), self.assertRaises(ValueError):
                    action()
        # Hash-free steps: the composer asserts each input digest before the step runs.
        stages = A._Stages(document['stage_digests'])
        with self.assertRaises(A.CompositionRefused):
            stages.chain('atlas_tectonics/integration_regional_workflow.py',
                         frozen['integration_regional_workflow']+'\n', ('never-run', lambda text: text))
        for key in ('atlas_tectonics/integration_regional_workflow.py@spatial_workflow_patch.transform',
                    'atlas_tectonics/integration_differential_geometry.py@patch_endpoint_seam.candidate_sources',
                    'atlas_tectonics/integration_differential_ale.py@patch_ale_checkpoints.candidate_source',
                    'atlas_tectonics/integration_component_volume_auto.py@patch_endpoint_scheduler.transform_auto'):
            path, label = key.split('@', 1)
            with self.subTest(unguarded=key), self.assertRaises(A.CompositionRefused):
                A._Stages(None).record(path, label, '0'*64)
        # Document-level refusals: wrong input pin, stage digest, external pin, layout, set or preloaded name.
        def changed(**edits):
            result = json.loads(json.dumps(document))
            for key, value in edits.items():
                result[key] = value
            return result
        files = dict(document['files'], **{'geometry_transfer.py': '0'*64})
        stages = dict(document['stage_digests'])
        stages['helpers/private_heat_original_joined_r6.py@private_heat_bundle.joined_successor_source'] = '1'*64
        external = dict(document['external_files'])
        external[next(iter(external))] = '2'*64
        for label, candidate in (('input pin', changed(files=files)), ('stage digest', changed(stage_digests=stages)),
                                 ('external pin', changed(external_files=external)),
                                 ('layout', changed(layout=dict(document['layout'], historical_tests='x'))),
                                 ('extra file', changed(files=dict(document['files'], **{'x.py': '3'*64}))),
                                 ('target', changed(target='composed-r1/../x'))):
            with self.subTest(document=label), self.assertRaises(A.CompositionRefused):
                A.construct(candidate)
        sys.modules['geometry_transfer'] = object()
        try:
            with self.assertRaises(A.CompositionRefused):
                A.construct(document)
        finally:
            del sys.modules['geometry_transfer']

    def test_two_dry_constructs_identical_and_exclusive_scratch_writes(self):
        first, second = self.composition, A.construct(self.document)
        for field in ('native', 'helpers', 'ram', 'runtime_py', 'stage_digests', 'chains', 'heat_report',
                      'historical_tests', 'data_only', 'historical_validators', 'required_modules'):
            self.assertEqual(getattr(first, field), getattr(second, field), field)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        manifests = []
        with tempfile.TemporaryDirectory(prefix='a', dir=SCRATCH) as one, \
                tempfile.TemporaryDirectory(prefix='b', dir=SCRATCH) as two:
            for root, composition in ((one, first), (two, second)):
                (Path(root)/'s').mkdir()
                target = Path(root)/'s'/'composed-r1'
                pin = A.write_composition(composition, target, self.sha)
                self.assertEqual(digest((target/'manifest.json').read_bytes()), pin)
                with self.assertRaises(FileExistsError):
                    A.write_composition(composition, target, self.sha)
                relative = A.workspace_relative(target)+'/'
                manifest = json.loads((target/'manifest.json').read_bytes())
                manifests.append(json.loads(json.dumps(manifest).replace(relative, '<target>/')))
            for manifest in manifests:
                manifest.pop('composer_sha256')
            self.assertEqual(manifests[0], manifests[1])
        self.assertFalse((A.HERE/'composed-r2').exists())
        if (A.HERE/self.document['target']).exists():
            # The frozen successor is written exactly once: main() refuses before composing.
            with self.assertRaises(FileExistsError):
                A.main(['--reviewed-inputs-sha256', self.sha])

    def test_successor_guard_imports_companions_from_its_own_directory(self):
        c = self.composition
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='g', dir=SCRATCH) as directory, \
                tempfile.TemporaryDirectory(prefix='w3-cwd-') as cwd:
            for name in ('private_heat_continuation_guard_r3.py', 'windows_workload_job.py',
                         'private_heat_resource_diagnostics_r1.py', 'historical_admission.py'):
                (Path(directory)/name).write_bytes(c.helpers[name])
            environment = {k: v for k, v in __import__('os').environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
            guard = str(Path(directory)/'private_heat_continuation_guard_r3.py')
            # As the supervisor launches it: a script whose only workspace path is its own directory.
            done = subprocess.run([sys.executable, '-B', guard, '--help'], capture_output=True, text=True,
                                  cwd=cwd, env=environment, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            self.assertIn('--launch', done.stdout)
            child = (
                'import json, sys, types\nfrom pathlib import Path\n'
                'directory = Path(sys.argv[1]).resolve()\nsys.path.insert(0, str(directory))\n'
                'import private_heat_continuation_guard_r3 as G\nimport historical_admission as H\n'
                'files = {n: str(Path(sys.modules[n].__file__).resolve().parent == directory) for n in '
                "('private_heat_continuation_guard_r3', 'windows_workload_job', 'private_heat_resource_diagnostics_r1')}\n"
                'H._loaded_source_fence(G, H.GUARD_PIN, lambda: None)\n'
                "fake = types.ModuleType('historical_guard'); fake.__file__ = sys.argv[2]\n"
                'try:\n    H._loaded_source_fence(fake, H.GUARD_PIN, lambda: None)\n    refused = False\n'
                'except H.HistoricalAdmissionRefused:\n    refused = True\n'
                'print(json.dumps(dict(files=files, historical_refused=refused, '
                'diagnostics=G.RESOURCE_DIAGNOSTICS is sys.modules["private_heat_resource_diagnostics_r1"])))\n')
            done = subprocess.run([sys.executable, '-B', '-I', '-c', child, directory,
                                   str(A.HISTORICAL/'private_heat_continuation_guard_r3.py')],
                                  capture_output=True, text=True, cwd=cwd, env=environment, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            result = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(result, dict(files={'private_heat_continuation_guard_r3': 'True', 'windows_workload_job': 'True',
                                             'private_heat_resource_diagnostics_r1': 'True'},
                                      historical_refused=True, diagnostics=True))

    def test_runner_and_reader_pass_guard_phase_with_unwrapped_check(self):
        for name in ('run_prepared_restart.py', 'reopen_prepared_restart.py'):
            tree = ast.parse(self.composition.helpers[name])
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'materialise']
            self.assertEqual(len(calls), 1, name)
            keywords = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
            self.assertEqual((keywords['phase'], keywords['check']), ('guard.phase', 'check'), name)
            check = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                     getattr(n.targets[0], 'id', None) == 'check']
            self.assertTrue(check and all(ast.unparse(n.value) == 'lambda: guard.check(force=True)' for n in check))


if __name__ == '__main__':
    unittest.main(verbosity=2)
