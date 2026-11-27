"""Landing 1: modules are found by plain imports and a worker child computes the parent's identity (D1)."""
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

SRC = Path(find_spec('atlas_tectonics').origin).parents[1]


class PlainImportStartTests(unittest.TestCase):
    def test_clean_interpreter_imports_without_a_list_file(self):
        self.assertFalse(list((SRC/'atlas_tectonics').glob('_application_sources.*')))
        code = (f"import sys; sys.path.insert(0, {str(SRC)!r}); import atlas_tectonics, atlas_shared;"
                "from atlas_tectonics.integration.reuse import execution_identity; print(execution_identity())")
        child = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True, timeout=120)
        self.assertEqual(child.returncode, 0, child.stderr)
        from atlas_tectonics.integration.reuse import execution_identity
        self.assertEqual(child.stdout.strip(), execution_identity())

    def test_dispatch_worker_starts_and_shares_the_parent_identity(self):
        # launch() admits only a -B -s -P, seed-zero parent with the allow-listed environment, so the parent runs
        # in a child of this test. It starts the kept worker exactly as dispatch does (empty input: one context,
        # then exit); the worker process prints the identity it computes once its worker body has returned.
        parent = f"""
import json, subprocess, sys
sys.path.insert(0, {str(SRC)!r})
from pathlib import Path
from atlas_tectonics.integration.parallel import dispatch
from atlas_tectonics.integration.reuse import execution_identity
job = Path(sys.argv[1])
(job/'kept').write_bytes(b'')
command, env = dispatch._worker_launch(job)
command[5] += ';from atlas_tectonics.integration.reuse import execution_identity as e;print(e())'
worker = subprocess.run(command, env=env, input=b'', capture_output=True, timeout=120)
print(json.dumps({{'started': worker.returncode, 'stderr': worker.stderr.decode(errors='replace')[-2000:],
                   'worker': worker.stdout.decode().strip(), 'parent': execution_identity(),
                   'record': sorted(json.loads((job/'startup.json').read_bytes()))}}))
"""
        from atlas_tectonics.integration.parallel.worker_bootstrap import clean_child_env
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder)/'job'
            job.mkdir()
            run = subprocess.run([sys.executable, '-B', '-s', '-P', '-c', parent, str(job)], env=clean_child_env(),
                                 capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(result['started'], 0, result['stderr'])
        self.assertRegex(result['worker'], '^[0-9a-f]{64}$')
        self.assertEqual(result['worker'], result['parent'])
        self.assertNotIn('execution_identity', result['record'])

if __name__ == '__main__':
    unittest.main()
