"""One retained dependency edge, restored-input guard and actual R26 CLI."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from work.test_r22_registry import recipe as reference
from work.test_r24_registry import bound
from work.generator_upgrade_r26 import registry


class RegistryTests(unittest.TestCase):
    def test_dependency_reuse_category_guard_and_captured_entrypoint(self):
        recipe = bound(reference(),registry)
        with tempfile.TemporaryDirectory(prefix='r26-entry-') as directory:
            root = Path(directory)
            cold = registry.run(recipe,cache_root=root/'cache')
            warm = registry.run(recipe,cache_root=root/'cache')
            self.assertEqual(cold['graph'],warm['graph'])
            self.assertEqual(warm['execution']['computed_stage_ids'],[])
            changed = deepcopy(recipe)
            changed['stages'][1]['inputs']['rates']['water_m3'] = '1/200'
            result = registry.run(changed,cache_root=root/'cache')
            self.assertEqual(result['execution']['computed_stage_ids'],['serve'])
            wrong = deepcopy(recipe)
            wrong['stages'][0]['category'] = 'settlements'
            with self.assertRaisesRegex(ValueError,'category is not implemented'):
                registry.run(wrong,cache=False)
            path = root/'r.json'
            path.write_text(json.dumps(recipe),encoding='utf-8')
            output = subprocess.run([sys.executable,'-B','-m','work.generator_upgrade_r26',
                str(path),'--no-cache','--workers','1'],capture_output=True,text=True)
            self.assertEqual(output.returncode,0,output.stderr)
            self.assertEqual(json.loads(output.stdout)['graph'],cold['graph'])


if __name__ == '__main__': unittest.main()
