"""Read-only exact retained HS1--20 roster and scientific-source closure.

No biological defaults, raster execution, occurrence inference or approval.
Manifest-declared large rasters/archives remain distinct from live-checked code
and small control metadata. This standalone provider imports only stdlib.
"""
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import stat

OLD = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted')
CURRENT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
REGISTRY = CURRENT/'work/module_review_ecology_r1/SOURCE_PINS.json'
REGISTRY_SHA256 = '498d8dc0c4c2037cc61eb915babf0148aceec220ee771488b9fbbc2fb136f12f'
CROSSWALK = OLD/'work/species_habitat/overlap_atlas/HS1_HS20_FROZEN_CROSSWALK.json'
CROSSWALK_SHA256 = 'aa23f708eab53a7a2b4524b62117b4c9338977cd8f5717bf6e98b83f94b5a641'
MAX_SOURCE_BYTES = 8*1024*1024
EXCEPTIONS = {14:'NONSPATIAL_EVENT_DRIVEN_WORLDWIDE_OCCURRENCE_NOT_GENERATED',
              19:'CANONICALLY_ABSENT_WILD_POPULATION_COUNTERFACTUAL_SEPARATE'}
EXTRA = (
 ('framework/README.md','eba873ccbb8b91dd0d1957d74a2edfdf7a1cbb77645f3732c82bded28b07595f'),
 ('framework/per_species_atlas_schema.json','c6e3eae3150e772a592f3f69417b461023ae4842a7aad31c618ef290bf57e8af'),
 ('framework/PRIMARY_SPECIES_ATLAS_VISUAL_SCIENCE_REVIEW_CONTRACT.md','b78e9a96bbfc7009851551ceeee37715d653492e1c608a32828f1e317b5e716a'))
CORRECTED = (
 ('runtime.py','fbedf5d183263a18f58dac5dafafd8f7df2085c2cc10e7e7522baeece3a8fffe'),
 ('science.py','994c727bdf5531203bbe554ca78496ca1995cd2047c7c315f72ce0c350a06921'),
 ('overlap.py','085d3e94f2ae06316dc897ed68657fd6ff970bd84e506df400b3ba6e72a9fecf'),
 ('apply_stage6d_species_ecology_overlay.py','e42ebce8d3416c7b6e8f88093035cd43de59d9d1954b61a13130caee413af985'),
 ('run_overlay.py','7f09e996ba17c5dd6b9f0247dbfa39e5889b6592064daeb24cecdf2a05fe30d5'))


def _checked(path, expected):
    path=Path(path)
    if not path.is_absolute():raise ValueError('absolute source path required')
    if type(expected) is not str or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise ValueError('exact SHA-256 required')
    for item in (path,*path.parents):
        info=item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('linked/reparse source prohibited')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_SOURCE_BYTES:raise ValueError('bounded singly-linked source required')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('source pin mismatch: '+str(path))
    return raw


def _json(raw):
    def pairs(items):
        value={}
        for k,v in items:
            if k in value:raise ValueError('duplicate JSON key')
            value[k]=v
        return value
    result=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    def finite(node):
        if isinstance(node,float) and not math.isfinite(node):raise ValueError('nonfinite JSON')
        if isinstance(node,dict):
            for v in node.values():finite(v)
        elif isinstance(node,list):
            for v in node:finite(v)
    finite(result);return result


def _relative(value):
    if type(value) is not str or not value or '\\' in value:raise ValueError('plain relative POSIX member required')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or ':' in value or str(p)!=value:raise ValueError('unsafe source member')
    return p


def _root_records():
    registry=_json(_checked(REGISTRY,REGISTRY_SHA256))
    crosswalk=_json(_checked(CROSSWALK,CROSSWALK_SHA256))
    if registry.get('schema')!='diadem.ecology.r1.source-pins.v1' or set(registry['species'])!={str(i) for i in range(1,21)}:raise ValueError('exact retained producer registry required')
    rows=crosswalk.get('species')
    if crosswalk.get('schema')!='diadem-hs1-hs20-frozen-overlap-crosswalk-1.0' or type(rows) is not list or len(rows)!=20 or {r['hs'] for r in rows}!=set(range(1,21)):raise ValueError('exact retained HS1--HS20 crosswalk required')
    return registry,crosswalk


def _package(row):
    directory=OLD/str(_relative(row['package']))
    path=directory/'MANIFEST.json'
    manifest=_json(_checked(path,row['source_manifest_sha256']))
    members={}
    for record in manifest['files']:
        rel=str(_relative(record['path']))
        if rel in members:raise ValueError('duplicate package member')
        if type(record['bytes']) is not int or record['bytes']<0:raise ValueError('package member size required')
        members[rel]=record
    return directory,path,manifest,members


