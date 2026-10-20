"""Step 10 (WP9) reviewed composition r3 candidate route: assemble_r2 b1069d77 with explicit, staged inputs.

Successor of R/composed-checks/assemble_r2.py b1069d77 (unchanged), for the Plan 02 gen-r3 candidate (Claude,
private retained decision). STAGING ONLY. The composition logic, the d2 dry-run equality, EXPECTED_HEAT/COLD, the stage
asserts, the sys.modules audit and the write-once target are assemble_r2's. The changes are:
  a. Explicit root. ROOT is a staged R-shaped tree (not live R): its top-level files must equal a pinned generation
     record row for row (no extra top-level module), and it replaces live R as the helper root, the transform
     import root and the audited tree. T, C, G, RC1, I_RUNTIME and H_ROOT are derived from ROOT exactly as live R's
     modules derive them (T = ROOT.parents[3]); nothing falls back to live R.
  b. Explicit target name (composed-rN), recorded in place of the fixed 'composed-r2'. The target must be new and
     outside live R.
  c. Explicit input binding. Every file under ROOT/compact-geometry-r1, every *.py in geometry-growth-r1/transforms,
     endpoint-checkpoints, composed-r1/helpers and composed-r1/ram, every file in composed-r1/runtime-src, and the two
     I files must equal the binding's pin, and the binding must pin nothing else. C, G and endpoint-checkpoints must
     be real folders inside ROOT (no link), because their modules resolve R from their own path. The binding names
     where each pinned byte string was located and in what role; a byte string located in a composition's output
     (any composed-rN folder other than the RC1 base composed-r1) is never accepted as a 'composer-input'
     location, and the located bytes must equal the pin. The binding's
     'selection' must be a non-empty statement for --pin/--compose: locating bytes does not select them.
  Every module loaded during composition must lie in a bound tree, ROOT's top level, H_ROOT or the interpreter.
r3 boundary revision r2 (Codex #1362; review W/work/plan02/ASSEMBLE-R3-REVIEW-r1.md 073eaab0). assemble-r3-r1's
assemble_r3.py af4a6fc0 stays unchanged.
r3 heat-reference revision (Codex private retained decision, option b; classification T/ac/plan02/pin-delta-r1 dba39add).
assemble-r3-r2's assemble_r3.py 4719eb61 stays unchanged.
  5. Two heat roots. H_ROOT stays the staged input-reading root (ROOT.parents[2]/heat-repair-20261007, the audit
     exception). H_REFERENCE, the permanent historical reference root passed to construct_compact_successor, is
     always live H (LIVE_R.parents[2]/heat-repair-20261007, by its literal name): the emitted helpers bind its
     absolute paths, never the stage's. ROOT_RULE requires a permanent root. configure() refuses unless live H is a
     real folder (no link up to its drive), outside the staged root, and the staged H_ROOT exists and resolves to
     exactly live H. A different target, a copy with equal bytes or a missing link is refused; nothing falls back.
  6. No staging-path leakage. Every emitted helper is refused if its text contains the staged workspace root
     (ROOT.parents[3]) or the staged H_ROOT, in plain or repr (escaped) form.
  7. The reviewed record's 'staged' adds heat_reference (the live H path) beside the staged H_ROOT, so --compose
     re-verifies both against --pin.
  1. Selected-set audit. The selected set is the generation rows (ROOT/<row>) plus the binding's pins. The binding
     must cover the required set (c) and may pin further existing files under ROOT or I_RUNTIME as an explicit
     dependency set. A module loaded during composition (or already loaded when composition starts) from anywhere
     except the two explicit exceptions must be a selected path with its pinned bytes, so --pin enrols only selected
     files. The exceptions are H_ROOT (the reference root, pinned by private_heat_bundle.REFERENCE_PINS) and the
     interpreter's prefixes; they are allowed and not recorded, as in r2. The audit compares named (absolute) paths;
     it is not a proof that every executed instruction came from the selected bytes (pre-existing r2 limitation).
  2. Target containment is checked on the resolved path as well as the named one, and no target ancestor may be a
     link, so a junction cannot route the target into the staged root or live R.
  3. Generation rows are plain, case-insensitively unique basenames with a closed row schema and a 64-hex sha256.
  4. Provenance roles are classified on both the named and the resolved location, case-insensitively, so an alias
     or a differently cased composed-rN folder is still a composition's output location.

Usage (all modes take the same bindings; --check runs only the binding checks, imports and composes nothing):
  python -B assemble_r3.py MODE --root ROOT --generation G --generation-sha256 HEX
         --input-binding B --input-binding-sha256 HEX --target TARGET [--reviewed OUT] [--dry D2]
  MODE --check                      binding checks only (selection may be null)
  MODE --pin   --reviewed OUT --dry D2   record the reviewed inputs (as assemble_r2 --pin)
  MODE --compose --reviewed OUT     re-verify, compose and write TARGET once (as assemble_r2 --compose)

Base: composed-r1/runtime-src (RC1, the reviewed composition r1; coordinator decision 16 Oct
11:00). Chains (wp9-inventory-notes.md):
  workflow   RC1 -> transform_v2 -> transform_v3 -> spatial records -> spatial validation ->
             compact_restart_patch -> R2 rev4 -> R3 rev2 -> publish_mesh_patch
  spatial_owner  RC1 -> exchange_record_patch.holder_source -> spatial_validation_patch.owner_source
  mimetic_heat   I -> current mimetic_patch.mimetic_source (re-pin of RC1's)
  endpoint_checkpoints  the current companion file
  differential_mesh  differential_mesh_patch.transform
  the 11 live_memory_composition STAGES (apply_native)
  differential_geometry  the geometry six, order A (allow_unreviewed_input; parity on this output)
  parallel_results / q2_directed / moving_face_moments / reuse.py: the four pinned geometry transforms
Nothing here reads a store, launches science or grants admission. Text in, text out.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

# r3: live R is never an input root; binding locations there are only hashed. Roots are set by configure(ROOT).
LIVE_R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
              'continuation-repair-20261013/optimisation-20261014/resumability-r1')
LIVE_H = LIVE_R.parents[2] / 'heat-repair-20261007'
T = R = C = G = RC1 = S1 = I_RUNTIME = H_ROOT = H_REFERENCE = None
LIVE_TREES = ()
SELECTED = {}      # r3 boundary r2: norm(path) -> pinned sha256 (generation rows + binding pins), set by main
GENERATION_ROW_KEYS = {'sha256', 'origin', 'live_r_sha256', 'gen_r2_sha256'}
PKG = 'atlas_tectonics'
SCHEMA = 'atlas.private.resumable-reviewed-inputs.r3'
BINDING_SCHEMA = 'atlas.private.plan02-composer-input-binding.r1'
ROLES = ('composer-input', 'retained-composition-output', 'frozen-composition')
TARGET_NAME = re.compile(r'composed-r[1-9][0-9]*')
GEOMETRY_SIX = ('growth_successor', 'wp20_zero_certificate', 'items_11_15_off', 'wp23_rotation',
                'complementary_cut', 'progress_hooks')
GEOMETRY_PINNED = (('integration_parallel_results.py', 'complementary_cut_adopt'),
                   ('integration_q2_directed.py', 'q2_zero_test'),
                   ('integration_moving_face_moments.py', 'jets_convolution'),
                   ('reuse.py', 'source_handles'))
EXTRA_HELPERS = ('private_heat_original_joined_r8.py', 'original_joined_r8_transform.py',
                 'publish_mesh_patch.py', 'heat_token_transform.py', 'publication_token_transform.py')
# The compact heat successor (coordinator + Steps 8-9, 16 Oct ~11:20): production heat route,
# live_memory=True. Its emitted helpers must equal the g13 live-memory-on layout (g13l1), the
# reviewed same-call re-proof composition; checked here by 8-hex prefix. The r13 issuer value is
# g13l1's composed_r13_sha256_before_reference_insert (the layout's file 549dbc86 carries the
# control-only r12 reference functions, which production does not).
EXPECTED_HEAT = {'private_heat_native_issuer_r13.py': 'dbaeecae', 'private_heat_checkpoint_consumer_r10.py': 'aa4a3f8e',
                 'private_heat_restored_binding_r10.py': '53bd2c58', 'private_heat_snapshot_store_r4.py': '8d206973',
                 'private_heat_joined_consumer_r6.py': '86c30c5c', 'private_heat_functionals_parallel_r1.py': 'c2325429'}
EXPECTED_COLD = '6dad6f06'
# Coordinator, 16 Oct (from the Steps 8-9 finding): heat result IDs and metadata bind the ABSOLUTE
# paths of the helper sources, so a composition is used only from the root recorded here.
ROOT_RULE = ('permanent root: heat result IDs bind absolute helper source paths; never move or copy this '
             'composition for use; launchers refuse to run from any other root')


class Refused(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Refused(message)


def file_sha(path):
    return sha256(path.read_bytes()).hexdigest()


def text_sha(text):
    return sha256(text.encode('utf8')).hexdigest()


def rel(path):
    # r3: the named (absolute, unresolved) path, so a pinned link stays inside the staged workspace
    return Path(os.path.abspath(path)).relative_to(T).as_posix()


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def within(path, root):
    return norm(path) == norm(root) or norm(path).startswith(norm(root) + os.sep)


def resolved_within(path, root):
    return within(Path(path).resolve(), Path(root).resolve())


def linked(path, stop):
    """Whether path or any of its parents up to stop is a link or junction."""
    path = Path(os.path.abspath(path))
    while True:
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            return True
        if norm(path) == norm(stop) or path.parent == path:
            return False
        path = path.parent


def configure(root):
    """r3 (a): every working root derives from the staged ROOT, as live R's own modules derive them."""
    global T, R, C, G, RC1, S1, I_RUNTIME, H_ROOT, H_REFERENCE, LIVE_TREES
    root = Path(os.path.abspath(root))
    require(root.is_dir() and not linked(root, root.anchor), 'staged root must be a real folder: ' + str(root))
    require(not resolved_within(root, LIVE_R) and not resolved_within(LIVE_R, root),
            'the staged root must not be, contain or lie in live R')
    R = root
    T = R.parents[3]
    C, G, RC1, S1 = R / 'compact-geometry-r1', R / 'geometry-growth-r1', R / 'composed-r1', R / 's1'
    I_RUNTIME = R.parent / 'runtime-integration-r1' / 'runtime-src'
    H_ROOT = R.parents[2] / 'heat-repair-20261007'
    H_REFERENCE = heat_reference(H_ROOT, LIVE_H, R.parents[3])
    LIVE_TREES = (C, R, G)
    for real in (C, G, R / 'endpoint-checkpoints'):
        require(real.is_dir() and not linked(real, R), 'must be a real folder inside the staged root: ' + str(real))


