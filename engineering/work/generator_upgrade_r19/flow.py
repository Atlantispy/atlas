"""R19 first-order hydrostatic HLL receiving water; no wave-driven mean flow.

Stocks and equal/opposite phase transfers are exact represented rationals.
Constitutive fluxes and integrated mixture-volume momentum (m4/s) are binary64.
Each call is ONE frozen explicit substep; the driver owns time/step budgets.
"""
from copy import copy
from fractions import Fraction as F
import math

from . import state as st

SCHEMA = 'diadem.coastal-hydrostatic-hll.r19'
CFL = 0.25
EPS = 2.220446049250313e-16


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError(name + ': Boolean is not a physical number')
    exact = st.q(value, name)
    result = float(exact)
    if (not math.isfinite(result) or (positive and result <= 0)
            or (nonnegative and result < 0) or (exact and result == 0)):
        raise ValueError(name + ': finite permitted value required')
    return result


def _vector(value, name):
    if type(value) not in (tuple, list) or len(value) != 2:
        raise ValueError(name + ': explicit two-vector required')
    return tuple(_number(v, name) for v in value)


def _clone(cell, *, empty=False):
    result = copy(cell)
    result.pores = list(cell.pores)
    result.suspended = {} if empty else dict(cell.suspended)
    result.free = F() if empty else cell.free
    result.momentum = tuple(cell.momentum)
    return result


def validate_geometry(cells, faces, links):
    """Require explicit closed water-cell faces; reaches have only links."""
    if type(cells) is not dict or not 1 <= len(cells) <= 32:
        raise ValueError('one to 32 explicit receiving/reach cells required')
    if any(type(k) is not str or not k or c.kind not in ('water', 'reach')
           for k, c in cells.items()):
        raise ValueError('stable cell IDs and explicit hydraulic kinds required')
    if (type(faces) not in (list, tuple) or type(links) not in (list, tuple)
            or len(faces) > 512 or len(links) > 256):
        raise ValueError('bounded explicit face/link inventory required')
    ids, pairs, walls = set(), set(), set()
    closure = {k: [[], []] for k, c in cells.items() if c.kind == 'water'}
    scales = {k: [] for k in closure}
    for face in faces:
        if type(face) is not dict or set(face) != {'id', 'left', 'right', 'width_m', 'normal_xy'}:
            raise ValueError('exact hydrostatic face schema required')
        fid, left, right = face['id'], face['left'], face['right']
        if type(fid) is not str or not fid or fid in ids:
            raise ValueError('unique nonempty hydraulic ID required')
        ids.add(fid)
        if left not in closure or (right is not None and (right not in closure or right == left)):
            raise ValueError('hydrostatic faces require water cells; None is an explicit wall')
        width = _number(face['width_m'], 'face width', positive=True)
        normal = _vector(face['normal_xy'], 'outward-left normal')
        if abs(math.hypot(*normal)-1.) > 64*EPS:
            raise ValueError('face normal must be unit length, not silently normalised')
        key = (left, normal)
        if right is None:
            if key in walls:
                raise ValueError('duplicate wall face')
            walls.add(key)
        else:
            key = frozenset((left, right))
            if key in pairs:
                raise ValueError('duplicate internal hydraulic adjacency')
            pairs.add(key)
        for cell, sign in ((left, 1), (right, -1)):
            if cell is not None:
                scales[cell].append(width)
                for axis in range(2):
                    closure[cell][axis].append(sign*width*normal[axis])
    for cell in closure:
        scale = math.fsum(scales[cell])
        if not scale or not math.isfinite(scale) or any(
                abs(math.fsum(values)) > 64*EPS*scale for values in closure[cell]):
            raise ValueError('missing/nonclosing explicit water-cell boundary: ' + cell)
    for link in links:
        if type(link) is not dict or set(link) != {'id', 'left', 'right', 'crest_m', 'conductance_m2_s'}:
            raise ValueError('exact reduced mouth-link schema required')
        lid, left, right = link['id'], link['left'], link['right']
        if type(lid) is not str or not lid or lid in ids:
            raise ValueError('unique nonempty hydraulic ID required')
        ids.add(lid)
        if left not in cells or right not in cells or left == right:
            raise ValueError('link requires distinct finite stored endpoints')
        key = frozenset((left, right))
        if key in pairs:
            raise ValueError('duplicate face/link hydraulic adjacency')
        pairs.add(key)
        _number(link['crest_m'], 'registered or scenario crest')
        _number(link['conductance_m2_s'], 'link conductance', nonnegative=True)
    return {'normal_closure_m': {k: [math.fsum(v) for v in values]
                                 for k, values in closure.items()},
            'boundary_semantics': 'Explicit reflecting fixture walls; not inferred geographic sea boundaries'}


