"""I05.3 current properties returned through the I04/I05 port record (tectonics/docs/I04_I05_PORTS.md).

Both values come from one MovingState at one common endpoint (the state's own time), and are derived, never stored:

- P1 columns (``moving_columns``) on the trace support: at each plate-boundary edge midpoint, the face on that side
  must hold exactly one cohort piece (D-P2), else the point is refused ``unresolved column``; a column is never
  averaged. Layers, bottom to top, are the piece's sublayers: current thickness, the cohort's fixed reference density
  and expansivity, and its finite-volume mean temperature as both boundary temperatures (the piecewise-constant case of
  the I01_GPE linear representation, exactly consistent with the conserved heat). Thermal buoyancy enters only
  through the temperature; reference mass is never edited, and an inventory guard ties the column to the I03 mass.
- P2 strength state (``strength_port``) on a piece support (amendment of 4 October 2026): per piece and sublayer,
  thickness, temperature, the lithostatic vertical stress at the sublayer's bottom and top from the same I01_GPE
  representation and datum (dry, zero surface load; not the mean pressure), the declared pore pressure, material and
  creep law, and raw kappa on the same material-point support P6 uses. Only the zero-healing law is admitted.
- P3 rigidity is a declared input carried unchanged and re-checked against the P1 thicknesses (``carried_core``); it is
  never derived from thermal thickness.

SPDX-License-Identifier: AGPL-3.0-only
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import math

import numpy as np

from . import integration_driving as _driving
from . import integration_material as _material
from . import integration_ports as P
from . import integration_sphere as _sphere
from . import integration_state as _state
from . import integration_thermal as _thermal
from .materials import _json


PIECE_SUPPORT = 'atlas.i05-piece-support.v1'
STRENGTH_SCHEMA = 'atlas.i05-strength-state.v1'
HEALING_NONE = 'atlas.i04-healing-none.v1'
EPS = 2.**-52


def _faces_of_edges(network):
    """{(a, b): face} for every directed ring edge: the face on the left of a -> b (rings run counter-clockwise)."""
    owner = {}
    for face in network.faces:
        for ring in (face.vertex_ids,)+tuple(face.holes):
            for a, b in zip(ring, ring[1:]+ring[:1]):
                owner[(a, b)] = face.face_id
    return owner


def _endpoint(moving, sphere, header, port):
    """The common endpoint check: the header names this state at its own time and step, in its own frame."""
    _material.bound_moving(moving, sphere)
    network = sphere.network
    if type(header) is not P.Header or header.port != port:
        raise P.PortRefused('a %s header is required' % port, P.UNSUPPORTED)
    # I04.4 coupled route: the state is the interval's candidate endpoint; the header names the interval's parent state
    # S0 and binds this endpoint through its network_id and moving identity (checked below), not its state_id.
    coupled = (header.endpoint_s == header.interval[3] == network.time_s and header.interval[1] == network.step
               and header.interval[0] < header.interval[1])
    if not coupled and header.parent_state_id != sphere.state_id:
        raise P.PortRefused('the header names another parent state', P.STALE_IDENTITY, detail='parent_state_id')
    if header.network_id != network.network_id:
        raise P.PortRefused('the header names another network', P.STALE_IDENTITY, detail='network_id')
    if header.frame_id != network.sphere.frame_id:
        raise P.PortRefused('the header names another frame', P.STALE_IDENTITY, detail='frame_id')
    if header.parameter_id != moving.moving_id:
        raise P.PortRefused('the header names another moving state: P1 and P2 are issued with parameter_id the '
                            'moving_id they are computed from', P.STALE_IDENTITY, detail='parameter_id')
    start = header.endpoint_s == header.interval[2] == network.time_s and header.interval[0] == network.step
    # I04.4 coupled route: the state is the interval's endpoint, so its own time is the interval's end.
    end = (header.endpoint_s == header.interval[3] == network.time_s and header.interval[1] == network.step
           and header.interval[0] < header.interval[1])
    if not (start or end):
        raise P.PortRefused('properties are evaluated at the moving state\'s own time: the start of the interval, or '
                            'its end for the coupled route', P.UNSUPPORTED, detail=_driving.EVALUATION)


def _check_datum(header, datum, sphere):
    """The header's datum, and for cohorts that come from a starting family (their I03 origin is the family
    schema's) I04a's v1 family datum gate: rho_m and T_ref exactly 3300 kg/m3 and 293.15 K (review basal-04)."""
    if type(datum) is not _driving.Datum:
        raise P.PortRefused('the shared Datum is required', P.MISSING_VALUE, detail='datum')
    if header.datum_id != _driving.datum_id(datum):
        raise P.PortRefused('the header names another datum', P.STALE_IDENTITY, detail='datum_id')
    from . import integration_family as _family
    family = _family.SCHEMA+'#'
    if any(c.origin_id.startswith(family) for c in sphere.material.cohorts) and (
            datum.mantle_density_kg_m3 != _family.MANTLE_DATUM_KG_M3
            or datum.reference_temperature_k != _family.DATUM_REFERENCE_K):
        raise P.PortRefused('family cohorts exist only on the %r kg/m3 / %r K datum (v1)'
                            % (_family.MANTLE_DATUM_KG_M3, _family.DATUM_REFERENCE_K), P.STALE_IDENTITY,
                            detail='datum_id')


def _piece_column(moving, sphere, index):
    piece = sphere.material.pieces()[index]
    record = moving.cohort(piece.cohort_id)
    phases = sphere.material.phases
    thickness, _ = _thermal.column_of(record, piece, phases)
    temperature = _thermal.temperatures(record, piece, moving.heat_j(index).tolist(), moving.enthalpy_reference_k,
                                        phases)
    return piece, record, thickness, temperature


GUARD_I05_EPS = 3.5                  # the I05 side of the guard: 7 roundings of eps/2 (re-derivation, 4 October 2026)


def inventory_bound(intervals):
    """The relative inventory-guard bound after ``intervals`` steps since the moving state's declaration:
    (3.5 + (k + 1)) eps (basal-05 re-derivation, coordinator ruling (B) of 4 October 2026).

    I05 side, 3.5 eps independent of n: each row rounds V/A, /H (H itself an fsum, one rounding), x h0, x rho and
    x A, and the final fsum rounds once: 7 roundings of at most eps/2. I03 side: a piece's mass M and volume V are each
    rounded once per interval (at most eps/2 each), so M/V gains at most eps per interval, summed linearly over the
    k + 1 roundings including the declaration's. This corrects the approved 4(n+2) eps, which miscounted; it is a
    re-derivation, not a change after results.
    """
    if type(intervals) is not int or intervals < 0:
        raise P.PortRefused('the intervals since declaration are a whole nonnegative count', P.MISSING_VALUE,
                            detail='declared_step')
    return (GUARD_I05_EPS+(intervals+1))*EPS


def inventory_guard(record, piece, thickness, phases, intervals):
    """sum(rho_ref t) A per phase equals the I03 reference mass of the piece within inventory_bound(intervals)
    relative, ``intervals`` being the steps since the moving state's declaration. It refuses beyond the bound; a
    mismatch is never repaired by editing a density."""
    masses = dict(zip(phases, piece.mass_kg))
    bound = inventory_bound(intervals)
    for phase in {s.phase for s in record.sublayers}:
        rows = [s.reference_density_kg_m3*t*piece.area_m2 for s, t in zip(record.sublayers, thickness)
                if s.phase == phase]
        held = math.fsum(rows)
        if abs(held-masses[phase]) > bound*abs(masses[phase]):
            raise P.PortRefused('the column of piece (%r, %r) does not hold its I03 reference mass of %r'
                                % (piece.face_id, piece.cohort_id, phase), P.INCOMPATIBLE_SUPPORT,
                                detail='reference mass')


def moving_columns(moving, sphere, support, header, datum):
    """P1 columns from the moving state at its own time: single-cohort faces only, never averaged (D-P2)."""
    _endpoint(moving, sphere, header, 'P1')
    _check_datum(header, datum, sphere)
    network = sphere.network
    if type(support) is not P.TraceSupport or support.network_id != network.network_id:
        raise P.PortRefused('a trace support of this network is required', P.INCOMPATIBLE_SUPPORT, detail='support')
    if header.support_id != support.support_id:
        raise P.PortRefused('the header names another support', P.INCOMPATIBLE_SUPPORT, detail='support_id')
    owner = _faces_of_edges(network)
    pieces_of = {}
    for index, piece in enumerate(sphere.material.pieces()):
        pieces_of.setdefault(piece.face_id, []).append(index)
    plate_of = {face.face_id: face.plate_id for face in network.faces}
    edges = [pair for boundary in network.boundaries for pair in _pairs(boundary)]     # trace_support's order
    if len(edges) != support.edges:
        raise P.PortRefused("the trace support does not follow this network's boundaries", P.INCOMPATIBLE_SUPPORT,
                            detail='support')
    offsets, values, sources, representation = [0], [[] for _ in range(5)], [], []
    for e, (a, b) in enumerate(edges):
        for side, key in ((0, (a, b)), (1, (b, a))):
            face = owner.get(key)
            if face is None or plate_of[face] != support.plates[e][side]:
                raise P.PortRefused('no face of plate %r lies beside trace edge %d' % (support.plates[e][side], e),
                                    P.UNRESOLVED_COLUMN, detail='face')
            held = pieces_of[face]
            columns = [_piece_column(moving, sphere, index) for index in held]
            for piece, record, thickness, _ in columns:
                inventory_guard(record, piece, thickness, sphere.material.phases, moving.step-moving.declared_step)
            piece, record, thickness, temperature = columns[0]
            if len(columns) == 1:
                representation.append(None)
                sources.append(piece.cohort_id)
            else:
                temperature = _cell_mean(moving, face, held, columns, 2*e+side)
                cohorts = tuple(sorted(c[0].cohort_id for c in columns))
                representation.append((CELL_MEAN, cohorts))
                sources.append(CELL_MEAN)
            for s, t, T in reversed(list(zip(record.sublayers, thickness, temperature))):
                for column, value in zip(values, (t, s.reference_density_kg_m3, s.alpha_per_k, T, T)):
                    column.append(value)
            offsets.append(len(values[0]))
    mixed = tuple(representation) if any(entry is not None for entry in representation) else None
    return P.columns_port(header, offsets, *values, sources=tuple(sources), representation=mixed)


CELL_MEAN = 'fv-cell-mean'


def _structure(record, thickness):
    """What must be bitwise equal for pieces to share one column: per sublayer the material, phase, reference density,
    expansivity and heat capacity, the tuple of sublayer thicknesses (so the emitted thicknesses are every piece's,
    P1-NOTE-1) and the tuple of sublayer depths."""
    return (tuple((s.material_id, s.phase, s.reference_density_kg_m3, s.alpha_per_k, s.heat_capacity_j_kg_k)
                  for s in record.sublayers), tuple(float(t) for t in thickness), tuple(np.cumsum(thickness).tolist()))


def _cell_mean(moving, face, held, columns, point):
    """The P1 fv-cell-mean column of a face holding several pieces (amendment of 4 October 2026).

    Admitted only when every piece has a bitwise-equal layer structure (_structure); otherwise the point refuses
    ``unresolved column`` (D-P2). Per sublayer the temperature is the caloric inverse of the exact mean specific
    enthalpy sum(H_i)/sum(rho t A_i), formed in rationals from the stored heat and rounded once: the enthalpy-consistent
    first-order finite-volume cell average, so pieces of equal temperature give exactly their own column. Histories
    and kappa are not touched (P2 and P6 stay per piece).
    """
    first = _structure(columns[0][1], columns[0][2])
    if any(_structure(record, thickness) != first for _, record, thickness, _ in columns[1:]):
        raise P.PortRefused('face %r beside trace point %d holds %d cohort pieces of different layer structure; '
                            'columns of different structure are never averaged (D-P2)' % (face, point, len(columns)),
                            P.UNRESOLVED_COLUMN, detail=face)
    record, reference = columns[0][1], moving.enthalpy_reference_k
    stored = [moving.heat_j(index) for index in held]
    out = []
    for l, s in enumerate(record.sublayers):
        heat = sum((Fraction(float(column[l])) for column in stored), Fraction(0))
        mass = sum((Fraction(s.reference_density_kg_m3*thickness[l]*piece.area_m2) for piece, _, thickness, _
                    in columns), Fraction(0))
        out.append(s.temperature(float(heat/mass), reference))
    return out


def _pairs(boundary):
    chain = list(boundary.vertex_ids)
    return list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])


def piece_support_id(sphere):
    """The P2 piece support: the ordered (face, cohort) pieces of one I03 state, bound to its network."""
    record = dict(schema=PIECE_SUPPORT, network_id=sphere.network.network_id,
                  material_id=sphere.material.material_id,
                  pieces=[[p.face_id, p.cohort_id] for p in sphere.material.pieces()])
    return hashlib.sha256(_json(record)).hexdigest()


@dataclass(frozen=True, init=False, eq=False, slots=True)
class StrengthState(_state._Immutable):
    """P2: per piece, its sublayers bottom to top (offsets as in P1), with the declared and transported inputs of
    strength. Values are owned, frozen copies; ``port_id`` is their identity."""
    header: P.Header
    pieces: tuple
    healing_law_id: str
    offsets: np.ndarray = field(repr=False)
    thickness_m: np.ndarray = field(repr=False)
    temperature_k: np.ndarray = field(repr=False)
    vertical_stress_bottom_pa: np.ndarray = field(repr=False)
    vertical_stress_top_pa: np.ndarray = field(repr=False)
    pore_pressure_pa: np.ndarray = field(repr=False)
    kappa: np.ndarray = field(repr=False)
    material_ids: tuple
    creep_law_ids: tuple
    port_id: str

    def __init__(self, *args, **kwargs):
        raise TypeError('StrengthState is issued by strength_port()')


def strength_port(moving, sphere, header, datum, *, healing_law_id):
    """P2 strength state of every piece at the moving state's own time, on the piece support.

    The vertical stress is integrated exactly down each column from zero at its top surface, with each sublayer's
    effective density rho_ref (1 - alpha (T - T_ref,datum)) and the datum's gravity: the same I01_GPE representation
    and datum as P1, so each column must pass P1's inventory guard. It is the lithostatic vertical stress, not a mean
    pressure. A missing pore pressure or creep law refuses ``missing value``; a healing law other than the
    zero-healing selection refuses ``unsupported``.
    """
    _endpoint(moving, sphere, header, 'P2')
    _check_datum(header, datum, sphere)
    if healing_law_id is None:
        raise P.PortRefused('the healing law is declared', P.MISSING_VALUE, detail='healing_law_id')
    if healing_law_id != HEALING_NONE:
        raise P.PortRefused('only the zero-healing law %r is admitted' % HEALING_NONE, P.UNSUPPORTED,
                            detail='healing_law_id')
    if header.support_id != piece_support_id(sphere):
        raise P.PortRefused('the header names another piece support', P.INCOMPATIBLE_SUPPORT, detail='support_id')
    g, t_ref = datum.gravity_m_s2, datum.reference_temperature_k
    offsets, rows, materials, creeps = [0], [[] for _ in range(6)], [], []
    for index in range(len(sphere.material.pieces())):
        piece, record, thickness, temperature = _piece_column(moving, sphere, index)
        inventory_guard(record, piece, thickness, sphere.material.phases, moving.step-moving.declared_step)
        stress = [0.]
        for s, t, T in zip(record.sublayers, thickness, temperature):
            effective = s.reference_density_kg_m3*(1-s.alpha_per_k*(T-t_ref))
            stress.append(stress[-1]+g*effective*t)
        layers = list(zip(record.sublayers, thickness, temperature, stress[:-1], stress[1:], record.kappa))
        for s, t, T, top, bottom, kappa in reversed(layers):
            if s.pore_pressure_pa is None:
                raise P.PortRefused('piece (%r, %r) declares no pore pressure' % (piece.face_id, piece.cohort_id),
                                    P.MISSING_VALUE, detail='pore_pressure_pa')
            if s.creep_law_id is None:
                raise P.PortRefused('piece (%r, %r) declares no creep law' % (piece.face_id, piece.cohort_id),
                                    P.MISSING_VALUE, detail='creep_law_id')
            for column, value in zip(rows, (t, T, bottom, top, s.pore_pressure_pa, kappa)):
                column.append(value)
            materials.append(s.material_id)
            creeps.append(s.creep_law_id)
        offsets.append(len(rows[0]))
    arrays = [_sphere._frozen(np.asarray(column, dtype=np.float64), np.float64) for column in rows]
    if not all(np.isfinite(a).all() for a in arrays):
        raise P.PortRefused('a strength value is not finite', P.MISSING_VALUE, detail='values')
    offsets = _sphere._frozen(np.asarray(offsets, dtype=np.int64), np.int64)
    pieces = tuple((p.face_id, p.cohort_id) for p in sphere.material.pieces())
    record = dict(schema=STRENGTH_SCHEMA, header=header.record(), pieces=[list(p) for p in pieces],
                  healing_law_id=healing_law_id, materials=materials, creep_laws=creeps)
    port_id = P._digest(record, (('offsets', offsets),)+tuple(zip(('thickness_m', 'temperature_k',
                                                                   'vertical_stress_bottom_pa',
                                                                   'vertical_stress_top_pa', 'pore_pressure_pa',
                                                                   'kappa'), arrays)))
    return _state._issue(StrengthState, header=header, pieces=pieces, healing_law_id=healing_law_id, offsets=offsets,
                         thickness_m=arrays[0], temperature_k=arrays[1], vertical_stress_bottom_pa=arrays[2],
                         vertical_stress_top_pa=arrays[3], pore_pressure_pa=arrays[4], kappa=arrays[5],
                         material_ids=tuple(materials), creep_law_ids=tuple(creeps), port_id=port_id)


CORE_FIELDS = ('material', 'basis', 'depth_reference', 'top_depth_m', 'bottom_depth_m', 'young_pa', 'poisson')
INVALID_CORE = 'REFUSED_INVALID_CORE'
UNPLACED = 'REFUSED_CORE_PLACEMENT_ABSENT'
UNSUPPORTED_CORE = 'REFUSED_UNSUPPORTED_CORE'
OUTSIDE_ROCK = 'REFUSED_CORE_OUTSIDE_ROCK'


def _core_refused(code, message):
    return P.PortRefused(message, P.UNSUPPORTED, detail=code)


def _core_real(value, name):
    """A finite real scalar (package reproduction of tools/check_i01_elastic_core.py ``_real``)."""
    if value is None or isinstance(value, (bool, np.bool_, str, bytes, complex, np.complexfloating)):
        raise _core_refused(INVALID_CORE, name+' must be a real scalar')
    try:
        varies = np.ndim(value) != 0
    except ValueError:
        varies = True
    if varies:
        raise _core_refused(UNSUPPORTED_CORE, name+' varies: horizontally varying, layered or multiple cores are '
                            'not this branch')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _core_refused(INVALID_CORE, name+' must be a real scalar') from None
    if not math.isfinite(value):
        raise _core_refused(INVALID_CORE, name+' must be finite')
    return value


def _checked_core(core):
    """The I01_ELASTIC_CORE section 6 declaration checks in that section's order (package reproduction of the tool's
    ``elastic_core`` and ``ElasticCore``; the tool stays unchanged and is imported only by the parity test)."""
    if isinstance(core, (list, tuple)):
        raise _core_refused(UNSUPPORTED_CORE, 'one core per declaration: multiple cores are not this branch')
    if not isinstance(core, Mapping):
        raise _core_refused(INVALID_CORE, 'an elastic-core declaration is required')
    keys = set(core)
    if keys & {'layers', 'cores'}:
        raise _core_refused(UNSUPPORTED_CORE, 'layered or multiple cores are not this branch')
    if not {'top_depth_m', 'bottom_depth_m'} <= keys:
        raise _core_refused(UNPLACED, 'a core declares its top and bottom depths; D or Te alone cannot locate it')
    if keys != set(CORE_FIELDS):
        raise _core_refused(INVALID_CORE, 'a core declares exactly '+', '.join(CORE_FIELDS)+'; its D, Te and c are '
                            'derived')
    if core['top_depth_m'] is None or core['bottom_depth_m'] is None:
        raise _core_refused(UNPLACED, 'a core declares its top and bottom depths; D or Te alone cannot locate it')
    for name in ('material', 'basis'):
        if type(core[name]) is not str or not core[name].strip():
            raise _core_refused(INVALID_CORE, 'a nonempty '+name+' text is required')
    if type(core['depth_reference']) is not str or core['depth_reference'] != 'rock_surface':
        raise _core_refused(INVALID_CORE, "core depths are measured below each column's rock surface: 'rock_surface'")
    top, bottom, young, poisson = (_core_real(core[name], name)
                                   for name in ('top_depth_m', 'bottom_depth_m', 'young_pa', 'poisson'))
    if top < 0:
        raise _core_refused(OUTSIDE_ROCK, 'the core top lies above the rock surface')
    if not top < bottom:
        raise _core_refused(INVALID_CORE, 'the core needs top < bottom: a positive thickness')
    if not young > 0:
        raise _core_refused(INVALID_CORE, "Young's modulus must be positive")
    if not -1 < poisson < .5:
        raise _core_refused(INVALID_CORE, "Poisson's ratio must lie in the isotropic elastic range (-1, 1/2)")
    try:
        rigidity = young*(bottom-top)**3/(12*(1-poisson**2))
        representable = 0 < rigidity < math.inf and math.isfinite(.5*(top+bottom))
    except OverflowError:
        representable = False
    if not representable:
        raise _core_refused(INVALID_CORE, 'core rigidity or transfer depth is not representable')
    return bottom


def carried_core(core, columns):
    """P3: the declared elastic core, carried unchanged after the I01_ELASTIC_CORE section 6 declaration checks in
    that section's order; its base must then lie within the rock of every P1 column (b <= min H).

    Te, D and c are never accepted, and nothing is derived from thermal thickness or isotherms.
    """
    bottom = _checked_core(core)
    if type(columns) is not P.Columns:
        raise P.PortRefused('P1 columns are required', P.UNSUPPORTED, detail='columns')
    thinnest = min(math.fsum(columns.layers(i)[0]) for i in range(columns.points))
    if not bottom <= thinnest:
        raise _core_refused(OUTSIDE_ROCK, 'the core base lies below the rock of a column')
    return dict(core)
