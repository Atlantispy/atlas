"""Additive Plan39 source-constructor candidate; no run or scientific authority."""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
CATALOGUE_SHA256 = '019944bf42007397c3cacb8756ea2e62862afa5170c79e28601d7a914cd86d22'
HISTORICAL_INPUTS = {'path':'ac/p31-hi-data-r1/HISTORICAL-INPUTS-r1.json','sha256':CATALOGUE_SHA256}
SELECTION_SCHEMA = 'atlas.private.plan31.plan39-source-selection.r1'

T = HERE = CONTROL = UTILITY = SUPPORT = None
CONSTRUCTION_CONTEXT = DESTINATION_OWNER = None


def configure(*, workspace, plan_parent, control_root, utility, support,
              context_binding, owner, selection, generation, selected_files, source_graph):
    """Bind one authenticated external context; source algorithms stay closed."""
    global T, HERE, CONTROL, UTILITY, SUPPORT, CONSTRUCTION_CONTEXT, DESTINATION_OWNER
    require(CONSTRUCTION_CONTEXT is None, 'constructor context already configured')
    T, HERE, CONTROL = map(Path, (workspace, plan_parent, control_root))
    UTILITY, SUPPORT = checked_ref(utility), checked_ref(support)
    CONSTRUCTION_CONTEXT = {'binding': checked_ref(context_binding),
                            'selection': checked_ref(selection), 'generation': generation,
                            'selected_files': dict(selected_files), 'source_graph': checked_ref(source_graph)}
    DESTINATION_OWNER = owner


def require(condition, message):
    if not condition:
        raise ValueError(message)



def digest(raw):
    return hashlib.sha256(raw).hexdigest()



def load(binding, name):
    path = Path(binding['path'])
    require(path.is_absolute() and path == path.resolve(), 'canonical implementation path required')
    raw = path.read_bytes()
    require(digest(raw) == binding['sha256'], 'implementation pin differs: '+name)
    spec = importlib.util.spec_from_file_location('_plan31_app_'+name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module



def same_ref(U,left,right):
    require(type(left) is dict and type(right) is dict and set(left)==set(right)=={'path','sha256'},'closed file references required')
    return left['sha256']==right['sha256'] and U.ordinary(Path(left['path']))==U.ordinary(Path(right['path']))



def rel(path):
    return Path(path).relative_to(T).as_posix()



def reference(path, raw):
    return {'path': str(path), 'sha256': digest(raw)}



def refuse(value):
    if isinstance(value, dict):
        require('purpose' not in value, 'purpose key refused, including falsey values')
        for key, item in value.items():
            require(not (isinstance(key, str) and key.casefold().startswith('plan31:rehearsal-')), 'rehearsal key refused')
            refuse(item)
    elif isinstance(value, list):
        for item in value:
            refuse(item)
    elif isinstance(value, str):
        require(not value.casefold().startswith('plan31:rehearsal-'), 'rehearsal value refused')



def translate(name, before, after):
    prefix = rel(before)+'/'
    require(type(name) is str and name.startswith(prefix), 'source member outside its declared parent')
    return rel(after)+'/'+name[len(prefix):]



def check_paths(U, roots, input_paths, outputs):
    require(len({str(p).casefold() for p in roots}) == len(roots), 'root case collision')
    for root in roots:
        require(root.is_absolute() and root == root.resolve() and not U.exists(root), 'occupied/noncanonical destination: '+str(root))
        U.ordinary(root.parent, directory=True)
        for other in roots:
            require(root == other or not root.is_relative_to(other), 'overlapping output roots')
        for name in input_paths:
            source = Path(name)
            require(source != root and not source.is_relative_to(root) and not root.is_relative_to(source), 'output/input overlap')
    seen = set()
    for path in outputs:
        require(path.is_absolute() and path == path.resolve() and any(path.is_relative_to(r) for r in roots), 'output outside selected roots')
        require(str(path).casefold() not in seen, 'case-insensitive output collision')
        require(len(str(path))+8 < 260, 'MAX_PATH allowance exceeded: '+str(path))
        require(not U.exists(path), 'existing output refused')
        seen.add(str(path).casefold())



def emit(U,path,raw):
    require(not U.exists(path),'existing output refused')
    missing=[];parent=path.parent
    while not U.exists(parent):missing.append(parent);parent=parent.parent
    U.ordinary(parent,directory=True)
    for directory in reversed(missing):directory.mkdir();U.ordinary(directory,directory=True)
    with path.open('xb') as stream:stream.write(raw)
    require(U.ordinary(path).read_bytes()==raw,'emitted bytes differ')
    return reference(path,raw)



def safe_member(name):
    require(type(name) is str and name.startswith(('src/','helpers/'))
            and not any(c in name for c in '\\:\0')
            and all(p and p not in ('.','..') and p.rstrip(' .') == p for p in name.split('/')),
            'unsafe selected source member')
    return name


def checked_ref(value):
    require(type(value) is dict and set(value) == {'path','sha256'}
            and type(value['path']) is str and Path(value['path']).is_absolute()
            and type(value['sha256']) is str and len(value['sha256']) == 64
            and all(c in '0123456789abcdef' for c in value['sha256']), 'closed absolute file binding required')
    return value


def closed_source_frame(frame):
    require(type(frame) is dict and frame.get('schema') == 'plan31.plan39.production-membership-candidate.r1'
            and frame.get('full_repin_graph_closed') is True
            and frame.get('active_current_pin_graph_reconciled') is True
            and frame.get('missing_imports_to_explicitly_excluded_members') == []
            and frame.get('constructed') is False and frame.get('runtime_qualified') is False,
            'settled source membership/repin closure required before construction')


def parent_admission(receipt,derivation):
    for record in (receipt,derivation):
        refuse(record)
        require(type(record) is dict and record.get('schema') == 'atlas.private.plan31.final-generation.r1'
            and record.get('status') == 'PREPARED_SOURCE_NOT_QUALIFIED' and record.get('pending') == []
            and record.get('completed_query_store') == 'files' and record.get('source_only') is True
            and record.get('fold_not_performed') is True
            and all(record.get(k) is False for k in ('execution_authority','interval_authority','scientific_acceptance','default_changed','holds_released')),
            'actual source-only prepared parent required')
    require(receipt.get('input_finality') is True and receipt.get('output_finality') is True,
            'parent construction finality required')


def row_provenance(U,inputs,base,name,row,raw):
    """Authenticate known historical annotations without selecting their bytes."""
    if 'supersedes_input' in row:
        previous = row['supersedes_input']
        if previous is None:
            require(name == 'helpers/runtime_interval_predictor.py'
                and row['parent_sha256'] is None and row['origin'] == 'received-component-port-candidate'
                and 'pin_site' not in row, 'null supersedes input is not this explicit new-member case')
            return
        checked_ref(previous)
        before = inputs.raw(Path(previous['path']),previous['sha256'])
        require(before != raw, 'supersedes provenance does not precede different selected bytes')
        if 'pin_site' in row:
            require(type(row['pin_classification']) is str and row['pin_classification'].strip(),
                    'nonempty pin classification required')
            site = row['pin_site']
            require(type(site) is dict and set(site) == {'assignment','line','old','new','occurrences','other_AST_unchanged'}
                and type(site['assignment']) is str and site['assignment'].isidentifier()
                and type(site['line']) is int and site['line'] > 0
                and type(site['occurrences']) is int and site['occurrences'] == 1
                and site['other_AST_unchanged'] is True, 'closed classified pin site required')
            expected = {'helpers/partition_routing_transform.py':'DERIVED_CONTROL_SHA256',
                        'helpers/private_heat_original_continuation_r1.py':'_SOURCE_SHA'}
            require(expected.get(name) == site['assignment'], 'classified pin assignment/member differs')
            for value in (site['old'],site['new']):
                require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
                        'classified pin values must be lowercase SHA256 literals')
            require(site['old'] != site['new'], 'classified pin did not change')
            trees = []
            for source,value in ((before,site['old']),(raw,site['new'])):
                text = source.decode('utf-8')
                tree = ast.parse(text)
                nodes = [n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0],ast.Name) and n.targets[0].id == site['assignment']]
                require(len(nodes) == 1 and nodes[0].lineno == site['line']
                    and ast.literal_eval(nodes[0].value) == value and text.count(value) == site['occurrences'],
                    'classified pin site differs from authenticated source')
                nodes[0].value = ast.Constant(value='[classified pin value]')
                trees.append(ast.dump(tree,include_attributes=False))
            require(trees[0] == trees[1], 'classified pin changed other AST')
    if 'omitted_optional_component_input' in row:
        require(name == 'helpers/private_heat_endpoint_inventory_r3.py'
            and row['origin'] == 'parent-retained-by-owner-disposition'
            and row['parent_sha256'] is not None
            and U.ordinary(Path(row['input']['path'])) == U.ordinary(base/name)
            and digest(raw) == row['parent_sha256'], 'omitted optional component must retain its exact parent')
        previous = checked_ref(row['omitted_optional_component_input'])
        require(inputs.raw(Path(previous['path']),previous['sha256']) != raw,
                'omitted optional source aliases selected parent bytes')


