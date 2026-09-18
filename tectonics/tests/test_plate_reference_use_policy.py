"""R1 source-use tests: no retuned generator, edited source or waived strict test.

Full originals are required offline. Tests distinguish numerical correctness,
source representation, observation selection and subsequent model validation.
Unknown findings fail closed; all original test cases remain separate/unchanged.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics.plate_reference import AREA_ROWS
from atlas_tectonics.plate_reference_acceptance import (
    OBSERVATION_SCALES_M, WITHHELD_MORPHOLOGY_PLATES,
    read_report_snapshot, reference_protocol,
)
from atlas_tectonics.plate_reference_dataset import (
    ReferenceDataError, PB2002_FILES, verify_source_bytes,
)
from atlas_tectonics.plate_reference_use import (
    prepare_reference_use, reference_use_policy, _validate_reviewed_report,
)
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'reference_data/pb2002'


class ReviewedReferenceUses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = prepare_reference_use(DATA)
        cls.policy = reference_use_policy()

    def observations(self, **changes):
        args = dict(metric='compactness', split='development', run_id='r1-use-test',
                    scale_m=100000., phase=0.)
        args.update(changes)
        return self.plan.observations(**args)

    def compare(self, values=(0.3, 0.6), **changes):
        args = dict(candidate_id='1'*64, candidate_count=2, unresolved_candidate=0,
                    metric='compactness', split='development', run_id='r1-use-test',
                    reference_scale_m=100000., candidate_scale_m=100000.,
                    reference_phase=0., candidate_phase=0.)
        args.update(changes)
        return self.plan.compare(values, **args)

    def test_scoped_acceptance_does_not_accept_strict_consistency_or_geology(self):
        s = self.plan.summary()
        self.assertEqual(s['status'], 'ACCEPTED_FOR_SCOPED_REFERENCE_USE')
        self.assertEqual(s['strict_status'], 'REFERENCE_DISCREPANCIES_REQUIRE_REVIEW')
        self.assertFalse(s['strict_reference_gate_passed'])
        self.assertFalse(s['geological_model_accepted'])
        self.assertFalse(s['r2_started'])

    def test_raw_pins_protocol_and_original_scientific_case_remain_valid(self):
        for name, _, n in PB2002_FILES:
            raw = (DATA/name).read_bytes()
            self.assertEqual(len(raw), n)
            self.assertEqual(verify_source_bytes(name, raw), dict(self.plan._dataset.raw_sha256)[name])
        original = json.loads((ROOT/'cases/plate_reference_r1.json').read_text())
        self.assertEqual(original['protocol'], reference_protocol())
        self.assertEqual(self.plan.strict_report()['protocol'], reference_protocol())

    def test_reviewed_scope_has_explicit_coverage(self):
        c = self.plan.summary()['coverage']
        self.assertEqual(c['ordinary_surface_morphology_eligible'], 51)
        self.assertEqual(c['closed_orogen_metrics_eligible'], 12)
        self.assertEqual(c['table_area_records'], 52)
        self.assertEqual(c['source_motion_rows'], 5819)
        self.assertEqual(c['surface_neighbour_count_eligible'], 43)
        self.assertEqual(c['withheld_morphology_eligible'], 10)

    def test_original_report_is_not_rewritten_by_qualification(self):
        old = json.loads((ROOT/'evidence/3cr1-complete-reference-checks.json').read_text())
        self.assertEqual(self.plan.strict_report(), old)
        self.assertEqual(len(old['connectivity']['incidence_discrepancies']), 5)
        self.assertEqual(len(old['numerical_issues']), 1)

    def test_on_table_transcription_matches_reviewed_publication(self):
        self.assertEqual(dict(AREA_ROWS)['ON'], 0.00802)
        self.assertEqual(self.policy['sources'][0]['facts']['area_steradians'], '0.00802')
        self.assertEqual(self.policy['decisions'][0]['cause'], 'NOT_ESTABLISHED')
        with self.assertRaises(ReferenceDataError):
            self.plan.require_use('table_outline_equivalence', plate_id='ON')
        self.plan.require_use('table_outline_equivalence', plate_id='AF')

    def test_on_table_and_outline_observations_stay_distinct(self):
        args = dict(metric='area_fraction', split='development', run_id='area-origin')
        table = self.plan.observations(**args, area_basis='published_table')
        outline = self.plan.observations(**args, area_basis='source_outline')
        i = table['plate_ids'].index('ON')
        self.assertEqual(table['values'][i], 0.00802/(4*math.pi))
        self.assertNotEqual(table['values'][i], outline['values'][i])
        self.assertEqual(table['included_count'], 52)
        self.assertEqual(outline['included_count'], 52)
        self.assertNotEqual(sum(table['values']), 1.)  # No renormalisation to fit closure.
        self.assertEqual(table['excluded'], [])

    def test_area_requires_explicit_origin_and_cannot_be_withheld_validation(self):
        for split, basis in [('development', None), ('withheld', 'published_table'),
                             ('withheld', 'source_outline'), ('development', 'average')]:
            with self.subTest(split=split, basis=basis), self.assertRaises(ReferenceDataError):
                self.plan.observations(metric='area_fraction', split=split,
                    run_id='area-test', area_basis=basis)

    def test_ms_simple_ring_shape_refused_but_original_diagnostic_retained(self):
        with self.assertRaises(ReferenceDataError):
            self.plan.require_use('ordinary_surface_morphology', plate_id='MS')
        row = next(p for p in self.plan.strict_report()['plates'] if p['plate_id']=='MS')
        value = row['multiscale']['scales'][0]['phases'][0]['sampled_compactness']
        self.assertGreater(value, 1.)  # Do not clip the raw evidence to hide the failure.
        self.assertEqual(self.plan.raw_curve('plate', 43).name, 'MS')

    def test_ms_exclusion_applies_to_every_scale_phase_and_shape_metric(self):
        for metric in ('compactness', 'reflex_turning_radians', 'boundary_length_radians'):
            for scale in OBSERVATION_SCALES_M:
                for phase in (0., .5):
                    with self.subTest(metric=metric, scale=scale, phase=phase):
                        result = self.observations(metric=metric, scale_m=scale, phase=phase)
                        self.assertNotIn('MS', result['plate_ids'])
                        self.assertEqual([x['plate_id'] for x in result['excluded']], ['MS'])
                        self.assertEqual(result['expected_population_count'], 42)

    def test_fixed_heldout_population_is_not_reselected(self):
        result = self.observations(split='withheld')
        self.assertEqual(result['plate_ids'], sorted(WITHHELD_MORPHOLOGY_PLATES))
        self.assertEqual(result['expected_population_count'], 10)
        self.assertEqual(result['excluded'], [])
        self.assertEqual(result['audit']['purpose'], 'validation')

    def test_scale_unresolved_records_are_disclosed_not_scored_as_zero(self):
        result = self.observations(split='withheld', scale_m=500000.)
        self.assertIn('MN', [r['plate_id'] for r in result['unresolved']])
        self.assertNotIn('MN', result['plate_ids'])
        self.assertEqual(result['included_count']+len(result['excluded'])+len(result['unresolved']), 10)
        self.assertGreater(min(result['values']), 0.)

    def test_peru_open_curve_retained_without_polygon_metric(self):
        source = self.plan.raw_curve('orogen', 11)
        self.assertFalse(source.explicitly_closed)
        self.assertEqual(source.count, 49)
        self.assertFalse(np.array_equal(source.coordinates[0], source.coordinates[-1]))
        with self.assertRaises(ReferenceDataError):
            self.plan.orogen_metrics(11)
        s = self.plan.orogen_metrics(1)
        self.assertIsInstance(s['metrics'], dict)
        self.assertEqual(s['role'], 'WITHHELD_WITHIN_MODEL')
        self.assertFalse(s['complete_global_mask'])

    def test_unavailable_global_uses_fail_instead_of_implied_full_coverage(self):
        for use in self.policy['restrictions']['unavailable_global_uses']:
            with self.subTest(use=use), self.assertRaises(ReferenceDataError):
                self.plan.require_use(use)

    def test_all_five_discrepant_surface_edges_refused_both_directions(self):
        for item in self.policy['connectivity_decisions']:
            a,b = np.array(item['finding']['edge'], dtype=float)
            for start,end in ((a,b),(b,a)):
                with self.subTest(edge=item['finding']['edge']), self.assertRaises(ReferenceDataError):
                    self.plan.require_surface_edge(start,end)

    def test_unaffected_source_edge_remains_available_in_both_directions(self):
        a,b = self.plan.raw_curve('boundary',1).coordinates[:2]
        self.plan.require_surface_edge(a,b)
        self.plan.require_surface_edge(b,a)

    def test_unknown_and_nearby_edges_are_not_snapped(self):
        a,b = self.plan.raw_curve('boundary',1).coordinates[:2]
        altered = a.copy(); altered[0] += 1e-8
        for start,end in [(altered,b), ([0,0],[1,1]), ([0,91],[0,90])]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                self.plan.require_surface_edge(start,end)

    def test_endpoint_shape_and_types_are_refused_before_conversion(self):
        invalid = (np.empty(100000), [False, 0.], ['0', '1'],
                   np.ma.array([0., 1.], mask=[True, False]))
        for start in invalid:
            with self.subTest(kind=type(start).__name__):
                with mock.patch('atlas_tectonics.plate_reference_use.np.asarray',
                                side_effect=AssertionError('converted invalid endpoint')):
                    with self.assertRaises(ValueError):
                        self.plan.require_surface_edge(start, [0., 1.])

    def test_edge_lookup_uses_prepared_keys_not_a_full_dataset_walk(self):
        a,b = self.plan.raw_curve('boundary',1).coordinates[:2]
        with mock.patch('atlas_tectonics.plate_reference_use._edge_key', wraps=__import__(
                'atlas_tectonics.plate_reference_use', fromlist=['_edge_key'])._edge_key) as key:
            self.plan.require_surface_edge(a,b)
            self.assertEqual(key.call_count, 1)

    def test_neighbour_counts_disclose_all_conservatively_affected_owners(self):
        result = self.plan.observations(metric='neighbour_count', split='source-verification', run_id='neighbours')
        self.assertEqual(result['included_count'],43)
        self.assertEqual(sorted(x['plate_id'] for x in result['excluded']),
                         self.policy['restrictions']['surface_neighbour_count_excluded'])
        self.assertTrue(all(float(v).is_integer() for v in result['values']))

    def test_original_motion_rows_and_flags_are_labelled_as_source_not_dynamics(self):
        for number in (1,5819):
            result = self.plan.source_step(number)
            source = self.plan._dataset.steps[number-1]
            self.assertEqual(result['source_boundary'], source.boundary)
            self.assertEqual(result['source_class'], source.kind)
            self.assertEqual(result['source_in_orogen'], source.in_orogen)
            self.assertFalse(result['source_flag_recomputed'])
            self.assertIn('NOT_UNIQUE_SURFACE_EDGE', result['use'])
            self.assertIn('evidence_role', result)

    def test_bad_use_record_and_selector_types_are_refused(self):
        actions = [lambda: self.plan.require_use('invented'),
                   lambda: self.plan.require_use('ordinary_surface_morphology',plate_id='XX'),
                   lambda: self.plan.require_use('ordinary_surface_morphology',plate_id='AF',orogen_record=1),
                   lambda: self.plan.require_use('source_diagnostics',plate_id='AF'),
                   lambda: self.plan.orogen_metrics(True), lambda: self.plan.orogen_metrics(14),
                   lambda: self.plan.raw_curve('boundary',True), lambda: self.plan.raw_curve('plate',53),
                   lambda: self.plan.source_step(0),lambda: self.plan.source_step(True)]
        for fn in actions:
            with self.assertRaises(ReferenceDataError): fn()

    def test_explicit_scale_phase_split_and_run_identity_are_required(self):
        for changes in [dict(scale_m=None),dict(scale_m=100.),dict(phase=None),dict(phase=False),
                        dict(scale_m='100000'),dict(split='validation'),dict(run_id=''),
                        dict(metric='unknown'),dict(area_basis='source_outline')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.observations(**changes)

    def test_qualified_comparison_has_identified_coverage_not_a_realism_pass(self):
        result = self.compare()
        self.assertEqual(result['reference_use_policy_id'], self.plan.policy_id)
        self.assertEqual(result['qualified_reference']['expected_population_count'],42)
        self.assertEqual(result['qualified_reference']['excluded'][0]['plate_id'],'MS')
        self.assertEqual(result['candidate_population_count'],2)
        self.assertFalse(result['geological_model_accepted'])
        self.assertEqual(len(result['qualified_comparison_id']),64)

    def test_candidate_scale_and_phase_must_match_without_boolean_aliases(self):
        for change in [dict(candidate_scale_m=500000.),dict(candidate_phase=.5),dict(candidate_phase=False)]:
            with self.subTest(change=change),self.assertRaises(ReferenceDataError):
                self.compare(**change)

    def test_candidate_population_missing_values_cannot_disappear(self):
        for change in [dict(candidate_count=3),dict(candidate_count=True),dict(unresolved_candidate=-1)]:
            with self.subTest(change=change),self.assertRaises(ReferenceDataError):
                self.compare(**change)
        result=self.compare(candidate_count=3,unresolved_candidate=1)
        self.assertEqual(result['candidate_population_count'],3)
        self.assertEqual(result['unresolved_candidate'],1)

    def test_invalid_candidate_values_are_refused(self):
        for values in ([np.nan,.2],[np.inf,.2],[-.1,.2],[1.1,.2]):
            with self.subTest(values=values),self.assertRaises(ValueError): self.compare(values)
        with self.assertRaises(ReferenceDataError):
            self.plan.compare([2.5],candidate_id='1'*64,candidate_count=1,unresolved_candidate=0,
                metric='neighbour_count',split='development',run_id='bad-neighbours')
        with self.assertRaises(ReferenceDataError):
            self.plan.compare([1.1],candidate_id='1'*64,candidate_count=1,unresolved_candidate=0,
                metric='area_fraction',split='development',run_id='bad-area',area_basis='published_table')

    def test_source_verification_is_not_a_candidate_comparison_split(self):
        with self.assertRaises(ReferenceDataError): self.compare(split='source-verification')

    def test_policy_phase_and_area_origin_bind_qualified_identity(self):
        first=self.compare()
        other=self.compare(reference_phase=.5,candidate_phase=.5)
        self.assertNotEqual(first['qualified_comparison_id'],other['qualified_comparison_id'])
        self.assertEqual(self.compare()['qualified_comparison_id'],first['qualified_comparison_id'])

    def test_detached_results_cannot_mutate_plan_or_policy(self):
        summary=self.plan.summary(); summary['restrictions']['ordinary_surface_morphology_excluded'].clear()
        result=self.observations(); result['plate_ids'].clear()
        report=self.plan.strict_report(); report['status']='PASS_COMPLETE_REFERENCE_CHECKS'
        policy=reference_use_policy(); policy['rules']['r2_started']=True
        self.assertEqual(self.plan.summary()['restrictions']['ordinary_surface_morphology_excluded'],['MS'])
        self.assertGreater(len(self.observations()['plate_ids']),0)
        self.assertEqual(self.plan.strict_report()['status'],'REFERENCE_DISCREPANCIES_REQUIRE_REVIEW')
        self.assertFalse(reference_use_policy()['rules']['r2_started'])
        with self.assertRaises(FrozenInstanceError): self.plan.policy_id='x'
        with self.assertRaises(TypeError): self.plan._plate_rows['AF']='x'

    def test_concurrent_readers_share_immutable_prepared_setup(self):
        with mock.patch('atlas_tectonics.plate_reference_use.reference_dataset_report',side_effect=AssertionError('recomputed')):
            with ThreadPoolExecutor(max_workers=3) as executor:
                values=list(executor.map(lambda _:self.observations(),range(6)))
        self.assertTrue(all(v==values[0] for v in values))

    def test_source_arrays_remain_immutable(self):
        a=self.plan.raw_curve('plate',43).coordinates
        with self.assertRaises(ValueError): a[0,0]=0
        with self.assertRaises(ValueError): a.setflags(write=True)

    def test_changed_or_missing_source_refused_before_scoped_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy=Path(tmp)/'data';shutil.copytree(DATA,copy)
            p=copy/'original/PB2002_steps.dat.txt'; p.write_bytes(p.read_bytes()+b'\n')
            with mock.patch('atlas_tectonics.plate_reference_use.reference_dataset_report',side_effect=AssertionError('bad source reached report')):
                with self.assertRaises(ReferenceDataError): prepare_reference_use(copy)

    def test_changed_policy_bytes_are_not_runtime_exemptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'policy.json';p.write_text('{}\n')
            with mock.patch('atlas_tectonics.plate_reference_use._POLICY_PATH',p):
                with self.assertRaises(ReferenceDataError): reference_use_policy()

    def test_unknown_incidence_finding_requires_new_review(self):
        report=self.plan.strict_report()
        report['connectivity']['incidence_discrepancies'][0]['boundary_uses']=1
        with self.assertRaises(ReferenceDataError): _validate_reviewed_report(report,self.policy)

    def test_motion_or_numerical_failure_is_not_covered_by_source_policy(self):
        for part in ('motion','area'):
            report=self.plan.strict_report()
            if part=='motion':report['motion']['issues']=[{'step':100}]
            else: report['plates'][0]['metrics']['area_formula_disagreement_sr']=.1
            with self.subTest(part=part),self.assertRaises(ReferenceDataError):
                _validate_reviewed_report(report,self.policy)

    def test_new_table_mismatch_or_resolved_on_discrepancy_requires_review(self):
        for pid in ('AF','ON'):
            report=self.plan.strict_report()
            row=next(x for x in report['plates'] if x['plate_id']==pid)
            row['area_difference_sr']=0. if pid=='ON' else .1
            with self.subTest(pid=pid),self.assertRaises(ReferenceDataError):
                _validate_reviewed_report(report,self.policy)

    def test_coverage_protocol_and_unknown_unresolved_changes_fail_closed(self):
        for kind in ('coverage','protocol','unresolved'):
            report=self.plan.strict_report()
            if kind=='coverage':report['measurement_coverage']['plates_measured']=51
            elif kind=='protocol':report['protocol']['scales_m']=[1.]
            else:report['source_geometry']['unresolved'].append({'source_id':'plate:1:AF'})
            with self.subTest(kind=kind),self.assertRaises(ReferenceDataError):
                _validate_reviewed_report(report,self.policy)

    def test_nonphysical_shape_outside_ms_quarantine_is_refused(self):
        report=self.plan.strict_report()
        report['plates'][0]['multiscale']['scales'][0]['phases'][0]['sampled_compactness']=2.
        with self.assertRaises(ReferenceDataError): _validate_reviewed_report(report,self.policy)

    def test_only_a_complete_registered_scale_report_can_be_qualified(self):
        report=self.plan.strict_report()
        report['plates'][0]['multiscale']['scales'].pop()
        with self.assertRaises(ReferenceDataError): _validate_reviewed_report(report,self.policy)

    def test_budget_refusals_release_shared_reservations(self):
        for maximum in (1,20<<20):
            budget=WorkBudget(maximum)
            with self.assertRaises(MemoryLimitError): prepare_reference_use(DATA,budget=budget)
            self.assertEqual(budget.reserved_bytes,0)
        budget=WorkBudget(1)
        with self.assertRaises(MemoryLimitError):self.observations(budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_cancellation_prevents_admission_and_partial_output(self):
        event=threading.Event();event.set();budget=WorkBudget(128<<20)
        with self.assertRaises(CancelledError):prepare_reference_use(DATA,budget=budget,cancel=event)
        with self.assertRaises(CancelledError):self.observations(budget=budget,cancel=event)
        with self.assertRaises(CancelledError):self.compare(budget=budget,cancel=event)
        self.assertEqual(budget.reserved_bytes,0)

    def test_complete_strict_report_survives_zstd_dedup_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.db';backup=Path(tmp)/'backup.db'
            with ArrayStore(path,StoreLimits(4096,1<<20,8<<20)) as store:
                receipt=self.plan.save_strict_report(store)
                count=store.statistics()['unique_chunks']
                self.assertEqual(self.plan.save_strict_report(store),receipt)
                self.assertEqual(store.statistics()['unique_chunks'],count)
                self.assertEqual(receipt['reference_use_policy_id'],self.plan.policy_id)
                store.backup_to(backup)
            path.unlink()
            with ArrayStore(backup,StoreLimits(4096,1<<20,8<<20)) as store:
                report=read_report_snapshot(store,receipt['strict_report_key'])
                self.assertEqual(report,self.plan.strict_report())
                _validate_reviewed_report(report,reference_use_policy())

    def test_offline_scoped_cli_is_distinct_from_unchanged_strict_failure(self):
        command=[sys.executable,'-I','-B',str(ROOT/'tools/prepare_plate_reference.py'),
                 '--verify-only','--data',str(DATA)]
        scoped=subprocess.run(command+['--assess-use'],capture_output=True,text=True,timeout=45)
        self.assertEqual(scoped.returncode,0,scoped.stderr)
        self.assertEqual(json.loads(scoped.stdout),self.plan.summary())
        strict=subprocess.run(command,capture_output=True,text=True,timeout=45)
        self.assertEqual(strict.returncode,1,strict.stderr)
        self.assertEqual(json.loads(strict.stdout),self.plan.strict_report())

    def test_missing_data_cli_does_not_emit_scoped_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/prepare_plate_reference.py'),
                '--verify-only','--data',tmp,'--assess-use'],capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,2)
            self.assertEqual(p.stdout,'')
            error=json.loads(p.stderr)
            self.assertEqual(error['status'],'BLOCKED_REFERENCE_ACCEPTANCE')
            self.assertFalse(error['geological_model_accepted'])


if __name__=='__main__':unittest.main()
