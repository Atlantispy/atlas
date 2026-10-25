"""Pinned Plan02 source staging only. No imports/constructors from copied sources.

The production CLI has no path/pin override. --stage requires separate execution
authority; authoring this file grants none. Diagnostics go to stdout, never B.
Failures keep every partial output. No repair, retry, replacement or deletion.
"""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import traceback

W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
O = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014'
B = O/'prepared-v2-r3'
D = W/'work/plan02/prepared-construction-v2-r3'
G = T/'ac/plan02/gen-r3'
S = T/'ac/s4/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
R = O/'resumability-r1'
H = T/'fidelity-integration-20261005/heat-repair-20261007'
PLAN = D/'source-plan-r1/source-copy-plan.json'
PLAN_SHA256 = 'd853763a63e4a2367d87ddd7f7617fff798c791fb205cfb87681518a7feae39c'
HANDOFF_INDEX_SHA256 = '95f0061c1dc7cda1a071f1a464cde6dd7070e5f4dabf6f2ef06f8f573cf6e990'
HANDOFF_SHA256 = 'cf6be24980fd5b75e94748797c158efe69524b2ce7f92d18264440719b8b0035'
PREPARER_SHA256 = 'b3bb9c11c69ec24b432c889e8aa7907da9f04c9855ee0b434acf3c00e8ba2366'
SELECTION_SHA256 = '0f2662815f38c4d1f82502d169e0e07ac9d583e51e28307389c402fd9254e163'
ROUTE = 'legacy-prepared-construct_successor'
MAX_FILE_BYTES = 8 << 20
MAX_SOURCE_BYTES = 32 << 20
MAX_METADATA_BYTES = 2 << 20
MAX_METADATA_TOTAL = 8 << 20
MAX_SOURCE_PATH = 384
MAX_DESTINATION_PATH = 240
MAX_ROWS = 153
MAX_DEPTH = 3


@dataclass(frozen=True)
class Policy:
    """Explicit fixture seam; production CLI always uses production_policy()."""
    plan: Path
    plan_sha256: str
    box: Path
    task: Path
    handoff_dir: Path
    index_sha256: str
    handoff_sha256: str
    preparer_sha256: str
    selection_sha256: str
    source_roots: tuple  # exact (parent directory, number of direct children)
    metadata: tuple  # exact (role, ordinary path, selected SHA-256)
    rows: int = MAX_ROWS
    selected: int = 66
    max_file_bytes: int = MAX_FILE_BYTES
    max_source_bytes: int = MAX_SOURCE_BYTES
    max_destination_path: int = MAX_DESTINATION_PATH


def production_policy():
    return Policy(PLAN, PLAN_SHA256, B, T, D, HANDOFF_INDEX_SHA256,
        HANDOFF_SHA256, PREPARER_SHA256, SELECTION_SHA256,
        tuple((Path(root), count) for root, count in (('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\ac\\plan02\\gen-r3', 89),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\ac\\s4\\fidelity-integration-20261005\\continuation-repair-20261013\\optimisation-20261014\\resumability-r1\\compact-geometry-r1', 38),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\ac\\s4\\fidelity-integration-20261005\\continuation-repair-20261013\\optimisation-20261014\\resumability-r1\\endpoint-checkpoints', 3),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\continuation-repair-20261013\\optimisation-20261014\\resumability-r1', 1),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\continuation-repair-20261013\\optimisation-20261014\\resumability-r1\\endpoint-checkpoints', 1),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\continuation-repair-20261013\\optimisation-20261014\\resumability-r1\\test-results', 13),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\rm\\p26\\d26h-r5', 1),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan02\\prepared-construction-v2-r3', 5),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan31\\g1\\src', 1),
         ('C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan31\\t1\\review-r2\\src', 1),)),
        (('generation', T/'ac/plan02/GENERATION-r3.json',
          'b20a09ce7cad44dea942023dbc07c0070dcaab4d16adec0023ed7f7f3aa86be3'),
         ('old_reviewed_inputs', G/'reviewed-inputs.json',
          'ffe35f7d7aa45f6de3924173806291e4ee311b303977e326c4d84a4452857bfb'),
         ('I', O/'runtime-integration-r1/manifest.json',
          '597c00328bb8aede225a8a936dcea2edab42d3c894eb87caeb974fdfd576979d'),
         ('filtered', O/'filtered-exact-r1/manifest.json',
          '43effbdb044218524c178518d155d7ff9d387d9b3859a4127e211a9cc5681683'),
         ('heat', H/'continuation-preparation-r3.json',
          'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c')))


