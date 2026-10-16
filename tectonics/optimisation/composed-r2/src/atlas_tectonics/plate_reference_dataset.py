"""3C-R1: strict, offline PB2002 input and scale-declared measurements.

This module reads source evidence; it never generates, repairs or calibrates a
plate layout. Present-day PB2002 is ONE evidence family. Its area spectrum has
already been used for calibration in Atlas. New spatially withheld observations
are not independent of PB2002's other observations or of its reconstruction.

Raw records retain the author's orientation, rounding and provenance. Missing
files, wrong Git object identities, malformed records and unresolved geometry are
errors, not permission to manufacture a complete benchmark from a small excerpt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import math
import re
from typing import Mapping

import numpy as np

from ._validation import TectonicsError, frozen, read_array, scalar, input_shape
from .geometry import _check_cancel
from .resources import select_budget


class ReferenceDataError(TectonicsError):
    """Missing, altered, unsupported or inconsistent scientific reference data."""


# Commit and object identities observed through GitHub, not guessed from filenames.
PB2002_COMMIT = '339b0c56563c118307b1f4542703047f5f698fae'
PB2002_FILES = (
    ('original/PB2002_plates.dig.txt', '90f1d48ecc58201d54d9a02b92c46c7846ee5af9', 329608),
    ('original/PB2002_boundaries.dig.txt', '94924e66808da7dccd1fcdcc0b86682231ea6f25', 181502),
    ('original/PB2002_orogens.dig.txt', '1c261ecc04c2c6e3f5c604f6b8d7695637b15cfb', 31662),
    ('original/PB2002_poles.dat.txt', '5aef5844405fed9858565e3076ba0288d2cf1116', 2802),
    ('original/PB2002_steps.dat.txt', 'b48506d79c614b241ce26cf949492ee7c6676d60', 564443),
    ('original/PB2002_steps_desc.txt', 'bd98759bf71a5ccb03f8093d98ea65801c445d7c', 1528),
    ('original/README.md', '0b16b27e087586e8d40137e6bb29fb6031c9470a', 8019),
    ('LICENSE.md', '288735dda9191adf22f0de1c980b7b72e8b9c9c9', 186),
)
PB2002_COUNTS = (52, 229, 13, 52, 5819)
EARTH_REFERENCE_RADIUS_M = 6_371_000.0
SOURCE_POSITION_BOUND_M = 60.0
STEP_POSITION_HALF_UNIT_DEG = 0.0005
POLE_POSITION_HALF_UNIT_DEG = 0.0005
POLE_RATE_HALF_UNIT_DEG_MA = 0.00005
BOUNDARY_CLASSES = ('CCB', 'CTF', 'CRB', 'OSR', 'OTF', 'OCB', 'SUB')
_END = '*** end of line segment ***'
_COORD = re.compile(r'^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*$')
_BOUNDARY = re.compile(r'^[A-Z]{2}[-/\\][A-Z]{2}$')


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _git_blob(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def source_manifest() -> dict:
    """Detached acquisition specification, including origin and legal attribution."""
    return dict(schema='atlas.pb2002-source-pins.v1', commit=PB2002_COMMIT,
                family='PB2002-Bird-2003', doi='10.1029/2001GC000252',
                curator='Hugo Ahlenius / Nordpil / fraxen', author='Peter Bird',
                licence='Open Data Commons Attribution 1.0',
                licence_url='https://opendatacommons.org/licenses/by/1.0/',
                files=[dict(path=p, git_blob=g, bytes=n,
                    url=f'https://raw.githubusercontent.com/fraxen/tectonicplates/{PB2002_COMMIT}/{p}')
                    for p, g, n in PB2002_FILES],
                warnings=['single present-day model, not a time series',
                          'orogens are overlapping deformation overlays, not extra plates',
                          'coordinate precision is not geological accuracy',
                          'derived GIS copies are not independent evidence'])


def verify_source_bytes(name: str, raw: bytes) -> str:
    """Require the pinned original bytes; return a stronger local payload identity.

    The Git SHA-1 matches a published object, not a signature. SHA-256 then binds
    the actual bytes to downstream records. No newline or encoding repair occurs.
    """
    pins = {p: (g, n) for p, g, n in PB2002_FILES}
    if name not in pins or type(raw) is not bytes:
        raise ReferenceDataError('unrecognised source or non-byte payload')
    expected, length = pins[name]
    if len(raw) != length or _git_blob(raw) != expected:
        raise ReferenceDataError(f'{name}: pinned source identity mismatch')
    return hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes | str) -> str:
    if isinstance(raw, str):
        text = raw
    elif type(raw) is bytes:
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ReferenceDataError('reference must be UTF-8/ASCII text') from exc
    else:
        raise ReferenceDataError('text or original bytes required')
    if '\0' in text or len(text) > 4 * 1024**2:
        raise ReferenceDataError('NUL or over-limit reference text')
    return text


def lonlat_vectors(coordinates) -> np.ndarray:
    """The source sphere's east-longitude/north-latitude degrees, not map x/y."""
    xy = read_array(coordinates, 'longitude/latitude', ndim=2)
    if xy.shape[1:] != (2,) or np.any(abs(xy[:, 1]) > 90):
        raise ReferenceDataError('two angular coordinates and latitude in [-90,90] required')
    # Reduce longitude for trigonometry only; preserve the original record unchanged.
    angles = np.deg2rad(np.column_stack(((xy[:, 0] + 180) % 360 - 180, xy[:, 1])))
    lon, lat = angles.T
    return frozen(np.column_stack((np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat))))


