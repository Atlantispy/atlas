"""Execute only the pinned independent D5 source assembler, via the small lane."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
HERE = Path(__file__).resolve().parent
PY = T / ".r44-env/Scripts/python.exe"
ASSEMBLER = HERE / "assemble_r3_plan06.py"
STAGE = T / "ac/p06r3b/stage-record-r2.json"
REVIEWED = HERE / "reviewed-d5-r1.json"


def h(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("check", "pin", "compose"))
    args = parser.parse_args()
    if h(ASSEMBLER) != "c84f98bf62116553b92103bd16a2d6f0fbf5d027c8273f6f90ab8fadfa80f45d":
        raise ValueError("assembler changed")
    if h(STAGE) != "e2095e84a3ae2ed14560e53a1cdcab448878d8c63494c60fcb98b5a22f6caa04":
        raise ValueError("stage record changed")
    record = json.loads(STAGE.read_bytes())
    if args.step == "pin":
        flags = record["pin_argv"]
    elif args.step == "check":
        flags = ["--check"] + record["common_argv"]
    else:
        flags = ["--compose"] + record["common_argv"] + ["--reviewed", str(REVIEWED), "--reviewed-sha256", h(REVIEWED)]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env["PYTHONHASHSEED"] = "0"
    command = [str(PY), "-B", "-I", str(T / "q/runq.py"), "small", "--cores", "1", "--gib", "0.5", "--",
               str(PY), "-B", "-E", "-s", str(ASSEMBLER)] + flags
    log = HERE / ("source-" + args.step + "-r2.log")
    with log.open("xb") as stream:
        result = subprocess.run(command, env=env, cwd=HERE, stdout=stream, stderr=subprocess.STDOUT)
    outcome = {"step": args.step, "exit_code": result.returncode, "command": command,
               "assembler_sha256": h(ASSEMBLER), "stage_sha256": h(STAGE), "log": str(log), "log_sha256": h(log)}
    path = HERE / ("source-" + args.step + "-r2.json")
    with path.open("x", encoding="utf8") as stream:
        json.dump(outcome, stream, indent=1)
    print(json.dumps(outcome))
    if result.returncode:
        print(log.read_text(encoding="utf8", errors="replace"))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
