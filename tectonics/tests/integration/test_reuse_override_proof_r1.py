"""Unit B (identity batch, issue 107 carry-over from 75): the reader refuses the identity override when the producer it
would reuse ran in proof mode (--open-proofs, recorded as the receipt's `open_proofs`). Other reuse is unchanged.
  python -B -I test_reuse_override_proof_r1.py <package parent folder>"""
import sys
import unittest
from unittest import mock

_STATE = list(sys.argv), list(sys.path), set(sys.modules)   # restored by tearDownModule: test workers are shared
sys.path.insert(0, sys.argv.pop(1))
from atlas_tectonics._private.integration import reopen_fresh_restart as R  # noqa: E402


def tearDownModule():   # a later unit in the same worker must not meet modules imported outside the checked loader
    argv, path, modules = _STATE
    sys.argv[:], sys.path[:] = argv, path
    for name in set(sys.modules) - modules:
        if name.partition('.')[0] in ('atlas_shared', 'atlas_tectonics'):   # numpy and others cannot load twice
            del sys.modules[name]


class Passed(Exception):
    """Raised by the first read after the receipt checks: the reader got past them."""


class Sources:
    pass


class Profile:
    def record(self):
        return {'store_directory': 'store'}


IDENTITY = '3'*64


def run(receipt, override, reusing=True, identity=IDENTITY):
    profile = Profile()
    reuse = ({'previous': profile, 'execution_identity': IDENTITY,
              'record': {'identity_override': override, 'miss': None}} if reusing else None)
    sources = Sources()
    sources.profile = profile
    receipt = dict({'identities': {'runtime_identity': identity}}, **receipt, mode='interval')

    def read_json(path, **_):   # the receipt, then the guard record: past the receipt checks
        if R.Path(path).name == 'run.json':
            return receipt, '0'*64
        raise Passed
    with mock.patch.object(R.F, 'FreshSources', Sources), \
            mock.patch.object(R.F, 'mode_output', lambda *a: R.Path('out')), \
            mock.patch.object(R.RUN, 'ordinary', lambda path, **_: path), \
            mock.patch.object(R.OR, 'read_json', read_json):
        try:
            result = R.producer_inputs(profile, sources=sources, mode='interval', receipt_sha256='0'*64,
                                       consumer_pid=1, reuse=reuse)
        except Passed:
            return None
        except Exception as error:   # the package's require raises its own error type
            return str(error)
    if result is None and reuse is not None and reuse['record']['miss']:
        return 'MISS: ' + reuse['record']['miss']
    raise AssertionError('producer_inputs returned without reading the guard record')


class OverrideInProofMode(unittest.TestCase):
    def test_override_allowed_for_ordinary_producer(self):   # a legitimate Debug reuse is unchanged
        self.assertIsNone(run({'open_proofs': False}, override=True))

    def test_override_allowed_for_receipt_before_proof_mode(self):   # older receipts carry no flag
        self.assertIsNone(run({}, override=True))

    def test_plain_reuse_of_proof_producer_unchanged(self):   # reuse without the override stays on in every mode
        self.assertIsNone(run({'open_proofs': True}, override=False))

    def test_other_identity_is_a_miss_not_a_refusal(self):
        self.assertEqual(run({}, override=False, identity='4'*64),
                         'MISS: previous run has another execution identity')

    def test_override_turns_an_identity_difference_into_no_miss(self):
        self.assertIsNone(run({}, override=True, identity='4'*64))

    def test_no_reuse_unchanged(self):
        self.assertIsNone(run({'open_proofs': True}, override=None, reusing=False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
