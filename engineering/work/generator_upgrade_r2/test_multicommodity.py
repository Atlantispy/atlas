"""Independent small primal, weak-dual, analytical, cut and vertex oracles."""
from dataclasses import replace
from fractions import Fraction as F
from itertools import combinations
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from . import multicommodity as m

E = "EXPLICIT SYNTHETIC SCENARIO; NOT DIADEM INPUT"
P = m.Period("same-explicit-window", 100)
O = m.Objective(m.OBJECTIVE, "explicit-weighted-service-experiment", E)


def q(row): return F(row["exact"])
def node(n, mode="land"): return m.Node(n, mode, E)
def commodity(c): return m.Commodity(c, "available edible mass at stated moisture basis", "kg", E)
def stock(k, n, c, x): return m.Stock(k, n, c, x, P.period_id, E)
def demand(k, n, c, x, weight=1): return m.Demand(k, n, c, x, weight, P.period_id, E)
def group(g, cap): return m.CapacityGroup(g, cap, P.period_id, E)
def rule(c, g, loss=0, factor=1): return m.CommodityRule(c, True, loss, (m.CapacityUse(g, factor, E),), E)
def link(k, a, b, rules, **kw):
    return m.Link(k, a, b, kw.get("kind", "TRAVEL"), kw.get("time", 1), kw.get("available", True), tuple(rules), P.period_id, E)


def solve(ns, cs, ss, ds, ls, gs, **kw):
    return m.solve_multicommodity(ns, cs, ss, ds, ls, gs, period=kw.pop("period", P),
        objective=kw.pop("objective", O), network_complete=kw.pop("network_complete", True), evidence_id=E, **kw)


def single(supply=10, need=10, cap=10, loss=0):
    return ([node("A"), node("B")], [commodity("grain")], [stock("s", "A", "grain", supply)],
            [demand("d", "B", "grain", need)], [link("ab", "A", "B", [rule("grain", "g", loss)])], [group("g", cap)])


def exact_linear_solve(a, b):
    """Independent rational Gaussian elimination for tiny vertex enumeration."""
    n = len(b); rows = [[F(x) for x in row] + [F(y)] for row, y in zip(a, b)]
    for c in range(n):
        pivot = next((r for r in range(c, n) if rows[r][c]), None)
        if pivot is None: return None
        rows[c], rows[pivot] = rows[pivot], rows[c]
        divisor = rows[c][c]; rows[c] = [x/divisor for x in rows[c]]
        for r in range(n):
            if r != c:
                factor = rows[r][c]
                rows[r] = [x-factor*y for x, y in zip(rows[r], rows[c])]
    return tuple(row[-1] for row in rows)


def vertex_optimum(a, b, c):
    """Enumerate every bounded polytope vertex, not HiGHS or route enumeration."""
    n = len(c)
    a = [tuple(F(x) for x in r) for r in a] + [tuple(-int(i == j) for j in range(n)) for i in range(n)]
    b = [F(x) for x in b] + [F(0)]*n
    best = F(0)
    for indices in combinations(range(len(a)), n):
        x = exact_linear_solve([a[i] for i in indices], [b[i] for i in indices])
        if x is None: continue
        if all(sum(ai*xi for ai, xi in zip(row, x)) <= bound for row, bound in zip(a, b)):
            best = max(best, sum(ci*xi for ci, xi in zip(c, x)))
    return best


