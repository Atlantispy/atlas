"""Build a D5 test runtime: a copy of a test composition plus the D5 transform and its two new modules.

Usage: python -B -I build_tree.py BASE_TREE OUT_TREE
BASE_TREE is a test-composition folder (TEST_COMPOSITION.json + atlas_tectonics); OUT_TREE must not exist.
The transform (../transforms/d5_wall_hooks.py) and the new modules (src/) are found next to this script.
TEST_COMPOSITION.json gets the new and changed file digests and a 'd5' transform entry, written as the base
record is (json indent 1, CRLF), after checking that this rendering reproduces the base record's bytes.
"""
import importlib.util
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRANSFORM = HERE.parent/'transforms'/'d5_wall_hooks.py'
NEW = ('integration_exact_twin.py', 'integration_wall_measures_gmp.py')
REL = 'atlas_tectonics/integration_wall_measures.py'


def digest(b):
    return sha256(b).hexdigest()


def render(rec):
    return json.dumps(rec, indent=1).replace('\n', '\r\n').encode()


base, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
if out.exists():
    raise SystemExit('%s exists' % out)
record_bytes = (base/'TEST_COMPOSITION.json').read_bytes()
record = json.loads(record_bytes)
if render(record) != record_bytes:
    raise SystemExit('base TEST_COMPOSITION.json is not in the expected rendering')
files = record['files']
was_sorted = list(files) == sorted(files)
source = (base/REL).read_bytes()
if files.get(REL) != digest(source):
    raise SystemExit('base record does not match its wall-measures file')
spec = importlib.util.spec_from_file_location('d5_wall_hooks', TRANSFORM)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
new = mod.transform(source.decode('utf8')).encode('utf8')
shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__'))
(out/REL).write_bytes(new)
added = {}
for name in NEW:
    data = (HERE/'src'/name).read_bytes()
    (out/'atlas_tectonics'/name).write_bytes(data)
    added['atlas_tectonics/'+name] = digest(data)
    if 'atlas_tectonics/'+name in files:
        raise SystemExit('base already has %s' % name)
files[REL] = digest(new)
files.update(added)
if was_sorted:
    record['files'] = dict(sorted(files.items()))
record['base'] = record['base'] + ' + d5'
record['transforms'].append(dict(transform='d5', module='transforms/d5_wall_hooks.py',
                                 module_sha256=digest(TRANSFORM.read_bytes()), file=REL,
                                 input_sha256=digest(source), output_sha256=digest(new), new_files=added))
(out/'TEST_COMPOSITION.json').write_bytes(render(record))
print('built', out.name, 'from', base.name, REL, digest(source)[:8], '->', digest(new)[:8],
      {k.split('/')[-1]: v[:8] for k, v in added.items()})
