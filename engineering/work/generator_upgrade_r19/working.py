"""Actual finite R18 material -> native river export -> bounded coastal case.

The two source centres are not asserted to be real coast/mouth locations. The
disjoint receiving strips and upstream forcing are explicit numerical fixtures
in the unchanged R18 relative frame. No Sea datum, old DEM or bed offset is used.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import hashlib
from pathlib import Path

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r18 import working as geology, consumer
from . import driver, owner, provenance as p, river_loads, state as s, substrate


CASES = {'C0_CLOSED_CALM', 'C1_NATIVE_RIVER_TO_COAST', 'C2_WAVE_STIRRING_AND_CURRENT'}
STATUS = 'WORKING NON-CANON'
FIXTURE = ('WORKING NON-CANON numerical/material fixture using actual R18 rock; '
           'source probes are not asserted geographic coasts or river mouths; '
           'no accepted Sea registration, bed translation or physical-boundary inference')
OUTLET = 'native_river_to_finite_mouth'


def _property(name, value, unit, evidence):
    return {'name': name, 'value': value, 'unit': unit,
            'evidence': evidence, 'status': STATUS}


def _initial_pores(column, saturated_depth_m):
    """Initial-state hypothesis: split the actual wet front, deeper pores dry.

Initial pore liquid is an additional, separately counted initial inventory, not
a subsequent free-water subsidy. Existing material contacts/properties remain.
"""
    requested = s.q(saturated_depth_m, nonnegative=True)
    height = column.surface_m-column.basal_elevation_m
    depth = min(requested, height)
    front = column.surface_m-depth
    layers, pores, records = [], [], []
    bottom = column.basal_elevation_m
    for index, layer in enumerate(column.layers):
        dz = layer.bulk_volume_m3/column.area_m2
        top = bottom+dz
        wet_dz = max(F(), min(dz, top-front))
        wet_mass = s.q(wet_dz*column.area_m2*layer.grain_density_kg_m3*(1-layer.porosity), nonnegative=True)
        dry_mass = s.q(layer.mass_kg-wet_mass, nonnegative=True)
        pore = s.q(wet_dz*column.area_m2*layer.porosity, nonnegative=True)
        if dry_mass:
            layers.append(layer if not wet_mass else replace(layer, mass_kg=dry_mass))
            pores.append(F())
        if wet_mass:
            layers.append(layer if not dry_mass else replace(layer, mass_kg=wet_mass))
            pores.append(pore)
        records.append({'source_layer_index': index, 'material_id': layer.material_id,
            'source_mass_kg': str(layer.mass_kg), 'dry_mass_kg': str(dry_mass),
            'wet_mass_kg': str(wet_mass), 'initial_pore_liquid_m3': str(pore),
            'original_bottom_m': str(bottom), 'original_top_m': str(top)})
        bottom = top
    result = replace(column, layers=tuple(layers))
    if result.mass_kg != column.mass_kg or result.surface_m != column.surface_m:
        raise ArithmeticError('initial pore-front split changed native mass or geometry')
    if len(layers) > 2048:
        raise ValueError('initial pore-front split exceeds native finite-layer budget')
    return result, pores, {'schema': 'diadem.finite-initial-pore-state.r19',
        'status': STATUS, 'requested_saturated_depth_m': str(requested),
        'applied_finite_depth_m': str(depth), 'wet_front_elevation_m': str(front),
        'additional_initial_liquid_m3': str(sum(pores, F())), 'layer_parcels': records,
        'remaining_pores': 'EXPLICITLY_DRY; NO_AUTOMATIC_LATER_WETTING',
        'material_mass_residual_kg': '0', 'bed_geometry_change_m': '0'}


def _geometry(column, source_xy, *, connect_reach, conductance):
    area = column.area_m2
    reach_area = F(100)
    if area != 16000000:
        raise ValueError('the declared fixture requires the actual native 4 km support')
    areas = {'coast_a': (area-reach_area)/2, 'coast_b': (area-reach_area)/2,
             'reach': reach_area}
    children, receipt = substrate.partition(column, areas)
    height = F(4000)
    widths = {key: value/height for key, value in areas.items()}
    x0, y0 = (s.q(value)-2000 for value in source_xy)
    x = x0
    strips = {}
    for key in ('reach', 'coast_a', 'coast_b'):
        strips[key] = {'x_min_m': str(x), 'x_max_m': str(x+widths[key]),
            'y_min_m': str(y0), 'y_max_m': str(y0+height),
            'area_m2': str(areas[key]), 'width_m': str(widths[key]), 'height_m': str(height)}
        x += widths[key]
    if x != x0+4000:
        raise ArithmeticError('disjoint strip geometry does not cover its one parent')
    faces = [
        {'id': 'a-left-wall', 'left': 'coast_a', 'right': None, 'width_m': '4000', 'normal_xy': [-1., 0.]},
        {'id': 'a-b-shared', 'left': 'coast_a', 'right': 'coast_b', 'width_m': '4000', 'normal_xy': [1., 0.]},
        {'id': 'b-right-wall', 'left': 'coast_b', 'right': None, 'width_m': '4000', 'normal_xy': [1., 0.]}]
    for key, prefix in (('coast_a', 'a'), ('coast_b', 'b')):
        for side, normal in (('top', [0., -1.]), ('bottom', [0., 1.])):
            faces.append({'id': prefix+'-'+side+'-wall', 'left': key, 'right': None,
                          'width_m': str(widths[key]), 'normal_xy': normal})
    links = ([{'id': 'finite-reach-to-a', 'left': 'reach', 'right': 'coast_a',
               'crest_m': str(column.surface_m), 'conductance_m2_s': conductance}]
             if connect_reach else [])
    geometry = {'schema': 'diadem.disjoint-coastal-strip-fixture.r19',
        'source_centre_xy_m': deepcopy(source_xy), 'strips': strips,
        'faces': deepcopy(faces), 'links': deepcopy(links),
        'scope': 'HYPOTHETICAL_DISJOINT_EQUAL_PROFILE_STRIPS_WITHIN_ONE_NATIVE_4000_M_SQUARE',
        'receiving_face_component': ['coast_a', 'coast_b'], 'initial_fill_seed': 'coast_a',
        'reach': 'SEPARATE_FINITE_UPSTREAM_STORE; NO_HYDROSTATIC_FACES',
        'c0_link_policy': 'C0_EXPLICITLY_ISOLATES_THE_DRY_REACH_FOR_CLOSED_CALM_REST',
        'geographic_coast_or_mouth_claimed': False, 'crop_is_physical_wall': False}
    return children, receipt, faces, links, geometry


def _validate_geology(snapshot, supports):
    """Cache hits still check current owner inputs, masks and causal bytes."""
    science = consumer.verify(snapshot)
    if {key: {name: row[name] for name in ('xy_m', 'area_m2')}
            for key, row in science['supports'].items()} != supports:
        raise ValueError('cached native source supports differ')
    spec = geology.inputs()
    geology.previous._mask(geology._reader_spec(spec))
    seen = set()
    for record in science['regional_input']['sampling']['sources'].values():
        identity = (record['path'], record['sha256'])
        if identity in seen:
            continue
        seen.add(identity)
        with Path(record['path']).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                raise ValueError('cached geological causal field changed')


def build_case(case_id='C1_NATIVE_RIVER_TO_COAST', *, cache=True):
    """Build two actual source columns once, then one finite native export.

