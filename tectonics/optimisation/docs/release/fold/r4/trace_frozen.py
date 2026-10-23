"""Loaded-file trace around one real heat call on a frozen composition (FOLD.md §9, condition 1a).

Usage (PYTHONHASHSEED=0; small lane):
  python -B trace_frozen.py HCF WORKDIR OUT_JSON REFERENCE_JSON|- TRACE_JSON

HCF is the reviewed heat_control_on_frozen.py. WORKDIR must already be prepared by its `prepare`.
This runs HCF's unchanged `child` in this process, so its own checks still apply: nothing loaded outside
the frozen paths, frozen inputs unchanged, arrays equal to the reference. Then it writes TRACE_JSON:
  modules  every loaded module with a file: resolved path, sha256, and the root it came from
  opened   every .py/.pyd/.dll file opened during the run (one audit hook, 'open' events only); a file that
           was opened but is not a loaded module was only read (for example hashed by a pin check)
  targets  for each pinned package file: the file that executed, its sha, and the heat-repair file the
           pins name, with whether that file was opened and whether it executed
Nothing outside OUT_JSON and TRACE_JSON is written. The exit code is HCF's.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import sys

TARGETS = ('integration_mimetic_heat', 'integration_exact_gmp', 'integration_spatial_transport',
           'integration_mimetic_newton')
PIN_HOLDERS = ('private_heat_geometry_inventory_r1', 'private_heat_interval_inventory_r4',
               'private_heat_low_solver_kernel_r2', 'private_heat_low_solver_kernel_r5',
               'private_heat_decimal_inventory_r1')
LITERAL = re.compile(r"'([A-Za-z]:\\\\[^']+?\.py)'")
OPENED = set()


def _audit(event, args):
    if event == 'open' and args and isinstance(args[0], str) and args[0][-3:] in ('.py', 'pyd', 'dll'):
        OPENED.add(args[0])


def _digest(path):
    try:
        return sha256(Path(path).read_bytes()).hexdigest()
    except OSError as error:
        return 'unreadable: %s' % type(error).__name__


def main(hcf, workdir, out, reference, trace_path):
    trace_path, workdir = Path(trace_path), Path(workdir).resolve()
    if trace_path.exists():
        raise SystemExit('the trace exists: %s' % trace_path)
    info = json.loads((workdir/'control.json').read_text(encoding='utf8'))
    roots = {'helpers': Path(info['paths'][0]).resolve(), 'native': Path(info['paths'][1]).resolve(),
             'h_tests': Path(info['paths'][2]).resolve()}
    roots['h_src'] = roots['h_tests'].parent/'src'
    roots['env'] = Path(sys.executable).resolve().parents[1]

    def root_of(path):
        for name, root in roots.items():
            if path.is_relative_to(root):
                return name
        return 'other'

    sys.addaudithook(_audit)
    sys.argv = [hcf, 'child', str(workdir), str(out)] + ([] if reference == '-' else [reference])
    code = 0
    try:
        runpy.run_path(hcf, run_name='__main__')
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    modules = {}
    for name, module in sorted(list(sys.modules.items())):
        where = getattr(module, '__file__', None)
        if where:
            path = Path(where).resolve()
            if root_of(path) != 'env':
                modules[name] = dict(file=str(path), root=root_of(path), sha256=_digest(path))
    loaded = {entry['file'] for entry in modules.values()}
    opened = sorted({str(Path(p).resolve()) for p in OPENED})
    named = {}
    for holder in PIN_HOLDERS:
        text = (roots['helpers']/(holder + '.py')).read_text(encoding='utf8')
        for literal in LITERAL.findall(text):
            named.setdefault(Path(literal.replace('\\\\', '\\')).name, set()).add(holder)
    targets = {}
    for stem in TARGETS:
        module = modules.get('atlas_tectonics.' + stem)
        h_file = roots['h_src']/'atlas_tectonics'/(stem + '.py')
        targets[stem] = dict(
            executed_file=module and module['file'], executed_root=module and module['root'],
            executed_sha256=module and module['sha256'],
            heat_repair_file=str(h_file), heat_repair_sha256=_digest(h_file),
            heat_repair_opened=str(h_file.resolve()) in opened, heat_repair_executed=str(h_file.resolve()) in loaded,
            pinned_by=sorted(named.get(stem + '.py', ())))
    from_h_src = sorted(f for f in loaded if root_of(Path(f)) == 'h_src')
    trace = dict(schema='atlas.rm.fold.loaded-file-trace.r1', hcf=str(Path(hcf).resolve()), hcf_sha256=_digest(hcf),
                 workdir=str(workdir), out=str(out), reference=reference, hcf_exit=code,
                 roots={k: str(v) for k, v in roots.items()}, targets=targets,
                 loaded_by_root={r: sum(1 for m in modules.values() if m['root'] == r) for r in roots},
                 loaded_from_h_src=from_h_src,
                 opened_not_loaded=[p for p in opened if p not in loaded and root_of(Path(p)) != 'env'],
                 modules=modules)
    with trace_path.open('x', encoding='utf8') as stream:
        json.dump(trace, stream, indent=1, sort_keys=True)
    print(json.dumps(dict(hcf_exit=code, targets={k: (v['executed_root'], (v['executed_sha256'] or '')[:8],
                                                       v['heat_repair_opened'], v['heat_repair_executed'])
                                                   for k, v in targets.items()},
                          loaded_from_h_src=len(from_h_src))), flush=True)
    return code


if __name__ == '__main__':
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
