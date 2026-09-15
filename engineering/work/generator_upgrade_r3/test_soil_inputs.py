"""Independent analytical stock/geometry/port checks for the actual R3 source."""
import copy
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from . import soil_inputs as s

L = s.landscape
EVIDENCE = 'synthetic dimensional fixture, not a Diadem estimate'


def properties(material='soil', phase='immobile_regolith', porosity=F(1, 2), **changes):
    p = s.MaterialHydraulics(material, phase, 2000, porosity, F(1, 10), 2, 2, F(1, 2),
                             F(1, 1000), F(1, 500), 1000, 30, EVIDENCE, 'SYNTHETIC TEST')
    return replace(p, **changes)


def profile():
    parent = L.Layer('parent', 6000, 2000, F(1, 2), 'immobile_regolith', EVIDENCE)
    top = L.Layer('soil', 2000, 2000, F(1, 2), 'immobile_regolith', EVIDENCE)
    column = L.Column(2, -5, (parent, top), 'SYNTHETIC TEST')
    return s.bind_column(column, (properties('parent'), properties()), ('parent-id', 'top-id'),
                         (F(6, 5), F(3, 5)), profile_id='fixture', evidence=EVIDENCE)


def sediment(mass=1000, porosity=F(1, 2), material='soil'):
    return L.Layer(material, mass, 2000, porosity, 'mobile_sediment', EVIDENCE)


