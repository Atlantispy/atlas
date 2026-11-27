"""Check finite-stock collar adoption through the real one-cell transport path.

Run with python -B -I tools/e4_collar_finite_adoption.py <package parent>.
SPDX-License-Identifier: AGPL-3.0-only
"""

import argparse
from contextlib import nullcontext
from fractions import Fraction
import hashlib
from importlib.util import find_spec
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


class FiniteCollarAdoption(unittest.TestCase):
    def test_adopts_the_producers_graph_content_identity(self):
        import numpy as np
        from threadpoolctl import threadpool_limits

        layout = find_spec('atlas_tectonics.integration')
        if layout is not None and layout.submodule_search_locations is not None:
            from atlas_tectonics.integration.coupling import spatial_ale as ale
            from atlas_tectonics.integration.heat.mimetic_heat import _enc
            from atlas_tectonics.integration.coupling.spatial_reservoir import PreparedFiniteStocks
            from atlas_tectonics.integration.coupling.spatial_transport import PreparedSpatialTransport
            from atlas_tectonics.regional.collar3d import PreparedRegionalCollar3D
            from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
            from atlas_tectonics.integration.resources import WorkBudget
        else:
            from atlas_tectonics import integration_spatial_ale as ale
            from atlas_tectonics.integration_mimetic_heat import _enc
            from atlas_tectonics.integration_spatial_reservoir import PreparedFiniteStocks
            from atlas_tectonics.integration_spatial_transport import PreparedSpatialTransport
            from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D
            from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
            from atlas_tectonics.resources import WorkBudget

        names = ('component_mass_kg:0', 'component_mass_kg:1', 'enthalpy_j',
                 'tracer:damage', 'tracer:accumulated_strain_ii')
        nonnegative = tuple(name for name in names if name != 'enthalpy_j')
        receipts = [{'source_sha256': 'a' * 64}]
        physical_graph = dict(
            cells=[dict(cell_id='physical', kind='exterior', start_volume_m3=_enc(1), end_volume_m3=_enc(2))],
            transfers=[], source='independently declared analytical one-cell fixture',
            physical_measure_receipts=receipts,
        )
        stock = dict(stock_id='ridge', kind='source', lineage=dict(source='declared analytical stock:ridge'),
                     volume_m3=_enc(1), exact=dict(zip(names, map(_enc, (3, 1, -2, 0, 0)), strict=True)))
        donor_amounts = (Fraction(3, 2), Fraction(1, 2), Fraction(3), Fraction(0), Fraction(0))
        donor = {name: (amount,) for name, amount in zip(names, donor_amounts, strict=True)}
        exchange = dict(stock_id='ridge', physical_cell_id='physical', direction='supply', face_id='ridge:wall',
                        volume_m3=_enc(1), physical_certificate_id='analytic unit wall')

        budget = WorkBudget(64 << 20)
        with PreparedFiniteStocks('adoption registry', [stock], field_names=names,
                                  nonnegative_fields=nonnegative, budget=budget) as owner:
            proposal = owner.prepare(owner.initial(), physical_graph, donor, [exchange],
                                     source_stage_id='source', transport_parent_id='spatial-parent')
            augmented_graph, stocks = proposal._transport_inputs()
            self.assertEqual(augmented_graph['physical_measure_receipts'], receipts)
            with threadpool_limits(1), PreparedSpatialTransport(augmented_graph, budget=budget) as operator:
                result = operator.advance(
                    stocks, state_id='spatial-parent', source_stage_id='source',
                    max_projection_errors=dict.fromkeys(names, Fraction(1, 10**11)),
                    nonnegative_fields=nonnegative,
                )
                byte_id = hashlib.sha256(operator._encoded).hexdigest()
            geometry_id = result.record()['geometry_id']
            self.assertNotEqual(byte_id, geometry_id)
            print(f'producer_geometry_id={geometry_id} augmented_graph_byte_id={byte_id}', flush=True)

            fields = {'component_mass_kg': np.array([1.5, .5]).reshape((2, 1, 1, 1)),
                      'enthalpy_j': np.full((1, 1, 1), 3.), 'tracer:damage': np.zeros((1, 1, 1)),
                      'tracer:accumulated_strain_ii': np.zeros((1, 1, 1))}
            source = SimpleNamespace(
                result_id='source', parent_state_id='native-parent', inventory=RegionalMechanicalSnapshot({}, fields),
                duration_s=.125, parent=SimpleNamespace(), source_stage=SimpleNamespace(), flow=SimpleNamespace(),
                heat_source_id='heat',
            )
            collar = SimpleNamespace(
                _budget=budget, _work_bytes=0, plan_id='collar', cells=(1, 1, 1),
                _operation=lambda cancel: nullcontext(), _spatial_layout=lambda source, graph: (physical_graph, (0,)),
                _native=SimpleNamespace(_composition=(0., 1.)), _verify=lambda: None,
                _registry=SimpleNamespace(registry_id=owner.definition()['registry_id']),
            )
            physical = ale._issue(ale.SpatialALEGraph, physical_graph, budget)
            adopted = PreparedRegionalCollar3D.transport_from_spatial(
                collar, source, result, physical, method='implicit-upwind', finite_proposal=proposal,
            )
            self.assertIs(adopted.finite_proposal, proposal)
            adopted_id = adopted.transport.descriptor()['augmented_graph_id']
            self.assertEqual(adopted_id, geometry_id)
            print(f'adopted_augmented_graph_id={adopted_id}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package_parent', type=Path)
    package_parent = parser.parse_args().package_parent.resolve()
    if not (package_parent / 'atlas_tectonics' / '__init__.py').is_file():
        parser.error('package_parent must contain the selected atlas_tectonics package')
    sys.path.insert(0, str(package_parent))
    unittest.main(argv=[sys.argv[0]])
