"""Bind changed geology orchestration separately; other producer keys stay valid."""
import hashlib
import sys
from work.generator_upgrade_r24.verification import Reader
from . import HERE

def sources():
    reader = Reader()
    try:
        paths = tuple(sorted(HERE.glob('*.py')))
        current = {str(path):hashlib.sha256(reader.checked(path)).hexdigest() for path in paths}
        if tuple(sorted(HERE.glob('*.py'))) != paths:
            raise ValueError('R30 source inventory changed')
        for name in ('work.generator_upgrade_r29', 'work.generator_upgrade_r29.registry'):
            module = sys.modules[name]
            path = module.__file__
            digest = hashlib.sha256(reader.checked(path)).hexdigest()
            if getattr(module, '_R12_EXECUTED_SHA256', None) != digest:
                raise ValueError('R30 retained orchestration source differs: '+path)
            current[path] = digest
        for name,module in tuple(sys.modules.items()):
            path = getattr(module,'__file__',None)
            if name == 'work.generator_upgrade_r30' or name.startswith('work.generator_upgrade_r30.') or path in current:
                if path not in current or getattr(module,'_R12_EXECUTED_SHA256',None) != current[path]:
                    raise ValueError('R30 executed source differs: '+str(path))
        # This is the additional orchestration layer only. The unchanged R28
        # runner verifies its full ancestor closure before/after execution;
        # each versioned adapter verifies its precise native code at every job,
        # cache acceptance and final cleanup. Do not repeat either full pass.
        return current
    finally:
        reader.finish()

def verify(expected):
    if sources() != expected:
        raise ValueError('R30 source changed; no silent repin')
