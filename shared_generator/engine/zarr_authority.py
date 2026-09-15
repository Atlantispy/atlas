#!/usr/bin/env python3
"""Transactional authority controls for a sharded Zarr v3 terrain array.

This is a staged prototype.  It deliberately supports one local array and one
writer at a time.  Raster exports are derived products; Zarr is the editable
working authority after an explicit ``init`` on a copied, validated store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Iterator, Sequence

MANIFEST_NAME = "AUTHORITY_MANIFEST.json"
ACTIVE_NAME = "ACTIVE_TRANSACTION.json"
LOCK_NAME = ".authority-access.lock"
CONTROL_DIR = ".authority"
TX_DIR = "transactions"
EXPORT_DIR = "exports"
MANIFEST_SCHEMA = "diadem.zarr-terrain-authority.v1"
JOURNAL_SCHEMA = "diadem.zarr-terrain-transaction.v1"
RECEIPT_SCHEMA = "diadem.zarr-terrain-export-receipt.v1"
HANDOFF_SCHEMA = "diadem.drive-publication-handoff.v1"
TERMINAL_STATES = {"COMMITTED", "ROLLED_BACK", "ABORTED"}


class AuthorityError(RuntimeError):
    """A fail-closed authority or transaction error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def fsync_file(path: Path) -> None:
    # Windows rejects FlushFileBuffers for a read-only handle.  All callers use
    # this after creating/replacing a writable file and before sealing recovery.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def fsync_parent(path: Path) -> None:
    # Windows does not provide a portable Python directory fsync.  On POSIX,
    # sync the directory entry as well.  Atomic replacement remains same-volume.
    if os.name == "nt":
        return
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        fsync_parent(path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, pretty_json_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exact parser error is incidental
        raise AuthorityError(f"Cannot read valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuthorityError(f"Expected a JSON object: {path}")
    return value


def with_control_hash(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("control_sha256", None)
    result["control_sha256"] = sha256_bytes(canonical_json_bytes(result))
    return result


def validate_control_hash(value: dict[str, Any], label: str) -> None:
    recorded = value.get("control_sha256")
    unsigned = dict(value)
    unsigned.pop("control_sha256", None)
    actual = sha256_bytes(canonical_json_bytes(unsigned))
    if not isinstance(recorded, str) or recorded != actual:
        raise AuthorityError(f"{label} control hash mismatch")


def write_control_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    signed = with_control_hash(value)
    atomic_write_json(path, signed)
    return signed


def set_read_only(path: Path) -> None:
    path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def make_writable(path: Path) -> None:
    if path.exists():
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def exact_array_equal(left: Any, right: Any) -> bool:
    import numpy as np

    a = np.asarray(left)
    b = np.asarray(right)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes(order="C") == b.tobytes(
        order="C"
    )


_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def normalize_relpath(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AuthorityError(f"Unsafe relative path: {value!r}")
    raw = value.replace("\\", "/")
    if raw.startswith(("/", "//", "\\\\?\\", "\\\\.\\")) or ":" in raw:
        raise AuthorityError(f"Unsafe rooted, device, drive-relative, or ADS path: {value!r}")
    if "//" in raw:
        raise AuthorityError(f"Unsafe empty path component: {value!r}")
    windows = PureWindowsPath(value)
    if windows.drive or windows.root or windows.is_absolute():
        raise AuthorityError(f"Unsafe Windows path: {value!r}")
    parts = raw.split("/")
    if not parts:
        raise AuthorityError(f"Unsafe relative path: {value!r}")
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((" ", ".")):
            raise AuthorityError(f"Unsafe path component {part!r} in {value!r}")
        if any(ord(character) < 32 for character in part):
            raise AuthorityError(f"Control character in relative path: {value!r}")
        base = part.split(".", 1)[0].upper()
        if base in _WINDOWS_RESERVED:
            raise AuthorityError(f"Reserved Windows path component {part!r}")
    return "/".join(parts)


def is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag) or path.is_symlink()


def require_safe_root(root: Path) -> Path:
    supplied = root.absolute()
    if is_reparse_point(supplied):
        raise AuthorityError(f"Controlled root itself is a reparse point: {supplied}")
    root = supplied.resolve(strict=True)
    if not root.is_dir() or is_reparse_point(root):
        raise AuthorityError(f"Root is missing, not a directory, or a reparse point: {root}")
    return root


def safe_child(root: Path, relative: str, *, create_parents: bool = False) -> Path:
    root = require_safe_root(root)
    normalized = normalize_relpath(relative)
    current = root
    parts = Path(normalized).parts
    for index, part in enumerate(parts):
        current = current / part
        is_leaf = index == len(parts) - 1
        if current.exists() or os.path.lexists(current):
            if is_reparse_point(current):
                raise AuthorityError(f"Reparse point is forbidden inside controlled root: {current}")
        elif create_parents and not is_leaf:
            current.mkdir()
            if is_reparse_point(current):
                raise AuthorityError(f"Created path unexpectedly became a reparse point: {current}")
    canonical_parent = current.parent.resolve(strict=True)
    try:
        common = os.path.commonpath([str(root), str(canonical_parent)])
    except ValueError as exc:
        raise AuthorityError(f"Path crosses volumes or roots: {current}") from exc
    if os.path.normcase(common) != os.path.normcase(str(root)):
        raise AuthorityError(f"Path escapes controlled root: {current}")
    return current


def validate_transaction_id(txid: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", txid):
        raise AuthorityError(f"Unsafe transaction ID: {txid!r}")
    return txid


def same_volume(first: Path, second: Path) -> bool:
    return os.path.splitdrive(str(first.resolve()))[0].casefold() == os.path.splitdrive(
        str(second.resolve())
    )[0].casefold()


@dataclass
class ExclusiveAccess(AbstractContextManager["ExclusiveAccess"]):
    root: Path
    purpose: str
    break_stale: bool = False
    lock_path: Path | None = None

    def __enter__(self) -> "ExclusiveAccess":
        self.root = require_safe_root(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = safe_child(self.root, LOCK_NAME)
        if self.break_stale and self.lock_path.exists():
            controls = safe_child(self.root, CONTROL_DIR)
            if not controls.is_dir():
                raise AuthorityError("Cannot preserve stale lock: safe control directory is missing")
            stale = safe_child(controls, f"stale-lock-{uuid.uuid4().hex}.json")
            os.replace(self.lock_path, stale)
        payload = pretty_json_bytes(
            {
                "schema": "diadem.zarr-authority-lock.v1",
                "pid": os.getpid(),
                "purpose": self.purpose,
                "created_utc": utc_now(),
            }
        )
        try:
            fd = os.open(str(self.lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            raise AuthorityError(
                f"Authority is locked: {self.lock_path}. Use recovery with explicit "
                "--break-stale-lock only after confirming no process is active."
            ) from exc
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.lock_path and self.lock_path.exists():
            self.lock_path.unlink()
            fsync_parent(self.lock_path)


def control_root(authority_root: Path) -> Path:
    return authority_root / CONTROL_DIR


def transaction_root(authority_root: Path, txid: str) -> Path:
    controls = safe_child(authority_root, CONTROL_DIR)
    if not controls.is_dir():
        raise AuthorityError("Authority control directory is missing")
    tx_base = safe_child(controls, TX_DIR)
    if not tx_base.exists():
        tx_base.mkdir()
    tx_base = require_safe_root(tx_base)
    return safe_child(tx_base, validate_transaction_id(txid))


def unfinished_transactions(authority_root: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    active = safe_child(authority_root, ACTIVE_NAME)
    if active.exists():
        try:
            pointer = read_json(active)
            found.append((active, str(pointer.get("state", "ACTIVE"))))
        except Exception:
            found.append((active, "CORRUPT"))
    controls = safe_child(authority_root, CONTROL_DIR)
    if controls.exists() and is_reparse_point(controls):
        raise AuthorityError("Authority control directory is a reparse point")
    tx_base = controls / TX_DIR
    if tx_base.exists() and is_reparse_point(tx_base):
        raise AuthorityError("Authority transaction directory is a reparse point")
    if tx_base.exists():
        for journal_path in sorted(tx_base.glob("*/journal.json")):
            try:
                state = str(read_json(journal_path).get("state", "UNKNOWN"))
            except Exception:
                state = "CORRUPT"
            if state not in TERMINAL_STATES:
                found.append((journal_path, state))
    return found


def require_no_unfinished(authority_root: Path) -> None:
    unfinished = unfinished_transactions(authority_root)
    if unfinished:
        details = ", ".join(f"{path}:{state}" for path, state in unfinished)
        raise AuthorityError(f"Unfinished authority transaction; recovery required: {details}")


def shard_records(array_root: Path) -> list[dict[str, Any]]:
    array_root = require_safe_root(array_root)
    chunk_root = safe_child(array_root, "c")
    if not chunk_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    discovered: list[Path] = []
    for current_name, directory_names, file_names in os.walk(chunk_root, topdown=True, followlinks=False):
        current = Path(current_name)
        if is_reparse_point(current):
            raise AuthorityError(f"Reparse point in Zarr shard tree: {current}")
        for directory_name in directory_names:
            directory = current / directory_name
            if is_reparse_point(directory):
                raise AuthorityError(f"Reparse point in Zarr shard tree: {directory}")
        for file_name in file_names:
            discovered.append(current / file_name)
    for path in sorted(discovered, key=lambda item: item.as_posix()):
        relative = path.relative_to(array_root).as_posix()
        path = safe_child(array_root, relative)
        records.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def merkle_root(metadata_sha256: str, records: Sequence[dict[str, Any]]) -> str:
    try:
        metadata_hash = bytes.fromhex(metadata_sha256)
    except ValueError as exc:
        raise AuthorityError("Invalid metadata SHA-256") from exc
    leaves = [hashlib.sha256(b"metadata\x00" + metadata_hash).digest()]
    for record in sorted(records, key=lambda item: str(item["path"])):
        path = normalize_relpath(str(record["path"])).encode("utf-8")
        digest = bytes.fromhex(str(record["sha256"]))
        size = str(int(record["size_bytes"])).encode("ascii")
        leaves.append(hashlib.sha256(b"shard\x00" + path + b"\x00" + digest + b"\x00" + size).digest())
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [
            hashlib.sha256(b"node\x00" + level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def load_manifest(authority_root: Path) -> dict[str, Any]:
    manifest_path = safe_child(authority_root, MANIFEST_NAME)
    if not manifest_path.is_file():
        raise AuthorityError(f"Missing authority manifest: {manifest_path}")
    manifest = read_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuthorityError("Unsupported authority manifest schema")
    validate_control_hash(manifest, "authority manifest")
    return manifest


def array_paths(authority_root: Path, manifest: dict[str, Any]) -> tuple[Path, Path]:
    relative = normalize_relpath(str(manifest["array_relpath"]))
    array_root = safe_child(authority_root, relative)
    if not array_root.is_dir():
        raise AuthorityError(f"Missing authority array directory: {array_root}")
    metadata_path = safe_child(array_root, "zarr.json")
    if not metadata_path.is_file():
        raise AuthorityError(f"Missing Zarr v3 metadata: {metadata_path}")
    return array_root, metadata_path


def verify_manifest(
    authority_root: Path,
    *,
    verify_all_shards: bool = False,
    verify_last_touched: bool = True,
) -> dict[str, Any]:
    manifest = load_manifest(authority_root)
    array_root, metadata_path = array_paths(authority_root, manifest)
    metadata_hash = sha256_file(metadata_path)
    if metadata_hash != manifest.get("metadata_sha256"):
        raise AuthorityError("Zarr metadata hash differs from authority manifest")
    records = manifest.get("shards")
    if not isinstance(records, list):
        raise AuthorityError("Authority shard catalogue is missing")
    paths = [str(record.get("path")) for record in records]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise AuthorityError("Authority shard catalogue is not uniquely sorted")
    expected_root = merkle_root(metadata_hash, records)
    if expected_root != manifest.get("root_hash"):
        raise AuthorityError("Authority Merkle/root hash mismatch")
    # Every runtime open performs a cheap full path-set and byte-size check.
    # This catches missing older shards (which Zarr could otherwise read as fill
    # values) and unmanifested shards. Cryptographic hashing remains limited to
    # the latest touched shards unless a full audit is requested.
    expected_by_path = {str(record["path"]): record for record in records}
    actual_by_path: dict[str, int] = {}
    chunk_root = safe_child(array_root, "c")
    if chunk_root.exists():
        if is_reparse_point(chunk_root):
            raise AuthorityError("Zarr chunk root is a reparse point")
        for path in chunk_root.rglob("*"):
            if path.is_file():
                relative = path.relative_to(array_root).as_posix()
                safe_child(array_root, relative)
                actual_by_path[relative] = path.stat().st_size
    if set(actual_by_path) != set(expected_by_path):
        missing = sorted(set(expected_by_path) - set(actual_by_path))
        extra = sorted(set(actual_by_path) - set(expected_by_path))
        raise AuthorityError(f"Authority shard path-set mismatch; missing={missing}, extra={extra}")
    for relative, size in actual_by_path.items():
        if size != int(expected_by_path[relative]["size_bytes"]):
            raise AuthorityError(f"Authority shard size mismatch: {relative}")

    to_verify: set[str] = set()
    if verify_all_shards:
        to_verify.update(paths)
    elif verify_last_touched:
        last = manifest.get("last_transaction") or {}
        for item in last.get("touched_shards", []):
            if item.get("new_exists"):
                to_verify.add(str(item["path"]))
    record_by_path = expected_by_path
    for relative in sorted(to_verify):
        record = record_by_path.get(relative)
        if record is None:
            raise AuthorityError(f"Touched shard absent from manifest: {relative}")
        path = array_root / Path(relative)
        if not path.is_file():
            raise AuthorityError(f"Authority shard is missing: {relative}")
        if path.stat().st_size != int(record["size_bytes"]) or sha256_file(path) != record["sha256"]:
            raise AuthorityError(f"Authority shard hash/size mismatch: {relative}")
    return manifest


def zarr_metadata(array_root: Path) -> dict[str, Any]:
    metadata = read_json(array_root / "zarr.json")
    if metadata.get("zarr_format") != 3 or metadata.get("node_type") != "array":
        raise AuthorityError("Only Zarr v3 arrays are supported")
    chunk_encoding = metadata.get("chunk_key_encoding", {})
    if chunk_encoding.get("name") != "default" or chunk_encoding.get("configuration", {}).get(
        "separator"
    ) != "/":
        raise AuthorityError("Only default slash-separated Zarr v3 chunk keys are supported")
    codecs = metadata.get("codecs", [])
    sharding = next(
        (
            codec
            for codec in codecs
            if isinstance(codec, dict) and codec.get("name") == "sharding_indexed"
        ),
        None,
    )
    if sharding is None:
        raise AuthorityError("Authority array must use indexed sharding")
    inner_codecs = sharding.get("configuration", {}).get("codecs", [])
    if not any(codec.get("name") == "crc32c" for codec in inner_codecs if isinstance(codec, dict)):
        raise AuthorityError("Authority array must retain CRC32C on every inner chunk")
    shape = metadata.get("shape")
    if not isinstance(shape, list) or len(shape) != 2 or any(int(value) <= 0 for value in shape):
        raise AuthorityError("Authority terrain must be a non-empty two-dimensional array")
    return metadata


def validate_promotion_source(metadata: dict[str, Any]) -> None:
    attrs = metadata.get("attributes") or {}
    if attrs.get("representation_status") != "DETACHED_VALIDATED_NOT_ACTIVE":
        raise AuthorityError("Only the detached validated terrain candidate may be promoted")
    if attrs.get("build_state") != "complete":
        raise AuthorityError("Terrain candidate build is not marked complete")
    canonical = attrs.get("effective_terrain_canonical_sha256")
    if not isinstance(canonical, str) or not re.fullmatch(r"[0-9a-f]{64}", canonical):
        raise AuthorityError("Validated canonical terrain digest is missing or malformed")
    lineage = attrs.get("source_lineage")
    if not isinstance(lineage, dict) or not lineage:
        raise AuthorityError("Sealed TIFF source lineage is missing")
    for role, record in lineage.items():
        if not isinstance(record, dict):
            raise AuthorityError(f"Malformed source lineage record: {role}")
        normalize_relpath(str(record.get("relative_path", "")))
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
            raise AuthorityError(f"Malformed source SHA-256 in lineage: {role}")
        if int(record.get("size_bytes", 0)) <= 0:
            raise AuthorityError(f"Malformed source byte size in lineage: {role}")


def normalize_source_provenance_paths(attrs: dict[str, Any]) -> dict[str, Any]:
    """Replace build-machine paths with portable sealed-lineage references."""

    lineage = attrs.get("source_lineage")
    if not isinstance(lineage, dict) or not lineage:
        raise AuthorityError("Cannot normalize provenance without sealed source lineage")
    source_grids = attrs.get("source_grids")
    if isinstance(source_grids, dict):
        normalized_grids: dict[str, Any] = {}
        for key, value in source_grids.items():
            if key not in lineage or not isinstance(value, dict):
                raise AuthorityError(f"Source-grid provenance is not lineage-bound: {key}")
            record = dict(value)
            record["path"] = normalize_relpath(str(lineage[key]["relative_path"]))
            record["path_semantics"] = (
                "GENERATOR_ROOT_RELATIVE_SEALED_LINEAGE_REFERENCE_NOT_RUNTIME_INPUT"
            )
            normalized_grids[key] = record
        attrs["source_grids"] = normalized_grids
    base = attrs.get("base_semantic_metadata")
    if isinstance(base, dict):
        base_key = "terrain_d31_100m"
        if base_key not in lineage:
            raise AuthorityError("Base semantic provenance lacks terrain lineage")
        normalized_base = dict(base)
        normalized_base["path"] = normalize_relpath(
            str(lineage[base_key]["relative_path"])
        )
        normalized_base["path_semantics"] = (
            "GENERATOR_ROOT_RELATIVE_SEALED_LINEAGE_REFERENCE_NOT_RUNTIME_INPUT"
        )
        attrs["base_semantic_metadata"] = normalized_base
    attrs["source_provenance_path_policy"] = (
        "PORTABLE_GENERATOR_ROOT_RELATIVE_SEALED_LINEAGE_REFERENCES"
    )
    return attrs


def build_manifest(
    authority_root: Path,
    array_relpath: str,
    metadata: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    array_root = safe_child(authority_root, array_relpath)
    metadata_path = safe_child(array_root, "zarr.json")
    metadata_hash = sha256_file(metadata_path)
    attrs = metadata.get("attributes") or {}
    source_lineage = {
        "migration_type": "VALIDATED_ZARR_COPY_PROMOTED_TO_EDITABLE_WORKING_AUTHORITY",
        "sealed_tiff_parents": attrs.get("source_lineage", {}),
        "original_representation_status": attrs.get("previous_representation_status"),
        "original_authority": attrs.get("previous_authority"),
        "migration_utc": attrs.get("authority_promoted_utc"),
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "authority_id": str(uuid.uuid4()),
        "authority_role": "EDITABLE_WORKING_AUTHORITY",
        "array_relpath": normalize_relpath(array_relpath),
        "generation": 0,
        "created_utc": utc_now(),
        "updated_utc": utc_now(),
        "metadata_sha256": metadata_hash,
        "root_hash_algorithm": "sha256-binary-merkle-v1",
        "root_hash": merkle_root(metadata_hash, records),
        "source_lineage": source_lineage,
        "shards": records,
        "last_transaction": None,
    }
    return with_control_hash(manifest)


def init_authority(
    authority_root: Path,
    array_relpath: str,
    *,
    expected_source_metadata_sha256: str,
) -> dict[str, Any]:
    authority_root = require_safe_root(authority_root)
    array_relpath = normalize_relpath(array_relpath)
    array_root = safe_child(authority_root, array_relpath)
    metadata_path = safe_child(array_root, "zarr.json")
    if not metadata_path.is_file():
        raise AuthorityError(f"No Zarr array metadata at {metadata_path}")
    if (authority_root / MANIFEST_NAME).exists():
        raise AuthorityError("Authority manifest already exists")
    with ExclusiveAccess(authority_root, "initialize-authority"):
        require_no_unfinished(authority_root)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_source_metadata_sha256):
            raise AuthorityError("Expected source metadata SHA-256 is malformed")
        actual_source_metadata_sha256 = sha256_file(metadata_path)
        if actual_source_metadata_sha256 != expected_source_metadata_sha256:
            raise AuthorityError("Copied candidate metadata does not match the pinned validated digest")
        metadata = zarr_metadata(array_root)
        validate_promotion_source(metadata)
        attrs = dict(metadata.get("attributes") or {})
        attrs = normalize_source_provenance_paths(attrs)
        attrs["previous_schema"] = attrs.get("schema")
        attrs["schema"] = "diadem.editable-terrain-zarr-authority.v1"
        attrs.setdefault("previous_representation_status", attrs.get("representation_status"))
        attrs.setdefault("previous_authority", attrs.get("authority"))
        if "validated_utc" in attrs:
            attrs["migration_source_validated_utc"] = attrs.pop("validated_utc")
        if "intended_future_role" in attrs:
            attrs["previous_intended_future_role"] = attrs.pop("intended_future_role")
        attrs["generation_0_canonical_sha256"] = attrs.pop(
            "effective_terrain_canonical_sha256"
        )
        if "composition" in attrs:
            attrs["migration_composition"] = attrs.pop("composition")
        attrs["current_content_identity"] = "AUTHORITY_MANIFEST_GENERATION_AND_ROOT_HASH"
        attrs["representation_status"] = "ACTIVE_EDITABLE_WORKING_AUTHORITY"
        attrs["authority"] = "EDITABLE_WORKING_AUTHORITY"
        attrs["current_role"] = "EDITABLE_WORKING_AUTHORITY"
        attrs["active_generator_integration"] = True
        attrs["authority_promoted_utc"] = utc_now()
        metadata["attributes"] = attrs
        atomic_write_json(metadata_path, metadata)
        metadata = zarr_metadata(array_root)
        records = shard_records(array_root)
        if not records:
            raise AuthorityError("Refusing to initialize an authority without shard files")
        controls = safe_child(authority_root, CONTROL_DIR)
        if not controls.exists():
            controls.mkdir()
        controls = require_safe_root(controls)
        for name in (TX_DIR, EXPORT_DIR):
            child = safe_child(controls, name)
            if not child.exists():
                child.mkdir()
        manifest = build_manifest(authority_root, array_relpath, metadata, records)
        atomic_write_json(authority_root / MANIFEST_NAME, manifest)
        return manifest


def affected_shard_paths(metadata: dict[str, Any], window: Sequence[int]) -> list[str]:
    row0, row1, col0, col1 = map(int, window)
    shape = tuple(map(int, metadata["shape"]))
    if not (0 <= row0 < row1 <= shape[0] and 0 <= col0 < col1 <= shape[1]):
        raise AuthorityError(f"Window {tuple(window)} is outside array shape {shape}")
    outer = tuple(map(int, metadata["chunk_grid"]["configuration"]["chunk_shape"]))
    paths = []
    for shard_row in range(row0 // outer[0], (row1 - 1) // outer[0] + 1):
        for shard_col in range(col0 // outer[1], (col1 - 1) // outer[1] + 1):
            paths.append(f"c/{shard_row}/{shard_col}")
    return sorted(paths)


def shard_window(metadata: dict[str, Any], relative: str) -> tuple[int, int, int, int]:
    parts = Path(relative).parts
    if len(parts) != 3 or parts[0] != "c":
        raise AuthorityError(f"Unexpected shard path: {relative}")
    shard_row, shard_col = int(parts[1]), int(parts[2])
    outer = tuple(map(int, metadata["chunk_grid"]["configuration"]["chunk_shape"]))
    shape = tuple(map(int, metadata["shape"]))
    row0, col0 = shard_row * outer[0], shard_col * outer[1]
    return row0, min(row0 + outer[0], shape[0]), col0, min(col0 + outer[1], shape[1])


def copy_recovery(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return {"exists": False, "sha256": None, "size_bytes": 0}
    shutil.copy2(source, destination)
    fsync_file(destination)
    set_read_only(destination)
    return {
        "exists": True,
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
    }


def copy_writable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    make_writable(destination)


def update_journal(path: Path, journal: dict[str, Any], state: str, **fields: Any) -> dict[str, Any]:
    journal.update(fields)
    journal["state"] = state
    journal["updated_utc"] = utc_now()
    return write_control_json(path, journal)


def remove_active_pointer(authority_root: Path, tx_root: Path) -> None:
    active = authority_root / ACTIVE_NAME
    if active.exists():
        pointer = read_json(active)
        validate_control_hash(pointer, "active transaction pointer")
        if str(pointer.get("transaction_id")) != tx_root.name:
            raise AuthorityError("Active pointer belongs to a different transaction")
        completed = tx_root / f"active-pointer-removed-{uuid.uuid4().hex}.json"
        os.replace(active, completed)
        fsync_parent(active)


def _open_zarr(path: Path, mode: str) -> Any:
    import zarr

    return zarr.open_array(str(path), mode=mode)


def _expected_shard_array(
    live_array: Any,
    metadata: dict[str, Any],
    shard_path: str,
    edit_window: Sequence[int],
    patch: Any,
) -> tuple[Any, tuple[int, int, int, int]]:
    import numpy as np

    sr0, sr1, sc0, sc1 = shard_window(metadata, shard_path)
    expected = np.asarray(live_array[sr0:sr1, sc0:sc1]).copy()
    row0, row1, col0, col1 = map(int, edit_window)
    ir0, ir1 = max(sr0, row0), min(sr1, row1)
    ic0, ic1 = max(sc0, col0), min(sc1, col1)
    if ir0 < ir1 and ic0 < ic1:
        expected[ir0 - sr0 : ir1 - sr0, ic0 - sc0 : ic1 - sc0] = patch[
            ir0 - row0 : ir1 - row0, ic0 - col0 : ic1 - col0
        ]
    return expected, (sr0, sr1, sc0, sc1)


def edit_window(
    authority_root: Path,
    window: Sequence[int],
    patch_npy: Path,
    *,
    note: str,
    expected_root: str | None = None,
    max_cells: int = 25_000_000,
    fail_after_shards: int | None = None,
) -> dict[str, Any]:
    import numpy as np

    authority_root = require_safe_root(authority_root)
    patch_npy = patch_npy.resolve()
    txid = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    tx_root = transaction_root(authority_root, txid)
    journal_path = tx_root / "journal.json"
    journal: dict[str, Any] = {}
    live_mutation_started = False
    with ExclusiveAccess(authority_root, f"edit:{txid}"):
        require_no_unfinished(authority_root)
        manifest = verify_manifest(authority_root, verify_last_touched=True)
        if expected_root and expected_root != manifest["root_hash"]:
            raise AuthorityError("Expected authority root does not match current root")
        array_root, metadata_path = array_paths(authority_root, manifest)
        metadata = zarr_metadata(array_root)
        row0, row1, col0, col1 = map(int, window)
        cells = (row1 - row0) * (col1 - col0)
        if cells <= 0 or cells > max_cells:
            raise AuthorityError(f"Edit contains {cells:,} cells; bounded limit is {max_cells:,}")
        patch = np.load(patch_npy, allow_pickle=False)
        expected_shape = (row1 - row0, col1 - col0)
        expected_dtype = np.dtype(metadata["data_type"])
        if patch.shape != expected_shape or patch.dtype != expected_dtype:
            raise AuthorityError(
                f"Patch must be shape {expected_shape}, dtype {expected_dtype}; got {patch.shape}, {patch.dtype}"
            )
        touched_paths = affected_shard_paths(metadata, window)
        tx_root.mkdir(parents=True, exist_ok=False)
        stage_array_root = tx_root / "stage" / Path(manifest["array_relpath"])
        recovery_array_root = tx_root / "recovery" / Path(manifest["array_relpath"])
        stage_array_root.mkdir(parents=True)
        recovery_array_root.mkdir(parents=True)
        journal = {
            "schema": JOURNAL_SCHEMA,
            "transaction_id": txid,
            "state": "STARTED",
            "created_utc": utc_now(),
            "updated_utc": utc_now(),
            "authority_id": manifest["authority_id"],
            "old_generation": manifest["generation"],
            "old_root_hash": manifest["root_hash"],
            "new_generation": int(manifest["generation"]) + 1,
            "new_root_hash": None,
            "window_half_open": [row0, row1, col0, col1],
            "patch_npy": str(patch_npy),
            "patch_sha256": sha256_file(patch_npy),
            "note": note,
            "touched_shards": [],
            "committed_shards": [],
        }
        journal = write_control_json(journal_path, journal)
        write_control_json(
            authority_root / ACTIVE_NAME,
            {
                "schema": "diadem.zarr-active-transaction.v1",
                "transaction_id": txid,
                "journal": str(journal_path.relative_to(authority_root).as_posix()),
                "state": "ACTIVE",
                "created_utc": utc_now(),
            },
        )
        try:
            # Recovery material is immutable and retained after both commit and rollback.
            old_manifest_recovery = tx_root / "recovery" / MANIFEST_NAME
            copy_recovery(authority_root / MANIFEST_NAME, old_manifest_recovery)
            copy_recovery(metadata_path, recovery_array_root / "zarr.json")
            copy_writable(metadata_path, stage_array_root / "zarr.json")
            old_records = {str(item["path"]): item for item in manifest["shards"]}
            touched: list[dict[str, Any]] = []
            for relative in touched_paths:
                live = safe_child(array_root, relative)
                recovery = recovery_array_root / Path(relative)
                stage = stage_array_root / Path(relative)
                recovery_info = copy_recovery(live, recovery)
                if live.exists():
                    copy_writable(live, stage)
                catalogue_record = old_records.get(relative)
                if bool(catalogue_record) != bool(recovery_info["exists"]):
                    raise AuthorityError(f"Manifest/live existence mismatch before edit: {relative}")
                if catalogue_record and (
                    catalogue_record["sha256"] != recovery_info["sha256"]
                    or int(catalogue_record["size_bytes"]) != int(recovery_info["size_bytes"])
                ):
                    raise AuthorityError(f"Manifest/live hash mismatch before edit: {relative}")
                touched.append(
                    {
                        "path": relative,
                        "old_exists": recovery_info["exists"],
                        "old_sha256": recovery_info["sha256"],
                        "old_size_bytes": recovery_info["size_bytes"],
                        "new_exists": None,
                        "new_sha256": None,
                        "new_size_bytes": None,
                    }
                )
            journal = update_journal(
                journal_path, journal, "RECOVERY_CAPTURED", touched_shards=touched
            )

            live_array = _open_zarr(array_root, "r")
            stage_array = _open_zarr(stage_array_root, "r+")
            # Decode each touched shard before mutation.  Zarr's crc32c codec validates
            # the inner chunks while they are read.
            expected_by_shard: dict[str, tuple[Any, tuple[int, int, int, int]]] = {}
            for relative in touched_paths:
                expected_by_shard[relative] = _expected_shard_array(
                    live_array, metadata, relative, window, patch
                )
            stage_array[row0:row1, col0:col1] = patch
            readback = np.asarray(stage_array[row0:row1, col0:col1])
            if not exact_array_equal(readback, patch):
                raise AuthorityError("Staged patch failed exact bitwise readback")
            for relative in touched_paths:
                expected, (sr0, sr1, sc0, sc1) = expected_by_shard[relative]
                actual = np.asarray(stage_array[sr0:sr1, sc0:sc1])
                if not exact_array_equal(actual, expected):
                    raise AuthorityError(
                        f"Staged edit changed data outside the requested window in {relative}"
                    )
            del stage_array
            del live_array

            updated_records = dict(old_records)
            for item in touched:
                staged = stage_array_root / Path(item["path"])
                if staged.exists():
                    item["new_exists"] = True
                    item["new_sha256"] = sha256_file(staged)
                    item["new_size_bytes"] = staged.stat().st_size
                    updated_records[item["path"]] = {
                        "path": item["path"],
                        "sha256": item["new_sha256"],
                        "size_bytes": item["new_size_bytes"],
                    }
                else:
                    item["new_exists"] = False
                    updated_records.pop(item["path"], None)
            new_records = [updated_records[key] for key in sorted(updated_records)]
            new_manifest = dict(manifest)
            new_manifest.update(
                {
                    "generation": int(manifest["generation"]) + 1,
                    "updated_utc": utc_now(),
                    "shards": new_records,
                    "root_hash": merkle_root(manifest["metadata_sha256"], new_records),
                    "last_transaction": {
                        "transaction_id": txid,
                        "committed_utc": None,
                        "window_half_open": [row0, row1, col0, col1],
                        "patch_sha256": journal["patch_sha256"],
                        "note": note,
                        "touched_shards": touched,
                    },
                }
            )
            new_manifest = with_control_hash(new_manifest)
            new_manifest_path = tx_root / "stage" / MANIFEST_NAME
            atomic_write_json(new_manifest_path, new_manifest)
            journal = update_journal(
                journal_path,
                journal,
                "PREPARED",
                touched_shards=touched,
                new_root_hash=new_manifest["root_hash"],
                new_manifest_control_sha256=new_manifest["control_sha256"],
            )

            journal = update_journal(journal_path, journal, "COMMITTING")
            live_mutation_started = True
            committed: list[str] = []
            for item in touched:
                relative = item["path"]
                live = safe_child(array_root, relative)
                staged = stage_array_root / Path(relative)
                live.parent.mkdir(parents=True, exist_ok=True)
                if item["new_exists"]:
                    if not same_volume(staged, live.parent):
                        raise AuthorityError("Staging and authority must be on the same volume")
                    os.replace(staged, live)
                    fsync_file(live)
                    if sha256_file(live) != item["new_sha256"]:
                        raise AuthorityError(f"Committed shard verification failed: {relative}")
                elif live.exists():
                    removed = tx_root / "commit-removed" / Path(relative)
                    removed.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live, removed)
                fsync_parent(live)
                committed.append(relative)
                journal = update_journal(
                    journal_path, journal, "COMMITTING", committed_shards=committed
                )
                if fail_after_shards is not None and len(committed) >= fail_after_shards:
                    raise AuthorityError("Injected test failure after shard replacement")

            new_manifest["last_transaction"]["committed_utc"] = utc_now()
            new_manifest = with_control_hash(new_manifest)
            atomic_write_json(new_manifest_path, new_manifest)
            if not same_volume(new_manifest_path, authority_root):
                raise AuthorityError("Manifest staging and authority must be on the same volume")
            os.replace(new_manifest_path, authority_root / MANIFEST_NAME)
            fsync_file(authority_root / MANIFEST_NAME)
            fsync_parent(authority_root / MANIFEST_NAME)
            verify_manifest(authority_root, verify_last_touched=True)
            journal = update_journal(
                journal_path,
                journal,
                "COMMITTED",
                committed_shards=committed,
                committed_utc=utc_now(),
                new_root_hash=new_manifest["root_hash"],
            )
            remove_active_pointer(authority_root, tx_root)
            return {
                "status": "COMMITTED",
                "transaction_id": txid,
                "generation": new_manifest["generation"],
                "old_root_hash": manifest["root_hash"],
                "new_root_hash": new_manifest["root_hash"],
                "touched_shards": touched_paths,
                "recovery_path": str((tx_root / "recovery").resolve()),
            }
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc), "utc": utc_now()}
            if journal_path.exists():
                if live_mutation_started:
                    update_journal(
                        journal_path, journal, "RECOVERY_REQUIRED", error=error
                    )
                    # ACTIVE_TRANSACTION deliberately remains. Runtime must refuse.
                else:
                    update_journal(journal_path, journal, "ABORTED", error=error)
                    remove_active_pointer(authority_root, tx_root)
            raise


def _find_recovery_tx(authority_root: Path, txid: str | None) -> tuple[Path, dict[str, Any]]:
    if txid:
        tx_root = transaction_root(authority_root, txid)
    else:
        active = authority_root / ACTIVE_NAME
        if not active.exists():
            unfinished = unfinished_transactions(authority_root)
            journals = [path for path, _ in unfinished if path.name == "journal.json"]
            if len(journals) != 1:
                raise AuthorityError("Specify --transaction-id; no unique active transaction")
            tx_root = journals[0].parent
        else:
            pointer = read_json(active)
            validate_control_hash(pointer, "active transaction pointer")
            tx_root = transaction_root(authority_root, str(pointer["transaction_id"]))
    journal_path = tx_root / "journal.json"
    journal = read_json(journal_path)
    validate_control_hash(journal, "transaction journal")
    return tx_root, journal


def recover_transaction(
    authority_root: Path,
    *,
    txid: str | None = None,
    mode: str = "auto",
    break_stale_lock: bool = False,
) -> dict[str, Any]:
    authority_root = require_safe_root(authority_root)
    with ExclusiveAccess(authority_root, "recover", break_stale=break_stale_lock):
        tx_root, journal = _find_recovery_tx(authority_root, txid)
        journal_path = tx_root / "journal.json"
        if journal.get("state") in TERMINAL_STATES:
            active = authority_root / ACTIVE_NAME
            if active.exists():
                pointer = read_json(active)
                validate_control_hash(pointer, "active transaction pointer")
                if str(pointer.get("transaction_id")) == str(journal["transaction_id"]):
                    remove_active_pointer(authority_root, tx_root)
            return {"status": journal["state"], "transaction_id": journal["transaction_id"]}
        old_manifest_path = tx_root / "recovery" / MANIFEST_NAME
        if not old_manifest_path.is_file():
            if journal.get("state") in {"STARTED", "RECOVERY_CAPTURED", "PREPARED"}:
                try:
                    current = verify_manifest(authority_root, verify_all_shards=True)
                except Exception:
                    current = None
                if (
                    current is not None
                    and int(current.get("generation", -1)) == int(journal.get("old_generation", -2))
                    and current.get("root_hash") == journal.get("old_root_hash")
                ):
                    journal = update_journal(
                        journal_path,
                        journal,
                        "ABORTED",
                        recovered_utc=utc_now(),
                        recovery_mode="safe-pre-mutation-abort",
                    )
                    remove_active_pointer(authority_root, tx_root)
                    return {
                        "status": "ABORTED",
                        "transaction_id": journal["transaction_id"],
                        "recovery_mode": "safe-pre-mutation-abort",
                    }
            raise AuthorityError("Immutable recovery manifest is missing")
        old_manifest = read_json(old_manifest_path)
        validate_control_hash(old_manifest, "recovery manifest")
        if journal.get("authority_id") != old_manifest.get("authority_id"):
            raise AuthorityError("Transaction/recovery authority identity mismatch")
        live_manifest: dict[str, Any] | None = None
        try:
            live_manifest = load_manifest(authority_root)
        except Exception:
            pass
        if (
            live_manifest is not None
            and live_manifest.get("authority_id") != journal.get("authority_id")
        ):
            raise AuthorityError("Refusing to recover an old transaction into a different authority")
        can_finalize = (
            mode == "auto"
            and live_manifest is not None
            and live_manifest.get("root_hash") == journal.get("new_root_hash")
            and int(live_manifest.get("generation", -1)) == int(journal.get("new_generation", -2))
        )
        if can_finalize:
            verify_manifest(authority_root, verify_last_touched=True)
            journal = update_journal(
                journal_path, journal, "COMMITTED", recovered_utc=utc_now(), recovery_mode="auto-finalize"
            )
            remove_active_pointer(authority_root, tx_root)
            return {
                "status": "COMMITTED",
                "transaction_id": journal["transaction_id"],
                "recovery_mode": "auto-finalize",
            }
        if mode not in {"auto", "rollback"}:
            raise AuthorityError("Recovery mode must be auto or rollback")
        array_root = safe_child(authority_root, str(old_manifest["array_relpath"]))
        recovery_array_root = tx_root / "recovery" / Path(old_manifest["array_relpath"])
        for item in journal.get("touched_shards", []):
            relative = normalize_relpath(str(item["path"]))
            live = safe_child(array_root, relative)
            recovery = recovery_array_root / Path(relative)
            if item.get("old_exists"):
                if not recovery.is_file() or sha256_file(recovery) != item.get("old_sha256"):
                    raise AuthorityError(f"Immutable recovery shard is missing/corrupt: {relative}")
                live.parent.mkdir(parents=True, exist_ok=True)
                temp = live.with_name(f".{live.name}.{uuid.uuid4().hex}.rollback")
                shutil.copy2(recovery, temp)
                make_writable(temp)
                fsync_file(temp)
                os.replace(temp, live)
                fsync_file(live)
                if (
                    live.stat().st_size != int(item["old_size_bytes"])
                    or sha256_file(live) != item["old_sha256"]
                ):
                    raise AuthorityError(f"Restored shard failed exact verification: {relative}")
            elif live.exists():
                removed = tx_root / "rollback-removed" / Path(relative)
                removed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(live, removed)
            if not item.get("old_exists") and live.exists():
                raise AuthorityError(f"Rollback failed to restore shard absence: {relative}")
            fsync_parent(live)
        manifest_temp = authority_root / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.rollback"
        shutil.copy2(old_manifest_path, manifest_temp)
        make_writable(manifest_temp)
        fsync_file(manifest_temp)
        os.replace(manifest_temp, authority_root / MANIFEST_NAME)
        fsync_file(authority_root / MANIFEST_NAME)
        verify_manifest(authority_root, verify_all_shards=True)
        journal = update_journal(
            journal_path, journal, "ROLLED_BACK", recovered_utc=utc_now(), recovery_mode="rollback"
        )
        remove_active_pointer(authority_root, tx_root)
        return {
            "status": "ROLLED_BACK",
            "transaction_id": journal["transaction_id"],
            "generation": old_manifest["generation"],
            "root_hash": old_manifest["root_hash"],
            "immutable_recovery_retained": str((tx_root / "recovery").resolve()),
        }


class AuthorityReadSession(AbstractContextManager["AuthorityReadSession"]):
    """Exclusive runtime session that prevents reads during edits/exports."""

    def __init__(self, authority_root: Path, *, verify_last_touched: bool = True):
        self.root = require_safe_root(authority_root)
        self.verify_last_touched = verify_last_touched
        self._access: ExclusiveAccess | None = None
        self.manifest: dict[str, Any] | None = None
        self.array: Any = None

    def __enter__(self) -> "AuthorityReadSession":
        if (self.root / LOCK_NAME).exists():
            raise AuthorityError("Authority is locked; runtime refuses concurrent access")
        self._access = ExclusiveAccess(self.root, "runtime-read")
        self._access.__enter__()
        try:
            require_no_unfinished(self.root)
            self.manifest = verify_manifest(
                self.root, verify_last_touched=self.verify_last_touched
            )
            array_root, _ = array_paths(self.root, self.manifest)
            self.array = _open_zarr(array_root, "r")
            return self
        except Exception:
            self._access.__exit__(*sys.exc_info())
            self._access = None
            raise

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.array = None
        if self._access:
            self._access.__exit__(exc_type, exc, tb)
            self._access = None


def _iter_windows(shape: Sequence[int], block: int = 2048) -> Iterator[tuple[int, int, int, int]]:
    for row0 in range(0, int(shape[0]), block):
        row1 = min(row0 + block, int(shape[0]))
        for col0 in range(0, int(shape[1]), block):
            col1 = min(col0 + block, int(shape[1]))
            yield row0, row1, col0, col1


def _raster_profile(metadata: dict[str, Any]) -> dict[str, Any]:
    from rasterio.transform import Affine

    attrs = metadata.get("attributes") or {}
    transform_values = attrs.get("transform")
    if not isinstance(transform_values, list) or len(transform_values) != 6:
        raise AuthorityError("Zarr authority metadata lacks a six-value affine transform")
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": int(metadata["shape"][0]),
        "width": int(metadata["shape"][1]),
        "count": 1,
        "dtype": metadata["data_type"],
        "transform": Affine(*map(float, transform_values)),
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "ZSTD",
        "zstd_level": 3,
        "predictor": 3,
        "num_threads": 1,
        "BIGTIFF": "IF_SAFER",
    }
    if attrs.get("crs_wkt"):
        profile["crs"] = attrs["crs_wkt"]
    if "nodata" in attrs and attrs["nodata"] is not None:
        profile["nodata"] = attrs["nodata"]
    return profile


def _write_base_geotiff(array: Any, metadata: dict[str, Any], path: Path) -> None:
    import numpy as np
    import rasterio
    from rasterio.windows import Window

    profile = _raster_profile(metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as destination:
        for row0, row1, col0, col1 in _iter_windows(metadata["shape"]):
            values = np.asarray(array[row0:row1, col0:col1])
            destination.write(values, 1, window=Window(col0, row0, col1 - col0, row1 - row0))
    fsync_file(path)


def _verify_raster_exact(
    array: Any, metadata: dict[str, Any], path: Path, *, require_cog: bool = False
) -> dict[str, Any]:
    import numpy as np
    import rasterio
    from rasterio.transform import Affine
    from rasterio.windows import Window

    attrs = metadata.get("attributes") or {}
    expected_transform = Affine(*map(float, attrs["transform"]))
    with rasterio.open(path) as source:
        if source.width != int(metadata["shape"][1]) or source.height != int(metadata["shape"][0]):
            raise AuthorityError(f"Raster dimensions differ from authority: {path}")
        if source.count != 1 or np.dtype(source.dtypes[0]) != np.dtype(metadata["data_type"]):
            raise AuthorityError(f"Raster dtype/band count differs from authority: {path}")
        if source.transform != expected_transform:
            raise AuthorityError(f"Raster affine transform differs from authority: {path}")
        expected_crs = attrs.get("crs_wkt")
        actual_crs = source.crs.to_wkt() if source.crs else None
        if expected_crs is None and actual_crs is not None:
            raise AuthorityError(f"Raster unexpectedly has a CRS: {path}")
        if expected_crs is not None:
            from rasterio.crs import CRS

            if source.crs != CRS.from_wkt(expected_crs):
                raise AuthorityError(f"Raster CRS differs from authority: {path}")
        expected_nodata = attrs.get("nodata")
        if expected_nodata != source.nodata and not (
            expected_nodata is not None
            and source.nodata is not None
            and np.isnan(expected_nodata)
            and np.isnan(source.nodata)
        ):
            raise AuthorityError(f"Raster nodata differs from authority: {path}")
        layout = source.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
        overviews = source.overviews(1)
        if require_cog:
            if source.driver != "GTiff" or layout != "COG":
                raise AuthorityError(f"Derived raster is not a Cloud-Optimized GeoTIFF: {path}")
            if max(source.width, source.height) > 512 and not overviews:
                raise AuthorityError(f"Large COG lacks reduced-resolution overviews: {path}")
        for row0, row1, col0, col1 in _iter_windows(metadata["shape"]):
            expected = np.asarray(array[row0:row1, col0:col1])
            actual = source.read(1, window=Window(col0, row0, col1 - col0, row1 - row0))
            if not exact_array_equal(actual, expected):
                raise AuthorityError(f"Raster pixel bits differ from authority in {path}")
    return {
        "exact_pixel_bits": True,
        "exact_affine": True,
        "exact_crs": True,
        "exact_nodata": True,
        "cog_layout": layout == "COG" if require_cog else None,
        "overview_levels": overviews,
    }


def _output_record(kind: str, path: Path, validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "validation": validation,
    }


def _build_handoff(
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    *,
    workspace_root: Path,
    target_relative_path: str,
    existing_drive_file_id: str | None,
    target_folder_id: str | None,
    receipt_path: Path,
) -> dict[str, Any]:
    output = receipt["outputs"][0]
    is_update = bool(existing_drive_file_id)
    operation = "update" if is_update else "create"
    publication_method = "drive_binary_update" if is_update else "drive_binary_create"
    parameters: dict[str, Any] = {
        "WorkspaceRoot": str(workspace_root),
        "PayloadRelativePath": target_relative_path,
        "TargetRelativePath": target_relative_path,
        "Operation": operation,
        "PublicationMethod": publication_method,
        "CreateMimeType": "image/tiff",
        "StatusLabel": f"Diadem terrain COG generation {manifest['generation']}",
        "Apply": True,
    }
    if not is_update:
        if not target_folder_id:
            raise AuthorityError("First-time COG creation requires a LocalFirst TargetFolderId")
        parameters["TargetFolderId"] = target_folder_id
    return with_control_hash(
        {
            "schema": HANDOFF_SCHEMA,
            "created_utc": utc_now(),
            "source_authority": {
                "authority_id": manifest["authority_id"],
                "generation": manifest["generation"],
                "root_hash": manifest["root_hash"],
            },
            "receipt_path": str(receipt_path),
            "publication_policy": "QUEUE_THEN_PREFLIGHT_THEN_REMOTE_WRITE_AND_READBACK",
            "target_relative_path": target_relative_path,
            "payload_relative_path": target_relative_path,
            "payload_sha256": output["sha256"],
            "payload_size_bytes": output["size_bytes"],
            "expected_existing_drive_file_id": existing_drive_file_id,
            "protected_snapshot_write_allowed": False,
            "add_publish_queue_item": {
                "tool": "Add-PublishQueueItem.ps1",
                "parameters": parameters,
            },
            "test_publish_preflight": {
                "tool": "Test-PublishPreflight.ps1",
                "parameters": {
                    "WorkspaceRoot": str(workspace_root),
                    "RemoteStatePath": "<connector-produced schema-v2 remote-state JSON path>",
                    "QueueItemId": "<queue_item_id returned by Add-PublishQueueItem>",
                    "Apply": True,
                },
            },
            "required_remote_completion": "Drive write, readback, receipt application, baseline refresh",
            "drive_write_performed": False,
        }
    )


def _valid_handoff(
    path: Path,
    expected: dict[str, Any],
) -> bool:
    try:
        actual = read_json(path)
        validate_control_hash(actual, "publication handoff")
    except Exception:
        return False
    for field in (
        "schema",
        "source_authority",
        "target_relative_path",
        "payload_relative_path",
        "payload_sha256",
        "payload_size_bytes",
        "expected_existing_drive_file_id",
        "add_publish_queue_item",
        "test_publish_preflight",
    ):
        if actual.get(field) != expected.get(field):
            return False
    return True


def finalize_day(
    authority_root: Path,
    *,
    workspace_root: Path,
    target_relative_path: str,
    existing_drive_file_id: str | None = None,
    target_folder_id: str | None = None,
) -> dict[str, Any]:
    import rasterio
    from rasterio.shutil import copy as raster_copy

    authority_root = require_safe_root(authority_root)
    workspace_root = require_safe_root(workspace_root)
    target_relative_path = normalize_relpath(target_relative_path)
    if target_relative_path.casefold().startswith(("01_drive_snapshot/", "02_working_files/")):
        raise AuthorityError(
            "LocalFirst paths are relative inside 02_Working_Files; omit the top-level prefix"
        )
    working_root = safe_child(workspace_root, "02_Working_Files")
    if not working_root.is_dir():
        raise AuthorityError(f"LocalFirst working root is missing: {working_root}")
    output = safe_child(working_root, target_relative_path, create_parents=True)
    # Re-evaluate after parent creation to close accidental path-mapping mistakes.
    output = safe_child(working_root, target_relative_path)

    controls = safe_child(authority_root, CONTROL_DIR)
    if not controls.is_dir():
        raise AuthorityError("Authority control directory is missing")
    exports = safe_child(controls, EXPORT_DIR)
    if not exports.exists():
        exports.mkdir()
    exports = require_safe_root(exports)
    receipt_path = safe_child(exports, "LATEST_EXPORT_RECEIPT.json")
    handoff_path = safe_child(exports, "DRIVE_PUBLICATION_HANDOFF.json")

    with ExclusiveAccess(authority_root, "end-of-day-finalize"):
        require_no_unfinished(authority_root)
        manifest = verify_manifest(authority_root, verify_last_touched=True)
        previous: dict[str, Any] | None = None
        routing_same = False
        try:
            candidate = read_json(receipt_path)
            validate_control_hash(candidate, "export receipt")
            if candidate.get("schema") != RECEIPT_SCHEMA:
                raise AuthorityError("Unexpected receipt schema")
            prior_output = candidate.get("outputs", [None])[0]
            if not isinstance(prior_output, dict):
                raise AuthorityError("Receipt output record is missing")
            same_content = (
                candidate.get("authority_id") == manifest["authority_id"]
                and int(candidate.get("generation", -1)) == int(manifest["generation"])
                and candidate.get("root_hash") == manifest["root_hash"]
                and candidate.get("target_relative_path") == target_relative_path
            )
            routing_same = (
                candidate.get("existing_drive_file_id") == existing_drive_file_id
                and candidate.get("target_folder_id") == target_folder_id
            )
            output_valid = (
                prior_output.get("kind") == "derived_cog_tiff"
                and Path(str(prior_output.get("path", ""))).resolve() == output.resolve()
                and output.is_file()
                and not is_reparse_point(output)
                and output.stat().st_size == int(prior_output.get("size_bytes", -1))
                and sha256_file(output) == prior_output.get("sha256")
            )
            if same_content and output_valid:
                previous = candidate
        except Exception:
            previous = None

        if previous is not None:
            if not routing_same:
                rebound_receipt = dict(previous)
                rebound_receipt.pop("control_sha256", None)
                rebound_receipt["created_utc"] = utc_now()
                rebound_receipt["existing_drive_file_id"] = existing_drive_file_id
                rebound_receipt["target_folder_id"] = target_folder_id
                previous = write_control_json(receipt_path, rebound_receipt)
            expected_handoff = _build_handoff(
                manifest,
                previous,
                workspace_root=workspace_root,
                target_relative_path=target_relative_path,
                existing_drive_file_id=existing_drive_file_id,
                target_folder_id=target_folder_id,
                receipt_path=receipt_path,
            )
            if routing_same and _valid_handoff(handoff_path, expected_handoff):
                return {
                    "status": "NO_CHANGE",
                    "generation": manifest["generation"],
                    "root_hash": manifest["root_hash"],
                    "receipt_path": str(receipt_path),
                    "handoff_path": str(handoff_path),
                    "message": "Authority generation and verified COG are unchanged.",
                }
            atomic_write_json(handoff_path, expected_handoff)
            return {
                "status": "HANDOFF_REBUILT",
                "generation": manifest["generation"],
                "root_hash": manifest["root_hash"],
                "receipt_path": str(receipt_path),
                "handoff_path": str(handoff_path),
            }

        array_root, _ = array_paths(authority_root, manifest)
        metadata = zarr_metadata(array_root)
        array = _open_zarr(array_root, "r")
        # Keep the staging path short.  LocalFirst mirrors Drive's descriptive
        # hierarchy, so placing a temporary directory beside the target can
        # exceed the legacy Windows MAX_PATH limit even when the final filename
        # itself is deliberately compact.  The authority controls and output
        # are required to be on the same volume so the final replacement stays
        # atomic.
        if os.stat(controls).st_dev != os.stat(output.parent).st_dev:
            raise AuthorityError("COG staging and output must be on the same volume")
        with tempfile.TemporaryDirectory(prefix=".dzt-", dir=controls) as temp_name:
            temp_dir = Path(temp_name)
            base_temp = temp_dir / "authority-base.tif"
            cog_temp = temp_dir / "authority-cog.tif"
            _write_base_geotiff(array, metadata, base_temp)
            _verify_raster_exact(array, metadata, base_temp)
            raster_copy(
                base_temp,
                cog_temp,
                driver="COG",
                compress="ZSTD",
                level=3,
                blocksize=512,
                overview_resampling="NEAREST",
                NUM_THREADS="1",
            )
            fsync_file(cog_temp)
            validation = _verify_raster_exact(array, metadata, cog_temp, require_cog=True)
            validated_temp_size = cog_temp.stat().st_size
            validated_temp_sha256 = sha256_file(cog_temp)
            # Final containment/reparse check immediately before atomic replacement.
            output = safe_child(working_root, target_relative_path)
            os.replace(cog_temp, output)
            fsync_file(output)
            fsync_parent(output)
            if (
                output.stat().st_size != validated_temp_size
                or sha256_file(output) != validated_temp_sha256
            ):
                raise AuthorityError("Final COG bytes differ from the exactly validated temporary COG")
            validation = _verify_raster_exact(array, metadata, output, require_cog=True)
        del array
        output_record = _output_record("derived_cog_tiff", output, validation)
        receipt = write_control_json(
            receipt_path,
            {
                "schema": RECEIPT_SCHEMA,
                "status": "EXPORTED_AND_EXACTLY_VALIDATED",
                "created_utc": utc_now(),
                "authority_id": manifest["authority_id"],
                "generation": manifest["generation"],
                "root_hash": manifest["root_hash"],
                "metadata_sha256": manifest["metadata_sha256"],
                "target_relative_path": target_relative_path,
                "existing_drive_file_id": existing_drive_file_id,
                "target_folder_id": target_folder_id,
                "outputs": [output_record],
                "tool_versions": {
                    "python": sys.version.split()[0],
                    "rasterio": rasterio.__version__,
                },
            },
        )
        handoff = _build_handoff(
            manifest,
            receipt,
            workspace_root=workspace_root,
            target_relative_path=target_relative_path,
            existing_drive_file_id=existing_drive_file_id,
            target_folder_id=target_folder_id,
            receipt_path=receipt_path,
        )
        atomic_write_json(handoff_path, handoff)
        return {
            "status": "EXPORTED",
            "generation": manifest["generation"],
            "root_hash": manifest["root_hash"],
            "outputs": [output_record],
            "receipt_path": str(receipt_path),
            "handoff_path": str(handoff_path),
        }


def inspect_authority(authority_root: Path, *, full: bool = False) -> dict[str, Any]:
    authority_root = require_safe_root(authority_root)
    if (authority_root / LOCK_NAME).exists():
        raise AuthorityError("Authority is locked; inspection refuses concurrent access")
    require_no_unfinished(authority_root)
    manifest = verify_manifest(
        authority_root, verify_all_shards=full, verify_last_touched=not full
    )
    return {
        "status": "PASS",
        "authority_id": manifest["authority_id"],
        "generation": manifest["generation"],
        "root_hash": manifest["root_hash"],
        "shard_count": len(manifest["shards"]),
        "verification_scope": "all_shards" if full else "controls_and_last_touched_shards",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Promote a copied validated Zarr store to working authority")
    init.add_argument("--authority-root", type=Path, required=True)
    init.add_argument("--array-relpath", default="effective_elevation_100m.zarr")
    init.add_argument("--expected-source-metadata-sha256", required=True)

    edit = sub.add_parser("edit", help="Commit one bounded rectangular .npy patch")
    edit.add_argument("--authority-root", type=Path, required=True)
    edit.add_argument("--window", type=int, nargs=4, metavar=("ROW0", "ROW1", "COL0", "COL1"), required=True)
    edit.add_argument("--patch-npy", type=Path, required=True)
    edit.add_argument("--note", required=True)
    edit.add_argument("--expected-root")
    edit.add_argument("--max-cells", type=int, default=25_000_000)
    edit.add_argument("--test-fail-after-shards", type=int, help=argparse.SUPPRESS)

    recover = sub.add_parser("recover", help="Finalize or roll back an interrupted commit")
    recover.add_argument("--authority-root", type=Path, required=True)
    recover.add_argument("--transaction-id")
    recover.add_argument("--mode", choices=("auto", "rollback"), default="auto")
    recover.add_argument("--break-stale-lock", action="store_true")

    verify = sub.add_parser("verify", help="Verify authority controls and shard hashes")
    verify.add_argument("--authority-root", type=Path, required=True)
    verify.add_argument("--full", action="store_true")

    export = sub.add_parser("finalize-day", help="Export dirty generation to one derived COG TIFF")
    export.add_argument("--authority-root", type=Path, required=True)
    export.add_argument("--workspace-root", type=Path, required=True)
    export.add_argument("--target-relative-path", required=True)
    export.add_argument("--existing-drive-file-id")
    export.add_argument("--target-folder-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = init_authority(
                args.authority_root,
                args.array_relpath,
                expected_source_metadata_sha256=args.expected_source_metadata_sha256,
            )
            output = {
                "status": "INITIALIZED",
                "authority_id": result["authority_id"],
                "generation": result["generation"],
                "root_hash": result["root_hash"],
                "shard_count": len(result["shards"]),
            }
        elif args.command == "edit":
            output = edit_window(
                args.authority_root,
                args.window,
                args.patch_npy,
                note=args.note,
                expected_root=args.expected_root,
                max_cells=args.max_cells,
                fail_after_shards=args.test_fail_after_shards,
            )
        elif args.command == "recover":
            output = recover_transaction(
                args.authority_root,
                txid=args.transaction_id,
                mode=args.mode,
                break_stale_lock=args.break_stale_lock,
            )
        elif args.command == "verify":
            output = inspect_authority(args.authority_root, full=args.full)
        elif args.command == "finalize-day":
            output = finalize_day(
                args.authority_root,
                workspace_root=args.workspace_root,
                target_relative_path=args.target_relative_path,
                existing_drive_file_id=args.existing_drive_file_id,
                target_folder_id=args.target_folder_id,
            )
        else:  # pragma: no cover
            raise AuthorityError(f"Unknown command: {args.command}")
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except AuthorityError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed, but retain a useful diagnostic
        print(
            json.dumps(
                {"status": "ERROR", "error": str(exc), "traceback": traceback.format_exc()},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