class Refused(ValueError):
    pass


class StageFailed(Exception):
    def __init__(self, report):
        self.report = report
        super().__init__(report['error']['message'])


def require(ok, message):
    if not ok:
        raise Refused(message)


def digest(raw):
    return sha256(raw).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: '+key)
        result[key] = value
    return result


def decode(raw):
    def no_constant(value):
        raise Refused('nonfinite JSON value: '+value)
    value = json.loads(raw.decode('utf8'), object_pairs_hook=_object,
                       parse_constant=no_constant)
    require(type(value) is dict, 'JSON object required')
    return value


def _component(part):
    require(type(part) is str and bool(re.fullmatch(r'[A-Za-z0-9_. -]+', part)),
            'unsafe path component: '+repr(part))
    require(part not in ('.', '..') and part == part.strip(' .'),
            'noncanonical path component: '+repr(part))
    require(not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])', part.split('.')[0]),
            'reserved path component: '+part)


def absolute(value, limit=MAX_SOURCE_PATH):
    raw = str(value)
    require(len(raw) <= limit and not raw.startswith(('\\\\', '//')),
            'path length or UNC/device path refused: '+raw)
    # Check raw components before pathlib can discard a dot or empty component.
    normal = raw.replace('\\', '/')
    components = normal.split('/')
    if re.fullmatch('[A-Za-z]:', components[0]):
        components = components[1:]
    elif components[0] == '':  # disposable POSIX fixtures only; CLI is Windows
        components = components[1:]
    for part in components:
        _component(part)
    path = Path(raw)
    require(path.is_absolute(), 'absolute ordinary path required: '+raw)
    return path


def key(path):
    return str(path).replace('\\', '/').casefold()


def relative(value):
    require(type(value) is str and '\\' not in value and len(value) <= 120,
            'normalised forward-slash relative name required')
    parts = value.split('/')
    require(1 <= len(parts) <= MAX_DEPTH, 'relative path depth exceeded')
    for part in parts:
        _component(part)
    return Path(*parts)


def fingerprint(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns,
            getattr(value, 'st_file_attributes', 0))


def shared_fingerprint(value):
    """Identity fields comparable between Windows pathname stat and fstat.

    ctime and attributes remain in same-API before/after checks. Windows may
    report different stable values for those fields through these two APIs.
    """
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns)


def ordinary(path, kind):
    """lstat every ancestor; never resolve or traverse a known reparse point."""
    path = absolute(path)
    parts = list(reversed(path.parents)) + [path]
    identities = []
    for item in parts:
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not getattr(info, 'st_file_attributes', 0) & 0x400,
                'symlink/reparse path refused: '+str(item))
        want_dir = item != path or kind == 'directory'
        require(stat.S_ISDIR(info.st_mode) if want_dir else stat.S_ISREG(info.st_mode),
                'ordinary '+('directory' if want_dir else 'file')+' required: '+str(item))
        # Directories legitimately change mtime as descendants are created.
        identities.append((key(item), info.st_dev, info.st_ino, info.st_mode,
                           getattr(info, 'st_file_attributes', 0)))
    require(key(path.resolve(strict=True)) == key(path), 'path alias refused: '+str(path))
    return tuple(identities), info


def absent(path):
    ordinary(path.parent, 'directory')
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise Refused('exclusive absent destination required: '+str(path))


