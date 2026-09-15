#!/usr/bin/env python3
"""Build a separate, non-canon Stage 6D primary-species census sidecar.

The numerical catalogue is deliberately external JSON.  This module validates
it against the existing 20-Haus species identity catalogue, compares it with a
Stage 6D V4 human ledger read-only, and writes a small independent SQLite/CSV/
JSON/README bundle.  It never edits or copies tables into the V4 database.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import stage6d_species_rules as species_rules


BUILDER_VERSION = "STAGE6D_PRIMARY_SPECIES_CENSUS_SIDECAR_V2"
SCHEMA_VERSION = "diadem.stage6d-primary-species-census-sidecar.v2"
NON_CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"

ONE_TO_ONE = "ONE_TO_ONE"
ONE_TO_MANY_UNIQUE_ENTITY = "ONE_TO_MANY_UNIQUE_ENTITY"
NO_PRIMARY_BOND = "NO_PRIMARY_BOND"
BOND_MODELS = frozenset({ONE_TO_ONE, ONE_TO_MANY_UNIQUE_ENTITY, NO_PRIMARY_BOND})
BOND_CAPABLE_COMPLETE = "COMPLETE"
BOND_CAPABLE_INCOMPLETE = "INCOMPLETE"
BOND_CAPABLE_STATUSES = frozenset({BOND_CAPABLE_COMPLETE, BOND_CAPABLE_INCOMPLETE})
POLICY_CAP_NONE = "NONE"
POLICY_CAP_USER_APPROVED = "USER_APPROVED"
POLICY_CAP_CANON_OR_REGISTRY = "CANON_OR_REGISTRY_SUPPORTED"
POLICY_CAP_STATUSES = frozenset(
    {POLICY_CAP_NONE, POLICY_CAP_USER_APPROVED, POLICY_CAP_CANON_OR_REGISTRY}
)
UNCERTAINTY_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "VERY_HIGH"})
TERRITORY_STATUSES = frozenset({"FOUND", "INCOMPLETE", "NOT_APPLICABLE"})

SCHWARZFLUT_PAIR = ("DUNKELHAUCH", "SCHWARZFLUT")
KEPT_PAIR = ("SEELENWACHT", "THE_KEPT")
DRAGON_PAIR = ("FEUERSCHUPPE", "DRACHE")
ROOTREACH_PAIR = ("VERFUEHRSCHLUND", "SUESSFAULSCHLUND")
DRAGON_PROVISIONAL_ACTIVE_TARGET = 398
SCHWARZFLUT_ACTIVE_CAP = 50
ROOTREACH_REGISTRY_CAP = 611
ACTIVE_CAP_SCOPE = "ESTABLISHED_HARD_POLICY_OR_REGISTRY_CEILING_WHEN_NON_NULL"
V4_COMPARISON_CAP_BASIS = "EFFECTIVE_ACTIVE_CAP_CENTRAL"

EXPLICIT_ESTABLISHED_CAPS = {
    SCHWARZFLUT_PAIR: (SCHWARZFLUT_ACTIVE_CAP, POLICY_CAP_USER_APPROVED),
    KEPT_PAIR: (0, POLICY_CAP_USER_APPROVED),
    ROOTREACH_PAIR: (ROOTREACH_REGISTRY_CAP, POLICY_CAP_CANON_OR_REGISTRY),
}

SQLITE_FILENAME = "Diadem_Stage6D_Primary_Species_Census_WORKING.sqlite"
CSV_FILENAME = "Diadem_Stage6D_Primary_Species_Census_Review_WORKING.csv"
SUMMARY_FILENAME = "Diadem_Stage6D_Primary_Species_Census_Summary_WORKING.json"
VALIDATION_FILENAME = "Diadem_Stage6D_Primary_Species_Census_Validation_WORKING.json"
README_FILENAME = "README_FIRST.md"

EXPECTED_SPECIES_BY_HAUS = {
    haus_id: rule.species_id
    for haus_id, rule in sorted(species_rules.SPECIES_RULES.items())
}
EXPECTED_PAIRS = frozenset(EXPECTED_SPECIES_BY_HAUS.items())

REQUIRED_ROW_FIELDS = frozenset(
    {
        "haus_id",
        "species_id",
        "display_name",
        "population_unit",
        "population_low",
        "population_central",
        "population_high",
        "bond_model",
        "bond_capable_status",
        "bond_capable_low",
        "bond_capable_central",
        "bond_capable_high",
        "maximum_active_primary_bonds",
        "policy_cap_status",
        "proposed_policy_cap",
        "provisional_active_primary_bonds",
        "territory_area_km2",
        "territory_area_status",
        "eligibility_definition",
        "counting_scope",
        "unresolved_variables",
        "method",
        "uncertainty",
        "canon_status",
        "source_evidence",
    }
)


class CatalogueValidationError(ValueError):
    """Raised when the input catalogue cannot safely produce a sidecar."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("species census catalogue failed validation:\n- " + "\n- ".join(self.errors))


@dataclass(frozen=True)
class V4Identity:
    run_id: str
    source_semantic_sha256: str
    canon_status: str
    completion_state: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _as_upper_id(value: Any) -> str:
    return str(value or "").strip().upper()


def _source_bundle_sha256(source_evidence: list[dict[str, Any]]) -> str:
    payload = [
        {
            "path": source["path"],
            "sections": source["sections"],
            "sha256": source["sha256"],
        }
        for source in source_evidence
    ]
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _normalise_source_evidence(
    row_label: str,
    value: Any,
    *,
    verify_source_hashes: bool,
    errors: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        errors.append(f"{row_label}: source_evidence must be a non-empty list")
        return []

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for index, source in enumerate(value):
        source_label = f"{row_label}.source_evidence[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{source_label}: must be an object")
            continue
        path_text = str(source.get("path") or "").strip()
        sections_value = source.get("sections")
        expected_hash = str(source.get("sha256") or "").strip().lower()
        if not path_text:
            errors.append(f"{source_label}: path is required")
        path = Path(path_text)
        if path_text and not path.is_absolute():
            errors.append(f"{source_label}: path must be absolute")
        if not isinstance(sections_value, list) or not sections_value:
            errors.append(f"{source_label}: sections must be a non-empty list")
            sections: list[str] = []
        else:
            sections = [str(section).strip() for section in sections_value]
            if any(not section for section in sections):
                errors.append(f"{source_label}: sections cannot contain empty values")
            if len(sections) != len(set(sections)):
                errors.append(f"{source_label}: duplicate section labels are not allowed")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            errors.append(f"{source_label}: sha256 must be 64 lowercase hexadecimal characters")

        identity = (path_text, tuple(sections))
        if identity in seen:
            errors.append(f"{source_label}: duplicate source path/section bundle")
        seen.add(identity)

        actual_hash: str | None = None
        verified = False
        if verify_source_hashes and path_text and path.is_absolute():
            if not path.is_file():
                errors.append(f"{source_label}: source file does not exist: {path}")
            else:
                actual_hash = sha256_file(path)
                verified = actual_hash == expected_hash
                if not verified:
                    errors.append(
                        f"{source_label}: source hash mismatch; expected {expected_hash}, got {actual_hash}"
                    )

        result.append(
            {
                "path": path_text,
                "sections": sections,
                "sha256": expected_hash,
                "actual_sha256": actual_hash,
                "hash_verified": verified if verify_source_hashes else None,
            }
        )
    return result