def overlay_payload(U,inputs,base,frame,native,helpers):
    """Apply only complete explicit members and before pins; inventory is never guessed."""
    expected = {**{'src/'+n:v for n,v in native.items()},**{'helpers/'+n:v for n,v in helpers.items()}}
    members = frame.get('members')
    require(type(members) is dict and members, 'explicit nonempty selected member map required')
    require(len({n.casefold() for n in members}) == len(members), 'selected case alias')
    payload,changes,additions = {},{},{}
    for name,row in members.items():
        safe_member(name)
        required = {'input','origin','parent_sha256'}
        shapes = (required,required|{'supersedes_input'},
                  required|{'supersedes_input','pin_classification','pin_site'},
                  required|{'omitted_optional_component_input'})
        require(type(row) is dict and set(row) in shapes
                and type(row['origin']) is str and row['origin'], 'closed selected member row required')
        source = checked_ref(row['input'])
        require(row['parent_sha256'] == expected.get(name), 'selected predecessor pin differs: '+name)
        raw = inputs.raw(Path(source['path']),source['sha256'])
        row_provenance(U,inputs,base,name,row,raw)
        if name in expected:
            before = inputs.raw(base/name,expected[name])
            if raw != before:
                changes[name] = {'before':expected[name],'after':source['sha256']}
        else:
            additions[name] = source['sha256']
        if name.endswith('.py'):
            ast.parse(raw,filename=name)
        payload[name] = raw
    omitted = set(expected)-set(members)
    classified = {}
    for category in ('explicit_exclusions','other_unselected_not_runtime_reachable'):
        rows = frame.get(category)
        require(type(rows) is dict, 'explicit omitted-source dispositions required')
        for name,row in rows.items():
            safe_member(name)
            require(name not in members, 'excluded member also selected')
            if name not in omitted:
                continue
            require(name not in classified, 'duplicate omitted parent disposition')
            binding = row.get('input') if type(row) is dict and 'input' in row else row
            checked_ref(binding)
            # The removal always binds the actual parent; the non-reachable map
            # may separately name a newer excluded candidate as provenance.
            inputs.raw(base/name,expected[name])
            if category == 'explicit_exclusions':
                require(binding['sha256'] == expected[name], 'omitted parent pin differs: '+name)
                require(U.ordinary(Path(binding['path'])) == U.ordinary(base/name), 'omitted parent path differs: '+name)
                require(type(row.get('reasons')) is list and row['reasons']
                        and all(type(v) is str and v.strip() for v in row['reasons']), 'reasoned exclusion required')
                classified[name] = {'sha256':expected[name],'disposition':category}
            else:
                inputs.raw(Path(binding['path']),binding['sha256'])
                classified[name] = {'sha256':expected[name],'disposition':category,'excluded_candidate':copy.deepcopy(binding)}
    require(set(classified) == omitted, 'unclassified omitted parent source')
    native_new = {k[4:]:digest(v) for k,v in payload.items() if k.startswith('src/')}
    helpers_new = {k[8:]:digest(v) for k,v in payload.items() if k.startswith('helpers/')}
    require(native_new and helpers_new and 'atlas_tectonics/__init__.py' in native_new, 'complete native/helper roots required')
    data_old = {k:v for k,v in native.items() if not k.endswith('.py')}
    data_new = {k:v for k,v in native_new.items() if not k.endswith('.py')}
    require(data_old.keys() == data_new.keys(), 'native DATA asset membership changed')
    data_delta = {name:(before,data_new[name]) for name,before in data_old.items() if before != data_new[name]}
    allowed_data_delta = {
        'atlas_tectonics/_fixtures/cases/i03_controls_v3.json': (
            'a8b2eed96f43f6b92f52919f26442087dd075122ca613c8a996d95c040219c67',
            '8b5d16fd4a0f829484ed990991652181a6d3a007ac6dd0cba116edac6541a505'),
        'atlas_tectonics/_fixtures/cases/i04_controls_v1.json': (
            '40d7ee7c9b022adc9b3f1b2d6e692839e22026c810d86bd1792438d0ff759de9',
            '7ff5062a2e85956a2b2f0a9a5e7e97e0438cad3e2f100726b32ff69597193f9a')}
    require(all(allowed_data_delta.get(name) == pair for name, pair in data_delta.items()),
        'unapproved public DATA counterpart change')
    exterior = {k:v for k,v in native_new.items() if k.endswith('.py') and not k.startswith('atlas_tectonics/')}
    require(set(exterior) <= {'atlas_runtime.py'}, 'unexplained source-root Python facade')
    require(CATALOGUE_SHA256 not in {digest(v) for v in payload.values()}, 'historical catalogue executable-byte alias')
    return payload,native_new,helpers_new,changes,additions,classified


