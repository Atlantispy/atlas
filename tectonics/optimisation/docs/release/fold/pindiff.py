"""Classify H-vs-S differences of pinned package files by top-level and class-level definition."""
import ast, hashlib, json, sys
from pathlib import Path

def defs(path):
    text = Path(path).read_bytes().replace(b'\r\n', b'\n').decode('utf-8')
    tree = ast.parse(text)
    out = {}
    def walk(nodes, prefix):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + n.name
                out[name] = hashlib.sha256(ast.dump(n).encode()).hexdigest()[:12]
                if isinstance(n, ast.ClassDef):
                    walk(n.body, name + '.')
            elif isinstance(n, (ast.Assign, ast.AnnAssign)) and not prefix:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        out['=' + t.id] = hashlib.sha256(ast.dump(n).encode()).hexdigest()[:12]
            elif isinstance(n, (ast.Import, ast.ImportFrom)) and not prefix:
                out['import:' + ast.unparse(n)] = 'i'
    walk(tree.body, '')
    return out

hroot, sroot, names = sys.argv[1], sys.argv[2], sys.argv[3:]
report = {}
for name in names:
    h, s = defs(f'{hroot}/{name}.py'), defs(f'{sroot}/{name}.py')
    report[name] = dict(
        added=sorted(k for k in s if k not in h),
        removed=sorted(k for k in h if k not in s),
        changed=sorted(k for k in h if k in s and h[k] != s[k]))
json.dump(report, sys.stdout, indent=1)
