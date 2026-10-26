"""Add exact guarded width sources and current N9 source tools; no runtime admission."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
MAP_SHA = '897ae80675b84ba801803b98837df3dec44158bda02eefad2e93f4e9c52261fc'
PARENT = {'path': 'tectonics/optimisation/workbench/plan31/final/build_candidate.py', 'sha256': 'ce33a92999775cb74b4d9829b7f6c88da6f6c1e596248b904709ef0cd1ed53ae'}
N9_MAP_SHA = '87fa86ed064c449bcab8704fd613045ffc6b2f436b8f7829856092abaa529a28'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parent_module(repo):
    path = repo/PARENT['path']
    raw = path.read_bytes()
    require(digest(raw) == PARENT['sha256'], 'parent builder pin differs')
    spec = importlib.util.spec_from_file_location('_plan31_width_parent', path)
    value = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value


def contract(repo):
    repo = Path(repo).absolute()
    parent = parent_module(repo)
    _, _, receiving, utilities, _ = parent.contract(repo)
    raw = utilities.read_source(HERE, 'SOURCE-MAP.json')
    require(digest(raw) == MAP_SHA, 'width source map pin differs')
    mapping = utilities.read_map(raw)
    require(mapping['schema'] == 'atlas.public.plan31.guarded-width.source-composition.r1'
            and mapping['base_builder'] == PARENT and mapping['base_source_map_sha256'] == parent.MAP_SHA
            and mapping['n9_public_source_map'] == {'path': 'N9-SOURCE-MAP.json', 'sha256': N9_MAP_SHA}
            and len(mapping['rows']) == 10 and len(mapping['native_width_members']) == 3
            and len(mapping['n9_tool_members']) == 7 and mapping['source_integration_selected'] is True
            and all(mapping[name] is False for name in ('full_C4_accepted', 'reader_width_tables_accepted',
                'runtime_admission', 'scientific_acceptance', 'default_changed', 'interval_authority', 'IV_permitted')),
            'guarded source-only width contract differs')
    require(digest(utilities.read_source(HERE, 'N9-SOURCE-MAP.json')) == N9_MAP_SHA,
            'actual N9 public map pin differs')
    outputs = {}
    for name, row in mapping['rows'].items():
        payload = utilities.read_source(HERE, row['payload'])
        require(digest(payload) == row['public_output_sha256'], 'actual N9/native tool pin differs: '+name)
        outputs[name] = payload
        if row['diff'] is not None:
            require(digest(utilities.read_source(HERE, row['diff'])) == row['diff_sha256'], 'width diff pin differs')
    for member, flag in [('helpers/n9-tools-r21/dump_arm_r5.py', 'EXTRACTION_READY'),
                          ('helpers/n9-tools-r21/compare_arms_r21.py', 'REPAIRS_COMPLETE')]:
        tree = ast.parse(outputs[member])
        values = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == flag for t in n.targets)]
        require(values == [False], 'public source readiness guard changed')
    _, _, _, applier = receiving.load(repo)
    return parent, utilities, mapping, outputs, applier


def materialise(repo, destination):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    for root in (repo, HERE):
        out, source = destination.resolve(), root.resolve()
        require(out != source and not out.is_relative_to(source) and not source.is_relative_to(out),
                'output overlaps read-only source')
    parent, utilities, mapping, outputs, applier = contract(repo)
    utilities.inside(Path(destination.anchor), destination.relative_to(destination.anchor).as_posix())
    utilities.refuse_existing(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.p31w-', dir=destination.parent) as temporary:
        stage = Path(temporary)/'source'
        prior = parent.materialise(repo, stage)
        require(prior['source_map_sha256'] == mapping['base_source_map_sha256'] and len(prior['files']) == 697,
                'actual complete final-source predecessor differs')
        files = dict(prior['files'])
        parent.verify_inventory(stage, files, utilities)
        changed = {}
        for name, row in mapping['rows'].items():
            old = utilities.read_source(stage, name)
            require(files.get(name) == row['public_base_sha256'] and digest(old) == row['public_base_sha256'],
                    'same-base source pin differs: '+name)
            if row['diff'] is not None:
                patch = utilities.read_source(HERE, row['diff'])
                require(applier.apply_diff(old, patch, name) == outputs[name], 'strict width derivation differs')
            utilities.inside(stage, name).write_bytes(outputs[name])
            files[name] = row['public_output_sha256']
            changed[name] = {'before': row['public_base_sha256'], 'after': row['public_output_sha256']}
        require(files['helpers/width_gate.py'] == mapping['width_gate_sha256'], 'width gate/helper changed')
        parent.verify_inventory(stage, files, utilities)
        result = dict(prior, schema='atlas.public.plan31.guarded-width.materialised-source.r1',
            source_map_sha256=MAP_SHA, parent_source_map_sha256=prior['source_map_sha256'],
            files=files, receiving_changes=changed, N9_width_selected=True, condition5_selected=True,
            full_C4_accepted=False, reader_width_tables_accepted=False, IV_permitted=False,
            public_guards_enabled=False, public_private_runnable_identity_equal=False,
            selection_sha256=utilities.generation({'member': 'source/'+name, 'public_sha256': pin}
                                                  for name, pin in files.items()))
        (stage/'SOURCE-MANIFEST.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',
                                                encoding='utf-8',newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    record = materialise(args.repo,args.out)
    print(json.dumps({k:v for k,v in record.items() if k not in ('files','changed_rows_from_s1a','receiving_changes')},sort_keys=True))


if __name__ == '__main__':
    main()
