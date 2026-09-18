"""Versioned PB2002 calibration facts, not a universal law for other planets.

Areas: Bird (2003), doi:10.1029/2001GC000252, Table 1, steradians,
transcribed from the paper's table (including its five-decimal rounding).
The mirror's HTML drops minus signs on Euler poles: NO pole is taken from it.
The two signed poles and boundary steps below come from the original electronic
PB2002_poles.dat / PB2002_steps.dat files, distributed by fraxen/tectonicplates.

This is a present-day model with unresolved diffuse orogens and incomplete small
plates. Morra et al. (2013), doi:10.1016/j.epsl.2013.04.020, show that the size
hierarchy changes in time. Matching these areas is calibration, NOT validation
of the geometry, rheology, formation process or future plate evolution.
"""
from __future__ import annotations
import hashlib
import math
import numpy as np
from .geometry import GeometryError, _json

REFERENCE_ID = 'bird-2003-pb2002-table1-areas-v1'
AREA_ROWS = (
 ('AF',1.44065),('AM',.13066),('AN',1.43268),('AP',.02050),
 ('AR',.12082),('AS',.00793),('AT',.01418),('AU',1.13294),
 ('BH',.01295),('BR',.00481),('BS',.01715),('BU',.01270),
 ('CA',.07304),('CL',.03765),('CO',.07223),('CR',.00356),
 ('EA',.00411),('EU',1.19630),('FT',.00079),('GP',.00036),
 ('IN',.30637),('JF',.00632),('JZ',.00241),('KE',.01245),
 ('MA',.01037),('MN',.00020),('MO',.00284),('MS',.01030),
 ('NA',1.36559),('NB',.00956),('ND',.02394),('NH',.01585),
 ('NI',.00306),('NZ',.39669),('OK',.07482),('ON',.00802),
 ('PA',2.57685),('PM',.00674),('PS',.13409),('RI',.00249),
 ('SA',1.03045),('SB',.00762),('SC',.04190),('SL',.00178),
 ('SO',.47192),('SS',.00317),('SU',.21967),('SW',.00454),
 ('TI',.00870),('TO',.00625),('WL',.01116),('YA',.05425),
)
# Original file: north latitude, east longitude, CCW deg/Ma, Pacific fixed.
POLE_ROWS = (('AF',59.160,-73.174,.9270), ('AN',64.315,-83.984,.8695))
# 12 consecutive original steps: lon0,lat0,lon1,lat1,opening,right_lateral mm/a.
# Rounded source values are compared with an explicit transcription/rounding
# allowance, NOT the much tighter internal numerical regression tolerance.
STEP_ROWS = (
 (-.438,-54.852,-.039,-54.677,1.2,13.1),
 (-.039,-54.677,.443,-54.451,.9,13.1),
 (.443,-54.451,.965,-54.832,13.1,-1.1),
 (.965,-54.832,1.695,-54.399,-.4,13.2),
 (1.695,-54.399,2.360,-54.037,.4,13.2),
 (2.360,-54.037,3.025,-53.651,.2,13.2),
 (3.025,-53.651,3.369,-53.834,13.2,.5),
 (3.369,-53.834,3.956,-54.127,13.2,.8),
 (3.956,-54.127,4.415,-54.430,13.2,-1.2),
 (4.415,-54.430,4.827,-54.162,-.2,13.3),
 (4.827,-54.162,5.084,-54.309,13.3,-.5),
 (5.084,-54.309,5.495,-54.543,13.3,-.5),
)
SOURCES = (
 ('areas','https://doi.org/10.1029/2001GC000252','Table 1'),
 ('area_transcription','https://www.yumpu.com/en/document/view/19285879/an-updated-digital-model-of-plate-boundaries-peter-bird','paper page 6; areas only'),
 ('poles','https://github.com/fraxen/tectonicplates/blob/master/original/PB2002_poles.dat.txt','git blob 5aef5844405fed9858565e3076ba0288d2cf1116; rows AF/AN'),
 ('steps','https://github.com/fraxen/tectonicplates/blob/master/original/PB2002_steps.dat.txt','git blob b48506d79c614b241ce26cf949492ee7c6676d60; steps 1-12'),
 ('limitations','https://arxiv.org/abs/1011.2752','time-dependent hierarchy; not universal present-day fit'),
 ('alternative_statistics','https://arxiv.org/abs/cond-mat/0202320','finite-area constrained power law; an alternative statistical interpretation'),
)


