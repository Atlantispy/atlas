"""IV1 replay: dump one adopted route (1) interval's proved records and head arrays, read-only.

Usage (the arm's interpreter, -B -s -P, never -I: it imports the runtime, which needs seed 0):
  PYTHONHASHSEED=0 python -B -s -P dump_arm.py --profile PROFILE --profile-sha256 HEX --interval 0|1 --out NEW_DIR
Refuses unless sys.flags.hash_randomization is 0 and no PYTHON* variable other than PYTHONHASHSEED=0 and
PYTHONDONTWRITEBYTECODE is set (the runner's interpreter gate is checked as well).

The arm's code comes from its profile: the native root and import roots go first on sys.path, as
RestartSources.selected() puts them. selected() itself is not used: its import fence refuses any unpinned
workspace file, and this tool is one. What the dump proves rests on byte identity instead: every dumped
record must have exactly the SHA-256 and length its independent reader proved under the full fence. After
the dump, the same rule as check_imported is applied to every loaded module (workspace .py files must be
pinned with the manifest sha256; atlas_tectonics must come from the native root), with one exception, this
file, whose sha256 is recorded. sources.verify() runs before and after. No admission and no workflow are
opened: the records are read by reference from the head snapshot.

Bindings (any failure refuses, and dump.json says FAILED):
- adopted-interval-000N.json: status ADOPTED_AFTER_INDEPENDENT_READER, its verdict_sha256 is the
  reader verdict file's sha256, its catalog digest is the opened catalog's, and its entry is the catalog head;
- the reader verdict has the PASS status of the mode, and its reopen_receipt_sha256 is the reader receipt's
  sha256; the receipt's record identities (and, at interval 1, the runner record's) are the targets;
- every dumped record's canonical bytes have exactly the target SHA-256 and length;
- the store change token is the same before and after.
Output: OUT/records/<kind>.json (canonical bytes), OUT/arrays/<n>.bin (raw little-endian array bytes;
name, dtype and shape in dump.json), OUT/dump.json. Exit 0 only if every check passed.
"""
import argparse
import gc
import json
import os
import sys
from hashlib import sha256
from pathlib import Path

SCHEMA = 'atlas.private.iv1-arm-dump.r1'
MODES = {0: 'root', 1: 'interval'}
ALLOWED_PYTHON_ENV = {'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': None}
RECORD_ARRAY = 'spatial-record:'


class DumpRefused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise DumpRefused(message)


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_stream(path, chunks):
    digest, size = sha256(), 0
    with open(path, 'xb') as stream:
        for chunk in chunks:
            view = memoryview(chunk).cast('B')
            digest.update(view)
            stream.write(view)
            size += view.nbytes
    return {'sha256': digest.hexdigest(), 'nbytes': size}


def bindings(F, row, interval, profile_sha256):
    """Adoption, verdict and receipt records of the interval, each bound to the next."""
    mode = MODES[interval]
    store_dir = Path(row['store_directory'])
    adopted_path = store_dir/F.record_name('adopted', interval)
    verdict_path = store_dir/F.record_name('reader-verdict', interval)
    runner_path = store_dir/F.record_name('runner-record', interval)
    receipt_path = Path(row['output_directory'])/('reader-'+mode)/'reopen.json'
    adopted = json.loads(adopted_path.read_bytes())
    verdict = json.loads(verdict_path.read_bytes())
    runner = json.loads(runner_path.read_bytes())
    receipt = json.loads(receipt_path.read_bytes())
    require(adopted.get('status') == 'ADOPTED_AFTER_INDEPENDENT_READER' and adopted.get('interval') == interval,
            'interval is not adopted after its independent reader')
    require(adopted.get('verdict_sha256') == file_sha(verdict_path), 'adoption names another reader verdict')
    require(verdict.get('status') == F.READER_PASS[mode] and verdict.get('interval') == interval,
            'reader verdict is not the PASS of this mode')
    require(verdict.get('reopen_receipt_sha256') == file_sha(receipt_path), 'verdict names another reader receipt')
    require(verdict.get('runner_record_sha256') == file_sha(runner_path), 'verdict names another runner record')
    require(receipt.get('mode') == mode and not receipt.get('errors') and
            receipt.get('profile_sha256') == profile_sha256,
            'reader receipt is not a clean read of the mode under this profile')
    key = 'root_record_identities' if mode == 'root' else 'record_identities'
    targets = receipt.get(key)
    require(type(targets) is dict and targets, 'reader receipt lacks its record identities')
    if mode == 'interval':
        require(runner.get('record_identities') == targets, 'runner and reader record identities differ')
    files = {name: {'path': str(path), 'sha256': file_sha(path)} for name, path in (
        ('adopted', adopted_path), ('verdict', verdict_path), ('runner_record', runner_path),
        ('reader_receipt', receipt_path))}
    return adopted, verdict, runner, targets, files


