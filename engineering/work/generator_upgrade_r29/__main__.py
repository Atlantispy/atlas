"""Run source-bound recipes with optimised tectonics and retained shared scheduling."""
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE,__file__,'exec',dont_inherit=True):
    raise ValueError('executed R29 entrypoint differs')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()
from work.generator_upgrade_r27 import __main__ as previous
from work.generator_upgrade_r28.preflight import clone
from . import registry

main = clone(previous.main,registry=registry,__doc__=__doc__)

if __name__ == '__main__':
    main()