def helper_review_rows(previous,frame,helper_pins,stage):
    result = {}
    for name,pin in helper_pins.items():
        row = frame['members']['helpers/'+name]
        after,prior = row['input'],previous.get(name)
        if prior is not None and prior['sha256'] == pin:
            result[name] = copy.deepcopy(prior)
            continue
        current = {'path':after['path'],'sha256':pin,'input':copy.deepcopy(after),'stage':stage}
        if prior is not None:
            current['parent_review'] = copy.deepcopy(prior)
        result[name] = current
    return result


def fixture_frame_match(frame_value,binding,declaration):
    require(type(frame_value) is dict, 'explicit membership fixture frame required')
    if set(frame_value) == {'path','sha256'}:
        checked_ref(frame_value)
        require(frame_value == binding, 'membership fixture reference differs')
    else:
        require(set(frame_value) == {'schema','modules','by_path'} and frame_value == declaration,
                'membership inline fixture declaration differs')


def fixture_map(payload,declaration,target):
    require(type(declaration) is dict and set(declaration) == {'schema','modules','by_path'}
            and declaration['schema'] == 'atlas.executable-fixtures.r1'
            and type(declaration['modules']) is dict and declaration['modules']
            and type(declaration['by_path']) is dict, 'closed executable fixture map required')
    require(not declaration['modules'].keys() & declaration['by_path'].keys(), 'logical/by-path fixture collision')
    physical = {name for name in payload if name.startswith('src/atlas_tectonics/_fixtures/') and name.endswith('.py')}
    native_names = {'.'.join(Path(name[len('src/atlas_tectonics/'):]).with_suffix('').parts)
        for name in payload if name.startswith('src/atlas_tectonics/') and name.endswith('.py')
        and not name.startswith('src/atlas_tectonics/_fixtures/') and Path(name).name != '__init__.py'}
    mapped = set()
    for name,path in {**declaration['modules'],**declaration['by_path']}.items():
        require(type(name) is str and name.isidentifier() and name not in sys.stdlib_module_names, 'invalid fixture name')
        require(name not in native_names, 'fixture logical name collides with native module')
        prefix = rel(target)+'/'
        require(type(path) is str and path.startswith(prefix), 'fixture outside new source root')
        member_name = safe_member(path[len(prefix):])
        require(member_name in physical and (Path(member_name).stem == name or name in declaration['by_path']),
                'fixture is not selected physical Python source')
        mapped.add(member_name)
    require(mapped == physical and physical, 'fixture map must cover every emitted physical fixture exactly')
    return copy.deepcopy(declaration)


def policy_rows(historical,current,parent,review,old_runtime,runtime,new_evidence):
    require(type(review) is dict and set(review) == {'native','evidence'}
            and type(review['native']) is dict and type(review['evidence']) is dict, 'closed explicit policy review required')
    delta = {n for n in historical['source_hashes'].keys() | current['source_hashes'].keys()
             if historical['source_hashes'].get(n) != current['source_hashes'].get(n)}
    require(set(review['native']) <= delta, 'policy review names an unchanged native member')
    rows = {}
    for name in sorted(delta):
        before,after = historical['source_hashes'].get(name),current['source_hashes'].get(name)
        explicit,prior = review['native'].get(name),parent['reviewed_changes'].get(name)
        if explicit is not None:
            require(type(explicit) is dict and set(explicit) == {'reason','evidence'}
                    and type(explicit['reason']) is str and explicit['reason'].strip()
                    and type(explicit['evidence']) is list and explicit['evidence']
                    and all(type(v) is str and v in new_evidence for v in explicit['evidence']),
                    'unbound new native review row: '+name)
            rows[name] = {'before':before,'after':after,'reason':explicit['reason'],
                          'evidence':[rel(runtime/'evidence'/n) for n in explicit['evidence']]}
        else:
            require(type(prior) is dict and prior['before'] == before and prior['after'] == after,
                    'actual new/changed/removed native member lacks reviewed disposition: '+name)
            rows[name] = copy.deepcopy(prior)
            rows[name]['evidence'] = [translate(v,old_runtime,runtime) for v in prior['evidence']]
    return rows


