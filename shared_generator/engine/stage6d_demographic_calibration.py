#!/usr/bin/env python3
"""Non-canon demographic calibration for Stage 6D working candidates.

This module is deliberately separate from :mod:`stage6d_human_rules`.  The
canon catalogue decides which human pools may exist; this calibration supplies
reviewable numerical shares only so a working population run can be completed.

The central invariant is non-negotiable::

    human_total = ordinary_unbonded + bonded

A bonded-share coefficient only divides an already-calculated human total.  It
never multiplies that total, raises carrying capacity, or creates additional
people.  Every inferred coefficient is visibly ``ASSUMPTION_DOMINATED`` and
can be replaced later without changing the residence or counting rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from stage6d_human_rules import (
    HUMAN_RULES,
    EXPECTED_HAUS_IDS,
    canonical_json,
)


METHOD_VERSION = "STAGE6D_DEMOGRAPHIC_CALIBRATION_V1"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"
INFERRED_STATUS = "ASSUMPTION_DOMINATED"
FIXED_WORKING_INPUT = "FIXED_WORKING_INPUT"
EXACT_RELATIONSHIP = "EXACT_RELATIONSHIP"


@dataclass(frozen=True)
class ShareCategory:
    category_id: str
    coefficient: float
    interpretation: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.coefficient <= 1.0:
            raise ValueError("share coefficient must lie between zero and one")


SHARE_CATEGORIES: dict[str, ShareCategory] = {
    "RARE_SPECIALIST": ShareCategory(
        "RARE_SPECIALIST", 0.10,
        "Bonding is exceptional or concentrated in a narrow specialist elite.",
    ),
    "LIMITED_MINORITY": ShareCategory(
        "LIMITED_MINORITY", 0.20,
        "Bonded people are a visible minority but ordinary residents dominate.",
    ),
    "SUBSTANTIAL_MINORITY": ShareCategory(
        "SUBSTANTIAL_MINORITY", 0.35,
        "Bonding is common enough to shape institutions without forming a majority.",
    ),
    "NEAR_PARITY": ShareCategory(
        "NEAR_PARITY", 0.50,
        "Bonded and ordinary residents are of broadly comparable scale.",
    ),
    "BONDED_MAJORITY": ShareCategory(
        "BONDED_MAJORITY", 0.65,
        "The residence type is organised chiefly around bonded/native life.",
    ),
    "BONDED_DOMINANT": ShareCategory(
        "BONDED_DOMINANT", 0.80,
        "Nearly all residents of this specialised pool are bonded.",
    ),
    "BONDED_EXCLUSIVE": ShareCategory(
        "BONDED_EXCLUSIVE", 1.00,
        "The physical context excludes ordinary humans; any human residents are bonded specialists.",
    ),
}


@dataclass(frozen=True)
class ResidenceShare:
    residence_type: str
    category_id: str
    evidence_basis: str
    status: str = INFERRED_STATUS

    @property
    def coefficient(self) -> float:
        return SHARE_CATEGORIES[self.category_id].coefficient

    def as_dict(self) -> dict[str, Any]:
        return {
            "residence_type": self.residence_type,
            "category_id": self.category_id,
            "coefficient": self.coefficient,
            "evidence_basis": self.evidence_basis,
            "status": self.status,
        }


@dataclass(frozen=True)
class DemographicCalibration:
    haus_id: str
    default_residence_type: str
    base_share: ResidenceShare | None
    residence_overrides: tuple[ResidenceShare, ...]
    fixed_bonded_count: int | None
    fixed_count_scope: str | None
    fixed_count_qualifier: str | None
    exact_counts_by_residence: tuple[tuple[str, int], ...]
    rationale: str

    def __post_init__(self) -> None:
        if self.base_share is None and self.fixed_bonded_count is None and not self.exact_counts_by_residence:
            raise ValueError(f"{self.haus_id}: calibration has no numerical rule")
        if self.fixed_bonded_count is not None and self.fixed_bonded_count < 0:
            raise ValueError("fixed bonded count cannot be negative")
        for _, value in self.exact_counts_by_residence:
            if value < 0:
                raise ValueError("exact bonded count cannot be negative")

    @property
    def source_pointers(self) -> tuple[dict[str, Any], ...]:
        return tuple(source.as_dict() for source in HUMAN_RULES[self.haus_id].source_pointers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "haus_id": self.haus_id,
            "default_residence_type": self.default_residence_type,
            "base_share": None if self.base_share is None else self.base_share.as_dict(),
            "residence_overrides": [item.as_dict() for item in self.residence_overrides],
            "fixed_bonded_count": self.fixed_bonded_count,
            "fixed_count_scope": self.fixed_count_scope,
            "fixed_count_qualifier": self.fixed_count_qualifier,
            "exact_counts_by_residence": dict(self.exact_counts_by_residence),
            "rationale": self.rationale,
            "source_pointers": list(self.source_pointers),
            "method_version": METHOD_VERSION,
            "canon_status": CANON_STATUS,
        }


@dataclass(frozen=True)
class HumanSplit:
    haus_id: str
    residence_type: str
    human_total: int
    ordinary_unbonded: int
    bonded: int
    coefficient_used: float | None
    evidence_status: str
    basis: str

    def __post_init__(self) -> None:
        if min(self.human_total, self.ordinary_unbonded, self.bonded) < 0:
            raise ValueError("population values cannot be negative")
        if self.ordinary_unbonded + self.bonded != self.human_total:
            raise ValueError("human split violates conservation identity")

    def as_estimate_rows(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return one-number rows; bonded ranges are intentionally impossible."""

        shared = {
            "haus_id": self.haus_id,
            "residence_type": self.residence_type,
            "human_total": self.human_total,
            "evidence_status": self.evidence_status,
            "basis": self.basis,
            "method_version": METHOD_VERSION,
            "canon_status": CANON_STATUS,
        }
        ordinary = {
            **shared,
            "population_class": "UNBONDED_HUMAN",
            "working_population": self.ordinary_unbonded,
        }
        bonded = {
            **shared,
            "population_class": "BONDED_HUMAN",
            "working_population": self.bonded,
        }
        return ordinary, bonded


