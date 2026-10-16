"""W4 composed reruns: shared paths, frozen composed-tree verification, RAM gate and import audit.

Standard library plus psutil only. Nothing here imports the native package or a
helper; every check runs its scientific imports in a fresh child process whose
import roots are exactly the composed ones (composed-r1/runtime-src, /helpers,
/ram and H/source/tectonics/tests). The composed tree is only ever read.
"""
import sys
sys.dont_write_bytecode = True  # never leave bytecode beside frozen sources

from hashlib import sha256
import json
import os
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent            # R/composed-checks
R = HERE.parent
O = R.parent
CR = O.parent
FI = CR.parent                                    # fidelity-integration-20261005
T = FI.parent                                     # the workspace (manifest paths are relative to it)
H = FI/'heat-repair-20261007'
H_TESTS = H/'source'/'tectonics'/'tests'
I = O/'runtime-integration-r1'
C = R/'compact-geometry-r1'
E = R/'endpoint-checkpoints'
RC = R/'composed-r1'
NATIVE = RC/'runtime-src'
HELPERS = RC/'helpers'
RAM = RC/'ram'
IMPORT_ROOTS = (HELPERS, RAM, H_TESTS)            # composed-r1 manifest layout.import_roots, in order
SCRATCH = T/'_t'/'w4-reruns'
PYTHON = T/'.r44-env'/'Scripts'/'python.exe'

MANIFEST_SHA256 = '6a6f493353942ebd27f10c73105fe7d10f5ab1bef1f4d54e72094ac5dcfe4e9b'
NATIVE_SOURCE_DIGEST = '6e3e6b7f19b689bfe85d6b4bd19e4a453202b9b059445bf9d78238a88740de20'
EXECUTION_IDENTITY = '86c819bb9c62d591f0c1e529baae717254f6fa21b28537348fe153146c40c906'
COMPANION_SHA256 = '4a835dc34f840fd12298a676ddae209966b378257e2693b04f7f681e65a7e451'
PREDECESSOR_COMPANION_SHA256 = 'f433773c3c70539d525737708178057cd33ca3be51ad0837c85853ccf01cdad8'
SUCCESSOR_GUARD_SHA256 = '9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772'
MIN_AVAILABLE_BYTES = 3 << 29                     # 1.5 GiB before any heavy child starts
RAM_POLLS, RAM_POLL_SECONDS = 10, 30.


class W4Refused(RuntimeError):
    """An input differs from the frozen composed scope; nothing is measured or claimed."""


def require(condition, message):
    if not condition:
        raise W4Refused(message)


def file_sha(path):
    digest = sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def manifest():
    raw = (RC/'manifest.json').read_bytes()
    require(sha256(raw).hexdigest() == MANIFEST_SHA256, 'composed-r1 manifest differs from the verified composition')
    return json.loads(raw)


def native_hashes(package):
    """'atlas_tectonics/<relative>.py' -> sha256, the manifest source_hashes spelling."""
    package = Path(package)
    return {'atlas_tectonics/'+'/'.join(p.relative_to(package).parts): file_sha(p)
            for p in sorted(package.rglob('*.py'))}


def tree_snapshot():
    """Every regular file under composed-r1 (path -> size, sha256) plus any bytecode directory."""
    files, caches = {}, []
    for path in sorted(RC.rglob('*')):
        relative = '/'.join(path.relative_to(RC).parts)
        if path.is_dir():
            if path.name == '__pycache__':
                caches.append(relative)
            continue
        files[relative] = [path.stat().st_size, file_sha(path)]
    return dict(files=len(files), caches=caches, digest=sha256(canonical(files)).hexdigest(), entries=files)