def _hll(hleft, hright, uleft, uright, normal, gravity):
    """Flux in global coordinates per unit face width, reconstructed depths."""
    hl, hr = float(hleft), float(hright)
    ul = math.fsum(a*b for a, b in zip(uleft, normal))
    ur = math.fsum(a*b for a, b in zip(uright, normal))
    cl, cr = math.sqrt(gravity*hl), math.sqrt(gravity*hr)
    if hl == hr == 0:
        return (0., 0., 0.), 0.
    if hleft == hright and uleft == uright == (0., 0.):
        # Identical reconstructed rest states: evaluate pressure using the
        # exact same floating expression as the well-balanced source below.
        return (0., *(.5*gravity*hl**2*n for n in normal)), cl
    if hr == 0:
        sl, sr = ul-cl, ul+2*cl
    elif hl == 0:
        sl, sr = ur-2*cr, ur+cr
    else:
        sl, sr = min(ul-cl, ur-cr), max(ul+cl, ur+cr)
    vl = (hl, hl*uleft[0], hl*uleft[1])
    vr = (hr, hr*uright[0], hr*uright[1])
    fl = (hl*ul, *(hl*ul*uleft[i]+.5*gravity*hl*hl*normal[i] for i in range(2)))
    fr = (hr*ur, *(hr*ur*uright[i]+.5*gravity*hr*hr*normal[i] for i in range(2)))
    if sl >= 0:
        flux = fl
    elif sr <= 0:
        flux = fr
    else:
        flux = tuple(math.fsum((sr*fl[i], -sl*fr[i], sl*sr*(vr[i]-vl[i])))/(sr-sl)
                     for i in range(3))
    if any(not math.isfinite(v) for v in (*flux, sl, sr)):
        raise ValueError('HLL flux/wave speed is not representable')
    return flux, max(abs(sl), abs(sr))


def _prepared(cells, palette, faces, links, constants, parameters, forcing):
    geometry = validate_geometry(cells, faces, links)
    gravity = _number(constants['gravity_m_s2'], 'gravity', positive=True)
    density = _number(constants['water_density_kg_m3'], 'water density', positive=True)
    drag = _number(parameters['bottom_drag_coefficient'], 'bottom drag', nonnegative=True)
    wind = _vector(forcing['wind_stress_Pa'], 'explicit wind stress')
    old = {k: _clone(c) for k, c in cells.items()}
    for cell in old.values():
        cell.validate(palette)
        _number(cell.column.area_m2, 'hydraulic area', positive=True)
        _number(cell.depth(palette), 'mixture depth', nonnegative=True)
        _vector(cell.velocity(palette), 'velocity')
    rows, drains, speeds = [], {k: [] for k in old}, {k: [] for k in old}
    for face in faces:
        left, right = face['left'], face['right']
        l = old[left]; r = old[right] if right is not None else l
        normal = _vector(face['normal_xy'], 'normal')
        width = _number(face['width_m'], 'width', positive=True)
        bed = max(l.column.surface_m, r.column.surface_m)
        hl, hr = max(l.eta(palette)-bed, F()), max(r.eta(palette)-bed, F())
        ul, ur = l.velocity(palette), r.velocity(palette)
        if right is None:
            un = math.fsum(a*b for a, b in zip(ul, normal))
            ur = tuple(ul[i]-2*un*normal[i] for i in range(2))
        flux, speed = _hll(hl, hr, ul, ur, normal, gravity)
        if right is None and any(ul):
            # Reflection has exactly zero mass and tangential momentum flux.
            pressure = math.fsum(flux[i+1]*normal[i] for i in range(2))
            flux = (0., *(pressure*v for v in normal))
        flow = width*flux[0]
        for cell in (left, right):
            if cell is not None:
                speeds[cell].append(width*speed)
        donor = left if flow > 0 else right
        if flow and donor is not None:
            drains[donor].append(abs(flow))
        rows.append({'id': face['id'], 'left': left, 'right': right, 'q': flow,
                     'width': width, 'normal': normal, 'flux': flux,
                     'hl': float(hl), 'hr': float(hr), 'kind': 'face'})
    for link in links:
        left, right = link['left'], link['right']
        crest = st.q(link['crest_m'])
        conductance = st.q(link['conductance_m2_s'], nonnegative=True)
        difference = max(old[left].eta(palette)-crest, F())-max(old[right].eta(palette)-crest, F())
        flow = _number(conductance*difference, 'signed reduced-link discharge')
        raw_flow = flow
        dry_limited = bool(flow and not old[left if flow > 0 else right].volume(palette))
        effective_crest = max(crest, old[left].column.surface_m, old[right].column.surface_m)
        # A newly deposited bed cannot be a hidden below-ground conduit. The
        # explicit fixed sill is retained, while obstructing native beds evolve.
        open_difference = (max(old[left].eta(palette)-effective_crest, F())
                           -max(old[right].eta(palette)-effective_crest, F()))
        flow = _number(conductance*open_difference, 'bed-aware signed mouth discharge')
        if dry_limited:
            flow = 0.  # Owner availability cap: a dry bed supplies no fluid.
        if flow:
            drains[left if flow > 0 else right].append(abs(flow))
        rows.append({'id': link['id'], 'left': left, 'right': right, 'q': flow,
                     'kind': 'link', 'conductance': float(conductance),
                     'raw_q': raw_flow, 'dry_donor_limited': dry_limited,
                     'fixed_crest': crest, 'effective_crest': effective_crest})
    return old, rows, drains, speeds, (gravity, density, drag, wind), geometry


