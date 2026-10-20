"""Pinned retained-source D5 stage; no runtime imports or assembly execution."""
import importlib.util
import json
import os
from hashlib import sha256
from pathlib import Path

T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
HERE = Path(__file__).resolve().parent
OLD = T / "ac/s4"
NEW = T / "ac/p06r3b"
TARGET = HERE / "composed-r6"
GEN = T / "ac/plan02/GENERATION-r3.json"
STAGER = T / "ac/plan02/stager-r4/stage_r4.py"
ASSEMBLER = HERE / "assemble_r3_plan06.py"
PINS = {
    GEN: "b20a09ce7cad44dea942023dbc07c0070dcaab4d16adec0023ed7f7f3aa86be3",
    OLD / "binding-r1.json": "7f8ab85133d92cb83c208f50b2bfb4dfd2b327a013912f6bf5b57b02d08ac460",
    OLD / "stage-record.json": "092bd18b87cd524b9ff29ba173e38d126d3689a33690e790b8bec379d8c45b29",
    STAGER: "bbc9a9138e47ad1a7fa69dfac376a5860e9bb2c430fca37917ab8b7d81478039",
    ASSEMBLER: "c84f98bf62116553b92103bd16a2d6f0fbf5d027c8273f6f90ab8fadfa80f45d",
}
ASSETS = {
    "hook": (HERE.parent / "transforms/d5_wall_hooks.py",
             "fc283890c38527531b7fbd2be0ab210003e76c7ce749db89bec4de943d032f66"),
    "integration_exact_twin.py": (HERE.parent / "src/integration_exact_twin.py",
             "8cb6e809af7154e1840acc8941e61712b76c21de4bc7ad2c87714b14e1da9839"),
    "integration_wall_measures_gmp.py": (HERE.parent / "src/integration_wall_measures_gmp.py",
             "720b29e480f4fd3fe1dd842a99ad7e526cef6702b9645843b9455f494e435ffa"),
}
SELECTION = (
    "WORKING NON-CANON: independent Plan06 D5 source integration build. Select the exact retained ac/s4 "
    "binding 7f8ab851 and generation b20a09ce as the baseline of the existing assemble_r3 route, "
    "plus the explicitly pinned repaired D5 hook and two modules. This is not the current live Plan02 "
    "generation, not a selected Plan31 final build and not N9 integration or replay authority. "
    "Use the existing baseline d2 check before D5 and bind all successor bytes. Preserve every prior output."
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    raw = (json.dumps(value, indent=1, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return sha256(raw).hexdigest()


def main():
    for path, pin in {**PINS, **{p: h for p, h in ASSETS.values()}}.items():
        require(digest(path) == pin, "source pin mismatch: " + str(path))
    s = load_module(STAGER, "plan06_retained_stager")
    require(not NEW.exists() and not TARGET.exists(), "new stage/target already exists")
    for path in (NEW, TARGET):
        require(not s.linked_ancestor(path.parent), "linked destination ancestor")
        require(s.SAFE_PATH.fullmatch(str(path)) is not None, "unsafe destination")
        for protected in (OLD, s.LIVE_R, s.LIVE_I, s.LIVE_H):
            require(not s.within(path, protected) and not s.within(protected, path), "destination overlaps source")
    old_record = json.loads((OLD / "stage-record.json").read_bytes())
    old_box = Path(old_record["box"])
    box, ilink, hlink = s.layout(NEW)
    binding = json.loads((OLD / "binding-r1.json").read_bytes())
    generation = json.loads(GEN.read_bytes())
    require(binding["schema"] == s.BINDING_SCHEMA, "old binding schema differs")
    work = []
    for key, pin in binding["pins"].items():
        require(Path(key).as_posix() == key and not Path(key).is_absolute() and ".." not in Path(key).parts,
                "invalid relative binding path")
        source, dest = OLD / key, NEW / key
        require(digest(source) == pin, "retained staged source drift: " + key)
        linked = s.within(source, old_box / "composed-r1") or s.within(source, old_box.parent / "runtime-integration-r1")
        if not linked:
            require(not s.linked_ancestor(source), "unexpected source link: " + key)
        work.append((dest, source, pin, linked))
    for name, row in generation["files"].items():
        require(Path(name).name == name, "generation path escape")
        source = old_box / name
        require(not s.linked_ancestor(source) and digest(source) == row["sha256"], "retained generation drift: " + name)
        work.append((box / name, source, row["sha256"], False))
    asset_dest = {"hook": box / "geometry-growth-r1/transforms/plan06_d5_wall_hooks.py"}
    asset_dest.update({n: box / "plan06-d5" / n for n in ASSETS if n != "hook"})
    work.extend((asset_dest[n], source, pin, False) for n, (source, pin) in ASSETS.items())
    require(len({s.norm(d) for d, _, _, _ in work}) == len(work), "destination collision")
    junctions = {box / "composed-r1": s.LIVE_R / "composed-r1", ilink: s.LIVE_I, hlink: s.LIVE_H}
    for link, target in junctions.items():
        require(not s.linked_ancestor(target) and target.is_dir(), "live reference is linked or absent")
    require(digest(s.LIVE_R / "composed-r1/manifest.json") == s.RC1_MANIFEST_SHA, "RC1 manifest changed")
    resolved = s.consumer_check(NEW, box, ilink, hlink)
    folders = {p.parent for p, _, _, linked in work if not linked} | set(junctions)
    records = [NEW / n for n in ("binding-r1.json", "d5-contract.json", "stage-record.json")]
    s.length_check([d for d, _, _, _ in work] + resolved + records, folders)
    # Transform source strings only; this module imports hashlib, never the Atlas runtime.
    hook = load_module(ASSETS["hook"][0], "plan06_hook_source")
    wall_path = T / "ac/plan02/composed-r3-out/composed-r3/src/atlas_tectonics/integration_wall_measures.py"
    before = wall_path.read_bytes()
    wall_pin = "d6b7d472246af0e8a9415b01465f035c0c860c7b358126fd1bba5c0025e671e0"
    require(sha256(before).hexdigest() == wall_pin, "baseline wall changed")
    after = hook.transform(before.decode()).encode()
    contract = {"schema": "atlas.private.plan06-d5-assembly.r1", "selection": SELECTION,
                "wall_input_sha256": wall_pin, "wall_output_sha256": sha256(after).hexdigest(),
                "assets": {n: pin for n, (_, pin) in ASSETS.items()}}
    box.mkdir(parents=True)
    for link, target in junctions.items():
        s.junction(link, target)
    for dest, source, pin, linked in work:
        if linked:
            require(digest(dest) == pin, "linked bytes changed")
        else:
            s.copy(source, dest, pin)
    pins, provenance = {}, {}
    for dest, source, pin, _ in work:
        if dest.parent == box:
            continue
        key = dest.relative_to(NEW).as_posix()
        pins[key] = pin
        provenance[key] = {"location": str(source), "location_role": "composer-input"}
    selected = {"schema": s.BINDING_SCHEMA, "pins": pins, "provenance": provenance, "selection": SELECTION}
    binding_sha = write_json(NEW / "binding-r1.json", selected)
    contract_sha = write_json(NEW / "d5-contract.json", contract)
    for path, pin in {**PINS, **{p: h for p, h in ASSETS.values()}}.items():
        require(digest(path) == pin, "source changed while staging: " + str(path))
    require(all(digest(d) == h and digest(p) == h for d, p, h, _ in work), "source/staged finality failed")
    dry = s.LIVE_R / "composed-checks/d2-TEST_COMPOSITION.json"
    dry_sha = "604c7feba285ba8eb4bf4c401a20c3c0dbce484bca0453ea0d393ed4a84659d0"
    require(digest(dry) == dry_sha, "dry record changed")
    common = ["--root", str(box), "--generation", str(GEN), "--generation-sha256", PINS[GEN],
              "--input-binding", str(NEW / "binding-r1.json"), "--input-binding-sha256", binding_sha,
              "--target", str(TARGET), "--d5-contract", str(NEW / "d5-contract.json"),
              "--d5-contract-sha256", contract_sha]
    record = {"schema": "atlas.private.plan06-d5-stage.r1", "selection": SELECTION, "box": str(box),
              "sources": {str(p): h for p, h in PINS.items()}, "assets": {n: {"path": str(p), "sha256": h} for n, (p, h) in ASSETS.items()},
              "copied": sum(not linked for _, _, _, linked in work), "linked": sum(linked for _, _, _, linked in work),
              "binding_sha256": binding_sha, "contract_sha256": contract_sha, "assembler": str(ASSEMBLER),
              "target": str(TARGET), "common_argv": common,
              "pin_argv": ["--pin"] + common + ["--reviewed", str(HERE / "reviewed-d5-r1.json"), "--dry", str(dry), "--dry-sha256", dry_sha]}
    write_json(NEW / "stage-record.json", record)
    print(json.dumps({"pass": True, "stage_record": str(NEW / "stage-record.json"), "sha256": digest(NEW / "stage-record.json"),
                      "copied": record["copied"], "linked": record["linked"]}))


if __name__ == "__main__":
    main()
