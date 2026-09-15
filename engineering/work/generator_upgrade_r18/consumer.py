"""Native erosion/terrain use with exact composite constituent stock accounts.

The terrain adapter mirrors R16's bounded interface but parses exact JSON K
values before constructing native properties: R16's direct JSON-only path cannot
carry a non-dyadic Fraction K. The unchanged R14 trial, native validation and
explicit hydrology, mobile-material and sediment laws remain authoritative.
No sorting, selective weathering, dissolution or preferential entrainment is
inferred: transfers carry the composite's congruent well-mixed composition.
"""
from copy import deepcopy
from fractions import Fraction as F
import math

from work.generator_upgrade_r14 import erosion, terrain
from work.generator_upgrade_r16 import regional, columns
from . import accounts, composite, provenance as p


SCOPE = 'CONGRUENT_WELL_MIXED_COMPOSITE_TRANSFERS_NO_COMPONENT_SORTING'


def _reference(value):
    """Bridge exact normalisation to native binary64 inputs without rounding."""
    exact = columns._q(value, 'native reference runoff', positive=True)
    try:
        represented = float(exact)
    except OverflowError as exc:
        raise ValueError('native normalisation is not exactly binary64-representable') from exc
    if not math.isfinite(represented) or F(represented) != exact:
        raise ValueError('native normalisation is not exactly binary64-representable; no rounding')
    return exact.numerator if exact.denominator == 1 else represented


def _state_palette(state, palette):
    if type(palette) is not dict:
        raise ValueError('explicit composite material palette required')
    for mid in palette:
        composite._validated(mid, palette)
    for _, column in state.columns:
        for layer in column.layers:
            if layer.material_id not in palette:
                raise ValueError('native material is absent from composite palette')
            density = columns._q(palette[layer.material_id]['grain_density_kg_m3'], 'bound composite grain density')
            if layer.grain_density_kg_m3 != density:
                raise ValueError('native material grain density differs from composition-bound identity')


def verify(snapshot):
    """Verify current R18/R16 sources, input files, science and grain identity."""
    execution, science = snapshot['execution'], snapshot['scientific']
    binding = execution['regional_input_identity']
    p.verify(binding)
    regional.p.verify(execution['identity'])
    if (science['regional_input']['execution_binding_sha256'] != p.sha(binding)
            or execution['scientific_sha256'] != p.sha(science)):
        raise ValueError('R18 regional input execution/scientific binding differs')
    if science['source_sha256'] != regional.p.sha(execution['identity']):
        raise ValueError('R18 regional native source binding differs')
    if science['source_status'] not in columns.STATUSES:
        raise ValueError('explicit working/synthetic geological input status required')
    regional._owner_source(science['owner_source'])
    regional._owner_source(science['regional_input']['source_package'])
    if 'owner_input' in science['regional_input']:
        regional._owner_source(science['regional_input']['owner_input'])
    columns._q(science['regional_input']['reference_runoff_m_year'], 'bound reference runoff', positive=True)
    _, native = regional.p.backend()
    state = native.LandscapeState.from_dict(science['state'])
    if not 1 <= len(state.columns) <= 32 or set(state.column_map) != set(science['supports']):
        raise ValueError('one native column per bounded geological support required')
    _state_palette(state, science['regional_input']['palette'])
    return science


def _lineage(snapshot):
    return {'r18_input_scientific_sha256': snapshot['execution']['scientific_sha256'],
            'r18_regional_input_sha256': p.sha(snapshot['scientific']['regional_input']),
            'r18_execution_sha256': p.sha(snapshot['execution']['regional_input_identity'])}