def heat_reference(staged_h, live_h, stage):
    """r3 (5): the permanent reference root is live H; the staged H must resolve to exactly it."""
    staged_h, live_h = Path(os.path.abspath(staged_h)), Path(os.path.abspath(live_h))
    require(live_h.is_dir() and not linked(live_h, live_h.anchor), 'live H must be a real folder: ' + str(live_h))
    require(not resolved_within(live_h, stage) and not within(live_h, stage),
            'live H must lie outside the staged workspace: ' + str(live_h))
    require(norm(staged_h) != norm(live_h), 'the staged H must be the stage path, not live H itself')
    require(staged_h.exists(), 'staged H is missing: ' + str(staged_h))
    require(norm(staged_h.resolve()) == norm(live_h.resolve()) == norm(live_h),
            'staged H does not resolve to live H: ' + str(staged_h) + ' -> ' + str(staged_h.resolve()))
    return live_h


def leaked(emitted, stage, staged_h):
    """r3 (6): emitted helper names whose text names the staged workspace or the staged H."""
    marks = set()
    for path in (stage, staged_h):
        text = str(Path(os.path.abspath(path)))
        marks |= {text, repr(text)[1:-1], text.replace(os.sep, '/')}
    out = []
    for name, raw in sorted(emitted.items()):
        text = raw.decode('utf8', 'replace') if isinstance(raw, bytes) else raw
        folded = text.casefold()
        if any(m.casefold() in folded for m in marks):
            out.append(name)
    return out


