"""Build only the selected Plan12 successor delta; no Atlas imports or execution.

Frozen predecessor sources and receipts remain unchanged. New current-consumer
pins are derived only at the six enumerated source seams below. Historical
consumer/transformer pins are deliberately outside this operation.
"""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
BASE = T / 'ac/p11-out/composed-r13'
SELECTION = W / 'work/plan05/integrated-r13/selection-order-03.json'
BASE_SHA = '052373386aec0eeb04f84d49c4468b616c34c52bbe0f7f37850593da94cc2ab5'
SELECTION_SHA = 'cd2f67e592a68b3a19df2277613563b1d6d4b43c0de527dd5dd8a68fe535ccac'
SELECTED = {
    'private_heat_certification_kernel_r1.py': '3be44650802e629bedeaf20ce2b70cd88a14f12ee83571e8560e10a5b1157241',
    'private_heat_exact_growth_r1.py': '35e77650f92bab4eaae254d7b57597d39ce55bd663d8092c0d93f6136c3c7ec4',
    'private_heat_low_ledger_inventory_r1.py': '462bf6a2a63cd11983da8c16ea3889a8cd72bfb374b09b3729907cb7a2a66596',
    'private_heat_certification_resources_r1.py': 'fadac10d59e7a453b7940db1ba382b925e40ec6e894f62a56b1efe99c5a84591',
    'private_heat_geometry_inventory_r1.py': '43d680cfa8cb0c387d26df5ceff36dd284e8d461f2727ee2f905b1ba357c6235',
    'private_heat_geometry_inventory_r3.py': 'f16501d7cb8721e524ff7db8c7542aa87c93034b877282038c309ce0082f5b1b',
    'private_heat_finish_inventory_r1.py': '4e6c3a7f3ec991c2dbbdf051e34e4b3c95c4aeea64edf3d04df281751e64056a',
    'private_heat_finish_inventory_r2.py': 'cdb1028c6a6dcb89e46b11f4e4c38c6daefbdbb45562959e3d963606e32e0dd6',
}
REPAIRED = {
    'private_heat_forward_kernel_r13.py': ('lf3', '70f4a8e4c59faa27144a4d8edf2840ef5e7308ccd4bc92e3b5ac014fc09c99e9'),
    'private_heat_native_issuer_r13.py': ('lf3', 'ee6821b457370d131645a92de4ed94dc60128021557e006191e078c50d915d1b'),
    'private_heat_physical_order_r1.py': ('', '3c5065dd7247b6198265f74b871bdef40b2ef8e5251ab404971261556900936f'),
}
ISSUER = 'private_heat_native_issuer_r13.py'
FORWARD = 'private_heat_forward_kernel_r13.py'
CAS = 'private_heat_checkpoint_consumer_r10.py'
JOINED = 'private_heat_joined_consumer_r6.py'
RESTORED = 'private_heat_restored_binding_r10.py'
RAM_CONTEXT = 'private_heat_restored_binding_ram_context_r1.py'
RAM_RECOVERY = 'private_heat_restored_binding_ram_recovery_r1.py'
CURRENT_CONSUMERS = (
    (CAS, (ISSUER, FORWARD)),
    (JOINED, (ISSUER, FORWARD, CAS)),
    (RESTORED, (ISSUER, FORWARD, CAS, JOINED)),
    (RAM_CONTEXT, (ISSUER, FORWARD, CAS, JOINED)),
    (RAM_RECOVERY, (RAM_CONTEXT,)),
)
NATIVE = 'atlas_tectonics/integration_private_heat_cold.py'
PRESERVED = (
    'native_transfer.py', 'record_views.py', 'segment_store.py', 'spatial_records_patch.py',
    'private_heat_checkpoint_consumer_r9.py', 'private_heat_restored_binding_r9.py',
    'private_heat_native_issuer_r12.py', 'private_heat_bundle.py',
    'historical_compact_heat.py', 'runtime_compatibility.py',
    'private_heat_grouped_account_r1.py', 'private_heat_snapshot_store_r4.py',
)


def digest(raw):
    return sha256(raw).hexdigest()


def read(path, expected):
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError('Source identity differs: ' + str(path))
    return raw


def derive(raw, replacements):
    """Replace one literal SHA token per enumerated current dependency only."""
    text = raw.decode('utf8')
    tree = ast.parse(text)
    for before, after in replacements:
        constants = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == before]
        if len(constants) != 1:
            raise ValueError('Current source pin must have exactly one literal: ' + before)
        pattern = re.compile(r"(['\"])" + re.escape(before) + r"\1")
        if len(pattern.findall(text)) != 1:
            raise ValueError('Current source pin spelling is ambiguous: ' + before)
        text = pattern.sub(lambda m: m[1] + after + m[1], text)
    result = text.encode('utf8')
    compile(result, '<derived-current-heat-consumer>', 'exec')
    return result


