"""G-PIN FALSE PASS: pinned sha equals the .py at __file__, but python -I -B executes a stale __pycache__ .pyc
(timestamp-validated pyc whose recorded mtime+size still match the edited source; -B stops writing, not reading)."""
from hashlib import sha256
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

root = Path(__file__).resolve().parent/'case_pyc'
shutil.rmtree(root, ignore_errors=True)
priv = root/'src'/'atlas_tectonics'/'_private'
priv.mkdir(parents=True)
(root/'src'/'atlas_tectonics'/'__init__.py').write_text('', encoding='utf8')
(priv/'__init__.py').write_text('', encoding='utf8')
mod = priv/'mod_r1.py'
mod.write_bytes(b'SCALE = 1.0\n')
py_compile.compile(str(mod), doraise=True)          # a pyc from an earlier import / earlier fold attempt
st = os.stat(mod)
mod.write_bytes(b'SCALE = 2.0\n')                    # same size edit; mtime preserved (copy2/copystat style)
os.utime(mod, ns=(st.st_atime_ns, st.st_mtime_ns))
pin = sha256(mod.read_bytes()).hexdigest()
print('check_pins ->', P.check_pins(root/'src', dict(pins={'atlas_tectonics._private.mod_r1': pin}))['status'])
run = subprocess.run([sys.executable, '-I', '-B', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); '
                      'import atlas_tectonics._private.mod_r1 as m; print(m.SCALE, m.__file__.endswith(".py"))',
                      str(root/'src')], capture_output=True, text=True)
print('source on disk says SCALE = 2.0; python -I -B executes SCALE =', run.stdout.strip(), run.stderr.strip()[-200:])
shutil.rmtree(root, ignore_errors=True)
