"""The q08 proof's checks fail closed (coordinator, 16 Oct 13:10): synthetic reports only, no admission.

Run: python -B test_time_admission_checks.py
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import time_admission_parts as T  # noqa: E402

PIN = 'e337fc205071fc6754b47b18f1c990fbfaec2162ae55cc3a1210cdbc9872ce81'
PREP = {'collar': 'c', 'funding': 'f', 'map': 'm', 'native': 'n', 'owner': 'o', 'spatial_owner': 's'}
BINDS = {'owner_definition_holds_bounds_id': True, 'owner_definition_holds_mesh_geometry_id': True}


def report(**changes):
    base = dict(identity={'bounds.bounds_id': 'b', 'mesh.geometry_id': 'g', 'owner.owner_id': 's',
                          'reference.provenance': '{"execution_identity": "x"}'},
                workflow_id='w', preparation_ids=dict(PREP), measurement_store_sha256=PIN,
                seeded_store=None, store_unchanged_from_seed=None, store_sidecars=[], passed=True)
    base.update(changes)
    return base


def seeded(**changes):
    values = dict(seeded_store={'source': 'src', 'sha256': PIN}, store_unchanged_from_seed=True,
                  seed_source_sha256_after=PIN)
    values.update(changes)
    return report(**values)


RUN_A = {'workflow_id': 'w', 'published_root': {'inspect': {'workflow_id': 'w'}, 'preparation_ids': dict(PREP)}}


def failed(rep, binds=BINDS, **kwargs):
    return sorted(name for name, ok in T.evaluate(rep, binds, **kwargs).items() if ok is not True)


class FailClosed(unittest.TestCase):
    def test_full_hit_arm_passes(self):
        self.assertEqual(failed(seeded(), expect_store=PIN, other=report(), run_a=RUN_A), [])

    def test_key_missing_from_the_other_report_fails(self):
        other = report()
        del other['identity']['mesh.geometry_id']
        self.assertEqual(failed(seeded(), other=other), ['expect:mesh.geometry_id'])

    def test_key_missing_from_this_report_fails(self):
        mine = seeded()
        del mine['identity']['bounds.bounds_id']
        self.assertEqual(failed(mine, other=report()), ['expect:bounds.bounds_id'])

    def test_both_sides_missing_a_field_fails(self):
        self.assertIn('expect:workflow_id', failed(seeded(workflow_id=None), other=report(workflow_id=None)))

    def test_identity_mismatch_fails(self):
        other = report()
        other['identity']['bounds.bounds_id'] = 'other'
        self.assertEqual(failed(seeded(), other=other), ['expect:bounds.bounds_id'])

    def test_failed_miss_report_fails_the_hit_arm(self):
        self.assertEqual(failed(seeded(), other=report(passed=False)), ['expect:report_passed'])
        self.assertEqual(failed(seeded(), other={k: v for k, v in report().items() if k != 'passed'}),
                         ['expect:report_passed'])

    def test_sidecar_fails(self):
        self.assertEqual(failed(report(store_sidecars=['initial-measurements.sqlite-journal'])),
                         ['store:closed_no_sidecars'])

    def test_changed_store_or_seed_source_fails(self):
        self.assertEqual(failed(seeded(store_unchanged_from_seed=False)), ['store:unchanged_from_seed'])
        self.assertEqual(failed(seeded(seed_source_sha256_after='0'*64)), ['seed:source_unchanged'])
        self.assertEqual(failed(seeded(seed_source_sha256_after=None)), ['seed:source_unchanged'])

    def test_store_pin_mismatch_fails(self):
        self.assertEqual(failed(report(measurement_store_sha256='0'*64), expect_store=PIN),
                         ['store:sha256_equals_pin'])

    def test_run_a_disagreement_fails(self):
        self.assertEqual(failed(report(workflow_id='v'), run_a=RUN_A),
                         ['run_a:published_root_workflow_id', 'run_a:workflow_id'])
        other_prep = copy.deepcopy(RUN_A)
        other_prep['published_root']['preparation_ids']['spatial_owner'] = 't'
        self.assertEqual(failed(report(), run_a=other_prep), ['run_a:preparation_ids', 'run_a:spatial_owner'])
        self.assertEqual(len(failed(report(), run_a={'workflow_id': 'w'})), 3)

    def test_owner_binding_missing_fails(self):
        self.assertEqual(failed(report(), {}, run_a=RUN_A),
                         ['run_a:owner_definition_holds_bounds_id', 'run_a:owner_definition_holds_mesh_geometry_id'])

    def test_metrics_only_cannot_pass_run_a(self):
        self.assertIn('run_a:workflow_id', failed(report(workflow_id=None, preparation_ids=None), {}, run_a=RUN_A))


if __name__ == '__main__':
    unittest.main(verbosity=1)