def _contract_records(entry):
    """Explicit config-declared biology/review references, not physical rasters."""
    if entry['config'] is None:return []
    config=_json(_checked(entry['config']['path'],entry['config']['sha256']));rows=[]
    def collect(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:
                rows.append({'path':str(OLD/str(_relative(value['path']))),'sha256':value['sha256']})
            else:
                for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    for key in ('contracts_and_canon','frozen_contracts','canon_bindings','governance_bindings','requirements_record'):
        if key in config:collect(config[key])
    if isinstance(config.get('requirements_record'),str):
        rows.append({'path':str(OLD/str(_relative(config['requirements_record']))),'sha256':config['requirements_record_sha256']})
    return rows


def source_bindings():
    """Live-checkable code/control pins, transitively expanded from pinned JSON.

    No live hash is promoted into a new expected pin. Expectations originate in
    fixed constants, the exact frozen registry/crosswalk and sealed manifests.
    This intentionally excludes large raster/archive bytes and image audits.
    """
    registry,crosswalk=_root_records();result={}
    def add(path,sha,role):
        path=str(Path(path).absolute())
        if path in result:
            if result[path]['sha256']!=sha:raise ValueError('conflicting source pins')
            return
        result[path]={'path':path,'sha256':sha,'role':role}
    add(REGISTRY,REGISTRY_SHA256,'retained corrected-ecology source registry; not species authority')
    add(CROSSWALK,CROSSWALK_SHA256,'frozen exact 20-case roles, bands, exceptions and declared package lineage')
    for hs,entry in registry['species'].items():
        for kind,record in entry.items():
            if record is not None:add(record['path'],record['sha256'],'HS'+hs+' retained '+kind+'; reference review only, not executed by R9')
        for record in _contract_records(entry):
            add(record['path'],record['sha256'],'historical config-declared biological/requirements/source-control reference; byte identity, not renewed current canon approval')
    for name,record in registry['dependencies'].items():
        add(record['path'],record['sha256'],'retained direct helper/source gate '+name+'; reference review only')
    for rel,sha in EXTRA:add(OLD/'work/species_habitat'/rel,sha,'retained habitat framework semantic/review contract')
    for rel,sha in CORRECTED:add(CURRENT/'work/module_review_ecology_r1'/rel,sha,'implemented corrected ecology scientific adapter; preserved, not re-executed by roster')
    for row in crosswalk['species']:
        directory,path,manifest,members=_package(row)
        add(path,row['source_manifest_sha256'],'HS'+str(row['hs'])+' exact retained package manifest, not approval revalidation')
        for rel,record in members.items():
            p=PurePosixPath(rel)
            if p.suffix.lower() in ('.py','.json','.md') and p.parts[0] not in ('audit','review','phone'):
                add(directory/rel,record['sha256'],'HS'+str(row['hs'])+' packaged scientific code/parameter/semantic metadata '+rel)
        for required in ('README.md',str(_relative(row['semantics'])).removeprefix(row['package']+'/')):
            if required not in members or str(directory/required) not in result:raise ValueError('required package semantics not bound')
    if len(result)>512:raise ValueError('bounded retained source inventory exceeded')
    return sorted(result.values(),key=lambda row:row['path'])


def verify_sources():
    rows=source_bindings()
    for row in rows:_checked(row['path'],row['sha256'])
    return {'schema':'diadem.r9.retained-source-check','status':'CODE_AND_CONTROL_BYTES_VERIFIED_REFERENCE_ONLY',
            'source_count':len(rows),'sources':rows,'large_rasters_archives_rehashed':False,
            'historical_package_approval_revalidated':False,'production_executed':False}


def retained_roster():
    """Exact retained 20-case support roster, not the complete R9 organism list."""
    checked=verify_sources();registry,crosswalk=_root_records();rows=[]
    for row in sorted(crosswalk['species'],key=lambda v:v['hs']):
        directory,path,manifest,members=_package(row)
        sem_path=OLD/str(_relative(row['semantics']))
        rel=sem_path.relative_to(directory).as_posix()
        semantics=_json(_checked(sem_path,members[rel]['sha256']))
        selected={k:copy.deepcopy(v) for k,v in semantics.items() if k in ('semantics','not_produced','movement_semantics','present_day_breeding_definition') or any(word in k.lower() for word in ('withheld','occurrence','range','population','abundance','carrying','species','support_semantic','not_canon','status'))}
        rows.append({'hs':row['hs'],'species':row['species'],'producer':copy.deepcopy(registry['species'][str(row['hs'])]),
            'declared_contract_bindings':_contract_records(registry['species'][str(row['hs'])]),
            'package_manifest':{'path':str(path),'sha256':row['source_manifest_sha256'],'declared_status':manifest.get('status')},
            'semantics':{'path':str(sem_path),'sha256':members[rel]['sha256'],'retained_statements':selected},
            'coequal_families':['A','B','C'],'family_binding_meaning':'coequal sensitivity bindings; invariant components may intentionally use one shared band, not fabricated variants',
            'support_meaning':'relative support, not occurrence probability, density or an actual route',
            'required_natural_lifecycle_core':copy.deepcopy(row['required_natural_lifecycle_core']),
            'components':copy.deepcopy(row['components']),
            'eligibility_contract':copy.deepcopy(row.get('eligibility_contract')),
            'exception':EXCEPTIONS.get(row['hs']),
            'declared_withheld_products':copy.deepcopy(row.get('unknown_or_withheld',row.get('withheld_products',[]))),
            'declared_principal_raster':row['continuous_raster'],
            'large_raster_reverified':False,'package_approval_revalidated':False})
    return {'schema':'diadem.r9.retained-habitat-roster','status':'REFERENCE_ONLY_NOT_OCCURRENCE_OR_ABUNDANCE',
        'source_count':checked['source_count'],'organisms':rows,
        'ordinary_headline_core_hs':[i for i in range(1,21) if i not in EXCEPTIONS],
        'complete_plant_or_R9_roster_established':False,'new_biological_parameters_supplied':False}