def plate_reference_record():
    """Detached factual reference record; not user-tunable acceptance evidence."""
    body = {'schema':REFERENCE_ID, 'area_unit':'steradian', 'areas':dict(AREA_ROWS),
            'sources':SOURCES, 'pole_reference_frame':'Pacific-fixed',
            'signed_poles':POLE_ROWS,'boundary_steps':STEP_ROWS,
            'boundary_motion_sample':'12-step AF-AN excerpt; complete Cocos outline is separately identified',
            'limitations':['single present-day reconstruction','rounded values',
                          'diffuse orogens unresolved','small-plate incompleteness']}
    body['reference_sha256']=hashlib.sha256(_json(body)).hexdigest()
    return body


def reference_area_fractions(count: int):
    """Largest-N spectrum, explicitly conditional, never N-independent truth.

    For N<52 omitted smaller areas are redistributed proportionally by a declared
    normalisation. For N=52 only tabulation rounding is normalised. Neither rule
    predicts missing plate locations or recreates Earth geography.
    """
    if type(count) is not int or not 2 <= count <= 52:
        raise GeometryError('PB2002 largest-N prior supports an explicit count in 2..52')
    rows=sorted(AREA_ROWS,key=lambda r:(-r[1],r[0]))[:count]
    total=math.fsum(v for _,v in rows)
    values=np.array([v/total for _,v in rows],dtype='f8')
    return np.frombuffer(values.tobytes(),dtype='f8')


def reference_motion_sample(radius_m: float = 6_371_000.):
    """Recompute the sourced short ridge/transform sample from signed Euler poles.

    Vectors use forward seconds; a Julian year (365.25 d) is an explicit unit
    conversion here, not a fitted rate. Opening = (v_right-v_left).right_normal.
    Bird right-lateral slip uses (v_left-v_right).tangent, hence opposite sign.
    Radius is supplied for the numerical reconstruction, not an Earth-size prior.
    """
    if isinstance(radius_m,(bool,str)) or not math.isfinite(radius_m) or radius_m <= 0:
        raise GeometryError('positive finite reference radius required')
    def xyz(lon,lat):
        lon,lat=np.deg2rad([lon,lat]);return np.array([math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)])
    poles={name:xyz(lon,lat)*math.radians(rate)/(1e6*365.25*86400) for name,lat,lon,rate in POLE_ROWS}
    scale=365.25*86400*1000
    answers=[]
    for lon0,lat0,lon1,lat1,op,rl in STEP_ROWS:
        a,b=xyz(lon0,lat0),xyz(lon1,lat1)
        normal=np.cross(a+b,b-a);normal/=np.linalg.norm(normal)
        mid=a+b;mid/=np.linalg.norm(mid)
        tangent=np.cross(normal,mid);right=-normal
        relative=np.cross(poles['AN']-poles['AF'],radius_m*mid)
        answers.append((float(relative@right)*scale,-float(relative@tangent)*scale,op,rl))
    return np.array(answers)


def _spherical_ring_metrics(directions):
    """Measure one simple open-hemisphere outline; report its supplied orientation.

    Input can omit or repeat its closing vertex. Edges are minor great circles.
    The area uses signed spherical triangles, NOT a planar map area. Reflex
    turning is reported at the supplied physical resolution; it is not turned
    into a fitted realism score. Adding collinear arc vertices changes neither
    area/perimeter nor nonzero turning, apart from explicit roundoff.
    """
    from ._validation import read_array
    points=read_array(directions,'outline',ndim=2)
    if points.shape[1:]!=(3,) or len(points)<3:raise GeometryError('at least three spherical outline vertices required')
    if np.array_equal(points[0],points[-1]):points=points[:-1]
    scale=np.max(np.abs(points),axis=1)
    if np.any(scale==0):raise GeometryError('zero outline direction')
    points=points/scale[:,None]
    points=points/np.linalg.norm(points,axis=1)[:,None]
    centre=points.sum(axis=0); norm=np.linalg.norm(centre)
    if norm==0:raise GeometryError('outline needs a well-conditioned hemisphere')
    centre/=norm
    if np.any(points@centre<=1e-8):raise GeometryError('outline is outside supported hemisphere')
    a=points;b=np.roll(points,-1,axis=0)
    cross=np.cross(a+b,b-a);lengths=np.arctan2(np.linalg.norm(cross,axis=1)/2,np.sum(a*b,axis=1))
    if np.any(lengths<=1e-12) or np.any(lengths>=math.pi-1e-12):raise GeometryError('degenerate or antipodal outline edge')
    normal=cross/np.linalg.norm(cross,axis=1)[:,None]
    terms=2*np.arctan2(np.sum(centre*np.cross(a,b),axis=1),1+a@centre+b@centre+np.sum(a*b,axis=1))
    area=math.fsum(terms)
    if not 0<abs(area)<2*math.pi:raise GeometryError('nondegenerate minor spherical outline required')
    orientation = 1 if area>0 else -1
    area=abs(area)
    # Reverse only the sign convention of this measurement. Source coordinates
    # remain unchanged, including the clockwise winding of the curator's GeoJSON.
    from shapely.geometry import Polygon
    east=np.cross([0.,0.,1.],centre)
    if np.linalg.norm(east)<1e-8:east=np.cross([1.,0.,0.],centre)
    east/=np.linalg.norm(east);north=np.cross(centre,east)
    projected=points@np.array([east,north]).T/(points@centre)[:,None]
    if not Polygon(projected).is_valid:raise GeometryError('invalid/self-crossing outline')
    incoming=np.cross(np.roll(normal,1,axis=0),a);outgoing=np.cross(normal,a)
    turning=np.arctan2(np.sum(a*np.cross(incoming,outgoing),axis=1),np.sum(incoming*outgoing,axis=1))
    turning*=orientation
    perimeter=math.fsum(lengths)
    return {'area_steradians':area,'perimeter_radians':perimeter,
            'compactness':area*(4*math.pi-area)/perimeter**2,'orientation':orientation,
            'reflex_turning_radians':math.fsum(max(0.,-float(t)) for t in turning if abs(t)>1e-12),
            'absolute_turning_radians':math.fsum(abs(float(t)) for t in turning if abs(t)>1e-12),
            'signed_turning_radians':math.fsum(turning),
            'max_segment_radians':float(lengths.max()),'segments':len(lengths)}


