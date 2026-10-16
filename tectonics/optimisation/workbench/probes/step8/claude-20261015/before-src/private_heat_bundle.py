"""Explicit new private heat source closure, never historical source repinning.

The caller supplies already-authenticated predecessor bytes. We copy the finite
dependency closure into a NEW directory, transform named consumers and
reconcile their compile-time dependency pins. The old sources, checkpoints and
recorded producer identities are untouched. Changed-runtime admission is still
mandatory and is not supplied by this composer.

construct() is the five-consumer heat closure used by the indexed heat
fixtures. construct_successor() is the complete composed-successor helper set:
it adds the continuation, coverage, cold-binding and driver roots, the routing
continuation and cold-binding indexed transforms, the RAM helpers (written to
<RC>/ram) and the authenticated companion helpers the closure imports.
"""
import ast
from hashlib import sha256
from pathlib import Path
import re
import sys
import io
import tokenize

import private_heat_indexed_runtime as P
import heat_payload_indexed_patch as PAYLOAD
import partition_routing_transform as ROUTING
import ram_context_indexed_patch as RAM_CONTEXT


JOINED_SHA = 'eed99e320c981867eec67fabba2b6061f1996b91fbfe10a6f765ab88d6765324'
HEAT_ROOTS = ('private_heat_native_issuer_r12.py', 'private_heat_native_projection_r4.py',
              'private_heat_checkpoint_consumer_r9.py', 'private_heat_joined_consumer_r6.py',
              'private_heat_original_joined_r6.py')
# The driver imports the continuation helper and probe r9 (which imports
# coverage r3 at module level); every cold reopen imports the RAM recovery.
ROOTS = HEAT_ROOTS+('private_heat_original_continuation_r1.py', 'private_heat_original_coverage_r3.py',
                    'private_heat_restored_binding_ram_recovery_r1.py', 'probe_heat_original_connected_r9.py')
# In the closure for their dependencies; their own bytes are never rewritten.
VERBATIM_ROOTS = ('probe_heat_original_connected_r9.py',)
# H files outside the I manifest, read by coverage r3/r2 from their own directory.
EXTERNAL_PINS = {
    'private_heat_original_coverage_r1.py': '90113110a3c7a37c70ea16df6de6166d61ed728d2bc974f6e2e3dbd49409c688',
    'private_heat_original_coverage_r2.py': '078a4a730d0cbac4c60b9e9e4f992859883af9ce282a089a9471125e214690c3',
}
# I/ram cold heat binding; reconciled with the closure and written to <RC>/ram.
RAM_PINS = {
    'private_heat_restored_binding_ram_context_r1.py': 'cd729dc216ede88ef22f46e38327ca8d2547f96990ea6de60d11cf7db926f428',
    'private_heat_restored_binding_ram_recovery_r1.py': '84a7a048e73073f6cb41f5b5d50b5dcb0aacb9c5403dda99b8c5aa3b1ef7f592',
}
RAM_RECOVERY = 'private_heat_restored_binding_ram_recovery_r1.py'
OBSERVER = 'private_heat_geometry_observer_r1.py'
OBSERVER_SHA = '3a6f2eadea7cf8168ab0b4517261f2d87d132f66486eeeebc930705f2a59f9d3'
# Copied verbatim AFTER pin reconciliation, never into its inputs, so their
# predecessor constants are not rewritten. private_heat_mesh_patch is a copy
# only: its issuer_source is never applied (the indexed runtime transform is).
HELPER_COPIES = ('heat_payload_indexed_patch.py', 'private_heat_indexed_runtime.py',
                 'private_heat_mesh_patch.py', OBSERVER)
# Authenticated companion helpers imported by the composed closure: the routing
# and funding continuation, the parent geometry transfer, the indexed issuer.
COMPANION_HELPERS = ('partition_routing_transform.py', 'partition_routing_patch.py', 'funding_transfer.py',
                     'geometry_transfer.py', 'native_transfer.py', 'spatial_transfer.py',
                     'partition_native_patch.py', 'partition_tables.py', 'mesh_tables.py',
                     'spatial_indexed_patch.py', 'pressure_indexed_patch.py', 'continuation_transfer.py',
                     'exterior_mesh_patch.py')