def incise(snapshot, forcing, duration_years):
    """Native finite erosion under explicit per-column discharge and slope.

This is prescribed local erosion, not regional runoff or sediment routing.
Composite K and original phase come from the bound palette; native binary64
hydraulic forcing is supplied by the caller, never inferred from geology.
"""
    science = verify(snapshot)
    palette = science['regional_input']['palette']
    reference = _reference(science['regional_input']['reference_runoff_m_year'])
    duration = columns._q(duration_years, 'erosion duration', nonnegative=True)
    _, native = regional.p.backend()
    initial = native.LandscapeState.from_dict(science['state'])
    regional.contract.plain(forcing)
    if type(forcing) is not dict or set(forcing) != set(initial.column_map):
        raise ValueError('one explicit forcing per generated geological column required')
    native_forcing = {}
    for key, row in forcing.items():
        regional.contract.exact(row, ('discharge_m3_year', 'hydraulic_slope', 'evidence', 'source_status'), 'local erosion forcing')
        regional.contract.text(row['evidence'])
        if row['source_status'] != science['source_status']:
            raise ValueError('local forcing and geological input statuses differ')
        def prop(name, value, unit):
            return native.PhysicalProperty(name, value, unit, row['evidence'], row['source_status'])
        native_forcing[key] = native.landscape.Forcing(
            prop('discharge', row['discharge_m3_year'], 'm3/year'),
            prop('hydraulic_slope', row['hydraulic_slope'], '1'))
    laws = []
    for mid, descriptor in sorted(palette.items()):
        laws.append(native.ErosionLaw(mid, descriptor['phase'],
            native.PhysicalProperty('erosion_coefficient_at_reference_runoff',
                columns._q(descriptor['k_per_year'], 'bound composite K', nonnegative=True),
                '1/year', descriptor['evidence'], science['source_status']),
            native.PhysicalProperty('reference_runoff', reference, 'm/year',
                descriptor['evidence'], science['source_status'])))
    result = erosion.advance(initial, native_forcing, laws, duration)
    receipt = regional._plain(result.receipt)
    projected = accounts.project_balances(receipt['global_material_balance'], palette, accounts.EROSION_STAGES)
    _state_palette(result.state, palette)
    verify(snapshot)
    return {'state': result.state.as_dict(), 'receipt': receipt,
            'forcing': deepcopy(forcing), 'duration_years': str(duration),
            'source_status': science['source_status'], 'palette': deepcopy(palette),
            'constituent_balances': projected, 'constituent_scope': SCOPE,
            'scope': 'PRESCRIBED_LOCAL_EROSION_NOT_REGIONAL_HYDROLOGY_OR_SEDIMENT_ROUTING',
            **_lineage(snapshot)}