def lonlat_directions(coordinates):
    """Explicit geocentric longitude/latitude degrees to unit Cartesian vectors."""
    from ._validation import read_array
    xy=read_array(coordinates,'longitude/latitude degrees',ndim=2)
    if xy.shape[1:]!=(2,) or np.any(abs(xy[:,1])>90):raise GeometryError('expected longitude/latitude degrees with valid latitude')
    angles=np.deg2rad(xy);lon,lat=angles.T
    points=np.column_stack((np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)))
    return np.frombuffer(points.tobytes(),dtype='f8').reshape(-1,3)

# Complete held-out outline: CO feature from curator GeoJSON blob
# 879951b5d17c0e11926025223378174fcb9f41f6. No thinning/smoothing.
COCOS_COORDINATES = (
    (-86.648, 10.235),
    (-86.4487, 9.9383),
    (-86.2036, 9.68364),
    (-85.9105, 9.42337),
    (-85.6124, 9.20327),
    (-85.3805, 9.08908),
    (-85.0438, 8.93723),
    (-84.6858, 8.77169),
    (-84.4187, 8.63674),
    (-84.1577, 8.47377),
    (-84.0072, 8.30028),
    (-83.8377, 8.18189),
    (-83.6054, 8.04445),
    (-83.3599, 7.92759),
    (-83.2331, 7.84854),
    (-83.0742, 7.59169),
    (-82.8748, 7.36639),
    (-82.8749, 7.11804),
    (-82.875, 6.56231),
    (-82.875, 5.83296),
    (-82.875, 5.05417),
    (-82.875, 4.56303),
    (-82.875, 4.07188),
    (-82.875, 3.5949),
    (-82.8064, 3.11792),
    (-83.3779, 3.16485),
    (-83.9225, 3.13869),
    (-84.4671, 3.11226),
    (-84.5667, 2.53424),
    (-84.5713, 2.06618),
    (-84.5759, 1.59812),
    (-85.3494, 1.64441),
    (-85.3861, 0.831804),
    (-86.2656, 0.880462),
    (-87.145, 0.928909),
    (-88.0245, 0.977144),
    (-88.9041, 1.02514),
    (-89.7836, 1.0729),
    (-90.6632, 1.12041),
    (-90.6973, 1.73615),
    (-91.5608, 1.81659),
    (-91.5376, 2.01117),
    (-92.1183, 1.99009),
    (-92.0902, 2.19975),
    (-92.2451, 2.22695),
    (-92.9279, 2.29988),
    (-93.6107, 2.37248),
    (-94.4044, 2.43994),
    (-95.1982, 2.50694),
    (-95.2241, 2.22175),
    (-96.1202, 2.23785),
    (-96.175, 1.87283),
    (-96.88, 1.88568),
    (-97.5851, 1.89824),
    (-97.5512, 2.08841),
    (-97.8463, 2.07656),
    (-98.3674, 2.14463),
    (-98.8886, 2.21253),
    (-98.9175, 2.11218),
    (-99.657, 2.19007),
    (-99.7389, 2.26882),
    (-99.8108, 2.2726),
    (-99.9129, 2.27227),
    (-100.047, 2.29966),
    (-100.066, 2.20704),
    (-100.394, 2.2065),
    (-100.644, 2.2044),
    (-101.067, 2.21046),
    (-101.196, 2.1989),
    (-101.203, 2.24142),
    (-101.512, 2.23226),
    (-101.49, 2.60499),
    (-101.697, 2.63971),
    (-101.878, 2.64213),
    (-102.068, 2.63532),
    (-102.109, 2.78564),
    (-102.096, 2.79833),
    (-102.118, 2.89294),
    (-102.145, 2.88876),
    (-102.193, 3.07219),
    (-102.219, 3.23869),
    (-102.199, 3.45816),
    (-102.259, 3.75071),
    (-102.184, 3.77753),
    (-102.32, 4.65326),
    (-102.457, 5.52897),
    (-102.558, 6.35535),
    (-102.659, 7.18172),
    (-102.81, 7.79085),
    (-102.961, 8.39993),
    (-103.595, 8.37048),
    (-104.229, 8.34001),
    (-104.258, 8.45574),
    (-104.296, 9.17474),
    (-104.296, 10.0171),
    (-103.598, 10.1232),
    (-103.628, 10.2746),
    (-103.739, 10.9366),
    (-103.807, 11.4045),
    (-103.875, 11.8723),
    (-103.772, 11.8904),
    (-103.927, 12.5868),
    (-104.181, 13.3284),
    (-104.437, 14.0698),
    (-104.563, 14.6722),
    (-104.69, 15.2745),
    (-105.32, 15.1076),
    (-105.357, 15.5576),
    (-105.398, 16.2605),
    (-105.367, 17.0308),
    (-105.399, 17.7679),
    (-105.586, 17.8808),
    (-105.51, 18.1403),
    (-105.442, 18.3552),
    (-105.352, 18.5511),
    (-105.247, 18.7619),
    (-105.043, 18.6216),
    (-104.725, 18.3684),
    (-104.406, 18.209),
    (-104.191, 18.1383),
    (-103.792, 17.92),
    (-103.2, 17.6155),
    (-102.432, 17.2799),
    (-101.703, 17.0256),
    (-100.867, 16.6363),
    (-100.336, 16.4424),
    (-99.806, 16.298),
    (-99.4347, 16.134),
    (-99.0281, 15.9191),
    (-98.5878, 15.7715),
    (-98.1657, 15.6399),
    (-97.6914, 15.508),
    (-97.2174, 15.3584),
    (-96.727, 15.3601),
    (-96.219, 15.3609),
    (-95.7986, 15.2765),
    (-95.4663, 15.0902),
    (-95.117, 14.8866),
    (-94.8729, 14.6998),
    (-94.5422, 14.4786),
    (-94.0552, 14.2221),
    (-93.6558, 14.0161),
    (-93.3094, 13.7932),
    (-92.9619, 13.7221),
    (-92.5992, 13.498),
    (-92.2724, 13.2233),
    (-92.0632, 13.2712),
    (-91.7186, 13.0801),
    (-91.3079, 12.8322),
    (-90.898, 12.5837),
    (-90.2927, 12.5426),
    (-89.619, 12.2948),
    (-88.9197, 11.9992),
    (-88.319, 11.6968),
    (-87.8901, 11.3967),
    (-87.4621, 11.0959),
    (-86.9749, 10.5473),
    (-86.648, 10.235),
)