# Step 7 is an explicit successor route. Legacy construction stays available;
# WP9 selects this route when it binds the complete current source inventory.
COMPACT_RENAMES = {
    'private_heat_native_issuer_r12.py': 'private_heat_native_issuer_r13.py',
    'private_heat_checkpoint_consumer_r9.py': 'private_heat_checkpoint_consumer_r10.py',
    'private_heat_restored_binding_r9.py': 'private_heat_restored_binding_r10.py',
    'private_heat_snapshot_store_r3.py': 'private_heat_snapshot_store_r4.py',
}
COMPACT_RUNTIME_HELPERS = (
    'heat_ledger_tables.py', 'heat_ledger_issuer_patch.py', 'heat_cold_patch.py',
    'exchange_record_patch.py', 'spatial_validation_patch.py', 'spatial_records_patch.py',
    'live_spatial_patch.py', 'live_finite_patch.py', 'live_mesh_patch.py',
    'live_partition_patch.py', 'differential_mesh_patch.py', 'live_transport_result.py',
    'live_collar_patch.py',
    'compact_contracts.py', 'content_cache.py', 'record_tables.py', 'record_views.py',
    'segment_store.py', 'interval_store_set.py', 'interval_catalog.py',
    'compact_store.py', 'partition_store.py', 'partition_v2.py', 'partition_workflow_patch.py',
    'support_source.py', 'spatial_workflow_patch.py', 'workflow_transfer.py',
    'materialise_endpoint.py', 'historical_admission.py', 'runtime_compatibility.py',
    'historical_compact_heat.py', 'compact_restart_store.py',
)
COMPACT_BUILD_HELPERS = ('private_heat_snapshot_store_r4.py',
    'private_heat_checkpoint_consumer_r10.py', 'private_heat_restored_binding_r10.py')
COMPACT_HELPERS = COMPACT_RUNTIME_HELPERS + COMPACT_BUILD_HELPERS
# In the closure only through support r3's historical lifecycle CLI. The
# composer writes the reviewed successor guard (resource_guard_patch) under this
# name, so the historical bytes are not emitted and no output may pin them.
GUARD = 'private_heat_continuation_guard_r3.py'
HISTORICAL_GUARD_SHA = '2d23f4bbc3b31b5aad3d68ef6e9b1a9800042fc75b12475b51dff468492ad796'
SUCCESSOR_GUARD_SHA = '9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772'
# Every import of the composed helper bytes resolves to the standard library,
# these helpers, or exactly one of these reviewed external groups.
EXTERNAL_IMPORTS = {
    'runtime': ('atlas_tectonics', 'blosc2', 'gmpy2', 'numpy', 'psutil', 'scipy', 'threadpoolctl'),
    'historical_tests': ('i04_differential_fixture', 'i04_differential_modes', 'test_i04_differential_force',
                         'test_i04_spatial_workflow'),
    # Composer helper inventory: the successor guard and its job helper, and the
    # workflow transfer imported lazily by the continuation/funding transfers.
    'composer_supplied': ('private_heat_continuation_guard_r3', 'windows_workload_job', 'workflow_transfer'),
    # Reached only from support r3's execute_cli and probe r9's run(), the
    # historical lifecycle entry points, never from the restart route.
    'off_route': ('probe_heat_original_continue_reopen_r3', 'probe_heat_original_reopen_r4'),
}
CONTINUATION = 'private_heat_original_continuation_r1.py'
CONTINUATION_SHA = '3d859c53c9b731fccbba09609b9c86c3104f445cc9c5f46367f63ef6ebc144df'
REFERENCE_PINS = {
    'source/tectonics/src/atlas_tectonics/integration_mimetic_newton.py':
        'ef0f3b48ec1c992f2887f53b21c054d69439e58be2d3d445069162f29a51a0f0',
    'source/tectonics/src/atlas_tectonics/integration_mimetic_heat.py':
        '4eb824b472c977d3c6b57693f966566f243f1a1d253472886a82b5b377bc1c94',
    'source/tectonics/src/atlas_tectonics/integration_spatial_transport.py':
        '70cdfc9a5b0a4e6b518f6354550fc2a23b333a0474c07dfac55f670cdffde230',
    'source/tectonics/src/atlas_tectonics/integration_exact_gmp.py':
        '1cecc336d4584f44ba3ae97636e22e4048638d627d656ab2cc766dc6b46d5f8f',
    'source/tectonics/tests/i04_differential_joined_control.py':
        '528832f2b10a74051a3123d00850c5f462cf8ebd76520e38ac8ba5aff763a078',
    'source/tectonics/tests/test_i04_spatial_workflow.py':
        'c7063bb01cb583e94e5f5b5aa0fd5e78cece7903a95e51a2fe2411293241d00d',
    'source/tectonics/tests/i04_differential_continuation_control.py':
        '9bae6ed33ed9e223ef7a8e0cdf447fc621ad78583d3a97760ff400e25ed80e60',
    # Read at import by original_spatial_r1 (reached from probe r9's run());
    # outside the I manifest, pinned by that helper's own _SOURCE_SHA.
    'source/tectonics/tests/i04_differential_spatial_fixture.py':
        'f13d48b68e0b6f0b2de92e2bb903c71fe6beb92e56f2795be131ea2488b760ee',
}
GMP_RESOURCES = 'private_heat_gmp_resources_r1.py'
GMP_INSERT = "sys.path.insert(0, str(HERE/'source'/'tectonics'/'src'))\n"
GMP_NEUTRAL = '# Runtime package selection belongs to the explicit source fence.\n'
JOINED_DERIVED = '_DERIVED_TEXT = _replace_exact(_ORIGINAL_TEXT, _EDITS)\n'
JOINED_TRANSFER = ('from continuation_transfer import joined_control_source as _GEOMETRY_TRANSFER_SOURCE\n'
                   '_DERIVED_TEXT = _replace_exact(_GEOMETRY_TRANSFER_SOURCE(_ORIGINAL_TEXT), _EDITS)\n')
