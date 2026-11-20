"""Unit B (identity batch, issue 107 carry-over from 75): the reader refuses the identity override when the producer it
would reuse ran in proof mode (--open-proofs, recorded as the receipt's `open_proofs`). Other reuse is unchanged.
  python -B -I test_reuse_override_proof_r1.py <package parent folder>"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, sys.argv.pop(1))
from atlas_tectonics._private import reopen_fresh_restart as R  # noqa: E402

REFUSAL = 'the identity override is refused for a proof-mode producer (--open-proofs)'


class Passed(Exception):
    """Raised by the first read after the receipt checks: the reader got past them."""


class Sources:
    pass


class Profile:
    def record(self):
        return {'store_directory': 'store'}


def run(receipt, override, reusing=True):
    profile = Profile()
    reuse = {'previous': profile, 'record': {'identity_override': override}} if reusing else None
    sources = Sources()
    sources.profile = profile
    with mock.patch.object(R.F, 'FreshSources', Sources), \
            mock.patch.object(R.F, 'mode_output', lambda *a: R.Path('out')), \
            mock.patch.object(R.RUN, 'pinned_json', lambda *a: dict(receipt, mode='interval')), \
            mock.patch.object(R.RO, '_bounded_json', mock.Mock(side_effect=Passed)):
        try:
            R.producer_inputs(profile, sources=sources, mode='interval', receipt_sha256='0'*64, consumer_pid=1,
                              reuse=reuse)
        except Passed:
            return None
        except Exception as error:   # the package's require raises its own error type
            return str(error)
    raise AssertionError('producer_inputs returned without reading the guard record')


class OverrideInProofMode(unittest.TestCase):
    def test_override_refused_for_proof_producer(self):
        self.assertIn(REFUSAL, run({'open_proofs': True}, override=True))

    def test_override_allowed_for_ordinary_producer(self):   # a legitimate Debug reuse is unchanged
        self.assertIsNone(run({'open_proofs': False}, override=True))

    def test_override_allowed_for_receipt_before_proof_mode(self):   # older receipts carry no flag
        self.assertIsNone(run({}, override=True))

    def test_plain_reuse_of_proof_producer_unchanged(self):   # reuse without the override stays on in every mode
        self.assertIsNone(run({'open_proofs': True}, override=False))

    def test_no_reuse_unchanged(self):
        self.assertIsNone(run({'open_proofs': True}, override=None, reusing=False))

    def test_release_refusal_still_first(self):
        self.assertIn('reads a diagnostic producer only', run({'production_release': True, 'open_proofs': True},
                                                               override=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
