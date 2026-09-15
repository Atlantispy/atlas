"""Independent exact food accounts and real retained-producer interface checks."""
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction as F
import hashlib
import itertools
import json
from pathlib import Path
import sys
import types
import unittest
import uuid

from . import food_accounting as fa

E = "DECLARED SYNTHETIC SCENARIO; NOT DIADEM AGRONOMY OR POPULATION"
S = "SYNTHETIC TEST"


def period(years=1, days=360):
    return fa.Period("scenario-year", years, days, E, S)


def bundle(components=None, daily=10, identity="diet"):
    return fa.FoodBundle(identity, components or (fa.FoodComponent("grain", 1, 100, E),), daily, E, S)


def obligation(identity="local", kind="recurring_consumption", amount=1, node="farm", recurrence=None, unit="person_years"):
    return fa.Obligation(identity, node, "diet", kind, recurrence or ("one_off" if kind == "one_off_reserve" else "per_year"),
                         unit, amount, ("claim:"+identity,), E, S)


def stock(identity="harvest", quantity=100, node="farm", commodity="grain", density=100):
    return fa.FoodStock(identity, node, commodity, "scenario-year", quantity, density, "harvest", "real-producer-output",
                        ("physical-lot:"+identity,), (E+":allocated geometry", E+":yield regime", E+":water budget"), E, S)


def policy(node="farm", order=("local",), kinds=("recurring_consumption", "one_off_reserve"), block=True):
    return fa.LocalPolicy(node, kinds, order, block, E)


def accounts(stocks=None, obligations=None, bundles=None, policies=None, **kw):
    return fa.prepare_accounts(stocks if stocks is not None else [stock()], obligations if obligations is not None else [obligation()],
                               bundles if bundles is not None else [bundle()], kw.pop("period", period()),
                               policies if policies is not None else [policy()], prior_debits=kw.pop("prior_debits", []),
                               source_ledger_complete=kw.pop("source_ledger_complete", True), **kw)


def actual_land_food(yield_kg=2, fraction=.75, losses=.1, population=100):
    path = Path(__file__).resolve().parents[1]/"generator_upgrade_r1"/"land_food.py"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != "4930ca4d09069a96e02de1127ddbf283a56ab17b04b9263a4ab6d4501976a4f3":
        raise RuntimeError("preserved land-food producer changed")
    name = "_food_accounting_actual_" + uuid.uuid4().hex
    m = types.ModuleType(name)
    m.__file__ = str(path)
    sys.modules[name] = m
    try:
        exec(compile(raw, str(path), "exec", optimize=sys.flags.optimize), m.__dict__)
        result = m.allocate_land_food([m.LandParcel("physical-parent", (0, 0, 10, 1), "water", E, S)],
                    [m.CropOption("option", "physical-parent", "synthetic-grain", yield_kg, fraction, losses, 100,
                                  1, 1, E, S)], [m.WaterPool("water", 10, E, S)], frame_id="synthetic-metres",
                    annual_energy_kcal_per_person=3600, fixed_population=population)
        if path.read_bytes() != raw:
            raise RuntimeError("producer changed during actual call")
        return result
    finally:
        sys.modules.pop(name, None)


def binding(**kw):
    return replace(fa.HarvestBinding("option", "physical-parent", "grain", "farm", "harvest", "physical-harvest-one",
                                    E+":actual allocation", E+":actual yield", E+":actual water", 100), **kw)


