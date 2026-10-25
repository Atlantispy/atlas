"""S1 Stage A port onto the explicit public Plan39 selection (guard-equivalent freshness for sealed interval readers).

Five helper rows, each pinned at input and output (PORT.json carries the same table):
- helpers/interval_store_set.py     b2b7a1ae -> 9b00661d  strict unified diff: module import + ReadOnlyNative guard set at
                                                          open (sealed readers only), asks it at each identity check,
                                                          releases it at close; nothing else changes
- helpers/test_s1_sealed_read.py    54edda3f -> e73ccc73  strict unified diff: E1, E2 and E4 keep today's walk route
- helpers/test_interval_store_set.py a9e89b3a -> 10c47f29 strict unified diff: E3 keeps today's walk route
- helpers/sealed_guard_set.py       absent   -> 5f68b934  added (the guard module)
- helpers/test_s1a_guarded_read.py  absent   -> 14d3b6dd  added (a test; not reached by runtime code)

Diffs are applied with the replay constructor's strict apply_diff semantics (every context and removed line must match
byte for byte; the rows are LF like their bases). Every other helper stays byte-identical. The helpers the new code
relies on are pinned at their public Plan39 bytes, so a base whose dependencies changed is refused for re-review instead
of ported. The L3 port (Plan 22) touches none of these rows or dependencies, so the port applies before or after it.
The output must lie outside the base composition, a refused apply removes the folder it created, and both commands
print the base helpers' tree digest for the composition record.

    python -B port_s1a.py verify BASE_HELPERS             check pins and re-derive the rows; writes nothing
    python -B port_s1a.py apply BASE_HELPERS OUT_HELPERS  copy BASE_HELPERS to OUT_HELPERS (must not exist), then port
"""
import hashlib
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
PORT = HERE / 'source'
STORE, S1TEST, ISTEST = 'helpers/interval_store_set.py', 'helpers/test_s1_sealed_read.py', 'helpers/test_interval_store_set.py'
GUARD, TEST = 'helpers/sealed_guard_set.py', 'helpers/test_s1a_guarded_read.py'
ROWS = {  # row: (kind, before_sha256 in public Plan39, after_sha256, diff file, diff sha256)
    STORE: ('diff', 'b2b7a1aec9f3257410f078cf16a0dedf0535e6bf8d14fc18127bb84673dab274',
            '9b00661d4a14c1b8181689f3823e6b1b1cb8c448cff3b2e31056095670cdc192',
            'interval_store_set.s1a.diff', '3191cf6daf0cca04c477c8dd6f3e744d9d511a39d1ec16dfc7213642e276c953'),
    S1TEST: ('diff', '54edda3ff75629f466ae5e9619102771e7d9e9176f1f907b0e3aae75318e95c6',
             'e73ccc73e51c4e0eda58bf9ddd9d2ecbdbafa30c0661cf043e8607102ba990d7',
             'test_s1_sealed_read.s1a.diff', 'f7a4a9bf89123e3af58511509184a6c280e73f087660732da9bb38bbecc793e1'),
    ISTEST: ('diff', 'a9e89b3a5c0b68a3646f59194f7b7213128539a7d42c55c8ecaf1614ef202ec5',
             '10c47f2932bda169fd841165bb5fd1b0a471f0e96ea2e33cc351eb593880d92a',
             'test_interval_store_set.s1a.diff', '3d42736f712ecef9f8db055fbc20f7086fd1e4593e2a8949b76312c277f9fe4b'),
    GUARD: ('add', None, '5f68b934e5886d2df69c1d7fc1ea3fa804d7a5f0c5d10dc6896a4b882ecebfe8', None, None),
    TEST: ('add', None, '14d3b6dd4eac271490ab0a2274306b81f979e5c11568468ae1acbb2ff6bfd645', None, None),
}
DEPENDENCIES = {  # what the guard module and the guarded tests rely on, at their public Plan39 bytes
    'helpers/interval_catalog.py': '51a5010e2a92aa325a0cc7f34fc9af27e86a3c12e5f69e35bf4a5197601d31e0',  # file_token
    'helpers/compact_contracts.py': '0aabad86c1ccffd79b79f8aa320c7406a0406c659105f21838beb37c5bc69f6e',  # ContractError
    'helpers/segment_store.py': 'a90ef8f3e519ee77ea4332380428ce2694c16134ec69603ccaf93ce95cea6cd9',  # verified_read
    'helpers/test_segment_store.py': '2a15702bcf35073bd57ab5e371f3dc7131647d60e4d5e53838a6abb413f5c093',  # fixtures
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path, pin, label):
    data = path.read_bytes()
    require(digest(data) == pin, 'Pin differs: ' + label)
    return data


