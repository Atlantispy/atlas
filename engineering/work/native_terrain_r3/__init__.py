"""Source-captured, lossless history adapter over unchanged native R2 science."""
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from work.generator_runtime_r12 import _CapturedLoader, _raw

HERE = Path(__file__).resolve().parent
_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed native history bootstrap differs from source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__ + '.'
        if not fullname.startswith(prefix):
            return None
        name = fullname[len(prefix):]
        if not name.isidentifier():
            raise ImportError('flat native history module identity required')
        source = HERE / (name + '.py')
        if not source.is_file():
            raise ImportError('undeclared native history module: ' + fullname)
        return importlib.util.spec_from_file_location(fullname, source, loader=_CapturedLoader(source))


sys.meta_path.insert(0, _Finder())
