"""Exact retained R2 hillslope bridge; no new material law or parameter defaults."""
from dataclasses import replace

from capture import CaptureState, number, vector
from r4_io import io, verify_dependencies


def hillslope_trial(state, *, dx_m, dy_m, diffusivity_m2_year, dt_years):
    if not isinstance(state, CaptureState):
        raise ValueError('R4 capture state required')
    dx = number(dx_m, 'dx', 0, True); dy = number(dy_m, 'dy', 0, True)
    dt = number(dt_years, 'dt', 0, True)
    k = vector(diffusivity_m2_year, state.size, 'diffusivity', 0)
    if any(a != dx * dy for a in state.cell_area_m2):
        raise ValueError('retained rectangular hillslope law requires original uniform native area')
    if not any(k):
        return state, {'process': 'hillslope_transport', 'internal_transferred_solid_m3': 0.,
                       'solid_volume_residual_m3': 0., 'mass_residual_kg': 0.,
                       'explicit_cfl': 0., 'boundary': 'closed material flux',
                       'retained_zero_forcing_identity': True}
    verify_dependencies()
    grid = io.Grid(state.shape[0], state.shape[1], dx, dy)
    prior = io.State(grid, state.bedrock_m, state.bed_solid_m3, (0.,) * state.size,
                     state.solid_density_kg_m3, state.solid_density_kg_m3)
    kernel = io.advance.__globals__['hillslope_step']
    following, report = kernel(prior, k, dt)
    result = replace(state, bedrock_m=following.bedrock_m,
                     bed_solid_m3=following.mobile_solid_m3)
    if result.liquid_m3 != state.liquid_m3 or result.suspended_solid_m3 != state.suspended_solid_m3:
        raise ValueError('hillslope bridge changed a phase inventory')
    return result, report
