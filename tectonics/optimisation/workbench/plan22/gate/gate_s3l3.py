"""Combined qualification gate for n12f-r1: S3 + L3 (+ S1 Stage A) composed onto the p1820c-r4 helpers.

    python -B gate_s3l3.py verify ROOT --paths PATHS.json   pins, applier, compositions and the fail-closed self-test; no suites
    python -B gate_s3l3.py run ROOT --paths PATHS.json      the same, then every suite; writes ROOT/GATE-RESULT.json

ROOT must not exist and should be short (MAX_PATH: the owner layout nests five folders). Inputs are only read.
PATHS.json supplies locations only; source/port identities and expected coverage are fixed below.

Inputs, all pinned below (any moved digest refuses before anything runs):
- base p1820c-r4: composition.json, helpers tree (405), src tree (287);
- ports: S3 port-r3 (Plan 21), L3 port-r3 (Plan 22), S1 Stage A (Plan 30, candidate) - each PORT.json, every
  packaged row and diff, every declared dependency at its r4 bytes. A dependency another port's row replaces is
  refused unless declared below (S3 imports record_views, which the L3 row replaces: re-proved by the S3 suites);
- the applier: require/lines_of/apply_diff extracted from the replay constructor and checked by text digest;
- the owner layout's runtime-src tree and test_materialise_endpoint, the heat-repair test root, the gate children.

Arms (each a full composition): b = base; c3 = base + S3 + L3; c4 = c3 + S1 Stage A; n = c3 with the S3 runtime row
reverted (the S3 negative fixture); m = c3 with a planted reader mutant (the gate cases' negative control).

Suites (children use the configured interpreter with PYTHONHASHSEED=0 and -B -P; no -I, as they import the runtime):
- composition layout W/<arm>/ac/c (suite_check.py): the 15-module identity set plus test_interval_store_set on
  b, c3, c4; test_l3_carried_pages on c3, c4; test_s1a_guarded_read on c4 (its L3S1ContractTests are the S1 side
  of contract C-L3S1);
- S3 layout S/<arm> (s3_child.py): lazy 19, consumers 17, own (L3) 22 on c3, c4; negative on n;
  Composition-layout suites get PYTHONPATH = suite_check's own three import roots, so their real-process children
  (the interval crash cases) import what the parent imports;
- owner layout O/<arm> (suite_check.py): the identity modules whose source names runtime-integration-r1, in the
  layout they were written for (helpers in resumability-r1 beside the owner runtime-src). Only here do the mesh v3
  close path and the step9a/segment/compact real-process cases run. An import error in the owner layout, or a
  module without one import-clean layout, fails the gate (a layout must not hide coverage);
- gate cases (gate_child.py + test_gate_l3_store.py): G0-G2 on c3, c4 (3/3); on m they must fail. G1 replaces an
  EVICTED interval file, unmocked, between batches while its pages are carried (a resident file cannot be replaced
  on Windows); G2 is the compact_store.py:612 nested-batch shape.
Acceptance is stated in evaluate(). Nothing is timed; three children run at a time.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PY = None  # configured by --paths; importing the evaluator reads no external inputs
OWNER_REL = 'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014'
HEAT_REL = 'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests'

BASE = None
BASE_COMPOSITION_JSON = 'ddd44a8857d17b0ef7910a70e86cb55da04e222ccaa284931d216502612b0bea'
BASE_TREES = {'helpers': ('eb58d2313e7aa35517b6f038a511d0ffe221c7afbe937abaac628bc94fe11674', 405),
              'src': ('76c9171c26876485bd281e9df392ea001c639395d894c7a12f15e35177f095e3', 287)}
APPLIER = None
APPLIER_FILE = '1d7fdcb3b4d1d20274a01364d3068cdee77e996b23de1c73f6423d3f055f1110'
APPLIER_TEXT = '29d6810c99a5c95f8886f5bb21dade46be90fc1d15f3a96565886f6389579483'
PORT_PINS = {  # name: (PORT.json sha256, row format); locations cannot override these pins
    's3': ('f4ddf752c517be423b18335c3e3bc7fc51b10fb939fbbffa62d18d3ea628081f', 's3'),
    'l3': ('fb2636dbd1f70dd6042f65a1efe235fd6249e6337a3aba4fe4b67f1acab59230', 'l3'),
    's1a': ('5d3f37263468bf9ccfeebadaeec13c4c2a1397081865b3e3088719d144f52ad3', 's1a'),
}
PORTS = {}

S3_DEPENDENCIES = {  # S3 PORT.json closure.after.helper, at their r4 bytes (gate-pinned)
    'helpers/compact_contracts.py': '0aabad86c1ccffd79b79f8aa320c7406a0406c659105f21838beb37c5bc69f6e',
    'helpers/content_cache.py': '97c5d69fc79ba19339c144a5221f83a16760cc94f8d9c7d89f2cf0e792b6645a',
    'helpers/record_tables.py': '56f18e8fb1403238ac73fa4f238f60c3aaf844936d11a652c24d6aa3d95701c7',
    'helpers/record_views.py': 'a6bbb81dcc88c7f4b84272929922a8e4f702694163b18d18c26d3b76a86f89bd',
    'helpers/spatial_indexed_patch.py': '83ca173c950094c45c5d10922fd93a27f1b9cc8d6cd525be345442df21ae6c83',
    'helpers/spatial_records_patch.py': '77abd1a2e9a76071f4997ee5ff2237b3af13db6b9d12da0eaa60e6b4fb23a1b7',
}
# (port, dependency) -> the port whose row may replace it, and why that is re-proved here.
DEPENDENCY_EXCEPTIONS = {('s3', 'helpers/record_views.py'): ('l3', 'S3 lazy/consumers suites on c3 and c4')}
OWNER_RUNTIME = None
OWNER_RUNTIME_TREE = ('d04577399bec9a62b71cafadf9415351520e4cc5dd22b96d5c386f3a032ebab1', 234)
OWNER_ENDPOINT = None
OWNER_ENDPOINT_SHA = '350299b08b98b09abbced20992b1b0a1ffebe4e98343280de141ff3a955969f7'
LEGACY_SPATIAL_OWNER = '0973cb3f0bccc833f476bbfa555864d62a6f906035b871f73e9d8a9c1ded9559'
COMPOSED_SPATIAL_OWNER = '74caa12601416e2058a307afc8b72b288b8a17e5d7ce45cd03048fad90def85f'
HEAT = None
HEAT_TREE = ('d1f4edf9ed967f931fe57e1418297fb1897774e6e21fe90b4197555ec0af6b5b', 579)
HARNESS = {  # gate children, pinned like every other input
    'suite_check': (None,
                    '03ea7acdb491774bb34ee6cb7b6e6b689d849a5b93629a6975b5e73379ac69ea'),
    's3_child': (HERE / 's3_child.py', '78549f5a694c657db1b40491d57ce8b2736b10f1e6b3ae61edee176c567b20ac'),
    'gate_child': (HERE / 'gate_child.py', 'db3c5e799b28c4695fb647f4a4eb98e866b751d62e313c5ab0362d002b1dd079'),
    'gate_cases': (HERE / 'test_gate_l3_store.py', '17294a3a3e2afe18223cd31ba5f68bccfac80e2818676b86f79cfbf4414a5e5d'),
}
IDENTITY = ('test_record_views', 'test_mesh_tables', 'test_record_tables', 'test_item14_page_layer', 'test_mesh_v3',
            'test_mesh_v3_header_column', 'test_mesh_v3_preparation', 'test_b17_binding_directory',
            'test_compact_header_retention', 'test_compact_store', 'test_private_heat_snapshot_store_r4',
            'test_s1_sealed_read', 'test_segment_store', 'test_step7b_record_reuse', 'test_step9a_pending')
LONGEST_PATH = 230  # leaves the suites' temporary names under MAX_PATH (260)
EXPECTED = {'test_l3_carried_pages': 22, 'test_s1a_guarded_read': 26, 'lazy': 19, 'consumers': 17, 'own': 22,
            'negative': 19, 'gate_cases': 3}
# m arm: the carry adopted before the verified read is entered (the gate cases must catch it).
MUTANT = ('            registry = None\n            try:\n                with self.segment.verified_read():\n'
          '                    if outer:\n                        registry = self._take_carried()\n',
          '            registry = self._take_carried() if outer else None\n            try:\n'
          '                with self.segment.verified_read():\n                    if outer:\n'
          '                        pass\n')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


PATH_KEYS = frozenset(('base', 'applier', 's3_port', 'l3_port', 's1a_port', 'owner_runtime',
                       'owner_endpoint', 'heat_tests', 'suite_check', 'python'))
DIRECTORY_KEYS = frozenset(('base', 'owner_runtime', 'heat_tests'))


def configure_paths(config):
    """Read only explicit locations; reject missing/extra keys, relative paths and wrong input kinds."""
    global BASE, APPLIER, OWNER_RUNTIME, OWNER_ENDPOINT, HEAT, PY, PORTS
    values = json.loads(Path(config).read_text(encoding='utf-8'))
    require(isinstance(values, dict) and set(values) == PATH_KEYS,
            'path config must contain exactly: ' + ', '.join(sorted(PATH_KEYS)))
    paths = {}
    for name, value in values.items():
        require(isinstance(value, str) and value.strip(), f'{name}: expected an absolute path string')
        path = Path(value)
        require(path.is_absolute(), f'{name}: path must be absolute')
        path = path.resolve()
        if name in DIRECTORY_KEYS:
            require(path.is_dir(), f'{name}: expected an existing directory')
        else:
            require(path.is_file(), f'{name}: expected an existing file')
        if name.endswith('_port'):
            require(path.name == 'PORT.json', f'{name}: name the exact PORT.json file, not its directory')
        paths[name] = path
    require(paths['python'] == Path(sys.executable).resolve(),
            'python: run this gate with the configured interpreter; children use that same executable')
    BASE, APPLIER, OWNER_RUNTIME, OWNER_ENDPOINT, HEAT, PY = (
        paths[name] for name in ('base', 'applier', 'owner_runtime', 'owner_endpoint', 'heat_tests', 'python'))
    PORTS = {name: (paths[name + '_port'], pin, form) for name, (pin, form) in PORT_PINS.items()}
    HARNESS['suite_check'] = (paths['suite_check'], HARNESS['suite_check'][1])
    return paths


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def files_of(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(Path(root).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def tree_digest(files):
    return digest(''.join(f'{name}\0{pin}\n' for name, pin in sorted(files.items())).encode())


def pinned(path, pin, label):
    data = Path(path).read_bytes()
    require(pin is None or digest(data) == pin, f'{label} digest moved: {path} {digest(data)} != {pin}')
    return data


def load_applier(path=None, file_pin=APPLIER_FILE, text_pin=APPLIER_TEXT):
    """require/lines_of/apply_diff from the replay constructor, verbatim (the S3 port's applier record)."""
    source = pinned(APPLIER if path is None else path, file_pin, 'constructor').decode('utf-8')
    tree = ast.parse(source)
    parts = []
    for name in ('require', 'lines_of', 'apply_diff'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        segment = ast.get_source_segment(source, node)
        require(segment is not None, f'constructor function not found: {name}')
        parts.append(str(segment))
    text = '\n\n\n'.join(parts) + '\n'
    require(digest(text.encode('utf-8')) == text_pin, 'applier text moved')
    space = {'re': re}
    exec(compile(text, 'construct_n12c-applier', 'exec'), space)  # noqa: S102 - pinned constructor text
    return space['apply_diff']


def port_rows(name, ports):
    """Normalised rows [(row, kind, before, after, packaged, diff, diff_sha)] and dependency pins of one port."""
    path, pin, form = ports[name]
    data = json.loads(pinned(path, pin, f'{name} PORT.json'))
    rows, root = [], Path(path).parent
    if form == 'l3':
        base = root.parent
        for r in data['rows']:
            rows.append((r['row'], {'swap': 'replace'}.get(r['kind'], r['kind']), r['before_sha256'], r['sha256'],
                         base / r['path'], base / r['diff'] if r['kind'] == 'diff' else None, r.get('diff_sha256')))
        deps = data['base']['dependencies_pinned']
    elif form == 's3':
        for r in data['rows']:
            packaged = 'rows/' + r['row']
            require(data['files'].get(packaged) == r['output_sha256'], f's3 files map disagrees: {packaged}')
            rows.append((r['row'], r['kind'], r.get('input_sha256'), r['output_sha256'], root / packaged,
                         root / r['diff'] if r['kind'] == 'diff' else None, r.get('diff_sha256')))
        deps = S3_DEPENDENCIES
    else:
        for row, r in data['rows'].items():
            rows.append((row, r['kind'], r['before'], r['after'], root / 'port' / row,
                         root / 'port' / r['diff'] if r['diff'] else None, r['diff_sha256']))
        deps = data['dependencies']
    for row, kind, before, _after, _packaged, diff, _diff_sha in rows:
        require(kind in ('replace', 'diff', 'add') and (kind == 'add') == (before is None)
                and (kind == 'diff') == (diff is not None), f'{name} row malformed: {row}')
    return rows, deps


def compose(base_helpers, names, out_helpers, apply_diff, ports=None):
    """Copy base_helpers to out_helpers (new) and apply the named ports' rows; refuse on any moved pin."""
    ports = ports or PORTS
    base = Path(base_helpers).parent
    table, deps, touched = [], {}, {}
    for name in names:
        rows, port_deps = port_rows(name, ports)
        for row in rows:
            require(row[0] not in touched, f'rows overlap: {row[0]} ({touched.get(row[0])} and {name})')
            touched[row[0]] = name
            table.append((name, *row))
        deps[name] = port_deps
    exceptions = []
    for name, port_deps in deps.items():
        for row, pin in port_deps.items():
            require(sha(base / row) == pin, f'{name} dependency moved: {row}')
            owner = touched.get(row)
            if owner is not None and owner != name:
                allowed = DEPENDENCY_EXCEPTIONS.get((name, row))
                require(allowed is not None and allowed[0] == owner,
                        f'{name} dependency {row} is replaced by the {owner} row (not declared)')
                exceptions.append(dict(port=name, dependency=row, replaced_by=owner, re_proof=(allowed or ('', ''))[1]))
    outputs = {}
    for name, row, kind, before, after, packaged, diff, diff_sha in table:
        target = base / row
        data = pinned(packaged, after, f'{name} packaged row {row}')
        if kind == 'add':
            require(not target.exists(), f'{name} added row already in the base: {row}')
        else:
            raw = pinned(target, before, f'{name} base row {row}')
            if kind == 'diff':
                require(apply_diff(raw, pinned(diff, diff_sha, f'{name} diff {row}'), row) == data,
                        f'{name} diff output differs from the packaged row: {row}')
        outputs[row] = data
    before_files = files_of(base_helpers)
    shutil.copytree(base_helpers, out_helpers, ignore=shutil.ignore_patterns('__pycache__'))
    for row, data in outputs.items():
        (Path(out_helpers).parent / row).write_bytes(data)
    after_files = files_of(out_helpers)
    expected = dict(before_files)
    expected.update({row.removeprefix('helpers/'): digest(data) for row, data in outputs.items()})
    require(after_files == expected, 'composed helpers differ from base + rows')
    return dict(ports=list(names), rows=[dict(port=n, row=r, kind=k, before=b, after=a) for n, r, k, b, a, *_ in table],
                dependency_exceptions=exceptions, helpers=len(after_files), helpers_tree=tree_digest(after_files))


def copy_checked(source, target, pin=None):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__'))
    got = files_of(target)
    require(got == files_of(source), f'copy differs: {target}')
    if pin is not None:
        require((tree_digest(got), len(got)) == pin, f'tree moved: {source}')
    return tree_digest(got)


def check_inputs():
    pinned(BASE / 'composition.json', BASE_COMPOSITION_JSON, 'base composition.json')
    for key, pin in BASE_TREES.items():
        got = files_of(BASE / key)
        require((tree_digest(got), len(got)) == pin, f'base {key} tree moved')
    got = files_of(OWNER_RUNTIME)
    require((tree_digest(got), len(got)) == OWNER_RUNTIME_TREE, 'owner runtime-src tree moved')
    pinned(OWNER_ENDPOINT, OWNER_ENDPOINT_SHA, 'owner test_materialise_endpoint')
    pinned(OWNER_RUNTIME / 'atlas_tectonics/integration_spatial_owner.py', LEGACY_SPATIAL_OWNER, 'owner spatial owner')
    pinned(BASE / 'src/atlas_tectonics/integration_spatial_owner.py', COMPOSED_SPATIAL_OWNER, 'composed spatial owner')
    got = files_of(HEAT)
    require((tree_digest(got), len(got)) == HEAT_TREE, 'heat-repair test tree moved')
    return {name: digest(pinned(path, pin, name)) for name, (path, pin) in HARNESS.items()}


def self_test(root, apply_diff):
    """Fail-closed cases on scratch copies under root/x; each must be refused with its reason."""
    x = root / 'x'
    x.mkdir()
    results = []

    def refused(label, needle, action):
        try:
            action()
            ok, text = False, 'accepted'
        except ValueError as error:
            text = str(error)
            ok = needle in text
        results.append(dict(case=label, refused=ok, reason=text[:160]))

    base = BASE / 'helpers'
    l3_json, l3_pin, l3_form = PORTS['l3']
    wrong = {**PORTS, 'l3': (l3_json, '0' * 64, l3_form)}
    refused('port json pin moved', 'l3 PORT.json digest moved',
            lambda: compose(base, ['l3'], x / 'a/helpers', apply_diff, wrong))
    pkg = x / 'pkg/n12f/r3'
    shutil.copytree(l3_json.parent, pkg, ignore=shutil.ignore_patterns('mutants', 'tools', 'checks'))
    with (pkg / 'helpers/record_views.py').open('ab') as stream:
        stream.write(b'# tamper\n')
    tampered = {**PORTS, 'l3': (pkg / 'PORT.json', l3_pin, l3_form)}
    refused('packaged row tampered', 'packaged row helpers/record_views.py',
            lambda: compose(base, ['l3'], x / 'b/helpers', apply_diff, tampered))
    drift = x / 'drift/helpers'
    shutil.copytree(base, drift)
    with (drift / 'content_cache.py').open('ab') as stream:
        stream.write(b'# drift\n')
    refused('dependency drift', 'dependency moved: helpers/content_cache.py',
            lambda: compose(drift, ['l3'], x / 'c/helpers', apply_diff))
    doubled = {**PORTS, 'l3b': PORTS['l3']}
    refused('overlapping rows', 'rows overlap',
            lambda: compose(base, ['l3', 'l3b'], x / 'd/helpers', apply_diff, doubled))
    undeclared = dict(DEPENDENCY_EXCEPTIONS)
    DEPENDENCY_EXCEPTIONS.clear()
    try:
        refused('undeclared dependency replacement', 'is replaced by the l3 row',
                lambda: compose(base, ['s3', 'l3'], x / 'e/helpers', apply_diff))
    finally:
        DEPENDENCY_EXCEPTIONS.update(undeclared)
    constructor = x / 'construct_n12c.py'
    constructor.write_bytes(APPLIER.read_bytes().replace(b'Zero-length diff hunks are refused',
                                                         b'Zero-length diff hunks refused'))
    refused('applier text moved', 'applier text moved',
            lambda: load_applier(constructor, sha(constructor), APPLIER_TEXT))
    for leftover in ('a', 'b', 'c', 'd', 'e'):
        require(not (x / leftover).exists() or not any((x / leftover).rglob('*.py')),
                f'a refused compose left files: {leftover}')
    return results


def build(root, apply_diff):
    arms = {}
    w, s, o = root / 'w', root / 's', root / 'o'
    base = BASE / 'helpers'
    plan = {'b': [], 'c3': ['s3', 'l3'], 'c4': ['s3', 'l3', 's1a'], 'n': ['s3', 'l3'], 'm': ['s3', 'l3']}
    for arm, names in plan.items():
        comp = w / arm / 'ac/c'
        comp.mkdir(parents=True)
        arms[arm] = compose(base, names, comp / 'helpers', apply_diff)
        copy_checked(BASE / 'src', comp / 'src', BASE_TREES['src'])
        copy_checked(HEAT, w / arm / HEAT_REL, HEAT_TREE)
    svp = w / 'n/ac/c/helpers/spatial_validation_patch.py'
    svp.write_bytes((base / 'spatial_validation_patch.py').read_bytes())
    arms['n']['reverted'] = dict(row='helpers/spatial_validation_patch.py', sha256=sha(svp))
    views = w / 'm/ac/c/helpers/record_views.py'
    text = views.read_text(encoding='utf-8')
    require(text.count(MUTANT[0]) == 1, 'mutant anchor not found once')
    views.write_text(text.replace(MUTANT[0], MUTANT[1]), encoding='utf-8', newline='\n')
    arms['m']['mutant'] = dict(row='helpers/record_views.py', sha256=sha(views), what='carry adopted before entry')
    for arm in ('c3', 'c4', 'n'):
        copy_checked(w / arm / 'ac/c/helpers', s / arm / 'res/helpers')
        copy_checked(BASE / 'src', s / arm / 'runtime-integration-r1/runtime-src', BASE_TREES['src'])
    for arm in ('b', 'c3', 'c4'):
        task = o / arm
        copy_checked(w / arm / 'ac/c/helpers', task / OWNER_REL / 'resumability-r1/helpers')
        shutil.copyfile(OWNER_ENDPOINT, task / OWNER_REL / 'resumability-r1/test_materialise_endpoint.py')
        copy_checked(OWNER_RUNTIME, task / OWNER_REL / 'runtime-integration-r1/runtime-src', OWNER_RUNTIME_TREE)
        (task / '_t').mkdir()
    (root / '_t').mkdir()  # the item-14 fixture's folder for the composition layout (helpers.parents[4] / '_t')
    longest = max(len(str(p)) for p in root.rglob('*'))
    require(longest < LONGEST_PATH, f'paths too long for the suites\' temporary names: {longest}')
    return arms, longest


def child_env(pythonpath=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    if pythonpath:
        env['PYTHONPATH'] = os.pathsep.join(map(str, pythonpath))
    return env


def owner_aware():
    """Identity modules that locate the owner runtime themselves (their base source names runtime-integration-r1)."""
    return [m for m in (*IDENTITY, 'test_interval_store_set')
            if 'runtime-integration-r1' in (BASE / 'helpers' / f'{m}.py').read_text(encoding='utf-8')]


def jobs(root, owner_mods):
    w, s, o = root / 'w', root / 's', root / 'o'
    out = []
    for arm in ('b', 'c3', 'c4'):
        mods = list(IDENTITY) + ['test_interval_store_set']
        mods += ['test_l3_carried_pages'] if arm != 'b' else []
        mods += ['test_s1a_guarded_read'] if arm == 'c4' else []
        comp = w / arm / 'ac/c'
        roots = [comp / 'helpers', comp / 'src', w / arm / HEAT_REL]  # suite_check's own sys.path roots
        out += [dict(id=f'w-{arm}-{m}', kind='suite', arm=arm, layout='composition', module=m,
                     helpers=comp / 'helpers', pythonpath=roots) for m in mods]
        out += [dict(id=f'o-{arm}-{m}', kind='suite', arm=arm, layout='owner', module=m,
                     helpers=o / arm / OWNER_REL / 'resumability-r1/helpers') for m in owner_mods]
    s3_modes = ('lazy', 'consumers', 'own')
    for arm, modes in (('c3', s3_modes), ('c4', s3_modes), ('n', ('negative',))):
        out +=[dict(id=f's-{arm}-{mode}', kind='s3', arm=arm, layout='s3', module=mode, fixture=s / arm)
                for mode in modes]
    out += [dict(id=f'g-{arm}', kind='gate', arm=arm, layout='composition', module='gate_cases',
                 helpers=w / arm / 'ac/c/helpers') for arm in ('c3', 'c4', 'm')]
    return out


def command(job, root):
    tmp = root / 't' / job['id']
    result = root / 'out' / (job['id'] + '.json')
    if job['kind'] == 'suite':
        tmp.mkdir(parents=True)
        return [str(PY), '-B', '-P', str(HARNESS['suite_check'][0]), str(job['helpers']), str(tmp), job['module']], None
    if job['kind'] == 'gate':
        tmp.mkdir(parents=True)
        return [str(PY), '-B', '-P', str(HARNESS['gate_child'][0]), str(job['helpers']), str(tmp),
                str(HARNESS['gate_cases'][0]), str(EXPECTED['gate_cases'])], None
    helpers, native = job['fixture'] / 'res/helpers', job['fixture'] / 'runtime-integration-r1/runtime-src'
    legacy = OWNER_RUNTIME / 'atlas_tectonics/integration_spatial_owner.py'
    names = ('test_s3_lazy_rows.py', 'test_d1b_carried_start.py', 'test_spatial_compact_cells.py',
             'spatial_validation_patch.py', 'record_views.py', 'test_l3_carried_pages.py')
    pins = {str(helpers / n): sha(helpers / n) for n in names}
    pins[str(native / 'atlas_tectonics/integration_spatial_owner.py')] = COMPOSED_SPATIAL_OWNER
    pins[str(legacy)] = LEGACY_SPATIAL_OWNER
    spec = dict(mode=job['module'], helpers=str(helpers), native=str(native), fixture_root=str(job['fixture']),
                legacy_owner=str(legacy), pins=pins, output=str(result), expected_runs=EXPECTED[job['module']])
    path = root / 'spec' / (job['id'] + '.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(spec, indent=1), encoding='utf-8')
    return [str(PY), '-B', '-P', str(HARNESS['s3_child'][0]), str(path)], result


def run_one(job, root):
    argv, result = command(job, root)
    log = root / 'log'
    started = time.monotonic()
    with (log / (job['id'] + '.out')).open('wb') as out, (log / (job['id'] + '.err')).open('wb') as err:
        try:
            code = subprocess.run(argv, stdout=out, stderr=err, env=child_env(job.get('pythonpath')), cwd=str(root),
                                  timeout=1200, check=False).returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    seconds = round(time.monotonic() - started, 1)
    text = (log / (job['id'] + '.out')).read_text(encoding='utf-8', errors='replace').strip()
    try:
        parsed = json.loads((result.read_text(encoding='utf-8') if result else text.splitlines()[-1]))
    except (OSError, ValueError, IndexError):
        parsed = None
    record = {k: (str(v) if isinstance(v, Path) else v) for k, v in job.items()}
    record.update(argv=argv, exit=code, seconds=seconds, result=parsed)
    return record


def outcome(record) -> dict:
    r = record['result'] or {}
    if record['kind'] == 's3':
        outcomes = r.get('outcomes') or {}
        no_skips = len(outcomes) == r.get('testsRun') and all(
            value in ('ok', 'failure', 'error') for value in outcomes.values())
        return dict(run=r.get('testsRun'), bad=r.get('failed_or_error'),
                    skipped=sum(value == 'skip' for value in outcomes.values()),
                    ok=r.get('expected_outcome') is True and no_skips)
    ok = (r.get('failures') == 0 and r.get('errors') == 0 and r.get('clean') is True
          and r.get('skipped') == 0)
    if record['kind'] == 'gate':  # gate_child also refuses foreign modules and a wrong run count
        ok = ok and r.get('passed') is True
    return dict(run=r.get('run'), failures=r.get('failures'), errors=r.get('errors'),
                skipped=r.get('skipped'), bad=sorted(r.get('bad', {})),
                clean=r.get('clean'), ok=ok)


def evaluate(records, s1a_changed, owner_mods):
    by = {rec['id']: rec for rec in records}
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(check=name, ok=bool(ok), detail=detail))

    for rec in records:
        check(f"{rec['id']} produced a result", rec['result'] is not None, f"exit {rec['exit']}")
        expected_exit = 1 if rec['id'] == 'g-m' else 0
        check(f"{rec['id']} exited as expected",
              type(rec['exit']) is int and rec['exit'] == expected_exit,
              dict(actual=rec['exit'], expected=expected_exit))
        o = outcome(rec)
        check(f"{rec['id']} has executed test coverage",
              type(o['run']) is int and type(o['skipped']) is int
              and 0 <= o['skipped'] < o['run'], o)
    hidden = sorted(f"{rec['id']}: {name}" for rec in records if rec['kind'] == 'suite' and rec['layout'] == 'owner'
                    for name, line in ((rec['result'] or {}).get('bad') or {}).items() if 'ModuleNotFoundError' in line)
    check('owner layout: no failure is an import error (coverage is not hidden by the layout)', not hidden, hidden[:6])
    mods = list(IDENTITY) + ['test_interval_store_set']

    def import_clean(record_id):
        r = by.get(record_id, {}).get('result')
        return r is not None and not any('ModuleNotFoundError' in line for line in (r.get('bad') or {}).values())

    uncovered = [m for m in mods if not any(import_clean(f'{p}-b-{m}') for p in ('w', 'o') if f'{p}-b-{m}' in by)]
    check('every identity module runs free of import errors in at least one layout', not uncovered, uncovered)
    for layout, prefix, layout_mods in (('composition', 'w', mods), ('owner', 'o', owner_mods)):
        for m in layout_mods:
            b = outcome(by[f'{prefix}-b-{m}'])
            for arm in ('c3', 'c4'):
                c = outcome(by[f'{prefix}-{arm}-{m}'])
                if arm == 'c4' and m in s1a_changed:
                    # S1 changes expectations/decorators, not test membership.
                    ok = (set(c['bad']) <= set(b['bad']) and c['clean']
                          and c['run'] == b['run'] and c['skipped'] == b['skipped'])
                    check(f'{layout} {m}: c4 (S1 Stage A changes this test) fails nothing b passes', ok,
                          f"b {b['run']}/{b['bad']} c4 {c['run']}/{c['bad']}")
                else:
                    keys = ('run', 'failures', 'errors', 'skipped', 'bad')
                    ok = {k: c[k] for k in keys} == {k: b[k] for k in keys} and c['clean']
                    check(f'{layout} {m}: {arm} outcome equals b', ok, dict(b=b, c=c))
    for arm in ('c3', 'c4'):
        o = outcome(by[f'w-{arm}-test_l3_carried_pages'])
        check(f'{arm} test_l3_carried_pages all pass', o['ok'] and o['run'] == EXPECTED['test_l3_carried_pages'], o)
        for mode in ('lazy', 'consumers', 'own'):
            o = outcome(by[f's-{arm}-{mode}'])
            check(f'{arm} S3 layout {mode}', o['ok'] and o['run'] == EXPECTED[mode], o)
        o = outcome(by[f'g-{arm}'])
        check(f'{arm} gate cases G0-G2 pass', o['ok'] and o['run'] == EXPECTED['gate_cases'], o)
    o = outcome(by['w-c4-test_s1a_guarded_read'])
    check('c4 test_s1a_guarded_read all pass', o['ok'] and o['run'] == EXPECTED['test_s1a_guarded_read'], o)
    o = outcome(by['s-n-negative'])
    check('n S3 negative detects the missing runtime row', o['ok'] and o['run'] == EXPECTED['negative'], o)
    o = outcome(by['g-m'])
    check('m gate cases catch the adopt-before-entry mutant', o['run'] == EXPECTED['gate_cases'] and not o['ok']
          and (o['failures'] or 0) + (o['errors'] or 0) > 0, o)
    return checks


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('verify', 'run'))
    parser.add_argument('root', help='new, short output directory outside every input tree')
    parser.add_argument('--paths', required=True, help='JSON file with the ten explicit input locations')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    require(not root.exists(), 'ROOT must not exist')
    locations = configure_paths(args.paths)
    input_roots = [path if key in DIRECTORY_KEYS else path.parent for key, path in locations.items()]
    require(not any(path == root or path in root.parents for path in (*input_roots, HERE)),
            'ROOT must lie outside every input tree and the gate directory')
    started = time.strftime('%Y-%m-%d %H:%M:%S')
    harness = check_inputs()
    apply_diff = load_applier()
    root.mkdir(parents=True)
    selftest = self_test(root, apply_diff)
    require(all(case['refused'] for case in selftest), 'fail-closed self-test: ' + json.dumps(selftest))
    arms, longest = build(root, apply_diff)
    s1a_changed = {row['row'].removeprefix('helpers/').removesuffix('.py') for row in arms['c4']['rows']
                   if row['port'] == 's1a' and row['kind'] != 'add'}
    owner_mods = owner_aware()
    result: dict = {}
    result.update(schema='plan22.n12f-gate.s3-l3-s1a.r3', started=started, command=[sys.executable, '-B', *sys.argv],
                  gate=dict(path=str(Path(__file__).resolve()), sha256=sha(__file__)), root=str(root),
                  pins=dict(base=dict(root=str(BASE), composition_json=BASE_COMPOSITION_JSON, trees=BASE_TREES),
                            ports={k: dict(json=str(v[0]), sha256=v[1]) for k, v in PORTS.items()},
                            applier=dict(constructor=str(APPLIER), file=APPLIER_FILE, text=APPLIER_TEXT),
                            s3_dependencies=S3_DEPENDENCIES, owner_runtime_tree=OWNER_RUNTIME_TREE,
                            owner_endpoint=OWNER_ENDPOINT_SHA, heat_tests_tree=HEAT_TREE, harness=harness),
                  self_test=selftest, arms=arms, longest_path=longest, owner_layout_modules=owner_mods)
    if args.mode == 'verify':
        result['verdict'] = 'VERIFIED_NOT_RUN'
    else:
        (root / 'log').mkdir()
        (root / 'out').mkdir()
        with ThreadPoolExecutor(max_workers=3) as pool:
            records = list(pool.map(lambda job: run_one(job, root), jobs(root, owner_mods)))
        checks = evaluate(records, s1a_changed, owner_mods)
        outside = [root / '_t', *(root / 'o' / arm / '_t' for arm in ('b', 'c3', 'c4'))]
        result.update(records=records, checks=checks, failed=[c for c in checks if not c['ok']],
                      item14_fixture_folders={str(p): len(list(p.iterdir())) for p in outside},
                      finished=time.strftime('%Y-%m-%d %H:%M:%S'),
                      verdict='PASS' if all(c['ok'] for c in checks) else 'FAIL')
    with (root / 'GATE-RESULT.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=1, default=str)
        stream.write('\n')
    print(result['verdict'], 'checks', len(result.get('checks', [])), 'failed', len(result.get('failed', [])),
          'result', sha(root / 'GATE-RESULT.json'))
    return 0 if result['verdict'] in ('PASS', 'VERIFIED_NOT_RUN') else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError) as error:
        print('gate refused:', error, file=sys.stderr)
        raise SystemExit(2) from error
