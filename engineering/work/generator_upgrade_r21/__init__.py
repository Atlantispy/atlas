"""Source-captured agriculture integration over unchanged, pinned components."""
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw, _CapturedLoader

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R21 bootstrap differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()
ROOT = Path(__file__).resolve().parents[1]
NATIVE = {
    '_native_crop': ('generator_upgrade_r1/agroclimate.py', '52a9848949682a295a190df499f18ab251d757e3c041ed74980482979bdcdd6b'),
    '_native_human': ('generator_upgrade_r11/human.py', '6817bfc61ebdd65e732493c1008eb5150b802f4cdc2a39220a20c18695394edb'),
    '_native_food': ('generator_upgrade_r2/food_accounting.py', '6132c0666e9fda16ea1260bcd4199ca277c9639b91570c3b821e2ed1615ec650'),
    '_native_geometry': ('generator_upgrade_r20/geometry.py', '4b0e502c180bd1d1e1d01fe5f647d80bf116985a51e4deecdce3f59171bab06d'),
    '_native_inputs': ('generator_upgrade_r20/inputs.py', '3f112c347ae62474d30fbcf3c6c3016c25ffa3dd1c96f9b2a39958d7cc6f24c2'),
    '_snapshot_contract': ('generator_upgrade_r11/snapshot.py', '9177895ed0f8c614dbccffa0714d4ac9b7679e120be5ac7360dbdbc7f12b9ba0'),
}


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__+'.'
        if not fullname.startswith(prefix):
            return None
        name = fullname[len(prefix):]
        if not name.isidentifier():
            raise ImportError('flat R21 module identity required')
        if name in NATIVE:
            relative, expected = NATIVE[name]
            source = ROOT/relative
            if hashlib.sha256(_raw(source)).hexdigest() != expected:
                raise ValueError('sealed agriculture dependency changed: '+str(source))
        else:
            source = Path(__file__).resolve().parent/(name+'.py')
        if not source.is_file():
            raise ImportError('undeclared R21 module: '+fullname)
        return importlib.util.spec_from_file_location(fullname, source, loader=_CapturedLoader(source))


sys.meta_path.insert(0, _Finder())
