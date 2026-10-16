"""Read-only: which helper files pin which other helper files by sha256.

usage: pin_graph.py <helpers dir> <target name> [<target name> ...]
Prints the reverse-transitive closure (every file whose pinned digest changes
when the targets change), with the pin path, plus importers of each target.
"""
import hashlib
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
targets = sys.argv[2:]
files = sorted(p for p in root.iterdir() if p.suffix == '.py' or p.suffix == '.json')
digest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
by_digest = {}
for n, d in digest.items():
    by_digest.setdefault(d, []).append(n)
hexre = re.compile(r'\b[0-9a-f]{64}\b')
pins = {}      # file -> set(pinned names)
for p in files:
    text = p.read_text(encoding='utf-8', errors='replace')
    s = set()
    for h in hexre.findall(text):
        for n in by_digest.get(h, ()):
            if n != p.name:
                s.add(n)
    pins[p.name] = s
rev = {}
for f, s in pins.items():
    for n in s:
        rev.setdefault(n, set()).add(f)
seen, frontier = {}, list(targets)
for t in targets:
    seen[t] = None
while frontier:
    n = frontier.pop()
    for f in sorted(rev.get(n, ())):
        if f not in seen:
            seen[f] = n
            frontier.append(f)
print('pin closure (file <- pins <- ...):')
for f, via in seen.items():
    if via is None:
        continue
    print(f'  {f}  pins  {via}')
print(len(seen) - len(targets), 'files change digest by pin rewrite')
imp = re.compile(r'^\s*(?:import|from)\s+(private_heat_\w+)', re.M)
for t in targets:
    mod = t[:-3]
    users = sorted(p.name for p in files if p.suffix == '.py' and re.search(r'\b' + mod + r'\b', p.read_text(encoding='utf-8', errors='replace')) and p.name != t)
    print(f'importers/mentions of {mod}: {len(users)}')
    for u in users:
        print('   ', u)
