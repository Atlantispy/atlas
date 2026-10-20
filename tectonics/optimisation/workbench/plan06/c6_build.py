"""Build local test-only N9-W and N9-W+D5 successors; does not import the runtime.
Usage: python -B c6_build.py F2 N9_W NEW_BASE NEW_CANDIDATE
"""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PIN = 'a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef'
REL = 'atlas_tectonics/integration_wall_measures.py'
digest = lambda b: sha256(b).hexdigest()
f2, n9, base, candidate = map(lambda p: Path(p).resolve(), sys.argv[1:5])
if base.exists() or candidate.exists():
    raise SystemExit('successor destinations must not exist')
raw = (f2/'TEST_COMPOSITION.json').read_bytes()
rec = json.loads(raw)
for relative, expected in rec['files'].items():
    if digest((f2/relative).read_bytes()) != expected:
        raise SystemExit('base manifest mismatch: '+relative)
source = n9.read_bytes()
if digest(source) != PIN:
    raise SystemExit('N9 W source pin mismatch')
old = rec['files'][REL]
shutil.copytree(f2, base, ignore=shutil.ignore_patterns('__pycache__'))
(base/REL).write_bytes(source)
rec['files'][REL] = PIN
rec['base'] += ' + local-test-only-N9-W'
rec['transforms'].append(dict(transform='local-test-only-N9-W', file=REL,
                             source=str(n9), input_sha256=old, output_sha256=PIN,
                             scope='C6 local boundary only; not selected N9 or Plan31'))
(base/'TEST_COMPOSITION.json').write_bytes(json.dumps(rec, indent=1).replace('\n', '\r\n').encode())
subprocess.run([sys.executable, '-B', str(HERE/'build_tree.py'), str(base), str(candidate)], check=True)
binding = dict(scope='C6 local W-composed boundary only; final N9/Plan31 unavailable',
               builder_sha256=digest(Path(__file__).read_bytes()), f2=str(f2),
               f2_manifest_sha256=digest(raw), n9_w=str(n9), n9_w_sha256=PIN,
               base=str(base), candidate=str(candidate),
               base_manifest_sha256=digest((base/'TEST_COMPOSITION.json').read_bytes()),
               candidate_manifest_sha256=digest((candidate/'TEST_COMPOSITION.json').read_bytes()))
(candidate/'C6_BUILD.json').write_text(json.dumps(binding, indent=2)+'\n')
print(json.dumps(binding))
