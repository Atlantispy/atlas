"""Source-captured political district generation; working, not canon."""
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw, _CapturedLoader

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R20 bootstrap differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__ + '.'
        if not fullname.startswith(prefix):
            return None
        name = fullname[len(prefix):]
        if not name.isidentifier():
            raise ImportError('flat R20 module identity required')
        source = Path(__file__).resolve().parent/(name+'.py')
        if name == '_snapshot_contract':
            source = Path(__file__).resolve().parents[1]/'generator_upgrade_r11'/'snapshot.py'
            if hashlib.sha256(_raw(source)).hexdigest() != '9177895ed0f8c614dbccffa0714d4ac9b7679e120be5ac7360dbdbc7f12b9ba0':
                raise ValueError('shared snapshot contract changed; explicit review required')
        if not source.is_file():
            raise ImportError('undeclared R20 module: '+fullname)
        return importlib.util.spec_from_file_location(fullname, source, loader=_CapturedLoader(source))


sys.meta_path.insert(0, _Finder())
