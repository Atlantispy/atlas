"""I04.3 material-dependent boundary response (D2) on the I03 spherical network. WORKING NON-CANON.

The reduced belt of a plate boundary (tectonics/docs/I04_CAUSAL_START.md, R4-4). At every P1 trace edge the belt is the
segment of the great circle through the edge midpoint normal to the boundary, of declared physical width ``w``, resolved
by the I03 faces it crosses. Each crossed piece is one laterally uniform I01 column built from P2 (the package column
kernel, unchanged), deforming at a uniform rate in depth; the cells act in series (thin-sheet equilibrium):

- in a cell, e_nn = a, e_nt = g, e_zz = -a; the invariant e = sqrt(a^2 + g^2) and c = a/e;
- the vertical force balance gives the mean pressure P = sigma_v - c s, so c = +-1 is I01's certified pure-shear
  closure and c = 0 is simple shear with the lithostatic stress as mean pressure;
- the depth-integrated tractions are F_n = 2 c S and F_t = sqrt(1 - c^2) S, with S = sum_q w_q s_q;
- equal tractions across the series cells force one c and one S on the whole line, so a velocity jump dv gives
  U = sqrt(dv_n^2 + (dv_t/2)^2), c = dv_n/U and one scalar monotone equation sum_k dy_k e_k(S; c) = U.

Weakening uses the nonlocal history kappa_bar - ell^2 kappa_bar'' = kappa along the line, with zero flux at the
declared closed belt sides (I01 contract, D2), applied at each depth over the cells holding material there. Raw kappa is
never written; the increment of the interval (P6) is the finite-volume mean over each piece, and its energy (P7) comes
from the same integration (port record D-P1). No event is proposed: separation, initiation and junction
reorganisation refuse by name (CM-07, CM-11, CM-14). P4 is not used.

Every belt result carries THIN_SHEET (I01_WEAKENING section 8 gives no threshold for 'much larger than ~100 km', so
none is invented) and reports w/H and the localised width over H; exactness is claimed only at c in {-1, 0, 1}, and
0 < |c| < 1 carries LODE (coordinator rulings of 4 October 2026, B1-B5).

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
import hashlib
import math
from numbers import Real

import numpy as np

from . import _integration_column as _column
from . import _integration_weakening as _weak
from . import integration_ports as P
from . import integration_sphere as S
from ._validation import TectonicsError
from .materials import _json

SCHEMA = 'atlas.i04-strength-declaration.v1'
METHOD = 'atlas.nonlocal-weakening-candidate.v1'
BELT = 'atlas.i04-reduced-belt.v1'
HEALING_NONE = 'atlas.i04-healing-none.v1'
EPS = 2.**-52
TOL = _column.POLICY['rate_relative_tolerance']             # 2e-11, the column kernel's rate tolerance
ITERATIONS = _column.POLICY['iterations']                    # 96
RESULTANT_TOL = 1e-10                                        # _integration_motion.FORCE_TOL (same balance, scalar)
SMALL_STRAIN = .05                                           # I01 weakening's small-strain guard, cumulative per belt
YIELD_CONVENTION = 'atlas.i01-plane-strain-drucker-prager.v1'  # C cos(phi) + P sin(phi) on the invariant (I01 D2)
THIN_SHEET = 'thin-sheet validity not established (I01_WEAKENING §8); reduced-model numerical claim only'
LODE = 'oblique belt (0 < |c| < 1): the declared Lode-angle-free plane-strain convention, an approximation'
COARSE = 'belt unresolved by the faces: line-quadrature deposit diluted (beta < 1 - tol)'
HEAT_OMITTED = 'dissipation not converted to heat (IN-05 v1, atlas.i04-dissipation-not-heated.v1)'
ONE_SIDED = ('declared one-sided shear-zone placement (I03 cannot carry history in sheared non-carrier rows)')
S_RELATIVE = TOL                                             # the belt stops on S at the kernel's own 2e-11
ORDER_RANGE = (2, _column.POLICY['max_order'])

MISSING = 'missing value'
INVALID = 'invalid input'
UNSUPPORTED = 'unsupported'
UNRESOLVED_BELT = 'unresolved belt'
UNRESOLVED_COLUMN = 'unresolved column'
DOUBLE_OWNERSHIP = 'double ownership'
NONCONVERGED = 'nonconverged belt'
STALE = 'stale identity'
CODES = (MISSING, INVALID, UNSUPPORTED, UNRESOLVED_BELT, UNRESOLVED_COLUMN, DOUBLE_OWNERSHIP, NONCONVERGED, STALE)

# Events that a stress state could suggest; none has an admitted law in v1 (I01_TRANSITIONS, closure matrix).
EVENT_REFUSALS = {
    'separation': 'refused: separation needs an admitted through-lithosphere law (CM-07)',
    'initiation': 'refused: initiation needs the resolved I07 method (CM-11)',
    'junction': 'refused: junction reorganisation needs an admitted law (CM-14)',
}


class StrengthRefused(TectonicsError):
    """A named D2 refusal; ``code`` is one of CODES and ``detail`` names the field or the I01 reason."""

    def __init__(self, message, code, detail=None):
        if code not in CODES:
            raise ValueError('unknown strength refusal code %r' % code)
        super().__init__(message)
        self.code, self.detail = code, detail


def _name(value, label):
    if type(value) is not str or not value.strip():
        raise StrengthRefused(label+' must be a nonempty name', INVALID, label)
    return value


def _real(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise StrengthRefused(label+' must be a real number', INVALID, label)
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise StrengthRefused(label+' is outside its finite support', INVALID, label)
    return value


# ---------------------------------------------------------------------------------------------------------------
# Declared inputs (IN-04 material inputs and scenario assumptions), each with provenance. Nothing defaults.

@dataclass(frozen=True, slots=True)
class BeltMaterial:
    """D2 material inputs of one material_id: undamaged cohesion C0 (Pa), friction phi0 (rad), plastic viscosity
    eta_p (Pa s), grain size (m) and the ASPECT-form weakening law on engineering plastic history (interval and the
    cohesion and friction factors of the package WeakeningLaw)."""
    cohesion_pa: float
    friction_rad: float
    plastic_viscosity_pa_s: float
    grain_m: float
    weakening_interval: tuple
    cohesion_factor: float
    friction_factor: float
    yield_convention: str
    source: str

    def __post_init__(self):
        if self.yield_convention != YIELD_CONVENTION:
            raise StrengthRefused('only the yield convention %r is admitted' % YIELD_CONVENTION, UNSUPPORTED,
                                  'yield_convention')
        _real(self.cohesion_pa, 'cohesion', nonnegative=True)
        phi = _real(self.friction_rad, 'friction', nonnegative=True)
        if not phi < math.pi/2:
            raise StrengthRefused('friction must lie in [0, pi/2)', INVALID, 'friction')
        _real(self.plastic_viscosity_pa_s, 'plastic viscosity', positive=True)
        _real(self.grain_m, 'grain size', positive=True)
        if type(self.weakening_interval) is not tuple or len(self.weakening_interval) != 2:
            raise StrengthRefused('the weakening interval is (start, end)', INVALID, 'weakening_interval')
        try:
            law = _weak.WeakeningLaw(self.weakening_interval[0], self.weakening_interval[1], self.cohesion_factor,
                                     self.friction_factor)
        except (TypeError, ValueError) as exc:
            raise StrengthRefused('the weakening law is not admitted: %s' % exc, INVALID, 'weakening') from None
        for key, value in (('cohesion_pa', self.cohesion_pa), ('friction_rad', self.friction_rad),
                           ('plastic_viscosity_pa_s', self.plastic_viscosity_pa_s), ('grain_m', self.grain_m),
                           ('cohesion_factor', law.cohesion_factor), ('friction_factor', law.friction_factor)):
            object.__setattr__(self, key, float(value))
        object.__setattr__(self, 'weakening_interval', (law.start, law.end))
        _name(self.source, 'material source')

    def law(self):
        return _weak.WeakeningLaw(self.weakening_interval[0], self.weakening_interval[1], self.cohesion_factor,
                                  self.friction_factor)

    def record(self):
        return dict(cohesion_pa=self.cohesion_pa, friction_rad=self.friction_rad,
                    plastic_viscosity_pa_s=self.plastic_viscosity_pa_s, grain_m=self.grain_m,
                    weakening_interval=list(self.weakening_interval), cohesion_factor=self.cohesion_factor,
                    friction_factor=self.friction_factor, yield_convention=self.yield_convention,
                    source=self.source)

    @classmethod
    def from_record(cls, record):
        return cls(record['cohesion_pa'], record['friction_rad'], record['plastic_viscosity_pa_s'], record['grain_m'],
                   tuple(record['weakening_interval']), record['cohesion_factor'], record['friction_factor'],
                   record['yield_convention'], record['source'])


@dataclass(frozen=True, slots=True)
class CreepLaw:
    """The I01 creep mechanisms of one creep_law_id: one to four (a, n, energy, volume, grain exponent) records, a
    already in SI invariant convention (no second conversion; I01_COLUMN)."""
    mechanisms: tuple
    source: str

    def __post_init__(self):
        if type(self.mechanisms) is not tuple or not 1 <= len(self.mechanisms) <= _column.POLICY['max_mechanisms']:
            raise StrengthRefused('one to four creep mechanisms are declared', INVALID, 'creep')
        clean = []
        for item in self.mechanisms:
            if type(item) is not dict:
                raise StrengthRefused('a creep mechanism is a dict of the I01 Creep fields', INVALID, 'creep')
            try:
                _weak.validate_creep(dict(item))
            except (TypeError, ValueError) as exc:
                raise StrengthRefused('creep mechanism refused: %s' % exc, INVALID, 'creep') from None
            clean.append(tuple(sorted((k, float(v)) for k, v in item.items())))
        object.__setattr__(self, 'mechanisms', tuple(clean))
        _name(self.source, 'creep source')

    def dicts(self):
        return [dict(item) for item in self.mechanisms]

    def record(self):
        return dict(mechanisms=self.dicts(), source=self.source)

    @classmethod
    def from_record(cls, record):
        return cls(tuple(dict(item) for item in record['mechanisms']), record['source'])


@dataclass(frozen=True, slots=True)
class Belt:
    """One D2 boundary's reduced belt: the physical width w (m), the D2 length ell (m), each with provenance, and the
    healing law (only zero healing is admitted). w is a declared physical shear-zone width, never derived. ``side``
    declares where the deforming zone lies: 'both' (w/2 on each side of the trace) or 'left'/'right' (the whole w within
    that plate's margin, a declared geometric assumption)."""
    width_m: float
    length_m: float
    healing_law_id: str
    width_source: str
    length_source: str
    side: str = 'both'

    def __post_init__(self):
        if self.side not in ('both', 'left', 'right'):
            raise StrengthRefused('a belt side is both, left or right', INVALID, 'side')
        object.__setattr__(self, 'width_m', _real(self.width_m, 'belt width', positive=True))
        object.__setattr__(self, 'length_m', _real(self.length_m, 'D2 length', positive=True))
        if self.healing_law_id is None:
            raise StrengthRefused('the healing law is declared', MISSING, 'healing_law_id')
        if self.healing_law_id != HEALING_NONE:
            raise StrengthRefused('only the zero-healing law %r is admitted' % HEALING_NONE, UNSUPPORTED,
                                  'healing_law_id')
        _name(self.width_source, 'belt width source')
        _name(self.length_source, 'D2 length source')

    def record(self):
        out = dict(width_m=self.width_m, length_m=self.length_m, healing_law_id=self.healing_law_id,
                   width_source=self.width_source, length_source=self.length_source)
        if self.side != 'both':
            out['side'] = self.side
        return out

    @classmethod
    def from_record(cls, record):
        return cls(record['width_m'], record['length_m'], record['healing_law_id'], record['width_source'],
                   record['length_source'], record.get('side', 'both'))


def _pairs(value, label, kind):
    items = sorted(value.items()) if isinstance(value, dict) else list(value)
    if any(type(p) is not tuple or len(p) != 2 or type(p[0]) is not str or type(p[1]) is not kind for p in items):
        raise StrengthRefused(label+': (name, %s) pairs required' % kind.__name__, INVALID, label)
    names = [p[0] for p in items]
    if len(set(names)) != len(names):
        raise StrengthRefused(label+': each name at most once', INVALID, label)
    return tuple(sorted(items))


@dataclass(frozen=True, slots=True)
class Declaration:
    """Every D2 input of one interval: belts per boundary, material and creep tables, and the depth quadrature (the
    Gauss order per layer of the I01 column)."""
    belts: tuple
    materials: tuple
    creep_laws: tuple
    order: int
    provenance: str

    def __post_init__(self):
        object.__setattr__(self, 'belts', _pairs(self.belts, 'belts', Belt))
        object.__setattr__(self, 'materials', _pairs(self.materials, 'materials', BeltMaterial))
        object.__setattr__(self, 'creep_laws', _pairs(self.creep_laws, 'creep laws', CreepLaw))
        if not self.belts:
            raise StrengthRefused('at least one D2 belt is declared', MISSING, 'belts')
        if type(self.order) is not int or not ORDER_RANGE[0] <= self.order <= ORDER_RANGE[1]:
            raise StrengthRefused('the Gauss order per layer is an integer in %s' % (ORDER_RANGE,), INVALID, 'order')
        _name(self.provenance, 'declaration provenance')

    def record(self):
        return dict(schema=SCHEMA, method=METHOD, belt=BELT, order=self.order, provenance=self.provenance,
                    belts=[[k, v.record()] for k, v in self.belts],
                    materials=[[k, v.record()] for k, v in self.materials],
                    creep_laws=[[k, v.record()] for k, v in self.creep_laws])

    @property
    def declaration_id(self):
        return hashlib.sha256(_json(self.record())).hexdigest()

    @classmethod
    def from_record(cls, record):
        """The declaration a stored record names (for replay); its identity must reproduce."""
        if record.get('schema') != SCHEMA:
            raise StrengthRefused('not a D2 declaration record', STALE, 'schema')
        return cls(tuple((k, Belt.from_record(v)) for k, v in record['belts']),
                   tuple((k, BeltMaterial.from_record(v)) for k, v in record['materials']),
                   tuple((k, CreepLaw.from_record(v)) for k, v in record['creep_laws']), record['order'],
                   record['provenance'])

    def belt(self, boundary_id):
        return dict(self.belts).get(boundary_id)

    def material(self, material_id):
        found = dict(self.materials).get(material_id)
        if found is None:
            raise StrengthRefused('no D2 material is declared for %r' % material_id, MISSING, 'materials')
        return found

    def creep(self, creep_law_id):
        found = dict(self.creep_laws).get(creep_law_id)
        if found is None:
            raise StrengthRefused('no creep law is declared for %r' % creep_law_id, MISSING, 'creep_laws')
        return found


# ---------------------------------------------------------------------------------------------------------------
# Columns from P2. Each piece's sublayers, top down, become I01 layers under the lithostatic closure; the layer
# density is taken from P2's own vertical stress, so the column reproduces P2's lithostatic stress.

def piece_rows(strength, index):
    """Rows of piece ``index`` in a P2 StrengthState, bottom to top (P2's order)."""
    if type(strength).__name__ != 'StrengthState':
        raise StrengthRefused('a P2 StrengthState is required', INVALID, 'strength')
    start, stop = int(strength.offsets[index]), int(strength.offsets[index+1])
    return range(start, stop)


def column_layers(strength, index, declaration, gravity_m_s2):
    """The I01 layer dicts (top down) of piece ``index``; the stress of each layer boundary is P2's."""
    rows = list(piece_rows(strength, index))[::-1]
    layers = []
    for row in rows:
        t = float(strength.thickness_m[row])
        top, bottom = float(strength.vertical_stress_top_pa[row]), float(strength.vertical_stress_bottom_pa[row])
        if not t > 0:
            raise StrengthRefused('a sublayer of piece %r has no thickness' % (strength.pieces[index],),
                                  UNSUPPORTED, 'thickness_m')
        density = (bottom-top)/(gravity_m_s2*t)
        if not (math.isfinite(density) and density > 0):
            raise StrengthRefused('a sublayer of piece %r has no positive effective density'
                                  % (strength.pieces[index],), UNSUPPORTED, 'vertical_stress')
        material = declaration.material(strength.material_ids[row])
        creep = declaration.creep(strength.creep_law_ids[row])
        temperature, pore = float(strength.temperature_k[row]), float(strength.pore_pressure_pa[row])
        layers.append(dict(name='%s:%s:%d' % (strength.pieces[index][0], strength.pieces[index][1], row),
                           thickness_m=t, temperature_k=[temperature, temperature], density_kg_m3=density,
                           pore_pressure_pa=[pore, pore], grain_m=material.grain_m, cohesion_pa=material.cohesion_pa,
                           friction_rad=material.friction_rad,
                           plastic_viscosity_pa_s=material.plastic_viscosity_pa_s, creep=creep.dicts()))
    return layers, rows


def prepare_column(strength, index, declaration, gravity_m_s2):
    """The prepared I01 column of one piece, with its rows (top down) and the per-point weakening law arrays.

    The lithostatic stress the kernel integrates must equal P2's at every layer boundary within the rounding of the
    two summation orders (4 n eps of the base stress); the weakening law must be certified for the column (history
    never raises yield)."""
    layers, rows = column_layers(strength, index, declaration, gravity_m_s2)
    try:
        prep = _weak.prepare(layers, declaration.order, closure=_weak.LITHOSTATIC, gravity=gravity_m_s2)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StrengthRefused('the I01 column of piece %r is refused: %s' % (strength.pieces[index], exc),
                              UNSUPPORTED, str(exc)) from None
    base = float(strength.vertical_stress_bottom_pa[rows[-1]])
    bound = 4*len(rows)*EPS*base
    stress, top = 0., 0.
    for layer, row in zip(layers, rows):
        stress = top+layer['density_kg_m3']*gravity_m_s2*layer['thickness_m']
        if abs(stress-float(strength.vertical_stress_bottom_pa[row])) > bound:
            raise StrengthRefused('the column does not reproduce P2\'s vertical stress', STALE, 'vertical_stress')
        top = stress
    materials = [declaration.material(strength.material_ids[row]) for row in rows]
    laws = tuple(m.law() for m in materials)
    for layer_index, law in enumerate(laws):
        mask = prep.layer == layer_index
        sub = _Subset(prep, mask)
        try:
            law.certify(sub)
        except ValueError as exc:
            raise StrengthRefused('the weakening law of %r is not certified: %s'
                                  % (strength.material_ids[rows[layer_index]], exc), UNSUPPORTED,
                                  'weakening') from None
    return prep, rows, laws


class _Subset:
    """The certify() view of one layer of a prepared column."""

    def __init__(self, prep, mask):
        self.plastic, self.cohesion_pa, self.friction_rad = prep.plastic[mask], prep.cohesion_pa[mask], \
            prep.friction_rad[mask]


def point_factors(prep, laws, kappa_bar):
    """Per-point (lambda_C, lambda_phi) from each layer's own weakening law on the nonlocal history."""
    kappa_bar = np.asarray(kappa_bar, dtype=float)
    if kappa_bar.shape != (prep.size,) or not np.all(np.isfinite(kappa_bar)) or np.any(kappa_bar < 0):
        raise StrengthRefused('the nonlocal history must be finite and nonnegative at every point', INVALID, 'kappa')
    cohesion, friction = np.ones(prep.size), np.ones(prep.size)
    for layer_index, law in enumerate(laws):
        mask = prep.layer == layer_index
        c, f = law.factors(kappa_bar[mask])
        cohesion[mask], friction[mask] = c, f
    return cohesion, friction


# ---------------------------------------------------------------------------------------------------------------
# The oblique stress solve: the package's vectorised safeguarded Newton in log stress (_integration_weakening.stresses)
# with the pressure-closure sign replaced by c = a/e in [-1, 1]. At c = +-1 it is that solver; the same tolerances,
# brackets and refusals apply.

def oblique_stresses(prep, factors, e, c, guess=None):
    """Point stresses s for invariant rate e > 0 and closure fraction c (P = sigma_v - c s)."""
    e = _real(e, 'invariant rate', positive=True)
    c = _real(c, 'closure fraction')
    if not -1. <= c <= 1.:
        raise StrengthRefused('the closure fraction lies in [-1, 1]', INVALID, 'c')
    le = math.log(e)
    lam_c, lam_f = factors
    friction = prep.friction_rad*lam_f
    cc, sp = prep.cohesion_pa*lam_c*np.cos(friction), np.sin(friction)
    try:
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            inv = np.where(prep.plastic, np.exp(-math.log(2)-np.log(prep.eta)-le), 0.)
            hi = np.where(prep.active, (le-prep.log_c)/prep.exponent, np.inf).min(axis=1)
            y0 = cc+np.maximum(prep.reference_pa-prep.pore_pa, 0.)*sp
            plastic_bound = np.logaddexp(math.log(2)+np.log(prep.eta)+le, np.log(y0))
            hi = np.where(prep.plastic, np.minimum(hi, plastic_bound), hi)
            lo = hi-np.log(prep.active.sum(axis=1)+prep.plastic)
            if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and lo.min() > -700 and hi.max() < 700):
                raise ValueError("stress outside bounded representable support")
            for _ in range(64):
                out = _weak._evaluate(prep, hi, le, c, cc, sp, inv)
                short = out["total"] < 1.
                if not short.any():
                    break
                hi = np.where(short, hi+math.log(2), hi)
            else:
                raise ValueError("no upper stress bracket within the supported range")
            if np.any(out["slope_min"] <= 0):
                raise ValueError("creep rate is not monotone in stress under the compressive pressure closure")
            for _ in range(64):
                out = _weak._evaluate(prep, lo, le, c, cc, sp, inv)
                long = out["total"] > 1.
                if not long.any():
                    break
                lo = np.where(long, lo-math.log(2), lo)
            else:
                raise ValueError("no lower stress bracket within the supported range")
            x = hi.copy() if guess is None else np.where((guess > lo) & (guess < hi), guess, hi)
            done = np.zeros(prep.size, dtype=bool)
            for iteration in range(ITERATIONS):
                out = _weak._evaluate(prep, x, le, c, cc, sp, inv)
                residual = out["total"]-1.
                done |= np.abs(residual) <= TOL
                if done.all():
                    break
                open_ = ~done
                hi = np.where(open_ & (residual > 0), x, hi)
                lo = np.where(open_ & (residual <= 0), x, lo)
                trial = x-np.log(out["total"])/(out["derivative"]/out["total"])
                candidate = np.where((trial > lo) & (trial < hi), trial, (lo+hi)/2)
                if np.any(open_ & (candidate == x)):
                    x, out, extra = _weak._refine_stress(prep, x, lo, hi, out, le, c, cc, sp, inv,
                                                         ITERATIONS-iteration-1)
                    iteration += extra
                    break
                x = np.where(open_, candidate, x)
            else:
                raise ValueError("vectorised creep/plasticity solve did not converge")
        s = out["s"]
        tangent = s/(e*out["derivative"])
        if not np.all(np.isfinite(tangent) & (tangent > 0)):
            raise ValueError("constitutive tangent not representable")
    except ValueError as exc:
        raise StrengthRefused('the belt column is outside the I01 kernel\'s support: %s' % exc, UNSUPPORTED,
                              str(exc)) from None
    return dict(x=x, stress=s, creep_rate=e*out["creep"], plastic_rate=e*out["plastic"], yield_pa=out["yield_pa"],
                tangent=tangent, derivative=out["derivative"], iterations=iteration+1)