def validate_catalogue_data(
    catalogue: Any,
    *,
    verify_source_hashes: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate and normalise a complete 20-row numerical catalogue."""

    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    if not isinstance(catalogue, dict):
        raise CatalogueValidationError(("catalogue root must be a JSON object",))
    if catalogue.get("canon_status") != NON_CANON_STATUS:
        errors.append(f"catalogue canon_status must be {NON_CANON_STATUS}")
    version = str(catalogue.get("catalogue_version") or "").strip()
    if not version:
        errors.append("catalogue_version is required")
    rows_value = catalogue.get("rows")
    if not isinstance(rows_value, list):
        raise CatalogueValidationError((*errors, "catalogue rows must be a list"))
    if len(rows_value) != 20:
        errors.append(f"catalogue must contain exactly 20 rows, found {len(rows_value)}")

    normalised: list[dict[str, Any]] = []
    haus_ids: list[str] = []
    species_ids: list[str] = []
    pairs: list[tuple[str, str]] = []

    for index, raw in enumerate(rows_value):
        row_label = f"rows[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{row_label}: row must be an object")
            continue
        missing = sorted(REQUIRED_ROW_FIELDS - raw.keys())
        if missing:
            errors.append(f"{row_label}: missing required fields {missing}")

        haus_id = _as_upper_id(raw.get("haus_id"))
        species_id = _as_upper_id(raw.get("species_id"))
        row_label = f"{row_label} {haus_id or '<NO_HAUS>'}/{species_id or '<NO_SPECIES>'}"
        haus_ids.append(haus_id)
        species_ids.append(species_id)
        pairs.append((haus_id, species_id))

        if not haus_id or not species_id:
            errors.append(f"{row_label}: haus_id and species_id are required")
        expected_species = EXPECTED_SPECIES_BY_HAUS.get(haus_id)
        if expected_species is None:
            errors.append(f"{row_label}: unknown Haus ID")
        elif expected_species != species_id:
            errors.append(
                f"{row_label}: expected species_id {expected_species} for Haus {haus_id}"
            )

        display_name = str(raw.get("display_name") or "").strip()
        population_unit = str(raw.get("population_unit") or "").strip().upper()
        method = str(raw.get("method") or "").strip()
        uncertainty = str(raw.get("uncertainty") or "").strip().upper()
        canon_status = str(raw.get("canon_status") or "").strip()
        bond_model = str(raw.get("bond_model") or "").strip().upper()
        bond_capable_status = str(raw.get("bond_capable_status") or "").strip().upper()
        policy_cap_status = str(raw.get("policy_cap_status") or "").strip().upper()
        territory_status = str(raw.get("territory_area_status") or "").strip().upper()
        eligibility_value = raw.get("eligibility_definition")
        counting_scope_value = raw.get("counting_scope")
        eligibility_definition = (
            eligibility_value.strip() if isinstance(eligibility_value, str) else ""
        )
        counting_scope = (
            counting_scope_value.strip() if isinstance(counting_scope_value, str) else ""
        )
        unresolved_value = raw.get("unresolved_variables")
        if isinstance(unresolved_value, list):
            unresolved_variables = [
                value.strip() if isinstance(value, str) else "" for value in unresolved_value
            ]
        else:
            unresolved_variables = []

        if not display_name:
            errors.append(f"{row_label}: display_name is required")
        if not population_unit:
            errors.append(f"{row_label}: population_unit is required")
        if not method:
            errors.append(f"{row_label}: method is required")
        if uncertainty not in UNCERTAINTY_LEVELS:
            errors.append(f"{row_label}: uncertainty must be one of {sorted(UNCERTAINTY_LEVELS)}")
        if canon_status != NON_CANON_STATUS:
            errors.append(f"{row_label}: canon_status must be {NON_CANON_STATUS}")
        if bond_model not in BOND_MODELS:
            errors.append(f"{row_label}: bond_model must be one of {sorted(BOND_MODELS)}")
        if bond_capable_status not in BOND_CAPABLE_STATUSES:
            errors.append(
                f"{row_label}: bond_capable_status must be one of "
                f"{sorted(BOND_CAPABLE_STATUSES)}"
            )
        if policy_cap_status not in POLICY_CAP_STATUSES:
            errors.append(
                f"{row_label}: policy_cap_status must be one of {sorted(POLICY_CAP_STATUSES)}"
            )
        if bond_model == ONE_TO_MANY_UNIQUE_ENTITY and (haus_id, species_id) != SCHWARZFLUT_PAIR:
            errors.append(f"{row_label}: one-to-many is permitted only for Schwarzflut")
        if (haus_id, species_id) == SCHWARZFLUT_PAIR and bond_model != ONE_TO_MANY_UNIQUE_ENTITY:
            errors.append(f"{row_label}: Schwarzflut must use {ONE_TO_MANY_UNIQUE_ENTITY}")
        if not isinstance(eligibility_value, str) or not eligibility_definition:
            errors.append(f"{row_label}: eligibility_definition must be a non-empty string")
        if not isinstance(counting_scope_value, str) or not counting_scope:
            errors.append(f"{row_label}: counting_scope must be a non-empty string")
        if not isinstance(unresolved_value, list) or not unresolved_value:
            errors.append(f"{row_label}: unresolved_variables must be a non-empty list")
        elif any(not isinstance(value, str) for value in unresolved_value):
            errors.append(f"{row_label}: unresolved_variables must contain only strings")
        elif any(not value for value in unresolved_variables):
            errors.append(f"{row_label}: unresolved_variables cannot contain empty values")
        elif len(unresolved_variables) != len(set(unresolved_variables)):
            errors.append(f"{row_label}: unresolved_variables cannot contain duplicates")

        population_fields = (
            "population_low",
            "population_central",
            "population_high",
        )
        capable_fields = (
            "bond_capable_low",
            "bond_capable_central",
            "bond_capable_high",
        )
        integers: dict[str, int] = {}
        for field in population_fields:
            value = raw.get(field)
            if not _is_nonnegative_int(value):
                errors.append(f"{row_label}: {field} must be a non-negative integer")
            else:
                integers[field] = int(value)
        if bond_capable_status == BOND_CAPABLE_COMPLETE:
            for field in capable_fields:
                value = raw.get(field)
                if not _is_nonnegative_int(value):
                    errors.append(
                        f"{row_label}: COMPLETE {field} must be a non-negative integer"
                    )
                else:
                    integers[field] = int(value)
        elif bond_capable_status == BOND_CAPABLE_INCOMPLETE:
            if any(raw.get(field) is not None for field in capable_fields):
                errors.append(
                    f"{row_label}: INCOMPLETE bond-capable band must be all-null"
                )

        established_cap = raw.get("maximum_active_primary_bonds")
        if established_cap is not None and not _is_nonnegative_int(established_cap):
            errors.append(
                f"{row_label}: maximum_active_primary_bonds must be null or a non-negative integer"
            )
        proposed_cap = raw.get("proposed_policy_cap")
        if proposed_cap is not None and not _is_nonnegative_int(proposed_cap):
            errors.append(f"{row_label}: proposed_policy_cap must be null or a non-negative integer")
        if policy_cap_status == POLICY_CAP_NONE and established_cap is not None:
            errors.append(
                f"{row_label}: maximum_active_primary_bonds must be null when policy_cap_status is NONE"
            )
        if policy_cap_status in {POLICY_CAP_USER_APPROVED, POLICY_CAP_CANON_OR_REGISTRY}:
            if not _is_nonnegative_int(established_cap):
                errors.append(
                    f"{row_label}: an established policy status requires maximum_active_primary_bonds"
                )

        expected_cap = EXPLICIT_ESTABLISHED_CAPS.get((haus_id, species_id))
        if expected_cap is None:
            if established_cap is not None or policy_cap_status != POLICY_CAP_NONE:
                errors.append(
                    f"{row_label}: no established hard policy/registry cap is allowed for this species"
                )
        else:
            expected_value, expected_status = expected_cap
            if established_cap != expected_value or policy_cap_status != expected_status:
                errors.append(
                    f"{row_label}: established cap must be {expected_value} with status "
                    f"{expected_status}"
                )

        provisional = raw.get("provisional_active_primary_bonds")
        if provisional is not None and not _is_nonnegative_int(provisional):
            errors.append(
                f"{row_label}: provisional_active_primary_bonds must be null or a non-negative integer"
            )

        if all(field in integers for field in population_fields):
            pop = tuple(integers[f"population_{suffix}"] for suffix in ("low", "central", "high"))
            if not pop[0] <= pop[1] <= pop[2]:
                errors.append(f"{row_label}: population band must satisfy low <= central <= high")
            if (
                _is_nonnegative_int(provisional)
                and bond_model != ONE_TO_MANY_UNIQUE_ENTITY
                and provisional > pop[2]
            ):
                errors.append(
                    f"{row_label}: provisional active count cannot exceed population_high"
                )

        if all(field in integers for field in capable_fields):
            capable = tuple(
                integers[f"bond_capable_{suffix}"] for suffix in ("low", "central", "high")
            )
            if not capable[0] <= capable[1] <= capable[2]:
                errors.append(f"{row_label}: bond-capable band must satisfy low <= central <= high")
            if all(field in integers for field in population_fields):
                pop = tuple(
                    integers[f"population_{suffix}"] for suffix in ("low", "central", "high")
                )
                for suffix, bond_value, population_value in zip(
                    ("low", "central", "high"), capable, pop, strict=True
                ):
                    if bond_value > population_value:
                        errors.append(
                            f"{row_label}: bond_capable_{suffix} cannot exceed population_{suffix}"
                        )
            if (
                _is_nonnegative_int(established_cap)
                and bond_model != ONE_TO_MANY_UNIQUE_ENTITY
                and established_cap > capable[2]
            ):
                errors.append(
                    f"{row_label}: maximum active bonds cannot exceed bond_capable_high"
                )
            if (
                provisional is not None
                and _is_nonnegative_int(established_cap)
                and established_cap < provisional
            ):
                errors.append(
                    f"{row_label}: provisional active target cannot exceed maximum active bonds"
                )
            if (
                _is_nonnegative_int(provisional)
                and bond_model == ONE_TO_ONE
                and provisional > capable[2]
            ):
                errors.append(
                    f"{row_label}: one-to-one provisional active count cannot exceed "
                    "bond_capable_high"
                )

        if (haus_id, species_id) == SCHWARZFLUT_PAIR:
            if bond_capable_status != BOND_CAPABLE_COMPLETE:
                errors.append(f"{row_label}: Schwarzflut bond_capable_status must be COMPLETE")
            if population_unit != "UNIQUE_ENTITY":
                errors.append(f"{row_label}: Schwarzflut population_unit must be UNIQUE_ENTITY")
            if any(raw.get(f"population_{suffix}") != 1 for suffix in ("low", "central", "high")):
                errors.append(f"{row_label}: Schwarzflut population band must be exactly 1/1/1")
            if any(raw.get(f"bond_capable_{suffix}") != 1 for suffix in ("low", "central", "high")):
                errors.append(f"{row_label}: Schwarzflut bond-capable band must be exactly 1/1/1")

        if (haus_id, species_id) == KEPT_PAIR:
            if bond_capable_status != BOND_CAPABLE_COMPLETE:
                errors.append(f"{row_label}: The Kept bond_capable_status must be COMPLETE")
            if bond_model != NO_PRIMARY_BOND:
                errors.append(f"{row_label}: The Kept must use {NO_PRIMARY_BOND}")
            if any(raw.get(f"bond_capable_{suffix}") != 0 for suffix in ("low", "central", "high")):
                errors.append(f"{row_label}: The Kept bond-capable band must be exactly 0/0/0")
            if provisional not in (None, 0):
                errors.append(f"{row_label}: The Kept provisional active count must be null or 0")
        if (haus_id, species_id) == DRAGON_PAIR:
            if provisional != DRAGON_PROVISIONAL_ACTIVE_TARGET:
                errors.append(
                    f"{row_label}: Drache provisional active target must be "
                    f"{DRAGON_PROVISIONAL_ACTIVE_TARGET}"
                )

        territory_area = raw.get("territory_area_km2")
        if territory_status not in TERRITORY_STATUSES:
            errors.append(
                f"{row_label}: territory_area_status must be one of {sorted(TERRITORY_STATUSES)}"
            )
        if territory_area is not None:
            if isinstance(territory_area, bool) or not isinstance(territory_area, (int, float)):
                errors.append(f"{row_label}: territory_area_km2 must be null or numeric")
            elif not math.isfinite(float(territory_area)) or float(territory_area) <= 0:
                errors.append(f"{row_label}: territory_area_km2 must be finite and positive")
            elif territory_status != "FOUND":
                errors.append(f"{row_label}: numeric territory area requires status FOUND")
        elif territory_status == "FOUND":
            errors.append(f"{row_label}: FOUND territory area requires territory_area_km2")

        sources = _normalise_source_evidence(
            row_label,
            raw.get("source_evidence"),
            verify_source_hashes=verify_source_hashes,
            errors=errors,
        )
        row = dict(raw)
        row.update(
            {
                "haus_id": haus_id,
                "species_id": species_id,
                "display_name": display_name,
                "population_unit": population_unit,
                "method": method,
                "uncertainty": uncertainty,
                "canon_status": canon_status,
                "bond_model": bond_model,
                "bond_capable_status": bond_capable_status,
                "policy_cap_status": policy_cap_status,
                "territory_area_status": territory_status,
                "eligibility_definition": eligibility_definition,
                "counting_scope": counting_scope,
                "unresolved_variables": unresolved_variables,
                "source_evidence": sources,
                "source_bundle_sha256": _source_bundle_sha256(sources) if sources else None,
            }
        )
        normalised.append(row)

    duplicate_hauses = sorted({value for value in haus_ids if haus_ids.count(value) > 1})
    duplicate_species = sorted({value for value in species_ids if species_ids.count(value) > 1})
    duplicate_pairs = sorted({value for value in pairs if pairs.count(value) > 1})
    if duplicate_hauses:
        errors.append(f"Haus IDs must be unique; duplicates: {duplicate_hauses}")
    if duplicate_species:
        errors.append(f"species IDs must be unique; duplicates: {duplicate_species}")
    if duplicate_pairs:
        errors.append(f"Haus/species pairs must be unique; duplicates: {duplicate_pairs}")

    actual_pairs = set(pairs)
    missing_pairs = sorted(EXPECTED_PAIRS - actual_pairs)
    extra_pairs = sorted(actual_pairs - EXPECTED_PAIRS)
    if missing_pairs:
        errors.append(f"missing expected Haus/species pairs: {missing_pairs}")
    if extra_pairs:
        errors.append(f"unexpected Haus/species pairs: {extra_pairs}")

    checks.update(
        {
            "expected_row_count": 20,
            "actual_row_count": len(rows_value),
            "unique_haus_count": len(set(haus_ids)),
            "unique_species_count": len(set(species_ids)),
            "expected_pair_set_complete": actual_pairs == EXPECTED_PAIRS,
            "source_hash_verification_requested": verify_source_hashes,
            "source_hashes_verified": bool(normalised)
            and all(
                source.get("hash_verified") is True
                for row in normalised
                for source in row["source_evidence"]
            )
            if verify_source_hashes
            else None,
            "schwarzflut_one_to_many_exception": any(
                (row["haus_id"], row["species_id"]) == SCHWARZFLUT_PAIR
                and row["bond_model"] == ONE_TO_MANY_UNIQUE_ENTITY
                for row in normalised
            ),
            "kept_active_cap_zero": any(
                (row["haus_id"], row["species_id"]) == KEPT_PAIR
                and row.get("maximum_active_primary_bonds") == 0
                for row in normalised
            ),
            "schwarzflut_active_cap": next(
                (
                    row.get("maximum_active_primary_bonds")
                    for row in normalised
                    if (row["haus_id"], row["species_id"]) == SCHWARZFLUT_PAIR
                ),
                None,
            ),
            "dragon_provisional_active_target": next(
                (
                    row.get("provisional_active_primary_bonds")
                    for row in normalised
                    if (row["haus_id"], row["species_id"]) == DRAGON_PAIR
                ),
                None,
            ),
            "bond_capable_status_counts": {
                status: sum(row.get("bond_capable_status") == status for row in normalised)
                for status in sorted(BOND_CAPABLE_STATUSES)
            },
            "bond_capable_incomplete_species": [
                row["species_id"]
                for row in normalised
                if row.get("bond_capable_status") == BOND_CAPABLE_INCOMPLETE
            ],
            "unresolved_variable_entry_count": sum(
                len(row.get("unresolved_variables", [])) for row in normalised
            ),
        }
    )
    if not verify_source_hashes:
        warnings.append(
            "Source hash verification was skipped; declared hashes were not checked against files."
        )
    report = {
        "status": (
            "FAIL"
            if errors
            else "PASS"
            if verify_source_hashes
            else "UNVERIFIED_INCOMPLETE"
        ),
        "builder_version": BUILDER_VERSION,
        "catalogue_version": version,
        "canon_status": catalogue.get("canon_status"),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
    if errors:
        raise CatalogueValidationError(errors)
    return sorted(normalised, key=lambda row: (row["haus_id"], row["species_id"])), report


def load_catalogue(
    path: Path,
    *,
    verify_source_hashes: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows, validation = validate_catalogue_data(
        data,
        verify_source_hashes=verify_source_hashes,
    )
    validation["catalogue_path"] = str(path.resolve())
    validation["catalogue_file_sha256"] = sha256_file(path)
    validation["catalogue_semantic_sha256"] = sha256_bytes(canonical_json(data).encode("utf-8"))
    return data, rows, validation


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def load_v4_comparison(path: Path) -> tuple[V4Identity, dict[str, dict[str, int | None]]]:
    """Read only the Haus human totals needed for comparison."""

    with closing(_readonly_sqlite(path)) as connection:
        run_rows = connection.execute(
            "SELECT run_id, source_semantic_sha256, canon_status, completion_state FROM stage6d_run"
        ).fetchall()
        if len(run_rows) != 1:
            raise RuntimeError(f"expected one V4 stage6d_run row, found {len(run_rows)}")
        run = run_rows[0]
        identity = V4Identity(
            run_id=str(run["run_id"]),
            source_semantic_sha256=str(run["source_semantic_sha256"]),
            canon_status=str(run["canon_status"]),
            completion_state=str(run["completion_state"]),
        )
        if identity.completion_state != "COMPLETE":
            raise RuntimeError(f"V4 source run is not COMPLETE: {identity.completion_state}")

        result: dict[str, dict[str, int | None]] = {}
        query = """
            SELECT hierarchy_id, ordinary_unbonded_humans, bonded_humans, human_total
            FROM stage6d_hierarchy_human_population
            WHERE hierarchy_level = 'HAUS'
        """
        for row in connection.execute(query):
            haus_id = _as_upper_id(row["hierarchy_id"])
            if haus_id in result:
                raise RuntimeError(f"duplicate V4 Haus human row: {haus_id}")
            result[haus_id] = {
                "ordinary_unbonded_humans": (
                    int(row["ordinary_unbonded_humans"])
                    if row["ordinary_unbonded_humans"] is not None
                    else None
                ),
                "old_v4_bonded": int(row["bonded_humans"]) if row["bonded_humans"] is not None else None,
                "human_total": int(row["human_total"]) if row["human_total"] is not None else None,
            }
    return identity, result


def _effective_active_caps(
    row: Mapping[str, Any],
    human_total: int | None,
) -> dict[str, int | None]:
    """Calculate scenario-feasible caps from biology, policy and available humans."""

    if row["bond_capable_status"] == BOND_CAPABLE_INCOMPLETE:
        return {suffix: None for suffix in ("low", "central", "high")}

    established_cap = row["maximum_active_primary_bonds"]
    if row["bond_model"] == ONE_TO_MANY_UNIQUE_ENTITY:
        # The one Schwarzflut entity may sustain multiple primary bonds.  Its
        # one-individual biological census therefore is not a patron-count cap.
        effective = int(established_cap)
        if human_total is not None:
            effective = min(effective, human_total)
        return {suffix: effective for suffix in ("low", "central", "high")}
    if row["bond_model"] == NO_PRIMARY_BOND:
        return {suffix: 0 for suffix in ("low", "central", "high")}

    result: dict[str, int] = {}
    for suffix in ("low", "central", "high"):
        limits = [int(row[f"bond_capable_{suffix}"])]
        if (
            established_cap is not None
            and row["policy_cap_status"]
            in {POLICY_CAP_USER_APPROVED, POLICY_CAP_CANON_OR_REGISTRY}
        ):
            limits.append(int(established_cap))
        if human_total is not None:
            limits.append(human_total)
        result[suffix] = min(limits)
    return result


def _comparison(old_v4_bonded: int | None, comparison_cap: int | None) -> dict[str, Any]:
    if comparison_cap is None:
        return {
            "old_v4_exceeds_active_cap": None,
            "exceedance_ratio": None,
            "exceedance_ratio_status": "EFFECTIVE_CAP_INCOMPLETE",
        }
    if old_v4_bonded is None:
        return {
            "old_v4_exceeds_active_cap": None,
            "exceedance_ratio": None,
            "exceedance_ratio_status": "V4_VALUE_MISSING_OR_UNRESOLVED",
        }
    exceeds = old_v4_bonded > comparison_cap
    if comparison_cap > 0:
        ratio: float | None = old_v4_bonded / comparison_cap
        status = "DEFINED"
    elif old_v4_bonded == 0:
        ratio = 0.0
        status = "ZERO_CAP_AND_ZERO_V4"
    else:
        ratio = None
        status = "UNBOUNDED_EXCEEDANCE_AGAINST_ZERO_CAP"
    return {
        "old_v4_exceeds_active_cap": exceeds,
        "exceedance_ratio": ratio,
        "exceedance_ratio_status": status,
    }


def attach_v4_comparison(
    rows: list[dict[str, Any]],
    v4_values: Mapping[str, Mapping[str, int | None]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        v4 = v4_values.get(row["haus_id"], {})
        row["human_total"] = v4.get("human_total")
        row["old_v4_bonded"] = v4.get("old_v4_bonded")
        row["ordinary_unbonded_humans"] = v4.get("ordinary_unbonded_humans")
        effective = _effective_active_caps(row, row["human_total"])
        for suffix, value in effective.items():
            row[f"effective_active_cap_{suffix}"] = value
        row["effective_active_cap_status"] = row["bond_capable_status"]
        row["maximum_active_primary_bonds_scope"] = ACTIVE_CAP_SCOPE
        row["v4_comparison_cap_basis"] = V4_COMPARISON_CAP_BASIS
        row.update(_comparison(row["old_v4_bonded"], effective["central"]))
        provisional = row["provisional_active_primary_bonds"]
        if (
            _is_nonnegative_int(provisional)
            and row["bond_model"] == ONE_TO_ONE
            and effective["high"] is not None
            and provisional > effective["high"]
        ):
            raise CatalogueValidationError(
                (
                    f"{row['haus_id']}/{row['species_id']}: provisional active count exceeds "
                    "the V4-human-limited effective high cap",
                )
            )
        row["v4_comparison_is_lower_bound"] = False
        enriched.append(row)
    return enriched


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE species_census_run (
            run_id TEXT PRIMARY KEY,
            created_utc TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            builder_version TEXT NOT NULL,
            catalogue_path TEXT NOT NULL,
            catalogue_file_sha256 TEXT NOT NULL,
            catalogue_semantic_sha256 TEXT NOT NULL,
            v4_database_path TEXT NOT NULL,
            v4_database_sha256 TEXT,
            v4_database_hash_status TEXT NOT NULL,
            v4_run_id TEXT NOT NULL,
            v4_source_semantic_sha256 TEXT NOT NULL,
            executable_source_sha256 TEXT NOT NULL,
            executable_source_hashes_json TEXT NOT NULL,
            canon_status TEXT NOT NULL,
            completion_state TEXT NOT NULL
                CHECK (completion_state IN ('COMPLETE', 'INCOMPLETE_UNVERIFIED_SOURCES'))
        );

        CREATE TABLE species_census_estimate (
            run_id TEXT NOT NULL REFERENCES species_census_run(run_id),
            haus_id TEXT NOT NULL,
            species_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            population_unit TEXT NOT NULL,
            population_low INTEGER NOT NULL CHECK (population_low >= 0),
            population_central INTEGER NOT NULL CHECK (population_central >= population_low),
            population_high INTEGER NOT NULL CHECK (population_high >= population_central),
            bond_model TEXT NOT NULL,
            bond_capable_status TEXT NOT NULL
                CHECK (bond_capable_status IN ('COMPLETE', 'INCOMPLETE')),
            bond_capable_low INTEGER CHECK (bond_capable_low >= 0 AND bond_capable_low <= population_low),
            bond_capable_central INTEGER CHECK (bond_capable_central >= 0 AND bond_capable_central <= population_central),
            bond_capable_high INTEGER CHECK (bond_capable_high >= 0 AND bond_capable_high <= population_high),
            maximum_active_primary_bonds INTEGER CHECK (maximum_active_primary_bonds >= 0),
            maximum_active_primary_bonds_scope TEXT NOT NULL
                CHECK (maximum_active_primary_bonds_scope = 'ESTABLISHED_HARD_POLICY_OR_REGISTRY_CEILING_WHEN_NON_NULL'),
            policy_cap_status TEXT NOT NULL,
            proposed_policy_cap INTEGER CHECK (proposed_policy_cap >= 0),
            provisional_active_primary_bonds INTEGER,
            territory_area_km2 REAL,
            territory_area_status TEXT NOT NULL,
            eligibility_definition TEXT NOT NULL CHECK (length(trim(eligibility_definition)) > 0),
            counting_scope TEXT NOT NULL CHECK (length(trim(counting_scope)) > 0),
            unresolved_variables_json TEXT NOT NULL CHECK (unresolved_variables_json <> '[]'),
            method TEXT NOT NULL,
            uncertainty TEXT NOT NULL,
            source_bundle_sha256 TEXT NOT NULL,
            canon_status TEXT NOT NULL,
            CHECK (
                (bond_capable_status = 'COMPLETE'
                    AND bond_capable_low IS NOT NULL
                    AND bond_capable_central IS NOT NULL
                    AND bond_capable_high IS NOT NULL
                    AND bond_capable_low <= bond_capable_central
                    AND bond_capable_central <= bond_capable_high)
                OR
                (bond_capable_status = 'INCOMPLETE'
                    AND bond_capable_low IS NULL
                    AND bond_capable_central IS NULL
                    AND bond_capable_high IS NULL)
            ),
            PRIMARY KEY (run_id, haus_id),
            UNIQUE (run_id, species_id)
        );

        CREATE TABLE species_census_source_evidence (
            run_id TEXT NOT NULL,
            haus_id TEXT NOT NULL,
            source_ordinal INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            sections_json TEXT NOT NULL,
            declared_sha256 TEXT NOT NULL,
            actual_sha256 TEXT,
            hash_verified INTEGER,
            PRIMARY KEY (run_id, haus_id, source_ordinal),
            FOREIGN KEY (run_id, haus_id)
                REFERENCES species_census_estimate(run_id, haus_id)
        );

        CREATE TABLE species_census_v4_comparison (
            run_id TEXT NOT NULL,
            haus_id TEXT NOT NULL,
            human_total INTEGER,
            ordinary_unbonded_humans INTEGER,
            old_v4_bonded INTEGER,
            maximum_active_primary_bonds INTEGER,
            maximum_active_primary_bonds_scope TEXT NOT NULL
                CHECK (maximum_active_primary_bonds_scope = 'ESTABLISHED_HARD_POLICY_OR_REGISTRY_CEILING_WHEN_NON_NULL'),
            policy_cap_status TEXT NOT NULL,
            proposed_policy_cap INTEGER,
            effective_active_cap_low INTEGER CHECK (effective_active_cap_low >= 0),
            effective_active_cap_central INTEGER CHECK (effective_active_cap_central >= 0),
            effective_active_cap_high INTEGER CHECK (effective_active_cap_high >= 0),
            effective_active_cap_status TEXT NOT NULL
                CHECK (effective_active_cap_status IN ('COMPLETE', 'INCOMPLETE')),
            v4_comparison_cap_basis TEXT NOT NULL
                CHECK (v4_comparison_cap_basis = 'EFFECTIVE_ACTIVE_CAP_CENTRAL'),
            old_v4_exceeds_active_cap INTEGER,
            exceedance_ratio REAL,
            exceedance_ratio_status TEXT NOT NULL,
            v4_comparison_is_lower_bound INTEGER NOT NULL CHECK (v4_comparison_is_lower_bound = 0),
            CHECK (
                (effective_active_cap_status = 'COMPLETE'
                    AND effective_active_cap_low IS NOT NULL
                    AND effective_active_cap_central IS NOT NULL
                    AND effective_active_cap_high IS NOT NULL
                    AND effective_active_cap_low <= effective_active_cap_central
                    AND effective_active_cap_central <= effective_active_cap_high)
                OR
                (effective_active_cap_status = 'INCOMPLETE'
                    AND effective_active_cap_low IS NULL
                    AND effective_active_cap_central IS NULL
                    AND effective_active_cap_high IS NULL
                    AND old_v4_exceeds_active_cap IS NULL
                    AND exceedance_ratio IS NULL)
            ),
            PRIMARY KEY (run_id, haus_id),
            FOREIGN KEY (run_id, haus_id)
                REFERENCES species_census_estimate(run_id, haus_id)
        );

        CREATE INDEX idx_species_census_species
            ON species_census_estimate(species_id);
        CREATE INDEX idx_species_census_v4_exceeds
            ON species_census_v4_comparison(old_v4_exceeds_active_cap);
        """
    )


