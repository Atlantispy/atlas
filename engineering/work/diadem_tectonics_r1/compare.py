"""Read-only exact comparison of the seven History A engineering products.

NPZ member order is not semantic. JSON list order, JSON scalar types, array
dtype/shape and C-order array bytes are semantic. PNGs are deliberately excluded.
The 64 MiB per-member limit exceeds the retained 1651 x 1951 float64 grids;
headers and payload lengths are checked before constructing an ndarray.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

import numpy as np


PREFIX = "checkpoint1-history-a-"
JSON_PRODUCTS = (
    "events.json", "faults-blocks.geojson", "provinces.geojson",
    "accommodation.geojson", "sections.geojson", "lineage.json",
)
ARRAY_NAMES = (
    "x_km", "y_km", "approved_peak_reference_names",
    "approved_peak_reference_xy_km", "approved_peak_reference_uncertainty_km",
    "annular_coordinate_elevation_contribution_m", "structural_model_domain_mask",
    "fault_block_id", "massif_structural_envelope_id", "crown_system_id",
    "crown_link_id", "accommodation_compartment_id", "block_relative_state_contribution",
    "fault_displacement_contribution", "crown_inherited_structure_contribution",
    "southern_renewal_contribution", "relative_structural_potential",
)
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_DIFFERENCES = 40
BLOCK_BYTES = 1024 * 1024


def _identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_BYTES), b""):
            digest.update(block)
            size += len(block)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite JSON number: {raw}")
    return value


def _invalid_constant(raw: str) -> None:
    raise ValueError(f"Nonfinite JSON constant: {raw}")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_pairs,
                         parse_float=_finite_float, parse_constant=_invalid_constant)


def _json_differences(reference: Any, candidate: Any) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    total = 0

    def add(path: str, reason: str, left: Any, right: Any) -> None:
        nonlocal total
        total += 1
        if len(records) < MAX_DIFFERENCES:
            records.append({"path": path or "/", "reason": reason,
                            "reference": repr(left)[:240], "candidate": repr(right)[:240]})

    def walk(left: Any, right: Any, path: str = "") -> None:
        if type(left) is not type(right):
            add(path, "scalar/container type differs", left, right)
        elif isinstance(left, dict):
            missing = sorted(left.keys() - right.keys())
            extra = sorted(right.keys() - left.keys())
            if missing or extra:
                add(path, "object key inventory differs", missing, extra)
            for key in sorted(left.keys() & right.keys()):
                escaped = key.replace("~", "~0").replace("/", "~1")
                walk(left[key], right[key], path + "/" + escaped)
        elif isinstance(left, list):
            if len(left) != len(right):
                add(path, "ordered list length differs", len(left), len(right))
            for index, (a, b) in enumerate(zip(left, right)):
                walk(a, b, path + f"/{index}")
        elif isinstance(left, float):
            if struct.pack(">d", left) != struct.pack(">d", right):
                add(path, "floating-point value differs", left, right)
        elif left != right:
            add(path, "value differs", left, right)

    walk(reference, candidate)
    return {"difference_count": total, "differences": records,
            "differences_truncated": total > len(records)}


def _archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members = archive.infolist()
    filenames = [item.filename for item in members]
    if len(filenames) != len(set(filenames)):
        raise ValueError("Duplicate NPZ member names")
    if any(item.orig_filename != item.filename for item in members):
        raise ValueError("Truncated/NUL-containing NPZ member name")
    expected = {name + ".npy" for name in ARRAY_NAMES}
    missing, extra = sorted(expected - set(filenames)), sorted(set(filenames) - expected)
    if missing or extra:
        raise ValueError(f"NPZ inventory differs: missing={missing}, extra={extra}")
    for item in members:
        if item.is_dir() or item.flag_bits & 1:
            raise ValueError(f"Directory/encrypted NPZ member: {item.filename}")
        if item.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"NPZ member exceeds {MAX_MEMBER_BYTES} bytes: {item.filename}")
    return {name[:-4]: item for name, item in zip(filenames, members)}


def _read_array(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> np.ndarray:
    # ZipFile.read validates decompression and CRC. Do not invoke pickle or
    # allocate from a declared shape before checking the complete payload.
    payload = archive.read(member)
    if len(payload) != member.file_size:
        raise ValueError(f"NPY member length differs: {member.filename}")
    stream = io.BytesIO(payload)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(
            stream, max_header_size=MAX_HEADER_BYTES)
    elif version == (2, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_2_0(
            stream, max_header_size=MAX_HEADER_BYTES)
    else:
        raise ValueError(f"Unsupported NPY version {version}: {member.filename}")
    if dtype.hasobject:
        raise ValueError(f"Object/pickle array forbidden: {member.filename}")
    if len(shape) > 32 or any(type(size) is not int or size < 0 for size in shape):
        raise ValueError(f"Invalid NPY shape: {member.filename}")
    count = math.prod(shape)
    byte_count = count * dtype.itemsize
    if byte_count > MAX_MEMBER_BYTES or stream.tell() + byte_count != len(payload):
        raise ValueError(f"NPY shape/dtype/payload length mismatch: {member.filename}")
    return np.frombuffer(payload, dtype=dtype, count=count, offset=stream.tell()).reshape(
        shape, order="F" if fortran else "C")


def _array_bytes(array: np.ndarray) -> memoryview:
    contiguous = np.ascontiguousarray(array)
    return memoryview(contiguous.reshape(-1).view(np.uint8))


def _array_identity(array: np.ndarray, raw: memoryview) -> dict[str, Any]:
    return {"shape": list(array.shape), "dtype": array.dtype.str,
            "dtype_description": array.dtype.descr if array.dtype.fields else None,
            "bytes": raw.nbytes, "sha256": hashlib.sha256(raw).hexdigest()}


def _bytes_equal(left: memoryview, right: memoryview) -> bool:
    if left.nbytes != right.nbytes:
        return False
    return all(left[start:start + BLOCK_BYTES].tobytes() ==
               right[start:start + BLOCK_BYTES].tobytes()
               for start in range(0, left.nbytes, BLOCK_BYTES))


def _lineage_check(lineage: Any, hashes: dict[str, str]) -> dict[str, Any]:
    if not isinstance(lineage, dict) or not isinstance(lineage.get("array_hashes"), dict):
        return {"status": "FAIL", "error": "lineage.array_hashes must be an object"}
    declared = lineage["array_hashes"]
    expected = set(ARRAY_NAMES)
    missing, extra = sorted(expected - declared.keys()), sorted(declared.keys() - expected)
    unavailable = sorted(expected - hashes.keys())
    mismatches = [
        {"array": name, "declared": declared[name], "actual": hashes[name]}
        for name in ARRAY_NAMES if name in declared and name in hashes
        and (type(declared[name]) is not str or declared[name] != hashes[name])
    ]
    return {"status": "PASS" if not (missing or extra or unavailable or mismatches) else "FAIL",
            "missing_keys": missing, "extra_keys": extra,
            "unavailable_arrays": unavailable, "hash_mismatches": mismatches}


def compare_products(reference_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    """Compare required products without writing, importing or running producers."""
    reference_dir, candidate_dir = Path(reference_dir), Path(candidate_dir)
    report: dict[str, Any] = {
        "schema": "diadem.tectonics.history-a-comparison.v1", "status": "FAIL",
        "reference_dir": str(reference_dir), "candidate_dir": str(candidate_dir),
        "scope": "Seven numerical/logical products only; PNGs and visual-review approval are not compared or conferred.",
        "npz_member_order_semantic": False, "files": {}, "arrays": {},
    }
    loaded: dict[str, Any] = {}
    for suffix in (*JSON_PRODUCTS, "structural-fields.npz"):
        filename = PREFIX + suffix
        paths = {"reference": reference_dir / filename, "candidate": candidate_dir / filename}
        entry: dict[str, Any] = {"status": "FAIL", "errors": []}
        report["files"][filename] = entry
        for role, path in paths.items():
            try:
                entry[role] = _identity(path)
            except (OSError, ValueError) as error:
                entry["errors"].append(f"{role}: {type(error).__name__}: {error}")
        if entry["errors"]:
            continue
        try:
            if suffix.endswith(".npz"):
                with zipfile.ZipFile(paths["reference"]) as ref_zip, zipfile.ZipFile(paths["candidate"]) as cand_zip:
                    ref_members, cand_members = _archive_members(ref_zip), _archive_members(cand_zip)
                    entry["key_inventory_exact"] = True
                    for name in ARRAY_NAMES:
                        array_entry: dict[str, Any] = {"status": "FAIL"}
                        report["arrays"][name] = array_entry
                        try:
                            left, right = _read_array(ref_zip, ref_members[name]), _read_array(cand_zip, cand_members[name])
                            left_bytes, right_bytes = _array_bytes(left), _array_bytes(right)
                            array_entry.update({
                                "reference": _array_identity(left, left_bytes),
                                "candidate": _array_identity(right, right_bytes),
                                "shape_exact": left.shape == right.shape,
                                "dtype_exact": left.dtype == right.dtype,
                                "raw_contiguous_bytes_exact": _bytes_equal(left_bytes, right_bytes),
                            })
                            array_entry["status"] = "PASS" if all(array_entry[key] for key in
                                ("shape_exact", "dtype_exact", "raw_contiguous_bytes_exact")) else "FAIL"
                            del left, right, left_bytes, right_bytes
                        except (OSError, ValueError, TypeError, EOFError, RuntimeError,
                                MemoryError, OverflowError, zipfile.BadZipFile, zlib.error) as error:
                            array_entry["error"] = f"{type(error).__name__}: {error}"
                    entry["status"] = "PASS" if all(row["status"] == "PASS" for row in report["arrays"].values()) else "FAIL"
            else:
                left, right = _read_json(paths["reference"]), _read_json(paths["candidate"])
                entry.update(_json_differences(left, right))
                entry["status"] = "PASS" if entry["difference_count"] == 0 else "FAIL"
                if suffix == "lineage.json":
                    loaded = {"reference": left, "candidate": right}
        except (OSError, ValueError, TypeError, EOFError, RuntimeError, MemoryError,
                OverflowError, zipfile.BadZipFile, zlib.error) as error:
            entry["errors"].append(f"{type(error).__name__}: {error}")
            entry["status"] = "FAIL"
        for role, path in paths.items():
            try:
                unchanged = _identity(path) == entry[role]
                entry[role + "_unchanged"] = unchanged
                if not unchanged:
                    entry["errors"].append(f"{role} file changed during comparison")
                    entry["status"] = "FAIL"
            except (OSError, ValueError) as error:
                entry["errors"].append(f"{role} recheck: {type(error).__name__}: {error}")
                entry["status"] = "FAIL"
    report["lineage_array_hashes"] = {}
    for role in ("reference", "candidate"):
        hashes = {name: row[role]["sha256"] for name, row in report["arrays"].items() if role in row}
        report["lineage_array_hashes"][role] = _lineage_check(loaded.get(role), hashes)
    if (all(row["status"] == "PASS" for row in report["files"].values())
            and len(report["arrays"]) == len(ARRAY_NAMES)
            and all(row["status"] == "PASS" for row in report["lineage_array_hashes"].values())):
        report["status"] = "PASS"
    return report
