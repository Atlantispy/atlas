"""Focused actual owner selection and exact reference identities."""
import unittest
from work.generator_upgrade_r22 import population_inputs as p


class PopulationInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.result = p.load()

    def test_actual_totals_and_selected_specialist_counts(self):
        r=self.result
        self.assertEqual(len(r['haus_rows']),20)
        self.assertEqual(r['accounted_human_identities'],15964359)
        self.assertEqual((r['specialist_sites'],r['specialist_humans']),(77,234076))
        self.assertEqual(sum(x['count'] for x in r['assignments']),15964359)
        self.assertEqual(r['count_excluding_incorporated_reference'],15964309)
        self.assertEqual([x['count'] for x in r['assignments'] if x['routine_human_food_demand'] is False],[50])
        self.assertEqual(r['unresolved_service_class_count'],15051683)

    def test_aggregate_membership_identity_and_null_limits_survive(self):
        r=self.result; a={x['pool_id']:x for x in r['assignments']}
        self.assertEqual(a['STILL-CAPITAL']['count'],60000)
        self.assertEqual(len(a['STILL-CAPITAL']['source_site_ids']),2)
        self.assertFalse(a['STILL-CAPITAL']['split_counts_selected'])
        self.assertEqual(a['MARIENHAIN:OTHER_PRIMARY_AGGREGATE']['count'],108000)
        self.assertEqual(len(a['MARIENHAIN:OTHER_PRIMARY_AGGREGATE']['source_site_ids']),27)
        self.assertFalse(a['MARIENHAIN:OTHER_PRIMARY_AGGREGATE']['can_crosswalk_whole_scope'])
        self.assertEqual(sum(x['count'] for x in r['assignments'] if x['residence_kind']=='MOBILE_HOME_MEMBERSHIP_AGGREGATE'),450000)
        self.assertEqual(r['unresolved_base_query']['null_estimate_rows'],226)
        self.assertTrue(all(x['placement_status']=='UNKNOWN' and x['replacement_support_id'] is None for x in r['assignments']))
        selected=p.application(r,'d'*64,haus='Stillklinge')
        self.assertEqual(selected['population']['count'],698132)
        with self.assertRaisesRegex(ValueError,'aggregate/membership'):
            p.application(r,'d'*64,crosswalk={'BASE:Stillklinge':{}})


if __name__=='__main__': unittest.main()
