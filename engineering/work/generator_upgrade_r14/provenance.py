"""Bind R14, unchanged R13 numerical code and the sealed finite-material kernel."""
import hashlib
from pathlib import Path
import sys
from work.generator_upgrade_r13 import provenance as parent

HERE = Path(__file__).resolve().parent
encoded, sha, checked = parent.encoded, parent.sha, parent.checked
_BACKEND = None
_BACKEND_ID = None


def backend():
    global _BACKEND, _BACKEND_ID
    if _BACKEND is None:
        bundle = parent.shared.load_science()
        r6 = bundle
        for _ in range(5):
            r6 = r6.parent
        tt = r6.graph.load('work.generator_upgrade_r3.terrain_transport')
        _BACKEND = (bundle, tt)
        _BACKEND_ID = parent.shared.execution_identity(bundle)
    return _BACKEND


def verify_backend():
    bundle, _ = backend()
    parent.shared.verify_execution(bundle, _BACKEND_ID, full=False)


def identity():
    bundle, _ = backend()
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for path in sorted(HERE.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        if (name == 'work.generator_upgrade_r14' or name.startswith('work.generator_upgrade_r14.')
                or name == '__main__' and getattr(module, '__file__', None) == str(HERE/'__main__.py')):
            path = getattr(module, '__file__', None)
            if getattr(module, '_R12_EXECUTED_SHA256', None) != sources.get(path):
                raise ValueError('R14 executed source differs: '+str(path))
    return {'schema': 'diadem.ground-execution-binding.r14', 'sources': sources,
            'soil': parent.identity(), 'sealed': parent.shared.execution_identity(bundle)}


def verify(expected):
    bundle, _ = backend()
    parent.shared.verify_execution(bundle, expected['sealed'], full=False)
    if identity() != expected:
        raise ValueError('ground source/runtime binding changed; no repin')