def roots_of(profile_path, profile_sha256):
    raw = Path(profile_path).read_bytes()
    require(sha256(raw).hexdigest() == profile_sha256, 'profile bytes differ from the given sha256')
    row = json.loads(raw)
    workspace = Path(row['workspace'])
    resolve = lambda p: Path(p) if Path(p).is_absolute() else workspace/p     # noqa: E731
    return resolve(row['native_root']).resolve(), [resolve(p).resolve() for p in row['import_roots']]


def loaded_audit(sources):
    """check_imported's rule over every loaded module, except this file (sha256 recorded)."""
    pins = json.loads(Path(sources.manifest_path).read_bytes())['files']
    own = Path(__file__).resolve()
    native = Path(sources.native_root)/'atlas_tectonics'
    workspace, env = Path(sources.workspace), Path(sources.workspace)/'.r44-env'
    checked = 0
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if name == 'atlas_tectonics' or name.startswith('atlas_tectonics.'):
            require(type(filename) is str and Path(filename).resolve().is_relative_to(native),
                    'native module outside the arm runtime: '+name)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path == own or not path.is_relative_to(workspace) or path.suffix != '.py' or path.is_relative_to(env):
            continue
        relative = path.relative_to(workspace).as_posix()
        require(pins.get(relative) == file_sha(path), 'unpinned module loaded: '+relative)
        checked += 1
    return {'pinned_modules_checked': checked, 'exempt': {'path': str(own), 'sha256': file_sha(own)}}


