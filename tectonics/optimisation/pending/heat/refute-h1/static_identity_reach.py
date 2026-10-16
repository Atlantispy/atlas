"""Static approximation of private_heat_native_issuer_r13._private_modules(): is exact_growth in
the LoadedIdentity set? Follows top-level `import private_heat_*` bindings (what vars(module) sees)."""
import ast
import re
from pathlib import Path

H = Path(__file__).resolve().parents[1]/'lw'/'helpers'


def top_imports(name):
    p = H/(name+'.py')
    if not p.exists():
        return set()
    out = set()
    for node in ast.parse(p.read_text(encoding='utf8')).body:
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name.startswith('private_heat_')}
    return out


seen, path, pending = set(), {}, [('private_heat_native_issuer_r13', None)]
while pending:
    name, parent = pending.pop()
    if name in seen:
        continue
    seen.add(name)
    path[name] = parent
    pending.extend((child, name) for child in top_imports(name))
target = 'private_heat_exact_growth_r1'
print('top-level import closure size:', len(seen), '| exact_growth reachable:', target in seen)
chain, cur = [], target
while cur in path and cur:
    chain.append(cur)
    cur = path[cur]
print('chain:', ' <- '.join(chain))
src = (H/'private_heat_forward_kernel_r13.py').read_text(encoding='utf8')
print('forward_kernel_r13 _SOURCES mentions exact_growth:', bool(re.search('exact_growth', src)))
