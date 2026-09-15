"""Source bindings for the bounded tectonic successor and retained native inputs."""
import hashlib
import sys
from work.generator_upgrade_r24.verification import Reader
from . import HERE

RETAINED = {
    'diadem_tectonics_r2/snapshot.py':'548333737476efb9518297e1138f9bb8f2a42f1a3dfb8da1e5647ff43e8dcda3',
    'diadem_tectonics_r2/geometry_audit.py':'78cac4df7dd0c553e8eb60e87b4c750fbe66e01bc1de489b90fe8caa912f9a36',
    'diadem_tectonics_r2/audit.py':'7defbdf1adb7a6038baa37b0b30ad60879cda61b77c8d16e12c5d548885e25eb',
    'diadem_tectonics_r1/sources.py':'bb75f09646f8d8a5cd3d127b57938d654f6817230bdbca0242ed8d29bf899e8a',
    'diadem_tectonics_r1/compare.py':'fe94ffbf6cf647cff240ab39f1251dfa27b059e89f6754d2a948211edacce4b7',
}

def sources():
    reader = Reader()
    try:
        paths = tuple(sorted(HERE.glob('*.py')))
        current = {str(path):hashlib.sha256(reader.checked(path)).hexdigest() for path in paths}
        if tuple(sorted(HERE.glob('*.py'))) != paths:
            raise ValueError('Tectonics R3 source inventory changed')
        for name,module in tuple(sys.modules.items()):
            path = getattr(module,'__file__',None)
            if name == 'work.diadem_tectonics_r3' or name.startswith('work.diadem_tectonics_r3.') or path in current:
                if path not in current or getattr(module,'_R12_EXECUTED_SHA256',None) != current[path]:
                    raise ValueError('Tectonics R3 executed source differs: '+str(path))
        for relative,expected in RETAINED.items():
            path = HERE.parent/relative
            actual = hashlib.sha256(reader.checked(path)).hexdigest()
            if actual != expected:
                raise ValueError('Retained tectonics source changed: '+str(path))
            current[str(path)] = actual
            if relative.startswith('diadem_tectonics_r1/'):
                alias = '_history_a_r3_r1_'+path.stem
                module = sys.modules.get(alias)
                if module is not None and (getattr(module,'__file__',None) != str(path)
                        or getattr(module,'_R12_EXECUTED_SHA256',None) != expected):
                    raise ValueError('Retained tectonics executed source differs: '+alias)
        return current
    finally:
        reader.finish()

def verify(expected):
    if sources() != expected:
        raise ValueError('Tectonics R3 source changed; no silent repin')