def closure_sensitivity(prep, factors, e, c, local):
    """ds/dc at fixed e per point: -s (d total/dc)/(d total/d ln s), from _evaluate's own terms (ruling C1).

    At fixed s, d(total)/dc = s sum_i V_i/(R T) scaled_i (the pressure P = sigma_v - c s in each creep law's activation
    term) + s sin(phi) inv where the point yields with P_eff > 0 (the friction term of Y)."""
    s, x = local['stress'], local['x']
    le = math.log(e)
    lam_c, lam_f = factors
    friction = prep.friction_rad*lam_f
    cc, sp = prep.cohesion_pa*lam_c*np.cos(friction), np.sin(friction)
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        inv = np.where(prep.plastic, np.exp(-math.log(2)-np.log(prep.eta)-le), 0.)
        scaled = np.exp(prep.log_c+prep.exponent*x[:, None]-le+c*prep.volume_rt*s[:, None])
    scaled = np.where(prep.active, scaled, 0.)
    dcreep = s*(prep.volume_rt*scaled).sum(axis=1)
    effective = prep.reference_pa-prep.pore_pa-c*s
    yielding = prep.plastic & (s-(cc+np.maximum(effective, 0.)*sp) > 0)
    dplastic = np.where(yielding & (effective > 0), s*sp*inv, 0.)
    return -s*(dcreep+dplastic)/local['derivative']


