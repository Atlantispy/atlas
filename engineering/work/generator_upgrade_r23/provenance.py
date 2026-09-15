"""Bind the optimisation's own executed code, independently of R22 science."""
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import provenance as common
from . import HERE

encoded, sha, checked = common.encoded, common.sha, common.checked


def sources():
    current = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for path in sorted(HERE.glob('*.py'))}
    if not current:
        raise ValueError('nonempty R23 source inventory required')
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if (name == 'work.generator_upgrade_r23'
                or name.startswith('work.generator_upgrade_r23.') or path in current):
            if path not in current or getattr(module, '_R12_EXECUTED_SHA256', None) != current[path]:
                raise ValueError('R23 executed source differs: '+str(path))
    return current


def verify(expected):
    if sources() != expected:
        raise ValueError('R23 optimisation source changed; no silent repin')
