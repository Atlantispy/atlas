"""Plan31 additive final/r3 source and constructor receiving entry point.

Construction is explicit, source-only and independently pinned. No mode grants
interval, default activation, Release qualification or scientific authority.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys


HERE = Path(__file__).resolve().parent
PARENT = {'path': 'tectonics/optimisation/workbench/plan31/final/r2/build_candidate.py',
          'sha256': '1e49634f8f3b44b0eb8da32009ba819c8e791098820aefa73ab9bd4755309fb1'}
IMPLEMENTATIONS = {
    'constructor_core.py': 'dbddd0cd7dfc77ca794a1fd0dbae6a0347f126e74a99565a6ac3d32ac9472358',
    'constructor_integrity.py': '2a8861d57dfc3aa201b35fa73bebd7e98c28b871f91a9f11b674fbc700be77c2',
    'profile_support.py': '762bea12f5f127c723aac1c25cf3fa8a0351191539883c258624c0363058bf01',
}
CONTEXT_SCHEMA = 'atlas.public.plan31.construction-context.r1'
PROBE = 'helpers/probe_execution_identity.py'
PROBE_SHA256 = 'd7c1fdcd756720eabaf3689fcd2b6e61a94eaf7ea2ab5c0a8fdcbea04f150feb'
HISTORICAL_INPUTS = {'path': 'ac/p31-hi-data-r1/HISTORICAL-INPUTS-r1.json',
                     'sha256': '019944bf42007397c3cacb8756ea2e62862afa5170c79e28601d7a914cd86d22'}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def ordinary(path, *, directory=False):
    """Bootstrap only: authenticate the pinned integrity module without imports."""
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(), 'canonical absolute path required')
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked/reparse input refused')
    require(path.is_dir() if directory else path.is_file(), 'ordinary input required')
    return path


def binding(path, pin):
    require(type(pin) is str and len(pin) == 64 and all(c in '0123456789abcdef' for c in pin),
            'lowercase SHA256 required')
    return {'path': str(ordinary(path)), 'sha256': pin}


def load(ref, name):
    require(type(ref) is dict and set(ref) == {'path', 'sha256'}, 'closed implementation binding required')
    path = ordinary(ref['path'])
    raw = path.read_bytes()
    require(digest(raw) == ref['sha256'], 'implementation pin differs: ' + name)
    spec = importlib.util.spec_from_file_location('_plan31_public_r3_' + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    require(ordinary(path).read_bytes() == raw, 'implementation changed during load')
    return module


def safe_member(name):
    require(type(name) is str and name.startswith(('src/', 'helpers/')),
            'explicit src/helpers member required')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    for part in name.split('/'):
        require(part and part not in ('.', '..') and part.rstrip(' .') == part
                and not any(ord(c) < 32 or c in '<>:"\\|?*' for c in part)
                and part.split('.')[0].upper() not in reserved,
                'unsafe Windows source member')
    return name


def legacy(repo):
    repo = ordinary(repo, directory=True)
    return load(binding(repo / PARENT['path'], PARENT['sha256']), 'legacy_r2')


def bootstrap_workspace(raw, workspace):
    """A supplied accepted parent bootstrap must already bind this workspace."""
    nodes = [node for node in ast.parse(raw).body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == 'T' for target in node.targets)]
    require(len(nodes) == 1 and len(nodes[0].targets) == 1, 'single parent bootstrap workspace binding required')
    value = nodes[0].value
    require(isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'Path'
            and len(value.args) == 1 and not value.keywords and isinstance(value.args[0], ast.Constant)
            and type(value.args[0].value) is str and Path(value.args[0].value) == Path(workspace),
            'parent bootstrap workspace differs; authenticated relocation inputs required')


def contract(repo):
    """Preserve r2's exact six-value, 697-member public source contract."""
    return legacy(repo).contract(Path(repo))


