"""I04.4 the first property/motion feedback: D1 and the D2 belts against I05 endpoint properties. WORKING NON-CANON.

Route ``d1d2_endpoint_fixed_point_v1`` (tectonics/docs/I04_CAUSAL_START.md, R4-7; coordinator rulings of 4 October
2026 and their round-1 verification). One interval is implicit at its endpoint (backward Euler, first order in time):

1. a predictor solves D1 with the belts at the parent state S0, warm-started from the parent interval's committed
   omega (or, for the first interval, from the belt-free balance at S0);
2. iterate k advances I03 and I05 from S0 with omega^k (rotations only from a P5 value, through the bound helper) and
   the raw-history increments dkappa^k (I05's two-pass split flow, sub-cohorts named by a pure function of cohort,
   increment and interval), giving the candidate endpoint E^k;
3. P1 and P2 are evaluated at E^k (headers name S0; E^k is bound by its network and moving identities) and D1 with
   the belts is solved there by exact-tangent Newton, warm-started from omega^k, giving omega^(k+1) and, from the
   same integration, dkappa^(k+1) = dt 2 e_p(E^k) (P6) and the energies (P7);
4. the interval converges when the relative changes of omega and dkappa (on pass-1 keys) fall to OUTER_RELATIVE;
   it refuses after OUTER_ITERATIONS, or when the change grows in two consecutive iterates after the second. Nothing
   is committed on refusal: no rock ages and no account is spent.

The result is the interval's Motion and MovingAdvance for an ordinary I02 commit. The advance carries the I04
``driving`` record, the interval's only D1/D2 provenance. Inheritance (the warm start, the labels, the cumulative belt
strain and the heat-omission bound) comes only from the parent interval's own record: a CoupledInterval of this
process, or a Verified record of the parent commit. On a ledger, ``step`` reads and replays the head's record itself
and ``commit`` binds the interval and the inheritance before committing; I05 binds the record's parent, endpoint,
motion and interval at every commit (``integration_material._bound_driving``). ``verify_driving`` replays a committed
record by solving the whole interval again from its verified parent and comparing every field bit for bit; a record
that is only found is never called provenance. P9 is the boundary reaction for I07/I09.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, fields
from functools import partial
import hashlib
import json
import math
import weakref

import numpy as np

from . import integration_clock as K
from . import integration_driving as D
from . import integration_material as M
from . import integration_ports as P
from . import integration_properties as R
from . import integration_strength as G
from . import integration_transfer as T
from ._validation import TectonicsError
from .materials import _json
from .timebase import advance_time

SCHEMA = 'atlas.i04-driving-provenance.v1'
ROUTE = 'd1d2_endpoint_fixed_point_v1'
OUTER_RELATIVE = 1e-8          # regional_strength.solve_regional_strength's relative Picard criterion
OUTER_ITERATIONS = 40          # and its iteration cap
PRODUCER = 'atlas_tectonics.integration_feedback'
REPLAYED = 'D1 provenance (replayed)'
PRODUCED = 'D1 provenance (produced and committed in this process)'
RECORDED = 'recorded, not replayed'

MISSING = 'missing value'
STALE = 'stale identity'
UNSUPPORTED = 'unsupported'
NONCONVERGED = 'nonconverged coupling'
UNRESOLVED_SUPPORT = 'unresolved endpoint support'
CODES = (MISSING, STALE, UNSUPPORTED, NONCONVERGED, UNRESOLVED_SUPPORT)
TEMPLATE_FIELDS = ('supplies', 'sinks', 'mesh')       # advance_from_motion
COUPLED_TEMPLATE_FIELDS = ('supplies', 'sinks')         # the coupled route (a mesh is not replayable in v1)
REFUSED_TEMPLATE = {
    'rotations': 'rotations come only from P5',
    'events': 'supplied Split, Merge and RidgeJump events are UR-02 prescribed transitions, refused in the D1/D2 route',
    'regional_returns': 'regional returns are not part of the D1/D2 route in v1',
    'junction_paths': 'junction paths are prescribed junction kinematics, refused in the D1/D2 route',
    'history_splits': 'splits come only from I05 split_for_increments on each iterate, never from the caller',
}
# Documented non-admissions (no code path proposes these; the template refusal above is the behavioural check).
EVENT_REFUSALS = dict(G.EVENT_REFUSALS, **{
    'ridge_jump': 'refused: a ridge jump needs an admitted law (UR-02 prescribed only)',
    'polarity_reversal': 'refused: subduction polarity reversal needs an admitted law (I07)',
    'slab_breakoff': 'refused: slab breakoff needs an admitted law (I07)',
    'collision': 'refused: continental arrival and collision need an admitted law (CM-12, I07)',
})


class FeedbackRefused(TectonicsError):
    """A coupled interval that cannot be formed, did not converge or does not replay; nothing was committed."""

    def __init__(self, message, code, detail=None):
        if code not in CODES:
            raise ValueError('unknown feedback refusal code %r' % code)
        super().__init__(message)
        self.code, self.detail = code, detail


# ---------------------------------------------------------------------------------------------------------------
# The P5 -> I03 binding (port record section 4; ruling P2).

def _bound(state, motion, end_time_s):
    if type(motion) is not P.PlateMotion:
        raise FeedbackRefused('a P5 PlateMotion is required', MISSING, 'motion')
    interval = motion.header.interval
    network = state.network
    checks = (('parent_state_id', state.state_id == motion.header.parent_state_id),
              ('interval', network.step == interval[0] and network.time_s == interval[2]),
              ('end_time_s', end_time_s == interval[3]),
              ('frame_id', motion.frame_id == network.sphere.frame_id),
              ('plate_ids', motion.plate_ids == network.plate_ids),
              ('network_id', motion.header.network_id == network.network_id),
              ('support_id', motion.header.support_id == P.plate_support_id(network.network_id, network.plate_ids)))
    for name, ok in checks:
        if not ok:
            raise FeedbackRefused('the P5 value is not bound to this state and interval (%s)' % name, STALE, name)
    return interval


def _template(template, admitted):
    template = dict(template or {})
    for name in sorted(template):
        if name in REFUSED_TEMPLATE:
            raise FeedbackRefused('the template supplies %s: %s' % (name, REFUSED_TEMPLATE[name]), UNSUPPORTED, name)
        if name not in admitted:
            raise FeedbackRefused('the template field %r is not admitted here' % name, UNSUPPORTED, name)
    return template


def advance_from_motion(state, motion, template=None, *, end_time_s, **options):
    """Advance I03 from a P5 value: the state must be P5's parent, at P5's start step and time, in its frame, with its
    plates, network and per-plate support, advanced to P5's end time. ``template`` holds only supplies, sinks and a
    mesh; rotations, events, regional returns, junction paths and history splits each refuse by name."""
    interval = _bound(state, motion, end_time_s)
    template = _template(template, TEMPLATE_FIELDS)
    return T.advance(state, T.Motion(interval[0], interval[1], D.stage_rotations(motion), **template),
                     end_time_s=end_time_s, **options)


def _advance_split(state, motion, template, splits, end_time_s):
    """The bound advance with I05's own history splits (private: splits never come from a caller)."""
    interval = _bound(state, motion, end_time_s)
    return T.advance(state, T.Motion(interval[0], interval[1], D.stage_rotations(motion), history_splits=splits,
                                     **dict(template)), end_time_s=end_time_s)