def lines_of(raw):
    parts = raw.split(b'\n')
    return [part + b'\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def apply_diff(raw, diff, name):
    """Apply a strict unified diff to raw bytes: every context and removed line must match exactly."""
    require(diff.endswith(b'\n'), 'Diff must end in a newline: ' + name)
    source, patch = lines_of(raw), lines_of(diff)
    require(len(patch) > 2 and patch[0].rstrip(b'\r\n') == b'--- a/' + name.encode()
            and patch[1].rstrip(b'\r\n') == b'+++ b/' + name.encode(), 'Diff names another file: ' + name)
    out, at, i = [], 0, 2
    while i < len(patch):
        hunk = re.fullmatch(rb'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', patch[i].rstrip(b'\r\n'))
        require(hunk is not None, 'Malformed diff hunk: ' + name)
        old_start, old_len, new_start, new_len = map(int, hunk.groups() if hunk else ())
        require(old_len > 0 and new_len > 0, 'Zero-length diff hunks are refused: ' + name)
        start = old_start - 1
        require(start >= at, 'Diff hunks out of order: ' + name)
        out += source[at:start]
        require(len(out) == new_start - 1, 'Diff hunk position differs: ' + name)
        at, old, new, i = start, 0, 0, i + 1
        while i < len(patch) and not patch[i].startswith(b'@@'):
            tag, text = patch[i][:1], patch[i][1:]
            require(tag in (b' ', b'-', b'+'), 'Unexpected diff line: ' + name)
            if tag != b'+':
                require(at < len(source) and source[at] == text, 'Diff context differs at line %d: %s' % (at + 1, name))
                at, old = at + 1, old + 1
            if tag != b'-':
                out.append(text)
                new += 1
            i += 1
        require((old, new) == (old_len, new_len), 'Diff hunk length differs: ' + name)
    return b''.join(out + source[at:])


def derive(base_helpers):
    """The five output rows from the pinned base helpers and the pinned package; nothing is written."""
    base = base_helpers.parent
    for row, pin in DEPENDENCIES.items():
        require(digest((base / row).read_bytes()) == pin,
                'Stage A dependency differs from the reviewed public Plan39 bytes (re-review the port): ' + row)
    outputs = {}
    for row, (kind, before, after, diff_name, diff_pin) in ROWS.items():
        target = base / row
        packaged = pinned(PORT / row, after, 'package ' + row)
        if kind == 'add':
            require(not target.exists(), 'Added row already present in the base: ' + row)
        else:
            raw = pinned(target, before, 'base ' + row)
            require(b'\r' not in raw, 'Diff input must be LF throughout: ' + row)
            diff = pinned(PORT / diff_name, diff_pin, diff_name)
            require(apply_diff(raw, diff, row) == packaged, 'Diff output differs from the packaged row: ' + row)
        outputs[row] = packaged
    return outputs


def tree(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}


def tree_digest(files):
    return digest(''.join(f'{name}\0{pin}\n' for name, pin in sorted(files.items())).encode())


def port(base_helpers, out_helpers, outputs):
    before = tree(base_helpers)
    shutil.copytree(base_helpers, out_helpers)
    require(tree(out_helpers) == before, 'Copy of the base helpers differs')
    for row, data in outputs.items():
        (out_helpers.parent / row).write_bytes(data)
    after = tree(out_helpers)
    names = {row.removeprefix('helpers/') for row in ROWS}
    added = {row.removeprefix('helpers/') for row, spec in ROWS.items() if spec[0] == 'add'}
    require(after.keys() == before.keys() | added
            and all(after[k] == v for k, v in before.items() if k not in names)
            and all(after[row.removeprefix('helpers/')] == ROWS[row][2] for row in ROWS),
            'Ported helpers differ from base + the five rows')
    return before, after


def main(argv):
    require(bool(argv) and len(argv) == {'verify': 2, 'apply': 3}.get(argv[0], -1),
            'Usage: port_s1a.py verify BASE_HELPERS | apply BASE_HELPERS OUT_HELPERS')
    base_helpers = Path(argv[1]).resolve()
    require(base_helpers.name == 'helpers' and base_helpers.is_dir(), 'BASE_HELPERS must be a helpers folder')
    outputs = derive(base_helpers)
    if argv[0] == 'verify':
        for row, (kind, before, after, _, _) in ROWS.items():
            print(kind, row, (before or 'absent')[:8], '->', after[:8])
        print('dependencies pinned', len(DEPENDENCIES), '; base helpers tree', tree_digest(tree(base_helpers)))
        return
    out_helpers = Path(argv[2]).resolve()
    require(out_helpers.name == 'helpers' and not out_helpers.exists(), 'OUT_HELPERS must be a new helpers folder')
    require(not out_helpers.is_relative_to(base_helpers.parent), 'OUT_HELPERS must lie outside the base composition')
    try:
        before, after = port(base_helpers, out_helpers, outputs)
    except BaseException:
        shutil.rmtree(out_helpers, ignore_errors=True)  # only the folder this run created; it did not exist before
        raise
    print('ported', len(before), '->', len(after), 'files; rows', ', '.join(f'{r} {ROWS[r][2][:8]}' for r in ROWS))
    print('base helpers tree', tree_digest(before), '; ported helpers tree', tree_digest(after))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (OSError, ValueError) as error:
        print('S1 Stage A port refused:', error, file=sys.stderr)
        raise SystemExit(1) from error