class SoilInputTests(unittest.TestCase):
    def test_layer_geometry_uses_actual_mass_density_porosity_and_area(self):
        p = profile()
        rows = s.hydraulic_rows(p)
        self.assertEqual([(r['thickness_m'], r['top_depth_m'], r['bottom_depth_m']) for r in rows],
                         [(F(1), F(0), F(1)), (F(3), F(1), F(4))])
        self.assertEqual(p.column.surface_m, -1)
        self.assertEqual(sum(r['thickness_m'] for r in rows), p.column.surface_m - p.column.basal_elevation_m)

    def test_hydraulic_rows_reverse_bottom_to_top_stock(self):
        self.assertEqual([r['layer_id'] for r in s.hydraulic_rows(profile())], ['top-id', 'parent-id'])

    def test_theta_uses_bulk_volume_not_solid_volume_or_area(self):
        rows = s.hydraulic_rows(profile())
        self.assertEqual([r['theta'] for r in rows], [F(3, 10), F(1, 5)])
        self.assertEqual([r['theta_s'] for r in rows], [F(1, 2), F(1, 2)])

    def test_directional_conductivity_and_strength_are_explicit(self):
        row = s.hydraulic_rows(profile())[0]
        self.assertEqual((row['ksat_m_s'], row['ksat_horizontal_m_s']), (F(1, 1000), F(1, 500)))
        self.assertEqual((row['effective_cohesion_pa'], row['friction_angle_deg']), (1000, 30))
        self.assertNotIn('horizon', row)
        self.assertNotIn('fertility', row)
        self.assertNotIn('head_m', row)

    def test_partial_surface_erosion_preserves_retained_theta(self):
        p = profile()
        result = s.strip_surface(p, 1000)
        self.assertEqual(result.profile.column.layers[-1].mass_kg, 1000)
        self.assertEqual(result.profile.bindings[-1].water_volume_m3, F(3, 10))
        self.assertEqual(result.exported_parcels[0].water_volume_m3, F(3, 10))
        self.assertEqual(s.hydraulic_rows(result.profile)[0]['theta'], F(3, 10))
        self.assertEqual(result.profile.column.layers[0], p.column.layers[0])

    def test_contact_crossing_exports_each_actual_layer_moisture(self):
        result = s.strip_surface(profile(), 3000)
        self.assertEqual([(p.layer.material_id, p.layer.mass_kg, p.water_volume_m3) for p in result.exported_parcels],
                         [('soil', 2000, F(3, 5)), ('parent', 1000, F(1, 5))])
        self.assertEqual(result.profile.water_volume_m3, 1)
        self.assertEqual(result.profile.bindings[0].layer_id, 'parent-id')
        self.assertEqual(result.receipt['water_residual_m3'], [0, 1])

    def test_exact_contact_removes_binding_without_phantom_layer(self):
        result = s.strip_surface(profile(), 2000)
        self.assertEqual(len(result.profile.bindings), 1)
        self.assertEqual(s.hydraulic_rows(result.profile)[0]['theta'], F(1, 5))

    def test_finite_exhaustion_exports_all_water_and_reports_unmet_mass(self):
        result = s.strip_surface(profile(), 10000)
        self.assertEqual(result.profile.bindings, ())
        self.assertEqual(s.hydraulic_rows(result.profile), ())
        self.assertEqual(result.profile.water_volume_m3, 0)
        self.assertEqual(sum(p.water_volume_m3 for p in result.exported_parcels), F(9, 5))
        self.assertEqual(result.receipt['unmet_mass_kg'], [2000, 1])
        self.assertEqual(result.profile.column.surface_m, -5)

    def test_zero_removal_has_no_export_and_exact_state(self):
        p = profile()
        result = s.strip_surface(p, 0)
        self.assertEqual(result.profile, p)
        self.assertEqual(result.exported_parcels, ())

    def test_actual_r1_landscape_erosion_is_reconciled(self):
        p = profile()
        def q(name, value, unit):
            return L.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')
        laws = tuple(L.ErosionLaw(key, 'immobile_regolith', q('erosion_coefficient_at_reference_runoff', 1, '1/year'),
                                q('reference_runoff', 1, 'm/year')) for key in ('parent', 'soil'))
        state = L.LandscapeState((('fixture', p.column),))
        forcing = {'fixture': L.Forcing(q('discharge', 1, 'm3/year'), q('hydraulic_slope', 1, '1'))}
        evolved = L.advance(state, forcing, laws, F(3, 2))
        result = s.reconcile_eroded_column(p, evolved.state.column_map['fixture'])
        self.assertEqual(result.profile.column.surface_m, F(-5, 2))
        self.assertEqual(result.profile.water_volume_m3, 1)
        self.assertEqual([p.layer for p in result.exported_parcels], [x.source_layer for x in evolved.eroded_parcels])

    def test_removal_refinement_preserves_final_exact_water(self):
        p = profile()
        whole = s.strip_surface(p, 3500)
        first = s.strip_surface(p, 1500)
        second = s.strip_surface(first.profile, 2000)
        self.assertEqual(whole.profile, second.profile)
        self.assertEqual(sum(x.water_volume_m3 for x in whole.exported_parcels),
                         sum(x.water_volume_m3 for x in (*first.exported_parcels, *second.exported_parcels)))

    def test_wet_deposition_changes_height_and_retains_buried_stock(self):
        p = profile()
        result = s.deposit_surface(p, sediment(), properties(phase='mobile_sediment'), F(1, 4),
                                   layer_id='deposit', evidence=EVIDENCE)
        self.assertEqual(result.profile.column.surface_m, F(-1, 2))
        self.assertEqual(result.profile.bindings[:-1], p.bindings)
        self.assertEqual(result.profile.column.layers[:-1], p.column.layers)
        self.assertEqual(result.profile.water_volume_m3, F(41, 20))
        self.assertEqual(result.water_to_surface_m3, 0)

    def test_packing_excess_water_goes_to_explicit_surface_port(self):
        p = profile()
        result = s.deposit_surface(p, sediment(porosity=F(1, 5)), properties(phase='mobile_sediment', porosity=F(1, 5)), F(1, 4),
                                   layer_id='dense-deposit', evidence=EVIDENCE)
        # 1000/2000/(1-1/5) = 5/8 m3 bulk; pores 1/8 m3.
        self.assertEqual(result.profile.bindings[-1].water_volume_m3, F(1, 8))
        self.assertEqual(result.water_to_surface_m3, F(1, 8))
        self.assertEqual(result.receipt['water_residual_m3'], [0, 1])

    def test_actual_eroded_water_and_mass_transfer_close_across_columns(self):
        source = profile()
        eroded = s.strip_surface(source, 1000)
        parcel = eroded.exported_parcels[0]
        layer = replace(parcel.layer, phase='mobile_sediment', porosity=F(1, 5))
        deposited = s.deposit_surface(profile(), layer, properties(phase='mobile_sediment', porosity=F(1, 5)),
                                      parcel.water_volume_m3, layer_id='routed', evidence=EVIDENCE)
        self.assertEqual(source.column.mass_kg + profile().column.mass_kg,
                         eroded.profile.column.mass_kg + deposited.profile.column.mass_kg)
        self.assertEqual(source.water_volume_m3 + profile().water_volume_m3,
                         eroded.profile.water_volume_m3 + deposited.profile.water_volume_m3 + deposited.water_to_surface_m3)
        self.assertEqual(deposited.water_to_surface_m3, F(7, 40))

    def test_deposit_then_re_erode_reexposes_original_water_state(self):
        p = profile()
        deposited = s.deposit_surface(p, sediment(), properties(phase='mobile_sediment'), F(1, 4), layer_id='new', evidence=EVIDENCE)
        eroded = s.strip_surface(deposited.profile, 1000)
        self.assertEqual(eroded.profile, p)
        self.assertEqual(eroded.exported_parcels[0].water_volume_m3, F(1, 4))

    def test_exhausted_column_can_receive_explicit_wet_sediment(self):
        empty = s.strip_surface(profile(), 8000).profile
        deposited = s.deposit_surface(empty, sediment(), properties(phase='mobile_sediment'), F(1, 4), layer_id='new', evidence=EVIDENCE)
        self.assertEqual(deposited.profile.column.surface_m, F(-9, 2))
        self.assertEqual(len(deposited.profile.bindings), 1)

    def test_subresidual_deposit_cannot_fabricate_minimum_water(self):
        with self.assertRaises(ValueError):
            s.deposit_surface(profile(), sediment(), properties(phase='mobile_sediment'), 0, layer_id='dry', evidence=EVIDENCE)

    def test_non_sediment_deposition_requires_explicit_phase_change(self):
        with self.assertRaises(ValueError):
            s.deposit_surface(profile(), profile().column.layers[-1], properties(), F(3, 5), layer_id='raw', evidence=EVIDENCE)

    def test_reused_active_layer_identity_rejects(self):
        with self.assertRaises(ValueError):
            s.deposit_surface(profile(), sediment(), properties(phase='mobile_sediment'), F(1, 4), layer_id='top-id', evidence=EVIDENCE)

    def test_deposition_properties_must_match_changed_packing(self):
        with self.assertRaises(ValueError):
            s.deposit_surface(profile(), sediment(porosity=F(1, 5)), properties(phase='mobile_sediment'), F(1, 4),
                              layer_id='bad-packing', evidence=EVIDENCE)

    def test_material_mass_gain_is_not_erosion_reconciliation(self):
        p = profile()
        with self.assertRaises(ValueError):
            s.reconcile_eroded_column(p, p.column.deposit(sediment()))

    def test_buried_removal_cannot_be_disguised_as_surface_erosion(self):
        p = profile()
        changed = replace(p.column, layers=(replace(p.column.layers[0], mass_kg=5000), p.column.layers[-1]))
        with self.assertRaises(ValueError):
            s.reconcile_eroded_column(p, changed)

    def test_geometry_frame_change_rejects(self):
        p = profile()
        for altered in (replace(p.column, area_m2=3), replace(p.column, basal_elevation_m=0)):
            with self.assertRaises(ValueError):
                s.reconcile_eroded_column(p, altered)

    def test_same_mass_repacking_or_identity_change_rejects(self):
        p = profile()
        for altered in (replace(p.column.layers[-1], porosity=F(1, 4)), replace(p.column.layers[-1], material_id='changed')):
            with self.assertRaises(ValueError):
                s.reconcile_eroded_column(p, replace(p.column, layers=(p.column.layers[0], altered)))

    def test_water_update_preserves_solid_geometry_and_exposes_signed_delta(self):
        p = profile()
        updated, receipt = s.replace_porewater(p, (F(3, 2), F(1, 2)), evidence='actual external Water ledger fixture')
        self.assertEqual(updated.column, p.column)
        self.assertEqual(receipt['net_water_change_m3'], [1, 5])
        depleted, receipt = s.replace_porewater(updated, (F(6, 5), F(3, 5)), evidence=EVIDENCE)
        self.assertEqual(depleted, p)
        self.assertEqual(receipt['net_water_change_m3'], [-1, 5])

    def test_water_update_never_clips_overcapacity(self):
        with self.assertRaises(ValueError):
            s.replace_porewater(profile(), (4, 1), evidence=EVIDENCE)

    def test_water_update_never_clips_subresidual_storage(self):
        with self.assertRaises(ValueError):
            s.replace_porewater(profile(), (0, 0), evidence=EVIDENCE)

    def test_unknown_or_conflicting_physical_inputs_reject(self):
        for status in ('UNKNOWN', 'CONFLICT', 'INCOMPLETE', 'Provisional'):
            with self.assertRaises(ValueError):
                properties(source_status=status)

    def test_wrong_material_phase_density_or_porosity_rejects_binding(self):
        p = profile()
        for changes in ({'material_id': 'other'}, {'phase': 'bedrock'}, {'grain_density_kg_m3': 2500}, {'porosity': F(1, 3)}):
            with self.assertRaises(ValueError):
                s.bind_column(p.column, (properties('parent'), properties(**changes)), ('a', 'b'),
                              (F(6, 5), F(3, 5)), profile_id='p', evidence=EVIDENCE)

    def test_duplicate_grain_density_for_material_identity_rejects(self):
        p = profile()
        altered = L.Layer('parent', 2000, 2500, F(1, 2), 'immobile_regolith', EVIDENCE)
        column = replace(p.column, layers=(p.column.layers[0], altered))
        with self.assertRaises(ValueError):
            s.bind_column(column, (properties('parent'), properties('parent', grain_density_kg_m3=2500)),
                          ('a', 'b'), (F(6, 5), F(1, 2)), profile_id='p', evidence=EVIDENCE)

    def test_invalid_physical_ranges_reject(self):
        cases = ({'porosity': 0}, {'porosity': 1}, {'theta_r': F(1, 2)}, {'theta_r': -1}, {'alpha_per_m': 0},
                 {'n': 1}, {'grain_density_kg_m3': 0}, {'ksat_vertical_m_s': -1}, {'effective_cohesion_pa': -1},
                 {'friction_angle_deg': 90})
        for changes in cases:
            with self.assertRaises(ValueError):
                properties(**changes)

    def test_bool_nonfinite_and_score_objects_are_not_parameters(self):
        for value in (True, float('inf'), float('nan'), {'score': .4}, '0.4'):
            with self.assertRaises(ValueError):
                properties(ksat_vertical_m_s=value)

    def test_zero_conductivity_is_preserved_as_physical_hypothesis(self):
        self.assertEqual(properties(ksat_vertical_m_s=0).ksat_vertical_m_s, 0)

    def test_negative_mualem_exponent_is_outside_admitted_water_regime(self):
        with self.assertRaises(ValueError):
            properties(mualem_l=-1)
        p = properties(mualem_l=0)
        self.assertEqual(s.MaterialHydraulics.from_dict(p.as_dict()), p)

    def test_exact_arithmetic_budget_rejects_before_physical_computation(self):
        with self.assertRaises(ValueError):
            properties(alpha_per_m=2 ** s.MAX_BITS)

    def test_inventory_lengths_and_mutability_reject(self):
        p = profile()
        for values in (([properties('parent'), properties()], ('a', 'b'), (F(6, 5), F(3, 5))),
                       ((properties('parent'),), ('a', 'b'), (F(6, 5), F(3, 5)))):
            with self.assertRaises(ValueError):
                s.bind_column(p.column, *values, profile_id='p', evidence=EVIDENCE)

    def test_layer_limit_is_explicit(self):
        with patch.object(s, 'MAX_LAYERS', 1):
            with self.assertRaises(ValueError):
                profile()

    def test_roundtrip_preserves_exact_packing_water_strength_and_ids(self):
        p = s.strip_surface(profile(), F(1000, 3)).profile
        restored = s.HydraulicProfile.from_dict(json.loads(json.dumps(p.as_dict())))
        self.assertEqual(restored, p)
        self.assertEqual(restored.as_dict(), p.as_dict())

    def test_profile_restore_rejects_owner_or_schema_drift(self):
        for key, value in (('owner_sha256', 'a' * 64), ('schema', 'legacy'), ('extra', True)):
            record = copy.deepcopy(profile().as_dict())
            record[key] = value
            with self.assertRaises(ValueError):
                s.HydraulicProfile.from_dict(record)

    def test_profile_restore_rejects_unknown_nested_material_fields(self):
        record = profile().as_dict()
        record['column']['layers'][0]['horizon'] = 'B'
        with self.assertRaises(ValueError):
            s.HydraulicProfile.from_dict(record)

    def test_profile_restore_revalidates_water_and_material_compatibility(self):
        for key, value in (('water_volume_m3', [100, 1]), ('water_volume_m3', [True, 1])):
            record = profile().as_dict()
            record['bindings'][0][key] = value
            with self.assertRaises(ValueError):
                s.HydraulicProfile.from_dict(record)
        record = profile().as_dict()
        record['bindings'][0]['properties']['porosity'] = [1, 4]
        with self.assertRaises(ValueError):
            s.HydraulicProfile.from_dict(record)

    def test_canon_inputs_never_promote_derived_profile_to_canon(self):
        p = profile()
        p = replace(p, column=replace(p.column, source_status='CANON'),
                    bindings=tuple(replace(b, properties=replace(b.properties, source_status='CANON')) for b in p.bindings))
        self.assertEqual(p.source_status, 'WORKING NON-CANON')
        self.assertEqual(s.hydraulic_rows(p)[0]['source_status'], 'WORKING NON-CANON')

    def test_derived_column_stock_status_cannot_remain_canon(self):
        p = profile()
        p = replace(p, column=replace(p.column, source_status='CANON'),
                    bindings=tuple(replace(b, properties=replace(b.properties, source_status='CANON')) for b in p.bindings))
        self.assertEqual(s.strip_surface(p, 100).profile.column.source_status, 'WORKING NON-CANON')
        updated, _ = s.replace_porewater(p, (F(6, 5), F(3, 5)), evidence=EVIDENCE)
        self.assertEqual(updated.column.source_status, 'WORKING NON-CANON')

    def test_owner_drift_fails_before_operation_without_modifying_source(self):
        p = profile()
        with patch.object(s, 'OWNER_SHA256', '0' * 64):
            with self.assertRaises(ValueError):
                s.hydraulic_rows(p)

    def test_predecessor_drift_fails_before_operation_without_source_write(self):
        p = profile()
        with patch.object(s, 'verify', side_effect=ValueError('source drift')):
            with self.assertRaises(ValueError):
                s.strip_surface(p, 100)

    def test_actual_predecessor_and_owner_hashes_are_preserved(self):
        s.verify_sources()
        self.assertEqual(hashlib.sha256(s.OWNER_PATH.read_bytes()).hexdigest(), s.OWNER_SHA256)
        self.assertEqual(hashlib.sha256(Path(L.__file__).read_bytes()).hexdigest(),
                         'fac564da0abd635ec3c7ad54ee06b4a09b807881367400b1eb6d1e52c2322c3b')


if __name__ == '__main__':
    unittest.main()