# ---------------------------------------------------------------------------------------------------------------
# Inputs, headers and the coupled P5.

@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything one coupled interval declares: the D1 forcing, the D2 declaration, the shared datum, the I03 template
    (supplies and sinks) and the I05 births and conduction."""
    forcing: object
    declaration: object
    datum: object
    template: tuple = ()
    births: tuple = ()
    conduction: object = None
    water_regime: object = None
    water_density_kg_m3: object = None

    def __post_init__(self):
        if type(self.forcing) is not D.Forcing:
            raise FeedbackRefused('a D1 Forcing is required', MISSING, 'forcing')
        if type(self.declaration) is not G.Declaration:
            raise FeedbackRefused('a D2 Declaration is required', MISSING, 'declaration')
        if set(self.forcing.belts) != set(dict(self.declaration.belts)):
            raise FeedbackRefused('the forcing\'s belts and the D2 declaration\'s belts differ', STALE, 'belts')
        if type(self.datum) is not D.Datum:
            raise FeedbackRefused('the shared Datum is required', MISSING, 'datum')
        if type(self.template) is not tuple or any(type(p) is not tuple or len(p) != 2 for p in self.template):
            raise FeedbackRefused('the template is (field, value) pairs', UNSUPPORTED, 'template')
        _template(dict(self.template), COUPLED_TEMPLATE_FIELDS)

    @property
    def parameter_id(self):
        """The coupled P5's model identity: the forcing and the D2 declaration (ruling P6)."""
        return hashlib.sha256(_json([self.forcing.forcing_id, self.declaration.declaration_id])).hexdigest()


def _header(port, parent, state, interval, endpoint_s, support_id, datum, parameter_id):
    network = state.network
    return P.Header(port, parent, interval, endpoint_s, network.network_id, support_id,
                    None if datum is None else D.datum_id(datum), parameter_id, network.sphere.frame_id,
                    'I04 (feedback)', PRODUCER)


def _motion_port(sphere, inputs, interval, omega, balance_id, residual):
    """A coupled P5 (ruling P6): parent S0, S0's network and per-plate support, the commit interval, endpoint at the
    interval's end; value omega with the endpoint balance and its fixed-point residual. Private: the outer loop issues
    trial values (residual None) to advance its iterates, and _finish issues the committed value from a converged
    interval only."""
    network = sphere.network
    header = P.Header('P5', sphere.state_id, tuple(interval), interval[3], network.network_id,
                      P.plate_support_id(network.network_id, network.plate_ids), None, inputs.parameter_id,
                      network.sphere.frame_id, 'I04 (feedback)', PRODUCER)
    return P._plate_motion(header, network.plate_ids, np.asarray(omega, dtype=float), frame_id=network.sphere.frame_id,
                           balance_id=balance_id, evaluation=D.EVALUATION_ENDPOINT, coupling_residual=residual)


def solve_at(state, moving, inputs, *, interval, parent_state_id, evaluation, omega_start=None):
    """(balance, belt term, P2, P1) at one state: properties at its own time, D1 with the belts there."""
    endpoint_s = interval[2] if evaluation == 'start' else interval[3]
    parent = state.state_id if evaluation == 'start' else parent_state_id
    support = P.trace_support(state.network)
    columns = None
    if inputs.forcing.gamma is not None:
        columns = R.moving_columns(moving, state, support,
                                   _header('P1', parent, state, interval, endpoint_s, support.support_id,
                                           inputs.datum, moving.moving_id), inputs.datum)
    strength = R.strength_port(moving, state, _header('P2', parent, state, interval, endpoint_s,
                                                      R.piece_support_id(state), inputs.datum, moving.moving_id),
                               inputs.datum, healing_law_id=G.HEALING_NONE)
    term = (G.BeltTerm(state, support, strength, inputs.declaration, inputs.datum, moving)
            if inputs.forcing.belts else None)
    result = D.balance(state.network, inputs.forcing, support=support if columns is not None else None,
                       columns_port=columns, datum=inputs.datum, water_regime=inputs.water_regime,
                       water_density_kg_m3=inputs.water_density_kg_m3, parent_state_id=parent_state_id,
                       interval=interval, belt_term=term, evaluation=evaluation,
                       endpoint_state_id=None if evaluation == 'start' else state.state_id, omega_start=omega_start)
    return result, term, strength, columns