Returns ``(CoastalRun, JSON-safe evidence)``. Construction exports are never
river sediment. C0 retains the unused native evidence but enqueues no river load.
"""
    if case_id not in CASES:
        raise ValueError('bounded C0/C1/C2 case required; C3 is a separate oracle')
    method, scenario = owner.inputs()
    recovered_sources = owner.sources()
    if scenario['constants']['unit_year_seconds'] != 31536000:
        raise ValueError('native fixture year conversion changed; no silent time repin')
    parameters = owner.parameters()
    source_supports = {f'r375_c{col}': {'xy_m': [-318000+4000*col, -478000+4000*375],
        'area_m2': 16000000} for col in (492, 493)}
    if cache:
        from .cache import CoastalCache
        native_cache = CoastalCache(component='native')
        snapshot, geology_hit = native_cache.reuse(
            {'stage': 'native-r18-geology', 'supports': source_supports,
             'owner_input_sha256': geology.INPUT_SHA, 'alternative': 'DEFAULT'},
            lambda: geology.build(source_supports), lambda value: _validate_geology(value, source_supports))
    else:
        native_cache, geology_hit = None, False
        snapshot = geology.build(source_supports)
    science = consumer.verify(snapshot)
    _, native = regional.p.backend()
    initial_native = native.LandscapeState.from_dict(science['state'])
    ordered = sorted(initial_native.column_map,
                     key=lambda key: (initial_native.column_map[key].surface_m, key))
    coast_id, river_id = ordered[0], ordered[-1]
    coast_before = initial_native.column_map[coast_id]
    river_before = initial_native.column_map[river_id]
    if river_before.surface_m <= coast_before.surface_m:
        raise ValueError('selected actual adjacent R18 sources have no positive river/coast relief; no bed offset invented')
    palette = science['regional_input']['palette']
    reference = science['regional_input']['reference_runoff_m_year']
    laws = []
    for mid, material in sorted(palette.items()):
        if material['phase'] != 'bedrock':
            raise ValueError('declared R18 geological source must retain original bedrock phase')
        laws.append({'material_id': mid, 'phase': material['phase'],
            'k_per_year': _property('erosion_coefficient_at_reference_runoff', material['k_per_year'],
                                    '1/year', material['evidence']),
            'reference_runoff_m_year': _property('reference_runoff', reference, 'm/year', material['evidence'])})
        laws.append({'material_id': mid, 'phase': 'mobile_sediment',
            'k_per_year': _property('erosion_coefficient_at_reference_runoff', '1/100000', '1/year',
                FIXTURE+'; explicit mobile fluvial K fixture, not an original-phase R18/Physical law'),
            'reference_runoff_m_year': _property('reference_runoff', reference, 'm/year', FIXTURE)})
    settling_per_year = F(str(parameters['sediment_settling_m_s']))*31536000
    if settling_per_year != 31536 or F(str(parameters['fresh_mobile_deposit_porosity'])) != F(2, 5):
        raise ValueError('declared native settling/porosity bridge changed')
    forcing = {'duration_years': str(F(900, 31536000)),
        'local_runoff_m3': {key: 4000 if key == river_id else 0 for key in source_supports},
        'connectors': [{'connector_id': OUTLET, 'source_id': river_id, 'receiver_id': None,
            'length_m': 4000, 'outlet_elevation_m': str(coast_before.surface_m),
            'evidence': FIXTURE+'; external numerical mouth contact at the unchanged lower native bed'}],
        'erosion_laws': laws,
        'sediment_laws': [{'material_id': mid, 'settling_m_year': str(settling_per_year),
            'deposited_porosity': '2/5', 'deposition_order': index, 'evidence': FIXTURE}
            for index, mid in enumerate(sorted(palette))],
        'controls': {'max_relief_change_fraction': '1/4', 'max_solid_liquid_ratio': '1/1000',
                     'evidence': FIXTURE+'; explicit native frozen-trial bounds'},
        'source_status': STATUS, 'evidence': FIXTURE+'; finite 4000 m3 local runoff over 900 seconds'}
    def validate_river(value):
        if (value['r18_input_scientific_sha256'] != snapshot['execution']['scientific_sha256']
                or value['forcing_sha256'] != p.sha(forcing)):
            raise ValueError('cached native river input/forcing differs')
        river_loads.extract(value, {OUTLET: 'reach'})
    if native_cache is not None:
        native_result, river_hit = native_cache.reuse(
            {'stage': 'native-r14-river', 'r18_scientific_sha256': snapshot['execution']['scientific_sha256'],
             'forcing': forcing}, lambda: consumer.terrain_step(snapshot, forcing), validate_river)
    else:
        native_result, river_hit = consumer.terrain_step(snapshot, forcing), False
    consumer.verify(snapshot)
    if (native_result['r18_input_scientific_sha256'] != snapshot['execution']['scientific_sha256']
            or native_result['forcing_sha256'] != p.sha(forcing)):
        raise ValueError('fresh native river result/source/forcing binding differs')
    extracted = river_loads.extract(native_result, {OUTLET: 'reach'})
    receiver = extracted['receivers']['reach']
    if F(receiver['water_m3']) != 4000:
        raise ArithmeticError('native once-only runoff export differs from the explicit 4000 m3 input')
    exported_mass = sum((F(row['mass_kg']) for row in receiver['materials'].values()), F())
    if case_id != 'C0_CLOSED_CALM' and exported_mass <= 0:
        raise ValueError('actual native source generated no sediment; no construction export substituted')
    after_native = native.LandscapeState.from_dict(native_result['state'])
    coast = after_native.column_map[coast_id]
    if coast.as_dict() != coast_before.as_dict():
        raise ArithmeticError('unforced native coast column changed before receiving-water construction')
    children, partition, faces, links, geometry = _geometry(coast,
        source_supports[coast_id]['xy_m'], connect_reach=case_id != 'C0_CLOSED_CALM',
        conductance=parameters['mouth_conductance_m2_s'])
    cells, pore_receipts = {}, {}
    for key, column in children.items():
        wet = key != 'reach'
        column, pores, record = _initial_pores(column, F(1, 4) if wet else F())
        cells[key] = s.Cell(column, pores, F(1, 4)*column.area_m2 if wet else F(),
                            {}, (0., 0.), 'water' if wet else 'reach')
        cells[key].validate(palette)
        pore_receipts[key] = record
    receiving_area = cells['coast_a'].column.area_m2+cells['coast_b'].column.area_m2
    receiving_free = cells['coast_a'].free+cells['coast_b'].free
    initial_eta = coast.surface_m+receiving_free/receiving_area
    if any(cells[key].eta(palette) != initial_eta for key in ('coast_a', 'coast_b')):
        raise ArithmeticError('initial flat connected receiving hypsometry does not close')
    initial_pores = sum((sum(cell.pores, F()) for cell in cells.values()), F())
    owner_binding = owner.binding()
    support_binding = {'context': deepcopy(science['context']), 'supports': deepcopy(source_supports)}
    frame_sha = p.sha(science['context'])
    geometry_sha = p.sha(geometry)
    lineage = {'schema': 'diadem.native-material-coastal-fixture-lineage.r19',
        'case_id': case_id, 'source_status': STATUS, 'fixture': FIXTURE,
        'owner_binding': owner_binding, 'recovered_source_register': recovered_sources,
        'source_r18_scientific_sha256': snapshot['execution']['scientific_sha256'],
        'source_r18_execution_sha256': p.sha(snapshot['execution']['regional_input_identity']),
        'source_support_binding': support_binding, 'source_support_sha256': p.sha(support_binding),
        'frame_sha256': frame_sha, 'river_source_id': river_id, 'coast_source_id': coast_id,
        'native_terrain_result_sha256': p.sha(native_result), 'native_forcing_sha256': p.sha(forcing),
        'river_extraction_sha256': p.sha(extracted), 'partition_sha256': p.sha(partition),
        'receiving_geometry_sha256': geometry_sha, 'initial_pore_state_sha256': p.sha(pore_receipts),
        'native_execution_authentication': 'DIRECT_SOURCE_CHECKED_CONSUMER_CALL; EXTRACTOR_ITSELF_IS_NOT_AUTHENTICATION',
        'native_fluid_scope': 'ISOTHERMAL_DRY_PORE_FLUVIAL_FIXTURE; NO_NATIVE_THERMAL_PARCEL_CONSUMED',
        'upstream_initial_actual_pores_m3': '0', 'upstream_fluvial_deposit_actual_pores_m3': '0',
        'attached_export_pore_liquid_m3': '0',
        'pore_assignment_scope': 'EXPLICIT_ADDITIONAL_FIXTURE_STATE; RETAIN_NATIVE_UNASSIGNED_RECEIPT_UNCHANGED',
        'initial_free_liquid_m3': str(receiving_free), 'additional_initial_bed_pore_liquid_m3': str(initial_pores),
        'initial_receiving_eta_m': str(initial_eta), 'initial_reach_liquid_m3': '0',
        'river_remainder_scope': 'UPSTREAM_NATIVE_REMAINDER_OUTSIDE_R19; ONLY_ACTUAL_ONCE_ONLY_EXPORT_IS_IMPORTED',
        'r18_to_sea_offset_m': None, 'sea_registration': 'NOT_ASSERTED',
        'receiving_bed_translated': False, 'old_dem_consumed': False,
        'physical_probes_asserted_coastal': False, 'geographic_coupling_claimed': False,
        'geographic_controls': 'RETAINED_READ_ONLY; NO_UNREGISTERED_GEOGRAPHIC_APPLICATION_OR_BYPASS_CLAIM',
        'canon_changed': False, 'production_authorised': False, 'full_map_or_year_run': False}
    run = driver.CoastalRun(cells, palette, faces, links, evidence=FIXTURE,
                           lineage=lineage, parameters=parameters)
    run.cache_reporting = {'native_geology_hit': geology_hit, 'native_river_hit': river_hit,
        'stats': native_cache.stats if native_cache is not None else {},
        'warnings': list(native_cache.warnings) if native_cache is not None else []}
    packet = {'schema': 'diadem.native-river-to-finite-reach-fixture.r19',
        'source_id': river_id, 'receiver_id': 'reach', 'source_status': STATUS,
        'source_support_sha256': p.sha(support_binding), 'receiver_support_sha256': geometry_sha,
        'frame_sha256': frame_sha, 'start_s': '0', 'duration_s': '900',
        'sign_convention': 'POSITIVE_FINITE_SOURCE_TO_REACH',
        'free_carrier_liquid_m3': receiver['water_m3'], 'attached_pore_liquid_m3': '0',
        'dry_materials': deepcopy(receiver['materials']), 'momentum_m4_s': [0., 0.],
        'momentum_hypothesis': 'EXPLICIT_ZERO_MOMENTUM_FINITE_NATIVE_EXPORT_SOURCE',
        'native_terrain_result_sha256': p.sha(native_result), 'river_extraction_sha256': p.sha(extracted),
        'native_pore_water_scope': extracted['pore_water_scope'], 'evidence': FIXTURE}
    packet_id = 'R19_NATIVE_EXPORT_'+p.sha(packet)
    if case_id != 'C0_CLOSED_CALM':
        run.enqueue(packet_id, 'reach', F(receiver['water_m3']),
            {mid: F(row['mass_kg']) for mid, row in receiver['materials'].items()},
            duration_s=F(900), source=packet, attached_pore_liquid_m3=F(), momentum=(0., 0.))
    evidence = {'schema': 'diadem.native-coastal-case-evidence.r19', 'case_id': case_id,
        'source_status': STATUS, 'fixture': FIXTURE, 'owner_method': method,
        'owner_scenario': scenario, 'owner_binding': owner_binding, 'recovered_sources': recovered_sources,
        'r18_snapshot': snapshot, 'native_forcing': forcing, 'native_result': native_result,
        'native_river_extraction': extracted, 'partition': partition, 'geometry': geometry,
        'initial_pore_states': pore_receipts, 'lineage': lineage,
        'finite_river_packet': packet, 'packet_id': packet_id,
        'river_packet_enqueued': case_id != 'C0_CLOSED_CALM',
        'upstream_remaining_column': after_native.column_map[river_id].as_dict(),
        'initial_receiving_state_sha256': p.sha({key: cell.as_dict() for key, cell in sorted(cells.items())})}
    p.verify(run.execution)
    return run, s.plain(evidence)


def run_case(run, case_id, stop_s=3600, max_step_s=30, phase_points=16, *, cache=True):
    """Drive the four owner intervals, respecting exact resume/forcing endpoints.