# The only import-path mutations left in composed helper bytes, all inside
# functions: the worker selects its CALLER's candidate/clone; native successor
# r6 names HERE-relative trees, which under the composed helpers directory are
# never H paths (reached only from probe r9 run/main); support r3 installs a
# temporary pin-verifying finder that adds no path. Anything else refuses.
REVIEWED_PATH_MUTATIONS = {
    ('private_heat_functionals_parallel_r1.py', '_select'):
        ('sys.path.remove(path)', 'sys.path.insert(0, path)'),
    ('private_heat_native_successor_r6.py', 'modules'):
        ('sys.path.insert(0, str(CLONE))', 'sys.path.insert(1, str(TESTS))'),
    ('private_heat_continuation_support_r3.py', 'ContinuationSources.imports'):
        ('sys.meta_path.insert(0, finder)', 'sys.meta_path.remove(finder)'),
}
_PATH_LISTS = frozenset(('path', 'meta_path', 'path_hooks', 'path_importer_cache'))
_MUTATORS = frozenset(('insert', 'append', 'extend', 'remove', 'pop', 'popitem', 'clear', 'sort', 'reverse',
                       'update', 'setdefault', '__setitem__', '__delitem__', '__iadd__', '__init__'))


def dependencies(raw, available):
    tree = ast.parse(raw)
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or '']
        elif isinstance(node, ast.Constant) and type(node.value) is str:
            names = [node.value.removesuffix('.py')]
        else:
            continue
        for name in names:
            if name.startswith('private_heat_') and name+'.py' in available:
                result.add(name+'.py')
    return result


def closure(inputs, roots=ROOTS):
    pending, selected = list(roots), {}
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in inputs or type(inputs[name]) is not bytes:
            raise ValueError('missing authenticated private heat dependency: '+name)
        raw = inputs[name]
        selected[name] = raw
        pending.extend(dependencies(raw, inputs)-selected.keys())
    return selected


def reconcile_dependency_pins(original, transformed):
    """Finite source-dependency DAG only; a cyclic pin closure refuses.

    Every replacement is an exact SHA string token in an explicit predecessor
    module. Newly introduced helper modules are NOT included: their historical
    transformer input hashes must never be rewritten into output hashes.
    """
    if set(original) != set(transformed):
        raise ValueError('explicit original/transformed source sets differ')
    old = {name: sha256(raw).hexdigest() for name, raw in original.items()}
    if len(set(old.values())) != len(old):
        raise ValueError('ambiguous original private source identity')
    pattern = re.compile(r"(['\"])([0-9a-f]{64})\1")
    owners = {value: name for name, value in old.items()}
    references = {}
    for name, raw in transformed.items():
        references[name] = {owners[m[2]] for m in pattern.finditer(raw.decode())
                            if m[2] in owners}
        if name in references[name]:
            raise ValueError('self-referential source pin cannot be reconciled: '+name)
    outputs, edits, pending = {}, [], set(original)
    while pending:
        ready = sorted(name for name in pending if references[name] <= outputs.keys())
        if not ready:
            raise ValueError('cyclic private source pins require explicit design review')
        for name in ready:
            def replacement(match):
                before = match[2]
                dependency = owners.get(before)
                if dependency is None:
                    return match[0]
                after = sha256(outputs[dependency]).hexdigest()
                if before != after:
                    edits.append(dict(consumer=name, dependency=dependency,
                                      predecessor=before, successor=after))
                return match[1]+after+match[1]
            outputs[name] = pattern.sub(replacement, transformed[name].decode()).encode()
            compile(outputs[name], name, 'exec')
            pending.remove(name)
    return outputs, edits


