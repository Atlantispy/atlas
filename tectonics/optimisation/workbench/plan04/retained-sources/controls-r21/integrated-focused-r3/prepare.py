"""Freeze one explicit accepted adapter and its exact retained71 result."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUEUE = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/q/runq.py")
QUEUE_SHA = "0bcffc6655e727adf46f0796f1a77916a64046c93244d2ed7f000b84d648eb5f"
FROZEN_INPUTS = HERE.parent.parent / "causal-r20/owner-run-r1/INPUT-PINS.json"
FROZEN_INPUTS_SHA = "3fddd4b92300f6b36e2e00b7afc7ab6e5d7917b3a3eee90005da34b1844841d6"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--retained-result", type=Path, required=True)
    parser.add_argument("--retained-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.retained_result) != args.retained_sha256 or digest(QUEUE) != QUEUE_SHA:
        raise ValueError("Explicit retained result or queue selection changed")
    result = json.loads(args.retained_result.read_text())
    if result.get("passed") is not True or result.get("group") != "all":
        raise ValueError("Exact retained71 result not admitted")
    if digest(FROZEN_INPUTS) != FROZEN_INPUTS_SHA:
        raise ValueError("Original input manifest changed")
    pins = json.loads(FROZEN_INPUTS.read_text())["source_pins"]
    pins[str(QUEUE)] = QUEUE_SHA
    pins.update(json.loads((args.base / "SOURCE-PINS.json").read_text())["pins"])
    for text, expected in pins.items():
        if digest(Path(text)) != expected:
            raise ValueError("Base selection changed: " + text)
    pins.update({str(path): digest(path) for path in HERE.glob("*.py")})
    for name in ("support.py", "report.py", "run_cases.py"):
        path = HERE.parent / name
        pins[str(path)] = digest(path)
    pins.update({str(QUEUE): QUEUE_SHA, str(args.retained_result): args.retained_sha256})
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"base": str(args.base), "retained_result": str(args.retained_result), "pins": pins,
                   "scope": "6 final provenance integration boundaries and six selected mutations; guards false"},
                  stream, indent=2)
    print(json.dumps({"selection": str(args.output), "sha256": digest(args.output)}))


if __name__ == "__main__":
    main()
