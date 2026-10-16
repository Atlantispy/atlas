import json, sys
from pathlib import Path
layout = Path(sys.argv[1]).resolve()
sys.path[:0] = json.loads((layout/'control.json').read_text(encoding='utf8'))['paths']
import private_heat_native_issuer_r13 as I
names = sorted(Path(p).name for p, _ in I._IMPORTED_SOURCES)
print(layout.name, 'sources', len(names), 'compiled helper listed:', any('compiled_dot' in n for n in names), 'modules in walk', len(I._private_modules()))
json.dump(names, open(sys.argv[2], 'w'))
