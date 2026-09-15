"""Compile corrected actual producer functions from freshly checked source bytes.

No historic module is imported, no global library monkeypatch is installed, and
no producer main is run by binding. Context supplies explicitly owned I/O objects.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy import sparse
from scipy.ndimage import distance_transform_edt, maximum_filter, minimum_filter
from scipy.linalg import solve_banded
from shapely.geometry import LineString, Point

from . import core
from . import provenance as identity

HERE=Path(__file__).resolve().parent
PINS=json.loads((HERE/'SOURCE_PINS.json').read_text())
ROOT=Path(PINS['root'])


def checked_source(relative):
    pin=PINS['sources'][relative]
    path=ROOT/relative
    raw=path.read_bytes()
    if len(raw)!=pin['bytes'] or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise RuntimeError(f'protected predecessor drift: {relative}')
    return raw.decode('utf-8-sig')


def verify_sources():
    for relative in PINS['sources']:
        checked_source(relative)
    return copy.deepcopy(PINS)


def implementation_identity():
    records={name:identity.sha256(HERE/name) for name in ('__init__.py','core.py','provenance.py','bindings.py','SOURCE_PINS.json')}
    return hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def replace_once(source, old, new):
    if source.count(old)!=1:
        raise RuntimeError(f'exact source correction anchor changed: {old[:90]}')
    return source.replace(old,new)


def _replace_body(source, name, body):
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.body=ast.parse(body).body
    return ast.unparse(ast.fix_missing_locations(tree))


def _prepend(source, name, statement):
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.body=ast.parse(statement).body+node.body
    return ast.unparse(ast.fix_missing_locations(tree))


def _compile(relative,names,source,context=None):
    original=ast.parse(checked_source(relative))
    scope={'np':np,'math':math,'warnings':warnings,'Path':Path,'json':json,
           'datetime':datetime,'timezone':timezone,'hashlib':hashlib,
           'distance_transform_edt':distance_transform_edt,'maximum_filter':maximum_filter,
           'minimum_filter':minimum_filter,'sparse':sparse,'solve_banded':solve_banded,
           'LineString':LineString,'Point':Point,'_core':core,'_identity':identity,
           'G':9.80665,'BUDYKO_OMEGA':3.4,'EDAPHIC_FEATHER_KM':30.,
           'ROOT':ROOT,'HERE':(ROOT/relative).parent,'_implementation_identity':implementation_identity,
           '__file__':str(ROOT/relative),'__name__':__name__}
    # Only literal declarations: never run top-level loads, mkdirs, imports or main.
    for n in original.body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            try: value=ast.literal_eval(n.value)
            except (ValueError,TypeError): continue
            scope[n.targets[0].id]=value
    scope.update(context or {})
    nodes=[n for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    if {n.name for n in nodes}!=set(names):
        raise RuntimeError('requested producer functions missing')
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future]+nodes,type_ignores=[])),f'<environment-successor:{relative}>','exec'),scope)
    checked_source(relative)
    receipt={'predecessor':str(ROOT/relative),**PINS['sources'][relative],
             'bound_functions':sorted(names),'transformed_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
             'status':'CALLABLE_SUCCESSOR_NOT_FULL_RUN_OR_INSTALLATION'}
    return SimpleNamespace(**{n:scope[n] for n in names},receipt=receipt,namespace=scope,source=source)


def _auxiliary_guard(ds,width,height):
    core.integer(width,'width'); core.integer(height,'height')
    t=ds.transform
    if not all(math.isfinite(float(v)) for v in (t.a,t.b,t.c,t.d,t.e,t.f)) or t.b!=0 or t.d!=0:
        raise ValueError('auxiliary affine must be finite and unrotated')
    values=ds.read(1)
    if not np.all(np.isin(values,[0,1])):
        raise ValueError('auxiliary mask must contain only known binary values')
    if getattr(ds,'nodata',None) in (0,1):
        raise ValueError('auxiliary binary codes collide with NODATA')


def _geology_zoom(src,factor,**kwargs):
    from work.spatial_corrections_r1 import Grid,intensive
    a=core.finite_array(src,'geology field')
    if a.ndim!=2 or float(factor)!=4 or kwargs.get('order')!=1:
        raise ValueError('bound geology successor expects 4 km to 1 km linear cells')
    source=Grid(a.shape,0.,0.,4.,4.)
    target=Grid((a.shape[0]*4,a.shape[1]*4),0.,0.,1.,1.)
    result=intensive(a,source,target,order=1)
    if not result.valid.all():
        raise ValueError('geology coverage incomplete')
    return result.values.astype(np.float32)


def bind(component,context=None):
    """Return actual source-derived callable components with scoped corrections.

    For I/O producers the explicit context supplies their resolved paths and
    dependencies. Context never bypasses the predecessor byte pin.
    """
    ctx=dict(context or {})
    if component=='macro':
        relative='work/climate_ecology/c0r3_natural_geometry/build_c0r3_natural_geometry.py'
        source,receipt=macro_source()
        names={n.name for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        def blocked():
            raise RuntimeError('production not activated: explicit frozen fields, run controls and new output binding required')
        ctx.setdefault('_SUCCESSOR_RUN_GATE',blocked)
        result=_compile(relative,names,source,ctx)
        result.receipt['macro_binding']=receipt
        return result
    if component=='climate_kernel':
        relative='work/climate_ecology/c1_preflight/scripts/build_c1_preflight.py'
        source=checked_source(relative)
        source=_replace_body(source,'conservative_coefficients','return _core.conservative_coefficients(field, FINE)')
        source=_replace_body(source,'fu_aet','return _core.fu_aet(p, pet, omega)')
        return _compile(relative,{'conservative_coefficients','smooth_reconstruct','block_view','block_mean','fu_aet'},source,ctx)
    if component=='climate_auxiliary':
        relative='work/climate_ecology/c1r2_1km_preview/build_c1r2_1km_preview.py'
        source=_prepend(checked_source(relative),'exact_auxiliary_fraction','_auxiliary_guard(ds, target_width, target_height)')
        ctx['_auxiliary_guard']=_auxiliary_guard
        return _compile(relative,{'exact_auxiliary_fraction'},source,ctx)
    if component=='climate_full_metrics':
        relative='work/climate_ecology/c1_production/scripts/build_c1_full_production.py'
        source=checked_source(relative)
        old=next(line for line in source.splitlines() if line.strip().startswith('b=np.concatenate([x[np.isfinite(x)&(x!=0)'))
        new='''        b=np.concatenate([x[np.isfinite(x)&(x<9000)] for x in boundary]) if boundary else np.empty(0)
        n=np.concatenate([x[np.isfinite(x)&(x<9000)] for x in near]) if near else np.empty(0)
        bp=float(np.percentile(b,95)) if b.size else 0.0
        np95=float(np.percentile(n,95)) if n.size else 0.0
        ratio=bp/max(np95,1e-9)
        result[f"{key}:{name}"]={"production_boundary_p95":bp,"near_boundary_p95":np95,"boundary_pairs":int(b.size),"near_pairs":int(n.size),"ratio":ratio,"pass":ratio<=2.0}'''
        source=replace_once(source,old,new)
        tree=ast.parse(source)
        outer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='native_regional_gates')
        buffered=next(n for n in ast.walk(outer) if isinstance(n,ast.FunctionDef) and n.name=='buffered')
        buffered.body=ast.parse("if not np.asarray(mask).any(): return np.zeros_like(mask, dtype=bool)").body+buffered.body
        tree.body.append(copy.deepcopy(buffered))
        source=ast.unparse(ast.fix_missing_locations(tree))
        return _compile(relative,{'global_output_seams','native_regional_gates','buffered'},source,ctx)
    if component=='biome_science':
        relative='work/biome_map/bm1r4_builder/bm1r4_science.py'
        source=_replace_body(checked_source(relative),'edaphic_feather_weight','return _core.edaphic_weight(valid_mask, cell_size_km, scale_km)')
        source=_prepend(source,'feather_physical_support',"_core.finite_array(weight, 'feather weight', True)\nif np.any(np.asarray(weight)>1): raise ValueError('weight exceeds one')")
        return _compile(relative,{'edaphic_feather_weight','feather_physical_support'},source,ctx)
    if component=='biome_hydrology_reader':
        relative='work/biome_map/bm1r2_builder/build_bm1r2_1km.py'
        source=checked_source(relative)
        source=replace_once(source,'clamp01(self._read_named(self.hydro, [persistent_name], window)[0])','_core.hydroperiod(self._read_named(self.hydro, [persistent_name], window)[0], eligible | water_pending)')
        source=replace_once(source,'clamp01(self._read_named(self.hydro, [seasonal_name], window)[0])','_core.hydroperiod(self._read_named(self.hydro, [seasonal_name], window)[0], eligible | water_pending)')
        return _compile(relative,{'InputSet'},source,ctx)
    if component=='biome_formation':
        from dataclasses import dataclass
        relative='work/biome_map/bm1r2_scaffold/bm1r2_core.py'
        source=checked_source(relative)
        constants={'OUTSIDE','BASE_CODES','FORMATION_CODES','FORMATION_COMPATIBILITY','UNCERTAINTY_LOW_SUPPORT','UNCERTAINTY_WEAK_DOMINANCE','UNCERTAINTY_FAMILY_DISAGREEMENT','UNCERTAINTY_FALLBACK_USED','UNCERTAINTY_EXACT_TIE'}
        assignments=[n for n in ast.parse(source).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in constants]
        constant_scope={'np':np}
        exec(compile(ast.Module(body=assignments,type_ignores=[]),'<pinned-biome-constants>','exec'),constant_scope)
        ctx.update({name:constant_scope[name] for name in constants});ctx['dataclass']=dataclass
        source=replace_once(source,'    broad_class = np.asarray(broad_class, dtype=np.uint8)','    broad_class = _core.uncast_broad_class(broad_class, eligible)')
        source=source.replace('    eligible = np.asarray(eligible, dtype=bool)','    eligible = _core.boolean_mask(eligible)')
        return _compile(relative,{'FormationResult','_top_margin','_median_composite_choice','classify_formations'},source,ctx)
    if component=='biome_uncertainty_render':
        relative='work/biome_map/bm1r2_builder/build_bm1r2_1km.py'
        source=replace_once(checked_source(relative),'for bit in range(8))','for bit in range(9))')
        return _compile(relative,{'render_reviews'},source,ctx)
    if component=='surface_envelopes':
        relative='work/surface_hydrology/s2a_full_1km/output/software/stage2a_model.py'
        source=checked_source(relative)
        source=replace_once(source,'    complete = (expected > 0) & (count == expected)','    complete = (expected > 0) & (count == expected)\n    array = np.where(realization_valid[:, None], array, np.nan)')
        source=_prepend(source,'strict_monthly_envelope','values, expected_count = _core.valid_envelope_inputs(values, expected_count)')
        source=_replace_body(source,'protected_overlap_fraction','return _core.protected_union(shape, row_start, col_start, systems)')
        return _compile(relative,{'strict_monthly_envelope','protected_overlap_fraction','strict_partitioned_envelope','positivity_class'},source,ctx)
    if component=='marine':
        relative='work/surface_hydrology/ws1_obsidian_sea_wind_seiche_shore_preflight/ws1_core.py'
        source=checked_source(relative)
        source=replace_once(source,'ux, uy = math.sin(angle), math.cos(angle)','ux, uy = math.sin(angle), -math.cos(angle)')
        source=replace_once(source,'sx, sy = x + epsilon_km * ux, y + epsilon_km * uy','sx, sy = x, y')
        source=replace_once(source,'    return max(0.0, (min(candidates) if candidates else 0.0) + epsilon_km)',"    result = max(0.0, min(candidates) if candidates else 0.0)\n    if result >= ray_length_km - 1e-9: raise ValueError('fetch ray truncated before shoreline')\n    return result")
        source=replace_once(source,'2.0 * h1 * h2 / np.maximum(h1 + h2, 1.0e-12)','np.minimum(h1,h2) / (0.5 + 0.5 * np.minimum(h1,h2)/np.maximum(h1,h2))')
        source=replace_once(source,'scale = G / (float(cell_km) * 1000.0) ** 2','scale = _core.operator_scale(cell_km)')
        source=replace_once(source,'        conductance = scale * edge_depth',"        conductance = scale * edge_depth\n        if not np.all(np.isfinite(conductance)) or np.any(conductance<=0): raise ValueError('face conductance not representable')")
        source=replace_once(source,'    return periods, modes, values[keep].tolist(), index',"    if len(modes) != mode_count: raise ValueError('required positive mode count not resolved')\n    _core.validate_seiche_eigenpairs(operator,wet,periods,modes,values[keep])\n    return periods, modes, values[keep].tolist(), index")
        source=_prepend(source,'solve_seiche_modes',"_core.integer(mode_count, 'mode count')\nif np.count_nonzero(wet)<=mode_count+2: raise ValueError('grid too small for retained sparse eigensolver mode count')")
        source=_prepend(source,'aggregate_depth','depth, subcell_counts = _core.aggregate_depth_inputs(depth, subcell_counts, factor)')
        source=_prepend(source,'shallow_water_operator',"_core.boolean_mask(wet, np.asarray(depth_m).shape)\n_core.positive_scalar(cell_km, 'cell size')\nif not np.all(np.isfinite(np.asarray(depth_m)[wet])) or np.any(np.asarray(depth_m)[wet]<=0): raise ValueError('wet depth unknown or nonpositive')")
        source=_prepend(source,'directional_fetch_km',"_core.positive_scalar(ray_length_km, 'ray length')\n_core.positive_scalar(epsilon_km, 'legacy epsilon')\n_core.finite_array(point_xy, 'point')\n_core.finite_array(wind_from_bearing_deg, 'bearing')")
        names={'directional_fetch_km','fetch_limited_hm0_m','block_sum','aggregate_depth','largest_component','shallow_water_operator','solve_seiche_modes','mode_participation_fraction','screen_basin_scale_modes','merian_period_hours','monthly_freezing_degree_day_proxy'}
        from scipy.sparse.linalg import eigsh
        ctx['eigsh']=eigsh
        return _compile(relative,names,source,ctx)
    if component=='marine_validation':
        relative='work/surface_hydrology/ws1_obsidian_sea_wind_seiche_shore_preflight/validate_ws1_preflight.py'
        source=checked_source(relative)
        source=replace_once(source,'    wet = arrays["sea_mask"].astype(bool)',"    if not np.all(np.isin(arrays['sea_mask'],[0,1])): raise ValueError('invalid sea-mask code')\n    wet = arrays[\"sea_mask\"].astype(bool)")
        source=replace_once(source,'        mode_checks[family] = checks', '''        operator, _ = _marine_operator(depth, wet, 2.5)
        selected_rows = sorted((row for row in period_rows if row["family_id"] == family), key=lambda row:int(row["mode_number"]))
        _core.validate_seiche_eigenpairs(operator, wet, [float(row["period_hours"]) for row in selected_rows], [arrays[f"{family}_mode_{mode}"] for mode in range(1,7)])
        checks["eigenpair_residuals_null_mode_and_orthogonality"] = True
        mode_checks[family] = checks''')
        ctx['_marine_operator']=bind('marine').shallow_water_operator
        return _compile(relative,{'main','sha256'},source,ctx)
    if component=='cryosphere_compare':
        relative='work/cryosphere/c1_r1/validate_output.py'
        source=_prepend(checked_source(relative),'max_difference','actual, expected = _core.require_float_comparison(actual, expected)')
        return _compile(relative,{'max_difference'},source,ctx)
    if component=='cryosphere_science':
        relative='work/cryosphere/c1_r1/snow_model.py'
        source=checked_source(relative)
        source=source.replace('mask = np.asarray(active, dtype=bool)','mask = _core.boolean_mask(active)')
        source=replace_once(source,'if np.any(snowfall[expanded] < -MASS_TOLERANCE_MM):','if np.any(snowfall[expanded] < 0):')
        source=replace_once(source,'    initial = store.copy()',"    if not all(np.all(np.isfinite(a)) for a in (positive_degree_days, capacity, potential_balance, prefix, suffix, store)): raise ValueError('snow model state not representable')\n    initial = store.copy()")
        source=replace_once(source,'    annual_residual = initial + annual_snowfall - annual_melt - store',"    annual_residual = (initial-store) + (annual_snowfall-annual_melt)\n    if not all(np.all(np.isfinite(a)) for a in (annual_snowfall,annual_capacity,annual_melt,store,monthly_store,annual_residual)): raise ValueError('snow ledger not representable')")
        source=_prepend(source,'classify_regime',"mask_check = _core.boolean_mask(active)\n_core.positive_scalar(tolerance_mm, 'balance tolerance', zero=True)\na_check=np.asarray(annual_snowfall_mm)\nb_check=np.asarray(annual_potential_balance_mm)\nif a_check.shape!=mask_check.shape or b_check.ndim!=3 or b_check.shape[0]<2 or b_check.shape[1:]!=mask_check.shape: raise ValueError('classification shape/scenario mismatch')\nif not np.all(np.isfinite(a_check[mask_check])) or np.any(a_check[mask_check]<0) or not np.all(np.isfinite(b_check[:,mask_check])): raise ValueError('unknown/negative cryosphere classification input')\nif np.any(b_check[:,mask_check]-a_check[mask_check]>tolerance_mm): raise ValueError('positive snow balance cannot exceed snowfall')")
        from dataclasses import dataclass
        from scipy.special import ndtr
        ctx.update({'dataclass':dataclass,'ndtr':ndtr,'DAYS_IN_MONTH':np.asarray((31,28,31,30,31,30,31,31,30,31,30,31),np.float64)})
        return _compile(relative,{'RegimeResult','SnowYearResult','SnowEnvelopeResult','_validate_forcing','classify_regime','simulate_snow_year','run_snow_envelope'},source,ctx)
    if component=='bathymetry_compare':
        relative='work/surface_hydrology/bs1_obsidian_sea_bathymetry_support_preflight/validate_preflight.py'
        source=_replace_body(checked_source(relative),'max_abs','difference = _core.exact_difference(a,b)\nreturn float(np.max(difference, initial=0.))')
        return _compile(relative,{'max_abs'},source,ctx)
    if component=='bathymetry_science':
        relative='work/surface_hydrology/bs1_obsidian_sea_bathymetry_support_preflight/bathymetry_core.py'
        source=checked_source(relative)
        source=replace_once(source,'where=denominator > 1.0e-12','where=denominator > 0.0')
        source=_prepend(source,'weighted_gaussian','values, weights = _core.weighted_fields(values, weights, sigma_cells)')
        from scipy import ndimage
        ctx['ndimage']=ndimage
        names={n.name for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        return _compile(relative,names,source,ctx)
    if component=='bathymetry_inputs':
        relative='work/surface_hydrology/bs1_obsidian_sea_bathymetry_support_preflight/build_preflight.py'
        source=checked_source(relative)
        source=replace_once(source,'(terrain_100m * mask_100m).reshape','(np.where(mask_100m, terrain_100m, 0.) * mask_100m).reshape')
        source=replace_once(source,'line_distance = ndimage.distance_transform_edt(fault_lines <= 0.0) * SCREEN_CELL_KM','line_distance = ndimage.distance_transform_edt(fault_lines <= 0.0) * SCREEN_CELL_KM if np.any(fault_lines > 0.0) else np.full(out_shape, np.inf)')
        source=_prepend(source,'aggregate_500m','mask_100m, terrain_100m = _core.bathymetry_children(mask_100m, terrain_100m)')
        from scipy import ndimage
        ctx['ndimage']=ndimage
        return _compile(relative,{'aggregate_500m','vector_structural_support'},source,ctx)
    if component=='soil_parent_identity':
        relative='work/pedology/p1_r1/scripts/build_p1r1.py'
        source=_replace_body(checked_source(relative),'compare_parent_snapshot','return _identity.parent_snapshots(before, after, utc_now())')
        return _compile(relative,{'compare_parent_snapshot','utc_now'},source,ctx)
    if component=='macro_geometry':
        relative='work/climate_ecology/c1r2_seam_repair/build_r1t12_regime_allocation_geometry_preflight.py'
        source=checked_source(relative)
        source=replace_once(source,'        field[field == nodata] = 0','        field[field == nodata] = np.nan')
        source=replace_once(source,'    if not np.all(np.isfinite(field)):',"    required = _core.boolean_mask(REQUIRED_DOMAIN, field.shape, 'physical-field required domain')\n    if not np.all(np.isfinite(field[required])):")
        ctx.setdefault('REQUIRED_DOMAIN',None)
        return _compile(relative,{'read_tif','normalize','robust_unit','project'},source,ctx)
    if component=='pipeline_identity':
        relative='work/biome_map/post_climate_pipeline/run_post_climate_pipeline.py'
        source=checked_source(relative)
        source=replace_once(source,'    return paths, parent_inputs(config, paths)','    inputs = parent_inputs(config, paths)\n    _identity.require_prepared_identities(payload, inputs, resolve)\n    return paths, inputs')
        source=replace_once(source,'if not str(paths["run"]).lower().startswith(str((ROOT / "work/biome_map/post_climate_pipeline/runs").resolve()).lower()):','if not paths["run"].resolve().is_relative_to((ROOT / "work/biome_map/post_climate_pipeline/runs").resolve()) or paths["run"].resolve() == (ROOT / "work/biome_map/post_climate_pipeline/runs").resolve():')
        source=replace_once(source,'"controller": Path(__file__), "ep1r3_builder": EP_BUILDER,','"controller": Path(__file__), "c1_builder": C1_BUILDER, "p1_builder": P1_BUILDER,\n                "c1_kernel": ROOT / "work/climate_ecology/c1_preflight/scripts/build_c1_preflight.py",\n                "p1_base_builder": ROOT / "work/pedology/p1_r1/scripts/build_p1r1.py",\n                "p1_core": ROOT / "work/pedology/p1_r1/scripts/p1r1_core.py", "ep1r3_builder": EP_BUILDER,')
        source=_replace_body(source,'gate_pass',"status=payload.get('status')\nif status is not None and (not isinstance(status,str) or not status.upper().startswith('PASS') or 'FAIL' in status.upper()): return False\nif 'pass' in payload: return payload['pass'] is True\nreturn isinstance(status,str) and status.upper().startswith('PASS')")
        return _compile(relative,{'require_prepared','prepare','validate_config','gate_pass'},source,ctx)
    if component=='s2e_common':
        relative='work/surface_hydrology/s2e_full_forcing/stage2e_common.py'
        source=checked_source(relative)
        source=replace_once(source,'    failures = []\n    for row in lock["sources"]:', '    _identity.verify_role_lock(lock, PATHS, ROOT)\n    failures = []\n    for row in lock["sources"]:')
        source=replace_once(source,'    if result["peak_process_rss_bytes"] > HARD_RSS_BYTES:',"    if result['peak_process_rss_bytes'] is None or result['peak_process_rss_bytes'] <= 0: raise RuntimeError('peak RSS unavailable; cannot pass resource gate')\n    if started is not None and result['elapsed_seconds'] > HARD_RUNTIME_SECONDS: raise RuntimeError('runtime gate exceeded')\n    if result[\"peak_process_rss_bytes\"] > HARD_RSS_BYTES:")
        return _compile(relative,{'verify_lock','require_resource_gate'},source,ctx)
    if component=='s2e_forcing':
        relative='work/surface_hydrology/s2e_full_forcing/build_forcing.py'
        source=checked_source(relative)
        source=replace_once(source,'        if not path.exists(): open_memmap(path, mode="w+", dtype=dtype, shape=shape).flush()', '''        if path.exists():
            existing = np.load(path, mmap_mode="r", allow_pickle=False)
            if existing.shape != shape or existing.dtype != np.dtype(dtype): raise ValueError("existing forcing array shape/dtype drift")
        else: open_memmap(path, mode="w+", dtype=dtype, shape=shape).flush()''')
        source=replace_once(source,'    completed = set(state["completed_tile_keys"])', '''    current_implementation = _implementation_identity()
    if state["completed_tile_keys"] and state.get("successor_implementation_sha256") != current_implementation:
        raise ValueError("forcing checkpoint implementation changed or is unbound")
    state["successor_implementation_sha256"] = current_implementation
    tile_records = _identity.forcing_completed_state(state, FRAME_1KM, TILE)
    completed = set(state["completed_tile_keys"])''')
        source=replace_once(source,'                if key in completed: continue', '''                if key in completed:
                    actual = _identity.forcing_tile_digest(land_grid, patch, p_grid, pet_grid, target_index, row0, row1, col0, col1)
                    if actual != tile_records[key]["payload_sha256"]: raise ValueError("completed forcing tile payload changed")
                    continue''')
        source=replace_once(source,'                state["completed_tile_keys"].append(key); state["tiles"].append(tile)', '                tile["payload_sha256"] = _identity.forcing_tile_digest(land_grid, patch, p_grid, pet_grid, target_index, row0, row1, col0, col1)\n                state["completed_tile_keys"].append(key); state["tiles"].append(tile)')
        return _compile(relative,{'full','initialise_outputs','validate_serialized_factorisation'},source,ctx)
    if component=='hg2_seasonal':
        relative='work/hydrogeology/hg2_seasonal_r1/seasonal.py'
        source=checked_source(relative)
        source=replace_once(source,'    mask = np.asarray(active, dtype=bool)','    mask = _core.boolean_mask(active)')
        source=replace_once(source,'    opening = zero_end / denominator',"    opening = zero_end / denominator\n    if not np.all(np.isfinite(opening[mask])): raise ValueError('periodic storage not representable')")
        source=replace_once(source,'        release[month] = pre - closing',"        release[month] = pre * -expm1(-float(days) / tau)\n        if not np.all(np.isfinite(pre[mask])) or not np.all(np.isfinite(closing[mask])) or not np.all(np.isfinite(release[month,mask])): raise ValueError('reservoir step not representable')")
        source=replace_once(source,'    residual = opening + np.sum(recharge, axis=0) - storage - np.sum(release, axis=0)','    residual = (opening - storage) + (np.sum(recharge, axis=0) - np.sum(release, axis=0))')
        ctx.update({'exp':math.exp,'expm1':math.expm1,'MONTH_DAYS':np.asarray((31,28,31,30,31,30,31,31,30,31,30,31),np.float64)})
        return _compile(relative,{'periodic_slow_release','accumulate_monthly_to_roots','assign_terminal_categories','low_season_diagnostics'},source,ctx)
    if component=='hg23_envelope':
        relative='work/hydrogeology/hg23_channel_accumulation_r1/run_hg23_envelope.py'
        source=checked_source(relative)
        source=replace_once(source,'    for index, record in enumerate(candidate_records):\n        load = roots["loads"][index]', '    load_by_id = _core.root_load_lookup(roots, candidate_records)\n    for index, record in enumerate(candidate_records):\n        load = load_by_id[record["root_cell_id"]]')
        from collections import defaultdict,Counter
        ctx.update({'defaultdict':defaultdict,'Counter':Counter})
        return _compile(relative,{'make_envelope','path_cache','utc_now'},source,ctx)
    if component=='hazard_mh':
        relative='work/mass_movement/build_mh1_static_support.py'
        source=_prepend(checked_source(relative),'classify',"_core.finite_required_fields(d, 'domain', {'snow_regime': (1,2,3,4)})")
        ctx['zoom']=_geology_zoom
        return _compile(relative,{'classify','stack_support','load_coarse_inputs'},source,ctx)
    if component in ('hazard_mh_validation','hazard_vh_validation'):
        volcanic=component=='hazard_vh_validation'
        relative=('work/volcanic_hazard/validate_vh1_static_support.py' if volcanic else 'work/mass_movement/validate_mh1_static_support.py')
        source=checked_source(relative)
        source=_prepend(source,'replay',"_core.finite_required_fields(d, 'domain', {'snow_regime':[1,2,3,4], 'small_ice':[0,1]})")
        if volcanic:
            source=replace_once(source,'math.cos(math.radians(145)), math.sin(math.radians(145))','math.sin(math.radians(145)), -math.cos(math.radians(145))')
        # AST unparse has normalised formatting, so insert guards structurally.
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.With) and len(node.items)==1:
                call=node.items[0].context_expr
                if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='open' and call.args and isinstance(call.args[0],ast.Name) and call.args[0].id=='diag_path':
                    node.body=ast.parse("diagnostic_grid = (ds.transform, ds.crs, ds.width, ds.height)\nif ds.nodata != -9999.: raise ValueError('hazard diagnostic NODATA differs')").body+node.body
                if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='open' and call.args and isinstance(call.args[0],ast.Name) and call.args[0].id in ('sup_path','support_path'):
                    node.body=ast.parse("if (ds.transform, ds.crs, ds.width, ds.height) != diagnostic_grid: raise ValueError('hazard diagnostic/support spatial grid mismatch')\n_core.require_hazard_stack(ds.read(), d['domain'], len(PROCESSES))\nif ds.nodata != 255: raise ValueError('hazard support NODATA differs')").body+node.body
        source=ast.unparse(ast.fix_missing_locations(tree))
        # Pilot evidence is Boolean throughout its halo, unlike NODATA-masked TIFs.
        source=source.replace('z[key].astype(bool)',"_core.require_binary_support(z[key], np.ones(z[key].shape, dtype=bool)).astype(bool)")
        names={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}-{'validate_package'}
        return _compile(relative,names,source,ctx)
    if component=='hazard_vh':
        relative='work/volcanic_hazard/build_vh1_static_support.py'
        source=checked_source(relative)
        source=replace_once(source,'math.cos(math.radians(145)), math.sin(math.radians(145))','math.sin(math.radians(145)), -math.cos(math.radians(145))')
        source=_prepend(source,'classify',"_core.finite_required_fields(d, 'domain', {'small_ice': (0,1), 'snow_regime': (1,2,3,4)})")
        ctx['zoom']=_geology_zoom
        return _compile(relative,{'classify','support_stack','geology_field','route_receiver','downstream_closure','buffered','source_distance','direction_sector'},source,ctx)
    if component=='hg0_package':
        relative='work/hydrogeology/hg0_r2_scientific_correction/scripts/build_hg0_r2_correction.py'
        source=checked_source(relative)
        source=replace_once(source,'    files=[]\n    for p in sorted(OUT.rglob("*")):', '    _identity.require_pass(validation)\n    _identity.require_payload_release(OUT, PACKAGE_MACHINE_ATTESTATION, PACKAGE_VISUAL_ATTESTATION, ("audit/HG0_R2_1_PACKAGE_VALIDATION.json",))\n    files=[]\n    for p in sorted(OUT.rglob("*")):')
        source=replace_once(source,'    if ZIP_PATH.exists(): ZIP_PATH.unlink()',"    if ZIP_PATH.exists(): raise RuntimeError('immutable archive already exists')")
        return _compile(relative,{'make_manifest_and_zip'},source,ctx)
    if component in ('bathymetry_release','marine_release'):
        relative=('work/surface_hydrology/bs1_obsidian_sea_bathymetry_support_preflight/finalize_preflight.py'
                  if component=='bathymetry_release' else 'work/surface_hydrology/ws1_obsidian_sea_wind_seiche_shore_preflight/finalize_ws1_preflight.py')
        source=checked_source(relative)
        source=replace_once(source,'    if ZIP.exists():\n        ZIP.unlink()',"    if ZIP.exists():\n        raise RuntimeError('immutable archive already exists')")
        source=replace_once(source,'    if validation["status"] != "PASS" or visual["status"] != "PASS":', '    _identity.require_payload_release(OUT, validation, visual, ("audit/INDEPENDENT_VALIDATION.json", "audit/VISUAL_REVIEW_ATTESTATION.json"))\n    if validation["status"] != "PASS" or visual["status"] != "PASS":')
        return _compile(relative,{'main','sha256','arcname'},source,ctx)
    if component=='climate_package':
        relative='work/climate_ecology/c1_production/scripts/build_c1_full_production.py'
        source=checked_source(relative)
        source=_prepend(source,'package','_identity.require_payload_release(RUN, PACKAGE_MACHINE_ATTESTATION, PACKAGE_VISUAL_ATTESTATION)')
        source=source.replace('if OUT.exists():shutil.rmtree(OUT)',"if OUT.exists():raise RuntimeError('immutable output already exists')")
        source=source.replace('if ZIP.exists():ZIP.unlink()',"if ZIP.exists():raise RuntimeError('immutable archive already exists')")
        source=source.replace('os.link(p,dest)','shutil.copy2(p,dest)')
        return _compile(relative,{'package'},source,ctx)
    if component=='climate_corrected_package':
        relative='work/climate_ecology/c1_production/scripts/package_c1_corrected_review.py'
        source=checked_source(relative)
        source=_prepend(source,'main','_identity.require_payload_release(RUN, PACKAGE_MACHINE_ATTESTATION, PACKAGE_VISUAL_ATTESTATION)')
        source=source.replace('        shutil.rmtree(OUT)',"        raise RuntimeError('immutable output already exists')")
        source=source.replace('            path.unlink()',"            raise RuntimeError('immutable archive or sidecar already exists')")
        source=source.replace('hardlink=True','hardlink=False')
        return _compile(relative,{'main','sha256','write_json','copy_tree_files','check_gate'},source,ctx)
    if component=='r14_release':
        relative='work/climate_ecology/c1r2_seam_repair/finalize_r1t14_climate_review.py'
        source=checked_source(relative)
        start=source.index('    annual_audit["visual_adjudication"] = {')
        end=source.index('    if annual_audit["accepted_geometry_pass"]:',start)
        source=source[:start]+'''    annual_audit["visual_adjudication"] = _identity.visual_adjudication(annual_audit, VISUAL_ATTESTATION, ROOT)
    annual_audit["accepted_geometry_pass"] = bool(annual_audit["machine_pass"] or annual_audit["visual_adjudication"]["pass"])
'''+source[end:]
        ctx.setdefault('VISUAL_ATTESTATION',None)
        names={n.name for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        return _compile(relative,names,source,ctx)
    if component=='biome_builder':
        relative='work/biome_map/bm1r4_builder/build_bm1r4_1km.py'
        source=checked_source(relative)
        source=replace_once(source,'    return lineage\n','    _identity.finish_manifest(out)\n    return lineage\n')
        source=replace_once(source,'key = (str(Path(ds.name).resolve()), EDAPHIC_FEATHER_KM, float(cell_size_km))','key = (str(Path(ds.name).resolve()), _identity.sha256(ds.name), EDAPHIC_FEATHER_KM, float(cell_size_km))')
        source=_prepend(source,'build_full',"if replace or Path(out).exists(): raise ValueError('successor output must be new; overwrite is forbidden')")
        ctx.setdefault('_WEIGHT_CACHE',{})
        ctx['edaphic_feather_weight']=core.edaphic_weight
        return _compile(relative,{'build_full','_full_feather_weight'},source,ctx)
    raise ValueError(f'unknown successor component: {component}')


def macro_source():
    """The current R12→R14 science, with a conserved lake component pre-budget.

    Returns source, not an executing main. Caller must provide the frozen field
    bindings/configuration and normal source/canon gates before a production run.
    """
    relative='work/climate_ecology/c0r3_natural_geometry/build_c0r3_natural_geometry.py'
    source=checked_source(relative)
    r12='work/climate_ecology/c1r2_seam_repair/run_r1t12_single_climate_probe.py'
    function=next(n for n in ast.parse(checked_source(r12)).body if isinstance(n,ast.FunctionDef) and n.name=='transformed_source')
    replacement_node=next(n for n in function.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='replacements' for t in n.targets))
    for old,new,label in ast.literal_eval(replacement_node.value):
        source=replace_once(source,old,new)
    # Unlike R13's old multiplication after addition, make source attribution
    # explicit and keep budget() and final precip on these same components.
    anchor='    # Calibrate the single amplitude to the approved Titan discharge through a closed annual budget.'
    correction='''    precip_external_raw, lake_precip = _core.corrected_precipitation_components(
        precip_external_raw, lake_precip, R1T13_CORRECTION, AREA_CELL,
        basin.astype(bool), recycled_lake_effect_km3 *
        (recycle_month.astype(np.float64) / math.fsum(recycle_month.astype(np.float64).tolist())) * 1e6)
'''
    source=replace_once(source,anchor,correction+'\n'+anchor)
    source=_replace_body(source,'fu_aet','return _core.fu_aet(p_annual, pet_annual, omega)')
    source=_prepend(source,'ensure_clean_output',"if OUT.exists(): raise RuntimeError('successor output must be new; historic output replacement forbidden')")
    # Compiling main does not grant permission to invoke its I/O. The first
    # instruction refuses any invocation until its external run gate is bound.
    source=_prepend(source,'main','_SUCCESSOR_RUN_GATE()')
    return source,{'predecessors':{str(ROOT/p):PINS['sources'][p] for p in (relative,r12)},
                   'transformed_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                   'current_profile':'R12 pathways + R14 delivery pattern, prescribed lake volume conserved',
                   'generation':'NOT_RUN; original source/canon gates and frozen field bindings remain required'}


def macro_component_fixture(external,lake,correction,cell_area,domain,monthly_volume):
    """Execute the exact corrected assignment from the compiled real main."""
    source,receipt=macro_source()
    main=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    assignment=next(n for n in main.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='corrected_precipitation_components')
    # The target volume is supplied directly to preserve the interface's exact
    # monthly source units in tiny fixtures, avoiding unrelated scenario setup.
    volume=core.finite_array(monthly_volume,'monthly volume',True)
    total=math.fsum(volume.tolist())
    scope={'_core':core,'np':np,'math':math,'precip_external_raw':external,'lake_precip':lake,
           'R1T13_CORRECTION':correction,'AREA_CELL':cell_area,'basin':domain,
           'recycled_lake_effect_km3':total/1e6,'recycle_month':volume if total else np.ones(12)}
    exec(compile(ast.Module(body=[assignment],type_ignores=[]),receipt['predecessors'].__iter__().__next__(),'exec'),scope)
    return scope['precip_external_raw'],scope['lake_precip'],receipt
