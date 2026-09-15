#!/usr/bin/env python3
"""Validate the exact 25-row Stage 6D source fixture before population work."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from stage6d_schema import _assert_checkpointed_source, semantic_rows_sha256


GOLDEN_IDS = (
    "S6-DKH-BLACKFLOOD-ANCHOR-01",
    "S6-MOOR-CAPITAL-ANCHOR-01",
    "S6-SEEL-CATHEDRAL-ANCHOR-01",
    "SITE4-0B5EC62F028E2B56",
    "SITE4-224ECBC0B96C5225",
    "SITE4-23A7F7D9AC3F3DB7",
    "SITE4-26C9A4D994A0404E",
    "SITE4-31B6BD7011DEA612",
    "SITE4-54BDE0A396156296",
    "SITE4-5823AB3C8FEE7666",
    "SITE4-5C8B1C2829C19843",
    "SITE4-5CE609D9B8FC9388",
    "SITE4-633F92DCE5D1BE39",
    "SITE4-84693898317C2B28",
    "SITE4-A744AAB52370DAD9",
    "SITE4-A872A7A2208D1A55",
    "SITE4-BB29BFB4F83D4C02",
    "SITE4-D88AFE50BA8458A5",
    "SITE4-E2FF9CB128EC0ECF",
    "C4BSITE-07C18DEC80A8DCAFF1",
    "C4BFSITE-006CE715F9CE0DCCDB",
    "C4BFSITE-0014C83677DD49DBB5",
    "C4BFSITE-008B86CDFDC2F112DB",
    "SITE4-0292E7E4BDA79B53",
    "C4BSITE-00C1D84B4D25613E7D",
)

EXPECTED_SHA256 = "be5f89187f3494ff27d3b2f9066369bfceb79b9c283eb77332eef9d78115f90c"


def load_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in GOLDEN_IDS)
    cursor = connection.execute(
        f"""
        WITH route AS (
            SELECT settlement_id, COUNT(*) AS route_count
            FROM stage6c5r_route_context
            GROUP BY settlement_id
        )
        SELECT
            s.settlement_id AS settlement_id,
            a.owner_haus_id AS owner_haus_id,
            s.stage6_active_settlement AS stage6_active_settlement,
            s.stage6_active_location AS stage6_active_location,
            s.stage6_ordinary_permanent_human_settlement AS stage6_ordinary_permanent_human_settlement,
            s.stage6b_functional_tier AS stage6b_functional_tier,
            s.stage6b_realised_settlement_form AS stage6b_realised_settlement_form,
            s.stage6b_form_family AS stage6b_form_family,
            a.analysis_status AS analysis_status,
            a.effective_vertical_domain AS effective_vertical_domain,
            a.capacity_support_score AS capacity_support_score,
            a.access_support_score AS access_support_score,
            a.capacity_band AS capacity_band,
            a.review_status AS review_status,
            r.disposition AS refinement_disposition,
            r.selection_status AS refinement_selection_status,
            r.semantic_key AS refinement_semantic_key,
            p.semantic_key AS physical_semantic_key,
            p.array_digest AS array_digest,
            p.pilot_site_gate_pass AS pilot_site_gate_pass,
            COALESCE(route.route_count,0) AS route_count
        FROM settlement AS s
        LEFT JOIN stage6c_site_assessment AS a USING(settlement_id)
        LEFT JOIN stage6c5_site_refinement AS r USING(settlement_id)
        LEFT JOIN stage6c5r_site_physical_context AS p USING(settlement_id)
        LEFT JOIN route USING(settlement_id)
        WHERE s.settlement_id IN ({placeholders})
        ORDER BY s.settlement_id
        """,
        GOLDEN_IDS,
    )
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def validate(source: Path) -> dict[str, Any]:
    source = source.resolve()
    _assert_checkpointed_source(source)
    connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    try:
        rows = load_rows(connection)
    finally:
        connection.close()
    if len(rows) != 25 or len({row["settlement_id"] for row in rows}) != 25:
        raise RuntimeError(f"Golden fixture identity count is not 25: {len(rows)}")
    digest = semantic_rows_sha256(rows)
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"Golden fixture digest changed: {digest} != {EXPECTED_SHA256}")

    active_settlement = sum(row["stage6_active_settlement"] == 1 for row in rows)
    active_location = sum(row["stage6_active_location"] == 1 for row in rows)
    ordinary_human = sum(
        row["stage6_ordinary_permanent_human_settlement"] == 1 for row in rows
    )
    tier_counts = Counter(row["stage6b_functional_tier"] for row in rows)
    status_counts = Counter(row["analysis_status"] for row in rows)
    refinement_count = sum(row["refinement_disposition"] is not None for row in rows)
    physical_count = sum(row["physical_semantic_key"] is not None for row in rows)
    route_count = sum(int(row["route_count"]) for row in rows)
    checks = {
        "active_settlement_count": (active_settlement, 24),
        "active_location_count": (active_location, 25),
        "ordinary_human_allowed_count": (ordinary_human, 18),
        "ft0_count": (tier_counts["FT0_HAUS_PRINCIPAL_SITE"], 19),
        "specialist_3d_count": (status_counts["DEFERRED_SPECIALIST_3D"], 7),
        "refinement_count": (refinement_count, 20),
        "physical_count": (physical_count, 19),
        "route_context_count": (route_count, 38),
    }
    failures = {key: value for key, value in checks.items() if value[0] != value[1]}
    if failures:
        raise RuntimeError(f"Golden fixture invariants changed: {failures}")
    excluded = [row["settlement_id"] for row in rows if row["stage6_active_settlement"] != 1]
    if excluded != ["C4BSITE-00C1D84B4D25613E7D"]:
        raise RuntimeError(f"Unexpected non-settlement control rows: {excluded}")
    return {
        "status": "PASS",
        "fixture_row_count": len(rows),
        "active_settlement_count": active_settlement,
        "semantic_sha256": digest,
        "specialist_3d_count": status_counts["DEFERRED_SPECIALIST_3D"],
        "refinement_count": refinement_count,
        "physical_count": physical_count,
        "route_context_count": route_count,
        "nonsettlement_control": excluded[0],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(json.dumps(validate(args.source), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
