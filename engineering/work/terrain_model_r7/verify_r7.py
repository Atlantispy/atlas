"""Preferred R7 exact-source verification launcher (retains mapped verifier name)."""
from pathlib import Path
import sys
import types

if __name__=='__main__':
    path=Path(__file__).absolute().with_name('release_source_runtime.py')
    raw=path.read_bytes();helper=types.ModuleType('_r7_exact_verification_bootstrap')
    helper.__file__=str(path);helper.EXECUTED_SOURCE_BYTES=raw
    sys.modules[helper.__name__]=helper
    exec(compile(raw,str(path),'exec',dont_inherit=True,optimize=0),helper.__dict__)
    raise SystemExit(helper.launch(path.parent))