def _share(residence_type: str, category_id: str, evidence_basis: str) -> ResidenceShare:
    return ResidenceShare(residence_type, category_id, evidence_basis)


def _calibration(
    haus_id: str,
    category_id: str,
    rationale: str,
    *,
    default_residence_type: str = "GENERAL_SITE_RESIDENT",
    overrides: tuple[ResidenceShare, ...] = (),
) -> DemographicCalibration:
    return DemographicCalibration(
        haus_id=haus_id,
        default_residence_type=default_residence_type,
        base_share=_share(default_residence_type, category_id, rationale),
        residence_overrides=overrides,
        fixed_bonded_count=None,
        fixed_count_scope=None,
        fixed_count_qualifier=None,
        exact_counts_by_residence=(),
        rationale=rationale,
    )


# The categories are intentionally broad.  Their function is to make a first
# complete working run possible while retaining enough overlap and uncertainty
# for later replacement.  They are qualitative readings of the linked primary
# Haus/species evidence, not demographic canon.
DEMOGRAPHIC_CALIBRATIONS: dict[str, DemographicCalibration] = {
    "BUCHHAIN": _calibration(
        "BUCHHAIN", "SUBSTANTIAL_MINORITY",
        "The Haus includes ordinary families and workers alongside a bond-shaped archive and rookery culture.",
        overrides=(
            _share("ARCHIVE_EDUCATION_OR_CRAFT_SETTLEMENT", "NEAR_PARITY", "Archive and rookery institutions concentrate bonded specialists."),
        ),
    ),
    "DUFTFAEHRTE": _calibration(
        "DUFTFAEHRTE", "BONDED_MAJORITY",
        "The mobile civilisation contains multiple caravans organised around Shimmerhound bonders, while Tiyofaehrten also contain relatives, dependants and affiliated families.",
        default_residence_type="MOBILE_CARAVAN_POOL",
        overrides=(
            _share("SPECIALIST_SANCTUARY_HOST", "SUBSTANTIAL_MINORITY", "Fixed sanctuaries include carers and non-bondable animals and are not copies of the moving court."),
        ),
    ),
    "DUNKELHAUCH": DemographicCalibration(
        haus_id="DUNKELHAUCH",
        default_residence_type="BLACKFLOOD_HEART_SYSTEM",
        base_share=None,
        residence_overrides=(),
        fixed_bonded_count=50,
        fixed_count_scope="HAUS_WIDE_ACTIVE_INFRASTRUCTURE_SYSTEM",
        fixed_count_qualifier="APPROXIMATELY_FIFTY_USER_APPROVED_WORKING_INPUT",
        exact_counts_by_residence=(),
        rationale="Approximately fifty bonded humans total, no ordinary population and no active population at former wartime fortifications.",
    ),
    "EDELSTEIN": _calibration(
        "EDELSTEIN", "SUBSTANTIAL_MINORITY",
        "Crownjaw bonding is politically and economically important but ordinary extraction, craft and trade settlements remain extensive.",
        overrides=(
            _share("SPECIES_SPECIFIC_OR_BONDED_SETTLEMENT", "BONDED_MAJORITY", "A species-specific settlement concentrates bonded households."),
        ),
    ),
    "EISENWEB": _calibration(
        "EISENWEB", "NEAR_PARITY",
        "Web, industrial and Thought-Web institutions make bonded participation common while ordinary labour and settlement remain substantial.",
        overrides=(
            _share("EXTRACTION_PROCESSING_OR_INDUSTRIAL_SETTLEMENT", "BONDED_MAJORITY", "Web-linked industrial sites preferentially concentrate Ferrarachne bonders."),
        ),
    ),
    "EREMITENSCHALE": _calibration(
        "EREMITENSCHALE", "SUBSTANTIAL_MINORITY",
        "The founder-shell and snail bond shape the Haus, but its very large agrarian network requires extensive ordinary households.",
        overrides=(
            _share("AGRARIAN_SETTLEMENT", "LIMITED_MINORITY", "Breadbasket villages contain many ordinary agricultural households."),
            _share("SPECIES_SPECIFIC_OR_BONDED_SETTLEMENT", "BONDED_MAJORITY", "Snail-specific sites concentrate bonded people."),
        ),
    ),
    "FEUERSCHUPPE": _calibration(
        "FEUERSCHUPPE", "RARE_SPECIALIST",
        "Dragon bonds are powerful, spatially demanding and elite relative to the broad ordinary settlement network.",
        overrides=(
            _share("CANOPY_TREE_OR_EYRIE_SETTLEMENT", "SUBSTANTIAL_MINORITY", "Eyrie settlements concentrate the uncommon dragon-bonded population."),
        ),
    ),
    "FROSTGLANZ": _calibration(
        "FROSTGLANZ", "SUBSTANTIAL_MINORITY",
        "Frosthirsch bonds shape court and movement but the retained ordinary rural network remains much larger.",
        overrides=(
            _share("PASTORAL_SETTLEMENT", "NEAR_PARITY", "Pastoral and herd-facing sites concentrate Frosthirsch bonders."),
        ),
    ),
    "GLANZGRUND": _calibration(
        "GLANZGRUND", "LIMITED_MINORITY",
        "Ordinary humans are limited to surface, dry or breathable districts; bond-specialist populations concentrate nearer native aquatic infrastructure.",
        overrides=(
            _share("SURFACE_FACING_SHAFT_OR_AIR_CAVERN_SETTLEMENT", "SUBSTANTIAL_MINORITY", "Breathable transition districts support a larger bonded interface population."),
            _share("FULLY_SUBMERGED_NATIVE_SPECIALIST_SETTLEMENT", "BONDED_EXCLUSIVE", "Ordinary humans are excluded from submerged communities; any possible human occupancy is bonded-specialist only and capacity remains 3D-incomplete."),
        ),
    ),
    "LAUBRAUNEN": _calibration(
        "LAUBRAUNEN", "BONDED_MAJORITY",
        "Humans may reside only inside existing native forest enclaves, so those pools are bond-selected rather than general towns.",
        default_residence_type="EMBEDDED_NATIVE_ENCLAVE",
        overrides=(
            _share("FOREST_EDGE_SETTLEMENT", "NEAR_PARITY", "Forest-edge hosts can support a larger ordinary embedded minority than deep canopy sites."),
            _share("CANOPY_TREE_OR_EYRIE_SETTLEMENT", "BONDED_DOMINANT", "Deep canopy/flet residence is especially bond-selected."),
        ),
    ),
    "MARIENHAIN": _calibration(
        "MARIENHAIN", "NEAR_PARITY",
        "Hive organisation and one-to-one non-drone bonds make bonded households common, while orchard, agricultural and export labour also sustains many ordinary residents.",
        overrides=(
            _share("HIVE_SETTLEMENT", "BONDED_MAJORITY", "Hives concentrate bonded human-Marienbiene pairs."),
            _share("HORTICULTURAL_OR_ORCHARD_SETTLEMENT", "SUBSTANTIAL_MINORITY", "Orchard settlements include extensive ordinary agricultural labour."),
        ),
    ),
    "MOORWANDLER": _calibration(
        "MOORWANDLER", "LIMITED_MINORITY",
        "Ordinary humans may settle suitable inter-river land; bonded Moorwandler strongly concentrate in stilt villages.",
        overrides=(
            _share("WETLAND_STILT_OR_CHANNEL_SETTLEMENT", "BONDED_MAJORITY", "Bonded Moorwandler are strongly concentrated in stilt/channel villages."),
            _share("GENERAL_SETTLEMENT", "RARE_SPECIALIST", "General inter-river settlements are chiefly ordinary and unbonded."),
        ),
    ),
    "NACHTFLUESTERN": _calibration(
        "NACHTFLUESTERN", "SUBSTANTIAL_MINORITY",
        "Bonding strongly shapes sleep and care institutions, but ordinary valley, orchard, road and spring communities are explicitly permitted.",
        overrides=(
            _share("MEDICAL_CARE_OR_SANCTUARY_SETTLEMENT", "NEAR_PARITY", "Sleep-care and sanctuary institutions concentrate bonders."),
        ),
    ),
    "SEELENWACHT": DemographicCalibration(
        haus_id="SEELENWACHT",
        default_residence_type="LIVING_CONGREGATION_SITE",
        base_share=None,
        residence_overrides=(),
        fixed_bonded_count=0,
        fixed_count_scope="EVERY_PRIMARY_SPECIES_HUMAN_POOL",
        fixed_count_qualifier="EXACT_PRIMARY_SPECIES_NO_BOND",
        exact_counts_by_residence=(),
        rationale="The Kept do not bond with living humans; Bannerhaus bonds are outside the primary-species calibration.",
    ),
    "SERENAKRONE": _calibration(
        "SERENAKRONE", "NEAR_PARITY",
        "Surface lagoon communities are built around close human-species and coral-foundation interaction without making all residents bonded.",
        default_residence_type="SURFACE_LAGOON_SETTLEMENT",
        overrides=(
            _share("FISHERY_OR_LAKESHORE_SETTLEMENT", "SUBSTANTIAL_MINORITY", "Mixed fishery communities support a larger ordinary population."),
        ),
    ),
    "STILLKLINGE": _calibration(
        "STILLKLINGE", "LIMITED_MINORITY",
        "The broad surface network admits ordinary humans, while cavern/roost communities concentrate Fogbat bonders.",
        overrides=(
            _share("SUBMERGED_OR_CAVERN_SETTLEMENT", "BONDED_MAJORITY", "Cavern and roost sites are strongly bond-selected; exact capacity remains 3D-incomplete."),
            _share("SURFACE_FACING_SHAFT_OR_AIR_CAVERN_SETTLEMENT", "NEAR_PARITY", "Air-cavern interfaces support both bonded specialists and ordinary infrastructure workers."),
        ),
    ),
    "STURMGLAS": _calibration(
        "STURMGLAS", "SUBSTANTIAL_MINORITY",
        "The city explicitly contains unbonded families and workers, while storm infrastructure makes bonded specialists common.",
        overrides=(
            _share("AEROHAMLET", "BONDED_MAJORITY", "Every Aerohamlet requires at least one bonded Sturmmeduse guardian and has qualification-selected crews."),
            _share("CIVIC_ADMINISTRATIVE_SETTLEMENT", "NEAR_PARITY", "The compact Peak concentrates bonded civic and technical specialists."),
        ),
    ),
    "VERFUEHRSCHLUND": DemographicCalibration(
        haus_id="VERFUEHRSCHLUND",
        default_residence_type="FOREST_FLOOR_CROWN_ENCLAVE_SETTLEMENT",
        base_share=None,
        residence_overrides=(),
        fixed_bonded_count=None,
        fixed_count_scope=None,
        fixed_count_qualifier=None,
        exact_counts_by_residence=(
            ("FOREST_FLOOR_CROWN_ENCLAVE_SETTLEMENT", 1),
            ("MOTHERS_MOUTH_CROWN_ENCLAVE", 1),
            ("EMBEDDED_NATIVE_ENCLAVE", 1),
        ),
        rationale="Each recognised crown enclave has exactly one active bonded Maw-Mother; enclave totals await Rootreach deduplication.",
    ),
    "WIEDERGEBORENE_FLAMME": _calibration(
        "WIEDERGEBORENE_FLAMME", "SUBSTANTIAL_MINORITY",
        "Phoenix bonds are central to medicine and sovereignty but ordinary clinicians, farmers, port workers and civic residents remain extensive.",
        overrides=(
            _share("MEDICAL_CARE_OR_SANCTUARY_SETTLEMENT", "BONDED_MAJORITY", "Major hospitals concentrate Phoenix bonders without making all clinical staff bonded."),
            _share("CATHEDRAL_OR_CUSTODIAL_SETTLEMENT", "NEAR_PARITY", "Rookery and Crown medical contexts concentrate bonded pairs."),
        ),
    ),
    "ZWIELICHT": _calibration(
        "ZWIELICHT", "NEAR_PARITY",
        "Paired-aspect political and aerial culture supports a large bonded population alongside a substantial ordinary settlement network.",
        overrides=(
            _share("CANOPY_TREE_OR_EYRIE_SETTLEMENT", "BONDED_MAJORITY", "Aerial and eyrie contexts concentrate Twinwing bonders."),
        ),
    ),
}


