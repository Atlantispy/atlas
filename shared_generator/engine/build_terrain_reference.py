"""Official bounded terrain reference entry; no Diadem production authority."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import types

PACKAGE=Path(__file__).with_name("terrain_reference_r2_repair_r1")
MAX_SOURCE_BYTES=16*1024*1024


def _workflow_source(path):
    """Read one regular, unlinked implementation file before executing it."""
    path=Path(path).absolute()
    for part in (path,*path.parents):
        info=part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:
            raise ValueError("linked terrain workflow source rejected")
    before=path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_SOURCE_BYTES:
        raise ValueError("bounded regular terrain workflow source required")
    def identity(info):
        return info.st_size,info.st_mtime_ns,info.st_ino,info.st_dev
    with path.open("rb") as stream:
        if identity(os.fstat(stream.fileno()))!=identity(before):
            raise ValueError("terrain workflow changed while opening")
        raw=stream.read(MAX_SOURCE_BYTES+1)
        after=identity(os.fstat(stream.fileno()))
    if len(raw)>MAX_SOURCE_BYTES or after!=identity(before) or identity(path.stat())!=after:
        raise ValueError("terrain workflow changed while reading")
    return raw


def load_workflow(package=PACKAGE):
    """Bind the successor workflow without using global import-name caches."""
    path=Path(package)/"workflow.py"
    raw=_workflow_source(path)
    module=types.ModuleType("_diadem_installed_terrain_reference_repair")
    module.__file__=str(path)
    exec(compile(raw,str(path),"exec"),module.__dict__)
    pins=module.verify_loaded_sources()
    own=[row for row in pins if row["name"]=="workflow.py"]
    expected={"name":"workflow.py","bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    if own!=[expected]:
        raise ValueError("terrain workflow executed bytes differ from its source identity")
    return module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe",type=Path,required=True)
    parser.add_argument("--expected-recipe-sha256",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args()
    workflow=load_workflow()
    if hashlib.sha256(workflow.read_bytes(args.recipe)).hexdigest()!=args.expected_recipe_sha256:
        raise ValueError("recipe changed since normal-workflow authorization")
    result=workflow.run(args.recipe,args.output,resume=args.resume,
                        expected_recipe_sha256=args.expected_recipe_sha256)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
