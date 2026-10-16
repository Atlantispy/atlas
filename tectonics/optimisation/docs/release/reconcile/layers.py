import ast, json, os, sys
t = json.load(open(sys.argv[1])); S = sys.argv[2]; H = sys.argv[3]
helpers = {f[:-3] for f in os.listdir(H) if f.endswith(".py")}
pkg = {f[:-3] for f in t["S"] if f.endswith(".py") and "/" not in f}
changed = {f[:-3] for f in t["S"] if f.endswith(".py") and f in t["HEAD"] and t["S"][f] != t["HEAD"][f]}
new = {f[:-3] for f in t["S"] if f.endswith(".py") and f not in t["HEAD"]}
work = changed | new
deps, hdeps, lazy = {}, {}, {}
for m in sorted(work):
    src = open(os.path.join(S, m + ".py"), encoding="utf-8").read(); tree = ast.parse(src)
    top = set(id(n) for n in tree.body)
    d, h, lz = set(), set(), set()
    for n in ast.walk(tree):
        names = []
        if isinstance(n, ast.ImportFrom):
            if n.level == 1: names = [n.module.split(".")[0]] if n.module else [a.name for a in n.names]
            elif n.module and n.module.split(".")[0] in helpers: h.add(n.module.split(".")[0])
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in helpers: h.add(a.name.split(".")[0])
        for x in names:
            if x in pkg and x != m:
                d.add(x)
                if id(n) not in top: lz.add(x)
    deps[m] = d & work; hdeps[m] = h; lazy[m] = lz & work
# layering over work-set deps (ignore cycles by SCC collapse)
import itertools
idx, low, st, on, sccs, c = {}, {}, [], set(), [], itertools.count()
def sc(v):
    idx[v] = low[v] = next(c); st.append(v); on.add(v)
    for w in deps[v]:
        if w not in idx: sc(w); low[v] = min(low[v], low[w])
        elif w in on: low[v] = min(low[v], idx[w])
    if low[v] == idx[v]:
        comp = set()
        while True:
            w = st.pop(); on.discard(w); comp.add(w)
            if w == v: break
        sccs.append(comp)
sys.setrecursionlimit(10000)
for v in sorted(work):
    if v not in idx: sc(v)
comp_of = {v: i for i, s in enumerate(sccs) for v in s}
level = {}
for i, s in enumerate(sccs):  # tarjan emits in reverse topological order (deps first)
    level[i] = 1 + max([level[comp_of[w]] for v in s for w in deps[v] if comp_of[w] != i] or [0])
by = {}
for i, s in enumerate(sccs):
    for v in s: by.setdefault(level[i], []).append(v)
for L in sorted(by):
    print(f"L{L}:", ", ".join(("*" if v in changed else "") + v + ("[H]" if hdeps[v] else "") for v in sorted(by[L])))
print("cycles:", [sorted(s) for s in sccs if len(s) > 1])
json.dump({"deps": {k: sorted(v) for k, v in deps.items()}, "hdeps": {k: sorted(v) for k, v in hdeps.items()}, "levels": {v: L for L in by for v in by[L]}}, open(sys.argv[4], "w"), indent=0)
