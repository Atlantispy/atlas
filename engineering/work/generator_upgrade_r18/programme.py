"""Translate the bound R18 owner contract into the finite geology programme.

Only the declared arithmetic syntax is parsed; no eval, imports, attribute
lookups or arbitrary functions are expressions. Decimal source lexemes enter
exact arithmetic directly, never through an AST float value. File/source binding
and exact JSON loading belong to the calling owner-input loader.
"""
import ast
from copy import deepcopy
import re

from work.generator_upgrade_r16 import columns
from . import rules


SCHEMA = 'diadem.physical.coverage-input-contract.r18'
DERIVED = ('g', 't', 'B', 'n', 'p', 'U')
ORDER = ('root', 'root_iron', 'root_forest_margin', 'root_metasedimentary',
         'root_gate_mineral_host', 'gate_protection', 'carbonate',
         'early_volcanic_core', 'early_volcanic_cover', 'basin',
         'southern_volcanic_core', 'southern_volcanic_cover', 'eastern_intrusion',
         'nv02_upper_core', 'nv02_upper_cover', 'pv02_upper_core', 'pv02_upper_cover',
         'silicification', 'structural_translation')
EMPLACEMENTS = {'root', 'carbonate', 'early_volcanic_cover', 'basin',
                'southern_volcanic_cover', 'nv02_upper_cover', 'pv02_upper_cover'}
ALTERNATIVES = {'BASIN_BEFORE_EARLY_VOLCANIC', 'TAPER_CARBONATE_UNDER_VOLCANIC_CORE',
                'HARMONIC_COMPOSITE_K'}
DECIMAL = re.compile(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact '+label+' fields required')


def _constant(value):
    return {'operation': 'constant', 'value': str(columns._q(value, 'owner formula literal'))}


def _arithmetic(source, names):
    if type(source) is int:
        return _constant(source)
    if type(source) is not str or not source.strip() or len(source) > 4096:
        raise ValueError('bounded owner expression text or exact integer required; no float lexeme recovery')
    source = source.strip()
    try:
        tree = ast.parse(source, mode='eval')
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('supported bounded owner arithmetic expression required') from exc
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise ValueError('owner arithmetic AST node budget exceeded')

    def convert(node):
        if isinstance(node, ast.Constant):
            lexeme = ast.get_source_segment(source, node)
            if type(node.value) not in (int, float) or lexeme is None or not DECIMAL.fullmatch(lexeme):
                raise ValueError('explicit decimal numeric lexeme required')
            return _constant(lexeme)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError('undeclared owner expression name: '+node.id)
            return {'operation': 'product', 'coefficient_m': '1', 'field': names[node.id]}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return {'operation': 'difference', 'terms': [_constant(0), convert(node.operand)]}
        if isinstance(node, ast.BinOp):
            operation = {ast.Add: 'sum', ast.Sub: 'difference', ast.Mult: 'product', ast.Div: 'quotient'}.get(type(node.op))
            if operation is None:
                raise ValueError('unsupported owner arithmetic operator')
            return {'operation': operation, 'terms': [convert(node.left), convert(node.right)]}
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ('min', 'max') and not node.keywords
                and 1 <= len(node.args) <= rules.MAX_TERMS):
            return {'operation': 'minimum' if node.func.id == 'min' else 'maximum',
                    'terms': [convert(argument) for argument in node.args]}
        raise ValueError('unsupported owner arithmetic syntax')

    expression = convert(tree.body)
    rules.referenced_fields(expression)  # same depth/node/literal budgets as execution
    return expression


def _units(values, material_ids):
    if type(values) is not list or not values or len(values) > 64:
        raise ValueError('bounded explicit eligible material list required')
    if any(type(unit) is not str or unit not in material_ids for unit in values) or len(set(values)) != len(values):
        raise ValueError('known unique eligible material identities required')
    return list(values)