def _once(source, old, new):
    # Line-start anchored, counting overlapping occurrences.
    starts, at = 0, source.find(old)
    while at >= 0:
        starts += at == 0 or source[at-1] == '\n'
        at = source.find(old, at+1)
    if source.count(old) != 1 or starts != 1:
        raise ValueError('private heat composition seam missing or ambiguous: '+old.strip()[:80])
    return source.replace(old, new, 1)


def _reference_paths(transformed, *, reference_root, reference_pins):
    """Keep original accounting-reference bytes separate from execution code.

    These are historical formula-policy source references, not imports. Their
    exact original pins stay unchanged. Moving helpers must not accidentally
    select the old package as executable code through its old sys.path insert:
    that insert is removed exactly once BEFORE any relocation, so it can never
    become an absolute historical path.
    """
    root = Path(reference_root)
    if not root.is_absolute():
        raise ValueError('explicit absolute historical reference directory required')
    if reference_pins != REFERENCE_PINS:
        raise ValueError('reference pins differ from original declared accounting policy')
    refs = tuple(REFERENCE_PINS)
    checked = {}
    for name in refs:
        raw = (root/name).read_bytes()
        if sha256(raw).hexdigest() != reference_pins.get(name):
            raise ValueError('historical accounting reference changed: '+name)
        checked[str(root/name)] = reference_pins[name]
    for name, raw in tuple(transformed.items()):
        source = raw.decode()
        if name == GMP_RESOURCES:
            source = _once(source, GMP_INSERT, GMP_NEUTRAL)
        source = source.replace("HERE/'source'/'tectonics'/'src'/'atlas_tectonics'",
            'Path('+repr(str(root/'source/tectonics/src/atlas_tectonics'))+')')
        for reference in refs:
            source = source.replace(repr(reference), repr(str(root/reference)))
            path_expression = '_HERE/'+'/'.join(repr(part) for part in reference.split('/'))
            source = source.replace(path_expression, '_Path('+repr(str(root/reference))+')')
        transformed[name] = source.encode()
    return checked


def path_mutations(name, raw):
    """Every sys.path/meta_path/path_hooks mutation as (scope, statement), aliases resolved."""
    tree = ast.parse(raw)
    modules, lists = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == 'sys')
        elif isinstance(node, ast.ImportFrom) and node.module == 'sys':
            lists.update(a.asname or a.name for a in node.names if a.name in _PATH_LISTS)
        elif isinstance(node, ast.ImportFrom) and node.module == 'site':
            lists.update(a.asname or a.name for a in node.names if a.name == 'addsitedir')

    def path_list(node):
        while isinstance(node, ast.Subscript):
            node = node.value
        return (isinstance(node, ast.Attribute) and node.attr in _PATH_LISTS and
                isinstance(node.value, ast.Name) and node.value.id in modules or
                isinstance(node, ast.Name) and node.id in lists)

    def mutates(node):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute) and (path_list(function.value) and function.attr in _MUTATORS
                                                        or function.attr == 'addsitedir'):
                return True
            return (isinstance(function, ast.Name) and function.id in ('setattr', 'delattr') and node.args
                    and isinstance(node.args[0], ast.Name) and node.args[0].id in modules or
                    isinstance(function, ast.Name) and function.id in lists)
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = (node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target])
            return any(path_list(target) for target in targets)
        return False

    found = []
    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = scope+(child.name,) if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                             ast.ClassDef)) else scope
            if mutates(child):
                found.append(('.'.join(scope) or '<module>', ast.unparse(child)))
            visit(child, inner)
    visit(tree, ())
    return found