def _write_sqlite(
    path: Path,
    *,
    run: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            _create_schema(connection)
            connection.execute(
                """
                INSERT INTO species_census_run (
                    run_id, created_utc, schema_version, builder_version,
                    catalogue_path, catalogue_file_sha256, catalogue_semantic_sha256,
                    v4_database_path, v4_database_sha256, v4_database_hash_status, v4_run_id,
                    v4_source_semantic_sha256, executable_source_sha256,
                    executable_source_hashes_json,
                    canon_status, completion_state
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run["run_id"], run["created_utc"], SCHEMA_VERSION, BUILDER_VERSION,
                    run["catalogue_path"], run["catalogue_file_sha256"],
                    run["catalogue_semantic_sha256"], run["v4_database_path"],
                    run["v4_database_sha256"], run["v4_database_hash_status"],
                    run["v4_run_id"],
                    run["v4_source_semantic_sha256"], run["executable_source_sha256"],
                    canonical_json(run["executable_source_hashes"]),
                    NON_CANON_STATUS, run["completion_state"],
                ),
            )
            for row in rows:
                connection.execute(
                    """
                    INSERT INTO species_census_estimate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run["run_id"], row["haus_id"], row["species_id"], row["display_name"],
                        row["population_unit"], row["population_low"], row["population_central"],
                        row["population_high"], row["bond_model"], row["bond_capable_status"],
                        row["bond_capable_low"],
                        row["bond_capable_central"], row["bond_capable_high"],
                        row["maximum_active_primary_bonds"],
                        row["maximum_active_primary_bonds_scope"],
                        row["policy_cap_status"], row["proposed_policy_cap"],
                        row["provisional_active_primary_bonds"],
                        row["territory_area_km2"], row["territory_area_status"],
                        row["eligibility_definition"], row["counting_scope"],
                        canonical_json(row["unresolved_variables"]), row["method"],
                        row["uncertainty"], row["source_bundle_sha256"], row["canon_status"],
                    ),
                )
                for ordinal, source in enumerate(row["source_evidence"], start=1):
                    connection.execute(
                        "INSERT INTO species_census_source_evidence VALUES (?,?,?,?,?,?,?,?)",
                        (
                            run["run_id"], row["haus_id"], ordinal, source["path"],
                            canonical_json(source["sections"]), source["sha256"],
                            source["actual_sha256"],
                            None if source["hash_verified"] is None else int(source["hash_verified"]),
                        ),
                    )
                connection.execute(
                    "INSERT INTO species_census_v4_comparison VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run["run_id"], row["haus_id"], row["human_total"],
                        row["ordinary_unbonded_humans"], row["old_v4_bonded"],
                        row["maximum_active_primary_bonds"],
                        row["maximum_active_primary_bonds_scope"],
                        row["policy_cap_status"], row["proposed_policy_cap"],
                        row["effective_active_cap_low"],
                        row["effective_active_cap_central"],
                        row["effective_active_cap_high"],
                        row["effective_active_cap_status"],
                        row["v4_comparison_cap_basis"],
                        None
                        if row["old_v4_exceeds_active_cap"] is None
                        else int(row["old_v4_exceeds_active_cap"]),
                        row["exceedance_ratio"], row["exceedance_ratio_status"], 0,
                    ),
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"new species census SQLite failed integrity_check: {integrity}")
            connection.commit()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