def check_generation(generation, generation_sha256):
    """r3 (a): ROOT's top level is exactly the pinned generation."""
    require(file_sha(Path(generation)) == generation_sha256, 'generation record differs from its pin')
    rows = json.loads(Path(generation).read_bytes())['files']
    # boundary r2 (3): plain top-level names, unique without regard to case, closed rows
    require(type(rows) is dict, 'generation files must be a mapping')
    for n, r in rows.items():
        require(type(n) is str and n == Path(n).name and n == n.strip() and n not in ('.', '..') and
                not any(c in n for c in '/\\:') and Path(n).suffix in ('.py', '.json'),
                'generation row is not a plain top-level file name: ' + repr(n))
        require(type(r) is dict and set(r) <= GENERATION_ROW_KEYS and type(r.get('sha256')) is str and
                re.fullmatch('[0-9a-f]{64}', r['sha256']) is not None, 'generation row schema differs: ' + n)
    require(len({os.path.normcase(n) for n in rows}) == len(rows), 'generation rows are not unique by case')
    bad =[n for n, r in rows.items() if not (R / n).is_file() or linked(R / n, R) or file_sha(R / n) != r['sha256']]
    require(not bad, 'staged root differs from the generation: ' + ', '.join(sorted(bad)[:5]))
    extra = sorted(p.name for p in R.glob('*.py') if p.name not in rows)
    require(not extra, 'staged root has top-level modules outside the generation: ' + ', '.join(extra[:5]))
    return {'path': str(Path(generation).resolve()), 'sha256': generation_sha256, 'rows': len(rows)}