def pinned(path, expected, cap):
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected),
            'exact SHA-256 required')
    path = absolute(path)
    chain, before = ordinary(path, 'file')
    require(before.st_size <= cap, 'file byte cap exceeded: '+str(path))
    with path.open('rb') as stream:
        before_open = os.fstat(stream.fileno())
        require(stat.S_ISREG(before_open.st_mode) and
                not getattr(before_open, 'st_file_attributes', 0) & 0x400,
                'opened source is not an ordinary file: '+str(path))
        require(shared_fingerprint(before_open) == shared_fingerprint(before),
                'source changed before open: '+str(path))
        raw = stream.read(cap+1)
        after_open = os.fstat(stream.fileno())
    after_chain, after = ordinary(path, 'file')
    require(chain == after_chain and fingerprint(before) == fingerprint(after) and
            fingerprint(before_open) == fingerprint(after_open) and
            shared_fingerprint(after_open) == shared_fingerprint(after),
            'source changed during read: '+str(path))
    require(len(raw) <= cap and len(raw) == before.st_size, 'bounded read changed: '+str(path))
    require(digest(raw) == expected, 'SHA-256 mismatch: '+str(path))
    return raw, (chain, fingerprint(after))


def _unchanged(path, identity):
    chain, info = ordinary(path, 'file')
    require((chain, fingerprint(info)) == identity, 'source identity changed: '+str(path))


