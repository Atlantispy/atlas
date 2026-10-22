"""One parser-boundary control; no queue, process, guard or scientific dispatch."""
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('plan17_duplicate_keys_tested', HERE / 'admission_r3.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class DuplicateKeys(unittest.TestCase):
    def test_duplicate_members_refuse_before_admission(self):
        cases = {
            'hold_cannot_be_hidden': b'{"hold":"usage reset","hold":false,"tickets":[]}',
            'nested_prediction_cannot_be_replaced':
                b'{"tickets":[{"pred_peak_gib":1.30,"pred_peak_gib":1.20}]}',
            'history_peak_cannot_be_replaced':
                b'{"source-command":[{"tracker":"job","peak":1.30,"peak":0.01}]}',
            'history_tracker_cannot_be_replaced':
                b'{"source-command":[{"tracker":"children","tracker":"job","peak":1.20}]}',
            'escaped_member_alias_cannot_hide_hold': b'{"hold":"usage reset","ho\\u006cd":false}',
            'deep_nested_object_is_checked': b'{"outer":[{"inner":{"peak":2,"peak":1}}]}',
        }
        with patch.object(M, 'admit_snapshot') as admission:
            for label, raw in cases.items():
                with self.subTest(case=label), self.assertRaisesRegex(ValueError, 'duplicate JSON member'):
                    decoded = M.read_json(raw)
                    admission(decoded)  # Reached only if the parser failed to refuse.
            admission.assert_not_called()
        valid = M.read_json(b'{"hold":false,"nested":{"peak":1.2000000000000000000000000001}}')
        self.assertIs(valid['hold'], False)
        self.assertEqual(valid['nested']['peak'], Decimal('1.2000000000000000000000000001'))
        with self.assertRaisesRegex(ValueError, 'non-finite JSON'):
            M.read_json(b'{"nested":{"peak":NaN}}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
