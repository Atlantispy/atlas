"""Plan40B explicit new public source binding; historical receipts are unchanged.

Owned startup preparation from an issued metric; no reconstruction admission.

The immutable metric and caller boundary are already owned. A scalar-only JSON
token scan bounds the simultaneous decode text, objects and parser containers;
the LOW inventory follows its actual per-face rational expressions. Admission
precedes record decoding and LOW extraction. Work is deliberately retained with
the output, without credit for aliases or early release.

The 1024-byte container unit and GMP workspace/recycled-slot conventions are
accounting policies, NOT allocator, scratch or RSS proofs. No polygon moment,
support selection, MPFR certificate, exact fallback or retained HIGH row is
admitted here. Imports/runtime and supplied metric ownership remain external.
This is a useful stage, not a whole-method resource certificate or native port.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import math
from pathlib import Path
import sys

import private_heat_low_geometry_kernel_r1 as LOW
import heat_payload_indexed_patch as INDEXED_PAYLOAD
import private_heat_low_ledger_inventory_r1 as L
import private_heat_decimal_sparse_core_r1 as P
from atlas_tectonics import integration_mimetic_heat as HEAT

HERE = Path(__file__).resolve().parent
_PINS = {
    'private_heat_low_geometry_kernel_r1.py': '4f74ffeb8a2b581d69c143ad11e67d7fa2d29d86e9ad01eec2f19452eeabffab',
    'private_heat_low_ledger_inventory_r1.py': '810a2b565515012e7ea68fd953ac495dede2d3d881dfe1a96788217fbf213695',
    'private_heat_gmp_resources_r1.py': '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca',
    'private_heat_interval_inventory_r1.py': '6ee4bf826a84efb236abd7fd42dfc4960ec0b1fc040bcbb59d0183a2d4428623',
    'private_heat_decimal_inventory_r1.py': '06a3ce93e139328913d09893ab7aa376f1104ee17de14f8740bf40c97b97cd02',
    str(Path(HEAT.__file__).resolve()): '7d020e15e49f686c64363b65956122fd1bfaa2cf4d512ca23729178b9574cb92',
}
UNIT = L.CONTAINER_UNIT


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Heat startup inventory cancelled')


def _size(count):
    if type(count) is not int or not 0 <= count <= sys.maxsize:
        raise OverflowError('Startup accounting exceeds addressable storage')
    return count


@dataclass(frozen=True)
class PreparationPlan:
    metadata_bytes: int
    components: tuple
    counts: tuple
    conductance_shapes: tuple
    geometry_id: str
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    reconstruction_admitted: bool = False
    whole_method_admission: bool = False

    @property
    def total_bytes(self):
        return _size(self.metadata_bytes+sum(value for _, value in self.components))


def json_decode_inventory(encoded, *, cancel=None):
    """Scan native canonical ASCII JSON without decoding/copying any token.

    This is sizing, not a replacement JSON validator. Only call on an issued
    metric's canonical encoding. Escaped string bytes overbound decoded code
    points. Four bytes/code point cover non-BMP Unicode; four bits/number byte
    cover integer payload. Units count values, container entries, parser/memo
    tables and active nesting. json.loads remains the original semantic reader.
    Caller owns the small scalar scan frame before this function is entered.
    """
    if type(encoded) is not bytes:
        raise TypeError('Issued canonical bytes required')
    strings = atoms = containers = entries = depth = deepest = 0
    string_bytes = number_bytes = 0
    quoted = escaped = atom = False
    for offset, byte in enumerate(encoded):
        if offset % 4096 == 0:
            _check(cancel)
        if byte > 127:
            raise ValueError('Issued ensure_ascii JSON required')
        if quoted:
            if escaped:
                escaped = False
                string_bytes += 1
            elif byte == 92:
                escaped = True
                string_bytes += 1
            elif byte == 34:
                quoted = False
            else:
                string_bytes += 1
        elif byte == 34:
            strings += 1
            quoted, atom = True, False
        elif byte in (91, 123):
            containers += 1
            depth += 1
            deepest = max(deepest, depth)
            atom = False
        elif byte in (93, 125):
            depth -= 1
            atom = False
        elif byte in (44, 58):
            entries += 1
            atom = False
        elif byte in (9, 10, 13, 32):
            atom = False
        else:
            if not atom:
                atoms += 1
                atom = True
            number_bytes += 1  # booleans/null overcharged as integer tokens
    _check(cancel)
    if quoted or escaped or depth:
        raise ValueError('Incomplete issued JSON')
    units = strings+atoms+containers+entries+deepest+1
    # Full decode text plus possible parser text copies; string payload, numeric
    # payload, objects/tables. No assumption of key interning or alias reuse.
    return _size(UNIT*units+8*len(encoded)+4*string_bytes+4*number_bytes), (
        ('json_strings', strings), ('json_atoms', atoms), ('json_containers', containers),
        ('json_entries', entries), ('json_depth', deepest), ('json_bytes', len(encoded)))


def _verify_sources(cancel):
    L.D._runtime(cancel)
    for name, expected in _PINS.items():
        digest = sha256()
        with (HERE/name).open('rb') as stream:
            while block := stream.read(65536):
                _check(cancel)
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError('Reviewed startup dependency changed: '+name)


def _derive(geometry, conductivity, boundary, metadata_bytes, R, G, cancel):
    ar = L.RationalGrowth(G, R, cancel)
    n, nf = len(geometry._cells), len(geometry._incidence)
    if type(conductivity) not in (int, float, Fraction):
        raise TypeError('Uniform represented int, float or Fraction conductivity required')
    # Same binary64 projection as the existing uniform forward kernel and LOW.
    k = float(conductivity)
    if not math.isfinite(k) or k <= 0:
        raise ValueError('Positive finite uniform conductivity required')
    ks = ar.q(k)
    if type(boundary) is not dict:
        raise TypeError('Owned plain boundary dictionary required')
    exposed = 0
    shapes = []
    rational_slots = n*ar.slot(ks)
    boundary_slots = 0
    for fi, (fid, linked) in enumerate(zip(geometry._face_ids, geometry._incidence, strict=True)):
        _check(cancel)
        i, _ = linked[0]
        first = geometry._cells[i]
        slot = first[2].index(fi)
        ns = [ar.q(value) for value in first[5][slot]]
        area = ar.total(ar.op('multiply', value, value) for value in ns)
        ds = [ar.q(geometry._cells[owner][6][geometry._cells[owner][2].index(fi)]) for owner, _ in linked]
        if len(linked) == 2:
            den = ar.total(ar.op('divide', value, ks) for value in ds)
            conductance = ar.op('divide', area, den)
        else:
            exposed += 1
            kind, value = boundary.get(fid, ('power', 0.))
            if kind not in ('temperature', 'power'):
                raise ValueError('Only temperature or outward power supported')
            value = float(value)
            if not math.isfinite(value):
                raise ValueError('Finite represented boundary value required')
            boundary_slots += ar.slot(ar.q(value))
            conductance = (ar.op('divide', ar.op('multiply', ks, area), ds[0])
                           if kind == 'temperature' else L.ZERO)
        shapes.append((conductance.numerator, conductance.denominator))
        # Retain Python conductance, two GMP weights even for singleton power,
        # negation/sign copies and already-owned distance aliases, all charged.
        rational_slots += 5*ar.slot(conductance)+sum(ar.slot(value) for value in ds)
    if any(key not in geometry._face_ids or len(geometry._incidence[geometry._face_ids.index(key)]) != 1
           for key in boundary):
        raise ValueError('Boundary must name actual exterior faces')
    if INDEXED_PAYLOAD.is_indexed(geometry):
        decode_bytes, json_counts = INDEXED_PAYLOAD.indexed_inventory(geometry, cancel=cancel)
    else:
        decode_bytes, json_counts = json_decode_inventory(geometry._encoded, cancel=cancel)
    components = (('record_decode_text_objects_parser', decode_bytes),
        ('low_containers_and_retained_identifiers', UNIT*(4*n+28*nf+8*exposed+16)),
        ('low_rational_generations', rational_slots+boundary_slots),
        ('low_scalar_expression_workspace', ar.scalar_work()))
    plan = PreparationPlan(metadata_bytes, components,
        (('cells', n), ('faces', nf), ('exterior_faces', exposed), *json_counts),
        tuple(shapes), geometry.geometry_id)
    plan.total_bytes
    return plan


class OwnedPreparation(P.OwnedSolve):
    def __init__(self, value, workspace, geometry):
        super().__init__(value, workspace)
        self._geometry = geometry

    def close(self):
        super().close()
        self._geometry = None


def admit(geometry, conductivity, boundary, *, budget, cancel=None):
    """Return an owned prospective plan; no payload decode/LOW output yet."""
    _check(cancel)
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
    from atlas_tectonics import exact_arithmetic
    import private_heat_gmp_resources_r1 as R
    if type(geometry) is not MimeticGeometry or geometry._budget is not budget:
        raise TypeError('Issued immutable geometry with identical caller budget required')
    G = exact_arithmetic.library()
    if G is None:
        raise RuntimeError('Selected GMP backend required')
    # No rational getters/arrays before the metadata lease. Native metric uses
    # Fraction; its integer getters borrow immutable already-owned ints.
    largest = 2048
    if type(conductivity) not in (int, float, Fraction) or type(boundary) is not dict:
        raise TypeError('Plain uniform represented conductivity and owned boundary required')
    def inspect_scalar(value):
        nonlocal largest
        if type(value) not in (int, float, Fraction):
            raise TypeError('Plain represented int, float or Fraction scalar required')
        if type(value) is Fraction:
            largest = max(largest, sys.getsizeof(value.numerator), sys.getsizeof(value.denominator))
        else:
            largest = max(largest, sys.getsizeof(value))
    inspect_scalar(conductivity)
    for key, entry in boundary.items():
        _check(cancel)
        if type(key) is not str or type(entry) not in (list, tuple) or len(entry) != 2:
            raise TypeError('Plain physical boundary key and two-part declaration required')
        inspect_scalar(entry[1])
    for cell in geometry._cells:
        _check(cancel)
        for vector in cell[5]:
            for value in vector:
                largest = max(largest, sys.getsizeof(value.numerator), sys.getsizeof(value.denominator))
        for value in cell[6]:
            largest = max(largest, sys.getsizeof(value.numerator), sys.getsizeof(value.denominator))
    metadata_bytes = _size(262144+UNIT*(len(geometry._cells)+4*len(geometry._incidence)+1)
        +R.native_workspace_allowance(8*largest, 32))
    work = R.OwnedWorkspace(budget, metadata_bytes, category='heat-startup-inventory', cancelled=cancel)
    work.__enter__()
    try:
        _verify_sources(cancel)
        plan = _derive(geometry, conductivity, boundary, metadata_bytes, R, G, cancel)
        return OwnedPreparation(plan, work, geometry)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def prepare(geometry, conductivity, boundary, *, budget, cancel=None):
    """Return owner of {'prepared', 'payload', 'inventory'}; borrow while live.

    Startup order/numbers are unchanged: LOW extraction then geometry.record().
    No mathematical or numerical reconstruction work is called by this stage.
    """
    owner = admit(geometry, conductivity, boundary, budget=budget, cancel=cancel)
    work = owner._workspace
    try:
        plan = owner.value
        work.resize_before_allocation_or_after_drop(plan.total_bytes)
        _check(cancel)
        prepared = LOW.prepare_geometry(geometry, conductivity, boundary, cancel=cancel)
        _check(cancel)
        if INDEXED_PAYLOAD.is_indexed(geometry):
            payload_owner = work.stack.enter_context(INDEXED_PAYLOAD.materialise(geometry, budget=budget, cancel=cancel))
            payload = payload_owner.value
        else:
            payload = geometry.record()
        _check(cancel)
        owner._value = dict(prepared=prepared, payload=payload, inventory=plan)
        return owner
    except BaseException:
        owner._workspace = None
        owner._value = None
        work.__exit__(*sys.exc_info())
        raise