class FoodAccountingTests(unittest.TestCase):
    def test_exact_two_commodity_energy_composition(self):
        b = bundle((fa.FoodComponent("grain", F(3, 4), 120, E), fa.FoodComponent("pulse", F(1, 4), 60, E)))
        r = fa.convert_obligation(obligation(amount=F(2, 3)), b, period())
        self.assertEqual(r["energy_kcal"], 2400)
        self.assertEqual(r["commodity_kg"], {"grain": F(15), "pulse": F(10)})
        self.assertFalse(r["nutritional_completeness"])

    def test_calendar_and_period_scale_recurring_not_one_off(self):
        annual = obligation(amount=2)
        reserve = obligation("reserve", "one_off_reserve", 2)
        self.assertEqual(fa.convert_obligation(annual, bundle(), period(F(1, 2), 300))["energy_kcal"], 3000)
        self.assertEqual(fa.convert_obligation(reserve, bundle(), period(F(1, 2), 300))["energy_kcal"], 6000)

    def test_explicit_kcal_is_not_person_years(self):
        r = fa.convert_obligation(obligation(amount=1000, unit="kcal"), bundle(), period(2))
        self.assertEqual(r["commodity_kg"], {"grain": 20})

    def test_decimal_and_binary_float_have_declared_exact_meanings(self):
        a = fa.convert_obligation(obligation(amount=Decimal("0.1")), bundle(), period())
        b = fa.convert_obligation(obligation(amount=.1), bundle(), period())
        self.assertEqual(a["energy_kcal"], 360)
        self.assertEqual(b["energy_kcal"], F(.1)*3600)
        self.assertNotEqual(a["energy_kcal"], b["energy_kcal"])

    def test_local_consumption_reserve_and_export_are_separate(self):
        obs = [obligation(), obligation("reserve", "one_off_reserve", F(1, 2))]
        r = accounts(obligations=obs, policies=[policy(order=("local", "reserve"))])
        row = r["stock_ledger"][0]
        self.assertEqual((row["initial_kg"], row["consumed_kg"], row["reserved_kg"], row["exportable_kg"]), (100, 36, 18, 46))
        self.assertEqual(row["residual_kg"], 0)
        self.assertEqual([u["disposition"] for u in r["local_uses"]], ["consumed", "reserved_stock"])

    def test_shortage_remains_real_demand_and_no_fabricated_supply(self):
        r = accounts(stocks=[stock(quantity=10)])
        self.assertEqual(r["remaining_demands"][0]["quantity_kg"], 26)
        self.assertEqual(r["exportable_supply_kg"], {("farm", "grain"): 0})
        self.assertEqual(r["export_blocked_nodes"], ["farm"])

    def test_missing_diet_commodity_does_not_substitute_other_food(self):
        r = accounts(stocks=[stock(commodity="pulse", density=60)])
        self.assertEqual(r["stock_ledger"][0]["held_kg"], 100)
        self.assertEqual(r["remaining_demands"][0]["quantity_kg"], 36)

    def test_export_hold_is_explicit_scenario_policy(self):
        r = accounts(stocks=[stock(commodity="pulse", density=60)], policies=[replace(policy(), block_export_on_shortfall=False)])
        self.assertEqual(r["stock_ledger"][0]["exportable_kg"], 100)
        self.assertEqual(r["remaining_demands"][0]["quantity_kg"], 36)

    def test_old_and_incremental_obligations_remain_separate(self):
        obs = [obligation("old", "old_commitment", 1, "town"), obligation("new", "new_increment", F(1, 2), "town")]
        r = accounts(obligations=obs, policies=[policy(order=()), policy("town", order=())])
        self.assertEqual([(d["kind"], d["quantity_kg"]) for d in r["remaining_demands"]], [("new_increment", 18), ("old_commitment", 36)])
        self.assertEqual(r["stock_ledger"][0]["exportable_kg"], 100)
        self.assertFalse(r["physical_additionality_validated"])

    def test_first_year_summary_cannot_be_a_third_atomic_credit(self):
        a = obligation()
        reserve = obligation("reserve", "one_off_reserve")
        total = replace(obligation("first-year", "new_increment"), component_claim_ids=a.component_claim_ids+reserve.component_claim_ids)
        with self.assertRaisesRegex(ValueError, "atomic accounting claim"):
            accounts(obligations=[a, reserve, total], policies=[policy(order=("local", "reserve"))])

    def test_accounting_credit_is_not_a_stock_origin(self):
        for value in ("credit", "obligation", "person_years", "population"):
            with self.subTest(origin=value), self.assertRaises(ValueError):
                replace(stock(), origin=value)

    def test_source_alias_and_additionality_double_import_reject(self):
        with self.assertRaisesRegex(ValueError, "already imported"):
            accounts(stocks=[stock(), replace(stock("duplicate"), source_use_ids=stock().source_use_ids)])

    def test_prior_source_use_reduces_export_once(self):
        debit = fa.StockDebit("already charged", "harvest", 20, "old_commitment", ("old-credit",), E)
        r = accounts(prior_debits=[debit])
        self.assertEqual(r["stock_ledger"][0]["prior_debit_kg"], 20)
        self.assertEqual(r["stock_ledger"][0]["exportable_kg"], 44)
        self.assertEqual(r["prior_debits"][0]["kind"], "old_commitment")

    def test_existing_and_outstanding_claim_cannot_be_charged_twice(self):
        debit = fa.StockDebit("use", "harvest", 20, "old_commitment", ("claim:local",), E)
        with self.assertRaisesRegex(ValueError, "already used"):
            accounts(prior_debits=[debit])

    def test_source_overdraft_rejects_even_when_other_input_unknown(self):
        debit = fa.StockDebit("use", "harvest", 101, "old_commitment", ("old",), E)
        with self.assertRaisesRegex(ValueError, "exceed physical"):
            accounts(prior_debits=[debit], source_ledger_complete=False)

    def test_unknown_is_not_zero_and_incomplete_history_blocks_certificate(self):
        for kwargs in ({"stocks": [replace(stock(), quantity_kg=None)]}, {"obligations": [replace(obligation(), amount=None)]},
                       {"source_ledger_complete": False}, {"bundles": [replace(bundle(), energy_kcal_person_day=None)]},
                       {"period": replace(period(), days_per_year=None)}):
            with self.subTest(kwargs=kwargs):
                r = accounts(**kwargs)
                self.assertEqual(r["status"], "UNKNOWN")
                self.assertIsNone(r["exportable_supply_kg"])
                self.assertIsNone(r["remaining_demands"])
                self.assertTrue(r["unresolved"])

    def test_known_empty_supply_retains_shortage(self):
        r = accounts(stocks=[])
        self.assertEqual(r["status"], "ACCOUNTED")
        self.assertEqual(r["exportable_supply_kg"], {})
        self.assertEqual(r["remaining_demands"][0]["quantity_kg"], 36)

    def test_stock_invariant_independent_exhaustive_small_oracle(self):
        for initial, need, reserved in itertools.product(range(6), repeat=3):
            obs = [obligation(amount=need, unit="kcal"), obligation("reserve", "one_off_reserve", reserved, unit="kcal")]
            r = accounts(stocks=[stock(quantity=F(initial, 100))], obligations=obs, policies=[policy(order=("local", "reserve"))])
            row = r["stock_ledger"][0]
            consumed = min(initial, need)
            kept = min(initial-consumed, reserved)
            self.assertEqual(row["consumed_kg"], F(consumed, 100))
            self.assertEqual(row["reserved_kg"], F(kept, 100))
            self.assertEqual(sum(row[k] for k in ("prior_debit_kg", "consumed_kg", "reserved_kg", "held_kg", "exportable_kg")), F(initial, 100))

    def test_input_permutations_do_not_change_declared_priority(self):
        stocks = [stock("b", 40), stock("a", 60)]
        obs = [obligation(), obligation("reserve", "one_off_reserve", F(1, 2))]
        a = accounts(stocks=stocks, obligations=obs, policies=[policy(order=("local", "reserve"))])
        b = accounts(stocks=stocks[::-1], obligations=obs[::-1], policies=[policy(order=("local", "reserve"))])
        self.assertEqual(a, b)

    def test_priority_not_inferred_from_alphabetical_obligation_ids(self):
        obs = [obligation("z", amount=1), obligation("a", amount=1)]
        r = accounts(stocks=[stock(quantity=40)], obligations=obs, policies=[policy(order=("z", "a"))])
        self.assertEqual(r["local_uses"][0]["obligation_id"], "z")
        self.assertEqual(r["local_uses"][0]["quantity_kg"], 36)

    def test_missing_or_contradictory_priority_rejects(self):
        obs = [obligation(), obligation("reserve", "one_off_reserve")]
        for p in (policy(order=("local",)), policy(order=("reserve", "local"))):
            with self.assertRaises(ValueError):
                accounts(obligations=obs, policies=[p])
        with self.assertRaises(ValueError):
            accounts(policies=[])

    def test_conflicting_commodity_composition_and_period_reject(self):
        with self.assertRaisesRegex(ValueError, "conflicting energy"):
            accounts(stocks=[stock(density=200)])
        with self.assertRaises(ValueError):
            accounts(stocks=[replace(stock(), period_id="another-year")])

    def test_invalid_exact_inputs_and_evidence_reject(self):
        for value in (True, -1, float("nan"), float("inf"), Decimal("NaN"), "1", 2**8193):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                replace(stock(), quantity_kg=value)
        with self.assertRaises(ValueError):
            replace(bundle(), diet_evidence=" ")
        with self.assertRaises(ValueError):
            fa.FoodBundle("bad", (fa.FoodComponent("g", F(2, 3), 100, E),), 10, E, S)
        with self.assertRaises(ValueError):
            replace(obligation("reserve", "one_off_reserve"), recurrence="per_year")

    def test_exact_json_preserves_fractions_and_tuple_supply_keys(self):
        r = accounts(stocks=[stock(quantity=F(301, 3))])
        safe = fa.exact_json(r)
        self.assertEqual(safe["stock_ledger"][0]["initial_kg"], {"numerator": 301, "denominator": 3})
        self.assertIn("available_edible_kg", json.dumps(safe, allow_nan=False))

    def test_actual_land_allocator_food_rows_create_only_physical_edible_stock(self):
        producer = actual_land_food()
        self.assertEqual(producer["status"], "OPTIMAL")
        imported = fa.stocks_from_food_budget(producer["food_budget"], [binding()], period(), source_id="actual model fixture", one_representative_harvest_in_period=True)
        self.assertEqual(imported["status"], "IMPORTED")
        self.assertEqual(imported["stocks"][0].quantity_kg, F(27, 2))
        self.assertEqual(imported["harvest_ledger"][0]["harvest_kg"], 20)
        self.assertEqual(imported["harvest_ledger"][0]["mass_residual_kg"], 0)
        r = accounts(stocks=list(imported["stocks"]))
        self.assertEqual(r["remaining_demands"][0]["quantity_kg"], F(45, 2))

    def test_population_in_actual_upstream_budget_cannot_change_stock(self):
        a, b = actual_land_food(population=0), actual_land_food(population=1000000)
        x = fa.stocks_from_food_budget(a["food_budget"], [binding()], period(), source_id="actual fixture", one_representative_harvest_in_period=True)
        y = fa.stocks_from_food_budget(b["food_budget"], [binding()], period(), source_id="actual fixture", one_representative_harvest_in_period=True)
        self.assertEqual(x["stocks"], y["stocks"])
        self.assertNotEqual(x["food_budget_sha256"], y["food_budget_sha256"])

    def test_actual_binary64_harvest_partition_never_rounds_supply_up(self):
        for y, edible, loss in ((.1, .3, .2), (.123456789, .71, .13), (2.3456, .3333, .5555)):
            producer = actual_land_food(y, edible, loss)
            r = fa.stocks_from_food_budget(producer["food_budget"], [binding()], period(), source_id="actual roundoff fixture", one_representative_harvest_in_period=True)
            row = r["harvest_ledger"][0]
            self.assertLessEqual(row["accepted_stock_kg"], row["reported_available_kg"])
            self.assertEqual(row["mass_residual_kg"], 0)
            self.assertGreaterEqual(row["unassigned_rounding_kg"], 0)

    def test_unknown_actual_food_option_blocks_import_not_zero(self):
        producer = actual_land_food(yield_kg=None)
        self.assertEqual(producer["status"], "UNKNOWN")
        # Actual retained food producer can return known and unknown rows; execute
        # that producer itself instead of constructing a golden food dictionary.
        path = Path(__file__).resolve().parents[1]/"generator_upgrade_r1"/"land_food.py"
        name = "_actual_unknown_food_"+uuid.uuid4().hex
        m = types.ModuleType(name); m.__file__ = str(path); sys.modules[name] = m
        try:
            exec(compile(path.read_bytes(), str(path), "exec"), m.__dict__)
            food = m._food_module()
            actual = food.food_budget([food.FoodParcel("option", 1, None, 1, 0, 100, 0, 0, E, "UNKNOWN")],
                                      available_land_m2=1, annual_energy_kcal_per_person=3600, fixed_population=1)
        finally:
            sys.modules.pop(name, None)
        imported = fa.stocks_from_food_budget(actual, [binding()], period(), source_id="actual unknown producer", one_representative_harvest_in_period=True)
        self.assertEqual(imported["status"], "UNKNOWN")
        self.assertIsNone(imported["stocks"])

    def test_harvest_mapping_composition_and_period_are_mandatory(self):
        budget = actual_land_food()["food_budget"]
        for mappings, p, declaration in (([], period(), True), ([binding()], period(F(1, 2)), True),
                                          ([binding()], period(), False), ([binding(edible_energy_kcal_kg=101)], period(), True)):
            with self.assertRaises(ValueError):
                fa.stocks_from_food_budget(budget, mappings, p, source_id="fixture", one_representative_harvest_in_period=declaration)

    def test_invalid_harvest_mass_cannot_hide_behind_upstream_receipt(self):
        budget = actual_land_food()["food_budget"]
        budget["rows"][0]["available_food_kg_year"] += 1
        with self.assertRaisesRegex(ValueError, "physically inconsistent"):
            fa.stocks_from_food_budget(budget, [binding()], period(), source_id="fixture", one_representative_harvest_in_period=True)

    def test_no_canon_promotion(self):
        r = accounts(stocks=[replace(stock(), source_status="CANON")])
        self.assertEqual(r["source_status"], "WORKING NON-CANON")
        self.assertFalse(r["physical_additionality_validated"])

    def test_harvest_source_status_preserved_without_promoting_computed_stock(self):
        budget = actual_land_food()["food_budget"]
        budget["rows"][0]["source_status"] = "CANON"
        imported = fa.stocks_from_food_budget(budget, [binding()], period(), source_id="status-boundary fixture", one_representative_harvest_in_period=True)
        self.assertEqual(imported["stocks"][0].source_status, "WORKING NON-CANON")
        self.assertEqual(imported["harvest_ledger"][0]["input_source_status"], "CANON")

    def test_unused_declared_unknown_bundle_is_not_silently_dropped(self):
        r = accounts(bundles=[bundle(), replace(bundle(identity="uncertain"), source_status="UNKNOWN")])
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIn("bundle:uncertain", r["unresolved"])

    def test_unknown_harvest_calendar_is_unresolved_not_zero(self):
        budget = actual_land_food()["food_budget"]
        r = fa.stocks_from_food_budget(budget, [binding()], replace(period(), duration_years=None), source_id="fixture", one_representative_harvest_in_period=True)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["stocks"])

    def test_one_evidence_document_may_support_all_three_harvest_roles(self):
        value = replace(stock(), production_evidence=(E, E, E))
        self.assertEqual(accounts(stocks=[value])["status"], "ACCOUNTED")

    def test_renamed_import_does_not_duplicate_same_actual_harvest_event(self):
        budget = actual_land_food()["food_budget"]
        first = fa.stocks_from_food_budget(budget, [binding()], period(), source_id="same actual producer", one_representative_harvest_in_period=True)
        second = fa.stocks_from_food_budget(budget, [binding(stock_id="renamed", source_use_id="renamed caller use")], period(), source_id="same actual producer", one_representative_harvest_in_period=True)
        with self.assertRaisesRegex(ValueError, "already imported"):
            accounts(stocks=[*first["stocks"], *second["stocks"]])


if __name__ == "__main__":
    unittest.main()