# ---------------------------------------------------------------------------------------------------------------
# One advance of the interval with omega and increments (I05's two-pass split flow).

def history_reference(cohort, values, *, interval):
    """The split sub-cohort's history reference: a pure function of (cohort, increment, interval) (ruling P1)."""
    digest = hashlib.sha256(_json([cohort, [float(v) for v in values], list(interval)])).hexdigest()[:16]
    return 'i04:belt-history:%s:%d:%s' % (cohort, interval[1], digest)


def _advance(sphere, moving, motion, inputs, increments, interval):
    """(step, MovingAdvance without provenance, endpoint moving state, {final piece: pass-1 piece}, split counts)."""
    template = dict(inputs.template)
    first = advance_from_motion(sphere, motion, template, end_time_s=interval[3])
    keys = {(p.face_id, p.cohort_id) for p in first.state.material.pieces()}
    step, final, parent_of, counts = first, (), {k: k for k in keys}, dict(distinct=0, sub_cohorts=0)
    if increments:
        if set(increments) != keys:
            raise FeedbackRefused('the endpoint support changed between iterates; increments are never remapped',
                                  UNRESOLVED_SUPPORT, 'pieces')
        splits, renamed = M.split_for_increments(first, tuple(sorted(increments.items())),
                                                 history_of=partial(history_reference, interval=interval))
        if splits:
            step = _advance_split(sphere, motion, template, splits, interval[3])
        final = renamed
        child_of = {}
        for split in splits:
            for history, _ in split.groups:
                child_of[M._splits.sub_cohort_id(split.cohort_id, interval[1], history)] = split.cohort_id
        parent_of = {(p.face_id, p.cohort_id): (p.face_id, child_of.get(p.cohort_id, p.cohort_id))
                     for p in step.state.material.pieces()}
        counts = dict(distinct=len({v for v in increments.values()}), sub_cohorts=len(child_of))
    advance = M.MovingAdvance(interval[0], interval[1], births=inputs.births, conduction=inputs.conduction,
                              increments=final)
    out = M.advance_moving(moving, sphere, step, advance)
    return step, advance, out.state, parent_of, counts


def _pieces_per_face(state):
    counts = {}
    for piece in state.material.pieces():
        counts[piece.face_id] = counts.get(piece.face_id, 0)+1
    values = list(counts.values())
    return dict(max=max(values), mean=math.fsum(values)/len(values), faces=len(values), pieces=sum(values))


def _relative(new, old):
    """max |new - old| / max(|new|, |old|) over keyed per-layer values (0/0 is 0); a key present on one side only
    counts its values against zeros."""
    diff = scale = 0.
    for key in sorted(set(new) | set(old)):
        a = np.asarray(new.get(key, ()), dtype=float)
        b = np.asarray(old.get(key, ()), dtype=float)
        a = np.zeros(b.size) if a.size == 0 else a
        b = np.zeros(a.size) if b.size == 0 else b
        diff = max(diff, float(np.max(np.abs(a-b))))
        scale = max(scale, float(np.max(np.abs(a))), float(np.max(np.abs(b))))
    return 0. if scale == 0. else diff/scale


def _omega_relative(new, old):
    scale = max(float(np.max(np.abs(new))), float(np.max(np.abs(old))))
    return 0. if scale == 0. else float(np.max(np.abs(np.asarray(new)-np.asarray(old))))/scale


def _keyed(products, strength, parent_of):
    """Per-piece products of the D2 integration at an endpoint, keyed by the pass-1 piece (the split parent)."""
    return {parent_of[(face, cohort)]: products[index] for index, (face, cohort) in enumerate(strength.pieces)
            if index in products}


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class CoupledInterval:
    """A converged coupled interval: the Motion and MovingAdvance to commit, the endpoint states, the balance at the
    endpoint, the applied coupled P5, P6, P7, P9 and the coupling report. Only an unchanged value issued by the
    converged solver can be committed or inherited; construction and dataclass copies do not issue provenance."""
    motion: object
    advance: object
    step: object
    moving: object
    balance: object
    motion_port: object
    increment_port: object
    dissipation_port: object
    reaction_port: object
    report: dict


@dataclass(frozen=True, eq=False)
class Verified:
    """A committed driving record bound to its commit and endpoint: replayed by verify_driving, or produced and
    committed by ``commit`` in this process. ``text`` is the record's canonical JSON. Only values issued here are
    trusted (a module-private registry): a hand-built value is refused by name."""
    commit_key: str
    state_id: str
    moving_id: str
    text: str
    status: str

    @property
    def record(self):
        return json.loads(self.text)


_ISSUED = weakref.WeakSet()
_COUPLED_ISSUED = weakref.WeakKeyDictionary()


def _coupled_digest(value):
    """Bind the actual transfer records and public diagnostics, not just their cached identities. Endpoint arrays
    are immutable owned values and remain bound by their state identities. Ports carry immutable arrays too; their
    complete fields are included here. The mutable nested balance/report mappings must still match on use."""
    ports = []
    for port in (value.motion_port, value.increment_port, value.dissipation_port, value.reaction_port):
        ports.append({f.name: port.header.record() if f.name == 'header' else getattr(port, f.name)
                      for f in fields(port)})
    return _digest(_plain(dict(motion=value.motion.record(), advance=value.advance.record(),
                               step=value.step.record(), moving=value.moving.descriptor(),
                               balance=value.balance.record(), ports=ports, report=value.report)))