def resultant(prep, factors, e, c, guess=None):
    """S(e; c) = sum_q w_q s_q (N/m), dS/de and dS/dc at fixed c and e respectively, with the point solution."""
    local = oblique_stresses(prep, factors, e, c, guess)
    w = prep.weight
    return (math.fsum(w*local['stress']), math.fsum(w*local['tangent']),
            math.fsum(w*closure_sensitivity(prep, factors, e, c, local)), local)


START_RATE = 1e-15        # first iterate of a rate search only; brackets and tolerances decide the result


def _bracket(evaluate, x, target, step=math.log(10.)):
    """Step by a fixed factor (ten for rates) from x until evaluate() brackets target, at most 64 steps; (lo, hi) in
    log space. The resultant varies weakly with rate where the belt is plastic, so its bracket steps by two."""
    value = evaluate(x)
    lo = hi = None
    for _ in range(64):
        if value < target:
            lo = x
            if hi is not None:
                return lo, hi
            x += step
        else:
            hi = x
            if lo is not None:
                return lo, hi
            x -= step
        value = evaluate(x)
    raise StrengthRefused('no bracket for the belt resultant within the supported range', NONCONVERGED, 'bracket')


def invert_resultant(prep, factors, target, c, *, guess=None):
    """(e, S, dS/de, dS/dc, points) with S(e; c) = target: a geometric bracket, then safeguarded Newton in log e (S is
    strictly increasing in e where the kernel's monotonicity checks pass), to the column's relative tolerance. The
    start is a fixed first iterate (START_RATE) unless ``guess`` is given from committed records."""
    target = _real(target, 'resultant', positive=True)
    cache = {}

    def evaluate(x):
        if x not in cache:
            cache[x] = resultant(prep, factors, math.exp(x), c)
        return cache[x][0]
    start = math.log(guess) if guess else math.log(START_RATE)
    lo, hi = _bracket(evaluate, start, target)
    x = hi
    for _ in range(ITERATIONS):
        evaluate(x)
        value, slope, sensitivity, local = cache[x]
        residual = value/target-1.
        if abs(residual) <= TOL:
            return math.exp(x), value, slope, sensitivity, local
        if residual > 0:
            hi = x
        else:
            lo = x
        trial = x+(target-value)/(slope*math.exp(x))
        if not lo < trial < hi:
            trial = (lo+hi)/2
        if trial == x:
            break
        x = trial
    raise StrengthRefused('the belt column rate for resultant %r did not converge' % target, NONCONVERGED, 'rate')


