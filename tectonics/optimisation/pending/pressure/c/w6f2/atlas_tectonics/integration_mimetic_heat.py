"""Conservative hybrid-mimetic diffusion on a source-issued metric complex.

This is the diffusion operator, not a physical mesh certificate. The exterior
geometry producer must establish support, non-overlap and geometric error.
Exact metric identities here establish linear consistency and paired incidence.
Method: Droniou (2014), section 4, equations 42--44 (HFV/HMM formulation).
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import weakref

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import cg, LinearOperator

from ._validation import TectonicsError, scalar
from .integration_regional_inventory import _width
from .regional_execution import RegionalMechanicalSnapshot
from .regional_heat3d import _cancel
from .resources import WorkBudget, MemoryLimitError, _ResizableLease
from .stokes_execution import _native_lease

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ALGEBRA = 1e-11                    # same linear/energy gate as native 3-D heat
# Cell-centred extremum-preserving discretisation (integration_extremum_heat):
# selected explicitly, it replaces the hybrid-mimetic solve for that plan.
EXTREMUM = 'extremum-multipoint'


def _json(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(record):
    return hashlib.sha256(_json(record)).hexdigest()


def _q(pair):
    if type(pair) is not list or len(pair) != 2 or any(type(v) is not str for v in pair):
        raise TectonicsError('canonical rational-hex metric pair required')
    try:
        result = Q(int(pair[0], 16), int(pair[1], 16))
    except (ValueError, ZeroDivisionError) as exc:
        raise TectonicsError('invalid exact thermal metric') from exc
    if [hex(result.numerator), hex(result.denominator)] != pair:
        raise TectonicsError('noncanonical exact thermal metric')
    return result


def _enc(value):
    value = Q(value)
    return [hex(value.numerator), hex(value.denominator)]


def _vector(value):
    if type(value) is not list or len(value) != 3:
        raise TectonicsError('three exact thermal coordinates required')
    return tuple(map(_q, value))


def _dot(a, b):
    return sum((x*y for x, y in zip(a, b)), Q(0))


def _moment_fails(vectors, centres, indexes, volume):
    """Exact reference first moments, after the caller's area-closure check."""
    return any(sum(n[i]*centres[fi][j] for n, fi in zip(vectors, indexes, strict=False)) !=
               (volume if i == j else 0) for i in range(3) for j in range(3))


_MOMENT_REFERENCE = _moment_fails


def _admitted_moment_fails(vectors, centres, indexes, volume, budget):
    """One complete bool-only operation; wrapped reference helpers stay visible."""
    if _moment_fails is not _MOMENT_REFERENCE:
        return _moment_fails(vectors, centres, indexes, volume)
    from . import integration_volume_bounds as B
    kernel = B._resident()
    if kernel is B:
        return _moment_fails(vectors, centres, indexes, volume)
    return kernel._mimetic_moment_fails(vectors, centres, indexes, volume, budget)


def _retain(obj, size, budget):
    lease = budget.reserve(size, category='mimetic-heat-retained')
    lease.__enter__()
    weakref.finalize(obj, lease.__exit__, None, None, None)



