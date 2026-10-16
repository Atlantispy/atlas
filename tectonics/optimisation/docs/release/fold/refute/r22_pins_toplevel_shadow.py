"""FALSE PASS (conditional): an un-rewritten top-level import passes the AST gate by design (prefix removal makes
`import b` == `from atlas_tectonics._private import b`), and G-PIN hashes atlas_tectonics._private.b, not the top-level
`b` that the folded module actually executes. A leftover top-level copy reachable on the -I path is then used."""
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

root = Path(__file__).resolve().parent/'case_shadow'
shutil.rmtree(root, ignore_errors=True)
src = root/'src'
priv = src/'atlas_tectonics'/'_private'
priv.mkdir(parents=True)
(src/'atlas_tectonics'/'__init__.py').write_text('', encoding='utf8')
(priv/'__init__.py').write_text('', encoding='utf8')
orig = 'import b\nSCALE = b.SCALE\n'
(priv/'a.py').write_bytes(orig.encode())               # fold forgot to rewrite this import
(priv/'b.py').write_bytes(b'SCALE = 2.0\n')     # the folded, pinned b
(src/'b.py').write_text('SCALE = 1.0\n', encoding='utf8')      # leftover top-level copy
pins = {'atlas_tectonics._private.a': sha256(orig.encode()).hexdigest(),
        'atlas_tectonics._private.b': sha256(b'SCALE = 2.0\n').hexdigest()}
print('ast_equivalent(un-rewritten import)  ->', P.ast_equivalent(orig, orig))
print('ast_equivalent(rewritten import)     ->', P.ast_equivalent(orig, 'from atlas_tectonics._private import b\n'
                                                                       'SCALE = b.SCALE\n'))
print('check_pins                           ->', P.check_pins(src, dict(pins=pins))['status'])
run = subprocess.run([sys.executable, '-I', '-B', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); '
                      'import atlas_tectonics._private.a as a; print(a.SCALE, a.b.__file__)', str(src)],
                     capture_output=True, text=True)
print('a.SCALE executed (pinned b says 2.0) ->', run.stdout.strip().replace(str(root), '<case>'))
shutil.rmtree(root, ignore_errors=True)