def preflight(policy):
    """Authenticate all metadata/row snapshots before any destination mutation."""
    box = absolute(policy.box, policy.max_destination_path)
    task = absolute(policy.task)
    require(box.name == 'prepared-v2-r3' and box.parents[3] == task,
            'prepared source-box depth/task topology mismatch')
    absent(box)
    require(0 < policy.rows <= MAX_ROWS and 0 < policy.selected <= policy.rows,
            'bounded expected row counts required')
    metadata_total = 0
    identities = {}
    def meta(path, pin):
        nonlocal metadata_total
        path = absolute(path)
        raw, identity = pinned(path, pin, MAX_METADATA_BYTES)
        metadata_total += len(raw)
        require(metadata_total <= MAX_METADATA_TOTAL, 'aggregate metadata byte cap exceeded')
        identities[path] = (pin, identity)
        return raw

    plan = decode(meta(policy.plan, policy.plan_sha256))
    require(set(plan) == {'schema', 'status', 'route', 'future_box', 'target',
                         'generation_predecessor', 'retained_old_reviewed_inputs', 'files', 'unavailable'},
            'unexpected source-plan fields')
    require(plan['schema'] == 'atlas.private.prepared-source-copy-plan.v1' and
            plan['status'] == 'PREPARATION_ONLY_NO_COPY_OR_BUILD' and plan['route'] == ROUTE and
            plan['target'] == 'composed-r1' and
            plan['unavailable'] == ['complete selected reviewed-inputs record', 'final generation'],
            'only the selected preparation-only source plan is stageable')
    require(key(absolute(plan['future_box'], policy.max_destination_path)) == key(box),
            'source plan destination differs from exact expected B')
    index = decode(meta(policy.handoff_dir/'HANDOFF-PINS.json', policy.index_sha256))
    require(index.get('schema') == 'atlas.private.prepared-authoring-handoff-pins.v1' and
            type(index.get('files')) is dict and 1 <= len(index['files']) <= 32,
            'invalid pinned handoff index')
    files = index['files']
    require(files.get('HANDOFF.md') == policy.handoff_sha256 and
            files.get('prepare_generation.py') == policy.preparer_sha256 and
            files.get('prepared-source-selection.json') == policy.selection_sha256,
            'handoff/preparer/source-selection identity mismatch')
    selection_raw = None
    for name, pin in sorted(files.items()):
        rel = relative(name)
        require(len(rel.parts) == 1, 'handoff must name direct files only')
        raw = meta(policy.handoff_dir/rel, pin)
        if name == 'prepared-source-selection.json':
            selection_raw = raw
    selection = decode(selection_raw)
    require(selection.get('route') == ROUTE and selection.get('layout') ==
            {'future_box': plan['future_box'], 'target': plan['target']},
            'source selection layout/route mismatch')
    refs = {role: (absolute(path), pin) for role, path, pin in policy.metadata}
    require(len(refs) == len(policy.metadata) and set(refs) ==
            {'generation', 'old_reviewed_inputs', 'I', 'filtered', 'heat'}, 'metadata roles mismatch')
    topology = {'I': box.parent/'runtime-integration-r1/manifest.json',
                'filtered': box.parent/'filtered-exact-r1/manifest.json',
                'heat': task/'fidelity-integration-20261005/heat-repair-20261007/continuation-preparation-r3.json'}
    for role, expected_path in topology.items():
        require(refs[role][0] == expected_path, 'protected '+role+' topology mismatch')
    for role, name in (('generation', 'generation_predecessor'),
                       ('old_reviewed_inputs', 'retained_old_reviewed_inputs')):
        path, pin = refs[role]
        require(type(plan[name]) is dict and set(plan[name]) == {'path', 'sha256'} and
                key(absolute(plan[name]['path'])) == key(path) and plan[name]['sha256'] == pin,
                'predecessor metadata binding mismatch: '+role)
    for path, pin in refs.values():
        meta(path, pin)  # identity only, no dataset/manifest inventory traversal

    rows = plan['files']
    require(type(rows) is dict and len(rows) == policy.rows, 'exact selected row count required')
    selected = selection.get('files')
    require(type(selected) is dict and len(selected) == policy.selected, 'selected-input count mismatch')
    for name, row in selected.items():
        require(name in rows and type(row) is dict and
                rows[name]['sha256'] == row.get('sha256') and
                key(absolute(rows[name]['source'])) == key(absolute(row.get('source'))),
                'selected input missing or altered: '+name)
    roots = {key(absolute(root)): count for root, count in policy.source_roots}
    require(len(roots) == len(policy.source_roots) and sum(roots.values()) == policy.rows,
            'invalid exact source-root counts')
    for root, _ in policy.source_roots:
        ordinary(root, 'directory')
        require(key(box) != key(root) and box not in root.parents and root not in box.parents,
                'source/destination root overlap')
    counts = dict.fromkeys(roots, 0)
    names, directories, sources, prepared = set(), set(), set(), []
    total = 0
    for name, row in sorted(rows.items()):
        rel = relative(name)
        dest = absolute(box/rel, policy.max_destination_path)
        require(dest.is_relative_to(box) and key(dest) not in names, 'destination collision/escape: '+name)
        names.add(key(dest))
        directories.update(key(p) for p in dest.parents if p != box and p.is_relative_to(box))
        require(type(row) is dict and set(row) in ({'source', 'sha256'}, {'source', 'sha256', 'scope'}),
                'unexpected source row: '+name)
        require('scope' not in row or type(row['scope']) is str, 'invalid row scope')
        src = absolute(row['source'])
        require(key(src.parent) in roots, 'source outside exact allowed parent roots: '+str(src))
        require(key(src) not in sources, 'source alias/duplicate row: '+str(src))
        sources.add(key(src))
        counts[key(src.parent)] += 1
        cap = min(policy.max_file_bytes, policy.max_source_bytes-total)
        require(cap >= 0, 'aggregate source byte cap exceeded')
        raw, identity = pinned(src, row['sha256'], cap)
        total += len(raw)
        prepared.append((name, src, row['sha256'], raw, identity))
    require(not names.intersection(directories), 'file/directory destination prefix collision')
    require(counts == roots, 'exact source-root distribution mismatch')
    for path, (_, identity) in identities.items():
        _unchanged(path, identity)
    for _, src, _, _, identity in prepared:
        _unchanged(src, identity)
    absent(box)
    return prepared, identities, total