def _reviewed_path_mutations(files):
    """Refuse any import-path mutation that is not exactly a reviewed function-level one."""
    reviewed = []
    for name, raw in sorted(files.items()):
        found = {}
        for scope, statement in path_mutations(name, raw):
            found.setdefault(scope, []).append(statement)
        for scope, statements in found.items():
            expected = REVIEWED_PATH_MUTATIONS.get((name, scope))
            if expected is None or tuple(sorted(statements)) != tuple(sorted(expected)):
                raise ValueError('unreviewed import-path mutation in composed helper: '+name+' '+scope)
            reviewed.append(dict(module=name, scope=scope, statements=list(expected)))
    return reviewed


def external_imports(files):
    """Group every import outside the stdlib and these files; anything unreviewed refuses."""
    stems = {Path(name).stem for name in files}
    groups = {name: group for group, names in EXTERNAL_IMPORTS.items() for name in names}
    found = {}
    for name, raw in sorted(files.items()):
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, ast.Import):
                modules = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                modules = [node.module.split('.')[0]]
            else:
                continue
            for module in modules:
                if module in sys.stdlib_module_names or module in stems:
                    continue
                if module not in groups:
                    raise ValueError('unbound import in composed heat helpers: '+name+' imports '+module)
                found.setdefault(groups[module], set()).add(module)
    return {group: sorted(names) for group, names in sorted(found.items())}


def construct(inputs, *, reference_root, reference_pins):
    """The five-consumer heat closure only (indexed heat fixtures); not the successor."""
    original = closure(inputs, HEAT_ROOTS)
    transformed = dict(original)
    for name, transform in (
            ('private_heat_native_issuer_r12.py', P.issuer_source),
            ('private_heat_native_projection_r4.py', P.projection_source)):
        transformed[name] = transform(original[name].decode()).encode()
    name = 'private_heat_joined_consumer_r6.py'
    transformed[name] = P.joined_source(original[name].decode(), expected_sha256=JOINED_SHA).encode()
    name = 'private_heat_original_joined_r6.py'
    transformed[name] = joined_driver_source(original[name].decode()).encode()
    transformed = PAYLOAD.additional_transform(transformed)
    references = _reference_paths(transformed, reference_root=reference_root,
                                  reference_pins=reference_pins)
    outputs, pins = reconcile_dependency_pins(original, transformed)
    _reviewed_path_mutations(outputs)
    return outputs, dict(schema='atlas.private.indexed-heat-source-composition.v1',
        original={name: sha256(raw).hexdigest() for name, raw in original.items()},
        successor={name: sha256(raw).hexdigest() for name, raw in outputs.items()},
        dependency_pin_changes=pins, preserved_accounting_references=references, checkpoint_admission=False,
        numerical_algorithm_changed=False)


def _authenticated(values, pins, label):
    if type(values) is not dict or set(values) != set(pins) or any(
            type(values[name]) is not bytes or sha256(values[name]).hexdigest() != pin
            for name, pin in pins.items()):
        raise ValueError('exact authenticated '+label+' inputs required')
    return dict(values)


def _rename_compact_dependencies(source):
    """Rename Python module references and exact filenames, never logical labels.

    In particular an r12 schema/method/producer label inside a larger string is
    historical logical data. It must not be changed by a packaging revision.
    """
    names = {Path(old).stem: Path(new).stem for old, new in COMPACT_RENAMES.items()}
    strings = {**COMPACT_RENAMES, **names}
    lines = source.splitlines(keepends=True)
    offsets, at = [], 0
    for line in lines:
        offsets.append(at)
        at += len(line)
    replacements = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        replacement = None
        if token.type == tokenize.NAME:
            replacement = names.get(token.string)
        elif token.type == tokenize.STRING:
            try:
                value = ast.literal_eval(token.string)
            except (ValueError, SyntaxError):
                continue
            if type(value) is str and value in strings:
                replacement = repr(strings[value])
        if replacement is not None:
            start = offsets[token.start[0]-1]+token.start[1]
            end = offsets[token.end[0]-1]+token.end[1]
            replacements.append((start, end, replacement))
    for start, end, replacement in reversed(replacements):
        source = source[:start]+replacement+source[end:]
    compile(source, '<compact-heat-renamed>', 'exec')
    return source


