"""One-time physical carve-out for finite open-base boundary compartments.

The full mechanical domain has no rigid collar. Each reservoir is an actual
adjacent Cartesian prism removed from the surrounding rigid source. It is then
an explicitly well-mixed boundary compartment, not a claim to locate the
unmodelled moving interface inside the depleted reservoir. Its imposed pressure
and traction are external mechanical boundary conditions, not generated heat.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import hashlib
import json
import weakref

from atlas_tectonics.integration import material as M
from atlas_tectonics.integration import support as U
from atlas_tectonics.integration.geometry import volume as V
from atlas_tectonics.integration.geometry.collar_geometry import FullCellFunding
from atlas_tectonics.integration.heat.mimetic_heat import _enc, _q
from atlas_tectonics.integration.coupling.regional_inventory import _width
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot


def _json(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(record):
    return hashlib.sha256(_json(record)).hexdigest()


def carve_basal_inventory(funding, sphere, moving, collar, reservoirs, *, budget, compartment_kind='source'):
    """Propose finite stock once; publication remains the workflow's operation.

    At most one uniform prism per boundary FV face. The source patch/layer must
    contain that whole exact prism. No partial coverage, extrapolated material,
    fresh-temperature reseeding, or implicit infinite supply is accepted.
    The legacy default only supplies material. Explicit 'reservoir' also
    receives material into the same finite, well-mixed compartment; its gross
    incoming/outgoing fluxes are solved jointly, not replaced by their net.
    """
    record = funding.descriptor()
    record.pop('funding_id')
    with budget.reserve(131072+12*_width(record)+8192*len(reservoirs), category='finite-basal-funding'):
        native = collar._native
        cells = collar.cell_geometries()
        base = cells[0]
        lower = tuple(min(c.lower_m[j] for c in cells) for j in range(3))
        upper = tuple(max(c.upper_m[j] for c in cells) for j in range(3))
        spacing = tuple((b-a)/n for a, b, n in zip(lower, upper, collar.cells))
        keys = tuple(map(tuple, record['component_keys']))
        names = tuple('component_mass_kg:'+str(i) for i in range(len(native._composition)))
        names += ('enthalpy_j',)+tuple(sorted(k for k in funding.arrays() if k.startswith('tracer:')))
        remainder = {(r['patch_id'], r['sublayer']): r for r in record['exterior_remainder']}
        patches = {p.patch_id: p for p in U.required(sphere.material).patches}
        physical = dict(moving._physical_columns)
        stock_rows, boxes, debits = [], [], []
        sides = {r.side for r in reservoirs}
        side = next(iter(sides))
        axis, end = 'xyz'.index(side[0]), int(side[1])
        for spec in sorted(reservoirs, key=lambda r: (r.side, r.face_index)):
            tangential = [j for j in range(3) if j != axis]
            lo, hi = list(lower), list(upper)
            lo[axis], hi[axis] = ((lower[axis]-spec.depth_m, lower[axis]) if end == 0 else
                                  (upper[axis], upper[axis]+spec.depth_m))
            for i, j in zip(spec.face_index, tangential):
                lo[j], hi[j] = lower[j]+i*spacing[j], lower[j]+(i+1)*spacing[j]
            box = V.CartesianCell(tuple(lo), tuple(hi), base.origin_m, base.basis, budget=budget)
            key = spec.patch_id, spec.sublayer
            patch = patches[spec.patch_id]
            column = moving.cohort(patch.cohort_id)
            heights, areal, _ = physical[spec.patch_id]
            shells = M.layer_geometry(column, heights, budget=budget)
            shell, layer = shells[spec.sublayer], column.sublayers[spec.sublayer]
            try:
                (V.convex_cone_union(patch.cells, budget=budget),)
            except V.VolumeError:
                pass
            # The same current physical per-volume fields used by full-cell
            # funding, not averages re-derived from rounded extensive stocks.
            rho, cp = Q(layer.reference_density_kg_m3), Q(layer.heat_capacity_j_kg_k)
            density_energy = areal[spec.sublayer]/shell.volume_per_area_m+rho*cp*Q(moving.enthalpy_reference_k)
            volume = box.volume_m3
            bounds = tuple(map(_q, remainder[key]['geometry_volume_enclosure_m3']))
            remainder[key]['geometry_volume_enclosure_m3'] = list(map(_enc, (bounds[0]-volume, bounds[1]-volume)))
            remainder[key]['geometry'] = 'actual source cone/shell minus native cells and finite basal prism union'
            fields = dict.fromkeys(names, Q(0))
            fields['component_mass_kg:'+str(keys.index(key))] = rho*volume
            fields['enthalpy_j'] = density_energy*volume
            fields['tracer:source_kappa'] = rho*volume*Q(column.kappa[spec.sublayer])
            debit = dict(zip(('volume_m3', 'mass_kg', 'enthalpy_j', 'source_kappa_mass_kg'),
                             (volume, rho*volume, fields['enthalpy_j'], fields['tracer:source_kappa'])))
            old = remainder[key]['stocks']
            for name, amount in debit.items():
                remaining = _q(old[name])-amount
                if remaining < 0:
                    raise V.VolumeError('actual source remainder cannot fund the finite basal prism')
                old[name] = _enc(remaining)
            lineage = dict(kind='finite-basal-reservoir', source_id=funding.funding_id,
                source=record['source'], source_key=list(key), reservoir=spec.record(),
                physical_cell_id=box.cell_id, physical_cell=box.record(),
                model='finite initially homogeneous boundary compartment; remaining spatial interface unmodelled')
            if compartment_kind != 'source':
                lineage['compartment_kind'] = compartment_kind
            stock_rows.append(dict(stock_id='basal:'+_hash({k: v for k, v in lineage.items() if k != 'source_id'}), kind=compartment_kind, lineage=lineage,
                                   volume_m3=_enc(volume), exact={k: _enc(v) for k, v in fields.items()}))
            boxes.append(box.record())
            debits.append(dict(source_key=list(key), cell_id=box.cell_id,
                               exact={k: _enc(v) for k, v in debit.items()}))
        record['exterior_remainder'] = [remainder[k] for k in sorted(remainder)]
        record['excluded_static_cells'] = boxes
        record['basal_inventory'] = dict(schema='atlas.finite-basal-funding.v1', base_funding_id=funding.funding_id,
            side=side, reservoirs=[r.record() for r in sorted(reservoirs, key=lambda r: (r.side, r.face_index))],
            stocks=stock_rows, exact_debits=debits,
            disjointness='one coordinate outside native box, tangential face cells disjoint; removed from rigid exterior',
            pressure_work='declared basal traction work remains external mechanical boundary work')
        if compartment_kind != 'source':
            record['basal_inventory']['compartment_kind'] = compartment_kind
        snapshot = RegionalMechanicalSnapshot(record, funding.arrays())
        result = object.__new__(FullCellFunding)
        object.__setattr__(result, '_snapshot', snapshot)
        object.__setattr__(result, '_resource', budget)
        object.__setattr__(result, '_source_volume_proven', getattr(funding, '_source_volume_proven', False))
        lease = budget.reserve(8192+2*snapshot.nbytes, category='finite-basal-funding-retained')
        lease.__enter__()
        try:
            weakref.finalize(result, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None)
            raise
        return result


def validate_basal_rows(funding, stocks):
    """Actual one-time funding, with optional B=G at initial admission only."""
    expected = funding.descriptor().get('basal_inventory', {}).get('stocks', [])
    supplied = [r for r in stocks if r.get('lineage', {}).get('kind') == 'finite-basal-reservoir']
    physical = []
    for row in supplied:
        if 'material_quadrature_m3' in row['exact']:
            row = dict(row, exact={k: v for k, v in row['exact'].items() if k != 'material_quadrature_m3'})
        physical.append(row)
    if sorted(physical, key=lambda r: r['stock_id']) != sorted(expected, key=lambda r: r['stock_id']):
        raise V.VolumeError('finite basal rows differ from the actual one-time geometric funding')
