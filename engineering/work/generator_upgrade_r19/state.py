"""Exact material/liquid stocks with disclosed binary64 momentum/flux laws."""
from dataclasses import dataclass
from fractions import Fraction as F
import math

from work.generator_upgrade_r16 import columns, regional
from work.generator_upgrade_r18 import composite


def q(value, name='coastal quantity', *, positive=False, nonnegative=False):
    return columns._q(value, name, positive=positive, nonnegative=nonnegative)


def represented(value):
    """Represent a constitutive amount once; subsequent stock entries are exact."""
    value = q(value, nonnegative=True)
    number = float(value)
    if not math.isfinite(number) or (value and number == 0):
        raise ValueError('coastal transfer is not representable in binary64')
    return F(number)


def plain(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def density(mid, palette):
    return q(palette[mid]['grain_density_kg_m3'], positive=True)


@dataclass
class Cell:
    column: object
    pores: list
    free: F
    suspended: dict
    momentum: tuple = (0., 0.)
    kind: str = 'water'

    def volume(self, palette):
        return q(self.free + sum((mass/density(mid, palette) for mid, mass in self.suspended.items()), F()), nonnegative=True)

    def depth(self, palette):
        return self.volume(palette)/self.column.area_m2

    def eta(self, palette):
        return self.column.surface_m+self.depth(palette)

    def velocity(self, palette):
        volume = self.volume(palette)
        return tuple(value/float(volume) for value in self.momentum) if volume else (0., 0.)

    def validate(self, palette):
        _, native = regional.p.backend()
        if type(self.column) is not native.Column or self.kind not in ('water', 'reach'):
            raise ValueError('native finite coastal column and declared hydraulic support required')
        if type(self.pores) is not list or len(self.pores) != len(self.column.layers):
            raise ValueError('one explicit pore-liquid stock per native layer required')
        self.free = q(self.free, nonnegative=True)
        for i, layer in enumerate(self.column.layers):
            if layer.grain_density_kg_m3 != density(layer.material_id, palette):
                raise ValueError('native density differs from composition-bound coastal identity')
            self.pores[i] = q(self.pores[i], nonnegative=True)
            if self.pores[i] > layer.bulk_volume_m3*layer.porosity:
                raise ValueError('tracked pore water exceeds actual native capacity')
        if type(self.suspended) is not dict:
            raise ValueError('explicit suspended material inventory required')
        for mid, mass in self.suspended.items():
            density(mid, palette)
            self.suspended[mid] = q(mass, nonnegative=True)
        if len(self.momentum) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in self.momentum):
            raise ValueError('finite two-dimensional integrated mixture momentum required')
        if not self.volume(palette) and any(self.momentum):
            raise ValueError('dry cell cannot retain hydrodynamic momentum')

    def as_dict(self):
        return {'column': self.column.as_dict(), 'pores': [str(v) for v in self.pores],
            'free': str(self.free), 'suspended': {k: str(v) for k, v in sorted(self.suspended.items())},
            'momentum': list(self.momentum), 'kind': self.kind}

    @classmethod
    def from_dict(cls, data, palette):
        if set(data) != {'column', 'pores', 'free', 'suspended', 'momentum', 'kind'}:
            raise ValueError('exact coastal cell schema required')
        _, native = regional.p.backend()
        result = cls(native.Column.from_dict(data['column']), [q(v) for v in data['pores']],
            q(data['free']), {k: q(v) for k, v in data['suspended'].items()}, tuple(data['momentum']), data['kind'])
        result.validate(palette)
        return result


