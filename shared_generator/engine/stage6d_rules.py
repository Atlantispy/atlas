#!/usr/bin/env python3
"""Transparent reference rules for the Stage 6D working population pass.

The rules deliberately produce review candidates, not demographic canon.  They
turn Stage 6B functional roles and Stage 6C/6C.5 physical summaries into broad
population and food-support priors without reopening the terrain rasters.  The
reference implementation stays small and auditable so later compiled or
accelerated implementations can be checked against it exactly.

Functional tier is only a centrality prior.  It is never treated as proof of a
particular population.  Settlement form, physical support, access, evidence
quality, local provisioning and conserved trade all remain separate factors.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from stage6d_schema import SCENARIO_PARAMETERS


METHOD_VERSION = "STAGE6D_REFERENCE_RULES_V2"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


@dataclass(frozen=True)
class TierPrior:
    central_population: int
    low_factor: float
    high_factor: float
    import_priority: float


@dataclass(frozen=True)
class FormPolicy:
    population_factor: float
    local_food_ratio: float
    storage_factor: float
    notes: str


@dataclass(frozen=True)
class HausPolicy:
    bonded_human_fraction: float
    human_residence_factor: float
    food_production_factor: float
    export_reserve_factor: float
    export_role: str
    notes: str
    food_support_class: str = "MIXED_OR_UNRESOLVED"
    import_priority_factor: float = 1.0
    within_network_redistribution_allowed: bool = True
    gross_food_product_trade_status: str = "POSSIBLE_NOT_QUANTIFIED"
    food_policy_evidence_status: str = "FOUND"
    source_pointers: tuple[str, ...] = ()


# These are deliberately wide candidate priors.  They place the 30,097-site
# registry on a coherent numerical scale while preserving substantial overlap
# between adjacent functional tiers.  Tier remains a service-role prior rather
# than a population classification.
TIER_PRIORS: dict[str, TierPrior] = {
    "FT0_HAUS_PRINCIPAL_SITE": TierPrior(45_000, 0.35, 2.60, 1.55),
    "FT1_MAJOR_REGIONAL_HUB": TierPrior(14_000, 0.32, 2.50, 1.40),
    "FT2_SUBREGIONAL_OR_SPECIALIST_CENTRE": TierPrior(3_200, 0.30, 2.60, 1.22),
    "FT3_LOCAL_CENTRE": TierPrior(820, 0.27, 2.75, 1.08),
    "FT4_MINOR_LOCAL_SITE": TierPrior(175, 0.22, 3.00, 0.92),
    "FTU_CONDITIONAL_FIELD_SITE": TierPrior(80, 0.00, 4.00, 0.75),
    "FTU_PERMANENCE_UNRESOLVED": TierPrior(120, 0.00, 5.00, 0.70),
}


def _form(
    population_factor: float,
    local_food_ratio: float,
    storage_factor: float,
    notes: str,
) -> FormPolicy:
    return FormPolicy(population_factor, local_food_ratio, storage_factor, notes)


# local_food_ratio is an annual human-equivalent support ratio relative to the
# form-adjusted central population prior.  It is a calibration assumption, not
# a crop-yield claim.  The legacy resource surfaces can move it by at most 15%.
FORM_POLICIES: dict[str, FormPolicy] = {
    "AGRARIAN_SETTLEMENT": _form(0.82, 1.55, 1.15, "Crop-producing rural cluster."),
    "ARCHIVE_EDUCATION_OR_CRAFT_SETTLEMENT": _form(1.05, 0.42, 1.12, "Institutional and craft concentration."),
    "CANOPY_TREE_OR_EYRIE_SETTLEMENT": _form(0.78, 0.88, 1.04, "Vertically distributed native enclave."),
    "CATHEDRAL_OR_CUSTODIAL_SETTLEMENT": _form(0.95, 0.38, 1.12, "Institutional custodial centre."),
    "CIVIC_ADMINISTRATIVE_SETTLEMENT": _form(1.45, 0.35, 1.18, "Dense service and administrative centre."),
    "CONDITIONAL_FIELD_SITE": _form(0.45, 0.75, 0.82, "Conditional rather than proven permanent population."),
    "EXTRACTION_PROCESSING_OR_INDUSTRIAL_SETTLEMENT": _form(0.88, 0.46, 1.10, "Industrial population with import dependence."),
    "FISHERY_OR_LAKESHORE_SETTLEMENT": _form(0.76, 1.28, 1.05, "Aquatic-food producing settlement."),
    "FOREST_EDGE_SETTLEMENT": _form(0.72, 1.02, 1.03, "Mixed forest-edge provisioning."),
    "FOREST_FLOOR_CROWN_ENCLAVE_SETTLEMENT": _form(0.66, 0.92, 1.03, "Forest enclave without a separate human town lattice."),
    "FREIGHT_TRANSFER_OR_LANDING_SETTLEMENT": _form(1.18, 0.38, 1.20, "Transfer node expected to import food."),
    "FULLY_SUBMERGED_NATIVE_SPECIALIST_SETTLEMENT": _form(0.70, 0.78, 1.03, "Specialist 3D capacity withheld until evidence exists."),
    "GENERAL_SETTLEMENT": _form(1.00, 0.82, 1.05, "Unspecialised mixed settlement."),
    "GENERAL_SETTLEMENT_FORM_REQUIRES_NON_CAPITAL_ROLE_REVIEW": _form(0.70, 0.72, 0.95, "Role unresolved; conservative population factor."),
    "HIVE_SETTLEMENT": _form(1.28, 1.45, 1.22, "Dense hive settlement with storage and agricultural integration."),
    "HORTICULTURAL_OR_ORCHARD_SETTLEMENT": _form(0.76, 1.40, 1.16, "Horticultural and orchard producer."),
    "MARKET_EXCHANGE_SETTLEMENT": _form(1.25, 0.48, 1.18, "Market concentration with imported provisioning."),
    "MEDICAL_CARE_OR_SANCTUARY_SETTLEMENT": _form(0.92, 0.34, 1.17, "Care and sanctuary centre with institutional demand."),
    "MIXED_RURAL_SETTLEMENT": _form(0.82, 1.18, 1.08, "Mixed rural producer."),
    "PASTORAL_SETTLEMENT": _form(0.68, 1.30, 1.08, "Pastoral producer with lower settlement density."),
    "RIVER_TERRACE_OR_WATERSIDE_SETTLEMENT": _form(0.92, 1.05, 1.08, "Waterside mixed producer and exchange site."),
    "ROUTE_CROSSING_OR_PASS_SETTLEMENT": _form(1.08, 0.55, 1.12, "Route service centre with partial import dependence."),
    "SHELTERED_VALLEY_SETTLEMENT": _form(0.84, 0.98, 1.08, "Valley mixed settlement."),
    "SPECIES_SPECIFIC_OR_BONDED_SETTLEMENT": _form(0.72, 0.88, 1.04, "Population composition follows species and Haus rules."),
    "SUBMERGED_OR_CAVERN_SETTLEMENT": _form(0.68, 0.72, 1.04, "Specialist 3D capacity withheld until evidence exists."),
    "SURFACE_FACING_SHAFT_OR_AIR_CAVERN_SETTLEMENT": _form(0.78, 0.62, 1.07, "Breathable cavern district with import dependence."),
    "SURFACE_LAGOON_SETTLEMENT": _form(0.90, 1.02, 1.07, "Surface-built lagoon community."),
    "WETLAND_EDGE_SETTLEMENT": _form(0.80, 1.08, 1.05, "Wetland-edge mixed producer."),
    "WETLAND_STILT_OR_CHANNEL_SETTLEMENT": _form(0.88, 1.12, 1.08, "Stilt or channel community with aquatic provisioning."),
    "WORK_SITE_PERMANENCE_UNRESOLVED": _form(0.38, 0.55, 0.80, "Permanence unresolved; estimate remains assumption-dominated."),
}


DEFAULT_HAUS_POLICY = HausPolicy(
    bonded_human_fraction=0.40,
    human_residence_factor=1.00,
    food_production_factor=1.00,
    export_reserve_factor=1.15,
    export_role="ORDINARY_NETWORK",
    notes="Generic working proposal pending a more specific canon rule.",
    food_policy_evidence_status="INCOMPLETE",
)


# These support policies are qualitative canon constraints paired with modest
# working calibration coefficients.  The source material establishes
# directions (breadbasket, mixed, import-dependent, or non-applicable), not
# exact yields.  Products, prices, tonnages and freight remain outside Stage 6D.
HAUS_POLICIES: dict[str, HausPolicy] = {
    "BUCHHAIN": HausPolicy(0.40, 1.00, 1.00, 1.15, "ORDINARY_NETWORK", "Substantial local staples with settlement-specific meat and fish support.", "SUBSTANTIAL_LOCAL_STAPLES_MIXED_IMPORTS", 1.00, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Ink Owl\Haus von Buchhain.docx#8. Economy, Subsistence and Material Culture",)),
    "DUFTFAEHRTE": HausPolicy(0.90, 0.00, 0.00, 1.00, "MOBILE_SHARED", "Multiple caravans use grain, gathering, hunting and trade; their numeric ledger is unresolved.", "MOBILE_MIXED_PROVISIONING_UNQUANTIFIED", 1.05, False, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Shimmerhound\Haus von Duftfährte.docx#8. Economy, Subsistence and Material Culture",)),
    "DUNKELHAUCH": HausPolicy(1.00, 0.00, 0.00, 1.00, "NO_ROUTINE_FOOD_NETWORK", "Approximately fifty bonded humans require no routine human food ledger.", "NO_ROUTINE_HUMAN_FOOD_NETWORK", 0.00, False, "NOT_APPLICABLE", "FOUND", (r"Blackflood\Haus von Dunkelhauch.docx#8. Economy, Subsistence and Material Culture",)),
    "EDELSTEIN": HausPolicy(0.40, 1.00, 0.90, 1.20, "ORDINARY_NETWORK", "Explicitly not agriculturally self-sufficient; terraces and fisheries supplement imported staples.", "EXPLICITLY_NOT_SELF_SUFFICIENT", 1.20, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Crownjaw\Haus vom Edelstein.docx#8. Economy, Subsistence and Material Culture",)),
    "EISENWEB": HausPolicy(0.40, 1.00, 0.85, 1.25, "ORDINARY_NETWORK", "The Peak is heavily dependent on imported food despite local crops, fungi and protected stores.", "HEAVILY_IMPORT_DEPENDENT", 1.25, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Ferrarachne\Haus von Eisenweb.docx#8. Economy, Subsistence and Material Culture",)),
    "EREMITENSCHALE": HausPolicy(0.40, 1.00, 1.50, 1.25, "PRINCIPAL_BREADBASKET_EXPORTER", "Principal breadbasket; resident demand and bounded reserves precede external support.", "PRINCIPAL_BREADBASKET", 0.85, True, "FOUND", "FOUND", (r"Hermit Snails\Haus von Eremitenschale.docx#8. Economy, Subsistence and Material Culture",)),
    "FEUERSCHUPPE": HausPolicy(0.40, 1.00, 1.10, 1.20, "SPECIALISED_LIVESTOCK_FOOD_EXPORTER", "Cattle-state lowlands provide pastoral and agrarian support and explicit meat exports, with major dragon demand.", "SPECIALISED_LIVESTOCK_PRODUCER", 0.95, True, "FOUND", "FOUND", (r"Dragon\Haus von Feuerschuppe.docx#8. Economy, Subsistence and Material Culture",)),
    "FROSTGLANZ": HausPolicy(0.40, 1.00, 0.90, 1.25, "ORDINARY_NETWORK", "Limited highland production is backed by cold storage and strategically important food imports.", "LIMITED_HIGHLAND_PRODUCTION_IMPORT_DEPENDENT", 1.20, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Frost Elk\Haus vom Frostglanz.docx#8. Economy, Subsistence and Material Culture",)),
    "GLANZGRUND": HausPolicy(0.45, 1.00, 0.95, 1.20, "ORDINARY_NETWORK", "Aquatic and cavern production supplements strategically important imported staples.", "MIXED_AQUATIC_IMPORT_DEPENDENT", 1.15, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Chromakraken\Haus von Glanzgrund.docx#8. Economy, Subsistence and Material Culture",)),
    "LAUBRAUNEN": HausPolicy(0.75, 1.00, 1.00, 1.20, "NATIVE_ENCLAVES_ONLY", "Forest foods are the ordinary calorie base; imported grain is a strategic reserve.", "FOREST_PROVISIONED_STRATEGIC_IMPORTS", 1.05, True, "FOUND", "FOUND", (r"Canopy Whipsnake\Haus von Laubraunen.docx#8. Economy, Subsistence and Material Culture",)),
    "MARIENHAIN": HausPolicy(0.45, 1.00, 1.65, 1.30, "PRINCIPAL_BREADBASKET_EXPORTER", "Diversified abundance and extensive agricultural exports make Marienhain a principal breadbasket.", "PRINCIPAL_BREADBASKET", 0.80, True, "FOUND", "FOUND", (r"Ladybee\Haus von Marienhain.docx#8. Economy, Subsistence and Material Culture",)),
    "MOORWANDLER": HausPolicy(0.55, 1.00, 1.00, 1.20, "ORDINARY_AND_STILT_NETWORK", "Fisheries, fungi and wetland livestock coexist with structurally important grain imports.", "MIXED_WETLAND_IMPORT_DEPENDENT", 1.20, True, "FOUND", "FOUND", (r"Bog Colossus\Haus der Moorwandler.docx#8. Economy, Subsistence and Material Culture",)),
    "NACHTFLUESTERN": HausPolicy(0.40, 1.00, 1.00, 1.20, "ORDINARY_NETWORK", "Orchards and lower fields support the Haus while imported staples cover unresolved shortfalls.", "HORTICULTURAL_MIXED_IMPORT_DEPENDENT", 1.15, True, "FOUND", "FOUND", (r"Nightwhisperer\Haus von Nachtflüstern.docx#8. Economy, Subsistence and Material Culture",)),
    "SEELENWACHT": HausPolicy(0.00, 1.00, 1.00, 1.15, "ORDINARY_NETWORK", "Only the living Congregation has ordinary food demand; the Cathedral is principally a Kept settlement.", "LIVING_CONGREGATION_SITE_SPECIFIC", 1.00, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"The Kept\Haus von Seelenwacht.docx#8. Economy, Subsistence and Material Culture",)),
    "SERENAKRONE": HausPolicy(0.45, 1.00, 0.95, 1.20, "SURFACE_LAGOON_NETWORK", "Fisheries, molluscs, valleys and terraces coexist with ordinary imported grain.", "MIXED_IMPORT_DEPENDENT_LAGOON", 1.15, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Serenafacher\Haus von Serenakrone.docx#13. Economy and Subsistence",)),
    "STILLKLINGE": HausPolicy(0.40, 1.00, 0.85, 1.25, "ORDINARY_NETWORK", "Explicitly not agriculturally self-sufficient; cave and valley foods supplement imports.", "NOT_SELF_SUFFICIENT_IMPORT_DEPENDENT", 1.25, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Fogbat\Haus von Stillklinge.docx#8. Economy, Subsistence and Material Culture",)),
    "STURMGLAS": HausPolicy(0.40, 1.00, 0.95, 1.20, "ORDINARY_NETWORK", "Lower farms and enclosed gardens provide fresh food while bulk staples are imported.", "MIXED_IMPORT_DEPENDENT_VERTICAL_CAPITAL", 1.15, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Aerojelly\Haus von Sturmglas.docx#8. Economy, Subsistence and Material Culture",)),
    "VERFUEHRSCHLUND": HausPolicy(0.75, 1.00, 1.00, 1.20, "NATIVE_ENCLAVES_ONLY", "Animal foods, fungi and imports support embedded enclaves; no plant food crops are cultivated.", "MIXED_ANIMAL_FUNGI_IMPORT_DEPENDENT", 1.10, True, "POSSIBLE_NOT_QUANTIFIED", "FOUND", (r"Venus Rafflesia\Haus des Verführschlunds.docx#8. Economy, Subsistence and Material Culture",)),
    "WIEDERGEBORENE_FLAMME": HausPolicy(0.40, 1.00, 1.00, 1.25, "ORDINARY_NETWORK", "Productive valleys, orchards and fisheries coexist with food imports and large institutional demand.", "MIXED_PRODUCTIVE_VALLEYS_WITH_IMPORTS", 1.10, True, "FOUND", "FOUND", (r"Phoenix\Haus der Wiedergeborenen Flamme.docx#8. Economy, Subsistence and Material Culture",)),
    "ZWIELICHT": HausPolicy(0.40, 1.00, 1.00, 1.20, "ORDINARY_NETWORK", "The balance between local staples and imported grain remains explicitly unresolved.", "SUBSISTENCE_BALANCE_INCOMPLETE", 1.10, True, "POSSIBLE_NOT_QUANTIFIED", "INCOMPLETE", (r"Twinwing\Haus von Zwielicht.docx#8. Economy, Subsistence and Material Culture",)),
}

FOOD_PRODUCER_FORMS = frozenset({
    "AGRARIAN_SETTLEMENT",
    "FISHERY_OR_LAKESHORE_SETTLEMENT",
    "FOREST_EDGE_SETTLEMENT",
    "HIVE_SETTLEMENT",
    "HORTICULTURAL_OR_ORCHARD_SETTLEMENT",
    "MIXED_RURAL_SETTLEMENT",
    "PASTORAL_SETTLEMENT",
    "RIVER_TERRACE_OR_WATERSIDE_SETTLEMENT",
    "SHELTERED_VALLEY_SETTLEMENT",
    "SURFACE_LAGOON_SETTLEMENT",
    "WETLAND_EDGE_SETTLEMENT",
    "WETLAND_STILT_OR_CHANNEL_SETTLEMENT",
})


SPECIALIST_3D_ANALYSIS_STATUS = "DEFERRED_SPECIALIST_3D"


def policy_for_haus(haus_id: str | None) -> HausPolicy:
    return HAUS_POLICIES.get(str(haus_id or "").upper(), DEFAULT_HAUS_POLICY)


def policy_for_form(form: str | None) -> FormPolicy:
    key = str(form or "GENERAL_SETTLEMENT")
    return FORM_POLICIES.get(key, FORM_POLICIES["GENERAL_SETTLEMENT"])


def _value(site: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = site.get(name)
        if value is not None:
            return float(value)
    return None


def effective_capacity_score(site: Mapping[str, Any]) -> float:
    value = _value(site, "capacity_support_score_10m", "capacity_support_score_100m")
    return clamp(0.50 if value is None else value, 0.0, 1.0)


def effective_access_score(site: Mapping[str, Any]) -> float:
    value = _value(site, "access_support_score_10m", "access_support_score_100m")
    return clamp(0.50 if value is None else value, 0.0, 1.0)


def effective_confidence(site: Mapping[str, Any]) -> float:
    value = _value(site, "evidence_confidence_score_10m", "evidence_confidence_score_100m")
    return clamp(0.50 if value is None else value, 0.05, 1.0)


def human_residence_factor(site: Mapping[str, Any]) -> float:
    haus = policy_for_haus(site.get("owner_haus_id"))
    if haus.human_residence_factor <= 0:
        return 0.0
    domain = str(site.get("effective_vertical_domain") or "")
    form = str(site.get("realised_settlement_form") or "")
    owner = str(site.get("owner_haus_id") or "").upper()
    if owner == "GLANZGRUND" and (
        domain in {"FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN", "SUBMERGED_OR_FLOODED_CAVERN"}
        or form == "FULLY_SUBMERGED_NATIVE_SPECIALIST_SETTLEMENT"
    ):
        return 0.0
    ordinary_allowed = site.get("ordinary_permanent_human_allowed")
    if ordinary_allowed in (0, False):
        if owner in {"LAUBRAUNEN", "VERFUEHRSCHLUND"}:
            return haus.human_residence_factor
        if owner == "MOORWANDLER":
            return haus.human_residence_factor
        # This flag controls whether a separate ordinary-human settlement
        # exists.  It is not a percentage multiplier for all human residents;
        # the builder decides whether the site receives an embedded/bonded pool.
        return haus.human_residence_factor
    return haus.human_residence_factor


def population_round(value: float) -> int:
    value = max(0.0, float(value))
    if value < 100:
        quantum = 1
    elif value < 1_000:
        quantum = 5
    elif value < 10_000:
        quantum = 25
    elif value < 100_000:
        quantum = 100
    else:
        quantum = 500
    return int(round(value / quantum) * quantum)


def structural_human_population_band(
    site: Mapping[str, Any],
    *,
    food_resource_index: float = 1.0,
) -> tuple[int | None, int | None, int | None, dict[str, Any]]:
    """Return a broad human population prior before food-trade constraints.

    ``food_resource_index`` is a dimensionless relative covariate centred on
    one and clamped to ±15%.  It must never be interpreted as a calibrated
    agricultural yield.
    """

    if str(site.get("stage6c_analysis_status")) == SPECIALIST_3D_ANALYSIS_STATUS:
        return None, None, None, {
            "status": "INCOMPLETE",
            "limiting_factor": "CAPACITY_WITHHELD_3D",
            "reason": "Surface context cannot fabricate specialist three-dimensional capacity.",
        }
    tier_key = str(site.get("functional_tier") or "")
    tier = TIER_PRIORS.get(tier_key)
    if tier is None:
        return None, None, None, {
            "status": "INCOMPLETE",
            "limiting_factor": "FUNCTIONAL_TIER_UNMAPPED",
            "reason": tier_key,
        }
    residence_factor = human_residence_factor(site)
    if residence_factor <= 0:
        return 0, 0, 0, {
            "status": "PROVEN_ABSENT",
            "limiting_factor": "HAUS_OR_DOMAIN_HUMAN_RESIDENCE_GATE",
        }

    form = policy_for_form(site.get("realised_settlement_form"))
    capacity = effective_capacity_score(site)
    access = effective_access_score(site)
    confidence = effective_confidence(site)
    # The wide but monotone ranges let unusually strong physical/access
    # evidence overturn an adjacent functional-tier prior.  At median support
    # they preserve the former calibration scale.
    physical_factor = 0.40 + 0.85 * capacity
    access_factor = 0.65 + 0.55 * access
    resource_factor = clamp(food_resource_index, 0.85, 1.15)
    central = (
        tier.central_population
        * form.population_factor
        * residence_factor
        * physical_factor
        * access_factor
        * resource_factor
    )
    uncertainty_expansion = 1.0 + (1.0 - confidence) * 0.85
    low = central * tier.low_factor / uncertainty_expansion
    high = central * tier.high_factor * uncertainty_expansion
    result = (
        population_round(low),
        population_round(central),
        population_round(high),
    )
    explanation = {
        "status": "FOUND",
        "tier_prior": tier_key,
        "tier_central_population": tier.central_population,
        "form": str(site.get("realised_settlement_form") or "GENERAL_SETTLEMENT"),
        "form_population_factor": form.population_factor,
        "human_residence_factor": residence_factor,
        "capacity_score": capacity,
        "physical_factor": physical_factor,
        "access_score": access,
        "access_factor": access_factor,
        "relative_food_resource_factor": resource_factor,
        "evidence_confidence": confidence,
        "warning": "Working demographic prior, not canon and not a calibrated census.",
    }
    return (*result, explanation)


def local_food_support_ratio(
    site: Mapping[str, Any],
    *,
    food_resource_index: float = 1.0,
) -> tuple[float, dict[str, Any]]:
    form = policy_for_form(site.get("realised_settlement_form"))
    haus = policy_for_haus(site.get("owner_haus_id"))
    form_key = str(site.get("realised_settlement_form") or "GENERAL_SETTLEMENT")
    capacity = effective_capacity_score(site)
    seasonal = _value(
        site, "seasonal_reliability_index_10m", "seasonal_reliability_index_100m"
    )
    if seasonal is None:
        seasonal = effective_access_score(site)
    environmental = 0.72 + 0.28 * math.sqrt(clamp(capacity, 0.0, 1.0))
    seasonal_factor = 0.75 + 0.25 * clamp(seasonal, 0.0, 1.0)
    relative_resource = clamp(food_resource_index, 0.85, 1.15)
    haus_factor_applied = form_key in FOOD_PRODUCER_FORMS
    haus_production_factor = haus.food_production_factor if haus_factor_applied else 1.0
    ratio = (
        form.local_food_ratio
        * haus_production_factor
        * environmental
        * seasonal_factor
        * relative_resource
    )
    return ratio, {
        "form_local_food_ratio": form.local_food_ratio,
        "haus_food_production_factor": haus_production_factor,
        "haus_food_factor_applied": haus_factor_applied,
        "haus_food_support_class": haus.food_support_class,
        "haus_food_policy_evidence_status": haus.food_policy_evidence_status,
        "gross_food_product_trade_status": haus.gross_food_product_trade_status,
        "storage_factor": form.storage_factor,
        "environmental_factor": environmental,
        "seasonal_factor": seasonal_factor,
        "relative_resource_factor": relative_resource,
        "export_role": haus.export_role,
        "export_reserve_factor": haus.export_reserve_factor,
        "import_priority_factor": haus.import_priority_factor,
        "within_network_redistribution_allowed": haus.within_network_redistribution_allowed,
        "claim_ceiling": "RELATIVE_WORKING_SUPPORT_ONLY_NOT_YIELD_OR_PRODUCTION_CANON",
    }


def trade_loss_fraction(access_score: float, scenario_id: str) -> float:
    parameters = SCENARIO_PARAMETERS[scenario_id]
    loss = parameters["loss_floor"] + parameters["loss_access_penalty"] * (
        1.0 - clamp(access_score, 0.0, 1.0)
    )
    return clamp(loss, 0.0, 0.75)


def rules_fingerprint() -> str:
    payload = {
        "method_version": METHOD_VERSION,
        "tier_priors": {key: vars(value) for key, value in TIER_PRIORS.items()},
        "form_policies": {key: vars(value) for key, value in FORM_POLICIES.items()},
        "haus_policies": {key: vars(value) for key, value in HAUS_POLICIES.items()},
        "default_haus_policy": vars(DEFAULT_HAUS_POLICY),
        "scenario_parameters": SCENARIO_PARAMETERS,
    }
    return fingerprint(payload)


def self_check() -> dict[str, Any]:
    missing = sorted(set(TIER_PRIORS) ^ {
        "FT0_HAUS_PRINCIPAL_SITE",
        "FT1_MAJOR_REGIONAL_HUB",
        "FT2_SUBREGIONAL_OR_SPECIALIST_CENTRE",
        "FT3_LOCAL_CENTRE",
        "FT4_MINOR_LOCAL_SITE",
        "FTU_CONDITIONAL_FIELD_SITE",
        "FTU_PERMANENCE_UNRESOLVED",
    })
    if missing:
        raise RuntimeError(f"Tier rule mismatch: {missing}")
    if len(FORM_POLICIES) != 30:
        raise RuntimeError(f"Expected 30 settlement-form policies, found {len(FORM_POLICIES)}")
    for key, policy in FORM_POLICIES.items():
        if min(policy.population_factor, policy.local_food_ratio, policy.storage_factor) < 0:
            raise RuntimeError(f"Negative form policy value: {key}")
    for key, policy in HAUS_POLICIES.items():
        if not 0.0 <= policy.bonded_human_fraction <= 1.0:
            raise RuntimeError(f"Invalid bonded fraction: {key}")
        if policy.food_production_factor < 0 or policy.export_reserve_factor < 1.0:
            raise RuntimeError(f"Invalid food support calibration: {key}")
        if policy.import_priority_factor < 0:
            raise RuntimeError(f"Invalid import priority: {key}")
    expected_haus = {
        "BUCHHAIN", "DUFTFAEHRTE", "DUNKELHAUCH", "EDELSTEIN", "EISENWEB",
        "EREMITENSCHALE", "FEUERSCHUPPE", "FROSTGLANZ", "GLANZGRUND",
        "LAUBRAUNEN", "MARIENHAIN", "MOORWANDLER", "NACHTFLUESTERN",
        "SEELENWACHT", "SERENAKRONE", "STILLKLINGE", "STURMGLAS",
        "VERFUEHRSCHLUND", "WIEDERGEBORENE_FLAMME", "ZWIELICHT",
    }
    if set(HAUS_POLICIES) != expected_haus:
        raise RuntimeError(
            f"Haus food-support coverage mismatch: {sorted(set(HAUS_POLICIES) ^ expected_haus)}"
        )
    return {
        "status": "PASS",
        "method_version": METHOD_VERSION,
        "tier_rule_count": len(TIER_PRIORS),
        "form_rule_count": len(FORM_POLICIES),
        "explicit_haus_rule_count": len(HAUS_POLICIES),
        "rules_fingerprint": rules_fingerprint(),
        "canon_status": CANON_STATUS,
    }


if __name__ == "__main__":
    print(json.dumps(self_check(), indent=2, ensure_ascii=False))