# ---------------------------------------------------------------------------------------------------------------
# The nonlocal history on a belt line: cell-centred finite volumes on the cells' own lengths dy_k, zero flux at both
# closed belt sides. With equal cells it is damage_regularisation's matrix (diagonal 1 + 2s, ends 1 + s, off -s,
# s = (ell/dx)^2) times dx. Well balanced: a constant is split off before the solve and restored after, so a uniform
# history stays exactly uniform. Raw kappa is an input only.

def line_operator(lengths, ell):
    """(diagonal, off-diagonal) of the symmetric M-matrix A with A kbar = D kappa, D = diag(dy)."""
    dy = np.asarray(lengths, dtype=float)
    if dy.ndim != 1 or dy.size < 1 or not np.all(np.isfinite(dy)) or np.any(dy <= 0):
        raise StrengthRefused('belt cells need positive lengths', INVALID, 'cells')
    ell = _real(ell, 'D2 length', positive=True)
    coupling = ell*ell/((dy[:-1]+dy[1:])/2)
    diagonal = dy.copy()
    diagonal[:-1] += coupling
    diagonal[1:] += coupling
    return diagonal, -coupling


def _tridiagonal(diagonal, off, rhs):
    """Thomas algorithm for a symmetric diagonally dominant tridiagonal system (no pivoting is needed)."""
    n = diagonal.size
    if n == 1:
        return rhs/diagonal
    c, d = np.empty(n), np.empty(n)
    c[0], d[0] = off[0]/diagonal[0], rhs[0]/diagonal[0]
    for i in range(1, n):
        denominator = diagonal[i]-off[i-1]*c[i-1]
        c[i] = off[i]/denominator if i < n-1 else 0.
        d[i] = (rhs[i]-off[i-1]*d[i-1])/denominator
    out = np.empty(n)
    out[-1] = d[-1]
    for i in range(n-2, -1, -1):
        out[i] = d[i]-c[i]*out[i+1]
    return out


def nonlocal_line(kappa, lengths, ell):
    """kappa_bar on one run of cells (zero flux at both ends), well balanced."""
    kappa = np.asarray(kappa, dtype=float)
    lengths = np.asarray(lengths, dtype=float)
    if kappa.shape != lengths.shape or not np.all(np.isfinite(kappa)) or np.any(kappa < 0):
        raise StrengthRefused('raw history must be finite, nonnegative and one value per cell', INVALID, 'kappa')
    diagonal, off = line_operator(lengths, ell)
    reference = float(kappa[0])
    deviation = kappa-reference
    if not np.any(deviation):
        return np.full(kappa.shape, reference)
    value = _tridiagonal(diagonal, off, lengths*deviation)+reference
    # Independent residual from flux differences (not the solver's factors), as damage_regularisation checks.
    flux = -off*np.diff(value)
    residual = lengths*(value-kappa)
    residual[:-1] -= flux
    residual[1:] += flux
    scale = max(float(np.max(np.abs(kappa))), float(np.max(np.abs(value))), np.finfo(float).tiny)
    size = float(np.max(lengths))+4*float(np.max(np.abs(off), initial=0.))
    if float(np.max(np.abs(residual))) > 128*EPS*size*scale or float(np.min(value)) < 0:
        raise StrengthRefused('the nonlocal history solve failed its residual or positivity check', NONCONVERGED,
                              'nonlocal')
    return value


def nonlocal_points(columns, ell):
    """kappa_bar at every Gauss point of every cell on one line.

    ``columns`` lists, in line order, (dy, point depths, (layer tops, layer bottoms) top down, raw kappa per layer).
    At each point depth z the operator acts across every cell, with kappa_j(z) the raw history of cell j's sublayer
    holding z (half-open [top, bottom)). A depth below any crossed cell's base has no history there, so the belt refuses
    'unresolved belt' (ruling B1(2)): there is no extrapolation and no depth filter (I01_WEAKENING)."""
    floor = min(float(bottoms[-1]) for _, _, (_, bottoms), _ in columns)
    if any(float(z) >= floor for _, depths, _, _ in columns for z in depths):
        raise StrengthRefused('a belt Gauss depth lies below the base of a crossed column: kappa is undefined there',
                              UNRESOLVED_BELT, 'depth')
    out = [np.empty(len(depths)) for _, depths, _, _ in columns]
    lookups = [(np.asarray(tops, dtype=float), np.asarray(kappa, dtype=float)) for _, _, (tops, _), kappa in columns]
    lengths = [dy for dy, _, _, _ in columns]
    for z in sorted({float(z) for _, depths, _, _ in columns for z in depths}):
        values = [float(k[np.searchsorted(tops, z, side='right')-1]) for tops, k in lookups]
        result = nonlocal_line(values, lengths, ell)
        for i, (_, depths, _, _) in enumerate(columns):
            mask = np.asarray(depths, dtype=float) == z
            if mask.any():
                out[i][mask] = result[i]
    return out


# ---------------------------------------------------------------------------------------------------------------
# Belt geometry: the normal line through each trace edge midpoint, walked face by face with exact great-circle
# intersections, clipped at -w/2 and +w/2. The line follows the physical boundary; the mesh only discretises it.

@dataclass(frozen=True, slots=True)
class Cell:
    """One belt cell: the face crossed, the plate side ('left' or 'right') and its interval [y0, y1] (m) on the line
    (y < 0 on the left plate)."""
    face_id: str
    side: str
    y0: float
    y1: float

    @property
    def length_m(self):
        return self.y1-self.y0


def _crossing(m, nu, q, u, v, phi_in):
    """The first angle phi > phi_in at which the line r(phi) = cos(phi) m + sin(phi) nu leaves through arc u -> v,
    or None."""
    pole = np.cross(u, v)
    norm = float(np.linalg.norm(pole))
    if norm == 0.:
        return None
    pole /= norm
    x = np.cross(q, pole)
    size = float(np.linalg.norm(x))
    if size <= S.ATTACHMENT_BAND_RAD:
        return None
    x /= size
    best = None
    for point in (x, -x):
        phi = math.atan2(float(point @ nu), float(point @ m))
        if not phi > phi_in:
            continue
        if (float(np.cross(u, point) @ pole) < -S.ATTACHMENT_BAND_RAD
                or float(np.cross(point, v) @ pole) < -S.ATTACHMENT_BAND_RAD):
            continue
        if min(float(np.linalg.norm(point-u)), float(np.linalg.norm(point-v))) <= S.ATTACHMENT_BAND_RAD:
            raise StrengthRefused('a belt line passes through a vertex', UNRESOLVED_BELT, 'vertex')
        if best is None or phi < best:
            best = phi
    return best


def _walk(network, owner, directions, index, m, nu, start_edge, plate, limit):
    """Cells (face, phi_in, phi_out) along r(phi) = cos(phi) m + sin(phi) nu for phi in [0, limit], entering the face
    on the far side of ``start_edge`` (a directed ring edge of the face behind the line).

    Leaving the plate through another edge means the line re-crosses a plate-boundary trace within w/2 (a bend, an
    offset smaller than w, or a junction neighbourhood): it refuses 'unresolved belt' (ruling B1(3))."""
    q = np.cross(m, nu)
    q /= np.linalg.norm(q)
    faces = {face.face_id: face for face in network.faces}
    cells, phi_in, entry = [], 0., start_edge
    face_id = owner.get((entry[1], entry[0]))
    for _ in range(len(faces)+1):
        if face_id is None:
            raise StrengthRefused('a belt line leaves the network', UNRESOLVED_BELT, 'face')
        face = faces[face_id]
        if face.plate_id != plate:
            raise StrengthRefused('a belt line re-crosses a plate-boundary trace within w/2 (into plate %r): bends, '
                                  'offsets smaller than w and junction belts are unresolved' % face.plate_id,
                                  UNRESOLVED_BELT, 'trace')
        best = None
        for ring in (face.vertex_ids,)+tuple(face.holes):
            for a, b in zip(ring, ring[1:]+ring[:1]):
                if (a, b) == (entry[1], entry[0]):
                    continue
                phi = _crossing(m, nu, q, directions[index[a]], directions[index[b]], phi_in)
                if phi is not None and (best is None or phi < best[0]):
                    best = (phi, (a, b))
        if best is None:
            raise StrengthRefused('a belt line has no exit from face %r' % face_id, UNRESOLVED_BELT, 'face')
        phi_out, edge = best
        if phi_out >= limit-S.ATTACHMENT_BAND_RAD:      # a face edge on the belt side, within I03's band, ends it
            cells.append((face_id, phi_in, limit))
            return cells
        cells.append((face_id, phi_in, phi_out))
        phi_in, entry = phi_out, edge
        face_id = owner.get((edge[1], edge[0]))
    raise StrengthRefused('a belt line did not close', UNRESOLVED_BELT, 'walk')


