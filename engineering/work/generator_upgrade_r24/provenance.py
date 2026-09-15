"""Exact current R23/R24 adapter bytes; native identities remain separate."""
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import provenance as common
from work.generator_upgrade_r23 import HERE as PREVIOUS
from . import HERE

encoded, sha, checked = common.encoded, common.sha, common.checked


def sources():
    current = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for root in (PREVIOUS, HERE) for path in sorted(root.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if (name in ('work.generator_upgrade_r23', 'work.generator_upgrade_r24')
                or name.startswith(('work.generator_upgrade_r23.', 'work.generator_upgrade_r24.'))
                or path in current):
            if path not in current or getattr(module, '_R12_EXECUTED_SHA256', None) != current[path]:
                raise ValueError('R24 adapter executed source differs: '+str(path))
    return current


def verify(expected):
    if sources() != expected:
        raise ValueError('R24 adapter source changed; no silent repin')