def read_context(repo, construction_context, context_sha256):
    """Authenticate one external context; never discover or select sources."""
    require(sys.dont_write_bytecode, 'run the constructor with -B')
    repo = ordinary(repo, directory=True)
    implementation_refs = {name: binding(HERE / name, pin) for name, pin in IMPLEMENTATIONS.items()}
    U = load(implementation_refs['constructor_integrity.py'], 'integrity')
    inputs = U.Inputs()
    for ref in implementation_refs.values():
        inputs.raw(Path(ref['path']), ref['sha256'])
    context_ref = binding(construction_context, context_sha256)
    context = inputs.doc(Path(context_ref['path']), context_ref['sha256'])
    fields = {'schema', 'status', 'pending', 'downstream_pending', 'generation', 'workspace', 'control_root',
              'plan_parent', 'owner', 'selection', 'source_graph', 'selected_files',
              'construction_only', 'historical_inputs'}
    require(type(context) is dict and set(context) == fields
            and context['schema'] == CONTEXT_SCHEMA
            and context['status'] == 'SOURCE_CONSTRUCTION_INPUTS_FROZEN'
            and context['pending'] == [] and context['historical_inputs'] == HISTORICAL_INPUTS,
            'closed settled public construction context required')
    require(type(context['generation']) is str and context['generation'].strip()
            and type(context['owner']) is str and context['owner'].strip(), 'explicit generation/owner required')
    for key in ('workspace', 'control_root', 'plan_parent'):
        U.ordinary(Path(context[key]), directory=True)
    for key in ('control_root', 'plan_parent'):
        root = Path(context[key])
        for source in (repo, HERE):
            require(root != source and not root.is_relative_to(source) and not source.is_relative_to(root),
                    'construction control/plan root overlaps public sources')
    selected = context['selected_files']
    require(type(selected) is dict and selected and all(type(n) is str for n in selected)
            and len({n.casefold() for n in selected}) == len(selected), 'complete public source map required')
    for name, pin in selected.items():
        safe_member(name)
        U.pin(pin)
    require(context['construction_only'] == [PROBE] and selected.get(PROBE) == PROBE_SHA256,
            'exact construction-only identity probe required')
    refs = {}
    for key in ('selection', 'source_graph'):
        ref = context[key]
        require(type(ref) is dict and set(ref) == {'path', 'sha256'}, 'closed ' + key + ' binding required')
        refs[key] = binding(ref['path'], ref['sha256'])
    graph = inputs.doc(Path(refs['source_graph']['path']), refs['source_graph']['sha256'])
    downstream = graph.get('pending')
    later = {'Corrected source implementation acceptance', 'Actual public constructor receiving integration',
             'Final runtime/fold qualification'}
    require(graph.get('schema') in ('plan31.public-source-reconciliation.r1', 'plan31.public-source-reconciliation.r2')
            and graph.get('status') == 'SOURCE_GRAPH_RECONCILED_NOT_RUNTIME_QUALIFIED'
            and type(downstream) is list and all(type(item) is str and item in later for item in downstream)
            and len(set(downstream)) == len(downstream) and context['downstream_pending'] == downstream
            and graph.get('files') == selected
            and graph.get('construction_only') == [PROBE]
            and all(graph.get(key) is False for key in ('selected_for_apply', 'source_generation_created',
                                                       'payload_executed', 'runtime_qualified')),
            'settled exact public source graph required; provisional sources refuse')
    selection = inputs.doc(Path(refs['selection']['path']), refs['selection']['sha256'])
    require(selection.get('generation') == context['generation']
            and selection.get('historical_inputs') == HISTORICAL_INPUTS,
            'context/selection generation or historical DATA differs')
    parent = selection.get('parent')
    require(type(parent) is dict and type(parent.get('bootstrap')) is dict
            and set(parent['bootstrap']) == {'path', 'sha256'}, 'explicit authenticated parent bootstrap required')
    bootstrap = binding(parent['bootstrap']['path'], parent['bootstrap']['sha256'])
    bootstrap_workspace(inputs.raw(Path(bootstrap['path']), bootstrap['sha256']), context['workspace'])
    inputs.recheck()
    C = load(implementation_refs['constructor_core.py'], 'core')
    C.configure(workspace=context['workspace'], plan_parent=context['plan_parent'],
                control_root=context['control_root'], utility=implementation_refs['constructor_integrity.py'],
                support=implementation_refs['profile_support.py'], context_binding=context_ref,
                owner=context['owner'], selection=context['selection'], generation=context['generation'],
                selected_files=selected, source_graph=refs['source_graph'])
    return C, U, inputs, context, context_ref, implementation_refs


