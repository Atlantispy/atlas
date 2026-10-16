"""AST gate FALSE PASSES: code changes that ast_equivalent accepts."""
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

S1, S2 = sha256(b'seed one').hexdigest(), sha256(b'seed two').hexdigest()

CASES = [
    ('abs data path swapped to another file',
     "import json\nCOEFFS = json.load(open('C:\\\\w\\\\composed-r2\\\\data\\\\conductivity_v1.json'))\n",
     "import json\nCOEFFS = json.load(open('C:\\\\w\\\\composed-r2\\\\data\\\\conductivity_v2.json'))\n"),
    ('abs data path -> any _identity.UPPER constant',
     "import json\nCOEFFS = json.load(open('C:\\\\w\\\\composed-r2\\\\data\\\\conductivity_v1.json'))\n",
     "import json\nfrom atlas_tectonics import _identity\nCOEFFS = json.load(open(_identity.OTHER_TABLE))\n"),
    ('"/" separator literal changed',
     "def key(p):\n    return p.replace('\\\\', '/')\n",
     "def key(p):\n    return p.replace('\\\\', '/x/')\n"),
    ('hex64 RNG seed changed (data, not a pin)',
     "import numpy as np\nRNG = np.random.default_rng(int('%s', 16))\n" % S1,
     "import numpy as np\nRNG = np.random.default_rng(int('%s', 16))\n" % S2),
    ('hex64 expected-digest refusal check changed',
     "def ok(d):\n    return d == '%s'\n" % S1,
     "def ok(d):\n    return d == '%s'\n" % S2),
    ('_identity import aliased onto an existing name (shadows DEBUG)',
     "DEBUG = False\ndef f(x):\n    return x + 1 if DEBUG else x\n",
     "DEBUG = False\nfrom atlas_tectonics import _identity as DEBUG\ndef f(x):\n    return x + 1 if DEBUG else x\n"),
    ('import atlas_tectonics._identity as <existing alias>',
     "import numpy as np\ndef f(x):\n    return np.sum(x)\n",
     "import numpy as np\nimport atlas_tectonics._identity as np\ndef f(x):\n    return np.sum(x)\n"),
    ('key call: callee of str(X(p).resolve()) swapped',
     "from pathlib import Path\ndef k(p):\n    return str(Path(p).resolve())\n",
     "from pathlib import Path\ndef k(p):\n    return str(Path.home().joinpath(p).resolve())\n"),
    ('key call: keywords on _identity.relkey dropped',
     "from pathlib import Path\ndef k(p):\n    return str(Path(p).resolve())\n",
     "from pathlib import Path\nfrom atlas_tectonics import _identity\ndef k(p):\n    return _identity.relkey(p, base='C:\\\\elsewhere')\n"),
    ("literal '<PATH>' already in the original",
     "MARK = '<PATH>'\n", "MARK = 'C:\\\\anything'\n"),
]
for name, orig, folded in CASES:
    print('%-62s ast_equivalent=%s' % (name, P.ast_equivalent(orig, folded)))

# show the shadowing case really changes behaviour (stub _identity module, no package needed)
import types  # noqa: E402
pkg = types.ModuleType('atlas_tectonics')
pkg._identity = types.ModuleType('atlas_tectonics._identity')
sys.modules['atlas_tectonics'], sys.modules['atlas_tectonics._identity'] = pkg, pkg._identity
for label, src in (('original', CASES[5][1]), ('folded', CASES[5][2])):
    ns = {}
    exec(src, ns)
    print('  shadow case %-8s f(10) = %s' % (label, ns['f'](10)))
