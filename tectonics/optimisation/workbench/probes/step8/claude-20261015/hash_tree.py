"""Hash every file under the given roots (non-recursive for C, selected R files).

Usage: python -B hash_tree.py OUT.json [--compare PREV.json]

Records SHA-256, size and mtime so later checks can detect any change made by
another writer (brief rule: stop if a file changes that this chat did not change).
"""
import hashlib
import json
import os
import sys

R = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
C = os.path.join(R, "compact-geometry-r1")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snapshot():
    out = {}
    for root in (C,):
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                st = os.stat(p)
                out[os.path.relpath(p, R).replace("\\", "/")] = {
                    "sha256": sha(p), "size": st.st_size, "mtime": st.st_mtime}
    for name in sorted(os.listdir(R)):
        p = os.path.join(R, name)
        if os.path.isfile(p):
            st = os.stat(p)
            out[name] = {"sha256": sha(p), "size": st.st_size, "mtime": st.st_mtime}
    tr = os.path.join(R, "test-results")
    for name in sorted(os.listdir(tr)):
        p = os.path.join(tr, name)
        if os.path.isfile(p):
            st = os.stat(p)
            out["test-results/" + name] = {"sha256": sha(p), "size": st.st_size, "mtime": st.st_mtime}
    return out


def main():
    out_path = sys.argv[1]
    snap = snapshot()
    if len(sys.argv) > 3 and sys.argv[2] == "--compare":
        with open(sys.argv[3], "r", encoding="utf-8") as f:
            prev = json.load(f)
        changed = sorted(k for k in snap if k in prev and snap[k]["sha256"] != prev[k]["sha256"])
        added = sorted(k for k in snap if k not in prev)
        removed = sorted(k for k in prev if k not in snap)
        print(json.dumps({"changed": changed, "added": added, "removed": removed}, indent=1))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1, sort_keys=True)
    print("files:", len(snap))


if __name__ == "__main__":
    main()