def build(spec, alternative='DEFAULT'):
    """Return a geology.interpret-compatible programme from the declared spec.

HARMONIC_COMPOSITE_K deliberately returns default geometry; the caller selects
the engine's harmonic k_mixing. The two vertical alternatives alter only their
declared order/thickness. Unexpected stage order, anchors or operator fields fail
closed rather than being silently ignored as new geological authority.
"""
    if type(spec) is not dict or spec.get('schema') != SCHEMA or spec.get('source_status') != 'WORKING NON-CANON':
        raise ValueError('explicit WORKING NON-CANON R18 owner contract required')
    columns._text(spec['id'], 'owner contract identity')
    if type(spec['revision']) is not int or spec['revision'] <= 0:
        raise ValueError('positive owner revision required')
    if type(alternative) is not str or alternative not in ALTERNATIVES | {'DEFAULT'}:
        raise ValueError('declared R18 alternative required')
    materials = spec['materials']
    if type(materials) is not list or not 1 <= len(materials) <= 64:
        raise ValueError('bounded owner material table required')
    material_ids = {row['material_id'] for row in materials}
    if len(material_ids) != len(materials) or any(type(unit) is not str for unit in material_ids):
        raise ValueError('unique owner material identities required')
    raw_fields = spec['field_inputs']
    if type(raw_fields) is not list or len(raw_fields) != 30 or len(set(raw_fields)) != 30:
        raise ValueError('exact thirty owner field identities required')
    for field in raw_fields:
        columns._text(field, 'owner field identity')
    aliases = {'a_'+unit.replace('-', '_'): 'affinity_'+unit.lower().replace('-', '_') for unit in material_ids}
    extra_fields = {'crown_massif_support', 'basin_fill_thickness_prior_km', 'silicification_sv_intensity'}
    if set(raw_fields) != set(aliases.values()) | extra_fields:
        raise ValueError('owner affinity aliases differ from exact source inventory')
    names = {field: field for field in raw_fields}
    names.update(aliases)
    expressions = spec['expressions']
    _exact(expressions, {'semantics', 'affinity_alias_rule', 'division', *DERIVED}, 'owner expressions')
    derived = []
    for name in DERIVED:
        derived.append({'name': name, 'expression': _arithmetic(expressions[name], names)})
        names[name] = name
    alternatives = spec['alternatives']
    if type(alternatives) is not list or len(alternatives) != len(ALTERNATIVES):
        raise ValueError('exact owner alternative inventory required')
    options = {row['id']: row for row in alternatives}
    if set(options) != ALTERNATIVES or len(options) != len(alternatives):
        raise ValueError('known unique owner alternatives required')
    if alternative == 'TAPER_CARBONATE_UNDER_VOLCANIC_CORE':
        for name in ('vcore', 'kcore'):
            derived.append({'name': name, 'expression': _arithmetic(options[alternative][name], names)})
            names[name] = name
    if ''.join(spec['composite']['default_k'].split()) != 'sum(v_i*modified_K_i)':
        raise ValueError('owner default K mixture rule changed')
    if ''.join(options['HARMONIC_COMPOSITE_K']['k_rule'].split()) != '1/sum(v_i/modified_K_i)':
        raise ValueError('owner harmonic K mixture rule changed')
    construction = spec['construction']
    if (construction['infinite_basement'] is not False
            or construction['additional_shortening_transform'] is not None
            or construction['final_terrain_input'] is not None):
        raise ValueError('undeclared infinite stock, deformation or terrain input')
    if (construction['replacement_rules']['anchor_default'] != 'current_stage_top'
            or columns._q(construction['replacement_rules']['added_height'], 'replacement added height') != 0):
        raise ValueError('unsupported replacement anchor/height semantics')
    _exact(construction['eligibility_sets'], ('all_except_GT',), 'owner eligibility sets')
    all_except_gt = _units(construction['eligibility_sets']['all_except_GT'], material_ids)
    if set(all_except_gt) != material_ids-{'GT-01'}:
        raise ValueError('all_except_GT must exactly exclude the protected owner unit')
    ordered = construction['ordered_stages']
    if type(ordered) is not list or tuple(row['id'] for row in ordered) != ORDER:
        raise ValueError('unexpected owner construction order; anchors require reviewed mapping')
    base = _arithmetic(construction['initial_basal_elevation_m'], names)
    if rules.referenced_fields(base):
        raise ValueError('explicit constant undeformed root base required')
    root_top = columns._q(construction['undeformed_root_top_m'], 'undeformed root anchor')
    root_height = _arithmetic(ordered[0]['thickness_m'], names)
    if rules.referenced_fields(root_height) or rules.evaluate(base, {})+rules.evaluate(root_height, {}) != root_top:
        raise ValueError('root top anchor differs from constant base plus root thickness')
    stages, translation, modifier_stage = [], None, None
    for index, row in enumerate(ordered):
        identity, operation = row['id'], row['operation']
        expected_operation = ('emplace_composite' if identity in EMPLACEMENTS else
                              'mechanical_modifier' if identity == 'silicification' else
                              'translate_base_and_all_contacts' if identity == 'structural_translation' else
                              'replace_current_host')
        if operation != expected_operation:
            raise ValueError('owner stage operation changed; root anchors/order need reviewed mapping')
        if operation == 'emplace_composite':
            extra = ({'zero_support_fallback'} if identity == 'root' else
                     {'post_mix_constituent_replacement'} if identity == 'basin' else set())
            height_key = 'thickness_m' if identity in ('root', 'basin') else 'thickness_rule'
            _exact(row, {'id', 'operation', 'members', height_key} | extra, 'emplacement stage')
            weights, terms = {}, []
            if type(row['members']) is not list or not 1 <= len(row['members']) <= 64:
                raise ValueError('bounded owner compartment members required')
            for member in row['members']:
                _exact(member, {'unit_id', 'support'} | ({'nominal_thickness_m'} if height_key == 'thickness_rule' else set()), 'compartment member')
                unit = member['unit_id']
                if unit not in material_ids or unit in weights:
                    raise ValueError('known unique compartment member required')
                weights[unit] = _arithmetic(member['support'], names)
                if height_key == 'thickness_rule':
                    terms.append({'operation': 'product', 'terms': [
                        _arithmetic(member['nominal_thickness_m'], names), deepcopy(weights[unit])]})
            if height_key == 'thickness_rule':
                if row['thickness_rule'] != 'maximum_nominal_times_support':
                    raise ValueError('unsupported shared compartment thickness rule')
                height = {'operation': 'maximum', 'terms': terms}
            else:
                height = _arithmetic(row['thickness_m'], names)
            if identity == 'carbonate' and alternative == 'TAPER_CARBONATE_UNDER_VOLCANIC_CORE':
                height = {'operation': 'product', 'terms': [height, _arithmetic('1-kcore', names)]}
            rules.referenced_fields(height)
            stage = {'stage_id': identity, 'kind': 'emplace', 'weights': weights, 'thickness_m': height}
            if identity == 'root':
                if row['zero_support_fallback'] not in weights:
                    raise ValueError('root fallback must name a supplied root constituent')
                stage['fallback_unit_id'] = row['zero_support_fallback']
            stages.append(stage)
            if identity == 'basin':
                post = row['post_mix_constituent_replacement']
                _exact(post, ('host_unit', 'replacement_unit', 'fraction', 'scope', 'added_volume_m3'), 'basin constituent replacement')
                if (post['scope'] != 'this_basin_only' or post['host_unit'] != 'BF-WC'
                        or post['replacement_unit'] != 'MH-01' or post['host_unit'] not in weights
                        or columns._q(post['added_volume_m3'], 'basin replacement added volume') != 0):
                    raise ValueError('unsupported basin host replacement scope')
                stages.append({'stage_id': 'basin_MH', 'kind': 'replace', 'depth_m': deepcopy(height),
                    'supports': {post['replacement_unit']: _arithmetic(post['fraction'], names)},
                    'eligible_units': [post['host_unit']], 'protected_units': ['GT-01']})
        elif operation == 'replace_current_host':
            anchored = index < ORDER.index('carbonate')
            eligible_key = 'eligible_current_units' if anchored else 'eligible_current_unit_set'
            expected = {'id', 'operation', 'depth_m', 'replacements', eligible_key}
            if anchored:
                expected.add('anchor')
            if identity == 'gate_protection':
                expected.add('already_resident_GT')
            _exact(row, expected, 'replacement stage')
            if anchored and row['anchor'] != 'undeformed_root_top':
                raise ValueError('unreviewed replacement anchor')
            if not anchored and row['eligible_current_unit_set'] != 'all_except_GT':
                raise ValueError('unreviewed post-root eligibility set')
            eligible = _units(row['eligible_current_units'], material_ids) if anchored else list(all_except_gt)
            if type(row['replacements']) is not list or not 1 <= len(row['replacements']) <= 64:
                raise ValueError('bounded explicit replacement members required')
            replacements = {}
            for member in row['replacements']:
                _exact(member, ('unit_id', 'support'), 'replacement member')
                unit = member['unit_id']
                if unit not in material_ids or unit in replacements:
                    raise ValueError('known unique replacement member required')
                replacements[unit] = _arithmetic(member['support'], names)
            stage = {'stage_id': identity, 'kind': 'replace', 'depth_m': _arithmetic(row['depth_m'], names),
                     'supports': replacements, 'eligible_units': eligible}
            if index >= ORDER.index('gate_protection'):
                stage['protected_units'] = ['GT-01']
            if identity == 'gate_protection' and row['already_resident_GT'] != 'retain_without_export_or_reimport':
                raise ValueError('resident Gate protection semantics changed')
            stages.append(stage)
        elif operation == 'mechanical_modifier':
            _exact(row, ('id', 'operation', 'overlay_id'), 'mechanical modifier stage')
            if identity != 'silicification' or row['overlay_id'] != 'SV-01':
                raise ValueError('unsupported mechanical modifier stage')
            modifier_stage = row['overlay_id']
        elif operation == 'translate_base_and_all_contacts':
            _exact(row, ('id', 'operation', 'displacement_m', 'stock_change'), 'translation stage')
            if identity != ORDER[-1] or columns._q(row['stock_change'], 'translation stock change') != 0:
                raise ValueError('translation must be final and stock-conserving')
            translation = _arithmetic(row['displacement_m'], names)
        else:
            raise ValueError('unsupported owner stage operation')
    if modifier_stage is None or translation is None:
        raise ValueError('required modifier and final structural translation missing')
    if alternative == 'BASIN_BEFORE_EARLY_VOLCANIC':
        pair = [row for row in stages if row['stage_id'] in ('basin', 'basin_MH')]
        if [row['stage_id'] for row in pair] != ['basin', 'basin_MH']:
            raise ValueError('complete basin/MH stage pair required')
        stages = [row for row in stages if row['stage_id'] not in ('basin', 'basin_MH')]
        position = next(index for index, row in enumerate(stages) if row['stage_id'] == 'early_volcanic_core')
        stages[position:position] = pair
    if type(spec['overlays']) is not list or len(spec['overlays']) != 1:
        raise ValueError('one explicit SV mechanical overlay required')
    overlay = spec['overlays'][0]
    _exact(overlay, ('unit_id', 'role', 'field', 'eligible_units', 'k_rule', 'application',
                    'added_volume_m3', 'added_mass_kg', 'density_porosity_mass', 'silica_chemistry'), 'mechanical overlay')
    local_names = {'s': 's', 'K_i': 'K_i'}
    if (overlay['unit_id'] != modifier_stage or overlay['role'] != 'mechanical_alteration_only'
            or overlay['field'] != 'silicification_sv_intensity'
            or overlay['density_porosity_mass'] != 'unchanged' or overlay['silica_chemistry'] is not False
            or columns._q(overlay['added_volume_m3'], 'overlay added volume') != 0
            or columns._q(overlay['added_mass_kg'], 'overlay added mass') != 0
            or _arithmetic(overlay['k_rule'], local_names) != _arithmetic('(1-s)*K_i+s*0.000005', local_names)):
        raise ValueError('unsupported or changed SV mechanical alteration law')
    eligible_overlay = _units(overlay['eligible_units'], material_ids)
    if 'GT-01' in eligible_overlay:
        raise ValueError('protected Gate unit cannot enter mechanical overlay')
    evidence = spec['id']+'; revision '+str(spec['revision'])+'; WORKING NON-CANON owner-assigned reconstruction'
    columns._text(evidence, 'programme evidence')
    return {'field_ranges': {field: ['0', None if field == 'basin_fill_thickness_prior_km' else '1'] for field in raw_fields},
            'derived_fields': derived, 'stages': stages,
            'mechanical_overlay': {'unit_id': modifier_stage, 'field': overlay['field'],
                'eligible_units': eligible_overlay, 'target_k_per_year': str(columns._q('0.000005', 'declared SV target K'))},
            'base_m': base, 'translation_m': translation, 'evidence': evidence}
