"""RF2 evidence: private workspace names in a folded tree that the line-based USER_PATH scan cannot see.

    python -B private_literals.py FOLDED_ROOT OUT_JSON

Lists, per .py file under FOLDED_ROOT, every str constant (docstrings included) and every comment that names a dated
workspace folder (a lower-case hyphenated name ending in -20YYMMDD, such as fidelity-integration-20261005), and every
str constant whose value parity v2.4's USER_PATH matches (the scan gate reads source lines, where escapes differ from
values). Constants are code a published package would carry; comments are text only. Exit 1 when any dated workspace
name is found in a constant or a comment (refuter r3: a relative workspace key the fold did not classify names one);
the USER_PATH constants are evidence only (the fold's scan gate carries FP:999 and FP:1006). OUT_JSON must not exist.
"""
import ast
import io
import json
from pathlib import Path
import re
import sys
import tokenize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'v24'))
import parity as PC  # noqa: E402  USER_PATH and WINDOWS_PREFIXES, as the fold's scan gate uses them

DATED = re.compile(r'(?<![\w-])[a-z][a-z0-9]*(?:-[a-z0-9]+)*-20\d{6}(?![\w])')
root, out = Path(sys.argv[1]), Path(sys.argv[2])
if not root.is_dir() or not any(root.rglob('*.py')):
    sys.exit('no folded tree at %s' % root)
rows = dict(constants=[], comments=[], user_path_constants=[])
for path in sorted(root.rglob('*.py')):
    rel = path.relative_to(root).as_posix()
    text = path.read_bytes().decode('utf8')
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for m in sorted(set(DATED.findall(node.value))):
                rows['constants'].append([rel, node.lineno, m])
            hit = PC.USER_PATH.search(node.value)
            if hit and node.value not in PC.WINDOWS_PREFIXES:
                rows['user_path_constants'].append([rel, node.lineno, node.value[max(0, hit.start() - 20):hit.end() + 20]])
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            for m in sorted(set(DATED.findall(tok.string))):
                rows['comments'].append([rel, tok.start[0], m])
summary = {k: dict(n=len(v), files=len({r[0] for r in v}), names=sorted({r[2] for r in v})[:12])
           for k, v in rows.items() if k != 'user_path_constants'}
summary['user_path_constants'] = dict(n=len(rows['user_path_constants']),
                                      at=['%s:%d' % (r[0], r[1]) for r in rows['user_path_constants']])
with open(out, 'x', encoding='utf8', newline='\n') as f:
    json.dump(dict(root=root.name, summary=summary, rows=rows), f, indent=1)
print(json.dumps(summary))
sys.exit(1 if rows['constants'] or rows['comments'] else 0)