def _write(path, raw):
    ordinary(path.parent, 'directory')
    with path.open('xb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), 'exclusive output is not a regular file')
        require(stream.write(raw) == len(raw), 'short output write: '+str(path))
        stream.flush()
        os.fsync(stream.fileno())
    return info.st_dev, info.st_ino


def _inventory(box, expected_files, expected_dirs):
    """Only enumerate the known shallow box; never walk an unexpected entry."""
    for folder in [box] + sorted(expected_dirs, key=str):
        ordinary(folder, 'directory')
        expected = {p.name for p in expected_files | expected_dirs if p.parent == folder}
        actual = set()
        with os.scandir(folder) as entries:
            for entry in entries:
                require(len(actual) < MAX_ROWS+16, 'output inventory bound exceeded')
                require(entry.name in expected, 'unexpected staged entry: '+entry.path)
                actual.add(entry.name)
        require(actual == expected, 'incomplete output inventory: '+str(folder))


def stage(policy):
    """The only effecting API. Fixtures may pass a separately built tiny policy."""
    report = dict(schema='atlas.private.prepared-source-staging.v1', status='NOT_CREATED',
        source_plan_sha256=policy.plan_sha256, handoff_index_sha256=policy.index_sha256,
        destination=str(policy.box), expected_rows=policy.rows, verified_rows=0,
        copied_rows=0, source_bytes=0, destination_created=False, created_directories=[],
        attempted_files=[], completed_files=[], phase='preflight',
        transforms_run=False, atlas_imported=False, profile_written=False,
        readiness_declared=False, automatic_cleanup=False)
    try:
        prepared, identities, total = preflight(policy)
        report.update(verified_rows=len(prepared), source_bytes=total, phase='exclusive-create')
        box = absolute(policy.box, policy.max_destination_path)
        parent_chain, _ = ordinary(box.parent, 'directory')
        absent(box)
        box.mkdir()  # no parents=True, no exist_ok; no adoption of an existing box
        report['destination_created'] = True
        box_chain, _ = ordinary(box, 'directory')
        require(box_chain[:-1] == parent_chain, 'destination ancestor identity changed')
        dirs = {p for name, *_ in prepared for p in (box/relative(name)).parents
                if p != box and p.is_relative_to(box)}
        report['phase'] = 'copy'
        for directory in sorted(dirs, key=lambda p: (len(p.parts), str(p))):
            require(ordinary(box, 'directory')[0] == box_chain, 'destination root changed')
            ordinary(directory.parent, 'directory')
            directory.mkdir()
            report['created_directories'].append(str(directory.relative_to(box)))
        created = {}
        for name, src, pin, raw, identity in prepared:
            require(ordinary(box, 'directory')[0] == box_chain, 'destination root changed')
            _unchanged(src, identity)
            dest = box/relative(name)
            report['attempted_files'].append(name)
            created[dest] = _write(dest, raw)
            check, _ = pinned(dest, pin, len(raw))
            require(check == raw, 'copied bytes differ: '+name)
            report['completed_files'].append(name)
            report['copied_rows'] += 1
        report['phase'] = 'post-copy-verification'
        for name, src, pin, raw, _ in prepared:
            dest = box/relative(name)
            require(ordinary(box, 'directory')[0] == box_chain, 'destination root changed')
            _, info = ordinary(dest, 'file')
            require((info.st_dev, info.st_ino) == created[dest], 'output file identity changed: '+name)
            pinned(dest, pin, len(raw))
            pinned(src, pin, len(raw))
        for path, (pin, _) in identities.items():
            pinned(path, pin, MAX_METADATA_BYTES)
        _inventory(box, set(created), dirs)
        report.update(status='STAGED_SOURCE_ONLY', phase='complete', post_copy_verified=True)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status='PARTIAL_RETAINED' if report['destination_created'] else 'REFUSED_NO_CREATE',
                      post_copy_verified=False,
                      error={'type': type(exc).__name__, 'message': str(exc)[:4096]},
                      interrupted=isinstance(exc, KeyboardInterrupt))
        raise StageFailed(report) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', action='store_true', required=True,
                        help='stage the fixed pinned 153-row plan after owner execution clearance')
    parser.parse_args(argv)
    require(os.name == 'nt', 'production entry point requires the selected Windows host')
    try:
        result = stage(production_policy())
    except StageFailed as exc:
        print(json.dumps(exc.report, sort_keys=True, allow_nan=False))
        traceback.print_exception(exc.__cause__)  # retain complete failure in the caller's stderr log
        return 130 if exc.report['interrupted'] else 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
