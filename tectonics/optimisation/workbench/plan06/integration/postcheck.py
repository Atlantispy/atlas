"""Inspect produced source bytes and bounded delta; no runtime imports."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
target = HERE / "composed-r6"
def h(path):
    return sha256(path.read_bytes()).hexdigest()
reviewed_path = HERE / "reviewed-d5-r1.json"
if h(reviewed_path) != "ce4559e24e6cc7585ef944a3d7be367f7d23c5eb71ceafae04fcde2f81009cb4":
    raise ValueError("reviewed record changed")
reviewed = json.loads(reviewed_path.read_bytes())
manifest_path = target / "composition.json"
manifest = json.loads(manifest_path.read_bytes())
basepath = T / "ac/plan02/composed-r3-out/composed-r3/composition.json"
if h(basepath) != "96c363b812bb986009399df49f8a7c8d1b60bdfb3d57395ff90a886f3d68ac1e":
    raise ValueError("baseline record changed")
base = json.loads(basepath.read_bytes())
expected = {"src/" + k: v for k, v in reviewed["outputs"].items()}
expected.update({"helpers/" + k: v["sha256"] for k, v in reviewed["helpers"].items()})
actual = {p.relative_to(target).as_posix(): h(p) for p in target.rglob("*") if p.is_file() and p != manifest_path}
changed = sorted(k for k in base["outputs"] if reviewed["outputs"].get(k) != base["outputs"][k])
added = sorted(set(reviewed["outputs"]) - set(base["outputs"]))
checks = {
    "written_inventory": actual == expected,
    "reviewed_binding": manifest["reviewed_inputs_sha256"] == h(reviewed_path),
    "root": manifest["root"] == str(target),
    "staged": manifest["staged"] == reviewed["staged"],
    "stages": manifest["stages"] == reviewed["stages"],
    "outputs": manifest["outputs"] == reviewed["outputs"],
    "helpers": manifest["helpers"] == {k: v["sha256"] for k, v in reviewed["helpers"].items()},
    "only_wall_changed": changed == ["atlas_tectonics/integration_wall_measures.py"],
    "only_two_modules_added": added == ["atlas_tectonics/integration_exact_twin.py", "atlas_tectonics/integration_wall_measures_gmp.py"],
    "no_source_removed": set(base["outputs"]) <= set(reviewed["outputs"]),
    "baseline_helpers_unchanged": manifest["helpers"] == base["helpers"],
    "baseline_stages_unchanged": manifest["stages"][:-3] == base["stages"],
    "three_d5_stages": [row["stage"] for row in manifest["stages"][-3:]] == [
        "plan06:d5_wall_hooks", "plan06:new:integration_exact_twin.py", "plan06:new:integration_wall_measures_gmp.py"],
    "unfrozen": manifest["frozen"] is False,
}
result = {"pass": all(checks.values()), "checks": checks, "source_files": len(actual),
          "composition_sha256": h(manifest_path), "reviewed_sha256": h(reviewed_path),
          "changed": changed, "added": added, "status": "INDEPENDENT_D5_SOURCE_BUILD_NOT_PLAN31_OR_RUNTIME_PROOF"}
with (HERE / "postcheck-r1.json").open("x", encoding="utf8") as stream:
    json.dump(result, stream, indent=1, sort_keys=True)
print(json.dumps(result))
raise SystemExit(0 if result["pass"] else 1)
