"""Policy and actual-current-runtime checks; historical approval is synthetic.

These tests do not approve any production build or checkpoint. They exercise
the independently reviewed-policy boundary, including actual native transfers.
"""
from copy import deepcopy
import gc
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import runtime_compatibility as R
import native_transfer as N
from workflow_transfer import HistoricalEndpointAdmission


def policy(old, new):
    return dict(schema=R.SCHEMA, constraints=deepcopy(R.CONSTRAINTS),
        historical=dict(source_hashes=old, native_source_digest=sha256(R.canonical(old)).hexdigest(),
            source_manifest_path='old.json', source_manifest_sha256='c'*64, execution_identity='a'*64),
        current=dict(source_hashes=new, native_source_digest=sha256(R.canonical(new)).hexdigest(),
            source_manifest_path='new.json', source_manifest_sha256='d'*64, execution_identity='b'*64),
        reviewed_changes={name: dict(before=old.get(name), after=new.get(name),
            reason='explicit synthetic fixture change review', evidence=['checks.json'])
            for name in set(old)|set(new) if old.get(name) != new.get(name)},
        evidence={'checks.json': 'e'*64})


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.old = {'atlas_tectonics/a.py': 'a'*64, 'atlas_tectonics/removed.py': 'b'*64}
        self.new = {'atlas_tectonics/a.py': 'c'*64, 'atlas_tectonics/added.py': 'd'*64}
        self.policy = policy(self.old, self.new)

    def test_complete_delta(self):
        R.check_policy(self.policy, historical=self.old, current=self.new)

    def test_omitted_added_removed_or_changed_file(self):
        for name in self.policy['reviewed_changes']:
            changed = deepcopy(self.policy)
            del changed['reviewed_changes'][name]
            with self.subTest(name=name), self.assertRaises(R.RuntimeCompatibilityRefused):
                R.check_policy(changed, historical=self.old, current=self.new)

    def test_weakened_contract(self):
        for name in R.CONSTRAINTS:
            changed = deepcopy(self.policy)
            changed['constraints'][name] = 'weakened'
            with self.subTest(name=name), self.assertRaises(R.RuntimeCompatibilityRefused):
                R.check_policy(changed, historical=self.old, current=self.new)

    def test_unknown_field_and_unbound_evidence(self):
        for mutate in (lambda x: x.update(automatic_approval=True),
                lambda x: x['evidence'].clear(),
                lambda x: x['reviewed_changes']['atlas_tectonics/a.py'].update(evidence=['unbound']),
                lambda x: x['reviewed_changes']['atlas_tectonics/a.py'].update(before='f'*64),
                lambda x: x['current'].update(native_source_digest='f'*64),
                lambda x: x['current'].update(execution_identity='not an identity')):
            changed = deepcopy(self.policy)
            mutate(changed)
            with self.subTest(change=changed), self.assertRaises(R.RuntimeCompatibilityRefused):
                R.check_policy(changed, historical=self.old, current=self.new)

    def test_changed_membership_or_bytes(self):
        with self.assertRaises(R.RuntimeCompatibilityRefused):
            R.check_policy(self.policy, historical=self.old, current={**self.new, 'foreign.py': 'f'*64})
        with self.assertRaises(R.RuntimeCompatibilityRefused):
            R.check_policy(self.policy, historical={**self.old, 'atlas_tectonics/a.py': 'f'*64}, current=self.new)

    def test_path_escape(self):
        with tempfile.TemporaryDirectory(prefix='compat-path-', dir=Path(__file__).parent) as directory:
            for relative in ('../bad', 'C:/bad', 'bad\\path', ''):
                with self.subTest(relative=relative), self.assertRaises(R.RuntimeCompatibilityRefused):
                    R._path(directory, relative)


class ActualAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_native_transfer as T
        cls.T = T
        T.setUpModule()
        T.NativeTransferTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.T.NativeTransferTests.tearDownClass()
        cls.T.tearDownModule()

    def test_actual_current_native_binding_and_refusals(self):
        fixture = self.T.NativeTransferTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory(prefix='compat-evidence-', dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            with N.admit_migrated_native_collar(**fixture.arguments) as lease:
                owned = lease.adopt()
            original = self.T.BASE.parent
            current = Path(self.T._temporary.name)
            old_sources, new_sources = R.source_inventory(original), R.source_inventory(current)
            review = policy(old_sources, new_sources)
            review['current']['execution_identity'] = fixture.native._context.identity
            for filename, record in (('old.json', old_sources), ('new.json', new_sources),
                                      ('checks.json', {'synthetic_fixture_review': True})):
                (root/filename).write_bytes(R.canonical(record))
            for side, filename in (('historical', 'old.json'), ('current', 'new.json')):
                review[side]['source_manifest_sha256'] = R.file_hash(root/filename)
            review['evidence']['checks.json'] = R.file_hash(root/'checks.json')
            (root/'review.json').write_bytes(R.canonical(review))
            capsule = {'producer': {key: review['historical'][key] for key in
                        ('execution_identity', 'native_source_digest', 'source_manifest_sha256')}}
            historical = object.__new__(HistoricalEndpointAdmission)
            object.__setattr__(historical, '_record', R.canonical(capsule))
            object.__setattr__(historical, '_binding', R.canonical({'capsule_sha256': sha256(R.canonical(capsule)).hexdigest()}))
            object.__setattr__(historical, '_source_audit', None)
            arguments = dict(policy_path=root/'review.json', policy_sha256=R.file_hash(root/'review.json'),
                evidence_root=root, historical_source_root=original, current_source_root=current,
                historical_admission=historical, native_transfer=owned, execution=fixture.native._context,
                budget=fixture.budget)
            before = fixture.budget.reserved_bytes
            admission = R.admit(**arguments)
            self.assertFalse(admission.record()['historical_acceptance_reissued'])
            self.assertEqual(admission.record()['current_execution_identity'], fixture.native._context.identity)
            self.assertEqual(fixture.budget.reserved_bytes-before, len(admission._record)+4096)
            self.assertEqual(fixture.budget.statistics()['categories'].get('runtime-compatibility-scratch', 0), 0)
            del admission
            gc.collect()
            self.assertEqual(fixture.budget.reserved_bytes, before)
            # A truthful source policy does not permit changed runtime binaries,
            # mode or callable state: the actual execution identity is pinned.
            altered = deepcopy(review)
            altered['current']['execution_identity'] = 'f'*64
            (root/'bad-review.json').write_bytes(R.canonical(altered))
            with self.assertRaisesRegex(R.RuntimeCompatibilityRefused, 'actual strict'):
                R.admit(**dict(arguments, policy_path=root/'bad-review.json', policy_sha256=R.file_hash(root/'bad-review.json')))
            # Evidence bytes changed after review, without altering the policy.
            (root/'checks.json').write_bytes(b'changed')
            with self.assertRaisesRegex(R.RuntimeCompatibilityRefused, 'review evidence changed'):
                R.admit(**arguments)
            self.assertEqual(fixture.budget.reserved_bytes, before)
            del owned, historical, arguments
        fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
