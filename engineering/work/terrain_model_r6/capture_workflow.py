"""Bounded capture snapshots with full phase-state checkpoint/recovery.

R4 successor of the frozen R3 workflow; no production or domain acceptance.
R3, R2 and the installed R2 task remain unchanged.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

import capture
from r4_io import io, verify_dependencies

HERE=Path(__file__).resolve().parent
# A same-named module from a prior R3 test process is not the R4 producer.
for module,filename in ((capture,'capture.py'),(getattr(capture,'event_settling',None),'event_settling.py'),
                        (getattr(capture,'phase_storage',None),'phase_storage.py')):
    if module is None or Path(module.__file__).resolve()!=HERE/filename:
        raise ValueError('R4 numerical namespace mismatch; use a fresh process')


def source_pins():
    pins=[{"name":p.name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
          for p in sorted(HERE.iterdir()) if p.suffix in {".py",".json",".md"} for raw in [io.read_bytes(p)]]
    return pins+verify_dependencies()


LOADED_SOURCE_PINS=source_pins()


def validate(recipe):
    io.require_keys(recipe,{"schema","purpose","scenario_id","state","forcing","limits","constraints","physical_acceptance","production_authorised"},"capture recipe")
    if recipe["schema"]!="diadem.terrain.capture.recipe.r4" or recipe["purpose"]!="SYNTHETIC_ENGINEERING_ONLY":
        raise ValueError("this bounded reference does not authorise Diadem generation")
    if recipe["physical_acceptance"] is not False or recipe["production_authorised"] is not False:
        raise ValueError("synthetic recipe cannot assert physical/production authority")
    if not isinstance(recipe["scenario_id"],str) or not recipe["scenario_id"]:raise ValueError("scenario ID required")
    io.require_keys(recipe["limits"],{"max_product_bytes","wall_seconds","checkpoint_steps"},"limits")
    for name,cap in (("max_product_bytes",64*1024*1024),("wall_seconds",120),("checkpoint_steps",4096)):
        value=recipe["limits"][name]
        if type(value) is not int or not 1<=value<=cap:raise ValueError("invalid "+name)
    state=capture.CaptureState(**recipe["state"])
    capture.check_controls(state,recipe["constraints"])
    io.require_keys(recipe["forcing"],{"steps","dt_years","outlets","connectivity","liquid_input_m3_year","suspended_input_m3_year",
        "bed_input_solid_m3_year","settling_m_year","source_label"},"forcing")
    steps=recipe["forcing"]["steps"]
    if type(steps) is not int or not 1<=steps<=4096 or steps*state.size>2097152:raise ValueError("step envelope exceeded")
    if math.ceil(steps/recipe["limits"]["checkpoint_steps"])>128:raise ValueError("at most128 durable checkpoints per bounded recipe")
    # Validate forcing even before admitting a previous committed generation.
    capture.number(recipe["forcing"]["dt_years"],"dt",0,True)
    capture.number(recipe["forcing"]["settling_m_year"],"settling",0)
    for name in ("liquid_input_m3_year","suspended_input_m3_year","bed_input_solid_m3_year"):
        capture.vector(recipe["forcing"][name],state.size,name,0)
    label=recipe["forcing"]["source_label"]
    if not isinstance(label,str) or not label.startswith("SYNTHETIC "):raise ValueError("explicit synthetic port source required")
    if any(w==0 and s>0 for w,s in zip(recipe["forcing"]["liquid_input_m3_year"],recipe["forcing"]["suspended_input_m3_year"])):
        raise ValueError("suspended inlet requires carrier liquid")
    outlets=recipe["forcing"]["outlets"];connectivity=recipe["forcing"]["connectivity"]
    if type(connectivity) is not int or connectivity not in (4,8):raise ValueError("explicit4/8 connectivity required")
    if type(outlets) is not list or any(type(i) is not int or not 0<=i<state.size for i in outlets) or len(set(outlets))!=len(outlets):
        raise ValueError("unique native outlet indices required")
    rows,cols=state.shape
    if any(i//cols not in (0,rows-1) and i%cols not in (0,cols-1) for i in outlets):raise ValueError("outlets must be native edge cells")
    return state


def product_pins(directory,names):
    return {name:{"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
            for name in names for raw in [io.read_bytes(directory/name)]}


def verify_output(directory,identity):
    directory=io.unlinked(directory);receipt=io.read_json(directory/"RECEIPT.json")
    if io.canonical(receipt["identity"])!=io.canonical(identity) or receipt["production_authorised"] is not False:
        raise ValueError("capture generation identity/authority mismatch")
    recipe=io.read_json(directory/"RECIPE.json");initial=validate(recipe)
    if hashlib.sha256(io.canonical(recipe)).hexdigest()!=identity["canonical_recipe_sha256"]:
        raise ValueError("stored recipe differs from bound canonical recipe")
    count=recipe["forcing"]["steps"];interval=recipe["limits"]["checkpoint_steps"]
    names=["RECIPE.json","RESULT.json"]+[f"CHECKPOINT-{min(i+interval,count):06d}.json" for i in range(0,count,interval)]
    if {p.name for p in directory.iterdir()}!=set(names)|{"RECEIPT.json"}:raise ValueError("foreign/missing capture output inventory")
    actual=product_pins(directory,names)
    if io.canonical(actual)!=io.canonical(receipt["products"]):raise ValueError("corrupt capture generation")
    if sum(p.stat().st_size for p in directory.iterdir())>recipe["limits"]["max_product_bytes"]:
        raise ValueError("capture storage envelope exceeded")
    previous=hashlib.sha256(io.canonical(initial.as_dict())).hexdigest()
    previous_time=initial.time_years
    checkpoint_names=names[2:]
    for completed,name in zip((min(i+interval,count) for i in range(0,count,interval)),checkpoint_names):
        record=io.read_json(directory/name)
        io.require_keys(record,{"identity","previous_state_sha256","completed_steps","state","diagnostics"},"checkpoint")
        if record["identity"]!=identity["generation_id"] or record["previous_state_sha256"]!=previous or type(record["completed_steps"]) is not int or record["completed_steps"]!=completed:
            raise ValueError("checkpoint generation/state chain mismatch")
        state=capture.CaptureState(**record["state"])
        if state.time_years<=previous_time:raise ValueError("checkpoint time does not advance")
        capture.check_controls(state,recipe["constraints"])
        if io.canonical(state.as_dict())!=io.canonical(record["state"]):raise ValueError("checkpoint state is not canonical/full precision")
        previous=hashlib.sha256(io.canonical(state.as_dict())).hexdigest();previous_time=state.time_years
    result=io.read_json(directory/"RESULT.json")
    if result["schema"]!="diadem.terrain.capture.result.r4" or result["scenario_id"]!=recipe["scenario_id"] or result["checkpoints"]!=checkpoint_names:
        raise ValueError("capture result recipe/checkpoint binding mismatch")
    if any(result[key] is not False for key in ("physical_acceptance","shoreline_capture_acceptance","production_authorised")):
        raise ValueError("capture result cannot assert physical/production authority")
    if io.canonical(result["state"])!=io.canonical(record["state"]) or io.canonical(result["physical_bed_m"])!=io.canonical(list(state.bed_m)) or io.canonical(result["current_diagnostics"])!=io.canonical(record["diagnostics"]):
        raise ValueError("capture final state/geometry differs from checkpoint")
    if io.canonical(product_pins(directory,names))!=io.canonical(actual):raise ValueError("capture product changed during verification")
    return receipt


def run(recipe_path,output,*,resume=False,interrupt_after_step=None,interrupt_at=None):
    started=time.monotonic();recipe_path=io.unlinked(recipe_path);output=io.unlinked(output)
    allowed=HERE.parents[1]/"outputs"/"terrain-model-r6-capture"
    if output==allowed or not output.is_relative_to(allowed) or output in recipe_path.parents:
        raise ValueError("capture output outside new bounded candidate roots")
    raw=io.read_bytes(recipe_path);recipe=io.parse_json(raw);initial=validate(recipe);pins=source_pins()
    if pins!=LOADED_SOURCE_PINS:raise ValueError("capture sources changed since module loading; restart with the frozen source set")
    identity={"recipe_sha256":hashlib.sha256(raw).hexdigest(),"canonical_recipe_sha256":hashlib.sha256(io.canonical(recipe)).hexdigest(),"implementation":pins,"python":sys.version,
              "platform":platform.platform(),"mode":"event_resolved_prescribed_port_capture_reference_r4"}
    identity["generation_id"]=hashlib.sha256(io.canonical(identity)).hexdigest()
    deadline=started+recipe["limits"]["wall_seconds"]
    def current():
        if source_pins()!=pins or io.read_bytes(recipe_path)!=raw:raise ValueError("capture source drift")
        if time.monotonic()>deadline:raise ValueError("whole capture workflow wall-time envelope exceeded")
    if output.exists():
        if not resume:raise FileExistsError(output)
        receipt=verify_output(output,identity);current()
        return {"status":"VERIFIED_CAPTURE_REUSE","generation_id":identity["generation_id"],"receipt":receipt}
    pending=io.unlinked(output.with_name(output.name+".pending-"+identity["generation_id"][:16]))
    if pending.exists():
        if not resume:raise FileExistsError("partial capture exists; explicit resume required")
    else:pending.mkdir(parents=True,exist_ok=False)
    def save(name,value):
        data=io.canonical(value);path=pending/name
        if path.exists():
            if io.read_bytes(path)!=data:raise ValueError("checkpoint/recovery content differs:"+name)
        else:
            size=sum(p.stat().st_size for p in pending.iterdir())+len(data)
            if size>recipe["limits"]["max_product_bytes"]:raise ValueError("capture checkpoint storage envelope exceeded")
            io.write_json_new(path,value)
    save("RECIPE.json",recipe)
    count=recipe["forcing"]["steps"];interval=recipe["limits"]["checkpoint_steps"]
    allowed_names={"RECIPE.json","RESULT.json","RECEIPT.json"}|{f"CHECKPOINT-{min(i+interval,count):06d}.json" for i in range(0,count,interval)}
    if {p.name for p in pending.iterdir()}-allowed_names:raise ValueError("foreign partial capture product")
    # A partial checkpoint is independently reconstructed before its state is
    # trusted. This reference prioritises verified recovery, not faster restart.
    state=initial;checkpoints=[];previous=hashlib.sha256(io.canonical(state.as_dict())).hexdigest()
    for from_step in range(0,count,interval):
        current();n=min(interval,count-from_step)
        forcing={**recipe["forcing"],"steps":n,"wall_seconds":recipe["limits"]["wall_seconds"],"constraints":recipe["constraints"]}
        state,diagnostics=capture.advance(state,**forcing)
        checkpoint={"identity":identity["generation_id"],"previous_state_sha256":previous,"completed_steps":from_step+n,
                    "state":state.as_dict(),"diagnostics":diagnostics}
        name=f"CHECKPOINT-{from_step+n:06d}.json";save(name,checkpoint)
        # Read back actual stored precision; restore all three material/water
        # stores and elapsed time together before the next interval.
        loaded=io.read_json(pending/name)
        if io.canonical(loaded)!=io.canonical(checkpoint) or io.read_bytes(pending/name)!=io.canonical(checkpoint):
            raise ValueError("checkpoint readback differs from independently computed state")
        state=capture.CaptureState(**loaded["state"])
        previous=hashlib.sha256(io.canonical(state.as_dict())).hexdigest();checkpoints.append(name)
        current()
        if interrupt_after_step is not None and from_step+n>=interrupt_after_step:
            raise RuntimeError("injected interruption after phase-state checkpoint")
    result={"schema":"diadem.terrain.capture.result.r4","scenario_id":recipe["scenario_id"],"state":state.as_dict(),
            "physical_bed_m":list(state.bed_m),"checkpoints":checkpoints,"current_diagnostics":diagnostics,
            "physical_acceptance":False,"shoreline_capture_acceptance":False,"production_authorised":False,
            "downstream_status":"NO_DIADEM_PRODUCTS_CHANGED; real-domain derivatives would require independent rebinding"}
    save("RESULT.json",result)
    if interrupt_at=="after_products":raise RuntimeError("injected interruption after products")
    names=["RECIPE.json","RESULT.json",*checkpoints]
    save("RECEIPT.json",{"identity":identity,"products":product_pins(pending,names),"production_authorised":False})
    verify_output(pending,identity);current()
    if interrupt_at=="after_receipt":raise RuntimeError("injected interruption after receipt")
    if output.exists():raise FileExistsError("another capture writer committed first")
    pending.rename(output)
    verify_output(output,identity);current()
    return {"status":"COMMITTED_CAPTURE_REFERENCE","generation_id":identity["generation_id"],"output":str(output),
            "production_authorised":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--recipe",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--resume",action="store_true")
    args=parser.parse_args();print(json.dumps(run(args.recipe,args.output,resume=args.resume),indent=2))


if __name__=="__main__":main()
