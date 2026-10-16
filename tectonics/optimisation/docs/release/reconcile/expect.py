"""Changed test assertions, remake 1a58e0b vs heat-repair (H) tests; also says which tree first changed each file (F0 or H)."""
import difflib, json, pathlib, re, sys
rm, f0, h, out = map(pathlib.Path, sys.argv[1:5])
rd = lambda p: p.read_text(encoding='utf-8').replace('\r\n', '\n').splitlines() if p.exists() else None
KEY = re.compile(r'assert|expectedFailure|skip|Raises|allow_cell_mean|fail\(')
res = {}
for p in sorted(rm.glob('test_*.py')):
    a, b, c = rd(p), rd(f0 / p.name), rd(h / p.name)
    if c is None or a == c:
        continue
    origin = 'F0' if b is not None and b != a else 'H'
    rem = [l.strip() for l in difflib.unified_diff(a, c, n=0, lineterm='') if l.startswith('-') and not l.startswith('---') and KEY.search(l)]
    add = [l.strip() for l in difflib.unified_diff(a, c, n=0, lineterm='') if l.startswith('+') and not l.startswith('+++') and KEY.search(l)]
    n = sum(1 for l in difflib.unified_diff(a, c, n=0, lineterm='') if l[:1] in '+-' and l[:3] not in ('+++', '---'))
    res[p.name] = dict(origin=origin, changed_lines=n, removed_asserts=rem, added_asserts=add)
json.dump(res, open(out, 'w'), indent=1)
for k, v in res.items():
    print(f"{k:45s} {v['origin']:3s} lines={v['changed_lines']:4d} -assert={len(v['removed_asserts']):3d} +assert={len(v['added_asserts']):3d}")
