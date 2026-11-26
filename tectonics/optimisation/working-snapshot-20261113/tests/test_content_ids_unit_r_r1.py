"""Unit R (issue 96): code identity changes provenance; physical input changes the heat plan ID.

Run directly with: python -B -I test_content_ids_unit_r_r1.py <tectonics source root> <shared source root>
"""
from importlib.machinery import PathFinder
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class HeatPlanContentIdentity(unittest.TestCase):
    def test_code_identity_does_not_move_the_plan_id_and_physics_does(self):
        if __name__ != '__main__':
            # A reused worker may already have the issued package loaded. Run just this unbound fixture in isolation.
            roots = [Path(PathFinder.find_spec(name).origin).resolve().parents[1]
                     for name in ('atlas_tectonics', 'atlas_shared')]
            subprocess.run([sys.executable, '-B', '-I', __file__, *roots], check=True)
            return

        from atlas_tectonics import reuse
        from atlas_tectonics.regional_heat3d import PreparedRegionalHeat3D

        def plan(conductivity=3.0):
            prepared = PreparedRegionalHeat3D((2, 2, 2), (1e3, 1e3, 1e3), 2.5e6, conductivity)
            try:
                return prepared.plan_id, prepared._definition['execution']
            finally:
                prepared.close()

        live = reuse.ExecutionContext.identity
        first, code_a = plan()
        try:
            reuse.ExecutionContext.identity = property(lambda self: 'f'*64)
            second, code_b = plan()
        finally:
            reuse.ExecutionContext.identity = live
        self.assertNotEqual(code_a, code_b)
        self.assertEqual(first, second)
        self.assertNotEqual(first, plan(conductivity=3.5)[0])


if __name__ == '__main__':
    src, shared = Path(sys.argv.pop(1)), Path(sys.argv.pop(1))
    with tempfile.TemporaryDirectory(prefix='atlas-unit-r-') as folder:
        root = Path(folder)
        shutil.copytree(src / 'atlas_tectonics', root / 'atlas_tectonics', ignore=shutil.ignore_patterns(
            '_application_sources.json', '_application_sources.sha256', '_fixtures', '__pycache__'))
        shutil.copytree(shared / 'atlas_shared', root / 'atlas_shared', ignore=shutil.ignore_patterns('__pycache__'))
        sys.path.insert(0, str(root))
        unittest.main()
