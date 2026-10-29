"""Compose the fixture-identity source and actual callers; no runtime admission."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
MAP_SHA='733ea3eea185c125c1ef30a2611a3327d6959c6ddf18964d23856c8ec28be30e'
PARENT={'path': 'tectonics/optimisation/workbench/plan31/final/width/build_candidate.py', 'sha256': 'b478279828fd7cc69f059197b345f92f9a0c5adebb45ee6c1c01dae756738f41'}

def require(value,message):
    if not value:raise ValueError(message)

def digest(raw):return hashlib.sha256(raw).hexdigest()

def contract(repo):
    path=Path(repo)/PARENT['path'];raw=path.read_bytes()
    require(digest(raw)==PARENT['sha256'],'width parent builder pin differs')
    spec=importlib.util.spec_from_file_location('_plan31_fixture_width',path)
    parent=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),parent.__dict__)
    baseline,utilities,_,_,applier=parent.contract(repo)
    raw=utilities.read_source(HERE,'SOURCE-MAP.json')
    require(digest(raw)==MAP_SHA,'fixture identity source map pin differs')
    mapping=utilities.read_map(raw)
    require(mapping['schema']=='atlas.public.plan31.fixture-identity.source-composition.r1'
        and mapping['base_builder']==PARENT and mapping['base_source_map_sha256']==parent.MAP_SHA
        and set(mapping['rows'])=={'src/atlas_tectonics/reuse.py','helpers/probe_execution_identity.py','helpers/run_prepared_restart.py'}
        and mapping['source_members']==697 and all(mapping[k] is False for k in ['private_public_identity_equal','runtime_admission','IV_permitted','scientific_acceptance','default_changed']),
        'closed fixture receiving contract differs')
    for name,pin in mapping['implementation_sources'].items():
        require(digest(utilities.read_source(HERE,name))==pin,'final implementation pin differs')
    payload={}
    for name,row in mapping['rows'].items():
        value=utilities.read_source(HERE,row['payload']);patch=utilities.read_source(HERE,row['diff'])
        require(digest(value)==row['after_sha256'] and digest(patch)==row['diff_sha256'],'fixture payload/diff pin differs')
        payload[name]=(value,patch)
    return parent,baseline,utilities,mapping,payload,applier

def materialise(repo,destination):
    repo,destination=Path(repo).absolute(),Path(destination).absolute()
    for root in [repo,HERE]:
        a,b=destination.resolve(),root.resolve()
        require(a!=b and not a.is_relative_to(b) and not b.is_relative_to(a),'output overlaps source')
    parent,baseline,utilities,mapping,payload,applier=contract(repo)
    utilities.inside(Path(destination.anchor),destination.relative_to(destination.anchor).as_posix())
    utilities.refuse_existing(destination)
    with tempfile.TemporaryDirectory(prefix='p31id-') as temporary:
        stage=Path(temporary)/'source';prior=parent.materialise(repo,stage)
        require(prior['source_map_sha256']==mapping['base_source_map_sha256'] and len(prior['files'])==697,'exact width predecessor differs')
        baseline.verify_inventory(stage,prior['files'],utilities)
        files=dict(prior['files']);changes={}
        for name,row in mapping['rows'].items():
            old=utilities.read_source(stage,name);value,patch=payload[name]
            require(files[name]==row['before_sha256'] and digest(old)==row['before_sha256']
                and applier.apply_diff(old,patch,name)==value,'same-base fixture derivation differs')
            files[name]=row['after_sha256'];changes[name]=dict(before=row['before_sha256'],after=row['after_sha256'])
        require(len({n.casefold() for n in files})==len(files),'case-insensitive output collision')
        for name in files:
            require(len(str(utilities.inside(destination,name)))+8<260,'final output exceeds MAX_PATH allowance')
        result=dict(prior,schema='atlas.public.plan31.fixture-identity.materialised-source.r1',
            parent_source_map_sha256=prior['source_map_sha256'],source_map_sha256=MAP_SHA,files=files,
            fixture_identity_receiving_changes=changes,fixture_identity_source_selected=True,
            private_public_identity_equal=False,selection_sha256=utilities.generation({'member':'source/'+n,'public_sha256':pin} for n,pin in files.items()))
        utilities.refuse_existing(destination);destination.mkdir(parents=True)
        for name,pin in files.items():
            target=utilities.inside(destination,name);target.parent.mkdir(parents=True,exist_ok=True)
            value=payload[name][0] if name in payload else utilities.read_source(stage,name)
            require(digest(value)==pin,'source changed before copy')
            with target.open('xb') as stream:stream.write(value)
        (destination/'SOURCE-MANIFEST.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        baseline.verify_inventory(destination,files,utilities)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',required=True,type=Path);parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();r=materialise(args.repo,args.out)
    print(json.dumps(dict(source_map_sha256=r['source_map_sha256'],selection_sha256=r['selection_sha256'],members=len(r['files']),runtime_admission=False,IV_permitted=False)))

if __name__=='__main__':main()