class MulticommodityTests(unittest.TestCase):
    def audit(self, r, args):
        """Reconstruct every reported account and dual inequality from INPUTS."""
        self.assertTrue(r["solved"], r)
        ns, cs, ss, ds, ls, gs = args
        sm = {s.stock_id:s for s in ss}; dm = {d.demand_id:d for d in ds}
        lm = {l.link_id:l for l in ls}; gm = {g.group_id:g for g in gs}
        used = {k:F(0) for k in sm}; delivered = {k:F(0) for k in dm}; loads = {k:F(0) for k in gm}
        ins = {(n.node_id,c.commodity_id):F(0) for n in ns for c in cs}; outs = dict(ins)
        flow = {(l.link_id,c.commodity_id):[F(0),F(0)] for l in ls for c in cs}
        prices = {row["constraint"]:q(row["price"]) for row in r["certificate"]["row_prices"]}
        upper = sum((q(row["capacity"])*q(row["price"]) for row in r["certificate"]["row_prices"]), F(0))
        achieved = F(0); cost = F(0)
        for route in r["routes"]:
            sk = route["stock_id"]; dk = route["demand_id"]; cid = route["commodity_id"]
            self.assertEqual(sm[sk].commodity_id, cid); self.assertEqual(dm[dk].commodity_id, cid)
            start = q(route["dispatched_kg"]); amount = start; survival = F(1)
            at = sm[sk].node_id; route_loads = {}; route_coefficients = {}
            seen = {at}; cost_per_kg = F(0)
            self.assertGreaterEqual(start, 0); self.assertLessEqual(start, q(route["dispatch_upper_kg"]))
            for lid in route["link_ids"]:
                l = lm[lid]; self.assertEqual(l.from_node, at); self.assertTrue(l.available)
                law = next(x for x in l.rules if x.commodity_id == cid)
                self.assertTrue(law.allowed)
                for use in law.capacity_uses:
                    v = amount*F(use.load_kg_per_kg_entering)
                    loads[use.group_id] += v
                    route_loads[use.group_id] = route_loads.get(use.group_id,F(0))+v
                    route_coefficients[use.group_id] = route_coefficients.get(use.group_id,F(0))+survival*F(use.load_kg_per_kg_entering)
                cost += amount*F(l.travel_time_s); cost_per_kg += survival*F(l.travel_time_s)
                outs[at,cid] += amount; flow[lid,cid][0] += amount
                amount *= 1-F(law.loss_fraction); survival *= 1-F(law.loss_fraction)
                at = l.to_node; self.assertNotIn(at, seen); seen.add(at)
                ins[at,cid] += amount; flow[lid,cid][1] += amount
            self.assertEqual(at,dm[dk].node_id); self.assertEqual(amount,q(route["delivered_kg"]))
            self.assertEqual(start-amount,q(route["lost_kg"])); self.assertEqual(survival,q(route["survival_fraction"]))
            self.assertEqual(start*cost_per_kg,q(route["cost_kg_s"]))
            expected_upper = min([F(sm[sk].available_kg),F(dm[dk].required_kg)/survival]+
                                 [F(gm[g].capacity_kg)/a for g,a in route_coefficients.items()])
            self.assertEqual(expected_upper,q(route["dispatch_upper_kg"]))
            self.assertEqual(route_loads,{g["group_id"]:q(g["load_kg"]) for g in route["capacity_loads"]})
            self.assertEqual(route_coefficients,{g["group_id"]:q(g["load_per_dispatched_kg"]) for g in route["capacity_loads"]})
            used[sk] += start; delivered[dk] += amount
            reward = survival*F(dm[dk].weight_per_kg); achieved += amount*F(dm[dk].weight_per_kg)
            dual_cover = prices["stock:"+sk]+survival*prices["demand:"+dk]+sum(a*prices["capacity:"+g] for g,a in route_coefficients.items())
            extra = q(route["dual_upper_price"])
            self.assertGreaterEqual(extra,0); self.assertGreaterEqual(dual_cover+extra,reward)
            upper += expected_upper*extra
        self.assertEqual(cost,q(r["transport_cost_kg_s"]))
        for s in r["stocks"]:
            self.assertEqual(used[s["stock_id"]],q(s["used_kg"]))
            self.assertEqual(q(s["used_kg"])+q(s["unused_kg"]),F(sm[s["stock_id"]].available_kg))
        for d in r["demands"]:
            self.assertEqual(delivered[d["demand_id"]],q(d["delivered_kg"]))
            self.assertEqual(q(d["delivered_kg"])+q(d["shortage_kg"]),F(dm[d["demand_id"]].required_kg))
        for row in r["flows"]:
            a,b = flow[row["link_id"],row["commodity_id"]]
            self.assertEqual((a,b,a-b),(q(row["entered_kg"]),q(row["exited_kg"]),q(row["lost_kg"])))
        for n in ns:
            for c in cs:
                local_use = sum(used[s.stock_id] for s in ss if s.node_id==n.node_id and s.commodity_id==c.commodity_id)
                local_delivery = sum(delivered[d.demand_id] for d in ds if d.node_id==n.node_id and d.commodity_id==c.commodity_id)
                self.assertEqual(local_use+ins[n.node_id,c.commodity_id],local_delivery+outs[n.node_id,c.commodity_id])
        for g in r["capacity_groups"]:
            self.assertEqual(loads[g["group_id"]],q(g["used_kg"]))
            self.assertLessEqual(q(g["used_kg"]),F(gm[g["group_id"]].capacity_kg))
            self.assertEqual(q(g["used_kg"])+q(g["unused_kg"]),F(gm[g["group_id"]].capacity_kg))
        for row in r["commodity_totals"]:
            self.assertEqual(q(row["stock_kg"]),q(row["delivered_kg"])+q(row["loss_kg"])+q(row["unused_stock_kg"]))
        cert = r["certificate"]
        self.assertEqual(achieved,q(cert["objective_achieved"])); self.assertEqual(upper,q(cert["objective_upper_bound"]))
        self.assertGreaterEqual(upper,achieved)
        self.assertLessEqual(upper-achieved,q(cert["relative_gap_tolerance"])*upper)
        json.dumps(r,allow_nan=False)

    def checked(self,args,**kw):
        r=solve(*args,**kw); self.audit(r,args); return r

    def test_single_loss_analytic_and_exact_stock(self):
        r=self.checked(single(10,10,10,F(1,5)))
        self.assertEqual(q(r["commodity_totals"][0]["delivered_kg"]),8)
        self.assertEqual(q(r["commodity_totals"][0]["loss_kg"]),2)

    def test_two_leg_loss_and_downstream_capacity(self):
        args=list(single(100,100,100)); args[0].append(node("C"))
        args[3]=[demand("d","C","grain",100)]
        args[4]=[link("ab","A","B",[rule("grain","g",F(1,5))]),link("bc","B","C",[rule("grain","h",F(1,4))])]
        args[5].append(group("h",40))
        r=self.checked(args)
        self.assertEqual(q(r["stocks"][0]["used_kg"]),50)
        self.assertEqual(q(r["commodity_totals"][0]["delivered_kg"]),30)
        self.assertEqual(q(r["commodity_totals"][0]["loss_kg"]),20)

    def test_same_terminal_repeated_use_is_added_not_overwritten(self):
        args=list(single(10,10,9)); args[0].append(node("C")); args[3]=[demand("d","C","grain",10)]
        args[4]=[link("ab","A","B",[rule("grain","g",F(1,2))]),link("bc","B","C",[rule("grain","g")])]
        r=self.checked(args)
        self.assertEqual(q(r["stocks"][0]["used_kg"]),6)
        self.assertEqual(q(r["capacity_groups"][0]["used_kg"]),9)

    def test_two_commodities_share_one_capacity(self):
        ns=[node("A"),node("B")]; cs=[commodity("a"),commodity("b")]
        ss=[stock(c,"A",c,8) for c in ("a","b")]; ds=[demand(c,"B",c,8,2 if c=="a" else 1) for c in ("a","b")]
        args=(ns,cs,ss,ds,[link("ab","A","B",[rule(c,"g") for c in ("a","b")])],[group("g",10)])
        r=self.checked(args)
        self.assertEqual(q(r["demands"][0]["delivered_kg"]),8)
        self.assertLessEqual(abs(q(r["demands"][1]["delivered_kg"])-2),F(1,10**12))

    def test_bidirectional_bottleneck_shared_not_reused(self):
        args=([node("A"),node("B")],[commodity("a"),commodity("b")],
              [stock("a","A","a",4),stock("b","B","b",4)],
              [demand("a","B","a",4,2),demand("b","A","b",4)],
              [link("ab","A","B",[rule(c,"g") for c in ("a","b")]),link("ba","B","A",[rule(c,"g") for c in ("a","b")])],
              [group("g",5)])
        r=self.checked(args)
        self.assertEqual(q(r["demands"][0]["delivered_kg"]),4)
        self.assertLessEqual(abs(q(r["demands"][1]["delivered_kg"])-1),F(1,10**12))

    def test_explicit_load_factor_controls_shared_mass_basis(self):
        args=list(single(10,10,6)); args[4]=[link("ab","A","B",[rule("grain","g",factor=2)])]
        r=self.checked(args); self.assertEqual(q(r["stocks"][0]["used_kg"]),3)

    def test_shared_terminal_and_individual_link_constraints(self):
        args=list(single(10,10,10)); args[5].append(group("terminal",4))
        law=m.CommodityRule("grain",True,0,(m.CapacityUse("g",1,E),m.CapacityUse("terminal",1,E)),E)
        args[4]=[link("ab","A","B",[law])]
        r=self.checked(args); self.assertEqual(q(r["stocks"][0]["used_kg"]),4)

    def test_divisible_triangle_has_half_integral_optimum(self):
        ns=[]; ss=[]; ds=[]; ls=[]; cs=[commodity(c) for c in "xyz"]
        for c, groups in zip("xyz",[("a","c"),("a","b"),("b","c")]):
            ns += [node(c+str(i)) for i in range(3)]; ss.append(stock(c,c+"0",c,1)); ds.append(demand(c,c+"2",c,1))
            for i,g in enumerate(groups):
                laws=[rule(co,g) if co==c else m.CommodityRule(co,False,None,(),E) for co in "xyz"]
                ls.append(link(c+str(i),c+str(i),c+str(i+1),laws))
        args=(ns,cs,ss,ds,ls,[group(g,1) for g in "abc"])
        r=self.checked(args)
        brute=vertex_optimum([(1,1,0),(0,1,1),(1,0,1)], [1,1,1], [1,1,1])
        self.assertEqual(brute,F(3,2)); self.assertEqual(q(r["certificate"]["objective_achieved"]),brute)
        self.assertEqual([q(d["delivered_kg"]) for d in r["demands"]],[F(1,2)]*3)

    def test_twenty_four_independent_exact_vertex_objectives(self):
        for cap in range(1,5):
            for loss in (F(0),F(1,4),F(1,2)):
                for weight in (1,3):
                    with self.subTest(cap=cap,loss=loss,weight=weight):
                        args=([node("A"),node("B")],[commodity("a"),commodity("b")],
                            [stock("a","A","a",3),stock("b","A","b",2)],
                            [demand("a","B","a",3,weight),demand("b","B","b",2)],
                            [link("ab","A","B",[rule("a","g",loss),rule("b","g",factor=2)])],[group("g",cap)])
                        r=self.checked(args)
                        optimum=vertex_optimum([(1,2),(1,0),(0,1)], [cap,3,2], [(1-loss)*weight,1])
                        achieved=q(r["certificate"]["objective_achieved"])
                        self.assertLessEqual(abs(achieved-optimum),F(1,10**8)*max(1,optimum))

    def test_coupled_assignment_not_greedy(self):
        ns=[node(n) for n in "ABXY"]
        args=(ns,[commodity("c")],[stock("a","A","c",1),stock("b","B","c",1)],
              [demand("x","X","c",1),demand("y","Y","c",1)],
              [link(k,a,b,[rule("c",k)]) for k,a,b in [("ax","A","X"),("ay","A","Y"),("bx","B","X")]],
              [group(k,1) for k in ("ax","ay","bx")])
        r=self.checked(args); self.assertEqual(q(r["certificate"]["objective_achieved"]),2)

    def test_lossless_cut_upper_bound(self):
        args=list(single(100,100,7)); args[0].append(node("C")); args[3]=[demand("d","C","grain",100)]
        args[4].append(link("bc","B","C",[rule("grain","h")]))
        args[5].append(group("h",9))
        r=self.checked(args); self.assertEqual(q(r["certificate"]["objective_upper_bound"]),7)

    def test_local_stock_no_transport_and_unused_remainder(self):
        args=([node("A")],[commodity("c")],[stock("s","A","c",10)],[demand("d","A","c",4)],[],[])
        r=self.checked(args)
        self.assertEqual(r["routes"][0]["link_ids"],[]); self.assertEqual(q(r["stocks"][0]["unused_kg"]),6)

    def test_zero_stock_is_known_shortage(self):
        r=self.checked(single(supply=0)); self.assertEqual(r["demands"][0]["status"],"SHORTAGE")

    def test_no_path_is_not_missing_evidence(self):
        args=list(single()); args[4]=[]
        r=self.checked(args); self.assertEqual(r["demands"][0]["status"],"NO_PATH_FROM_KNOWN_STOCK")

    def test_zero_capacity_path_is_shortage_not_no_path(self):
        r=self.checked(single(cap=0)); self.assertEqual(r["demands"][0]["status"],"SHORTAGE")

    def test_complete_loss_path_is_shortage_not_no_path(self):
        r=self.checked(single(loss=1)); self.assertEqual(r["demands"][0]["status"],"SHORTAGE")

    def test_closed_link_blocks_passage(self):
        args=list(single()); args[4]=[replace(args[4][0],available=False)]
        r=self.checked(args); self.assertEqual(r["demands"][0]["status"],"NO_PATH_FROM_KNOWN_STOCK")

    def test_known_incompatible_commodity_blocks_passage(self):
        args=list(single()); args[4]=[link("ab","A","B",[m.CommodityRule("grain",False,None,(),E)])]
        r=self.checked(args); self.assertEqual(r["demands"][0]["status"],"NO_PATH_FROM_KNOWN_STOCK")

    def test_missing_inputs_never_become_zero(self):
        variants=[]
        for field in ("available_kg",):
            a=list(single()); a[2]=[replace(a[2][0],**{field:None})]; variants.append(a)
        a=list(single()); a[3]=[replace(a[3][0],required_kg=None)]; variants.append(a)
        a=list(single()); a[5]=[group("g",None)]; variants.append(a)
        a=list(single()); a[4]=[replace(a[4][0],available=None)]; variants.append(a)
        a=list(single()); a[4]=[link("ab","A","B",[rule("grain","g",None)])]; variants.append(a)
        a=list(single()); a[4]=[link("ab","A","B",[])]; variants.append(a)
        a=list(single()); a[4]=[link("ab","A","B",[replace(rule("grain","g"),capacity_uses=())])]; variants.append(a)
        for args in variants:
            with self.subTest(args=args):
                r=solve(*args); self.assertFalse(r["solved"]); self.assertEqual(r["status"],"MISSING_EVIDENCE"); self.assertIsNone(r["flows"])

    def test_incomplete_network_unknown(self):
        self.assertEqual(solve(*single(),network_complete=False)["status"],"MISSING_EVIDENCE")

    def test_period_mismatch_on_every_periodic_record(self):
        for index in (2,3,4,5):
            args=list(single()); args[index]=[replace(args[index][0],period_id="other-window")]
            with self.subTest(index=index),self.assertRaises(m.TransportError):solve(*args)

    def test_no_person_or_energy_unit_can_enter_mass_solver(self):
        for unit in ("person-years","kcal","tonnes",None):
            args=list(single()); args[1]=[replace(args[1][0],unit=unit)]
            with self.subTest(unit=unit),self.assertRaises(m.TransportError):solve(*args)

    def test_nonfinite_negative_bool_and_overflow_input_rejected(self):
        for bad in (True,-1,float("nan"),float("inf"),2**300):
            with self.subTest(bad=bad),self.assertRaises(m.TransportError):solve(*single(supply=bad))
        for bad in (-F(1,10),F(11,10)):
            with self.assertRaises(m.TransportError):solve(*single(loss=bad))

    def test_duplicate_ids_and_rules_rejected(self):
        args=list(single()); args[0]=args[0]+[args[0][0]]
        with self.assertRaises(m.TransportError):solve(*args)
        args=list(single()); args[4]=[link("ab","A","B",[rule("grain","g"),rule("grain","g")])]
        with self.assertRaises(m.TransportError):solve(*args)

    def test_explicit_transfer_required_for_mode_change(self):
        args=list(single()); args[0]=[node("A","land"),node("B","water")]
        with self.assertRaises(m.TransportError):solve(*args)
        args[4]=[replace(args[4][0],kind="TRANSFER")]
        self.checked(args)

    def test_no_implicit_objective_or_zero_priority(self):
        with self.assertRaises(m.TransportError):solve(*single(),objective=m.Objective("FAIR",E,E))
        args=list(single()); args[3]=[replace(args[3][0],weight_per_kg=0)]
        with self.assertRaises(m.TransportError):solve(*args)

    def test_rational_supply_loss_and_load_no_accounting_roundoff(self):
        r=self.checked(single(F(1,3),1,F(1,3),F(1,7)))
        self.assertEqual(q(r["commodity_totals"][0]["delivered_kg"]),F(2,7))
        self.assertEqual(q(r["commodity_totals"][0]["loss_kg"]),F(1,21))

    def test_node_route_and_search_envelopes_fail_closed(self):
        with patch.object(m,"MAX_NODES",1),self.assertRaises(m.TransportError):solve(*single())
        with patch.object(m,"MAX_ROUTES",0),self.assertRaises(m.TransportError):solve(*single())
        with patch.object(m,"MAX_PATH_STEPS",0),self.assertRaises(m.TransportError):solve(*single())

    def test_tiny_objective_dynamic_range_rejected_not_silently_dropped(self):
        args=list(single()); args[3].append(demand("tiny","B","grain",1,F(1,10**13)))
        with self.assertRaises(m.TransportError):solve(*args)

    def test_solver_failure_is_not_a_zero_supply_result(self):
        fake=SimpleNamespace(success=False,status=1,message="budget exhausted")
        with patch.object(m,"linprog",return_value=fake):r=solve(*single())
        self.assertFalse(r["solved"]); self.assertEqual(r["status"],"NUMERICAL_FAILURE")

    def test_bad_feasible_solution_rejected_by_independent_dual_gap(self):
        original=m.linprog
        def bad(*a,**kw):
            r=original(*a,**kw); r.x[:]=0; return r
        with patch.object(m,"linprog",side_effect=bad):r=solve(*single())
        self.assertFalse(r["solved"]); self.assertEqual(r["status"],"NUMERICAL_FAILURE")

    def test_exact_monotone_repair_of_small_solver_capacity_overshoot(self):
        args=list(single()); args[3]=[demand("a","B","grain",10),demand("b","B","grain",10)]
        original=m.linprog
        def perturbed(*a,**kw):
            r=original(*a,**kw); r.x[:]=[0.5+1e-10,0.5+1e-10]; return r
        with patch.object(m,"linprog",side_effect=perturbed):r=self.checked(args)
        self.assertLess(q(r["certificate"]["minimum_single_repair_factor"]),1)
        self.assertEqual(q(r["capacity_groups"][0]["used_kg"]),10)

    def test_canonical_input_order_does_not_change_solution(self):
        args=single(); a=self.checked(args)
        b=self.checked([list(reversed(rows)) for rows in args])
        self.assertEqual(a,b)


if __name__ == "__main__":
    unittest.main()
