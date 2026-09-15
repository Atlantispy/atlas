"""One actual pinned predecessor module identity shared by all R3 adapters."""
from pathlib import Path
import hashlib
import sys
import types

ROOT=Path(__file__).resolve().parents[1]
LANDSCAPE_PATH=ROOT/'generator_upgrade_r1/landscape.py'
LANDSCAPE_SHA='fac564da0abd635ec3c7ad54ee06b4a09b807881367400b1eb6d1e52c2322c3b'


def verify():
    raw=LANDSCAPE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=LANDSCAPE_SHA:raise ValueError('retained physical landscape source changed')
    return raw


def _load():
    module=types.ModuleType(__name__+'._physical_landscape')
    module.__file__=str(LANDSCAPE_PATH)
    if module.__name__ in sys.modules:raise ValueError('private physical source namespace occupied')
    sys.modules[module.__name__]=module
    try:exec(compile(verify(),str(LANDSCAPE_PATH),'exec',dont_inherit=True,optimize=0),module.__dict__)
    finally:del sys.modules[module.__name__]
    return module


landscape=_load()