def bound_files():
    """r3 (c): the exact file set the binding must pin (T-relative)."""
    found = set()
    for path in C.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            found.add(path)
    for folder in (G / 'transforms', R / 'endpoint-checkpoints', RC1 / 'helpers', RC1 / 'ram'):
        found.update(p for p in folder.glob('*.py') if p.is_file())
    found.update(p for p in (RC1 / 'runtime-src').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    found.update((I_RUNTIME / PKG / 'integration_mimetic_heat.py', I_RUNTIME / PKG / 'integration_private_heat_cold.py'))
    return {rel(p): p for p in found}


def check_binding(binding, binding_sha256, *, selected):
    """r3 (c): every bound input equals its pin; locations and roles are recorded, never treated as selection."""
    raw = Path(binding).read_bytes()
    require(sha256(raw).hexdigest() == binding_sha256, 'input binding differs from its pin')
    document = json.loads(raw)
    require(type(document) is dict and document.get('schema') == BINDING_SCHEMA and
            set(document) == {'schema', 'pins', 'provenance', 'selection'}, 'closed input binding r1 required')
    pins, provenance, selection = document['pins'], document['provenance'], document['selection']
    require(type(pins) is dict and type(provenance) is dict and set(provenance) == set(pins),
            'every pin needs exactly one provenance row')
    require(selection is None or (type(selection) is str and selection.strip() != ''), 'selection is null or a statement')
    require(not selected or selection is not None, 'no selection recorded: located bytes are not selected inputs')
    required = bound_files()
    extra = sorted(set(required) - set(pins))
    require(not extra, 'staged input not pinned: ' + ', '.join(extra[:5]))
    # boundary r2 (1): pins beyond the required set are an explicit dependency set under ROOT or I_RUNTIME
    paths = {name: T / name for name in pins}
    missing = sorted(name for name, path in paths.items() if not path.is_file())
    require(not missing, 'pinned input absent from the staged root: ' + ', '.join(missing[:5]))
    outside = sorted(name for name, path in paths.items() if not (within(path, R) or within(path, I_RUNTIME)))
    require(not outside, 'pinned dependency outside the staged root and I: ' + ', '.join(outside[:5]))
    changed = sorted(name for name, path in paths.items() if file_sha(path) != pins[name])
    require(not changed, 'staged input differs from its pin: ' + ', '.join(changed[:5]))
    for name, row in provenance.items():
        require(type(row) is dict and set(row) == {'location', 'location_role'} and row['location_role'] in ROLES,
                'provenance row needs location and a known role: ' + name)
        location = Path(row['location'])
        require(location.is_absolute(), 'provenance location must be absolute: ' + name)
        require(not (composition_output(location) and row['location_role'] == 'composer-input'),
                "a composition's output location is not a composer-input location: " + name)
        require(location.is_file() and file_sha(location) == pins[name],
                'located bytes differ from the pin: ' + name)
    return {'path': str(Path(binding).resolve()), 'sha256': binding_sha256, 'pins': len(pins),
            'required': len(required), 'dependencies': len(pins) - len(required), 'selection': selection}


def composition_output(location):
    """boundary r2 (4): whether a location lies in a composition's folder, on the named or the resolved path,
    without regard to case. composed-r1 (RC1) is the composer's declared base, not an output location."""
    def output(path, bases):
        if any(within(path, base) for base in bases):
            return False
        return any(TARGET_NAME.fullmatch(part.lower()) for part in Path(path).parts)
    named = Path(os.path.abspath(location))
    return (output(named, (RC1, LIVE_R / 'composed-r1')) or
            output(named.resolve(), (RC1.resolve(), (LIVE_R / 'composed-r1').resolve())))


def select(generation, binding):
    """boundary r2 (1): the selected set the composition audit enforces (named path -> pinned digest)."""
    rows = json.loads(Path(generation).read_bytes())['files']
    pins = json.loads(Path(binding).read_bytes())['pins']
    selected = {norm(R / n): r['sha256'] for n, r in rows.items()}
    selected.update({norm(T / n): sha for n, sha in pins.items()})
    return selected


def audit(modules):
    """boundary r2 (1): every given module file is selected with its pinned bytes, or lies in an explicit exception
    (H_ROOT, the interpreter). Returns the selected files that took part, T-relative, for the reviewed record."""
    loaded, unselected = {}, []
    exceptions = (H_ROOT, Path(sys.prefix), Path(sys.base_prefix))
    for name in sorted(modules):
        path = getattr(modules[name], '__file__', None)
        if not path or norm(path) == norm(__file__):     # this tool itself
            continue
        if norm(path) in SELECTED:
            require(file_sha(Path(path)) == SELECTED[norm(path)], 'selected module changed: ' + name + ' ' + path)
            loaded[rel(Path(path))] = SELECTED[norm(path)]
        elif not any(within(path, root) for root in exceptions):
            unselected.append(name + ' ' + str(path))
    require(not unselected, 'module outside the selected set: ' + ', '.join(unselected[:5]))
    return loaded


def check_target(target, name):
    """r3 (b): an explicit new revision outside live R."""
    target = Path(os.path.abspath(target))
    require(TARGET_NAME.fullmatch(name) is not None and target.name == name, 'explicit composed-rN target required')
    require(not target.exists(), 'target exists; a composition is written once')
    require(not resolved_within(target.parent, LIVE_R), 'staging target must lie outside live R')
    require(not within(target, R) and not within(R, target), 'target must lie outside the staged root')
    # boundary r2 (2): the resolved target too, and no linked ancestor
    require(not linked(target.parent, target.anchor), 'a target ancestor is a link or junction')
    resolved = target.parent.resolve() / target.name
    for root in (R, LIVE_R):
        require(not within(resolved, root.resolve()) and not within(root.resolve(), resolved),
                'resolved target lies in or contains ' + str(root))
    return target


def lf(path):
    return path.read_bytes().decode('utf8').replace('\r\n', '\n')


def helper_sources():
    """(name -> source path): every top-level *.py of the s1 import roots, flattened in their
    order with the first match winning (Steps 8-9 rule, 16 Oct 11:12): R, C, composed-r1/helpers,
    composed-r1/ram. The live R/C copy wins for every name that also exists in RC1's folders,
    and the route (1) runner family (launch/run/reopen/driver/width gate/ledger/worker
    selection) and every FRESH_MODULE are included, so the frozen helpers are self-contained."""
    chosen = {}
    for root in (R, C, RC1 / 'helpers', RC1 / 'ram'):
        for path in sorted(root.glob('*.py')):
            chosen.setdefault(path.name, path)
    missing = [name for name in EXTRA_HELPERS if name not in chosen]
    require(not missing, 'required helpers missing from the roots: ' + ', '.join(missing))
    return chosen


# Plan06 D5 is opt-in and selected through the existing staged input binding.
PLAN06_D5 = None
PLAN06_D5_ASSETS = {}
PLAN06_D5_BASE_SOURCES = None
PLAN06_D5_NAMES = ('integration_exact_twin.py', 'integration_wall_measures_gmp.py')


def plan06_select_d5(contract_path, contract_sha256):
    global PLAN06_D5, PLAN06_D5_ASSETS
    PLAN06_D5 = None
    PLAN06_D5_ASSETS = {}
    require(bool(contract_path) == bool(contract_sha256),
            'D5 needs both --d5-contract and --d5-contract-sha256')
    if not contract_path:
        return None
    path = Path(os.path.abspath(contract_path))
    require(path.is_file() and not linked(path, path.anchor), 'D5 contract must be a real file')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == contract_sha256, 'D5 contract differs from its pin')
    # Reject duplicate keys rather than silently choosing a competing selection.
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'D5 contract duplicate key: ' + key)
            out[key] = value
        return out
    doc = json.loads(raw, object_pairs_hook=unique)
    require(type(doc) is dict and set(doc) == {
        'schema', 'selection', 'wall_input_sha256', 'wall_output_sha256', 'assets'},
        'D5 contract fields differ')
    require(doc['schema'] == 'atlas.private.plan06-d5-assembly.r1', 'D5 contract schema differs')
    require(type(doc['selection']) is str and bool(doc['selection'].strip()), 'D5 selection absent')
    for key in ('wall_input_sha256', 'wall_output_sha256'):
        require(type(doc[key]) is str and re.fullmatch('[0-9a-f]{64}', doc[key]) is not None,
                'D5 wall hash is invalid: ' + key)
    names = ('hook',) + PLAN06_D5_NAMES
    require(type(doc['assets']) is dict and set(doc['assets']) == set(names), 'D5 asset set differs')
    paths = {'hook': G / 'transforms' / 'plan06_d5_wall_hooks.py'}
    paths.update({name: R / 'plan06-d5' / name for name in PLAN06_D5_NAMES})
    for name, candidate in paths.items():
        want = doc['assets'][name]
        require(type(want) is str and re.fullmatch('[0-9a-f]{64}', want) is not None,
                'D5 asset hash is invalid: ' + name)
        require(candidate.is_file() and not linked(candidate, R), 'D5 asset missing or linked: ' + name)
        require(SELECTED.get(norm(candidate)) == want, 'D5 asset not selected at this pin: ' + name)
        require(file_sha(candidate) == want, 'D5 asset bytes differ: ' + name)
        PLAN06_D5_ASSETS[name] = (candidate, want)
    PLAN06_D5 = doc
    return {'contract': str(path), 'sha256': contract_sha256, 'selection': doc}