def calibration_for_haus(haus_id: str) -> DemographicCalibration:
    key = str(haus_id).upper()
    try:
        return DEMOGRAPHIC_CALIBRATIONS[key]
    except KeyError as exc:
        raise KeyError(f"no Stage 6D demographic calibration for Haus {haus_id!r}") from exc


def residence_share(haus_id: str, residence_type: str | None = None) -> ResidenceShare | None:
    calibration = calibration_for_haus(haus_id)
    resolved_type = residence_type or calibration.default_residence_type
    for override in calibration.residence_overrides:
        if override.residence_type == resolved_type:
            return override
    return calibration.base_share


def split_human_total(
    haus_id: str,
    human_total: int,
    residence_type: str | None = None,
) -> HumanSplit:
    """Split one already-calculated total without changing it.

    Inferred shares use deterministic half-up rounding.  Exact relationship
    rules and fixed totals take precedence over coefficients.
    """

    if isinstance(human_total, bool) or int(human_total) != human_total or human_total < 0:
        raise ValueError("human_total must be a non-negative integer")
    human_total = int(human_total)
    calibration = calibration_for_haus(haus_id)
    resolved_type = residence_type or calibration.default_residence_type

    exact_by_residence = dict(calibration.exact_counts_by_residence)
    if resolved_type in exact_by_residence:
        bonded = exact_by_residence[resolved_type]
        if bonded > human_total:
            raise ValueError(
                f"{calibration.haus_id} {resolved_type}: exact bonded count {bonded} exceeds human total {human_total}"
            )
        return HumanSplit(
            calibration.haus_id,
            resolved_type,
            human_total,
            human_total - bonded,
            bonded,
            None,
            EXACT_RELATIONSHIP,
            calibration.rationale,
        )

    if calibration.fixed_bonded_count is not None:
        bonded = calibration.fixed_bonded_count
        if calibration.haus_id == "DUNKELHAUCH" and human_total != bonded:
            raise ValueError(
                "DUNKELHAUCH active human total must remain the approved approximately-fifty bonded pool"
            )
        if bonded > human_total:
            raise ValueError(
                f"{calibration.haus_id}: fixed bonded count {bonded} exceeds human total {human_total}"
            )
        return HumanSplit(
            calibration.haus_id,
            resolved_type,
            human_total,
            human_total - bonded,
            bonded,
            None,
            FIXED_WORKING_INPUT if calibration.haus_id == "DUNKELHAUCH" else EXACT_RELATIONSHIP,
            calibration.rationale,
        )

    share = residence_share(calibration.haus_id, resolved_type)
    if share is None:
        raise ValueError(f"{calibration.haus_id} {resolved_type}: no share or exact relationship")
    bonded = int(math.floor(human_total * share.coefficient + 0.5))
    bonded = min(human_total, max(0, bonded))
    return HumanSplit(
        calibration.haus_id,
        resolved_type,
        human_total,
        human_total - bonded,
        bonded,
        share.coefficient,
        INFERRED_STATUS,
        share.evidence_basis,
    )


