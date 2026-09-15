#!/usr/bin/env python3
"""Canon-grounded human pool rules for the Stage 6D working proposal.

The catalogue defines *where and how* ordinary/unbonded and bonded humans may
be counted for each of the twenty primary Hauses.  It does not manufacture a
census or infer a bonded share from settlement form.  Every Haus has two
explicit profiles, even when a profile is proven absent, so later code cannot
silently merge ordinary and bonded humans or fall back to a generic rule.

Population identity is exact: ``human_total = ordinary_unbonded + bonded``.
Hosted services belong to the host settlement once and never create a second
sponsor population.  Bonded people have one working population number per
pool; bond-stage distributions are deliberately prohibited.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


METHOD_VERSION = "STAGE6D_CANON_HUMAN_POOL_CATALOGUE_V1"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"

PRIMARY_HAUS_ROOT = Path(
    r"C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\01_Current_Drive_Snapshot\Primary Hausen"
)
STAGE6_RESIDENCY_REPORT = Path(
    r"C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\01_Current_Drive_Snapshot\Geography\High-Resolution Map Modes\30 Settlement Formation\Stage 6 - Settlement Realisation\00 Portfolio Decision Register\ALL_20_HAUS_STAGE6_DECISION_REPORT_2026-08-27.md"
)

FOUND = "FOUND"
PROVEN_ABSENT = "PROVEN_ABSENT"
INCOMPLETE = "INCOMPLETE"

ORDINARY = "ORDINARY_UNBONDED"
BONDED = "BONDED"

SITE_RESIDENT = "SITE_RESIDENT"
MOBILE_SHARED = "MOBILE_SHARED"
ADMINISTRATIVE_ONLY = "ADMINISTRATIVE_ONLY"

SEPARATE_SITE_POOLS = "SEPARATE_SITE_POOLS"
EMBEDDED_NATIVE_HOST_ONLY = "EMBEDDED_NATIVE_HOST_ONLY"
NO_PERMANENT_POOL = "NO_PERMANENT_POOL"
ONE_TERRITORIAL_SHARED_POOL = "ONE_TERRITORIAL_SHARED_POOL"
MULTIPLE_MOBILE_CARAVAN_POOLS = "MULTIPLE_MOBILE_CARAVAN_POOLS"
ONE_ACTIVE_INFRASTRUCTURE_POOL = "ONE_ACTIVE_INFRASTRUCTURE_POOL"
SURFACE_DRY_OR_BREATHABLE_ONLY = "SURFACE_DRY_OR_BREATHABLE_ONLY"
SURFACE_LAGOON_ONLY = "SURFACE_LAGOON_ONLY"
GENERAL_WITH_STILT_CONCENTRATION = "GENERAL_WITH_STILT_CONCENTRATION"

KNOWN_TOTAL_NONE = "UNRESOLVED"
KNOWN_TOTAL_EXACT = "EXACT"
KNOWN_TOTAL_APPROXIMATE = "APPROXIMATE"

HOSTED_COUNT_RULE = (
    "Count every hosted-service human at the host settlement exactly once. "
    "Sponsor or service affiliation is metadata and creates neither a second "
    "population record nor a territorial enclave."
)
TOTAL_IDENTITY_RULE = "HUMAN_TOTAL_EQUALS_ORDINARY_UNBONDED_PLUS_BONDED"
BONDED_SINGLE_NUMBER_RULE = (
    "One working bonded-human number per population pool; no low/high bond "
    "bands and no bond-stage distribution."
)

EXPECTED_HAUS_IDS = frozenset(
    {
        "BUCHHAIN",
        "DUFTFAEHRTE",
        "DUNKELHAUCH",
        "EDELSTEIN",
        "EISENWEB",
        "EREMITENSCHALE",
        "FEUERSCHUPPE",
        "FROSTGLANZ",
        "GLANZGRUND",
        "LAUBRAUNEN",
        "MARIENHAIN",
        "MOORWANDLER",
        "NACHTFLUESTERN",
        "SEELENWACHT",
        "SERENAKRONE",
        "STILLKLINGE",
        "STURMGLAS",
        "VERFUEHRSCHLUND",
        "WIEDERGEBORENE_FLAMME",
        "ZWIELICHT",
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SourcePointer:
    """Human-auditable evidence pointer without pretending to quote a page."""

    source_kind: str
    relative_path: str
    sections: tuple[str, ...]
    authority_status: str

    @property
    def path(self) -> Path:
        if self.source_kind == "STAGE6_RESIDENCY_DECISION_REPORT":
            return STAGE6_RESIDENCY_REPORT
        return PRIMARY_HAUS_ROOT / self.relative_path

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "path": str(self.path),
            "sections": list(self.sections),
            "authority_status": self.authority_status,
        }


@dataclass(frozen=True)
class HumanPoolRule:
    """One ordinary/unbonded or bonded profile for one Haus."""

    pool_role: str
    population_class: str
    pool_kind: str
    residence_mode: str
    evidence_status: str
    known_population: int | None
    known_population_qualifier: str
    counting_rule: str
    site_gate_codes: tuple[str, ...]
    bonded_share_category: str | None = None

    def __post_init__(self) -> None:
        if self.pool_role not in {ORDINARY, BONDED}:
            raise ValueError(f"invalid pool role: {self.pool_role}")
        if self.population_class not in {"UNBONDED_HUMAN", "BONDED_HUMAN"}:
            raise ValueError(f"invalid population class: {self.population_class}")
        if self.evidence_status not in {FOUND, PROVEN_ABSENT, INCOMPLETE}:
            raise ValueError(f"invalid evidence status: {self.evidence_status}")
        if self.known_population is not None and self.known_population < 0:
            raise ValueError("known population cannot be negative")
        if self.evidence_status == PROVEN_ABSENT and self.known_population != 0:
            raise ValueError("a proven-absent pool must have known population zero")
        if self.pool_role == BONDED and self.bonded_share_category not in {None, "UNRESOLVED"}:
            raise ValueError("bonded shares may not be invented by this catalogue")

    @property
    def profile_suffix(self) -> str:
        return "UNBONDED_HUMAN" if self.pool_role == ORDINARY else "BONDED_HUMAN"

    def as_dict(self) -> dict[str, Any]:
        return {
            "pool_role": self.pool_role,
            "population_class": self.population_class,
            "pool_kind": self.pool_kind,
            "residence_mode": self.residence_mode,
            "evidence_status": self.evidence_status,
            "known_population": self.known_population,
            "known_population_qualifier": self.known_population_qualifier,
            "counting_rule": self.counting_rule,
            "site_gate_codes": list(self.site_gate_codes),
            "bonded_share_category": self.bonded_share_category,
        }


@dataclass(frozen=True)
class HumanHausRule:
    """Complete human pool and anti-duplication rule for one primary Haus."""

    haus_id: str
    display_name: str
    primary_species_id: str
    ordinary: HumanPoolRule
    bonded: HumanPoolRule
    bond_count_constraint: str
    hosted_service_rule: str
    total_identity_rule: str
    inactive_site_rule: str
    source_pointers: tuple[SourcePointer, ...]
    notes: tuple[str, ...] = ()

    def profile_id(self, pool_role: str) -> str:
        rule = self.ordinary if pool_role == ORDINARY else self.bonded
        return f"HUMAN::{self.haus_id}::{rule.profile_suffix}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "haus_id": self.haus_id,
            "display_name": self.display_name,
            "primary_species_id": self.primary_species_id,
            "ordinary": self.ordinary.as_dict(),
            "bonded": self.bonded.as_dict(),
            "bond_count_constraint": self.bond_count_constraint,
            "hosted_service_rule": self.hosted_service_rule,
            "total_identity_rule": self.total_identity_rule,
            "inactive_site_rule": self.inactive_site_rule,
            "source_pointers": [source.as_dict() for source in self.source_pointers],
            "notes": list(self.notes),
            "method_version": METHOD_VERSION,
            "canon_status": CANON_STATUS,
        }


@dataclass(frozen=True)
class SiteGateDecision:
    allowed: bool
    evidence_status: str
    preference: str
    reason_code: str


def _report(haus_heading: str) -> SourcePointer:
    return SourcePointer(
        source_kind="STAGE6_RESIDENCY_DECISION_REPORT",
        relative_path="",
        sections=("Controlling rules", haus_heading),
        authority_status="WORKING_CONSOLIDATION_REVIEW_ONLY_NOT_NEW_CANON",
    )


def _doc(path: str, *sections: str, species: bool = False) -> SourcePointer:
    return SourcePointer(
        source_kind="PRIMARY_SPECIES_DOCX" if species else "PRIMARY_HAUS_DOCX",
        relative_path=path,
        sections=tuple(sections),
        authority_status="PRIMARY_CANON_SOURCE",
    )


def _ordinary(
    residence_mode: str = SEPARATE_SITE_POOLS,
    *,
    pool_kind: str = SITE_RESIDENT,
    evidence_status: str = INCOMPLETE,
    known_population: int | None = None,
    qualifier: str = KNOWN_TOTAL_NONE,
    counting_rule: str = (
        "Create a distinct ordinary/unbonded human count for each eligible "
        "resident pool; never derive it as the remainder of a bonded fraction."
    ),
    gates: Iterable[str] = ("PHYSICALLY_AND_INFRASTRUCTURALLY_SUPPORTABLE",),
) -> HumanPoolRule:
    return HumanPoolRule(
        pool_role=ORDINARY,
        population_class="UNBONDED_HUMAN",
        pool_kind=pool_kind,
        residence_mode=residence_mode,
        evidence_status=evidence_status,
        known_population=known_population,
        known_population_qualifier=qualifier,
        counting_rule=counting_rule,
        site_gate_codes=tuple(gates),
    )


def _bonded(
    residence_mode: str = SEPARATE_SITE_POOLS,
    *,
    pool_kind: str = SITE_RESIDENT,
    evidence_status: str = INCOMPLETE,
    known_population: int | None = None,
    qualifier: str = KNOWN_TOTAL_NONE,
    counting_rule: str = BONDED_SINGLE_NUMBER_RULE,
    gates: Iterable[str] = ("PRIMARY_SPECIES_BOND_CONTEXT_PRESENT",),
) -> HumanPoolRule:
    return HumanPoolRule(
        pool_role=BONDED,
        population_class="BONDED_HUMAN",
        pool_kind=pool_kind,
        residence_mode=residence_mode,
        evidence_status=evidence_status,
        known_population=known_population,
        known_population_qualifier=qualifier,
        counting_rule=counting_rule,
        site_gate_codes=tuple(gates),
        bonded_share_category="UNRESOLVED" if evidence_status == INCOMPLETE else None,
    )


def _standard(
    haus_id: str,
    display_name: str,
    species_id: str,
    folder: str,
    haus_doc: str,
    species_doc: str,
    *,
    notes: Iterable[str] = (),
) -> HumanHausRule:
    return HumanHausRule(
        haus_id=haus_id,
        display_name=display_name,
        primary_species_id=species_id,
        ordinary=_ordinary(),
        bonded=_bonded(),
        bond_count_constraint=(
            "Total bonded humans unresolved. Count each living human once in "
            "the bonded profile of their primary residence pool."
        ),
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="NO_SPECIAL_INACTIVE_SITE_EXCEPTION",
        source_pointers=(
            _report(display_name),
            _doc(f"{folder}\\{haus_doc}", "4. Territory, Capital and Settlement", "5. Kinship, Membership and Social Organisation", "9. Primary Species and Bannerhaeuser"),
            _doc(f"{folder}\\{species_doc}", "Bonding and Bonded Progression", "7. Diet, Social Life and Reproduction", species=True),
        ),
        notes=tuple(notes),
    )


HUMAN_RULES: dict[str, HumanHausRule] = {
    "BUCHHAIN": _standard(
        "BUCHHAIN", "Buchhain", "SKRIPTEULE", "Ink Owl",
        "Haus von Buchhain.docx", "Skripteule ~1 Giant Ink Owl.docx",
    ),
    "DUFTFAEHRTE": HumanHausRule(
        haus_id="DUFTFAEHRTE",
        display_name="Duftfaehrte",
        primary_species_id="SCHIMMERHUND",
        ordinary=_ordinary(
            MULTIPLE_MOBILE_CARAVAN_POOLS,
            pool_kind=MOBILE_SHARED,
            evidence_status=INCOMPLETE,
            counting_rule=(
                "Do not create ordinary permanent human site pools. Count any "
                "unbonded relatives, dependants, or affiliated humans once in "
                "their actual caravan's mobile pool. Duftfaehrte can contain "
                "multiple caravans; the capital caravan is one of them. Fixed "
                "host grounds are anchors, not separate populations."
            ),
            gates=(
                "NO_ORDINARY_PERMANENT_HUMAN_SETTLEMENTS",
                "ONE_MOBILE_SEASONAL_HAUS_POOL",
                "ANCHORS_DO_NOT_OWN_POPULATION",
            ),
        ),
        bonded=_bonded(
            MULTIPLE_MOBILE_CARAVAN_POOLS,
            pool_kind=MOBILE_SHARED,
            counting_rule=(
                f"{BONDED_SINGLE_NUMBER_RULE} Use one population pool per actual "
                "caravan. The capital caravan and other caravans are distinct; "
                "fixed host grounds are anchors, not separate populations."
            ),
            gates=("MULTIPLE_MOBILE_CARAVAN_POOLS", "ANCHORS_DO_NOT_OWN_POPULATION"),
        ),
        bond_count_constraint=(
            "Caravan totals and caravan count are unresolved. Count each bonded "
            "mobile human once in their actual caravan and never multiply them "
            "by capital-caravan anchor or court-host grounds."
        ),
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="FIXED_HOST_GROUNDS_ARE_ANCHORS_NOT_PERMANENT_HUMAN_TOWNS",
        source_pointers=(
            _report("Duftfährte"),
            _doc(r"Shimmerhound\Haus von Duftfährte.docx", "4. Territory, Capital and Settlement", "5. Kinship, Membership and Social Organisation", "Obsidian Arena bonding"),
            _doc(r"Shimmerhound\Shimmerhound ~1 Schimmerhund.docx", "Bonding and Bonded Progression", "Habitat, Geology and Range", species=True),
        ),
    ),
    "DUNKELHAUCH": HumanHausRule(
        haus_id="DUNKELHAUCH",
        display_name="Dunkelhauch",
        primary_species_id="SCHWARZFLUT",
        ordinary=_ordinary(
            NO_PERMANENT_POOL,
            pool_kind=ADMINISTRATIVE_ONLY,
            evidence_status=PROVEN_ABSENT,
            known_population=0,
            qualifier=KNOWN_TOTAL_EXACT,
            counting_rule="No general ordinary-human settlement layer.",
            gates=("NO_GENERAL_ORDINARY_HUMAN_LAYER",),
        ),
        bonded=_bonded(
            ONE_ACTIVE_INFRASTRUCTURE_POOL,
            pool_kind=MOBILE_SHARED,
            evidence_status=FOUND,
            known_population=50,
            qualifier=KNOWN_TOTAL_APPROXIMATE,
            counting_rule=(
                f"{BONDED_SINGLE_NUMBER_RULE} Record approximately fifty bonded "
                "humans once across the active Blackflood Heart/infrastructure system."
            ),
            gates=("BLACKFLOOD_HEART_SYSTEM_ONLY",),
        ),
        bond_count_constraint="Approximately fifty bonded humans total; this is a Haus-wide total, not fifty per site.",
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule=(
            "Former settlement locations are inactive wartime fortifications. "
            "They retain identity but receive no resident population in peacetime."
        ),
        source_pointers=(
            _report("Dunkelhauch"),
            _doc(r"Blackflood\Haus von Dunkelhauch.docx", "4. Territory, Capital and Settlement", "5. Kinship, Membership and Social Organisation"),
            _doc(r"Blackflood\Dunkelhauch ~1 Schwarzflut.docx", "Bonding and Bonded Progression", "Social Life", species=True),
        ),
        notes=("No external enclaves and no routine food-settlement network.",),
    ),
    "EDELSTEIN": _standard(
        "EDELSTEIN", "Edelstein", "EDELMAUL", "Crownjaw",
        "Haus vom Edelstein.docx", "Crownjaw ~1 Edelmaul.docx",
    ),
    "EISENWEB": _standard(
        "EISENWEB", "Eisenweb", "STAHLSPINNE", "Ferrarachne",
        "Haus von Eisenweb.docx", "Ferrarachne ~1 Stahlspinne.docx",
    ),
    "EREMITENSCHALE": _standard(
        "EREMITENSCHALE", "Eremitenschale", "EREMITENSCHNECKE", "Hermit Snails",
        "Haus von Eremitenschale.docx", "Eremitenschnecke ~1 Hermit Snail.docx",
        notes=("Breadbasket/export status changes food supply and trade, never the human counting identity.",),
    ),
    "FEUERSCHUPPE": _standard(
        "FEUERSCHUPPE", "Feuerschuppe", "DRACHE", "Dragon",
        "Haus von Feuerschuppe.docx", "European Dragon ~1 Drache.docx",
    ),
    "FROSTGLANZ": _standard(
        "FROSTGLANZ", "Frostglanz", "FROSTHIRSCH", "Frost Elk",
        "Haus vom Frostglanz.docx", "Frost Elk ~1 Frosthirsch.docx",
    ),
    "GLANZGRUND": HumanHausRule(
        haus_id="GLANZGRUND",
        display_name="Glanzgrund",
        primary_species_id="CHROMAKRAKE",
        ordinary=_ordinary(
            SURFACE_DRY_OR_BREATHABLE_ONLY,
            gates=(
                "SURFACE_COMMUNITY_OR_DRY_DISTRICT",
                "SURFACE_FACING_SHAFT_OR_AIR_CAVERN",
                "NO_FULLY_SUBMERGED_ORDINARY_HUMANS",
            ),
        ),
        bonded=_bonded(
            SEPARATE_SITE_POOLS,
            gates=(
                "PRIMARY_SPECIES_BOND_CONTEXT_PRESENT",
                "SUBMERGED_BONDED_CAPACITY_REQUIRES_SPECIALIST_3D_EVIDENCE",
            ),
        ),
        bond_count_constraint="Bonded-human total unresolved; submerged bonded capacity remains INCOMPLETE until specialist 3D evidence exists.",
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="NO_SPECIAL_INACTIVE_SITE_EXCEPTION",
        source_pointers=(
            _report("Glanzgrund"),
            _doc(r"Chromakraken\Haus von Glanzgrund.docx", "4. Territory, Capital and Settlement", "5. Kinship, Membership and Social Organisation"),
            _doc(r"Chromakraken\Chromakrake ~1 Chromakraken.docx", "Bonding and Bonded Progression", "6. Habitat, Geology and Range", species=True),
        ),
    ),
    "LAUBRAUNEN": HumanHausRule(
        haus_id="LAUBRAUNEN",
        display_name="Laubraunen",
        primary_species_id="SCHUPPENRINDE",
        ordinary=_ordinary(
            EMBEDDED_NATIVE_HOST_ONLY,
            counting_rule=(
                "Create an ordinary/unbonded count only inside an existing "
                "bonded/native canopy, flet, root-adjacent or forest-edge host. "
                "Never create a separate ordinary-human settlement pool."
            ),
            gates=("EXISTING_NATIVE_ENCLAVE_REQUIRED", "NO_GENERIC_GREAT_FOREST_GROUND_LAYER"),
        ),
        bonded=_bonded(
            EMBEDDED_NATIVE_HOST_ONLY,
            gates=("EXISTING_NATIVE_ENCLAVE_REQUIRED", "FOREST_OR_CANOPY_CONTEXT_REQUIRED"),
        ),
        bond_count_constraint="Total bonded humans unresolved; bonded and ordinary counts remain separate columns within the same native host pool.",
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="NO_SEPARATE_HUMAN_SITE_IDENTITY_MAY_BE_SYNTHESISED",
        source_pointers=(
            _report("Laubraunen"),
            _doc(r"Canopy Whipsnake\Haus von Laubraunen.docx", "4. Territory, Capital and Settlement", "5. Kinship, Membership and Social Organisation"),
            _doc(r"Canopy Whipsnake\Schuppenrinde ~1 Canopy Whipsnake.docx", "Bonding and Bonded Progression", "6. Habitat, Geology and Range", species=True),
        ),
    ),
    "MARIENHAIN": HumanHausRule(
        **{
            **_standard(
                "MARIENHAIN", "Marienhain", "MARIENBIENE", "Ladybee",
                "Haus von Marienhain.docx", "Marienbiene ~1 Ladybee.docx",
                notes=("Breadbasket/export status changes food supply and trade, never the human counting identity.",),
            ).__dict__,
            "bond_count_constraint": (
                "One bonded human corresponds to one bondable individual Marienbiene; "
                "drones never bond. Overall bonded-human total remains unresolved."
            ),
        }
    ),
    "MOORWANDLER": HumanHausRule(
        haus_id="MOORWANDLER",
        display_name="Moorwandler",
        primary_species_id="MOORRIESE",
        ordinary=_ordinary(
            GENERAL_WITH_STILT_CONCENTRATION,
            gates=(
                "SUITABLE_INTER_RIVER_LAND_ALLOWED",
                "INFRASTRUCTURE_SUPPORTED_WETLAND_ALLOWED",
                "BONDING_NOT_MEMBERSHIP_REQUIREMENT",
            ),
        ),
        bonded=_bonded(
            GENERAL_WITH_STILT_CONCENTRATION,
            gates=("STILT_VILLAGES_STRONGLY_PREFERRED_NOT_EXCLUSIVE",),
        ),
        bond_count_constraint="Bonded-human total unresolved; distribution is concentrated in stilt villages but not forced into an exclusive stage or site class.",
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="NO_SPECIAL_INACTIVE_SITE_EXCEPTION",
        source_pointers=(
            _report("Moorwandler"),
            _doc(r"Bog Colossus\Haus der Moorwandler.docx", "4. Territory, Capital and Settlement", "5. Kinship, Membership and Social Organisation"),
            _doc(r"Bog Colossus\Bog Colossus ~1 Moorriese.docx", "Bonding and Bonded Progression", "6. Habitat, Geology and Range", species=True),
        ),
    ),
    "NACHTFLUESTERN": _standard(
        "NACHTFLUESTERN", "Nachtflüstern", "NACHTFLUESTERER", "Nightwhisperer",
        "Haus von Nachtflüstern.docx", "Nightwhisperer ~1 Nachtflüsterer.docx",
    ),
    "SEELENWACHT": HumanHausRule(
        haus_id="SEELENWACHT",
        display_name="Seelenwacht",
        primary_species_id="THE_KEPT",
        ordinary=_ordinary(
            SEPARATE_SITE_POOLS,
            gates=("LIVING_CONGREGATION_SITE", "PHYSICALLY_AND_INFRASTRUCTURALLY_SUPPORTABLE"),
        ),
        bonded=_bonded(
            NO_PERMANENT_POOL,
            pool_kind=ADMINISTRATIVE_ONLY,
            evidence_status=PROVEN_ABSENT,
            known_population=0,
            qualifier=KNOWN_TOTAL_EXACT,
            counting_rule="The Kept do not form a bond with a living human; primary-species bonded-human count is zero.",
            gates=("PRIMARY_SPECIES_HAS_NO_BOND",),
        ),
        bond_count_constraint="Primary-species bonded humans exactly zero; Bannerhaus bonds belong to their own later catalogues.",
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="UNMANNED_SATELLITE_CLOISTER_IS_NOT_A_RESIDENT_HUMAN_POOL_UNLESS_A_HOST_CUSTODIANSHIP_IS_EVIDENCED",
        source_pointers=(
            _report("Seelenwacht"),
            _doc(r"The Kept\Haus von Seelenwacht.docx", "The Cathedral capital", "Satellite cloisters", "5. Membership and Social Organisation", "9. Primary Species and Bannerhaeuser"),
            _doc(r"The Kept\The Kept ~1 die Aufgehobenen.docx", "Formation", "Social Organisation", species=True),
        ),
        notes=("Living Congregation and Kept stock-flow remain distinct populations.",),
    ),
    "SERENAKRONE": HumanHausRule(
        haus_id="SERENAKRONE",
        display_name="Serenakrone",
        primary_species_id="SERENAFACHER",
        ordinary=_ordinary(
            SURFACE_LAGOON_ONLY,
            gates=("SHORE_ISLAND_OR_SURFACE_BUILT_INFRASTRUCTURE", "NO_SUBMERGED_HUMAN_SETTLEMENT"),
        ),
        bonded=_bonded(
            SURFACE_LAGOON_ONLY,
            gates=("SURFACE_LAGOON_HUMAN_POOL", "UNDERWATER_CORAL_IS_CONTEXT_ONLY"),
        ),
        bond_count_constraint="Bonded-human total unresolved; both human profiles remain surface communities even where their species or foundations are underwater.",
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="UNDERWATER_GLASS_CORAL_FOUNDATION_IS_NOT_A_HUMAN_RESIDENT_POOL",
        source_pointers=(
            _report("Serenakrone"),
            _doc(r"Serenafacher\Haus von Serenakrone.docx", "5. Capital and Settlement", "6. Glass Coral Foundations", "7. Kinship, Membership and Civic Status"),
            _doc(r"Serenafacher\Serenafächer ~1 Krönhummer.docx", "Bonding and Bonded Progression", "12. Habitat, Geology and Range", species=True),
        ),
    ),
    "STILLKLINGE": _standard(
        "STILLKLINGE", "Stillklinge", "NEBELFLEDER", "Fogbat",
        "Haus von Stillklinge.docx", "Nebelfleder ~1 Fog Bat.docx",
        notes=("Infrastructure-enabled cavern human pools remain INCOMPLETE where specialist 3D capacity is unavailable.",),
    ),
    "STURMGLAS": _standard(
        "STURMGLAS", "Sturmglas", "STURMMEDUSE", "Aerojelly",
        "Haus von Sturmglas.docx", "Sturmmeduse ~1 Aero-Jelly Species Page.docx",
        notes=("Aerohamlets are resident/mobile settlements, not duplicate copies of the capital population.",),
    ),
    "VERFUEHRSCHLUND": HumanHausRule(
        haus_id="VERFUEHRSCHLUND",
        display_name="Verführschlund",
        primary_species_id="SUESSFAULSCHLUND",
        ordinary=_ordinary(
            EMBEDDED_NATIVE_HOST_ONLY,
            counting_rule=(
                "Ordinary/unbonded humans may be counted inside an existing "
                "crown/native enclave, including Mother's Mouth where supported. "
                "Never create a separate ordinary-human settlement pool."
            ),
            gates=("EXISTING_CROWN_ENCLAVE_REQUIRED", "NO_GENERIC_GROUND_SETTLEMENT_LAYER"),
        ),
        bonded=_bonded(
            EMBEDDED_NATIVE_HOST_ONLY,
            gates=("RECOGNISED_CROWN_ENCLAVE_REQUIRED", "ONE_ACTIVE_BOND_PER_CROWN_ENCLAVE"),
        ),
        bond_count_constraint=(
            "Exactly one active bonded human (the Maw-Mother) per recognised "
            "crown enclave. Enclave totals remain unresolved until connected "
            "Rootreach identities are deduplicated."
        ),
        hosted_service_rule=HOSTED_COUNT_RULE,
        total_identity_rule=TOTAL_IDENTITY_RULE,
        inactive_site_rule="NO_SEPARATE_HUMAN_SITE_IDENTITY_MAY_BE_SYNTHESISED",
        source_pointers=(
            _report("Verführschlund"),
            _doc(r"Venus Rafflesia\Haus des Verführschlunds.docx", "4. Territory, Peak and Settlement", "5. Kinship, Membership and Social Organisation", "17. Internal Design Notes"),
            _doc(r"Venus Rafflesia\Sweet-Rot Maw ~1 Süßfäulschlund.docx", "Bonding and Bonded Progression", "6. Habitat, Geology and Range", species=True),
        ),
    ),
    "WIEDERGEBORENE_FLAMME": HumanHausRule(
        **{
            **_standard(
                "WIEDERGEBORENE_FLAMME", "Wiedergeborene Flamme", "PHOENIX", "Phoenix",
                "Haus der Wiedergeborenen Flamme.docx", "Phoenix.docx",
            ).__dict__,
            "bond_count_constraint": (
                "One bonded human corresponds to one continuing Phoenix individual. "
                "Rebirth does not create a new human, Phoenix, or bonded pair record; "
                "overall bonded-human total remains unresolved."
            ),
        }
    ),
    "ZWIELICHT": _standard(
        "ZWIELICHT", "Zwielicht", "ZWEIFLUEGEL", "Twinwing",
        "Haus von Zwielicht.docx", "Zweiflügel ~1 Twinwing Monarchs.docx",
    ),
}


def rule_for_haus(haus_id: str) -> HumanHausRule:
    """Return an exact rule; unknown Hauses fail closed with no generic fallback."""

    key = str(haus_id).upper()
    try:
        return HUMAN_RULES[key]
    except KeyError as exc:
        raise KeyError(f"no Stage 6D human rule for Haus {haus_id!r}") from exc


def human_total(ordinary_unbonded: int, bonded: int) -> int:
    """Apply the sole permitted human total identity."""

    if ordinary_unbonded < 0 or bonded < 0:
        raise ValueError("human population components cannot be negative")
    return int(ordinary_unbonded) + int(bonded)


def profile_rows(rule: HumanHausRule) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return schema-compatible profile dictionaries for both human classes."""

    rows: list[dict[str, Any]] = []
    for pool_rule in (rule.ordinary, rule.bonded):
        composite = {
            "catalogue_method_version": METHOD_VERSION,
            "haus_id": rule.haus_id,
            "pool_rule": pool_rule.as_dict(),
            "bond_count_constraint": rule.bond_count_constraint,
            "hosted_service_rule": rule.hosted_service_rule,
            "total_identity_rule": rule.total_identity_rule,
            "inactive_site_rule": rule.inactive_site_rule,
            "source_pointers": [source.as_dict() for source in rule.source_pointers],
            "notes": list(rule.notes),
        }
        rows.append(
            {
                "profile_id": rule.profile_id(pool_rule.pool_role),
                "population_class": pool_rule.population_class,
                "biological_entity_id": "HUMAN",
                "counting_unit": "INDIVIDUAL_HUMAN",
                "residence_mode": pool_rule.residence_mode,
                "food_demand_milliunits_per_counting_unit": 1000,
                "composite_demand_json": canonical_json(composite),
                "evidence_status": pool_rule.evidence_status,
                "rule_fingerprint": rule_fingerprint(rule, pool_rule.pool_role),
                "canon_status": CANON_STATUS,
            }
        )
    return rows[0], rows[1]


