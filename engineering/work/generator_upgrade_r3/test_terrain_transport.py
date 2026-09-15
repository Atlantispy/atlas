"""Actual pinned finite-layer and independent routed mass/geometry oracles."""
from dataclasses import replace
from fractions import Fraction as F
import json
import math
import unittest
from unittest.mock import patch

from . import terrain_transport as t

E = "EXPLICIT SYNTHETIC OPEN-DRAINAGE SCENARIO; NOT DIADEM PARAMETERS"
S = "SYNTHETIC TEST"


def prop(name, value, unit): return t.PhysicalProperty(name, value, unit, E, S)
def layer(material="rock", mass=100, density=10, porosity=0, phase="bedrock", evidence=E):
    return t.Layer(material, mass, density, porosity, phase, evidence)
def column(layers=None, area=1, base=0):
    return t.Column(area, base, tuple([layer()] if layers is None else layers), S)
def law(material="rock", phase="bedrock", k=.1):
    return t.ErosionLaw(material, phase, prop("erosion_coefficient_at_reference_runoff",k,"1/year"),prop("reference_runoff",1,"m/year"))
def laws(material="rock", k=.1): return (law(material,"bedrock",k),law(material,"mobile_sediment",k))
def sed(material="rock", settle=0, porosity=0, order=0): return t.SedimentLaw(material,settle,porosity,order,E)
def edge(k, source, receiver, length=1, level=None): return t.Connector(k,source,receiver,length,level,E)
def controls(fraction=F(1,4), ratio=F(1,5)): return t.TrialControls(fraction,ratio,E)
def one(*, mass=100, density=10, k=.1, settling=0, porosity=0):
    state=t.LandscapeState((("a",column([layer(mass=mass,density=density)])),))
    return (state,{"a":4},(edge("out","a",None,10,0),),laws(k=k),(sed(settle=settling,porosity=porosity),))
def trial(args,duration=1,**kwargs):
    return t.terrain_trial(*args,duration_years=duration,controls=kwargs.pop("controls",controls()),evidence_id=E,**kwargs)