CSV_FIELDS = (
    "haus_id",
    "species_id",
    "display_name",
    "population_unit",
    "population_low",
    "population_central",
    "population_high",
    "bond_model",
    "bond_capable_status",
    "bond_capable_low",
    "bond_capable_central",
    "bond_capable_high",
    "maximum_active_primary_bonds",
    "maximum_active_primary_bonds_scope",
    "policy_cap_status",
    "proposed_policy_cap",
    "provisional_active_primary_bonds",
    "territory_area_km2",
    "territory_area_status",
    "eligibility_definition",
    "counting_scope",
    "unresolved_variables",
    "human_total",
    "ordinary_unbonded_humans",
    "old_v4_bonded",
    "effective_active_cap_low",
    "effective_active_cap_central",
    "effective_active_cap_high",
    "effective_active_cap_status",
    "v4_comparison_cap_basis",
    "old_v4_exceeds_active_cap",
    "exceedance_ratio",
    "exceedance_ratio_status",
    "v4_comparison_is_lower_bound",
    "method",
    "uncertainty",
    "canon_status",
    "source_paths",
    "source_sections",
    "source_sha256s",
    "source_bundle_sha256",
)


def _csv_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {field: row.get(field) for field in CSV_FIELDS}
    result["unresolved_variables"] = canonical_json(row["unresolved_variables"])
    result["source_paths"] = canonical_json([source["path"] for source in row["source_evidence"]])
    result["source_sections"] = canonical_json(
        [{"path": source["path"], "sections": source["sections"]} for source in row["source_evidence"]]
    )
    result["source_sha256s"] = canonical_json(
        [{"path": source["path"], "sha256": source["sha256"]} for source in row["source_evidence"]]
    )
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(row))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _readme_text(run: Mapping[str, Any], rows: list[dict[str, Any]]) -> str:
    missing_v4 = sum(row["old_v4_bonded"] is None for row in rows)
    exceeded = sum(row["old_v4_exceeds_active_cap"] is True for row in rows)
    incomplete_capability = sum(
        row["bond_capable_status"] == BOND_CAPABLE_INCOMPLETE for row in rows
    )
    return f"""# Stage 6D Primary-Species Census Sidecar

Status: **WORKING PROPOSAL — REVIEW ONLY — NOT CANON**

Run: `{run['run_id']}`  
Source Stage 6D run: `{run['v4_run_id']}`

This folder is a separate primary-species census sidecar. It does not alter,
replace, attach to, or regenerate the Stage 6D V4 database. The V4 database was
opened read-only only to copy Haus-level human totals and old generic bonded-
human values into a comparison table.

The old V4 bonded-human values are **comparison evidence only**. They are never
treated as lower bounds for primary-species populations or active bonds.
The default build records the completed V4 run ID and semantic source hash but
does not reread the full ~945 MB database to hash its container. Use the CLI's
explicit `--hash-v4-file` option only when a container hash is required.

## Files

- `{SQLITE_FILENAME}` — normalized run, estimate, source-evidence and V4-comparison tables.
- `{CSV_FILENAME}` — one review row per Haus/species pair.
- `{SUMMARY_FILENAME}` — run lineage, counts, grouped totals and file hashes.
- `{VALIDATION_FILENAME}` — catalogue and invariant validation evidence.
- `{README_FILENAME}` — this guide.

## Required catalogue rules

- Exactly 20 unique Haus IDs and 20 unique species IDs, matching the existing
  Stage 6D species identity catalogue.
- `low <= central <= high` for population and bond-capable bands.
- A bond-capable band is either `COMPLETE` with three ordered non-negative
  integers, or `INCOMPLETE` with all three values null. Mixed/partial bands are
  invalid. Each complete band is no greater than the corresponding population
  band.
- Incomplete capability evidence produces null low/central/high effective caps,
  a null V4 exceedance result and a null ratio; it is never coerced to zero.
- Every row defines its eligibility meaning, counting scope, and a non-empty
  list of unresolved variables.
- `maximum_active_primary_bonds` is nullable and contains only an established
  hard policy/registry ceiling with an approved/supporting `policy_cap_status`.
  A `proposed_policy_cap` is review metadata and never enters hard-cap maths.
- Low, central and high effective caps are calculated as the minimum of the
  matching bond-capable count, that institutional ceiling, and (for one-to-one
  bonds when known) the Haus human total.
- The only established hard caps in this version are Schwarzflut
  ({SCHWARZFLUT_ACTIVE_CAP}, one-to-many), The Kept (0), and the current
  recognised Rootreach registry ({ROOTREACH_REGISTRY_CAP}). Drache's
  {DRAGON_PROVISIONAL_ACTIVE_TARGET} is a provisional actual active-bond target,
  not a hard cap and therefore does not constrain its scenario capacity.
- The Kept active-bond cap is zero.
- Drache provisional active target is {DRAGON_PROVISIONAL_ACTIVE_TARGET}.
- Every row remains `{NON_CANON_STATUS}` and carries auditable source paths,
  section labels and SHA-256 hashes.

## Comparison summary

- Rows: {len(rows)}
- Rows where old V4 generic bonded humans exceed the central effective cap: {exceeded}
- Rows with unresolved/missing V4 Haus totals: {missing_v4}
- Rows with explicitly incomplete bond-capability bands: {incomplete_capability}

Population totals are grouped by `population_unit` in the summary JSON. They
must not be summed across heterogeneous units such as individual animals, the
single Schwarzflut entity, connected Rootreach, Phoenix continuity, sky-reef
features, or Kept stock/flow records.
"""