@dataclass(frozen=True, slots=True, init=False)
class ReferenceCurve:
    """An immutable source curve. Array descriptors are private to each caller."""
    name: str
    kind: str
    source_title: str
    record_number: int
    _points: bytes = field(repr=False)
    count: int
    repeated_vertex_indices: tuple[int, ...] = field(repr=False)
    explicitly_closed: bool

    def __init__(self, name, kind, title, number, coordinates, *, preserve_source_geometry=False):
        if type(preserve_source_geometry) is not bool:
            raise ReferenceDataError('source-geometry preservation must be an explicit boolean')
        if kind not in ('plate', 'boundary', 'orogen') or not isinstance(name, str) or not name:
            raise ReferenceDataError('named source curve and known kind required')
        shape = input_shape(coordinates, 'source coordinates')
        if len(shape)!=2 or shape[1]!=2 or not 2<=shape[0]<=20000:
            raise ReferenceDataError('bounded N by 2 source coordinates required')
        points = read_array(coordinates, 'source coordinates', ndim=2)
        if points.shape[1:] != (2,) or len(points) < (4 if kind != 'boundary' else 2):
            raise ReferenceDataError('insufficient source coordinates')
        if np.any(abs(points[:, 1]) > 90) or len(points) > 20000:
            raise ReferenceDataError('invalid latitude or excessive curve length')
        if type(number) is not int or number < 1 or not isinstance(title, str) or len(title) > 2048:
            raise ReferenceDataError('invalid source locator')
        vectors = lonlat_vectors(points)
        closure = np.linalg.norm(vectors[0] - vectors[-1])
        closed = bool(closure <= 2e-14)
        if kind != 'boundary' and not closed and not preserve_source_geometry:
            raise ReferenceDataError(f'{name}: polygon not explicitly closed')
        chord = np.linalg.norm(np.diff(vectors, axis=0), axis=1)
        # PB2002 concatenates source segments with their shared endpoint repeated.
        # Preserve every raw coordinate; ONLY exactly equal adjacent coordinate
        # pairs may be excluded from a derived measurement view. Nearby unequal
        # points remain subject to the original numerical refusal thresholds.
        repeated = np.all(points[1:] == points[:-1], axis=1)
        invalid_short = (chord < 1e-14) & ~(repeated & preserve_source_geometry)
        if np.any(invalid_short) or np.any(chord > 2 - 1e-14):
            raise ReferenceDataError(f'{name}: degenerate or antipodal source edge')
        for attr, value in [('name', name), ('kind', kind), ('source_title', title),
                            ('record_number', number), ('_points', points.tobytes()), ('count', len(points)),
                            ('repeated_vertex_indices', tuple(int(i)+1 for i in np.flatnonzero(repeated))),
                            ('explicitly_closed', closed)]:
            object.__setattr__(self, attr, value)

    @property
    def coordinates(self):
        return np.frombuffer(self._points, dtype='f8').reshape(self.count, 2)

    def measurement_coordinates(self):
        """Return an immutable numerical view, never a replacement source record.

        Exact repetitions carry no arc length or area. Their original indices are
        retained above for audit. An open polygon is NOT implicitly closed, snapped
        or extrapolated; callers must report its unresolved source geometry.
        """
        if self.kind != 'boundary' and not self.explicitly_closed:
            raise ReferenceDataError(f'{self.name}: open source polygon; no closure inferred')
        if not self.repeated_vertex_indices:
            return self.coordinates
        keep = np.ones(self.count, dtype=bool)
        keep[list(self.repeated_vertex_indices)] = False
        return frozen(self.coordinates[keep])

    @property
    def source_id(self):
        return f'{self.kind}:{self.record_number}:{self.name}'

    @property
    def owners(self):
        if self.kind != 'boundary':
            raise ReferenceDataError('only boundary curves carry two owners')
        return self.name[:2], self.name[3:]

    @property
    def subducting_side(self):
        return {'/': 'right', '\\': 'left', '-': None}.get(self.name[2]) if self.kind == 'boundary' else None


