"""The r7 joined-control helper changes only the owned two-scalar account inspection.

r6's inspection read heat._result._snapshot._metadata, which the compact r13
CompactHeatSnapshot does not have (heat_ledger_tables slots): every compact run
would raise AttributeError in check_global_accounts, after publication. r7 reads
the two scalars through heat_cold_patch.ledger_access, the joined consumer's own
accessor; a native snapshot keeps r6's exact decode branch.
"""
import json
import sys
import types
import unittest
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
R6 = HERE/'composed-r1'/'helpers'/'private_heat_original_joined_r6.py'
R7 = HERE/'private_heat_original_joined_r7.py'
sys.path[:0] = [str(HERE.parent/'runtime-integration-r1'/'runtime-src'), str(HERE/'compact-geometry-r1')]


def constants(path):
    """The module's literal edit tables, without executing the joined control."""
    source = path.read_text(encoding='utf8')
    prefix = source[:source.index('\ndef _replace_exact(')]
    namespace = {'__file__': str(path)}
    exec(compile(prefix, str(path)+'[constants]', 'exec'), namespace)  # noqa: S102 - the helper's own literal tables
    return namespace


def inspection(snippet):
    namespace = {}
    # The subject is the helper's derived account text, which the helper itself executes.
    exec('def inspect(result, cancel, W):\n'+snippet+'    return outgoing, heating\n', namespace)  # noqa: S102
    return namespace['inspect']


class Joined:
    """Stands in for LiveJoinedHeat: the inspection needs only its type, budget and snapshot."""


@contextmanager
def decoded(raw, budget, cancel):
    yield SimpleNamespace(value=json.loads(raw))


def fake_consumer():
    module = types.ModuleType('private_heat_joined_consumer_r6')
    module.LiveJoinedHeat = Joined
    module.verify_live = lambda heat, cancel=None: None
    module.R = SimpleNamespace(check=lambda cancel: None, decoded=decoded)
    return module


class OriginalJoinedR7Tests(unittest.TestCase):
    def test_only_the_inspection_edit_differs(self):
        old, new = constants(R6), constants(R7)
        self.assertEqual(new['_EDITS'], old['_EDITS'])
        self.assertEqual(new['_SOURCE_SHA'], old['_SOURCE_SHA'])
        self.assertEqual(new['_ACCOUNTS_SHA'], old['_ACCOUNTS_SHA'])
        self.assertEqual(len(new['_ACCOUNT_EDITS']), 2)
        self.assertEqual(new['_ACCOUNT_EDITS'][0], old['_ACCOUNT_EDITS'][0])
        (label, before, after), (old_label, old_before, old_after) = new['_ACCOUNT_EDITS'][1], old['_ACCOUNT_EDITS'][1]
        self.assertEqual((label, before), (old_label, old_before))
        self.assertIn('_snapshot._metadata', old_after)
        self.assertNotIn('_snapshot._metadata', after)
        self.assertIn('_HEAT_COLD.ledger_access(heat._result._snapshot', after)
        # Line by line, the rest of the file is r6's: the docstring note, the edit and two r7 tags.
        old_lines, new_lines = R6.read_text(encoding='utf8').splitlines(), R7.read_text(encoding='utf8').splitlines()
        added = [line for line in new_lines if line not in set(old_lines)]
        removed = [line for line in old_lines if line not in set(new_lines)]
        self.assertEqual(added, [
            'R7 (16 Oct 2026) changes one account edit only: the two exact scalars of the owned',
            'account inspection are read through heat_cold_patch.ledger_access. A compact r13',
            'heat snapshot has no _metadata and is read through its ledger record; a native',
            "snapshot keeps r6's exact decode branch. Nothing else differs from r6.",
            '     "    import heat_cold_patch as _HEAT_COLD\\n"',
            '     "        with _HEAT_COLD.ledger_access(heat._result._snapshot,\\n"',
            '     "                budget=heat._budget, cancel=cancel, resources=_joined.R) as decoded:\\n"',
            "    return dict(schema='atlas.private.original-joined-derivation.r7',",
            "exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_joined_r7]', 'exec'), globals())"])
        self.assertEqual(removed, [
            '     "        with _joined.R.decoded(heat._result._snapshot._metadata,\\n"',
            '     "                budget=heat._budget, cancel=cancel) as decoded:\\n"',
            "    return dict(schema='atlas.private.original-joined-derivation.r6',",
            "exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_joined_r6]', 'exec'), globals())"])

    def test_composer_transform_reproduces_r7_byte_for_byte(self):
        import original_joined_r7_transform as T
        r6 = R6.read_bytes().decode('utf8')
        self.assertEqual(T.r7_source(r6), R7.read_bytes().decode('utf8'))
        with self.assertRaisesRegex(ValueError, 'anchor missing or ambiguous'):
            T.r7_source(T.r7_source(r6))

    def run_inspection(self, after, snapshot, budget):
        heat = Joined()
        heat._budget, heat._result = budget, SimpleNamespace(_snapshot=snapshot)
        result = SimpleNamespace(exterior=SimpleNamespace(_heat=heat))
        W = SimpleNamespace(_decode=lambda pair: Fraction(int(pair[0], 16), int(pair[1], 16)))
        with patch.dict(sys.modules, {'private_heat_joined_consumer_r6': fake_consumer()}):
            return inspection(after)(result, None, W)

    def test_inspection_reads_compact_and_native_snapshots(self):
        from atlas_tectonics.resources import WorkBudget
        from content_cache import create_retained_scope
        from heat_ledger_tables import CompactHeatSnapshot
        new, old = constants(R7)['_ACCOUNT_EDITS'][1][2], constants(R6)['_ACCOUNT_EDITS'][1][2]
        meta = {'exact_outward_boundary_energy_j': ['0x3', '0x7'], 'exact_source_energy_j': ['-0x5', '0x2'],
                'exact_cell_storage_residual_j': [['0x1', '0x3']]}
        expected = (Fraction(3, 7), Fraction(-5, 2))
        budget = WorkBudget(64 << 20)
        scope = create_retained_scope(budget, process_epoch='joined-r7')
        snapshot = CompactHeatSnapshot.from_components(meta, {'enthalpy_j': np.array([1.0])}, scope=scope)
        self.assertEqual(self.run_inspection(new, snapshot, budget), expected)
        # The mutant (r6's edit) cannot read a compact snapshot.
        with self.assertRaises(AttributeError):
            self.run_inspection(old, snapshot, budget)
        native = SimpleNamespace(_metadata=json.dumps(meta, sort_keys=True, separators=(',', ':')).encode())
        self.assertEqual(self.run_inspection(new, native, budget), expected)
        self.assertEqual(self.run_inspection(old, native, budget), expected)
        import gc
        gc.collect()
        snapshot.close()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
