"""Pin consistency in le (before L1) and lf (after L1); stale-digest scan; transform reproduces lf."""
import re, sys
from hashlib import sha256
from pathlib import Path
HS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HS/'transforms'))
import l1_low_ledger_op as X
le, lf = HS/'le'/'helpers', HS/'lf'/'helpers'
def shas(d):
    return {p.name: sha256(p.read_bytes()).hexdigest() for p in d.iterdir() if p.is_file()}
a, b = shas(le), shas(lf)
changed = sorted(n for n in a if a[n] != b.get(n))
print('changed le->lf:', changed)
print('only in one:', sorted(set(a) ^ set(b)))
old_digests = {a[n]: n for n in changed}
pin = re.compile(r"""['"]([\w.]+\.py)['"]\s*:\s*['"]([0-9a-f]{64})['"]""")
bad = 0
for p in sorted(lf.iterdir()):
    if not p.is_file():
        continue
    text = p.read_bytes().decode('utf8', 'replace')
    for m in re.finditer(r'[0-9a-f]{64}', text):
        if m.group(0) in old_digests:
            print('STALE digest of', old_digests[m.group(0)], 'in', p.name); bad += 1
    for name, dig in pin.findall(text):
        if name in b and b[name] != dig and name in changed:
            print('MISMATCH pin', p.name, name, dig[:12], 'actual', b[name][:12]); bad += 1
print('stale/mismatch count', bad)
src = (le/'private_heat_low_ledger_inventory_r1.py').read_bytes().decode('utf8')
out = X.transform(src)
print('transform(le) == lf low_ledger:', out.encode('utf8') == (lf/'private_heat_low_ledger_inventory_r1.py').read_bytes())
# Re-run the cascade in memory on le copies and compare with lf
files = {n: (le/n).read_bytes().decode('utf8') for n in a}
files['private_heat_low_ledger_inventory_r1.py'] = out
log = X.repin_cascade(lambda n: files[n], lambda n, t: files.__setitem__(n, t))
diff = [n for n in files if files[n].encode('utf8') != (lf/n).read_bytes()]
print('in-memory cascade vs lf differing files:', diff)
for pinner, _ in X.CASCADE:
    x, y = (le/pinner).read_bytes().decode('utf8').splitlines(), files[pinner].splitlines()
    print(pinner, 'lines changed', sum(1 for i, j in zip(x, y) if i != j), 'line counts', len(x), len(y))
