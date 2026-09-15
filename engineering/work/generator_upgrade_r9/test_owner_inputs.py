"""Owner identity/status/source closure, without biological defaults or GIS runs."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest

from . import owner_inputs as o, sources


class OwnerInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pins=o.source_bindings()
        cls.roster=o.biological_roster()
        cls.ecology,cls.plants,cls.validation,cls.files=o._context()

    def test_all_owner_pins_live_and_combined_exact_bounded_union(self):
        self.assertEqual(len(self.pins),143)
        combined={r['path']:r['sha256'] for r in sources.source_bindings()}
        for r in self.pins:
            self.assertEqual(set(r),{'path','sha256','role'})
            self.assertTrue(Path(r['path']).is_absolute())
            self.assertEqual(hashlib.sha256(o._checked(r['path'],r['sha256'])).hexdigest(),r['sha256'])
            if r['path'] in combined:self.assertEqual(combined[r['path']],r['sha256'])
            combined[r['path']]=r['sha256']
        self.assertEqual(len(combined),256)

    def test_exact_stable36_and17plant_roster(self):
        expected={'HS'+str(i) for i in range(1,21)}|{'bannerhaus_'+i for i in o.PLANT_IDS}
        self.assertEqual(set(self.roster),expected)
        self.assertEqual(sum(r['kind']=='PLANT' for r in self.roster.values()),17)
        self.assertEqual(self.roster['HS3']['kind'],'ANIMAL')
        self.assertEqual(self.roster['HS4']['kind'],'PLANT')
        for ident,r in self.roster.items():
            self.assertEqual(r['organism_id'],ident)
            self.assertEqual(r['source_status'],'WORKING NON-CANON')
        self.assertIn('READY_FOR_BOUNDED_R9_INTEGRATION_WITH_EXPLICIT_UNKNOWNS',self.roster['HS1']['source_binding']['raw_status'])

    def test_every_primary_population_row_preserved_exactly(self):
        for row in self.files['ROSTER.json']['rows']:
            out=self.roster['HS'+str(row['hs'])]
            self.assertEqual(out['population_reference'],row)
            self.assertEqual(out['name'],row['species'])
            self.assertEqual(out['retained_hs'],row['hs'])
            for key,source in out['special_details']['population_source_references'].items():
                self.assertEqual(source,self.files['SOURCES.json']['sources'][key])

    def test_additional_plants_do_not_inherit_primary_population(self):
        for ident,r in self.roster.items():
            if ident.startswith('bannerhaus_'):
                self.assertIsNone(r['population_reference'])
                self.assertIsNone(r['retained_hs'])
                self.assertIsNone(r['special_details']['density'])
                self.assertIsNone(r['special_details']['movement_budget'])
        self.assertEqual(self.roster['HS4']['population_reference']['working_total'],875)

    def test_exact_names_from_retained_register_not_filename_guess(self):
        self.assertEqual(self.roster['bannerhaus_codex_blooms']['name'],'Codex-Blooms')
        self.assertEqual(self.roster['bannerhaus_mistchimes_nebelglockchen']['name'],'Mistchimes / Nebelglöckchen')
        self.assertEqual(self.roster['bannerhaus_sleep_s_voice_schlafstimme']['name'],"Sleep's Voice / Schlafstimme")

    def test_dossier_status_not_promoted_from_identity_est(self):
        seed=self.roster['bannerhaus_seedshot_lamp_reeds']
        self.assertIn('DRAFT/NON-CANON',seed['source_binding']['raw_status'])
        self.assertEqual(seed['special_details']['node_reference']['fields']['canon_state'],'EST')
        self.assertEqual(seed['source_status'],'WORKING NON-CANON')
        edge=seed['special_details']['terminal_edge_reference']['fields']
        self.assertEqual((edge['edge_type'],edge['edge_confidence']),('PD','STW'))

    def test_raw_plant_source_table_loci_and_hashes_preserved(self):
        pins={r['path']:r['sha256'] for r in self.pins}
        for ident,p in self.plants.items():
            self.assertEqual(self.roster[ident]['source_binding'],p)
            self.assertEqual(pins[p['path']],p['sha256'])
            self.assertIn('P',p['raw_status'])

    def test_hs4_count_identity_reproduction_host_uncertainty(self):
        r=self.roster['HS4'];d=r['special_details']
        self.assertEqual(d['adult_movement'],'NOT_APPLICABLE_ROOTED_SESSILE_ADULT')
        self.assertIn('non-additive',d['count_unit'])
        self.assertIn('UNKNOWN',d['universal_skyreach_host_gate'])
        self.assertIn('supersedes blanket TBD',d['reproduction'])
        self.assertEqual(d['primary_reference']['raw_status'],'PRIMARY_DOMAIN_SOURCE_STATUS_UNVERIFIED')
        self.assertEqual(d['primary_reference']['sha256'],o.PRIMARY_HS4_SHA256)

    def test_event_and_absent_wild_exceptions_not_density_defaults(self):
        kept=self.roster['HS14'];black=self.roster['HS19']
        self.assertEqual(kept['kind'],'OTHER');self.assertEqual(black['kind'],'OTHER')
        self.assertIsNone(kept['population_reference']['working_total'])
        self.assertEqual(kept['special_details']['habitat_generated_density'],'NOT_APPLICABLE')
        self.assertEqual(black['population_reference']['working_total'],1)
        self.assertEqual(black['special_details']['wild_population_count'],0)
        self.assertEqual(black['population_reference']['incorporated_embodiment_capable_human_identities'],50)
        self.assertEqual(black['special_details']['wild_migration'],'NOT_APPLICABLE')

    def test_annual_mean_and_all_stage_scopes_not_mobile_cohorts(self):
        self.assertIn('annual-mean',self.roster['HS9']['population_reference']['temporal_basis'])
        for hs in (9,15):self.assertIn('UNKNOWN',self.roster['HS'+str(hs)]['special_details']['mobile_cohort'])
        self.assertEqual(self.roster['HS15']['population_reference']['working_total'],120000)

    def test_latest_totals_and_limited_scope_not_replaced_by_old_centres(self):
        for hs,total in ((5,31340),(11,11800),(13,500),(20,140)):
            self.assertEqual(self.roster['HS'+str(hs)]['population_reference']['working_total'],total)
        self.assertIn('foreign',self.roster['HS13']['special_details']['spatial_presence'])
        self.assertIsNone(self.roster['HS17']['special_details']['whole_diadem_total'])
        self.assertEqual(self.roster['HS17']['population_reference']['working_total'],7600)

    def test_new_hs10_and_hs11_permissions_do_not_fill_numeric_gaps(self):
        self.assertIn('cave-to-river-valley',self.roster['HS10']['special_details']['seasonal_role'])
        note=self.roster['HS11']['special_details']['recruitment_contract']
        self.assertIn('permitted',note);self.assertIn('not every adult-use cell',note);self.assertIn('UNKNOWN',note)

    def test_no_universal_sessile_rule_for_wandering_mangrove(self):
        d=self.roster['bannerhaus_wandering_mangroves']['special_details']
        self.assertIn('stepping',d['qualitative_constraint_readback'])
        self.assertIsNone(d['movement_budget'])
        self.assertNotIn('adult_movement',d)

    def test_no_selected_parameter_menu_or_auto_density(self):
        for r in self.roster.values():
            d=r['special_details']
            self.assertIsNone(d['occupied_habitat_fraction'])
            self.assertIn('UNKNOWN',d['quantitative_spatial_rules_status'])
        self.assertNotIn('parameter_scenario',self.roster['HS1'])

    def test_curated_real_graph_and_bias_controls_bound_without_execution(self):
        paths={Path(r['path']).name:r for r in self.pins}
        self.assertIn('connectivity.py',paths)
        self.assertIn('not executed',paths['connectivity.py']['role'])
        self.assertIn('AUDIT ONLY',paths['BIAS_REVIEW_NOTICE.md']['role'])
        self.assertIn('human',paths['stage6d_rootreach_footprint.py']['role'])

    def test_provider_only_imports_stdlib(self):
        tree=ast.parse(Path(o.__file__).read_bytes())
        allowed={'copy','csv','hashlib','io','json','math','pathlib','re','stat'}
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):self.assertTrue(all(a.name in allowed for a in n.names))
            if isinstance(n,ast.ImportFrom):self.assertIn(n.module,allowed);self.assertEqual(n.level,0)

    def test_output_fresh_json_safe_and_bounded_individual_evidence(self):
        first=o.biological_roster();saved=copy.deepcopy(first)
        first['HS1']['population_reference']['working_total']=0
        self.assertEqual(o.biological_roster(),saved)
        json.dumps(saved,allow_nan=False,ensure_ascii=False)
        for r in saved.values():self.assertLess(len(r['evidence']+'; '+str(r['special_details'])),4096)

    def test_hash_drift_rejected_without_repin(self):
        with self.assertRaisesRegex(ValueError,'pin mismatch'):
            o._checked(o.POPULATION/'VALIDATION.json','0'*64)

    def test_duplicate_nonfinite_json_rejected(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}'):
            with self.assertRaises(ValueError):o._json(raw)

    def test_missing_or_unsafe_dossier_table_rejected(self):
        text=self.ecology['ROSTER_BIOLOGY_SOURCES.md']
        with self.assertRaises(ValueError):o._plant_table(text.replace('`aurblatt`;','`absent`;'))
        with self.assertRaises(ValueError):o._plant_table(text.replace('Peak (Ink Owl)\\Aurblatt.docx','..\\Aurblatt.docx'))
        with self.assertRaises(ValueError):o._plant_table(text.replace('Peak (Ink Owl)\\Aurblatt.docx','\\Aurblatt.docx'))
        with self.assertRaises(ValueError):o._plant_table('')


if __name__=='__main__':unittest.main()
