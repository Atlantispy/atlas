"""Disposable contract controls -- SOURCE ONLY in the authoring handoff.

Do not treat this unexecuted file as evidence of passing tests. When separately
authorised, it imports only these stdlib candidate tools and uses synthetic
metadata in TemporaryDirectory. It never constructs Atlas, calls transforms,
imports a runtime, probes identity, opens a store or emits a real profile.
"""
from copy import deepcopy
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A = load('prepared_candidate_unit', HERE/'assemble_resumable.py')
P = load('prepared_generation_unit', HERE/'prepare_generation.py')


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def pin(value):
    return sha256(value).hexdigest()


def measured():
    stages = dict(A.PACKAGE_DIGESTS)
    stages['composition@outputs'] = '7'*64
    return dict(schema='atlas.private.prepared-stage-measurement.v1', status='MEASURED_NOT_SELECTED',
        route=A.ROUTE, assembler_sha256=pin((HERE/'assemble_resumable.py').read_bytes()),
        source_selection_sha256=A.SOURCE_SELECTION_SHA256, files=dict(A.SELECTED_INPUT_PINS),
        package_baseline_sha256=pin(A.canonical(A.PACKAGE_DIGESTS)), stage_digests=stages, package_stage_drift={})


class Contracts(unittest.TestCase):
    def test_input_omission_and_wrong_selected_pin_refuse(self):
        row = dict(schema=A.DOCUMENT_SCHEMA, predecessor_manifest_sha256=A.PREDECESSOR,
            filtered_manifest_sha256=A.FILTERED_MANIFEST, files=dict(A.SELECTED_INPUT_PINS),
            external_files=dict(A.EXTERNAL_FILES), layout=dict(A.LAYOUT), target='composed-r4',
            authority='DISPOSABLE UNIT RECORD; no real selection', accuracy='UNIT ONLY',
            source_selection_sha256=A.SOURCE_SELECTION_SHA256, stage_digests=measured()['stage_digests'],
            package_stage_changes={}, stage_measurement=dict(path='stage-measurement.json', sha256='1'*64),
            stage_selection=dict(path='stage-selection.json', sha256='2'*64))
        A._check_document(row, check_stages=True)
        for name in ('dev_stage_timing.py', 'start_gate.py', 'route2_gate.py', 'fresh_interval_driver.py',
                     'compact-geometry-r1/segment_store.py'):
            bad = deepcopy(row)
            del bad['files'][name]
            with self.subTest(omitted=name), self.assertRaisesRegex(A.CompositionRefused, 'exactly'):
                A._check_document(bad, check_stages=True)
        bad = deepcopy(row)
        bad['files']['fresh_interval_driver.py'] = '0'*64
        with self.assertRaisesRegex(A.CompositionRefused, 'explicit gen-r3/s4'):
            A._check_document(bad, check_stages=True)

    def test_endpoint_reconciled_and_other_package_pins_remain_enforced(self):
        key = 'atlas_tectonics/integration_endpoint_checkpoints.py@patch_endpoint_seam.companion'
        path, label = key.split('@', 1)
        selected = A.SELECTED_INPUT_PINS[A.ENDPOINT_COMPANION]
        A._Stages(None).record(path, label, selected)
        with self.assertRaisesRegex(A.CompositionRefused, 'selected package'):
            A._Stages(None).record(path, label, '4a835dc34f840fd12298a676ddae209966b378257e2693b04f7f681e65a7e451')
        other = 'helpers/private_heat_continuation_guard_r3.py@resource_guard_patch.transform'
        path, label = other.split('@', 1)
        A._Stages(None).record(path, label, A.PACKAGE_DIGESTS[other])
        with self.assertRaisesRegex(A.CompositionRefused, 'selected package'):
            A._Stages(None).record(path, label, '0'*64)

    def test_measurement_records_drift_but_cannot_be_built(self):
        key = next(iter(A.PACKAGE_DIGESTS))
        path, label = key.split('@', 1)
        stages = A._Stages(None, measuring=True)
        stages.record(path, label, '0'*64)
        self.assertEqual(stages.package_drift[key], dict(before=A.PACKAGE_DIGESTS[key], after='0'*64))
        with self.assertRaisesRegex(A.CompositionRefused, 'cannot be written'):
            A.build_manifest(SimpleNamespace(stages_verified=False), Path('unused'), '1'*64)
        with self.assertRaisesRegex(A.CompositionRefused, 'no unchecked construction'):
            A.construct({}, check_stages=False)

    def test_stage_measurement_binds_complete_sources_and_drift(self):
        row = measured()
        A.check_stage_measurement(row)
        for field in ('assembler_sha256', 'source_selection_sha256', 'package_baseline_sha256'):
            bad = deepcopy(row)
            bad[field] = '0'*64
            with self.subTest(field=field), self.assertRaisesRegex(A.CompositionRefused, 'different source bytes'):
                A.check_stage_measurement(bad)
        bad = deepcopy(row)
        key = next(iter(A.PACKAGE_DIGESTS))
        bad['stage_digests'][key] = '0'*64
        with self.assertRaisesRegex(A.CompositionRefused, 'drift is incomplete'):
            A.check_stage_measurement(bad)
        bad['package_stage_drift'][key] = dict(before=A.PACKAGE_DIGESTS[key], after='0'*64)
        A.check_stage_measurement(bad)

    def test_legacy_bundle_scope_checks_bytes_and_restores_after_failure(self):
        raw = b'UNIT = True\n'
        old = {'composer_supplied': ('already_shipped',), 'off_route': ('historical_cli',)}
        bundle = SimpleNamespace(EXTERNAL_IMPORTS=old)
        with patch.object(A, 'COPIED_HELPERS', {'unit.py': 'unit.py'}), \
                patch.object(A, 'SELECTED_INPUT_PINS', {'unit.py': pin(raw)}):
            with self.assertRaisesRegex(RuntimeError, 'deliberate unit failure'):
                with A._legacy_bundle_import_closure(bundle, {'unit.py': raw}):
                    self.assertEqual(bundle.EXTERNAL_IMPORTS['composer_supplied'], ('already_shipped', 'unit'))
                    self.assertEqual(bundle.EXTERNAL_IMPORTS['off_route'], old['off_route'])
                    raise RuntimeError('deliberate unit failure')
            self.assertIs(bundle.EXTERNAL_IMPORTS, old)
            with self.assertRaisesRegex(A.CompositionRefused, 'unauthenticated'):
                with A._legacy_bundle_import_closure(bundle, {'unit.py': b'changed'}):
                    self.fail('bad helper admitted')

    def test_actual_review_subject_two_distinct_participants_and_exact_native_delta(self):
        # All synthetic. No evidence files or accepted review artefact are emitted.
        manifest = dict(reviewed_inputs_sha256='1'*64, composer_sha256='2'*64, source_hashes={'unit.py': '3'*64})
        record = dict(schema='atlas.private.prepared-delta-review.v1', status='ACCEPTED_FOR_PREPARED_C2', route=A.ROUTE,
            subject=dict(source_manifest_sha256='4'*64, reviewed_inputs_sha256='1'*64,
                composer_sha256='2'*64, source_selection_sha256=A.SOURCE_SELECTION_SHA256),
            reviews=[dict(reviewer='DISPOSABLE UNIT '+str(i), role='synthetic test participant',
                scope='complete-prepared-package', disposition='ACCEPT',
                evidence=dict(path='unit/'+str(i)+'.md', sha256='5'*64)) for i in (1, 2)],
            native_reasons={'unit.py': dict(before=None, after='3'*64, reason='Synthetic added unit source')})
        self.assertEqual(len(A.validate_review_record(record, manifest, '4'*64, {})), 2)
        bad = deepcopy(record)
        bad['reviews'][1]['reviewer'] = bad['reviews'][0]['reviewer']
        with self.assertRaisesRegex(A.CompositionRefused, 'distinct'):
            A.validate_review_record(bad, manifest, '4'*64, {})
        bad = deepcopy(record)
        bad['native_reasons'] = {}
        with self.assertRaisesRegex(A.CompositionRefused, 'exact native delta'):
            A.validate_review_record(bad, manifest, '4'*64, {})
        with self.assertRaisesRegex(A.CompositionRefused, 'bind the complete'):
            A.validate_review_record(record, manifest, '6'*64, {})

    def test_generation_retains_unchanged_rows_and_never_creates_seed_record(self):
        with tempfile.TemporaryDirectory(prefix='prepared-metadata-unit-') as tmp:
            root = Path(tmp)
            source = b'x = 1\n'
            generation = {'files': {'assemble_resumable.py': dict(sha256='a'*64, origin='old'),
                'reviewed-inputs.json': dict(sha256='b'*64, origin='old'),
                'caller.py': dict(sha256=pin(source), origin='retained', custom_metadata='keep exactly')}}
            consumer_pins = {name: pin(source) for name in P.ORIGINAL_CONSUMER_PINS}
            for name, expected in P.ORIGINAL_CONSUMER_PINS.items():
                generation['files'][name] = dict(sha256=expected, origin='old-test')
                (root/name).write_bytes(source)
            old = dict(predecessor_manifest_sha256='c'*64, filtered_manifest_sha256='d'*64,
                       external_files={}, layout={})
            for name, raw in (('generation.json', encoded(generation)), ('old.json', encoded(old)),
                              ('assemble_resumable.py', source), ('write_prepared_profile.py', source)):
                (root/name).write_bytes(raw)
            selection = dict(generation=dict(path=str(root/'generation.json'), sha256=pin(encoded(generation))),
                predecessor_reviewed_inputs=dict(path=str(root/'old.json'), sha256=pin(encoded(old))),
                files={'caller.py': dict(source=str(root/'caller.py'), sha256=pin(source))},
                route='legacy-prepared-construct_successor', layout=dict(future_box='UNCREATED_UNIT_BOX', target='composed-r4'))
            selected_raw = encoded(selection)
            (root/'prepared-source-selection.json').write_bytes(selected_raw)
            c = dict(SELECTED_INPUT_PINS={'caller.py': pin(source)}, SOURCE_SELECTION_SHA256=pin(selected_raw),
                     ROUTE=selection['route'], DOCUMENT_SCHEMA='atlas.private.resumable-reviewed-inputs.v3',
                     PACKAGE_DIGESTS={'unit@input': '1'*64}, RETAINED_RECEIPT_PINS={},
                     RETAINED_AUXILIARY_PINS={'w2k-suite': 'e'*64})
            with patch.object(P, 'HERE', root), patch.object(P, 'SELECTION_SHA256', pin(selected_raw)), \
                    patch.object(P, 'constants', return_value=c), patch.object(P, 'PROFILE_WRITER_SHA256', pin(source)):
                preview = P.prepare(pin(source), consumer_pins=consumer_pins)
                self.assertEqual(set(preview), {'source-copy-plan.json'})
                self.assertNotIn('reviewed-inputs.json', json.loads(preview['source-copy-plan.json'])['files'])
                measurement = dict(schema='atlas.private.prepared-stage-measurement.v1', status='MEASURED_NOT_SELECTED',
                    route=c['ROUTE'], assembler_sha256=pin(source), source_selection_sha256=pin(selected_raw),
                    files=c['SELECTED_INPUT_PINS'], package_baseline_sha256=pin(A.canonical(c['PACKAGE_DIGESTS'])),
                    stage_digests={'unit@input': '1'*64, 'composition@outputs': '2'*64}, package_stage_drift={})
                mraw = encoded(measurement)
                decision = dict(schema='atlas.private.prepared-stage-selection.v1', status='SELECTED_FOR_SOURCE_BUILD',
                    measurement_sha256=pin(mraw), assembler_sha256=pin(source), source_selection_sha256=pin(selected_raw),
                    package_stage_changes={}, authority='DISPOSABLE UNIT ONLY', accuracy='No real execution')
                draw = encoded(decision)
                (root/'m.json').write_bytes(mraw)
                (root/'d.json').write_bytes(draw)
                result = P.prepare(pin(source), consumer_pins=consumer_pins,
                    measurement=root/'m.json', measurement_sha256=pin(mraw),
                    stage_selection=root/'d.json', stage_selection_sha256=pin(draw))
                successor = json.loads(result['GENERATION-prepared-r1.json'])
                self.assertEqual(successor['files']['caller.py'], generation['files']['caller.py'])
                self.assertEqual(successor['changed_rows'], sorted(
                    ['assemble_resumable.py', 'reviewed-inputs.json', *P.ORIGINAL_CONSUMER_PINS]))
                self.assertFalse((root/'reviewed-inputs.json').exists())  # prepare is pure metadata; no live write
                decision['measurement_sha256'] = '0'*64
                draw = encoded(decision)
                (root/'d.json').write_bytes(draw)
                with self.assertRaisesRegex(ValueError, 'explicit stage selection'):
                    P.prepare(pin(source), consumer_pins=consumer_pins,
                        measurement=root/'m.json', measurement_sha256=pin(mraw),
                        stage_selection=root/'d.json', stage_selection_sha256=pin(draw))

    def test_both_child_bootstraps_authenticate_before_dependent_imports(self):
        functions = []
        for name in P.ORIGINAL_CONSUMER_PINS:
            tree = ast.parse((HERE/name).read_bytes())
            child = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                         and getattr(n.targets[0], 'id', None) == 'CHILD')
            functions.append(next(n for n in ast.parse(child).body if isinstance(n, ast.FunctionDef)
                                  and n.name == 'bootstrap_runner'))
        self.assertEqual(ast.dump(functions[0]), ast.dump(functions[1]))
        namespace = {}
        exec(compile(ast.Module(body=[functions[0]], type_ignores=[]), '<disposable-bootstrap>', 'exec'), namespace)
        bootstrap = namespace['bootstrap_runner']
        names = ('start_gate', 'route2_gate', 'run_prepared_restart')
        saved = {n: sys.modules.pop(n) for n in names if n in sys.modules}
        try:
            with tempfile.TemporaryDirectory(prefix='prepared-child-unit-') as tmp:
                workspace = Path(tmp).resolve()
                target = workspace/'composed-r4'
                helpers, review = target/'helpers', target/'review'
                helpers.mkdir(parents=True)
                review.mkdir()
                sources = {'start_gate': b'VALUE = 3\n', 'route2_gate': b'import start_gate as SG\nVALUE = SG.VALUE\n',
                           'run_prepared_restart': b'import start_gate as SG\nimport route2_gate as RG\nVALUE = SG.VALUE+RG.VALUE\n'}
                for name, raw in sources.items():
                    (helpers/(name+'.py')).write_bytes(raw)
                manifest = dict(schema=A.MANIFEST_SCHEMA, prepared_route=A.ROUTE,
                    restart_runner='composed-r4/helpers/run_prepared_restart.py',
                    layout=dict(native_root='composed-r4/runtime-src', import_roots=['composed-r4/helpers']),
                    files={'composed-r4/helpers/'+n+'.py': pin(raw) for n, raw in sources.items()})
                mraw = encoded(manifest)
                (target/'manifest.json').write_bytes(mraw)
                profile = dict(schema=A.PROFILE_SCHEMA, workspace=str(workspace),
                    source_manifest=dict(path='composed-r4/manifest.json', sha256=pin(mraw)),
                    native_root=manifest['layout']['native_root'], import_roots=manifest['layout']['import_roots'])
                praw = encoded(profile)
                profile_path = review/A.PROFILE_NAME
                profile_path.write_bytes(praw)
                runner = helpers/'run_prepared_restart.py'
                before = list(sys.path)
                self.assertEqual(bootstrap(runner, profile_path, pin(praw)).VALUE, 6)
                self.assertEqual(sys.path, before)
                for name in names:
                    sys.modules.pop(name, None)
                (helpers/'start_gate.py').write_bytes(b'raise AssertionError("UNPINNED CODE EXECUTED")\n')
                with self.assertRaisesRegex(ValueError, 'selected bytes differ'):
                    bootstrap(runner, profile_path, pin(praw))
                self.assertFalse(any(name in sys.modules for name in names))
                (helpers/'start_gate.py').write_bytes(sources['start_gate'])
                profile['source_manifest']['path'] = 'another/manifest.json'
                bad = encoded(profile)
                profile_path.write_bytes(bad)
                with self.assertRaisesRegex(ValueError, 'another manifest root'):
                    bootstrap(runner, profile_path, pin(bad))
                self.assertFalse(any(name in sys.modules for name in names))
        finally:
            for name in names:
                sys.modules.pop(name, None)
            sys.modules.update(saved)


if __name__ == '__main__':
    unittest.main(verbosity=2)
