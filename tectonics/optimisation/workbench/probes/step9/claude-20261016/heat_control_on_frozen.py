"""Same-call heat control (C/step7_same_call_heat_control) run ON a frozen composition.

Usage:
  python -B heat_control_on_frozen.py prepare WORKDIR NATIVE_ROOT HELPERS_DIR [HELPERS_DIR ...]
  python -B heat_control_on_frozen.py child WORKDIR OUT_JSON [REFERENCE_JSON|-] [SAVE_ARRAYS_DIR]

prepare: WORKDIR must not exist. The frozen composition's own private_heat_native_issuer_r13
(first found in the HELPERS_DIRs) must be the reviewed production issuer, sha256
EXPECTED_R13 (pre-reference-insert, live memory on; g13l1/control.json). The issuers pin
their sibling helpers by their own folder, so the frozen helpers are copied byte for byte into
WORKDIR/helpers (first found wins, as on the import path; every copy recorded by digest) and,
exactly as the control's prepare() does, the verbatim r12 advance/_advance_verified are
inserted into that copy of r13 only, as advance_legacy_packaging before MARKER. control.json's
import paths are [WORKDIR/helpers, NATIVE_ROOT, H tests]; the frozen native tree is used in
place and nothing frozen is changed.

child (a fresh process): runs the control's own child() on WORKDIR. Afterwards every loaded
module whose file is under the workspace must lie in one of those paths, or be the control
script or this script; anything else (for instance a live C module the frozen helpers lack)
is listed in the output and fails the check. With REFERENCE_JSON (a reviewed control output of
the SAME composition, such as g13-same-call-live1.json for g13l1) every array digest must also be
equal; result IDs and metadata digests are compared for the record. With SAVE_ARRAYS_DIR (must not
exist) the r13 result's arrays and each cell's keys are saved there by a sys.monitoring observer
(``_array_saver``; no global profile or trace function) and must equal the control's own array
digests. WORKDIR and every import path inside the workspace except H's tests are digested before
and after the control: any change fails the check. OUT_JSON must not exist. Nothing outside OUT_JSON
and SAVE_ARRAYS_DIR is written.

FAIL CLOSED (review 16 Oct 2026): the child exits 0 only when frozen_check.status is PASS (control
PASS, nothing loaded outside the frozen paths, no difference from the reference, the save complete
and equal to the control's digests, the frozen inputs unchanged); otherwise it exits 1 after writing
OUT_JSON and, when saving, SAVE_ARRAYS_DIR/frozen_check.json.
"""
import json
import re
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
WORKSPACE = R.parents[3]
H = WORKSPACE/'fidelity-integration-20261005'/'heat-repair-20261007'
H_TESTS = H/'source'/'tectonics'/'tests'
ENV = WORKSPACE/'.r44-env'
ISSUER = 'private_heat_native_issuer_r13.py'
EXPECTED_R13 = 'dbaeecae1602fa16287bc760f745332d58dc9026cc946a9eebec9c616a0b54a9'
SAME = ('result_id', 'metadata_sha256', 'metadata_bytes')
TOOL = 4                        # sys.monitoring tool id of the array saver (3 is the private heat observers')
TOOL_NAME = 'heat-control-array-saver'
ARRAY_NAME = re.compile(r'[A-Za-z0-9_]+')


