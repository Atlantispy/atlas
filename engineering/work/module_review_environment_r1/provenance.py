"""Fail-closed identities/attestations; these do not grant canon or approval."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_SHA = re.compile(r'^[0-9a-f]{64}$')


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def within(path, root):
    p,r=Path(path).resolve(),Path(root).resolve()
    if p==r or not p.is_relative_to(r):
        raise ValueError('target must be strictly inside the explicit output root')
    return p


def require_pass(record):
    if not isinstance(record, dict):
        raise ValueError('gate must be a record')
    status=record.get('status')
    if not isinstance(status,str) or not status.startswith('PASS') or any(s in status for s in ('FAIL','PENDING','UNKNOWN')):
        raise ValueError('gate is not an unambiguous PASS')
    if 'pass' in record and record['pass'] is not True:
        raise ValueError('gate pass field conflicts with status')
    checks=record.get('checks',record.get('gates'))
    if checks is not None and (not isinstance(checks,dict) or not checks or any(v is not True for v in checks.values())):
        raise ValueError('gate has missing, nonboolean or failed checks')
    return record


def validate_hashes(records, root=None):
    if not isinstance(records, dict) or not records:
        raise ValueError('nonempty exact artifact identity map required')
    for name, expected in records.items():
        if not isinstance(expected,str) or not _SHA.fullmatch(expected):
            raise ValueError('invalid SHA-256')
        path=within(Path(root)/name,root) if root is not None else Path(name).resolve()
        if not path.is_file() or sha256(path)!=expected:
            raise ValueError(f'artifact identity mismatch: {name}')
    return records


def visual_adjudication(annual_audit, attestation=None, root=None):
    """Only an explicit hash-bound record can adjudicate the one soft watch.

    This validates identity/content, not the reviewer's real-world identity.
    An absent attestation never becomes a visual PASS, even on machine PASS.
    """
    missing={'status':'NOT_SUPPLIED','pass':False,'finding':None}
    if attestation is None:
        return missing
    require_pass(attestation)
    for key in ('reviewer','reviewed_utc','finding'):
        if not isinstance(attestation.get(key),str) or not attestation[key].strip():
            raise ValueError(f'visual attestation requires {key}')
    if attestation.get('integrity')!=annual_audit.get('integrity'):
        raise ValueError('visual review is not bound to this exact artifact set')
    validate_hashes(attestation['integrity'],root)
    failures=sorted(k for k,v in annual_audit['gates'].items() if v is not True)
    allowed=['no_new_southwest_planar_front_numeric']
    if failures not in ([],allowed) or attestation.get('adjudicated_gates',[])!=failures:
        raise ValueError('visual review may not override other scientific failures')
    return dict(attestation)


def parent_snapshots(before, after, timestamp):
    changes=[]
    for record in (before,after):
        if record.get('status')!='PASS':
            changes.append({'reason':'snapshot_not_pass'})
    def keyed(record):
        rows=record.get('records',[])
        result={r['path']:r for r in rows}
        if not rows or len(result)!=len(rows):
            raise ValueError('empty or duplicate source identities')
        for row in rows:
            if not _SHA.fullmatch(str(row.get('actual_sha256',''))):
                raise ValueError('all parents require actual content hashes; no size-only fallback')
            if row.get('hash_matches_expected') is not True:
                raise ValueError('parent identity was not verified against its bound source')
        return result
    a,b=keyed(before),keyed(after)
    for path in sorted(set(a)|set(b)):
        if path not in a or path not in b:
            changes.append({'path':path,'reason':'missing_from_one_snapshot'}); continue
        for key in ('bytes','actual_sha256','expected_sha256'):
            if a[path].get(key)!=b[path].get(key):
                changes.append({'path':path,'reason':key})
    return {'schema_version':'environment-parent-content-identity-r1','created_utc':timestamp,
            'status':'FAIL' if changes else 'PASS','changes':changes,
            'comparison_basis':'Exact parent path set, SHA-256 and byte count; timestamp changes alone are not content changes'}


def fresh_manifest(out, name='MANIFEST.json'):
    root=Path(out).resolve()
    if not root.is_dir():
        raise ValueError('output directory missing')
    entries=[]
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.relative_to(root).as_posix() not in (name,'SHA256SUMS.txt'):
            within(p,root)
            entries.append({'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p)})
    return {'schema':'environment-successor-final-manifest-r1','status':'REVIEW_ONLY_NOT_CANON','files':entries}


def finish_manifest(out):
    manifest=fresh_manifest(out)
    (Path(out)/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest


def require_fresh_manifest(out, manifest):
    if manifest.get('files')!=fresh_manifest(out)['files']:
        raise ValueError('manifest does not bind the current complete payload')


def verify_role_lock(lock, paths, root):
    records=lock.get('records',lock.get('sources'))
    if not isinstance(records,list) or len(records)!=len(paths):
        raise ValueError('source lock does not contain exactly the required roles')
    by_role={r['role']:r for r in records}
    if set(by_role)!=set(paths) or len(by_role)!=len(records):
        raise ValueError('source roles are missing or duplicated')
    for role,path in paths.items():
        p=Path(path).resolve(); row=by_role[role]
        if (Path(root)/row['path']).resolve()!=p or p.stat().st_size!=row['bytes'] or sha256(p)!=row['sha256']:
            raise ValueError(f'actual bound source differs from lock: {role}')
    return True


def require_prepared_identities(payload, inputs, resolve):
    records=payload.get('parent_inputs')
    if not isinstance(records,dict) or set(records)!=set(inputs):
        raise ValueError('prepared input roles differ from actual producer inputs')
    for role,path in inputs.items():
        record=records[role]
        if Path(resolve(record['path'])).resolve()!=Path(path).resolve() or sha256(path)!=record['sha256']:
            raise ValueError(f'parent changed after pipeline preparation: {role}')
    return inputs


def array_digest(arrays):
    import numpy as np
    digest=hashlib.sha256()
    for array in arrays:
        a=np.ascontiguousarray(array)
        digest.update(json.dumps([a.shape,a.dtype.str],separators=(',',':')).encode())
        digest.update(a.tobytes())
    return digest.hexdigest()


def forcing_tile_digest(land_grid,patch,p_grid,pet_grid,target_index,row0,row1,col0,col1):
    import numpy as np
    index=np.asarray(target_index)
    cols=p_grid.shape[-1]
    rr,cc=index//cols,index%cols
    positions=np.flatnonzero((rr>=row0)&(rr<row1)&(cc>=col0)&(cc<col1))
    return array_digest((land_grid[...,row0:row1,col0:col1],patch[...,positions],
                         p_grid[...,row0:row1,col0:col1],pet_grid[...,row0:row1,col0:col1],index[positions]))


def forcing_completed_state(state,frame,tile):
    expected={f'r{r:04d}c{c:04d}' for r in range(0,frame[0],tile) for c in range(0,frame[1],tile)}
    completed=state.get('completed_tile_keys',[]);rows=state.get('tiles',[])
    if len(set(completed))!=len(completed) or len({r['key'] for r in rows})!=len(rows):
        raise ValueError('duplicate checkpoint tile identities')
    if set(completed)!={r['key'] for r in rows} or not set(completed)<=expected:
        raise ValueError('checkpoint catalogue does not match the exact output tiling')
    if any(not _SHA.fullmatch(str(r.get('payload_sha256',''))) for r in rows):
        raise ValueError('legacy/unhashed checkpoint cannot establish current payload integrity')
    return {r['key']:r for r in rows}


def package_payload_identity(root,exclude=()):
    excluded=set(exclude)|{'MANIFEST.json','SHA256SUMS.txt'}
    return {r['path']:r['sha256'] for r in fresh_manifest(root)['files'] if r['path'] not in excluded}


def require_payload_release(root,machine,visual,exclude=()):
    require_pass(machine);require_pass(visual)
    actual=package_payload_identity(root,exclude)
    if not actual:
        raise ValueError('empty package payload cannot be reviewed')
    for name,record in (('machine',machine),('visual',visual)):
        if record.get('bound_payload')!=actual:
            raise ValueError(f'{name} review is not bound to every current package payload member')
        if not isinstance(record.get('reviewer'),str) or not record['reviewer'].strip():
            raise ValueError(f'{name} attestation must name the reviewer/validator')
        if not isinstance(record.get('reviewed_utc'),str) or not record['reviewed_utc'].strip():
            raise ValueError(f'{name} attestation must state its review time')
    return True