def bootstrap_frame(raw, *, base_relative, target_relative, old_counts, new_counts, payload):
    """Bind the selected fresh-runner CLI; retain its existing admission gates."""
    entry = 'run_fresh_interval.py'
    require('helpers/'+entry in payload, 'selected fresh bootstrap entry is absent')
    tree = ast.parse(payload['helpers/'+entry])
    require(any(isinstance(node, ast.FunctionDef) and node.name == 'main' for node in tree.body),
            'selected fresh bootstrap entry must expose its existing main')
    replacements = (
        (('REAL_ROOT = T / "'+base_relative+'"').encode(), ('REAL_ROOT = T / "'+target_relative+'"').encode()),
        (('REAL_COUNTS = '+str(old_counts)).encode(), ('REAL_COUNTS = '+str(new_counts)).encode()),
        (b'ENTRY_NAME = "launch_fresh_interval.py"', b'ENTRY_NAME = "run_fresh_interval.py"'),
        (b'Pinned outer entry for the unchanged native launcher under Python -B -s -P.',
         b'Pinned outer entry for the selected fresh runner under Python -B -s -P.'),
        (b'This changes no import path or native child command.',
         b'Use the fresh runner --mode/profile CLI; existing launch/workload admission gates remain.'),
        (b'Execute only the original native launcher, restoring caller-owned state.',
         b'Execute only the selected fresh runner, restoring caller-owned state.'),
    )
    for before, after in replacements:
        require(raw.count(before) == 1, 'unique bootstrap source/count/entry anchor required')
        raw = raw.replace(before, after)
    ast.parse(raw)
    return raw