class TerrainTests(unittest.TestCase):
    def audit(self,result,before):
        """Independently reconstruct geometry and every source/deposit/export split."""
        initial=before.column_map; final=result.state.column_map; stripped=result.erosion_state.column_map
        by_origin={(r["source_cell"],r["source_layer_index"]):r for r in result.erosion_events}
        withdrawals={k:F(0) for k in initial}; land_in={k:F(0) for k in initial}
        for key,row in by_origin.items():
            original=initial[key[0]].layers[key[1]]
            self.assertEqual(original.mass_kg,row["source_initial_mass_kg"])
            self.assertEqual(original.mass_kg,row["eroded_mass_kg"]+row["remaining_mass_kg"])
            self.assertEqual(original.material_id,row["source_layer"]["material_id"])
            self.assertGreater(row["eroded_mass_kg"],0)
            withdrawals[key[0]] += row["eroded_mass_kg"]
            total=F(0)
            for deposit in result.deposit_events:
                for source in deposit["sources"]:
                    if (source["source_cell"],source["source_layer_index"])==key:
                        total+=source["mass_kg"]
                        self.assertEqual(source["fraction_of_eroded_mass"],source["mass_kg"]/row["eroded_mass_kg"])
            for exported in result.exports:
                if (exported["source_cell"],exported["source_layer_index"])==key:
                    total+=exported["mass_kg"]
                    self.assertEqual(exported["solid_volume_m3"],exported["mass_kg"]/original.grain_density_kg_m3)
            self.assertEqual(total,row["eroded_mass_kg"])
        accumulated={k:list(c.layers) for k,c in stripped.items()}
        for row in result.deposit_events:
            k=row["destination_cell"]; deposited=row["layer"]
            self.assertEqual(row["destination_layer_index"],len(accumulated[k]))
            self.assertEqual(sum((s["mass_kg"] for s in row["sources"]),F(0)),deposited.mass_kg)
            self.assertEqual(deposited.phase,"mobile_sediment")
            for source in row["sources"]:
                original=initial[source["source_cell"]].layers[source["source_layer_index"]]
                self.assertEqual(original.material_id,deposited.material_id)
                self.assertEqual(original.grain_density_kg_m3,deposited.grain_density_kg_m3)
            accumulated[k].append(deposited);land_in[k]+=deposited.mass_kg
        for k,c in final.items():
            self.assertEqual(tuple(accumulated[k]),c.layers)
            self.assertEqual(initial[k].mass_kg-withdrawals[k],stripped[k].mass_kg)
            self.assertEqual(initial[k].mass_kg-withdrawals[k]+land_in[k],c.mass_kg)
            expected=F(c.basal_elevation_m)+sum((l.mass_kg/l.grain_density_kg_m3/(1-l.porosity) for l in c.layers),F(0))/c.area_m2
            self.assertEqual(c.surface_m,expected)
        initial_mass=sum((c.mass_kg for c in initial.values()),F(0))
        final_mass=sum((c.mass_kg for c in final.values()),F(0))
        self.assertEqual(initial_mass,final_mass+sum((r["mass_kg"] for r in result.exports),F(0)))
        water=result.receipt
        self.assertEqual(sum(water["local_runoff_m3"].values(),F(0)),sum(water["water_exports_m3"].values(),F(0)))
        for row in water["sediment_transfers"]:
            self.assertEqual(row["incoming_kg"],row["deposited_kg"]+row["outgoing_kg"])
            self.assertEqual(row["transport_fraction"]-row["exact_theoretical_transport_fraction"],
                             row["transport_fraction_representation_error"])
        for row in water["material_balances"]:
            self.assertEqual(row["mass_residual_kg"],0);self.assertEqual(row["solid_residual_m3"],0)
        json.dumps(t.exact_json(water),allow_nan=False)

    def checked(self,args,**kw):
        r=trial(args,**kw);self.audit(r,args[0]);return r

    def test_actual_R1_called_and_exact_analytical_erosion(self):
        args=one(k=F(1,10))
        with patch.object(t.landscape,"advance",wraps=t.landscape.advance) as called:
            r=self.checked(args)
        self.assertEqual(called.call_count,1)
        self.assertEqual(r.state.column_map["a"].mass_kg,98)
        self.assertEqual(r.state.column_map["a"].surface_m,F(49,5))
        self.assertEqual(sum(x["mass_kg"] for x in r.exports),2)

    def test_sequential_source_and_receiver_deposition_analytic(self):
        state=t.LandscapeState((("a",column([layer("rock",10)],base=10)),("b",column([layer("floor",10)]))))
        args=(state,{"a":F(2,5),"b":0},(edge("ab","a","b"),edge("out","b",None,1,0)),
              (*laws("rock",F(1,100)),*laws("floor",0)),(sed("rock",4,0,0),sed("floor",4,0,1)))
        r=self.checked(args,duration=F(1,10))
        self.assertEqual(r.erosion_events[0]["eroded_mass_kg"],F(1,5))
        self.assertEqual([d["mass_kg"] for d in r.deposit_events],[F(1,10),F(1,20)])
        self.assertEqual(sum(x["mass_kg"] for x in r.exports),F(1,20))
        self.assertEqual(r.state.column_map["a"].surface_m,F(1099,100))
        self.assertEqual(r.state.column_map["b"].surface_m,F(201,200))

    def test_current_surface_routes_and_runoff_accumulation(self):
        state=t.LandscapeState(tuple((k,column([layer(mass=10)],base=z)) for k,z in [("a",3),("b",2),("c",0)]))
        edges=(edge("ab","a","b"),edge("ac","a","c",10),edge("bc","b","c"),edge("out","c",None,1,0))
        flow=t.route_water(state,{"a":1,"b":2,"c":3},edges,duration_years=2)
        self.assertEqual(flow["receivers"],{"a":"b","b":"c","c":None})
        self.assertEqual(flow["discharge_m3_year"],{"a":F(1,2),"b":F(3,2),"c":3})
        self.assertEqual(flow["external_exports_m3"],{"out":6})

    def test_routing_recomputed_from_changed_geometry(self):
        cols={k:column([layer(mass=10)],base=z) for k,z in [("a",3),("b",2),("c",0)]}
        edges=(edge("ab","a","b"),edge("ac","a","c",2),edge("bout","b",None,1,-1),edge("cout","c",None,1,-1))
        state=t.LandscapeState(tuple(cols.items()))
        first=t.route_water(state,{k:1 for k in cols},edges,duration_years=1)
        cols["b"]=replace(cols["b"],basal_elevation_m=0)
        second=t.route_water(t.LandscapeState(tuple(cols.items())),{k:1 for k in cols},edges,duration_years=1)
        self.assertEqual(first["receivers"]["a"],"c");self.assertEqual(second["receivers"]["a"],"b")

    def test_distinct_finite_layer_contact_uses_new_erosion_law(self):
        c=column([layer("hard",1),layer("soft",F(1,20))],base=15)
        state=t.LandscapeState((("a",c),))
        args=(state,{"a":F(2,5)},(edge("out","a",None,c.surface_m,0),),
              (*laws("hard",F(1,10)),*laws("soft",F(1,2))), (sed("hard",order=0),sed("soft",order=1)))
        r=self.checked(args,duration=F(1,10))
        self.assertEqual([x["source_layer_index"] for x in r.erosion_events],[1,0])
        self.assertEqual([x["eroded_mass_kg"] for x in r.erosion_events],[F(1,20),F(19,100)])
        self.assertEqual(r.state.column_map["a"].layers[0].mass_kg,F(81,100))

    def test_bedrock_to_mobile_deposit_preserves_density_not_bulk_volume(self):
        r=self.checked(one(k=F(1,10),settling=4,porosity=F(1,2)))
        self.assertEqual(r.deposit_events[0]["layer"].mass_kg,1)
        self.assertEqual(r.deposit_events[0]["layer"].bulk_volume_m3,F(1,5))
        self.assertEqual(r.state.column_map["a"].surface_m,10)
        self.assertEqual(r.state.column_map["a"].mass_kg,99)

    def test_repeated_same_material_layers_retain_source_indices(self):
        c=column([layer("rock",1,10,0,evidence="lower"),layer("rock",F(1,20),10,F(1,2),evidence="upper")],base=20)
        args=(t.LandscapeState((("a",c),)),{"a":F(2,5)},(edge("out","a",None,c.surface_m,0),),laws(k=1),(sed(),))
        r=self.checked(args,duration=F(1,10),controls=controls(ratio=F(9,10)))
        self.assertEqual([x["source_layer_index"] for x in r.erosion_events],[1,0])
        self.assertEqual([x["source_layer"]["evidence"] for x in r.erosion_events],["upper","lower"])

    def test_explicit_deposition_order_not_material_name_order(self):
        state=t.LandscapeState((("a",column([layer("zeta",10)],base=5)),("b",column([layer("alpha",10)],base=4)),("c",column([layer("floor",10)]))))
        args=(state,{"a":F(2,5),"b":F(2,5),"c":0},(edge("ac","a","c"),edge("bc","b","c"),edge("out","c",None,1,0)),
              (*laws("zeta",F(1,100)),*laws("alpha",F(1,100)),*laws("floor",0)),
              (sed("alpha",4,0,2),sed("zeta",4,0,1),sed("floor",4,0,0)))
        r=self.checked(args,duration=F(1,10))
        self.assertEqual([d["material_id"] for d in r.deposit_events if d["destination_cell"]=="c"],["zeta","alpha"])

    def test_same_material_merge_retains_each_origin_contribution(self):
        state=t.LandscapeState((("a",column([layer(mass=10)],base=5)),("b",column([layer(mass=10)],base=4)),("c",column([layer("floor",10)]))))
        args=(state,{"a":F(2,5),"b":F(2,5),"c":0},(edge("ac","a","c"),edge("bc","b","c"),edge("out","c",None,1,0)),
              (*laws(k=F(1,100)),*laws("floor",0)),(sed(settle=4),sed("floor",4,0,1)))
        r=self.checked(args,duration=F(1,10))
        event=next(d for d in r.deposit_events if d["destination_cell"]=="c")
        self.assertEqual({s["source_cell"] for s in event["sources"]},{"a","b"})

    def test_water_and_solid_exports_split_between_declared_outlets(self):
        state=t.LandscapeState((("a",column()),("b",column())))
        args=(state,{"a":4,"b":9},(edge("aout","a",None,10,0),edge("bout","b",None,10,0)),laws(k=F(1,10)),(sed(),))
        r=self.checked(args)
        self.assertEqual(r.receipt["water_exports_m3"],{"aout":4,"bout":9})
        self.assertEqual({x["outlet_connector"] for x in r.exports},{"aout","bout"})

    def test_no_runoff_means_no_erosion_even_on_steep_slope(self):
        args=list(one());args[1]={"a":0}
        r=self.checked(args);self.assertEqual(r.state.column_map["a"].layers,args[0].column_map["a"].layers)

    def test_zero_erosion_law_means_conservative_water_only(self):
        r=self.checked(one(k=0,settling=4));self.assertFalse(r.erosion_events);self.assertFalse(r.deposit_events)

    def test_finite_exhaustion_does_not_invent_bedrock(self):
        c=column([layer(mass=F(1,100))],base=100)
        args=(t.LandscapeState((("a",c),)),{"a":4},(edge("out","a",None,100,0),),laws(k=1),(sed(),))
        r=self.checked(args);self.assertEqual(r.state.column_map["a"].layers,())

    def test_dry_closed_cell_preserved_but_wet_closed_pit_rejected(self):
        state=t.LandscapeState((("a",column()),))
        self.assertEqual(t.route_water(state,{"a":0},(),duration_years=1)["external_exports_m3"],{})
        with self.assertRaises(t.TerrainRegimeError):t.route_water(state,{"a":1},(),duration_years=1)

    def test_upstream_flow_into_closed_pit_is_not_lost(self):
        state=t.LandscapeState((("a",column(base=1)),("b",column())))
        with self.assertRaises(t.TerrainRegimeError):
            t.route_water(state,{"a":1,"b":0},(edge("ab","a","b"),),duration_years=1)

    def test_oversized_trial_rejected_without_mutating_original(self):
        args=one(k=1);before=args[0].as_dict()
        with self.assertRaises(t.TerrainStepTooLarge):trial(args,controls=controls(F(1,100),F(9,10)))
        self.assertEqual(args[0].as_dict(),before)

    def test_dilute_transport_regime_is_enforced_not_clipped(self):
        with self.assertRaises(t.TerrainRegimeError):trial(one(k=1),controls=controls(F(1,2),F(1,100)))

    def test_geometry_refinement_restores_trial_admissibility(self):
        args=one(k=1)
        with self.assertRaises(t.TerrainStepTooLarge):trial(args,controls=controls(F(1,100),F(9,10)))
        small=list(args);small[1]={"a":F(1,10)}
        self.checked(small,duration=F(1,40),controls=controls(F(1,100),F(9,10)))

    def test_step_halving_converges_to_independent_exponential_surface(self):
        # dM/dt=-K*sqrt(Q)/L*M; no settling, fixed outlet, fixed Q=4.
        errors=[]
        for count in (4,8,16,32):
            args=list(one(k=F(1,10))); dt=F(1,count)
            args[1]={"a":4*dt}
            for _ in range(count):args[0]=self.checked(args,duration=dt).state
            errors.append(abs(float(args[0].column_map["a"].mass_kg)-100*math.exp(-.02)))
        self.assertTrue(all(a>b>0 for a,b in zip(errors,errors[1:])))
        self.assertTrue(all(1.9<a/b<2.1 for a,b in zip(errors,errors[1:])))

    def test_constant_discharge_refinement_preserves_total_water_forcing(self):
        args=list(one());dt=F(1,8);args[1]={"a":4*dt};total=F(0)
        for _ in range(8):
            r=self.checked(args,duration=dt);args[0]=r.state;total+=sum(r.receipt["water_exports_m3"].values(),F(0))
        self.assertEqual(total,4)

    def test_updated_state_persists_and_continues_identically(self):
        args=list(one(settling=4,porosity=F(1,2)))
        first=self.checked(args);serialized=json.dumps(first.state.as_dict(),allow_nan=False)
        restored=t.LandscapeState.from_json(serialized)
        a=list(args);a[0]=first.state;b=list(args);b[0]=restored
        self.assertEqual(trial(a).state,trial(b).state)

    def test_missing_physical_forcing_not_zero(self):
        args=list(one());args[1]={"a":None}
        with self.assertRaises(t.TerrainContractError):trial(args)

    def test_missing_mobile_or_settling_law_rejected_before_change(self):
        args=list(one());args[3]=(law(),)
        with self.assertRaises(t.TerrainContractError):trial(args)
        args=list(one());args[4]=()
        with self.assertRaises(t.TerrainContractError):trial(args)

    def test_unused_laws_remain_valid_after_material_exhaustion(self):
        args=list(one());args[4]=(*args[4],sed("old",order=1))
        self.checked(args)

    def test_invalid_connector_and_ambiguous_deposit_order(self):
        for action in (lambda:edge("x","a","a"),lambda:edge("x","a",None,1,None),
                       lambda:edge("x","a","b",0),lambda:edge("x","a","b",1,0)):
            with self.assertRaises(t.TerrainContractError):action()
        args=list(one());args[4]=(*args[4],sed("other",order=0))
        with self.assertRaises(t.TerrainContractError):trial(args)

    def test_nonfinite_bool_negative_inputs_and_bad_duration(self):
        for bad in (True,float("nan"),float("inf"),-1):
            args=list(one());args[1]={"a":bad}
            with self.assertRaises(t.TerrainContractError):trial(args)
        for bad in (0,True,None):
            with self.assertRaises(t.TerrainContractError):trial(one(),duration=bad)

    def test_bound_native_inventory_and_duplicate_connector_rejected(self):
        args=list(one());args[2]=args[2]*2
        with self.assertRaises(t.TerrainContractError):trial(args)
        with patch.object(t,"MAX_CELLS",0),self.assertRaises(t.TerrainContractError):trial(one())

    def test_pore_water_not_invented_in_sediment_records(self):
        r=self.checked(one(settling=4))
        self.assertTrue(all("UNASSIGNED" in e["pore_water_assignment"] for e in r.deposit_events))
        self.assertIn("not included",r.receipt["pore_water"])

    def test_nondyadic_constitutive_factor_is_disclosed_not_mass_writeoff(self):
        r=self.checked(one(settling=8))
        row=r.receipt["sediment_transfers"][0]
        self.assertEqual(row["exact_theoretical_transport_fraction"],F(1,3))
        self.assertEqual(row["transport_fraction"],F(1/3))
        self.assertNotEqual(row["transport_fraction_representation_error"],0)
        self.assertLessEqual(abs(row["transport_fraction_representation_error"]),F(math.ulp(1/3))/2)
        self.assertEqual(row["outgoing_kg"],row["incoming_kg"]*F(1/3))

    def test_constitutive_rounding_rejects_lost_positive_branches(self):
        for q,va in ((F(1,2**1100),F(1)),(F(1),F(1,2**60))):
            with self.assertRaisesRegex(t.TerrainContractError,"positive transport/deposition branch"):
                t._settling_factor(q,va)
        self.assertEqual(t._settling_factor(F(1),F(0)),(F(1),F(1)))

    def test_repeated_nondyadic_settling_preserves_bounded_exact_geometry(self):
        args=list(one(k=F(1,10),settling=8));dt=F(1,32);args[1]={"a":4*dt}
        for _ in range(32):
            r=self.checked(args,duration=dt);args[0]=r.state
        self.assertLess(args[0].column_map["a"].surface_m.denominator.bit_length(),t.MAX_BITS)


if __name__=="__main__":unittest.main()
