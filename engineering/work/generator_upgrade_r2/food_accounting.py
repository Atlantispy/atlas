"""Exact commodity food accounts: obligations never manufacture physical stock.

All mass is available edible commodity kg, not raw crop mass or a proxy credit.
This bounded adapter does not infer diets, calendars, priority, physical farms,
nutritional completeness, transport, storage losses or observed production.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math

STATUSES = {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST", "UNKNOWN"}
KINDS = {"recurring_consumption", "one_off_reserve", "old_commitment", "new_increment"}
LIMIT = 4096
BITS = 8192


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(name + " requires a bounded nonblank identity/evidence")
    return value


def _q(value, name, *, positive=False, nullable=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float, Fraction, Decimal):
        raise ValueError(name + " requires an explicit real quantity")
    if (type(value) is float and not math.isfinite(value)) or (type(value) is Decimal and not value.is_finite()):
        raise ValueError(name + " must be finite")
    result = Fraction(value)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > BITS:
        raise ValueError(name + " exceeds exact-arithmetic bound")
    if result < 0 or (positive and not result):
        raise ValueError(name + " must be " + ("positive" if positive else "nonnegative"))
    return result


def _status(value):
    if value not in STATUSES:
        raise ValueError("unsupported source status")


def _records(items, cls, name, key):
    if not isinstance(items, (tuple, list)) or len(items) > LIMIT or any(type(x) is not cls for x in items):
        raise ValueError("bounded explicit " + name + " required")
    if len({getattr(x, key) for x in items}) != len(items):
        raise ValueError("duplicate " + name + " identity")
    return tuple(sorted(items, key=lambda x: getattr(x, key)))


def _ids(values, name):
    if not isinstance(values, tuple) or not values or len(values) > LIMIT:
        raise ValueError("explicit nonempty " + name + " required")
    for value in values:
        _text(value, name)
    if len(set(values)) != len(values):
        raise ValueError("duplicate " + name)


@dataclass(frozen=True)
class Period:
    period_id: str
    duration_years: object
    days_per_year: object
    calendar_evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.period_id, "period")
        _text(self.calendar_evidence, "calendar evidence")
        _status(self.source_status)
        for key in ("duration_years", "days_per_year"):
            object.__setattr__(self, key, _q(getattr(self, key), key, positive=True, nullable=True))


@dataclass(frozen=True)
class FoodComponent:
    commodity_id: str
    energy_share: object
    edible_energy_kcal_kg: object
    composition_evidence: str

    def __post_init__(self):
        _text(self.commodity_id, "commodity")
        _text(self.composition_evidence, "composition evidence")
        object.__setattr__(self, "energy_share", _q(self.energy_share, "energy share", nullable=True))
        object.__setattr__(self, "edible_energy_kcal_kg", _q(self.edible_energy_kcal_kg, "energy density", positive=True, nullable=True))
        if self.energy_share is not None and self.energy_share > 1:
            raise ValueError("energy share exceeds one")


@dataclass(frozen=True)
class FoodBundle:
    bundle_id: str
    components: tuple[FoodComponent, ...]
    energy_kcal_person_day: object
    diet_evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.bundle_id, "bundle")
        _text(self.diet_evidence, "diet evidence")
        _status(self.source_status)
        components = _records(self.components, FoodComponent, "food components", "commodity_id")
        if not components:
            raise ValueError("a food bundle requires explicit commodity composition")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "energy_kcal_person_day", _q(self.energy_kcal_person_day, "daily energy", positive=True, nullable=True))
        known = sum((c.energy_share for c in components if c.energy_share is not None), Fraction())
        if known > 1 or (all(c.energy_share is not None for c in components) and known != 1):
            raise ValueError("energy shares must sum exactly to one")


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    node_id: str
    bundle_id: str
    kind: str
    recurrence: str
    amount_unit: str
    amount: object
    component_claim_ids: tuple[str, ...]
    evidence: str
    source_status: str

    def __post_init__(self):
        for key in ("obligation_id", "node_id", "bundle_id", "evidence"):
            _text(getattr(self, key), key)
        _status(self.source_status)
        _ids(self.component_claim_ids, "atomic accounting claims")
        if self.kind not in KINDS or self.recurrence not in {"per_year", "one_off"} or self.amount_unit not in {"person_years", "kcal"}:
            raise ValueError("explicit obligation kind, recurrence and units required")
        if self.kind == "recurring_consumption" and self.recurrence != "per_year":
            raise ValueError("recurring consumption is an annual rate")
        if self.kind == "one_off_reserve" and self.recurrence != "one_off":
            raise ValueError("initial reserve is a one-off stock, not an annual rate")
        object.__setattr__(self, "amount", _q(self.amount, "obligation amount", nullable=True))


def convert_obligation(obligation, bundle, period):
    """Convert a supplied dietary energy accounting obligation, never to supply.

    person_years/per_year denotes person-year equivalents per declared year;
    person_years/one_off is a finite energy obligation, e.g. an initial reserve.
    """
    if type(obligation) is not Obligation or type(bundle) is not FoodBundle or type(period) is not Period:
        raise ValueError("typed obligation, bundle and period required")
    if obligation.bundle_id != bundle.bundle_id:
        raise ValueError("obligation uses a different dietary bundle")
    unknown = (obligation.source_status == "UNKNOWN" or bundle.source_status == "UNKNOWN" or period.source_status == "UNKNOWN"
               or obligation.amount is None or bundle.energy_kcal_person_day is None or period.days_per_year is None
               or period.duration_years is None or any(c.energy_share is None or c.edible_energy_kcal_kg is None for c in bundle.components))
    base = {"obligation_id": obligation.obligation_id, "node_id": obligation.node_id, "bundle_id": bundle.bundle_id,
            "kind": obligation.kind, "recurrence": obligation.recurrence, "amount_unit": obligation.amount_unit,
            "amount": obligation.amount, "period_id": period.period_id, "component_claim_ids": obligation.component_claim_ids,
            "evidence": obligation.evidence, "diet_evidence": bundle.diet_evidence, "calendar_evidence": period.calendar_evidence,
            "input_source_status": obligation.source_status, "nutritional_completeness": False,
            "duration_years": period.duration_years, "days_per_year": period.days_per_year,
            "daily_person_energy_kcal": bundle.energy_kcal_person_day,
            "components": [{"commodity_id": c.commodity_id, "energy_share": c.energy_share,
                            "edible_energy_kcal_kg": c.edible_energy_kcal_kg, "composition_evidence": c.composition_evidence} for c in bundle.components],
            "bundle_source_status": bundle.source_status, "calendar_source_status": period.source_status}
    if unknown:
        return {**base, "status": "UNKNOWN", "energy_kcal": None, "commodity_kg": None}
    energy = obligation.amount
    if obligation.amount_unit == "person_years":
        energy = _q(energy * bundle.energy_kcal_person_day * period.days_per_year, "person-year energy")
    if obligation.recurrence == "per_year":
        energy = _q(energy * period.duration_years, "period energy")
    mass = {c.commodity_id: _q(energy*c.energy_share/c.edible_energy_kcal_kg, "commodity demand") for c in bundle.components}
    if sum((mass[c.commodity_id]*c.edible_energy_kcal_kg for c in bundle.components), Fraction()) != energy:
        raise ArithmeticError("food conversion energy failed exact conservation")
    return {**base, "status": "CONVERTED", "energy_kcal": energy, "commodity_kg": mass}


@dataclass(frozen=True)
class FoodStock:
    stock_id: str
    node_id: str
    commodity_id: str
    period_id: str
    quantity_kg: object
    edible_energy_kcal_kg: object
    origin: str
    source_id: str
    source_use_ids: tuple[str, ...]
    production_evidence: tuple[str, ...]
    evidence: str
    source_status: str

    def __post_init__(self):
        for key in ("stock_id", "node_id", "commodity_id", "period_id", "source_id", "evidence"):
            _text(getattr(self, key), key)
        _status(self.source_status)
        if self.origin not in {"harvest", "inventory"}:
            raise ValueError("physical stock requires harvest or inventory, never an accounting credit")
        _ids(self.source_use_ids, "physical source-use identities")
        if not isinstance(self.production_evidence, tuple) or not self.production_evidence or len(self.production_evidence) > LIMIT:
            raise ValueError("explicit production/inventory evidence required")
        for evidence in self.production_evidence:
            _text(evidence, "production/inventory evidence")
        if self.origin == "harvest" and len(self.production_evidence) != 3:
            raise ValueError("harvest requires allocation, yield-regime and water-budget evidence")
        object.__setattr__(self, "quantity_kg", _q(self.quantity_kg, "physical edible stock", nullable=True))
        object.__setattr__(self, "edible_energy_kcal_kg", _q(self.edible_energy_kcal_kg, "stock commodity composition", positive=True, nullable=True))


@dataclass(frozen=True)
class StockDebit:
    use_id: str
    stock_id: str
    quantity_kg: object
    kind: str
    component_claim_ids: tuple[str, ...]
    evidence: str

    def __post_init__(self):
        for key in ("use_id", "stock_id", "evidence"):
            _text(getattr(self, key), key)
        if self.kind not in KINDS:
            raise ValueError("source debit requires its preserved obligation kind")
        _ids(self.component_claim_ids, "already charged atomic claims")
        object.__setattr__(self, "quantity_kg", _q(self.quantity_kg, "prior source debit", nullable=True))


@dataclass(frozen=True)
class LocalPolicy:
    node_id: str
    protected_order: tuple[str, ...]
    obligation_order: tuple[str, ...]
    block_export_on_shortfall: bool
    evidence: str

    def __post_init__(self):
        _text(self.node_id, "policy node")
        _text(self.evidence, "local allocation policy")
        if type(self.block_export_on_shortfall) is not bool:
            raise ValueError("explicit export-shortfall policy required")
        if not isinstance(self.protected_order, tuple) or set(self.protected_order) - {"recurring_consumption", "one_off_reserve"} or len(set(self.protected_order)) != len(self.protected_order):
            raise ValueError("only explicit local consumption/reserve priorities are supported")
        if not isinstance(self.obligation_order, tuple) or len(set(self.obligation_order)) != len(self.obligation_order):
            raise ValueError("explicit unique local obligation priority required")
        for identity in self.obligation_order:
            _text(identity, "priority obligation")


def prepare_accounts(stocks, obligations, bundles, period, policies, *, prior_debits, source_ledger_complete):
    """Reserve/consume only real source mass under a supplied local policy.

    Prior debits are already charged uses, not a second fulfilment of outstanding
    obligations. Reusing an atomic claim in either inventory rejects. Additionality
    is a reconciled ledger claim only, not independently validated new agriculture.
    """
    stocks = _records(stocks, FoodStock, "stocks", "stock_id")
    obligations = _records(obligations, Obligation, "obligations", "obligation_id")
    bundles = _records(bundles, FoodBundle, "bundles", "bundle_id")
    policies = _records(policies, LocalPolicy, "local policies", "node_id")
    debits = _records(prior_debits, StockDebit, "prior debits", "use_id")
    if type(period) is not Period or type(source_ledger_complete) is not bool:
        raise ValueError("explicit period and source-ledger completeness required")
    stock_by_id = {s.stock_id: s for s in stocks}
    bundle_by_id = {b.bundle_id: b for b in bundles}
    if any(s.period_id != period.period_id for s in stocks):
        raise ValueError("stocks and demand must share the explicitly bound period")
    source_ids = [x for s in stocks for x in s.source_use_ids]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("physical source already imported: would duplicate stock/additionality")
    claims = [x for o in obligations for x in o.component_claim_ids] + [x for d in debits for x in d.component_claim_ids]
    if len(set(claims)) != len(claims):
        raise ValueError("atomic accounting claim already used; first-year sum is not a third claim")
    if any(d.stock_id not in stock_by_id for d in debits):
        raise ValueError("source debit has no physical stock")
    if any(o.bundle_id not in bundle_by_id for o in obligations):
        raise ValueError("unbound dietary bundle")
    # One commodity identity cannot silently represent incompatible compositions.
    composition = {}
    for group in [b.components for b in bundles] + [stocks]:
        for c in group:
            if c.edible_energy_kcal_kg is not None:
                if c.commodity_id in composition and composition[c.commodity_id] != c.edible_energy_kcal_kg:
                    raise ValueError("conflicting energy density for the same commodity")
                composition[c.commodity_id] = c.edible_energy_kcal_kg
    nodes = {s.node_id for s in stocks} | {o.node_id for o in obligations}
    if {p.node_id for p in policies} != nodes:
        raise ValueError("every scenario node requires its explicit local export policy")
    for p in policies:
        wanted = {o.obligation_id for o in obligations if o.node_id == p.node_id and o.kind in p.protected_order}
        if set(p.obligation_order) != wanted:
            raise ValueError("policy must order exactly its protected local obligations")
        ordered_kinds = [next(o.kind for o in obligations if o.obligation_id == key) for key in p.obligation_order]
        ranks = [p.protected_order.index(k) for k in ordered_kinds]
        if ranks != sorted(ranks):
            raise ValueError("local obligation order contradicts declared kind priority")
    converted = [convert_obligation(o, bundle_by_id[o.bundle_id], period) for o in obligations]
    reasons = []
    if not source_ledger_complete:
        reasons.append("source-use/additionality ledger incomplete")
    reasons += ["stock:"+s.stock_id for s in stocks if s.quantity_kg is None or s.edible_energy_kcal_kg is None or s.source_status == "UNKNOWN"]
    reasons += ["obligation:"+r["obligation_id"] for r in converted if r["status"] == "UNKNOWN"]
    reasons += ["debit:"+d.use_id for d in debits if d.quantity_kg is None]
    reasons += ["bundle:"+b.bundle_id for b in bundles if b.source_status == "UNKNOWN" or b.energy_kcal_person_day is None
                or any(c.energy_share is None or c.edible_energy_kcal_kg is None for c in b.components)]
    if period.source_status == "UNKNOWN" or period.days_per_year is None or period.duration_years is None:
        reasons.append("calendar")
    base = {"schema": "diadem.food-commodity-accounts.r2", "period_id": period.period_id,
            "conversions": converted, "unresolved": reasons, "physical_additionality_validated": False,
            "source_ledger_complete": source_ledger_complete,
            "local_policies": [{"node_id": p.node_id, "protected_order": p.protected_order, "obligation_order": p.obligation_order,
                                "block_export_on_shortfall": p.block_export_on_shortfall, "evidence": p.evidence} for p in policies],
            "source_status": "SYNTHETIC TEST" if all(x.source_status == "SYNTHETIC TEST" for x in (*stocks, *obligations, *bundles, period)) else "WORKING NON-CANON"}
    # Even incomplete scenarios must not conceal a demonstrated known overdraft.
    for stock in stocks:
        charged = sum((d.quantity_kg for d in debits if d.stock_id == stock.stock_id and d.quantity_kg is not None), Fraction())
        if stock.quantity_kg is not None and charged > stock.quantity_kg:
            raise ValueError("existing commitments exceed physical source stock")
    if reasons:
        return {**base, "status": "UNKNOWN", "stock_ledger": None, "local_uses": None,
                "remaining_demands": None, "exportable_supply_kg": None, "mass_basis": "available_edible_kg"}
    available = {s.stock_id: s.quantity_kg for s in stocks}
    charged = {s.stock_id: Fraction() for s in stocks}
    for d in debits:
        available[d.stock_id] -= d.quantity_kg
        charged[d.stock_id] += d.quantity_kg
    remaining = {(r["obligation_id"], c): q for r in converted for c, q in r["commodity_kg"].items()}
    lookup = {r["obligation_id"]: r for r in converted}
    uses = []
    for policy in policies:
        for identity in policy.obligation_order:
            row = lookup[identity]
            for commodity in sorted(row["commodity_kg"]):
                key = (identity, commodity)
                for stock in stocks:
                    if stock.node_id != policy.node_id or stock.commodity_id != commodity:
                        continue
                    take = min(available[stock.stock_id], remaining[key])
                    if take:
                        available[stock.stock_id] -= take
                        remaining[key] -= take
                        uses.append({"stock_id": stock.stock_id, "obligation_id": identity, "node_id": policy.node_id,
                                     "commodity_id": commodity, "quantity_kg": take, "kind": row["kind"],
                                     "disposition": "reserved_stock" if row["kind"] == "one_off_reserve" else "consumed",
                                     "policy_evidence": policy.evidence})
    blocked = {p.node_id for p in policies if p.block_export_on_shortfall and any(remaining[(oid, c)] > 0 for oid in p.obligation_order for c in lookup[oid]["commodity_kg"])}
    ledgers, exportable = [], {}
    for stock in stocks:
        consumed = sum((u["quantity_kg"] for u in uses if u["stock_id"] == stock.stock_id and u["disposition"] == "consumed"), Fraction())
        reserved = sum((u["quantity_kg"] for u in uses if u["stock_id"] == stock.stock_id and u["disposition"] == "reserved_stock"), Fraction())
        held = available[stock.stock_id] if stock.node_id in blocked else Fraction()
        free = available[stock.stock_id] - held
        residual = stock.quantity_kg - charged[stock.stock_id] - consumed - reserved - held - free
        if residual != 0:
            raise ArithmeticError("physical stock failed exact conservation")
        key = (stock.node_id, stock.commodity_id)
        exportable[key] = _q(exportable.get(key, Fraction()) + free, "exportable commodity stock")
        ledgers.append({"stock_id": stock.stock_id, "node_id": stock.node_id, "commodity_id": stock.commodity_id,
                        "source_id": stock.source_id, "source_use_ids": stock.source_use_ids,
                        "production_evidence": stock.production_evidence, "evidence": stock.evidence, "origin": stock.origin,
                        "input_source_status": stock.source_status, "edible_energy_kcal_kg": stock.edible_energy_kcal_kg,
                        "initial_kg": stock.quantity_kg, "prior_debit_kg": charged[stock.stock_id], "consumed_kg": consumed,
                        "reserved_kg": reserved, "held_kg": held, "exportable_kg": free, "residual_kg": residual})
    demands = [{"obligation_id": r["obligation_id"], "node_id": r["node_id"], "commodity_id": c,
                "quantity_kg": remaining[(r["obligation_id"], c)], "kind": r["kind"],
                "recurrence": r["recurrence"], "component_claim_ids": r["component_claim_ids"]}
               for r in converted for c in sorted(r["commodity_kg"])]
    return {**base, "status": "ACCOUNTED", "stock_ledger": ledgers, "local_uses": uses,
            "remaining_demands": demands, "exportable_supply_kg": exportable,
            "prior_debits": [{"use_id": d.use_id, "stock_id": d.stock_id, "quantity_kg": d.quantity_kg,
                              "kind": d.kind, "component_claim_ids": d.component_claim_ids, "evidence": d.evidence} for d in debits],
            "export_blocked_nodes": sorted(blocked), "transport_fulfilment": "NOT_SOLVED", "mass_basis": "available_edible_kg"}


@dataclass(frozen=True)
class HarvestBinding:
    option_id: str
    physical_parent_id: str
    commodity_id: str
    node_id: str
    stock_id: str
    source_use_id: str
    allocation_evidence: str
    yield_regime_evidence: str
    water_budget_evidence: str
    edible_energy_kcal_kg: object

    def __post_init__(self):
        for key in ("option_id", "physical_parent_id", "commodity_id", "node_id", "stock_id", "source_use_id", "allocation_evidence", "yield_regime_evidence", "water_budget_evidence"):
            _text(getattr(self, key), key)
        object.__setattr__(self, "edible_energy_kcal_kg", _q(self.edible_energy_kcal_kg, "harvest commodity energy", positive=True, nullable=True))


def _rounding_bound(values):
    """Only the predecessor's declared binary64 arithmetic gets an ULP bound."""
    return 4 * sum((Fraction(math.ulp(v)) for v in values if type(v) is float), Fraction())


