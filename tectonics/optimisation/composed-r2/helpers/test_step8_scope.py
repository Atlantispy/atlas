"""Run-scope closure preserves failure evidence and paid escaped owners."""
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'compact-geometry-r1'),
               str(HERE.parent/'runtime-integration-r1/runtime-src')]
from atlas_tectonics.resources import WorkBudget
from content_cache import ChargeSpec
import run_prepared_restart as RUN


class ScopeLifetime(unittest.TestCase):
    def test_normal_close_records_zero(self):
        budget, record = WorkBudget(1 << 30), {}
        with RUN.retained_run(budget, record) as scope:
            with scope.reserve(ChargeSpec('fixture', 32)) as reservation:
                owned = reservation.commit(b'x'*32)
            owned.close()
        self.assertGreater(record['compact_retained_before_close']['retained_bytes'], 0)
        self.assertEqual(record['compact_retained_after_close']['retained_bytes'], 0)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_live_failure_owner_stays_paid_and_original_error_survives(self):
        budget, record = WorkBudget(1 << 30), {}
        error = ValueError('original work failed')
        with self.assertRaises(ValueError) as caught:
            with RUN.retained_run(budget, record) as scope:
                with scope.reserve(ChargeSpec('fixture', 32)) as reservation:
                    owned = reservation.commit(b'x'*32)
                raise error
        self.assertIs(caught.exception, error)
        self.assertIn('Retained scope finalisation also failed', error.__notes__[0])
        self.assertNotIn('compact_retained_after_close', record)
        self.assertGreater(budget.reserved_bytes, 0)
        owned.close()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