C2 wind/wave forcing is active on zero-based intervals 1 and 2 (900--2700 s).
A failed or out-of-regime step propagates; CoastalRun retains its valid prefix.
No clipping, dilution, automatic regime repair or partial-success label is added.
"""
    if case_id not in CASES or run.lineage.get('case_id') != case_id:
        raise ValueError('case identity must match its source-bound initial state')
    if type(phase_points) is not int or phase_points not in (16, 32):
        raise ValueError('declared 16/32-point phase quadrature required')
    _, scenario = owner.inputs()
    durations = scenario['numerics']['forcing_intervals_s']
    if durations != [900, 900, 900, 900] or scenario['numerics']['representative_duration_s'] != 3600:
        raise ValueError('owner forcing schedule changed; no inferred replacement schedule')
    stop = s.q(stop_s, nonnegative=True)
    maximum = s.q(max_step_s, positive=True)
    if not run.time <= stop <= 3600:
        raise ValueError('forward continuation within the bounded 3600-second case required')
    cases = {row['id']: row for row in scenario['cases']}
    if cache:
        from .cache import CoastalCache
        coastal_cache = CoastalCache()
    else:
        coastal_cache = None
    reporting = getattr(run, 'cache_reporting', {})
    reporting.setdefault('interval_hits', 0)
    reporting.setdefault('interval_writes', 0)
    for index in range(4):
        endpoint = F((index+1)*900)
        if run.time >= endpoint or run.time >= stop:
            continue
        active = case_id == 'C2_WAVE_STIRRING_AND_CURRENT' and index in cases[case_id]['active_intervals']
        forcing = {'wind_stress_Pa': deepcopy(cases[case_id]['wind_stress_Pa']) if active else [0., 0.],
            'wave_rms_shear_Pa': cases[case_id]['wave_rms_shear_Pa'] if active else 0,
            'wave_direction_xy': deepcopy(cases[case_id]['wave_direction_xy']) if active else [0., 0.],
            'phase_points': phase_points}
        target = min(stop, endpoint)
        invocation = {'stage': 'coastal-forcing-interval',
            'initial_scientific_sha256': run.checkpoint()['scientific_sha256'],
            'end_s': str(target), 'forcing': forcing, 'max_step_s': str(maximum),
            'max_steps': 10000}
        saved = coastal_cache.load_checkpoint(invocation) if coastal_cache is not None else None
        if saved is not None:
            restored = driver.CoastalRun.restore(saved)
            run.__dict__.update(restored.__dict__)
            reporting['interval_hits'] += 1
        else:
            try:
                run.advance(target, forcing, max_step_s=maximum)
            except Exception:
                if coastal_cache is not None:
                    prefix = run.checkpoint()
                    key = dict(invocation, stage='coastal-failed-prefix',
                               prefix_scientific_sha256=prefix['scientific_sha256'])
                    reporting['failed_prefix'] = {'invocation': key,
                        'save': coastal_cache.save_checkpoint(key, prefix)}
                    run.cache_reporting = reporting
                raise
            if coastal_cache is not None:
                result = coastal_cache.save_checkpoint(invocation, run.checkpoint())
                reporting['interval_writes'] += int(result['saved'])
        if coastal_cache is not None:
            reporting['coastal_stats'] = coastal_cache.stats
            reporting['warnings'] = list(coastal_cache.warnings)
        run.cache_reporting = reporting
    if run.time != stop:
        raise ArithmeticError('coastal case did not reach its requested exact endpoint')
    return run.checkpoint()