def derive(frozen,constructor_path,core_binding,selection_path=None,selection_pin=None):
    require(sys.dont_write_bytecode and os.name == 'nt', 'Windows constructor with -B required')
    require(CONSTRUCTION_CONTEXT is not None and type(frozen) is dict and len(frozen) == 1, 'one authenticated context selection required')
    generation,binding = next(iter(frozen.items()))
    checked_ref(binding)
    require(generation == CONSTRUCTION_CONTEXT['generation'] and binding == CONSTRUCTION_CONTEXT['selection'], 'context selection override refused')
    require(selection_path in (None,binding['path']) and selection_pin in (None,binding['sha256']), 'frozen selection override refused')
    U = load(UTILITY,'utility')
    inputs = U.Inputs()
    for ref in (UTILITY,core_binding,SUPPORT,CONSTRUCTION_CONTEXT['binding'],CONSTRUCTION_CONTEXT['source_graph']):
        inputs.raw(Path(checked_ref(ref)['path']),ref['sha256'])
    require(Path(core_binding['path']) == Path(__file__).resolve(), 'actual executing core binding required')
    constructor = reference(constructor_path,inputs.raw(constructor_path,digest(constructor_path.read_bytes())))
    s = inputs.doc(Path(binding['path']),binding['sha256'])
    refuse(s)
    fields = {'schema','status','generation','stage','line','pending','completed_query_store','source_only','apply_authorised',
        'runnable','default_changed','scientific_acceptance','IV_permitted','target_root','runtime_root','owned_root',
        'base','base_composition_sha256','parent','producer_contract','destination_authority','membership','fixture_map',
        'profile_maps','plan02_binding','historical_inputs','historical_seed','supplementary_inputs','policy_review'}
    require(type(s) is dict and set(s) == fields and s['schema'] == SELECTION_SCHEMA
        and s['status'] == 'SOURCE_SELECTION_FROZEN' and s['generation'] == generation and s['line'] == 'final'
        and s['pending'] == [] and s['completed_query_store'] == 'files' and s['source_only'] is True
        and all(s[k] is False for k in ('apply_authorised','runnable','default_changed','scientific_acceptance','IV_permitted')),
        'closed frozen no-run source selection required')
    require(type(s['stage']) is str and s['stage'] == 'plan31:final-generation-'+generation, 'exact generation stage required')
    authority = inputs.doc(Path(checked_ref(s['destination_authority'])['path']),s['destination_authority']['sha256'])
    target,runtime,owned = (Path(s[k]) for k in ('target_root','runtime_root','owned_root'))
    require(authority['generation'] == generation and all(Path(authority[k]) == p for k,p in [('source',target),('runtime',runtime),('owned',owned)])
            and authority.get('owner') == DESTINATION_OWNER
            and authority.get('blockers') == [] and authority.get('selection_not_frozen') is False,
            'exact settled sole-owner destination authority required')
    require(target.parent == runtime.parent == T/'ac' and owned.parent == CONTROL, 'closed output parents differ')
    require(s['historical_inputs'] == HISTORICAL_INPUTS, 'fixed historical DATA binding differs')
    inputs.raw(T/HISTORICAL_INPUTS['path'],CATALOGUE_SHA256)
    require(type(s['supplementary_inputs']) is list, 'explicit source evidence bindings required')
    for ref in s['supplementary_inputs']:
        inputs.raw(Path(checked_ref(ref)['path']),ref['sha256'])
    parent = s['parent']
    base,old_runtime = Path(parent['root']),Path(parent['runtime'])
    require(base.as_posix() == s['base'] and parent['composition']['sha256'] == s['base_composition_sha256'], 'parent composition binding differs')
    for key in ('composition','reviewed_inputs','manifest','fresh_profile','prepared_profile','receipt','derivation','bootstrap','policy'):
        checked_ref(parent[key])
    for key,path in {'composition':base/'composition.json','manifest':old_runtime/'manifest.json',
        'fresh_profile':old_runtime/'fresh-profile.json','prepared_profile':old_runtime/'prepared-profile.json',
        'derivation':old_runtime/'derivation.json','policy':old_runtime/'runtime-policy.json'}.items():
        require(U.ordinary(Path(parent[key]['path'])) == U.ordinary(path), 'exact parent metadata path differs: '+key)
    comp,reviewed,native,helpers = U.composition(inputs,base,parent['composition']['sha256'],Path(parent['reviewed_inputs']['path']),parent['reviewed_inputs']['sha256'])
    old_manifest = inputs.doc(Path(parent['manifest']['path']),parent['manifest']['sha256'])
    fresh = inputs.doc(Path(parent['fresh_profile']['path']),parent['fresh_profile']['sha256'])
    prepared = inputs.doc(Path(parent['prepared_profile']['path']),parent['prepared_profile']['sha256'])
    receipt = inputs.doc(Path(parent['receipt']['path']),parent['receipt']['sha256'])
    derivation = inputs.doc(Path(parent['derivation']['path']),parent['derivation']['sha256'])
    parent_admission(receipt,derivation)
    for key in ('composition_sha256','manifest_sha256','profile_sha256','prepared_profile','reviewed_inputs','bootstrap','source_inputs'):
        require(receipt[key] == derivation[key], 'parent receipt/derivation mismatch: '+key)
    require(receipt['composition_sha256'] == parent['composition']['sha256'] and receipt['manifest_sha256'] == parent['manifest']['sha256']
        and receipt['profile_sha256'] == parent['fresh_profile']['sha256'] and receipt['derivation_sha256'] == parent['derivation']['sha256']
        and same_ref(U,receipt['prepared_profile'],parent['prepared_profile']) and receipt['reviewed_inputs'] == parent['reviewed_inputs']
        and receipt['bootstrap'] == parent['bootstrap'] and receipt.get('input_finality') is True and receipt.get('output_finality') is True,
        'parent final output/finality bindings differ')
    for record,schema in ((fresh,'atlas.fresh-interval-profile.v2'),(prepared,'atlas.prepared-restart-launch.v3')):
        require(record['schema'] == schema and record['workspace'] == str(T) and record['native_root'] == rel(base/'src')
            and record['import_roots'] == [rel(base/'helpers')] and record['historical_inputs'] == HISTORICAL_INPUTS
            and record['source_manifest'] == {'path':rel(old_runtime/'manifest.json'),'sha256':parent['manifest']['sha256']}, 'parent profile source frame differs')
    frame = inputs.doc(Path(checked_ref(s['membership'])['path']),s['membership']['sha256'])
    closed_source_frame(frame)
    payload,native_new,helpers_new,changes,additions,removals = overlay_payload(U,inputs,base,frame,native,helpers)
    require({name:digest(raw) for name,raw in payload.items()} == CONSTRUCTION_CONTEXT['selected_files'], 'public source/constructor selected bytes differ')
    declaration = inputs.doc(Path(checked_ref(s['fixture_map'])['path']),s['fixture_map']['sha256'])
    fixtures = fixture_map(payload,declaration,target)
    fixture_frame_match(frame.get('fixture_map'),s['fixture_map'],declaration)
    profile_doc = inputs.doc(Path(checked_ref(s['profile_maps'])['path']),s['profile_maps']['sha256'])
    require(profile_doc.get('schema') == 'plan31.plan39.profile-member-maps.r1' and profile_doc.get('historical_data') == HISTORICAL_INPUTS,
            'profile member-map frame differs')
    maps = {}
    for key,count in (('fresh',21),('prepared',41)):
        row = profile_doc['profiles'][key]
        mapping = row['required_modules']
        require(row['required_count'] == row['selected_count'] == count and row['selected_modules'] == mapping,
                'exact required-only profile selection required')
        maps[key] = mapping
    support_context = {'source_root':rel(target),'runtime_root':rel(runtime),'profile_maps':maps,
        'source_pins':{'runners':{n:digest(payload['helpers/'+n+'.py']) for n in ('run_fresh_interval','run_prepared_restart')},
        'probe':digest(payload['helpers/probe_execution_identity.py']),
        'drivers':{n:digest(payload['helpers/'+n+'.py']) for n in ('fresh_interval_driver','prepared_interval_driver')},
        'preparation':{'path':rel(target/'helpers/runtime_radial_fixture.py'),'sha256':digest(payload['helpers/runtime_radial_fixture.py'])}}}
    S = load(SUPPORT,'profiles')
    S.configure(**support_context)
    layout = S.profile_layout(inputs,workspace=T,payload=payload,parent_fresh_binding=parent['fresh_profile'],line='final')
    require(checked_ref(s['plan02_binding'])['sha256'] == S.PLAN02_SHA256, 'unchanged c697 prepared component required')
    inputs.raw(Path(s['plan02_binding']['path']),S.PLAN02_SHA256)
    inputs.raw(Path(s['plan02_binding']['path']).with_name('historical_input_contract.py'),S.HISTORICAL_HELPER_SHA256)
    historical,_,_ = S.historical_policy_inputs(inputs,workspace=T,seed_policy_binding=checked_ref(s['historical_seed']))
    contract = inputs.doc(Path(checked_ref(s['producer_contract'])['path']),s['producer_contract']['sha256'])
    require(contract['schema'] == 'atlas.public.plan31.context-producer-contract.r1'
            and contract['generation'] == generation and Path(contract['constructor_path']) == constructor_path
            and Path(contract['selection_path']) == Path(binding['path']), 'actual producer contract paths differ')
    require(contract.get('frozen_selection_binding') == {
        'kind':'EXTERNAL_AUTHENTICATED_CLOSED_CONTEXT',
        'context_schema':'atlas.public.plan31.construction-context.r1',
        'selected_path':binding['path'], 'entry_is_independently_pinned':True,
        'selection_and_context_are_independently_hashed':True,
        'exact_rederived_plan_required_for_apply':True, 'no_literal_wrapper_claim':True}
        and all(contract['frozen_selection_binding'][key] is True for key in (
            'entry_is_independently_pinned', 'selection_and_context_are_independently_hashed',
            'exact_rederived_plan_required_for_apply', 'no_literal_wrapper_claim')),
        'exact external-context producer binding required')
    for key,value in contract['selection_admission']['required_values'].items():
        require(s.get(key) == value, 'selection contract mismatch: '+key)
    reviewed = copy.deepcopy(reviewed)
    reviewed.update(target=target.name,target_root=str(target),outputs=native_new)
    reviewed['helpers'] = helper_review_rows(reviewed['helpers'],frame,helpers_new,s['stage'])
    require(s['stage'] not in reviewed['staged'], 'new stage already exists')
    reviewed['staged'][s['stage']] = {'schema':'atlas.private.plan31.final-stage.r1','generation':generation,'stage':s['stage'],
        'status':'SOURCE_SELECTION_FROZEN','pending':[],'selection_path':binding['path'],'selection_sha256':binding['sha256'],
        'constructor':constructor,'parent_composition_sha256':s['base_composition_sha256'],'producer_contract':s['producer_contract'],
        'source_membership':s['membership'],'fixture_map':s['fixture_map'],'historical_inputs':HISTORICAL_INPUTS,
        'completed_query_store':'files','source_only':True,'fold_not_performed':True,'observer_reissue_required':True,
        'execution_authority':False,'interval_authority':False,'scientific_acceptance':False,'default_changed':False,'holds_released':False}
    for name in sorted(changes.keys() | additions.keys() | removals.keys()):
        reviewed['stages'].append({'module':name,'stage':s['stage'],
            'input_sha256':changes.get(name,{}).get('before',removals.get(name,{}).get('sha256')),
            'output_sha256':digest(payload[name]) if name in payload else None,
            'note':'Explicit selected Plan39 source disposition; original parent retained.'})
    old_policy = inputs.doc(Path(parent['policy']['path']),parent['policy']['sha256'])
    require(old_policy.get('historical') == historical
        and old_policy['current']['source_hashes'] == old_manifest['source_hashes']
        and old_policy['current']['source_manifest_path'] == rel(old_runtime/'manifest.json')
        and old_policy['current']['source_manifest_sha256'] == parent['manifest']['sha256'],
        'parent policy/source/runtime frame differs')
    review = s['policy_review']
    require(type(review) is dict and set(review) == {'native','evidence'} and type(review['evidence']) is dict, 'explicit policy review required')
    new_evidence,evidence_raw = {},{}
    fixed_evidence = {'source-membership.json':s['membership'],'fixture-map.json':s['fixture_map'],'profile-members.json':s['profile_maps']}
    require(not fixed_evidence.keys() & review['evidence'].keys(), 'review evidence collides with fixed source evidence')
    for name,ref in {**fixed_evidence,**review['evidence']}.items():
        require(type(name) is str and name and '/' not in name and not any(c in name for c in '\\:\0') and name.rstrip(' .') == name
                and name not in ('.','..'), 'unsafe evidence member')
        raw = inputs.raw(Path(checked_ref(ref)['path']),ref['sha256'])
        evidence_raw[name],new_evidence[name] = raw,ref['sha256']
    projected_native = {n:v for n,v in native_new.items() if n.startswith('atlas_tectonics/') and n.endswith('.py')}
    policy_rows(historical,{'source_hashes':projected_native},old_policy,review,old_runtime,runtime,new_evidence)
    # Close source metadata only after every construction input is authenticated.
    for path,pin in inputs.pins.items():
        require(path not in reviewed['files'] or reviewed['files'][path] == pin, 'conflicting historical reviewed input')
        reviewed['files'][path] = pin
    reviewed_path = owned/'reviewed-inputs.json'
    reviewed_raw = U.canonical(reviewed)
    comp = copy.deepcopy(comp)
    comp.update(root=str(target),outputs=native_new,helpers=helpers_new,staged=reviewed['staged'],stages=reviewed['stages'],reviewed_inputs=str(reviewed_path),reviewed_inputs_sha256=digest(reviewed_raw))
    refuse(comp)
    refuse(reviewed)
    comp_raw = U.canonical(comp)
    before = {**{rel(base/'src'/n):v for n,v in native.items()},**{rel(base/'helpers'/n):v for n,v in helpers.items()}}
    require(old_manifest['files'] == {k:v for k,v in before.items() if k.endswith('.py')}, 'parent executable manifest/source membership differs')
    require(all(old_manifest['data_only'].get(k) == v for k,v in before.items() if not k.endswith('.py'))
        and old_manifest['data_only'].get(rel(base/'composition.json')) == parent['composition']['sha256'], 'parent DATA/composition manifest differs')
    outputs = {target/n:raw for n,raw in payload.items()}
    outputs.update({reviewed_path:reviewed_raw,target/'composition.json':comp_raw})
    data = {rel(target/n):digest(raw) for n,raw in payload.items() if not n.endswith('.py')}
    data[rel(target/'composition.json')] = digest(comp_raw)
    def planned(path,raw):
        require(path not in outputs or outputs[path] == raw, 'conflicting planned evidence/output')
        outputs[path],data[rel(path)] = raw,digest(raw)
    for name,pin in old_manifest['data_only'].items():
        if name in before or name == rel(base/'composition.json'):
            continue
        raw = inputs.raw(U.member(T,name),pin)
        if name.startswith(rel(old_runtime)+'/evidence/'):
            planned(T/translate(name,old_runtime,runtime),raw)
        else:
            data[name] = pin
    for name,pin in old_policy['evidence'].items():
        planned(T/translate(name,old_runtime,runtime),inputs.raw(U.member(T,name),pin))
    for name,raw in evidence_raw.items():
        planned(runtime/'evidence'/name,raw)
    data[HISTORICAL_INPUTS['path']] = CATALOGUE_SHA256
    files = {rel(target/n):digest(raw) for n,raw in payload.items() if n.endswith('.py')}
    native_hashes = {n:v for n,v in native_new.items() if n.startswith('atlas_tectonics/') and n.endswith('.py')}
    manifest = copy.deepcopy(old_manifest)
    manifest.update(files=files,data_only=data,source_hashes=native_hashes,
        composition={'root':rel(target),'composition_json':rel(target/'composition.json'),'composition_sha256':digest(comp_raw),
        'frozen':False,'import_root_order':[rel(target/'helpers')]},fixture_source_map=fixtures)
    require(not files.keys() & data.keys() and data[HISTORICAL_INPUTS['path']] == CATALOGUE_SHA256
        and HISTORICAL_INPUTS['path'] not in files and CATALOGUE_SHA256 not in files.values(), 'DATA/source separation differs')
    refuse(manifest)
    outputs[runtime/'manifest.json'] = U.canonical(manifest)
    boot = inputs.raw(Path(parent['bootstrap']['path']),parent['bootstrap']['sha256'])
    boot = bootstrap_frame(boot, base_relative=rel(base), target_relative=rel(target),
        old_counts=(len(native),len(helpers)), new_counts=(len(native_new),len(helpers_new)), payload=payload)
    outputs[owned/'bootstrap_native.py'] = boot
    deferred = [runtime/n for n in ('derivation.json','fresh-profile.json','prepared-profile.json','execution-identity.json','runtime-policy.json')]+[owned/n for n in ('BUILD-RESULT.json','identity-probe-process.json','prepared-construction.json')]
    transient = [owned/'BUILD-RESULT.unpublished.json',owned/'CONSTRUCTION-FAILED.json']
    check_paths(U,[target,runtime,owned],inputs.pins,list(outputs)+deferred+transient)
    inputs.recheck()
    plan = {'schema':'atlas.private.plan31.plan39-source-plan.r1','status':'UNEXECUTED_SOURCE_PLAN','selection':binding,'constructor':constructor,
        'core':core_binding,'source_inputs':dict(inputs.pins),'outputs':{str(p):{'sha256':digest(raw),'bytes':len(raw)} for p,raw in sorted(outputs.items(),key=lambda x:str(x[0]))},
        'deferred_metadata':[str(p) for p in deferred],'transient_or_failure_metadata':[str(p) for p in transient],
        'changed_source_members':len(changes),'added_source_members':len(additions),'removed_parent_source_members':len(removals),
        'preserved_source_members':len(payload)-len(changes)-len(additions),'source_root_members':len(native_new),
        'native_package_python_members':len(native_hashes),'helper_members':len(helpers_new),'source_only':True,'worker_dispatched':False,'scientific_acceptance':False}
    b = {'selected':s,'selection':binding,'constructor':constructor,'payload':payload,'outputs':outputs,'composition':comp,'manifest':manifest,
        'parent':parent,'changes':changes,'additions':additions,'removals':removals,'new_evidence':new_evidence,'parent_policy':old_policy,
        'support':S,'layout':layout,'runner_module_lists_changed':set(fresh['modules']) != set(maps['fresh']) or set(prepared['modules']) != set(maps['prepared']),
        'reviewed_inputs':reference(reviewed_path,reviewed_raw),'bootstrap':reference(owned/'bootstrap_native.py',boot)}
    return U,inputs,b,plan



