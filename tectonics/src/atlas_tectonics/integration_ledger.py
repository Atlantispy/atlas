"""I02.3/I02.5 accepted-state ledger of the first I02 route: state and exchanges committed together. WORKING NON-CANON.

One ledger holds one root history of the finite-strain column (integration_state) in the native ArrayStore. Each
accepted commit carries the column's accepted state with all of its accounts and, when finite reservoirs are attached,
their current whole stocks, named exterior accounts and the transfer records applied during the commit's interval.

Head coordination adds no table and no second file. A successor is published under a key derived from its parent's
key, and ArrayStore keeps one immutable body per key: an identical body is an idempotent replay and any other body is
a conflict. Publishing the successor of a parent is therefore a compare-and-swap of the accepted head, performed by
ArrayStore.put inside the one SQLite write transaction it opens with BEGIN IMMEDIATE, together with every chunk and the
manifest (arrays, accounts, transfer records and lineage). The ledger's own parent and exactly-once checks run in the
same transaction, just before COMMIT, through put's publication_check. The store uses a rollback journal
(journal_mode=DELETE, synchronous=FULL): until the journal is deleted nothing is committed, and a journal left by an
interrupted commit is rolled back by the next connection. SQLite atomicity covers this one database file only.

Transfers name a producer, a ledger-unique ASCII label, donor, receiver, whole-stock component masses (kg) and signed
enthalpy (J) in the stocks' declared enthalpy basis, and declare the interval of whole global steps they were produced
for; only the commit spanning exactly that interval applies them, so their parent is the accepted commit at the
interval's start. Committing checks finite availability, units, support and basis in exact rational arithmetic, and
debits and credits once: each changed stock is rounded once, from its exact new value, into a new native W08Inventory,
and a change too small to alter a stored stock is refused. Mass or heat entering or leaving the represented stocks is
booked exactly against a declared, named exterior source or sink, and the rounding of the stored stocks is kept as an
exact account, so the closure identity holds exactly. Quantities are declared by their producer: nothing here is a
transport or rate law. The closed column strip itself transfers nothing. Operational timings never enter a commit.

Saving is the commit itself (I02.5). The root stores the reference, initial history and native payloads once; a
successor stores only its current column arrays, its stocks and its transfer index, and content-addressed chunks
share every unchanged payload. Reopening rebuilds the root through its validating constructors, refuses a source or
runtime identity, as its caller declares them, other than the ones recorded with the history, and restores any
commit's column state through integration_state.restore (admitted ranges and the retained step relations) and its
stocks by applying the recorded transfers to the parent's stored stocks again; every identity must reproduce.
Prepared operators are never stored: a Continuation rebuilds them from the pinned inputs.

Every successor record carries the digest of its parent's record, and every read first confirms the whole chain from
the root to the head, re-reading and checking it whenever the store may have changed (its change token), so a stored
commit rewritten without rewriting every later record is refused wherever it is.
Inspection then restores and validates the inspected commit (its snapshot, the root's and, with stocks, its parent's)
before returning any value; no physics runs. The store itself is trusted local state: these checks establish
consistency, not who wrote a record. A well-formed, well-linked record inside the admitted ranges and consistent with
the retained step relations is restored, continued and admitted whoever wrote it, including one appended through
ArrayStore.put; a writer who rewrites the head, or a commit together with every later record, has rewritten the
accepted history. Neither is defended here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from collections.abc import Mapping
import dataclasses
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import math
import re

import numpy as np

from . import integration_state as _state
from ._validation import TectonicsError, scalar
from .materials import _json, _name, _sha
from .resources import select_budget
from .storage import ArrayStore, StoreConflict
from .timebase import advance_time


SCHEMA = 'atlas.i02-ledger.v1'
TRANSFER_SCHEMA = 'atlas.i02-transfer.v1'
EXCHANGE_SCHEMA = 'atlas.i02-exchange.v1'
UNITS = {'enthalpy': 'J', 'mass': 'kg'}          # whole W08 stocks; per-metre strip quantities cannot enter
ROLES = ('source', 'sink')
MAX_TRANSFERS = 64                               # per commit
MAX_APPLIED = 65536                              # transfer labels per ledger; the label index stays bounded
MAX_PATH = _state.MAX_STEPS                      # accepted pieces in one commit
# Finite accounting range of any single quantity or account: sums of up to 2**63 such terms stay finite in binary64.
EXACT_LIMIT = 2.**960
MAX_EXACT_TEXT = 1024                            # characters of one exact n/d account
# Transfer labels and exterior names: ASCII tokens compared exactly, so no Unicode form can alias another.
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z')
_EXACT = re.compile(r'-?[0-9]{1,700}/[0-9]{1,400}\Z')
_DOMAIN = b'atlas.i02-ledger.v1\0'
_LABEL = b'atlas.i02-transfer-label.v1\0'
_KINDS = ('root', 'successor')
# Arrays a successor commit stores; the reference, initial history and native payloads are the root commit's.
CURRENT = ('theta_k', 'kappa', 'yield_stage_counts')
EXCHANGE_ARRAYS = ('exchange.component_mass_kg', 'exchange.enthalpy_j', 'exchange.supplied_kg', 'exchange.supplied_j',
                   'ledger.applied')


class LedgerError(TectonicsError):
    """An invalid proposal, incompatible ledger or refused restoration; nothing was published."""


class LedgerConflict(LedgerError):
    """Stale parent: this parent already has a different accepted successor; nothing was published."""


class ExchangeRefused(LedgerError):
    """A transfer proposal the ledger refuses (its declaration, interval, support, availability or resolution);
    nothing was published. Any other LedgerError of a commit concerns the ledger or its store, not the proposal."""


def _derive(kind, *parts):
    digest = hashlib.sha256(_DOMAIN+kind.encode('ascii'))
    for part in parts:
        digest.update(b'\0'+part.encode('ascii'))
    return digest.hexdigest()


def successor_key(ledger_id, parent_key):
    """The one key under which the accepted successor of ``parent_key`` can be published."""
    return _derive('successor', _sha(ledger_id, 'ledger identity'), _sha(parent_key, 'parent commit'))


def root_key(ledger_id):
    return _derive('root', _sha(ledger_id, 'ledger identity'))


def _label_digest(ledger_id, label):
    return hashlib.sha256(_LABEL+ledger_id.encode('ascii')+b'\0'+label.encode('utf-8')).digest()


def _token(value, label):
    if type(value) is not str or TOKEN.fullmatch(value) is None:
        raise LedgerError(label+' must be an ASCII token of letters, digits and ._:/@+- (compared exactly)')
    return value


def _bounded(value, label):
    if abs(value) > EXACT_LIMIT:
        raise LedgerError(label+' exceeds the finite accounting range')
    return value


def _within(value, label):
    """_bounded for a value a transfer proposal produced: leaving the range refuses the proposal."""
    if abs(value) > EXACT_LIMIT:
        raise ExchangeRefused(label+' would leave the finite accounting range')
    return value


def _exact_text(value):
    text = '%d/%d' % (value.numerator, value.denominator)
    if len(text) > MAX_EXACT_TEXT:
        raise LedgerError('an exact account exceeds its bounded representation')
    return text


def _exact(text, label):
    """A stored exact account: canonical dyadic n/d text within the bounds, as a Fraction."""
    if type(text) is not str or _EXACT.fullmatch(text) is None:
        raise LedgerError(label+': an exact n/d account is required')
    value = Fraction(text)
    if value.denominator & (value.denominator-1) or _exact_text(value) != text:
        raise LedgerError(label+': a canonical dyadic account is required')
    return _bounded(value, label)


def _canonical(value, label):
    try:
        return _json(value)
    except TectonicsError as exc:
        raise LedgerError(label+': finite JSON data required') from exc


class _Issued:
    """Issued by this module only: no public constructor, pickle or copies."""
    __slots__ = ()

    def __init__(self, *args, **kwargs):
        raise TypeError(type(self).__name__+' is issued by a Ledger only')

    def __reduce__(self):
        raise TypeError(type(self).__name__+' is not pickled; it is read back from its native store')

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def _issue(cls, **values):
    item = object.__new__(cls)
    for key, value in values.items():
        object.__setattr__(item, key, value)
    return item


# ----------------------------------------------------------------------------- transfers and exchange accounts

@dataclass(frozen=True, slots=True)
class Transfer:
    """One declared finite exchange proposal over a declared interval of whole global steps.

    ``start_step`` and ``end_step`` declare the interval (start_step, end_step] of the fixed global schedule the
    quantities were produced for; the proposal can only be committed by the commit spanning exactly that interval, so
    its parent is the accepted commit at ``start_step`` of the ledger. That parent's state identity cannot be known
    before the interval is computed; the commit binds it through the ledger's hash chain. ``component_mass_kg`` gives
    one nonnegative whole-stock mass per component of the attached stocks (a mapping or (component, kg) pairs);
    ``enthalpy_j`` is signed and in ``basis``, the stocks' declared enthalpy convention. A transfer moves positive mass,
    or, without mass, positive heat from donor to receiver. Values are captured as plain floats at construction, so
    later edits to caller objects cannot reach the proposal, and every quantity lies in the finite accounting range.
    ``label`` is an ASCII token unique within the ledger and compared exactly. The producer declares the quantities; no
    transport or rate law is implied.
    """
    label: str
    producer: str
    donor: str
    receiver: str
    component_mass_kg: object
    enthalpy_j: float
    basis: str
    start_step: int
    end_step: int
    units: object = (('enthalpy', 'J'), ('mass', 'kg'))

    def __post_init__(self):
        _token(self.label, 'transfer label')
        for name in ('producer', 'donor', 'receiver', 'basis'):
            _name(getattr(self, name), 'transfer '+name)
        if self.donor == self.receiver:
            raise LedgerError('a transfer needs distinct donor and receiver')
        steps = (self.start_step, self.end_step)
        if any(type(step) is not int for step in steps) or not 0 <= self.start_step < self.end_step <= _state.MAX_STEPS:
            raise LedgerError('a transfer declares its interval as whole global steps start_step < end_step')
        masses = self.component_mass_kg
        pairs = list(masses.items()) if isinstance(masses, Mapping) else masses
        if type(pairs) not in (list, tuple) or not pairs:
            raise LedgerError('transfer masses: one (component, kg) value per component required')
        checked = []
        for pair in pairs:
            if type(pair) not in (list, tuple) or len(pair) != 2:
                raise LedgerError('transfer masses: (component, kg) pairs required')
            component, value = pair
            _name(component, 'transfer component')
            if isinstance(value, (bool, np.bool_)) or isinstance(value, np.ndarray):
                raise LedgerError('transfer masses: one plain real number per component')
            checked.append((component, _bounded(scalar(value, 'transfer component mass', nonnegative=True),
                                                'transfer component mass')))
        checked.sort()
        if len({component for component, _ in checked}) != len(checked):
            raise LedgerError('transfer masses: each component once')
        if isinstance(self.enthalpy_j, (bool, np.bool_)) or isinstance(self.enthalpy_j, np.ndarray):
            raise LedgerError('transfer enthalpy: one plain real number')
        enthalpy = _bounded(scalar(self.enthalpy_j, 'transfer enthalpy'), 'transfer enthalpy')
        if not any(value > 0 for _, value in checked) and not enthalpy > 0:
            raise LedgerError('a transfer moves positive mass, or positive heat from its donor to its receiver')
        try:
            units = dict(self.units) if isinstance(self.units, Mapping) or type(self.units) in (list, tuple) else None
        except (TypeError, ValueError):
            units = None
        if units != UNITS:
            raise LedgerError('transfers carry whole-stock kg and J; convert strip or scaled units explicitly')
        object.__setattr__(self, 'component_mass_kg', tuple(checked))
        object.__setattr__(self, 'enthalpy_j', enthalpy)
        object.__setattr__(self, 'units', tuple(sorted(units.items())))


@dataclass(frozen=True, eq=False, init=False, slots=True)
class Exchange(_Issued):
    """Current finite stocks, named exteriors and their exact cumulative accounts at one accepted time; immutable.

    ``inventory`` is the native W08Inventory of current whole stocks (binary64), dated at the commit time and owned by
    the ledger. ``exteriors`` are the declared (name, role) boundaries. Exact rational accounts, never rounded, hold
    the root totals, what each exterior has supplied to the stocks since the root (received amounts are negative) and
    the rounding of the stored stocks: each commit rounds every changed stock once, from its exact new value. The
    closure identity sum(stocks) = initial + sum(supplied) + rounding therefore holds exactly for every component and
    for signed enthalpy. The exact allowance accumulates half a unit in the last place of every stock value a commit
    changes, and so rounds: the most that correct rounding can contribute. The rounding account may never exceed it.
    The float ``supplied_*`` arrays are correctly rounded views for inspection.
    """
    inventory: object
    exteriors: tuple
    exchange_id: str
    _initial: tuple = field(repr=False)
    _supplied: tuple = field(repr=False)
    _rounding: tuple = field(repr=False)
    _allowance: tuple = field(repr=False)
    _supplied_kg: np.ndarray = field(repr=False)
    _supplied_j: np.ndarray = field(repr=False)

    @property
    def initial_kg(self):
        return tuple(float(value) for value in self._initial[0])

    @property
    def initial_j(self):
        return float(self._initial[1])

    @property
    def supplied_kg(self):
        return self._supplied_kg.view()

    @property
    def supplied_j(self):
        return self._supplied_j.view()

    @property
    def rounding_kg(self):
        return tuple(float(value) for value in self._rounding[0])

    @property
    def rounding_j(self):
        return float(self._rounding[1])

    @property
    def allowance_kg(self):
        return tuple(float(value) for value in self._allowance[0])

    @property
    def allowance_j(self):
        return float(self._allowance[1])

    def closure(self):
        """Exact closure: sum(stocks) - initial - sum(supplied) per component (kg) and for signed enthalpy (J).

        The residuals are the rounding of the stored float stocks, reported as floats; ``identity_exact`` is True
        when each equals the ledger's exact rounding account, i.e. nothing was created, lost or booked twice, and
        that account lies within its exact rounding allowance. The rounding is reported, not negligible: a change that
        would round to no change of a stored stock is refused, but otherwise each stored stock is within half a unit
        in the last place of its exact value per commit that changes it, which at a large stock can be comparable to
        a small transfer. Exterior accounts are exact, so an amount moved to a sink is booked exactly while the stock
        it left may be rounded by an amount comparable to it; the difference is in these residuals.
        """
        stocks, energy = self.inventory.component_mass_kg, self.inventory.enthalpy_j
        (initial, initial_j), (supplied, supplied_j), (rounding, rounding_j) = \
            self._initial, self._supplied, self._rounding
        exact, residuals = True, []
        for k in range(len(self.inventory.component_ids)):
            residual = sum((Fraction(x) for x in stocks[:, k]), Fraction(0))-initial[k]-sum(
                (row[k] for row in supplied), Fraction(0))
            exact &= residual == rounding[k]
            residuals.append(float(residual))
        heat = sum((Fraction(x) for x in energy), Fraction(0))-initial_j-sum(supplied_j, Fraction(0))
        allowance, allowance_j = self._allowance
        within = all(abs(r) <= a for r, a in zip(rounding, allowance)) and abs(rounding_j) <= allowance_j
        return dict(component_residual_kg=residuals, enthalpy_residual_j=float(heat),
                    identity_exact=bool(exact and heat == rounding_j and within))

    def descriptor(self):
        (initial, initial_j), (supplied, supplied_j), (rounding, rounding_j) = \
            self._initial, self._supplied, self._rounding
        return dict(schema=EXCHANGE_SCHEMA, exchange_id=self.exchange_id, inventory=self.inventory.descriptor(),
                    inventory_id=self.inventory.inventory_id, exteriors=[list(pair) for pair in self.exteriors],
                    units=UNITS, exact=dict(
                        initial_kg=[_exact_text(v) for v in initial], initial_j=_exact_text(initial_j),
                        supplied_kg=[[_exact_text(v) for v in row] for row in supplied],
                        supplied_j=[_exact_text(v) for v in supplied_j],
                        rounding_kg=[_exact_text(v) for v in rounding], rounding_j=_exact_text(rounding_j),
                        allowance_kg=[_exact_text(v) for v in self._allowance[0]],
                        allowance_j=_exact_text(self._allowance[1])))


def _frozen(array, dtype=np.float64):
    raw = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(raw.tobytes(), dtype=dtype).reshape(raw.shape)


def _exchange(inventory, exteriors, initial, supplied, rounding, allowance):
    """Issue exchange accounts; the identity binds the inventory, exteriors and every exact account."""
    components = len(inventory.component_ids)
    for value in (*initial[0], initial[1], *(v for row in supplied[0] for v in row), *supplied[1], *rounding[0],
                  rounding[1], *allowance[0], allowance[1]):
        _bounded(value, 'an exact exchange account')
    supplied_kg = _frozen(np.array([[float(v) for v in row] for row in supplied[0]],
                                   dtype=np.float64).reshape(len(exteriors), components))
    supplied_j = _frozen(np.array([float(v) for v in supplied[1]], dtype=np.float64))
    item = _issue(Exchange, inventory=inventory, exteriors=exteriors, exchange_id='', _initial=initial,
                  _supplied=supplied, _rounding=rounding, _allowance=allowance, _supplied_kg=supplied_kg,
                  _supplied_j=supplied_j)
    record = item.descriptor()
    del record['exchange_id'], record['inventory']
    object.__setattr__(item, 'exchange_id', hashlib.sha256(_canonical(record, 'exchange record')).hexdigest())
    return item


def _exteriors(value, root):
    """Declared (name, role) exterior boundaries: ASCII tokens that differ, even ignoring case, from every stock node
    and native cohort."""
    if type(value) not in (tuple, list):
        raise LedgerError('exteriors: a sequence of (name, role) pairs required')
    out = []
    for pair in value:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise LedgerError('exteriors: (name, role) pairs required')
        name, role = pair
        _token(name, 'exterior name')
        if role not in ROLES:
            raise LedgerError('an exterior is a named source or sink')
        out.append((name, role))
    names = [name.casefold() for name, _ in out]
    if len(set(names)) != len(names) or len(out) > 64:
        raise LedgerError('at most 64 distinctly named exteriors')
    stocks = () if root.reservoirs is None else root.reservoirs.node_ids
    if set(names) & {name.casefold() for name in (*stocks, *root.layer_cohorts)}:
        raise LedgerError('an exterior name reuses a stock node or a native material cohort')
    if out and root.reservoirs is None:
        raise LedgerError('named exteriors exchange with attached finite reservoirs; none are attached')
    return tuple(sorted(out))


def _owned(inventory, **changes):
    """A W08Inventory the ledger owns, rebuilt from the given one's descriptor and arrays (or ``changes``).

    Rebuilding from an inventory without changes must reproduce its identity: stocks edited behind their identity
    after acceptance refuse instead of being spent.
    """
    from .w08_inventory import W08Inventory
    values = dict(node_ids=inventory.node_ids, node_kinds=inventory.node_kinds, component_ids=inventory.component_ids,
                  component_mass_kg=inventory.component_mass_kg, enthalpy_j=inventory.enthalpy_j,
                  source_id=inventory.source_id, enthalpy_source=inventory.enthalpy_source, time_s=inventory.time_s,
                  formation_time_s=inventory.formation_time_s, origin_ids=inventory.origin_ids)
    values.update(changes)
    try:
        owned = W08Inventory(values.pop('node_ids'), values.pop('node_kinds'), values.pop('component_ids'),
                             values.pop('component_mass_kg'), values.pop('enthalpy_j'), **values)
    except (TectonicsError, OverflowError) as exc:
        raise LedgerError('the stocks are not a valid native inventory: '+str(exc)) from exc
    if not changes and owned.inventory_id != inventory.inventory_id:
        raise LedgerError('stocks changed after they were accepted; their identity no longer reproduces')
    return owned


def _root_exchange(root, exteriors):
    inventory = _owned(root.reservoirs)
    stocks, energy = inventory.component_mass_kg, inventory.enthalpy_j
    for value in (*stocks.flat, *energy):
        _bounded(float(value), 'an initial stock')
    count = len(inventory.component_ids)
    zero = Fraction(0)
    initial = (tuple(sum((Fraction(x) for x in stocks[:, k]), zero) for k in range(count)),
               sum((Fraction(x) for x in energy), zero))
    return _exchange(inventory, exteriors, initial,
                     (tuple((zero,)*count for _ in exteriors), (zero,)*len(exteriors)), ((zero,)*count, zero),
                     ((zero,)*count, zero))


def _intact(exchange):
    """The exchange as accepted: its stocks reproduce their identity and its exact accounts reproduce its own."""
    if type(exchange) is not Exchange:
        raise LedgerError('typed exchange accounts required')
    _owned(exchange.inventory)
    again = _exchange(exchange.inventory, exchange.exteriors, exchange._initial, exchange._supplied,
                      exchange._rounding, exchange._allowance)
    if again.exchange_id != exchange.exchange_id:
        raise LedgerError('exchange accounts changed after they were accepted')
    return exchange


def _apply(ledger_id, parent_key, interval, key, exchange, transfers, applied, end_time):
    """Validate and apply transfers in order, in exact arithmetic, then round every changed stock once.

    Each proposal is validated again at use (however it was built). Balances run exactly, so finite availability is
    exact and a large flow cannot absorb a small one; exterior accounts stay exact. A stock whose exact change is
    nonzero but too small to change its stored binary64 value is refused rather than silently dropped. The rounding of
    each stored stock enters the exact rounding account, so the closure identity holds exactly.
    """
    inventory = _intact(exchange).inventory
    nodes = {name: i for i, name in enumerate(inventory.node_ids)}
    outside = {name: (j, role) for j, (name, role) in enumerate(exchange.exteriors)}
    components = inventory.component_ids
    old, energy = inventory.component_mass_kg, inventory.enthalpy_j
    mass = [[Fraction(x) for x in row] for row in old]
    heat = [Fraction(x) for x in energy]
    supplied = [list(row) for row in exchange._supplied[0]]
    supplied_j = list(exchange._supplied[1])
    touched, records, digests = set(), [], []
    for proposal in transfers:
        if type(proposal) is not Transfer:
            raise ExchangeRefused('typed Transfer proposals required')
        try:
            transfer = dataclasses.replace(proposal)      # validated again at use, however it was built
        except (AttributeError, TypeError) as exc:
            raise ExchangeRefused('an incomplete transfer proposal') from exc
        except TectonicsError as exc:
            raise ExchangeRefused(str(exc)) from exc
        if transfer.basis != inventory.enthalpy_source:
            raise ExchangeRefused("transfer enthalpy basis differs from the stocks' declared convention")
        if tuple(name for name, _ in transfer.component_mass_kg) != components:
            raise ExchangeRefused('transfer components differ from the attached stocks (incompatible inventory)')
        if (transfer.start_step, transfer.end_step) != (interval[2], interval[3]):
            raise ExchangeRefused('a transfer declared for the interval (%d, %d] cannot be committed over (%d, %d]'
                                  % (transfer.start_step, transfer.end_step, interval[2], interval[3]))
        moved = [Fraction(value) for _, value in transfer.component_mass_kg]
        moved_j = Fraction(transfer.enthalpy_j)
        digest = _label_digest(ledger_id, transfer.label)
        if digest in applied or digest in digests:
            raise ExchangeRefused('transfer label already applied in this history: each transfer is applied once')
        ends = []
        for side in (transfer.donor, transfer.receiver):
            if side in nodes:
                ends.append(('node', nodes[side]))
            elif side in outside:
                ends.append(('exterior',)+outside[side])
            else:
                raise ExchangeRefused('transfer donor/receiver is neither an attached stock nor a declared exterior '
                                      '(support mismatch; the closed column strip exchanges no material)')
        donor, receiver = ends
        if donor[0] == receiver[0] == 'exterior':
            raise ExchangeRefused('an exterior-to-exterior transfer is outside the represented accounts')
        if donor[0] == 'exterior' and donor[2] != 'source':
            raise ExchangeRefused('a declared sink cannot be a transfer donor')
        if receiver[0] == 'exterior' and receiver[2] != 'sink':
            raise ExchangeRefused('a declared source cannot be a transfer receiver')
        if donor[0] == 'node':
            d = donor[1]
            balance = [have-give for have, give in zip(mass[d], moved)]
            if any(value < 0 for value in balance):
                raise ExchangeRefused('finite availability: the donor stock holds less than the transfer')
            mass[d], heat[d] = balance, heat[d]-moved_j
            touched.add(d)
        else:
            j = donor[1]
            supplied[j] = [have+give for have, give in zip(supplied[j], moved)]
            supplied_j[j] += moved_j
        if receiver[0] == 'node':
            r = receiver[1]
            mass[r], heat[r] = [have+give for have, give in zip(mass[r], moved)], heat[r]+moved_j
            touched.add(r)
        else:
            j = receiver[1]
            supplied[j] = [have-give for have, give in zip(supplied[j], moved)]
            supplied_j[j] -= moved_j
        record = dict(schema=TRANSFER_SCHEMA, ledger_id=ledger_id, parent_key=parent_key,
                      interval=dict(start_s=interval[0], end_s=interval[1], start_step=interval[2],
                                    end_step=interval[3]),
                      label=transfer.label, producer=transfer.producer, donor=transfer.donor,
                      receiver=transfer.receiver, component_mass_kg=dict(transfer.component_mass_kg),
                      enthalpy_j=transfer.enthalpy_j, basis=transfer.basis, units=UNITS)
        records.append(dict(record, transfer_id=hashlib.sha256(_canonical(record, 'transfer record')).hexdigest()))
        digests.append(digest)
    stored, stored_j = np.array(old), np.array(energy)
    rounding, rounding_j = list(exchange._rounding[0]), exchange._rounding[1]
    allowance, allowance_j = list(exchange._allowance[0]), exchange._allowance[1]
    for i in sorted(touched):
        for k, exact in enumerate(mass[i]):
            value = float(_within(exact, 'a stock'))
            if exact != Fraction(old[i, k]) and value == old[i, k]:
                raise ExchangeRefused('a transfer is below the resolution of a stock it changes; it cannot be booked '
                                      'faithfully and is refused')
            stored[i, k] = value
            if exact != Fraction(old[i, k]):                 # only a changed value is rounded
                rounding[k] += Fraction(value)-exact
                allowance[k] += Fraction(math.ulp(value))/2
        value = float(_within(heat[i], 'a stock enthalpy'))
        if heat[i] != Fraction(energy[i]) and value == energy[i]:
            raise ExchangeRefused('a transfer is below the resolution of a stock enthalpy it changes; it cannot be '
                                  'booked faithfully and is refused')
        stored_j[i] = value
        if heat[i] != Fraction(energy[i]):
            rounding_j += Fraction(value)-heat[i]
            allowance_j += Fraction(math.ulp(value))/2
    # Correct rounding guarantees this; a violation is an implementation fault, and nothing is published.
    if any(abs(r) > a for r, a in zip(rounding, allowance)) or abs(rounding_j) > allowance_j:
        raise LedgerError('stock rounding exceeds its exact allowance: nothing was published')
    try:                                     # the parent's accounts were valid: any failure here is the proposal's
        stocks = _owned(inventory, component_mass_kg=stored, enthalpy_j=stored_j, time_s=end_time,
                        source_id=inventory.source_id if not records else 'atlas.i02-ledger-commit:'+key)
        after = _exchange(stocks, exchange.exteriors, exchange._initial,
                          (tuple(tuple(row) for row in supplied), tuple(supplied_j)), (tuple(rounding), rounding_j),
                          (tuple(allowance), allowance_j))
        after.descriptor()                                # every exact account fits its bounded representation
    except ExchangeRefused:
        raise
    except LedgerError as exc:
        raise ExchangeRefused(str(exc)) from exc
    return after, tuple(records), tuple(digests)


# ----------------------------------------------------------------------------- commits and the ledger

@dataclass(frozen=True, eq=False, init=False, slots=True)
class Commit(_Issued):
    """One accepted commit of a ledger: its key, lineage, accepted time and transfer identities; metadata only.

    ``interval`` is (start_s, end_s, start_step, end_step) of the whole global steps it accepted (None for the root).
    Physical arrays stay in the store until requested; ``Ledger.state`` returns the committed CommonState. A ledger
    re-reads a commit's stored record before using it, so an edited or foreign Commit object is refused.
    """
    ledger_id: str
    key: str
    parent_key: str | None
    sequence: int
    state_id: str
    time_s: float
    elapsed_s: float
    accepted_steps: int
    interval: tuple | None
    transfer_ids: tuple
    _metadata: bytes = field(repr=False)

    def metadata(self):
        return json.loads(self._metadata)


_COMMIT_FIELDS = ('ledger_id', 'key', 'parent_key', 'sequence', 'state_id', 'time_s', 'elapsed_s', 'accepted_steps',
                  'interval', 'transfer_ids', '_metadata')
_SUCCESSOR_KEYS = frozenset(('schema', 'kind', 'ledger_id', 'key', 'parent_key', 'parent_digest', 'sequence',
                             'interval', 'path', 'transfers', 'state', 'exchange'))
_SUCCESSOR_STATE = frozenset(('state_id', 'parent_state_id', 'time_s', 'elapsed_s', 'accepted_steps', 'column'))
_TRANSFER_KEYS = frozenset(('schema', 'ledger_id', 'parent_key', 'interval', 'label', 'producer', 'donor', 'receiver',
                            'component_mass_kg', 'enthalpy_j', 'basis', 'units', 'transfer_id'))
_MISSING = object()
# Calendar events this route supports: prescribed savepoints. Any other declared event stops every clock of the
# history at the last whole step not after it; a commit can never step past one.
SUPPORTED_EVENTS = frozenset(('savepoint',))
MAX_EVENTS = 1024


def _state_arrays(state):
    arrays = {'reference.'+name: array for name, array in state.reference._arrays()}
    arrays.update(('column.'+name, array) for name, array in state.column._arrays())
    arrays['materials.partial_thickness_m'] = state.materials.thickness_m
    arrays['materials.mesh_edges_m'] = state.materials.grid.edges_m
    if state.reservoirs is not None:
        arrays['reservoirs.component_mass_kg'] = state.reservoirs.component_mass_kg
        arrays['reservoirs.enthalpy_j'] = state.reservoirs.enthalpy_j
    return arrays


def _exchange_arrays(exchange, applied):
    return {'exchange.component_mass_kg': exchange.inventory.component_mass_kg,
            'exchange.enthalpy_j': exchange.inventory.enthalpy_j,
            'exchange.supplied_kg': exchange._supplied_kg, 'exchange.supplied_j': exchange._supplied_j,
            'ledger.applied': applied}


def _applied(digests):
    return np.frombuffer(b''.join(digests), dtype=np.uint8).reshape(len(digests), 32)


def _digests(array):
    raw = np.asarray(array)
    if raw.dtype != np.uint8 or raw.ndim != 2 or raw.shape[1] != 32:
        raise LedgerError('the stored transfer index is not a list of 32-byte label digests')
    return tuple(row.tobytes() for row in raw)


def _is_sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _step_times(start_s, step_s, steps):
    """Epoch times of the global step boundaries 0..steps of the fixed schedule; they must all be distinct."""
    times = [advance_time(start_s, k*step_s) for k in range(steps+1)]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise LedgerError("the fixed schedule's step boundaries are not all distinct at this epoch time; choose a "
                          'nearer epoch or a longer step')
    return times


def _calendar(events, times):
    """Declared calendar entries as a sorted list of [time_s, kind, label] inside the fixed schedule ``times``.

    Every event lies between the history start and the schedule end, and a savepoint falls exactly on a whole step
    boundary, so no declared entry can leave a clock unable to plan.
    """
    if type(events) not in (tuple, list) or len(events) > MAX_EVENTS:
        raise LedgerError('a calendar is a sequence of at most %d events' % MAX_EVENTS)
    whole, out = set(times), set()
    for event in events:
        values = tuple(event) if type(event) in (tuple, list) else tuple(getattr(event, name, None)
                                                                         for name in ('time_s', 'kind', 'label'))
        if len(values) != 3:
            raise LedgerError('a calendar event declares its time, kind and label')
        time_s, kind, label = values
        if isinstance(time_s, (bool, np.bool_)):
            raise LedgerError('a calendar event time is a real number')
        time_s = scalar(time_s, 'calendar event time')
        _token(kind, 'calendar event kind')
        _token(label, 'calendar event label')
        if not times[0] <= time_s <= times[-1]:
            raise LedgerError('a calendar event lies outside the fixed schedule of this history')
        if kind in SUPPORTED_EVENTS and time_s not in whole:
            raise LedgerError('a savepoint must fall exactly on a whole step of the fixed global schedule')
        out.add((time_s, kind, label))
    return [list(item) for item in sorted(out)]


def _crosses(calendar, start_s, end_s):
    """The first unsupported calendar event a commit from ``start_s`` to ``end_s`` would step past, if any."""
    for time_s, kind, label in calendar:
        if kind not in SUPPORTED_EVENTS and start_s <= time_s < end_s:
            return kind, label
    return None


# Derived inspection fields: (units, support, owner, meaning). Stored fields take theirs from the state catalogue.
DERIVED = {
    'temperature_k': ('K', 'material point', 'column thermal state',
                      'T = T_steady + theta at material points; derived on read, never stored'),
    'current_depth_m': ('m', 'material point', 'column kinematics',
                        'current material depth z0/lam from the original reference; derived on read'),
}
EXCHANGE_FIELDS = {
    'exchange.component_mass_kg': ('kg', 'W08 node x component', 'finite exterior accounts',
                                   'current whole-stock component masses at the commit time'),
    'exchange.enthalpy_j': ('J', 'W08 node', 'finite exterior accounts',
                            'current signed stock enthalpy in its declared basis at the commit time'),
    'exchange.supplied_kg': ('kg', 'exterior x component', 'finite exterior accounts',
                             'cumulative mass supplied to the stocks by each named exterior since the root, rounded '
                             'from its exact account'),
    'exchange.supplied_j': ('J', 'exterior', 'finite exterior accounts',
                            'cumulative signed enthalpy supplied to the stocks by each named exterior since the root, '
                            'rounded from its exact account'),
}
_REFERENCE_FIELDS = {'layer_thickness_m': 'layer_thickness_m', 'point_layer': 'point_layer',
                     'reference_depth_m': 'depth_m', 'reference_weight_m': 'weight_m',
                     'reference_overburden_pa': 'overburden_pa', 'reference_density_kg_m3': 'density_kg_m3',
                     'steady_temperature_k': 'steady_temperature_k', 'capacity_j_m2_k': 'capacity_j_m2_k',
                     'radiogenic_w_m2': 'radiogenic_w_m2', 'thermal_density_kg_m3': 'thermal_density_kg_m3'}
_COLUMN_FIELDS = {'theta_k': 'theta_k', 'kappa': 'kappa', 'yield_stage_counts': 'yield_stage_counts',
                  'initial_theta_k': 'initial_theta_k', 'initial_kappa': 'initial_kappa'}


def _copy(array):
    array = np.asarray(array)
    return np.frombuffer(np.ascontiguousarray(array).tobytes(), dtype=array.dtype).reshape(array.shape)


def _root_metadata(ledger_id, declaration, root, exchange, sphere=None):
    """The complete root record of a ledger: what create() stores and open() must find exactly."""
    record = dict(schema=SCHEMA, kind='root', ledger_id=ledger_id, key=root_key(ledger_id), parent_key=None,
                  sequence=0, declaration=declaration, interval=None, path=[], transfers=[],
                  state=dict(state_id=root.state_id, parent_state_id=None, time_s=root.time_s,
                             elapsed_s=root.column.elapsed_s, accepted_steps=0, record=json.loads(root._record),
                             reference=root.reference.descriptor(), settings=root.settings.descriptor(),
                             column=root.column.descriptor(), materials=root.materials.descriptor(),
                             reservoirs=None if root.reservoirs is None else root.reservoirs.descriptor()),
                  exchange=None if exchange is None else exchange.descriptor())
    if sphere is not None:                   # I03: only a ledger with an attached network records one
        record['sphere'] = sphere.descriptor()
    return record


def _bound_sphere(root, sphere, exchange):
    """I03.1: the declared spherical network attached to ``root``, checked against it and the exchange."""
    from . import integration_sphere as _sphere
    try:
        state = _sphere.bound(root, sphere, None if exchange is None else exchange.inventory,
                              () if exchange is None else exchange.exteriors)
    except LedgerError:
        raise
    except TectonicsError as exc:
        raise LedgerError('the spherical network cannot be attached to this history: '+str(exc)) from exc
    return state, dict(schema=_sphere.SCHEMA, state_id=state.state_id)


def _sphere_linked(metadata, parent):
    """I03.2: a successor's stored network step continues its parent commit's network state over its interval."""
    from . import integration_transfer as _transfer
    return _transfer.linked(metadata['sphere'], json.loads(parent._metadata)['sphere'], metadata['interval'])


def _proposal(value):
    """A Transfer or (I03.2) the Motion of an attached spherical network: both declare the interval of whole global
    steps they are committed over."""
    if type(value) is Transfer:
        return True
    from . import integration_transfer as _transfer
    return type(value) is _transfer.Motion


def _network_content(metadata):
    """(producer of an attached network's own stock transfers, [its motion identity]) of a stored commit."""
    if 'sphere' not in metadata:
        return None, []
    from . import integration_transfer as _transfer
    return _transfer.content(metadata)


class Ledger:
    """One root history in one ArrayStore, issued by create() or open(); one connection per ledger.

    Commits are appended only as the unique successor of their parent, and only states a Continuation computed from
    the accepted parent can be committed. No commit is rewritten or deleted and nothing is collected: the store has no
    eviction. States and stocks of commits made elsewhere are restored from the store through the validating
    constructors and the package restorer, and their identities must reproduce. A small working set of restored
    objects is kept, each tied to the exact stored record it came from. Not thread-safe; separate processes use
    separate stores on one file.
    """
    __slots__ = ('_store', '_ledger_id', '_root', '_root_meta', '_budget', '_states', '_exchanges', '_applied',
                 '_chain', '_token', '_spheres')

    def __init__(self, *args, **kwargs):
        raise TypeError('a Ledger is issued by Ledger.create() or Ledger.open() only')

    def __reduce__(self):
        raise TypeError('a Ledger holds a live store connection and is never pickled')

    @classmethod
    def _new(cls, store, ledger_id, budget):
        ledger = object.__new__(cls)
        for name, value in dict(_store=store, _ledger_id=ledger_id, _root=None, _root_meta=None, _budget=budget,
                                _states={}, _exchanges={}, _applied={}, _chain=None, _token=None,
                                _spheres={}).items():
            object.__setattr__(ledger, name, value)
        return ledger

    def _rooted(self, metadata, state, exchange, sphere=None):
        commit = self._issued(metadata)
        object.__setattr__(self, '_root', commit)
        object.__setattr__(self, '_root_meta', json.loads(commit._metadata))
        self._keep(self._states, commit, state)
        self._keep(self._exchanges, commit, exchange)
        self._keep(self._applied, commit, ())
        self._keep(self._spheres, commit, sphere)
        return commit

    @classmethod
    def create(cls, store, root, *, exteriors=(), calendar=(), sphere=None, budget=None):
        """Record the declared initial ``root`` state (and its attached stocks) as the root commit; idempotent.

        Attached W08 reservoirs of the root envelope become the initial stocks of the exchange accounts (a copy the
        ledger owns); the envelope keeps them as its initial payload, as it keeps its initial temperature departure.
        Exteriors and the event calendar ((time_s, kind, label) entries, or objects with those attributes) are
        declared once here and bound into the ledger identity, so every later clock honours them. ``sphere`` (I03)
        attaches a declared spherical network (integration_sphere.initial_sphere) dated at the root's epoch and
        start: it is stored in the root commit beside the column state and bound into the ledger identity, and every
        later commit then carries its successor.
        """
        if not isinstance(store, ArrayStore):
            raise LedgerError('a native ArrayStore is required')
        root = _state._verified(root)
        if root.parent_state_id is not None or root.issued_by == _state.RESTORED:
            raise LedgerError('a ledger starts from a declared initial state; an accepted successor cannot be a root '
                              '(cumulative steps and limits are never reset)')
        outside = _exteriors(exteriors, root)
        exchange = None if root.reservoirs is None else _root_exchange(root, outside)
        times = _step_times(root.start_time_s, root.settings.step_s, root.settings.steps)
        declaration = dict(schema=SCHEMA, route=_state.ROUTE, root_state_id=root.state_id,
                           exchange=None if exchange is None else exchange.descriptor(),
                           calendar=_calendar(calendar, times))
        arrays = _state_arrays(root)
        if sphere is not None:
            if getattr(sphere, 'issued_by', None) != _state.DECLARED:
                raise LedgerError('a ledger starts from a declared initial network; a computed or restored one '
                                  'cannot be a root')
            sphere, declaration['sphere'] = _bound_sphere(root, sphere, exchange)
            arrays.update(sphere.arrays())
        ledger_id = hashlib.sha256(_canonical(declaration, 'ledger declaration')).hexdigest()
        if exchange is not None:
            arrays.update(_exchange_arrays(exchange, _applied([])))
        metadata = _root_metadata(ledger_id, declaration, root, exchange, sphere)
        try:
            store.put(metadata['key'], arrays, metadata, budget=budget)
        except StoreConflict as exc:
            raise LedgerConflict('a different root was recorded under this ledger identity') from exc
        ledger = cls._new(store, ledger_id, budget)
        return ledger, ledger._rooted(metadata, root, exchange, sphere)

    @classmethod
    def open(cls, store, ledger_id, *, source_id, runtime_id, budget=None):
        """Reopen a saved ledger: rebuild and verify its root; refuse another source or runtime identity.

        ``source_id``/``runtime_id`` are the identities the caller now declares for its producer and runtime; they must
        equal the ones recorded with the history. The comparison is only as good as the caller's declaration (the I02
        workflow declares the identities it computes), and state() and the finite-admission restored() do not repeat
        it. The root is rebuilt through its validating constructors and the complete stored root record must equal the
        record those rebuilt parts produce. Nothing is rebound, and no accepted step is re-run.
        """
        if not isinstance(store, ArrayStore):
            raise LedgerError('a native ArrayStore is required')
        for value, label in ((ledger_id, 'ledger identity'), (source_id, 'source identity'),
                             (runtime_id, 'runtime identity')):
            _sha(value, label)
        key = root_key(ledger_id)
        metadata = store.metadata(key)
        if metadata is None:
            raise LedgerError('the store holds no ledger with this identity')
        try:
            declaration = metadata['declaration']
            ok = (hashlib.sha256(_canonical(declaration, 'ledger declaration')).hexdigest() == ledger_id
                  and declaration['schema'] == SCHEMA and declaration['route'] == _state.ROUTE)
            produced = (metadata['state']['record']['identity']['source_id'],
                        metadata['state']['record']['identity']['runtime_id'])
        except (KeyError, TypeError):
            ok = False
        if not ok:
            raise LedgerError('the stored root is not a ledger root of this schema')
        if produced != (source_id, runtime_id):
            raise LedgerError('the saved history was produced under another source or runtime identity; it is not '
                              'silently rebound')
        ledger = cls._new(store, ledger_id, budget)
        arrays = store.get(key, budget=budget)
        root = ledger._restore_root(metadata, arrays)
        exchange = None
        if root.reservoirs is not None:
            try:
                outside = _exteriors(tuple(tuple(pair) for pair in declaration['exchange']['exteriors']), root)
            except (KeyError, TypeError) as exc:
                raise LedgerError('the stored exterior declaration is invalid') from exc
            exchange = _root_exchange(root, outside)
        try:
            calendar = _calendar(declaration['calendar'], _step_times(root.start_time_s, root.settings.step_s,
                                                                       root.settings.steps))
        except (KeyError, TypeError) as exc:
            raise LedgerError('the stored calendar is invalid') from exc
        rebuilt = dict(schema=SCHEMA, route=_state.ROUTE, root_state_id=root.state_id,
                       exchange=None if exchange is None else exchange.descriptor(), calendar=calendar)
        sphere = None
        if 'sphere' in declaration:              # I03: rebuild the attached network through its own constructors
            from . import integration_sphere as _sphere
            try:
                sphere = _sphere.restore_sphere(metadata.get('sphere'), arrays, budget=budget, exclusive=True)
            except LedgerError:
                raise
            except TectonicsError as exc:
                raise LedgerError('the stored spherical network is not restored: '+str(exc)) from exc
            sphere, rebuilt['sphere'] = _bound_sphere(root, sphere, exchange)
        expected = _root_metadata(ledger_id, rebuilt, root, exchange, sphere)
        if (_canonical(rebuilt, 'ledger declaration') != _canonical(declaration, 'ledger declaration')
                or _canonical(expected, 'root record') != _canonical(metadata, 'root record')
                or (exchange is not None and (ledger._stored_exchange(metadata, arrays).exchange_id
                                              != exchange.exchange_id or _digests(arrays['ledger.applied'])))):
            raise LedgerError('the stored root record is not the record of the rebuilt root: edited or foreign')
        ledger._rooted(metadata, root, exchange, sphere)
        return ledger

    @property
    def ledger_id(self):
        return self._ledger_id

    @property
    def store(self):
        return self._store

    @property
    def root(self):
        return self._root

    @property
    def calendar(self):
        """The declared event calendar: (time_s, kind, label) tuples in time order."""
        return tuple(tuple(event) for event in self._root_meta['declaration']['calendar'])

    def _keep(self, cache, commit, value):
        # A small bounded working set: the root and the latest commits touched in this process, each tied to the
        # exact record it belongs to, so a Commit of the same key from another store never receives it.
        cache[commit.key] = (commit._metadata, value)
        while len(cache) > 4:
            del cache[next(k for k in cache if k != self._root_key())]

    @staticmethod
    def _cached(cache, commit):
        entry = cache.get(commit.key)
        return entry[1] if entry is not None and entry[0] == commit._metadata else _MISSING

    def _root_key(self):
        return root_key(self._ledger_id)

    def _issued(self, metadata):
        """A Commit over checked manifest metadata of this ledger."""
        try:
            state, interval = metadata['state'], metadata['interval']
            return _issue(Commit, ledger_id=self._ledger_id, key=metadata['key'], parent_key=metadata['parent_key'],
                          sequence=metadata['sequence'], state_id=state['state_id'], time_s=state['time_s'],
                          elapsed_s=state['elapsed_s'], accepted_steps=state['accepted_steps'],
                          interval=None if interval is None else (interval['start_s'], interval['end_s'],
                                                                  interval['start_step'], interval['end_step']),
                          transfer_ids=tuple(t['transfer_id'] for t in metadata['transfers']),
                          _metadata=_canonical(metadata, 'commit metadata'))
        except (KeyError, TypeError) as exc:
            raise LedgerError('a stored commit record is incomplete') from exc

    def _own(self, commit):
        if type(commit) is not Commit or commit.ledger_id != self._ledger_id:
            raise LedgerError('a commit issued by this ledger is required')
        return commit

    def _current(self, commit):
        """The commit's manifest metadata as stored now; it must be exactly the metadata the commit was issued over."""
        metadata = self._store.metadata(commit.key)
        if metadata is None or _canonical(metadata, 'commit metadata') != commit._metadata:
            raise LedgerError('the commit is missing from, or changed in, its store')
        return metadata

    def _authentic(self, commit):
        """(commit reissued from its stored record, that record); every field of the object must match it."""
        commit = self._own(commit)
        metadata = self._current(commit)
        issued = self._issued(metadata)
        if any(getattr(issued, name) != getattr(commit, name) for name in _COMMIT_FIELDS):
            raise LedgerError('the commit object differs from its stored record')
        return issued, metadata

    def _schedule(self):
        record = self._root_meta['state']
        schedule = record['settings']['numerical_policy']['schedule']
        return schedule['steps'], schedule['step_s'], record['record']['clock']['start_time_s']

    def _checked(self, metadata, parent):
        """Structural checks of a successor manifest found under ``parent``'s successor key, from metadata only.

        The record must be exactly what commit() writes for that parent: its parent's record digest, a whole-step
        interval on the fixed schedule, a consistent path, well-formed column, transfer and exchange records, and no
        step past an unsupported calendar event. Values are checked by restoration (state(), exchange()): ranges,
        identities and the retained step relations, which establish consistency, not who wrote the record.
        """
        expected = successor_key(self._ledger_id, parent.key)
        steps, step_s, start = self._schedule()
        declared = self._root_meta['declaration']['exchange']
        sphered = 'sphere' in self._root_meta['declaration']          # I03: every successor then carries its step
        keys = _SUCCESSOR_KEYS | {'sphere'} if sphered else _SUCCESSOR_KEYS
        try:
            state, interval, path, transfers = (metadata[k] for k in ('state', 'interval', 'path', 'transfers'))
            accepted, column, exchange = state['accepted_steps'], state['column'], metadata['exchange']
            ok = (type(metadata) is dict and set(metadata) == keys and metadata['schema'] == SCHEMA
                  and metadata['kind'] == 'successor' and metadata['ledger_id'] == self._ledger_id
                  and metadata['key'] == expected and metadata['parent_key'] == parent.key
                  and metadata['parent_digest'] == hashlib.sha256(parent._metadata).hexdigest()
                  and type(metadata['sequence']) is int and metadata['sequence'] == parent.sequence+1
                  and type(state) is dict and set(state) == _SUCCESSOR_STATE and _is_sha(state['state_id'])
                  and _is_sha(state['parent_state_id']) and type(accepted) is int
                  and parent.accepted_steps < accepted <= steps
                  and state['elapsed_s'] == accepted*step_s and state['time_s'] == advance_time(start, accepted*step_s)
                  and interval == dict(start_s=parent.time_s, end_s=state['time_s'], start_step=parent.accepted_steps,
                                       end_step=accepted)
                  and type(column) is dict and set(column) == _state._COLUMN_KEYS
                  and column['semantics'] == _state.SUCCESSOR_SEMANTICS and column['accepted_steps'] == accepted
                  and column['elapsed_s'] == state['elapsed_s']
                  and type(path) is list and 1 <= len(path) <= MAX_PATH
                  and all(type(p) is list and len(p) == 2 and _is_sha(p[0]) and type(p[1]) is int for p in path)
                  and all(a[1] < b[1] for a, b in zip(path, path[1:])) and path[0][1] > parent.accepted_steps
                  and path[-1] == [state['state_id'], accepted]
                  and state['parent_state_id'] == (path[-2][0] if len(path) > 1 else parent.state_id)
                  and type(transfers) is list and len(transfers) <= MAX_TRANSFERS
                  and all(type(t) is dict and set(t) == _TRANSFER_KEYS and _is_sha(t['transfer_id'])
                          and t['parent_key'] == parent.key for t in transfers)
                  and (exchange is None) == (declared is None) and (declared is not None or not transfers)
                  and (exchange is None or (type(exchange) is dict and exchange.get('schema') == EXCHANGE_SCHEMA
                                            and exchange.get('exteriors') == declared['exteriors']
                                            and type(exchange.get('exact')) is dict))
                  and _crosses(self._root_meta['declaration']['calendar'], parent.time_s, state['time_s']) is None
                  and (not sphered or _sphere_linked(metadata, parent)))
        except (KeyError, TypeError, ValueError, TectonicsError):
            ok = False
        if not ok:
            if sphered and type(metadata) is dict and type(metadata.get('sphere')) is dict:
                from . import integration_transfer as _transfer
                schema = metadata['sphere'].get('schema')
                if schema != _transfer.SCHEMA:
                    raise LedgerError('unsupported spherical step schema %r; this runtime requires %r; '
                                      'no implicit history migration' % (schema, _transfer.SCHEMA))
            raise LedgerError('a stored commit is not a well-formed successor of its parent in this ledger')
        return self._issued(metadata)

    def chain(self):
        """The accepted commits from the root to the head, in order, once every link has been re-read and checked.

        Reads manifest metadata only. A broken link anywhere refuses the whole chain; no prefix is returned. The checked
        chain is reused while the store's change token shows that nothing was written since it was read, and this
        ledger extends it with its own commits when nothing else was written in between.
        """
        token = self._store.change_token()
        if self._chain is not None and token == self._token:
            return self._chain
        object.__setattr__(self, '_chain', None)
        self._authentic(self._root)
        commit, out = self._root, [self._root]
        while True:
            metadata = self._store.metadata(successor_key(self._ledger_id, commit.key))
            if metadata is None:
                break
            commit = self._checked(metadata, commit)
            out.append(commit)
        object.__setattr__(self, '_chain', tuple(out))
        object.__setattr__(self, '_token', token)
        return self._chain

    def head(self):
        """The accepted head: the last commit of the one chain of successors from the root; reads metadata only."""
        return self.chain()[-1]

    def _on_chain(self, commit):
        """(commit reissued from its stored record, that record) once the whole chain from the root to the head has
        been re-read with the commit on it unchanged: a stored commit its descendants no longer bind is refused."""
        commit, metadata = self._authentic(commit)
        chain = self.chain()
        if (type(commit.sequence) is not int or not 0 <= commit.sequence < len(chain)
                or chain[commit.sequence]._metadata != commit._metadata):
            raise LedgerError('the commit is not stored unchanged on the accepted chain of this ledger')
        return commit, metadata

    def verify(self, commit):
        """``commit`` is stored unchanged on the one accepted chain to the head, and its state and stocks restore
        exactly."""
        commit, metadata = self._on_chain(commit)
        self._restored(commit, metadata)
        self._restored_exchange(commit, metadata)
        self._restored_sphere(commit, metadata)
        return commit

    def verify_chain(self):
        """Every commit from the root to the head restores exactly and reproduces its identities; returns the head.

        One pass: the chain is re-read once and each commit's state and stocks are restored from the store. This
        establishes that a trusted store is consistent, not who wrote its records.
        """
        chain = self.chain()
        for commit in chain:
            metadata = self._current(commit)
            self._restored(commit, metadata)
            self._restored_exchange(commit, metadata)
            self._restored_sphere(commit, metadata)
        return chain[-1]

    # ------------------------------------------------------------------------- restoration (I02.5)

    def _restore_root(self, metadata, arrays):
        """Rebuild the root through its validating constructors from the persisted inputs; identities must reproduce."""
        from .materials import restore_material_state
        if arrays is None:
            raise LedgerError('the stored root has no arrays')
        try:
            s = metadata['state']
            record, ref, sett = s['record'], s['reference'], s['settings']
            pinned = ref['pinned_preparation']
            point, depth, weight = (arrays['reference.'+name] for name in ('point_layer', 'reference_depth_m',
                                                                           'reference_weight_m'))
            reference = _state.ColumnReference(
                mechanical=dict(key=(pinned['layers'], pinned['order'], pinned['closure'], pinned['gravity']),
                                fingerprint=ref['mechanical_fingerprint'], layer=point, depth_m=depth, weight=weight,
                                reference_pa=arrays['reference.reference_overburden_pa'],
                                density=arrays.get('reference.reference_density_kg_m3'),
                                thickness_m=ref['thickness_m']),
                thermal=dict(provider=ref['thermal_provider'], inputs=ref['pinned_thermal'],
                             fingerprint=ref['thermal_fingerprint'],
                             mechanical_fingerprint=ref['mechanical_fingerprint'], layer=point, depth_m=depth,
                             volume_m=weight, reference_density_kg_m3=arrays['reference.thermal_density_kg_m3'],
                             capacity=arrays['reference.capacity_j_m2_k'],
                             radiogenic=arrays['reference.radiogenic_w_m2'],
                             steady_k=arrays['reference.steady_temperature_k'],
                             boundary_temperature=tuple(ref['boundary_temperature_k']), thickness_m=ref['thickness_m']),
                budget=self._budget)
            numerics, parameters = sett['numerical_policy'], sett['parameters']
            window = numerics['window']
            settings = _state.ColumnSettings(
                representation=dict(sett['closure']['representation'], stretch_window=window['stretch'],
                                    temperature_window_k=window['temperature_k'],
                                    max_temperature_step_k=window['max_temperature_step_k']),
                law=parameters['law'], drive=parameters['drive'], heat_fractions=parameters['heat_fractions'],
                policy=numerics['policy'], schedule=dict(duration_s=numerics['schedule']['duration_s'],
                                                         steps=numerics['schedule']['steps']))
            materials = restore_material_state(s['materials'], arrays['materials.partial_thickness_m'],
                                               record['materials']['state_id'], budget=self._budget,
                                               edges_m=arrays['materials.mesh_edges_m'])
            reservoirs = None
            if s['reservoirs'] is not None:
                reservoirs = self._inventory(s['reservoirs'], arrays['reservoirs.component_mass_kg'],
                                             arrays['reservoirs.enthalpy_j'], record['reservoirs']['inventory_id'])
            labels = record['identity']
            identity = _state.StateIdentity(world_id=labels['world_id'], scenario_id=labels['scenario_id'],
                                            epoch_id=record['clock']['epoch_id'], source_id=labels['source_id'],
                                            runtime_id=labels['runtime_id'], unit_system=record['unit_system'])
            root = _state.initial_state(
                identity=identity, start_time_s=record['clock']['start_time_s'], frame_id=record['frame']['frame_id'],
                reference=reference, settings=settings, theta0_k=arrays['column.initial_theta_k'],
                kappa0=arrays['column.initial_kappa'], materials=materials,
                layer_cohorts=tuple(record['materials']['layer_cohorts']), reservoirs=reservoirs,
                reservoir_basis=None if record['reservoirs'] is None else record['reservoirs']['enthalpy_basis'],
                budget=self._budget)
        except (KeyError, TypeError, IndexError) as exc:
            raise LedgerError('the stored root record is incomplete') from exc
        if root.state_id != s['state_id']:
            raise LedgerError('the stored root does not reproduce its identity')
        return root

    @staticmethod
    def _inventory(descriptor, mass, enthalpy, expected):
        from .w08_inventory import W08Inventory
        if type(descriptor) is not dict or descriptor.get('schema') != 'atlas.w08-inventory.v1':
            raise LedgerError('stored stocks are not a W08 inventory of this schema')
        try:
            inventory = W08Inventory(tuple(descriptor['node_ids']), tuple(descriptor['node_kinds']),
                                     tuple(descriptor['component_ids']), mass, enthalpy,
                                     source_id=descriptor['source_id'], enthalpy_source=descriptor['enthalpy_source'],
                                     time_s=descriptor['time_s'], formation_time_s=descriptor['formation_time_s'],
                                     origin_ids=tuple(descriptor['origin_ids']))
        except (KeyError, TypeError, OverflowError) as exc:
            raise LedgerError('stored stocks are incomplete') from exc
        if inventory.inventory_id != expected:
            raise LedgerError('stored stocks do not reproduce their inventory identity')
        return inventory

    def _stored_exchange(self, metadata, arrays):
        """The exchange accounts exactly as stored with a commit, checked against the ledger's declaration."""
        declared = self._declared_exchange(metadata)
        stored = metadata['exchange']
        try:
            exact, known = stored['exact'], declared['exact']
            ok = (type(stored) is dict and stored['schema'] == EXCHANGE_SCHEMA and stored['units'] == UNITS
                  and (stored['exteriors'], exact['initial_kg'], exact['initial_j'])
                  == (declared['exteriors'], known['initial_kg'], known['initial_j'])
                  and all(stored['inventory'][name] == declared['inventory'][name]
                          for name in ('schema', 'node_ids', 'node_kinds', 'component_ids', 'origin_ids',
                                       'formation_time_s', 'enthalpy_source'))
                  and stored['inventory']['time_s'] == metadata['state']['time_s'])
            if ok:
                inventory = self._inventory(stored['inventory'], arrays['exchange.component_mass_kg'],
                                            arrays['exchange.enthalpy_j'], stored['inventory_id'])
                initial = (tuple(_exact(v, 'initial') for v in exact['initial_kg']), _exact(exact['initial_j'],
                                                                                           'initial'))
                supplied = (tuple(tuple(_exact(v, 'supplied') for v in row) for row in exact['supplied_kg']),
                            tuple(_exact(v, 'supplied') for v in exact['supplied_j']))
                rounding = (tuple(_exact(v, 'rounding') for v in exact['rounding_kg']),
                            _exact(exact['rounding_j'], 'rounding'))
                allowance = (tuple(_exact(v, 'allowance') for v in exact['allowance_kg']),
                             _exact(exact['allowance_j'], 'allowance'))
                exchange = _exchange(inventory, tuple(tuple(pair) for pair in stored['exteriors']), initial, supplied,
                                     rounding, allowance)
                ok = (exchange.exchange_id == stored['exchange_id']
                      and _canonical(exchange.descriptor(), 'exchange record') == _canonical(stored, 'exchange record')
                      and exchange._supplied_kg.tobytes() == np.asarray(arrays['exchange.supplied_kg'],
                                                                        dtype=np.float64).tobytes()
                      and exchange._supplied_j.tobytes() == np.asarray(arrays['exchange.supplied_j'],
                                                                       dtype=np.float64).tobytes())
        except (KeyError, TypeError, ValueError) as exc:
            raise LedgerError('stored exchange accounts are incomplete') from exc
        if not ok:
            raise LedgerError('stored stocks, exteriors or accounts differ from the ledger declaration or their '
                              'own identity')
        return exchange

    def _declared_exchange(self, metadata):
        declared = (self._root_meta if self._root_meta is not None else metadata)['declaration']['exchange']
        if declared is None:
            raise LedgerError('no finite stocks are declared in this ledger')
        return declared

    def state(self, commit):
        """The committed CommonState of ``commit``: this process's own, or restored from the store and verified.

        The commit must be on the accepted chain to the head. A restored successor is rebuilt by
        integration_state.restore from the root and its recorded values, and must reproduce the stored identity, column
        record and lineage exactly. No accepted step is re-run.
        """
        return self._restored(*self._on_chain(commit))

    def _restored(self, commit, metadata):
        state = self._cached(self._states, commit)
        if state is not _MISSING:
            return state
        arrays = self._store.get(commit.key, budget=self._budget)
        s, path = metadata['state'], metadata['path']
        try:
            state = _state.restore(self._cached(self._states, self._root), parent_state_id=s['parent_state_id'],
                                   column=s['column'], theta_k=arrays['column.theta_k'], kappa=arrays['column.kappa'],
                                   yield_stage_counts=arrays['column.yield_stage_counts'], budget=self._budget)
        except (KeyError, TypeError) as exc:
            raise LedgerError('the stored commit is incomplete') from exc
        parent = path[-2][0] if len(path) > 1 else self._store.metadata(commit.parent_key)['state']['state_id']
        if (state.state_id, state.parent_state_id, state.column.accepted_steps, state.time_s,
                state.column.elapsed_s) != (s['state_id'], parent, s['accepted_steps'], s['time_s'], s['elapsed_s']):
            raise LedgerError('the stored commit does not reproduce its state identity or lineage')
        self._keep(self._states, commit, state)
        return state

    def exchange(self, commit):
        """The exchange accounts at ``commit`` (None when no finite stocks are attached).

        The commit must be on the accepted chain to the head. Restored accounts must equal the parent's stored stocks
        with this commit's recorded transfers applied once: the transfers are validated and applied again and the result
        must reproduce the stored identity.
        """
        return self._restored_exchange(*self._on_chain(commit))

    def _restored_exchange(self, commit, metadata):
        exchange = self._cached(self._exchanges, commit)
        if exchange is not _MISSING:
            return exchange
        if self._root_meta['declaration']['exchange'] is None:
            self._keep(self._exchanges, commit, None)
            return None
        arrays = self._store.get(commit.key, budget=self._budget)
        parent_meta = self._store.metadata(commit.parent_key)
        parent_arrays = self._store.get(commit.parent_key, budget=self._budget)
        try:
            parent = self._stored_exchange(parent_meta, parent_arrays)
            before = _digests(parent_arrays['ledger.applied'])
            transfers = tuple(Transfer(label=r['label'], producer=r['producer'], donor=r['donor'],
                                       receiver=r['receiver'], component_mass_kg=r['component_mass_kg'],
                                       enthalpy_j=r['enthalpy_j'], basis=r['basis'],
                                       start_step=r['interval']['start_step'], end_step=r['interval']['end_step'],
                                       units=r['units'])
                              for r in metadata['transfers'])
            after, records, new = _apply(self._ledger_id, commit.parent_key, commit.interval, commit.key, parent,
                                         transfers, set(before), commit.time_s)
            stored, applied = self._stored_exchange(metadata, arrays), _digests(arrays['ledger.applied'])
        except (KeyError, TypeError) as exc:
            raise LedgerError('the stored exchange accounts are incomplete') from exc
        except ExchangeRefused as exc:                    # a stored record, not a proposal: its store is inconsistent
            raise LedgerError('a stored transfer record no longer applies to its parent: '+str(exc)) from exc
        except LedgerError:
            raise
        except TectonicsError as exc:                     # e.g. a stored mass that is negative or not a number
            raise LedgerError('a stored transfer record is not a valid transfer: '+str(exc)) from exc
        if (after.exchange_id != stored.exchange_id or list(records) != metadata['transfers']
                or applied != before+new):
            raise LedgerError('the stored stocks are not the parent stocks with these transfers applied once')
        self._keep(self._exchanges, commit, stored)
        self._keep(self._applied, commit, applied)
        return stored

    def _applied_digests(self, commit):
        applied = self._cached(self._applied, commit)
        if applied is _MISSING:
            self._exchanges.pop(commit.key, None)
            self._restored_exchange(commit, self._current(commit))
            applied = self._cached(self._applied, commit)
        return applied

    def sphere(self, commit):
        """The spherical network state (I03) at ``commit``, or None when this history has no network attached.

        The commit must be on the accepted chain to the head. A state read back from the store is rebuilt through
        integration_sphere's validating constructors; a successor's material must also be its parent's stored
        material with the commit's recorded transfers applied once (integration_transfer.restored), and every
        identity must reproduce. The recorded motion is applied again to rebuild the moved geometry; no
        intersection is measured again.
        """
        return self._restored_sphere(*self._on_chain(commit))

    def _restored_sphere(self, commit, metadata):
        state = self._cached(self._spheres, commit)
        if state is not _MISSING:
            return state
        if 'sphere' not in self._root_meta['declaration']:
            self._keep(self._spheres, commit, None)
            return None
        from . import integration_transfer as _transfer
        arrays = self._store.get(commit.key, budget=self._budget)
        try:
            parent = self._cached(self._spheres, self._issued(self._store.metadata(commit.parent_key)))
            if parent is _MISSING:
                parent = (self._store.metadata(commit.parent_key),
                          self._store.get(commit.parent_key, budget=self._budget))
            state = _transfer.restored(parent, metadata, arrays, budget=self._budget)
        except LedgerError:
            raise
        except (KeyError, TypeError) as exc:
            raise LedgerError('the stored spherical network is incomplete') from exc
        except TectonicsError as exc:
            raise LedgerError('the stored spherical network is not restored: '+str(exc)) from exc
        self._keep(self._spheres, commit, state)
        return state

    # ------------------------------------------------------------------------- inspection (I02.5/I02.6)

    def describe(self, commit):
        """What a commit holds: time, schedule, accounts, identities and fields, from its restored, validated state.

        The chain's manifest metadata is re-read, then only the root's and this commit's snapshots (and, with stocks,
        its parent's) are read; no physics runs. Every value is a fresh copy; editing it changes nothing held by the
        ledger.
        """
        commit, metadata = self._on_chain(commit)
        state = self._restored(commit, metadata)
        exchange = self._restored_exchange(commit, metadata)
        sphere = self._restored_sphere(commit, metadata)
        if sphere is not None:
            from . import integration_sphere as _sphere
            sphere = _sphere.summary(sphere)
        record, column = json.loads(state._record), state.column.descriptor()
        schedule = state.settings.descriptor()['numerical_policy']['schedule']
        accepted, steps = state.column.accepted_steps, state.settings.steps
        described = dict(
            ledger_id=self._ledger_id, key=commit.key, parent_key=commit.parent_key, sequence=commit.sequence,
            state_id=state.state_id, parent_state_id=state.parent_state_id, root_state_id=state.root_state_id,
            time_s=state.time_s, elapsed_s=state.column.elapsed_s, accepted_steps=accepted,
            remaining_steps=steps-accepted,
            history='initial' if accepted == 0 else 'complete' if accepted == steps else 'partial',
            interval=json.loads(json.dumps(metadata['interval'])), schedule=schedule, stretch=column['stretch'],
            accounts_j_m=column['accounts_j_m'], counters=column['counters'], extrema=column['extrema'],
            identity=dict(record['identity'], epoch_id=record['clock']['epoch_id'], unit_system=record['unit_system'],
                          frame_id=record['frame']['frame_id'], start_time_s=record['clock']['start_time_s']),
            identities=state.identities(), admission=state.admission,
            transfers=[t['transfer_id'] for t in metadata['transfers']],
            exchange=None if exchange is None else dict(exchange_id=exchange.exchange_id,
                                                        inventory_id=exchange.inventory.inventory_id,
                                                        exteriors=[list(pair) for pair in exchange.exteriors],
                                                        time_s=exchange.inventory.time_s,
                                                        closure=exchange.closure()),
            calendar=[list(event) for event in self.calendar], fields=sorted(self._fields(exchange is not None)))
        if sphere is not None:                   # I03: only a history with an attached network reports one
            described['sphere'] = sphere
        return described

    def _fields(self, stocked):
        names = {*_COLUMN_FIELDS, *DERIVED}
        names.update(item['name'] for item in self._root_meta['state']['reference']['arrays'])
        if stocked:
            names.update(EXCHANGE_FIELDS)
        return names

    def field(self, commit, name):
        """One physical field of ``commit`` with units, support, owner, accepted time and identity.

        Values come from the commit's restored, validated state (or stocks): after the chain's manifest metadata, only
        the root's and this commit's snapshots (and its parent's stocks for an exchange field) are read, and no physics
        runs. The array is a fresh read-only copy.
        """
        commit, metadata = self._on_chain(commit)
        state = self._restored(commit, metadata)
        exchange = self._restored_exchange(commit, metadata)
        if type(name) is not str or name not in self._fields(exchange is not None):
            raise LedgerError('unknown field; describe() lists the fields of a commit')
        if name in DERIVED:
            units, support, owner, meaning = DERIVED[name]
            values = getattr(state, name)
        elif name in EXCHANGE_FIELDS:
            units, support, owner, meaning = EXCHANGE_FIELDS[name]
            values = {'exchange.component_mass_kg': exchange.inventory.component_mass_kg,
                      'exchange.enthalpy_j': exchange.inventory.enthalpy_j,
                      'exchange.supplied_kg': exchange.supplied_kg, 'exchange.supplied_j': exchange.supplied_j}[name]
        else:
            _, units, support, owner, _, _, meaning = _state._INDEX[name]
            values = (getattr(state.column, _COLUMN_FIELDS[name]) if name in _COLUMN_FIELDS
                      else getattr(state.reference, _REFERENCE_FIELDS[name]))
        values = _copy(values)
        return dict(name=name, units=units, support=support, owner=owner, meaning=meaning, values=values,
                    dtype=values.dtype.str, shape=list(values.shape), commit=commit.key, state_id=state.state_id,
                    time_s=state.time_s, accepted_steps=state.column.accepted_steps, source_id=state.source_id,
                    runtime_id=state.runtime_id)

    # ------------------------------------------------------------------------- commits (I02.3)

    def commit(self, parent, path, transfers=(), *, cancel=None, budget=None):
        """Publish the accepted successor of ``parent``: its column state, accounts, stocks and transfers at once.

        ``path`` holds the accepted pieces a Continuation computed from the parent's state, in order (each the
        successor of the previous); the last is the committed state and together they span whole global steps. A
        declared, restored or otherwise issued state is refused, and so is a step past an unsupported calendar event.
        The committed state must satisfy the relations its restoration checks (integration_state.publishable), so the
        ledger never publishes a state that breaks them.
        ``transfers`` are applied during that interval to the parent's stocks; each must declare exactly this interval
        (the parent's global step to the last piece's), or the commit is refused. Everything is written in one store
        transaction that also performs the compare-and-swap of the head; a conflict, failure or cancellation publishes
        nothing. A lock another connection holds longer than the store's 5 s busy timeout surfaces as the store's
        StoreError: nothing is published and the call can be retried.
        """
        parent, expected_parent = self._authentic(parent)
        previous = self._restored(parent, expected_parent)
        pieces = tuple(path) if type(path) in (tuple, list) else None
        if not pieces or len(pieces) > MAX_PATH:
            raise LedgerError('a commit accepts one to %d advanced pieces' % MAX_PATH)
        context, prior, steps = _state._context(previous), previous.state_id, previous.column.accepted_steps
        for piece in pieces:
            piece = _state._verified(piece)
            if piece.issued_by != _state.COMPUTED:
                raise LedgerError('only states a Continuation computed from the accepted parent can be committed; '
                                  'declared or restored states cannot')
            if piece.parent_state_id != prior:
                raise LedgerError("an advanced piece does not continue the parent commit's accepted state")
            if _state._context(piece) != context:
                raise LedgerError('an advanced piece belongs to another history, reference, settings or payload')
            if piece.column.accepted_steps <= steps:
                raise LedgerError('each accepted piece advances whole global steps')
            prior, steps = piece.state_id, piece.column.accepted_steps
        end = pieces[-1]
        try:
            _state.publishable(end)
        except TectonicsError as exc:
            raise LedgerError('the accepted state breaks the relations its restoration checks, so it is not '
                              'published: '+str(exc)) from exc
        crossed = _crosses(self._root_meta['declaration']['calendar'], parent.time_s, end.time_s)
        if crossed is not None:
            raise LedgerError('a commit cannot step past the unsupported %s event %r in the declared calendar'
                              % crossed)
        interval = (parent.time_s, end.time_s, parent.accepted_steps, end.column.accepted_steps)
        key = successor_key(self._ledger_id, parent.key)
        transfers = tuple(transfers) if type(transfers) in (tuple, list) else None
        step = None
        if transfers is not None and 'sphere' in self._root_meta['declaration']:
            # I03.2: the attached network moves over exactly this interval. Its step is computed from the parent
            # commit's network state, and its finite-stock transfers join this commit's exchange.
            from . import integration_transfer as _transfer
            transfers, step = _transfer.proposed(self, parent, expected_parent, interval, transfers,
                                                 self._budget if budget is None else budget, cancel)
        if transfers is None or len(transfers) > MAX_TRANSFERS:
            raise ExchangeRefused('at most %d transfers per commit' % MAX_TRANSFERS)
        exchange = self._restored_exchange(parent, expected_parent)
        if exchange is None:
            if transfers:
                raise ExchangeRefused('no finite stocks are attached to this history: the closed strip transfers '
                                      'nothing')
            after, records, applied = None, (), ()
        else:
            if json.loads(_canonical(exchange.descriptor(), 'exchange record')) != expected_parent['exchange']:
                raise LedgerError('the parent stocks held in this process differ from the stored parent')
            applied = self._applied_digests(parent)
            after, records, new = _apply(self._ledger_id, parent.key, interval, key, exchange, transfers,
                                         set(applied), end.time_s)
            if not after.closure()['identity_exact']:
                raise LedgerError('the exchange accounts do not close exactly: nothing was published')
            applied = applied+new
            if len(applied) > MAX_APPLIED:
                raise LedgerError('the ledger transfer index is full')
        arrays = {'column.'+name: array for name, array in end.column._arrays() if name in CURRENT}
        if after is not None:
            arrays.update(_exchange_arrays(after, _applied(applied)))
        metadata = dict(schema=SCHEMA, kind='successor', ledger_id=self._ledger_id, key=key, parent_key=parent.key,
                        parent_digest=hashlib.sha256(parent._metadata).hexdigest(), sequence=parent.sequence+1,
                        interval=dict(start_s=interval[0], end_s=interval[1], start_step=interval[2],
                                      end_step=interval[3]),
                        path=[[piece.state_id, piece.column.accepted_steps] for piece in pieces],
                        transfers=list(records),
                        state=dict(state_id=end.state_id, parent_state_id=end.parent_state_id, time_s=end.time_s,
                                   elapsed_s=end.column.elapsed_s, accepted_steps=end.column.accepted_steps,
                                   column=end.column.descriptor()),
                        exchange=None if after is None else after.descriptor())
        if step is not None:
            arrays.update(step.arrays())
            metadata['sphere'] = step.record()
        self._checked(json.loads(_canonical(metadata, 'commit metadata')), parent)   # exactly what head() accepts
        store = self._store
        parent_index = None if after is None else store.reference(parent.key, 'ledger.applied').descriptor_sha256

        def check():
            # Inside the writer transaction, just before COMMIT: the parent is still this ledger's accepted commit
            # with the transfer index validated above. The head compare-and-swap itself is put()'s immutable key.
            if store.metadata(parent.key) != expected_parent:
                raise LedgerConflict('the parent commit is missing or changed')
            if parent_index is not None and store.reference(parent.key, 'ledger.applied').descriptor_sha256 != \
                    parent_index:
                raise LedgerConflict('the parent transfer index changed')
            # The store's change token as this transaction will leave it: nothing needs reading once the successor
            # is published, so nothing can fail after it.
            tokens.append(store.change_token())

        tokens, opened = [], store.change_token()
        try:
            store.put(key, arrays, metadata, publication_check=check, cancel=cancel,
                      budget=self._budget if budget is None else budget)
        except StoreConflict as exc:
            raise LedgerConflict('stale parent: another candidate is already accepted after this parent') from exc
        commit, chain = self._issued(metadata), self._chain
        # The checked chain stays exact only if nothing was written since it was read and no other connection
        # committed before this transaction began (data_version); otherwise the next read re-reads it.
        exact = (chain is not None and tokens and self._token == opened and tokens[-1][0] == opened[0]
                 and chain[-1].key == parent.key and chain[-1]._metadata == parent._metadata)
        object.__setattr__(self, '_chain', chain+(commit,) if exact else None)
        object.__setattr__(self, '_token', tokens[-1] if exact else None)
        self._keep(self._states, commit, end)
        self._keep(self._exchanges, commit, after)
        self._keep(self._applied, commit, applied)
        self._keep(self._spheres, commit, None if step is None else step.state)
        return commit
