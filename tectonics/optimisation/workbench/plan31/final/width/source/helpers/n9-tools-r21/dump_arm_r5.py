"""IV1 replay: dump one adopted route (1) interval's proved records and head arrays, read-only.

Usage (the arm's interpreter, -B -s -P, never -I: it imports the runtime, which needs seed 0):
  PYTHONHASHSEED=0 python -B -s -P dump_arm.py --profile PROFILE --profile-sha256 HEX --interval 0|1 --out NEW_DIR --observer-path SCRIPT --observer-sha256 HEX
Refuses unless sys.flags.hash_randomization is 0 and no PYTHON* variable other than PYTHONHASHSEED=0 and
PYTHONDONTWRITEBYTECODE is set (the runner's interpreter gate is checked as well).

The arm's code comes from its pinned profile and manifest. The observer's exact resolved
entry path and SHA must be supplied independently. Its import fence covers the bootstrap
and store reader, compiles pinned source bytes, rejects data-only imports and enforces first
resolution. Existing environment exclusions are retained. FreshSources checks paths and
the complete source inventory before and after the read-only extraction.
This draft remains disabled until the remaining proof-binding repairs and review pass.

r3 predecessor (successor of dump_arm_r2 7b893a72, Plan 04 step 2) adds the producer-receipt and stage-record
bindings, emits the read-only store change tokens before and after extraction, and records the
interpreter/environment observations. The fence, record and array extraction are r2's, unchanged.
The comparator re-derives every binding below from the proof files; these are the observer's own checks.

Bindings (any failure refuses, and dump.json says FAILED):
- adopted-interval-000N.json: status ADOPTED_AFTER_INDEPENDENT_READER with no review approval, its
  verdict_sha256 and runner_record_sha256 are those files' sha256, its catalog_sha256 is the catalog file's,
  its catalog digest is the opened catalog's, and its entry is the catalog head;
- the reader verdict has the PASS status of the mode, and its reopen_receipt_sha256, producer_receipt_sha256
  and runner_record_sha256 are those files' sha256; the reader receipt names the same producer receipt;
- the producer receipt run-<mode>/run.json is a clean seal of this mode under this profile, naming the runner record;
- stage-<mode>.json is ADOPTED (or the interval width-gate stop), with the runner, reader, finalise and adopt
  steps naming exactly these receipts, verdict and adoption;
- the reader receipt's record identities (and, at interval 1, the runner record's) are the targets;
- every dumped record's canonical bytes have exactly the target SHA-256 and length;
- the store change token is the same before and after (both emitted).
r5 retains independently root-bound full metadata in head.root_metadata and records the post-fence
environment only after restoring the import path. Its added proof consumer is array_bindings_r5.py.
r4 adds each plain array's closed manifest descriptor and its digest, plus the store chunk_bytes.
Descriptor evidence alone does not establish reader binding. This public export keeps
EXTRACTION_READY False, as the publication check requires; the staged private successor sets it True.
Root routes: compact records are read from their owned-block streams (r2 passed the
block stream itself to the writer, which refuses on any compact store); a root whose differential
partition is a v2 segment reference is dumped to records/partition.json, reopened through
partition_store.open_partition_v2 and bound to its header by partition_workflow_patch.compact_header;
dump.json names every decoder module (workspace path and pinned sha256) after the reads.
Output: OUT/records/<kind>.json (canonical bytes), OUT/arrays/<n>.bin (raw little-endian array bytes;
name, dtype and shape in dump.json), OUT/dump.json. Exit 0 only if every check passed.
"""
import argparse
import gc
import importlib.abc
import importlib.machinery
import json
import os
import sys
from hashlib import sha256
from pathlib import Path

