"""Explicit finite, prescribed mixed receiver; not a hydraulic solver.

Dry-source particles carry no pore water. Receiver saturation draws liquid
from its finite free-water stock. Applicability/owner binding must be supplied.
No overflow, evaporation, backflow, infiltration or unreported import exists.
"""
from dataclasses import dataclass
from fractions import Fraction as F
from . import materials as m


@dataclass(frozen=True)
class FiniteReceiver:
    receiver_id: str
    area_m2: F
    floor_m: F
    rim_m: F
    outlet_control_m: F
    initial_water_m3: F
    deposit_porosity: F
    source_water_limit_m3: F
    evidence: str

    def __post_init__(self):
        for name in ('area_m2', 'initial_water_m3', 'deposit_porosity', 'source_water_limit_m3'):
            object.__setattr__(self, name, m.q(getattr(self, name), name, positive=name == 'area_m2'))
        for name in ('floor_m', 'rim_m', 'outlet_control_m'):
            value = getattr(self, name)
            if type(value) not in (int, float, F):
                raise ValueError('explicit finite receiver elevation required')
            object.__setattr__(self, name, F(value))
        if (not self.receiver_id or not self.evidence or not self.floor_m < self.rim_m < self.outlet_control_m
                or self.deposit_porosity >= 1):
            raise ValueError('resolved finite receiver geometry/packing/evidence required')
        self.account(F(), F())

    def account(self, cumulative_liquid_m3, cumulative_solid_m3):
        liquid = m.q(cumulative_liquid_m3, 'receiver cumulative liquid')
        solid = m.q(cumulative_solid_m3, 'receiver cumulative solid')
        if liquid > self.source_water_limit_m3:
            raise ValueError('finite effective runoff source exhausted')
        bulk = solid / (1 - self.deposit_porosity)
        pores = bulk * self.deposit_porosity
        free = self.initial_water_m3 + liquid - pores
        bed = self.floor_m + bulk / self.area_m2
        stage = bed + free / self.area_m2
        if free < 0 or bed >= self.rim_m or stage >= self.rim_m or stage >= self.outlet_control_m:
            raise ValueError('finite receiver requires unresolved drying/overflow/backwater regime')
        if (free + pores != self.initial_water_m3 + liquid
                or bulk * (1 - self.deposit_porosity) != solid):
            raise ArithmeticError('exact finite receiver water/solid closure failed')
        return {'receiver_id': self.receiver_id, 'cumulative_liquid_m3': liquid,
                'cumulative_solid_m3': solid, 'sediment_bulk_m3': bulk,
                'pore_water_m3': pores, 'free_water_m3': free,
                'bed_m': bed, 'stage_m': stage, 'rim_m': self.rim_m,
                'outlet_control_m': self.outlet_control_m, 'evidence': self.evidence,
                'regime': 'PRESCRIBED_FINITE_UNIFORM_SATURATED_DEPOSIT_DRY_SOURCE_NO_BACKWATER',
                'hydraulic_solution_claimed': False}
