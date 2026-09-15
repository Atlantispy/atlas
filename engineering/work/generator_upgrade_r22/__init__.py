"""Captured successor for remaining biological and whole-world connections."""
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from work.generator_runtime_r12 import _CapturedLoader, _raw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NATIVE = {
    '_native_transport': ('generator_upgrade_r2/multicommodity.py', 'cb51a0e36574e5f22e712feb1629a4b6ec2283e5a818c20dc9465d54dd74c17b'),
    '_native_ecosystem': ('generator_upgrade_r11/ecosystem.py', '334eb376c35c3d3a861f746ea3adcf457ef813adc915da4025a5d1a6c68b3cc2'),
    '_native_stock': ('generator_upgrade_r9/stock.py', '33ec7eea9f0c9f8b7deddbb58f658aed257468928094d742eb174dc77d81d181'),
    '_native_spatial': ('generator_upgrade_r9/spatial.py', '559b82423c21ab5063384c25129a4d9fc84c76f091d5e91b3e224d26b798ffa0'),
    'spatial': ('generator_upgrade_r9/spatial.py', '559b82423c21ab5063384c25129a4d9fc84c76f091d5e91b3e224d26b798ffa0'),
    '_native_plants': ('generator_upgrade_r10/plants.py', 'ed874f9831d77efd1dd7d078df8f091fc840f2a2905286a95a49feabfec1e8a2'),
    '_native_organic': ('generator_upgrade_r7/organic.py', '0ac67b211851d07754afcd88faba20436f6e517389d614e25aaa2588de8770e3'),
    '_native_fertility': ('generator_upgrade_r7/fertility.py', '7edaa9c2facd72081cca485c72b14fe07ef67c0753027ecddb69f329575bb5f4'),
}
_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R22 bootstrap differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__+'.'
        if not fullname.startswith(prefix):
            return None
        name = fullname[len(prefix):]
        if not name.isidentifier():
            raise ImportError('flat R22 module identity required')
        if name in NATIVE:
            relative, expected = NATIVE[name]
            source = ROOT/relative
            if hashlib.sha256(_raw(source)).hexdigest() != expected:
                raise ValueError('sealed biological dependency changed: '+str(source))
        else:
            source = HERE/(name+'.py')
        if not source.is_file():
            raise ImportError('undeclared R22 module: '+fullname)
        return importlib.util.spec_from_file_location(fullname, source, loader=_CapturedLoader(source))


sys.meta_path.insert(0, _Finder())
