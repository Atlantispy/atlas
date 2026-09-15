"""New orchestration sources, without salting unrelated producer/cache keys."""
import hashlib
import sys
from work.generator_upgrade_r24.verification import Reader
from work.generator_upgrade_r30 import provenance as retained
from . import HERE


def sources():
    reader = Reader()
    try:
        paths = tuple(sorted(HERE.glob('*.py')))
        current = {str(path):hashlib.sha256(reader.checked(path)).hexdigest() for path in paths}
        if tuple(sorted(HERE.glob('*.py'))) != paths:
            raise ValueError('R31 source inventory changed')
        for name, module in tuple(sys.modules.items()):
            if name == 'work.generator_upgrade_r31' or name.startswith('work.generator_upgrade_r31.'):
                path = getattr(module, '__file__', None)
                if path not in current or getattr(module, '_R12_EXECUTED_SHA256', None) != current[path]:
                    raise ValueError('R31 executed source differs: '+str(path))
        return {'sources':current, 'retained_r30':retained.sources()}
    finally:
        reader.finish()


def verify(expected):
    if sources() != expected:
        raise ValueError('R31 source changed; no silent repin')
