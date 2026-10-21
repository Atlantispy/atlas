"""Prepare only the agreed marker delta from the integrated Plans10-12 driver."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
BASE = T / 'ac/p1012-r1'
R = T / 'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
PINS = {
    'fresh_interval_driver.py': '5b33873c2e088ae555ad3ed5427c1daee8f567654c1c6eb79ac32ccfa7cfa21c',
    'prepared_interval_driver.py': '8dd8720cbb4a96b89dbbb78a742eb75d01e811441ab63d63fe02b2b01ee665f7',
}


def change(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Expected one source anchor: ' + before)
    return text.replace(before, after)


def main():
    out = HERE / 'candidate/helpers'
    out.mkdir(parents=True, exist_ok=False)
    records = {}
    for name, expected in PINS.items():
        raw = (BASE / 'helpers' / name).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError('Integrated source changed: ' + name)
        text = raw.decode('utf8')
        if name == 'fresh_interval_driver.py':
            text = change(text, "(_closure(guard, 'certificate'), 'closed_guard_certificates')",
                          "(SimpleNamespace(__code__=_closure(guard, 'certificate')), 'closed_guard_certificates')")
            text = change(text, "(_closure(guard, 'admissible'), 'closed_guard_admissible_tests')",
                          "(SimpleNamespace(__code__=_closure(guard, 'admissible')), 'closed_guard_admissible_tests')")
            text = change(text, 'return SimpleNamespace(__code__=found[0])', 'return found[0]')
            text = change(text, '# Exactly one direct nested function of that name; a deeper one is not a match. The observer reads\n    # only ``__code__``, so the code object is presented alone.',
                          '# Return exactly one direct nested code object; deeper functions do not match.\n    # Tick registration supplies the observer probe without executing either closure.')
        result = text.encode('utf8')
        (out / name).write_bytes(result)
        records[name] = dict(source=str(BASE / 'helpers' / name), before=expected,
                             candidate=str(out / name), after=sha256(result).hexdigest(),
                             changed=raw != result)
    historical = R / 'probes/step8/claude-20261015/before-src'
    history = {p.name: dict(path=str(p), sha256=sha256(p.read_bytes()).hexdigest())
               for p in historical.glob('*before-item11m')}
    record = dict(status='PREPARED_NOT_TESTED', baseline=str(BASE), files=records,
                  historical_baseline='28 run / 7 failures, retained; not claimed current',
                  retained_before_copies=history, numerical_changes=False)
    (HERE / 'marker-delta.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf8')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
