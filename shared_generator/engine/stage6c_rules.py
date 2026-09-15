"""Deterministic Stage 6C access/capacity rule catalogue.

This module is deliberately read-only with respect to the verified Stage 6B
SQLite source.  It derives the observed base and owner-Haus profiles, resolves
small explicit policy overrides, and returns serialisable rows for the Stage 6C
catalogue tables.  It does not create or modify any database or deliverable.

The public entry points are:

* ``read_only_connection``
* ``owner_rows``
* ``base_policy_rows``
* ``profile_catalog_rows``
* ``profile_component_rows``
* ``coordinate_semantics_catalog_rows``
* ``coordinate_semantics_assignment_rows``
* ``self_check``

All classifications remain WORKING PROPOSAL - REVIEW ONLY - NOT CANON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from source_catalogue import generator_root, source_path

METHOD_VERSION = "STAGE6C_ACCESS_CAPACITY_PROFILE_V1"
CANON_STATUS = "WORKING_PROPOSAL_REVIEW_ONLY_NOT_CANON"

EXPECTED_BASE_PROFILE_COUNT = 59
EXPECTED_RESOLVED_PROFILE_COUNT = 217
EXPECTED_COMPONENTS_PER_PROFILE = 9
EXPECTED_PROFILE_COMPONENT_COUNT = 1_953
EXPECTED_COORDINATE_CLASS_COUNT = 21
EXPECTED_OWNER_COUNT = 30_097
EXPECTED_REGISTRY_COUNT = 31_271
EXPECTED_PROVISIONAL_REGISTRY_COUNT = 1_714
EXPECTED_PROVISIONAL_SETTLEMENT_COUNT = 1_713

SPECIALIST_3D_DOMAINS = frozenset(
    {
        "SUBSURFACE",
        "AERIAL_VERTICAL",
        "SURFACE_FACING_DRY_OR_AIR_CAVERN_DISTRICTS",
        "SURFACE_CLIFF_TERRACE_VERTICAL",
        "FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN",
        "SUBMERGED_OR_FLOODED_CAVERN",
    }
)

ROOT = generator_root()
DEFAULT_DB = source_path("stage6b_parent_sqlite")


COMPONENT_CODES = (
    "TERRAIN_SUPPORT",
    "HYDROLOGY_SUPPORT",
    "FLOOD_COMPATIBILITY",
    "CORE_CAPACITY",
    "EXPANSION_CAPACITY",
    "LAND_ACCESS",
    "WATER_ACCESS",
    "SEASONAL_RELIABILITY",
    "DOMAIN_FIT",
)

CAPACITY_COMPONENTS = frozenset(
    {
        "TERRAIN_SUPPORT",
        "HYDROLOGY_SUPPORT",
        "FLOOD_COMPATIBILITY",
        "CORE_CAPACITY",
        "EXPANSION_CAPACITY",
        "DOMAIN_FIT",
    }
)
ACCESS_COMPONENTS = frozenset(
    {"LAND_ACCESS", "WATER_ACCESS", "SEASONAL_RELIABILITY"}
)


def _weight_set(
    terrain: float,
    hydrology: float,
    flood: float,
    core: float,
    expansion: float,
    domain: float,
    land: float,
    water: float,
    seasonal: float,
) -> dict[str, float]:
    return {
        "TERRAIN_SUPPORT": terrain,
        "HYDROLOGY_SUPPORT": hydrology,
        "FLOOD_COMPATIBILITY": flood,
        "CORE_CAPACITY": core,
        "EXPANSION_CAPACITY": expansion,
        "DOMAIN_FIT": domain,
        "LAND_ACCESS": land,
        "WATER_ACCESS": water,
        "SEASONAL_RELIABILITY": seasonal,
    }


WEIGHT_SETS: dict[str, dict[str, float]] = {
    "SURFACE_BALANCED": _weight_set(
        0.18, 0.12, 0.10, 0.22, 0.18, 0.20, 0.50, 0.25, 0.25
    ),
    "WATER_DEPENDENT": _weight_set(
        0.10, 0.25, 0.12, 0.18, 0.15, 0.20, 0.15, 0.60, 0.25
    ),
    "FOREST_VERTICAL": _weight_set(
        0.15, 0.10, 0.10, 0.20, 0.15, 0.30, 0.65, 0.10, 0.25
    ),
    "ROUTE_NODE": _weight_set(
        0.15, 0.10, 0.10, 0.20, 0.15, 0.30, 0.65, 0.15, 0.20
    ),
    "MOBILE_OR_RECURRENT": _weight_set(
        0.10, 0.15, 0.05, 0.15, 0.10, 0.45, 0.25, 0.35, 0.40
    ),
    "DEFERRED_SPECIALIST_3D": _weight_set(
        0.05, 0.05, 0.05, 0.10, 0.10, 0.65, 0.30, 0.30, 0.40
    ),
}


def _form_policy(
    morphology: str,
    capacity_metric: str,
    primary_access: str,
    secondary_access: Sequence[str],
    footprint_recipe: str,
    *,
    weight_set: str = "SURFACE_BALANCED",
    hydrology_preference: str = "MODERATE",
    flood_tolerance: str = "LOW",
    slope_limit_deg: float = 25.0,
    core_target_km2: float = 1.5,
    expansion_target_km2: float = 20.0,
    capacity_operator: str = "REQUIRED_WEIGHTED_GEOMEAN",
    access_operator: str = "WEIGHTED_MAX",
) -> dict[str, Any]:
    return {
        "morphology_class": morphology,
        "capacity_metric_kind": capacity_metric,
        "primary_access_mode": primary_access,
        "secondary_access_modes": tuple(secondary_access),
        "footprint_recipe_family": footprint_recipe,
        "weight_set_code": weight_set,
        "hydrology_preference": hydrology_preference,
        "flood_tolerance": flood_tolerance,
        "slope_limit_deg": float(slope_limit_deg),
        "core_target_km2": float(core_target_km2),
        "expansion_target_km2": float(expansion_target_km2),
        "capacity_operator": capacity_operator,
        "access_operator": access_operator,
        "band_thresholds": (0.25, 0.45, 0.65, 0.82),
    }


# Exactly the 30 active Stage 6B realised-settlement-form values.  A domain
# modifier is applied after these form defaults; only observed form/domain pairs
# are materialised, producing exactly 59 base recipes from the current V3 source.
FORM_POLICIES: dict[str, dict[str, Any]] = {
    "AGRARIAN_SETTLEMENT": _form_policy(
        "DISPERSED_AGRARIAN_CLUSTER",
        "SURFACE_DEVELOPABLE_AREA",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "DISPERSED_CLUSTER",
        slope_limit_deg=12.0,
        core_target_km2=2.0,
        expansion_target_km2=30.0,
    ),
    "ARCHIVE_EDUCATION_OR_CRAFT_SETTLEMENT": _form_policy(
        "INSTITUTIONAL_CAMPUS",
        "CAMPUS_SUPPORT_AREA",
        "LAND_TRACK_POTENTIAL",
        ("SPECIALIST_SERVICE_ACCESS",),
        "COMPACT_CAMPUS",
    ),
    "CANOPY_TREE_OR_EYRIE_SETTLEMENT": _form_policy(
        "CANOPY_CROWN_NETWORK",
        "CANOPY_SUPPORT",
        "VERTICAL_OR_AERIAL_ACCESS",
        ("FOREST_FLOOR_TRANSFER",),
        "CANOPY_NETWORK_DEFERRED_VERTICAL_DETAIL",
        weight_set="FOREST_VERTICAL",
        flood_tolerance="HIGH",
        slope_limit_deg=40.0,
    ),
    "CATHEDRAL_OR_CUSTODIAL_SETTLEMENT": _form_policy(
        "CATHEDRAL_CUSTODIAL_CAMPUS",
        "INSTITUTIONAL_SUPPORT_AREA",
        "LAND_TRACK_POTENTIAL",
        ("SPECIALIST_SERVICE_ACCESS",),
        "COMPACT_CAMPUS",
    ),
    "CIVIC_ADMINISTRATIVE_SETTLEMENT": _form_policy(
        "COMPACT_CIVIC_CORE",
        "CIVIC_CORE_SUPPORT_AREA",
        "MULTIMODAL_ACCESS_POTENTIAL",
        ("LAND_TRACK_POTENTIAL", "LOCAL_WATER_ACCESS"),
        "COMPACT_CIVIC_CORE",
        weight_set="ROUTE_NODE",
        core_target_km2=2.5,
        expansion_target_km2=35.0,
    ),
    "CONDITIONAL_FIELD_SITE": _form_policy(
        "CONDITIONAL_SERVICE_SITE",
        "CONDITIONAL_LOCAL_SUPPORT",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "CONDITIONAL_RECIPE_ONLY",
        core_target_km2=0.5,
        expansion_target_km2=5.0,
    ),
    "EXTRACTION_PROCESSING_OR_INDUSTRIAL_SETTLEMENT": _form_policy(
        "RESOURCE_NODE_CLUSTER",
        "INDUSTRIAL_TERRAIN_SUPPORT",
        "FREIGHT_LAND_ACCESS_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "RESOURCE_NODE_CLUSTER",
        weight_set="ROUTE_NODE",
        slope_limit_deg=30.0,
    ),
    "FISHERY_OR_LAKESHORE_SETTLEMENT": _form_policy(
        "WATERSIDE_FISHERY_CLUSTER",
        "WATERSIDE_SUPPORT_AREA",
        "WATERBORNE_ACCESS_POTENTIAL",
        ("LAND_TRACK_POTENTIAL",),
        "SHORELINE_LINEAR_CLUSTER",
        weight_set="WATER_DEPENDENT",
        hydrology_preference="NEAR",
        flood_tolerance="MODERATE",
    ),
    "FOREST_EDGE_SETTLEMENT": _form_policy(
        "FOREST_EDGE_LINEAR_CLUSTER",
        "FOREST_EDGE_SUPPORT",
        "LAND_TRACK_POTENTIAL",
        ("FOREST_INTERIOR_ACCESS",),
        "FOREST_EDGE_LINEAR",
        weight_set="FOREST_VERTICAL",
    ),
    "FOREST_FLOOR_CROWN_ENCLAVE_SETTLEMENT": _form_policy(
        "FOREST_FLOOR_ENCLAVE",
        "FOREST_FLOOR_SUPPORT",
        "FOREST_FLOOR_ROUTE_ACCESS",
        ("CANOPY_TRANSFER",),
        "FOREST_FLOOR_CLUSTER",
        weight_set="FOREST_VERTICAL",
        flood_tolerance="HIGH",
    ),
    "FREIGHT_TRANSFER_OR_LANDING_SETTLEMENT": _form_policy(
        "LANDING_TRANSFER_NODE",
        "TRANSFER_NODE_SUPPORT",
        "WATERBORNE_ACCESS_POTENTIAL",
        ("FREIGHT_LAND_ACCESS_POTENTIAL",),
        "LANDING_TRANSFER_NODE",
        weight_set="WATER_DEPENDENT",
        hydrology_preference="NEAR",
        flood_tolerance="MODERATE",
        access_operator="REQUIRED_WEIGHTED_GEOMEAN",
    ),
    "FULLY_SUBMERGED_NATIVE_SPECIALIST_SETTLEMENT": _form_policy(
        "FULLY_SUBMERGED_SPECIALIST_NODE",
        "SPECIALIST_3D_DEFERRED",
        "SUBMERGED_SPECIALIST_ACCESS_DEFERRED",
        (),
        "DEFERRED_SPECIALIST_3D",
        weight_set="DEFERRED_SPECIALIST_3D",
        hydrology_preference="NEAR",
        flood_tolerance="HIGH",
    ),
    "GENERAL_SETTLEMENT": _form_policy(
        "GENERAL_CLUSTER",
        "GENERAL_LOCAL_SUPPORT",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "GENERAL_CLUSTER",
    ),
    "GENERAL_SETTLEMENT_FORM_REQUIRES_NON_CAPITAL_ROLE_REVIEW": _form_policy(
        "GENERAL_CLUSTER_REVIEW",
        "PROVISIONAL_LOCAL_SUPPORT",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "GENERAL_CLUSTER_REVIEW",
    ),
    "HIVE_SETTLEMENT": _form_policy(
        "HIVE_CLUSTER",
        "HIVE_DOMAIN_SUPPORT",
        "SPECIALIST_LAND_ACCESS",
        ("VERTICAL_TRANSFER",),
        "HIVE_CLUSTER_DEFERRED_INTERNAL_DETAIL",
        weight_set="FOREST_VERTICAL",
        slope_limit_deg=40.0,
    ),
    "HORTICULTURAL_OR_ORCHARD_SETTLEMENT": _form_policy(
        "DISPERSED_ORCHARD_CLUSTER",
        "SURFACE_DEVELOPABLE_AREA",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "DISPERSED_CLUSTER",
        slope_limit_deg=15.0,
        core_target_km2=1.5,
        expansion_target_km2=25.0,
    ),
    "MARKET_EXCHANGE_SETTLEMENT": _form_policy(
        "COMPACT_MARKET_CLUSTER",
        "MARKET_NODE_SUPPORT",
        "MULTIMODAL_ACCESS_POTENTIAL",
        ("LAND_TRACK_POTENTIAL", "LOCAL_WATER_ACCESS"),
        "COMPACT_MARKET_CLUSTER",
        weight_set="ROUTE_NODE",
    ),
    "MEDICAL_CARE_OR_SANCTUARY_SETTLEMENT": _form_policy(
        "MEDICAL_SANCTUARY_CAMPUS",
        "SPECIALIST_SERVICE_SUPPORT",
        "RELIABLE_SERVICE_ACCESS",
        ("LAND_TRACK_POTENTIAL", "LOCAL_WATER_ACCESS"),
        "SPECIALIST_CAMPUS",
        weight_set="ROUTE_NODE",
    ),
    "MIXED_RURAL_SETTLEMENT": _form_policy(
        "MIXED_DISPERSED_CLUSTER",
        "SURFACE_DEVELOPABLE_AREA",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "MIXED_DISPERSED_CLUSTER",
        slope_limit_deg=18.0,
    ),
    "PASTORAL_SETTLEMENT": _form_policy(
        "DISPERSED_PASTORAL_CLUSTER",
        "PASTORAL_SUPPORT_AREA",
        "LAND_TRACK_POTENTIAL",
        ("SEASONAL_WATER_ACCESS",),
        "DISPERSED_PASTORAL_CLUSTER",
        core_target_km2=2.0,
        expansion_target_km2=40.0,
    ),
    "RIVER_TERRACE_OR_WATERSIDE_SETTLEMENT": _form_policy(
        "RIVER_LINEAR_TERRACE",
        "RIVER_TERRACE_SUPPORT",
        "RIVERINE_ACCESS_POTENTIAL",
        ("LAND_TRACK_POTENTIAL",),
        "RIVER_ALIGNED_LINEAR",
        weight_set="WATER_DEPENDENT",
        hydrology_preference="NEAR",
        flood_tolerance="MODERATE",
    ),
    "ROUTE_CROSSING_OR_PASS_SETTLEMENT": _form_policy(
        "ROUTE_NODE_CLUSTER",
        "ROUTE_NODE_SUPPORT",
        "LAND_ROUTE_NODE_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "ROUTE_NODE_CLUSTER",
        weight_set="ROUTE_NODE",
        slope_limit_deg=32.0,
    ),
    "SHELTERED_VALLEY_SETTLEMENT": _form_policy(
        "VALLEY_LINEAR_CLUSTER",
        "VALLEY_FLOOR_SUPPORT",
        "VALLEY_ROUTE_ACCESS",
        ("LOCAL_WATER_ACCESS",),
        "VALLEY_ALIGNED_LINEAR",
        slope_limit_deg=20.0,
    ),
    "SPECIES_SPECIFIC_OR_BONDED_SETTLEMENT": _form_policy(
        "SPECIES_SPECIFIC_CLUSTER",
        "SPECIES_DOMAIN_SUPPORT",
        "SPECIALIST_ACCESS",
        ("LAND_TRACK_POTENTIAL", "VERTICAL_TRANSFER"),
        "SPECIES_SPECIFIC_RECIPE",
        weight_set="FOREST_VERTICAL",
    ),
    "SUBMERGED_OR_CAVERN_SETTLEMENT": _form_policy(
        "SUBMERGED_OR_CAVERN_SPECIALIST_NODE",
        "SPECIALIST_3D_DEFERRED",
        "CAVERN_OR_SUBMERGED_ACCESS_DEFERRED",
        (),
        "DEFERRED_SPECIALIST_3D",
        weight_set="DEFERRED_SPECIALIST_3D",
        flood_tolerance="HIGH",
    ),
    "SURFACE_FACING_SHAFT_OR_AIR_CAVERN_SETTLEMENT": _form_policy(
        "SHAFT_INTERFACE_CLUSTER",
        "SPECIALIST_3D_DEFERRED",
        "SHAFT_INTERFACE_ACCESS_DEFERRED",
        ("SURFACE_LAND_ACCESS",),
        "DEFERRED_SPECIALIST_3D",
        weight_set="DEFERRED_SPECIALIST_3D",
    ),
    "SURFACE_LAGOON_SETTLEMENT": _form_policy(
        "SURFACE_LAGOON_PLATFORM_NETWORK",
        "LAGOON_PLATFORM_SUPPORT",
        "LAGOON_WATERBORNE_ACCESS",
        ("SHORE_TRANSFER",),
        "SURFACE_LAGOON_NETWORK",
        weight_set="WATER_DEPENDENT",
        hydrology_preference="NEAR",
        flood_tolerance="HIGH",
        access_operator="REQUIRED_WEIGHTED_GEOMEAN",
    ),
    "WETLAND_EDGE_SETTLEMENT": _form_policy(
        "WETLAND_EDGE_LINEAR_CLUSTER",
        "WETLAND_EDGE_SUPPORT",
        "MIXED_WETLAND_LAND_ACCESS",
        ("CHANNEL_ACCESS",),
        "WETLAND_EDGE_LINEAR",
        weight_set="WATER_DEPENDENT",
        hydrology_preference="NEAR",
        flood_tolerance="MODERATE",
    ),
    "WETLAND_STILT_OR_CHANNEL_SETTLEMENT": _form_policy(
        "STILT_CHANNEL_NETWORK",
        "WETLAND_PLATFORM_SUPPORT",
        "CHANNEL_WATERBORNE_ACCESS",
        ("BOARDWALK_ACCESS",),
        "STILT_CHANNEL_NETWORK",
        weight_set="WATER_DEPENDENT",
        hydrology_preference="NEAR",
        flood_tolerance="HIGH",
        access_operator="REQUIRED_WEIGHTED_GEOMEAN",
    ),
    "WORK_SITE_PERMANENCE_UNRESOLVED": _form_policy(
        "WORK_SITE_UNRESOLVED",
        "CONDITIONAL_LOCAL_SUPPORT",
        "LAND_TRACK_POTENTIAL",
        ("LOCAL_WATER_ACCESS",),
        "CONDITIONAL_RECIPE_ONLY",
        core_target_km2=0.5,
        expansion_target_km2=5.0,
    ),
}


DOMAIN_MODIFIERS: dict[str, dict[str, Any]] = {
    "SURFACE": {},
    "UNSPECIFIED": {
        "capacity_metric_kind": "PROVISIONAL_DOMAIN_CONTEXT",
        "footprint_recipe_family": "DEFERRED_DOMAIN_RESOLUTION",
    },
    "FOREST_CANOPY": {
        "capacity_metric_kind": "CANOPY_SUPPORT",
        "primary_access_mode": "VERTICAL_OR_AERIAL_ACCESS",
        "footprint_recipe_family": "CANOPY_NETWORK_DEFERRED_VERTICAL_DETAIL",
        "weight_set_code": "FOREST_VERTICAL",
        "flood_tolerance": "HIGH",
    },
    "FOREST_FLOOR_ROOT": {
        "capacity_metric_kind": "FOREST_FLOOR_SUPPORT",
        "primary_access_mode": "FOREST_FLOOR_ROUTE_ACCESS",
        "footprint_recipe_family": "FOREST_FLOOR_CLUSTER",
        "weight_set_code": "FOREST_VERTICAL",
        "flood_tolerance": "HIGH",
    },
    "WETLAND_INTERIOR": {
        "capacity_metric_kind": "WETLAND_PLATFORM_SUPPORT",
        "primary_access_mode": "CHANNEL_WATERBORNE_ACCESS",
        "footprint_recipe_family": "STILT_CHANNEL_NETWORK",
        "weight_set_code": "WATER_DEPENDENT",
        "hydrology_preference": "NEAR",
        "flood_tolerance": "HIGH",
        "access_operator": "REQUIRED_WEIGHTED_GEOMEAN",
    },
    "NOMADIC_ROUTE_ANCHOR": {
        "capacity_metric_kind": "RECURRENT_HOST_SUPPORT",
        "primary_access_mode": "MOBILE_ROUTE_ACCESS",
        "footprint_recipe_family": "RECURRENT_ANCHOR_RECIPE",
        "weight_set_code": "MOBILE_OR_RECURRENT",
        "capacity_operator": "WEIGHTED_GEOMEAN",
    },
    "SUBSURFACE": {
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "SUBSURFACE_ACCESS_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
    },
    "AERIAL_VERTICAL": {
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "AERIAL_VERTICAL_ACCESS_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
    },
    "SURFACE_FACING_DRY_OR_AIR_CAVERN_DISTRICTS": {
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "SHAFT_INTERFACE_ACCESS_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
    },
    "SURFACE_CLIFF_TERRACE_VERTICAL": {
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "CLIFF_VERTICAL_ACCESS_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
    },
    "FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN": {
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "SUBMERGED_SPECIALIST_ACCESS_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
        "hydrology_preference": "NEAR",
        "flood_tolerance": "HIGH",
    },
    "SUBMERGED_OR_FLOODED_CAVERN": {
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "CAVERN_OR_SUBMERGED_ACCESS_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
        "hydrology_preference": "NEAR",
        "flood_tolerance": "HIGH",
    },
}


# Sparse, evidence-led overrides only.  These retain explicit project decisions;
# they do not introduce culture, religion, population rank or new military logic.
HAUS_OVERRIDES: dict[tuple[str, str, str], dict[str, Any]] = {
    (
        "DUFTFAEHRTE",
        "MEDICAL_CARE_OR_SANCTUARY_SETTLEMENT",
        "NOMADIC_ROUTE_ANCHOR",
    ): {
        "override_code": "DUFTFAEHRTE_RECURRENT_HOST_ONLY",
        "morphology_class": "RECURRENT_MEDICAL_HOST_ANCHOR",
        "capacity_metric_kind": "RECURRENT_HOST_SUPPORT",
        "primary_access_mode": "MOBILE_ROUTE_ACCESS",
        "footprint_recipe_family": "RECURRENT_ANCHOR_RECIPE",
        "weight_set_code": "MOBILE_OR_RECURRENT",
    },
    (
        "DUNKELHAUCH",
        "CIVIC_ADMINISTRATIVE_SETTLEMENT",
        "SUBSURFACE",
    ): {
        "override_code": "DUNKELHAUCH_HEART_INFRASTRUCTURE_SYSTEM",
        "morphology_class": "COMPACT_HEART_INFRASTRUCTURE_SYSTEM",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "footprint_recipe_family": "DEFERRED_SPECIALIST_3D",
        "weight_set_code": "DEFERRED_SPECIALIST_3D",
    },
    (
        "GLANZGRUND",
        "FULLY_SUBMERGED_NATIVE_SPECIALIST_SETTLEMENT",
        "FULLY_SUBMERGED_NATIVE_SPECIALIST_DOMAIN",
    ): {
        "override_code": "GLANZGRUND_FULLY_SUBMERGED_NATIVE_SPECIALIST",
        "morphology_class": "FULLY_SUBMERGED_NATIVE_SPECIALIST_NODE",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
    },
    (
        "GLANZGRUND",
        "SURFACE_FACING_SHAFT_OR_AIR_CAVERN_SETTLEMENT",
        "SURFACE_FACING_DRY_OR_AIR_CAVERN_DISTRICTS",
    ): {
        "override_code": "GLANZGRUND_SURFACE_FACING_SHAFT_INTERFACE",
        "morphology_class": "SURFACE_FACING_SHAFT_INTERFACE_CLUSTER",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
    },
    (
        "MOORWANDLER",
        "WETLAND_STILT_OR_CHANNEL_SETTLEMENT",
        "WETLAND_INTERIOR",
    ): {
        "override_code": "MOORWANDLER_DEEP_WETLAND_STILT_NETWORK",
        "morphology_class": "DEEP_WETLAND_STILT_CHANNEL_NETWORK",
        "capacity_metric_kind": "WETLAND_PLATFORM_SUPPORT",
        "primary_access_mode": "CHANNEL_WATERBORNE_ACCESS",
        "weight_set_code": "WATER_DEPENDENT",
    },
    (
        "MOORWANDLER",
        "WETLAND_STILT_OR_CHANNEL_SETTLEMENT",
        "SURFACE",
    ): {
        "override_code": "MOORWANDLER_SURFACE_CODED_STILT_SITE",
        "morphology_class": "WETLAND_STILT_CHANNEL_NETWORK",
        "capacity_metric_kind": "WETLAND_PLATFORM_SUPPORT",
        "primary_access_mode": "CHANNEL_WATERBORNE_ACCESS",
        "weight_set_code": "WATER_DEPENDENT",
    },
    (
        "SERENAKRONE",
        "SURFACE_LAGOON_SETTLEMENT",
        "SURFACE",
    ): {
        "override_code": "SERENAKRONE_SURFACE_LAGOON_NOT_SUBMERGED",
        "morphology_class": "SURFACE_LAGOON_PLATFORM_NETWORK",
        "capacity_metric_kind": "LAGOON_PLATFORM_SUPPORT",
        "footprint_recipe_family": "SURFACE_LAGOON_NETWORK",
    },
    (
        "STILLKLINGE",
        "MEDICAL_CARE_OR_SANCTUARY_SETTLEMENT",
        "SUBSURFACE",
    ): {
        "override_code": "STILLKLINGE_SUBSURFACE_MEDICAL_NODE",
        "morphology_class": "SUBSURFACE_MEDICAL_NODE",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
    },
    (
        "STILLKLINGE",
        "SPECIES_SPECIFIC_OR_BONDED_SETTLEMENT",
        "SUBSURFACE",
    ): {
        "override_code": "STILLKLINGE_SUBSURFACE_SPECIES_NODE",
        "morphology_class": "SUBSURFACE_SPECIES_NODE",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
    },
    (
        "STILLKLINGE",
        "SUBMERGED_OR_CAVERN_SETTLEMENT",
        "SUBSURFACE",
    ): {
        "override_code": "STILLKLINGE_DRY_OR_AIR_CAVERN_NODE",
        "morphology_class": "SUBSURFACE_CAVERN_NODE",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
    },
    (
        "STILLKLINGE",
        "SUBMERGED_OR_CAVERN_SETTLEMENT",
        "SUBMERGED_OR_FLOODED_CAVERN",
    ): {
        "override_code": "STILLKLINGE_REPAIRED_RIVER_CAVERN_NODE",
        "morphology_class": "SUBMERGED_OR_FLOODED_CAVERN_NODE",
        "capacity_metric_kind": "SPECIALIST_3D_DEFERRED",
        "primary_access_mode": "CAVERN_OR_SUBMERGED_ACCESS_DEFERRED",
    },
}


def _coordinate_rule(
    code: str,
    source_semantics: str | None,
    selection_rule: str,
    value_resolution_km: float | None,
    anchor_status: str,
    provisional_anchor: bool,
    uncertainty_shape: str,
    uncertainty_radius_km: float | None,
    vertical_status: str,
    footprint_status: str,
    basis: str,
) -> dict[str, Any]:
    return {
        "coordinate_semantics_code": code,
        "source_semantics_exact": source_semantics,
        "selection_rule": selection_rule,
        "value_resolution_km": value_resolution_km,
        "anchor_status": anchor_status,
        "provisional_anchor": int(provisional_anchor),
        "horizontal_uncertainty_shape": uncertainty_shape,
        "default_horizontal_uncertainty_radius_km": uncertainty_radius_km,
        "vertical_uncertainty_status": vertical_status,
        "footprint_status": footprint_status,
        "basis": basis,
    }


HALF_CELL_DIAGONAL_KM = math.sqrt(0.5**2 + 0.5**2)

SOURCE_COORDINATE_RULES: dict[str, dict[str, Any]] = {
    "FIXED_SURFACE_SETTLEMENT_POINT": _coordinate_rule(
        "FIXED_SURFACE_POINT",
        "FIXED_SURFACE_SETTLEMENT_POINT",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "SURFACE_ONLY",
        "DEFERRED_UNTIL_POPULATION",
        "Fixed source point; the point is not a settlement footprint.",
    ),
    "FIXED_HOST_SERVICE_POINT": _coordinate_rule(
        "FIXED_HOST_SERVICE_POINT",
        "FIXED_HOST_SERVICE_POINT",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "INHERIT_SITE_DOMAIN",
        "NOT_A_SETTLEMENT_FOOTPRINT",
        "Fixed host-service point; hosted overlays do not establish owner Haus.",
    ),
    "FIXED_SURVEYED_DRAINED_ROOTREACH_CROWN_CENTRED_OR_FOREST_FLOOR_COMMUNITY_POINT_NO_GENERIC_GROUND_LAYER": _coordinate_rule(
        "FIXED_ROOTREACH_FOREST_FLOOR_POINT",
        "FIXED_SURVEYED_DRAINED_ROOTREACH_CROWN_CENTRED_OR_FOREST_FLOOR_COMMUNITY_POINT_NO_GENERIC_GROUND_LAYER",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "FOREST_ROOT_OR_FLOOR_LAYER",
        "DEFERRED_UNTIL_POPULATION",
        "Forest-floor/root-layer point; no generic ground layer is inferred.",
    ),
    "FIXED_CANOPY_CROWN_OR_FLET_COMMUNITY_POINT_EXACT_VERTICAL_GEOMETRY_DEFERRED": _coordinate_rule(
        "FIXED_CANOPY_POINT_VERTICAL_DEFERRED",
        "FIXED_CANOPY_CROWN_OR_FLET_COMMUNITY_POINT_EXACT_VERTICAL_GEOMETRY_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "DEFERRED_SPECIALIST_VERTICAL",
        "DEFERRED_VERTICAL_GEOMETRY",
        "Horizontal canopy anchor is fixed; exact vertical geometry is deferred.",
    ),
    "EXACT_PRESERVED_STAGE5B_DISPLAY_POINT": _coordinate_rule(
        "PRESERVED_STAGE5B_DISPLAY_POINT",
        "EXACT_PRESERVED_STAGE5B_DISPLAY_POINT",
        "EXACT_SOURCE_SEMANTICS",
        None,
        "PRESERVED_DISPLAY_POINT",
        False,
        "SOURCE_DEFINED",
        None,
        "INHERIT_SITE_DOMAIN",
        "DEFERRED_UNTIL_POPULATION",
        "Preserve the exact stored value; lexical decimals do not imply positional certainty.",
    ),
    "FIXED_ROOT_ADJACENT_OR_FOREST_EDGE_SPECIALISED_SUPPORT_POINT_NO_GENERIC_GROUND_ELIGIBILITY": _coordinate_rule(
        "FIXED_ROOT_ADJACENT_SUPPORT_POINT",
        "FIXED_ROOT_ADJACENT_OR_FOREST_EDGE_SPECIALISED_SUPPORT_POINT_NO_GENERIC_GROUND_ELIGIBILITY",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "FOREST_ROOT_OR_EDGE_LAYER",
        "DEFERRED_UNTIL_POPULATION",
        "Specialist root/edge point; no generic ground eligibility is inferred.",
    ),
    "SURFACE_FACING_SHAFT_INTERFACE_POINT_EXACT_3D_DEFERRED": _coordinate_rule(
        "FIXED_SHAFT_INTERFACE_POINT_3D_DEFERRED",
        "SURFACE_FACING_SHAFT_INTERFACE_POINT_EXACT_3D_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_INTERFACE_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "DEFERRED_SPECIALIST_3D",
        "DEFERRED_SPECIALIST_3D",
        "Surface interface is fixed; cavern extent is not inferred.",
    ),
    "FIXED_SURFACE_LAGOON_SETTLEMENT_POINT_EXACT_SHORE_ISLAND_OR_BUILT_LAYOUT_DEFERRED": _coordinate_rule(
        "FIXED_SURFACE_LAGOON_POINT_LAYOUT_DEFERRED",
        "FIXED_SURFACE_LAGOON_SETTLEMENT_POINT_EXACT_SHORE_ISLAND_OR_BUILT_LAYOUT_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "SURFACE_LAGOON",
        "DEFERRED_SHORE_ISLAND_OR_BUILT_LAYOUT",
        "Surface lagoon point; it is not a submerged settlement or exact layout.",
    ),
    "WORKING_CAPITAL_POINT_ANCHOR_EXACT_3D_DEFERRED": _coordinate_rule(
        "WORKING_CAPITAL_POINT_3D_DEFERRED",
        "WORKING_CAPITAL_POINT_ANCHOR_EXACT_3D_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        None,
        "WORKING_POINT_ANCHOR",
        True,
        "HOST_FEATURE_UNQUANTIFIED",
        None,
        "DEFERRED_SPECIALIST_3D",
        "DEFERRED_SPECIALIST_3D",
        "Working capital anchor; decimal precision does not make a footprint exact.",
    ),
    "SEMI_MOBILE_OPERATIONAL_ANCHOR_NOT_CADASTRAL_FOOTPRINT": _coordinate_rule(
        "SEMI_MOBILE_OPERATIONAL_ANCHOR",
        "SEMI_MOBILE_OPERATIONAL_ANCHOR_NOT_CADASTRAL_FOOTPRINT",
        "EXACT_SOURCE_SEMANTICS",
        None,
        "SEMI_MOBILE_ANCHOR",
        True,
        "ROUTE_CORRIDOR_UNQUANTIFIED",
        None,
        "MOBILE_OR_RECURRENT",
        "NOT_A_CADASTRAL_FOOTPRINT",
        "Operational anchor can recur within a route context.",
    ),
    "FIXED_SURFACE_SETTLEMENT_NOT_LAKESHORE_PORT": _coordinate_rule(
        "FIXED_SURFACE_POINT_NOT_PORT",
        "FIXED_SURFACE_SETTLEMENT_NOT_LAKESHORE_PORT",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_DISPLAY_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "SURFACE_ONLY",
        "DEFERRED_UNTIL_POPULATION",
        "Fixed surface point; no lakeshore-port access is inferred.",
    ),
    "ANALYTICAL_SURFACE_PROXY_FOR_FULLY_SUBMERGED_CAVERN_NODE_EXACT_3D_DEFERRED": _coordinate_rule(
        "ANALYTICAL_SUBMERGED_NODE_SURFACE_PROXY",
        "ANALYTICAL_SURFACE_PROXY_FOR_FULLY_SUBMERGED_CAVERN_NODE_EXACT_3D_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "ANALYTICAL_PROXY",
        True,
        "HOST_FEATURE_UNQUANTIFIED",
        None,
        "DEFERRED_SPECIALIST_3D",
        "DEFERRED_SPECIALIST_3D",
        "Surface proxy only; submerged node geometry is not displaced to the proxy.",
    ),
    "WORKING_CAPITAL_ANCHOR_POINT_NOT_3D_FOOTPRINT": _coordinate_rule(
        "WORKING_CAPITAL_ANCHOR_NOT_FOOTPRINT",
        "WORKING_CAPITAL_ANCHOR_POINT_NOT_3D_FOOTPRINT",
        "EXACT_SOURCE_SEMANTICS",
        None,
        "WORKING_POINT_ANCHOR",
        True,
        "HOST_FEATURE_UNQUANTIFIED",
        None,
        "DEFERRED_SPECIALIST_3D",
        "NOT_A_3D_FOOTPRINT",
        "Working anchor point only.",
    ),
    "PERMANENT_SPECIES_WELFARE_INFRASTRUCTURE": _coordinate_rule(
        "FIXED_SPECIES_WELFARE_INFRASTRUCTURE",
        "PERMANENT_SPECIES_WELFARE_INFRASTRUCTURE",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "FIXED_INFRASTRUCTURE_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "INHERIT_SITE_DOMAIN",
        "NOT_A_SETTLEMENT_FOOTPRINT",
        "Permanent welfare infrastructure remains an installation, not a settlement footprint.",
    ),
    "FIXED_SURFACE_LAGOON_CAPITAL_POINT_EXACT_SHORE_ISLAND_OR_BUILT_LAYOUT_DEFERRED": _coordinate_rule(
        "FIXED_SURFACE_LAGOON_CAPITAL_LAYOUT_DEFERRED",
        "FIXED_SURFACE_LAGOON_CAPITAL_POINT_EXACT_SHORE_ISLAND_OR_BUILT_LAYOUT_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        None,
        "FIXED_DISPLAY_POINT",
        False,
        "HOST_FEATURE_UNQUANTIFIED",
        None,
        "SURFACE_LAGOON",
        "DEFERRED_SHORE_ISLAND_OR_BUILT_LAYOUT",
        "Fixed surface lagoon capital point; layout remains deferred.",
    ),
    "FIXED_2D_PROXY_EXACT_AERIAL_GEOMETRY_DEFERRED": _coordinate_rule(
        "FIXED_2D_AERIAL_PROXY",
        "FIXED_2D_PROXY_EXACT_AERIAL_GEOMETRY_DEFERRED",
        "EXACT_SOURCE_SEMANTICS",
        1.0,
        "ANALYTICAL_PROXY",
        True,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "DEFERRED_SPECIALIST_VERTICAL",
        "DEFERRED_VERTICAL_GEOMETRY",
        "2D proxy only; exact aerial geometry is deferred.",
    ),
}


FALLBACK_COORDINATE_RULES: tuple[dict[str, Any], ...] = (
    _coordinate_rule(
        "INACTIVE_REJECTED_GRID_POINT",
        None,
        "STAGE6_ACTIVE_LOCATION=0",
        1.0,
        "INACTIVE_RETAINED_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "NOT_APPLICABLE_INACTIVE",
        "NOT_APPLICABLE_INACTIVE",
        "The source point is preserved for identity lineage but excluded from active analysis.",
    ),
    _coordinate_rule(
        "STAGE6_ADDED_GRID_ANCHOR",
        None,
        "SOURCE_SEMANTICS_MISSING; STAGE6_ADDED_IDENTITY=1; BOTH_COORDINATES_ON_HALF_KM_GRID",
        1.0,
        "WORKING_POINT_ANCHOR",
        True,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "INHERIT_SITE_DOMAIN",
        "DEFERRED_UNTIL_POPULATION",
        "Added Stage 6 point anchor; the 1 km source-cell footprint is not a settlement footprint.",
    ),
    _coordinate_rule(
        "STAGE6_ADDED_SUBGRID_ANCHOR",
        None,
        "SOURCE_SEMANTICS_MISSING; STAGE6_ADDED_IDENTITY=1; NOT_BOTH_COORDINATES_ON_HALF_KM_GRID",
        None,
        "WORKING_POINT_ANCHOR",
        True,
        "HOST_FEATURE_UNQUANTIFIED",
        None,
        "INHERIT_SITE_DOMAIN",
        "DEFERRED_UNTIL_POPULATION",
        "Sub-grid numeric precision is preserved but does not imply exact positional certainty.",
    ),
    _coordinate_rule(
        "LEGACY_MISSING_SEMANTICS_GRID_POINT",
        None,
        "SOURCE_SEMANTICS_MISSING; STAGE6_ADDED_IDENTITY=0; BOTH_COORDINATES_ON_HALF_KM_GRID",
        1.0,
        "UNRESOLVED_SOURCE_POINT",
        False,
        "SQUARE_SOURCE_CELL",
        HALF_CELL_DIAGONAL_KM,
        "INHERIT_SITE_DOMAIN",
        "DEFERRED_UNTIL_POPULATION",
        "Legacy point with missing semantics; retain the coordinate and flag inferred precision.",
    ),
    _coordinate_rule(
        "LEGACY_MISSING_SEMANTICS_SUBGRID_POINT",
        None,
        "SOURCE_SEMANTICS_MISSING; STAGE6_ADDED_IDENTITY=0; NOT_BOTH_COORDINATES_ON_HALF_KM_GRID",
        None,
        "UNRESOLVED_SOURCE_POINT",
        False,
        "UNQUANTIFIED",
        None,
        "INHERIT_SITE_DOMAIN",
        "DEFERRED_UNTIL_POPULATION",
        "Legacy sub-grid point with missing coordinate semantics; no precision is invented.",
    ),
)


OWNER_SQL = """
WITH owner AS (
    SELECT
        s.settlement_id,
        h.haus_id,
        'SETTLEMENT_MEMBERSHIP' AS owner_assignment_basis
    FROM settlement s
    JOIN stage6_site_disposition m
      ON m.source_site_id = s.settlement_id
     AND m.stage6b_membership_location_role = 'SETTLEMENT'
    JOIN haus h ON h.haus_name = m.haus
    WHERE s.stage6_active_settlement = 1

    UNION ALL

    SELECT
        s.settlement_id,
        h.haus_id,
        'ADDED_TARGET_HAUS' AS owner_assignment_basis
    FROM settlement s
    JOIN json_each(s.target_hauses_json) j
    JOIN haus h ON h.haus_name = j.value
    WHERE s.stage6_active_settlement = 1
      AND s.stage6_added_identity = 1
)
SELECT settlement_id, haus_id, owner_assignment_basis
FROM owner
ORDER BY settlement_id
"""


BASE_COMBINATION_SQL = """
SELECT
    stage6b_realised_settlement_form AS realised_settlement_form,
    COALESCE(stage6_vertical_domain_class, vertical_domain_class, 'UNSPECIFIED')
        AS effective_vertical_domain,
    COUNT(*) AS site_count