def edge_vertices(network, support, edge):
    """The (a, b) vertex IDs of trace edge ``edge``, in its boundary record's direction."""
    boundary = network.boundaries[int(support.edge_boundary[edge])]
    chain = list(boundary.vertex_ids)
    pairs = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
    first = int(np.flatnonzero(support.edge_boundary == support.edge_boundary[edge])[0])
    return pairs[edge-first]


def belt_cells(network, support, edge, width_m, side='both'):
    """The belt cells of trace edge ``edge`` for physical width w: left cells (y < 0), then right cells, in line order.

    The left plate lies toward a x b; nu_left = unit(b x a) points to the right plate. The right walk enters the face
    on the right of a -> b (the face whose ring holds b -> a); the left walk the face whose ring holds a -> b."""
    from .integration_properties import _faces_of_edges
    if type(support) is not P.TraceSupport or support.network_id != network.network_id:
        raise StrengthRefused('the trace support of this network is required', STALE, 'support')
    owner = _faces_of_edges(network)
    index = {vertex: i for i, vertex in enumerate(network.vertex_ids)}
    directions = np.asarray(network.vertex_direction, dtype=float)
    a_id, b_id = edge_vertices(network, support, edge)
    m, nu = np.asarray(support.midpoint[edge], dtype=float), np.asarray(support.nu_left[edge], dtype=float)
    radius = float(network.sphere.radius_m)
    limit = width_m/(2*radius) if side == 'both' else width_m/radius
    if not limit < math.pi/2:
        raise StrengthRefused('a belt half-width reaches a quarter of the sphere', UNSUPPORTED, 'width')
    left_plate, right_plate = support.plates[edge]
    right = _walk(network, owner, directions, index, m, nu, (a_id, b_id), right_plate, limit) \
        if side != 'left' else []
    left = _walk(network, owner, directions, index, m, -nu, (b_id, a_id), left_plate, limit) \
        if side != 'right' else []
    cells = [Cell(face, 'left', -radius*hi, -radius*lo) for face, lo, hi in reversed(left)]
    cells += [Cell(face, 'right', radius*lo, radius*hi) for face, lo, hi in right]
    return tuple(cells)


# ---------------------------------------------------------------------------------------------------------------
# One belt line assembled from P2 and solved for a velocity jump.

_P2_FIELDS = ('thickness_m', 'temperature_k', 'vertical_stress_bottom_pa', 'vertical_stress_top_pa',
              'pore_pressure_pa', 'kappa')


def _content(strength, index):
    """P2 content of one piece, for the bitwise identity of the pieces of one face."""
    rows = piece_rows(strength, index)
    return (tuple(getattr(strength, name)[rows.start:rows.stop].tobytes() for name in _P2_FIELDS),
            strength.material_ids[rows.start:rows.stop], strength.creep_law_ids[rows.start:rows.stop])


def face_pieces(strength):
    """{face_id: [piece indices]} on the P2 piece support."""
    out = {}
    for index, (face, _) in enumerate(strength.pieces):
        out.setdefault(face, []).append(index)
    return out


@dataclass(frozen=True, eq=False, slots=True)
class LineCell:
    """A belt cell with its column: the face, the pieces it stands for (bitwise identical P2 content), the prepared
    I01 column, its P2 rows (top down), per-layer weakening laws, layer depths, raw kappa per layer and the column's
    lithostatic stress integral (N/m) for the within-belt GPE omission report."""
    cell: Cell
    pieces: tuple
    prep: object
    rows: tuple
    laws: tuple
    tops: np.ndarray
    bottoms: np.ndarray
    kappa: np.ndarray
    sigma_v_integral: float


@dataclass(frozen=True, eq=False, slots=True)
class Line:
    """The belt line of one trace edge: its cells in line order, the edge midpoint m, the normal nu toward the right
    plate, the along-strike direction t = m x nu (from a toward b), the edge length (m), its belt and the cohorts whose
    bond support is unresolved (reported, ruling P4)."""
    edge: int
    boundary_id: str
    belt: Belt
    cells: tuple
    midpoint: np.ndarray
    normal: np.ndarray
    tangent: np.ndarray
    length_m: float
    unresolved_bonds: tuple


def build_line(network, support, strength, declaration, gravity_m_s2, edge, *, columns=None, bonds=None):
    """Assemble the belt line of trace edge ``edge``. ``columns`` caches prepared columns by piece index; ``bonds``
    maps cohort IDs to their BondRecord.bond ('BONDED', 'BROKEN' or 'UNRESOLVED').

    A BROKEN cohort refuses 'unsupported': its residual state is broken-surface sliding with zero cohesion, and
    treating it as intact would be implicit rewelding (IN-04). D2 never observes or changes a bond latch in v1."""
    boundary_id = support.boundary_ids[int(support.edge_boundary[edge])]
    belt = declaration.belt(boundary_id)
    if belt is None:
        raise StrengthRefused('boundary %r declares no D2 belt' % boundary_id, MISSING, 'belts')
    cells = belt_cells(network, support, edge, belt.width_m, belt.side)
    by_face = face_pieces(strength)
    columns = {} if columns is None else columns
    bonds = {} if bonds is None else bonds
    out, unresolved = [], set()
    for cell in cells:
        held = by_face.get(cell.face_id)
        if not held:
            raise StrengthRefused('belt face %r holds no material' % cell.face_id, UNRESOLVED_COLUMN, cell.face_id)
        first = _content(strength, held[0])
        if any(_content(strength, index) != first for index in held[1:]):
            raise StrengthRefused('belt face %r holds pieces of different strength content; no history or column '
                                  'is averaged' % cell.face_id, UNRESOLVED_COLUMN, cell.face_id)
        for index in held:
            cohort = strength.pieces[index][1]
            state = bonds.get(cohort)
            if state == 'BROKEN':
                raise StrengthRefused('belt cohort %r is BROKEN: broken-surface sliding has zero cohesion and is not '
                                      'an intact belt column (no implicit rewelding, IN-04)' % cohort, UNSUPPORTED,
                                      'bond')
            if state == 'UNRESOLVED':
                unresolved.add(cohort)
        if held[0] not in columns:
            columns[held[0]] = prepare_column(strength, held[0], declaration, gravity_m_s2)
        prep, rows, laws = columns[held[0]]
        thickness = np.array([float(strength.thickness_m[row]) for row in rows])
        bottoms = np.cumsum(thickness)
        tops = bottoms-thickness
        kappa = np.array([float(strength.kappa[row]) for row in rows])
        sigma = math.fsum(prep.weight*prep.reference_pa)
        out.append(LineCell(cell, tuple(held), prep, tuple(rows), laws, tops, bottoms, kappa, sigma))
    a_id, b_id = edge_vertices(network, support, edge)
    index = {vertex: i for i, vertex in enumerate(network.vertex_ids)}
    directions = np.asarray(network.vertex_direction, dtype=float)
    a, b = directions[index[a_id]], directions[index[b_id]]
    radius = float(network.sphere.radius_m)
    theta = 2*math.atan2(float(np.linalg.norm(a-b)), float(np.linalg.norm(a+b)))
    m, nu = np.asarray(support.midpoint[edge], dtype=float), np.asarray(support.nu_left[edge], dtype=float)
    return Line(edge, boundary_id, belt, tuple(out), m, nu, np.cross(m, nu), radius*theta, tuple(sorted(unresolved)))


def line_history(line):
    """kappa_bar at each cell's Gauss points (raw kappa is read, never written)."""
    columns = [(c.cell.length_m, c.prep.depth_m, (c.tops, c.bottoms), c.kappa) for c in line.cells]
    return nonlocal_points(columns, line.belt.length_m)


