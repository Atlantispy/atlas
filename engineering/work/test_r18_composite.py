"""Two exact synthetic shared-compartment/transfer checks; no model runs."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r18 import composite


def constituents():
    return [dict(unit_id='A', bulk_weight='1/4', grain_density_kg_m3=2, porosity='1/5'),
            dict(unit_id='B', bulk_weight='3/4', grain_density_kg_m3=4, porosity='2/5'),
            dict(unit_id='ZERO', bulk_weight=0, grain_density_kg_m3=3, porosity=0)]


def create(rows=None, **changes):
    options = {'phase': 'bedrock', 'evidence': 'SYNTHETIC TEST explicit mixture'}
    options.update(changes)
    return composite.create(constituents() if rows is None else rows, '1/10', **options)


class CompositeTests(unittest.TestCase):
    def test_exact_shared_compartment_stock_and_permutation_identity(self):
        original = constituents()
        material = create(original)
        self.assertEqual(original, constituents())
        self.assertEqual(material['grain_density_kg_m3'], '44/13')
        self.assertEqual(material['porosity'], '7/20')
        self.assertEqual(material['k_per_year'], '1/10')
        self.assertEqual(material['omitted_zero_weight_unit_ids'], ['ZERO'])
        self.assertEqual([row['mass_fraction'] for row in material['constituents']], ['2/11', '9/11'])
        self.assertEqual([row['solid_fraction'] for row in material['constituents']], ['4/13', '9/13'])
        reordered = create(list(reversed(original)))
        self.assertEqual(reordered, material)
        self.assertEqual(create(original, evidence='SYNTHETIC TEST revised citation')['material_id'], material['material_id'])
        self.assertEqual(create(original[:2])['material_id'], material['material_id'])
        changed = constituents(); changed[0]['bulk_weight'], changed[1]['bulk_weight'] = '1/2', '1/2'
        self.assertNotEqual(create(changed)['material_id'], material['material_id'])
        self.assertNotEqual(create(phase='mobile_sediment')['material_id'], material['material_id'])
        other_k = composite.create(original, '1/20', phase='bedrock', evidence='SYNTHETIC TEST supplied K')
        self.assertNotEqual(other_k['material_id'], material['material_id'])
        palette = {material['material_id']: material}
        projected = composite.project_mass(material['material_id'], 110, palette)
        self.assertEqual(projected, {'A': {'mass_kg': '20', 'solid_volume_m3': '10'},
                                     'B': {'mass_kg': '90', 'solid_volume_m3': '45/2'}})
        # A 50 m3 bulk compartment carries exactly the same mass and solid volume.
        self.assertEqual(50*(1-F(material['porosity']))*F(material['grain_density_kg_m3']), 110)
        self.assertEqual(sum(F(row['solid_volume_m3']) for row in projected.values()), F(110)/F(material['grain_density_kg_m3']))

    def test_congruent_removed_remaining_stock_projection_and_invalid_inputs(self):
        material = create(); identity = material['material_id']; palette = {identity: material}
        before = composite.project_mass(identity, 110, palette)
        removed = composite.project_mass(identity, '77/3', palette)
        remaining = composite.project_mass(identity, F(110)-F(77, 3), palette)
        for unit in before:
            for quantity in ('mass_kg', 'solid_volume_m3'):
                self.assertEqual(F(before[unit][quantity]), F(removed[unit][quantity])+F(remaining[unit][quantity]))
        self.assertEqual(composite.project_mass(identity, 0, palette),
                         {unit: {'mass_kg': '0', 'solid_volume_m3': '0'} for unit in before})
        invalid = [[], constituents()+[deepcopy(constituents()[0])]]
        for key, value in [('bulk_weight', '1/2'), ('bulk_weight', -1), ('bulk_weight', True),
                           ('grain_density_kg_m3', 0), ('grain_density_kg_m3', float('inf')),
                           ('porosity', 1), ('porosity', float('nan')), ('unit_id', 'UNKNOWN')]:
            rows = constituents(); rows[0][key] = value; invalid.append(rows)
        rows = constituents(); del rows[0]['porosity']; invalid.append(rows)
        rows = constituents(); rows[0]['thickness_m'] = 1; invalid.append(rows)
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                create(rows)
        for key, value in [('grain_density_kg_m3', '4'), ('material_id', 'forged')]:
            forged = deepcopy(material); forged[key] = value
            with self.assertRaisesRegex(ValueError, 'descriptor or identity changed'):
                composite.project_mass(identity, 110, {identity: forged})
        forged = deepcopy(material); forged['constituents'][0]['mass_fraction'] = '1/2'
        with self.assertRaisesRegex(ValueError, 'descriptor or identity changed'):
            composite.project_mass(identity, 110, {identity: forged})
        for mass in (-1, True, float('nan'), 1 << 8192):
            with self.subTest(mass=mass), self.assertRaises(ValueError):
                composite.project_mass(identity, mass, palette)
        with self.assertRaisesRegex(ValueError, 'palette'):
            composite.project_mass(identity, 1, {})
        with self.assertRaises(ValueError):
            create(phase='UNKNOWN')
        with self.assertRaises(ValueError):
            create(evidence='UNKNOWN')
        with self.assertRaises(ValueError):
            composite.create(constituents(), -1, phase='bedrock', evidence='SYNTHETIC TEST')
        with self.assertRaises(TypeError):
            composite.create(constituents(), 1, evidence='SYNTHETIC TEST')


if __name__ == '__main__':
    unittest.main()
