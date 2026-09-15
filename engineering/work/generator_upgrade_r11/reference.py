"""Explicit seasonal-consequence reference choices; no biological adoption."""
from . import binding

E = 'SYNTHETIC TEST: connected finite seasonal consequences, not adopted Diadem parameters or production.'


def recipe(bundle):
    return {'schema': binding.RECIPE_SCHEMA, 'source_sha256': bundle.source_sha256,
        'source_status': 'WORKING NON-CANON', 'evidence': E,
        'parent_recipe': bundle.parent.reference.recipe(bundle.parent),
        'parameters': {'routing_substeps_per_shortest_month': 16,
            'network_conductance_multiplier': '1', 'plant_absorbed_light_multiplier': '1',
            'monthly_settlement_water_demand_m3': '4', 'edible_fraction_of_test_harvest': '1/4',
            'food_processing_loss_fraction': '1/10'},
        'reference_laws': 'R11_EXPLICIT_SYNTHETIC_NETWORK_PLANT_AND_HUMAN_CONSEQUENCES',
        'scope': 'All nine independent snow/stand scenarios and both actual R10 cells. Actual parent exports and roots feed new conditional models. No summing alternatives, adopted world map, inferred real food species, historical evolution or optimisation.'}
