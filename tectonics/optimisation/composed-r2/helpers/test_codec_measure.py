"""Bounded WP10 measurement contracts; fixtures cannot enable production."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import codec_measure as M


class FakeStore:
    limits = SimpleNamespace(chunk_bytes=65536, codec_workspace_bytes=8 << 20)
    compression = ('raw', True)

    def __init__(self):
        self.encodes = self.decodes = 0

    def _encode(self, raw, dt):
        self.encodes += 1
        return 'raw', raw

    def _decode(self, label, payload, dt, count):
        self.decodes += 1
        return payload

    def _blob_id(self, descriptor, raw):
        return sha256(b'atlas-typed-chunk-v1\0' + descriptor + b'\0' + raw).hexdigest()


def raw_encode(store, raw, dt, rule):
    return 'raw', raw


def raw_decode(store, label, payload, dt, count):
    return payload


def bound(raw_bytes, dt, rule):
    return 65536 + raw_bytes * 4


class MeasurementTests(unittest.TestCase):
    def sample(self, source_kind='synthetic'):
        return M.CodecSample('csr_offsets', '<u8', np.arange(128, dtype='<u8').tobytes(),
                             'explicit local fixture', source_kind)

    def measure(self, **kwargs):
        return M.measure_class(FakeStore(), [self.sample()], repeats=1, warmups=0,
            candidates=[M.CodecCandidate('candidate', {'codec': 'raw', 'enabled': True})],
            encode_candidate=raw_encode, decode_candidate=raw_decode,
            workspace_bound=bound, **kwargs)

    def evidence(self):
        return dict(matched_real_run_provenance='matched local owner run',
            class_read_path_seconds=10., added_decode_seconds=.5,
            cold_raw_bytes=100_000_000, cold_encoded_bytes=50_000_000,
            baseline_total_seconds=20., candidate_total_seconds=19.,
            baseline_persistence_seconds=5., candidate_persistence_seconds=3.,
            hot_reads=2, cold_reads=5)

    def eligible_report(self):
        report = self.measure()
        report['source_kind'] = 'real'
        report['candidates'][0]['encoded_over_raw'] = .8
        return report

    def test_native_uses_exact_store_methods_and_no_writes(self):
        store = FakeStore()
        result = M.measure_class(store, [self.sample()], [M.CodecCandidate('native')], repeats=3, warmups=1)
        self.assertEqual((store.encodes, store.decodes), (4, 4))
        row = result['candidates'][0]
        self.assertTrue(row['exact_raw_and_chunk_identity'])
        self.assertEqual(row['encoded_over_raw'], 1.)
        self.assertIsNone(row['persistence_seconds'])
        self.assertIsNone(row['workspace_bound_bytes'])
        self.assertIsNone(result['read_frequency']['hot_reads'])
        self.assertEqual(store.compression, ('raw', True))

    def test_candidate_records_observed_frequency_without_inference(self):
        result = self.measure(read_frequency={'hot_reads': 0, 'cold_reads': 7, 'observation': 'measured fixture'})
        self.assertEqual(result['read_frequency']['cold_reads'], 7)
        self.assertEqual(result['candidates'][0]['workspace_bound_bytes'], 69632)
        self.assertEqual(result['candidates'][0]['workspace_status'], 'VERIFIED_BOUND')

    def test_bad_roundtrip_is_refused_before_reporting_success(self):
        with self.assertRaisesRegex(M.MeasurementRefused, 'decoded raw'):
            M.measure_class(FakeStore(), [self.sample()], [M.CodecCandidate('bad', {'codec': 'raw'})],
                repeats=1, warmups=0, encode_candidate=raw_encode,
                decode_candidate=lambda *args: b'corrupt', workspace_bound=bound)

    def test_candidate_workspace_limit_is_not_relaxed(self):
        with self.assertRaisesRegex(M.MeasurementRefused, 'workspace limit'):
            M.measure_class(FakeStore(), [self.sample()], [M.CodecCandidate('bad', {'codec': 'raw'})],
                repeats=1, warmups=0, encode_candidate=raw_encode, decode_candidate=raw_decode,
                workspace_bound=lambda *args: (8 << 20) + 1)

    def test_all_declared_families_are_covered_with_aligned_bounded_samples(self):
        samples = M.synthetic_samples()
        self.assertEqual(tuple(s.array_class for s in samples), M.ARRAY_CLASSES)
        self.assertTrue(all(len(s.raw) == 65536 and s.source_kind == 'synthetic' for s in samples))
        self.assertGreater(len(set(next(s.raw for s in samples if s.array_class == 'integer_magnitudes'))), 240)

    def test_manifest_only_sample_plan_reads_no_payload(self):
        descriptor = dict(array_name='support.lookup', array_class='sorted_lookup',
                          dtype='<u8', shape=[20000], source_ref={'ref': 'caller-authenticated-fixture'})
        result = M.sampling_manifest([descriptor])
        self.assertEqual(result['payload_reads'], 0)
        self.assertEqual(result['arrays'][0]['proposed_chunk_indices'], [0, 1, 2])
        self.assertNotIn('sorted_lookup', result['missing_classes'])
        self.assertEqual(len(result['missing_classes']), len(M.ARRAY_CLASSES)-1)
        self.assertFalse(result['enabled'])

    def test_explicit_alternate_backend_evidence_is_retained_but_never_enables(self):
        capability = {'zstd': {'status': 'AVAILABLE', 'provenance': 'reviewed alternative fixture backend'}}
        result = M.measure_class(FakeStore(), [self.sample()],
            [M.CodecCandidate('alternate', {'codec': 'zstd', 'enabled': True})], repeats=1, warmups=0,
            encode_candidate=raw_encode, decode_candidate=raw_decode, workspace_bound=bound,
            backend_capabilities=capability)
        row = result['candidates'][0]
        self.assertEqual(row['backend_capability_evidence'], capability['zstd'])
        self.assertEqual(row['codec_capability_status'], 'AVAILABLE')
        self.assertFalse(row['enabled'])

    def test_bounds_and_mixed_classes_refuse(self):
        for raw in (b'', b'a' * 65537, b'123'):
            with self.assertRaises(M.MeasurementRefused):
                M.CodecSample('csr_offsets', '<u8', raw, 'fixture')
        with self.assertRaisesRegex(M.MeasurementRefused, 'one class'):
            M.measure_class(FakeStore(), M.synthetic_samples(1024)[:2], [M.CodecCandidate('raw')])
        with self.assertRaises(M.MeasurementRefused):
            M.measure_class(FakeStore(), [self.sample()], [M.CodecCandidate('raw')], repeats=10)

    def test_synthetic_even_with_complete_gate_values_never_adopts(self):
        result = self.measure()
        result['candidates'][0]['encoded_over_raw'] = .2
        decision = M.assess_adoption(result, 'candidate', self.evidence())
        self.assertEqual(decision['status'], 'INCOMPLETE')
        self.assertIn('representative real class samples', decision['missing_evidence'])
        self.assertFalse(decision['enabled'])

    def test_complete_real_gate_is_review_only_and_thresholds_are_inclusive(self):
        report, evidence = self.eligible_report(), self.evidence()
        evidence['cold_raw_bytes'] = (1 << 30)
        evidence['cold_encoded_bytes'] = evidence['cold_raw_bytes'] - .01 * M.STORE_BYTES
        decision = M.assess_adoption(report, 'candidate', evidence)
        self.assertEqual(decision['status'], 'READY_FOR_OWNER_REVIEW')
        self.assertFalse(decision['enabled'])
        self.assertFalse(decision['policy_written'])

    def test_each_actual_benefit_gate_can_disable(self):
        base_report, base_evidence = self.eligible_report(), self.evidence()
        mutations = [('ratio', .80001), ('added_decode_seconds', .50001),
                     ('cold_encoded_bytes', 99_000_000), ('candidate_total_seconds', 20.)]
        for field, value in mutations:
            report, evidence = deepcopy(base_report), deepcopy(base_evidence)
            if field == 'ratio':
                report['candidates'][0]['encoded_over_raw'] = value
            else:
                evidence[field] = value
            with self.subTest(field=field):
                decision = M.assess_adoption(report, 'candidate', evidence)
                self.assertEqual(decision['status'], 'TESTED_DISABLED')
                self.assertFalse(decision['enabled'])

    def test_missing_persistence_is_not_invented(self):
        evidence = self.evidence()
        del evidence['candidate_persistence_seconds']
        decision = M.assess_adoption(self.eligible_report(), 'candidate', evidence)
        self.assertEqual(decision['status'], 'INCOMPLETE')
        self.assertIn('candidate_persistence_seconds', decision['missing_evidence'])

    def test_native_workspace_gap_blocks_new_zstd_even_with_raw_fallback(self):
        report = M.measure_class(FakeStore(), [self.sample()],
            [M.CodecCandidate('zstd', {'codec': 'zstd', 'enabled': True})], repeats=1, warmups=0,
            encode_candidate=raw_encode, decode_candidate=raw_decode, workspace_bound=bound)
        self.assertEqual(report['candidates'][0]['effective_labels'], ['raw'])
        decision = M.assess_adoption(report, 'zstd', self.evidence())
        self.assertEqual(decision['status'], 'BLOCKED')
        self.assertIn('workspace', decision['capability_gaps'][0])

    def test_missing_optional_package_is_reported_not_installed(self):
        with patch.object(M.importlib, 'import_module', side_effect=ImportError('fixture absent')):
            report = M.capability_report()
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertFalse(report['enabled'])

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'measurement.json'
            M._write_new(path, {'enabled': False})
            with self.assertRaises(FileExistsError):
                M._write_new(path, {'enabled': True})
            self.assertEqual(json.loads(path.read_text()), {'enabled': False})

    def tradeoff_fixture(self):
        # Contract-only invented evidence; never saved as production policy.
        from codec_tradeoff import TRADEOFF_ID
        report, evidence = self.eligible_report(), self.evidence()
        report['candidates'][0]['requested_rule'] = dict(codec='delta-zstd-v1', level=1, shuffle='byte')
        evidence.update(tradeoff_id=TRADEOFF_ID, comparator_codec='zstd', comparator_level=1,
            comparator_shuffle='byte', comparator_physical_bytes=100_000_000,
            candidate_physical_bytes=80_000_000, report_sha256='d'*64,
            baseline_total_seconds=80., candidate_total_seconds=87.)
        return report, evidence

    def test_accepted_tradeoff_boundary_is_review_only_and_agrees_with_policy(self):
        from codec_tradeoff import TRADEOFF_FIELDS, TRADEOFF_ID
        from storage_codec_runtime import normalise_policy
        report, evidence = self.tradeoff_fixture()
        decision = M.assess_adoption(report, 'candidate', evidence)
        self.assertEqual(decision['status'], 'READY_FOR_OWNER_REVIEW')
        self.assertEqual(decision['accepted_time_tradeoff'], TRADEOFF_ID)
        self.assertFalse(decision['enabled'] or decision['policy_written'])
        policy_evidence = {key: evidence[key] for key in TRADEOFF_FIELDS}
        policy_evidence.update(scope='real', report_sha256=evidence['report_sha256'],
            compression_ratio=.8, added_decode_fraction=.05, cold_saving_bytes=50_000_000,
            baseline_total_seconds=80., candidate_total_seconds=87.)
        key = 'atlas.private.heat-ledger.logical.v1/int.offset'
        policy = normalise_policy(dict(schema='atlas.codec-policy.v1',
            default=dict(codec='raw', enabled=False), arrays={key:dict(
                codec='delta-zstd-v1', enabled=True, level=1, shuffle='byte', evidence=policy_evidence)},
            parallel_workers=1, prefetch=False))
        self.assertEqual(dict(policy.for_array(key).evidence)['tradeoff_id'], TRADEOFF_ID)

    def test_tradeoff_refuses_worse_time_or_physical_saving(self):
        for key, value in (('candidate_total_seconds', 87.000001),
                           ('candidate_physical_bytes', 80_000_001)):
            report, evidence = self.tradeoff_fixture()
            evidence[key] = value
            with self.subTest(key=key):
                self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'TESTED_DISABLED')

    def test_tradeoff_requires_exact_comparator_profile_and_complete_report_binding(self):
        for key, value in (('tradeoff_id', 'unapproved'), ('comparator_codec', 'raw'),
                           ('comparator_level', 3), ('comparator_shuffle', 'bit'),
                           ('comparator_physical_bytes', True), ('report_sha256', 'bad')):
            report, evidence = self.tradeoff_fixture()
            evidence[key] = value
            with self.subTest(key=key):
                self.assertNotEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'READY_FOR_OWNER_REVIEW')
        for key in ('tradeoff_id', 'comparator_physical_bytes', 'report_sha256'):
            report, evidence = self.tradeoff_fixture()
            del evidence[key]
            self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'INCOMPLETE')
        for rule in (dict(codec='zstd', level=1, shuffle='byte'),
                     dict(codec='delta-zstd-v1', level=3, shuffle='byte'),
                     dict(codec='delta-zstd-v1', level=1, shuffle='bit')):
            report, evidence = self.tradeoff_fixture()
            report['candidates'][0]['requested_rule'] = rule
            self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'TESTED_DISABLED')

    def test_tradeoff_never_promotes_synthetic_or_missing_run_evidence(self):
        report, evidence = self.tradeoff_fixture()
        report['source_kind'] = 'synthetic'
        evidence['scope'] = 'real'  # Cannot override the actual measurement kind.
        self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'INCOMPLETE')
        for key in ('matched_real_run_provenance', 'candidate_persistence_seconds', 'cold_reads'):
            report, evidence = self.tradeoff_fixture()
            del evidence[key]
            self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'INCOMPLETE')

    def test_tradeoff_keeps_other_benefit_and_workspace_gates(self):
        for key, value in (('added_decode_seconds', .50001), ('cold_encoded_bytes', 99_000_000)):
            report, evidence = self.tradeoff_fixture()
            evidence[key] = value
            self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'TESTED_DISABLED')
        report, evidence = self.tradeoff_fixture()
        report['candidates'][0]['encoded_over_raw'] = .80001
        self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'TESTED_DISABLED')
        report, evidence = self.tradeoff_fixture()
        report['candidates'][0]['workspace_status'] = 'INCOMPLETE'
        self.assertEqual(M.assess_adoption(report, 'candidate', evidence)['status'], 'INCOMPLETE')


if __name__ == '__main__':
    unittest.main()