def prepare(workdir, native_root, helpers):
    workdir, native_root = Path(workdir), Path(native_root).resolve()
    helpers = [Path(path).resolve() for path in helpers]
    if workdir.exists():
        raise SystemExit('the work directory must not exist')
    found = next((folder/ISSUER for folder in helpers if (folder/ISSUER).is_file()), None)
    if found is None:
        raise SystemExit('the frozen helpers have no '+ISSUER)
    issuer = found.read_bytes().decode('utf8')
    if sha256(issuer.encode()).hexdigest() != EXPECTED_R13:
        raise SystemExit('frozen r13 is not the reviewed production issuer: '+sha256(issuer.encode()).hexdigest())
    sys.path.insert(0, str(C))
    import step7_same_call_heat_control as CONTROL
    # The control's own predecessor rule (prepare(), lines 97-100); the transformer is the
    # frozen composition's private_heat_indexed_runtime, imported from the frozen helpers.
    sys.path[:0] = [str(folder) for folder in helpers]
    import private_heat_indexed_runtime as P
    if not any(Path(P.__file__).resolve() == (folder/'private_heat_indexed_runtime.py').resolve() for folder in helpers):
        raise SystemExit('private_heat_indexed_runtime did not load from the frozen helpers')
    predecessor = P.issuer_source((H/'private_heat_native_issuer_r12.py').read_text(encoding='utf8'))
    if issuer.count(CONTROL.MARKER) != 1:
        raise SystemExit('reference declaration boundary changed')
    # The issuers pin their sibling helpers by their own folder, so the reference copy of
    # r13 must sit beside them: the frozen helpers are copied byte for byte (first found wins,
    # as on the import path) and only r13 is replaced. Every copy is recorded by digest.
    copy = workdir/'helpers'
    copy.mkdir(parents=True)
    copied = {}
    for folder in helpers:
        for path in sorted(folder.glob('*.py')):
            if path.name not in copied:
                raw = path.read_bytes()
                (copy/path.name).write_bytes(raw)
                copied[path.name] = {'source': str(path), 'sha256': sha256(raw).hexdigest()}
    (copy/ISSUER).write_bytes(issuer.replace(CONTROL.MARKER, CONTROL.reference_functions(predecessor)+CONTROL.MARKER)
                              .encode('utf8'))
    paths = [str(copy.resolve()), str(native_root), str(H_TESTS)]
    info = {'paths': paths, 'live_memory': True, 'inventory_added_for_control': [], 'frozen': True,
            'native_root': str(native_root), 'frozen_helpers': [str(folder) for folder in helpers],
            'composed_r13_sha256_before_reference_insert': EXPECTED_R13,
            'reference_r13_sha256': sha256((copy/ISSUER).read_bytes()).hexdigest(),
            'copied_helpers': copied}
    (workdir/'control.json').write_text(json.dumps(info, indent=1), encoding='utf8')
    print(json.dumps({'prepared': str(workdir), 'helpers_copied': len(copied),
                      'reference_r13_sha256': info['reference_r13_sha256']}))


KEY_FIELDS = ('cell_id', 'logical_cell_id', 'voxel_index', 'partition_path', 'radial_band', 'chart',
              'source_chart_id', 'grid_id')


def _write_new(path, text):
    """Exclusive creation: an existing file is never overwritten."""
    with open(path, 'x', encoding='utf8') as handle:
        handle.write(text)


def _save_cell_keys(directory, caller):
    """cell_keys.json: per cell of the heat result, in the result's own order, its mesh row's key fields.

    Read-only, from the control's own objects in its child() frame: ``old`` (the verbatim r12
    result; its metadata bytes give the result's cell order, cell_ids) and ``view`` (the call's
    compact mesh, whose rows carry cell_id and logical_cell_id and, when present, the fields
    logical_cell_id is derived from). cell_id binds provenance (funding and support ids), so a
    route-independent comparison matches cells by logical_cell_id (Coordinator D-l, 16 Oct 2026).
    Returns the number of cells written.
    """
    local = caller.f_locals
    order = json.loads(local['old']._snapshot._metadata)['cell_ids']
    view, rows, mesh_order = local['view'], {}, []
    for index in range(view.cell_count):
        row = view.cell(index)
        value = row.value
        rows[value['cell_id']] = {key: value[key] for key in KEY_FIELDS if key in value}
        mesh_order.append(value['cell_id'])
        del row, value
    # heat_ledger_tables._ordered_mesh_binding requires the heat cell order to be the mesh's row
    # order; recorded here so the evidence shows it on each route.
    _write_new(directory/'cell_keys.json', json.dumps(dict(
        order='the heat result cell order (legacy metadata cell_ids)', mesh_row_order_equal=order == mesh_order,
        cells=[rows[cell] for cell in order])))
    return len(order)


def _hooks():
    """Global hooks active now, for the record: profile/trace functions, tracemalloc, monitoring tools."""
    tracing = sys.modules.get('tracemalloc')
    return dict(profile=sys.getprofile() is not None, trace=sys.gettrace() is not None,
                tracemalloc=bool(tracing is not None and tracing.is_tracing()),
                monitoring_tools={str(tool): sys.monitoring.get_tool(tool) for tool in range(6)
                                  if sys.monitoring.get_tool(tool) is not None})