def _compact_sources(original, transformed, compact_helpers, stages, *, live_memory=True):
    # These are source transformers. Their runtime dependencies must already
    # resolve through the caller's explicit source selection, never sys.path edits.
    import exchange_record_patch as EXCHANGE
    import spatial_validation_patch as VALIDATION
    import heat_ledger_issuer_patch as LEDGER
    import live_spatial_patch as LIVE
    import private_heat_checkpoint_consumer_r10 as CONSUMER
    import private_heat_restored_binding_r10 as RESTORED

    for module in (EXCHANGE, VALIDATION, LEDGER, LIVE, CONSUMER, RESTORED):
        name = Path(module.__file__).name
        if compact_helpers[name] != Path(module.__file__).read_bytes():
            raise ValueError('compact transformer differs from authenticated bytes: '+name)

    def apply(name, label, transform, source=None):
        transformed[name] = transform((transformed[name] if source is None else source).decode()).encode()
        stages[name+'@'+label] = sha256(transformed[name]).hexdigest()

    apply('private_heat_native_issuer_r12.py', 'heat_ledger_issuer_patch.issuer_source', LEDGER.issuer_source)
    apply('private_heat_native_projection_r4.py', 'heat_ledger_issuer_patch.projection_source', LEDGER.projection_source)
    joined = 'private_heat_joined_consumer_r6.py'
    apply(joined, 'exchange_record_patch.producer_source', EXCHANGE.producer_source)
    apply(joined, 'heat_ledger_issuer_patch.joined_source', LEDGER.joined_source)
    apply(joined, 'spatial_validation_patch.joined_source', VALIDATION.joined_source)
    if live_memory:
        apply(joined, 'live_spatial_patch.joined_source', LIVE.joined_source)
        apply('private_heat_native_issuer_r12.py', 'live_spatial_patch.issuer_source', LIVE.issuer_source)
        apply('private_heat_native_projection_r4.py', 'live_spatial_patch.projection_source', LIVE.projection_source)
    for name, transform in (('private_heat_checkpoint_consumer_r9.py', CONSUMER.transform),
                             ('private_heat_restored_binding_r9.py', RESTORED.transform)):
        apply(name, COMPACT_RENAMES[name].removesuffix('.py')+'.transform', transform, original[name])
    transformed['private_heat_snapshot_store_r3.py'] = compact_helpers['private_heat_snapshot_store_r4.py']
    # The parallel selector captures loaded compact dependencies just as it
    # captures the existing indexed helpers; no wildcard path permission.
    workers = tuple(sorted(set(PAYLOAD.WORKER_RUNTIME_HELPERS) |
        {Path(name).stem for name in COMPACT_RUNTIME_HELPERS}))
    name = 'private_heat_functionals_parallel_r1.py'
    source = transformed[name].decode()
    source = _once(source, '_INDEXED_RUNTIME_HELPERS = frozenset('+repr(PAYLOAD.WORKER_RUNTIME_HELPERS)+')\n',
                   '_INDEXED_RUNTIME_HELPERS = frozenset('+repr(workers)+')\n')
    transformed[name] = source.encode()
    for name, raw in tuple(transformed.items()):
        transformed[name] = _rename_compact_dependencies(raw.decode()).encode()
    return workers


def construct_compact_successor(inputs, *, reference_root, reference_pins, external, ram,
                                helpers, compact_helpers, live_memory=True):
    """Step 7 r13/r10/r4 source closure, with Step 6 producer registration.

    All inputs are explicit authenticated bytes. This is component composition,
    not WP9's frozen runtime, historical migration or changed-runtime admission.
    """
    if (type(live_memory) is not bool or type(compact_helpers) is not dict or set(compact_helpers) != set(COMPACT_HELPERS)
            or any(type(raw) is not bytes for raw in compact_helpers.values())):
        raise ValueError('exact authenticated compact heat helper inventory required')
    return construct_successor(inputs, reference_root=reference_root, reference_pins=reference_pins,
        external=external, ram=ram, helpers=helpers, _compact_helpers=compact_helpers,
        _live_memory=live_memory)


