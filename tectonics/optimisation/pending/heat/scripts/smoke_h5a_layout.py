"""Cheap import smoke of a prepared layout before its ticket (16 Oct; review-before-queue "smoke the exact harness").

Usage: python -B smoke_h5a_layout.py LAYOUT [LAYOUT ...]      (one fresh process per layout)
In each layout, as the control's child() does (sys.path[:0] = control.json paths), it imports the issuer and the
joined consumer and reports: which forward/functionals files are loaded and whether functionals has prepare_shared;
issuer _verify_implementation(); joined consumer _verify(); checkpoint consumer _verify(); cold workflow _verify();
and every static _PINS / _BINDING_SHA of the 6 H5a pinners checked against the file on disk (mismatches listed).
No heat call runs. Run on BASE and OUT: OUT must load its own H5a files, and every check must end as on BASE.
"""
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

PINNERS = ('helpers/private_heat_checkpoint_consumer_r10.py', 'helpers/private_heat_joined_consumer_r6.py',
           'helpers/private_heat_restored_binding_r10.py', 'ram/private_heat_restored_binding_ram_context_r1.py',
           'ram/private_heat_restored_binding_ram_recovery_r1.py',
           'runtime-src/atlas_tectonics/integration_private_heat_cold.py')


def _attempt(report, name, call):
    try:
        call()
        report[name] = 'OK'
    except Exception as error:      # reported, never hidden
        report[name] = '%s: %s' % (type(error).__name__, str(error)[:160])


def _static_pins(layout):
    found, bad = 0, []
    for rel in PINNERS:
        path = layout/rel
        text = path.read_text(encoding='utf8')
        namespace = {}
        for line in text.split('\n'):
            if line.startswith('_BINDING_SHA = '):
                namespace['_BINDING_SHA'] = line.split("'")[1]
        pins = {}
        if '_PINS = {' in text:
            block = text.split('_PINS = {', 1)[1].split('}', 1)[0]
            for line in block.split('\n'):
                parts = line.split("'")
                if len(parts) >= 4:
                    pins[parts[1]] = parts[3]
        for name, pin in pins.items():
            target = next((d/name for d in (path.parent, layout/'helpers', layout/'ram') if (d/name).is_file()), None)
            found += 1
            if target is None or sha256(target.read_bytes()).hexdigest() != pin:
                bad.append('%s pins %s' % (path.name, name))
        if '_BINDING_SHA' in namespace:
            found += 1
            binding = {'private_heat_restored_binding_ram_recovery_r1.py':
                       layout/'ram/private_heat_restored_binding_ram_context_r1.py',
                       'integration_private_heat_cold.py': layout/'helpers/private_heat_restored_binding_r10.py'}[path.name]
            if sha256(binding.read_bytes()).hexdigest() != namespace['_BINDING_SHA']:
                bad.append('%s _BINDING_SHA' % path.name)
    return found, bad


def child(layout):
    layout = Path(layout).resolve()
    info = json.loads((layout/'control.json').read_text(encoding='utf8'))
    sys.path[:0] = info['paths']
    report = dict(layout=layout.name)
    import private_heat_native_issuer_r13 as I
    import private_heat_joined_consumer_r6 as J
    import private_heat_checkpoint_consumer_r10 as CK
    from atlas_tectonics import integration_private_heat_cold as COLD
    F = I.F
    report['forward'] = '%s %s' % (Path(F.__file__).relative_to(layout), sha256(Path(F.__file__).read_bytes()).hexdigest()[:8])
    report['functionals'] = '%s %s' % (Path(F.FUNCTIONS.__file__).relative_to(layout),
                                       sha256(Path(F.FUNCTIONS.__file__).read_bytes()).hexdigest()[:8])
    report['prepare_shared'] = hasattr(F.FUNCTIONS, 'prepare_shared')
    _attempt(report, 'issuer _verify_implementation', I._verify_implementation)
    _attempt(report, 'joined _verify', J._verify)
    _attempt(report, 'checkpoint _verify', lambda: CK._verify(None))
    _attempt(report, 'cold _verify', lambda: COLD._verify(None))
    found, bad = _static_pins(layout)
    report['static pins'] = '%d checked, mismatched: %s' % (found, bad or 'none')
    print(json.dumps(report), flush=True)


def main():
    if sys.argv[1] == 'child':
        return child(sys.argv[2])
    worst = 0
    for layout in sys.argv[1:]:
        done = subprocess.run([sys.executable, '-B', __file__, 'child', layout])
        worst = max(worst, done.returncode)
    return worst


if __name__ == '__main__':
    sys.exit(main())