def outline_reference_record():
    """One complete held-out plate outline, not a full PB2002 shape distribution."""
    record = {'schema':'pb2002-cocos-complete-outline-v1','plate_code':'CO',
        'source':'https://github.com/fraxen/tectonicplates/blob/master/GeoJSON/PB2002_plates.json',
        'source_blob':'879951b5d17c0e11926025223378174fcb9f41f6',
        'selection':'complete CO feature, line 52, closing point retained',
        'attribution':'Peter Bird (2003); curation Hugo Ahlenius / Nordpil; GeoJSON preparation csterling',
        'licence':'Open Data Commons Attribution Licence 1.0',
        'coordinate_units':'longitude/latitude degrees','coordinates':COCOS_COORDINATES,
        'role':'held-out numerical/morphology challenge; not used to fit generator',
        'limitation':'one small oceanic plate cannot validate the complete global shape distribution'}
    record['record_sha256']=hashlib.sha256(_json(record)).hexdigest()
    return record


def spherical_ring_metrics(directions, *, limits=None, budget=None, cancel=None):
    """Budgeted outline measurements; native GEOS workspace remains an allowance."""
    from .geometry import _limits, _check_cancel
    from ._validation import input_shape
    from .resources import select_budget
    _check_cancel(cancel);limit=_limits(limits)
    shape=input_shape(directions,'outline')
    if len(shape)!=2 or shape[1]!=3 or not 3<=shape[0]<=limit.max_vertices:
        raise GeometryError('outline shape or vertex limit exceeded')
    with select_budget(budget).reserve(1024*shape[0]+16384,category='plate-outline-metrics'):
        result=_spherical_ring_metrics(directions)
        _check_cancel(cancel)
        return result
