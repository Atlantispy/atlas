"""Unit R (issue 96, content identifiers), T-2 on the 3D heat plan: one plan built under two code identities
gives one plan_id; a changed physical input gives another. Runs on an unbound copy (no inventory pair, no fixtures).
  python -B -I test_content_ids_unit_r_r1.py <tectonics source root> <shared source root>"""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix='atlas-unit-r-'))
_src = Path(sys.argv.pop(1)) if __name__ == '__main__' else Path(
    importlib.util.find_spec('atlas_tectonics').origin).parents[1]  # under the runner: --src on PYTHONPATH
_shared = Path(sys.argv.pop(1)) if __name__ == '__main__' else Path(
    importlib.util.find_spec('atlas_shared').origin).parents[1]
shutil.copytree(_src / 'atlas_tectonics', _root / 'atlas_tectonics', ignore=shutil.ignore_patterns(
    '_application_sources.json', '_application_sources.sha256', '_fixtures', '__pycache__'))
shutil.copytree(_shared / 'atlas_shared', _root / 'atlas_shared', ignore=shutil.ignore_patterns('__pycache__'))
sys.path.insert(0, str(_root))
from atlas_tectonics import reuse  # noqa: E402
from atlas_tectonics.regional_heat3d import PreparedRegionalHeat3D  # noqa: E402


def _plan(conductivity=3.0):
    plan = PreparedRegionalHeat3D((2, 2, 2), (1e3, 1e3, 1e3), 2.5e6, conductivity)
    try:
        return plan.plan_id, plan._definition['execution']
    finally:
        plan.close()


class HeatPlanContentIdentity(unittest.TestCase):
    def test_code_identity_does_not_move_the_plan_id_and_physics_does(self):
        live = reuse.ExecutionContext.identity
        first, code_a = _plan()
        try:
            reuse.ExecutionContext.identity = property(lambda self: 'f'*64)   # another build of the code
            second, code_b = _plan()
        finally:
            reuse.ExecutionContext.identity = live
        self.assertNotEqual(code_a, code_b)        # the stored plan still names its code (R-2)
        self.assertEqual(first, second)
        self.assertNotEqual(first, _plan(conductivity=3.5)[0])


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        shutil.rmtree(_root, ignore_errors=True)
