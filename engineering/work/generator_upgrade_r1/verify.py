"""Fresh-source, two-mode verification and one exclusive reference receipt.

Run this file directly with the bundled Python and existing scientific runtime.
No producer installation, world generation, benchmark or canon mutation occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time
import unittest

HERE=Path(__file__).resolve().parent
TASK=HERE.parents[1]
sys.path.insert(0,str(TASK))
READS={}
SUITES=("test_agroclimate", "test_land_food", "test_transport", "test_landscape", "test_integration")
EXPECTED_TEST_COUNT=134
TEST_INVENTORY_SHA256="c781b6f312989beab16ea45dc26382f0c17e236a9a358ad509dc74a6a640238f"
CATALOGUE_PINS={
    "release_contract.json":"a9fddf523c2bc3af5a0fe210062804e9dbd28e4a6fd27f05ded7929f5f40cda7",
    "catalogue/physical.json":"1c9aee0e9fa1bb04692322583673b812956e7950e5ae3c563922b3457ef6823b",
    "catalogue/environment.json":"9713cfec2019a853d6ba226d43e402147e60b3a6ecac5b0e2ee44c240cde1c8e",
    "catalogue/human_systems.json":"ac57d23e7e56fb655c4d0970e633f368e9395e9a074246fe419e8aab0349879e",
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path,data):
    with Path(path).open("x",encoding="utf-8") as stream:
        json.dump(data,stream,sort_keys=True,indent=2,allow_nan=False);stream.write("\n")


class SourceLoader(importlib.abc.Loader):
    def __init__(self,path):self.path=path
    def create_module(self,spec):return None
    def exec_module(self,module):
        raw=self.path.read_bytes();digest=hashlib.sha256(raw).hexdigest();key=str(self.path)
        if key in READS and READS[key]!=digest:raise ValueError("executed source changed")
        READS[key]=digest
        module.__file__=str(self.path)
        exec(compile(raw,str(self.path),"exec",dont_inherit=True),module.__dict__)


class SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if not fullname.startswith("work."):return None
        base=TASK.joinpath(*fullname.split("."))
        for candidate,package in ((base.with_suffix(".py"),False),(base/"__init__.py",True)):
            if candidate.is_file():
                return importlib.util.spec_from_file_location(fullname,candidate,loader=SourceLoader(candidate),
                    submodule_search_locations=[str(base)] if package else None)
        return None


def snapshot():
    return {str(p):sha(p) for p in sorted(HERE.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py",".md",".json"}}


def predecessor_readback():
    seal_path=TASK/"outputs/module-review-2026-09-10/FINAL_VERIFICATION.json"
    if sha(seal_path)!="6181ff1ced0e8fe7c6a96240bb702f38c55fbda2cfaccabe0c892336eda32b48":
        raise ValueError("prior module-review seal changed; no silent repin")
    prior=json.loads(seal_path.read_text())
    for path,expected in prior["candidate_source_snapshot"].items():
        if sha(path)!=expected:raise ValueError("prior corrected source changed: "+path)
    for name,expected in CATALOGUE_PINS.items():
        if sha(TASK/"work/generator_capabilities_r1"/name)!=expected:
            raise ValueError("18-category scope/acceptance contract changed: "+name)
    return {"prior_review_seal_sha256":sha(seal_path),
            "prior_candidate_files_unchanged":len(prior["candidate_source_snapshot"]),
            "catalogue_pins":CATALOGUE_PINS,
            "claim":"source preservation; previous 938 checks are not rerun or recounted here"}


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


class Result(unittest.TextTestResult):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.started=[];self.stopped=[];self.passed=[]
    def startTest(self,test):self.started.append(test.id());super().startTest(test)
    def stopTest(self,test):self.stopped.append(test.id());super().stopTest(test)
    def addSuccess(self,test):self.passed.append(test.id());super().addSuccess(test)


def worker(path):
    sys.meta_path.insert(0,SourceFinder())
    before=snapshot();preserved=predecessor_readback()
    suite=unittest.defaultTestLoader.loadTestsFromNames(["work.generator_upgrade_r1."+s for s in SUITES])
    inventory=[t.id() for t in flatten(suite)]
    inventory_sha=hashlib.sha256(json.dumps(inventory,separators=(",",":")).encode()).hexdigest()
    if (len(inventory)!=EXPECTED_TEST_COUNT or len(inventory)!=len(set(inventory))
            or inventory_sha!=TEST_INVENTORY_SHA256):
        raise ValueError("new implementation inventory incomplete/duplicated")
    output=io.StringIO();started=time.perf_counter()
    result=unittest.TextTestRunner(stream=output,verbosity=2,resultclass=Result).run(suite)
    duration=time.perf_counter()-started
    valid=(result.wasSuccessful() and not result.skipped and not result.expectedFailures
           and not result.unexpectedSuccesses and inventory==result.started==result.stopped==result.passed)
    reference=None
    if valid:
        from work.generator_upgrade_r1.reference import food_network_reference
        from work.generator_upgrade_r1.landscape import verification_reference
        reference={"crop_food_transport":food_network_reference(), "layered_landscape":verification_reference()}
    if snapshot()!=before:raise ValueError("new source changed during tests")
    if predecessor_readback()!=preserved:raise ValueError("predecessor changed during tests")
    for name,digest in READS.items():
        if sha(name)!=digest:raise ValueError("executed source changed: "+name)
    import numpy,scipy
    receipt={"status":"PASS" if valid else "FAIL","test_ids":inventory,"started":result.started,
        "stopped":result.stopped,"passed":result.passed,"tests":result.testsRun,
        "failures":len(result.failures),"errors":len(result.errors),"skips":len(result.skipped),
        "duration_seconds":duration,"optimisation_flag":sys.flags.optimize,
        "source_snapshot":before,"executed_source_hashes":READS,"predecessor_readback":preserved,
        "runtime":{"python":platform.python_version(),"numpy":numpy.__version__,"scipy":scipy.__version__},
        "reference":reference,"test_log":output.getvalue()}
    dump(path,receipt)
    print(json.dumps({key:receipt[key] for key in ("status","tests","failures","errors","skips","duration_seconds")}))
    return 0 if valid else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--worker",type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker)
    if not args.run_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",args.run_id):
        parser.error("provide a new bounded --run-id")
    root=TASK/"outputs/generator-upgrade-r1"/args.run_id
    for path in (root,*root.parents):
        if path.exists():
            info=path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:
                raise ValueError("linked/reparse output parent rejected")
    root.mkdir(parents=True,exist_ok=False)
    before=snapshot();prior=predecessor_readback();records=[]
    for label,flags in (("normal",[]),("assertions_disabled",["-OO"])):
        path=root/(label+".json")
        completed=subprocess.run([sys.executable,"-B",*flags,str(Path(__file__).resolve()),"--worker",str(path)],
                                 cwd=TASK,capture_output=True,text=True,timeout=900,env=os.environ.copy())
        dump(root/(label+"-process.json"),{"exit_code":completed.returncode,"stdout":completed.stdout,"stderr":completed.stderr})
        if completed.returncode!=0:raise RuntimeError("verification failed; diagnostics preserved: "+str(root))
        records.append(json.loads(path.read_text()))
    a,b=records
    for key in ("test_ids","source_snapshot","executed_source_hashes","predecessor_readback","runtime","reference"):
        if a[key]!=b[key]:raise ValueError("two-mode verification differs: "+key)
    if before!=snapshot() or prior!=predecessor_readback():raise ValueError("verification source drift")
    receipt={"schema":"diadem.scientific-upgrade-tranche.r1","status":"REFERENCE_IMPLEMENTED_AND_VERIFIED",
        "distinct_named_checks":len(a["test_ids"]),"runs_per_check":2,"failures":0,"errors":0,"skips":0,
        "test_ids":a["test_ids"],"source_snapshot":before,"predecessor_readback":prior,
        "workers":[{"path":str(root/(label+".json")),"sha256":sha(root/(label+".json"))}
                   for label in ("normal","assertions_disabled")],
        "runtime":a["runtime"],"reference_sha256":hashlib.sha256(json.dumps(a["reference"],sort_keys=True,allow_nan=False).encode()).hexdigest(),
        "production_installed":False,"whole_generator_upgraded":False,"all_categories_physically_accepted":False,
        "new_world_generated":False,"canon_changed":False,"generation_speedup_percent":None,
        "scope":"new bounded layered erosion, crop-water, land/food allocation and transport components with actual connected crop-food-network reference"}
    dump(root/"VERIFICATION.json",receipt)
    print(json.dumps({key:receipt[key] for key in ("status","distinct_named_checks","runs_per_check","failures","errors","skips","whole_generator_upgraded")}))
    return 0


if __name__=="__main__":raise SystemExit(main())
