"""Location-independent access to the active Diadem generator sources.

The catalogue contains relative paths and immutable hashes.  Callers never need
to know the user's profile, checkout date, Drive layout, or this generator's
installation directory.  Set ``DIADEM_GENERATOR_CATALOGUE`` only when an
explicit alternate catalogue is required for an isolated test.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping


CATALOGUE_FILENAME = "generator_source_catalogue.json"
CATALOGUE_ENV = "DIADEM_GENERATOR_CATALOGUE"
EXPECTED_SCHEMA = "diadem-generator-source-catalogue-1.0"


def _discover_catalogue() -> Path:
    override = os.environ.get(CATALOGUE_ENV)
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{CATALOGUE_ENV} does not name a file: {path}")
        return path

    start = Path(__file__).resolve().parent
    for directory in (start, *start.parents):
        candidate = directory / CATALOGUE_FILENAME
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not find {CATALOGUE_FILENAME} above {start}; "
        f"set {CATALOGUE_ENV} to an explicit catalogue file"
    )


@lru_cache(maxsize=1)
def catalogue_path() -> Path:
    return _discover_catalogue()


@lru_cache(maxsize=1)
def load_catalogue() -> Mapping[str, Any]:
    path = catalogue_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != EXPECTED_SCHEMA:
        raise ValueError(f"Unsupported generator catalogue schema: {payload.get('schema')!r}")
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("Generator catalogue must contain a sources object")
    if payload.get("source_count") != len(sources):
        raise ValueError(
            f"Catalogue source_count={payload.get('source_count')} but contains {len(sources)} entries"
        )
    root = path.parent.resolve()
    for key, entry in sources.items():
        relative = Path(str(entry.get("relative_path", "")))
        if not relative.parts or relative.is_absolute():
            raise ValueError(f"Source {key!r} must use a non-empty relative path")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Source {key!r} escapes the generator root: {relative}") from error
        digest = str(entry.get("sha256", ""))
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"Source {key!r} has an invalid lowercase SHA-256")
    return payload


def generator_root() -> Path:
    return catalogue_path().parent


def source_entry(key: str) -> Mapping[str, Any]:
    try:
        return load_catalogue()["sources"][key]
    except KeyError as error:
        raise KeyError(f"Unknown generator source key: {key}") from error


def source_path(key: str, *, require_exists: bool = True) -> Path:
    path = (generator_root() / str(source_entry(key)["relative_path"])).resolve()
    if require_exists and not path.is_file():
        raise FileNotFoundError(f"Missing generator source {key}: {path}")
    return path


def source_paths(keys: Iterable[str] | None = None) -> dict[str, Path]:
    selected = load_catalogue()["sources"].keys() if keys is None else keys
    return {key: source_path(key) for key in selected}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_catalogue(keys: Iterable[str] | None = None) -> dict[str, Any]:
    sources = load_catalogue()["sources"]
    selected = list(sources) if keys is None else list(keys)
    unknown = sorted(set(selected).difference(sources))
    if unknown:
        raise KeyError(f"Unknown generator source keys: {unknown}")
    rows: dict[str, Any] = {}
    failed: list[str] = []
    for key in selected:
        entry = source_entry(key)
        path = source_path(key, require_exists=False)
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        actual = sha256_file(path) if exists else None
        ok = exists and size == int(entry["bytes"]) and actual == entry["sha256"]
        rows[key] = {
            "path": str(path),
            "exists": exists,
            "expected_bytes": entry["bytes"],
            "actual_bytes": size,
            "expected_sha256": entry["sha256"],
            "actual_sha256": actual,
            "ok": ok,
        }
        if not ok:
            failed.append(key)
    return {"ok": not failed, "checked_count": len(selected), "failed_keys": failed, "results": rows}


__all__ = [
    "CATALOGUE_ENV",
    "CATALOGUE_FILENAME",
    "catalogue_path",
    "generator_root",
    "load_catalogue",
    "sha256_file",
    "source_entry",
    "source_path",
    "source_paths",
    "verify_catalogue",
]