def width_2sigma(line):
    """The closures width metric on the line: 2 sqrt(second moment of kappa), kappa the cell's depth-mean raw
    history weighted by dy (tools/check_i01_closures.py:218); None where no history is held."""
    y = np.array([(c.cell.y0+c.cell.y1)/2 for c in line.cells])
    dy = np.array([c.cell.length_m for c in line.cells])
    h = np.array([math.fsum((c.bottoms-c.tops)*c.kappa)/float(c.bottoms[-1]) for c in line.cells])*dy
    total = math.fsum(h)
    if total <= 0:
        return None
    centre = math.fsum(y*h)/total
    return 2*math.sqrt(math.fsum((y-centre)**2*h)/total)


def increment_width(line, response):
    """The localisation width of the interval's weakening on the line: 2 sqrt(second moment) of the depth-mean plastic
    rate per cell weighted by dy (the increment profile, as the closures tool and Case B length measure it); None when
    nothing yields. Reported, not gated."""
    if response['u'] == 0. or response['points'][0] is None:
        return None
    y = np.array([(c.cell.y0+c.cell.y1)/2 for c in line.cells])
    h = np.array([float(np.sum(c.prep.weight*p['plastic_rate'])/np.sum(c.prep.weight))*c.cell.length_m
                  for c, p in zip(line.cells, response['points'])])
    total = math.fsum(h)
    if not total > 0:
        return None
    centre = math.fsum(y*h)/total
    return 2*math.sqrt(math.fsum((y-centre)**2*h)/total)


def _zero(line, factors):
    """U = 0: the explicit continuous zero limit (f = 0, S = 0, no increment or dissipation); no kernel call and
    c = 0/0 is never formed (ruling B2(1))."""
    return dict(traction=np.zeros(3), resultant=0., c=None, u=0., sign=0., rates=[0.]*len(line.cells),
                points=[None]*len(line.cells), power=0., column_power=0., slope=None, sensitivity=None,
                factors=factors, u_residual=0., width=math.fsum(c.cell.length_m for c in line.cells),
                gpe_ratio=None)


def solve_line(line, dv, *, history=None):
    """The belt response to the velocity jump dv = v_R - v_L (m/s, at the midpoint, tangent to the sphere).

    Returns the traction on the left plate f (N/m; the right plate takes -f), the common resultant S and closure
    fraction c, U, the per-cell invariant rates and point solutions, the power per length f.dv = 2 S U, the column
    work per length sum dy 2 e_k S, the exact tangents dS/dU and dS/dc (at fixed U), the U residual and the within-belt
    GPE omission ratio max_k |integral sigma_v,k dz - mean| / S. The resultant is solved on S to the kernel's 2e-11
    (ruling C2(2))."""
    dv = np.asarray(dv, dtype=float)
    dv_n, dv_t = float(dv @ line.normal), float(dv @ line.tangent)
    u = math.hypot(dv_n, dv_t/2)
    factors = [point_factors(c.prep, c.laws, kb) for c, kb in zip(line.cells, line_history(line)
                                                                     if history is None else history)]
    if u == 0.:
        return _zero(line, factors)
    c = max(-1., min(1., dv_n/u))
    sign = math.copysign(1., dv_t) if dv_t else 0.
    lengths = [cell.cell.length_m for cell in line.cells]
    cache = {}

    def compatibility(x):
        if x not in cache:
            rows = [invert_resultant(cell.prep, f, math.exp(x), c) for cell, f in zip(line.cells, factors)]
            cache[x] = (math.fsum(dy*row[0] for dy, row in zip(lengths, rows)), rows)
        return cache[x][0]
    width = math.fsum(lengths)
    start = math.log(resultant(line.cells[0].prep, factors[0], START_RATE, c)[0])
    lo, hi = _bracket(compatibility, start, u, math.log(2.))
    x = hi
    for _ in range(ITERATIONS):
        compatibility(x)
        total, rows = cache[x]
        if total > u:
            hi = x
        elif total < u:
            lo = x
        # Newton in ln S: dU/d ln S = S sum dy de_k/dS = S sum dy / (dS_k/de).
        derivative = math.exp(x)*math.fsum(dy/row[2] for dy, row in zip(lengths, rows))
        step = -(total-u)/derivative
        if abs(step) <= S_RELATIVE:           # the estimated relative error of S is at most the kernel's 2e-11
            break
        trial = x+step
        if not lo < trial < hi:
            trial = (lo+hi)/2
        if trial == x:
            break
        x = trial
    else:
        raise StrengthRefused('the belt line of edge %d did not converge on S' % line.edge, NONCONVERGED, 'resultant')
    total, rows = cache[x]
    resultant_ = math.exp(x)
    rates = [row[0] for row in rows]
    points = [row[4] for row in rows]
    du_ds = math.fsum(dy/row[2] for dy, row in zip(lengths, rows))
    de_dc = [-row[3]/row[2] for row in rows]                     # de_k/dc at fixed S
    sensitivity = -math.fsum(dy*d for dy, d in zip(lengths, de_dc))/du_ds   # dS/dc at fixed U
    traction = resultant_*(2*c*line.normal+math.sqrt(max(0., 1-c*c))*sign*line.tangent)
    sigma = [cell.sigma_v_integral for cell in line.cells]
    mean = math.fsum(s*dy for s, dy in zip(sigma, lengths))/width
    return dict(traction=traction, resultant=resultant_, c=c, u=u, sign=sign, rates=rates, points=points,
                power=2*resultant_*u, column_power=math.fsum(dy*2*e*resultant_ for dy, e in zip(lengths, rates)),
                slope=1./du_ds, sensitivity=sensitivity, factors=factors, u_residual=(total-u)/u, width=width,
                gpe_ratio=max(abs(s-mean) for s in sigma)/resultant_)


def traction_tangent(line, response):
    """The exact df/d(dv) (3 x 3, in the tangent plane), including the closure sensitivity dS/dc (ruling C1(1)).

    f = (S/U) A dv with A = 2 nu nu^T + t t^T/2, U^2 = dv.A dv/2 and c = dv.nu/U, so dU/d(dv) = A dv/(2U),
    dc/d(dv) = nu/U - c A dv/(2U^2) and
    df/d(dv) = (S/U) A + (A dv) [ (dS/dU - S/U)/U dU/d(dv) + (dS/dc/U) dc/d(dv) ]^T,
    which is not symmetric when dS/dc != 0. At rest the stiffness is not finite for a nonlinear column; None is returned
    and the caller refuses (an inner iterate never sits at U = 0 unless the forcing is zero, ruling C1(5))."""
    u, s = response['u'], response['resultant']
    if u == 0.:
        return None
    nu, t = line.normal, line.tangent
    a = 2*np.outer(nu, nu)+np.outer(t, t)/2
    dv = response['c']*u*nu+2*response['sign']*math.sqrt(max(0., 1-response['c']**2))*u*t
    adv = a @ dv
    du = adv/(2*u)
    dc = nu/u-response['c']*adv/(2*u*u)
    row = (response['slope']-s/u)/u*du+(response['sensitivity']/u)*dc
    return (s/u)*a+np.outer(adv, row)


# ---------------------------------------------------------------------------------------------------------------
# P6 and P7 from the same integration (port record D-P1). Over an interval dt, at the coupled endpoint (backward
# Euler), each belt cell's Gauss points accumulate dkappa = dt 2 e_p (engineering plastic shear) and the creep and
# plastic energies dt 2 s e_creep and dt 2 s e_p (J/m3). Each crossing deposits on the strip dy x L_e (a line
# quadrature): a piece receives sum (dy L_e / A_face) of its crossings, so a piece outside every belt receives exactly
# zero. The sublayer mean of Gauss increments is the depth discretisation of raw history (ruling B5(2)).

def _layer_means(prep, values):
    """Gauss-weighted mean of per-point values over each layer of a prepared column (top down)."""
    layers = int(prep.layer.max())+1
    out = np.empty(layers)
    for layer in range(layers):
        mask = prep.layer == layer
        out[layer] = math.fsum(prep.weight[mask]*values[mask])/math.fsum(prep.weight[mask])
    return out