def dump(args, record):
    native_root, import_roots = roots_of(args.profile, args.profile_sha256)
    sys.path[:0] = [str(native_root), *(str(p) for p in import_roots)]
    import run_fresh_interval as F
    import run_prepared_restart as RUN
    profile = F.FreshProfile.read(args.profile, args.profile_sha256)
    sources = F.FreshSources(profile)
    require(Path(sources.native_root).resolve() == native_root and
            [Path(p).resolve() for p in sources.import_roots] == import_roots, 'profile roots differ')
    sources.check_paths()
    record['source_proof_before'] = sources.verify()
    row = profile.record()
    out = Path(args.out)
    (out/'records').mkdir()
    (out/'arrays').mkdir()
    adopted, verdict, runner, targets, files = bindings(F, row, args.interval, args.profile_sha256)
    record.update(bindings=files, widths=verdict.get('widths'), width_gate=verdict.get('width_gate'),
                  interpreter=RUN.interpreter_gate())
    import compact_restart_store as CRS
    import spatial_indexed_patch as SI
    import spatial_records_patch as SR
    import workflow_transfer as W
    from atlas_tectonics.resources import WorkBudget
    from compact_contracts import SegmentRef
    from compact_store import CompactMeshStoreV3
    budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    scope = RUN.new_retained_scope(budget)
    try:
        catalog = Path(row['store_directory'])/F.CATALOG
        store = CRS.CompactRestartStore.open_catalog(catalog, scope=scope)
        with store:
            require(store.readonly, 'the adopted catalog did not open read-only')
            F._store_configuration(store)
            head_entry = store.store_set.head
            require(store.store_set.catalog_digest == adopted['catalog_digest'] and
                    head_entry.interval == args.interval and
                    head_entry.file_sha256 == adopted['entry']['file_sha256'] == verdict['entry']['file_sha256'],
                    'opened catalog is not the adopted one, or its head is another interval')
            token = store.change_token()
            workflow_id = runner['workflow_id']
            root_key = W.workflow_key('root', workflow_id)
            key = root_key if args.interval == 0 else W.workflow_key('successor', root_key)
            head = store.metadata(key)
            require(type(head) is dict and head.get('key') == key and head.get('sequence') == args.interval and
                    head.get('kind') == MODES[args.interval].replace('interval', 'successor'),
                    'workflow head of the interval not found in the store')
            state = head['exterior_state']
            refs = dict(state['record_blobs'])
            if args.interval == 1:
                refs.update(head['exterior_advance']['record_blobs'])
                refs['certification'] = head['differential_certification']['record_blob']
                refs['differential'] = head['differential_geometry']['record_blob']
            found = {}
            if 'compact_mesh' in state:
                producer = state['compact_mesh']['source_producer']
                with SR.open_records(store, refs, budget=budget, scope=scope, source_producer=producer) as opened:
                    require(set(opened) == set(refs), 'compact record inventory differs from its references')
                    for name, child in sorted(opened.items()):
                        found[name] = write_stream(out/'records'/(name+'.json'), child.iter_json())
                        child.close()
                reference = state['compact_mesh']
                mesh = CompactMeshStoreV3(store, scope=scope).open(
                    SegmentRef.from_wire(reference['segment']), expected_geometry_id=state['thermal_mesh_id'])
                found['mesh'] = write_stream(out/'records'/'mesh.json', SI.iter_logical_json(mesh))
                del mesh
            else:
                require(args.interval == 0, 'a native successor has no compact records')
                for name, reference in sorted(refs.items()):
                    require(type(reference) is dict and set(reference) == {'array', 'bytes', 'sha256'} and
                            reference['array'] == RECORD_ARRAY+name, 'native root record reference differs')
                    chunks = (chunk for _, chunk in store.iter_chunks(key, reference['array'], budget=budget))
                    found[name] = write_stream(out/'records'/(name+'.json'), chunks)
                    require(found[name] == {'sha256': reference['sha256'], 'nbytes': reference['bytes']},
                            'native record bytes differ from their reference: '+name)
            record['records'] = found
            expected = {name: value for name, value in targets.items() if name != 'partition'}
            require(found == expected, 'dumped record bytes differ from the proved identities')
            record['partition'] = {'dumped': False, 'identity': targets.get('partition'),
                                   'reason': 'descriptor statistics only (the reader proves it the same way)'}
            arrays = []
            manifest = store._manifest(key)
            require(type(manifest) is dict, 'head manifest not found')
            plain = sorted((n, d) for n, d in manifest['arrays'].items() if not n.startswith(RECORD_ARRAY))
            for index, (name, desc) in enumerate(plain):
                chunks = (chunk for _, chunk in store.iter_chunks(key, name, budget=budget))
                written = write_stream(out/'arrays'/('%04d.bin' % index), chunks)
                arrays.append({'name': name, 'file': '%04d.bin' % index, 'dtype': str(desc['dtype']),
                               'shape': list(desc['shape']), **written})
            record['arrays'] = arrays
            require(store.change_token() == token, 'the dump changed the store')
            record['head'] = {'key': key, 'kind': head['kind'], 'sequence': head['sequence']}
        record['loaded_audit'] = loaded_audit(sources)
        record['source_proof'] = sources.verify()
        require(record['source_proof'] == record['source_proof_before'], 'sources changed during the dump')
    finally:
        gc.collect()
        scope.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--profile', required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--interval', type=int, choices=sorted(MODES), required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if not sys.dont_write_bytecode:
        raise SystemExit('run with -B to preserve frozen sources')
    if sys.flags.hash_randomization or sys.flags.ignore_environment or sys.flags.isolated:
        raise SystemExit('the runtime needs seed 0: run with PYTHONHASHSEED=0 and -B -s -P, never -I or -E')
    stray = {k: v for k, v in os.environ.items() if k.upper().startswith('PYTHON') and
             (k.upper() not in ALLOWED_PYTHON_ENV or ALLOWED_PYTHON_ENV[k.upper()] not in (None, v))}
    if stray:
        raise SystemExit('clean the environment first: '+', '.join(sorted(stray)))
    out = Path(args.out)
    out.mkdir(parents=False, exist_ok=False)
    record = {'schema': SCHEMA, 'status': 'STARTED', 'pid': os.getpid(), 'interval': args.interval,
              'profile': {'path': str(Path(args.profile).resolve()), 'sha256': args.profile_sha256},
              'errors': []}
    try:
        dump(args, record)
        record['status'] = 'PASS'
    except BaseException as error:  # noqa: BLE001 - every failure is recorded, then re-raised as the exit code
        record['status'] = 'FAILED'
        record['errors'].append({'type': type(error).__name__, 'message': str(error)})
    with open(out/'dump.json', 'x', encoding='utf8') as stream:
        json.dump(record, stream, indent=1, sort_keys=True, allow_nan=False)
    print(json.dumps({'status': record['status'], 'errors': record['errors'],
                      'records': {k: v['nbytes'] for k, v in record.get('records', {}).items()},
                      'arrays': len(record.get('arrays', []))}), flush=True)
    return 0 if record['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
