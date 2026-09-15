#!/usr/bin/env python3
"""Canon-grounded species counting rules for the Stage 6D proposal.

This catalogue answers a deliberately narrow question: how a future Stage 6D
builder may *identify and count* each primary species without double counting
mobile, recurring, colonial, or hosted contexts.  It does not estimate species
population, biomass, food demand, yield, or carrying capacity.  Those values
remain ``None`` unless the canon itself supplies a defensible quantity.

The source pointers are intentionally human-auditable.  They point to the
primary Haus and species DOCX records and the exact named sections used for the
counting decision.  The rules are working implementation controls, never a
promotion of a demographic result to canon.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


METHOD_VERSION = "STAGE6D_CANON_SPECIES_COUNTING_CATALOGUE_V1"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
PRIMARY_HAUS_ROOT = Path(
    r"C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\01_Current_Drive_Snapshot\Primary Hausen"
)

# This field is deliberately separate from the sidecar's FOUND / INCOMPLETE /
# CONFLICT evidence status.  A numerical biological demand can be not
# applicable without making the existence of the species itself unknown.
NUMERIC_STATUS_INCOMPLETE = "INCOMPLETE"
NUMERIC_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SourcePointer:
    """One exact primary DOCX path plus the sections relevant to this rule."""

    relative_path: str
    sections: tuple[str, ...]

    @property
    def path(self) -> Path:
        return PRIMARY_HAUS_ROOT / self.relative_path

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sections": list(self.sections),
        }


@dataclass(frozen=True)
class SpeciesCountingRule:
    """Non-numeric counting and residence constraints for one Haus/species pair."""

    haus_id: str
    species_id: str
    display_name: str
    population_class: str
    counting_unit: str
    residence_mode: str
    deduplication_rule: str
    hard_exclusions: tuple[str, ...]
    numeric_status: str
    known_exact_count: int | None
    food_demand_milliunits_per_counting_unit: int | None
    food_demand_status: str
    source_pointers: tuple[SourcePointer, SourcePointer]
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def profile_id(self) -> str:
        return f"SPECIES::{self.haus_id}::{self.species_id}"

    def as_profile_row(self) -> dict[str, Any]:
        """Return the direct, non-numeric portion of a sidecar profile row."""

        composite = {
            "catalogue_method_version": METHOD_VERSION,
            "counting_unit": self.counting_unit,
            "residence_mode": self.residence_mode,
            "numeric_status": self.numeric_status,
            "food_demand_status": self.food_demand_status,
            "deduplication_rule": self.deduplication_rule,
            "hard_exclusions": list(self.hard_exclusions),
            "source_pointers": [pointer.as_dict() for pointer in self.source_pointers],
            "notes": list(self.notes),
            "warnings": list(self.warnings),
        }
        return {
            "profile_id": self.profile_id,
            "population_class": self.population_class,
            "biological_entity_id": self.species_id,
            "counting_unit": self.counting_unit,
            "residence_mode": self.residence_mode,
            "food_demand_milliunits_per_counting_unit": self.food_demand_milliunits_per_counting_unit,
            "composite_demand_json": _canonical_json(composite),
            "evidence_status": "INCOMPLETE" if self.numeric_status == NUMERIC_STATUS_INCOMPLETE else "FOUND",
            "rule_fingerprint": rule_fingerprint(self),
            "canon_status": CANON_STATUS,
        }


def _src(relative_path: str, *sections: str) -> SourcePointer:
    return SourcePointer(relative_path, tuple(sections))


# The standard source sections are named in the current primary DOCX files.
# The two documents are intentionally both retained: species biology governs
# the count unit; Haus territory/settlement/governance governs placement and
# whether a record is a site, an anchor, or a true population context.
_S = "6. Habitat, Geology and Range"
_D = "7. Diet, Social Life and Reproduction"
_H = "4. Territory, Capital and Settlement"
_M = "5. Kinship, Membership and Social Organisation"
_E = "8. Economy, Subsistence and Material Culture"
_P = "9. Primary Species and Bannerhäuser"


def _rule(
    haus_id: str,
    species_id: str,
    display_name: str,
    population_class: str,
    counting_unit: str,
    residence_mode: str,
    deduplication_rule: str,
    hard_exclusions: Iterable[str],
    haus_doc: str,
    species_doc: str,
    *,
    haus_sections: tuple[str, ...] = (_H, _M, _E, _P),
    species_sections: tuple[str, ...] = (_S, _D),
    numeric_status: str = NUMERIC_STATUS_INCOMPLETE,
    known_exact_count: int | None = None,
    food_demand_milliunits_per_counting_unit: int | None = None,
    food_demand_status: str = NUMERIC_STATUS_INCOMPLETE,
    notes: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> SpeciesCountingRule:
    return SpeciesCountingRule(
        haus_id=haus_id,
        species_id=species_id,
        display_name=display_name,
        population_class=population_class,
        counting_unit=counting_unit,
        residence_mode=residence_mode,
        deduplication_rule=deduplication_rule,
        hard_exclusions=tuple(hard_exclusions),
        numeric_status=numeric_status,
        known_exact_count=known_exact_count,
        food_demand_milliunits_per_counting_unit=food_demand_milliunits_per_counting_unit,
        food_demand_status=food_demand_status,
        source_pointers=(
            _src(haus_doc, *haus_sections),
            _src(species_doc, *species_sections),
        ),
        notes=tuple(notes),
        warnings=tuple(warnings),
    )


# Any apparent precision in species headcounts would be fabricated at this
# stage.  Every ecological demand is therefore NULL/INCOMPLETE except the two
# non-ecological special cases below: Schwarzflut and The Kept.
SPECIES_RULES: dict[str, SpeciesCountingRule] = {
    "BUCHHAIN": _rule(
        "BUCHHAIN", "SKRIPTEULE", "Skripteule / Giant Ink Owl",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "TERRITORIAL_RANGE_WITH_SITE_ASSOCIATION",
        "Count an owl once by stable individual identity; a library, archive, or hosted-service site is an association, never a second owl population.",
        ("NO_SITE_IDENTITY_AS_SPECIES_COUNT", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Ink Owl\Haus von Buchhain.docx", r"Ink Owl\Skripteule ~1 Giant Ink Owl.docx",
    ),
    "DUFTFAEHRTE": _rule(
        "DUFTFAEHRTE", "SCHIMMERHUND", "Schimmerhund / Shimmerhound",
        "MOBILE_SHARED_POOL", "INDIVIDUAL", "MOBILE_SEASONAL_SHARED_POOL",
        "One territorial mobile pool only. The moving court and all twenty fixed court-host grounds are anchors/contexts, not duplicated resident populations.",
        ("NO_FIXED_ANCHOR_DUPLICATION", "NO_ORDINARY_PERMANENT_HUMAN_LATTICE_INFERENCE", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Shimmerhound\Haus von Duftfährte.docx", r"Shimmerhound\Shimmerhound ~1 Schimmerhund.docx",
        notes=("Capital caravan/court is nonspatial; anchor sites retain a host role but do not own the mobile population.",),
    ),
    "DUNKELHAUCH": _rule(
        "DUNKELHAUCH", "SCHWARZFLUT", "Schwarzflut / Blackflood",
        "RESIDENT_SPECIES", "UNIQUE_CONTINUOUS_INDIVIDUAL", "BLACKFLOOD_HEART_SYSTEM",
        "Exactly one continuing organism/person. Its Heart, infrastructure, manifestations, and first-bond lineage are not separate population records.",
        ("NO_REPEAT_SCHWARZFLUT", "NO_HEART_AS_SECOND_INDIVIDUAL", "NO_ECOLOGICAL_CAPACITY_MODEL"),
        r"Blackflood\Haus von Dunkelhauch.docx", r"Blackflood\Dunkelhauch ~1 Schwarzflut.docx",
        numeric_status="FOUND", known_exact_count=1,
        food_demand_milliunits_per_counting_unit=0,
        food_demand_status=NUMERIC_STATUS_NOT_APPLICABLE,
        notes=("Zero here means non-applicable to the ordinary ecological food ledger, not proof of no material requirements in any other system.",),
    ),
    "EDELSTEIN": _rule(
        "EDELSTEIN", "EDELMAUL", "Edelmaul / Crownjaw",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "TERRITORIAL_RANGE_WITH_SITE_ASSOCIATION",
        "Count each Crownjaw once by persistent biological identity; gem/extraction settlements and lairs are contexts, not duplicate animals.",
        ("NO_SITE_IDENTITY_AS_SPECIES_COUNT", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Crownjaw\Haus vom Edelstein.docx", r"Crownjaw\Crownjaw ~1 Edelmaul.docx",
    ),
    "EISENWEB": _rule(
        "EISENWEB", "STAHLSPINNE", "Stahlspinne / Ferrarachne",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "WEB_NETWORK_RANGE",
        "Count each Ferrarachne once across a connected web range. The unique Kronweberin is one named node, never once per web, workshop, or settlement.",
        ("NO_WEB_CONTEXT_DUPLICATION", "NO_KRONWEBERIN_MULTIPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Ferrarachne\Haus von Eisenweb.docx", r"Ferrarachne\Ferrarachne ~1 Stahlspinne.docx",
        notes=("The unique Ferrarachne Kronweberin must be represented as a single identity if/when named-instance data is installed.",),
    ),
    "EREMITENSCHALE": _rule(
        "EREMITENSCHALE", "EREMITENSCHNECKE", "Eremitenschnecke / Hermit Snail",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "TERRITORIAL_RANGE_WITH_SITE_ASSOCIATION",
        "Count a snail once by biological identity; agricultural, storage, and settlement contexts do not become species headcounts.",
        ("NO_SITE_IDENTITY_AS_SPECIES_COUNT", "NO_BREADBASKET_YIELD_FROM_SPECIES_COUNT", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Hermit Snails\Haus von Eremitenschale.docx", r"Hermit Snails\Eremitenschnecke ~1 Hermit Snail.docx",
        notes=("The Haus's user-directed breadbasket/export role belongs to the human food ledger, not a fabricated snail population or crop-yield calculation.",),
    ),
    "FEUERSCHUPPE": _rule(
        "FEUERSCHUPPE", "DRACHE", "Drache / European Dragon",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "AERIAL_TERRITORIAL_RANGE",
        "Count a dragon once across its aerial territory; eyries, peaks, and service sites are associated locations, not duplicate dragons.",
        ("NO_AERIE_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Dragon\Haus von Feuerschuppe.docx", r"Dragon\European Dragon ~1 Drache.docx",
    ),
    "FROSTGLANZ": _rule(
        "FROSTGLANZ", "FROSTHIRSCH", "Frosthirsch / Frost Elk",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "SEASONAL_HERD_RANGE",
        "Count each Frosthirsch once by individual identity; a herd is a range grouping and must not be summed again at every seasonal site.",
        ("NO_SEASONAL_SITE_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Frost Elk\Haus vom Frostglanz.docx", r"Frost Elk\Frost Elk ~1 Frosthirsch.docx",
    ),
    "GLANZGRUND": _rule(
        "GLANZGRUND", "CHROMAKRAKE", "Chromakrake / Chromakraken",
        "RESIDENT_SPECIES", "INDIVIDUAL", "SUBMERGED_NATIVE_SPECIALIST_DOMAIN",
        "Count each Chromakrake once in the native submerged domain; submerged communities remain native context and cannot be used to infer ordinary human residency or 3D capacity.",
        ("NO_SUBMERGED_HUMAN_INFERENCE", "NO_SURFACE_2D_CAPACITY_SUBSTITUTION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Chromakraken\Haus von Glanzgrund.docx", r"Chromakraken\Chromakrake ~1 Chromakraken.docx",
        notes=("Species totals and biological demand remain incomplete pending specialist 3D evidence.",),
    ),
    "LAUBRAUNEN": _rule(
        "LAUBRAUNEN", "SCHUPPENRINDE", "Schuppenrinde / Canopy Whipsnake",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "CANOPY_FOREST_RANGE",
        "Count each Schuppenrinde once across its connected forest/canopy range; isolated forest fragments are range evidence, not automatically separate population totals.",
        ("NO_NONFOREST_RANGE_EXPANSION", "NO_SEPARATE_ORDINARY_HUMAN_SETTLEMENT_INFERENCE", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Canopy Whipsnake\Haus von Laubraunen.docx", r"Canopy Whipsnake\Schuppenrinde ~1 Canopy Whipsnake.docx",
        notes=("Its strongly forest-constrained suitability remains a species-range gate, not a numerical headcount.",),
    ),
    "MARIENHAIN": _rule(
        "MARIENHAIN", "MARIENBIENE", "Marienbiene / Ladybee",
        "RESIDENT_SPECIES", "INDIVIDUAL", "HIVE_AND_ORCHARD_RANGE",
        "Count individuals once; hive/settlement records are contexts. Count the Queen-Mother tag once only, and never count drones as bondable individuals.",
        ("NO_HIVE_AS_POPULATION_DUPLICATION", "NO_QUEEN_MOTHER_MULTIPLICATION", "NO_DRONE_BOND_COUNT", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Ladybee\Haus von Marienhain.docx", r"Ladybee\Marienbiene ~1 Ladybee.docx",
        notes=("One human ↔ one individual Marienbiene is an exact relationship minimum where a bond is evidenced; it does not provide an overall species total.",),
        warnings=("User spelling 'Marienbien' is retained as an input warning; current canon source binding is Haus von Marienhain / Marienbiene.",),
    ),
    "MOORWANDLER": _rule(
        "MOORWANDLER", "MOORRIESE", "Moorriese / Bog Colossus",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "WETLAND_RANGE_WITH_STILT_ASSOCIATION",
        "Count a Bog Colossus once across its wetland range; stilt villages and deep-wetland capital contexts do not create duplicate species records.",
        ("NO_STILT_SITE_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Bog Colossus\Haus der Moorwandler.docx", r"Bog Colossus\Bog Colossus ~1 Moorriese.docx",
    ),
    "NACHTFLUESTERN": _rule(
        "NACHTFLUESTERN", "NACHTFLUESTERER", "Nachtflüsterer / Nightwhisperer",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "TERRITORIAL_RANGE_WITH_SITE_ASSOCIATION",
        "Count an individual once by biological identity; sleep-wing, hospital, or hosted-service context is not a separate species population.",
        ("NO_HOSTED_SERVICE_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Nightwhisperer\Haus von Nachtflüstern.docx", r"Nightwhisperer\Nightwhisperer ~1 Nachtflüsterer.docx",
    ),
    "SEELENWACHT": _rule(
        "SEELENWACHT", "THE_KEPT", "The Kept / die Aufgehobenen",
        "RESIDENT_SPECIES", "STOCK_FLOW_INDIVIDUAL_NOT_ECOLOGICAL_POPULATION", "CUSTODIAL_STOCK_FLOW",
        "Treat The Kept as a custodial stock-flow, not an ecological carrying-capacity population. A person is counted once through custody/identity lineage, not once per mausoleum, cathedral, or service context.",
        ("NO_ECOLOGICAL_CAPACITY_MODEL", "NO_FOOD_DEMAND_MODEL", "NO_HOSTED_SERVICE_DUPLICATION"),
        r"The Kept\Haus von Seelenwacht.docx", r"The Kept\The Kept ~1 die Aufgehobenen.docx",
        species_sections=("6. Formation, Habitat, Geology and Range", "7. Diet, Social Life and Reproduction"),
        food_demand_milliunits_per_counting_unit=0,
        food_demand_status=NUMERIC_STATUS_NOT_APPLICABLE,
        notes=("Zero means the ordinary ecological food ledger is not applicable; it is not a claim that custodial support or material inputs are zero.",),
    ),
    "SERENAKRONE": _rule(
        "SERENAKRONE", "SERENAFACHER", "Serenafächer / Crown Lobster",
        "RESIDENT_SPECIES", "INDIVIDUAL", "SUBMERGED_REEF_AND_LAGOON_CONTEXT",
        "Count each Serenafächer once across reef/lagoon habitat. Surface lagoon settlements are human contexts; underwater coral/foundation habitat is not a submerged human settlement count.",
        ("NO_SURFACE_LAGOON_DUPLICATION", "NO_SUBMERGED_HUMAN_INFERENCE", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Serenafacher\Haus von Serenakrone.docx", r"Serenafacher\Serenafächer ~1 Krönhummer.docx",
        haus_sections=("5. Capital and Settlement", "6. Glass Coral Foundations", "7. Kinship, Membership and Civic Status"),
        species_sections=("8. Respiration, Hydration and Metabolism", "12. Habitat, Geology and Range"),
    ),
    "STILLKLINGE": _rule(
        "STILLKLINGE", "NEBELFLEDER", "Nebelfleder / Fog Bat",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "ROOST_AND_CAVERN_RANGE",
        "Count each Fog Bat once by biological identity; roosts, caverns, and surface accesses are habitat contexts, never independently summed colonies without an identity linkage.",
        ("NO_ROOST_DUPLICATION", "NO_CAVERN_2D_CAPACITY_SUBSTITUTION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Fogbat\Haus von Stillklinge.docx", r"Fogbat\Nebelfleder ~1 Fog Bat.docx",
    ),
    "STURMGLAS": _rule(
        "STURMGLAS", "STURMMEDUSE", "Sturmmeduse / Aero-Jelly",
        "WILD_RANGE_SPECIES", "ADULT_INDIVIDUAL_PLUS_SEPARATE_SKY_REEF_FEATURE", "AERIAL_RANGE_AND_SKY_REEF",
        "Adults and sky reefs are distinct record types: count adult individuals once, record sky reefs as separate non-individual habitat/reproductive features, and never add a reef to the adult headcount.",
        ("NO_SKY_REEF_AS_ADULT_COUNT", "NO_AERIAL_SITE_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Aerojelly\Haus von Sturmglas.docx", r"Aerojelly\Sturmmeduse ~1 Aero-Jelly Species Page.docx",
    ),
    "VERFUEHRSCHLUND": _rule(
        "VERFUEHRSCHLUND", "SUESSFAULSCHLUND", "Süßfäulschlund / Sweet-Rot Maw",
        "RESIDENT_SPECIES", "CONNECTED_ROOTREACH", "CONNECTED_ROOTREACH_AND_CROWN_ENCLAVE_CONTEXT",
        "Count connected Rootreach systems, not visible crowns. One recognised Maw and one active bond per crown enclave are linked minima, but cannot be summed into a population until Rootreach connectivity deduplication is known.",
        ("NO_VISIBLE_CROWN_AS_INDIVIDUAL_COUNT", "NO_ROOTREACH_DUPLICATION", "NO_SEPARATE_ORDINARY_HUMAN_SETTLEMENT_INFERENCE", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Venus Rafflesia\Haus des Verführschlunds.docx", r"Venus Rafflesia\Sweet-Rot Maw ~1 Süßfäulschlund.docx",
        haus_sections=("4. Territory, Peak and Settlement", "5. Kinship, Membership and Social Organisation", "7. Law, Evidence and Jurisdiction"),
        species_sections=("4. Size, Immobility and Physiology", "6. Habitat, Geology and Range", "7. Diet, Social Life and Reproduction"),
        notes=("Current numerical status is incomplete specifically because connected Rootreach lineage data has not yet been installed.",),
    ),
    "WIEDERGEBORENE_FLAMME": _rule(
        "WIEDERGEBORENE_FLAMME", "PHOENIX", "Phoenix",
        "RESIDENT_SPECIES", "CONTINUOUS_INDIVIDUAL_ACROSS_REBIRTH", "MOBILE_HOSTED_SERVICE_RANGE",
        "A rebirth is the same continuing Phoenix individual, not a new population entry. Hospital/service sites are host contexts and count the Phoenix only at its primary current identity.",
        ("NO_REBIRTH_DUPLICATION", "NO_HOSPITAL_HOST_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Phoenix\Haus der Wiedergeborenen Flamme.docx", r"Phoenix\Phoenix.docx",
        notes=("One human ↔ one Phoenix is an exact linked relationship minimum where a bond is evidenced; it does not establish a complete species census.",),
    ),
    "ZWIELICHT": _rule(
        "ZWIELICHT", "ZWEIFLUEGEL", "Zweiflügel / Twinwing Monarch",
        "WILD_RANGE_SPECIES", "INDIVIDUAL", "AERIAL_TERRITORIAL_RANGE",
        "Count a Twinwing once by persistent individual identity across its aerial territory; paired or courtly contexts are associations, not duplicate population totals.",
        ("NO_AERIAL_SITE_DUPLICATION", "NO_UNSUPPORTED_BIOLOGICAL_DEMAND_QUANTIFICATION"),
        r"Twinwing\Haus von Zwielicht.docx", r"Twinwing\Zweiflügel ~1 Twinwing Monarchs.docx",
    ),
}


EXPECTED_HAUS_IDS = frozenset({
    "BUCHHAIN", "DUFTFAEHRTE", "DUNKELHAUCH", "EDELSTEIN", "EISENWEB",
    "EREMITENSCHALE", "FEUERSCHUPPE", "FROSTGLANZ", "GLANZGRUND",
    "LAUBRAUNEN", "MARIENHAIN", "MOORWANDLER", "NACHTFLUESTERN",
    "SEELENWACHT", "SERENAKRONE", "STILLKLINGE", "STURMGLAS",
    "VERFUEHRSCHLUND", "WIEDERGEBORENE_FLAMME", "ZWIELICHT",
})


def rule_for_haus(haus_id: str | None) -> SpeciesCountingRule:
    """Resolve a canonical Haus ID, preserving the known Marienbien warning."""

    normalized = str(haus_id or "").upper().strip()
    aliases = {
        "MARIENBIEN": "MARIENHAIN",
        "MARIENBIENE": "MARIENHAIN",
        "HAUS_VON_MARIENHAIN": "MARIENHAIN",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return SPECIES_RULES[normalized]
    except KeyError as error:
        raise KeyError(f"No Stage 6D primary-species rule for Haus {haus_id!r}") from error


def rule_fingerprint(rule: SpeciesCountingRule) -> str:
    payload = {
        "method_version": METHOD_VERSION,
        "haus_id": rule.haus_id,
        "species_id": rule.species_id,
        "counting_unit": rule.counting_unit,
        "residence_mode": rule.residence_mode,
        "deduplication_rule": rule.deduplication_rule,
        "hard_exclusions": rule.hard_exclusions,
        "numeric_status": rule.numeric_status,
        "known_exact_count": rule.known_exact_count,
        "food_demand": rule.food_demand_milliunits_per_counting_unit,
        "food_demand_status": rule.food_demand_status,
        "sources": [pointer.as_dict() for pointer in rule.source_pointers],
        "notes": rule.notes,
        "warnings": rule.warnings,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def catalogue_fingerprint() -> str:
    return hashlib.sha256(
        _canonical_json({key: rule_fingerprint(value) for key, value in sorted(SPECIES_RULES.items())}).encode("utf-8")
    ).hexdigest()


def self_check(*, require_local_sources: bool = False) -> dict[str, Any]:
    """Validate the non-negotiable counting and unknown-demand rules."""

    actual = frozenset(SPECIES_RULES)
    if actual != EXPECTED_HAUS_IDS:
        raise RuntimeError(f"Expected Haus IDs differ: missing={sorted(EXPECTED_HAUS_IDS - actual)} extra={sorted(actual - EXPECTED_HAUS_IDS)}")
    if len(SPECIES_RULES) != 20:
        raise RuntimeError(f"Expected 20 primary Haus/species rules, found {len(SPECIES_RULES)}")

    for haus_id, rule in SPECIES_RULES.items():
        if rule.haus_id != haus_id:
            raise RuntimeError(f"Rule/key mismatch: {haus_id} vs {rule.haus_id}")
        if len(rule.source_pointers) != 2 or not all(pointer.sections for pointer in rule.source_pointers):
            raise RuntimeError(f"Incomplete source pointers for {haus_id}")
        is_non_ecological = rule.species_id in {"SCHWARZFLUT", "THE_KEPT"}
        if is_non_ecological:
            if rule.food_demand_milliunits_per_counting_unit != 0 or rule.food_demand_status != NUMERIC_STATUS_NOT_APPLICABLE:
                raise RuntimeError(f"Non-ecological food handling invalid for {haus_id}")
        elif rule.food_demand_milliunits_per_counting_unit is not None or rule.food_demand_status != NUMERIC_STATUS_INCOMPLETE:
            raise RuntimeError(f"Unsupported biological food demand fabricated for {haus_id}")
        if rule.known_exact_count is not None and rule.known_exact_count < 0:
            raise RuntimeError(f"Negative exact count for {haus_id}")
        if require_local_sources:
            missing = [str(pointer.path) for pointer in rule.source_pointers if not pointer.path.is_file()]
            if missing:
                raise RuntimeError(f"Missing primary source(s) for {haus_id}: {missing}")

    return {
        "status": "PASS",
        "method_version": METHOD_VERSION,
        "rule_count": len(SPECIES_RULES),
        "numeric_population_complete_count": sum(rule.numeric_status == "FOUND" for rule in SPECIES_RULES.values()),
        "food_demand_incomplete_count": sum(rule.food_demand_status == NUMERIC_STATUS_INCOMPLETE for rule in SPECIES_RULES.values()),
        "catalogue_fingerprint": catalogue_fingerprint(),
        "canon_status": CANON_STATUS,
    }


if __name__ == "__main__":
    print(json.dumps(self_check(require_local_sources=True), ensure_ascii=False, indent=2, sort_keys=True))