def interval_products(lines, responses, strength, piece_areas, dt):
    """(increments, energy, bound) per P2 piece index, each a per-layer array (top down, the cohort record's order).

    ``increments`` is P6's kappa increment, ``energy`` P7's (creep, plastic) energies in J/m3, and ``bound`` the D-P1
    ceiling sum_crossings (dy L_e/A) 2 dt e_k (e_k the cell invariant, uniform in depth), against which every
    increment is checked (ruling B5(1))."""
    dt = _real(dt, 'interval duration', positive=True)
    face_area = {}
    for index, (face, _) in enumerate(strength.pieces):
        face_area[face] = face_area.get(face, 0.)+float(piece_areas[index])
    sums = {}
    for line, response in zip(lines, responses):
        if response['u'] == 0.:
            continue
        for cell, rate, local in zip(line.cells, response['rates'], response['points']):
            prep = cell.prep
            plastic = _layer_means(prep, local['plastic_rate'])
            creep_power = _layer_means(prep, 2*local['stress']*local['creep_rate'])
            plastic_power = _layer_means(prep, 2*local['stress']*local['plastic_rate'])
            share = cell.cell.length_m*line.length_m/face_area[cell.cell.face_id]
            for index in cell.pieces:
                total = sums.setdefault(index, [np.zeros(plastic.size) for _ in range(4)])
                total[0] += share*2*dt*plastic
                total[1] += share*dt*creep_power
                total[2] += share*dt*plastic_power
                total[3] += share*2*dt*rate
    increments, energy, bound = {}, {}, {}
    for index in range(len(strength.pieces)):
        layers = len(piece_rows(strength, index))
        if index in sums:
            inc, creep, plastic, ceiling = sums[index]
        else:
            inc = creep = plastic = ceiling = np.zeros(layers)
        if np.any(inc < 0):
            raise StrengthRefused('a negative kappa increment', UNSUPPORTED, 'negative increment')
        # The kernel solves creep + plastic = e to TOL, so a fully plastic point's rate may exceed e by TOL.
        if np.any(inc > ceiling*(1+TOL+4*EPS)):
            raise StrengthRefused('a kappa increment above 2 integral e dt', UNSUPPORTED, 'increment above 2∫e dt')
        increments[index], energy[index], bound[index] = inc, (creep, plastic), ceiling
    return increments, energy, bound


def event_diagnostics(lines, responses):
    """Per boundary, the stress states that might suggest an event, each with its v1 refusal. Nothing here edits a
    network or creates a Motion event: a stress flag is a report, never a transition (I04.3)."""
    out = {}
    for line, response in zip(lines, responses):
        if response['u'] == 0. or response['points'][0] is None:
            continue
        yielding = all(bool(np.all(local['plastic_rate'] > 0)) for local in response['points'])
        if not yielding or abs(response['c']) <= S.ATTACHMENT_BAND_RAD:
            continue                      # the transform end member (the LODE label's band) suggests no event
        kind = 'separation' if response['c'] > 0 else 'initiation'
        out.setdefault(line.boundary_id, set()).add(EVENT_REFUSALS[kind])
    return {k: sorted(v) for k, v in sorted(out.items())}


def _cross(v):
    """The matrix [v x] with [v x] y = v x y."""
    return np.array([[0., -v[2], v[1]], [v[2], 0., -v[0]], [-v[1], v[0], 0.]])


def _arc_extreme(u, v, pole):
    """The largest angular distance from the great circle with ``pole`` along the minor arc u -> v."""
    angles = [abs(math.asin(max(-1., min(1., float(p @ pole))))) for p in (u, v)]
    normal = np.cross(u, v)
    size = float(np.linalg.norm(normal))
    if size > 0:
        normal /= size
        projected = pole-(pole @ normal)*normal
        norm = float(np.linalg.norm(projected))
        if norm > 0:
            for point in (projected/norm, -projected/norm):
                if float(np.cross(u, point) @ normal) >= 0 and float(np.cross(point, v) @ normal) >= 0:
                    angles.append(abs(math.asin(max(-1., min(1., float(point @ pole))))))
    return max(angles)


