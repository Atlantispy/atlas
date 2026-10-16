import json, sys
from pathlib import Path
layout = Path(sys.argv[1]).resolve()
sys.path[:0] = json.loads((layout/'control.json').read_text(encoding='utf8'))['paths']
import private_heat_functionals_parallel_r1 as PAR
import private_heat_certification_kernel_r1 as K
import private_heat_functionals_kernel_r1 as FK
before = PAR._files()
n = len(sys.modules)
assert K._h3_module() is not None
after = PAR._files()
fresh = {p: d for p, d in after.items() if p not in before}
print('modules added by first H3 load:', len(sys.modules) - n, '; new tracked files:', [Path(p).name for p in fresh])
places = Path(FK.__file__).resolve().parent, Path(PAR._clone())
print('caller _unlike(worker loaded) when caller lacks the helper:', PAR._unlike(fresh, dict(before), *places))
print('caller _unlike when caller already has it:', PAR._unlike(fresh, dict(after), *places))
print('_confirm style compare own-vs-caller-table mismatches:', sorted(Path(p).name for p, d in after.items() if p in before and before[p] != d))