def _stream_encoding_capacity(record, budget):
    """Canonical bytes plus only the active iterencode path/token workspace."""
    from .integration_spatial_transport import _json_encoding_capacity, _workspace
    from .resources import _GrowingLease
    encoded, _ = _json_encoding_capacity(record, budget)
    active = set()
    largest = 32
    path_work = deepest = 0
    with _workspace(budget, 65536, 'mimetic-json-stream-scan') as workspace:
        scan = workspace.enter_context(_GrowingLease(budget))
        def visit(node, depth, entries):
            nonlocal largest, path_work, deepest
            if depth > deepest:
                scan.add(2048*(depth-deepest), category='mimetic-json-stream-scan')
                deepest = depth
            if isinstance(node, (dict, list, tuple)):
                identity = id(node)
                if identity in active:
                    raise ValueError('Circular reference detected')
                active.add(identity)
                if isinstance(node, dict):
                    entries += len(node)
                path_work = max(path_work, 2048*depth+128*entries)
                try:
                    if isinstance(node, dict):
                        for key, value in node.items():
                            visit(key, depth+1, entries)
                            visit(value, depth+1, entries)
                    else:
                        for value in node:
                            visit(value, depth+1, entries)
                finally:
                    active.remove(identity)
            elif isinstance(node, str):
                # ensure_ascii emits at most six bytes per BMP code point,
                # twelve per non-BMP point. This does not format/copy tokens.
                largest = max(largest, 2+(6 if node.isascii() else 12)*len(node))
            elif isinstance(node, int):
                largest = max(largest, 4+(abs(node).bit_length()*30103)//100000)
        visit(record, 1, 0)
    # One mutable full-output buffer; immutable returned bytes are funded by
    # the caller. Two successive Unicode tokens and their ASCII conversion
    # can overlap. Sorted-key tables persist along the whole ancestor path.
    return encoded, 65536+encoded+4*largest+path_work


def _stream_json(record, encoded_capacity, scratch, budget):
    """Same canonical bytes, without the C encoder's all-chunk accumulation."""
    from .integration_spatial_transport import _workspace
    with _workspace(budget, scratch, 'mimetic-metric-encoding'):
        output = bytearray(encoded_capacity-64)
        view = memoryview(output)
        offset = 0
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
        for chunk in encoder.iterencode(record):
            part = chunk.encode('ascii')
            end = offset+len(part)
            if end > len(output):
                raise RuntimeError('canonical JSON capacity was exceeded')
            view[offset:end] = part
            offset = end
        return bytes(view[:offset])


def _metric_allocation_capacity(record, budget):
    """Fund new exact metrics and work, not the caller's borrowed provenance.

    Hex widths bound parsing without decoding rationals. Each incidence uses
    its own face/centre widths. Denominator products bound exact sums without
    assuming cancellation; only one arithmetic expression is evaluated at once.
    """
    from .integration_spatial_transport import (_workspace, _hex_pair_bits,
        _rational_storage, _difference_bits, _sum_profile_bits, _add_profile)
    cells, faces = record['cells'], record['faces']
    with _workspace(budget, 65536+2048*len(faces), 'mimetic-metric-capacity-scan'):
        def vector_bits(value):
            if type(value) is not list or len(value) != 3:
                return ((1, 1),)*3
            return tuple(_hex_pair_bits(pair) for pair in value)
        profiles = {}
        face_work = face_ids = largest_parse = largest_claim = 0
        for row in faces:
            face_ids += _width(row['face_id'])
            centre, normal = vector_bits(row['centroid_m']), vector_bits(row['area_vector_m2'])
            for bits in (*centre, *normal):
                face_work += _rational_storage(bits)
                largest_parse = max(largest_parse, 8*_rational_storage(bits)+sum(bits))
            if type(row['face_id']) is str:
                profiles[row['face_id']] = centre, normal
            claimed = row.get('owners')
            if type(claimed) in (list, tuple, dict, str):
                largest_claim = max(largest_claim, 256*len(claimed))
        retained = 8192+256*(len(cells)+len(faces))+face_ids
        scratch = 65536+1024*len(faces)+512*len(cells)+face_work+largest_claim
        arithmetic = 0
        for row in cells:
            row['cell_id']
            volume = _hex_pair_bits(row['volume_m3'])
            centre = vector_bits(row['centroid_m'])
            retained += 512+_rational_storage(volume)+sum(map(_rational_storage, centre))
            for bits in (volume, *centre):
                largest_parse = max(largest_parse, 8*_rational_storage(bits)+sum(bits))
            sums = [[0, 0, 0] for _ in range(12)]
            linked = row['faces'] if type(row['faces']) is list else ()
            for item in linked:
                if type(item) not in (list, tuple) or len(item) != 2 or type(item[0]) is not str:
                    continue  # The original incidence validation remains decisive.
                face_centre, normal = profiles.get(item[0], (((1, 1),)*3, ((1, 1),)*3))
                offset = tuple(_difference_bits(a, b) for a, b in zip(face_centre, centre))
                distance_profile = [0, 0, 0]
                for i in range(3):
                    _add_profile(sums[i], normal[i])
                    for j in range(3):
                        product = normal[i][0]+offset[j][0], normal[i][1]+offset[j][1]
                        _add_profile(sums[3+3*i+j], product)
                        if i == j:
                            _add_profile(distance_profile, product)
                distance = _sum_profile_bits(distance_profile)
                retained += (512+sum(map(_rational_storage, normal))+
                    sum(map(_rational_storage, offset))+_rational_storage(distance))
                arithmetic = max(arithmetic, 32*_rational_storage(
                    (2*distance[0]+2, 2*distance[1]+2)))
            for profile in sums:
                bits = _sum_profile_bits(profile)
                # Includes cross-products against the exact volume and GCD work.
                arithmetic = max(arithmetic, 32*_rational_storage(
                    (2*max(bits[0], volume[0])+2, 2*max(bits[1], volume[1])+2)))
            scratch += 512+256*len(linked)
        return retained, scratch+arithmetic+largest_parse


class _CompactMetricRow:
    """One explicitly owned decoded row; never a whole-record substitute."""
    __slots__ = ('_owned',)

    def __init__(self, owned):
        self._owned = owned

    def __getitem__(self, key):
        return self._owned.value[key]

    def get(self, key, default=None):
        return self._owned.value.get(key, default)


class _CompactMetricRows:
    """A bounded row accessor, not an eagerly reconstructed metric record."""
    __slots__ = ('view', 'kind')

    def __init__(self, view, kind):
        self.view, self.kind = view, kind

    def __len__(self):
        return self.view.cell_count if self.kind == 'cell' else self.view.face_count

    def __getitem__(self, index):
        if type(index) is not int or not 0 <= index < len(self):
            raise IndexError(index)
        owned = self.view.cell(index) if self.kind == 'cell' else self.view.face(index)
        return _CompactMetricRow(owned)

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


class MimeticGeometry:
    """Immutable exact metric complex, with no invented physical certification.

    A record contains cells with cell_id, volume_m3, centroid_m and signed face
    references; faces contain face_id, centroid_m and area_vector_m2. Other
    producer provenance and physical approximation bounds are retained verbatim.
    Each planar control cell must have a strict star-shaped centre, with the
    complete first-moment identity checked below. Producers may supply convex
    cells or exact unions with cancelled internal facets and a proved kernel.
    The metric point need not equal the volume centroid (Droniou2014, §4).
    """
    def __setattr__(self, name, value):
        if hasattr(self, name):
            raise TectonicsError('mimetic geometry is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, record, *, budget):
        if type(budget) is not WorkBudget or type(record) is not dict:
            raise TectonicsError('explicit geometry record and shared WorkBudget required')
        if type(record.get('cells')) is not list or type(record.get('faces')) is not list:
            raise TectonicsError('complete cell and planar-face metric tables required')
        if not record['cells'] or not record['faces']:
            raise TectonicsError('empty thermal metric complex')
        # Borrowed source provenance is already owned by the caller. Only
        # the immutable encoding, decoded metrics and real work are admitted.
        # Lazy imports avoid transport's existing import of this module's _q.
        from .integration_spatial_transport import _workspace, _preserve_workspace
        encoded_capacity, encoding_scratch = _stream_encoding_capacity(record, budget)
        metric_retained, metric_scratch = _metric_allocation_capacity(record, budget)
        retained = ExitStack()
        committed = False
        try:
            live = retained.enter_context(_ResizableLease(budget, category='mimetic-heat-retained'))
            live.resize(encoded_capacity)
            encoded = _stream_json(record, encoded_capacity, encoding_scratch, budget)
            live.resize(64+len(encoded))
            live.resize(64+len(encoded)+metric_retained)
            with _workspace(budget, metric_scratch, 'mimetic-metric-validation'):
                faces, centres, normals = {}, [], []
                for i, row in enumerate(record['faces']):
                    key = row.get('face_id')
                    if type(key) is not str or not key or key in faces:
                        raise TectonicsError('unique named thermal faces required')
                    faces[key] = i
                    centres.append(_vector(row['centroid_m']))
                    normal = _vector(row['area_vector_m2'])
                    if not any(normal):
                        raise TectonicsError('zero-area thermal face')
                    normals.append(normal)
                incidence = [[] for _ in faces]
                keys, decoded = set(), []
                for ci, row in enumerate(record['cells']):
                    key = row.get('cell_id')
                    if type(key) is not str or not key or key in keys:
                        raise TectonicsError('unique named thermal cells required')
                    keys.add(key)
                    volume, centre = _q(row['volume_m3']), _vector(row['centroid_m'])
                    if volume <= 0 or type(row['faces']) is not list or len(row['faces']) < 4:
                        raise TectonicsError('positive three-dimensional thermal cell required')
                    indexes, signs, offsets, vectors, distances = [], [], [], [], []
                    for face, sign in row['faces']:
                        if face not in faces or type(sign) is not int or sign not in (-1, 1):
                            raise TectonicsError('named signed thermal face incidence required')
                        fi = faces[face]
                        if fi in indexes:
                            raise TectonicsError('duplicate face in one thermal cell')
                        vector = tuple(sign*v for v in normals[fi])
                        offset = tuple(x-y for x, y in zip(centres[fi], centre))
                        distance = _dot(vector, offset)
                        if distance <= 0:
                            raise TectonicsError('thermal centre must be strictly inside every planar face')
                        indexes.append(fi); signs.append(sign); offsets.append(offset)
                        vectors.append(vector); distances.append(distance)
                        incidence[fi].append((ci, sign))
                    if any(sum(n[j] for n in vectors) != 0 for j in range(3)):
                        raise TectonicsError('exact thermal face vectors do not close')
                    # The closure statement directly above has refused every
                    # cell whose area vectors do not sum to zero exactly, so
                    # sum(n_i*(x_f-x_c)_j) = sum(n_i*x_f,j)-x_c,j*sum(n_i)
                    # equals sum(n_i*x_f,j). The first moment is therefore
                    # summed over the face centroids, with the same exact
                    # value in each of the nine entries. This equivalence
                    # depends on that statement standing first, unconditionally.
                    if _admitted_moment_fails(vectors, centres, indexes, volume, budget):
                        raise TectonicsError('thermal metric moments violate the exact divergence identity')
                    decoded.append((volume, centre, tuple(indexes), tuple(signs), tuple(offsets),
                                    tuple(vectors), tuple(distances)))
                for fi, linked in enumerate(incidence):
                    if len(linked) not in (1, 2) or (len(linked) == 2 and linked[0][1]+linked[1][1] != 0):
                        raise TectonicsError('thermal face requires one boundary owner or opposite paired owners')
                    claimed = record['faces'][fi].get('owners')
                    if claimed is not None and sorted(claimed) != sorted(record['cells'][i]['cell_id'] for i, _ in linked):
                        raise TectonicsError('thermal face owners disagree with actual signed cell incidence')
                self._encoded, self._cells, self._incidence = encoded, tuple(decoded), tuple(map(tuple, incidence))
                self._face_ids, self._budget = tuple(faces), budget
                self.geometry_id = hashlib.sha256(encoded).hexdigest()
                # Clear mutable construction containers before releasing work.
                del faces, centres, normals, incidence, keys, decoded
                del indexes, signs, offsets, vectors, distances
                del normal, centre, vector, offset, distance, volume
                weakref.finalize(self, retained.close)
                committed = True
        except BaseException as error:
            failure_owner = _preserve_workspace(error, retained)
            raise
        finally:
            if not committed:
                retained.close()

    @classmethod
    def from_compact(cls, view, *, budget):
        """Validate indexed exact metrics without expanding source provenance.

        CompactMesh authenticates storage and canonical scientific identity;
        this entrypoint still performs every native metric/ownership check.
        Neither operation certifies physical coverage or a heat solution.
        """
        from mesh_tables import CompactMesh
        from .integration_spatial_transport import _workspace, _preserve_workspace
        if (cls is not MimeticGeometry or type(view) is not CompactMesh or
                not getattr(view, '_sealed', False) or type(budget) is not WorkBudget):
            raise TectonicsError('actual compact mesh and shared WorkBudget required')
        if view.budget is not budget:
            raise TectonicsError('compact thermal mesh belongs to a different budget')
        if not view.cell_count or not view.face_count:
            raise TectonicsError('empty thermal metric complex')
        face_rows = _CompactMetricRows(view, 'face')
        cell_rows = _CompactMetricRows(view, 'cell')
        # This bounded scan retains bit-width profiles, not a decoded copy of
        # geometry/support provenance. The original exact arithmetic capacity
        # calculation is reused with indexed sequences.
        metric_retained, metric_scratch = _metric_allocation_capacity(
            {'faces': face_rows, 'cells': cell_rows}, budget)
        self = object.__new__(cls)
        retained = ExitStack()
        committed = False
        try:
            live = retained.enter_context(_ResizableLease(budget, category='mimetic-heat-retained'))
            live.resize(metric_retained+4096)
            with _workspace(budget, metric_scratch, 'mimetic-metric-validation'):
                faces, centres, normals = {}, [], []
                for i, row in enumerate(face_rows):
                    key = row.get('face_id')
                    if type(key) is not str or not key or key in faces:
                        raise TectonicsError('unique named thermal faces required')
                    faces[key] = i
                    centres.append(_vector(row['centroid_m']))
                    normal = _vector(row['area_vector_m2'])
                    if not any(normal):
                        raise TectonicsError('zero-area thermal face')
                    normals.append(normal)
                incidence = [[] for _ in faces]
                keys, decoded = set(), []
                for ci, row in enumerate(cell_rows):
                    key = row.get('cell_id')
                    if type(key) is not str or not key or key in keys:
                        raise TectonicsError('unique named thermal cells required')
                    keys.add(key)
                    volume, centre = _q(row['volume_m3']), _vector(row['centroid_m'])
                    if volume <= 0 or type(row['faces']) is not list or len(row['faces']) < 4:
                        raise TectonicsError('positive three-dimensional thermal cell required')
                    indexes, signs, offsets, vectors, distances = [], [], [], [], []
                    for face, sign in row['faces']:
                        if face not in faces or type(sign) is not int or sign not in (-1, 1):
                            raise TectonicsError('named signed thermal face incidence required')
                        fi = faces[face]
                        if fi in indexes:
                            raise TectonicsError('duplicate face in one thermal cell')
                        vector = tuple(sign*v for v in normals[fi])
                        offset = tuple(x-y for x, y in zip(centres[fi], centre))
                        distance = _dot(vector, offset)
                        if distance <= 0:
                            raise TectonicsError('thermal centre must be strictly inside every planar face')
                        indexes.append(fi); signs.append(sign); offsets.append(offset)
                        vectors.append(vector); distances.append(distance)
                        incidence[fi].append((ci, sign))
                    if any(sum(n[j] for n in vectors) != 0 for j in range(3)):
                        raise TectonicsError('exact thermal face vectors do not close')
                    # The closure statement directly above has refused every
                    # cell whose area vectors do not sum to zero exactly, so
                    # sum(n_i*(x_f-x_c)_j) = sum(n_i*x_f,j)-x_c,j*sum(n_i)
                    # equals sum(n_i*x_f,j). The first moment is therefore
                    # summed over the face centroids, with the same exact
                    # value in each of the nine entries. This equivalence
                    # depends on that statement standing first, unconditionally.
                    if _admitted_moment_fails(vectors, centres, indexes, volume, budget):
                        raise TectonicsError('thermal metric moments violate the exact divergence identity')
                    decoded.append((volume, centre, tuple(indexes), tuple(signs), tuple(offsets),
                                    tuple(vectors), tuple(distances)))
                for fi, linked in enumerate(incidence):
                    if len(linked) not in (1, 2) or (len(linked) == 2 and linked[0][1]+linked[1][1] != 0):
                        raise TectonicsError('thermal face requires one boundary owner or opposite paired owners')
                    claimed = face_rows[fi].get('owners')
                    if claimed is not None and sorted(claimed) != sorted(cell_rows[i]['cell_id'] for i, _ in linked):
                        raise TectonicsError('thermal face owners disagree with actual signed cell incidence')
                self._indexed = view
                self._encoded = None
                self._cells, self._incidence = tuple(decoded), tuple(map(tuple, incidence))
                self._face_ids, self._budget = tuple(faces), budget
                self.geometry_id = view.geometry_id
                del faces, centres, normals, incidence, keys, decoded
                del indexes, signs, offsets, vectors, distances
                del normal, centre, vector, offset, distance, volume
                weakref.finalize(self, retained.close)
                committed = True
                return self
        except BaseException as error:
            failure_owner = _preserve_workspace(error, retained)
            raise
        finally:
            if not committed:
                retained.close()

    def cell_id(self, index):
        """Failure diagnostics must not expand the entire indexed mesh."""
        indexed = getattr(self, '_indexed', None)
        if indexed is not None:
            owned = indexed.cell(index)
            return owned.value['cell_id']
        return self.record()['cells'][index]['cell_id']

    def legacy_record(self):
        """Explicit charged export; retain its owner while borrowing .value."""
        indexed = getattr(self, '_indexed', None)
        if indexed is None:
            raise TectonicsError('owned legacy export is specific to indexed geometry')
        return indexed.legacy_record()

    def record(self):
        indexed = getattr(self, '_indexed', None)
        if indexed is not None:
            raise TectonicsError('indexed geometry requires direct rows or explicit owned legacy_record export')
        return json.loads(self._encoded)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class MimeticHeatResult:
    """Actual issued solve, with the exact binary input arrays it consumed."""
    _snapshot: RegionalMechanicalSnapshot = field(repr=False)
    _budget: object = field(repr=False, compare=False)
    _geometry: MimeticGeometry = field(repr=False)
    _plan_definition: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('mimetic heat results are issued by their prepared solver')

    @property
    def result_id(self):
        return self._snapshot.result_id

    @property
    def nbytes(self):
        return self._snapshot.nbytes

    @property
    def array_names(self):
        return self._snapshot.array_names

    def descriptor(self):
        return self._snapshot.descriptor()

    def plan_descriptor(self):
        """Immutable issuing-plan evidence, outside the unchanged result identity."""
        encoded = getattr(self, '_plan_definition', None)
        if type(encoded) is not bytes or hashlib.sha256(encoded).hexdigest() != self.descriptor().get('plan_id'):
            raise TectonicsError('joined heat result lacks its bound solver plan')
        return json.loads(encoded)

    def array(self, name):
        return self._snapshot.array(name)


class PreparedMimeticHeat3D:
    """One paired implicit diffusion solve, including the actual finite cells.

    Face temperatures are retained unknowns, not a two-point approximation on
    oblique cells. Capacities come from the CURRENT advected material each step.
    The sparse operator is prepared once for unchanged geometry/conductivity;
    no dense all-pairs matrix or unbounded factor cache is constructed.
    """
    def __init__(self, geometry, conductivity_w_m_k, *, budget, positivity_method='refuse'):
        self._guard = None
        self._closed, self._active = False, False
        if type(geometry) is not MimeticGeometry or geometry._budget is not budget:
            raise TectonicsError('issued exact thermal metrics on the shared budget required')
        if positivity_method not in ('refuse', 'experimental-nonlinear-insulated', 'experimental-kss',
                                     'experimental-bounded-kss', EXTREMUM):
            raise TectonicsError('unknown mimetic positivity method')
        self._positivity_method = positivity_method
        self._geometry, self._budget = geometry, budget
        self._nc, self._nf = len(geometry._cells), len(geometry._incidence)
        self._n = self._nc+self._nf
        entries = sum((len(row[2])+1)**2 for row in geometry._cells)
        self._guard = budget.reserve(2*1024**2+96*entries+2048*self._n, category='mimetic-heat-plan')
        self._guard.__enter__()
        try:
            conductivity = np.broadcast_to(np.asarray(conductivity_w_m_k, dtype=float), (self._nc,)).copy()
            if not np.isfinite(conductivity).all() or np.any(conductivity <= 0):
                raise TectonicsError('positive finite cell conductivity required')
            if positivity_method == EXTREMUM:
                self._prepare_extremum(conductivity)
                return
            rows, cols, values, local = [], [], [], []
            patch_roundoff = 0.
            with _native_lease(), np.errstate(over='raise', invalid='raise', divide='raise'):
                for ci, (volume, _, faces, signs, offsets, vectors, distances) in enumerate(geometry._cells):
                    m = len(faces)
                    indices = np.asarray((ci, *(self._nc+f for f in faces)), dtype=int)
                    G = np.zeros((3, m+1))
                    G[:, 1:] = np.asarray([[float(v/volume) for v in n] for n in vectors]).T
                    # Exact closure makes the cell coefficient identically zero;
                    # do not manufacture a small gradient from summation roundoff.
                    dx = np.asarray([[float(q) for q in x] for x in offsets])
                    S = np.column_stack((-np.ones(m), np.eye(m)))-dx@G
                    gamma = np.asarray([float(Q(float(conductivity[ci]))*_dot(n, n)/d)
                                        for n, d in zip(vectors, distances)])
                    K = float(volume)*conductivity[ci]*(G.T@G)+S.T@(gamma[:, None]*S)
                    # Derive cell entries from the face block, preserving the
                    # constant nullspace algebraically instead of discarding it.
                    K[0, 1:] = -np.sum(K[1:, 1:], axis=0)
                    K[1:, 0] = K[0, 1:]
                    K[0, 0] = -np.sum(K[0, 1:])
                    if not np.isfinite(K).all() or np.any(np.diag(K) <= 0):
                        raise TectonicsError('unrepresentable or degenerate mimetic cell operator')
                    # Precision selection, not a changed physical criterion.
                    # On an affine temperature the exact face action is k*n.g
                    # and the cell action is zero. Near-coincident planes can
                    # make this O(1) identity disappear in a binary64 Gram
                    # matrix even when a subsequent relative residual is tiny.
                    # Compare against the physical affine flux, not against
                    # the arbitrarily large stabilisation coefficients.
                    affine = np.vstack((np.zeros((1, 3)), dx))
                    expected = np.vstack((np.zeros((1, 3)),
                        conductivity[ci]*np.asarray(vectors, dtype=float)))
                    flux_scale = np.max(np.abs(expected), axis=0)
                    patch_roundoff = max(patch_roundoff,
                        float(np.max(np.abs(K@affine-expected)/flux_scale)))
                    local.append((indices, K, signs))
                    rows.extend(np.repeat(indices, m+1)); cols.extend(np.tile(indices, m+1)); values.extend(K.ravel())
                matrix = sparse.coo_matrix((values, (rows, cols)), shape=(self._n, self._n)).tocsr()
                matrix.sum_duplicates(); matrix.eliminate_zeros()
            self._matrix, self._local = matrix, tuple(local)
            self._conductivity = conductivity
            self._decimal_required = patch_roundoff > ALGEBRA
            self._definition = dict(schema='atlas.mimetic-heat-plan.v1', geometry_id=geometry.geometry_id,
                conductivity_w_m_k=conductivity.tolist(), cells=self._nc, faces=self._nf,
                method='hybrid mimetic mixed; exact metric consistency plus positive normal-distance stabilisation',
                time_method='backward Euler on current advected capacities',
                linear_method='symmetric CG with diagonal preconditioner; same-form matrix-free precision fallback; no dense factor',
                linear_relative_tolerance=ALGEBRA, energy_relative_tolerance=ALGEBRA,
                binary64_affine_patch_relative_error=patch_roundoff,
                arithmetic_policy='binary64 unless local affine consistency or current-capacity addition loses the existing algebra tolerance; then decimal80',
                positivity_method=positivity_method,
                positivity_policy='original refusal by default; explicit experimental opt-in enables insulated Scheme 2; active correction has unverified thin-cell accuracy and no second-order claim',
                boundary='declared whole-domain thermal boundary; omitted faces explicitly insulated',
                geometric_accuracy='producer owns physical support and approximation bounds; metric identities alone do not certify it')
            self.plan_id = _hash(self._definition)
            self._stats = dict(advances=0, cg_iterations=0, matrix_builds=1,
                               precision_fallback_advances=0, precision_factor_builds=0,
                               nonlinear_fallback_advances=0)
            self._verify()
        except BaseException:
            self.close()
            raise

    def _verify(self):
        if self._closed or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
            raise TectonicsError('closed or changed mimetic diffusion source')

    @contextmanager
    def _operation(self, cancel):
        self._verify(); _cancel(cancel)
        if self._active:
            raise TectonicsError('mimetic heat plan is already active')
        self._active = True
        try:
            with _native_lease():
                yield
        finally:
            self._active = False

    def descriptor(self):
        self._verify(); return json.loads(_json(self._definition))

    def statistics(self):
        return dict(self._stats)

    def advance(self, enthalpy_j, capacity_j_k, duration_s, *, state_id,
                source_w=0., boundary=None, cancel=None):
        """Boundary values are ('temperature', K) or ('power', outward watts)."""
        dt = scalar(duration_s, 'heat duration', positive=True)
        if type(state_id) is not str or not state_id:
            raise TectonicsError('actual current material/geometry state identity required')
        if self._positivity_method == EXTREMUM:
            return self._advance_extremum(enthalpy_j, capacity_j_k, dt, state_id, source_w, boundary, cancel)
        with self._operation(cancel), self._budget.reserve(2*1024**2+1024*self._n+32*self._matrix.nnz,
                category='mimetic-heat-step'):
            def cells(value, label, positive=False):
                result = np.broadcast_to(np.asarray(value, dtype=float), (self._nc,)).copy()
                if not np.isfinite(result).all() or (positive and np.any(result <= 0)):
                    raise TectonicsError(label+' must be finite'+(' and positive' if positive else ''))
                return result
            old, capacity = cells(enthalpy_j, 'enthalpy', True), cells(capacity_j_k, 'capacity', True)
            source = cells(source_w, 'source power')
            boundary = {} if boundary is None else dict(boundary)
            reference = float(old[0]/capacity[0])
            initial = old-capacity*reference
            rhs = np.r_[initial+dt*source, np.zeros(self._nf)]
            A = dt*self._matrix+sparse.diags(np.r_[capacity, np.zeros(self._nf)], format='csr')
            fixed, fixed_values = [], []
            ids = {name: i for i, name in enumerate(self._geometry._face_ids)}
            for name, entry in boundary.items():
                if name not in ids or len(self._geometry._incidence[ids[name]]) != 1:
                    raise TectonicsError('thermal boundary must name an actual one-owner face')
                if type(entry) not in (tuple, list) or len(entry) != 2:
                    raise TectonicsError('typed thermal boundary pair required')
                kind, value = entry
                value = scalar(value, 'thermal boundary value')
                fi = ids[name]
                if kind == 'temperature':
                    if value <= 0:
                        raise TectonicsError('absolute boundary temperature must be positive')
                    fixed.append(self._nc+fi); fixed_values.append(value-reference)
                elif kind == 'power':
                    rhs[self._nc+fi] -= dt*value
                else:
                    raise TectonicsError('thermal boundary must declare temperature or outward power')
            fixed = np.asarray(fixed, dtype=int)
            free = np.ones(self._n, dtype=bool); free[fixed] = False
            solution = np.zeros(self._n); solution[fixed] = fixed_values
            # A thin but positive cell can also have a perfectly represented
            # affine stiffness yet lose its finite capacity when C is added
            # to dt*K. Select arithmetic from that roundoff bound, not from a
            # dimensional cell-size cutoff or a changed physical tolerance.
            high_precision = self._decimal_required or bool(np.any(
                np.spacing(dt*self._matrix.diagonal()[:self._nc]) > ALGEBRA*capacity))
            arithmetic = dict(precision='binary64')
            factor_builds = int(high_precision)
            if high_precision:
                from .integration_mimetic_precision import solve
                precise = solve(self._geometry, self._conductivity, old, capacity,
                    dt, source, boundary, reference, budget=self._budget, cancel=cancel)
                solution = precise['solution']
                new = precise['enthalpy']
                raw = precise['raw']
                iterations = [precise['iterations']]
                relative, norm, rhs_norm = (precise[k] for k in ('linear_relative', 'rhs_max', 'rhs_norm'))
                arithmetic = precise['evidence']
            else:
                reduced = A[free][:, free].tocsr()
                reduced_rhs = rhs[free]-A[free][:, fixed]@solution[fixed]
                diag = reduced.diagonal()
                if not np.isfinite(diag).all() or np.any(diag <= 0):
                    raise TectonicsError('mimetic heat system is not positively diagonally scaled')
                iterations = [0]
                def callback(_):
                    iterations[0] += 1
                    _cancel(cancel)
                inverse = LinearOperator(reduced.shape, matvec=lambda x: x/diag, dtype=float)
                # CG stops in the 2-norm; derive its internal tolerance from the
                # existing infinity-norm acceptance gate, not a fitted threshold.
                rhs_norm = float(np.linalg.norm(reduced_rhs))
                solver_rtol = (ALGEBRA*float(np.max(np.abs(reduced_rhs)))/rhs_norm if rhs_norm else ALGEBRA)
                answer, info = cg(reduced, reduced_rhs, M=inverse, rtol=solver_rtol, atol=0.,
                                  maxiter=max(200, 2*self._n), callback=callback)
                _cancel(cancel)
                residual = reduced@answer-reduced_rhs
                norm = max(float(np.max(np.abs(reduced_rhs), initial=0.)),
                           float(np.max(np.abs(reduced@answer), initial=0.)))
                relative = float(np.max(np.abs(residual), initial=0.))/norm if norm else 0.
                if info != 0 or not np.isfinite(answer).all() or relative > ALGEBRA:
                    raise TectonicsError('mimetic heat linear solve failed the existing relative heat gate')
                solution[free] = answer
                new = old+(capacity*solution[:self._nc]-initial)
            insulated = all(kind == 'power' and value == 0 for kind, value in boundary.values())
            faces_absolute = (precise['absolute_temperature'][self._nc:] if high_precision
                              else solution[self._nc:]+reference)
            experimental = self._positivity_method != 'refuse'
            correction_scope = insulated or (self._positivity_method in ('experimental-kss', 'experimental-bounded-kss')
                and all(kind == 'temperature' and value > 0 or kind == 'power' and value == 0
                        for kind, value in boundary.values()))
            invalid = np.any(new <= 0) or (experimental and correction_scope and np.any(faces_absolute <= 0))
            if experimental and invalid and np.isfinite(new).all() and np.isfinite(solution).all():
                from .integration_mimetic_precision import solve_monotone
                offsets = (precise['evidence']['solution_offset_decimal'] if high_precision
                           else list(map(str, solution)))
                precise = solve_monotone(self._geometry, self._conductivity, old, capacity,
                    dt, source, boundary, reference, offsets, budget=self._budget, cancel=cancel,
                    method={'experimental-kss': 'kss', 'experimental-bounded-kss': 'bounded-kss'}.get(
                        self._positivity_method, 'scheme2'))
                solution, new, raw = (precise[k] for k in ('solution', 'enthalpy', 'raw'))
                iterations = [precise['iterations']]
                relative, norm, rhs_norm = (precise[k] for k in ('linear_relative', 'rhs_max', 'rhs_norm'))
                arithmetic = precise['evidence']
                faces_absolute = precise['absolute_temperature'][self._nc:]
                if not np.isfinite(faces_absolute).all() or np.any(faces_absolute <= 0):
                    raise TectonicsError('nonlinear HMM face temperature lost positivity in output projection')
                factor_builds += arithmetic['nonlinear']['iterations']
                high_precision = True
            if not np.isfinite(new).all() or np.any(new <= 0):
                raise TectonicsError('mimetic heat would create nonpositive/nonfinite absolute enthalpy')
            # Assemble one oriented interface amount for both owners. Any
            # difference from the two solved local traces remains algebraic
            # residual, never additional heat or a changed temperature.
            if not high_precision:
                raw = [[] for _ in range(self._nf)]
                for ci, (indices, K, signs) in enumerate(self._local):
                    out = -dt*(K@solution[indices])[1:]
                    for fi, sign, amount in zip(self._geometry._cells[ci][2], signs, out):
                        raw[fi].append((ci, sign, float(amount)))
            return self._issue(old, new, capacity, source, boundary, dt, state_id, raw, faces_absolute,
                               iterations, relative, norm, rhs_norm, arithmetic, high_precision, factor_builds, cancel)


    def _prepare_extremum(self, conductivity):
        """Plan identity of the cell-centred method; no hybrid-mimetic matrix is built."""
        self._matrix, self._local, self._conductivity = None, (), conductivity
        self._decimal_required, self._extremum = False, None
        self._definition = dict(schema='atlas.mimetic-heat-plan.v1', geometry_id=self._geometry.geometry_id,
            conductivity_w_m_k=conductivity.tolist(), cells=self._nc, faces=self._nf,
            method='cell-centred extremum-preserving nonlinear finite volume; one transfer per face: two-point '
                   'part plus harmonic-limited two-sided remainder with certified nonnegative weights',
            time_method='backward Euler on current advected capacities',
            linear_method='bounded frozen-weight M-matrix steps and Newton trials; subtraction-free binary64 '
                          'elimination applied and refined in decimal80; no dense factor',
            linear_relative_tolerance=ALGEBRA, energy_relative_tolerance=ALGEBRA,
            arithmetic_policy='decimal80 for every advance',
            positivity_method=EXTREMUM,
            positivity_policy='explicit selection; with zero boundary power every cell and face temperature '
                              'stays within the range of the backward-Euler loads and prescribed temperatures; '
                              'an unconverged or out-of-range state is refused, never clipped',
            boundary='declared whole-domain thermal boundary; omitted faces explicitly insulated',
            geometric_accuracy='producer owns physical support and approximation bounds; metric identities alone do not certify it')
        self.plan_id = _hash(self._definition)
        self._stats = dict(advances=0, cg_iterations=0, matrix_builds=0, precision_fallback_advances=0,
                           precision_factor_builds=0, nonlinear_fallback_advances=0, stencil_builds=0,
                           stencil_seconds=0., solve_seconds=0.)
        self._verify()

    def _release_extremum(self):
        if getattr(self, '_extremum', None) is not None:
            self._extremum[2].__exit__(None, None, None)
            self._extremum = None

    def _advance_extremum(self, enthalpy_j, capacity_j_k, dt, state_id, source_w, boundary, cancel):
        """The same issued result and accounts, from the cell-centred discretisation."""
        from . import integration_extremum_heat as X
        with self._operation(cancel), self._budget.reserve(2*1024**2+1024*self._n, category='mimetic-heat-step'):
            def cells(value, label, positive=False):
                result = np.broadcast_to(np.asarray(value, dtype=float), (self._nc,)).copy()
                if not np.isfinite(result).all() or (positive and np.any(result <= 0)):
                    raise TectonicsError(label+' must be finite'+(' and positive' if positive else ''))
                return result
            old, capacity = cells(enthalpy_j, 'enthalpy', True), cells(capacity_j_k, 'capacity', True)
            source = cells(source_w, 'source power')
            boundary = {} if boundary is None else dict(boundary)
            reference = float(old[0]/capacity[0])
            ids = {name: i for i, name in enumerate(self._geometry._face_ids)}
            fixed = set()
            for name, entry in boundary.items():
                if name not in ids or len(self._geometry._incidence[ids[name]]) != 1:
                    raise TectonicsError('thermal boundary must name an actual one-owner face')
                if type(entry) not in (tuple, list) or len(entry) != 2:
                    raise TectonicsError('typed thermal boundary pair required')
                kind, value = entry
                value = scalar(value, 'thermal boundary value')
                if kind == 'temperature':
                    if value <= 0:
                        raise TectonicsError('absolute boundary temperature must be positive')
                    fixed.add(ids[name])
                elif kind != 'power':
                    raise TectonicsError('thermal boundary must declare temperature or outward power')
            fixed = frozenset(fixed)
            if self._extremum is None or self._extremum[0] != fixed:
                # Stencils depend on geometry, conductivity and WHICH faces hold a
                # temperature, never on a boundary value, capacity or duration.
                self._release_extremum()
                with self._budget.reserve(X.workspace_bytes(self._geometry), category='extremum-heat-stencil'):
                    prepared = X.prepare(self._geometry, self._conductivity, fixed, budget=self._budget, cancel=cancel)
                    lease = self._budget.reserve(prepared.bytes, category='extremum-heat-retained')
                    lease.__enter__()
                self._extremum = (fixed, prepared, lease)
                self._stats['stencil_builds'] += 1
                self._stats['stencil_seconds'] += prepared.seconds
            precise = X.solve(self._geometry, self._conductivity, old, capacity, dt, source, boundary, reference,
                              budget=self._budget, cancel=cancel, prepared=self._extremum[1])
            new = precise['enthalpy']
            if not np.isfinite(new).all() or np.any(new <= 0):
                raise TectonicsError('mimetic heat would create nonpositive/nonfinite absolute enthalpy')
            self._stats['solve_seconds'] += precise['statistics']['seconds']
            arithmetic = precise['evidence']
            return self._issue(old, new, capacity, source, boundary, dt, state_id, precise['raw'],
                               precise['absolute_temperature'][self._nc:], [precise['iterations']],
                               precise['linear_relative'], precise['rhs_max'], precise['rhs_norm'], arithmetic,
                               True, arithmetic['nonlinear']['eliminations'], cancel)

    def _issue(self, old, new, capacity, source, boundary, dt, state_id, raw, faces_absolute,
               iterations, relative, norm, rhs_norm, arithmetic, high_precision, factor_builds, cancel):
        """One oriented transfer per face, exact accounts and the issued result."""
        paired = np.zeros(self._nf); pairing_residual = np.zeros(self._nf)
        cell_out = np.zeros(self._nc)
        exact_cell_out = [Q(0)]*self._nc
        exact_face = []
        for fi, rows in enumerate(raw):
            paired[fi] = math.fsum(sign*amount for _, sign, amount in rows)/len(rows)
            pairing_residual[fi] = math.fsum(amount for _, _, amount in rows) if len(rows) == 2 else 0.
            amount = Q(float(paired[fi]))
            if len(rows) == 1:
                kind, value = boundary.get(self._geometry._face_ids[fi], ('power', 0.))
                if kind == 'power':
                    # A natural boundary specifies the physical transfer,
                    # including exact insulation. Its solved local trace
                    # differs by algebraic residual, not external heat.
                    # Retain dt*power exactly, even when its binary report
                    # cannot represent that product without rounding.
                    ci, sign, raw_amount = rows[0]
                    amount = sign*Q(dt)*Q(float(value))
                    paired[fi] = float(amount)
                    pairing_residual[fi] = float(Q(raw_amount)-sign*amount)
            exact_face.append(amount)
            for ci, sign, _ in rows:
                cell_out[ci] += sign*paired[fi]
                exact_cell_out[ci] += sign*amount
        boundary_energy = math.fsum(rows[0][1]*paired[i] for i, rows in enumerate(raw) if len(rows) == 1)
        change = math.fsum(float(b)-float(a) for a, b in zip(old, new))
        supplied = math.fsum(float(dt*q) for q in source)
        balance = change+boundary_energy-supplied
        scale = max(math.fsum(old), math.fsum(new), abs(boundary_energy), abs(supplied))
        if abs(balance)/scale > ALGEBRA:
            raise TectonicsError('mimetic heat energy residual exceeds the existing heat gate: '+
                json.dumps(dict(balance_j=balance, energy_scale_j=scale, relative=abs(balance)/scale,
                    linear_relative=relative, cg_iterations=iterations[0],
                    rhs_norm=rhs_norm, rhs_max=norm, boundary_energy_j=boundary_energy,
                    storage_change_j=change), sort_keys=True))
        # Sum the SAME represented face amount exactly on both owners.
        # Summing already-rounded cell totals would reintroduce unpaired
        # energy even though the face exchange itself is shared.
        exact_source = [Q(dt)*Q(float(s)) for s in source]
        exact_boundary = sum((rows[0][1]*exact_face[i] for i, rows in enumerate(raw)
                              if len(rows) == 1), Q(0))
        exact_cell = [Q(float(b))-Q(float(a))+j-s
                      for a, b, j, s in zip(old, new, exact_cell_out, exact_source)]
        metadata = dict(schema='atlas.mimetic-heat-advance.v1', plan_id=self.plan_id,
            geometry_id=self._geometry.geometry_id, state_id=state_id, duration_s=dt,
            boundary=boundary, cg_iterations=iterations[0], linear_relative_residual=relative,
            arithmetic=arithmetic,
            energy_balance_error_j=balance, energy_balance_relative_residual=abs(balance)/scale,
            exact_cell_storage_residual_j=list(map(_enc, exact_cell)),
            exact_source_energy_j=_enc(sum(exact_source, Q(0))),
            exact_outward_boundary_energy_j=_enc(exact_boundary),
            exact_paired_face_energy_j=list(map(_enc, exact_face)),
            source_energy_j=supplied, outward_boundary_energy_j=boundary_energy,
            accounting='one paired face amount; prescribed natural flux exact; storage/projection residual retained separately')
        snapshot = RegionalMechanicalSnapshot(metadata, dict(enthalpy_j=new, temperature_k=new/capacity,
            input_enthalpy_j=old, input_capacity_j_k=capacity, input_source_w=source,
            face_temperature_k=faces_absolute, paired_face_energy_j=paired,
            unpaired_local_flux_residual_j=pairing_residual, cell_outward_energy_j=cell_out))
        result = object.__new__(MimeticHeatResult)
        object.__setattr__(result, '_snapshot', snapshot)
        object.__setattr__(result, '_budget', self._budget)
        object.__setattr__(result, '_geometry', self._geometry)
        plan_definition = _json(self._definition)
        object.__setattr__(result, '_plan_definition', plan_definition)
        _retain(result, 8192+snapshot.nbytes+len(plan_definition), self._budget)
        self._verify(); _cancel(cancel)
        self._stats['advances'] += 1; self._stats['cg_iterations'] += iterations[0]
        if high_precision:
            self._stats['precision_fallback_advances'] += 1
            self._stats['precision_factor_builds'] += factor_builds
        if 'nonlinear' in arithmetic:
            self._stats['nonlinear_fallback_advances'] += 1
        return result

    def close(self):
        if self._active:
            raise TectonicsError('cannot close an active mimetic heat plan')
        if not self._closed:
            self._closed = True
            self._matrix, self._local = None, ()
            self._release_extremum()
            if self._guard is not None:
                self._guard.__exit__(None, None, None); self._guard = None

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
