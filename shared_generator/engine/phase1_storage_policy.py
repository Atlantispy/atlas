#!/usr/bin/env python3
"""Enforce the Phase 1 rule that production code does not create ZIP packages.

The guard is deliberately narrow.  It scans only active first-party Python and
PowerShell code under ``06_Generator_System`` and ``04_Manifests/Tools``.  ZIP
readers, Office Open XML readers, NumPy ``.npz`` storage, tests, benchmarks,
dependencies, caches, recovery copies and disabled legacy tools remain valid.

This module does not open or hash project datasets.  It only parses small source
files, so it is suitable for routine generator validation.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Sequence


SCHEMA = "diadem-phase1-storage-policy-1.0"
SOURCE_SUFFIXES = {".py", ".ps1", ".psm1"}

# Directory exclusions are matched case-insensitively.  Prefix exclusions cover
# quarantined LocalFirst copies whose generated suffix changes between runs.
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    "__pycache__",
    "benchmarks",
    "cache",
    "deps",
    "generator_deps",
    "zarr_deps",
    "legacy_disabled",
    "recovery",
    "recovery_snapshots",
    "tests",
}
EXCLUDED_DIRECTORY_PREFIXES = (
    ".localfirst.failed-",
)

# This is an intentional compression A/B test.  It creates ZIP bytes in memory
# and writes only benchmark metrics; it is not a production package path.
EXCLUDED_FILE_NAMES = {
    "run_zip_vs_zstd_ab.py",
}

POWERSHELL_WRITER_PATTERNS = (
    (
        "powershell_compress_archive",
        re.compile(r"(?i)(?<![\w-])Compress-Archive(?![\w-])"),
    ),
    (
        "powershell_zip_create_from_directory",
        re.compile(
            r"(?i)\[\s*(?:System\.)?IO\.Compression\.ZipFile\s*\]\s*"
            r"::\s*CreateFromDirectory\b"
        ),
    ),
    (
        "powershell_zip_archive_create_or_update",
        re.compile(r"(?i)ZipArchiveMode\s*\]\s*::\s*(?:Create|Update)\b"),
    ),
)


def _relative(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _directory_is_excluded(name: str) -> bool:
    folded = name.casefold()
    return folded in EXCLUDED_DIRECTORY_NAMES or any(
        folded.startswith(prefix) for prefix in EXCLUDED_DIRECTORY_PREFIXES
    )


def _source_files(scope_root: Path) -> Iterable[Path]:
    """Yield source files while pruning excluded trees before descent."""

    for directory, child_directories, files in os.walk(scope_root, topdown=True, followlinks=False):
        child_directories[:] = [
            name for name in child_directories if not _directory_is_excluded(name)
        ]
        base = Path(directory)
        for name in sorted(files):
            path = base / name
            if path.suffix.casefold() not in SOURCE_SUFFIXES:
                continue
            if name.casefold() in EXCLUDED_FILE_NAMES:
                continue
            yield path


def _dotted_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _finding(
    path: Path,
    workspace_root: Path,
    node: ast.AST | None,
    rule: str,
    detail: str,
    *,
    language: str,
) -> dict[str, Any]:
    return {
        "file": _relative(path, workspace_root),
        "line": int(getattr(node, "lineno", 0) or 0),
        "column": int(getattr(node, "col_offset", 0) or 0) + 1 if node else 0,
        "language": language,
        "rule": rule,
        "detail": detail,
    }


class _PythonPolicyVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, workspace_root: Path) -> None:
        self.path = path
        self.workspace_root = workspace_root
        self.aliases: dict[str, str] = {}
        self.findings: list[dict[str, Any]] = []
        self.npz_writers: list[dict[str, Any]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            self.aliases[item.asname or item.name.split(".", 1)[0]] = item.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for item in node.names:
                if item.name != "*":
                    self.aliases[item.asname or item.name] = f"{node.module}.{item.name}"
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted_name(node.func, self.aliases)

        if name in {"zipfile.ZipFile", "zipfile.PyZipFile"}:
            mode_node = _keyword(node, "mode")
            if mode_node is None and len(node.args) >= 2:
                mode_node = node.args[1]
            mode = "r" if mode_node is None else _literal_string(mode_node)
            if mode != "r":
                detail = (
                    f"{name} uses mode {mode!r}; only the literal read mode 'r' is permitted "
                    "in active production code"
                    if mode is not None
                    else f"{name} uses a dynamic mode that is not provably read-only"
                )
                self.findings.append(
                    _finding(
                        self.path,
                        self.workspace_root,
                        node,
                        "python_zipfile_write_mode",
                        detail,
                        language="python",
                    )
                )

        elif name == "shutil.make_archive":
            format_node = _keyword(node, "format")
            if format_node is None and len(node.args) >= 2:
                format_node = node.args[1]
            archive_format = _literal_string(format_node)
            if archive_format is None or archive_format.casefold() == "zip":
                detail = (
                    "shutil.make_archive explicitly requests ZIP"
                    if archive_format is not None
                    else "shutil.make_archive uses a dynamic or missing format"
                )
                self.findings.append(
                    _finding(
                        self.path,
                        self.workspace_root,
                        node,
                        "python_make_archive_zip",
                        detail,
                        language="python",
                    )
                )

        # NPZ is a numerical array container, not a .zip working/release package.
        # Record it for later Phase 2 migration without failing Phase 1.
        if name in {
            "numpy.savez",
            "numpy.savez_compressed",
        }:
            self.npz_writers.append(
                _finding(
                    self.path,
                    self.workspace_root,
                    node,
                    "informational_npz_writer",
                    f"{name} retained as numerical storage; not a Phase 1 ZIP-package violation",
                    language="python",
                )
            )

        self.generic_visit(node)


def _scan_python(path: Path, workspace_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        return (
            [
                {
                    "file": _relative(path, workspace_root),
                    "line": int(error.lineno or 0),
                    "column": int(error.offset or 0),
                    "language": "python",
                    "rule": "python_parse_error",
                    "detail": error.msg,
                }
            ],
            [],
        )
    visitor = _PythonPolicyVisitor(path, workspace_root)
    visitor.visit(tree)
    return visitor.findings, visitor.npz_writers


def _scan_powershell(path: Path, workspace_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    for line_number, line in enumerate(lines, 1):
        # Comment-only lines are documentation, not executable writer paths.
        if line.lstrip().startswith("#"):
            continue
        for rule, pattern in POWERSHELL_WRITER_PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append(
                    {
                        "file": _relative(path, workspace_root),
                        "line": line_number,
                        "column": match.start() + 1,
                        "language": "powershell",
                        "rule": rule,
                        "detail": "PowerShell ZIP creation is prohibited in active production code",
                    }
                )
    return findings


def scan_workspace(workspace_root: str | Path) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    requested_roots = (
        workspace / "06_Generator_System",
        workspace / "04_Manifests" / "Tools",
    )
    present_roots = [path for path in requested_roots if path.is_dir()]
    missing_roots = [_relative(path, workspace) for path in requested_roots if not path.is_dir()]

    findings: list[dict[str, Any]] = []
    npz_writers: list[dict[str, Any]] = []
    scanned_files: list[str] = []
    for scope_root in present_roots:
        for path in _source_files(scope_root):
            scanned_files.append(_relative(path, workspace))
            if path.suffix.casefold() == ".py":
                python_findings, python_npz = _scan_python(path, workspace)
                findings.extend(python_findings)
                npz_writers.extend(python_npz)
            else:
                findings.extend(_scan_powershell(path, workspace))

    if missing_roots:
        findings.append(
            {
                "file": None,
                "line": 0,
                "column": 0,
                "language": "policy",
                "rule": "storage_policy_scope_missing",
                "detail": f"Required active-code roots are missing: {missing_roots}",
            }
        )

    findings.sort(key=lambda item: (str(item["file"]), item["line"], item["rule"]))
    npz_writers.sort(key=lambda item: (str(item["file"]), item["line"]))
    return {
        "schema": SCHEMA,
        "status": "PASS" if not findings else "FAIL",
        "workspace_root": str(workspace),
        "scope_roots": [_relative(path, workspace) for path in requested_roots],
        "missing_scope_roots": missing_roots,
        "scanned_source_file_count": len(scanned_files),
        "scanned_suffixes": sorted(SOURCE_SUFFIXES),
        "dataset_files_opened_or_hashed": 0,
        "policy": {
            "new_zip_working_or_release_packages": "PROHIBITED",
            "zip_readers_and_ooxml_readers": "PERMITTED",
            "npz_numerical_storage": "PERMITTED_AND_REPORTED_FOR_PHASE_2",
            "tests_benchmarks_dependencies_caches_recovery_and_disabled_legacy": "EXCLUDED",
            "legacy_exact_reassembly_outside_active_roots": "PERMITTED",
        },
        "findings": findings,
        "informational_npz_writers": npz_writers,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="diadem-storage-policy-") as temporary:
        workspace = Path(temporary)
        engine = workspace / "06_Generator_System" / "engine"
        tools = workspace / "04_Manifests" / "Tools"

        _write(
            engine / "safe_reader.py",
            "import zipfile\nimport numpy as np\n"
            "zipfile.ZipFile('legacy.zip', 'r').close()\n"
            "np.savez_compressed('tile.npz', values=[1, 2, 3])\n",
        )
        _write(
            tools / "Sync-PreparedDriveDelta.ps1",
            "$archive = [IO.Compression.ZipFile]::OpenRead($Path)\n",
        )
        _write(
            engine / "tests" / "test_legacy.py",
            "import zipfile\nzipfile.ZipFile('temporary.zip', 'w').close()\n",
        )
        _write(
            engine / "run_zip_vs_zstd_ab.py",
            "import zipfile\nzipfile.ZipFile('benchmark.zip', 'w').close()\n",
        )

        safe_report = scan_workspace(workspace)
        safe_ok = (
            safe_report["status"] == "PASS"
            and len(safe_report["informational_npz_writers"]) == 1
            and safe_report["dataset_files_opened_or_hashed"] == 0
        )

        _write(
            engine / "bad_zip_writer.py",
            "import zipfile as zf\nwith zf.ZipFile('new.zip', mode='w'):\n    pass\n",
        )
        _write(
            engine / "bad_archive_writer.py",
            "from shutil import make_archive as pack\npack('new', 'zip')\n",
        )
        _write(
            tools / "Bad-ZipWriter.ps1",
            "Compress-Archive -Path $Source -DestinationPath 'new.zip'\n",
        )
        unsafe_report = scan_workspace(workspace)
        found_rules = {item["rule"] for item in unsafe_report["findings"]}
        expected_rules = {
            "python_zipfile_write_mode",
            "python_make_archive_zip",
            "powershell_compress_archive",
        }
        unsafe_ok = unsafe_report["status"] == "FAIL" and expected_rules.issubset(found_rules)

        passed = safe_ok and unsafe_ok
        return {
            "schema": f"{SCHEMA}-self-test",
            "status": "PASS" if passed else "FAIL",
            "safe_fixture_passed": safe_ok,
            "unsafe_fixture_blocked": unsafe_ok,
            "expected_rules": sorted(expected_rules),
            "observed_rules": sorted(found_rules),
            "dataset_files_opened_or_hashed": 0,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Local workspace containing 06_Generator_System and 04_Manifests/Tools",
    )
    parser.add_argument("--self-test", action="store_true", help="Run isolated policy fixtures only")
    parser.add_argument("--report", type=Path, help="Optional JSON report destination")
    args = parser.parse_args(argv)

    workspace_root = args.workspace_root or Path(__file__).resolve().parent.parent.parent
    report = self_test() if args.self_test else scan_workspace(workspace_root)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