def construction_contract(repo, *, construction_context, context_sha256):
    """Return the actual reviewed derivation boundary, with no outputs or probe."""
    C, _, context_inputs, context, context_ref, refs = read_context(repo, construction_context, context_sha256)
    frozen = {context['generation']: context['selection']}
    U, inputs, build, plan = C.derive(frozen, ordinary(HERE / 'build_candidate.py'), refs['constructor_core.py'])
    context_inputs.recheck()
    require({n: digest(raw) for n, raw in build['payload'].items()} == context['selected_files'],
            'source and constructor payloads differ')
    return C, U, inputs, build, plan, context_ref


def generation(files):
    rows = [{'member': 'source/' + name, 'public_sha256': pin} for name, pin in sorted(files.items())]
    return digest((json.dumps(rows, indent=2, ensure_ascii=True) + '\n').encode('utf-8'))


def materialise(repo, destination, *, construction_context=None, context_sha256=None):
    """Legacy calls stay r2; an explicit context emits the constructor's payload."""
    require((construction_context is None) == (context_sha256 is None), 'context path and pin are paired')
    if construction_context is None:
        return legacy(repo).materialise(Path(repo), Path(destination))
    C, U, inputs, build, plan, context_ref = construction_contract(
        repo, construction_context=construction_context, context_sha256=context_sha256)
    destination = Path(destination)
    require(destination.is_absolute() and destination == destination.resolve(), 'canonical source destination required')
    for source in (ordinary(repo, directory=True), HERE):
        require(destination != source and not destination.is_relative_to(source) and not source.is_relative_to(destination),
                'source output overlaps public sources')
    files = {name: digest(raw) for name, raw in build['payload'].items()}
    result = {'schema': 'atlas.public.plan31.final.materialised-source.r3',
              'source_map_sha256': C.CONSTRUCTION_CONTEXT['source_graph']['sha256'],
              'construction_context_sha256': context_ref['sha256'],
              'source_selection_sha256': build['selection']['sha256'], 'selection_sha256': generation(files),
              'files': files, 'construction_only': [PROBE],
              'release_files': {name: pin for name, pin in files.items() if name != PROBE},
              'runtime_admission': False, 'IV_permitted': False, 'scientific_acceptance': False,
              'default_changed': False, 'private_public_identity_equal': False,
              'source_plan_sha256': digest(U.canonical(plan))}
    outputs = {destination / name: raw for name, raw in build['payload'].items()}
    outputs[destination / 'SOURCE-MANIFEST.json'] = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode('utf-8')
    C.check_paths(U, [destination], inputs.pins, outputs)
    inputs.recheck()
    for path, raw in outputs.items():
        C.emit(U, path, raw)
    expected = {path.relative_to(destination).as_posix(): digest(raw) for path, raw in outputs.items()}
    U.inventory(destination, U.Inputs(), expected)
    inputs.recheck()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('source', 'check', 'plan', 'apply'), default='source')
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--construction-context', type=Path)
    parser.add_argument('--context-sha256')
    parser.add_argument('--selection')
    parser.add_argument('--selection-sha256')
    parser.add_argument('--plan-root', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--reviewed-constructor-sha256')
    args = parser.parse_args(argv)
    if args.mode == 'source':
        require(args.out is not None, 'source requires --out')
        require(all(getattr(args, key) is None for key in ('selection', 'selection_sha256', 'plan_root',
                                                        'plan_sha256', 'reviewed_constructor_sha256')),
                'constructor operands are not source operands')
        result = materialise(args.repo, args.out, construction_context=args.construction_context,
                             context_sha256=args.context_sha256)
        print(json.dumps({'source_map_sha256': result['source_map_sha256'],
                          'selection_sha256': result['selection_sha256'], 'members': len(result['files']),
                          'runtime_admission': False, 'IV_permitted': False, 'scientific_acceptance': False}, sort_keys=True))
        return 0
    require(args.out is None and args.construction_context is not None and args.context_sha256 is not None,
            'constructor requires explicit context path/pin and no --out')
    C, _, context_inputs, context, _, refs = read_context(args.repo, args.construction_context, args.context_sha256)
    forwarded = [args.mode]
    for key in ('selection', 'selection_sha256', 'plan_root', 'plan_sha256', 'reviewed_constructor_sha256'):
        value = getattr(args, key)
        if value is not None:
            forwarded.extend(('--' + key.replace('_', '-'), str(value)))
    context_inputs.recheck()
    return C.main({context['generation']: context['selection']}, ordinary(HERE / 'build_candidate.py'),
                  refs['constructor_core.py'], forwarded)


if __name__ == '__main__':
    raise SystemExit(main())