def plan06_apply_d5(sources, stage, replace, load):
    doc = PLAN06_D5
    for name, (path, pin) in PLAN06_D5_ASSETS.items():
        require(file_sha(path) == pin, 'D5 asset changed before composition: ' + name)
    wall = 'integration_wall_measures.py'
    require(text_sha(sources[PKG + '/' + wall]) == doc['wall_input_sha256'],
            'D5 wall input differs from the selected contract')
    for name in PLAN06_D5_NAMES:
        require(PKG + '/' + name not in sources, 'D5 module already present: ' + name)
    # No allow_unreviewed_input: the transform's own exact hash guard remains active.
    stage(wall, 'plan06:d5_wall_hooks', load('plan06_d5_wall_hooks'))
    require(text_sha(sources[PKG + '/' + wall]) == doc['wall_output_sha256'],
            'D5 wall output differs from the selected contract')
    for name in PLAN06_D5_NAMES:
        path, pin = PLAN06_D5_ASSETS[name]
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == pin, 'D5 module changed during composition: ' + name)
        # Preserve exact selected bytes, including line endings; no silent normalisation.
        replace(name, 'plan06:new:' + name, raw.decode('utf8'))
    for name, (path, pin) in PLAN06_D5_ASSETS.items():
        require(file_sha(path) == pin, 'D5 asset changed during composition: ' + name)


# Additive Plan04 payload support on the frozen Plan06 assembler c84f98bf... .
# No N9 numerical transform or scientific/composition selection happens here.
PLAN04_SCHEMA = 'atlas.private.plan04-tool-payload.r1'
PLAN04_FOLDER = 'n9-tools-r21'
PLAN04_LAUNCHER = 'launch_fresh_interval.py'
PLAN04_SELECTION = None
PLAN04_ASSETS = {}


def plan04_inventory():
    """Exact regular-file inventory; no links, hidden additions or cache exceptions."""
    folder = R / PLAN04_FOLDER
    require(folder.is_dir() and not linked(folder, folder.anchor),
            'Plan04 payload folder missing or linked')
    found = {PLAN04_LAUNCHER}
    for path in folder.rglob('*'):
        require(not linked(path, folder), 'Plan04 payload entry linked: ' + str(path))
        require(path.is_file() or path.is_dir(), 'Plan04 payload entry is not a regular file or folder')
        if path.is_file():
            found.add(path.relative_to(R).as_posix())
    return found


def plan04_validate_name(name):
    require(type(name) is str and name and name == name.strip() and
            not any(c in name for c in '\\:') and
            all(part not in ('', '.', '..') and part == part.strip() and
                not part.endswith('.') and
                re.fullmatch(r'[A-Za-z0-9_.-]+', part) is not None
                for part in name.split('/')),
            'Plan04 asset path must be a canonical relative path: ' + repr(name))
    require(name == PLAN04_LAUNCHER or name.startswith(PLAN04_FOLDER + '/'),
            'Plan04 asset outside the launcher and payload folder: ' + name)


def plan04_select(contract_path, contract_sha256):
    """Validate an explicit tool-only payload against independent staged input pins."""
    global PLAN04_SELECTION, PLAN04_ASSETS
    PLAN04_SELECTION, PLAN04_ASSETS = None, {}
    require(bool(contract_path) == bool(contract_sha256),
            'Plan04 needs both --plan04-contract and --plan04-contract-sha256')
    if not contract_path:
        return None
    path = Path(os.path.abspath(contract_path))
    require(path.is_file() and not linked(path, path.anchor),
            'Plan04 contract must be a real file')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == contract_sha256, 'Plan04 contract differs from its pin')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Plan04 contract duplicate key: ' + key)
            result[key] = value
        return result

    try:
        doc = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Refused('Plan04 contract is not valid JSON') from error
    require(type(doc) is dict and set(doc) == {'schema', 'selection', 'assets'},
            'Plan04 contract fields differ')
    require(doc['schema'] == PLAN04_SCHEMA, 'Plan04 contract schema differs')
    require(type(doc['selection']) is str and bool(doc['selection'].strip()),
            'Plan04 explicit tool-payload selection absent')
    assets = doc['assets']
    require(type(assets) is dict and PLAN04_LAUNCHER in assets and len(assets) > 1,
            'Plan04 needs the selected launcher and a nonempty payload')
    for name, digest in assets.items():
        plan04_validate_name(name)
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest) is not None,
                'Plan04 asset hash invalid: ' + name)
    require(len({name.casefold() for name in assets}) == len(assets),
            'Plan04 asset names collide by case')
    require(plan04_inventory() == set(assets), 'Plan04 exact payload inventory differs')
    checked = {}
    for name, digest in assets.items():
        candidate = R / name
        require(candidate.is_file() and not linked(candidate, candidate.anchor),
                'Plan04 asset missing or linked: ' + name)
        require(SELECTED.get(norm(candidate)) == digest,
                'Plan04 asset not selected at this pin: ' + name)
        require(file_sha(candidate) == digest, 'Plan04 asset bytes differ: ' + name)
        checked[name] = (candidate, digest)
    PLAN04_ASSETS = checked
    PLAN04_SELECTION = {
        'contract': str(path), 'sha256': contract_sha256, 'selection': doc,
        'assembler_sha256': file_sha(Path(__file__)),
        'scope': 'tool-payload-only; no scientific or composition selection',
    }
    return PLAN04_SELECTION