def finish(U,inputs,b,plan_inputs):
    s=b['selected'];target,runtime,owned=(Path(s[k]) for k in ('target_root','runtime_root','owned_root'))
    emitted={}
    def put(path,raw):
        binding=emit(U,path,raw);emitted[path]=raw;return binding
    manifest_ref={'path':rel(runtime/'manifest.json'),'sha256':digest(b['outputs'][runtime/'manifest.json'])}
    S=b['support'];layout=b['layout']
    _,native,native_digest=S.validate_source_closure(inputs,workspace=T,native_root=layout['native_root'],manifest_binding=manifest_ref,profile_paths=list(layout['profile_paths'].values()),expected_native_members=len(b['composition']['outputs']),inventory=U.inventory)
    measurement,current,process=S.capture_final_identity(inputs,workspace=T,manifest_binding=manifest_ref,source_hashes=native,layout=layout)
    require(current['native_source_digest']==native_digest,'new identity/source digest differs')
    historical,limits,compression=S.historical_policy_inputs(inputs,workspace=T,seed_policy_binding=s['historical_seed'])
    old=b['parent_policy'];old_runtime=Path(b['parent']['runtime'])
    require(old['historical'] == historical, 'retained historical policy differs')
    evidence={translate(n,old_runtime,runtime):pin for n,pin in old['evidence'].items()}
    evidence.update({rel(runtime/'evidence'/n):pin for n,pin in b['new_evidence'].items()})
    rows=policy_rows(historical,current,old,s['policy_review'],old_runtime,runtime,b['new_evidence'])
    _,policy_raw=S.build_policy(inputs,workspace=T,evidence_root='.',historical=historical,current=current,reviewed_changes=rows,evidence=evidence)
    policy_ref=put(runtime/'runtime-policy.json',policy_raw)
    identity_ref=put(runtime/'execution-identity.json',U.canonical(measurement));put(owned/'identity-probe-process.json',U.canonical(process))
    component=S.authenticate_plan02(inputs,binding=s['plan02_binding'])
    fresh,prepared=S.final_profile_documents(inputs,component,workspace=T,layout=layout,manifest_binding=manifest_ref,policy_binding={'path':rel(runtime/'runtime-policy.json'),'sha256':policy_ref['sha256']},policy_raw=policy_raw,store_limits=limits,compression=compression)
    refuse(fresh);refuse(prepared)
    fresh_ref=put(runtime/'fresh-profile.json',U.canonical(fresh));prepared_ref=put(runtime/'prepared-profile.json',U.canonical(prepared))
    extras={'prepared_profile':prepared_ref,'runtime_policy':policy_ref,'execution_identity':current['execution_identity'],'native_source_digest':native_digest,'identity_measurement':identity_ref}
    inputs.recheck()
    record={'schema':'atlas.private.plan31.final-generation.r1' if s['line']=='final' else 'atlas.private.combined1820.integration.r1','status':'PREPARED_SOURCE_NOT_QUALIFIED','generation':s['generation'],'stage':s['stage'],'pending':[],'completed_query_store':'files','selection':b['selection'],'constructor_sha256':b['constructor']['sha256'],'producer_contract':s['producer_contract'],'parent_composition_sha256':s['base_composition_sha256'],'composition_sha256':digest(b['outputs'][target/'composition.json']),'manifest_sha256':manifest_ref['sha256'],'profile_sha256':fresh_ref['sha256'],'prepared_profile':prepared_ref,'historical_inputs':s['historical_inputs'],'reviewed_inputs':b['reviewed_inputs'],'bootstrap':b['bootstrap'],'source_inputs':dict(inputs.pins),'native_outputs':len(b['composition']['outputs']),'helper_outputs':len(b['composition']['helpers']),'changes':b['changes'],'additions':b['additions'],'removals':b['removals'],'source_only':True,'fold_not_performed':True,'observer_reissue_required':True,'execution_authority':False,'interval_authority':False,'scientific_acceptance':False,'numerical_changes':False,'default_changed':False,'holds_released':False,'runner_module_lists_changed':b['runner_module_lists_changed'],'cache_copy_revived':False}
    refuse(record);derivation=put(runtime/'derivation.json',U.canonical(record))
    U.composition(U.Inputs(),target,record['composition_sha256'],Path(b['reviewed_inputs']['path']),b['reviewed_inputs']['sha256'])
    receipt=dict(record,derivation_sha256=derivation['sha256'],input_finality=True,output_finality=True);receipt_raw=U.canonical(receipt)
    final_path=owned/'BUILD-RESULT.json';validation_path=owned/'BUILD-RESULT.unpublished.json';final_ref=reference(final_path,receipt_raw)
    result={'receipt':final_ref,'derivation':derivation,'fresh_profile':fresh_ref,**extras};validation_identity=None
    try:
        validation_ref=put(validation_path,receipt_raw);info=U.ordinary(validation_path).stat();validation_identity=(info.st_dev,info.st_ino)
        config=S.paired_config(component,construction_receipt=validation_ref,derivation=derivation,composition=reference(target/'composition.json',b['outputs'][target/'composition.json']),fresh_profile=fresh_ref,prepared_profile=prepared_ref,fresh_runner={'path':str(target/'helpers/run_fresh_interval.py'),'sha256':b['manifest']['files'][rel(target/'helpers/run_fresh_interval.py')]},prepared_runner={'path':str(target/'helpers/run_prepared_restart.py'),'sha256':b['manifest']['files'][rel(target/'helpers/run_prepared_restart.py')]},compatibility_policy=policy_ref,prepared_record=prepared)
        require(config['construction_receipt']==validation_ref,'paired consumer changed validated receipt binding')
        config=copy.deepcopy(config);config['construction_receipt']=final_ref;result['config']=put(owned/'prepared-construction.json',U.canonical(config))
        validate_completion(U,inputs,b,emitted,plan_inputs)
        require(not U.exists(final_path),'existing completion receipt refused')
        info=U.ordinary(validation_path).stat();require((info.st_dev,info.st_ino)==validation_identity and validation_path.read_bytes()==receipt_raw,'unpublished validated receipt changed')
        require(os.name=='nt','Windows no-replace rename required');os.rename(validation_path,final_path)
    except BaseException as error:
        try:
            failure={'schema':'plan31.failed-construction.r1','status':'FAILED_NOT_COMPLETED','input_finality':False,'output_finality':False,'error':type(error).__name__+': '+str(error),'unpublished_receipt_sha256':digest(receipt_raw),'unpublished_receipt_text':receipt_raw.decode('utf-8'),'published_completion':False}
            emit(U,owned/'CONSTRUCTION-FAILED.json',U.canonical(failure))
        except Exception as evidence_error:error.add_note('Failure-evidence write also failed: '+str(evidence_error))
        finally:
            if U.exists(validation_path):
                info=U.ordinary(validation_path).stat();require(validation_identity is not None and (info.st_dev,info.st_ino)==validation_identity,'foreign unpublished file preserved');validation_path.unlink()
        raise
    return result



