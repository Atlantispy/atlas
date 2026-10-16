import ast, os, re, sys, json
H = sys.argv[1]
seeds = sys.argv[2].split(",")
stdlib = set(sys.stdlib_module_names)
helpers = {f[:-3] for f in os.listdir(H) if f.endswith(".py")}
pat = re.compile(r"(?i)(the-diadem|users[/\\]LOCAL_USER|fidelity-integration|composed-r\d|resumability-r1|[A-Z]:[/\\]\w)")
seen, order, edges, sus, sizes, test_like = set(), [], {}, {}, {}, []
stack = list(seeds)
while stack:
    m = stack.pop()
    if m in seen or m not in helpers: continue
    seen.add(m); order.append(m)
    src = open(os.path.join(H, m + ".py"), encoding="utf-8").read()
    sizes[m] = src.count("\n")
    deps = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import): names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module: names = [n.module]
        else: continue
        for x in names:
            top = x.split(".")[0]
            if top in helpers: deps.add(top)
    # dynamic loads by file name
    for x in re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)\.py['\"]", src):
        if x in helpers: deps.add(x)
    edges[m] = sorted(deps)
    stack.extend(deps)
    hits = [f"{i}: {l.strip()[:100]}" for i, l in enumerate(src.splitlines(), 1) if pat.search(l)]
    if hits: sus[m] = hits
missing = sorted(set(seeds) - helpers)
print("seeds", len(seeds), "missing-from-helpers", missing)
print("closure", len(seen), "lines", sum(sizes.values()))
print("closure modules:", ", ".join(sorted(seen)))
print("with path/private strings:", len(sus))
for m in sorted(sus): print(" ", m, len(sus[m]), "|", sus[m][0])
json.dump({"closure": sorted(seen), "edges": edges, "sizes": sizes, "sus": sus}, open(os.path.join(os.path.dirname(H.rstrip('/')), "..", "x"), "w") if False else open(sys.argv[3], "w"), indent=0)
