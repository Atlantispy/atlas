"""Profiling sampler switch: the stack sampler starts only when ATLAS_PROFILE_SAMPLER=1 (unset, "0" and "true" leave
it off, and no folder is made). Each case runs in its own interpreter.
  python -B -I test_profile_sampler_switch_r1.py <package parent folder>"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if __name__ == '__main__' and len(sys.argv) > 3:       # child: <root> <scratch> <case>
    sys.path.insert(0, sys.argv[1])
    from atlas_tectonics._private import run_fresh_interval as F
    F._profile_sampler(Path(sys.argv[2]) / sys.argv[3], 'test')
    time.sleep(0.5)
    print(any(t.name == 'profile-stack-sampler' for t in threading.enumerate()), (Path(sys.argv[2]) / sys.argv[3]).is_dir())
    sys.exit()
ROOT = (Path(sys.argv.pop(1)) if __name__ == '__main__' else
        Path(importlib.util.find_spec('atlas_tectonics').origin).parents[1])  # under the runner: --src on PYTHONPATH


class SamplerSwitch(unittest.TestCase):
    def test_cases(self):
        with tempfile.TemporaryDirectory() as scratch:
            for case, value, want in (('unset', None, 'False False'), ('on', '1', 'True True'), ('zero', '0', 'False False'),
                                      ('true', 'true', 'False False')):
                with self.subTest(case=case):
                    env = {k: v for k, v in os.environ.items() if k != 'ATLAS_PROFILE_SAMPLER'}
                    if value is not None:
                        env['ATLAS_PROFILE_SAMPLER'] = value
                    r = subprocess.run([sys.executable, '-B', '-I', __file__, str(ROOT), scratch, case], env=env,
                                       capture_output=True, text=True)
                    self.assertEqual((r.returncode, r.stdout.strip()), (0, want), r.stderr[-800:])


if __name__ == '__main__':
    unittest.main()
