"""Prepare the accepted Heat S1 source delta without importing Atlas.

Production adds exact r5/r11 and changes only the selected r13 FINISH import,
then derives current consumer pins in dependency order. The separate proof
alias delta retains r4/r10 names solely for the already approved D-b layout.
This is source preparation, not runtime qualification or scientific proof.
"""
import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import re


BASE_PIN = 'cb71df92d0ab2f3ab175c43a669d5b8ffc1d4d350cbdc49b68fd6f2cabfb74d5'
S1_PINS = {
    'private_heat_closed_owned_r5.py': '6da4964cad7a2553cce40ef53fd2a42f6c6f12bd605a92685b59652f7e74c079',
    'private_heat_finish_kernel_r11.py': 'e5a2409fb87695dc0151c7b256f27bea2e550d0fdaf5a66a44b516dde53f3e15',
}
BASE_HEAT = {
    'private_heat_closed_owned_r4.py': '62b7ffc42c8201c59dd10c6d35e0cbb20dcb068cf9be01f1ee3781b272024206',
    'private_heat_finish_kernel_r10.py': '31ed7a29c5ee06c04a69eaccb5ec863517b3ad3550e8f3cadef98a0b6356f873',
    'private_heat_forward_kernel_r13.py': '70f4a8e4c59faa27144a4d8edf2840ef5e7308ccd4bc92e3b5ac014fc09c99e9',
    'private_heat_native_issuer_r13.py': 'ee6821b457370d131645a92de4ed94dc60128021557e006191e078c50d915d1b',
    'private_heat_physical_order_r1.py': '3c5065dd7247b6198265f74b871bdef40b2ef8e5251ab404971261556900936f',
}
F = 'private_heat_forward_kernel_r13.py'
C = 'private_heat_checkpoint_consumer_r10.py'
J = 'private_heat_joined_consumer_r6.py'
B = 'private_heat_restored_binding_r10.py'
CTX = 'private_heat_restored_binding_ram_context_r1.py'
REC = 'private_heat_restored_binding_ram_recovery_r1.py'
NATIVE = 'atlas_tectonics/integration_private_heat_cold.py'
CASCADE = ((C, (F,)), (J, (F, C)), (B, (F, C, J)),
           (CTX, (F, C, J)), (REC, (CTX,)), (NATIVE, (B,)))


def digest(raw):
    return sha256(raw).hexdigest()


def read(path, expected):
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError('Source identity differs: ' + str(path))
    return raw


def once(raw, old, new):
    if raw.count(old) != 1:
        raise ValueError('Required source seam is not unique: ' + old.decode('utf8'))
    changed = raw.replace(old, new)
    compile(changed, '<s1-source-only>', 'exec')
    return changed


