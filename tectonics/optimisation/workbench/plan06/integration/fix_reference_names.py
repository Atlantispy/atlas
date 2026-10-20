"""Add a binding successor naming immutable reference roots instead of old-stage aliases."""
from hashlib import sha256
import json
from pathlib import Path

T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
STAGE = T / "ac/p06r3b"
OLD = T / "ac/s4"
def h(p):
    return sha256(p.read_bytes()).hexdigest()
def write(p, doc):
    with p.open("x", encoding="utf8") as f:
        f.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return h(p)
binding_path = STAGE / "binding-r1.json"
if h(binding_path) != "b30eaa6b3cc32104305891ac90f34fb236c00d1e8b43475d7b0a9a3fc867fc84":
    raise ValueError("binding predecessor changed")
if h(STAGE / "stage-record.json") != "ed1a63720078a6679c72794eeb90e95a1152c79eb7d731074131bf0a393822c3":
    raise ValueError("stage predecessor changed")
doc = json.loads(binding_path.read_bytes())
old_record = json.loads((OLD / "stage-record.json").read_bytes())
box = Path(old_record["box"])
aliases = {box / "composed-r1": Path(old_record["junctions"]["composed-r1"]),
           box.parent / "runtime-integration-r1": Path(old_record["junctions"]["runtime-integration-r1"])}
changed = []
for key, row in doc["provenance"].items():
    source = Path(row["location"])
    for alias, target in aliases.items():
        if source.is_relative_to(alias):
            expected = target / source.relative_to(alias)
            if source.resolve() != expected or h(expected) != doc["pins"][key]:
                raise ValueError("reference alias mismatch: " + key)
            row["location"] = str(expected)
            changed.append(key)
            break
if len(changed) != 587:
    raise ValueError("unexpected reference row count")
pin = write(STAGE / "binding-r2.json", doc)
record = json.loads((STAGE / "stage-record.json").read_bytes())
record["binding_sha256"] = pin
record["predecessor"] = {"path": str(STAGE / "stage-record.json"), "sha256": h(STAGE / "stage-record.json")}
record["reference_provenance_correction"] = {"rows": len(changed), "source_bytes_changed": False}
for field in ("common_argv", "pin_argv"):
    args = record[field]
    args[args.index("--input-binding") + 1] = str(STAGE / "binding-r2.json")
    args[args.index("--input-binding-sha256") + 1] = pin
sha = write(STAGE / "stage-record-r2.json", record)
print(json.dumps({"binding_sha256": pin, "stage_record_sha256": sha, "rows": len(changed)}))
