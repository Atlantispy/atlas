#!/usr/bin/env python3
"""CLI for the independent Stage 6D primary-species census sidecar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage6d_species_census import build_species_census_sidecar


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--catalogue",
        type=Path,
        required=True,
        help="20-row JSON catalogue with explicit bond-capability completeness statuses",
    )
    result.add_argument("--v4-db", type=Path, required=True, help="Completed Stage 6D V4 SQLite")
    result.add_argument("--output-dir", type=Path, required=True, help="New or empty output folder")
    result.add_argument(
        "--skip-source-hash-verification",
        action="store_true",
        help="Development-only: validate declared hash syntax without reading source files",
    )
    result.add_argument(
        "--hash-v4-file",
        action="store_true",
        help=(
            "Opt in to hashing the full V4 SQLite. By default the completed V4 run ID "
            "and semantic source hash provide lineage without rereading the ~945 MB file."
        ),
    )
    return result


def main() -> int:
    args = parser().parse_args()
    result = build_species_census_sidecar(
        catalogue_path=args.catalogue,
        v4_database_path=args.v4_db,
        output_dir=args.output_dir,
        verify_source_hashes=not args.skip_source_hash_verification,
        hash_v4_file=args.hash_v4_file,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
