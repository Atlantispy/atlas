import ast, hashlib, json, os, subprocess, sys
SP = sys.argv[1]
T = r"C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
A = r"C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas"
F = T + "/fidelity-integration-20261005"
R = F + "/continuation-repair-20261013/optimisation-20261014/resumability-r1"
D = {"X": SP + "/x/tectonics/src/atlas_tectonics", "F0": F + "/source/tectonics/src/atlas_tectonics",
     "H": F + "/heat-repair-20261007/source/tectonics/src/atlas_tectonics",
     "RC1": R + "/composed-r1/runtime-src/atlas_tectonics", "S": R + "/composed-r2/src/atlas_tectonics"}
def rd(k, f):
    if k == "HEAD":
        r = subprocess.run(["git", "-C", A, "show", "1a58e0b:tectonics/src/atlas_tectonics/" + f], capture_output=True)
        return r.stdout.replace(b"\r\n", b"\n") if r.returncode == 0 else None
    p = os.path.join(D[k], f)
    return open(p, "rb").read().replace(b"\r\n", b"\n") if os.path.exists(p) else None
def defs(src):
    out = {}
    if src is None: return out
    tree = ast.parse(src); text = src.decode("utf-8")
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out[n.name + "." + m.name] = hashlib.sha1(ast.get_source_segment(text, m).encode()).hexdigest()
                out[n.name + "<cls>"] = hashlib.sha1("".join(ast.get_source_segment(text, b) or "" for b in n.body if not isinstance(b,(ast.FunctionDef,ast.AsyncFunctionDef))).encode()).hexdigest()
            else:
                out[n.name] = hashlib.sha1(ast.get_source_segment(text, n).encode()).hexdigest()
        else:
            seg = ast.get_source_segment(text, n) or ""
            out.setdefault("<module>", "")
            out["<module>"] = hashlib.sha1((out["<module>"] + seg).encode()).hexdigest()
    return out
def changed(a, b):
    da, db = defs(a), defs(b)
    mod = sorted(k for k in set(da) & set(db) if da[k] != db[k])
    return {"modified": mod, "added": sorted(set(db) - set(da)), "removed": sorted(set(da) - set(db))}
def numstat(a, b, name):
    pa, pb = os.path.join(SP, "tmp_a.py"), os.path.join(SP, "tmp_b.py")
    open(pa, "wb").write(a or b""); open(pb, "wb").write(b or b"")
    r = subprocess.run(["git", "diff", "--no-index", "--numstat", pa, pb], capture_output=True, text=True).stdout.split()
    return (int(r[0]), int(r[1])) if r else (0, 0)
FILES = sys.argv[2].split(",")
res = {}
for f in FILES:
    v = {k: rd(k, f) for k in ["X", "HEAD", "F0", "H", "RC1", "S"]}
    h = {k: (hashlib.sha256(b).hexdigest()[:8] if b is not None else None) for k, b in v.items()}
    s_line = [h["F0"], h["H"], h["RC1"], h["S"]]
    if h["HEAD"] in s_line:
        base, kind = "HEAD", "S-forward"
    elif h["S"] == h["X"] or h["S"] in (h["X"],):
        base, kind = "X", "HEAD-forward"
    else:
        base, kind = "X", "both"
    B = v[base] if base != "X" else v["X"]
    e = {"kind": kind, "base": base, "hash": h,
         "head_vs_base": numstat(B, v["HEAD"], f) if kind == "both" else None,
         "s_vs_base": numstat(B, v["S"], f),
         "steps": {f"{a}->{b}": numstat(v[a], v[b], f) for a, b in [("X","F0") if kind=="both" else ("HEAD","F0"), ("F0","H"), ("H","RC1"), ("RC1","S")] if h[a] != h[b]},
         "s_defs": changed(B, v["S"])}
    if kind == "both":
        e["head_defs"] = changed(B, v["HEAD"])
        # does S already contain HEAD's change? trial 3-way merge in scratch
        for k, nm in [("X","base"),("HEAD","ours"),("S","theirs")]:
            open(os.path.join(SP, "m_" + nm + ".py"), "wb").write(v[k] or b"")
        r = subprocess.run(["git", "merge-file", "-p", os.path.join(SP,"m_ours.py"), os.path.join(SP,"m_base.py"), os.path.join(SP,"m_theirs.py")], capture_output=True)
        merged = r.stdout
        e["merge_conflicts"] = r.returncode
        e["merge_equals_S"] = merged == v["S"]
        e["overlap_defs"] = sorted(set(e["head_defs"]["modified"]) & set(e["s_defs"]["modified"]))
        # does F0 contain HEAD's change already? (merge X,HEAD,F0 == F0)
        open(os.path.join(SP,"m_theirs.py"),"wb").write(v["F0"])
        r2 = subprocess.run(["git", "merge-file", "-p", os.path.join(SP,"m_ours.py"), os.path.join(SP,"m_base.py"), os.path.join(SP,"m_theirs.py")], capture_output=True)
        e["F0_merge_conflicts"] = r2.returncode; e["F0_contains_HEAD"] = r2.stdout == v["F0"]
    res[f] = e
json.dump(res, open(os.path.join(SP, "three.json"), "w"), indent=1)
for f, e in res.items():
    line = f"{f:34} {e['kind']:11} base={e['base']:4} S+/-{e['s_vs_base']}"
    if e["kind"] == "both":
        line += f" HEAD+/-{e['head_vs_base']} conflicts={e['merge_conflicts']} mergeEqS={e['merge_equals_S']} F0hasHEAD={e['F0_contains_HEAD']}/{e['F0_merge_conflicts']} overlap={e['overlap_defs']}"
    print(line)
