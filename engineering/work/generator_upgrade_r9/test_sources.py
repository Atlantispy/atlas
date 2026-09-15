"""Exact retained reference closure, without historical producer execution."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
from . import sources as s


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt=s.verify_sources();cls.roster=s.retained_roster()

    def test_all_code_control_sources_match_expected_pins(self):
        self.assertEqual(self.receipt['source_count'],193)
        self.assertEqual(len({r['path'] for r in self.receipt['sources']}),193)
        self.assertFalse(self.receipt['production_executed'])
        self.assertFalse(self.receipt['large_rasters_archives_rehashed'])
        self.assertFalse(self.receipt['historical_package_approval_revalidated'])

    def test_exact_twenty_unique_case_identities(self):
        rows=self.roster['organisms']
        self.assertEqual([r['hs'] for r in rows],list(range(1,21)))
        self.assertEqual(len({r['species'] for r in rows}),20)
        self.assertEqual(rows[10]['species'],'Zweiflügel-Monarchen')
        self.assertEqual(rows[14]['species'],'Serenafächer')

    def test_all_actual_producers_have_scientific_derive_entrypoint(self):
        for row in self.roster['organisms']:
            pin=row['producer']['builder'];tree=ast.parse(s._checked(pin['path'],pin['sha256']))
            self.assertIn('derive',{n.name for n in tree.body if isinstance(n,ast.FunctionDef)})

    def test_hs14_is_nonbiological_event_not_an_ordinary_niche(self):
        row=self.roster['organisms'][13]
        self.assertEqual(row['required_natural_lifecycle_core'],{'operator':'not_applicable','components':[]})
        self.assertFalse(row['semantics']['retained_statements']['biological_species'])
        self.assertIsNone(row['semantics']['retained_statements']['occurrence_generation_raster'])
        self.assertIn('EVENT_DRIVEN',row['exception'])

    def test_hs19_absent_wild_population_preserves_counterfactual(self):
        row=self.roster['organisms'][18]
        self.assertIn('CANONICALLY_ABSENT',row['semantics']['retained_statements']['wild_population'])
        self.assertEqual(row['components']['counterfactual_fragment']['role'],'counterfactual')
        self.assertNotIn(19,self.roster['ordinary_headline_core_hs'])
        self.assertNotIn(14,self.roster['ordinary_headline_core_hs'])
        self.assertEqual(len(self.roster['ordinary_headline_core_hs']),18)

    def test_sessile_adult_and_missing_dispersal_not_lost(self):
        sem=self.roster['organisms'][3]['semantics']['retained_statements']['semantics']
        self.assertEqual(sem['adult_movement'],'NOT_APPLICABLE_ROOTED_SESSILE_ADULT')
        self.assertIn('WITHHELD',sem['seed_pollen_and_juvenile_dispersal'])

    def test_invariant_skripteule_movement_not_fabricated_families(self):
        row=self.roster['organisms'][1]
        self.assertEqual(len(set(row['components']['movement']['bands'].values())),1)
        self.assertIn('invariant',row['semantics']['retained_statements']['movement_semantics'])
        self.assertIn('excluded',row['semantics']['retained_statements']['present_day_breeding_definition'])

    def test_all_selected_component_references_exist_without_flattening_alternatives(self):
        def check(node,components):
            if set(node)=={'component'}:self.assertIn(node['component'],components)
            else:
                self.assertIn(node['operator'],('minimum','maximum','not_applicable'))
                for child in node['components']:check(child,components)
        for row in self.roster['organisms']:check(row['required_natural_lifecycle_core'],row['components'])
        self.assertEqual(self.roster['organisms'][2]['required_natural_lifecycle_core']['components'][0]['operator'],'maximum')

    def test_no_full_roster_density_or_approval_claim(self):
        self.assertFalse(self.roster['complete_plant_or_R9_roster_established'])
        self.assertFalse(self.roster['new_biological_parameters_supplied'])
        for row in self.roster['organisms']:
            self.assertFalse(row['package_approval_revalidated']);self.assertFalse(row['large_raster_reverified'])
            self.assertEqual(row['package_manifest']['declared_status'],'PASS_FOR_VISUAL_REVIEW_NOT_CANON')

    def test_source_inventory_is_small_control_metadata_not_maps(self):
        for row in self.receipt['sources']:
            self.assertIn(Path(row['path']).suffix.lower(),('.py','.json','.md','.txt','.docx'))
            self.assertLessEqual(Path(row['path']).stat().st_size,s.MAX_SOURCE_BYTES)
            self.assertTrue(row['role'])

    def test_api_returns_fresh_roster_and_strict_json(self):
        modified=s.retained_roster();modified['organisms'][0]['species']='mutated'
        self.assertEqual(s.retained_roster(),self.roster)
        json.loads(json.dumps(self.roster,ensure_ascii=False,allow_nan=False))

    def test_separately_declared_requirements_are_pinned_not_silently_omitted(self):
        for hs in (3,4,5,7,13,15,17,18,20):
            row=self.roster['organisms'][hs-1]
            self.assertTrue(any('requirements' in p['path'].lower() for p in row['declared_contract_bindings']))
        bindings={r['path']:r['sha256'] for r in self.receipt['sources']}
        for row in self.roster['organisms']:
            for pin in row['declared_contract_bindings']:self.assertEqual(bindings[pin['path']],pin['sha256'])

    def test_changed_source_pin_fails_without_repin(self):
        with self.assertRaisesRegex(ValueError,'pin mismatch'):s._checked(s.REGISTRY,'0'*64)

    def test_duplicate_nonfinite_json_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}',b'{"a":Infinity}'):
            with self.assertRaises(ValueError):s._json(raw)

    def test_unsafe_member_and_nonabsolute_source_rejected(self):
        for value in ('../escape','/root','C:/absolute','a/../escape','a//b','a\\b','./a',''):
            with self.assertRaises(ValueError):s._relative(value)
        with self.assertRaises(ValueError):s._checked('relative.json','0'*64)

    def test_valid_source_size_and_hash_have_no_write_side_effect(self):
        pin=self.receipt['sources'][0];path=Path(pin['path']);before=path.stat()
        raw=s._checked(path,pin['sha256'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),pin['sha256'])
        self.assertEqual(path.stat().st_mtime_ns,before.st_mtime_ns)


if __name__=='__main__':unittest.main()