SCHEMA = 'atlas.private.iv1-arm-dump.r5-draft'
# Released for the condition-4 replay (owner clearance); dump() refuses while this is False.
EXTRACTION_READY = False
_ENTRY_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
MODES = {0: 'root', 1: 'interval'}
ALLOWED_PYTHON_ENV = {'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': None}
RECORD_ARRAY = 'spatial-record:'
# Root-route condition (b): the modules the compact record, v3 mesh, v2 partition and native
# record reads below execute (profiled on the selected base's own producer stores). Each is imported
# through the fence; dump.json names its workspace path and pinned sha256, and the comparator refuses
# any other module set, path or digest (array_bindings_r5.DECODER_PATHS).
DECODER_MODULES = (
    'compact_contracts', 'compact_restart_store', 'compact_store', 'content_cache', 'interval_catalog',
    'interval_store_set', 'mesh_tables', 'native_transfer', 'partition_native_patch', 'partition_store',
    'partition_tables', 'partition_v2', 'partition_workflow_patch', 'record_tables', 'record_views',
    'segment_store', 'spatial_indexed_patch', 'spatial_record_recipes', 'spatial_records_patch',
    'spatial_workflow_patch', 'support_source', 'atlas_tectonics.integration_spatial_transport',
    'atlas_tectonics.resources', 'atlas_tectonics.storage')
