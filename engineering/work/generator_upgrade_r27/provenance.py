"""Capture scheduling-policy code without invalidating unchanged science results."""
import hashlib
import sys
from work.generator_runtime_r12.provenance import sha
from work.generator_upgrade_r24.verification import Reader
from work.generator_upgrade_r26 import provenance as previous
from . import HERE


def sources():
    reader = Reader()
    try:
        paths = tuple(sorted(HERE.glob('*.py')))
        current = {str(path):hashlib.sha256(reader.checked(path)).hexdigest() for path in paths}
        if tuple(sorted(HERE.glob('*.py'))) != paths:
            raise ValueError('R27 source inventory changed during verification')
        for name,module in tuple(sys.modules.items()):
            path = getattr(module,'__file__',None)
            if name == 'work.generator_upgrade_r27' or name.startswith('work.generator_upgrade_r27.') or path in current:
                if path not in current or getattr(module,'_R12_EXECUTED_SHA256',None) != current[path]:
                    raise ValueError('R27 executed source differs: '+str(path))
        current.update(previous.sources())
        return current
    finally:
        reader.finish()


def verify(expected):
    if sources() != expected:
        raise ValueError('R27 scheduling source changed; no silent repin')