def _limit(old, rows, drains, speeds, palette, maximum):
    limit = maximum
    for key, cell in old.items():
        wave = math.fsum(speeds[key]); outflow = math.fsum(drains[key])
        if wave:
            limit = min(limit, CFL*float(cell.column.area_m2)/wave)
        if outflow:
            limit = min(limit, CFL*float(cell.volume(palette))/outflow)
    for row in rows:
        if row['kind'] == 'link' and row['conductance']:
            inverse_area = sum(1/float(old[k].column.area_m2) for k in (row['left'], row['right']))
            limit = min(limit, CFL/(row['conductance']*inverse_area))
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError('positive hydraulic substep cannot be represented')
    return limit


def stable_dt(cells, palette, faces, links, constants, parameters, forcing, maximum_s):
    data = _prepared(cells, palette, faces, links, constants, parameters, forcing)
    maximum = _number(maximum_s, 'maximum hydraulic step', positive=True)
    return _limit(*data[:4], palette, maximum)


def advance(cells, palette, faces, links, dt_s, constants, parameters, forcing):
    """Validate, calculate, then atomically commit one conservative substep."""
    dt = _number(dt_s, 'hydraulic step', positive=True)
    old, rows, drains, speeds, physics, geometry = _prepared(
        cells, palette, faces, links, constants, parameters, forcing)
    allowed = _limit(old, rows, drains, speeds, palette, dt)
    if dt > allowed:
        raise ValueError('hydraulic step exceeds positivity/CFL bound; reduce dt')
    gravity, density, drag, wind = physics
    result = {k: _clone(c) for k, c in old.items()}
    impulses = {k: [[], []] for k in old}
    ports = {name: [[], []] for name in ('reflecting_wall', 'bed_source', 'closure_compensation',
                                        'reduced_link_support', 'wind', 'bottom_drag')}
    records, discrepancy = [], F()
    for row in rows:
        left, right, flow = row['left'], row['right'], row['q']
        if row['kind'] == 'face':
            n, width, flux = row['normal'], row['width'], row['flux']
            for key, sign, reconstructed in ((left, -1, row['hl']), (right, 1, row['hr'])):
                if key is None:
                    continue
                depth = float(old[key].depth(palette))
                for axis in range(2):
                    # Local constant-pressure subtraction sums to zero on a
                    # closed cell. This avoids catastrophic rest-state cancellation.
                    impulse = sign*dt*width*(flux[axis+1]-.5*gravity*reconstructed**2*n[axis])
                    impulses[key][axis].append(impulse)
                    ports['bed_source'][axis].append(sign*dt*width*.5*gravity*(depth**2-reconstructed**2)*n[axis])
                    ports['closure_compensation'][axis].append(-sign*dt*width*.5*gravity*depth**2*n[axis])
                    if right is None:
                        ports['reflecting_wall'][axis].append(-dt*width*flux[axis+1])
        if not flow:
            continue
        donor, receiver = (left, right) if flow > 0 else (right, left)
        requested = st.q(abs(flow)*dt, 'represented mixture request', nonnegative=True)
        if not requested:
            raise ValueError('positive hydraulic transfer underflows representation')
        # Independent copies preserve the actual OLD donor composition at every
        # face; all equal/opposite stock deltas are accumulated before commit.
        parcel = st.transfer(_clone(old[donor]), _clone(old[receiver], empty=True), palette, requested)
        result[donor].free -= parcel['free']; result[receiver].free += parcel['free']
        for mid, mass in parcel['materials'].items():
            result[donor].suspended[mid] -= mass
            result[receiver].suspended[mid] = result[receiver].suspended.get(mid, F())+mass
        actual = parcel['volume']; discrepancy += abs(actual-requested)
        if row['kind'] == 'link':
            velocity = old[donor].velocity(palette)
            for axis in range(2):
                impulse = float(actual)*velocity[axis]
                impulses[donor][axis].append(-impulse)
                if old[receiver].kind == 'water':
                    impulses[receiver][axis].append(impulse)
                else:
                    ports['reduced_link_support'][axis].append(-impulse)
        records.append({'id': row['id'], 'kind': row['kind'], 'donor': donor, 'receiver': receiver,
                        'requested_mixture_m3': requested, 'actual_mixture_m3': actual,
                        'signed_discharge_m3_s': flow, 'free_liquid_m3': parcel['free'],
                        'dry_material_kg': parcel['materials'], 'volume_representation_error_m3': actual-requested})
    for key, cell in result.items():
        volume = cell.volume(palette)
        momentum = tuple(math.fsum((old[key].momentum[i], *impulses[key][i])) for i in range(2))
        if not volume and any(momentum):
            raise ValueError('dry momentum after hydraulic transfer; refine, do not clip')
        if cell.kind == 'reach':
            for i in range(2):
                ports['reduced_link_support'][i].append(-momentum[i])
            momentum = (0., 0.)
        elif volume:
            area, depth = float(cell.column.area_m2), float(cell.depth(palette))
            wind_impulse = tuple(dt*area*v/density for v in wind)
            driven = tuple(momentum[i]+wind_impulse[i] for i in range(2))
            speed = math.hypot(*driven)/float(volume)
            denominator = 1.+drag*speed*dt/depth
            if not math.isfinite(denominator):
                raise ValueError('bottom drag decay is not representable')
            damped = tuple(v/denominator for v in driven)
            for i in range(2):
                ports['wind'][i].append(wind_impulse[i])
                ports['bottom_drag'][i].append(damped[i]-driven[i])
            momentum = damped
        cell.momentum = momentum
        cell.validate(palette)
    port_totals = {name: [math.fsum(v) for v in axes] for name, axes in ports.items()}
    residual = [math.fsum([*(result[k].momentum[i]-old[k].momentum[i] for k in old),
                           *(-v[i] for v in port_totals.values())]) for i in range(2)]
    rounding_bounds = [128*EPS*math.fsum([
        *(abs(old[k].momentum[i])+abs(result[k].momentum[i]) for k in old),
        *(abs(v) for k in old for v in impulses[k][i]),
        *(abs(v) for axes in ports.values() for v in axes[i])]) for i in range(2)]
    if any(not math.isfinite(v) for v in (*residual, *rounding_bounds)) or any(
            abs(residual[i]) > rounding_bounds[i] for i in range(2)):
        raise ValueError('momentum account exceeds its operand-roundoff bound')
    # Per-phase exact equal/opposite identities are checked independently of HLL.
    if sum((c.free for c in result.values()), F()) != sum((c.free for c in old.values()), F()):
        raise ArithmeticError('internal liquid face balance failed')
    mids = {mid for c in old.values() for mid in c.suspended}
    if any(sum((c.suspended.get(mid, F()) for c in result.values()), F()) !=
           sum((c.suspended.get(mid, F()) for c in old.values()), F()) for mid in mids):
        raise ArithmeticError('internal suspended material face balance failed')
    receipt = st.plain({'schema': SCHEMA, 'duration_s': dt, 'cfl': CFL, 'geometry': geometry,
        'transfers': records, 'gross_mixture_transfer_m3': sum((r['actual_mixture_m3'] for r in records), F()),
        'link_demands': [{'id': r['id'], 'head_law_discharge_m3_s': r['raw_q'],
                         'fixed_crest_m': r['fixed_crest'], 'effective_current_bed_crest_m': r['effective_crest'],
                         'signed_head_law_demand_m3': F(r['raw_q'])*F(dt),
                         'effective_discharge_m3_s': r['q'],
                         'dry_donor_availability_cap': r['dry_donor_limited']}
                        for r in rows if r['kind'] == 'link'],
        'phase_volume_representation_error_bound_m3': discrepancy,
        'momentum_ports_m4_s': port_totals, 'momentum_representation_residual_m4_s': residual,
        'momentum_operand_roundoff_bound_m4_s': rounding_bounds,
        'method': 'Hydrostatic reconstructed HLL; first-order frozen donor phase fractions; exact represented stock splits; quadratic bottom-drag constant-depth decay after wind',
        'scope': 'Dilute constant-water-density barotropic inertia. Reduced links have finite stocks, not river momentum equations; their reach support absorbs declared momentum. No wave forcing of mean flow, tides, salinity or groundwater.'})
    for key, cell in result.items():
        cells[key].free, cells[key].suspended, cells[key].momentum = cell.free, cell.suspended, cell.momentum
    return receipt