def parse_dig(raw: bytes | str, kind: str, *, preserve_source_geometry=False) -> tuple[ReferenceCurve, ...]:
    """Parse complete author-format segments, preserving duplicate boundary titles.

    Boundaries with the same pair can have distinct provenance/polarity. They
    remain separate records. Unterminated or malformed records never become a
    shorter, apparently successful dataset. The strict default is unchanged.
    The pinned-source loader explicitly preserves duplicate endpoints and open
    polygons as evidence; preservation never grants geometric validity.
    """
    if type(preserve_source_geometry) is not bool:
        raise ReferenceDataError('source-geometry preservation must be an explicit boolean')
    if kind not in ('plate', 'boundary', 'orogen'):
        raise ReferenceDataError('unknown DIG record kind')
    records, title, points = [], None, []
    for line_number, line in enumerate(_decode(raw).splitlines(), 1):
        text = line.strip()
        if not text:
            continue
        if text == _END:
            if title is None:
                raise ReferenceDataError(f'unexpected segment end at line {line_number}')
            name = title[:5] if kind == 'boundary' else title[:2] if kind == 'plate' else title
            if (kind == 'boundary' and not _BOUNDARY.fullmatch(name)) or (kind == 'plate' and not re.fullmatch('[A-Z]{2}', name)):
                raise ReferenceDataError(f'invalid source identifier at line {line_number}')
            records.append(ReferenceCurve(name, kind, title, len(records)+1, points,
                                          preserve_source_geometry=preserve_source_geometry))
            if len(records) > 1024:
                raise ReferenceDataError('too many DIG segments')
            title, points = None, []
        elif title is None:
            if _COORD.fullmatch(text):
                raise ReferenceDataError('coordinate without a source title')
            title = text
        else:
            match = _COORD.fullmatch(text)
            if match is None:
                raise ReferenceDataError(f'invalid coordinate at line {line_number}')
            points.append((float(match[1]), float(match[2])))
            if len(points) > 20000:
                raise ReferenceDataError('too many vertices')
    if title is not None:
        raise ReferenceDataError('unterminated DIG segment')
    if not records:
        raise ReferenceDataError('empty DIG file')
    if kind != 'boundary' and len({r.name for r in records}) != len(records):
        raise ReferenceDataError('duplicate polygon identifier')
    return tuple(records)


