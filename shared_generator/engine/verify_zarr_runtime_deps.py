#!/usr/bin/env python3
"""Verify the portable Zarr overlay before any generator module imports it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


MANIFEST_NAME = "ZARR_RUNTIME_DEPS_MANIFEST.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
            raise ValueError(f"Compiled Python cache is forbidden in Zarr runtime: {relative}")
        rows.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def tree_hash(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify(engine_root: Path) -> dict[str, Any]:
    manifest = json.loads((engine_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    deps = engine_root / str(manifest["relative_path"])
    if not deps.is_dir():
        raise FileNotFoundError(f"Portable Zarr runtime is missing: {deps}")
    rows = inventory(deps)
    observed = {
        "file_count": len(rows),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in rows),
        "tree_sha256": tree_hash(rows),
    }
    expected = {key: manifest[key] for key in observed}
    if observed != expected:
        raise ValueError(
            f"Portable Zarr runtime identity mismatch: expected={expected}, observed={observed}"
        )
    return {"status": "PASS", **observed, "path": str(deps.resolve())}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.engine_root.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
