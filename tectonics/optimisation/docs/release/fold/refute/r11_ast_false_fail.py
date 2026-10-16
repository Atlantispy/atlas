"""AST gate FALSE FAILS: legitimate fold rewrites that ast_equivalent rejects."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

CASES = [
    ('abs key literal -> package-relative key literal',
     "PINS = {'C:\\\\w\\\\composed-r2\\\\helpers\\\\private_heat_tree_r1.py': 'x'}\n",
     "PINS = {'atlas_tectonics/_private/private_heat_tree_r1.py': 'x'}\n"),
    ('lower-case _identity attribute',
     "ROOT = 'C:\\\\w\\\\heat-repair\\\\src\\\\atlas_tectonics'\n",
     "from atlas_tectonics import _identity\nROOT = _identity.package_dir\n"),
    ('relative import inside the package',
     "import private_heat_tree_r1 as T\n",
     "from . import private_heat_tree_r1 as T\n"),
    ('module name in str with private prefix, slash form',
     "NAME = 'private_heat_tree_r1.py'\n",
     "NAME = 'atlas_tectonics/_private/private_heat_tree_r1.py'\n"),
]
for name, orig, folded in CASES:
    print('%-52s ast_equivalent=%s' % (name, P.ast_equivalent(orig, folded)))