@dataclass(frozen=True, slots=True)
class EulerPole:
    plate_id: str
    latitude_deg: float
    longitude_deg: float
    rate_deg_ma: float
    source_note: str = ''

    def __post_init__(self):
        if re.fullmatch('[A-Z]{2}', self.plate_id) is None:
            raise ReferenceDataError('invalid pole plate')
        for key in ('latitude_deg', 'longitude_deg', 'rate_deg_ma'):
            object.__setattr__(self, key, scalar(getattr(self, key), key))
        if abs(self.latitude_deg) > 90:
            raise ReferenceDataError('invalid pole latitude')

    @property
    def vector_rad_ma(self):
        return lonlat_vectors([[self.longitude_deg, self.latitude_deg]])[0] * math.radians(self.rate_deg_ma)


def parse_poles(raw: bytes | str) -> tuple[EulerPole, ...]:
    values = []
    for line in _decode(raw).splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=4)
        if len(parts) < 4:
            raise ReferenceDataError('incomplete pole row')
        try:
            values.append(EulerPole(parts[0], *map(float, parts[1:4]), parts[4] if len(parts) > 4 else ''))
        except (ValueError, TypeError) as exc:
            raise ReferenceDataError('invalid signed pole row') from exc
        if len(values) > 512:
            raise ReferenceDataError('too many poles')
    if not values or len({v.plate_id for v in values}) != len(values):
        raise ReferenceDataError('empty or duplicate pole catalogue')
    return tuple(values)


@dataclass(frozen=True, slots=True)
class BoundaryStep:
    number: int
    boundary: str
    continuous: bool
    start: tuple[float, float]
    end: tuple[float, float]
    length_km: float
    azimuth_deg: float
    speed_mm_a: float
    velocity_azimuth_deg: float
    opening_mm_a: float
    right_lateral_mm_a: float
    elevation_m: float
    seafloor_age_ma: int | None
    kind: str
    in_orogen: bool


def parse_steps(raw: bytes | str) -> tuple[BoundaryStep, ...]:
    """Author Table-2 fixed columns; signs, continuity and unknown ages survive.

    Age >180 Ma is explicitly unknown per the source, not an old measured age.
    Source SUB combines convergence with geological evidence. It must not be
    reclassified solely from the sign of the computed velocity.
    """
    result = []
    for line in _decode(raw).splitlines():
        if not line.strip():
            continue
        row = line.ljust(96)
        if len(line.rstrip()) > 96 or row[5] not in (' ', ':') or row[91] not in (' ', ':') or row[95] not in (' ', '*'):
            raise ReferenceDataError('invalid step width or continuity/orogen marker')
        name, kind = row[6:11], row[92:95]
        if not _BOUNDARY.fullmatch(name) or kind not in BOUNDARY_CLASSES:
            raise ReferenceDataError('invalid step boundary or class')
        try:
            number = int(row[:4]); age = int(row[87:90])
            spans = ((12,20),(21,28),(29,37),(38,45),(46,51),(52,55),
                     (56,61),(62,65),(66,72),(73,79),(80,86))
            x = [float(row[a:b]) for a,b in spans]
        except ValueError as exc:
            raise ReferenceDataError('missing or malformed numeric step field') from exc
        if (number != len(result)+1 or not all(map(math.isfinite, x)) or x[4] <= 0 or x[6] < 0 or age < 0
                or not 0 <= x[5] <= 360 or not 0 <= x[7] <= 360):
            raise ReferenceDataError('invalid step sequence or numeric range')
        if max(abs(x[1]),abs(x[3])) > 90:
            raise ReferenceDataError('invalid step latitude')
        continuous = row[5] == ':'
        if continuous and (not result or result[-1].boundary != name or result[-1].end != (x[0],x[1])):
            raise ReferenceDataError('step continuity disagrees with preceding record')
        if row[91] == ':' and (not continuous or result[-1].kind != kind):
            raise ReferenceDataError('class-continuity marker disagrees')
        result.append(BoundaryStep(number,name,continuous,tuple(x[:2]),tuple(x[2:4]),
                     *x[4:],None if age>180 else age,kind,row[95]=='*'))
        if len(result) > 10000:
            raise ReferenceDataError('too many boundary steps')
    if not result:
        raise ReferenceDataError('empty step table')
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PB2002Dataset:
    plates: tuple[ReferenceCurve, ...]
    boundaries: tuple[ReferenceCurve, ...]
    orogens: tuple[ReferenceCurve, ...]
    poles: tuple[EulerPole, ...]
    steps: tuple[BoundaryStep, ...]
    raw_sha256: tuple[tuple[str, str], ...]
    dataset_id: str

    @property
    def numerical_bytes(self):
        return sum(len(c._points) for c in self.plates+self.boundaries+self.orogens)

    def provenance(self):
        record = source_manifest()
        record.update(dataset_id=self.dataset_id, raw_sha256=dict(self.raw_sha256),
                      counts=dict(zip(('plates','boundaries','orogens','poles','steps'),
                                  map(len,(self.plates,self.boundaries,self.orogens,self.poles,self.steps)))))
        return record