SEGMENT_REF_SCHEMA = 'atlas.segment-ref.v1'       # compact_contracts.SEGMENT_REF_SCHEMA
PARTITION_ROUTE = 'compact-partition-v2'
STAGE_ADOPTED = ('ADOPTED', 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2')
STAGE_STEPS = ('runner', 'reader', 'finalise', 'adopt')


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
    """Adoption, verdict, receipt and stage records of the interval, each bound to the next."""
    mode = MODES[interval]
    store_dir, attempt = Path(row['store_directory']), Path(row['output_directory'])
    adopted_path = store_dir/F.record_name('adopted', interval)
    verdict_path = store_dir/F.record_name('reader-verdict', interval)
    runner_path = store_dir/F.record_name('runner-record', interval)
    receipt_path = attempt/('reader-'+mode)/'reopen.json'
    producer_path = attempt/('run-'+mode)/'run.json'
    stage_path = attempt/('stage-'+mode+'.json')
    catalog_path = store_dir/F.CATALOG
    paths = (('adopted', adopted_path), ('verdict', verdict_path), ('runner_record', runner_path),
             ('reader_receipt', receipt_path), ('producer_receipt', producer_path), ('stage_record', stage_path),
             ('catalog', catalog_path))
    raw = {name: path.read_bytes() for name, path in paths}
    pins = {name: sha256(value).hexdigest() for name, value in raw.items()}
    adopted, verdict, runner, receipt, producer, stage = (json.loads(raw[name]) for name in (
        'adopted', 'verdict', 'runner_record', 'reader_receipt', 'producer_receipt', 'stage_record'))
    require(adopted.get('status') == 'ADOPTED_AFTER_INDEPENDENT_READER' and adopted.get('interval') == interval,
            'interval is not adopted after its independent reader')
    require('review_approval_sha256' not in adopted, 'a review-approved adoption is not a replay arm')
    require(adopted.get('verdict_sha256') == pins['verdict'], 'adoption names another reader verdict')
    require(adopted.get('runner_record_sha256') == pins['runner_record'], 'adoption names another runner record')
    require(adopted.get('catalog_sha256') == pins['catalog'], 'catalog file differs from the adopted one')
    require(verdict.get('status') == F.READER_PASS[mode] and verdict.get('interval') == interval and
            not verdict.get('review_only'), 'reader verdict is not the PASS of this mode')
    require(verdict.get('reopen_receipt_sha256') == pins['reader_receipt'], 'verdict names another reader receipt')
    require(verdict.get('runner_record_sha256') == pins['runner_record'], 'verdict names another runner record')
    require(verdict.get('producer_receipt_sha256') == pins['producer_receipt'] ==
            receipt.get('producer_receipt_sha256'), 'verdict or reader names another producer receipt')
    require(receipt.get('mode') == mode and not receipt.get('errors') and not receipt.get('review_only') and
            receipt.get('profile_sha256') == profile_sha256,
            'reader receipt is not a clean read of the mode under this profile')
    require(producer.get('mode') == mode and producer.get('status') == F.SEALED_STATUS[mode] and
            not producer.get('errors') and producer.get('profile_sha256') == profile_sha256 and
            type(producer.get('runner_record')) is dict and set(producer['runner_record']) == {'path', 'sha256'} and
            Path(producer['runner_record']['path']).resolve() == runner_path.resolve() and
            producer['runner_record']['sha256'] == pins['runner_record'],
            'producer receipt is not a clean seal of this mode naming the runner record')
    steps = stage.get('steps')
    require(type(steps) is list and [s.get('name') for s in steps if type(s) is dict] == list(STAGE_STEPS) and
            all(s.get('ok') is True for s in steps), 'stage record lacks exactly one clean step of each kind')
    named = {s['name']: s for s in steps}
    require(stage.get('status') in (STAGE_ADOPTED if mode == 'interval' else STAGE_ADOPTED[:1]) and
            named['runner'].get('receipt_sha256') == pins['producer_receipt'] and
            named['reader'].get('receipt_sha256') == pins['reader_receipt'] and
            named['finalise'].get('verdict_sha256') == pins['verdict'] and
            named['adopt'].get('adopted_sha256') == pins['adopted'],
            'stage record does not name exactly these receipts, verdict and adoption')
    key = 'root_record_identities' if mode == 'root' else 'record_identities'
    targets = receipt.get(key)
    require(type(targets) is dict and targets, 'reader receipt lacks its record identities')
    if mode == 'interval':
        require(runner.get('record_identities') == targets, 'runner and reader record identities differ')
    files = {name: {'path': str(path), 'sha256': pins[name], 'nbytes': len(raw[name])} for name, path in paths}
    # Every bound file is re-hashed once more at the end: a file replaced during extraction refuses.
    return adopted, verdict, runner, targets, files


def recheck(files):
    for name, value in files.items():
        require(file_sha(value['path']) == value['sha256'], 'bound file changed during the dump: '+name)


def token_wire(token):
    """The store change token as exact JSON: tuples become lists; only str/int/bool/None leaves."""
    if type(token) in (tuple, list):
        return [token_wire(item) for item in token]
    require(token is None or type(token) in (str, int, bool), 'store change token has an inexact leaf')
    return token


def environment():
    """Interpreter and environment observations; only PYTHON* variables, which main() already restricted."""
    flags = {name: getattr(sys.flags, name) for name in dir(sys.flags)
             if not name.startswith('_') and type(getattr(sys.flags, name)) in (int, bool)}
    executable = Path(sys.executable).resolve()
    return {'executable': str(executable), 'executable_sha256': file_sha(executable),
            'version': sys.version, 'version_info': list(sys.version_info[:3]),
            'implementation': sys.implementation.name, 'cache_tag': sys.implementation.cache_tag,
            'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'platform': sys.platform,
            'byteorder': sys.byteorder, 'flags': flags, 'dont_write_bytecode': sys.dont_write_bytecode,
            'argv': list(sys.argv), 'cwd': os.getcwd(), 'path_at_start': list(sys.path),
            'python_environment': {k: v for k, v in sorted(os.environ.items()) if k.upper().startswith('PYTHON')}}


def roots_of(profile_path, profile_sha256):
    raw = Path(profile_path).read_bytes()
    require(sha256(raw).hexdigest() == profile_sha256, 'profile bytes differ from the given sha256')
    row = json.loads(raw)
    workspace = Path(row['workspace'])
    resolve = lambda p: Path(p) if Path(p).is_absolute() else workspace/p     # noqa: E731
    return resolve(row['native_root']).resolve(), [resolve(p).resolve() for p in row['import_roots']]


class ObserverFence:
    """Pinned-source import fence, including bootstrap, with one exact main-file exemption.

    The complete source inventory is still verified by FreshSources before and
    after reading the store. This fence verifies the actual bytes compiled for
    workspace imports, and retains RestartSources' environment exclusions.
    """

    def __init__(self, profile_path, profile_pin, observer_path, observer_pin):
        self.profile_path = Path(profile_path).resolve()
        self.profile_pin = profile_pin
        self.observer_path = Path(observer_path).resolve()
        self.observer_pin = observer_pin
        require(file_sha(self.profile_path) == profile_pin, 'profile pin differs before import')
        row = json.loads(self.profile_path.read_bytes())
        self.workspace = Path(row['workspace']).resolve()
        require(self.workspace.is_dir(), 'workspace is not a directory')
        self.env = self.workspace/'.r44-env'
        self.native_root = self.resolve(row['native_root'])
        self.roots = (self.native_root, *(self.resolve(p) for p in row['import_roots']))
        require(all(p.is_dir() for p in self.roots), 'an import root is missing')
        self.manifest_path = self.resolve(row['source_manifest']['path'])
        self.manifest_pin = row['source_manifest']['sha256']
        require(file_sha(self.manifest_path) == self.manifest_pin, 'manifest pin differs before import')
        manifest = json.loads(self.manifest_path.read_bytes())
        require(type(manifest.get('files')) is dict and manifest['files'], 'missing importable source pins')
        require(type(manifest.get('data_only')) is dict, 'missing data-only source inventory')
        require(not set(manifest['files']) & set(manifest['data_only']), 'data-only and importable sources overlap')
        self.pins = dict(manifest['files'])
        self.data_only = frozenset(manifest['data_only'])
        for rel in (*self.pins, *self.data_only):
            require(self.resolve(rel).relative_to(self.workspace).as_posix() == rel,
                    'source inventory path is not canonical: '+rel)
        self.imported = set()
        self._entered = False

    def resolve(self, value):
        path = Path(value)
        path = (path if path.is_absolute() else self.workspace/path).resolve()
        require(path.is_relative_to(self.workspace), 'source path escapes the workspace: '+str(path))
        return path

    def verify_inputs(self):
        require(file_sha(self.profile_path) == self.profile_pin, 'profile changed during observation')
        require(file_sha(self.manifest_path) == self.manifest_pin, 'manifest changed during observation')
        require(file_sha(self.observer_path) == self.observer_pin, 'observer differs from independently supplied pin')
        main = sys.modules.get('__main__')
        filename = getattr(main, '__file__', None)
        require(type(filename) is str and Path(filename).resolve() == self.observer_path,
                'observer exemption requires the exact __main__ entry file')

    def check_module(self, name, path, *, bootstrap=False):
        native = name == 'atlas_tectonics' or name.startswith('atlas_tectonics.')
        if native:
            require(path is not None and path.is_relative_to(self.native_root/'atlas_tectonics'),
                    'native module outside the arm runtime: '+name)
        if path is None:
            return False
        if path == self.observer_path:
            require(name == '__main__' and file_sha(path) == self.observer_pin,
                    'observer exemption used by another module or changed file')
            return False
        if not path.is_relative_to(self.workspace) or path.is_relative_to(self.env):
            return False
        require(path.suffix != '.pyc', 'workspace bytecode cannot bypass pinned source: '+name)
        if path.suffix != '.py':
            return False
        require(not bootstrap, 'workspace module loaded before observer fence: '+name)
        rel = path.relative_to(self.workspace).as_posix()
        require(rel not in self.data_only, 'data-only source imported: '+rel)
        require(self.pins.get(rel) == file_sha(path), 'unpinned workspace module: '+rel)
        if '.' not in name and name != '__main__' and path.stem == name:
            first = None
            for root in self.roots:
                for candidate in (root/name/'__init__.py', root/(name+'.py')):
                    if candidate.is_file():
                        first = candidate.resolve()
                        break
                if first is not None:
                    break
            require(first == path, 'module is not the first source resolution: '+name)
        return True

    def audit(self, *, bootstrap=False):
        self.verify_inputs()
        # multiprocessing registers the verified entry object under this name.
        # Remove only that redundant object alias; all other aliases still refuse.
        main = sys.modules.get('__main__')
        if sys.modules.get('__mp_main__') is main:
            del sys.modules['__mp_main__']
        checked = 0
        for name, module in tuple(sys.modules.items()):
            filename = getattr(module, '__file__', None)
            path = Path(filename).resolve() if type(filename) is str else None
            checked += self.check_module(name, path, bootstrap=bootstrap)
        return {'pinned_modules_checked': checked,
                'exempt': {'path': str(self.observer_path), 'sha256': self.observer_pin},
                'pinned_source_imports': len(self.imported),
                'data_only_exclusion': True, 'first_resolution': True, 'source_bytes_loader': True}

    def __enter__(self):
        require(not self._entered, 'observer fence cannot be re-entered')
        self.audit(bootstrap=True)
        owner = self

        class Loader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                path = Path(self.path).resolve()
                rel = path.relative_to(owner.workspace).as_posix()
                raw = path.read_bytes()
                require(rel not in owner.data_only and sha256(raw).hexdigest() == owner.pins.get(rel),
                        'import source bytes differ from pin: '+rel)
                owner.imported.add(rel)
                return compile(raw, str(path), 'exec', dont_inherit=True)

        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
                filename = None if spec is None else spec.origin
                origin = Path(filename).resolve() if filename and filename not in ('built-in', 'frozen') else None
                if spec is not None and owner.check_module(fullname, origin):
                    spec.loader = Loader(fullname, str(origin))
                    return spec
                return None

        self._old_path, self._old_meta = list(sys.path), list(sys.meta_path)
        sys.path[:0] = [str(p) for p in self.roots]
        sys.meta_path.insert(0, Finder())
        self._entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.audit()
        finally:
            sys.path[:] = self._old_path
            sys.meta_path[:] = self._old_meta
            self._entered = False
        return False



def descriptor_row(name, index, descriptor, written):
    """Retain the exact closed manifest descriptor, independently digested by this observer."""
    require(type(descriptor) is dict and set(descriptor) == {'dtype', 'shape', 'chunks'},
            'head array descriptor is not closed: '+name)
    require(type(descriptor['dtype']) is str and type(descriptor['shape']) is list and
            all(type(n) is int and n >= 0 for n in descriptor['shape']) and
            type(descriptor['chunks']) is list and all(type(n) is str for n in descriptor['chunks']),
            'head array descriptor types differ: '+name)
    copied = {'dtype': descriptor['dtype'], 'shape': list(descriptor['shape']),
              'chunks': list(descriptor['chunks'])}
    raw = json.dumps(copied, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'name': name, 'file': '%04d.bin' % index, 'dtype': copied['dtype'],
            'shape': list(copied['shape']), **written, 'descriptor': copied,
            'descriptor_sha256': sha256(raw).hexdigest()}


def decoders(fence):
    """Import every decoder module through the fence; return its workspace path and pinned sha256."""
    found = {}
    for name in DECODER_MODULES:
        module = importlib.import_module(name)
        filename = getattr(module, '__file__', None)
        require(type(filename) is str, 'decoder module has no source file: '+name)
        path = fence.resolve(filename)
        rel = path.relative_to(fence.workspace).as_posix()
        require(rel in fence.imported and fence.pins.get(rel) == file_sha(path),
                'decoder module not loaded from its pinned source: '+name)
        found[name] = {'path': rel, 'sha256': fence.pins[rel]}
    return found


def owned_parts(stream):
    """The bytes of a record_views stream: a context-managed iterator of owned blocks, each released after use."""
    with stream as blocks:
        for block in blocks:
            with block:
                yield block.value


def compact_records(store, state, refs, out, *, budget, scope):
    """Stream the compact state children and the state's v3 thermal mesh as canonical logical bytes.

    The producer's own readers authenticate every chunk and logical identity; the mesh must be the
    one the state names (thermal_mesh_id). The caller compares the result with the reader targets.
    """
    import spatial_indexed_patch as SI
    import spatial_records_patch as SR
    from compact_contracts import SegmentRef
    from compact_store import CompactMeshStoreV3
    reference = state.get('compact_mesh')
    require(type(reference) is dict and type(state.get('thermal_mesh_id')) is str,
            'compact state has no v3 thermal mesh join')
    found = {}
    with SR.open_records(store, refs, budget=budget, scope=scope,
                         source_producer=reference['source_producer']) as opened:
        require(set(opened) == set(refs), 'compact record inventory differs from its references')
        for name, child in sorted(opened.items()):
            # r3 fix: r2 passed child.iter_json() itself, whose items are owned blocks, not bytes.
            found[name] = write_stream(out/'records'/(name+'.json'), owned_parts(child.iter_json()))
            child.close()
    mesh = CompactMeshStoreV3(store, scope=scope).open(
        SegmentRef.from_wire(reference['segment']), expected_geometry_id=state['thermal_mesh_id'])
    found['mesh'] = write_stream(out/'records'/'mesh.json', SI.iter_logical_json(mesh))
    del mesh
    return found


def compact_partition(store, header, out, *, scope):
    """Root route (c): the root header's v2 partition, read and bound to that header.

    The producer's segment reader authenticates the chunks; the header must be exactly the one
    partition_workflow_patch.compact_header derives from the stored descriptor, and the streamed
    descriptor bytes must have the reference's logical identity.
    """
    import partition_store as PS
    import partition_workflow_patch as PW
    from compact_contracts import SegmentRef
    require(type(header) is dict and type(header.get('compact_partition')) is dict and
            header['compact_partition'].get('schema') == SEGMENT_REF_SCHEMA,
            'root partition header has no v2 segment reference')
    wire = header['compact_partition']
    ref = SegmentRef.from_wire(wire)
    view = PS.open_partition_v2(store, ref, scope=scope)
    require(PW.compact_header(view, {}, wire) == header, 'root partition header differs from its stored descriptor')
    written = write_stream(out/'records'/'partition.json', PW.iter_descriptor_json(view))
    del view
    require(written == {'sha256': ref.identity.sha256, 'nbytes': ref.identity.canonical_bytes},
            'root partition descriptor bytes differ from the reference identity')
    return {'dumped': True, 'route': PARTITION_ROUTE, 'reference': wire, **written}


def head_records(store, key, head, interval, targets, out, *, budget, scope):
    """The head's record bytes by its own route (compact, or a native root), each exactly its proved identity."""
    state = head['exterior_state']
    refs = dict(state['record_blobs'])
    if interval == 1:
        refs.update(head['exterior_advance']['record_blobs'])
        refs['certification'] = head['differential_certification']['record_blob']
        refs['differential'] = head['differential_geometry']['record_blob']
    found = {}
    if 'compact_mesh' in state:
        found = compact_records(store, state, refs, out, budget=budget, scope=scope)
    else:
        require(interval == 0, 'a native successor has no compact records')
        for name, reference in sorted(refs.items()):
            require(type(reference) is dict and set(reference) == {'array', 'bytes', 'sha256'} and
                    reference['array'] == RECORD_ARRAY+name, 'native root record reference differs')
            chunks = (chunk for _, chunk in store.iter_chunks(key, reference['array'], budget=budget))
            found[name] = write_stream(out/'records'/(name+'.json'), chunks)
            require(found[name] == {'sha256': reference['sha256'], 'nbytes': reference['bytes']},
                    'native record bytes differ from their reference: '+name)
    expected = {name: value for name, value in targets.items() if name != 'partition'}
    require(found == expected, 'dumped record bytes differ from the proved identities: ' +
            ', '.join(sorted(n for n in set(found) | set(expected) if found.get(n) != expected.get(n))))
    return found


def head_partition(store, head, interval, targets, out, *, scope):
    """The root v2 descriptor itself when the head references one; otherwise the reader-proved identity only."""
    nested = head.get('differential_partition')
    compact = nested.get('compact_partition') if type(nested) is dict else None
    if interval == 0 and type(compact) is dict and compact.get('schema') == SEGMENT_REF_SCHEMA:
        require('partition' not in targets, 'root reader proves no partition identity to bind')
        return compact_partition(store, nested, out, scope=scope)
    return {'dumped': False, 'identity': targets.get('partition'),
            'reason': 'descriptor statistics only (the reader proves it the same way)'}


def dump(args, record):
    require(EXTRACTION_READY, 'N9 r5 dump repairs incomplete: no extraction or acceptance yet')
    with ObserverFence(args.profile, args.profile_sha256, args.observer_path, args.observer_sha256) as fence:
        _dump(args, record, fence)
    record['environment_after'] = environment()
    require(record['environment_after'] == record['environment'],
            'observer interpreter or environment changed during extraction')


def _dump(args, record, fence):
    native_root, import_roots = roots_of(args.profile, args.profile_sha256)
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
    import workflow_transfer as W
    from atlas_tectonics.resources import WorkBudget
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
            record['store_token_before'] = token_wire(token)
            workflow_id = runner['workflow_id']
            root_key = W.workflow_key('root', workflow_id)
            key = root_key if args.interval == 0 else W.workflow_key('successor', root_key)
            head = store.metadata(key)
            require(type(head) is dict and head.get('key') == key and head.get('sequence') == args.interval and
                    head.get('kind') == MODES[args.interval].replace('interval', 'successor'),
                    'workflow head of the interval not found in the store')
            root_metadata = store.metadata(root_key)
            require(type(root_metadata) is dict and root_metadata.get('key') == root_key and
                    root_metadata.get('kind') == 'root' and root_metadata.get('sequence') == 0,
                    'opened root metadata is not this workflow root')
            if args.interval == 0:
                published = runner.get('root')
                root_raw = json.dumps(root_metadata, sort_keys=True, separators=(',', ':'),
                                      allow_nan=False).encode()
                require(type(published) is dict and published.get('root_key') == root_key and
                        sha256(root_raw).hexdigest() == published.get('root_metadata_sha256'),
                        'root metadata differs from independently reader-checked published root')
            else:
                producer = json.loads(Path(files['producer_receipt']['path']).read_bytes())
                require(root_metadata == producer.get('completed_endpoint', {}).get('root_metadata'),
                        'root metadata differs from independently reader-checked completed endpoint')
            record['records'] = head_records(store, key, head, args.interval, targets, out,
                                             budget=budget, scope=scope)
            record['partition'] = head_partition(store, head, args.interval, targets, out, scope=scope)
            arrays = []
            manifest = store._manifest(key)
            require(type(manifest) is dict, 'head manifest not found')
            record['store_limits'] = {'chunk_bytes': store.limits.chunk_bytes}
            plain = sorted((n, d) for n, d in manifest['arrays'].items() if not n.startswith(RECORD_ARRAY))
            for index, (name, desc) in enumerate(plain):
                chunks = (chunk for _, chunk in store.iter_chunks(key, name, budget=budget))
                written = write_stream(out/'arrays'/('%04d.bin' % index), chunks)
                arrays.append(descriptor_row(name, index, desc, written))
            record['arrays'] = arrays
            after = store.change_token()
            record['store_token_after'] = token_wire(after)
            require(after == token, 'the dump changed the store')
            record['head'] = {'key': key, 'kind': head['kind'], 'sequence': head['sequence'],
                              'root_metadata': root_metadata}
        # After the reads: naming the decoders cannot change the import order the reads ran under.
        record['decoders'] = decoders(fence)
        record['loaded_audit'] = fence.audit()
        record['source_proof'] = sources.verify()
        require(record['source_proof'] == record['source_proof_before'], 'sources changed during the dump')
        recheck(files)
    except BaseException as error:
        close_scope(scope, error)
        raise
    close_scope(scope)


def close_scope(scope, error=None):
    """Close the retained scope. After a refusal its failing frames still own their paid blocks (by design),
    so a close failure of any Exception type is noted on the original error instead of replacing it:
    dump.json keeps the cause."""
    gc.collect()
    if error is None:
        scope.close()
        return
    try:
        scope.close()
    except Exception as closing:
        error.add_note('retained scope left open after the refusal: %s: %s' % (type(closing).__name__, closing))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--profile', required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--interval', type=int, choices=sorted(MODES), required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--observer-path', required=True)
    parser.add_argument('--observer-sha256', required=True)
    args = parser.parse_args(argv)
    require(Path(args.observer_path).resolve() == Path(__file__).resolve() and
            args.observer_sha256 == _ENTRY_SHA256 == file_sha(__file__),
            'observer entry file differs from independently supplied path/pin')
    if not sys.flags.no_user_site or not sys.flags.safe_path:
        raise SystemExit('observer requires both -s and -P')
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
              'observer': {'path': str(Path(__file__).resolve()), 'sha256': _ENTRY_SHA256,
                           'no_user_site': sys.flags.no_user_site, 'safe_path': sys.flags.safe_path},
              'environment': environment(), 'errors': []}
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
