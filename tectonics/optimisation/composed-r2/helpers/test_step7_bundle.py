"""Step 7 source closure and compact heat integration, without frozen composition."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
R = HERE.parent
BASE = HERE.parents[1]/'runtime-integration-r1'
H = HERE.parents[3]/'heat-repair-20261007'
T = HERE.parents[4]
for directory in (BASE/'runtime-src', R, R/'endpoint-checkpoints'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import private_heat_bundle as B
import test_private_heat_bundle_extended as OLD


def compact_inputs():
    manifest, inputs, external, ram, helpers = OLD.authenticated_inputs()
    compact = {name: OLD._helper_source(name) for name in B.COMPACT_HELPERS}
    return manifest, inputs, external, ram, helpers, compact


def successor():
    _, inputs, external, ram, helpers, compact = compact_inputs()
    return B.construct_compact_successor(inputs, reference_root=H,
        reference_pins=B.REFERENCE_PINS, external=external, ram=ram,
        helpers=helpers, compact_helpers=compact)


def write_layout(directory):
    """Bounded test layout; actual WP9 output and source pins stay untouched."""
    helper_out, ram_out, report = successor()
    root, helpers, ram = OLD.write_layout(directory, helper_out, ram_out)
    # Fresh-owner controls use the native holder and streamed validation from
    # Step 6. No runner, interval or migration source is silently activated.
    import spatial_transfer as TRANSFER
    import spatial_indexed_patch as INDEXED
    import exchange_record_patch as EXCHANGE
    import spatial_validation_patch as VALIDATION
    path = root/'atlas_tectonics/integration_spatial_owner.py'
    source = INDEXED.transform(TRANSFER.spatial_owner_source(path.read_text(encoding='utf8')))
    path.write_text(VALIDATION.owner_source(EXCHANGE.holder_source(source)), encoding='utf8', newline='\n')
    import heat_cold_patch as COLD
    import partition_workflow_transform as PARTITION
    import workflow_transfer as WORKFLOW
    path = root/'atlas_tectonics/integration_private_heat_cold.py'
    source = PARTITION.cold_source(WORKFLOW.private_heat_cold_source(path.read_text(encoding='utf8')))
    path.write_text(B.cold_binding_source(COLD.transform(source), report), encoding='utf8', newline='\n')
    return root, helpers, ram, report


class BundleTests(unittest.TestCase):
    def test_source_closure_pins_kernel_and_producer_registration(self):
        helpers, ram, report = successor()
        self.assertEqual(report['schema'], 'atlas.private.compact-heat-successor-composition.v1')
        self.assertFalse(report['checkpoint_admission'])
        self.assertFalse(report['numerical_algorithm_changed'])
        for old, new in B.COMPACT_RENAMES.items():
            self.assertNotIn(old, helpers)
            self.assertIn(new, helpers)
        self.assertEqual(report['cold_binding_sha256']['successor'],
                         sha256(helpers['private_heat_restored_binding_r10.py']).hexdigest())
        kernel = 'private_heat_forward_kernel_r13.py'
        self.assertEqual(ast.dump(ast.parse(helpers[kernel]), include_attributes=False),
                         ast.dump(ast.parse((H/kernel).read_bytes()), include_attributes=False))
        for name, raw in {**helpers, **ram}.items():
            compile(raw, name, 'exec')
        for name in ('private_heat_native_issuer_r13.py', 'private_heat_checkpoint_consumer_r10.py',
                     'private_heat_restored_binding_r10.py'):
            self.assertNotIn(b'import private_heat_native_issuer_r12', helpers[name])
        joined = helpers['private_heat_joined_consumer_r6.py'].decode()
        self.assertIn('EXCHANGE_RECORD.build_advance', joined)
        self.assertIn('_SV.access', joined)
        self.assertTrue(any('heat_ledger_issuer_patch.issuer_source' in key
                            for key in report['stage_digests']))
        pins = {sha256(raw).hexdigest() for raw in (*helpers.values(), *ram.values())}
        for change in report['dependency_pin_changes']:
            self.assertIn(change['successor'], pins)

    def test_exact_helper_inventory_and_transformer_bytes_refuse(self):
        _, inputs, external, ram, helpers, compact = compact_inputs()
        def build(changed):
            return B.construct_compact_successor(inputs, reference_root=H,
                reference_pins=B.REFERENCE_PINS, external=external, ram=ram,
                helpers=helpers, compact_helpers=changed)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            build({k: v for k, v in compact.items() if k != 'heat_ledger_tables.py'})
        changed = dict(compact)
        changed['heat_ledger_issuer_patch.py'] += b'\n# unbound transformer\n'
        with self.assertRaisesRegex(ValueError, 'authenticated bytes'):
            build(changed)

    def test_dependency_rename_preserves_historical_logical_labels(self):
        source = ("import private_heat_native_issuer_r12 as I\n"
                  "filename = 'private_heat_checkpoint_consumer_r9.py'\n"
                  "schema = 'atlas.private.heat.r12'\n"
                  "label = 'private_heat_native_issuer_r12.advance'\n")
        result = B._rename_compact_dependencies(source)
        self.assertIn('import private_heat_native_issuer_r13 as I', result)
        self.assertIn("'private_heat_checkpoint_consumer_r10.py'", result)
        self.assertIn("'atlas.private.heat.r12'", result)
        self.assertIn("'private_heat_native_issuer_r12.advance'", result)

    def test_composed_imports_in_fresh_process(self):
        with tempfile.TemporaryDirectory(prefix='step7-source-', dir=T/'_t') as directory:
            root, helpers, ram, report = write_layout(directory)
            script = ("import sys,json,importlib,pathlib; "
                "sys.path[:0]=json.loads(sys.argv[1]); "
                "mods=[importlib.import_module(n) for n in "
                "('private_heat_native_issuer_r13','private_heat_checkpoint_consumer_r10',"
                "'private_heat_restored_binding_r10','private_heat_joined_consumer_r6')]; "
                "assert all(pathlib.Path(m.__file__).parent==pathlib.Path(sys.argv[2]) for m in mods); "
                "cold=importlib.import_module('atlas_tectonics.integration_private_heat_cold'); "
                "cold._verify(None); assert cold.B is mods[2]; "
                "print(json.dumps({'imports':[m.__name__ for m in mods]}))")
            paths = [str(root), str(helpers), str(ram), str(H/'source/tectonics/tests')]
            child = subprocess.run([sys.executable, '-B', '-c', script, json.dumps(paths), str(helpers)],
                cwd=directory, capture_output=True, text=True, timeout=120)
            self.assertEqual(child.returncode, 0, child.stdout+'\n'+child.stderr)
            self.assertEqual(len(json.loads(child.stdout)['imports']), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