FROM settlement
WHERE stage6_active_settlement = 1
GROUP BY 1, 2
ORDER BY 1, 2
"""


OBSERVED_PROFILE_SQL = """
WITH owner AS (
    SELECT
        s.settlement_id,
        h.haus_id
    FROM settlement s
    JOIN stage6_site_disposition m
      ON m.source_site_id = s.settlement_id
     AND m.stage6b_membership_location_role = 'SETTLEMENT'
    JOIN haus h ON h.haus_name = m.haus
    WHERE s.stage6_active_settlement = 1

    UNION ALL

    SELECT
        s.settlement_id,
        h.haus_id
    FROM settlement s
    JOIN json_each(s.target_hauses_json) j
    JOIN haus h ON h.haus_name = j.value
    WHERE s.stage6_active_settlement = 1
      AND s.stage6_added_identity = 1
)
SELECT
    o.haus_id,
    s.stage6b_realised_settlement_form AS realised_settlement_form,
    COALESCE(s.stage6_vertical_domain_class, s.vertical_domain_class, 'UNSPECIFIED')
        AS effective_vertical_domain,
    COUNT(*) AS site_count
FROM owner o
JOIN settlement s ON s.settlement_id = o.settlement_id
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""


def _stable_id(prefix: str, *parts: str, length: int = 20) -> str:
    canonical = "|".join(parts).encode("utf-8")
    return f"{prefix}{hashlib.sha256(canonical).hexdigest()[:length].upper()}"


