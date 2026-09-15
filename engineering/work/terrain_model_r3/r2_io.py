"""Read-only binding to the reviewed R2 file/receipt primitives."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
R2=HERE.parent/"terrain_model_r2"
INDEX=HERE.parents[1]/"outputs"/"terrain-model-r2"/"reference-r2-03"/"REFERENCE_VERIFICATION.json"
INDEX_SHA256="7eea0a8f30e64c34025330e55a667d4d6a7a1f589dc75f1c5c7067daf89bf1ba"
data=INDEX.read_bytes()
if hashlib.sha256(data).hexdigest()!=INDEX_SHA256:raise ValueError("R2 reference evidence identity changed")
EXPECTED={row["name"]:row["sha256"] for row in json.loads(data)["implementation"]}
NAMES=("core.py","workflow.py","materials.py","constructive.py","water.py","basin_topology.py","NUMERICAL_CONTRACT.json")


def verify_dependencies():
    pins=[]
    for name in NAMES:
        path=R2/name;raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=EXPECTED[name]:raise ValueError("reviewed R2 IO dependency changed:"+name)
        pins.append({"name":"R2/"+name,"bytes":len(raw),"sha256":digest})
    return pins


verify_dependencies()
prior=list(sys.path)
try:
    sys.path.insert(0,str(R2))
    spec=importlib.util.spec_from_file_location("_r3_reviewed_r2_io",R2/"workflow.py")
    io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
finally:sys.path[:]=prior
verify_dependencies()
