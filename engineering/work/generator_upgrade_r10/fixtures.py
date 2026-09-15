"""Pinned bounded validation fixture; never substitutes for fresh release parents."""
import hashlib
import json
from pathlib import Path
import stat

PATH=Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/outputs/generator-upgrade-r8/biomes-reference-01/n-worker-reference/full-result.json')
SHA256='19a0975d09d1571e68ed510421b085675753b64ddfba316c8e8e2d68662cb000'
SIZE=8055099
RECIPE_PATH=PATH.with_name('recipe.json')
RECIPE_SHA256='5c2e34ae5c25872bda1f5afb8e160ebf7f3da8390d940a4f4fa1f5f66b38fd32'


def raw():
    for path in (PATH,*PATH.parents):
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400: raise ValueError('linked fixture refused')
    if not PATH.is_file() or PATH.stat().st_size!=SIZE: raise ValueError('exact sealed fixture size required')
    value=PATH.read_bytes()
    if len(value)!=SIZE or hashlib.sha256(value).hexdigest()!=SHA256: raise ValueError('validation fixture changed; no silent repin')
    return value


def source_bindings():
    raw()
    for path in (RECIPE_PATH,*RECIPE_PATH.parents):
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400: raise ValueError('linked recipe fixture refused')
    if not RECIPE_PATH.is_file() or RECIPE_PATH.stat().st_size!=144206 or hashlib.sha256(RECIPE_PATH.read_bytes()).hexdigest()!=RECIPE_SHA256: raise ValueError('exact recipe validation fixture required; no repin')
    return [{'path':str(PATH),'sha256':SHA256,'role':'sealed R8 saved output used only for bounded regression fixtures; release separately reruns actual R9 and R8'},
        {'path':str(RECIPE_PATH),'sha256':RECIPE_SHA256,'role':'sealed R8 saved recipe used only by actual formed-column hydraulic regression/refinement fixture; no production forcing substitution'}]


def physical():
    return json.loads(raw())