def repin(raw, replacements):
    text = raw.decode('utf8')
    tree = ast.parse(text)
    for before, after in replacements:
        constants = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and node.value == before]
        pattern = re.compile(r"(['\"])" + re.escape(before) + r"\1")
        if len(constants) != 1 or len(pattern.findall(text)) != 1:
            raise ValueError('Current dependency pin is not exactly one literal: ' + before)
        text = pattern.sub(lambda match: match[1] + after + match[1], text)
    changed = text.encode('utf8')
    compile(changed, '<s1-current-consumer-pins>', 'exec')
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--s1', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base, s1, out = args.base.resolve(), args.s1.resolve(), args.output.resolve()
    if not out.is_dir() or any((out / item).exists()
                             for item in ('production-delta', 'proof-alias-delta', 'integration-map.json')):
        raise ValueError('Output folder must exist and all generated targets must be absent')
    composition = json.loads(read(base / 'composition.json', BASE_PIN))
    originals = {}

    def baseline(name, native=False):
        relative = ('src/' if native else 'helpers/') + name
        pin = composition['outputs' if native else 'helpers'][name]
        raw = read(base / relative, pin)
        originals[relative] = raw
        return raw

    for name, expected in BASE_HEAT.items():
        if composition['helpers'].get(name) != expected:
            raise ValueError('Selected lf3 base binding differs: ' + name)
        baseline(name)
    production, entries = {}, {}
    for name, pin in S1_PINS.items():
        if name in composition['helpers'] or (base / 'helpers' / name).exists():
            raise ValueError('Accepted S1 module must be a new base member: ' + name)
        raw = read(s1 / name, pin)
        compile(raw, str(s1 / name), 'exec')
        relative = 'helpers/' + name
        production[relative] = raw
        entries[relative] = dict(operation='exact-accepted-source-addition', base_sha256=None,
            source=str(s1 / name), source_sha256=pin, output_sha256=pin)
    before_forward = baseline(F)
    after_forward = once(before_forward,
        b'import private_heat_finish_kernel_r10 as FINISH\n',
        b'import private_heat_finish_kernel_r11 as FINISH\n')
    production['helpers/' + F] = after_forward
    entries['helpers/' + F] = dict(operation='one-FINISH-import-only',
        source=str(base / 'helpers' / F), base_sha256=digest(before_forward),
        output_sha256=digest(after_forward), retained='All physical-order, LOW, L1 and admission code')
    for name, dependencies in CASCADE:
        native = name == NATIVE
        relative = ('src/' if native else 'helpers/') + name
        before = baseline(name, native=native)
        replacements, changes = [], []
        for dependency in dependencies:
            old = composition['helpers'][dependency]
            new = digest(production['helpers/' + dependency])
            replacements.append((old, new))
            changes.append(dict(dependency=dependency, before=old, after=new))
        after = repin(before, replacements)
        production[relative] = after
        entries[relative] = dict(operation='enumerated-current-dependency-pins-only',
            source=str(base / relative), base_sha256=digest(before), output_sha256=digest(after),
            changes=changes)
    if len(production) != 9:
        raise ValueError('Expected exactly two additions, one forward and six current consumers')
    aliases = {
        'helpers/private_heat_closed_owned_r4.py': production['helpers/private_heat_closed_owned_r5.py'],
        'helpers/private_heat_finish_kernel_r10.py': once(
            production['helpers/private_heat_finish_kernel_r11.py'],
            b'import private_heat_closed_owned_r5 as Q\n', b'import private_heat_closed_owned_r4 as Q\n'),
    }
    # The alias proof's producer and all its explicit current consumer pins stay
    # byte-identical; dynamic source/loaded-code closures capture changed Q/FINISH.
    compile(aliases['helpers/private_heat_closed_owned_r4.py'], '<s1-proof-alias-r4>', 'exec')
    proof_entries = {relative: dict(base_sha256=digest(originals[relative]),
        output_sha256=digest(raw), production_use=False) for relative, raw in aliases.items()}
    for relative, raw in originals.items():
        read(base / relative, digest(raw))
    read(base / 'composition.json', BASE_PIN)
    for folder, files in (('production-delta', production), ('proof-alias-delta', aliases)):
        for relative, raw in files.items():
            destination = out / folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(raw)
    report = dict(schema='atlas.private.plan14.s1-source-delta.r1',
        status='SOURCE_PREPARED_NOT_RUNTIME_QUALIFIED',
        base=dict(path=str(base / 'composition.json'), sha256=BASE_PIN, lane='lf3', h5a_enabled=False),
        builder_sha256=digest(Path(__file__).read_bytes()), production_files=entries,
        proof_alias_files=proof_entries,
        production_contract=dict(
            exact_sources=S1_PINS, physical_order_preserved=BASE_HEAT['private_heat_physical_order_r1.py'],
            issuer_bytes_preserved=BASE_HEAT['private_heat_native_issuer_r13.py'],
            historical_sources='Existing r4/r10 and historical consumers, receipts and source inventories unchanged',
            serial_integration='Apply this exact delta to the pinned p1012 base BEFORE C14; then derive C14 pins from that successor. Never overwrite a later C14 forward/consumer with this p1012-derived candidate.',
            after_C14_alternative='Apply only the exact FINISH import seam plus accepted new modules to actual C14 bytes; rederive current pins from actual resulting dependencies and issue a new map.',
            identity='New composition/profile/manifest and eligible ROOT required; old receipts never repinned'),
        accepted_evidence=dict(
            acceptance='coordinator-handoff-20261016.md:18:11 Heat S1 accepted NOT REFUTED, 266 fuzz cases, zero mismatches',
            tests=dict(path='hs/tests/test_s1_closed_reuse_r2.py', sha256='69c3ac8f478496eeb258b958730cc86499c7af9c23b6a575fc9b705a1fd9db6a', cases=30),
            log=dict(path='hs/evidence/test-s1-r3-s1.log', sha256='b1897434f4d5c333896352fe298ed1c1af587994ee2f5e100a1542e7bda49091'),
            changed_fields=dict(path='hs/evidence/s1-changed-fields-r2.md', sha256='2c3ea60b6d6c00c950b83ec7fded0d356170e2698bd89336f41051df4700592c')),
        changed_field_contract=dict(
            unchanged=['Exact guard theta/selection, energy/face contents and three certificate values',
                       'Sealed numerical outputs and value digests', 'Forward-result compact admission amount'],
            changed=['Source bindings and identities incorporating their exact preimages',
                     'Unsealed finish diagnostics: operation, retention, reservation and scalar observations',
                     'Closed-stage budget amounts, certificate ticks, timing and cancellation-poll counts'],
            aliasing='Nested endpoint certificate dictionaries share objects while equal values are retained',
            proof_translation='Approved same-call alias layout changes only r4/r10 source digest leaves and resulting bound identities, plus exact layout-root translation. Production r5/r11 names require the explicit r4->r5/r10->r11 source correspondence, F change and six current consumer bindings in this map; this is source correspondence, not a scientific equality result.',
            forbidden='No generic acceptance of all 64-hex leaves; no blanket metadata-byte parity or new numerical tolerance'),
        proof_alias_contract=dict(
            reason='Historical compare_ab_r2 substitutes roots, not module names: exact-name production r5/r11 creates different source-path keys.',
            layout='Copy pinned current base to a NEW disposable layout, replace ONLY these two helper files, regenerate its exact source inventory/control roots. Keep production r5/r11 additions outside this proof layout.',
            adaptation='r5 bytes exactly under r4; r11 bytes under r10 with its sole Q import changed back to r4',
            forward_and_consumers='Unchanged byte-for-byte; their source/loaded-code closures discover the new Q/FINISH bytes',
            limit='This two-file delta is not a complete executable W4 layout or approved launch request'),
        required_checks=[
            'Source-only: verify exact nine-file production delta, accepted helper bytes, one forward import and enumerated pin-only consumer changes; validate actual new composition/profile source admission.',
            'Focused new integration: bind actual F.FINISH.Q r11/r5 and code identities through selected profile; preserve physical support/public order, exact accounts and final lease release. Adapt existing combined heat qualification rather than rerun unrelated evidence.',
            'Current checkpoint/joined/restored/RAM/native-cold admissions and disposable wrong dependency/code/source/runtime refusals must cover actual joint generation.',
            'W4 remains MISSING: separately source-bind and release the genuine same-call W4 proof using the approved alias layout and current physical-order repair; preserve worker/env/start/cleanup guards. Require complete nonempty arrays/accounts/scalars/ledgers and explicit evidence-bound metadata differences, not compare_ab_r2 generic digest PASS alone.',
            'Prove production-to-proof alias correspondence by the exact two import/name substitutions above and bound source map; do not call old q32 lf3/lh evidence an S1 W4 result.',
            'If C14 changes the selected route, the required combined proof must identify that actual generation. Source preparation and historical 30-case acceptance do not establish it.',
        ],
        run_authority='No tests, scientific imports, simulations, queue jobs or hold releases performed; W4 requires its own specific launch authority',
        scientific_acceptance=False, runtime_qualification=False, tests_run=False,
        historical_receipts_changed=False, base_modified=False)
    with (out / 'integration-map.json').open('x', encoding='utf8', newline='\n') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(status=report['status'], production_files=len(production),
        proof_alias_files=len(aliases), map=str(out / 'integration-map.json'),
        map_sha256=digest((out / 'integration-map.json').read_bytes()))))


if __name__ == '__main__':
    main()
