"""Explicit developer commands, isolated focused tests and truthful capability reporting."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from . import SCOPE
from . import core


def _binding(path: str):
    return core.parse(core.read(Path(path)))


def _command(*arguments: str) -> list[str]:
    return [sys.executable, "-I", "-B", str(core.ROOT / "tools/develop.py"), *arguments]


def _check_outside_source(path: Path) -> Path:
    path = core.safe(path)
    if not path.is_relative_to(core.ROOT / ".atlas-dev"):
        raise core.DevelopmentError("development records must be inside this checkout's ignored .atlas-dev directory")
    return path


def _profile(name: str, record: dict) -> dict:
    config = core.profiles()
    if name not in config["profiles"]:
        raise core.DevelopmentError("unsupported profile; inspect doctor for excluded routes")
    identity = core.verify(record)
    sys.path.insert(0, str(core.ROOT))
    sys.path.insert(0, str(core.ROOT / "tests"))
    if name == "tooling":
        result = subprocess.run([sys.executable, "-I", "-B", str(core.ROOT / "tools/check_coding_safety.py")],
                                cwd=core.ROOT, check=False)
        if result.returncode:
            raise core.DevelopmentError("source wiring check failed")
    suite = unittest.defaultTestLoader.loadTestsFromNames(config["profiles"][name]["tests"])
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    core.verify(record)
    report = {"schema": "atlas.public-development.tests.v1", "scope": SCOPE, "profile": name,
              "binding_sha256": identity, "tests_run": result.testsRun, "failures": len(result.failures),
              "errors": len(result.errors), "skipped": len(result.skipped),
              "status": "PASS" if result.wasSuccessful() and not result.skipped else "INCOMPLETE"}
    if not result.wasSuccessful():
        report["status"] = "FAIL"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas offline public development; no historical run adoption.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report supported profiles and exclusions without importing Atlas")
    sub.add_parser("bootstrap", help="Create a NEW package-free venv and NEW initial public binding")
    capture = sub.add_parser("capture", help="Explicitly create a NEW binding after reviewed public edits")
    capture.add_argument("--output", required=True)
    for name in ("check", "smoke", "test", "_profile"):
        child = sub.add_parser(name, help=argparse.SUPPRESS if name == "_profile" else None)
        child.add_argument("--binding", required=True)
        if name in ("test", "_profile"):
            child.add_argument("--profile", required=True)
        if name in ("smoke", "test", "_profile"):
            child.add_argument("--report")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            # No project import or native-library probe occurs here.
            print(json.dumps({"scope": SCOPE, "environment_policy": core.parse(core.read(
                core.ROOT / "development/ENVIRONMENT.json")), **core.profiles()}, indent=2))
            return 0
        if args.command == "bootstrap":
            interpreter = core.bootstrap()
            path = core.ROOT / ".atlas-dev/bindings/initial.json"
            command = [str(interpreter), "-I", "-B", str(core.ROOT / "tools/develop.py"),
                       "capture", "--output", str(path)]
            completed = subprocess.run(command, cwd=core.ROOT, check=False)
            if completed.returncode:
                raise core.DevelopmentError("venv created, but initial binding failed; no ready environment claimed")
            print("Ready for PUBLIC profiles only. Interpreter: " + str(interpreter))
            return 0
        core.runtime_identity()
        if args.command == "capture":
            output = _check_outside_source(Path(args.output))
            record = core.capture()
            core.write_new(output, core.canonical(record) + b"\n")
            print(json.dumps({"status": "NEW_PUBLIC_BINDING", "binding_sha256": record["binding_sha256"],
                              "file": str(output), "source_files": len(record["binding"]["source_files"])}))
            return 0
        record = _binding(args.binding)
        identity = core.verify(record)
        if args.command == "check":
            print(json.dumps({"status": "PASS", "scope": SCOPE, "binding_sha256": identity}))
            return 0
        report_path = _check_outside_source(Path(args.report)) if args.report else None
        if report_path is not None and report_path.exists():
            raise core.DevelopmentError("report already exists; no execution begun")
        if args.command == "smoke":
            from .fixture import smoke
            report = smoke(record)
        elif args.command == "_profile":
            report = _profile(args.profile, record)
        else:
            config = core.profiles()["profiles"]
            selected = list(config) if args.profile == "all-public" else [args.profile]
            if any(name not in config for name in selected):
                raise core.DevelopmentError("unsupported profile; doctor explains excluded routes")
            reports = []
            for name in selected:
                # Child's private result is under .atlas-dev, not inside source.
                private_report = core.ROOT / ".atlas-dev" / ("profile-" + os.urandom(12).hex() + ".json")
                try:
                    command = _command("_profile", "--binding", str(Path(args.binding).absolute()),
                                       "--profile", name, "--report", str(private_report))
                    result = subprocess.run(command, cwd=core.ROOT, check=False, timeout=180)
                    if private_report.exists():
                        reports.append(core.parse(core.read(private_report)))
                    else:
                        raise core.DevelopmentError("profile failed before obtaining test evidence: " + name)
                    if result.returncode:
                        break
                finally:
                    private_report.unlink(missing_ok=True)
            core.verify(record)
            complete = len(reports) == len(selected) and all(r["status"] == "PASS" for r in reports)
            report = {"schema": "atlas.public-development.suite.v1", "scope": SCOPE,
                      "binding_sha256": identity, "profiles": reports,
                      "status": "PASS" if complete else "INCOMPLETE"}
        if report_path is not None:
            core.write_new(report_path, core.canonical(report) + b"\n")
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS" else 1
    except (core.DevelopmentError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
