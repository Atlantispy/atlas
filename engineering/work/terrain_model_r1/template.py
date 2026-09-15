"""Explicit UNKNOWNs for the delivered design; no invented Diadem values."""
from contract import SCHEMA, FAMILIES, GROUPS, TEST_IDS


def make_recipe(sources=None):
    owners = {"frame": "Physical", "structure": "Physical", "history": "Physical/Climate",
              "forcing": "Climate/Water", "base_levels": "Water", "constraints": "Physical/GEO", "numerics": "Engineering"}
    return {
        "schema": SCHEMA, "world_id": "diadem", "world_state": "fixed_snapshot",
        "snapshot_id": None, "source_status": "WORKING NON-CANON",
        "mode": "process_constrained_reconstruction", "mode_status": "ENGINEERING_PROPOSAL_NOT_BOUND",
        "sources": sources or [],
        "frame": {"id": None, "crs": None, "origin": None, "x_direction": None, "y_direction": None,
                  "horizontal_datum": None, "vertical_datum": None, "horizontal_unit": "m", "vertical_unit": "m",
                  "validity": None, "boundaries": None, "spacing_m": None, "effective_support_m": None, "source_ids": []},
        "input_groups": [{"id": group, "state": "UNKNOWN", "owner": owners[group], "source_ids": [],
                          "binding": None, "reason": "Recipe-specific input selection is not supplied by the requirements package."}
                         for group in sorted(GROUPS)],
        "coverage": {"state": "UNKNOWN", "owner": "Physical", "source_ids": [], "domain_inventory_source_ids": [],
                     "coverage_proof": None, "additional_family_inventory": "UNKNOWN",
                     "reason": "Bind all named mountains, intervening terrain and applicable submerged/exceptional relief; no shape inferred from names."},
        "families": [{"id": key, "name": value, "state": "UNKNOWN", "owner": "Physical", "source_ids": [],
                      "support": "NOT_ASSESSED_FOR_NEW_MODEL", "algorithm": None, "domain_binding": None,
                      "parameter_binding": None, "reason": "Applicability is unresolved; this is not proof an older producer is absent."}
                     for key, value in FAMILIES.items()],
        "constraint_inventory": {"state": "UNKNOWN", "owner": "Physical/GEO", "source_ids": [],
                                 "reason": "Bind actual hard/soft/reference roles; predecessor terrain/water/means are not automatically hard."},
        "constraints": [],
        "tests": [{"id": key, "state": "UNKNOWN", "owner": "Climate/Engineering" if key.startswith("CF") else "Water/Engineering" if key.startswith("W") else "Physical/Engineering",
                   "source_ids": [], "reason": "Fixture, applicable law and actual unit-aware tolerance are not yet frozen.",
                   "requirements": key, "regime": None, "parameters": None, "expected": None, "method": None,
                   "acceptance_layer": None,
                   "fixture": {"source_ids": [], "split": None, "shape": None, "spacing_m": None, "seed": None},
                   "tolerance": {"metric": None, "units": None, "atol": None, "rtol": None,
                                 "scale_definition": None, "physical_band": None, "justification": None}}
                  for key in sorted(TEST_IDS)],
        "coupling": {"state": "UNKNOWN", "owner": "Physical/Water/Climate", "source_ids": [],
                     "reason": "Choose and validate coupling for each active recipe; preserve original C1 binding.",
                     "method": None, "stopping_rule": None, "limits": None, "influence_proof": None,
                     "c1_compatibility": None, "meltwater_producer": None, "mass_basis": "reconstruction_geometric_change"},
        "downstream": {"state": "UNKNOWN", "owner": "Engineering/GEO", "source_ids": [],
                       "reason": "Bind old/new water, atmospheric and material influence; filename equality is not compatibility.",
                       "influence_rule": None, "compatibility_rule": None,
                       "dependent_products": ["refinement", "gradients", "water", "climate", "soils", "sites", "resources", "habitats", "routes"]},
        "development_resources": {"max_cells": 16384, "max_workers": 1, "memory_mib": 512,
                                  "storage_mib": 64, "wall_seconds": 120,
                                  "cancellation_rule": "Stop before an allocation/output exceeds its declared envelope; no model execution authorised by this intake."},
        "production_resource_envelope": None,
    }
