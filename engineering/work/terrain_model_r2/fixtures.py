"""Explicit engineering scenarios, never inferred Diadem geology or defaults."""
from copy import deepcopy
import math

from core import Grid
import constructive


def base(rows=8,cols=8,spacing=100.,scenario="branched_upland"):
    g=Grid(rows,cols,spacing,spacing); n=g.size
    # Explicit tilted, asymmetric, along-strike structural scaffold. Its scale
    # and form are synthetic construction inputs, not fitted real topography.
    bed=[20.+.012*(rows-r)*spacing+2.*math.cos(2*math.pi*(c+.5)/cols)*math.sin(math.pi*(r+.5)/rows)
         for r in range(rows) for c in range(cols)]
    return {"schema":"diadem.terrain.bounded-reference.r2","purpose":"SYNTHETIC_ENGINEERING_ONLY",
      "scenario_id":scenario,"source_status":"WORKING NON-CANON SYNTHETIC",
      "grid":{"rows":rows,"cols":cols,"dx_m":spacing,"dy_m":spacing},
      "initial":{"bedrock_m":bed,"mobile_solid_m3":[.3*g.area_m2]*n,"porosity":[0.]*n,
                 "rock_density_kg_m3":2700.,"sediment_density_kg_m3":2700.},
      "operations":[{"kind":"coupled","steps":8,"dt_years":.1,"diffusivity_m2_year":[.003]*n,
        "runoff_m_year":[1. if i%cols<cols//2 else .5 for i in range(n)],
        "sediment_k_per_year":[.01]*n,"rock_k_per_year":[.005 if i%cols<cols//2 else .0025 for i in range(n)],
        "cover_scale_m":1.,"settling_m_year":5.,"external_outlets":list(range((rows-1)*cols,n))}],
      "constraints":[],"coverage":{**{f"L{i:02d}":{"status":"NOT_IN_THIS_SYNTHETIC_FIXTURE","reason":"No claim for this family in this selected fixture."} for i in range(1,12)},
          "additional":{"status":"UNSUPPORTED","reason":"Diadem-wide inventory/exceptional regimes not inferred from synthetic cases."}},
      "coupling":{"mode":"PRESCRIBED_SYNTHETIC_FORCING_SENSITIVITY_ONLY","reason":"Runoff, materials and structural scaffold are explicit test forcing. No real C1 climate reused.",
        "terrain_forcing_max_change_m":10.,"dependent_fields":["refinement","gradients","water","climate","soils","sites","resources","habitats","routes"]},
      "limits":{"max_cells":16384,"max_steps":4096,"max_product_bytes":64*1024*1024,"max_cell_steps":2097152,"wall_seconds":120},
      "parameter_evidence":[{"source":"https://gmd.copernicus.org/articles/10/4577/2017/","use":"Published mixed-regime parameters; spatial K/runoff contrast, dt and geometry are synthetic sensitivity choices."},
                             {"source":"https://seismo.berkeley.edu/~kirchner/reprints/1999_29_Roering_nonlinear.pdf","use":"K=.003 m2/year; scaffold is not a recovered natural landscape."}]}


def suite():
    upland=base()
    for family in ("L01","L02","L03","L10"):
        upland["coverage"][family]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Shared synthetic scaffold, soil flux and mixed-bed routing with lithology/runoff contrast; morphology validation incomplete."}
    deposition=deepcopy(upland);deposition["scenario_id"]="upland_to_submerged_receiver"
    deposition["operations"].append({"kind":"submerged_deposition","source":"preceding_channel_export","cells":[63],
        "parameters":[{"fraction":1.,"settling_m_per_year":5.,"receiving_stage_m":100.,"interval_years":.8}]})
    for f in ("L08","L11"):deposition["coverage"][f]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Conservative source-to-receiver sediment deposition only; waves/tides/levees/mass failure unimplemented."}
    soil=base(4,4,10.,"weathering_to_soil_to_channels")
    soil["operations"].insert(0,{"kind":"soil","parameters":{"bare_rate_m_per_year":.000075,"cover_scale_m":.5,
        "rock_grain_density_kg_m3":2700.,"rock_porosity":0.,"regolith_grain_density_kg_m3":2700.,"regolith_porosity":0.,
        "mobile_grain_density_kg_m3":2700.,"mobile_porosity":0.,"dissolved_rock_fraction":.1,"mobile_fraction_of_retained_solids":1.,
        "evidence_id":"SYNTHETIC explicit yield and production scenario; exponential law literature, not Diadem calibration"},
        "rock_available_kg":[1e9]*16,"regolith_kg":[0.]*16,"duration_years":1.})
    # Isolate this material-interface test on explicit externally draining
    # ground. The earlier basin-capture scaffold is retained separately below
    # as a required rejection regression, not silently repaired or passed.
    soil["initial"]["bedrock_m"]=[20.+.2*(3-i//4)+.01*(3-i%4) for i in range(16)]
    basin=base(2,3,1.,"nested_basin_partial_and_spill")
    basin["initial"]["bedrock_m"]=[0.,1.,3.,0.,1.,3.]
    basin["initial"]["mobile_solid_m3"]=[0.]*6
    basin["operations"]=[{"kind":"basin","basins":[
        {"id":"west","cell_indices":[0,1],"children":[],"spill_m":3.,"spill_to_leaf":"east"},
        {"id":"east","cell_indices":[3,4],"children":[],"spill_m":3.,"spill_to_leaf":"west"},
        {"id":"joined","cell_indices":[0,1,2,3,4,5],"children":["west","east"],"spill_m":4.,"spill_to_leaf":None}],
        "leaf_water_m3":{"west":8.,"east":5.}}]
    basin["coverage"]["L07"]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Finite nested storage/spill on a declared synthetic hierarchy, no basin genesis or hydraulics."}
    ice=base(2,3,10.,"ice_to_tephra_to_wind")
    ice["initial"].update(bedrock_m=[4.,3.,2.,3.,2.,1.],mobile_solid_m3=[0.]*6,porosity=[.4]*6)
    ice["operations"]= [
      {"kind":"glacial_erosion","deposition_target":"mobile","parameters":{"ice_extent":[True,True,False,False,False,False],"warm_bed":[True,True,False,False,False,False],
        "sliding_speed_m_per_yr":[2.,3.,0.,0.,0.,0.],"erosion_constant_yr_per_m":1e-4,"duration_yr":10.,"erodible_thickness_m":[1.]*6,
        "receivers":[1,2,-1,4,5,-1],"deposit_fraction":[0.,0.,.75,0.,0.,0.],"bedrock_porosity":0.,"deposit_porosity":.4,"law":constructive.GLACIAL_LAW,"source_label":"SYNTHETIC prescribed sliding and source-to-deposit fractions"}},
      {"kind":"tephra_fallout","deposition_target":"mobile","parameters":{"origin_x_m":0.,"origin_y_m":0.,"footprint":[True]*6,"vent_x_m":5.,"vent_y_m":5.,
        "wind_x_m_s":.1,"wind_y_m_s":0.,"fall_time_s":10.,"diffusivity_m2_s":2.,"supplied_solid_m3":1.,"deposit_porosity":.4,"source_label":"SYNTHETIC constant-wind single-fall-time Gaussian test"}},
      {"kind":"aeolian_transport","deposition_target":"mobile","parameters":{"receivers":[1,2,-1,4,5,-1],"friction_velocity_east_m_s":[.6]*6,"friction_velocity_north_m_s":[0.]*6,
        "threshold_m_s":[.39]*6,"grain_diameter_m":.00045,"grain_density_kg_m3":2700.,"air_density_kg_m3":1.2,"gravity_m_s2":9.81,"porosity":.4,"duration_s":100.,
        "external_supply_solid_m3":[0.]*6,"law":constructive.AEOLIAN_LAW,"source_label":"SYNTHETIC common particle phase; saturated sand flux only"}}]
    for f in ("L04","L06","L09","L10"):ice["coverage"][f]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Source-to-deposit and supply-limited transfer only; not full glacier, volcano or dune morphology."}
    karst=base(2,2,10.,"carbonate_dissolved_export")
    karst["operations"]=[{"kind":"dissolution","parameters":{"mineral":"calcite_linear_region_2","transfer_coefficient_m_per_year":.1,
        "equilibrium_rock_equivalent_kg_m3":.1,"minimum_saturation":.36,"maximum_saturation":.9,"grain_density_kg_m3":2700.,"evidence_id":"SYNTHETIC reduced linear-film carbonate scenario within declared saturation interval"},
        "rock_available_kg":[1e6]*4,"water_m3":[10.]*4,"dissolved_rock_input_kg":[.4]*4,"reactive_area_m2":[1.]*4,"duration_years":1.}]
    karst["coverage"]["L05"]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Dissolved rock/carrier-water exchange only; no cavern/collapse/cockpit morphology."}
    peat=base(2,2,10.,"organic_accumulation_compaction")
    peat["operations"]=[{"kind":"organic","parameters":{"input_dry_organic_kg_m2_per_year":.1,"input_dry_mineral_kg_m2_per_year":.01,"decay_per_year":.01,
        "organic_grain_density_kg_m3":1400.,"mineral_grain_density_kg_m3":2700.,"evidence_id":"SYNTHETIC constant-input first-order decay; explicit saturated column"},
        "organic_kg":[0.]*4,"mineral_kg":[0.]*4,"void_ratio":[4.]*4,"external_water_m3":[1.]*4,"duration_years":1.},
      {"kind":"compaction","parameters":{"compression_index":.5,"minimum_effective_stress_pa":1000.,"maximum_effective_stress_pa":10000.,"evidence_id":"SYNTHETIC calibrated-interval placeholder; no Diadem peat coefficients"},
        "effective_stress_before_pa":[1000.]*4,"effective_stress_after_pa":[2000.]*4}]
    peat["coverage"]["L07"]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Separate organic dry mass, mineral mass, pore water and compaction; no field peat calibration."}
    flat=base(4,4,100.,"gentle_plain_zero_forcing")
    flat["initial"]["bedrock_m"]=[5.]*16
    flat["operations"][0].update(runoff_m_year=[0.]*16)
    automatic=base(4,4,10.,"automatic_basin_on_uneven_ground")
    automatic["operations"]=[{"kind":"automatic_basin","outlets":[12,13,14,15],"connectivity":8,
        "water_input_m3":[1.]*16,"source":"declared_independent_snapshot"}]
    automatic["coverage"]["L07"]={"status":"TESTED_NUMERICAL_SUBSET","reason":"Exact surface-derived basin topology and finite storage; no physical depression origin or transient channel capture claim."}
    return [upland,deposition,soil,basin,ice,karst,peat,flat,automatic]


def near_flat_capture_regression():
    recipe=deepcopy(suite()[2])
    recipe["scenario_id"]="near_flat_internal_basin_capture_UNSUPPORTED_REGRESSION"
    recipe["initial"]["bedrock_m"]=base(4,4,10.)["initial"]["bedrock_m"]
    recipe["coverage"]["L10"]={"status":"UNSUPPORTED","reason":"Tie-born depositional links require evolving basin/capture coupling; dt reduction alone does not resolve current relative-relief guard."}
    return recipe