def _array_saver(directory, caller_code):
    """A sys.monitoring PY_RETURN observer: on the r13 issuer's advance() return to the control's
    child() (``caller_code``), save every array of its result and each cell's keys.

    Read-only observation: no code object, attribute or input changes. Not a global profile or trace
    function: every other return location is disabled for this tool at its first event
    (sys.monitoring.DISABLE), so the cost is one callback per return location the run reaches. The
    sys.setprofile hook this replaces ran a Python call on every call and return and made each arm
    about 2.5x slower (16 Oct: 85-133 s without it, 227-322 s with it). Only the module-level
    ``advance`` (co_qualname) of a file named ISSUER whose caller frame runs ``caller_code`` is saved,
    once: <name>.npy (exclusive creation), arrays.json (shape, dtype and SHA-256 of each array) and
    cell_keys.json (``_save_cell_keys``). An error is recorded in the state, never raised into the
    heat call; the child then fails. Returns (install, remove, state).
    """
    import numpy as np
    monitoring = sys.monitoring
    directory.mkdir(parents=True)
    state = dict(saved=False, error=None, arrays={}, cells=None, advance_returns=0, hooks_at_save=None, events=0)

    def on_return(code, offset, value):
        state['events'] += 1
        if state['saved'] or state['error'] is not None:
            return monitoring.DISABLE
        if code.co_qualname != 'advance' or Path(code.co_filename).name != ISSUER:
            return monitoring.DISABLE
        state['advance_returns'] += 1
        if value is None:
            return None
        try:
            frame = sys._getframe(1)
            if frame.f_code is not code:
                raise RuntimeError('the observed frame is not the returning advance()')
            caller = frame.f_back
            if caller is None or caller.f_code is not caller_code:
                raise RuntimeError('advance() did not return to the control child()')
            names = list(value.array_names)
            if not names or len(set(names)) != len(names) or not all(ARRAY_NAME.fullmatch(name) for name in names):
                raise RuntimeError('array names missing, repeated or not plain: %r' % (names,))
            table = {}
            for name in names:
                array = np.array(value.array(name), copy=True)
                with open(directory/(name+'.npy'), 'xb') as handle:
                    np.save(handle, array, allow_pickle=False)
                table[name] = dict(shape=list(array.shape), dtype=array.dtype.str,
                                   sha256=sha256(array.tobytes()).hexdigest())
            _write_new(directory/'arrays.json', json.dumps(table))
            state['cells'] = _save_cell_keys(directory, caller)
            state.update(saved=True, arrays=table, hooks_at_save=_hooks())
        except Exception as error:          # recorded; the child fails on it
            state['error'] = '%s: %s' % (type(error).__name__, error)
        return monitoring.DISABLE

    def install():
        if monitoring.get_tool(TOOL) is not None:
            raise SystemExit('sys.monitoring tool %d is in use: %s' % (TOOL, monitoring.get_tool(TOOL)))
        monitoring.use_tool_id(TOOL, TOOL_NAME)
        monitoring.register_callback(TOOL, monitoring.events.PY_RETURN, on_return)
        monitoring.set_events(TOOL, monitoring.events.PY_RETURN)
        # A code object keeps a location DISABLEd by an earlier saver in this process, which would hide
        # advance() from this one; in a fresh child nothing is monitored before this, so nothing else changes.
        monitoring.restart_events()

    def remove():
        if monitoring.get_tool(TOOL) == TOOL_NAME:
            monitoring.set_events(TOOL, 0)
            monitoring.register_callback(TOOL, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(TOOL)
    return install, remove, state


def _inputs_digest(workdir, paths):
    """SHA-256 over every file of WORKDIR and of each import path inside the workspace (H's tests excepted)."""
    roots = [workdir]+[path for path in paths if path.is_relative_to(WORKSPACE) and not path.is_relative_to(H)
                       and not path.is_relative_to(workdir)]
    digest = sha256()
    for root in roots:
        for path in sorted(item for item in root.rglob('*') if item.is_file()):
            digest.update(('%s\0%s\0' % (path, sha256(path.read_bytes()).hexdigest())).encode('utf8'))
    return digest.hexdigest()


def _save_check(state, result):
    """Problems of the save, against the control's own array digests and cell count (empty: complete)."""
    problems = []
    if state['error'] is not None:
        problems.append('observer: '+state['error'])
    if not state['saved']:
        problems.append('the r13 advance() result was not saved (returns seen: %d)' % state['advance_returns'])
        return problems
    recorded = result.get('arrays')
    if type(recorded) is not dict or not recorded or set(recorded) != set(state['arrays']):
        problems.append('saved array names differ from the control result')
    else:
        problems += ['%s: saved SHA-256 differs from the control' % name for name in sorted(recorded)
                     if state['arrays'][name]['sha256'] != recorded[name]]
    if state['cells'] is None or state['cells'] != result.get('cell_count'):
        problems.append('cell keys for %r cells, the control has %r' % (state['cells'], result.get('cell_count')))
    return problems


def child(workdir, out, reference=None, save_arrays=None):
    workdir, out = Path(workdir).resolve(), Path(out)
    if out.exists():
        raise SystemExit('the output exists: %s' % out)
    info = json.loads((workdir/'control.json').read_text(encoding='utf8'))
    allowed = [Path(path).resolve() for path in info['paths']]
    before = _inputs_digest(workdir, allowed)
    sys.path.append(str(C))
    import step7_same_call_heat_control as CONTROL
    saver = None
    if save_arrays is not None:
        saver = _array_saver(Path(save_arrays), CONTROL.child.__code__)
        saver[0]()
    hooks_before = _hooks()
    try:
        CONTROL.child(str(workdir), str(out))
    finally:
        if saver is not None:
            saver[1]()
    hooks_after = _hooks()
    own = {Path(__file__).resolve(), Path(CONTROL.__file__).resolve()}
    leaks = sorted({str(Path(module.__file__).resolve()) for module in list(sys.modules.values())
                    if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(WORKSPACE)
                    and not Path(module.__file__).resolve().is_relative_to(ENV)
                    and Path(module.__file__).resolve() not in own
                    and not any(Path(module.__file__).resolve().is_relative_to(root) for root in allowed)})
    after = _inputs_digest(workdir, allowed)
    result = json.loads(out.read_text(encoding='utf8'))
    result['frozen_check'] = {'paths': info['paths'], 'loaded_outside_frozen': leaks,
                              'inputs_sha256_before': before, 'inputs_sha256_after': after,
                              'hooks_before': hooks_before, 'hooks_after': hooks_after}
    differences = []
    if before != after:
        differences.append('frozen inputs changed during the run')
    if reference is not None:
        expected = json.loads(Path(reference).read_text(encoding='utf8'))
        # Every array (the numbers) must be identical to the reviewed run of the same composition.
        # Result IDs and metadata are compared for the record only: heat provenance binds the
        # absolute paths of its helper sources, so a layout in another folder has other IDs with
        # the same numbers (validation 16 Oct 2026: 860 B of metadata from about 86 helper paths
        # 10 characters shorter).
        if type(expected.get('arrays')) is not dict or not expected['arrays']:
            differences.append('reference has no arrays')
        elif result.get('arrays') != expected['arrays']:
            differences.append('arrays')
        informational = [f'{side}.{key}' for side in ('legacy', 'compact') for key in SAME
                         if result[side][key] != expected[side][key]]
        result['frozen_check'].update(reference=str(reference),
            reference_sha256=sha256(Path(reference).read_bytes()).hexdigest(),
            path_bound_fields_differing=informational,
            path_bound_note='heat result IDs and metadata bind absolute helper source paths; arrays are compared')
    if saver is not None:
        state = saver[2]
        problems = _save_check(state, result)
        differences += problems
        result['frozen_check']['save'] = dict(
            directory=str(save_arrays), observer='sys.monitoring tool %d, PY_RETURN, DISABLE elsewhere' % TOOL,
            saved=state['saved'], advance_returns=state['advance_returns'], observer_events=state['events'],
            error=state['error'],
            arrays=state['arrays'], cells=state['cells'], hooks_at_save=state['hooks_at_save'], problems=problems)
    result['frozen_check']['differences_from_reference'] = differences
    status = 'PASS' if result.get('status') == 'PASS' and not leaks and not differences else 'FAIL'
    result['frozen_check']['status'] = status
    text = json.dumps(result, indent=2, sort_keys=True)
    out.write_text(text, encoding='utf8')
    if saver is not None:
        _write_new(Path(save_arrays)/'frozen_check.json', json.dumps(dict(
            status=status, control_status=result.get('status'), out=str(out),
            out_sha256=sha256(out.read_bytes()).hexdigest(), arrays=result.get('arrays'),
            cell_count=result.get('cell_count'), reference=None if reference is None else str(reference),
            differences=differences, leaks=leaks), indent=1))
    print(json.dumps({'control': result.get('status'), 'frozen_check': status,
                      'leaks': leaks[:10], 'differences': differences}), flush=True)
    return 0 if status == 'PASS' else 1


def main():
    if sys.argv[1] == 'prepare':
        prepare(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif sys.argv[1] == 'child':
        # child WORKDIR OUT [REFERENCE|-] [SAVE_ARRAYS_DIR]
        if not 4 <= len(sys.argv) <= 6:
            raise SystemExit('child WORKDIR OUT [REFERENCE|-] [SAVE_ARRAYS_DIR]')
        reference = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != '-' else None
        raise SystemExit(child(sys.argv[2], sys.argv[3], reference, sys.argv[5] if len(sys.argv) > 5 else None))
    else:
        raise SystemExit('prepare or child')


if __name__ == '__main__':
    main()