def _site_value(site: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = site.get(name)
        if value is not None:
            return str(value).upper()
    return ""


def gate_site(haus_id: str, pool_role: str, site: Mapping[str, Any]) -> SiteGateDecision:
    """Apply the narrow, auditable residence gate without estimating a census."""

    rule = rule_for_haus(haus_id)
    pool = rule.ordinary if pool_role == ORDINARY else rule.bonded
    if pool.evidence_status == PROVEN_ABSENT:
        return SiteGateDecision(False, PROVEN_ABSENT, "NONE", "PROFILE_PROVEN_ABSENT")
    if pool.pool_kind == MOBILE_SHARED:
        return SiteGateDecision(False, FOUND, "SHARED_POOL_ONLY", "DO_NOT_CREATE_SITE_POOL")

    form = _site_value(site, "realised_settlement_form", "settlement_form")
    domain = _site_value(site, "effective_vertical_domain", "vertical_domain")
    native = site.get("native_enclave") in (1, True, "1", "TRUE") or any(
        token in form for token in ("ENCLAVE", "CANOPY", "CROWN", "HIVE", "SPECIES_SPECIFIC")
    )

    if (
        rule.haus_id == "SEELENWACHT"
        and pool_role == ORDINARY
        and _site_value(site, "entity_type") == "CATHEDRAL_CAPITAL"
        and site.get("ordinary_permanent_human_allowed") in (0, False, "0", "FALSE")
    ):
        return SiteGateDecision(
            False,
            PROVEN_ABSENT,
            "HOSTED_OR_TEMPORARY_ONLY",
            "CATHEDRAL_CAPITAL_IS_PRINCIPALLY_KEPT_NOT_A_PERMANENT_HUMAN_POOL",
        )

    if rule.haus_id == "GLANZGRUND" and pool_role == ORDINARY:
        submerged = "SUBMERGED" in form or "SUBMERGED" in domain or "FLOODED_CAVERN" in domain
        if submerged:
            return SiteGateDecision(False, PROVEN_ABSENT, "NONE", "NO_ORDINARY_HUMANS_IN_SUBMERGED_COMMUNITY")
        return SiteGateDecision(True, INCOMPLETE, "ALLOWED", "SURFACE_DRY_OR_BREATHABLE_CONTEXT")

    if rule.haus_id == "SERENAKRONE":
        if "FULLY_SUBMERGED" in form or "SUBMERGED" in domain:
            return SiteGateDecision(False, PROVEN_ABSENT, "NONE", "HUMAN_LAGOON_SETTLEMENTS_ARE_SURFACE")
        if "LAGOON" in form or "SURFACE" in domain or site.get("surface_built") in (1, True, "1", "TRUE"):
            return SiteGateDecision(True, INCOMPLETE, "ALLOWED", "SURFACE_LAGOON_CONTEXT")
        return SiteGateDecision(False, INCOMPLETE, "REVIEW", "SURFACE_LAGOON_EVIDENCE_REQUIRED")

    if rule.haus_id in {"LAUBRAUNEN", "VERFUEHRSCHLUND"}:
        if not native:
            return SiteGateDecision(False, PROVEN_ABSENT, "NONE", "EXISTING_NATIVE_HOST_REQUIRED")
        return SiteGateDecision(True, INCOMPLETE, "EMBEDDED_ONLY", "COUNT_WITHIN_NATIVE_HOST")

    if rule.haus_id == "MOORWANDLER":
        if pool_role == BONDED:
            preferred = "STILT" in form or "CHANNEL" in form or "WETLAND" in form
            return SiteGateDecision(
                True,
                INCOMPLETE,
                "STRONGLY_PREFERRED" if preferred else "ALLOWED_NOT_PREFERRED",
                "BONDED_STILT_CONCENTRATION",
            )
        return SiteGateDecision(True, INCOMPLETE, "ALLOWED", "ORDINARY_INTER_RIVER_OR_SUPPORTED_WETLAND")

    if "DEFERRED_SPECIALIST_3D" in _site_value(site, "stage6c_analysis_status"):
        return SiteGateDecision(True, INCOMPLETE, "CAPACITY_WITHHELD", "SPECIALIST_3D_EVIDENCE_REQUIRED")
    return SiteGateDecision(True, INCOMPLETE, "ALLOWED", "STANDARD_SUPPORTABILITY_GATE")


def rule_fingerprint(rule: HumanHausRule, pool_role: str | None = None) -> str:
    payload: dict[str, Any] = rule.as_dict()
    if pool_role is not None:
        payload = {
            "haus_id": rule.haus_id,
            "pool_role": pool_role,
            "pool": (rule.ordinary if pool_role == ORDINARY else rule.bonded).as_dict(),
            "shared": {
                "bond_count_constraint": rule.bond_count_constraint,
                "hosted_service_rule": rule.hosted_service_rule,
                "total_identity_rule": rule.total_identity_rule,
                "inactive_site_rule": rule.inactive_site_rule,
                "source_pointers": [source.as_dict() for source in rule.source_pointers],
                "method_version": METHOD_VERSION,
            },
        }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def catalogue_fingerprint() -> str:
    return hashlib.sha256(
        canonical_json({key: HUMAN_RULES[key].as_dict() for key in sorted(HUMAN_RULES)}).encode("utf-8")
    ).hexdigest()


def validate_catalogue(*, require_source_files: bool = False) -> list[str]:
    failures: list[str] = []
    keys = frozenset(HUMAN_RULES)
    if keys != EXPECTED_HAUS_IDS:
        failures.append(f"Haus coverage mismatch missing={sorted(EXPECTED_HAUS_IDS - keys)} extra={sorted(keys - EXPECTED_HAUS_IDS)}")
    profile_ids: set[str] = set()
    for key in sorted(HUMAN_RULES):
        rule = HUMAN_RULES[key]
        if rule.haus_id != key:
            failures.append(f"{key}: haus_id mismatch {rule.haus_id}")
        if rule.total_identity_rule != TOTAL_IDENTITY_RULE:
            failures.append(f"{key}: invalid human total rule")
        if rule.hosted_service_rule != HOSTED_COUNT_RULE:
            failures.append(f"{key}: hosted service rule drift")
        if len(rule.source_pointers) < 3:
            failures.append(f"{key}: requires report, Haus and species evidence pointers")
        for role in (ORDINARY, BONDED):
            profile_id = rule.profile_id(role)
            if profile_id in profile_ids:
                failures.append(f"duplicate profile id {profile_id}")
            profile_ids.add(profile_id)
        if rule.bonded.known_population is not None and key not in {"DUNKELHAUCH", "SEELENWACHT"}:
            failures.append(f"{key}: unsupported bonded census installed")
        if rule.bonded.known_population_qualifier == KNOWN_TOTAL_APPROXIMATE and key != "DUNKELHAUCH":
            failures.append(f"{key}: unsupported approximate bonded total")
        if require_source_files:
            for source in rule.source_pointers:
                if not source.path.is_file():
                    failures.append(f"{key}: missing source {source.path}")
    return failures


def self_check() -> dict[str, Any]:
    failures = validate_catalogue(require_source_files=False)
    return {
        "status": "PASS" if not failures else "FAIL",
        "method_version": METHOD_VERSION,
        "haus_count": len(HUMAN_RULES),
        "profile_count": len(HUMAN_RULES) * 2,
        "catalogue_fingerprint": catalogue_fingerprint(),
        "failures": failures,
    }


if __name__ == "__main__":
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))
