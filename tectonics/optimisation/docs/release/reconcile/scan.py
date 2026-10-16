import ast, json, os, re, sys
t = json.load(open(sys.argv[1]))
S = sys.argv[2]
targets = sorted(f for f in t["S"] if f.endswith(".py") and t["S"][f] != t["HEAD"].get(f))
stdlib = set(sys.stdlib_module_names)
third = {"numpy", "scipy", "shapely", "numba", "llvmlite", "gmpy2", "mpmath", "sympy", "psutil"}
pat = re.compile(r"(?i)(the-diadem|users[/\\]LOCAL_USER|fidelity-integration|composed-r\d|resumability-r1|continuation-repair|optimisation-2026|\.atlas-dev|codex|[A-Z]:[/\\])")
ext, sus = {}, {}
for f in targets:
    src = open(os.path.join(S, f), encoding="utf-8").read()
    tree = ast.parse(src)
    for n in ast.walk(tree):
        mods = []
        if isinstance(n, ast.Import): mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module: mods = [n.module]
        for m in mods:
            top = m.split(".")[0]
            if top in stdlib or top in third or top == "atlas_tectonics": continue
            ext.setdefault(f, set()).add(f"{m}@{n.lineno}")
    for i, line in enumerate(src.splitlines(), 1):
        if pat.search(line):
            sus.setdefault(f, []).append(f"{i}: {line.strip()[:110]}")
print("NON-PACKAGE IMPORTS (outside stdlib/known third-party):")
for f, s in sorted(ext.items()): print(" ", f, sorted(s))
print("PATH/PRIVATE STRINGS:")
for f, s in sorted(sus.items()):
    print(" ", f, len(s)); [print("     ", x) for x in s[:4]]
