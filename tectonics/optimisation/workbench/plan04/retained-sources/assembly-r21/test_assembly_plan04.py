"""Source-independent construction fixtures: never import or run Atlas science."""
from contextlib import redirect_stdout
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('assembly_plan04', HERE / 'assemble_r3_plan04.py')
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def digest(raw):
    return sha256(raw).hexdigest()


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='_fixture-', dir=HERE)
        self.home = Path(self.tmp.name)
        self.root = self.home / 'stage' / 'fidelity' / 'continuation' / 'optimisation' / 'R'
        self.root.mkdir(parents=True)
        A.T = self.home / 'stage'
        A.R = self.root
        A.C = self.root / 'compact-geometry-r1'
        A.G = self.root / 'geometry-growth-r1'
        A.RC1 = self.root / 'composed-r1'
        A.I_RUNTIME = self.root.parent / 'runtime-integration-r1' / 'runtime-src'
        A.LIVE_R = self.home / 'protected-live-R'
        A.PLAN06_D5 = None
        A.PLAN06_D5_ASSETS = {}
        A.PLAN04_SELECTION = None
        A.PLAN04_ASSETS = {}
        self.raw = {
            'launch_fresh_interval.py': b'# synthetic selected launcher\r\n',
            'n9-tools-r21/compare.py': b'# synthetic comparison tool\n',
            'n9-tools-r21/data/schema.json': b'{"fixture":true}\n',
        }
        for name, raw in self.raw.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.doc = {
            'schema': A.PLAN04_SCHEMA,
            'selection': 'Synthetic tool-only inclusion; no science or composition selection.',
            'assets': {name: digest(raw) for name, raw in self.raw.items()},
        }
        A.SELECTED = {A.norm(self.root / name): digest(raw) for name, raw in self.raw.items()}
        self.contract = self.home / 'payload.json'
        self.save_contract()
        self.target = self.home / 'composed-r21'
        self.reviewed = self.home / 'reviewed.json'
        self.dry = self.home / 'dry.json'
        self.sources = {'atlas_tectonics/fixture.py': '# source construction fixture\n'}
        A.PLAN06_D5_BASE_SOURCES = dict(self.sources)
        self.dry.write_text(json.dumps({'src_files': {
            key: A.text_sha(value) for key, value in self.sources.items()
        }}), encoding='utf8')
        for name in ('integration_mimetic_heat.py', 'integration_private_heat_cold.py'):
            path = A.I_RUNTIME / A.PKG / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# synthetic inherited input\n')
        endpoint = self.root / 'endpoint-checkpoints' / 'integration_endpoint_checkpoints.py'
        endpoint.parent.mkdir()
        endpoint.write_bytes(b'# synthetic endpoint\n')
        self.staged = {'root': str(self.root)}

    def tearDown(self):
        self.tmp.cleanup()

    def save_contract(self):
        self.contract.write_text(json.dumps(self.doc), encoding='utf8')
        self.contract_sha = A.file_sha(self.contract)

    def select(self):
        result = A.plan04_select(self.contract, self.contract_sha)
        self.staged['plan04_tools'] = result
        return result

    def compose_fixture(self, pins=None):
        return dict(self.sources), [], {}, {}

    def pin(self):
        with patch.object(A, 'compose', self.compose_fixture), patch.object(
                A, 'helper_sources', return_value={
                    A.PLAN04_LAUNCHER: self.root / A.PLAN04_LAUNCHER
                }), redirect_stdout(io.StringIO()):
            A.pin(self.reviewed, self.dry, A.file_sha(self.dry), self.target, self.staged)
        return json.loads(self.reviewed.read_bytes())

    def compose(self):
        with patch.object(A, 'compose', self.compose_fixture), redirect_stdout(io.StringIO()):
            A.compose_target(self.reviewed, A.file_sha(self.reviewed), self.target, self.staged)

    def test_explicit_contract_and_assembler_identity(self):
        result = self.select()
        self.assertEqual(result['sha256'], self.contract_sha)
        self.assertEqual(result['assembler_sha256'], A.file_sha(HERE / 'assemble_r3_plan04.py'))
        self.assertEqual(result['selection'], self.doc)

    def test_missing_flag_pair(self):
        for args in ((self.contract, None), (None, self.contract_sha)):
            with self.subTest(args=args), self.assertRaisesRegex(A.Refused, 'both'):
                A.plan04_select(*args)

    def test_no_option_retains_base_and_resets_previous_choice(self):
        self.select()
        self.assertIsNone(A.plan04_select(None, None))
        self.assertEqual(A.PLAN04_ASSETS, {})
        self.staged = {'root': str(self.root)}
        pins = self.pin()
        self.assertEqual(set(pins['helpers']), {A.PLAN04_LAUNCHER})
        self.assertNotIn('plan04_tools', pins['staged'])
        self.compose()
        self.assertFalse((self.target / 'helpers' / A.PLAN04_FOLDER).exists())

    def test_omitted_asset_from_contract(self):
        del self.doc['assets']['n9-tools-r21/compare.py']
        self.save_contract()
        with self.assertRaisesRegex(A.Refused, 'inventory'):
            self.select()

    def test_omitted_asset_from_disk(self):
        (self.root / 'n9-tools-r21/compare.py').unlink()
        with self.assertRaisesRegex(A.Refused, 'inventory'):
            self.select()

    def test_extra_asset_on_disk(self):
        (self.root / 'n9-tools-r21/extra.py').write_bytes(b'# unexpected\n')
        with self.assertRaisesRegex(A.Refused, 'inventory'):
            self.select()

    def test_extra_asset_in_contract(self):
        self.doc['assets']['n9-tools-r21/extra.py'] = '0' * 64
        self.save_contract()
        with self.assertRaisesRegex(A.Refused, 'inventory'):
            self.select()

    def test_changed_tool_bytes(self):
        (self.root / 'n9-tools-r21/compare.py').write_bytes(b'# changed\n')
        with self.assertRaisesRegex(A.Refused, 'bytes differ'):
            self.select()

    def test_changed_launcher_bytes(self):
        (self.root / A.PLAN04_LAUNCHER).write_bytes(b'# changed launcher\n')
        with self.assertRaisesRegex(A.Refused, 'bytes differ'):
            self.select()

    def test_contract_hash_mismatch(self):
        with self.assertRaisesRegex(A.Refused, 'contract differs'):
            A.plan04_select(self.contract, '0' * 64)

    def test_self_asserted_contract_without_selected_asset(self):
        del A.SELECTED[A.norm(self.root / 'n9-tools-r21/compare.py')]
        with self.assertRaisesRegex(A.Refused, 'not selected'):
            self.select()

    def test_empty_selection(self):
        self.doc['selection'] = ' '
        self.save_contract()
        with self.assertRaisesRegex(A.Refused, 'selection absent'):
            self.select()

    def test_closed_contract_and_duplicate_keys(self):
        self.doc['scientific_ready'] = True
        self.save_contract()
        with self.assertRaisesRegex(A.Refused, 'fields differ'):
            self.select()
        self.contract.write_bytes(b'{"schema":1,"schema":2}')
        with self.assertRaisesRegex(A.Refused, 'duplicate key'):
            A.plan04_select(self.contract, A.file_sha(self.contract))

    def test_path_escape_and_case_collision(self):
        for name in ('../x.py', 'n9-tools-r21/../x.py', 'n9-tools-r21\\x.py',
                     '/x.py', 'n9-tools-r21/x.py:stream', 'n9-tools-r21//x.py',
                     'n9-tools-r21/x.', 'other/x.py'):
            with self.subTest(name=name), self.assertRaises(A.Refused):
                A.plan04_validate_name(name)
        self.doc['assets']['n9-tools-r21/COMPARE.py'] = '0' * 64
        self.save_contract()
        with self.assertRaisesRegex(A.Refused, 'collide'):
            self.select()

    def test_all_inputs_outputs_and_contract_recorded_exactly(self):
        self.select()
        pins = self.pin()
        for name, raw in self.raw.items():
            self.assertEqual(pins['files'][A.rel(self.root / name)], digest(raw))
            self.assertEqual(pins['helpers'][name]['sha256'], digest(raw))
        self.assertEqual(pins['staged']['plan04_tools']['selection'], self.doc)
        self.compose()
        record = json.loads((self.target / 'composition.json').read_bytes())
        self.assertEqual(record['staged'], self.staged)
        for name, raw in self.raw.items():
            self.assertEqual((self.target / 'helpers' / name).read_bytes(), raw)
            self.assertEqual(record['helpers'][name], digest(raw))
        self.assertEqual((self.target / 'src/atlas_tectonics/fixture.py').read_text(),
                         self.sources['atlas_tectonics/fixture.py'])

    def test_omitted_reviewed_asset_refuses_before_target_write(self):
        self.select()
        pins = self.pin()
        del pins['helpers']['n9-tools-r21/compare.py']
        self.reviewed.write_text(json.dumps(pins), encoding='utf8')
        with self.assertRaisesRegex(A.Refused, 'reviewed helper inventory'):
            self.compose()
        self.assertFalse(self.target.exists())

    def test_extra_reviewed_asset_refuses_before_target_write(self):
        self.select()
        pins = self.pin()
        pins['helpers']['n9-tools-r21/extra.py'] = {'path': None, 'sha256': '0' * 64}
        self.reviewed.write_text(json.dumps(pins), encoding='utf8')
        with self.assertRaisesRegex(A.Refused, 'reviewed helper inventory'):
            self.compose()
        self.assertFalse(self.target.exists())

    def test_changed_reviewed_asset_refuses_before_target_write(self):
        self.select()
        pins = self.pin()
        pins['helpers']['n9-tools-r21/compare.py']['sha256'] = '0' * 64
        self.reviewed.write_text(json.dumps(pins), encoding='utf8')
        with self.assertRaisesRegex(A.Refused, 'reviewed helper differs'):
            self.compose()
        self.assertFalse(self.target.exists())

    def test_changed_contract_after_pin_refuses_before_target_write(self):
        self.select()
        self.pin()
        self.doc['selection'] = 'Different explicit selection'
        self.save_contract()
        with self.assertRaisesRegex(A.Refused, 'contract differs'):
            self.compose()
        self.assertFalse(self.target.exists())

    def test_different_valid_contract_vs_reviewed_record(self):
        self.select()
        self.pin()
        self.doc['selection'] = 'Different explicit selection'
        self.save_contract()
        self.select()
        with self.assertRaisesRegex(A.Refused, 'staged root'):
            self.compose()
        self.assertFalse(self.target.exists())

    def test_asset_changes_during_composition_refuse_before_target_write(self):
        self.select()
        self.pin()
        def mutate(pins=None):
            (self.root / 'n9-tools-r21/compare.py').write_bytes(b'changed during compose')
            return self.compose_fixture(pins)
        with patch.object(A, 'compose', mutate), self.assertRaisesRegex(A.Refused, 'bytes differ'):
            A.compose_target(self.reviewed, A.file_sha(self.reviewed), self.target, self.staged)
        self.assertFalse(self.target.exists())

    def test_inherited_target_guard_and_write_once(self):
        self.assertEqual(A.check_target(self.target, self.target.name), self.target)
        for bad in (self.root / 'composed-r22', A.LIVE_R / 'composed-r22',
                    self.home / 'not-composed'):
            with self.subTest(path=bad), self.assertRaises(A.Refused):
                A.check_target(bad, bad.name)
        self.select()
        self.pin()
        self.compose()
        with self.assertRaisesRegex(A.Refused, 'target exists'):
            self.compose()
        with self.assertRaisesRegex(A.Refused, 'reviewed inputs already exist'):
            self.pin()

    def test_launcher_must_be_inherited_exact_helper_not_emitted_override(self):
        self.select()
        with self.assertRaisesRegex(A.Refused, 'launcher replaced'):
            A.plan04_add_helpers({}, {A.PLAN04_LAUNCHER: {'path': None, 'sha256': '0' * 64}})

    def test_main_check_wires_plan04_and_d5_without_composing(self):
        args = ['--check', '--root', str(self.root), '--generation', 'g',
                '--generation-sha256', 'gsha', '--input-binding', 'b',
                '--input-binding-sha256', 'bsha', '--target', str(self.target),
                '--d5-contract', 'd5', '--d5-contract-sha256', 'd5sha',
                '--plan04-contract', str(self.contract),
                '--plan04-contract-sha256', self.contract_sha]
        output = io.StringIO()
        with patch.object(A, 'preflight', return_value=(self.staged, self.target)) as preflight, \
                patch.object(A, 'plan06_select_d5', return_value={'fixture': 'd5'}) as d5, \
                patch.object(A, 'compose') as compose, redirect_stdout(output):
            A.main(args)
        self.assertFalse(preflight.call_args.kwargs['selected'])
        d5.assert_called_once_with('d5', 'd5sha')
        compose.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result['plan06_d5'], {'fixture': 'd5'})
        self.assertEqual(result['plan04_tools']['sha256'], self.contract_sha)


if __name__ == '__main__':
    unittest.main(verbosity=2)