def construct_successor(inputs, *, reference_root, reference_pins, external, ram, helpers,
                        _compact_helpers=None, _live_memory=True):
    """Complete composed-successor heat helpers: (helpers, ram, report).

    inputs: caller-authenticated (I-pinned) H private_heat_* bytes and probe r9.
    external/ram: exactly EXTERNAL_PINS / RAM_PINS, checked here as well.
    helpers: exactly HELPER_COPIES + COMPANION_HELPERS, caller-authenticated;
    the transformers this module ran must be the very bytes shipped.
    Every transform runs on ORIGINAL bytes, then the payload transforms, the
    reference relocation and finally source-pin reconciliation. The historical
    guard is not emitted (the composer writes the reviewed successor guard under
    its name); every remaining import must fall in EXTERNAL_IMPORTS.
    """
    external = _authenticated(external, EXTERNAL_PINS, 'external coverage')
    ram = _authenticated(ram, RAM_PINS, 'I/ram cold binding')
    if (type(inputs) is not dict or type(helpers) is not dict or
            set(helpers) != set(HELPER_COPIES+COMPANION_HELPERS) or
            any(type(raw) is not bytes for raw in (*inputs.values(), *helpers.values()))):
        raise ValueError('exact authenticated predecessor and helper bytes required')
    if (sha256(helpers[OBSERVER]).hexdigest() != OBSERVER_SHA or
            helpers['heat_payload_indexed_patch.py'] != PAYLOAD.helper_source() or
            any(helpers[Path(module.__file__).name] != Path(module.__file__).read_bytes()
                for module in (P, ROUTING))):
        raise ValueError('shipped helpers differ from the observer pin or the transformers applied')
    available = dict(inputs)
    for name, raw in (*external.items(), *ram.items()):
        if name in available:
            raise ValueError('duplicate authenticated private heat input: '+name)
        available[name] = raw
    original = closure(available, ROOTS)
    if not (set(external) | set(ram)) <= original.keys():
        raise ValueError('coverage or cold-binding helper is outside the composed closure')
    transformed = dict(original)
    stage = {}
    for name, transform in (
            ('private_heat_native_issuer_r12.py', P.issuer_source),
            ('private_heat_native_projection_r4.py', P.projection_source)):
        transformed[name] = transform(original[name].decode()).encode()
    name = 'private_heat_joined_consumer_r6.py'
    transformed[name] = P.joined_source(original[name].decode(), expected_sha256=JOINED_SHA).encode()
    name = 'private_heat_original_joined_r6.py'
    transformed[name] = joined_successor_source(original[name].decode()).encode()
    stage[name+'@joined_successor_source'] = sha256(transformed[name]).hexdigest()
    transformed[CONTINUATION] = ROUTING.original_continuation_source(original[CONTINUATION].decode()).encode()
    if sha256(transformed[CONTINUATION]).hexdigest() != CONTINUATION_SHA:
        raise ValueError('compact/funding continuation helper differs from the reviewed output')
    stage[CONTINUATION+'@original_continuation_source'] = CONTINUATION_SHA
    name = RAM_CONTEXT.NAME
    transformed[name] = RAM_CONTEXT.transform(original[name].decode()).encode()
    stage[name+'@ram_context_indexed_patch'] = sha256(transformed[name]).hexdigest()
    transformed = PAYLOAD.additional_transform(transformed)
    workers = list(PAYLOAD.WORKER_RUNTIME_HELPERS)
    if _compact_helpers is not None:
        workers = _compact_sources(original, transformed, _compact_helpers, stage, live_memory=_live_memory)
    references = _reference_paths(transformed, reference_root=reference_root,
                                  reference_pins=reference_pins)
    outputs, pins = reconcile_dependency_pins(original, transformed)
    if any(outputs[name] != original[name] for name in VERBATIM_ROOTS):
        raise ValueError('verbatim composition root was rewritten')
    if (sha256(original[GUARD]).hexdigest() != HISTORICAL_GUARD_SHA or outputs[GUARD] != original[GUARD] or
            any(HISTORICAL_GUARD_SHA.encode() in raw for raw in outputs.values())):
        raise ValueError('historical guard is pinned by the closure; the successor guard cannot replace it')
    emitted = {name: raw for name, raw in outputs.items() if name != GUARD}
    ram_out = {name: emitted[name] for name in RAM_PINS}
    helper_out = {name: raw for name, raw in emitted.items() if name not in RAM_PINS}
    if _compact_helpers is not None:
        helper_out = {COMPACT_RENAMES.get(name, name): raw for name, raw in helper_out.items()}
    for name in HELPER_COPIES+COMPANION_HELPERS:
        if name in outputs:
            raise ValueError('copied helper collides with the composed closure: '+name)
        helper_out[name] = helpers[name]
    if _compact_helpers is not None:
        for name in COMPACT_RUNTIME_HELPERS:
            if name in helper_out:
                raise ValueError('compact helper collides with composed source: '+name)
            helper_out[name] = _compact_helpers[name]
    reviewed = _reviewed_path_mutations({**helper_out, **ram_out})
    imported = external_imports({**helper_out, **ram_out})
    recovery = sha256(ram_out[RAM_RECOVERY]).hexdigest()
    cold_name = 'private_heat_restored_binding_r10.py' if _compact_helpers is not None else RAM_RECOVERY
    cold_hash = sha256(helper_out[cold_name]).hexdigest() if _compact_helpers is not None else recovery
    report = dict(schema=('atlas.private.compact-heat-successor-composition.v1' if _compact_helpers is not None
                          else 'atlas.private.indexed-heat-successor-composition.v2'),
        roots=list(ROOTS), verbatim_roots=list(VERBATIM_ROOTS),
        original={name: sha256(raw).hexdigest() for name, raw in original.items()},
        successor={name: sha256(raw).hexdigest() for name, raw in emitted.items()},
        changed=sorted(name for name in outputs if outputs[name] != original[name]),
        dependency_pin_changes=pins, preserved_accounting_references=references,
        stage_digests=stage, ram_helpers={name: sha256(raw).hexdigest() for name, raw in ram_out.items()},
        ram_recovery_sha256=recovery,
        cold_binding_sha256=dict(predecessor=RAM_PINS[RAM_RECOVERY], successor=cold_hash),
        copied_helpers={name: sha256(helpers[name]).hexdigest() for name in HELPER_COPIES+COMPANION_HELPERS},
        composer_supplied={GUARD: SUCCESSOR_GUARD_SHA}, external_imports=imported,
        worker_runtime_helpers=list(workers), reviewed_path_mutations=reviewed,
        checkpoint_admission=False, numerical_algorithm_changed=False)
    if _compact_helpers is not None:
        report.update(cold_binding_module=cold_name, renamed=dict(COMPACT_RENAMES), live_memory=_live_memory,
            compact_helpers={name: sha256(raw).hexdigest() for name, raw in _compact_helpers.items()},
            emitted={name: sha256(raw).hexdigest() for name, raw in {**helper_out, **ram_out}.items()})
    return helper_out, ram_out, report


