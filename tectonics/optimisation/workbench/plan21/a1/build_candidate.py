"""Construct the exact A1/diagnostic/source-binding overlay in a NEW source tree."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile

PORT_SHA = 'ea700d55d1ec46c54261d7b708b04a0c0d1a38a1b38cce53001ac6e53075463a'
PARENT_MANIFEST_SHA = '79dd7890d882575fe1bc280eefb553f9b3f9f2371d748ff223514cc03ca557de'
FLAGS = ('runtime_admission','default_changed','scientific_acceptance','interval_authority','selected','enablement')
HERE = Path(__file__).resolve().parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def guarded(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if not part.exists():
            continue
        attributes = part.lstat()
        if stat.S_ISLNK(attributes.st_mode) or getattr(attributes,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0):
            raise ValueError('Linked source/destination path refused')
    return path


def inside(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(p in ('','..','.') or ':' in p or '\\' in p for p in relative.parts):
        raise ValueError('Invalid source member')
    path = guarded(root.joinpath(*relative.parts))
    if root not in path.parents:
        raise ValueError('Source member escaped root')
    return path


def contract():
    raw = (HERE/'PORT.json').read_bytes()
    if digest(raw) != PORT_SHA:
        raise ValueError('A1 overlay contract changed')
    data = json.loads(raw)
    if data.get('schema') != 'atlas.plan21.a1.source-overlay.r1' or any(data.get(k) is not False for k in FLAGS):
        raise ValueError('A1 authority contract differs')
    return data


def derive(parent):
    parent = guarded(parent)
    result = {}
    for row in contract()['rows']:
        name = row['path']
        if digest(inside(parent,name).read_bytes()) != row['base_sha256']:
            raise ValueError('A1 input source changed: '+name)
        raw = inside(HERE/'payloads',name).read_bytes()
        if digest(raw) != row['candidate_sha256']:
            raise ValueError('A1 output payload changed: '+name)
        result[name] = raw
    return result


def materialise(parent, destination, *, expected_parent_manifest_sha256=PARENT_MANIFEST_SHA):
    parent, destination = guarded(parent), guarded(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('A1 destination already exists')
    raw = inside(parent,'SOURCE-MANIFEST.json').read_bytes()
    if digest(raw) != expected_parent_manifest_sha256:
        raise ValueError('A1 parent manifest changed')
    manifest = json.loads(raw)
    if any(manifest.get(k) is not False for k in FLAGS) or not isinstance(manifest.get('files'),dict):
        raise ValueError('A1 parent authority/membership differs')
    files = dict(manifest['files'])
    data = {}
    for name,pin in files.items():
        content = inside(parent,name).read_bytes()
        if digest(content) != pin:
            raise ValueError('A1 parent member changed: '+name)
        data[name] = content
    outputs = derive(parent)
    if not set(outputs) <= set(files):
        raise ValueError('A1 overlay cannot change membership')
    data.update(outputs)
    files.update({name:digest(value) for name,value in outputs.items()})
    entries = sorted((dict(member='source/'+name,public_sha256=pin) for name,pin in files.items()),key=lambda e:e['member'])
    result = dict(schema='atlas.plan21.a1.materialised-source.r1',
        status='INTEGRATED_SOURCE_CANDIDATE_NOT_QUALIFIED',parent_manifest_sha256=digest(raw),
        parent_selection_sha256=manifest['selection_sha256'],source_map_sha256=PORT_SHA,
        selection_sha256=digest((json.dumps(entries,indent=2,ensure_ascii=True)+'\n').encode('utf8')),
        source_members=len(files),files=files,**dict.fromkeys(FLAGS,False))
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.a1-source-',dir=destination.parent) as temporary:
        stage=Path(temporary)/'source';stage.mkdir()
        for name,content in data.items():
            target=inside(stage,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
        (stage/'SOURCE-MANIFEST.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
        if destination.exists() or destination.is_symlink():
            raise ValueError('A1 destination became occupied')
        stage.rename(destination)
    return {k:v for k,v in result.items() if k!='files'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--parent-manifest-sha256',default=PARENT_MANIFEST_SHA)
    args=parser.parse_args()
    try:
        result=materialise(args.parent,args.output,expected_parent_manifest_sha256=args.parent_manifest_sha256)
    except (OSError,ValueError) as error:
        parser.exit(1,'A1 source construction refused: '+str(error)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