def plan04_recheck():
    """Recheck at trust transitions, retaining the original selected state."""
    if PLAN04_SELECTION is None:
        return
    expected = PLAN04_SELECTION
    current = plan04_select(expected['contract'], expected['sha256'])
    require(current == expected, 'Plan04 selected contract or assembler changed')


def plan04_add_helpers(files, helpers):
    """Bind payload sources and the output layout used by the selected launcher."""
    plan04_recheck()
    for name, (path, digest) in PLAN04_ASSETS.items():
        row = {'path': rel(path), 'sha256': digest}
        if name == PLAN04_LAUNCHER:
            require(helpers.get(name) == row,
                    'Plan04 launcher replaced or absent in inherited helper route')
        else:
            require(name not in helpers, 'Plan04 payload helper collision: ' + name)
            helpers[name] = row
        files[rel(path)] = digest


def plan04_check_reviewed(pins):
    """Refuse missing, changed or extra reviewed payload rows before any target write."""
    plan04_recheck()
    if PLAN04_SELECTION is None:
        return
    names = {name for name in pins['helpers']
             if name.startswith(PLAN04_FOLDER + '/') or name == PLAN04_LAUNCHER}
    require(names == set(PLAN04_ASSETS), 'Plan04 reviewed helper inventory differs')
    for name, (path, digest) in PLAN04_ASSETS.items():
        require(pins['files'].get(rel(path)) == digest,
                'Plan04 reviewed input differs: ' + name)
        require(pins['helpers'].get(name) == {'path': rel(path), 'sha256': digest},
                'Plan04 reviewed helper differs: ' + name)


