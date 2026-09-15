#!/usr/bin/env python3
"""Create validated Zstd-Parquet analytical mirrors from an SQLite authority.

The SQLite database remains authoritative and is opened read-only. Large tables
are streamed in bounded batches, written to a sibling staging directory, read
back for exact typed-value parity, and only then installed atomically.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

EXPECTED_PYARROW = "25.0.1"
DEFAULT_MIN_ROWS = 10_000
# Phase 3 benchmark winner: a 65,536-row group was the best balanced layout
# for the current analytical tables.  The same value bounds SQLite fetching.
DEFAULT_BATCH_ROWS = 65_536
DEFAULT_ZSTD_LEVEL = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("invalid SQLite identifier")
    return '"' + value.replace('"', '""') + '"'


def arrow_type(declared: str) -> pa.DataType:
    value = declared.upper().strip()
    if "INT" in value:
        return pa.int64()
    if any(token in value for token in ("CHAR", "CLOB", "TEXT")):
        return pa.string()
    if any(token in value for token in ("REAL", "FLOA", "DOUB")):
        return pa.float64()
    if "BLOB" in value:
        return pa.binary()
    raise TypeError(f"unsupported SQLite declared type: {declared!r}")


def table_schema(connection: sqlite3.Connection, table_name: str) -> pa.Schema:
    quoted = quote_identifier(table_name)
    rows = list(connection.execute(f"PRAGMA table_info({quoted})"))
    if not rows:
        raise KeyError(f"table not found: {table_name}")
    return pa.schema([pa.field(row[1], arrow_type(row[2]), nullable=True) for row in rows])


def update_value(digest: Any, value: Any) -> None:
    if value is None:
        digest.update(b"N")
    elif isinstance(value, bool):
        digest.update(b"I" + struct.pack(">q", int(value)))
    elif isinstance(value, int):
        digest.update(b"I" + struct.pack(">q", value))
    elif isinstance(value, float):
        digest.update(b"F" + struct.pack(">d", value))
    elif isinstance(value, str):
        payload = value.encode("utf-8")
        digest.update(b"T" + struct.pack(">Q", len(payload)) + payload)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        digest.update(b"B" + struct.pack(">Q", len(payload)) + payload)
    else:
        raise TypeError(f"unsupported value type: {type(value).__name__}")


def update_row(digest: Any, row: Sequence[Any]) -> None:
    digest.update(b"R" + struct.pack(">I", len(row)))
    for value in row:
        update_value(digest, value)


def rows_to_table(rows: Sequence[Sequence[Any]], schema: pa.Schema) -> pa.Table:
    columns = []
    for index, field in enumerate(schema):
        columns.append(pa.array((row[index] for row in rows), type=field.type))
    return pa.Table.from_arrays(columns, schema=schema)


def parquet_digest(path: Path, batch_rows: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    row_count = 0
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=batch_rows):
        columns = [column.to_pylist() for column in batch.columns]
        for row in zip(*columns):
            update_row(digest, row)
            row_count += 1
    return row_count, digest.hexdigest()


def parquet_to_csv(path: Path, destination: Path, batch_rows: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    parquet = pq.ParquetFile(path)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(parquet.schema_arrow.names)
        for batch in parquet.iter_batches(batch_size=batch_rows):
            columns = [column.to_pylist() for column in batch.columns]
            for row in zip(*columns):
                writer.writerow(row)
                count += 1
    return count


def export_table(
    connection: sqlite3.Connection,
    table_name: str,
    destination: Path,
    batch_rows: int,
    include_csv: bool,
) -> dict[str, Any]:
    schema = table_schema(connection, table_name)
    quoted = quote_identifier(table_name)
    cursor = connection.execute(f"SELECT * FROM {quoted} ORDER BY rowid")
    source_digest = hashlib.sha256()
    row_count = 0
    started = time.perf_counter()
    parquet_path = destination / f"{table_name}.parquet"
    writer = pq.ParquetWriter(
        parquet_path,
        schema,
        compression="zstd",
        compression_level=DEFAULT_ZSTD_LEVEL,
        use_dictionary=True,
        write_statistics=True,
        data_page_version="2.0",
    )
    try:
        while True:
            rows = cursor.fetchmany(batch_rows)
            if not rows:
                break
            for row in rows:
                update_row(source_digest, row)
            writer.write_table(rows_to_table(rows, schema), row_group_size=len(rows))
            row_count += len(rows)
    finally:
        writer.close()
    write_seconds = time.perf_counter() - started

    verify_started = time.perf_counter()
    parquet_rows, readback_digest = parquet_digest(parquet_path, batch_rows)
    if parquet_rows != row_count or readback_digest != source_digest.hexdigest():
        raise AssertionError(f"typed-value parity failed for {table_name}")
    if pq.ParquetFile(parquet_path).schema_arrow != schema:
        raise AssertionError(f"schema parity failed for {table_name}")
    verify_seconds = time.perf_counter() - verify_started

    csv_info = None
    if include_csv:
        csv_path = destination / "review_exports" / f"{table_name}.csv"
        csv_rows = parquet_to_csv(parquet_path, csv_path, batch_rows)
        if csv_rows != row_count:
            raise AssertionError(f"CSV row-count parity failed for {table_name}")
        csv_info = {
            "relative_path": csv_path.relative_to(destination).as_posix(),
            "size_bytes": csv_path.stat().st_size,
            "sha256": sha256_file(csv_path),
            "row_count": csv_rows,
            "status": "DERIVED_HUMAN_REVIEW_EXPORT",
        }

    return {
        "table": table_name,
        "row_count": row_count,
        "column_count": len(schema),
        "schema": [{"name": field.name, "type": str(field.type)} for field in schema],
        "semantic_sha256": source_digest.hexdigest(),
        "parquet": {
            "relative_path": parquet_path.relative_to(destination).as_posix(),
            "size_bytes": parquet_path.stat().st_size,
            "sha256": sha256_file(parquet_path),
            "compression": "zstd",
            "compression_level": DEFAULT_ZSTD_LEVEL,
            "write_seconds": round(write_seconds, 6),
            "readback_verify_seconds": round(verify_seconds, 6),
        },
        "csv": csv_info,
        "parity": "PASS",
    }


def discover_tables(connection: sqlite3.Connection, minimum_rows: int) -> list[str]:
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    selected: list[str] = []
    for name in names:
        quoted = quote_identifier(name)
        if connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0] >= minimum_rows:
            selected.append(name)
    return selected


def build(args: argparse.Namespace) -> dict[str, Any]:
    if pa.__version__ != EXPECTED_PYARROW:
        raise RuntimeError(f"PyArrow {EXPECTED_PYARROW} required; found {pa.__version__}")
    database = args.database.resolve(strict=True)
    destination = args.output.resolve(strict=False)
    if destination == database or destination in database.parents:
        raise ValueError("output must not contain or equal the source database")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_state = {
        "size_bytes": database.stat().st_size,
        "last_write_ns": database.stat().st_mtime_ns,
        "sha256": sha256_file(database),
    }
    requested_selection = {
        "minimum_rows": args.min_rows,
        "explicit_tables": args.table,
        "include_csv": args.include_csv,
    }
    format_policy = {
        "row_group_rows": args.batch_rows,
        "compression": "zstd",
        "compression_level": DEFAULT_ZSTD_LEVEL,
        "dictionary_encoding": True,
        "write_statistics": True,
        "data_page_version": "2.0",
        "partitioning": "none",
    }
    if destination.exists():
        if destination.is_symlink():
            raise RuntimeError(f"refusing reparse/symlink destination: {destination}")
        existing_manifest_path = destination / "MANIFEST.json"
        if existing_manifest_path.is_file():
            existing = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
            outputs_valid = all(
                (destination / item["parquet"]["relative_path"]).is_file()
                and sha256_file(destination / item["parquet"]["relative_path"])
                == item["parquet"]["sha256"]
                and (
                    item.get("csv") is None
                    or (
                        (destination / item["csv"]["relative_path"]).is_file()
                        and sha256_file(destination / item["csv"]["relative_path"])
                        == item["csv"]["sha256"]
                    )
                )
                for item in existing.get("tables", [])
            )
            if (
                existing.get("source_database", {}).get("sha256") == source_state["sha256"]
                and existing.get("source_database", {}).get("size_bytes") == source_state["size_bytes"]
                and existing.get("selection") == requested_selection
                and existing.get("format_policy") == format_policy
                and existing.get("runtime", {}).get("pyarrow") == pa.__version__
                and outputs_valid
            ):
                return {**existing, "status": "NO_CHANGE"}
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir()
    started = time.perf_counter()
    previous = None
    try:
        uri = f"file:{database.as_posix()}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite quick_check failed")
            tables = args.table or discover_tables(connection, args.min_rows)
            if not tables:
                raise RuntimeError("no tables matched the export selection")
            results = [
                export_table(connection, name, staging, args.batch_rows, args.include_csv)
                for name in tables
            ]
        after = database.stat()
        if (after.st_size, after.st_mtime_ns) != (
            source_state["size_bytes"],
            source_state["last_write_ns"],
        ):
            raise RuntimeError("source database changed during export")
        manifest = {
            "schema_version": 1,
            "status": "PASS",
            "created_utc": utc_now(),
            "authority": "SQLITE_READ_ONLY_SOURCE",
            "source_database": {"path": str(database), **source_state},
            "runtime": {"python": sys.version.split()[0], "pyarrow": pa.__version__},
            "selection": requested_selection,
            "format_policy": format_policy,
            "batch_rows": args.batch_rows,
            "tables": results,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        }
        (staging / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if destination.exists():
            if not args.replace:
                raise FileExistsError(f"destination exists: {destination}")
            previous = destination.parent / f".{destination.name}.previous-{uuid.uuid4().hex}"
            destination.rename(previous)
        staging.rename(destination)
        if previous is not None:
            shutil.rmtree(previous)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if previous is not None and previous.exists() and not destination.exists():
            previous.rename(destination)
        raise


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--table", action="append", default=[])
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--batch-rows", type=int, default=DEFAULT_BATCH_ROWS)
    parser.add_argument("--include-csv", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    if args.min_rows < 1 or args.batch_rows < 1:
        parser.error("row limits must be positive")
    return args


def main() -> int:
    manifest = build(parse_args())
    print(json.dumps({
        "status": manifest["status"],
        "tables": [item["table"] for item in manifest["tables"]],
        "elapsed_seconds": manifest["elapsed_seconds"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