def cold_binding_source(source, report):
    """The composer's exact count-1 rewrite of the cold reader's RAM-recovery pin."""
    pins = report['cold_binding_sha256']
    if pins['predecessor'] != RAM_PINS[RAM_RECOVERY] or not re.fullmatch('[0-9a-f]{64}', pins['successor']):
        raise ValueError('composed cold binding pin required')
    return _once(source, "_BINDING_SHA = '"+pins['predecessor']+"'\n", "_BINDING_SHA = '"+pins['successor']+"'\n")


def joined_driver_source(source):
    """Pass an explicitly owned durable query store; all physics is unchanged."""
    marker = '_EDITS = _EDITS + _PARTITION_EDITS'
    edits = (
        ('indexed-state-comparison-helper',
         'import numpy as np\n',
         'import numpy as np\nimport private_heat_indexed_runtime as INDEXED_REOPEN\n'),
        ('explicit-completed-query-owner',
         '                              before_advance=None, completed_observer=None, max_partition_components=8192):',
         '                              before_advance=None, completed_observer=None, max_partition_components=8192,\n'
         '                              endpoint_checkpoints=None):'),
        ('forward-completed-query-owner',
         'max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel)',
         'max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel,\n'
         '                    _endpoint_checkpoints=endpoint_checkpoints)'),
        ('retain-indexed-reopen-operands',
         'record=accepted.exterior.state.record(), fields=accepted.exterior.state.arrays(),',
         'record=INDEXED_REOPEN.spatial_record(accepted.exterior.state), fields=accepted.exterior.state.arrays(),'),
        ('compare-indexed-reopen-operands',
         "    test.assertEqual(workflow.exterior_state.record(), expected['record'])",
         "    INDEXED_REOPEN.compare_spatial_records(test, workflow.exterior_state, expected['record'])"),
    )
    return P._replace(source, marker, '_RESTART_EDITS = '+repr(edits)+'\n'+marker+' + _RESTART_EDITS')


def joined_successor_source(source):
    """Plus the parent geometry transfer, applied to the ORIGINAL control text before every edit."""
    return _once(joined_driver_source(source), JOINED_DERIVED, JOINED_TRANSFER)