def terrain_step(snapshot, forcing):
    """One unchanged R14 terrain trial with exact original-phase composite K.

Hydrology, mobile-phase erosion, settling, deposition and controls must all be
explicit. Original-phase laws for every current/buried composite retain its
bound K and runoff normalisation. Separate mobile-phase laws are not guessed.
"""
    science = verify(snapshot)
    palette = science['regional_input']['palette']
    reference = columns._q(science['regional_input']['reference_runoff_m_year'], 'bound reference runoff', positive=True)
    regional.contract.plain(forcing)
    regional.contract.exact(forcing, ('duration_years', 'local_runoff_m3', 'connectors',
        'erosion_laws', 'sediment_laws', 'controls', 'evidence', 'source_status'), 'regional terrain forcing')
    if forcing['source_status'] != science['source_status']:
        raise ValueError('regional forcing/scenario status differs')
    _, native = regional.p.backend()
    state = native.LandscapeState.from_dict(science['state'])
    materials = {layer.material_id for _, column in state.columns for layer in column.layers}
    connectors = []
    for supplied in forcing['connectors']:
        row = deepcopy(supplied)
        row['length_m'] = columns._q(row['length_m'], 'connector length', positive=True)
        if row['outlet_elevation_m'] is not None:
            row['outlet_elevation_m'] = columns._q(row['outlet_elevation_m'], 'outlet elevation')
        edge = native.Connector(**row)
        if edge.receiver_id is not None:
            a, b = (science['supports'][key]['xy_m'] for key in (edge.source_id, edge.receiver_id))
            distance = math.hypot(float(regional._signed(a[0])-regional._signed(b[0])),
                                  float(regional._signed(a[1])-regional._signed(b[1])))
            if not distance > 0 or not math.isclose(float(edge.length_m), distance, rel_tol=1e-12):
                raise ValueError('connector length differs from construction support coordinates')
        connectors.append(edge)
    laws, supplied_keys = [], set()
    for row in forcing['erosion_laws']:
        regional.contract.exact(row, ('material_id', 'phase', 'k_per_year', 'reference_runoff_m_year'), 'regional erosion law')
        key = (row['material_id'], row['phase'])
        if key in supplied_keys:
            raise ValueError('duplicate material/phase erosion law')
        supplied_keys.add(key)
        properties, exact_values = [], {}
        for name in ('k_per_year', 'reference_runoff_m_year'):
            supplied = row[name]
            regional.contract.exact(supplied, ('name', 'value', 'unit', 'evidence', 'status'), 'native physical property')
            if supplied['status'] != science['source_status']:
                raise ValueError('erosion law cannot promote a different input status')
            exact = columns._q(supplied['value'], name,
                               positive=name == 'reference_runoff_m_year', nonnegative=True)
            exact_values[name] = exact
            value = exact if name == 'k_per_year' else _reference(exact)
            properties.append(native.PhysicalProperty(**dict(supplied, value=value)))
        if row['material_id'] in materials and row['phase'] == palette[row['material_id']]['phase']:
            if (exact_values['k_per_year'] != columns._q(palette[row['material_id']]['k_per_year'], 'bound composite K')
                    or exact_values['reference_runoff_m_year'] != reference):
                raise ValueError('original-phase erosion law differs from bound composite K/normalisation')
        laws.append(native.ErosionLaw(row['material_id'], row['phase'], *properties))
    if not {(mid, palette[mid]['phase']) for mid in materials} <= supplied_keys:
        raise ValueError('original-phase bound erosion law missing for current/buried composite')
    sediment_laws = []
    for supplied in forcing['sediment_laws']:
        row = deepcopy(supplied)
        for name in ('settling_m_year', 'deposited_porosity'):
            row[name] = columns._q(row[name], name, nonnegative=True)
        sediment_laws.append(native.SedimentLaw(**row))
    control = deepcopy(forcing['controls'])
    for name in ('max_relief_change_fraction', 'max_solid_liquid_ratio'):
        control[name] = columns._q(control[name], name, positive=True)
    if type(forcing['local_runoff_m3']) is not dict:
        raise ValueError('explicit local runoff mapping required')
    runoff = {key: columns._q(value, 'local runoff volume', nonnegative=True)
              for key, value in forcing['local_runoff_m3'].items()}
    result = terrain.trial(state, runoff, tuple(connectors), laws, sediment_laws,
        duration_years=columns._q(forcing['duration_years'], 'terrain duration', positive=True),
        controls=native.TrialControls(**control), evidence_id=forcing['evidence'])
    receipt = regional._plain(result.receipt)
    projected = accounts.project_balances(receipt['material_balances'], palette, accounts.TERRAIN_STAGES)
    _state_palette(result.state, palette)
    verify(snapshot)
    return {'state': result.state.as_dict(), 'receipt': receipt,
            'input_recipe_sha256': science['recipe_sha256'], 'forcing_sha256': p.sha(forcing),
            'source_status': science['source_status'], 'palette': deepcopy(palette),
            'constituent_balances': projected, 'constituent_scope': SCOPE,
            'native_receipt_status_scope': 'retained R14 implementation label; input/scenario status is stated separately',
            'whole_diadem_year_verified': False,
            'adapter_scope': 'R16_INTERFACE_WITH_EXACT_COMPOSITE_K_TO_UNCHANGED_R14_TRIAL',
            **_lineage(snapshot)}