def _issued_coupled(value, *, detail):
    """Refuse before a solve or ledger write unless this is the unchanged converged result issued here.

    Weak keys retain neither the result nor its endpoint arrays after the caller releases it. The stored value is
    only a digest; it contains no reference back to the result. This is a public-API integrity guard, not a defence
    against arbitrary mutation of private Python process state."""
    if type(value) is not CoupledInterval or value not in _COUPLED_ISSUED:
        raise FeedbackRefused('the coupled interval was not issued by the converged solver in this process',
                              STALE, detail)
    try:
        unchanged = _coupled_digest(value) == _COUPLED_ISSUED[value]
    except (TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        unchanged = False
    if not unchanged:
        raise FeedbackRefused('the issued coupled interval has changed since convergence', STALE, detail)


def _issue(commit_key, state_id, moving_id, text, status):
    out = Verified(commit_key, state_id, moving_id, text, status)
    _ISSUED.add(out)
    return out


def _trusted(value):
    """A Verified value issued in this process by verify_driving (REPLAYED) or commit (PRODUCED)."""
    return type(value) is Verified and value in _ISSUED and value.status in (REPLAYED, PRODUCED)


def _canonical(record):
    return _json(record).decode('utf-8')


def _digest(record):
    return hashlib.sha256(_json(record)).hexdigest()


def _parent_record(parent, sphere, moving):
    """The parent interval's driving record, from an object bound to this very state (never a caller's dict)."""
    if parent is None:
        return None
    if type(parent) is CoupledInterval:
        _issued_coupled(parent, detail='parent')
        state_id, moving_id, record = parent.step.state.state_id, parent.moving.moving_id, \
            parent.advance.declared_driving()
    elif type(parent) is Verified:
        if not _trusted(parent):
            raise FeedbackRefused('the Verified parent was not issued by verify_driving or commit in this process',
                                  UNSUPPORTED, 'parent')
        state_id, moving_id, record = parent.state_id, parent.moving_id, parent.record
    else:
        raise FeedbackRefused('the parent is a CoupledInterval of this process or a Verified commit record; a '
                              'caller-supplied record is not admitted', UNSUPPORTED, 'parent')
    if state_id != sphere.state_id or moving_id != moving.moving_id:
        raise FeedbackRefused('the parent interval does not end at this state', STALE, 'parent')
    if not isinstance(record, dict) or record.get('schema') != SCHEMA or record.get('endpoint_state_id') != state_id:
        raise FeedbackRefused('the parent interval carries no driving record of this route', STALE, 'parent')
    return record


def _inherited(record, sphere):
    """What an interval takes from its parent's driving record (rulings B3(3), B4, C1(4), P4)."""
    if record is None:
        return dict(omega=None, labels=(), normal_strain={}, heat_bound_k=0., digest=None)
    try:
        omega = np.asarray(record['p5']['omega_rad_s'], dtype=float)
        if tuple(record['p5']['plate_ids']) != sphere.network.plate_ids:
            omega = None
        return dict(omega=omega, labels=tuple(record['labels']), normal_strain=dict(record['normal_strain']),
                    heat_bound_k=float(record['heat_omission']['cumulative_bound_k']), digest=_digest(record))
    except (KeyError, TypeError, ValueError) as exc:
        raise FeedbackRefused('the parent driving record is malformed: %s' % exc, MISSING, 'parent') from None


def accumulate_strain(inherited, added):
    """The cumulative belt strain E_b per boundary (ruling B4): the parent's value plus this interval's max_k |a_k| dt;
    a total above the unchanged I01 guard 0.05 refuses 'unsupported' before anything is committed."""
    total = dict(inherited)
    for name, value in added.items():
        total[name] = total.get(name, 0.)+value
        if total[name] > G.SMALL_STRAIN:
            raise FeedbackRefused('belt %r would exceed the I01 small-strain guard (cumulative max |a| dt = %.6g > '
                                  '0.05): longer normal deformation belongs to the finite-admission route or I07'
                                  % (name, total[name]), UNSUPPORTED, 'small strain')
    return total


def coupled_interval(sphere, moving, inputs, *, interval, parent=None, outer_iterations=OUTER_ITERATIONS):
    """Solve one interval at its endpoint; returns a CoupledInterval or refuses (nothing is committed).

    ``parent`` is the parent interval: the CoupledInterval this process produced for it, or the Verified record of the
    parent commit (``step`` reads and replays it on a ledger); None only for a first interval. It fixes the warm start,
    the inherited labels, the cumulative belt strain and the heat-omission bound, and its record's digest is recorded.
    ``outer_iterations`` may lower the cap (a refusal test); it never raises it."""
    if type(inputs) is not Inputs:
        raise FeedbackRefused('declared Inputs are required', MISSING, 'inputs')
    if type(outer_iterations) is not int or not 1 <= outer_iterations <= OUTER_ITERATIONS:
        raise FeedbackRefused('the outer cap is an integer in [1, %d]' % OUTER_ITERATIONS, UNSUPPORTED, 'cap')
    interval = tuple(interval)
    dt = interval[3]-interval[2]
    S0 = sphere.state_id
    inherited = _inherited(_parent_record(parent, sphere, moving), sphere)
    start, _, _, _ = solve_at(sphere, moving, inputs, interval=interval, parent_state_id=S0, evaluation='start',
                              omega_start=inherited['omega'])
    omega, balance_id = start.omega_rad_s.copy(), start.balance_id
    increments, ceilings, history, changes = {}, {}, [], []
    for k in range(outer_iterations):
        trial = _motion_port(sphere, inputs, interval, omega, balance_id, None)
        step, advance, end_moving, parent_of, counts = _advance(sphere, moving, trial, inputs, increments, interval)
        result, term, strength, columns = solve_at(step.state, end_moving, inputs, interval=interval,
                                                   parent_state_id=S0, evaluation='end', omega_start=omega)
        if term is None:
            new, energies, bounds = {}, {}, {}
        else:
            produced, energies, bounds = term.products(dt)
            new = {key: tuple(float(v) for v in value)
                   for key, value in _keyed(produced, strength, parent_of).items()}
            if not any(any(v) for v in new.values()):
                new = {}
            bounds = _keyed(bounds, strength, parent_of)
        omega_change = _omega_relative(result.omega_rad_s, omega)
        kappa_change = _relative(new, increments)
        change = max(omega_change, kappa_change)
        changes.append(change)
        rho = changes[-1]/changes[-2] if len(changes) > 1 and changes[-2] > 0 else None
        history.append(dict(iteration=k, omega_relative=omega_change, kappa_relative=kappa_change, rho=rho,
                            newton_iterations=None if result.belt is None else result.belt['newton_iterations'],
                            pieces_per_face=_pieces_per_face(step.state), increments=counts))
        if change <= OUTER_RELATIVE:
            # rho < 1 holds here by construction (every earlier change exceeded OUTER_RELATIVE), so no rho refusal.
            return _finish(sphere, inputs, interval, start, omega, step, advance, end_moving, result, term, strength,
                           energies, ceilings if increments else {}, parent_of, history, inherited)
        if k >= 3 and changes[-1] > changes[-2] > changes[-3]:
            raise FeedbackRefused('the coupled interval stopped contracting (two consecutive increases)', NONCONVERGED,
                                  json.dumps(changes))
        omega, balance_id = result.omega_rad_s.copy(), result.balance_id
        increments, ceilings = new, bounds
    raise FeedbackRefused('the coupled interval did not converge in %d outer iterations' % outer_iterations,
                          NONCONVERGED, json.dumps(changes))


def _heat_bound(moving, strength, energies):
    """Per piece, the omitted heat's pointwise adiabatic bound dT <= max_l E_l/(rho_l cp_l t_l A) = max_l
    (E_l/V_l)/(rho_l cp_l) (K), with E_l the omitted creep + plastic energy of sublayer l (ruling P4); returns (the
    largest, [[face, cohort, bound]] for every piece with a nonzero bound)."""
    rows = []
    for index, (face, cohort) in enumerate(strength.pieces):
        pair = energies.get(index)
        if pair is None:
            continue
        record = moving.cohort(cohort)
        density = np.array([s.reference_density_kg_m3*s.heat_capacity_j_kg_k for s in record.sublayers])
        bound = float(np.max((pair[0]+pair[1])/density))
        if bound > 0:
            rows.append([face, cohort, bound])
    rows.sort()
    return max([r[2] for r in rows]+[0.]), rows


def _lateral_allowance(conduction):
    """I05's declared lateral-omission temperature allowance for this interval, when lateral heat is omitted."""
    if conduction is None or conduction.lateral != 'omit':
        return None
    value = (conduction.declared_certificate() or {}).get('temperature_allowance_k')
    return None if value is None else float(value)


def _energy_closure(dissipation_port, strength, sphere, work_j):
    """|sum over pieces and sublayers of (E_creep + E_plastic)_l t_l A / (belt column work x dt) - 1| (P7 closure)."""
    areas = {(p.face_id, p.cohort_id): float(p.area_m2) for p in sphere.material.pieces()}
    offsets = np.asarray(dissipation_port.offsets)
    energy = (np.asarray(dissipation_port.creep_energy_j_m3)+np.asarray(dissipation_port.plastic_energy_j_m3)) \
        * np.asarray(strength.thickness_m)
    total = math.fsum(float(math.fsum(energy[int(offsets[i]):int(offsets[i+1])]))*areas[piece]
                      for i, piece in enumerate(dissipation_port.pieces))
    if work_j == 0.:
        return 0. if total == 0. else math.inf
    return abs(total/work_j-1)


def _finish(sphere, inputs, interval, start, omega, step, advance, end_moving, result, term, strength, energies,
            ceilings, parent_of, history, inherited):
    """The converged interval's ports and provenance. P6 is the increment actually applied, with the D-P1 ceiling of
    the integration that produced it; P7 is the energy of the integration at the committed endpoint."""
    state = step.state
    parent = sphere.state_id
    endpoint_s = interval[3]
    dt = interval[3]-interval[2]
    normal = accumulate_strain(inherited['normal_strain'], {} if term is None else term.normal_strain(dt))
    pieces = strength.pieces
    offsets = np.asarray(strength.offsets)
    applied_increments = dict(advance.increments)
    rows, bounds, creep, plastic = [], [], [], []
    for index, piece in enumerate(pieces):
        layers = int(offsets[index+1]-offsets[index])
        values = applied_increments.get(piece, (0.,)*layers)
        ceiling = ceilings.get(parent_of[piece])
        rows.extend(reversed(values))
        bounds.extend(reversed(list(ceiling)) if ceiling is not None else [0.]*layers)
        pair = energies.get(index)
        creep.extend(reversed(list(pair[0])) if pair is not None else [0.]*layers)
        plastic.extend(reversed(list(pair[1])) if pair is not None else [0.]*layers)
    support_id = R.piece_support_id(state)
    increment_port = P._mechanical_increment(
        _header('P6', parent, state, interval, endpoint_s, support_id, None, result.balance_id), pieces, offsets,
        np.asarray(rows, dtype=float), np.asarray(bounds, dtype=float))
    dissipation_port = P._dissipation(
        _header('P7', parent, state, interval, endpoint_s, support_id, None, result.balance_id), pieces, offsets,
        np.asarray(creep, dtype=float), np.asarray(plastic, dtype=float), P.HEAT_NOT_CONVERTED)
    closure = None
    if term is not None:
        # P7 closure (ruling C2(3)): the energies booked per piece equal the belt's column work over dt, within the
        # derived bound of the hierarchy (the belt's U residual and the kernel's work partition).
        closure = _energy_closure(dissipation_port, strength, state, result.belt['column_work_w']*dt)
        closure_bound = result.belt['u_residual']+D.PARTITION
        if not closure <= closure_bound:
            raise FeedbackRefused('P7 energies do not close on the belt\'s column work (%.3g > %.3g)'
                                  % (closure, closure_bound), NONCONVERGED, 'p7 closure')
    support = P.trace_support(state.network)
    owned = tuple(bool(support.boundary_ids[int(support.edge_boundary[e])] in inputs.forcing.belts)
                  for e in range(support.edges))
    velocity, traction = np.zeros((support.edges, 3)), np.zeros((support.edges, 3))
    if term is not None:
        last_omega = term.last[0]
        for line, response in zip(term.lines, term.last[1]):
            left, right = (term.order[p] for p in support.plates[line.edge])
            velocity[line.edge] = term.radius*np.cross(last_omega[right]-last_omega[left], line.midpoint)
            traction[line.edge] = response['traction']
    radius = float(state.network.sphere.radius_m)
    lengths = np.array([radius*2*math.atan2(float(np.linalg.norm(support.start[e]-support.end[e])),
                                            float(np.linalg.norm(support.start[e]+support.end[e])))
                        for e in range(support.edges)])
    reaction_port = P._boundary_reaction(
        _header('P9', parent, state, interval, endpoint_s, support.support_id, None, result.balance_id), support,
        owned, velocity, traction, lengths)
    residual = _omega_relative(result.omega_rad_s, omega)
    motion_port = _motion_port(sphere, inputs, interval, omega, result.balance_id, residual)
    labels = set(inherited['labels'])|{G.HEAT_OMITTED}
    if term is not None:
        labels |= set(result.belt['labels'])
    heat, per_piece = _heat_bound(end_moving, strength, energies)
    last = history[-1]
    rho = last['rho']
    delta = max(last['omega_relative'], last['kappa_relative'])
    # A-posteriori error of the committed iterate x_k: |x_k - x*| <= |x_(k+1) - x_k|/(1 - rho).
    error = delta if rho is None else delta/(1-rho)
    # D1 axis tilt |omega_xy|/|omega| against I03's measured margins (ruling P5(7)); 0 at rest.
    size = float(np.linalg.norm(omega))
    tilt = float(np.linalg.norm(np.asarray(omega)[:, :2]))/size if size else 0.
    report = dict(route=ROUTE, iterations=len(history), history=history, outer_relative=OUTER_RELATIVE,
                  outer_cap=OUTER_ITERATIONS, iteration_error=error, residual=residual, axis_tilt=tilt,
                  p7_closure_relative=closure, events={} if term is None else term.events(),
                  heat_rule=P.HEAT_NOT_CONVERTED, pieces_per_face=_pieces_per_face(state),
                  sublayers=int(np.max(np.diff(offsets))))
    driving = dict(schema=SCHEMA, route=ROUTE, parent_state_id=parent, interval=list(interval),
                   endpoint_state_id=state.state_id, motion_id=step.motion.motion_id,
                   parent_driving_sha256=inherited['digest'], start_balance_id=start.balance_id,
                   p5=dict(port_id=motion_port.port_id, balance_id=motion_port.balance_id, residual=residual,
                           plate_ids=list(motion_port.plate_ids), omega_rad_s=motion_port.omega_rad_s.tolist()),
                   balance=_plain(result.record()), forcing=_plain(inputs.forcing.record()),
                   declaration=_plain(inputs.declaration.record()), coupling=_plain(report),
                   labels=sorted(labels), normal_strain=_plain(normal),
                   heat_omission=dict(interval_bound_k=heat, cumulative_bound_k=inherited['heat_bound_k']+heat,
                                      per_piece_k=per_piece, lateral_allowance_k=_lateral_allowance(inputs.conduction),
                                      label=G.HEAT_OMITTED),
                   p6=dict(port_id=increment_port.port_id, bound=[float(x) for x in increment_port.bound]),
                   ports=dict(p7=dissipation_port.port_id, p9=reaction_port.port_id))
    committed = M.MovingAdvance(advance.start_step, advance.end_step, births=advance.births,
                                conduction=advance.conduction, increments=advance.increments, driving=_plain(driving))
    out = CoupledInterval(step.motion, committed, step, end_moving, result, motion_port, increment_port,
                          dissipation_port, reaction_port, report)
    _COUPLED_ISSUED[out] = _coupled_digest(out)
    return out


def _plain(value):
    """Plain JSON data (mappings to dicts, tuples to lists, numpy scalars to Python numbers), for the frozen text."""
    def default(o):
        if hasattr(o, 'items'):
            return dict(o)
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        return list(o)
    return json.loads(json.dumps(value, default=default, allow_nan=False))


# ---------------------------------------------------------------------------------------------------------------
# The ledger route: inheritance from the parent commit, binding at commit, replay on reopen (rulings P1, P2(e)).

def bind_commit_interval(ledger_interval, motion):
    """Field-by-field: the ledger interval (start_s, end_s, start_step, end_step) equals the P5 interval's
    (interval[2], interval[3], interval[0], interval[1]) — never compared as tuples."""
    interval = motion.header.interval if type(motion) is P.PlateMotion else tuple(motion)
    if ledger_interval is None or (float(ledger_interval[0]), float(ledger_interval[1]), int(ledger_interval[2]),
                                   int(ledger_interval[3])) != (float(interval[2]), float(interval[3]),
                                                                int(interval[0]), int(interval[1])):
        raise FeedbackRefused('the commit interval is not the P5 interval', STALE, 'interval')


def find_driving(ledger, commit):
    """The driving record stored with ``commit`` (None for an interval without one), labelled RECORDED: a found
    record is never called D1 provenance until verify_driving replays it."""
    metadata = commit.metadata()
    moving = metadata.get('moving') if isinstance(metadata, dict) else None
    advance = None if not isinstance(moving, dict) else moving.get('advance')
    if not isinstance(advance, dict) or advance.get('driving') is None:
        return None
    return dict(record=advance['driving'], status=RECORDED)


def _history(ledger, chain, upto):
    """The index of the last commit at or before ``upto`` that carries a driving record (None when none does). In v1
    a coupled chain must be unbroken: a commit without a record after one with a record refuses ('chain': E_b and the
    labels are not carried across a non-coupled interval), and any committed I03 topology event refuses ('events': no
    lineage mapping for E_b)."""
    last = None
    for index in range(1, upto+1):
        commit = chain[index]
        sphere = commit.metadata().get('sphere')
        motion = sphere.get('motion') if isinstance(sphere, dict) else None
        if isinstance(motion, dict) and motion.get('events'):
            raise FeedbackRefused('the history holds a committed I03 topology event: the coupled route has no lineage '
                                  'mapping for the cumulative belt strain in v1', UNSUPPORTED, 'events')
        if find_driving(ledger, commit) is not None:
            last = index
        elif last is not None:
            raise FeedbackRefused('a non-coupled interval follows a coupled one: the cumulative strain and the labels '
                                  'are not carried across it in v1', UNSUPPORTED, 'chain')
    return last


def next_interval(ledger):
    """The head's next interval on the ledger's own schedule: (start_step, end_step, start_s, end_s)."""
    head = ledger.head()
    state = ledger.state(head)
    k, step_s = head.accepted_steps, state.settings.step_s
    return (k, k+1, advance_time(state.start_time_s, k*step_s), advance_time(state.start_time_s, (k+1)*step_s))


def step(ledger, inputs, *, verified=None, cache=None, outer_iterations=OUTER_ITERATIONS):
    """The coupled interval that follows the ledger's head, inheriting from the head's own driving record: the record
    is replayed (verify_driving), or ``verified`` is the Verified value ``commit`` returned for this head."""
    chain = ledger.chain()
    head = chain[-1]
    parent = None
    if _history(ledger, chain, len(chain)-1) is not None:
        if verified is not None:
            found = find_driving(ledger, head)
            if not _trusted(verified) or verified.commit_key != head.key or \
                    verified.text != _canonical(found['record']):
                raise FeedbackRefused('the verified record is not an issued verification of the head\'s', STALE,
                                      'verified')
            parent = verified
        else:
            parent = verify_driving(ledger, head, cache=cache)
    return coupled_interval(ledger.sphere(head), ledger.moving(head), inputs, interval=next_interval(ledger),
                            parent=parent, outer_iterations=outer_iterations)


def commit(ledger, coupled, *, deadline=None):
    """Commit a coupled interval on the ledger's head; returns the Verified record of the new head.

    Before the write: the value is the unchanged result of the converged solver issued in this process, the interval
    equals the ledger's next interval field by field (ruling P2(e)), the parent state is
    the head's, and the record inherits from the head's own driving record (refused by name when the head carries a
    record that was not used). I05 binds the record's parent, endpoint, motion and interval again inside the commit."""
    if type(coupled) is not CoupledInterval:
        raise FeedbackRefused('a CoupledInterval is required', MISSING, 'coupled')
    _issued_coupled(coupled, detail='coupled')
    chain = ledger.chain()
    head = chain[-1]
    record = coupled.advance.declared_driving()
    if record['parent_state_id'] != ledger.sphere(head).state_id:
        raise FeedbackRefused('the coupled interval does not start at the head', STALE, 'parent_state_id')
    last = _history(ledger, chain, len(chain)-1)
    found = find_driving(ledger, head) if last is not None else None
    if record['parent_driving_sha256'] != (None if found is None else _digest(found['record'])):
        raise FeedbackRefused('the coupled interval did not inherit the head\'s driving record', STALE, 'parent')
    k0, k1, s0, s1 = next_interval(ledger)
    bind_commit_interval((s0, s1, k0, k1), coupled.motion_port)
    outcome = K.Clock(ledger).advance(steps=1, transfers=(coupled.motion, coupled.advance), deadline=deadline)
    if outcome.status not in (K.COMPLETED, K.HISTORY_COMPLETE):
        raise FeedbackRefused('the ledger did not commit the interval: %s' % outcome.reason, STALE, 'commit')
    new = outcome.head
    if ledger.sphere(new).state_id != coupled.step.state.state_id or \
            ledger.moving(new).moving_id != coupled.moving.moving_id:
        raise FeedbackRefused('the committed endpoint is not the solved endpoint; do not continue from it', STALE,
                              'endpoint')
    return _issue(new.key, coupled.step.state.state_id, coupled.moving.moving_id, _canonical(record), PRODUCED)


# Binding and inheritance fields first, so a refusal names the root cause (a dropped inheritance, another interval or
# another motion), then every other field in name order.
_BINDING_FIELDS = ('parent_driving_sha256', 'interval', 'parent_state_id', 'endpoint_state_id', 'motion_id')


def _first_difference(produced, record):
    rest = sorted((set(produced) | set(record)) - set(_BINDING_FIELDS))
    for key in _BINDING_FIELDS+tuple(rest):
        if produced.get(key) != record.get(key):
            return key
    return 'driving'


def _cached(ledger, commit, cache):
    """A cache hit certifies what a miss does. It is accepted only for an issued verification of this very record and
    endpoint (the cache is keyed by the positional commit key, which another ledger of the same identity shares;
    round 2), and only when the chain behind it is this ledger's: the parent commit is validated through the same path
    (a validated hit, or a replay on a miss) and the record's parent digest must be that of the parent commit's stored
    record, or None when no coupled history precedes it (round 3). A valid cache costs O(n) comparisons, no solves."""
    cached = cache[commit.key]
    found = find_driving(ledger, commit)
    if (not _trusted(cached) or cached.commit_key != commit.key or found is None
            or cached.text != _canonical(found['record']) or cached.state_id != ledger.sphere(commit).state_id
            or cached.moving_id != ledger.moving(commit).moving_id):
        raise FeedbackRefused('the cached verification is not this commit\'s record', STALE, 'cache')
    chain = ledger.chain()
    keys = [c.key for c in chain]
    if commit.key not in keys or keys.index(commit.key) == 0:
        raise FeedbackRefused('the commit is not a successor on this ledger', STALE, 'commit')
    index = keys.index(commit.key)
    parent = None
    if _history(ledger, chain, index-1) is not None:
        parent = verify_driving(ledger, chain[index-1], cache=cache)
    if found['record'].get('parent_driving_sha256') != (None if parent is None else _digest(parent.record)):
        raise FeedbackRefused('the cached record does not continue the parent commit\'s record', STALE,
                              'parent_driving_sha256')
    return cached


def verify_driving(ledger, commit, *, cache=None):
    """Replay a commit's driving record; returns a Verified value or refuses by name.

    The parent commit's record is verified first (recursively; ``cache`` holds verified commits by key) and the chain
    must be unbroken. The interval binds field by field to the ledger interval. The whole interval is then solved again
    from the parent commit's restored states with the record's forcing and declaration, the committed motion's
    supplies and sinks, and the committed advance's births and conduction, inheriting from the verified parent record.
    The replayed driving record must equal the stored one in every field (labels, cumulative strain, heat, the coupling
    report, the start balance, P5, P6 and its bound, the P7/P9 identities), the replayed advance must equal the
    committed one (so the committed increments are the replayed D2 products and the split names are reproduced), the
    replayed motion must be the committed motion, and the replayed endpoint states the restored ones. Each record is
    verified once per cache: a hit is accepted only for an issued verification of this very record and endpoint, so a
    chain of n intervals costs n solves with one cache, from cold (one per coupled interval, as on reopen)."""
    cache = {} if cache is None else cache
    if commit.key in cache:
        return _cached(ledger, commit, cache)
    found = find_driving(ledger, commit)
    if found is None:
        raise FeedbackRefused('the commit carries no driving record', MISSING, 'driving')
    record = found['record']
    if not isinstance(record, dict) or record.get('schema') != SCHEMA:
        raise FeedbackRefused('the driving record is not of this schema', STALE, 'schema')
    chain = ledger.chain()
    keys = [c.key for c in chain]
    if commit.key not in keys or keys.index(commit.key) == 0:
        raise FeedbackRefused('the commit is not a successor on this ledger', STALE, 'commit')
    index = keys.index(commit.key)
    parent_commit = chain[index-1]
    parent = None
    if _history(ledger, chain, index-1) is not None:
        parent = verify_driving(ledger, parent_commit, cache=cache)
    metadata = commit.metadata()
    try:
        interval = tuple(record['interval'])
        bind_commit_interval(commit.interval, interval)
        forcing = D.Forcing.from_record(record['forcing'])
        declaration = G.Declaration.from_record(record['declaration'])
        balance = record['balance']
        datum = D.Datum(**balance['datum']) if balance.get('datum') else None
        motion = T._motion(metadata['sphere']['motion'])
        advance = M.MovingAdvance.from_record(metadata['moving']['advance'])
    except FeedbackRefused:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, TectonicsError) as exc:
        raise FeedbackRefused('the driving record or its commit is incomplete: %s' % exc, MISSING, 'driving') from None
    if forcing.record() != record['forcing'] or declaration.record() != record['declaration']:
        raise FeedbackRefused('the driving record\'s inputs do not reproduce', STALE, 'inputs')
    if motion.mesh is not None:
        raise FeedbackRefused('a declared mesh replacement is not replayable in v1', UNSUPPORTED, 'mesh')
    template = tuple((name, value) for name, value in (('supplies', motion.supplies), ('sinks', motion.sinks))
                     if value)
    try:
        inputs = Inputs(forcing, declaration, datum, template, advance.births, advance.conduction,
                        balance.get('water_regime'), balance.get('water_density_kg_m3'))
        rerun = coupled_interval(ledger.sphere(parent_commit), ledger.moving(parent_commit), inputs,
                                 interval=interval, parent=parent)
    except TectonicsError as exc:
        raise FeedbackRefused('the interval does not replay: %s' % exc, STALE, 'replay') from None
    produced = rerun.advance.declared_driving()
    if produced != record:
        raise FeedbackRefused('the driving record does not replay', STALE, _first_difference(produced, record))
    if rerun.advance.advance_id != advance.advance_id:
        raise FeedbackRefused('the committed advance (increments, births, conduction) does not replay', STALE,
                              'advance')
    if rerun.motion.motion_id != metadata['sphere'].get('motion_id'):
        raise FeedbackRefused('the committed motion does not replay', STALE, 'motion')
    if ledger.sphere(commit).state_id != rerun.step.state.state_id or \
            ledger.moving(commit).moving_id != rerun.moving.moving_id:
        raise FeedbackRefused('the restored endpoint is not the replayed endpoint', STALE, 'endpoint')
    out = _issue(commit.key, rerun.step.state.state_id, rerun.moving.moving_id, _canonical(record), REPLAYED)
    cache[commit.key] = out
    return out


def omission_labels(ledger, commit):
    """The heat-omission label of a state's temperatures (ruling P4): after any committed D1/D2 interval up to and
    including ``commit``, (HEAT_OMITTED, the last record's cumulative pointwise bound in K, I05's lateral allowance of
    that interval); () when no D1/D2 interval precedes it. The values are as recorded (verify_driving replays them)."""
    chain = ledger.chain()
    keys = [c.key for c in chain]
    for index in range(keys.index(commit.key), 0, -1):
        found = find_driving(ledger, chain[index])
        if found is not None:
            heat = found['record'].get('heat_omission', {})
            return (G.HEAT_OMITTED, heat.get('cumulative_bound_k'), heat.get('lateral_allowance_k'))
    return ()
