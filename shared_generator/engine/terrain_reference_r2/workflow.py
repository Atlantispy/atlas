"""Parameterized bounded-reference workflow; production and adoption disabled.

This entry is deliberately usable only for declared synthetic engineering
recipes. Its gate is not a substitute for the future Diadem input/owner gates.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import uuid

from core import Grid, State, advance, constraints_check, field, gradients, number
import constructive
import materials
import water
import basin_topology

HERE=Path(__file__).resolve().parent
MAX_FILE=16*1024*1024
MAX_PRODUCT_BYTES=64*1024*1024


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")


def unlinked(path):
    path=Path(path).absolute()
    # Inspect the lexical chain before normalisation so a symlink/.. traversal
    # cannot disappear during resolve; compare containment on normalised paths.
    for current in (path,*path.parents):
        if current.is_symlink() or (current.exists() and getattr(current.stat(),"st_file_attributes",0)&0x400):
            raise ValueError("linked/reparse path rejected:"+str(current))
    return path.resolve(strict=False)


def read_bytes(path,maximum=MAX_FILE):
    path=unlinked(path)
    if not path.is_file() or path.stat().st_size>maximum:
        raise ValueError("bounded regular file required:"+str(path))
    before=path.stat()
    with path.open("rb") as stream:data=stream.read(maximum+1)
    after=path.stat()
    if len(data)>maximum or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
        raise ValueError("source changed/oversized during read")
    return data


def pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError("duplicate JSON key:"+key)
        result[key]=value
    return result


def read_json(path):
    return parse_json(read_bytes(path))


def parse_json(data):
    result=json.loads(data,object_pairs_hook=pairs,
                      parse_constant=lambda x:(_ for _ in ()).throw(ValueError("nonfinite JSON")))
    canonical(result)
    return result


def implementation_pins():
    return [{"name":p.name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            for p in sorted(HERE.iterdir()) if p.suffix in {".py",".json",".md"}
            for data in [read_bytes(p)]]


def require_keys(value,keys,name):
    if type(value) is not dict or set(value)!=set(keys):
        raise ValueError(name+" has missing/unknown keys")


def constructive_frame(state,parameters):
    """Explicit south-row core to north-row constructive conversion."""
    g=state.grid;n=g.size
    def index(i):
        if type(i) is not int or not -1<=i<n:raise ValueError("invalid constructive cell identity")
        return i if i==-1 else (g.rows-1-i//g.cols)*g.cols+i%g.cols
    def reverse(values):
        if not isinstance(values,(list,tuple)) or len(values)!=n:raise ValueError("constructive field/grid mismatch")
        return [values[index(i)] for i in range(n)]
    per_cell={"footprint","thickness_weights","ice_extent","warm_bed","sliding_speed_m_per_yr",
              "bed_gradient","erodible_thickness_m","deposit_fraction","friction_velocity_east_m_s",
              "friction_velocity_north_m_s","threshold_m_s","external_supply_solid_m3",
              "cumulative_normal_heave_m","active_layer_m","outlet_gradient"}
    p={k:reverse(v) if k in per_cell else v for k,v in parameters.items()}
    if "receivers" in p:p["receivers"]=[index(j) for j in reverse(p["receivers"])]
    if "vent_cells" in p:p["vent_cells"]=[index(i) for i in p["vent_cells"]]
    if "origin_y_m" in p:
        if p["origin_y_m"]!=g.origin_y_m or p["origin_x_m"]!=g.origin_x_m:
            raise ValueError("tephra origin must match the shared grid")
        p["origin_y_m"]=-(g.origin_y_m+g.rows*g.dy_m)
        p["vent_y_m"]=-p["vent_y_m"]
        p["wind_y_m_s"]=-p["wind_y_m_s"]
    return p,index,reverse


def constructive_result_to_core(result,index,reverse,n):
    result=dict(result)
    for key,value in list(result.items()):
        if key in {"vent_cells","capped_cells"}:result[key]=[index(i) for i in value]
        elif isinstance(value,list) and len(value)==n:result[key]=reverse(value)
    if "gaussian_mean_m" in result:result["gaussian_mean_m"][1]*=-1
    result["delivered_frame"]="synthetic_local_m_x_east_y_south"
    result["frame_adapter"]="row reversal; y-coordinate reflection; receivers and cell IDs remapped"
    return result


def validate_recipe(recipe):
    require_keys(recipe,{"schema","purpose","scenario_id","source_status","grid","initial","operations",
                         "constraints","coverage","coupling","limits","parameter_evidence"},"recipe")
    if recipe["schema"]!="diadem.terrain.bounded-reference.r2" or recipe["purpose"]!="SYNTHETIC_ENGINEERING_ONLY":
        raise ValueError("Diadem/production generation is not authorised by this reference entry")
    if recipe["source_status"]!="WORKING NON-CANON SYNTHETIC" or not isinstance(recipe["scenario_id"],str) or not recipe["scenario_id"]:
        raise ValueError("explicit synthetic identity required")
    g=Grid(**recipe["grid"])
    if g.frame!="synthetic_local_m_x_east_y_south" or g.vertical_datum!="synthetic_relative_m":
        raise ValueError("unbound real-world/Diadem coordinate frames are not admitted")
    require_keys(recipe["limits"],{"max_cells","max_steps","max_product_bytes","max_cell_steps","wall_seconds"},"limits")
    for key,cap in (("max_cells",16384),("max_steps",4096),("max_product_bytes",MAX_PRODUCT_BYTES),("max_cell_steps",2097152),("wall_seconds",120)):
        value=recipe["limits"][key]
        if type(value) is not int or not 1<=value<=cap:raise ValueError("invalid bounded "+key)
    if g.size>recipe["limits"]["max_cells"]:raise ValueError("cell envelope exceeded")
    if type(recipe["operations"]) is not list or not 1<=len(recipe["operations"])<=64:
        raise ValueError("requires1..64 declared operations")
    if type(recipe["coverage"]) is not dict or set(recipe["coverage"])!={f"L{i:02d}" for i in range(1,12)}|{"additional"}:
        raise ValueError("all terrain families must have explicit coverage")
    for family,item in recipe["coverage"].items():
        require_keys(item,{"status","reason"},family)
        if item["status"] not in {"TESTED_NUMERICAL_SUBSET","NOT_IN_THIS_SYNTHETIC_FIXTURE","UNSUPPORTED"} or not isinstance(item["reason"],str) or not item["reason"]:
            raise ValueError("coverage cannot assert unverified physical acceptance")
    require_keys(recipe["coupling"],{"mode","reason","terrain_forcing_max_change_m","dependent_fields"},"coupling")
    if recipe["coupling"]["mode"]!="PRESCRIBED_SYNTHETIC_FORCING_SENSITIVITY_ONLY" or not recipe["coupling"]["reason"]:
        raise ValueError("real climate feedback has not been validated")
    number(recipe["coupling"]["terrain_forcing_max_change_m"],"forcing support bound",0)
    if not isinstance(recipe["parameter_evidence"],list) or not recipe["parameter_evidence"]:
        raise ValueError("parameter evidence/scenario declarations required")
    s=State(grid=g,**recipe["initial"])
    if s.source_status!="WORKING NON-CANON SYNTHETIC ENGINEERING SCENARIO":
        raise ValueError("synthetic reference state cannot assert canon or real-domain authority")
    for c in recipe["constraints"]:
        if not isinstance(c,dict) or c.get("source_status") not in {"SYNTHETIC","WORKING NON-CANON SYNTHETIC"}:
            raise ValueError("synthetic reference controls require explicitly synthetic source status")
    constraints_check(s,recipe["constraints"])
    return s


def execute(recipe):
    s=validate_recipe(recipe); initial=s; n=s.grid.size; area=s.grid.area_m2
    deadline=time.monotonic()+recipe["limits"]["wall_seconds"]
    records=[]; total_steps=0; layers={}; aux=[0.]*n
    channel_solid_reservoir=0.; channel_water_reservoir=0.
    finite_rock=None
    water_result=None; water_status="NOT_COMPUTED"; automatic_water_assessed=False
    for op in recipe["operations"]:
        if time.monotonic()>deadline:raise ValueError("bounded wall-time envelope exceeded")
        if type(op) is not dict or "kind" not in op:raise ValueError("operation kind required")
        kind=op["kind"]; args={k:v for k,v in op.items() if k!="kind"}
        if any(aux) and kind not in {"basin","automatic_basin","organic","compaction"}:
            raise ValueError("erosion through organic/immobile layers needs a separate validated adapter")
        before=[z+h for z,h in zip(s.surface_m,aux)]
        bedrock_before=s.bedrock_m
        if kind=="coupled":
            total_steps+=args.get("steps",0)
            if total_steps>recipe["limits"]["max_steps"] or total_steps*n>recipe["limits"]["max_cell_steps"]:raise ValueError("step envelope exceeded")
            if set(args)&{"constraints","_deadline"}:raise ValueError("constraints/deadline belong to the shared recipe")
            s,steps=advance(s,constraints=recipe["constraints"],_deadline=deadline,**args)
            channel_solid_reservoir+=math.fsum(step["channel"]["external_solid_export_m3"] for step in steps)
            channel_water_reservoir+=math.fsum(step["channel"]["external_water_export_m3"] for step in steps)
            record={"kind":kind,"steps":steps,"actual_surface_used_for_channels":True}
        elif kind=="soil":
            require_keys(args,{"parameters","rock_available_kg","regolith_kg","duration_years"},"soil")
            p=materials.SoilProductionParameters(**args["parameters"])
            if p.rock_grain_density_kg_m3!=s.rock_density_kg_m3 or p.mobile_grain_density_kg_m3!=s.sediment_density_kg_m3 or p.rock_porosity!=0 or any(v!=p.mobile_porosity for v in s.porosity):
                raise ValueError("soil/state material density or porosity mismatch")
            rock=field(args["rock_available_kg"],n,"available rock",0)
            reg=field(args["regolith_kg"],n,"regolith",0)
            if any(reg):raise ValueError("initial immobile regolith must be represented before this adapter; use zero initial regolith")
            if finite_rock is not None and list(rock)!=finite_rock:raise ValueError("finite rock inventory reset between operations")
            finite_rock=list(rock)
            transfers=materials.soil_production_batch([
                {"area_m2":area,"rock_available_kg":rock[i],"regolith_kg":reg[i],
                 "mobile_kg":s.mobile_solid_m3[i]*s.sediment_density_kg_m3,"duration_years":args["duration_years"]}
                for i in range(n)],p)
            s=replace(s,bedrock_m=tuple(z-t.bedrock_lowering_m for z,t in zip(s.bedrock_m,transfers)),
                      mobile_solid_m3=tuple(t.mobile_after_kg/s.sediment_density_kg_m3 for t in transfers))
            aux=[t.regolith_after_kg/(p.regolith_grain_density_kg_m3*(1-p.regolith_porosity)*area) for t in transfers]
            if any(aux):layers["immobile_regolith"]={"height_m":aux,"parameters":asdict(p),"mass_kg":[t.regolith_after_kg for t in transfers]}
            record={"kind":kind,"transfers":[asdict(t) for t in transfers],"dissolved_destination":"explicit unresolved rock-derived reservoir; not lost or chemistry-certified"}
        elif kind=="dissolution":
            require_keys(args,{"parameters","rock_available_kg","water_m3","dissolved_rock_input_kg","reactive_area_m2","duration_years"},"dissolution")
            p=materials.DissolutionParameters(**args["parameters"])
            if p.grain_density_kg_m3!=s.rock_density_kg_m3:raise ValueError("dissolution substrate density mismatch")
            fields={k:field(args[k],n,k,0) for k in ("rock_available_kg","water_m3","dissolved_rock_input_kg","reactive_area_m2")}
            if finite_rock is not None and list(fields["rock_available_kg"])!=finite_rock:raise ValueError("finite rock inventory reset between operations")
            finite_rock=list(fields["rock_available_kg"])
            transfers=materials.dissolution_batch([{**{k:v[i] for k,v in fields.items()},"duration_years":args["duration_years"]} for i in range(n)],p)
            s=replace(s,bedrock_m=tuple(z-t.rock_solid_removed_m3/area for z,t in zip(s.bedrock_m,transfers)))
            record={"kind":kind,"transfers":[asdict(t) for t in transfers],"surface_interpretation":"uniform column chemical denudation only; no void collapse or conduit geometry"}
        elif kind in {"volcanic_emplacement","tephra_fallout","glacial_erosion","aeolian_transport","frost_creep"}:
            require_keys(args,{"parameters","deposition_target"},"constructive")
            p=dict(args["parameters"])
            if s.grid.dx_m!=s.grid.dy_m:raise ValueError("constructive adapter requires square cells")
            reserved={"rows","cols","cell_size_m","base_elevation_m","bed_elevation_m","surface_elevation_m","mobile_thickness_m","bed_gradient"}
            if set(p)&reserved:raise ValueError("operation cannot replace shared state geometry")
            if kind=="glacial_erosion":p["bed_gradient"]=gradients(s.grid,s.surface_m)["grade_m_per_m"]
            if kind=="aeolian_transport" and p.get("grain_density_kg_m3")!=s.sediment_density_kg_m3:raise ValueError("aeolian grain density differs from shared mobile material")
            p,index,reverse=constructive_frame(s,p)
            common={"rows":s.grid.rows,"cols":s.grid.cols,"cell_size_m":s.grid.dx_m}
            if kind in {"volcanic_emplacement","tephra_fallout"}:
                result=getattr(constructive,kind)(reverse(s.surface_m),**common,**p)
            elif kind=="glacial_erosion":
                if any(s.mobile_solid_m3):raise ValueError("prescribed glacial bare-bed law cannot erase unmodelled cover")
                if s.rock_density_kg_m3!=s.sediment_density_kg_m3:raise ValueError("glacial volume adapter requires equal solid densities")
                if p.get("bedrock_porosity")!=0:raise ValueError("shared bedrock is explicitly nonporous")
                result=constructive.glacial_erosion(reverse(s.surface_m),**common,**p)
            elif kind=="aeolian_transport":result=constructive.aeolian_transport(reverse(s.cover_m),**common,**p)
            else:result=constructive.frost_creep(reverse(s.surface_m),reverse(s.cover_m),**common,**p)
            result=constructive_result_to_core(result,index,reverse,n)
            target=args["deposition_target"]
            if target not in {"bedrock","mobile"}:raise ValueError("typed deposition target required")
            deposit_p=p.get("deposit_porosity",p.get("porosity"))
            if target=="mobile" and any(v!=deposit_p for v in s.porosity):raise ValueError("deposition/state porosity mismatch")
            if target=="bedrock" and (kind not in {"volcanic_emplacement"} or deposit_p!=0):raise ValueError("only explicitly nonporous constructive emplacement may add bedrock")
            if target=="bedrock" and any(s.mobile_solid_m3):raise ValueError("bedrock emplacement over cover requires a burial/stratigraphy adapter")
            new_rock=[z-e+(d if target=="bedrock" else 0) for z,e,d in zip(s.bedrock_m,result["bedrock_erosion_m"],result["deposition_m"])]
            mobile=[v-e*area*(1-p0)+(d*area*(1-p0) if target=="mobile" else 0) for v,e,d,p0 in zip(s.mobile_solid_m3,result["mobile_erosion_m"],result["deposition_m"],s.porosity)]
            s=replace(s,bedrock_m=tuple(new_rock),mobile_solid_m3=tuple(mobile))
            record={"kind":kind,"deposition_target":target,"result":result}
        elif kind=="submerged_deposition":
            require_keys(args,{"cells","parameters","source"},kind)
            if len(args["cells"])!=len(args["parameters"]) or len(set(args["cells"]))!=len(args["cells"]):raise ValueError("unique deposition cells required")
            if args["source"] not in {"declared_external_boundary","preceding_channel_export"}:raise ValueError("deposition source must be explicit")
            linked=args["source"]=="preceding_channel_export"
            if linked:
                fractions=[number(p.get("fraction"),"receiver fraction",0) for p in args["parameters"]]
                if math.fsum(fractions)!=1.:raise ValueError("receiver fractions must sum exactly to1")
            mobile=list(s.mobile_solid_m3); records_local=[]
            for i,p in zip(args["cells"],args["parameters"]):
                if type(i) is not int or not 0<=i<n or set(p)&{"bed_m","cell_area_m2","porosity"}:raise ValueError("invalid submerged state override")
                p=dict(p)
                if linked:
                    if set(p)&{"incoming_solid_m3_per_year","water_discharge_m3_per_year"}:raise ValueError("linked sediment/water must come from preceding channel, not independent values")
                    fraction=p.pop("fraction"); interval=number(p.get("interval_years"),"receiver interval",0,True)
                    p["incoming_solid_m3_per_year"]=channel_solid_reservoir*fraction/interval
                    p["water_discharge_m3_per_year"]=channel_water_reservoir*fraction/interval
                r=water.local_sediment_deposition(bed_m=s.surface_m[i],cell_area_m2=area,porosity=s.porosity[i],**p)
                mobile[i]+=r["deposited_solid_m3"]
                records_local.append({"cell":i,**r})
            s=replace(s,mobile_solid_m3=tuple(mobile))
            record={"kind":kind,"source":args["source"],"cells":records_local,"receiving_stage_is_prescribed_not_solved":True}
            if linked:
                record["internal_transfer_from_channels"]={"solid_m3":channel_solid_reservoir,"water_m3":channel_water_reservoir}
                channel_solid_reservoir=0.;channel_water_reservoir=0.
        elif kind=="basin":
            if automatic_water_assessed:raise ValueError("repeated water assessment needs a validated inventory continuation adapter")
            require_keys(args,{"basins","leaf_water_m3"},kind)
            physical=[z+h for z,h in zip(s.surface_m,aux)]
            water_result=water.fill_spill_merge(physical,[area]*n,args["basins"],args["leaf_water_m3"])
            water_status="CURRENT_ON_EXACT_REPRESENTED_BED"
            record={"kind":kind,"result":water_result,"physical_bed_unchanged":True}
        elif kind=="automatic_basin":
            if automatic_water_assessed or any(r["kind"]=="basin" for r in records):raise ValueError("repeated water assessment needs a validated inventory continuation adapter")
            automatic_water_assessed=True
            require_keys(args,{"outlets","connectivity","water_input_m3","source"},kind)
            if args["source"]!="declared_independent_snapshot":
                raise ValueError("automatic basin is an independent water snapshot, not channel feedback")
            physical=[z+h for z,h in zip(s.surface_m,aux)]
            volumes=field(args["water_input_m3"],n,"explicit cell water volume",0)
            topology=basin_topology.extract_basin_topology(physical,[s.grid.rows,s.grid.cols],args["outlets"],connectivity=args["connectivity"])
            supplies={leaf:math.fsum(v for v,label in zip(volumes,topology["cell_to_leaf"]) if label==leaf) for leaf in topology["leaf_ids"]}
            direct=math.fsum(v for v,label in zip(volumes,topology["cell_to_leaf"]) if label is None)
            if topology["basins"]:
                storage=water.fill_spill_merge(physical,[area]*n,topology["basins"],supplies,**topology["storage_options"])
            else:
                storage={"water_depth_m":[0.]*n,"water_surface_m":[None]*n,"active_pools":[],
                         "stored_volume_m3":0.,"exported_volume_m3":0.,"input_volume_m3":0.,"water_residual_m3":0.}
            total=math.fsum(volumes); exported=math.fsum([direct,storage["exported_volume_m3"]])
            residual=math.fsum([storage["stored_volume_m3"],exported,-total])
            if abs(residual)>1e-9+1e-12*max(total,storage["stored_volume_m3"],exported):raise ValueError("automatic basin water ledger does not close")
            water_result={**storage,"input_volume_m3":total,"exported_volume_m3":exported,"water_residual_m3":residual,
                          "direct_boundary_export_m3":direct,"basin_boundary_export_m3":storage["exported_volume_m3"],
                          "topology":topology,"source":args["source"],"transient_channel_feedback_solved":False}
            water_status="CURRENT_ON_EXACT_REPRESENTED_BED"
            record={"kind":kind,"result":water_result,"physical_bed_unchanged":True}
        elif kind=="organic":
            require_keys(args,{"parameters","organic_kg","mineral_kg","void_ratio","external_water_m3","duration_years"},kind)
            if "immobile_regolith" in layers:raise ValueError("organic/immobile mixed stratigraphy requires explicit adapter")
            p=materials.OrganicParameters(**args["parameters"])
            if "organic" in layers and any(getattr(p,k)!=layers["organic"]["parameters"][k] for k in ("organic_grain_density_kg_m3","mineral_grain_density_kg_m3")):
                raise ValueError("existing organic-layer grain densities cannot silently change")
            arrays={k:field(args[k],n,k,0) for k in ("organic_kg","mineral_kg","void_ratio","external_water_m3")}
            if "organic" not in layers and (any(arrays["organic_kg"]) or any(arrays["mineral_kg"])):
                raise ValueError("new organic layer requires zero initial inventory; existing layers need explicit initial stratigraphy")
            if "organic" in layers and any(list(arrays[k])!=layers["organic"][k] for k in ("organic_kg","mineral_kg","void_ratio")):
                raise ValueError("organic operation must consume previous layer inventories")
            transfers=materials.organic_batch([{**{k:v[i] for k,v in arrays.items()},"area_m2":area,"duration_years":args["duration_years"]} for i in range(n)],p)
            aux=[t.bulk_volume_after_m3/area for t in transfers]
            layers["organic"]={"height_m":aux,"organic_kg":[t.organic_after_kg for t in transfers],
                               "mineral_kg":[t.mineral_after_kg for t in transfers],"void_ratio":list(arrays["void_ratio"]),"parameters":asdict(p)}
            record={"kind":kind,"transfers":[asdict(t) for t in transfers],"decay_export":"dry organic-origin kg; chemical gas identity unresolved"}
        elif kind=="compaction":
            require_keys(args,{"parameters","effective_stress_before_pa","effective_stress_after_pa"},kind)
            if "organic" not in layers:raise ValueError("compaction requires represented organic layer")
            layer=layers["organic"]; p=materials.CompactionParameters(**args["parameters"])
            organic_p=layer["parameters"]
            stresses={k:field(args[k],n,k,0) for k in ("effective_stress_before_pa","effective_stress_after_pa")}
            transfers=materials.compaction_batch([{"area_m2":area,"solid_volume_m3":layer["organic_kg"][i]/organic_p["organic_grain_density_kg_m3"]+layer["mineral_kg"][i]/organic_p["mineral_grain_density_kg_m3"],
                 "void_ratio":layer["void_ratio"][i],**{k:v[i] for k,v in stresses.items()}} for i in range(n)],p)
            aux=[t.bulk_volume_after_m3/area for t in transfers]
            layer["height_m"]=aux; layer["void_ratio"]=[t.void_ratio_after for t in transfers]
            record={"kind":kind,"transfers":[asdict(t) for t in transfers]}
        else:raise ValueError("unsupported process:"+str(kind))
        if time.monotonic()>deadline:raise ValueError("bounded wall-time envelope exceeded after operation")
        if finite_rock is not None:
            changes=[(old-new)*area*s.rock_density_kg_m3 for old,new in zip(bedrock_before,s.bedrock_m)]
            finite_rock=[amount-change for amount,change in zip(finite_rock,changes)]
            if min(finite_rock)<-1e-6:raise ValueError("operation exhausts shared finite rock inventory")
            finite_rock=[max(0.,v) for v in finite_rock]
        physical=[z+h for z,h in zip(s.surface_m,aux)]
        if kind not in {"basin","automatic_basin"} and water_result is not None and canonical(physical)!=canonical(before):
            # Preserve prior water evidence in its operation record, but never
            # expose it as current after the physical bed/layers change.
            water_result=None;water_status="STALE_BED_CHANGED_REQUIRES_RECOMPUTATION"
        if max(abs(z-b) for z,b in zip(physical,initial.surface_m))>recipe["coupling"]["terrain_forcing_max_change_m"]:
            raise ValueError("synthetic prescribed-forcing sensitivity envelope exceeded during sequence")
        proxy=replace(s,bedrock_m=tuple(z+h for z,h in zip(s.bedrock_m,aux)))
        record["shared_surface_control_residuals"]=constraints_check(proxy,recipe["constraints"])
        record["maximum_height_change_m"]=max(abs(z-b) for z,b in zip(physical,before))
        records.append(record)
    physical=[z+h for z,h in zip(s.surface_m,aux)]
    delta=[z-b for z,b in zip(physical,initial.surface_m)]
    if max(abs(v) for v in delta)>recipe["coupling"]["terrain_forcing_max_change_m"]:
        raise ValueError("synthetic prescribed-forcing sensitivity envelope exceeded; recompute forcing")
    return {"schema":"diadem.terrain.bounded-result.r2","status":"NUMERICAL_REFERENCE_NOT_PHYSICAL_ACCEPTANCE",
            "scenario_id":recipe["scenario_id"],"grid":asdict(s.grid),"state":{**s.as_dict(),"surface_m":physical},
            "auxiliary_layers":layers,"change_m":delta,"gradients":gradients(s.grid,physical),
            "finite_rock_remaining_kg":finite_rock,
            "unconsumed_channel_boundary_transfer":{"solid_m3":channel_solid_reservoir,"water_m3":channel_water_reservoir},
            "operations":records,"water":water_result,"water_status":water_status,"coverage":recipe["coverage"],
            "downstream_invalidation":{"status":"REQUIRED_IF_ADOPTED_NO_PRODUCTS_REBUILT","dependencies":recipe["coupling"]["dependent_fields"],
                "domain":"union of old/new terrain, water, atmospheric and material influence; real domain unresolved"},
            "gates":{"bounded_numerical_recipe":"BOUND","whole_model_B":"INCOMPLETE","physical_C":"INCOMPLETE","optimisation_D":"NOT_RUN","production_E":"NOT_RUN","adoption_F":"NOT_RUN"},
            "production_authorised":False,"diadem_canon_changed":False}


def write_json_new(path,value):
    data=canonical(value)
    if len(data)>MAX_FILE:raise ValueError("product file budget exceeded")
    with unlinked(path).open("xb") as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    if read_bytes(path)!=data:raise ValueError("write/readback mismatch")


def verify_generation(directory,identity):
    directory=unlinked(directory); receipt=read_json(directory/"RECEIPT.json")
    if canonical(receipt["identity"])!=canonical(identity) or receipt.get("production_authorised") is not False:raise ValueError("generation identity/authority mismatch")
    if set(receipt["products"])!={"RECIPE.json","RESULT.json"}:raise ValueError("unexpected generation inventory")
    if {p.name for p in directory.iterdir()}!={"RECEIPT.json","RECIPE.json","RESULT.json"}:raise ValueError("mixed/extra generation products")
    for name,pin in receipt["products"].items():
        data=read_bytes(directory/name)
        if canonical({"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})!=canonical(pin):raise ValueError("corrupt generation product:"+name)
    recipe=read_json(directory/"RECIPE.json")
    total=sum(p.stat().st_size for p in directory.iterdir())
    if total>recipe["limits"]["max_product_bytes"]:raise ValueError("committed product byte budget exceeded")
    return receipt


def run(recipe_path,output,*,resume=False,interrupt_at=None,expected_recipe_sha256=None):
    started=time.monotonic()
    recipe_path=unlinked(recipe_path); output=unlinked(output)
    if output==output.parent or output in recipe_path.parents:raise ValueError("output contains source or is a root")
    allowed=(HERE.parents[1]/"outputs"/"terrain-model-r2",)
    # Installed normal-workflow copy may only emit below its generated_outputs.
    if HERE.parent.name=="engine":allowed=(HERE.parent.parent/"generated_outputs",)
    if not any(output.is_relative_to(root.resolve()) and output!=root.resolve() for root in allowed):
        raise ValueError("output outside bounded candidate roots")
    data=read_bytes(recipe_path); recipe=parse_json(data); pins=implementation_pins()
    validate_recipe(recipe)
    deadline=started+recipe["limits"]["wall_seconds"]
    if expected_recipe_sha256 is not None and hashlib.sha256(data).hexdigest()!=expected_recipe_sha256:
        raise ValueError("recipe changed since caller authorisation")
    identity={"recipe_sha256":hashlib.sha256(data).hexdigest(),"implementation":pins,"python":sys.version,
              "platform":platform.platform(),"mode":"reference"}
    generation_id=hashlib.sha256(canonical(identity)).hexdigest()
    identity["generation_id"]=generation_id
    if output.exists():
        if not resume:raise FileExistsError(output)
        receipt=verify_generation(output,identity)
        if implementation_pins()!=pins or read_bytes(recipe_path)!=data:raise ValueError("source drift on reuse")
        if time.monotonic()>deadline:raise ValueError("whole-reference reuse wall-time envelope exceeded")
        return {"status":"VERIFIED_REUSE","generation_id":generation_id,"receipt":receipt}
    pending=unlinked(output.with_name(output.name+".pending-"+generation_id[:16]))
    if pending.exists():
        if not resume:raise FileExistsError("uncommitted generation; explicit resume required")
        if not (pending/"RECEIPT.json").exists():
            # An interruption before sealing is not trusted. Recompute the
            # bounded pure result and compare every existing byte; never
            # overwrite a corrupt/foreign partial generation to make it pass.
            if {p.name for p in pending.iterdir()}!={"RECIPE.json","RESULT.json"}:raise ValueError("incomplete partial products; preserve and use a new output path")
            if read_bytes(pending/"RECIPE.json")!=canonical(recipe) or read_bytes(pending/"RESULT.json")!=canonical(execute(recipe)):
                raise ValueError("unsealed recovery products do not match exact reconstruction")
            products={name:{"bytes":len(blob),"sha256":hashlib.sha256(blob).hexdigest()}
                      for name in ("RECIPE.json","RESULT.json") for blob in [read_bytes(pending/name)]}
            write_json_new(pending/"RECEIPT.json",{"identity":identity,"products":products,"production_authorised":False})
        verify_generation(pending,identity)
    else:
        result=execute(recipe)
        if implementation_pins()!=pins or read_bytes(recipe_path)!=data:raise ValueError("source changed during construction")
        blobs={"RECIPE.json":canonical(recipe),"RESULT.json":canonical(result)}
        products={name:{"bytes":len(blob),"sha256":hashlib.sha256(blob).hexdigest()} for name,blob in blobs.items()}
        receipt={"identity":identity,"products":products,"production_authorised":False}
        if sum(len(b) for b in blobs.values())+len(canonical(receipt))>recipe["limits"]["max_product_bytes"]:raise ValueError("total product budget including receipt exceeded")
        pending.mkdir(parents=True,exist_ok=False)
        write_json_new(pending/"RECIPE.json",recipe)
        write_json_new(pending/"RESULT.json",result)
        if interrupt_at=="after_products":raise RuntimeError("injected interruption after products")
        write_json_new(pending/"RECEIPT.json",receipt)
        verify_generation(pending,identity)
        if interrupt_at=="after_receipt":raise RuntimeError("injected interruption after receipt")
    if implementation_pins()!=pins or read_bytes(recipe_path)!=data:raise ValueError("source drift before commit")
    if time.monotonic()>deadline:raise ValueError("whole-reference wall-time envelope exceeded before commit")
    # Both absolute paths are confined to the same authorised candidate parent;
    # no overwrite, deletion, predecessor move or active authority is involved.
    if output.exists():raise FileExistsError("another writer committed first")
    pending.rename(output)
    verify_generation(output,identity)
    if implementation_pins()!=pins or read_bytes(recipe_path)!=data:raise ValueError("source drift after commit")
    if time.monotonic()>deadline:raise ValueError("generation committed but whole-reference wall-time envelope exceeded")
    return {"status":"COMMITTED_BOUNDED_REFERENCE","generation_id":generation_id,"output":str(output),"production_authorised":False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recipe",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--resume",action="store_true")
    args=p.parse_args()
    print(json.dumps(run(args.recipe,args.output,resume=args.resume),indent=2))


if __name__=="__main__":main()
