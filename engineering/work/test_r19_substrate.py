"""Two synthetic finite-substrate checks; no coastal/world generation."""
from dataclasses import replace
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r18 import composite
from work.generator_upgrade_r19 import substrate


E = 'SYNTHETIC TEST: finite substrate mechanics; not Diadem coastal calibration'


class SubstrateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.native = regional.p.backend()

    def test_exact_partition_contact_crossing_and_finite_exhaustion(self):
        native = self.native
        area = F(12)
        lower = native.Layer('test-dense', area*2*2700*F(9, 10),
                             F(2700), F(1, 10), 'bedrock', E)
        upper = native.Layer('test-porous', area*1*2000*F(3, 4),
                             F(2000), F(1, 4), 'bedrock', E)
        original = native.Column(area, F(-3), (lower, upper), 'SYNTHETIC TEST')
        initial_mass = original.mass_kg
        self.assertEqual(original.surface_m, 0)

        children, receipt = substrate.partition(original,
            {'active-strip': F(7, 2), 'inactive-remainder': F(17, 2)})
        type(self).partition_receipt = receipt
        self.assertEqual(set(children), {'active-strip', 'inactive-remainder'})
        self.assertNotEqual(children['active-strip'].area_m2, children['inactive-remainder'].area_m2)
        self.assertEqual(sum((child.area_m2 for child in children.values()), F()), area)
        self.assertEqual(sum((child.mass_kg for child in children.values()), F()), initial_mass)
        for child in children.values():
            self.assertEqual(child.basal_elevation_m, original.basal_elevation_m)
            self.assertEqual(child.surface_m, original.surface_m)
            self.assertEqual(child.source_status, 'SYNTHETIC TEST')
            bottom = child.basal_elevation_m
            for actual, parent, expected_top in zip(child.layers, original.layers, (F(-1), F())):
                self.assertEqual((actual.material_id, actual.phase, actual.evidence,
                    actual.grain_density_kg_m3, actual.porosity),
                    (parent.material_id, parent.phase, parent.evidence,
                     parent.grain_density_kg_m3, parent.porosity))
                self.assertEqual(actual.mass_kg, parent.mass_kg*child.area_m2/area)
                bottom += actual.bulk_volume_m3/child.area_m2
                self.assertEqual(bottom, expected_top)
        for index, parent in enumerate(original.layers):
            self.assertEqual(sum((child.layers[index].mass_kg for child in children.values()), F()), parent.mass_kg)
            self.assertEqual(sum((child.layers[index].mass_kg/child.layers[index].grain_density_kg_m3
                                  for child in children.values()), F()), parent.mass_kg/parent.grain_density_kg_m3)
        for name in ('mass_residual_kg', 'solid_volume_residual_m3', 'area_residual_m2'):
            self.assertEqual(F(receipt[name]), 0)
        with self.assertRaises(ValueError):
            substrate.partition(original, {'active-strip-without-remainder': F(7, 2)})
        with self.assertRaises(ValueError):
            substrate.partition(original, {'duplicate-a': area, 'duplicate-b': area})

        after, removed, unmet = substrate.strip_depth(original, F(3, 2))
        self.assertEqual(unmet, 0)
        self.assertEqual([layer.material_id for layer in removed], ['test-porous', 'test-dense'])
        self.assertEqual(removed[0], upper)
        self.assertEqual(removed[1].mass_kg, area*F(1, 2)*2700*F(9, 10))
        self.assertEqual(removed[1].porosity, lower.porosity)
        self.assertEqual(removed[1].grain_density_kg_m3, lower.grain_density_kg_m3)
        self.assertEqual(after.layers, (replace(lower, mass_kg=lower.mass_kg-removed[1].mass_kg),))
        self.assertEqual(after.surface_m, F(-3, 2))
        self.assertEqual(sum((layer.mass_kg for layer in removed), F())+after.mass_kg, initial_mass)
        self.assertEqual(sum((layer.bulk_volume_m3 for layer in removed), F()), area*F(3, 2))
        exhausted, all_removed, unmet = substrate.strip_depth(original, 4)
        self.assertEqual(exhausted.layers, ())
        self.assertEqual(exhausted.surface_m, original.basal_elevation_m)
        self.assertEqual(unmet, 1)
        self.assertEqual(sum((layer.mass_kg for layer in all_removed), F()), initial_mass)
        self.assertEqual(sum((layer.mass_kg/layer.grain_density_kg_m3 for layer in all_removed), F()),
                         sum((layer.mass_kg/layer.grain_density_kg_m3 for layer in original.layers), F()))
        self.assertEqual(original.layers, (lower, upper))
        self.assertEqual(original.mass_kg, initial_mass)

    def test_bound_modified_k_contrast_and_independent_mobile_porosity(self):
        decision = substrate.decision()
        type(self).owner_decision = decision
        self.assertEqual(decision['source_status'], 'WORKING NON-CANON')
        self.assertEqual(decision['vertical_and_geometry']['r18_to_sea_registration'], 'NOT_ASSERTED')
        constituents = [
            {'unit_id': 'test-A', 'bulk_weight': '1/3', 'grain_density_kg_m3': 2700, 'porosity': '0.02'},
            {'unit_id': 'test-B', 'bulk_weight': '2/3', 'grain_density_kg_m3': 2500, 'porosity': '0.1'}]
        # Explicit synthetic alteration of A before arithmetic mixture; the
        # coastal bridge must use this bound effective K, not a prototype K.
        modified_a = (1-F(1, 2))*F('0.00002')+F(1, 2)*F('0.000005')
        effective_k = F(1, 3)*modified_a+F(2, 3)*F('0.00001')
        descriptor = composite.create(constituents, effective_k, phase='bedrock', evidence=E)
        mid = descriptor['material_id']; palette = {mid: descriptor}
        reference = F(str(decision['substrate_and_materials']['bounded_coastal_contrast']['reference_k_per_year']))
        self.assertGreater(reference, 0)
        self.assertEqual(substrate.bedrock_contrast(mid, palette), effective_k/reference)
        self.assertNotEqual(effective_k, F('0.00002'))
        zero = composite.create(constituents, 0, phase='bedrock', evidence=E)
        self.assertEqual(substrate.bedrock_contrast(zero['material_id'], {zero['material_id']: zero}), 0)
        nonrock = composite.create(constituents, effective_k, phase='mobile_sediment', evidence=E)
        with self.assertRaises(ValueError):
            substrate.bedrock_contrast(nonrock['material_id'], {nonrock['material_id']: nonrock})

        phi = F(str(decision['sediment_material_default']['fresh_deposit_porosity']))
        self.assertEqual(phi, F(2, 5))
        rock_phi = F(descriptor['porosity'])
        self.assertNotEqual(phi, rock_phi)
        rock = self.native.Layer(mid, F(123), F(descriptor['grain_density_kg_m3']), rock_phi, 'bedrock', E)
        column = self.native.Column(F(1), F(), (rock,), 'SYNTHETIC TEST')
        _, parcels, unmet = substrate.strip_depth(column, column.surface_m)
        self.assertEqual(unmet, 0)
        self.assertEqual(parcels, (rock,))
        mobile = replace(parcels[0], phase='mobile_sediment', porosity=phi)
        self.assertEqual(mobile.material_id, rock.material_id)
        self.assertEqual(mobile.mass_kg, rock.mass_kg)
        self.assertEqual(mobile.grain_density_kg_m3, rock.grain_density_kg_m3)
        self.assertEqual(mobile.bulk_volume_m3, rock.mass_kg/rock.grain_density_kg_m3/(1-phi))
        self.assertNotEqual(mobile.bulk_volume_m3, rock.bulk_volume_m3)
        self.assertEqual(composite.project_mass(mid, mobile.mass_kg, palette),
                         composite.project_mass(mid, rock.mass_kg, palette))


if __name__ == '__main__':
    unittest.main()
