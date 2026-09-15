"""Real pinned owner delivery plus adversarial and isolated arithmetic examples."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from . import biology as b

DELIVERY = Path(r'C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\02_Working_Files\Species_Coordination\Generator_R11_Inputs_2026-09-11')
MANIFEST_SHA = '7d91d7c46275581574092f5a3f11dbf0ddb7391a546864a59a9e4433f97ab5d4'


def actual_package():
    raw = (DELIVERY / 'DELIVERY_MANIFEST_R1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA:
        raise ValueError('test owner manifest changed')
    m = json.loads(raw)
    documents = {}
    for r in m['files']:
        raw = (DELIVERY / r['relative_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != r['sha256']:
            raise ValueError('test owner input changed: ' + r['relative_path'])
        if r['relative_path'].endswith('.json'):
            documents[r['relative_path']] = json.loads(raw)
    return {'manifest_sha256': MANIFEST_SHA, 'entry_sha256': m['entry_point']['sha256'],
        'source_bindings': {r['relative_path']: {'path': r['path'], 'sha256': r['sha256']} for r in m['files']},
        'documents': documents, 'scope': 'Pinned actual owner delivery, not test coefficients.'}


class BiologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = actual_package()
        cls.o = b.build_overlay(cls.p)

    def record(self, field, value, unit=None, oid='HS7'):
        schema = self.p['documents'][b.SCHEMA]
        r = b._record(schema, oid, 'isolated-validation-example:' + field, field, value,
            [b._bound_ref(self.p, b.CATALOGUE, '/field_catalog/' + field)],
            'ISOLATED VALIDATOR TEST: constructed value, never current delivered calibration or real output.')
        r['unit'] = unit
        return r

    def support(self, stage='ADULT', management='NATURAL', unit='m3'):
        return dict(support_id='declared-test-volume', native_measure_unit=unit, native_measure='100',
            scope_id='bounded-explicit-test', cohort_id='same-cohort', life_stage=stage,
            natural_or_managed=management, physical_scenario_id='test-geometry', calendar_id='explicit-test-calendar',
            source_evidence='ISOLATED TEST physical/native support; not a real Diadem habitat assignment.')

    def phases(self, a, z):
        return [dict(phase_id='first', start_seconds='0', duration_seconds='100', predicates=a,
                    evidence='ISOLATED TEST explicit condition, not threshold inferred from weather'),
                dict(phase_id='second', start_seconds='100', duration_seconds='100', predicates=z,
                    evidence='ISOLATED TEST explicit condition, not threshold inferred from weather')]

    def test_actual_delivery_exact_counts(self):
        self.assertEqual(len(self.o['identities']), 36)
        self.assertEqual(self.o['validation']['records'], 272)
        self.assertEqual(len(self.o['field_catalogue']), 35)
        self.assertEqual(sum(r['kind'] == 'PLANT' for r in self.o['identities']), 17)
        self.assertEqual(sum(':quantity:' in r['record_id'] for r in self.o['field_records']), 91)

    def test_every_source_row_is_retained_byte_equivalent_json(self):
        d = self.p['documents']
        for identity in self.o['identities']:
            oid = identity['organism_id']
            if identity['kind'] == 'PLANT':
                original = next(r for r in d[b.PLANTS]['plants'] if r['id'] == ('primary_sweet_rot_maw' if oid == 'HS4' else oid))
            else:
                original = next(r for r in d[b.PRIMARY]['records'] if r['organism_id'] == oid)
            self.assertEqual(identity['source_fact_record'], original)

    def test_no_new_selected_coefficients_or_population(self):
        self.assertFalse(any(r['model_use'] == 'SELECTED_FOR_R11' for r in self.o['field_records']))
        self.assertTrue(all(r['selection'] is None for r in self.o['permitted_unselected_scenarios']))
        self.assertTrue(all(r['quantitative_model_status'] == 'UNKNOWN' for r in self.o['identities']))
        hs1 = next(r for r in self.o['identities'] if r['organism_id'] == 'HS1')
        self.assertEqual(hs1['population_reference']['raw_owner_row']['working_total'], 24000)
        self.assertNotEqual(hs1['population_reference']['raw_owner_row']['physical_eligible_reference'], 24000)

    def test_override_does_not_rewrite_raw_predecessor(self):
        raw = next(r for r in self.o['identities'] if r['organism_id'] == 'HS4')['source_fact_record']
        self.assertEqual(raw['facts'][-1]['certainty'], 'CONFLICT_UNRESOLVED')
        effective = next(r for r in self.o['field_records'] if r['record_id'] == 'HS4:fact:8')
        self.assertEqual(effective['assertion_state'], 'UNKNOWN')
        self.assertIsNone(effective['value'])
        self.assertEqual(self.o['hs4']['effective_selection'], None)

    def test_cross_source_reference_does_not_inherit_wrong_source(self):
        r = next(r for r in self.o['field_records'] if r['record_id'] == 'HS4:fact:8')
        self.assertNotEqual(r['source_refs'][0]['sha256'], r['source_refs'][1]['sha256'])
        self.assertIn('P41', r['source_refs'][1]['locator'])

    def test_paragraph_conventions_are_not_collapsed(self):
        plant = next(r for r in self.o['field_records'] if r['record_id'] == 'HS4:fact:0')
        animal = next(r for r in self.o['field_records'] if r['record_id'] == 'HS1:recruitment')
        self.assertIn('direct', plant['source_refs'][0]['locator'])
        self.assertIn('including paragraphs in tables', animal['source_refs'][0]['locator'])

    def test_seedshot_raw_status_not_promoted(self):
        row = next(r for r in self.o['field_records'] if r['organism_id'] == 'bannerhaus_seedshot_lamp_reeds')
        self.assertIn('NON-CANON', row['source_refs'][0]['raw_source_status'])
        self.assertIsNone(row['kernel_status'])

    def test_phoenix_successor_and_scoped_approval_preserved(self):
        row = next(r for r in self.o['identities'] if r['organism_id'] == 'HS13')
        original = self.p['documents'][b.PRIMARY]['records'][11]
        self.assertEqual(row['source_fact_record'], original)
        refs = [s for r in self.o['field_records'] if r['organism_id'] == 'HS13' for s in r['source_refs']]
        self.assertTrue(any(s['sha256'] == '891e4d55b138fc43ce8bcf4342cf4dca45003528ccc3a8d0291238f07d4801dc' for s in refs))

    def test_special_branches_not_blanket_null(self):
        self.assertEqual(self.o['special']['HS19']['wild_organism_count'], 0)
        self.assertEqual(self.o['special']['HS19']['continuous_organism_count'], 1)
        self.assertIsNone(self.o['special']['HS14']['dated_register'])
        self.assertFalse(self.o['special']['HS19']['incorporated_persons_are_organisms'])

    def test_adult_nonmoving_does_not_become_propagule_claim(self):
        rows = [r for r in self.o['field_records'] if r['field_id'] == 'movement.mode']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['context']['life_stage'] == 'ADULT' and r['value'] == 'NONMOVING' for r in rows))

    def test_source_quantity_shape_and_literal_unit_preserved(self):
        quantities = [r for r in self.o['field_records'] if ':quantity:' in r['record_id']]
        self.assertTrue(any(r['value'].get('depth_origin') == 0 for r in quantities))
        self.assertTrue(any(r['value'].get('comparator') == 'often less than' for r in quantities))
        self.assertTrue(all(r['field_id'] == 'natural_history.observation' and r['context']['duration_s'] is None for r in quantities))

    def test_inputs_unchanged_and_deterministic(self):
        p = deepcopy(self.p)
        self.assertEqual(b.build_overlay(p), self.o)
        self.assertEqual(p, self.p)
        json.dumps(self.o, allow_nan=False)
        self.assertEqual(sum(len(r['record_ids']) for r in self.o['identities']), 272)

    def test_catalogue_or_identity_drift_rejected(self):
        for target in ('catalogue', 'identity', 'kind', 'roster'):
            p = deepcopy(self.p)
            if target == 'catalogue':
                p['documents'][b.CATALOGUE]['field_catalog'].pop('movement.mode')
            elif target == 'identity':
                p['documents'][b.ENTRY]['identity_records'][0]['organism_id'] = 'HS2'
            elif target == 'kind':
                p['documents'][b.ENTRY]['identity_records'][0]['kind'] = 'PLANT'
            else:
                p['documents']['contract_review/roster_readback.json'].pop('HS3')
            with self.assertRaises(ValueError):
                b.build_overlay(p)

    def test_schema_envelope_and_unknown_rules(self):
        r = self.record('habitat.requirements', {})
        for mutate in (lambda r: r.update(extra=1), lambda r: r.pop('context'),
                lambda r: r.update(assertion_state='UNKNOWN'), lambda r: r.update(value=float('nan'))):
            bad = deepcopy(r)
            mutate(bad)
            with self.assertRaises(ValueError):
                b.validate_records(self.p, [bad])
        r.update(assertion_state='UNKNOWN', value=None, model_use='WITHHELD',
            unresolved_owner='Species owner', required_action='Supply matched law')
        self.assertEqual(b.validate_records(self.p, [r])['records'], 1)

    def test_all_35_declared_field_ids_checked(self):
        for field in self.o['field_catalogue']:
            oid = 'HS4' if field.startswith('plant.') else 'HS1'
            if field == 'special.event_register':
                oid = 'HS14'
            elif field.startswith('special.'):
                oid = 'HS19'
            r = self.record(field, None, oid=oid)
            r.update(assertion_state='UNKNOWN', model_use='WITHHELD', unresolved_owner='Correct owner', required_action='Supply field')
            self.assertEqual(b.validate_records(self.p, [r])['records'], 1)

    def test_source_and_model_applicability_fail_closed(self):
        for r in (self.record('plant.pft_mapping', {}, oid='HS1'),
                  self.record('animal.seasonal_resource_refuge_response', {}, oid='HS4'),
                  self.record('special.wild_count', 0, 'wild organism identities', oid='HS14'),
                  self.record('movement.mode', 'MIGRATES_SOMETIMES')):
            with self.assertRaises(ValueError):
                b.validate_records(self.p, [r])
        r = self.record('habitat.requirements', {})
        for key, value in (('sha256', '0'*64), ('raw_source_status', 'SYNTHETIC TEST'), ('raw_source_status', 'CANON')):
            bad = deepcopy(r)
            bad['source_refs'][0][key] = value
            with self.assertRaises(ValueError):
                b.validate_records(self.p, [bad])
        with self.assertRaises(ValueError):
            b.validate_records(self.p, [r, r])

    def test_finite_quantity_fraction_and_native_unit_validation(self):
        for value, unit in ((True, '1'), (float('inf'), '1'), (-.1, '1'), (1.1, '1'), (.2, 'm2')):
            with self.assertRaises(ValueError):
                b.validate_records(self.p, [self.record('habitat.habitat_fraction', value, unit)])
        r = self.record('density.value', '2', 'animal/m3')
        r['context'].update(counting_unit='animal', native_measure_unit='m3')
        b.validate_records(self.p, [r])
        r['unit'] = 'animal/m2'
        with self.assertRaises(ValueError):
            b.validate_records(self.p, [r])

    def test_signed_occupancy_is_allowed_but_not_automatically_selected(self):
        r = self.record('occupancy.logit_slope', '-2', '1 per unit habitat_support')
        b.validate_records(self.p, [r])
        r.update(model_use='SELECTED_FOR_R11', kernel_status='WORKING NON-CANON', use_decision_ref=r['source_refs'][0])
        with self.assertRaisesRegex(ValueError, 'selection is not present'):
            b.validate_records(self.p, [r])

    def test_structured_law_not_a_numeric_compiler(self):
        r = self.record('plant.temperature_response', {'unsupported_law': 'invented'}, oid='HS4')
        b.validate_records(self.p, [r])  # readable constraint, not executable
        r.update(model_use='SELECTED_FOR_R11', kernel_status='WORKING NON-CANON', use_decision_ref=r['source_refs'][0])
        p = deepcopy(self.p)
        for key in r['context']:
            if key not in ('native_measure_unit', 'duration_s'):
                r['context'][key] = 'explicit-test'
        p['documents'][b.ENTRY]['compiler_ready_numeric_field_records'] = [r]
        with self.assertRaisesRegex(ValueError, 'structured biology'):
            b.validate_records(p, [r])

    def test_hs4_unselected_default_and_truth_table(self):
        self.assertEqual(b.hs4_host_access(self.o)['status'], 'PERMITTED_UNSELECTED')
        for a in (True, False, None):
            for z in (True, False, None):
                got = b.hs4_host_access(self.o, selection=b.PATHWAY, usable_connection=a,
                    sufficient_vascular_supply=z, evidence='ISOLATED TEST explicit host-fed pathway')
                want = False if False in (a, z) else (True if a is True and z is True else None)
                self.assertIs(got['host_access_prerequisite'], want)
                self.assertIsNone(got['whole_organism_persistence'])
                self.assertIsNone(got['host_free_viability'])

    def test_hs4_rejects_unselected_observation_and_false_numeric(self):
        for kw in ({'usable_connection': True}, {'selection': b.PATHWAY, 'usable_connection': 1},
                {'selection': b.PATHWAY, 'usable_connection': True}, {'selection': 'HOST_FREE_MORPH'}):
            with self.assertRaises(ValueError):
                b.hs4_host_access(self.o, **kw)

    def test_hs4_seasons_have_real_qualitative_change_not_biomass(self):
        got = b.compare_seasons(self.o, organism_id='HS4', support=self.support('NODES'),
            phases=self.phases({'wet_period': True, 'dry_period': False}, {'wet_period': False, 'dry_period': True}))
        self.assertTrue(got['categorical_response_changed'])
        self.assertEqual(got['applicable_rule_count'], 2)
        self.assertTrue(all(p['quantitative_productivity'] is None for p in got['phases']))

    def test_evergreen_is_not_equal_growth_and_cultivated_not_wild(self):
        got = b.compare_seasons(self.o, organism_id='bannerhaus_periwinkle_vine', support=self.support(),
            phases=self.phases({'winter': True}, {'winter': False}))
        self.assertIn('No obligatory winter dormancy', got['phases'][0]['categorical_responses'][0]['response'])
        for management, count in (('NATURAL', 0), ('MANAGED', 1)):
            got = b.compare_seasons(self.o, organism_id='bannerhaus_mistleholly_berries',
                support=self.support('MATURE_CROWN', management),
                phases=self.phases({'mature_cultivated_crown': True}, {'mature_cultivated_crown': True}))
            self.assertEqual(got['applicable_rule_count'], count)

    def test_animal_stage_specific_freeze_response(self):
        for stage, count in (('ADULT', 1), ('TADPOLE', 0)):
            got = b.compare_seasons(self.o, organism_id='HS12', support=self.support(stage),
                phases=self.phases({'hard_freeze': False}, {'hard_freeze': True}))
            self.assertEqual(got['applicable_rule_count'], count)
            self.assertIsNone(got['phases'][1]['quantitative_abundance'])

    def test_missing_predicate_unknown_not_zero(self):
        got = b.compare_seasons(self.o, organism_id='HS4', support=self.support('NODES'), phases=self.phases({}, {}))
        self.assertTrue(all(r['triggered'] is None for p in got['phases'] for r in p['categorical_responses']))
        self.assertIsNone(got['categorical_response_changed'])
        got = b.compare_seasons(self.o, organism_id='HS4', support=self.support('NODES'),
            phases=self.phases({}, {'wet_period': True}))
        self.assertIsNone(got['categorical_response_changed'])

    def test_unsupported_seasonal_rules_keep_facts(self):
        got = b.compare_seasons(self.o, organism_id='bannerhaus_red_wheat_grass', support=self.support(), phases=self.phases({}, {}))
        self.assertEqual(got['applicable_rule_count'], 0)
        self.assertTrue(got['source_fact_record']['facts'])
        self.assertIsNone(got['categorical_response_changed'])

    def test_seasonal_support_and_calendar_reject_bad_joins(self):
        for change in ('native', 'stage', 'duplicate', 'overlap', 'contradiction', 'nonboolean', 'special'):
            s = self.support('NODES')
            phases = self.phases({}, {})
            oid = 'HS4'
            if change == 'native': s['native_measure_unit'] = 'projected_km2'
            elif change == 'stage': s['life_stage'] = None
            elif change == 'duplicate': phases[1]['phase_id'] = 'first'
            elif change == 'overlap': phases[1]['start_seconds'] = '99'
            elif change == 'contradiction': phases[0]['predicates'] = {'wet_period': True, 'dry_period': True}
            elif change == 'nonboolean': phases[0]['predicates'] = {'wet_period': 1}
            else: oid = 'HS19'
            with self.assertRaises(ValueError):
                b.compare_seasons(self.o, organism_id=oid, support=s, phases=phases)

    def test_overlay_mutation_rejected(self):
        o = deepcopy(self.o)
        o['special']['HS19']['wild_organism_count'] = 50
        with self.assertRaises(ValueError):
            b.hs4_host_access(o)

    def density_fixture(self, unit='m3', basis='PER_OCCUPIED_MEASURE'):
        # Isolated FUTURE-DELIVERY schema fixture, never actual delivery or calibration.
        p = deepcopy(self.p)
        fields = [('density.value', '2', 'animal/' + unit)]
        if basis != 'PER_WHOLE_CELL_MEASURE': fields.append(('habitat.habitat_fraction', '1/2', '1'))
        if basis == 'PER_OCCUPIED_MEASURE': fields.append(('density.occupied_fraction', '1/4', '1'))
        rows = [self.record(f, v, u) for f, v, u in fields]
        for r in rows:
            r['context'] = {k: 'same-explicit-test' for k in r['context']}
            r['context'].update(counting_unit='animal', native_measure_unit=unit, duration_s='100', natural_or_managed='NATURAL')
            r.update(model_use='SELECTED_FOR_R11', kernel_status='WORKING NON-CANON', use_decision_ref=r['source_refs'][0])
        p['documents'][b.ENTRY]['compiler_ready_numeric_field_records'] = deepcopy(rows)
        s = dict(support_id='same-explicit-test', native_measure_unit=unit, native_measure='100', evidence='ISOLATED TEST geometry')
        return p, rows, s

    def test_native_linear_area_volume_arithmetic_no_projection(self):
        for unit in ('m', 'm2', 'm3'):
            for basis, expected in (('PER_WHOLE_CELL_MEASURE', '200'), ('PER_HABITAT_MEASURE', '100'), ('PER_OCCUPIED_MEASURE', '25')):
                p, rows, s = self.density_fixture(unit, basis)
                got = b.declared_native_density(p, rows, support=s, basis=basis)
                self.assertEqual(got['expected_entities'], expected)
                self.assertEqual(got['native_measure_unit'], unit)

    def test_actual_delivery_cannot_select_future_fixture(self):
        _, rows, s = self.density_fixture()
        with self.assertRaisesRegex(ValueError, 'selection is not present'):
            b.declared_native_density(self.p, rows, support=s, basis='PER_OCCUPIED_MEASURE')

    def test_native_joint_scenario_and_fraction_application(self):
        p, rows, s = self.density_fixture()
        rows[1]['context']['joint_scenario_id'] = 'independent-wrong-menu'
        p['documents'][b.ENTRY]['compiler_ready_numeric_field_records'] = deepcopy(rows)
        with self.assertRaisesRegex(ValueError, 'share exact joint'):
            b.declared_native_density(p, rows, support=s, basis='PER_OCCUPIED_MEASURE')
        p, rows, s = self.density_fixture()
        s['native_measure_unit'] = 'm2'
        with self.assertRaisesRegex(ValueError, 'native geometry differ'):
            b.declared_native_density(p, rows, support=s, basis='PER_OCCUPIED_MEASURE')
        with self.assertRaisesRegex(ValueError, 'conditional minimum'):
            b.declared_native_density(p, rows, support=s, basis='PER_WHOLE_CELL_MEASURE')


if __name__ == '__main__':
    unittest.main()