def _canonical_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        list(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@contextmanager
def read_only_connection(path: str | Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Open the Stage 6B SQLite source in immutable read-only mode."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    uri = f"{resolved.as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def owner_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(OWNER_SQL)]


def derive_owner_map(
    connection: sqlite3.Connection,
) -> dict[str, dict[str, str]]:
    """Return the unique settlement-owner mapping used by Stage 6C.

    Hosted-service overlay Hauses are intentionally excluded.  Existing sites
    use the membership whose Stage 6B location role is ``SETTLEMENT``; Stage-6
    added identities use their single target Haus.
    """

    result: dict[str, dict[str, str]] = {}
    for row in owner_rows(connection):
        settlement_id = str(row["settlement_id"])
        if settlement_id in result:
            raise AssertionError(f"Duplicate Stage 6C owner for {settlement_id}")
        result[settlement_id] = {
            "haus_id": str(row["haus_id"]),
            "owner_assignment_basis": str(row["owner_assignment_basis"]),
        }
    return result


def observed_base_combinations(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(BASE_COMBINATION_SQL)]


def observed_profile_combinations(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(OBSERVED_PROFILE_SQL)]


def _resolved_policy(
    realised_form: str,
    effective_domain: str,
    haus_id: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if realised_form not in FORM_POLICIES:
        raise KeyError(f"No Stage 6C form policy for {realised_form!r}")
    if effective_domain not in DOMAIN_MODIFIERS:
        raise KeyError(f"No Stage 6C domain modifier for {effective_domain!r}")

    policy = deepcopy(FORM_POLICIES[realised_form])
    basis = [f"FORM:{realised_form}", f"DOMAIN:{effective_domain}"]
    policy.update(deepcopy(DOMAIN_MODIFIERS[effective_domain]))

    if haus_id is not None:
        override = HAUS_OVERRIDES.get((haus_id, realised_form, effective_domain))
        if override:
            override = deepcopy(override)
            basis.append(f"HAUS_OVERRIDE:{override.pop('override_code')}")
            policy.update(override)

    weight_set_code = policy["weight_set_code"]
    if weight_set_code not in WEIGHT_SETS:
        raise KeyError(f"Unknown weight set {weight_set_code!r}")
    return policy, basis


def base_policy_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for combo in observed_base_combinations(connection):
        realised_form = combo["realised_settlement_form"]
        effective_domain = combo["effective_vertical_domain"]
        policy, basis = _resolved_policy(realised_form, effective_domain)
        rows.append(
            {
                "base_policy_id": _stable_id(
                    "S6C-BP-", realised_form, effective_domain, METHOD_VERSION
                ),
                "realised_settlement_form": realised_form,
                "effective_vertical_domain": effective_domain,
                "site_count": int(combo["site_count"]),
                "morphology_class": policy["morphology_class"],
                "capacity_metric_kind": policy["capacity_metric_kind"],
                "primary_access_mode": policy["primary_access_mode"],
                "secondary_access_modes_json": json.dumps(
                    policy["secondary_access_modes"], separators=(",", ":")
                ),
                "footprint_recipe_family": policy["footprint_recipe_family"],
                "weight_set_code": policy["weight_set_code"],
                "hydrology_preference": policy["hydrology_preference"],
                "flood_tolerance": policy["flood_tolerance"],
                "slope_limit_deg": policy["slope_limit_deg"],
                "core_target_km2": policy["core_target_km2"],
                "expansion_target_km2": policy["expansion_target_km2"],
                "capacity_operator": policy["capacity_operator"],
                "access_operator": policy["access_operator"],
                "policy_basis_json": json.dumps(basis, separators=(",", ":")),
                "method_version": METHOD_VERSION,
                "canon_status": CANON_STATUS,
            }
        )
    rows.sort(
        key=lambda row: (
            row["realised_settlement_form"],
            row["effective_vertical_domain"],
        )
    )
    return rows


def profile_catalog_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for combo in observed_profile_combinations(connection):
        haus_id = combo["haus_id"]
        realised_form = combo["realised_settlement_form"]
        effective_domain = combo["effective_vertical_domain"]
        policy, basis = _resolved_policy(realised_form, effective_domain, haus_id)
        thresholds = policy["band_thresholds"]
        rows.append(
            {
                "profile_id": _stable_id(
                    "S6C-P-",
                    haus_id,
                    realised_form,
                    effective_domain,
                    METHOD_VERSION,
                ),
                "haus_id": haus_id,
                "realised_settlement_form": realised_form,
                "effective_vertical_domain": effective_domain,
                "site_count": int(combo["site_count"]),
                "morphology_class": policy["morphology_class"],
                "capacity_metric_kind": policy["capacity_metric_kind"],
                "primary_access_mode": policy["primary_access_mode"],
                "secondary_access_modes_json": json.dumps(
                    policy["secondary_access_modes"], separators=(",", ":")
                ),
                "capacity_operator": policy["capacity_operator"],
                "access_operator": policy["access_operator"],
                "footprint_recipe_family": policy["footprint_recipe_family"],
                "band_t1": thresholds[0],
                "band_t2": thresholds[1],
                "band_t3": thresholds[2],
                "band_t4": thresholds[3],
                "profile_basis": json.dumps(basis, separators=(",", ":")),
                "method_version": METHOD_VERSION,
                "canon_status": CANON_STATUS,
            }
        )
    rows.sort(key=lambda row: row["profile_id"])
    return rows


def _component_rule(
    policy: Mapping[str, Any], component_code: str
) -> dict[str, Any]:
    deferred = policy["weight_set_code"] == "DEFERRED_SPECIALIST_3D"
    missing_policy = "DEFER_SPECIALIST_3D" if deferred else "DIRECT_OR_PROFILE_FALLBACK"
    required = 0 if deferred else 1

    if component_code == "TERRAIN_SUPPORT":
        return {
            "raw_metric_code": "terrain_slope_deg",
            "transform_code": "DEFERRED" if deferred else "LOW_BETTER",
            "p0": 0.0,
            "p1": policy["slope_limit_deg"],
            "p2": None,
            "p3": None,
            "required": required,
            "missing_policy": missing_policy,
        }

    if component_code == "HYDROLOGY_SUPPORT":
        preference = policy["hydrology_preference"]
        if deferred:
            transform, params = "DEFERRED", (None, None, None, None)
        elif preference == "NEAR":
            transform, params = "LOW_BETTER", (0.0, 5.0, None, None)
        elif preference == "MODERATE":
            transform, params = "RANGE_TRAPEZOID", (0.0, 0.25, 5.0, 15.0)
        else:
            transform, params = "CONSTANT", (1.0, None, None, None)
        return {
            "raw_metric_code": "corrected_surface_water_distance_km",
            "transform_code": transform,
            "p0": params[0],
            "p1": params[1],
            "p2": params[2],
            "p3": params[3],
            "required": 0 if deferred else 1,
            "missing_policy": missing_policy,
        }

    if component_code == "FLOOD_COMPATIBILITY":
        tolerance = policy["flood_tolerance"]
        if deferred:
            transform, params = "DEFERRED", (None, None, None, None)
        elif tolerance == "HIGH":
            transform, params = "CONSTANT", (1.0, None, None, None)
        elif tolerance == "MODERATE":
            transform, params = "RANGE_TRAPEZOID", (0.0, 0.0, 0.55, 1.0)
        else:
            transform, params = "LOW_BETTER", (0.0, 1.0, None, None)
        return {
            "raw_metric_code": "flood_exposure_index",
            "transform_code": transform,
            "p0": params[0],
            "p1": params[1],
            "p2": params[2],
            "p3": params[3],
            "required": 0 if deferred else 1,
            "missing_policy": missing_policy,
        }

    simple: dict[str, tuple[str, str, tuple[Any, Any, Any, Any], int]] = {
        "CORE_CAPACITY": (
            "developable_area_r1_km2",
            "HIGH_BETTER",
            (0.0, policy["core_target_km2"], None, None),
            required,
        ),
        "EXPANSION_CAPACITY": (
            "developable_area_r5_km2",
            "HIGH_BETTER",
            (0.0, policy["expansion_target_km2"], None, None),
            required,
        ),
        "LAND_ACCESS": (
            "land_access_cost_index",
            "LOW_BETTER",
            (0.0, 1.0, None, None),
            0 if deferred else 1,
        ),
        "WATER_ACCESS": (
            "water_access_index",
            "HIGH_BETTER",
            (0.0, 1.0, None, None),
            0 if deferred else 1,
        ),
        "SEASONAL_RELIABILITY": (
            "seasonal_reliability_index",
            "HIGH_BETTER",
            (0.0, 1.0, None, None),
            required,
        ),
        "DOMAIN_FIT": (
            "domain_fit_index",
            "HIGH_BETTER",
            (0.0, 1.0, None, None),
            required,
        ),
    }
    raw_metric, transform, params, component_required = simple[component_code]
    if deferred:
        transform = "DEFERRED"
        params = (None, None, None, None)
    if (
        component_code == "DOMAIN_FIT"
        and policy["capacity_metric_kind"] == "PROVISIONAL_DOMAIN_CONTEXT"
    ):
        component_required = 0
        missing_policy = "REVIEW_OR_PROVINCE_FALLBACK"
    return {
        "raw_metric_code": raw_metric,
        "transform_code": transform,
        "p0": params[0],
        "p1": params[1],
        "p2": params[2],
        "p3": params[3],
        "required": component_required,
        "missing_policy": missing_policy,
    }


def profile_component_rows(
    connection: sqlite3.Connection,
    profiles: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if profiles is None:
        profiles = profile_catalog_rows(connection)

    rows: list[dict[str, Any]] = []
    for profile in profiles:
        policy, _ = _resolved_policy(
            str(profile["realised_settlement_form"]),
            str(profile["effective_vertical_domain"]),
            str(profile["haus_id"]),
        )
        weights = WEIGHT_SETS[policy["weight_set_code"]]
        for component_code in COMPONENT_CODES:
            rule = _component_rule(policy, component_code)
            rows.append(
                {
                    "profile_id": profile["profile_id"],
                    "component_code": component_code,
                    "component_group": (
                        "CAPACITY"
                        if component_code in CAPACITY_COMPONENTS
                        else "ACCESS"
                    ),
                    "raw_metric_code": rule["raw_metric_code"],
                    "transform_code": rule["transform_code"],
                    "p0": rule["p0"],
                    "p1": rule["p1"],
                    "p2": rule["p2"],
                    "p3": rule["p3"],
                    "weight": weights[component_code],
                    "required": rule["required"],
                    "missing_policy": rule["missing_policy"],
                }
            )
    rows.sort(key=lambda row: (row["profile_id"], row["component_code"]))
    return rows


def score_policy(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return the resolved scoring policy for one profile-catalog row."""

    policy, basis = _resolved_policy(
        str(profile["realised_settlement_form"]),
        str(profile["effective_vertical_domain"]),
        str(profile["haus_id"]),
    )
    return {
        "capacity_operator": policy["capacity_operator"],
        "access_operator": policy["access_operator"],
        "band_thresholds": tuple(policy["band_thresholds"]),
        "weight_set_code": policy["weight_set_code"],
        "weights": dict(WEIGHT_SETS[policy["weight_set_code"]]),
        "components": {
            component_code: _component_rule(policy, component_code)
            for component_code in COMPONENT_CODES
        },
        "policy_basis": tuple(basis),
    }


def build_profile_rows(
    connection: sqlite3.Connection,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, str]],
]:
    """Build resolved profiles, components and the exact site-profile map."""

    profiles = profile_catalog_rows(connection)
    components = profile_component_rows(connection, profiles)
    profile_by_key = {
        (
            str(row["haus_id"]),
            str(row["realised_settlement_form"]),
            str(row["effective_vertical_domain"]),
        ): str(row["profile_id"])
        for row in profiles
    }
    owners = derive_owner_map(connection)
    settlement_rows = connection.execute(
        """
        SELECT
            settlement_id,
            stage6b_realised_settlement_form,
            COALESCE(stage6_vertical_domain_class, vertical_domain_class, 'UNSPECIFIED')
                AS effective_vertical_domain
        FROM settlement
        WHERE stage6_active_settlement=1
        ORDER BY settlement_id
        """
    )
    site_profile_map: dict[str, dict[str, str]] = {}
    for row in settlement_rows:
        settlement_id = str(row["settlement_id"])
        owner = owners[settlement_id]
        key = (
            owner["haus_id"],
            str(row["stage6b_realised_settlement_form"]),
            str(row["effective_vertical_domain"]),
        )
        try:
            profile_id = profile_by_key[key]
        except KeyError as exc:
            raise KeyError(f"No Stage 6C profile for site {settlement_id}: {key}") from exc
        site_profile_map[settlement_id] = {
            "profile_id": profile_id,
            "owner_haus_id": owner["haus_id"],
            "owner_assignment_basis": owner["owner_assignment_basis"],
            "effective_vertical_domain": key[2],
        }
    if len(site_profile_map) != EXPECTED_OWNER_COUNT:
        raise AssertionError(
            f"Expected {EXPECTED_OWNER_COUNT} site-profile assignments, got {len(site_profile_map)}"
        )
    return profiles, components, site_profile_map


def coordinate_semantics_catalog_rows(
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    if connection is not None:
        observed = {
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT json_extract(source_row_json, '$.coordinate_semantics')
                FROM stage6_site_disposition
                WHERE json_extract(source_row_json, '$.coordinate_semantics') IS NOT NULL
                """
            )
        }
        defined = set(SOURCE_COORDINATE_RULES)
        if observed != defined:
            missing = sorted(observed - defined)
            unused = sorted(defined - observed)
            raise AssertionError(
                f"Coordinate semantics mismatch; missing={missing}, unused={unused}"
            )
    rows = [deepcopy(SOURCE_COORDINATE_RULES[key]) for key in sorted(SOURCE_COORDINATE_RULES)]
    rows.extend(deepcopy(list(FALLBACK_COORDINATE_RULES)))
    rows.sort(key=lambda row: row["coordinate_semantics_code"])
    return rows


def coordinate_catalog_rows(
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Compatibility name used by the Stage 6C builder."""

    return coordinate_semantics_catalog_rows(connection)


def _is_half_km_grid(x_km: float, y_km: float) -> bool:
    return abs(x_km * 2.0 - round(x_km * 2.0)) < 1e-9 and abs(
        y_km * 2.0 - round(y_km * 2.0)
    ) < 1e-9


def coordinate_semantics_code_for_site(
    source_semantics: str | None,
    stage6_added_identity: int,
    x_km: float,
    y_km: float,
    stage6_active_location: int = 1,
) -> str:
    if int(stage6_active_location) == 0:
        return "INACTIVE_REJECTED_GRID_POINT"
    if source_semantics is not None:
        try:
            return SOURCE_COORDINATE_RULES[source_semantics][
                "coordinate_semantics_code"
            ]
        except KeyError as exc:
            raise KeyError(f"Unmapped coordinate semantics {source_semantics!r}") from exc
    on_grid = _is_half_km_grid(float(x_km), float(y_km))
    if int(stage6_added_identity) == 1:
        return "STAGE6_ADDED_GRID_ANCHOR" if on_grid else "STAGE6_ADDED_SUBGRID_ANCHOR"
    return (
        "LEGACY_MISSING_SEMANTICS_GRID_POINT"
        if on_grid
        else "LEGACY_MISSING_SEMANTICS_SUBGRID_POINT"
    )


def coordinate_semantics_assignment_rows(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    catalog = {
        row["coordinate_semantics_code"]: row
        for row in coordinate_semantics_catalog_rows(connection)
    }
    query = """
    WITH semantics AS (
        SELECT
            source_site_id,
            MAX(json_extract(source_row_json, '$.coordinate_semantics'))
                AS source_coordinate_semantics
        FROM stage6_site_disposition
        GROUP BY source_site_id
    )
    SELECT
        s.settlement_id,
        s.display_x_km,
        s.display_y_km,
        s.stage6_added_identity,
        s.stage6_active_location,
        s.stage6_active_settlement,
        semantics.source_coordinate_semantics
    FROM settlement s
    LEFT JOIN semantics ON semantics.source_site_id = s.settlement_id
    ORDER BY s.settlement_id
    """
    result: list[dict[str, Any]] = []
    for row in connection.execute(query):
        code = coordinate_semantics_code_for_site(
            row["source_coordinate_semantics"],
            row["stage6_added_identity"],
            row["display_x_km"],
            row["display_y_km"],
            row["stage6_active_location"],
        )
        rule = catalog[code]
        result.append(
            {
                "settlement_id": row["settlement_id"],
                "original_display_x_km": row["display_x_km"],
                "original_display_y_km": row["display_y_km"],
                "coordinate_semantics_code": code,
                "coordinate_value_resolution_km": rule["value_resolution_km"],
                "coordinate_precision_basis": rule["basis"],
                "anchor_status": rule["anchor_status"],
                "provisional_anchor": rule["provisional_anchor"],
                "horizontal_uncertainty_shape": rule[
                    "horizontal_uncertainty_shape"
                ],
                "horizontal_uncertainty_radius_km": rule[
                    "default_horizontal_uncertainty_radius_km"
                ],
                "vertical_uncertainty_status": rule[
                    "vertical_uncertainty_status"
                ],
                "footprint_status": rule["footprint_status"],
                "stage6_active_settlement": row["stage6_active_settlement"],
            }
        )
    return result


def analysis_status_for(
    *,
    stage6_active_location: int,
    stage6_active_settlement: int,
    conditionality_status: str | None,
    effective_vertical_domain: str,
) -> str:
    """Return the mutually exclusive Stage 6C analysis-status category."""

    if int(stage6_active_location) == 0:
        return "INACTIVE"
    if int(stage6_active_settlement) == 0:
        return "NOT_APPLICABLE_NONSETTLEMENT"
    if effective_vertical_domain in SPECIALIST_3D_DOMAINS:
        return "DEFERRED_SPECIALIST_3D"
    if conditionality_status in {
        "CONDITIONAL_FIELD_SITE",
        "WORK_SITE_PERMANENCE_UNRESOLVED",
    }:
        return "READY_2D_CONDITIONAL"
    return "READY_2D_CURRENT"


def _validate_weight_sets() -> None:
    for code, weights in WEIGHT_SETS.items():
        if set(weights) != set(COMPONENT_CODES):
            raise AssertionError(f"Weight-set coverage mismatch for {code}")
        capacity_sum = sum(weights[key] for key in CAPACITY_COMPONENTS)
        access_sum = sum(weights[key] for key in ACCESS_COMPONENTS)
        if not math.isclose(capacity_sum, 1.0, abs_tol=1e-12):
            raise AssertionError(f"Capacity weights for {code} sum to {capacity_sum}")
        if not math.isclose(access_sum, 1.0, abs_tol=1e-12):
            raise AssertionError(f"Access weights for {code} sum to {access_sum}")


def self_check(path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    _validate_weight_sets()
    if len(FORM_POLICIES) != 30:
        raise AssertionError(f"Expected 30 form policies, got {len(FORM_POLICIES)}")
    if len(DOMAIN_MODIFIERS) != 12:
        raise AssertionError(
            f"Expected 12 domain modifiers, got {len(DOMAIN_MODIFIERS)}"
        )

    with read_only_connection(path) as connection:
        owners = owner_rows(connection)
        base = base_policy_rows(connection)
        profiles = profile_catalog_rows(connection)
        components = profile_component_rows(connection, profiles)
        coordinate_catalog = coordinate_semantics_catalog_rows(connection)
        coordinate_assignments = coordinate_semantics_assignment_rows(connection)

        if len(owners) != EXPECTED_OWNER_COUNT:
            raise AssertionError(f"Expected {EXPECTED_OWNER_COUNT} owners, got {len(owners)}")
        if len({row['settlement_id'] for row in owners}) != EXPECTED_OWNER_COUNT:
            raise AssertionError("Owner derivation is not one row per active settlement")
        if len(base) != EXPECTED_BASE_PROFILE_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_BASE_PROFILE_COUNT} base policies, got {len(base)}"
            )
        if len(profiles) != EXPECTED_RESOLVED_PROFILE_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_RESOLVED_PROFILE_COUNT} profiles, got {len(profiles)}"
            )
        if len(components) != EXPECTED_PROFILE_COMPONENT_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_PROFILE_COMPONENT_COUNT} component rows, got {len(components)}"
            )
        if len(coordinate_catalog) != EXPECTED_COORDINATE_CLASS_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_COORDINATE_CLASS_COUNT} coordinate classes, got {len(coordinate_catalog)}"
            )
        if len(coordinate_assignments) != EXPECTED_REGISTRY_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_REGISTRY_COUNT} coordinate assignments, got {len(coordinate_assignments)}"
            )

        observed_profile_keys = {
            (
                row["haus_id"],
                row["realised_settlement_form"],
                row["effective_vertical_domain"],
            )
            for row in profiles
        }
        if len(observed_profile_keys) != EXPECTED_RESOLVED_PROFILE_COUNT:
            raise AssertionError("Resolved profile keys are not unique")

        unused_overrides = sorted(set(HAUS_OVERRIDES) - observed_profile_keys)
        if unused_overrides:
            raise AssertionError(f"Unused Haus overrides: {unused_overrides}")

        component_counts: dict[str, int] = {}
        group_weight_sums: dict[tuple[str, str], float] = {}
        for row in components:
            component_counts[row["profile_id"]] = (
                component_counts.get(row["profile_id"], 0) + 1
            )
            key = (row["profile_id"], row["component_group"])
            group_weight_sums[key] = group_weight_sums.get(key, 0.0) + float(
                row["weight"]
            )
        if set(component_counts.values()) != {EXPECTED_COMPONENTS_PER_PROFILE}:
            raise AssertionError("Each profile must have exactly nine component rows")
        bad_weight_groups = {
            key: value
            for key, value in group_weight_sums.items()
            if not math.isclose(value, 1.0, abs_tol=1e-12)
        }
        if bad_weight_groups:
            raise AssertionError(f"Profile component weights do not sum to one: {bad_weight_groups}")

        provisional_registry_count = sum(
            int(row["provisional_anchor"]) for row in coordinate_assignments
        )
        provisional_settlement_count = sum(
            int(row["provisional_anchor"])
            for row in coordinate_assignments
            if int(row["stage6_active_settlement"]) == 1
        )
        if provisional_registry_count != EXPECTED_PROVISIONAL_REGISTRY_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_PROVISIONAL_REGISTRY_COUNT} provisional registry anchors, got {provisional_registry_count}"
            )
        if provisional_settlement_count != EXPECTED_PROVISIONAL_SETTLEMENT_COUNT:
            raise AssertionError(
                f"Expected {EXPECTED_PROVISIONAL_SETTLEMENT_COUNT} provisional settlement anchors, got {provisional_settlement_count}"
            )

        owner_basis_counts: dict[str, int] = {}
        for row in owners:
            owner_basis_counts[row["owner_assignment_basis"]] = (
                owner_basis_counts.get(row["owner_assignment_basis"], 0) + 1
            )
        expected_owner_basis = {
            "SETTLEMENT_MEMBERSHIP": 28_400,
            "ADDED_TARGET_HAUS": 1_697,
        }
        if owner_basis_counts != expected_owner_basis:
            raise AssertionError(
                f"Owner-basis counts changed: {owner_basis_counts} != {expected_owner_basis}"
            )

        profiles_per_haus: dict[str, int] = {}
        for row in profiles:
            profiles_per_haus[row["haus_id"]] = (
                profiles_per_haus.get(row["haus_id"], 0) + 1
            )

        return {
            "status": "PASS",
            "source_db": str(Path(path).resolve()),
            "method_version": METHOD_VERSION,
            "canon_status": CANON_STATUS,
            "form_policy_count": len(FORM_POLICIES),
            "domain_modifier_count": len(DOMAIN_MODIFIERS),
            "base_policy_count": len(base),
            "resolved_profile_count": len(profiles),
            "profile_component_count": len(components),
            "coordinate_class_count": len(coordinate_catalog),
            "coordinate_assignment_count": len(coordinate_assignments),
            "owner_count": len(owners),
            "owner_basis_counts": owner_basis_counts,
            "profiles_per_haus": dict(sorted(profiles_per_haus.items())),
            "provisional_registry_count": provisional_registry_count,
            "provisional_settlement_count": provisional_settlement_count,
            "haus_override_count": len(HAUS_OVERRIDES),
            "base_policy_sha256": _canonical_hash(base),
            "profile_catalog_sha256": _canonical_hash(profiles),
            "profile_component_sha256": _canonical_hash(components),
            "coordinate_catalog_sha256": _canonical_hash(coordinate_catalog),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        default=DEFAULT_DB,
        help="Verified Stage 6B SQLite source (opened immutable/read-only).",
    )
    args = parser.parse_args(argv)
    print(json.dumps(self_check(args.database), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
