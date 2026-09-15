"""Exact-source preservation and current physical-interface bindings."""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
TASK=HERE.parents[1]
SEALS=(
 ('outputs/module-review-2026-09-10/FINAL_VERIFICATION.json','6181ff1ced0e8fe7c6a96240bb702f38c55fbda2cfaccabe0c892336eda32b48','candidate_source_snapshot'),
 ('outputs/generator-upgrade-r1/integrated-reference-01/VERIFICATION.json','5f34947fcd9d87c62461ef86862af4e05e5d2cf879be3eb1f226ff8f98b5b5d5','source_snapshot'),
 ('outputs/generator-upgrade-r2/integrated-reference-02/VERIFICATION.json','bbaf37fddfce682cbf52705efa43510705e359299b540bab10a86d9bdd663650','source_snapshot'))
W=Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace')
INTERFACES={
 str(W/'02_Working_Files/Geography/Generator_Terrain_Requirements/Water_Interface_R1/Water_Terrain_Design_Contract_R1.md'):
 'f2443fbcf4532d227a8aa29c21d2d9ce39c3f44d809550498f2baa904439dc41',
 str(W/'02_Working_Files/Geography/Climate_Biomes_Soils/Generator_Terrain_Interface/R1/CLIMATE_SOIL_TERRAIN_INTERFACE_R1.md'):
 'b4e1a43cf9f3e98f122b00751720a6cadf85821cbb72ae1930cca19f7cf5a9e0'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    # Only scoped candidate and explicitly pinned predecessor maps, never a
    # full-workspace scan or a new audit of every historical implementation.
    current={str(p):sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
             and p.suffix in {'.py','.json','.md'}}
    predecessors=[];protected={};catalogues={}
    for name,expected,key in SEALS:
        path=TASK/name
        if sha(path)!=expected:raise ValueError('predecessor seal changed; no silent repin')
        record=json.loads(path.read_text(encoding='utf-8'))
        if 'predecessor_readback' in record:
            for name,h in record['predecessor_readback'].get('catalogue_pins',{}).items():
                target=str(TASK/'work/generator_capabilities_r1'/name)
                if target in catalogues and catalogues[target]!=h:raise ValueError('conflicting retained category contracts')
                if sha(target)!=h:raise ValueError('retained category contract changed')
                catalogues[target]=h
        for p,h in record[key].items():
            if p in protected and protected[p]!=h:raise ValueError('conflicting predecessor identities')
            if sha(p)!=h:raise ValueError('protected source changed: '+p)
            protected[p]=h
        predecessors.append({'path':str(path),'sha256':expected,'source_files':len(record[key]),'tests_rerun':False})
    for p,h in INTERFACES.items():
        if sha(p)!=h:raise ValueError('physical interface changed; no silent repin')
    from work.generator_upgrade_r2.bindings import owner_bindings
    owners=owner_bindings()
    # The actual finite-column operator freshly executes these separately pinned
    # foundation files. They are not part of the previous161-file tranche maps;
    # record their already-retained pins without inflating that preservation count.
    from .deps import landscape
    dependencies={str(landscape.FOUNDATION/name):expected for name,expected in landscape.FOUNDATION_PINS.items()}
    for p,h in dependencies.items():
        if sha(p)!=h:raise ValueError('executed foundation dependency changed; no silent repin')
    import numpy,scipy,platform
    identity={'r3_sources':current,'predecessors':predecessors,'protected_sources':protected,
        'physical_interfaces':INTERFACES,'category_contracts':catalogues,'owner_bindings':owners,
        'executed_dependency_sources':dependencies,
        'runtime':{'python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__}}
    return identity,hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
