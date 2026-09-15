from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from diadem_contract.fault_harness import (
    CapabilityUnavailable,
    CorruptStageError,
    InjectedCancellation,
    TransactionalByteStore,
    make_fault_evidence,
    run_with_fallback,
    verify_or_rebuild,
)
from diadem_contract.validation import validate_document


class FaultHarnessTests(unittest.TestCase):
    def test_cancellation_preserves_last_commit_and_clean_resume_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = TransactionalByteStore(Path(temporary))
            original_digest = store.initialise(b"generation-zero")
            with self.assertRaises(InjectedCancellation):
                store.update(b"generation-one", cancel_after_stage=True)
            self.assertEqual(store.digest(), original_digest)
            store.discard_stage()
            expected = store.update(b"generation-one")
            self.assertEqual(store.digest(), expected)

    def test_corrupt_stage_never_replaces_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = TransactionalByteStore(Path(temporary))
            original_digest = store.initialise(b"known-good")
            with self.assertRaises(CorruptStageError):
                store.update(b"candidate", corrupt_stage=True)
            self.assertEqual(store.digest(), original_digest)

    def test_corrupt_cache_rebuilds_from_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authority = root / "authority.bin"
            cache = root / "cache.bin"
            authority.write_bytes(b"authoritative")
            cache.write_bytes(b"corrupt")
            self.assertTrue(verify_or_rebuild(cache, authority))
            self.assertEqual(cache.read_bytes(), authority.read_bytes())
            self.assertFalse(verify_or_rebuild(cache, authority))

    def test_capability_failure_selects_reference_fallback(self):
        def optimised():
            raise CapabilityUnavailable("GPU backend unavailable")

        payload, report = run_with_fallback(optimised, lambda: b"reference-result")
        self.assertEqual(payload, b"reference-result")
        self.assertTrue(report["selected"])
        self.assertTrue(report["reason_recorded"])
        self.assertTrue(report["telemetry_recorded"])

    def test_fault_evidence_records_validate(self):
        for name, document in make_fault_evidence().items():
            result = validate_document(document)
            self.assertTrue(result.passed, (name, result.as_dict()))


if __name__ == "__main__":
    unittest.main()