def load_pb2002(directory, *, budget=None, cancel=None) -> PB2002Dataset:
    """Validate all eight sources before parsing; no network or partial-data mode.

    The result is caller-owned. The work reservation is an allocation estimate,
    not a process-RSS promise or an automatic lifetime reservation on returned data.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ReferenceDataError('complete PB2002 source directory is missing')
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ReferenceDataError('linked reference directories are refused')
    policy = select_budget(budget)
    with policy.reserve(16*sum(n for _,_,n in PB2002_FILES)+4*1024**2, category='plate-reference-input'):
        payloads, identities = {}, []
        for name, _, size in PB2002_FILES:
            _check_cancel(cancel)
            path = root/name
            if not path.is_file() or any(p.is_symlink() for p in (path,*path.parents)):
                raise ReferenceDataError(f'missing or linked pinned file: {name}')
            with path.open('rb') as stream:
                raw = stream.read(size+1)
            identities.append((name,verify_source_bytes(name,raw)))
            payloads[name] = raw
        # All eight byte identities passed above. Preserve real-source artefacts
        # without admitting unverified files or weakening the strict geometry API.
        plates = parse_dig(payloads['original/PB2002_plates.dig.txt'],'plate',
                           preserve_source_geometry=True)
        boundaries = parse_dig(payloads['original/PB2002_boundaries.dig.txt'],'boundary')
        orogens = parse_dig(payloads['original/PB2002_orogens.dig.txt'],'orogen',
                            preserve_source_geometry=True)
        poles = parse_poles(payloads['original/PB2002_poles.dat.txt'])
        steps = parse_steps(payloads['original/PB2002_steps.dat.txt'])
        counts = tuple(map(len,(plates,boundaries,orogens,poles,steps)))
        if counts != PB2002_COUNTS or sum(c.count for c in boundaries) != 6048:
            raise ReferenceDataError(f'incomplete PB2002 inventory: {counts}')
        known = {p.name for p in plates}
        if known != {p.plate_id for p in poles} or any(not set(c.owners)<=known for c in boundaries):
            raise ReferenceDataError('plate, boundary and pole inventories disagree')
        if sum(c.count-1 for c in boundaries) != len(steps):
            raise ReferenceDataError('step and boundary edge counts disagree')
        identity = hashlib.sha256(_json(dict(schema='atlas.pb2002-complete.v1',files=identities))).hexdigest()
        _check_cancel(cancel)
        return PB2002Dataset(plates,boundaries,orogens,poles,steps,tuple(identities),identity)


def _unit_vectors(values):
    a = read_array(values,'spherical directions',ndim=2)
    if a.shape[1:] != (3,) or len(a)<2:
        raise ReferenceDataError('two or more Cartesian direction triples required')
    scale = np.max(abs(a),axis=1)
    if np.any(scale==0):
        raise ReferenceDataError('zero spherical direction')
    a=a/scale[:,None];a/=np.linalg.norm(a,axis=1)[:,None]
    return a


def _angles(a,b):
    return np.arctan2(np.linalg.norm(np.cross(a+b,b-a),axis=1)/2,np.sum(a*b,axis=1))


def spherical_ring_measures(directions, *, budget=None, cancel=None):
    """Oriented simple closed ring, with two independent spherical area formulae.

    Counterclockwise means the interior is on the left as viewed from outside.
    Reversing a ring denotes its spherical complement; it is NOT silently flipped
    to the smaller region. Self-intersection validity is a separate prerequisite.
    No planar map, centroid-inside assumption or open-hemisphere restriction is
    used by the area formula. Measures describe this supplied boundary resolution.
    """
    _check_cancel(cancel)
    shape=np.shape(directions)
    if len(shape)!=2 or shape[1]!=3:
        raise ReferenceDataError('expected N by 3 directions')
    with select_budget(budget).reserve(768*shape[0]+16384,category='plate-reference-metrics'):
        p=_unit_vectors(directions)
        if np.linalg.norm(p[0]-p[-1]) < 2e-14:
            p=p[:-1]
        if len(p)<3:
            raise ReferenceDataError('closed polygon needs three distinct vertices')
        a=p;b=np.roll(p,-1,axis=0);angles=_angles(a,b)
        if np.any(angles<=1e-14) or np.any(angles>=math.pi-1e-12):
            raise ReferenceDataError('degenerate or antipodal polygon edge')
        normals=np.cross(a+b,b-a);normals/=np.linalg.norm(normals,axis=1)[:,None]
        incoming=np.cross(np.roll(normals,1,axis=0),a)
        outgoing=np.cross(normals,a)
        turns=np.arctan2(np.sum(a*np.cross(incoming,outgoing),axis=1),np.sum(incoming*outgoing,axis=1))
        area=(2*math.pi-math.fsum(turns))%(4*math.pi)
        # A fan anchor need not be in the ring; modulo 4*pi accounts for wrapping.
        # Pick the most conditioned of a fixed set, never perturb the source ring.
        anchors=np.array([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1],
                          [1,1,1],[-1,1,1],[1,-1,1],[1,1,-1]],dtype=float)
        anchors/=np.linalg.norm(anchors,axis=1)[:,None]
        cross=np.cross(a,b);dot=np.sum(a*b,axis=1)
        best=None
        for c in anchors:
            den=1+a@c+b@c+dot;det=cross@c
            quality=float(np.min(np.hypot(den,det)))
            if best is None or quality>best[0]:best=(quality,den,det)
        if best[0]<1e-12:
            raise ReferenceDataError('spherical area fan is numerically unresolved')
        independent=math.fsum(2*np.arctan2(best[2],best[1]))%(4*math.pi)
        perimeter=math.fsum(angles)
        if not 0<area<4*math.pi or not all(map(math.isfinite,(area,independent,perimeter))):
            raise ReferenceDataError('invalid area or perimeter')
        _check_cancel(cancel)
        return dict(area_steradians=area,independent_area_steradians=independent,
                    area_formula_disagreement_sr=abs(area-independent),perimeter_radians=perimeter,
                    compactness=area*(4*math.pi-area)/perimeter**2,
                    absolute_turning_radians=math.fsum(abs(v) for v in turns),
                    reflex_turning_radians=math.fsum(max(-float(v),0) for v in turns),
                    maximum_segment_radians=float(angles.max()),segments=len(p))


def _sample_ring_at_scale(directions, spacing_rad, *, phase=0., max_samples=100000, budget=None, cancel=None):
    """Uniform arc-length samples for a declared observation scale, not simplification.

    Source vertices are not themselves the sampling unit. Adding collinear points
    therefore cannot improve the metric. ``phase`` exposes sensitivity to sample
    origin; changing it does not move the underlying curve.
    """
    spacing=scalar(spacing_rad,'sampling spacing',positive=True)
    phase=scalar(phase,'sampling phase',nonnegative=True)
    if phase>=1 or type(max_samples) is not int or max_samples<4:
        raise ReferenceDataError('phase in [0,1) and finite sample limit required')
    _check_cancel(cancel)
    shape=input_shape(directions,'spherical directions')
    if len(shape)!=2 or shape[1]!=3:
        raise ReferenceDataError('expected N by 3 directions')
    p=_unit_vectors(directions)
    if np.linalg.norm(p[0]-p[-1])<2e-14:p=p[:-1]
    if len(p)<3:raise ReferenceDataError('three vertices required')
    b=np.roll(p,-1,axis=0);arcs=_angles(p,b)
    if np.any(arcs<=1e-14) or np.any(arcs>=math.pi-1e-12):raise ReferenceDataError('invalid ring edge')
    length=math.fsum(arcs)
    if spacing < length/max_samples:
        raise ReferenceDataError('requested observation resolution exceeds sample budget')
    count=int(math.ceil(length/spacing))
    if count<4:return None  # Unresolved at this physical scale; not an invented zero.
    if count>max_samples:raise ReferenceDataError('requested observation resolution exceeds sample budget')
    with select_budget(budget).reserve(256*(len(p)+count)+16384,category='plate-reference-sampling'):
        edges=np.r_[0.,np.cumsum(arcs)]
        targets=((np.arange(count)+phase)*length/count)%length
        idx=np.minimum(np.searchsorted(edges,targets,side='right')-1,len(p)-1)
        t=(targets-edges[idx])/arcs[idx]
        theta=arcs[idx]
        out=(np.sin((1-t)*theta)[:,None]*p[idx]+np.sin(t*theta)[:,None]*b[idx])/np.sin(theta)[:,None]
        _check_cancel(cancel)
        return frozen(out)


def sample_ring_at_scale(directions, spacing_rad, *, phase=0., max_samples=100000, budget=None, cancel=None):
    """Memory-admitted arc-length sampling; retained caller output is separate."""
    _check_cancel(cancel)
    shape=input_shape(directions,'spherical directions')
    if len(shape)!=2 or shape[1]!=3:
        raise ReferenceDataError('expected N by 3 directions')
    policy=select_budget(budget)
    with policy.reserve(256*shape[0]+16384,category='plate-reference-sampling-input'):
        return _sample_ring_at_scale(directions,spacing_rad,phase=phase,max_samples=max_samples,
                                     budget=policy,cancel=cancel)


def multiscale_ring_measures(directions, radius_m, scales_m=(100000.,250000.,500000.), *, budget=None, cancel=None):
    """Report two sampling phases; no minimum plate-size information is discarded."""
    radius=scalar(radius_m,'radius',positive=True)
    if type(scales_m) not in (tuple,list) or not 1<=len(scales_m)<=16:
        raise ReferenceDataError('finite explicit observation-scale sequence required')
    native=spherical_ring_measures(directions,budget=budget,cancel=cancel)
    records=[]
    for scale in scales_m:
        scale=scalar(scale,'physical observation scale',positive=True)
        phases=[]
        for phase in (0.,.5):
            points=sample_ring_at_scale(directions,scale/radius,phase=phase,budget=budget,cancel=cancel)
            if points is None:
                phases.append({'phase':phase,'status':'UNRESOLVED_AT_SCALE'});continue
            m=spherical_ring_measures(points,budget=budget,cancel=cancel)
            # Boundary-length-weighted second moment, NOT the area inertia tensor.
            eigen=np.linalg.eigvalsh(points.T@points/len(points))
            phases.append(dict(phase=phase,status='MEASURED',samples=len(points),
                               sampled_perimeter_radians=m['perimeter_radians'],
                               sampled_area_steradians=m['area_steradians'],
                               sampled_compactness=m['compactness'],
                               reflex_turning_radians=m['reflex_turning_radians'],
                               absolute_turning_radians=m['absolute_turning_radians'],
                               boundary_second_moment_eigenvalues=eigen.tolist()))
        records.append(dict(scale_m=scale,phases=phases))
    return dict(native=native,scales=records,
                interpretation='scale-labelled shape measurements, not a geological acceptance score')


def step_motion(step: BoundaryStep, poles: Mapping[str,EulerPole], *, radius_m=EARTH_REFERENCE_RADIUS_M):
    """Forward relative motion at a minor-arc midpoint, with source-derived bounds.

    Bird reports v_left-v_right, divergent opening and right-lateral slip. Atlas's
    opening is (v_right-v_left).right_normal; the right-lateral sign is the opposite
    of Atlas's right-minus-left tangential component. Do not change these signs to
    match a plotted boundary. Source rounding bounds are NOT geological uncertainty.
    """
    if type(step) is not BoundaryStep:raise ReferenceDataError('BoundaryStep required')
    radius=scalar(radius_m,'reference radius',positive=True)
    left,right=step.boundary[:2],step.boundary[3:]
    if left not in poles or right not in poles:raise ReferenceDataError('missing named Euler pole')
    a,b=lonlat_vectors([step.start,step.end])
    theta=float(_angles(a[None,:],b[None,:])[0])
    if not 1e-14<theta<math.pi-1e-12:
        raise ReferenceDataError('zero or ambiguous antipodal boundary step')
    mid=a+b;mid/=np.linalg.norm(mid)
    normal=np.cross(a+b,b-a);norm=np.linalg.norm(normal)
    if norm<=1e-14:raise ReferenceDataError('unresolved boundary direction')
    normal/=norm;tangent=np.cross(normal,mid)
    relative=np.cross(poles[right].vector_rad_ma-poles[left].vector_rad_ma,mid)*radius*.001
    opening=float(relative@(-normal));lateral=-float(relative@tangent)
    speed=float(np.linalg.norm(relative));theta=float(_angles(a[None,:],b[None,:])[0])
    # Two endpoint positions rounded to 0.001 degrees constrain the plane normal.
    # This conservative bound widens for short steps; an unresolved direction is
    # reported rather than assigned a convenient universal velocity tolerance.
    epsilon=math.sqrt(2)*math.radians(STEP_POSITION_HALF_UNIT_DEG)
    cross_error=4*epsilon+4*epsilon**2
    relative_normal_error=cross_error/max(math.sin(theta),np.finfo(float).tiny)
    angle_bound=math.asin(min(1.,relative_normal_error))
    pole_error=0.;maximum_rate=0.
    for name in (left,right):
        pole=poles[name]
        maximum_rate+=math.radians(abs(pole.rate_deg_ma))
        pole_error+=math.radians(POLE_RATE_HALF_UNIT_DEG_MA)+math.radians(abs(pole.rate_deg_ma))*math.sqrt(2)*math.radians(POLE_POSITION_HALF_UNIT_DEG)
    bound=.05+radius*.001*(pole_error+maximum_rate*(epsilon+2*math.sin(angle_bound/2)))
    speed_bound=.05+radius*.001*(pole_error+maximum_rate*epsilon)
    length_bound_km=.05+2*radius*epsilon/1000
    if not all(map(math.isfinite,(opening,lateral,speed,bound,length_bound_km))):
        raise ReferenceDataError('motion units outside finite numerical range')
    return dict(number=step.number,boundary=step.boundary,kind=step.kind,
                opening_mm_a=opening,right_lateral_mm_a=lateral,speed_mm_a=speed,
                source_opening_mm_a=step.opening_mm_a,source_right_lateral_mm_a=step.right_lateral_mm_a,
                source_speed_mm_a=step.speed_mm_a,
                opening_error_mm_a=opening-step.opening_mm_a,
                right_lateral_error_mm_a=lateral-step.right_lateral_mm_a,
                component_rounding_bound_mm_a=bound,
                speed_error_mm_a=speed-step.speed_mm_a,speed_rounding_bound_mm_a=speed_bound,
                direction_resolved=relative_normal_error<1,
                length_km=theta*radius/1000,source_length_km=step.length_km,
                length_rounding_bound_km=length_bound_km,
                observed_boundary_class_preserved=True)
