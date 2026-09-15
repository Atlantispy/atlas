#!/usr/bin/env python3
"""Verify that current and historical Diadem format readers remain present.

This is a capability/coverage check.  It never extracts archives, opens a
database for writing, or rewrites a source file.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path


ENGINE = Path(__file__).resolve().parent
GENERATOR = ENGINE.parent
WORKSPACE = GENERATOR.parent
REGISTRY = ENGINE / "HISTORICAL_FORMAT_COMPATIBILITY.json"
DRIVE_MANIFEST = WORKSPACE / "04_Manifests" / "drive_mirror_manifest.json"


def classify(name: str) -> str:
    lower = name.casefold()
    if re.search(r"\.tar\.zst\.part\d{3}-of-\d{3}$", lower):
        return ".tar.zst.partNNN-of-NNN"
    if re.search(r"\.zip\.part\d{3}$", lower):
        return ".zip.partNNN"
    if re.search(r"\.part\d{2}-of-\d{2}\.bin$", lower):
        return ".partNN-of-NN.bin"
    if lower.endswith(".jsonl.zst"):
        return ".jsonl.zst"
    if lower.endswith(".tar.zst"):
        return ".tar.zst"
    suffix = Path(name).suffix.casefold()
    return suffix or "<none>"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    require(registry.get("schema_version") == 1, "unsupported compatibility registry")
    families = registry.get("families", [])
    require(families, "compatibility registry is empty")
    covered = {extension for family in families for extension in family["extensions"]}

    checked_handlers = []
    for family in families:
        require(family.get("handlers"), f"no retained handler for {family['id']}")
        for handler in family["handlers"]:
            path = (GENERATOR / handler["path"]).resolve()
            require(path.is_file(), f"retained handler missing: {path}")
            text = path.read_text(encoding="utf-8-sig", errors="strict")
            require(
                handler["must_contain"] in text,
                f"handler signature missing for {family['id']}: {path}",
            )
            if path.suffix.casefold() == ".py":
                compile(text, str(path), "exec")
            checked_handlers.append(path)

    manifest = json.loads(DRIVE_MANIFEST.read_text(encoding="utf-8"))
    current_families = {
        classify(Path(item["local_relative_path"]).name) for item in manifest["files"]
    }
    uncovered = sorted(current_families - covered)
    require(not uncovered, f"uncovered current snapshot formats: {uncovered}")

    runtime = {}
    for module_name in ("numpy", "rasterio", "zstandard", "zarr", "pyarrow"):
        module = importlib.import_module(module_name)
        runtime[module_name] = getattr(module, "__version__", "available")

    result = {
        "status": "PASS",
        "registry": str(REGISTRY),
        "registered_families": len(families),
        "checked_handler_files": len(set(checked_handlers)),
        "current_snapshot_format_families": sorted(current_families),
        "uncovered_current_formats": uncovered,
        "runtime": runtime,
        "read_only_check": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
