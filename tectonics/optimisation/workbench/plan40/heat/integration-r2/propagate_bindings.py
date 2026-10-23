"""Construct explicit NEW public receiving bindings; never migrate old receipts.

Only the five named receiving modules are emitted. No Atlas module is imported.
The selected map may be a complete map or an entries-only overlay on the fixed
parent. Its entries require member, public_path and public_sha256. Output is an
entries-only overlay printed to stdout for the caller's final source selection.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

BASE = 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
BASE_SHA = 'ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'
OUTPUT = 'tectonics/optimisation/workbench/plan40/heat/integration-r2/source/helpers'
PREFIX = 'source/helpers/'
OLD = {
    'private_heat_native_issuer_r13.py': '10c40a136bb193b93938f02e31c374e84857204716e988f81a2706be76a73681',
    'private_heat_snapshot_store_r4.py': '8d2069737d55533f352a566b7b83fb46ea415a5fb58d57f10f66d14ec9aa1d49',
    'private_heat_issuer_resources_r4.py': 'f80d741c76586a41fa1a49415c19f72a0bb1eb3b0e1726e1d8cb52df2dcffdd6',
    'private_heat_native_projection_r5.py': '7fb40186f8b2e58426f269bef8fc034e42954d937b5a09331f903c50ce550616',
    'private_heat_forward_kernel_r13.py': 'de344f4796d712c1f543fe3380fdfaf23ec4a92ce41c926287a2212e2f00ad91',
    'private_heat_checkpoint_consumer_r10.py': 'fa28074f3ec54339c7c20a0cb3b5a4a0e15f13dacba6ef6d4a1f7277f9c33fbe',
    'private_heat_grouped_account_r1.py': '392eb3d3ed0d73dccbbdac1a2eddc5e1409ef1e8c5b84fd773bcc35e4d910d60',
    'private_heat_joined_consumer_r6.py': 'cdfdbd72864f1f13904dd068e48d7e143453968466d9373f4f654687e5dd5b89',
    'private_heat_restored_binding_ram_context_r1.py': '6cffa8ec6ba1f2fdf064b41da785c71636e1754c9054ed5de63549922e9864f8',
}
CHECKPOINT = ('private_heat_snapshot_store_r4.py', 'private_heat_issuer_resources_r4.py',
              'private_heat_native_projection_r5.py', 'private_heat_forward_kernel_r13.py',
              'private_heat_native_issuer_r13.py')
JOINED = ('private_heat_grouped_account_r1.py', 'private_heat_native_issuer_r13.py',
          'private_heat_checkpoint_consumer_r10.py', 'private_heat_forward_kernel_r13.py')
RESTORED = ('private_heat_checkpoint_consumer_r10.py', 'private_heat_native_issuer_r13.py',
            'private_heat_issuer_resources_r4.py', 'private_heat_snapshot_store_r4.py',
            'private_heat_forward_kernel_r13.py', 'private_heat_grouped_account_r1.py',
            'private_heat_joined_consumer_r6.py')
# Explicit topological order: issuer captures its dependency graph dynamically.
RULES = (
    ('private_heat_checkpoint_consumer_r10.py', CHECKPOINT,
     {'_ISSUER_SHA': 'private_heat_native_issuer_r13.py'}),
    ('private_heat_joined_consumer_r6.py', JOINED, {}),
    ('private_heat_restored_binding_r10.py', RESTORED, {}),
    ('private_heat_restored_binding_ram_context_r1.py', RESTORED, {}),
    ('private_heat_restored_binding_ram_recovery_r1.py', (),
     {'_BINDING_SHA': 'private_heat_restored_binding_ram_context_r1.py'}),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Relative in-repository path required: ' + relative)
    if not path.resolve().is_relative_to(root):
        raise ValueError('Path escapes repository: ' + relative)
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise ValueError('Linked source/output refused: ' + str(ancestor))
    return path


def entries(document):
    result = {}
    for entry in document['entries']:
        member = entry['member']
        if member in result:
            raise ValueError('Duplicate selected member: ' + member)
        result[member] = entry
    return result


def verified(root, entry):
    data = inside(root, entry['public_path']).read_bytes()
    if digest(data) != entry['public_sha256']:
        raise ValueError('Selected source changed: ' + entry['member'])
    return data


def rewrite(data, name, keys, scalar_rules, selected, *, generated=False):
    """Replace only AST-located literal pins with exact predecessor assertions."""
    tree = ast.parse(data, filename=name)
    declarations = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {'_PINS', *scalar_rules}:
                    if target.id in declarations:
                        raise ValueError('Duplicate pin declaration: ' + target.id)
                    declarations[target.id] = node.value
    required = set(scalar_rules) | ({'_PINS'} if keys else set())
    if set(declarations) != required:
        raise ValueError('Missing or unexpected pin declaration: ' + name)
    replacements = []
    seen = {}

    def pin(node, dependency):
        if not isinstance(node, ast.Constant):
            raise ValueError('Mutated predecessor pin: ' + name + ':' + dependency)
        value = node.value
        if generated:
            if (not isinstance(value, str) or len(value) != 64
                    or any(c not in '0123456789abcdef' for c in value)):
                raise ValueError('Invalid generated pin: ' + name + ':' + dependency)
            if dependency in seen and seen[dependency] != value:
                raise ValueError('Inconsistent generated pin: ' + dependency)
            seen[dependency] = value
        elif value != OLD[dependency]:
            raise ValueError('Mutated predecessor pin: ' + name + ':' + dependency)
        replacement = selected[PREFIX + dependency]['public_sha256']
        replacements.append((node, repr(replacement).encode('ascii')))

    for variable, dependency in scalar_rules.items():
        pin(declarations[variable], dependency)
    if keys:
        pins = declarations['_PINS']
        if not isinstance(pins, ast.Dict):
            raise ValueError('Literal pin dictionary required: ' + name)
        actual_keys = [ast.literal_eval(k) for k in pins.keys]
        if actual_keys != list(keys):
            raise ValueError('Changed predecessor pin set/order: ' + name)
        for key, value in zip(actual_keys, pins.values, strict=True):
            if name == RULES[0][0] and key == 'private_heat_native_issuer_r13.py':
                if not isinstance(value, ast.Name) or value.id != '_ISSUER_SHA':
                    raise ValueError('Issuer alias changed')
            else:
                pin(value, key)
    # AST columns are UTF-8 byte offsets. Preserve all other predecessor bytes.
    lines = data.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans = [(offsets[n.lineno-1] + n.col_offset,
              offsets[n.end_lineno-1] + n.end_col_offset, value)
             for n, value in replacements]
    for start, end, value in sorted(spans, reverse=True):
        data = data[:start] + value + data[end:]
    ast.parse(data, filename=name)
    return data


def validate_generated(original, current, name, keys, scalar_rules):
    """Only pin literal bytes may differ from the authenticated predecessor."""
    historical = {PREFIX + key: {'public_sha256': value} for key, value in OLD.items()}
    restored = rewrite(current, name, keys, scalar_rules, historical, generated=True)
    if restored != original:
        raise ValueError('Generated receiver changed outside pin literals: ' + name)


def validate_selection(root, selected_map):
    """Read-only check of all five actual final receiving chains, no imports."""
    root = Path(root).resolve(strict=True)
    parent_data = inside(root, BASE).read_bytes()
    if digest(parent_data) != BASE_SHA:
        raise ValueError('Parent selection identity changed')
    parent = entries(json.loads(parent_data))
    selected = entries(json.loads(inside(root, selected_map).read_bytes()))
    checked = []
    for name, keys, scalar_rules in RULES:
        member = PREFIX + name
        original = verified(root, parent[member])
        current = verified(root, selected[member])
        validate_generated(original, current, name, keys, scalar_rules)
        for dependency in (*keys, *scalar_rules.values()):
            verified(root, selected[PREFIX + dependency])
        expected = rewrite(original, name, keys, scalar_rules, selected)
        if current != expected:
            raise ValueError('Final receiving pin chain differs: ' + name)
        checked.append(member)
    return checked


def propagate(root, selected_map, *, update_generated=False):
    root = Path(root).resolve(strict=True)
    parent_data = inside(root, BASE).read_bytes()
    if digest(parent_data) != BASE_SHA:
        raise ValueError('Parent selection identity changed')
    parent = entries(json.loads(parent_data))
    selected = dict(parent)
    selected.update(entries(json.loads(inside(root, selected_map).read_bytes())))
    # Validate the entire incoming selection before constructing any successor.
    for entry in selected.values():
        verified(root, entry)
    outputs, overlay = [], []
    for name, keys, scalar_rules in RULES:
        member = PREFIX + name
        old = verified(root, parent[member])
        if selected[member] != parent[member]:
            if (not update_generated or
                    selected[member]['public_path'] != OUTPUT + '/' + name):
                raise ValueError('Receiving module already overlaid: ' + member)
            validate_generated(old, verified(root, selected[member]), name, keys, scalar_rules)
        new = rewrite(old, name, keys, scalar_rules, selected)
        if new == old:
            continue
        public_path = OUTPUT + '/' + name
        entry = dict(parent[member], public_path=public_path, public_sha256=digest(new))
        entry.update(binding_status='NEW_PUBLIC_RECEIVING_BINDING_NOT_HISTORICAL_RESTART',
                     predecessor_public_path=parent[member]['public_path'],
                     predecessor_public_sha256=parent[member]['public_sha256'],
                     transformations=list(parent[member].get('transformations', [])) +
                     ['Explicit new public receiving pins; original checks unchanged'])
        selected[member] = entry
        target = inside(root, public_path)
        current = target.read_bytes() if target.exists() else None
        if current is not None and current != new:
            if not update_generated:
                raise ValueError('Refusing to overwrite different successor: ' + public_path)
            validate_generated(old, current, name, keys, scalar_rules)
        outputs.append((target, new, current))
        overlay.append(entry)
    # All inputs, declarations and destinations validated before the first write.
    for target, data, previous in outputs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if previous is None:
            with target.open('xb') as stream:
                stream.write(data)
        elif previous != data:
            if target.read_bytes() != previous:
                raise ValueError('Generated receiver changed during construction: ' + str(target))
            target.write_bytes(data)
    return {'identity_kind': 'NEW_PUBLIC_RECEIVING_BINDINGS_NOT_RUNTIME_ACCEPTANCE',
            'predecessor_source_map_sha256': BASE_SHA, 'entries': overlay}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--selected-map', required=True, help='Repository-relative map/overlay')
    parser.add_argument('--update-generated', action='store_true',
                        help='Update only five known pin-only generated successors')
    args = parser.parse_args()
    print(json.dumps(propagate(args.root, args.selected_map,
                               update_generated=args.update_generated), indent=2) + '\n', end='')


if __name__ == '__main__':
    main()