def verify_composed():
    """Hash every manifest-pinned file and data-only reference against the frozen manifest."""
    begun = time.perf_counter()
    m = manifest()
    bad = []
    for kind in ('files', 'data_only'):
        for relative, pin in m[kind].items():
            path = T/relative
            if not path.is_file() or file_sha(path) != pin:
                bad.append(relative)
    hashes = native_hashes(NATIVE/'atlas_tectonics')
    require(not bad, 'composed manifest entries differ on disk: '+', '.join(bad[:5]))
    require(hashes == m['source_hashes'], 'composed runtime-src differs from manifest source_hashes')
    require(sha256(canonical(hashes)).hexdigest() == m['native_source_digest'] == NATIVE_SOURCE_DIGEST,
            'composed native source digest differs')
    snapshot = tree_snapshot()
    require(not snapshot['caches'], 'bytecode directory present in composed-r1: '+', '.join(snapshot['caches']))
    return dict(manifest_sha256=MANIFEST_SHA256, files=len(m['files']), data_only=len(m['data_only']),
                native_sources=len(hashes), native_source_digest=NATIVE_SOURCE_DIGEST,
                tree_files=snapshot['files'], tree_digest=snapshot['digest'],
                seconds=time.perf_counter()-begun)


def ram_gate(minimum=MIN_AVAILABLE_BYTES, polls=RAM_POLLS, wait=RAM_POLL_SECONDS):
    """Wait (bounded) while available RAM is below the gate; refuse rather than start a heavy child."""
    import psutil
    seen = []
    for attempt in range(polls):
        available = psutil.virtual_memory().available
        seen.append(available)
        if available >= minimum:
            return dict(available_bytes=available, polls=attempt+1, waited_seconds=attempt*wait)
        time.sleep(wait)
    raise W4Refused('available RAM stayed below %.2f GiB: %s' % (minimum/2**30, [round(v/2**30, 2) for v in seen]))


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def import_audit(modules, *, test_copies=(), native_copy=None, harness_files=()):
    """Classify every loaded module file. Anything outside the composed roots, the
    interpreter environment, the named test-only copies, this harness and the named
    measurement files (harness_files) is a violation."""
    harness_files = {Path(p).resolve() for p in harness_files}
    m = manifest()
    pinned = {T/relative: 'files' for relative in m['files']}
    pinned.update({T/relative: 'data_only' for relative in m['data_only']})
    environment = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    roots = [('composed-native', NATIVE), ('composed-helper', HELPERS), ('composed-ram', RAM)]
    if native_copy is not None:
        roots.append(('composed-native-copy', Path(native_copy)))
    counts, h_tests, copies, violations, unpinned, helpers = {}, {}, {}, [], [], []
    for name, module in sorted(modules.items()):
        location = getattr(module, '__file__', None)
        if not location:
            continue
        path = Path(location).resolve()
        kind = None
        if any(_inside(path, root) for root in environment):
            kind = 'environment'
        else:
            for label, root in roots:
                if _inside(path, root.resolve()):
                    kind = label
                    break
        if kind is None and _inside(path, H_TESTS.resolve()):
            kind = 'h-tests'
            h_tests[name] = pinned.get(path, 'not-pinned')
            if pinned.get(path) != 'files':
                unpinned.append(name)
        if kind is None and any(_inside(path, Path(c).resolve()) for c in test_copies):
            kind = 'test-copy'
            copies[name] = file_sha(path)
        if kind is None and ((path.parent == HERE and path.name.startswith('w4r_')) or path in harness_files):
            kind = 'w4-harness'
        if kind is None:
            violations.append([name, str(path)])
            continue
        counts[kind] = counts.get(kind, 0)+1
        if kind in ('composed-native', 'composed-helper', 'composed-ram'):
            require(pinned.get(path) == 'files', 'loaded composed file not pinned: '+name)
        if kind in ('composed-helper', 'composed-ram'):
            helpers.append(name)
    return dict(counts=counts, h_tests=h_tests, h_tests_not_in_files=sorted(unpinned),
                test_copies=copies, helpers_loaded=sorted(helpers), violations=violations)


def write_exclusive(path, record):
    """Create a NEW result file; an existing one is never overwritten."""
    path = Path(path)
    require(not path.exists(), 'output exists; refusing to overwrite '+str(path))
    partial = path.with_name(path.name+'.partial')
    with open(partial, 'x', encoding='utf8', newline='\n') as target:
        target.write(json.dumps(record, indent=2, sort_keys=True)+'\n')
    require(not path.exists(), 'output appeared meanwhile; refusing to overwrite '+str(path))
    os.replace(partial, path)
    return file_sha(path)
