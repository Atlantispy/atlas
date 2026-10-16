import hashlib, json, os, subprocess, sys
T = r"C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
A = r"C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas"
F = T + "/fidelity-integration-20261005"
R = F + "/continuation-repair-20261013/optimisation-20261014/resumability-r1"
DIRS = {
    "S": R + "/composed-r2/src/atlas_tectonics",
    "RC1": R + "/composed-r1/runtime-src/atlas_tectonics",
    "H": F + "/heat-repair-20261007/source/tectonics/src/atlas_tectonics",
    "F0": F + "/source/tectonics/src/atlas_tectonics",
}
COMMITS = {"R7": "c856236", "I03": "30a79e6", "HEAD": "1a58e0b"}
def norm(b): return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()[:12]
out = {}
for k, d in DIRS.items():
    m = {}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f.endswith((".pyc",)): continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d).replace("\\", "/")
            m[rel] = norm(open(p, "rb").read())
    out[k] = m
for k, c in COMMITS.items():
    ls = subprocess.run(["git", "-C", A, "ls-tree", "-r", c, "tectonics/src/atlas_tectonics"], capture_output=True, text=True).stdout.splitlines()
    m = {}
    for line in ls:
        meta, path = line.split("\t", 1)
        blob = meta.split()[2]
        data = subprocess.run(["git", "-C", A, "cat-file", "blob", blob], capture_output=True).stdout
        rel = path[len("tectonics/src/atlas_tectonics/"):]
        m[rel] = norm(data)
    out[k] = m
json.dump(out, open(sys.argv[1], "w"), indent=0)
for k, m in out.items(): print(k, len(m))