def _grouped_totals(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = grouped.setdefault(
            row["population_unit"],
            {
                "row_count": 0,
                "population_low": 0,
                "population_central": 0,
                "population_high": 0,
                "bond_capable_low": 0,
                "bond_capable_central": 0,
                "bond_capable_high": 0,
                "bond_capable_complete_row_count": 0,
                "bond_capable_incomplete_row_count": 0,
            },
        )
        bucket["row_count"] += 1
        for field in ("population_low", "population_central", "population_high"):
            bucket[field] += int(row[field])
        if row["bond_capable_status"] == BOND_CAPABLE_COMPLETE:
            bucket["bond_capable_complete_row_count"] += 1
            for field in ("bond_capable_low", "bond_capable_central", "bond_capable_high"):
                bucket[field] += int(row[field])
        else:
            bucket["bond_capable_incomplete_row_count"] += 1
    for bucket in grouped.values():
        if bucket["bond_capable_incomplete_row_count"]:
            for field in ("bond_capable_low", "bond_capable_central", "bond_capable_high"):
                bucket[field] = None
            bucket["bond_capable_totals_status"] = BOND_CAPABLE_INCOMPLETE
        else:
            bucket["bond_capable_totals_status"] = BOND_CAPABLE_COMPLETE
    return dict(sorted(grouped.items()))


def _ensure_new_output_folder(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise FileExistsError(f"output path exists and is not a directory: {path}")
        if any(path.iterdir()):
            raise FileExistsError(f"output folder must be new or empty: {path}")
    else:
        path.mkdir(parents=True)


def build_species_census_sidecar(
    *,
    catalogue_path: Path,
    v4_database_path: Path,
    output_dir: Path,
    verify_source_hashes: bool = True,
    hash_v4_file: bool = False,
) -> dict[str, Any]:
    """Validate inputs and write a new independent species-census bundle."""

    catalogue_path = catalogue_path.resolve()
    v4_database_path = v4_database_path.resolve()
    output_dir = output_dir.resolve()
    if not catalogue_path.is_file():
        raise FileNotFoundError(catalogue_path)
    if not v4_database_path.is_file():
        raise FileNotFoundError(v4_database_path)

    _, rows, validation = load_catalogue(
        catalogue_path,
        verify_source_hashes=verify_source_hashes,
    )
    v4_identity, v4_values = load_v4_comparison(v4_database_path)
    rows = attach_v4_comparison(rows, v4_values)

    source_paths = [
        Path(__file__).resolve(),
        Path(species_rules.__file__).resolve(),
        Path(__file__).with_name("build_stage6d_species_census.py").resolve(),
    ]
    executable_source_hashes = {
        str(path): sha256_file(path)
        for path in sorted(set(source_paths))
        if path.is_file()
    }
    executable_source_sha256 = sha256_bytes(
        canonical_json(executable_source_hashes).encode("utf-8")
    )
    v4_database_sha256 = sha256_file(v4_database_path) if hash_v4_file else None
    v4_database_hash_status = (
        "COMPUTED" if hash_v4_file else "NOT_COMPUTED_V4_RUN_SEMANTIC_IDENTITY_USED"
    )
    run_payload = {
        "builder_version": BUILDER_VERSION,
        "catalogue_semantic_sha256": validation["catalogue_semantic_sha256"],
        "v4_run_id": v4_identity.run_id,
        "v4_source_semantic_sha256": v4_identity.source_semantic_sha256,
        "v4_database_sha256": v4_database_sha256,
        "v4_database_hash_status": v4_database_hash_status,
        "executable_source_sha256": executable_source_sha256,
        "executable_source_hashes": executable_source_hashes,
        "source_hash_verification_status": validation["status"],
    }
    run_id = "S6D-SPECIES-" + sha256_bytes(canonical_json(run_payload).encode("utf-8"))[:20].upper()
    created_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run = {
        "run_id": run_id,
        "created_utc": created_utc,
        "catalogue_path": str(catalogue_path),
        "catalogue_file_sha256": validation["catalogue_file_sha256"],
        "catalogue_semantic_sha256": validation["catalogue_semantic_sha256"],
        "v4_database_path": str(v4_database_path),
        "v4_database_sha256": v4_database_sha256,
        "v4_database_hash_status": v4_database_hash_status,
        "v4_run_id": v4_identity.run_id,
        "v4_source_semantic_sha256": v4_identity.source_semantic_sha256,
        "executable_source_sha256": executable_source_sha256,
        "executable_source_hashes": executable_source_hashes,
        "completion_state": (
            "COMPLETE"
            if validation["status"] == "PASS"
            else "INCOMPLETE_UNVERIFIED_SOURCES"
        ),
        "canon_status": NON_CANON_STATUS,
    }

    validation.update(
        {
            "run_id": run_id,
            "v4_database_path": str(v4_database_path),
            "v4_database_sha256": v4_database_sha256,
            "v4_database_hash_status": v4_database_hash_status,
            "v4_run_id": v4_identity.run_id,
            "v4_completion_state": v4_identity.completion_state,
            "v4_values_are_lower_bounds": False,
            "comparison_row_count": len(rows),
        }
    )

    _ensure_new_output_folder(output_dir)
    sqlite_path = output_dir / SQLITE_FILENAME
    csv_path = output_dir / CSV_FILENAME
    validation_path = output_dir / VALIDATION_FILENAME
    readme_path = output_dir / README_FILENAME
    summary_path = output_dir / SUMMARY_FILENAME

    _write_sqlite(sqlite_path, run=run, rows=rows)
    _write_csv(csv_path, rows)
    _write_json(validation_path, validation)
    readme_path.write_text(_readme_text(run, rows), encoding="utf-8")

    output_hashes = {
        path.name: {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for path in (sqlite_path, csv_path, validation_path, readme_path)
    }
    summary = {
        **run,
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "completion_state": run["completion_state"],
        "row_count": len(rows),
        "source_evidence_row_count": sum(len(row["source_evidence"]) for row in rows),
        "v4_comparison_missing_count": sum(row["old_v4_bonded"] is None for row in rows),
        "old_v4_exceeds_active_cap_count": sum(
            row["old_v4_exceeds_active_cap"] is True for row in rows
        ),
        "v4_comparison_incomplete_cap_count": sum(
            row["effective_active_cap_status"] == BOND_CAPABLE_INCOMPLETE for row in rows
        ),
        "bond_capable_status_counts": {
            status: sum(row["bond_capable_status"] == status for row in rows)
            for status in sorted(BOND_CAPABLE_STATUSES)
        },
        "bond_capable_incomplete_species": [
            row["species_id"]
            for row in rows
            if row["bond_capable_status"] == BOND_CAPABLE_INCOMPLETE
        ],
        "unresolved_variable_entry_count": sum(
            len(row["unresolved_variables"]) for row in rows
        ),
        "v4_comparison_cap_basis": V4_COMPARISON_CAP_BASIS,
        "v4_values_are_lower_bounds": False,
        "grouped_arithmetic_totals_by_population_unit": _grouped_totals(rows),
        "established_hard_cap_sum": sum(
            int(row["maximum_active_primary_bonds"] or 0) for row in rows
        ),
        "effective_active_cap_sums": {
            suffix: (
                None
                if any(row[f"effective_active_cap_{suffix}"] is None for row in rows)
                else sum(int(row[f"effective_active_cap_{suffix}"]) for row in rows)
            )
            for suffix in ("low", "central", "high")
        },
        "effective_active_cap_complete_only_sums": {
            suffix: sum(
                int(row[f"effective_active_cap_{suffix}"])
                for row in rows
                if row[f"effective_active_cap_{suffix}"] is not None
            )
            for suffix in ("low", "central", "high")
        },
        "output_files": output_hashes,
        "validation_status": validation["status"],
        "warnings": [
            "Working ecological estimates are not canon.",
            "Old V4 generic bonded-human values are comparison evidence, never lower bounds.",
            "Nullable maximum active values are established hard ceilings; proposed caps do not constrain results.",
            "Do not sum population bands across heterogeneous population units.",
        ] + list(validation["warnings"]),
    }
    _write_json(summary_path, summary)
    summary["summary_file"] = {
        "path": str(summary_path),
        "sha256": sha256_file(summary_path),
        "size_bytes": summary_path.stat().st_size,
    }
    return {
        "status": validation["status"],
        "run_id": run_id,
        "output_dir": str(output_dir),
        "sqlite": str(sqlite_path),
        "review_csv": str(csv_path),
        "summary_json": str(summary_path),
        "validation_json": str(validation_path),
        "readme": str(readme_path),
        "row_count": len(rows),
        "v4_source_unchanged_by_design": True,
    }
