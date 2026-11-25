"""Profiling sampler switch: the stack sampler starts only when ATLAS_PROFILE_SAMPLER=1 (unset, "0" and "true" leave
it off, and no folder is made). Each case runs in its own interpreter.
  python -B -I test_profile_sampler_switch_r1.py <tectonics source root> <shared source root>"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if __name__ == '__main__' and len(sys.argv) > 3:       # child: <root> <shared> <scratch> <case>
    sys.path[:0] = sys.argv[1:3]
    from atlas_tectonics._private import run_fresh_interval as F
    folder = Path(sys.argv[3]) / sys.argv[4]
    F._profile_sampler(folder, 'test')
    time.sleep(0.5)
    print(any(t.name == 'profile-stack-sampler' for t in threading.enumerate()), folder.is_dir())
    sys.exit()
ROOT = (Path(sys.argv.pop(1)) if __name__ == '__main__' else
        Path(importlib.util.find_spec('atlas_tectonics').origin).parents[1])  # under the runner: --src on PYTHONPATH
SHARED = (Path(sys.argv.pop(1)) if __name__ == '__main__' else
          Path(importlib.util.find_spec('atlas_shared').origin).parents[1])


class SamplerSwitch(unittest.TestCase):
    def test_cases(self):
        with tempfile.TemporaryDirectory() as scratch:
            for case, value, want in (('unset', None, 'False False'), ('on', '1', 'True True'), ('zero', '0', 'False False'),
                                      ('true', 'true', 'False False')):
                with self.subTest(case=case):
                    env = {k: v for k, v in os.environ.items() if k != 'ATLAS_PROFILE_SAMPLER'}
                    if value is not None:
                        env['ATLAS_PROFILE_SAMPLER'] = value
                    r = subprocess.run([sys.executable, '-B', '-I', __file__, str(ROOT), str(SHARED), scratch, case], env=env,
                                       capture_output=True, text=True)
                    self.assertEqual((r.returncode, r.stdout.strip()), (0, want), r.stderr[-800:])


if __name__ == '__main__':
    unittest.main()
