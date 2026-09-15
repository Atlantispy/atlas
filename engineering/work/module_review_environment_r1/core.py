"""Explicit numerical/data contracts used by the pinned producer successors."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.linalg import solve_banded
from scipy.ndimage import distance_transform_edt


def boolean_mask(value, shape=None, name='mask'):
    a = np.asarray(value)
    if a.dtype.kind != 'b' or (shape is not None and a.shape != shape):
        raise ValueError(f'{name} must be a Boolean array on the exact grid')
    return a


def positive_scalar(value, name='value', zero=False):
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        raise ValueError(f'{name} must be a real scalar')
    x = float(value)
    if not math.isfinite(x) or (x < 0 if zero else x <= 0):
        raise ValueError(f'{name} is outside the finite permitted range')
    return x


def finite_array(value, name='array', nonnegative=False):
    a = np.asarray(value, dtype=np.float64)
    if not np.all(np.isfinite(a)) or (nonnegative and np.any(a < 0)):
        raise ValueError(f'{name} must be finite' + (' and nonnegative' if nonnegative else ''))
    return a


def integer(value, name='integer', minimum=1):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return int(value)


def conservative_coefficients(field, fine):
    """Invert the actual child-centre average, including singleton dimensions."""
    n = integer(fine, 'fine')
    a = finite_array(field, 'parent field')
    if a.ndim != 2 or min(a.shape) < 1:
        raise ValueError('parent field must be a nonempty 2D grid')
    offset = (np.arange(n, dtype=np.float64) + .5) / n - .5
    weight = float(np.maximum(-offset, 0).mean())
    def band(size):
        b = np.zeros((3, size))
        b[0, 1:] = weight; b[2, :-1] = weight
        b[1] = 1 - 2*weight; b[1, 0] = b[1, -1] = 1 - weight
        if size == 1:
            b[1, 0] = 1.
        return b
    y = solve_banded((1, 1), band(a.shape[0]), a, check_finite=True)
    out = solve_banded((1, 1), band(a.shape[1]), y.T, check_finite=True).T
    if not np.all(np.isfinite(out)):
        raise ValueError('reconstruction coefficients not representable')
    return out


def fu_aet(precipitation, pet, omega=3.4):
    """Stable Fu equation preserving the actual available-water upper bound."""
    p, e = np.broadcast_arrays(finite_array(precipitation, 'precipitation', True), finite_array(pet, 'PET', True))
    w = positive_scalar(omega, 'omega')
    if w <= 1:
        raise ValueError('Fu omega must exceed one')
    low = np.minimum(p, e); high = np.maximum(p, e)
    ratio = np.divide(low, high, out=np.zeros_like(low), where=high > 0)
    loss = high * np.expm1(np.log1p(ratio**w) / w)
    return np.clip(low-loss, 0, low)


def corrected_precipitation_components(external, lake, correction, cell_area, domain, monthly_lake_volume_mm_km2):
    """Correct spatial delivery without changing a prescribed recycled source.

    Lake input already includes its wet/dry fractional allocation. Integrate
    over *cell area*, not land fraction a second time. Volume is mm km2.
    """
    ext = finite_array(external, 'external precipitation', True)
    lk = finite_array(lake, 'lake precipitation', True)
    factor = finite_array(correction, 'delivery correction', True)
    if ext.ndim != 3 or ext.shape[0] != 12 or lk.shape != ext.shape or factor.shape != ext.shape:
        raise ValueError('precipitation components/correction must be (12,row,col) on identical grids')
    mask = boolean_mask(domain, ext.shape[1:], 'basin')
    area = np.broadcast_to(finite_array(cell_area, 'cell area', True), mask.shape)
    if not mask.any() or np.any(area[mask] <= 0):
        raise ValueError('basin must have positive known cell areas')
    target = finite_array(monthly_lake_volume_mm_km2, 'monthly recycled volumes', True)
    if target.shape != (12,):
        raise ValueError('monthly recycled volume must contain twelve entries')
    if np.any(lk[:, ~mask] != 0):
        raise ValueError('lake deposition outside declared basin')
    out = np.zeros_like(lk)
    with np.errstate(over='raise', invalid='raise', divide='raise'):
        try:
            corrected_external = ext * factor
            # Scaling before multiplying avoids finite-factor product overflow.
            for m in range(12):
                if target[m] == 0:
                    continue
                shape = lk[m, mask]
                f = factor[m, mask]
                if not np.any(shape > 0) or not np.any((shape > 0) & (f > 0)):
                    raise ValueError('positive recycled source has no corrected deposition support')
                shape = shape / shape.max()
                f = f / f.max()
                pattern = shape * f
                integral = math.fsum((pattern * area[mask]).tolist())
                if not math.isfinite(integral) or integral <= 0:
                    raise ValueError('corrected recycled integral not representable')
                out[m, mask] = pattern * (target[m] / integral)
        except FloatingPointError as exc:
            raise ValueError('corrected precipitation not representable') from exc
    if not np.all(np.isfinite(out)) or not np.all(np.isfinite(corrected_external)):
        raise ValueError('corrected precipitation not representable')
    for m in range(12):
        actual = math.fsum((out[m, mask]*area[mask]).tolist())
        if not math.isclose(actual, target[m], rel_tol=2e-13, abs_tol=0.):
            raise ValueError('recycled water did not close to its declared volume')
    return corrected_external, out


def edaphic_weight(valid_mask, cell_size_km, scale_km=30.):
    valid = boolean_mask(valid_mask)
    cell = positive_scalar(cell_size_km, 'cell size')
    scale = positive_scalar(scale_km, 'feather scale')
    if valid.ndim != 2 or min(valid.shape) < 1:
        raise ValueError('edaphic mask must be a nonempty 2D array')
    if valid.all():
        return np.ones(valid.shape, np.float32)
    if not valid.any():
        return np.zeros(valid.shape, np.float32)
    distance = distance_transform_edt(valid) * cell
    if not np.all(np.isfinite(distance)):
        raise ValueError('edaphic distance not representable')
    result = -np.expm1(-distance/scale)
    result[~valid] = 0
    return result.astype(np.float32)


def exact_difference(actual, expected):
    """Fail on mask/nonfinite mismatch before any tolerance calculation."""
    a, b = np.asarray(actual), np.asarray(expected)
    if a.shape != b.shape or a.dtype.kind not in 'fiu' or b.dtype.kind not in 'fiu':
        raise ValueError('numeric arrays must have identical shapes')
    fa, fb = np.isfinite(a), np.isfinite(b)
    if not np.array_equal(fa, fb) or np.any(np.isinf(a)) or np.any(np.isinf(b)):
        raise ValueError('known/UNKNOWN mismatch or infinite value')
    delta = np.abs(a[fa].astype(np.float64)-b[fa].astype(np.float64))
    if not np.all(np.isfinite(delta)):
        raise ValueError('difference not representable')
    return delta


def require_float_comparison(actual, expected):
    exact_difference(actual, expected)
    # Historical comparator counts NaN differences; replace matching UNKNOWN
    # with identical zero only *after* equality of masks was established.
    a, b = np.asarray(actual).copy(), np.asarray(expected).copy()
    unknown = ~np.isfinite(a)
    a[unknown] = 0; b[unknown] = 0
    return a, b


def protected_union(shape, row_start, col_start, systems):
    if len(shape) != 2:
        raise ValueError('two grid dimensions required')
    rows, cols = [integer(x, 'shape') for x in shape]
    rstart, cstart = integer(row_start, 'row start', 0), integer(col_start, 'column start', 0)
    rectangles = []
    for s in systems:
        rr = tuple(s['rows_100m_half_open']); cc = tuple(s['cols_100m_half_open'])
        if len(rr) != 2 or len(cc) != 2:
            raise ValueError('rectangle needs two endpoints per axis')
        r0,r1,c0,c1 = [integer(x, 'rectangle endpoint', 0) for x in (*rr,*cc)]
        if r0>=r1 or c0>=c1:
            raise ValueError('rectangle must have positive area')
        rectangles.append((r0,r1,c0,c1))
    result = np.zeros((rows, cols))
    # At most 100 exact subcell states per output cell; union, not additive overlap.
    # Blocks limit scratch to ten fine rows independently of world height.
    for r in range(rows):
        occupancy = np.zeros((10, cols*10), bool)
        y0=(rstart+r)*10; x0=cstart*10
        for r0,r1,c0,c1 in rectangles:
            a,b=max(r0,y0)-y0,min(r1,y0+10)-y0
            c,d=max(c0,x0)-x0,min(c1,x0+cols*10)-x0
            if a<b and c<d:
                occupancy[a:b,c:d] = True
        result[r] = occupancy.reshape(10,cols,10).sum(axis=(0,2))/100.
    return result


def valid_envelope_inputs(values, expected_count):
    a = np.asarray(values, np.float64); e=np.asarray(expected_count)
    if a.ndim!=4 or a.shape[1]!=12 or e.shape!=a.shape[2:]:
        raise ValueError('envelope input shape mismatch')
    if e.dtype.kind not in 'iu' or np.any(e<0) or np.any(e>a.shape[0]):
        raise ValueError('expected count must be an integer from zero to scenario count')
    if np.any(np.isinf(a)):
        raise ValueError('infinite scenario values are not UNKNOWN')
    return a,e


def aggregate_depth_inputs(depth, counts, factor):
    d=np.asarray(depth, np.float64); c=np.asarray(counts)
    integer(factor, 'aggregation factor')
    if d.ndim!=2 or c.shape!=d.shape or c.dtype.kind not in 'iu' or np.any(c<0):
        raise ValueError('wet counts must be nonnegative integers on the depth grid')
    if not np.all(np.isfinite(d[c>0])) or np.any(d[c>0]<=0):
        raise ValueError('positive-area water must have known positive depth')
    return np.where(c>0,d,0.),c


def weighted_fields(values,weights,sigma):
    v=np.asarray(values,np.float64);w=finite_array(weights,'weights',True)
    positive_scalar(sigma,'smoothing sigma',zero=True)
    if v.ndim!=2 or w.shape!=v.shape or not np.all(np.isfinite(v[w>0])):
        raise ValueError('positive-weight source must be known on the same 2D grid')
    scale=float(w.max(initial=0))
    if scale>0:w=w/scale
    return np.where(w>0,v,0.),w


def bathymetry_children(mask,terrain):
    m=np.asarray(mask);z=np.asarray(terrain)
    if m.ndim!=2 or z.shape!=m.shape or not np.all(np.isin(m,[0,1])):
        raise ValueError('bathymetry child grid requires known binary wet mask')
    if not np.all(np.isfinite(z[m==1])):
        raise ValueError('submerged child elevation must be known')
    return m,z


def root_load_lookup(roots,records):
    ids=np.asarray(roots['ids']);loads=finite_array(roots['loads'],'monthly root loads',True)
    if ids.ndim!=1 or ids.dtype.kind not in 'iu' or loads.shape!=(ids.size,12) or np.any(ids<0) or len(np.unique(ids))!=ids.size:
        raise ValueError('root IDs/loads must be unique, integral and aligned')
    record_ids=[r['root_cell_id'] for r in records]
    if any(isinstance(i,(bool,np.bool_)) or not isinstance(i,(int,np.integer)) for i in record_ids):
        raise ValueError('record root IDs must be integers')
    if len(set(record_ids))!=len(record_ids) or set(record_ids)!=set(ids.tolist()):
        raise ValueError('candidate root IDs do not exactly match load root IDs')
    if 'types' in roots:
        types=np.asarray(roots['types'])
        if types.shape!=ids.shape or not np.all(np.isin(types,[1,2,3,4])):
            raise ValueError('invalid root terminal types')
        expected=dict(zip(ids.tolist(),types.tolist()))
        if any(r['terminal_type']!=expected[r['root_cell_id']] for r in records):
            raise ValueError('candidate/load terminal type mismatch')
    return {int(i):loads[n] for n,i in enumerate(ids)}


def hydroperiod(values,required):
    a=np.asarray(values,np.float32);mask=boolean_mask(required,a.shape)
    if not np.all(np.isfinite(a[mask])) or np.any((a[mask]<0)|(a[mask]>1)):
        raise ValueError('required hydroperiod fraction is UNKNOWN or outside 0..1')
    return np.where(mask,a,np.nan)


def operator_scale(cell_km):
    cell=positive_scalar(cell_km,'operator cell size')
    spacing=cell*1000.
    if not math.isfinite(spacing) or spacing<=0:
        raise ValueError('operator cell size not representable in metres')
    scale=(9.80665/spacing)/spacing
    if not math.isfinite(scale) or scale<=0:
        raise ValueError('operator scale not representable')
    return scale


def validate_seiche_eigenpairs(operator,wet,periods,modes,eigenvalues=None,tolerance=2e-5):
    mask=boolean_mask(wet)
    p=finite_array(periods,'mode periods',True)
    if p.ndim!=1 or p.size==0 or len(modes)!=p.size or np.any(p<=0):
        raise ValueError('complete positive periods/modes required')
    derived=(2*math.pi/(p*3600.))**2
    values=derived if eigenvalues is None else finite_array(eigenvalues,'eigenvalues',True)
    if values.shape!=p.shape or np.any(values<=0) or not np.allclose(values,derived,rtol=1e-10,atol=0):
        raise ValueError('mode periods and eigenvalues disagree')
    if operator.shape!=(int(mask.sum()),int(mask.sum())):
        raise ValueError('operator/mask dimensions differ')
    vectors=[]
    norm=float(np.max(np.asarray(abs(operator).sum(axis=1)),initial=0.))
    if not math.isfinite(norm) or norm<=0:
        raise ValueError('invalid seiche operator norm')
    if np.max(np.abs(operator@np.ones(operator.shape[0])),initial=0)>norm*1e-12:
        raise ValueError('constant field is not a no-flux null mode')
    for value,mode in zip(values,modes):
        a=np.asarray(mode)
        if a.shape!=mask.shape or not np.all(np.isfinite(a[mask])) or not np.all(np.isnan(a[~mask])):
            raise ValueError('mode field mask/known values differ')
        vector=np.asarray(a[mask],np.float64);length=float(np.linalg.norm(vector))
        if length==0 or not math.isfinite(length):
            raise ValueError('zero or unrepresentable mode')
        residual=float(np.linalg.norm(operator@vector-value*vector))/(norm*length)
        if not math.isfinite(residual) or residual>tolerance:
            raise ValueError('seiche eigenpair residual exceeds tolerance')
        if abs(float(vector.mean()))>tolerance*float(np.max(np.abs(vector))):
            raise ValueError('nonconstant seiche mode is not orthogonal to constant mode')
        vectors.append(vector/length)
    gram=np.asarray(vectors)@np.asarray(vectors).T
    if not np.allclose(gram,np.eye(len(vectors)),rtol=0,atol=tolerance):
        raise ValueError('seiche modes are not mutually orthogonal')
    return {'status':'PASS','mode_count':len(vectors),'relative_operator_residual_tolerance':tolerance}


def finite_required_fields(fields, domain_key, categorical=None):
    """Fail closed; cannot relabel missing evidence as an absence of hazard."""
    if domain_key not in fields:
        raise ValueError('missing domain mask')
    mask=boolean_mask(fields[domain_key])
    for key,value in fields.items():
        a=np.asarray(value)
        if a.shape != mask.shape:
            raise ValueError(f'{key} is not on the domain grid')
        if a.dtype.kind in 'fiu' and (not np.all(np.isfinite(a[mask])) or np.any(a[mask]==-9999.)):
            raise ValueError(f'{key} contains UNKNOWN inside required domain')
    for key,codes in (categorical or {}).items():
        if key in fields and not np.all(np.isin(fields[key][mask], codes)):
            raise ValueError(f'{key} contains invalid categorical codes')
    return fields


def require_binary_support(value, domain, nodata=255):
    a=np.asarray(value); mask=boolean_mask(domain, a.shape[-2:])
    if not np.all(np.isin(a[...,mask], [0,1])) or not np.all(a[...,~mask]==nodata):
        raise ValueError('support raster does not match binary/domain/NODATA contract')
    return a


def require_hazard_stack(values,domain,process_count):
    a=np.asarray(values);mask=boolean_mask(domain)
    if a.shape!=(4*integer(process_count,'process count'),*mask.shape):
        raise ValueError('hazard stack must have three alternatives and one agreement band per process')
    for i in range(process_count):
        alternatives=require_binary_support(a[4*i:4*i+3],mask)
        agreement=a[4*i+3]
        if not np.all(agreement[~mask]==255) or not np.array_equal(agreement[mask],alternatives[:,mask].sum(axis=0)):
            raise ValueError('hazard agreement band or NODATA is inconsistent')
    return a


def uncast_broad_class(values,eligible):
    a=np.asarray(values);mask=boolean_mask(eligible,a.shape)
    if a.dtype.kind not in 'iu' or not np.all(np.isin(a[mask],[1,2,3,4])):
        raise ValueError('eligible broad class must be an exact valid integer before casting')
    return np.where(mask,a,0).astype(np.uint8)
