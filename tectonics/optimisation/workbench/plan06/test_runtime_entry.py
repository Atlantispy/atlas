"""Bounded entry-contract controls after q27 rejected runq's no-bytecode environment."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
target = root / "evidence" / "entry-target.py"
with target.open("x", encoding="utf8") as stream:
    stream.write("import sys\nassert sys.dont_write_bytecode\nprint('TARGET_ENTERED')\n")
env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
rows = []
for label, delta, success in (
    ("small lane", {"PYTHONHASHSEED": "0"}, True),
    ("ticket lane", {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}, True),
    ("wrong bytecode value", {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "0"}, False),
    ("unexpected Python configuration", {"PYTHONHASHSEED": "0", "PYTHONPATH": str(root)}, False),
    ("wrong hash seed", {"PYTHONHASHSEED": "1"}, False),
):
    result = subprocess.run([sys.executable, "-B", "-s", "-P", str(root / "runtime_entry.py"),
                             str(target)], env=env | delta, capture_output=True, text=True)
    entered = "TARGET_ENTERED" in result.stdout
    ok = (result.returncode == 0) == success and entered == success
    rows.append(dict(case=label, ok=ok, exit=result.returncode,
                     stdout=result.stdout, stderr=result.stderr))
record = dict(passed=all(x["ok"] for x in rows), cases=rows,
              entry_sha256=hashlib.sha256((root / "runtime_entry.py").read_bytes()).hexdigest())
with (root / "evidence" / "runtime-entry-check.json").open("x", encoding="utf8") as stream:
    json.dump(record, stream, indent=2)
print(json.dumps(dict(passed=record["passed"], cases=len(rows), entry_sha256=record["entry_sha256"])))
raise SystemExit(0 if record["passed"] else 1)
