#!/usr/bin/env python3
"""Create a new Stage 6D species catalogue from a reviewed ecology overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_ROW_OVERRIDES = {
    "population_unit",
    "population_low",
    "population_central",
    "population_high",
    "bond_capable_status",
    "bond_capable_low",
    "bond_capable_central",
    "bond_capable_high",
    "proposed_policy_cap",
    "provisional_active_primary_bonds",
    "eligibility_definition",
    "counting_scope",
    "unresolved_variables",
    "method",
    "uncertainty",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base = load_json(args.base)
    overlay = load_json(args.overlay)
    changes = overlay.get("rows")
    if not isinstance(changes, list) or not changes:
        raise ValueError("overlay rows must be a non-empty list")

    by_species: dict[str, dict] = {}
    for change in changes:
        species_id = str(change.get("species_id") or "").strip().upper()
        if not species_id or species_id in by_species:
            raise ValueError(f"invalid or duplicate species_id in overlay: {species_id!r}")
        unknown = set(change) - ALLOWED_ROW_OVERRIDES - {"species_id", "ecology"}
        if unknown:
            raise ValueError(f"unsupported override fields for {species_id}: {sorted(unknown)}")
        by_species[species_id] = change

    applied: list[str] = []
    ecology_rows: list[dict] = []
    for row in base["rows"]:
        species_id = row["species_id"]
        change = by_species.get(species_id)
        if change is None:
            continue
        for field in ALLOWED_ROW_OVERRIDES:
            if field in change:
                row[field] = change[field]
        ecology = change.get("ecology")
        if not isinstance(ecology, dict) or not ecology:
            raise ValueError(f"{species_id}: ecology metadata is required")
        ecology_rows.append({"haus_id": row["haus_id"], "species_id": species_id, **ecology})
        applied.append(species_id)

    missing = sorted(set(by_species) - set(applied))
    if missing:
        raise ValueError(f"overlay species missing from base catalogue: {missing}")
    if len(applied) != len(base["rows"]):
        raise ValueError(
            f"overlay must explicitly reconcile every base row; applied {len(applied)} of {len(base['rows'])}"
        )

    base["catalogue_version"] = str(overlay["catalogue_version"])
    base["reconciliation"] = {
        "status": "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON",
        "method_version": overlay["method_version"],
        "source_catalogue": str(args.base.resolve()),
        "species_count": len(applied),
        "ecology_rows": ecology_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(base, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "species_count": len(applied), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