def build():
    composition = json.loads(read(BASE / 'composition.json', BASE_SHA))
    selection = json.loads(read(SELECTION, SELECTION_SHA))
    outputs, entries = {}, {}

    def baseline(name, native=False):
        area, pins = ('src', 'outputs') if native else ('helpers', 'helpers')
        return read(BASE / area / name, composition[pins][name])

    def selected(name, source, pin):
        if selection['source_pins'].get(str(source.resolve())) != pin:
            raise ValueError('Selected source is not in the frozen closure: ' + str(source))
        raw = read(source, pin)
        compile(raw, str(source), 'exec')
        dest = 'helpers/' + name
        outputs[dest] = raw
        entries[dest] = dict(source=str(source), source_sha256=pin, output_sha256=pin,
            operation='exact-selected-source', base_sha256=composition['helpers'].get(name))

    for name, pin in SELECTED.items():
        selected(name, T / 'hs/lf3/helpers' / name, pin)
    repair = W / 'work/plan05/integrated-r13/order-repair'
    for name, (folder, pin) in REPAIRED.items():
        selected(name, repair / folder / name, pin)

    def current(name, dependencies, native=False):
        raw = baseline(name, native=native)
        replacements, changes = [], []
        for dependency in dependencies:
            before = composition['helpers'][dependency]
            after = digest(outputs['helpers/' + dependency])
            replacements.append((before, after))
            changes.append(dict(dependency=dependency, before=before, after=after))
        changed = derive(raw, replacements)
        dest = ('src/' if native else 'helpers/') + name
        outputs[dest] = changed
        entries[dest] = dict(source=str(BASE / dest), source_sha256=digest(raw),
            base_sha256=digest(raw), output_sha256=digest(changed),
            operation='derive-enumerated-current-dependency-pins', changes=changes)

    for name, dependencies in CURRENT_CONSUMERS:
        current(name, dependencies)
    current(NATIVE, (RESTORED,), native=True)

    preserved = {name: digest(baseline(name)) for name in PRESERVED}
    # Only one new numerical helper is added; every other candidate has a
    # verified predecessor. The current pins are source dependencies, never
    # old stored consumer_sources, snapshot bindings or receipt fields.
    for dest, entry in entries.items():
        if entry['base_sha256'] is not None:
            if digest((BASE / dest).read_bytes()) != entry['base_sha256']:
                raise ValueError('Predecessor changed during construction: ' + dest)

    target = HERE / 'candidate'
    if target.exists():
        raise FileExistsError('Candidate is immutable; use a new reviewed revision')
    target.mkdir()
    for dest, raw in outputs.items():
        path = target / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
        entries[dest]['candidate'] = str(path)

    report = dict(schema='plan12.selected-heat-integration-delta.r1',
        status='SOURCE_CANDIDATE_ONLY_NOT_RUNTIME_QUALIFIED',
        base=dict(path=str(BASE / 'composition.json'), sha256=BASE_SHA),
        selected=dict(path=str(SELECTION), sha256=SELECTION_SHA, lane='lf3', h5a_enabled=False),
        files=entries, preserved_helpers=preserved,
        source_contract=dict(
            current_receipts='New forward, checkpoint and cold-reader identities derive from this successor.',
            historical_receipts='Unchanged; original producer sources and consumer bindings are not rewritten.',
            historical_resume='Use existing historical endpoint and explicit current-runtime compatibility admission.',
            native_cold_binding='Current integration_private_heat_cold pins derived restored_binding_r10.',
            indexed_root='Issuer HERE resolves from selected private_heat_indexed_runtime.__file__; no benchmark path.',
            canonicalisation='Selected exact physical support order; public cells, face owners and accounts restored.',
            inherited_plans='Retain composed-r13 native and compact helpers except the enumerated heat delta.',
            c14='H2 -> L1 -> H3 remains future composition; H3/Plan13 not included.'),
        required_integration_checks=[
            'Load from the new combined native/helper roots in a fresh fenced process; assert all selected source and loaded-code identities, including ORDER.',
            'Current CAS._verify, joined source_bindings, restored._verify and native cold binding accept exact successor bytes; a one-byte disposable dependency mutation must refuse.',
            'Run the existing manufactured eight-cell full-forward seam under combined roots with workers=0; original public order/accounts and final lease release must hold.',
            'Save and cold-restore a new selected forward result through current compact consumers; wrong consumer/source/runtime binding must refuse.',
            'Historical resumed root uses existing original-reader admission; never pass its old receipt to a current-consumer path by repinning.',
        ],
        execution_performed=False, science_imported=False, receipts_changed=False,
        builder_sha256=digest(Path(__file__).read_bytes()))
    with (HERE / 'integration-map.json').open('x', encoding='utf8', newline='\n') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(files=len(outputs), helper_files=len(outputs)-1,
        native_files=1, map=str(HERE / 'integration-map.json'),
        status=report['status'])))


if __name__ == '__main__':
    build()