def validate_completion(U,inputs,b,emitted,plan_inputs):
    s=b['selected'];target,runtime=(Path(s[k]) for k in ('target_root','runtime_root'))
    inputs.recheck()
    plan_inputs.recheck()
    U.composition(U.Inputs(),target,digest(b['outputs'][target/'composition.json']),Path(b['reviewed_inputs']['path']),b['reviewed_inputs']['sha256'])
    for path,raw in {**b['outputs'],**emitted}.items():
        require(U.ordinary(path).read_bytes()==raw,'final source/metadata output changed: '+str(path))
    require(not any((runtime/n).exists() for n in ('attempt-r1','store-r1','queries-r1','prepared-attempt-r1','prepared-queries-r1')),'unexpected workload outputs')



def main(frozen,constructor_path,core_binding,argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('check','plan','apply'))
    parser.add_argument('--selection');parser.add_argument('--selection-sha256')
    parser.add_argument('--plan-root',type=Path);parser.add_argument('--plan-sha256')
    parser.add_argument('--reviewed-constructor-sha256')
    args=parser.parse_args(argv)
    require((args.mode=='apply')==(args.plan_sha256 is not None) and (args.mode=='apply')==(args.reviewed_constructor_sha256 is not None),'apply requires exact plan and independently reviewed constructor pins')
    require(args.mode=='check' or args.plan_root is not None,'explicit plan root required')
    U,inputs,b,plan=derive(frozen,constructor_path,core_binding,args.selection,args.selection_sha256)
    raw=U.canonical(plan)
    if args.mode=='plan':
        root=args.plan_root;require(root.parent==HERE and not U.exists(root),'new plan must be directly under control root');U.ordinary(root.parent,directory=True);root.mkdir();emit(U,root/'PLAN.json',raw);inputs.recheck()
    elif args.mode=='apply':
        require(args.reviewed_constructor_sha256==b['constructor']['sha256'],'independently reviewed constructor differs')
        require(args.plan_root.parent==HERE,'plan outside control root')
        checked=U.Inputs();require(checked.raw(args.plan_root/'PLAN.json',args.plan_sha256)==raw,'current source plan differs')
        inputs.recheck();checked.recheck()
        checked.raw(T/HISTORICAL_INPUTS['path'],CATALOGUE_SHA256);checked.recheck()
        for path,data in b['outputs'].items():emit(U,path,data)
        # Validate the emitted current source/review pair before the identity probe.
        U.composition(inputs,Path(b['selected']['target_root']),digest(b['outputs'][Path(b['selected']['target_root'])/'composition.json']),Path(b['reviewed_inputs']['path']),b['reviewed_inputs']['sha256'])
        inputs.recheck();result=finish(U,inputs,b,checked)
        print(json.dumps({'status':'PREPARED_SOURCE_NOT_QUALIFIED','generation':b['selected']['generation'],'composition_sha256':digest(b['outputs'][Path(b['selected']['target_root'])/'composition.json']),'manifest_sha256':digest(b['outputs'][Path(b['selected']['runtime_root'])/'manifest.json']),'changed_source_members':len(b['changes']),'added_source_members':len(b['additions']),'preserved_source_members':len(b['payload'])-len(b['changes'])-len(b['additions']),'worker_dispatched':False,'result':result},sort_keys=True));return 0
    print(json.dumps({'status':'CHECK_ONLY_NOTHING_WRITTEN' if args.mode=='check' else 'UNEXECUTED_SOURCE_PLAN','plan_sha256':digest(raw),'source_outputs':len(plan['outputs']),'deferred_metadata':len(plan['deferred_metadata']),'source_bytes':sum(r['bytes'] for r in plan['outputs'].values()),'generation':b['selected']['generation'],'constructor':b['constructor']},sort_keys=True));return 0
