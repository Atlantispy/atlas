from fractions import Fraction as Q

from atlas_tectonics import integration_wall_measures as W

from atlas_tectonics.integration_regional_workflow import CollarWorkflow, retained_inventory_accounts

def operations(collar):
    def strip(value):
        return {k: strip(v) for k, v in value.items() if k != 'budget'} if isinstance(value, dict) else value
    return tuple(strip(p.statistics()) for p in (collar._native, collar._transport, collar._heat))

def exact_fields(snapshot):
    totals = {f'component_mass_kg:{i}': sum((Q(float(v)) for v in a.flat), Q(0))
              for i, a in enumerate(snapshot.array('component_mass_kg'))}
    totals.update({k: sum((Q(float(v)) for v in snapshot.array(k).flat), Q(0))
                   for k in snapshot.array_names if k != 'component_mass_kg'})
    return totals

def check_global_accounts(test, before_exterior, source, result):
    """Exact physical inventories plus separate cumulative numerical accounts."""
    def complete(collar_state, exterior_state):
        report = retained_inventory_accounts(collar_state, exterior_state, budget=exterior_state._budget)
        return {name: W._decode(value) for name, value in report['accounted'].items()}

    old = complete(source.parent, before_exterior)
    new = complete(result.state, result.exterior.state)
    before, donor = exact_fields(source.parent.fields), exact_fields(source.inventory)
    booked = {k: donor[k]-before[k] for k in before}
    audit = result.collar.source_stage.source_audit
    total = lambda name: sum((Q(float(v)) for v in audit.array(name).flat), Q(0))
    test.assertEqual(booked['enthalpy_j'], total('enthalpy_after_sources_j')-total('enthalpy_before_sources_j'))
    test.assertEqual(booked['tracer:accumulated_strain_ii'],
                     total('strain_history_after_sources_kg')-total('strain_history_before_kg'))
    for name, value in booked.items():
        if name not in ('enthalpy_j', 'tracer:accumulated_strain_ii'):
            test.assertEqual(value, 0, name)  # This Newtonian control has no other source.
    heat = result.exterior._heat.descriptor()
    outgoing = W._decode(heat['exact_outward_boundary_energy_j'])
    heating = W._decode(heat['exact_source_energy_j'])
    test.assertEqual(outgoing, 0)
    test.assertEqual(heating, 0)  # Native sources have already been booked once.
    requested = total('requested_source_energy_j')
    source_addition_rounding = requested-booked['enthalpy_j']
    for name in old:
        expected = old[name]+booked[name]
        if name == 'enthalpy_j':
            expected = old[name]+requested-source_addition_rounding+heating-outgoing
        test.assertEqual(new[name], expected, name)