def calibration_fingerprint() -> str:
    return hashlib.sha256(
        canonical_json(
            {key: DEMOGRAPHIC_CALIBRATIONS[key].as_dict() for key in sorted(DEMOGRAPHIC_CALIBRATIONS)}
        ).encode("utf-8")
    ).hexdigest()


def validate_calibrations() -> list[str]:
    failures: list[str] = []
    keys = frozenset(DEMOGRAPHIC_CALIBRATIONS)
    if keys != EXPECTED_HAUS_IDS:
        failures.append(
            f"Haus coverage mismatch missing={sorted(EXPECTED_HAUS_IDS - keys)} extra={sorted(keys - EXPECTED_HAUS_IDS)}"
        )
    for key in sorted(DEMOGRAPHIC_CALIBRATIONS):
        calibration = DEMOGRAPHIC_CALIBRATIONS[key]
        if calibration.haus_id != key:
            failures.append(f"{key}: haus_id mismatch")
        for share in ((calibration.base_share,) if calibration.base_share else ()) + calibration.residence_overrides:
            if share.status != INFERRED_STATUS:
                failures.append(f"{key} {share.residence_type}: inferred coefficient not assumption dominated")
            if share.category_id not in SHARE_CATEGORIES:
                failures.append(f"{key} {share.residence_type}: unknown category")
        if key == "DUNKELHAUCH" and calibration.fixed_bonded_count != 50:
            failures.append("DUNKELHAUCH: approved approximately-fifty bonded total not preserved")
        if key == "SEELENWACHT" and calibration.fixed_bonded_count != 0:
            failures.append("SEELENWACHT: primary-species bonded zero not preserved")
        if key not in {"DUNKELHAUCH", "SEELENWACHT"} and calibration.fixed_bonded_count is not None:
            failures.append(f"{key}: unsupported fixed Haus-wide bonded census")
    return failures


def self_check() -> dict[str, Any]:
    failures = validate_calibrations()
    return {
        "status": "PASS" if not failures else "FAIL",
        "method_version": METHOD_VERSION,
        "haus_count": len(DEMOGRAPHIC_CALIBRATIONS),
        "share_category_count": len(SHARE_CATEGORIES),
        "calibration_fingerprint": calibration_fingerprint(),
        "invariant": "human_total = ordinary_unbonded + bonded",
        "failures": failures,
    }


if __name__ == "__main__":
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))
