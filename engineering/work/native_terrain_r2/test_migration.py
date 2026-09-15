"""Focused synthetic migration checks; no native example continuation."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.native_terrain_r1 import evolve as old, materials as m, provenance as old_p
from work.native_terrain_r1.test_evolve import connection, CLOCK, EVIDENCE
from work.native_terrain_r1.test_materials import descriptor
from work.native_terrain_r1.receiver import FiniteReceiver
from . import migration as mig, numerics as n, provenance as p


def split_fixture(*, original_mass=None, tiny=F(1, 10**435), export=True, receiver=None):
    executor, base, _ = connection(diffusion=F(), erosion=F(), receiver=receiver)
    state = old._native(base['body'])
    column = state.column_map['a']
    index = len(column.layers) - 1
    if original_mass is not None:
        source = replace(column.layers[index], mass_kg=original_mass)
        column = replace(column, layers=(*column.layers[:index], source))
        state = replace(state, columns=tuple((key, column if key == 'a' else value)
                                            for key, value in state.columns))
        base = old.from_synthetic(state, base['body']['palette'], CLOCK,
                                  evidence=EVIDENCE, reference_runoff_m_year=F(1))
    body = deepcopy(base['body'])
    origin = next(iter(body['lineage']['a'][index]))
    source = state.column_map['a'].layers[index]
    kept = source.mass_kg - tiny * (2 if export else 1)
    donor = replace(state.column_map['a'], layers=(*state.column_map['a'].layers[:index],
                                                replace(source, mass_kg=kept)))
    receiver_column = state.column_map['b']
    receiver_column = replace(receiver_column,
                             layers=(*receiver_column.layers, replace(source, mass_kg=tiny)))
    successor = replace(state, columns=tuple((key, donor if key == 'a' else
        receiver_column if key == 'b' else value) for key, value in state.columns))
    body['state'] = successor.as_dict()
    body['initial_state_sha256'] = old_p.sha(body['state'])
    body['lineage']['a'][index][origin] = str(kept)
    body['lineage']['b'].append({origin: str(tiny)})
    if export:
        body['exported_origin_mass_kg'][origin] = str(tiny)
    untouched = next(key for key in body['origins'] if key != origin)
    body['exported_origin_mass_kg'][untouched] = '0'
    envelope = old._seal(body, base['binding'])
    old.validate(envelope)
    return executor, envelope, origin


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='native-r2-migration-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'predecessor.json'

    def reference(self, envelope):
        raw = p.encoded(envelope)
        self.path.write_bytes(raw)
        return {'checkpoint_path': str(self.path.resolve()),
                'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
                'body_sha256': envelope['body_sha256'],
                'history_count': len(envelope['body']['history'])}

    def test_exact_representable_state_preserves_metadata_frozen_stocks_and_bytes(self):
        executor, envelope, _ = connection(diffusion=F(), erosion=F())
        original = deepcopy(envelope)
        reference = self.reference(envelope)
        raw = self.path.read_bytes()
        result, receipt = mig.migrate(envelope, executor, predecessor_ref=reference)
        self.assertEqual(result['body']['state'], envelope['body']['state'])
        for name in ('origins', 'palette', 'clock', 'source', 'lineage', 'exported_origin_mass_kg'):
            self.assertEqual(result['body'][name], envelope['body'][name])
        self.assertEqual(receipt['numeric_l1_units'], 0)
        self.assertEqual(F(receipt['maximum_surface_change_m']), 0)
        self.assertEqual(receipt['before'], receipt['after'])
        self.assertEqual(envelope, original)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse(receipt['predecessor_trajectory_equivalence_claimed'])

    def test_tiny_positive_retained_export_and_zero_export_preserved_exact_closure(self):
        executor, envelope, origin = split_fixture()
        result, receipt = mig.migrate(envelope, executor, predecessor_ref=self.reference(envelope))
        before, after = envelope['body'], result['body']
        state = old._native(after)
        old._lineage_check(after, state)
        measured = 0
        for cell, rows in before['lineage'].items():
            for index, row in enumerate(rows):
                self.assertEqual(set(row), set(after['lineage'][cell][index]))
                for key, value in row.items():
                    successor = F(after['lineage'][cell][index][key])
                    self.assertGreater(successor, 0)
                    n.units(successor)
                    measured += n.ceil_error_units(abs(successor - F(value)))
        for key, value in before['exported_origin_mass_kg'].items():
            successor = F(after['exported_origin_mass_kg'][key])
            self.assertEqual(successor > 0, F(value) > 0)
            measured += n.ceil_error_units(abs(successor - F(value)))
        self.assertEqual(F(after['exported_origin_mass_kg'][origin]), n.Q)
        self.assertEqual(F(after['lineage']['b'][-1][origin]), n.Q)
        self.assertLessEqual(measured, receipt['numeric_l1_units'])
        self.assertGreater(receipt['numeric_l1_units'], 0)
        self.assertLessEqual(F(receipt['bulk_l1_error_bound_m3']), F(1, 10**12))
        self.assertEqual(after['continuation_base']['numeric_l1_units'], receipt['numeric_l1_units'])
        self.assertEqual(receipt['positive_incidences_lost'], 0)
        self.assertGreater(receipt['before']['maximum_mass_denominator_bits'], 1000)
        self.assertLessEqual(receipt['after']['maximum_mass_denominator_bits'], 65)
        for cell, column in state.columns:
            for index, layer in enumerate(column.layers):
                previous = old._native(before).column_map[cell].layers[index]
                self.assertEqual(replace(layer, mass_kg=previous.mass_kg), previous)
                self.assertGreater(layer.mass_kg, 0)

    def test_non_quantum_initial_total_and_insufficient_positive_quanta_reject_immutably(self):
        for amount, tiny in ((F(1, 3), F(1, 100)), (n.Q, n.Q / 3)):
            executor, envelope, _ = split_fixture(original_mass=amount, tiny=tiny, export=False)
            original = deepcopy(envelope)
            ref = self.reference(envelope)
            raw = self.path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'quant|unit|multiple'):
                mig.migrate(envelope, executor, predecessor_ref=ref)
            self.assertEqual(envelope, original)
            self.assertEqual(self.path.read_bytes(), raw)

    def test_pinned_source_body_raw_and_reference_rejections(self):
        executor, envelope, _ = connection(diffusion=F(), erosion=F())
        reference = self.reference(envelope)
        for key, value in (('checkpoint_path', 'relative.json'), ('checkpoint_sha256', '0' * 64),
                           ('body_sha256', '0' * 64), ('history_count', 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                mig.migrate(envelope, executor, predecessor_ref={**reference, key: value})
        with self.assertRaises(ValueError):
            mig.migrate(envelope, executor, predecessor_ref={})
        changed = deepcopy(envelope)
        changed['binding']['sources'][next(iter(changed['binding']['sources']))] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'binding|source'):
            mig.migrate(changed, executor, predecessor_ref=reference)
        self.path.write_bytes(p.encoded({**envelope, 'body_sha256': '0' * 64}))
        reference['checkpoint_sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'body pin'):
            mig.migrate(envelope, executor, predecessor_ref=reference)

    def test_predecessor_change_during_migration_rejected(self):
        executor, envelope, _ = connection(diffusion=F(), erosion=F())
        reference = self.reference(envelope)
        allocate = n.allocate_positive
        def change_parent(total, desired):
            self.path.write_bytes(b'{}')
            return allocate(total, desired)
        with patch.object(n, 'allocate_positive', side_effect=change_parent):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                mig.migrate(envelope, executor, predecessor_ref=reference)

    def test_prefix_time_water_and_history_retained_by_reference(self):
        executor, envelope, acceptance = connection(diffusion=F(), erosion=F())
        envelope = executor.advance(envelope, F(1), acceptance, operation_id='original-prefix')
        reference = self.reference(envelope)
        result, receipt = mig.migrate(envelope, executor, predecessor_ref=reference)
        body = result['body']
        self.assertEqual(body['history'], [])
        self.assertEqual(body['initial_elapsed_years'], '1')
        self.assertEqual(body['continuation_base']['surface_water_exported_m3'], '2/5')
        self.assertEqual(body['parent']['predecessor'], reference)
        self.assertEqual(body['parent']['migration'], receipt)
        self.assertNotIn('body', body['parent'])
        self.assertEqual(len(envelope['body']['history']), 1)
        self.assertEqual(receipt['prefix_operation_ids'], ['original-prefix'])
        self.assertEqual(receipt['successor_initial_state_sha256'], p.sha(body['state']))
        self.assertEqual(receipt['initial_elapsed_years'], body['initial_elapsed_years'])
        self.assertEqual(receipt['prior_surface_water_exported_m3'], '2/5')
        self.assertEqual(receipt['prior_cumulative_allocation_error_m3'],
                         envelope['body']['cumulative_allocation_error_m3'])
        self.assertEqual(receipt['original_origin_inventory_sha256'], p.sha(envelope['body']['origins']))
        for name in ('palette', 'clock', 'source'):
            self.assertEqual(receipt[name + '_sha256'], p.sha(envelope['body'][name]))

    def test_conservative_bulk_conversion_includes_receiving_packing_and_receiver(self):
        receiver = FiniteReceiver('test', F(100), F(-20), F(-1), F(0), F(1), F(9, 10), F(1), EVIDENCE)
        executor, envelope, _ = split_fixture(receiver=receiver)
        palette = envelope['body']['palette']
        executor.packing = {key: F(19, 20) for key in executor.packing}
        minimum = min(F(d['grain_density_kg_m3']) * (1 - porosity)
            for key, d in palette.items()
            for porosity in (F(d['porosity']), executor.packing.get(key, F(d['porosity'])), receiver.deposit_porosity))
        self.assertEqual(mig.minimum_mass_per_bulk(executor, palette), minimum)
        result, receipt = mig.migrate(envelope, executor, predecessor_ref=self.reference(envelope))
        self.assertEqual(F(receipt['bulk_l1_error_bound_m3']), n.mass(receipt['numeric_l1_units']) / minimum)
        exported = sum((F(value) / F(palette[result['body']['origins'][key]['material_id']]['grain_density_kg_m3'])
                        for key, value in result['body']['exported_origin_mass_kg'].items()), F())
        self.assertEqual(F(result['body']['receiver']['cumulative_solid_m3']), exported)
        self.assertEqual(F(result['body']['receiver']['cumulative_liquid_m3']), 0)

    def test_actual_codec_control_is_authenticated_without_embedding_prefix(self):
        executor, envelope, acceptance = connection(diffusion=F(), erosion=F())
        envelope = executor.advance(envelope, F(1), acceptance, operation_id='codec-prefix')
        codec_path = Path(__file__).resolve().parents[2] / 'outputs/native-terrain-r1/checkpoint_io.py'
        spec = importlib.util.spec_from_file_location('native_migration_test_codec', codec_path)
        codec = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(codec)
        codec.save_checkpoint(self.path, {'envelope': envelope, 'cumulative_model_seconds': 0})
        restored = codec.load(self.path)['envelope']
        raw = self.path.read_bytes()
        history_raw = {file: file.read_bytes() for file in self.path.parent.glob('history/*.json')}
        reference = {'checkpoint_path': str(self.path.resolve()),
            'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
            'body_sha256': restored['body_sha256'], 'history_count': 1}
        read_bytes = Path.read_bytes
        def only_control(path):
            self.assertEqual(path, self.path)
            return read_bytes(path)
        with patch.object(Path, 'read_bytes', only_control):
            control = mig.read_predecessor_control(reference)
        self.assertNotIn('history', control['body'])
        self.assertEqual(control['body_sha256'], restored['body_sha256'])
        result, _ = mig.migrate(restored, executor, predecessor_ref=reference)
        self.assertEqual(result['body']['history'], [])
        self.assertEqual(result['body']['parent']['predecessor'], reference)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual({file: file.read_bytes() for file in history_raw}, history_raw)

    def test_fixed_migration_cap_rejects_large_bulk_error_without_changing_parent(self):
        # Deliberately sparse synthetic material makes one quantum's bulk effect
        # exceed the declared cap; no cap widening or hidden loss is permitted.
        executor, base, _ = connection(diffusion=F(), erosion=F())
        tt = m.native()
        material = descriptor('sparse-cap-test', F(1, 10**12), F(), 'mobile_sediment')
        layer = tt.Layer(material['material_id'], F(1), F(1, 10**12), F(),
                         'mobile_sediment', material['evidence'])
        state = tt.LandscapeState((('a', tt.Column(F(1), F(), (layer,), 'SYNTHETIC TEST')),))
        envelope = old.from_synthetic(state, {material['material_id']: material}, CLOCK,
                                      evidence=EVIDENCE, reference_runoff_m_year=F(1))
        body = deepcopy(envelope['body'])
        origin = next(iter(body['origins']))
        tiny = F(1, 10**435)
        column = replace(state.column_map['a'], layers=(replace(layer, mass_kg=1 - tiny),
                                                       replace(layer, mass_kg=tiny)))
        state = replace(state, columns=(('a', column),))
        body.update(state=state.as_dict(), initial_state_sha256=p.sha(state.as_dict()),
                    lineage={'a': [{origin: str(1 - tiny)}, {origin: str(tiny)}]})
        envelope = old._seal(body, envelope['binding'])
        executor.packing = {material['material_id']: F()}
        executor.sediment_laws = (replace(executor.sediment_laws[0],
            material_id=material['material_id'], deposited_porosity=F()),)
        reference = self.reference(envelope)
        raw = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'migration bulk L1 allocation error cap exceeded'):
            mig.migrate(envelope, executor, predecessor_ref=reference)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_channel_deposition_porosity_is_in_conversion_and_material_ids_are_validated(self):
        executor, envelope, _ = connection(diffusion=F(), erosion=F())
        palette = envelope['body']['palette']
        executor.sediment_laws = tuple(replace(law, deposited_porosity=F(99, 100))
                                       for law in executor.sediment_laws)
        expected = min(F(row['grain_density_kg_m3']) / 100 for row in palette.values())
        self.assertEqual(mig.minimum_mass_per_bulk(executor, palette), expected)
        result, receipt = mig.migrate(envelope, executor, predecessor_ref=self.reference(envelope))
        self.assertEqual(F(receipt['minimum_mass_per_bulk_m3']), expected)
        self.assertEqual(F(result['body']['minimum_mass_per_bulk_m3']), expected)
        valid = executor.sediment_laws
        executor.sediment_laws = (*valid, valid[0])
        with self.assertRaisesRegex(ValueError, 'material identity'):
            mig.minimum_mass_per_bulk(executor, palette)
        executor.sediment_laws = (replace(valid[0], material_id='unknown-synthetic-material'),)
        with self.assertRaisesRegex(ValueError, 'material identity'):
            mig.minimum_mass_per_bulk(executor, palette)


if __name__ == '__main__':
    unittest.main(verbosity=2)
