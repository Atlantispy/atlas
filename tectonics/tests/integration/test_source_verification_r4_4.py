"""Execution context lifetime checks."""
import unittest

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.integration import reuse


class VerificationLifecycleTests(unittest.TestCase):
    def test_closed_context_rejects_and_close_is_idempotent(self):
        context = reuse.ExecutionContext()
        context.close()
        context.close()
        with self.assertRaises(TectonicsError):
            context.verify()


if __name__ == '__main__':
    unittest.main()