def stocks_from_food_budget(food_budget, bindings, period, *, source_id, one_representative_harvest_in_period):
    """Import actual R1 food_budget rows; annual crop output is not an accounting credit.

    This adapter admits one explicitly modelled annual harvest, not partial-year
    interpolation. It retains source status; MODELLED supply is not observed stock.
    """
    bindings = _records(bindings, HarvestBinding, "harvest bindings", "option_id")
    if type(period) is not Period or not isinstance(food_budget, dict) or food_budget.get("schema") != "diadem.independent-food-energy-budget.r1":
        raise ValueError("actual independent food budget schema and declared period required")
    _text(source_id, "actual producer/source identity")
    if one_representative_harvest_in_period is not True or (period.duration_years is not None and period.duration_years != 1):
        raise ValueError("annual harvest stock requires exactly one declared representative annual cycle")
    rows = food_budget.get("rows")
    unknown = food_budget.get("unknown_parcel_ids")
    if not isinstance(rows, list) or len(rows) > LIMIT or not isinstance(unknown, list) or len(unknown) > LIMIT:
        raise ValueError("bounded food rows and explicit unknown inventory required")
    if any(not isinstance(r, dict) for r in rows):
        raise ValueError("invalid food row")
    row_ids = [r.get("parcel_id") for r in rows]
    for value in row_ids + unknown:
        _text(value, "food option identity")
    if len(set(row_ids + unknown)) != len(row_ids + unknown):
        raise ValueError("food source contains duplicate known/unknown option")
    if {b.option_id for b in bindings} != set(row_ids + unknown):
        raise ValueError("explicit option-to-parent/commodity/node mapping must cover every food row")
    for field in ("stock_id", "source_use_id"):
        if len({getattr(b, field) for b in bindings}) != len(bindings):
            raise ValueError("duplicate harvest stock/source-use mapping")
    mapping = {b.option_id: b for b in bindings}
    stocks, ledger = [], []
    reasons = ["unknown food option:"+x for x in unknown]
    for row in sorted(rows, key=lambda r: r["parcel_id"]):
        b = mapping[row["parcel_id"]]
        _text(row.get("evidence"), "food production evidence")
        _status(row.get("source_status"))
        keys = ("harvest_kg_year", "non_edible_kg_year", "loss_kg_year", "available_food_kg_year")
        values = [row.get(k) for k in keys]
        h, n, loss, food = [_q(v, k) for k, v in zip(keys, values)]
        budget = h-n-loss
        if budget < 0 or abs(h-n-loss-food) > _rounding_bound(values):
            raise ValueError("upstream harvest partition is physically inconsistent beyond represented rounding")
        accepted = min(food, budget)
        # Preserve reported available food conservatively: no upward roundoff supply.
        upstream_energy = _q(row.get("available_energy_kcal_year"), "upstream available energy")
        if b.edible_energy_kcal_kg is None or row["source_status"] == "UNKNOWN":
            reasons.append("unresolved harvest commodity:"+b.option_id)
        else:
            physical_energy = food*b.edible_energy_kcal_kg
            if abs(physical_energy-upstream_energy) > _rounding_bound([row.get("available_energy_kcal_year")]):
                raise ValueError("harvest commodity composition does not match actual food energy")
        derived_status = "SYNTHETIC TEST" if row["source_status"] == "SYNTHETIC TEST" and period.source_status == "SYNTHETIC TEST" else "WORKING NON-CANON"
        event_identity = "harvest-event:" + hashlib.sha256(json.dumps([source_id, period.period_id, b.option_id], separators=(",", ":")).encode()).hexdigest()
        stocks.append(FoodStock(b.stock_id, b.node_id, b.commodity_id, period.period_id, accepted, b.edible_energy_kcal_kg, "harvest", source_id,
                               (b.source_use_id, event_identity), (b.allocation_evidence, b.yield_regime_evidence, b.water_budget_evidence),
                               row["evidence"], derived_status))
        ledger.append({"option_id": b.option_id, "physical_parent_id": b.physical_parent_id, "stock_id": b.stock_id,
                       "harvest_kg": h, "non_edible_kg": n, "loss_kg": loss, "reported_available_kg": food,
                       "accepted_stock_kg": accepted, "unassigned_rounding_kg": budget-accepted,
                       "withheld_available_rounding_kg": food-accepted, "mass_residual_kg": h-n-loss-accepted-(budget-accepted),
                       "input_source_status": row["source_status"], "derived_stock_status": derived_status})
    if period.source_status == "UNKNOWN" or period.days_per_year is None or period.duration_years is None:
        reasons.append("calendar")
    digest = hashlib.sha256(json.dumps(food_budget, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"schema": "diadem.harvest-stock-import.r2", "status": "UNKNOWN" if reasons else "IMPORTED",
            "stocks": None if reasons else tuple(stocks), "unresolved": reasons, "harvest_ledger": ledger,
            "food_budget_sha256": digest, "source_id": source_id, "period_id": period.period_id,
            "observed_production_claim": False}


def exact_json(value):
    """JSON-safe exact receipt; [numerator, denominator] is always labelled."""
    if isinstance(value, Fraction):
        return {"numerator": value.numerator, "denominator": value.denominator}
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            return [{"key": exact_json(k), "value": exact_json(v)} for k, v in sorted(value.items())]
        return {k: exact_json(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [exact_json(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {k: exact_json(getattr(value, k)) for k in value.__dataclass_fields__}
    return value
