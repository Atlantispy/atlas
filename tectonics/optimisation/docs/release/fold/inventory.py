"""Inventory of the rewrite sites the fold transformer must handle (read-only AST scan).

  python -B inventory.py HELPERS_DIR OUT_JSON [TRACE_JSON]

For every non-test helper (or only the trace-loaded ones, given TRACE_JSON), it counts and locates:
  helper_imports    `import H [as K]` / `from H import y` where H is a helper module in HELPERS_DIR
  string_modules    calls whose first argument is a string naming a helper module (import_module, find_spec, ...)
  abs_literals      string constants that are absolute paths
  file_anchors      uses of __file__ (key and pin construction start from these)
  key_builds        str(Path(x).resolve()) and str(x.resolve()) calls
  read_by_key       Path(k).read_bytes()/read_text()/open() where k is a loop/key variable, not __file__
  star_or_relative  `from H import *` and relative imports (the transformer must refuse or special-case them)
"""
import ast
import json
from pathlib import Path
import sys


def scan(path, helpers):
    tree = ast.parse(path.read_text(encoding='utf8'))
    out = {k: [] for k in ('helper_imports', 'string_modules', 'abs_literals', 'file_anchors', 'key_builds',
                           'read_by_key', 'star_or_relative')}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in helpers:
                    out['helper_imports'].append([node.lineno, alias.name, alias.asname])
        elif isinstance(node, ast.ImportFrom):
            if node.level or any(a.name == '*' for a in node.names):
                out['star_or_relative'].append([node.lineno, '.' * node.level + (node.module or ''),
                                                [a.name for a in node.names]])
            if node.module and node.module.split('.')[0] in helpers:
                out['helper_imports'].append([node.lineno, node.module, [a.name for a in node.names]])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if len(text) > 3 and (text[1:3] in (':\\', ':/') or text.startswith('\\\\')):
                out['abs_literals'].append([node.lineno, text[-60:]])
        elif isinstance(node, ast.Name) and node.id == '__file__':
            out['file_anchors'].append(node.lineno)
        elif isinstance(node, ast.Call):
            f = node.func
            if (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and node.args[0].value.split('.')[0] in helpers):
                out['string_modules'].append([node.lineno, ast.unparse(f), node.args[0].value])
            if (isinstance(f, ast.Name) and f.id == 'str' and len(node.args) == 1 and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == 'resolve'):
                out['key_builds'].append([node.lineno, ast.unparse(node)[:80]])
            if isinstance(f, ast.Attribute) and f.attr in ('read_bytes', 'read_text', 'open'):
                target = ast.unparse(f.value)
                if '__file__' not in target and 'HERE' not in target and target not in ('path', 'self'):
                    out['read_by_key'].append([node.lineno, ast.unparse(node)[:80]])
    return {k: v for k, v in out.items() if v}


def main(helpers_dir, out_json, trace_json=None):
    helpers_dir = Path(helpers_dir)
    helpers = {p.stem for p in helpers_dir.glob('*.py')}
    names = sorted(p.stem for p in helpers_dir.glob('*.py') if not p.stem.startswith('test_'))
    if trace_json:
        loaded = json.loads(Path(trace_json).read_text(encoding='utf8'))['modules']
        names = sorted(n for n, m in loaded.items() if m['root'] == 'helpers')
    report = {name: scan(helpers_dir/(name + '.py'), helpers) for name in names}
    totals = {}
    for sites in report.values():
        for kind, rows in sites.items():
            totals[kind] = totals.get(kind, 0) + len(rows)
    Path(out_json).write_text(json.dumps(dict(modules=len(names), totals=totals, sites=report), indent=1,
                                         sort_keys=True), encoding='utf8')
    print(json.dumps(dict(modules=len(names), totals=totals,
                          with_abs_literals=sorted(n for n, s in report.items() if 'abs_literals' in s),
                          with_star_or_relative=sorted(n for n, s in report.items() if 'star_or_relative' in s))))


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
