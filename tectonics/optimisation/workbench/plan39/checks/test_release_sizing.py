"""Release decision 5 sizing in start_gate: cap, gate, shipped-table refusal; strict values unchanged."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(os.environ.get('ATLAS_COMPOSITION', '.')) / 'helpers'))
import start_gate as G

GiB = 1 << 30
COMPOSITION = 'a' * 64
SEED0 = SimpleNamespace(hash_randomization=0)


def table(**routes):
    return {'schema': G.RELEASE_TABLE_SCHEMA, 'composition': COMPOSITION, 'routes': routes}


def entry(peak, mode='strict'):
    return {'peak_bytes': peak, 'record': 'stage-runner.json sha256=' + 'b' * 64, 'execution_mode': mode}


class ReleaseSizing(unittest.TestCase):
    def test_strict_values_unchanged(self):
        self.assertEqual((G.RSS_BYTES, G.FREE_BYTES, G.LOGICAL_BYTES, G.ALLOWANCE_BYTES),
                         (12 * GiB, GiB, 16 * GiB, GiB))
        self.assertEqual(G.gate_bytes(5 * GiB), 5 * GiB + GiB + GiB + GiB)

    def test_cap(self):
        self.assertEqual(G.release_cap_bytes(16 * GiB), 12 * GiB)          # 16 GiB machine: unchanged
        self.assertEqual(G.release_cap_bytes(15 * GiB + (700 << 20)), 12 * GiB)  # usable RAM of a 16 GiB machine
        self.assertEqual(G.release_cap_bytes(64 * GiB), 12 * GiB)          # never above today's 12 GiB
        self.assertEqual(G.release_cap_bytes(8 * GiB), 5 * GiB)
        for bad in (3 * GiB, 0, -1, 2.0 * GiB, True):
            with self.subTest(bad=bad), self.assertRaises(G.StartGateRefused):
                G.release_cap_bytes(bad)

    def test_gate_is_peak_times_1_2_plus_floor(self):
        self.assertEqual(G.release_gate_bytes(5), 5 + 1 + GiB)
        self.assertEqual(G.release_gate_bytes(10 * GiB), 12 * GiB + GiB)
        with self.assertRaises(G.StartGateRefused):
            G.release_gate_bytes(0)

    def test_decision_needs_an_authentic_shipped_entry(self):
        decision = G.release_decision('fresh-runner', COMPOSITION, table(**{'fresh-runner': entry(4 * GiB)}))
        self.assertEqual((decision['predicted_peak_bytes'], decision['gate_bytes']),
                         (4 * GiB, 4 * GiB + -(-4 * GiB // 5) + GiB))
        refusals = {
            'no entry': ('fresh-runner', COMPOSITION, table()),
            'other composition': ('fresh-runner', 'c' * 64, table(**{'fresh-runner': entry(GiB)})),
            'release-measured': ('fresh-runner', COMPOSITION, table(**{'fresh-runner': entry(GiB, 'release')})),
            'no record sha': ('fresh-runner', COMPOSITION, table(**{'fresh-runner': dict(entry(GiB), record='x')})),
            'extra field': ('fresh-runner', COMPOSITION, table(**{'fresh-runner': dict(entry(GiB), booking=1)})),
            'malformed table': ('fresh-runner', COMPOSITION, dict(table(), extra=1)),
            'bad composition': ('fresh-runner', 'A' * 64, table(**{'fresh-runner': entry(GiB)})),
        }
        for name, args in refusals.items():
            with self.subTest(name), self.assertRaises(G.StartGateRefused):
                G.release_decision(*args)

    def test_admit(self):
        decision = G.release_decision('fresh-runner', COMPOSITION, table(**{'fresh-runner': entry(4 * GiB)}))
        admitted = G.release_admit(decision, decision['gate_bytes'], 16 * GiB, SEED0)
        self.assertEqual(G.release_guard_limits(admitted),
                         {'rss_bytes': 12 * GiB, 'free_floor_bytes': GiB, 'start_available_bytes': decision['gate_bytes'],
                          'logical_budget_bytes': 16 * GiB})
        small = G.release_admit(decision, decision['gate_bytes'], 8 * GiB, SEED0)
        self.assertEqual(G.release_guard_limits(small)['rss_bytes'], 5 * GiB)
        with self.assertRaises(G.StartGateRefused):                         # below the gate
            G.release_admit(decision, decision['gate_bytes'] - 1, 16 * GiB, SEED0)
        big = G.release_decision('fresh-runner', COMPOSITION, table(**{'fresh-runner': entry(6 * GiB)}))
        with self.assertRaisesRegex(G.StartGateRefused, 'too small'):       # peak above this machine's cap
            G.release_admit(big, 64 * GiB, 8 * GiB, SEED0)
        with self.assertRaises(G.StartGateRefused):                         # random seed
            G.release_admit(decision, 64 * GiB, 16 * GiB, SimpleNamespace(hash_randomization=1))
        with self.assertRaises(G.StartGateRefused):                         # forged decision
            G.release_admit(dict(decision, gate_bytes=1), 64 * GiB, 16 * GiB, SEED0)
        with self.assertRaises(G.StartGateRefused):                         # strict decision is not a release one
            G.release_admit(G.decide({'stage': 'x'}, booking=(GiB, 'b')), 64 * GiB, 16 * GiB, SEED0)
        with self.assertRaises(G.StartGateRefused):
            G.release_guard_limits(dict(admitted, rss_cap_bytes=13 * GiB))


if __name__ == '__main__':
    unittest.main()
