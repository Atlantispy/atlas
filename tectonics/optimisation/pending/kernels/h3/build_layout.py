"""Build a new heat-control layout from an existing H3 layout with rebuilt H3 outputs installed.

Usage: python -B -I build_layout.py SRC_LAYOUT OUT_LAYOUT H3_OUT
SRC_LAYOUT: a layout folder (control.json, runtime-src, helpers, ram). OUT_LAYOUT must not exist.
H3_OUT: a folder written by transforms/h3_compiled_dot.py (kernel, resources, compiled helper); the three
replace the layout's.
control.json: each path inside SRC_LAYOUT is moved to the same place inside OUT_LAYOUT; every other field and
path is kept, in the source rendering (checked to reproduce the source bytes first).
"""
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

KERNEL = 'private_heat_certification_kernel_r1.py'
RESOURCES = 'private_heat_certification_resources_r1.py'
COMPILED = 'private_heat_compiled_dot_r1.py'

src, out, h3 = (Path(a).resolve() for a in sys.argv[1:4])
if out.exists():
    raise SystemExit('%s exists' % out)
raw = (src/'control.json').read_bytes()
control = json.loads(raw)
render = None
for indent in (None, 1, 2):
    for newline in ('\n', '\r\n'):
        text = json.dumps(control, indent=indent).replace('\n', newline).encode()
        for tail in (b'', newline.encode()):
            if text+tail == raw:
                render = (indent, newline, tail)
if render is None:
    raise SystemExit('control.json is not in a known rendering')
moved = []
for i, path in enumerate(control['paths']):
    p = Path(path).resolve()
    if p == src or src in p.parents:
        control['paths'][i] = str(out/p.relative_to(src))
        moved.append(i)
shutil.copytree(src, out, ignore=shutil.ignore_patterns('__pycache__'))
for name in (KERNEL, RESOURCES, COMPILED):
    before = (out/'helpers'/name).read_bytes()
    after = (h3/name).read_bytes()
    (out/'helpers'/name).write_bytes(after)
    print(name, sha256(before).hexdigest()[:8], '->', sha256(after).hexdigest()[:8])
indent, newline, tail = render
(out/'control.json').write_bytes(json.dumps(control, indent=indent).replace('\n', newline).encode()+tail)
print('paths moved', moved, 'of', len(control['paths']), '; control.json', sha256(raw).hexdigest()[:8], '->',
      sha256((out/'control.json').read_bytes()).hexdigest()[:8])