class BeltTerm:
    """The D2 belt term of the D1 balance at one state: every trace edge of a belted boundary, its line assembled once
    from that state's P2, and its history (kappa_bar) fixed for the state.

    ``evaluate(omega)`` returns the belt torques (n, 3) on the network's plates, the exact tangent -d tau/d omega
    (3n, 3n; non-symmetric where dS/dc != 0) and a report. Per trace edge, dv = R (omega_R - omega_L) x m; the left
    plate receives R m x f L_e and the right the opposite (midpoint quadrature, so the power identity's belt term is
    f.dv L_e = 2 S U L_e). The last evaluation's responses are kept for P6/P7.

    Coverage (ruling B3): each crossed face's line-quadrature coverage beta = sum dy L_e / A is compared with a
    tolerance derived from that face's geometry: (1/cos h - 1) (the band's leading term) + the great-circle bulge of
    its edges (each edge's distance from the trace beyond its endpoints', times its length, over A) + I03's relative
    area tolerance. beta > 1 + tol refuses 'unresolved belt'; a face whose
    centroid lies within w/2 of a belt's trace edges but which no line crosses refuses too; beta < 1 - tol labels the
    whole result COARSE."""

    def __init__(self, sphere, support, strength, declaration, datum, moving):
        from . import integration_properties as _properties
        if type(sphere).__name__ != 'SphereState':
            raise StrengthRefused('a SphereState is required', INVALID, 'state')
        if type(moving).__name__ != 'MovingState':
            raise StrengthRefused('the I05 moving state of P2 is required (its bonds are checked)', INVALID, 'moving')
        network = sphere.network
        if type(support) is not P.TraceSupport or support.network_id != network.network_id:
            raise StrengthRefused('the trace support of this state\'s network is required', STALE, 'support')
        if type(declaration) is not Declaration:
            raise StrengthRefused('a D2 Declaration is required', INVALID, 'declaration')
        if strength.header.network_id != network.network_id:
            raise StrengthRefused('P2 belongs to another network', STALE, 'network_id')
        if (strength.header.support_id != _properties.piece_support_id(sphere)
                or tuple(strength.pieces) != tuple((p.face_id, p.cohort_id) for p in sphere.material.pieces())):
            raise StrengthRefused('P2 is not on this state\'s piece support', STALE, 'support_id')
        if strength.header.parameter_id != moving.moving_id:
            raise StrengthRefused('P2 was issued from another moving state', STALE, 'parameter_id')
        known = {b.boundary_id for b in network.boundaries}
        unknown = set(dict(declaration.belts)) - known
        if unknown:
            raise StrengthRefused('a belt is declared on unknown boundary %r' % sorted(unknown)[0], INVALID, 'belts')
        self.network_id, self.state_id = network.network_id, sphere.state_id
        self.boundaries = frozenset(dict(declaration.belts))
        self.declaration_id, self.strength_id = declaration.declaration_id, strength.port_id
        self.radius = float(network.sphere.radius_m)
        self.plates = network.plate_ids
        self.order = {plate: i for i, plate in enumerate(self.plates)}
        gravity = float(datum.gravity_m_s2)
        bonds = {c.cohort_id: c.bond.bond for c in moving.cohorts}
        columns = {}
        self.lines = tuple(build_line(network, support, strength, declaration, gravity, e, columns=columns,
                                      bonds=bonds)
                           for e in range(support.edges)
                           if support.boundary_ids[int(support.edge_boundary[e])] in self.boundaries)
        self.histories = tuple(line_history(line) for line in self.lines)
        self.sides = tuple(tuple(self.order[p] for p in support.plates[line.edge]) for line in self.lines)
        self.strength = strength
        self.piece_areas = tuple(p.area_m2 for p in sphere.material.pieces())
        self._coverage(network, support)
        self.last = None

    def _coverage(self, network, support):
        """Check physical coverage on the declared geometric side, not merely on its plate. A plate may wrap
        around a trace endpoint; its faces across the great-circle normal are not in a one-sided belt. The
        point-to-arc footprint (including endpoint caps), missed-face gate and beta tolerance are unchanged."""
        face_area = {}
        for index, (face, _) in enumerate(self.strength.pieces):
            face_area[face] = face_area.get(face, 0.)+float(self.piece_areas[index])
        index = {vertex: i for i, vertex in enumerate(network.vertex_ids)}
        directions = np.asarray(network.vertex_direction, dtype=float)
        faces = {face.face_id: face for face in network.faces}
        covered, tolerance = {}, {}
        poles = []
        for line in self.lines:
            a_id, b_id = edge_vertices(network, support, line.edge)
            a, b = directions[index[a_id]], directions[index[b_id]]
            pole = np.cross(a, b)
            pole /= np.linalg.norm(pole)
            h = line.belt.width_m/(2*self.radius) if line.belt.side == 'both' else line.belt.width_m/self.radius
            left_plate, right_plate = support.plates[line.edge]
            sides = {'both': (left_plate, right_plate), 'left': (left_plate,), 'right': (right_plate,)}
            poles.append((a, b, pole, h, line.belt.side, sides[line.belt.side]))
            for cell in line.cells:
                face_id = cell.cell.face_id
                covered[face_id] = covered.get(face_id, 0.)+cell.cell.length_m*line.length_m
                face = faces[face_id]
                bulge = 0.
                for ring in (face.vertex_ids,)+tuple(face.holes):
                    for u_id, v_id in zip(ring, ring[1:]+ring[:1]):
                        u, v = directions[index[u_id]], directions[index[v_id]]
                        ends = max(abs(math.asin(max(-1., min(1., float(x @ pole))))) for x in (u, v))
                        excess = _arc_extreme(u, v, pole)-ends      # the edge's bulge beyond its endpoints
                        if excess > 0:
                            arc = 2*math.atan2(float(np.linalg.norm(u-v)), float(np.linalg.norm(u+v)))
                            bulge += self.radius*arc*self.radius*excess
                tol = (1/math.cos(h)-1)+bulge/face_area[face_id]+S.RELATIVE_TOLERANCE
                tolerance[face_id] = max(tolerance.get(face_id, 0.), tol)
        self.coverage = {face: covered[face]/face_area[face] for face in sorted(covered)}
        self.tolerance = tolerance
        over = [face for face, beta in self.coverage.items() if beta > 1+tolerance[face]]
        if over:
            raise StrengthRefused('face %r is covered %.6g times by belt strips (beta > 1 + tol): aliasing or '
                                  'overlapping belts' % (over[0], self.coverage[over[0]]), UNRESOLVED_BELT, 'beta')
        crossed = set(covered)
        belted_plates = {p for *_, plates in poles for p in plates}
        for face in network.faces:
            if face.face_id in crossed or face.plate_id not in belted_plates:
                continue
            ring = [directions[index[v]] for v in face.vertex_ids]
            centre = np.sum(ring, axis=0)
            centre /= np.linalg.norm(centre)
            for a, b, pole, h, side, plates in poles:
                signed = float(centre @ pole)       # positive is left of the directed great-circle trace
                if ((side == 'left' and signed < -S.ATTACHMENT_BAND_RAD)
                        or (side == 'right' and signed > S.ATTACHMENT_BAND_RAD)):
                    continue
                if face.plate_id in plates and _point_arc_distance(centre, a, b, pole) < h:
                    raise StrengthRefused('face %r lies within the declared belt footprint but no belt line crosses it'
                                          % face.face_id, UNRESOLVED_BELT, 'missed')
        self.resolved = {face: abs(beta-1) <= tolerance[face] for face, beta in self.coverage.items()}

    def evaluate(self, omega):
        omega = np.asarray(omega, dtype=float).reshape(len(self.plates), 3)
        n = len(self.plates)
        torque, tangent = np.zeros((n, 3)), np.zeros((3*n, 3*n))
        responses, margins = [], []
        for line, history, (left, right) in zip(self.lines, self.histories, self.sides):
            m = line.midpoint
            dv = self.radius*np.cross(omega[right]-omega[left], m)
            response = solve_line(line, dv, history=history)
            responses.append(response)
            if response['u'] == 0.:
                continue
            arm = _cross(m)
            tau = self.radius*line.length_m*(arm @ response['traction'])
            torque[left] += tau
            torque[right] -= tau
            local = traction_tangent(line, response)
            if local is None or not np.all(np.isfinite(local)):
                raise StrengthRefused('the belt tangent is not representable near U = 0', NONCONVERGED, 'tangent')
            plane = np.array([line.normal, line.tangent])
            reduced = plane @ local @ plane.T
            margins.append(float(np.linalg.eigvalsh((reduced+reduced.T)/2)[0]))
            block = self.radius**2*line.length_m*(arm @ local @ arm.T)
            for i, j, sign in ((left, left, 1.), (right, right, 1.), (left, right, -1.), (right, left, -1.)):
                tangent[3*i:3*i+3, 3*j:3*j+3] += sign*block
        self.last = (omega.copy(), tuple(responses))
        return torque, tangent, self.report(responses, margins)

    def report(self, responses, margins=()):
        """Per boundary and in total: dissipation (W) as f.dv L and as column work, edges, peak resultant, plastic
        share, the c range, coverage and resolution, w/H, the raw-history width over H (raw kappa: mostly the inherited
        profile), the interval increment's localisation width, the within-belt GPE omission ratio, the U residual, the
        unresolved bonds and the labels; per-edge symmetric tangent margins (reported, not gated)."""
        per = {}
        for line, response in zip(self.lines, responses):
            item = per.setdefault(line.boundary_id, dict(power=[], column=[], edges=0, peak=0., plastic=[], work=[],
                                                          c=[], beta=[], resolved=True, thickness=0., widths=[],
                                                          gains=[],
                                                          gpe=[], u_residual=0., bonds=set()))
            item['power'].append(response['power']*line.length_m)
            item['column'].append(response['column_power']*line.length_m)
            item['edges'] += 1
            item['peak'] = max(item['peak'], response['resultant'])
            item['u_residual'] = max(item['u_residual'], abs(response['u_residual']))
            item['bonds'] |= set(line.unresolved_bonds)
            if response['c'] is not None:
                item['c'].append(response['c'])
            if response['gpe_ratio'] is not None:
                item['gpe'].append(response['gpe_ratio'])
            width = width_2sigma(line)
            gain = increment_width(line, response)
            if gain is not None:
                item['gains'].append(gain)
            if width is not None:
                item['widths'].append(width)
            for cell, local in zip(line.cells, response['points']):
                face = cell.cell.face_id
                item['beta'].append(self.coverage[face])
                item['resolved'] = item['resolved'] and self.resolved[face]
                item['thickness'] = max(item['thickness'], float(cell.bottoms[-1]))
                if local is not None:
                    w = cell.prep.weight
                    area = cell.cell.length_m*line.length_m
                    item['plastic'].append(area*math.fsum(2*w*local['stress']*local['plastic_rate']))
                    item['work'].append(area*math.fsum(2*w*local['stress']*(local['plastic_rate']
                                                                             + local['creep_rate'])))
        out, labels = {}, {THIN_SHEET}
        for name, item in sorted(per.items()):
            work = math.fsum(item['work'])
            belt = self.declaration_belts()[name]
            # End members within I03's rounding band (64 eps) are classed as end members for this label only; the
            # computation always uses the c it is given.
            oblique = any(S.ATTACHMENT_BAND_RAD < abs(c) < 1-S.ATTACHMENT_BAND_RAD for c in item['c'])
            if oblique:
                labels.add(LODE)
            if not item['resolved']:
                labels.add(COARSE)
            if belt.get('side', 'both') != 'both':
                labels.add(ONE_SIDED)
            out[name] = dict(side=belt.get('side', 'both'), dissipation_w=math.fsum(item['power']),
                             column_work_w=math.fsum(item['column']), edges=item['edges'],
                             peak_resultant_n_m=item['peak'],
                             plastic_share=math.fsum(item['plastic'])/work if work else 0.,
                             c_min=min(item['c']) if item['c'] else None,
                             c_max=max(item['c']) if item['c'] else None,
                             beta_min=min(item['beta']), beta_max=max(item['beta']), resolved=item['resolved'],
                             width_over_thickness=belt['width_m']/item['thickness'],
                             raw_kappa_width_2sigma_over_thickness=(max(item['widths'])/item['thickness']
                                                                    if item['widths'] else None),
                             increment_width_2sigma_m=max(item['gains']) if item['gains'] else None,
                             gpe_omission_ratio=max(item['gpe']) if item['gpe'] else None,
                             u_residual=item['u_residual'], unresolved_bonds=sorted(item['bonds']))
        return dict(dissipation_w=math.fsum(v['dissipation_w'] for v in out.values()),
                    column_work_w=math.fsum(v['column_work_w'] for v in out.values()),
                    u_residual=max([v['u_residual'] for v in out.values()]+[0.]),
                    tangent_margin_min=min(margins) if margins else None, boundaries=out,
                    labels=sorted(labels), declaration_id=self.declaration_id, strength_id=self.strength_id,
                    state_id=self.state_id)

    def declaration_belts(self):
        return {line.boundary_id: line.belt.record() for line in self.lines}

    def normal_strain(self, dt):
        """Per boundary, max_k |a_k| dt over its cells at the last evaluation (a_k = c e_k): the interval's share of the
        cumulative I01 small-strain guard (ruling B4)."""
        if self.last is None:
            raise StrengthRefused('the belt term has not been evaluated', MISSING, 'balance')
        out = {}
        for line, response in zip(self.lines, self.last[1]):
            c = response['c'] or 0.
            value = max([abs(c)*e*dt for e in response['rates']]+[0.])
            out[line.boundary_id] = max(out.get(line.boundary_id, 0.), value)
        return out

    def products(self, dt):
        """P6 increments, P7 energies and the D-P1 bounds from the last evaluation (the converged balance)."""
        if self.last is None:
            raise StrengthRefused('the belt term has not been evaluated', MISSING, 'balance')
        return interval_products(self.lines, self.last[1], self.strength, self.piece_areas, dt)

    def events(self):
        if self.last is None:
            raise StrengthRefused('the belt term has not been evaluated', MISSING, 'balance')
        return event_diagnostics(self.lines, self.last[1])


def _point_arc_distance(point, a, b, pole):
    """Geodesic angle from ``point`` to the minor great-circle arc a -> b with pole ``pole``."""
    projected = point-(point @ pole)*pole
    norm = float(np.linalg.norm(projected))
    if norm > 0:
        foot = projected/norm
        if float(np.cross(a, foot) @ pole) >= 0 and float(np.cross(foot, b) @ pole) >= 0:
            return abs(math.asin(max(-1., min(1., float(point @ pole)))))
    return min(math.acos(max(-1., min(1., float(point @ a)))), math.acos(max(-1., min(1., float(point @ b)))))