def compose(pins=None):
    """Compose in memory. With pins, assert each stage's input/output against them.
    Returns (sources, stages, loaded modules, emitted heat helpers name -> bytes)."""
    audit(dict(sys.modules))     # boundary r2 (1): nothing unselected is already loaded
    sys.path[:0] = [str(C), str(I_RUNTIME), str(R), str(R / 'endpoint-checkpoints')]
    sys.dont_write_bytecode = True
    before_modules = set(sys.modules)
    import compact_restart_patch as P
    import differential_mesh_patch as DP
    import exchange_record_patch as E
    import heat_token_transform as H
    import live_memory_composition as LMC
    import mimetic_patch as MP
    import partition_workflow_transform as PWT
    import publication_token_transform as TT
    import publish_mesh_patch as PM
    import spatial_records_patch as SR
    import spatial_validation_patch as V
    import spatial_workflow_patch as Y
    base = RC1 / 'runtime-src'
    sources = {}
    for path in sorted(base.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            key = path.relative_to(base).as_posix()
            sources[key] = lf(path) if path.suffix == '.py' else path.read_bytes()
    stages = []
    expected = None if pins is None else iter(pins['stages'])

    def record(name, label, before, after, note=None):
        row = dict(module=name, stage=label, input_sha256=None if before is None else text_sha(before),
                   output_sha256=text_sha(after))
        if note:
            row['note'] = note
        if expected is not None:
            want = next(expected, None)
            require(want is not None and {k: want.get(k) for k in row} == row,
                    f'stage differs from the reviewed record: {name} {label}')
        stages.append(row)

    def stage(name, label, fn):
        key = f'{PKG}/{name}'
        before = sources[key]
        after = fn(before)
        compile(after, name, 'exec')
        sources[key] = after
        record(name, label, before, after)

    def replace(name, label, text):
        key = f'{PKG}/{name}'
        compile(text, name, 'exec')
        before = sources.get(key)
        sources[key] = text
        record(name, label, before, text, 'file replaced, not transformed')

    def load(module):
        path = G / 'transforms' / f'{module}.py'
        spec = importlib.util.spec_from_file_location(f'_g_{module}', path)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        sys.modules[f'_g_{module}'] = loaded
        return loaded.transform

    for label, fn in (('partition_workflow_transform.transform_v2', PWT.transform_v2),
                      ('spatial_workflow_patch.transform_v3', Y.transform_v3),
                      ('spatial_records_patch.transform', SR.transform),
                      ('spatial_validation_patch.workflow_source', V.workflow_source),
                      ('compact_restart_patch.workflow_source', P.workflow_source),
                      ('publication_token_transform.transform (R2 rev4)', TT.transform),
                      ('heat_token_transform.transform (R3 rev2)', H.transform),
                      ('publish_mesh_patch.transform', PM.transform)):
        stage('integration_regional_workflow.py', label, fn)
    stage('integration_spatial_owner.py', 'exchange_record_patch.holder_source', E.holder_source)
    stage('integration_spatial_owner.py', 'spatial_validation_patch.owner_source', V.owner_source)
    replace('integration_mimetic_heat.py', 'mimetic_patch.mimetic_source on I (re-pin)',
            MP.mimetic_source(lf(I_RUNTIME / PKG / 'integration_mimetic_heat.py')))
    replace('integration_endpoint_checkpoints.py', 'current endpoint companion',
            lf(R / 'endpoint-checkpoints' / 'integration_endpoint_checkpoints.py'))
    stage('integration_differential_mesh.py', 'differential_mesh_patch.transform', DP.transform)
    names = sorted({name for name, _, _ in LMC.STAGES})
    inputs = {name: sources[f'{PKG}/{name}'] for name in names}
    native, _applied = LMC.apply_native(inputs)
    # Re-derive each STAGES step's input/output text in order so the record carries both
    # digests, then require the replay to equal apply_native's own result.
    current = dict(inputs)
    for name, label, transform in LMC.STAGES:
        before = current[name]
        after = transform(before)
        compile(after, name, 'exec')
        current[name] = after
        record(name, 'live_memory_composition:' + label, before, after)
    require(all(current[name] == native[name] for name in names), 'apply_native differs from its STAGES replay')
    for name in names:
        sources[f'{PKG}/{name}'] = current[name]
    for module in GEOMETRY_SIX:
        transform = load(module)
        stage('integration_differential_geometry.py', f'geometry:{module} (allow_unreviewed_input)',
              lambda text, transform=transform: transform(text, allow_unreviewed_input=True))
    for name, module in GEOMETRY_PINNED:
        stage(name, f'geometry:{module}', load(module))
    # The compact heat successor (step7_same_call_heat_control.prepare's reviewed recipe, without
    # the control-only r12 reference insert), live_memory=True; no inventory additions allowed.
    import heat_cold_patch as COLD
    import private_heat_bundle as B
    import test_step7_bundle as SB
    import workflow_transfer as WT
    _, inputs, external, ram, helpers_in, compact = SB.compact_inputs()
    helper_out, ram_out, report = B.construct_compact_successor(
        inputs, reference_root=H_REFERENCE, reference_pins=B.REFERENCE_PINS, external=external, ram=ram,
        helpers=helpers_in, compact_helpers=compact, live_memory=True)
    emitted = dict(helper_out)
    for name, raw in ram_out.items():
        require(name not in emitted, 'compact successor helper/ram name clash: ' + name)
        emitted[name] = raw
    for name, prefix in EXPECTED_HEAT.items():
        require(name in emitted and sha256(emitted[name]).hexdigest().startswith(prefix),
                f'compact heat helper differs from the g13 live-memory layout: {name}')
    bad = leaked(emitted, R.parents[3], H_ROOT)
    require(not bad, 'emitted helper names the staging path: ' + ', '.join(bad[:5]))
    replace('integration_private_heat_cold.py', 'I text (RC1 chain replaced by the compact heat route)',
            lf(I_RUNTIME / PKG / 'integration_private_heat_cold.py'))
    stage('integration_private_heat_cold.py', 'workflow_transfer.private_heat_cold_source', WT.private_heat_cold_source)
    stage('integration_private_heat_cold.py', 'partition_workflow_transform.cold_source', PWT.cold_source)
    stage('integration_private_heat_cold.py', 'heat_cold_patch.transform', COLD.transform)
    stage('integration_private_heat_cold.py', 'private_heat_bundle.cold_binding_source (compact report)',
          lambda text: B.cold_binding_source(text, report))
    require(text_sha(sources[f'{PKG}/integration_private_heat_cold.py']).startswith(EXPECTED_COLD),
            'private_heat_cold differs from the g13 live-memory composition')
    # Preserve every baseline byte for the original complete d2 parity assertion.
    global PLAN06_D5_BASE_SOURCES
    PLAN06_D5_BASE_SOURCES = dict(sources)
    if PLAN06_D5 is not None:
        plan06_apply_d5(sources, stage, replace, load)
    if expected is not None:
        require(next(expected, None) is None, 'unexpected remaining reviewed stage')
    # boundary r2 (1): only selected files (with their pinned bytes) or the explicit exceptions took part
    loaded = audit({name: sys.modules[name] for name in set(sys.modules) - before_modules})
    return sources, stages, loaded, emitted


def same_root(a, b):
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def pin(out, dry, dry_sha256, target, staged):
    require(not out.exists(), 'reviewed inputs already exist; a new revision needs a new file')
    require(not target.exists(), 'target exists; a composition is written once')
    require(file_sha(dry) == dry_sha256, 'reviewed dry run differs from its pin')
    sources, stages, loaded, emitted = compose()
    # Every composed source equals the reviewed dry run d2 (whose geometry parity is the
    # evidence), except private_heat_cold, which the compact heat route replaces.
    dry_files = json.loads(dry.read_text(encoding='utf8'))['src_files']
    cold = f'{PKG}/integration_private_heat_cold.py'
    baseline = PLAN06_D5_BASE_SOURCES
    for key, value in baseline.items():
        digest = text_sha(value) if isinstance(value, str) else sha256(value).hexdigest()
        require(key == cold or dry_files.get(key) == digest, 'composition differs from the reviewed dry run: ' + key)
    require(set(dry_files) == set(baseline), 'composition file set differs from the reviewed dry run')
    files = {rel(p): file_sha(p) for p in sorted((RC1 / 'runtime-src').rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts}
    for path in (I_RUNTIME / PKG / 'integration_mimetic_heat.py', I_RUNTIME / PKG / 'integration_private_heat_cold.py',
                 R / 'endpoint-checkpoints' / 'integration_endpoint_checkpoints.py'):
        files[rel(path)] = file_sha(path)
    files.update(loaded)
    if PLAN06_D5 is not None:
        files.update({rel(path): pin for path, pin in PLAN06_D5_ASSETS.values()})
    helpers = {name: dict(path=None, source='compact-successor', sha256=sha256(raw).hexdigest())
               for name, raw in sorted(emitted.items())}
    conflicts = []
    for name, path in helper_sources().items():
        if name in helpers:
            if helpers[name]['sha256'] != file_sha(path):
                conflicts.append(dict(name=name, emitted=helpers[name]['sha256'][:8], root_copy=rel(path)))
            continue
        helpers[name] = dict(path=rel(path), sha256=file_sha(path))
    plan04_add_helpers(files, helpers)
    document = dict(schema=SCHEMA, base='composed-r1/runtime-src (RC1)', target=target.name,
                    target_root=str(target), root_rule=ROOT_RULE, staged=staged,
                    dry_run={'path': str(dry), 'sha256': dry_sha256},
                    files=files, helpers=helpers, stages=stages, emitted_overrides_root_copies=conflicts,
                    heat_route='private_heat_bundle.construct_compact_successor, live_memory=True',
                    outputs={k: text_sha(v) if isinstance(v, str) else sha256(v).hexdigest()
                             for k, v in sorted(sources.items())},
                    completed_query_store='files', codec_policy=None,
                    decisions='coordinator 16 Oct: RC1 base (11:00), chain (09:00), (b\') (07:52), '
                              'R2/R3 re-pin, geometry order A (10:28), WP17 files (10:08), no codec policy')
    out.write_text(json.dumps(document, indent=1, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps(dict(files=len(files), helpers=len(helpers), emitted=len(emitted), stages=len(stages),
                          outputs=len(sources), emitted_overrides_root_copies=conflicts), indent=1))


def compose_target(reviewed, reviewed_sha256, target, staged):
    require(not target.exists(), 'target exists; a composition is written once')
    require(file_sha(reviewed) == reviewed_sha256, 'reviewed inputs differ from their pin')
    pins = json.loads(reviewed.read_text(encoding='utf8'))
    require(pins.get('schema') == SCHEMA, 'reviewed inputs schema differs')
    require(same_root(target, pins['target_root']) and target.name == pins['target'],
            'target is not the reviewed permanent root: ' + pins['target_root'])
    require(pins.get('staged') == staged, 'staged root, generation or input binding differs from the reviewed record')
    plan04_check_reviewed(pins)
    for path, want in pins['files'].items():
        require(file_sha(T / path) == want, 'reviewed input changed: ' + path)
    for name, row in pins['helpers'].items():
        if row['path'] is not None:
            require(file_sha(T / row['path']) == row['sha256'], 'reviewed helper changed: ' + name)
    sources, stages, loaded, emitted = compose(pins)
    for name, row in pins['helpers'].items():
        if row['path'] is None:
            require(name in emitted and sha256(emitted[name]).hexdigest() == row['sha256'],
                    'compact heat successor emitted different bytes: ' + name)
    require({n for n, r in pins['helpers'].items() if r['path'] is None} == set(emitted),
            'compact heat successor emitted a different helper set')
    for path, sha in loaded.items():
        require(pins['files'].get(path) == sha, 'unpinned or changed module took part: ' + path)
    outputs = {k: text_sha(v) if isinstance(v, str) else sha256(v).hexdigest() for k, v in sorted(sources.items())}
    require(outputs == pins['outputs'], 'composed outputs differ from the reviewed record')
    plan04_check_reviewed(pins)
    src, helpers = target / 'src', target / 'helpers'
    for key, value in sources.items():
        path = src / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode('utf8') if isinstance(value, str) else value)
    helpers.mkdir(parents=True)
    for name, row in sorted(pins['helpers'].items()):
        data = emitted[name] if row['path'] is None else (T / row['path']).read_bytes()
        require(sha256(data).hexdigest() == row['sha256'], 'helper changed during composition: ' + name)
        destination = helpers / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    record = dict(schema='atlas.private.resumable-composition.r3', reviewed_inputs=str(reviewed),
                  reviewed_inputs_sha256=reviewed_sha256, staged=staged, stages=stages, outputs=outputs,
                  helpers={k: v['sha256'] for k, v in pins['helpers'].items()},
                  root=str(target), root_rule=ROOT_RULE,
                  completed_query_store='files', codec_policy=None, frozen=False)
    (target / 'composition.json').write_text(json.dumps(record, indent=1, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps(dict(stages=len(stages), outputs=len(outputs), helpers=len(pins['helpers'])), indent=1))
    print('composition-r3-written')


def preflight(root, generation, generation_sha256, binding, binding_sha256, target, *, selected):
    """r3: every binding is checked before any import or composition; sets the selected set the audit enforces."""
    global SELECTED
    configure(root)
    staged = dict(root=str(R), heat_reference=dict(root=str(H_REFERENCE), staged=str(H_ROOT)),
                  generation=check_generation(generation, generation_sha256),
                  input_binding=check_binding(binding, binding_sha256, selected=selected))
    target = check_target(target, Path(target).name)
    SELECTED = select(generation, binding)
    return staged, target


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ('--check', '--pin', '--compose'):
        mode.add_argument(flag, action='store_true')
    for flag in ('--root', '--generation', '--generation-sha256', '--input-binding', '--input-binding-sha256',
                 '--target'):
        parser.add_argument(flag, required=True)
    for flag in ('--reviewed', '--reviewed-sha256', '--dry', '--dry-sha256'):
        parser.add_argument(flag)
    parser.add_argument('--d5-contract')
    parser.add_argument('--d5-contract-sha256')
    parser.add_argument('--plan04-contract')
    parser.add_argument('--plan04-contract-sha256')
    args = parser.parse_args(argv)
    require(not args.pin or (args.reviewed and args.dry and args.dry_sha256), '--pin needs --reviewed, --dry, --dry-sha256')
    require(not args.compose or (args.reviewed and args.reviewed_sha256), '--compose needs --reviewed, --reviewed-sha256')
    staged, target = preflight(args.root, args.generation, args.generation_sha256, args.input_binding,
                               args.input_binding_sha256, args.target, selected=not args.check)
    d5 = plan06_select_d5(args.d5_contract, args.d5_contract_sha256)
    if d5 is not None:
        staged['plan06_d5'] = d5
    plan04 = plan04_select(args.plan04_contract, args.plan04_contract_sha256)
    if plan04 is not None:
        staged['plan04_tools'] = plan04
    if args.check:
        print(json.dumps(dict(check='ok', target=str(target), **staged), indent=1, sort_keys=True))
    elif args.pin:
        pin(Path(os.path.abspath(args.reviewed)), Path(os.path.abspath(args.dry)), args.dry_sha256, target, staged)
    else:
        compose_target(Path(os.path.abspath(args.reviewed)), args.reviewed_sha256, target, staged)


if __name__ == '__main__':
    try:
        main()
    except Refused as error:
        raise SystemExit('assemble_r3 refused: ' + str(error)) from None