def transfer(donor, receiver, palette, mixture_volume):
    """Signed-flow caller chooses donor. This books stocks, NOT momentum.

The phase fluxes are each represented once in binary64, then debited/credited
exactly. Their sum is the actual applied mixture flux; it can differ by roundoff
from the hydrodynamic flux. No material density or fixed constituent fraction is
rounded/redefined by this operation.
"""
    available = donor.volume(palette)
    demand = q(mixture_volume, nonnegative=True)
    if demand > available:
        raise ValueError('coastal face overdraw; reduce the time step')
    if not available or not demand:
        return {'volume': F(), 'fraction': 0., 'free': F(), 'materials': {}}
    fraction = demand/available
    def amount(stock):
        return stock if fraction == 1 else min(stock, represented(stock*fraction))
    liquid = amount(donor.free)
    masses = {mid: amount(mass) for mid, mass in donor.suspended.items()}
    donor_free = q(donor.free-liquid, nonnegative=True)
    receiver_free = q(receiver.free+liquid, nonnegative=True)
    donor_masses = {mid: q(donor.suspended[mid]-mass, nonnegative=True) for mid, mass in masses.items()}
    receiver_masses = {mid: q(receiver.suspended.get(mid, F())+mass, nonnegative=True) for mid, mass in masses.items()}
    donor.free, receiver.free = donor_free, receiver_free
    for mid, mass in masses.items():
        donor.suspended[mid] = donor_masses[mid]
        receiver.suspended[mid] = receiver_masses[mid]
    actual = liquid+sum((mass/density(mid, palette) for mid, mass in masses.items()), F())
    return {'volume': actual, 'fraction': float(actual/available), 'free': liquid, 'materials': masses}


def inventory(cells, palette):
    water = F(); materials = {}
    for cell in cells.values():
        cell.validate(palette)
        water = q(water+cell.free+sum(cell.pores, F()), nonnegative=True)
        for layer in cell.column.layers:
            materials[layer.material_id] = q(materials.get(layer.material_id, F())+layer.mass_kg, nonnegative=True)
        for mid, mass in cell.suspended.items():
            materials[mid] = q(materials.get(mid, F())+mass, nonnegative=True)
    return {'water_m3': water, 'materials_kg': materials,
        'solid_m3': {mid: mass/density(mid, palette) for mid, mass in materials.items()}}


def balances(before, imported, after, palette):
    for record in (before, imported, after):
        q(record['water_m3'], nonnegative=True)
        if set(record['solid_m3']) != set(record['materials_kg']):
            raise ValueError('material/solid inventory identities differ')
        for mid, mass in record['materials_kg'].items():
            if q(record['solid_m3'][mid], nonnegative=True) != q(mass, nonnegative=True)/density(mid, palette):
                raise ArithmeticError('solid inventory differs from bound native grain mass/density')
    water = before['water_m3']+imported['water_m3']-after['water_m3']
    if water:
        raise ArithmeticError('coastal total liquid including bed pores does not close')
    rows, constituents = [], {}
    mids = set(before['materials_kg']) | set(imported['materials_kg']) | set(after['materials_kg'])
    for mid in sorted(mids):
        a, b, c = (record['materials_kg'].get(mid, F()) for record in (before, imported, after))
        if a+b-c:
            raise ArithmeticError('coastal native dry mass does not close')
        if before['solid_m3'].get(mid, F())+imported['solid_m3'].get(mid, F())-after['solid_m3'].get(mid, F()):
            raise ArithmeticError('coastal grain solid volume does not close')
        rows.append({'material_id': mid, 'initial_mass_kg': str(a), 'imported_mass_kg': str(b),
            'final_mass_kg': str(c), 'mass_residual_kg': '0', 'solid_residual_m3': '0'})
        for stage, amount in (('initial', a), ('imported', b), ('final', c)):
            for unit, values in composite.project_mass(mid, amount, palette).items():
                target = constituents.setdefault(unit, {})
                for key, value in values.items():
                    target[stage+'_'+key] = target.get(stage+'_'+key, F())+q(value)
    for row in constituents.values():
        for suffix in ('mass_kg', 'solid_volume_m3'):
            if row['initial_'+suffix]+row['imported_'+suffix]-row['final_'+suffix]:
                raise ArithmeticError('coastal constituent account does not close')
            row['residual_'+suffix] = '0'
    return {'water_residual_m3': '0', 'materials': rows,
        'constituents': [{'unit_id': unit, **plain(row)} for unit, row in sorted(constituents.items())]}
