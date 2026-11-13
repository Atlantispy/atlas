from fractions import Fraction as Q

from atlas_tectonics import integration_collar_geometry as G

def fund(source, owner, collar, budget):
    return G.fund_full_cells(*source[:2], collar, owner, max_cell_volume_width_m3=Q(1, 10**8),
        max_field_errors=dict(mass_kg=Q(0), enthalpy_j=Q(1, 10**7), source_kappa_mass_kg=Q(0)),
        max_leaves=512, budget=budget)
