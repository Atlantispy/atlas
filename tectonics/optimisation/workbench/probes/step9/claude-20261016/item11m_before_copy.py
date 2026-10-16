"""Item 11 M: rebuild the before-copy of test_fresh_interval_driver.py (ace18923) by undoing this step's
first four edits on a copy, and refuse unless the result hashes to ace18923. Writes only the before-copy.
Usage: python -B item11m_before_copy.py
"""
from hashlib import sha256
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
SOURCE = RESUMABILITY/'test_fresh_interval_driver.py'
TARGET = RESUMABILITY/'probes'/'step8'/'claude-20261015'/'before-src'/'test_fresh_interval_driver.py.before-item11m'
EXPECTED = 'ace18923'

UNDO = [
    ("""# Item 11 M: markers at calls inside the finish and the projection, and three heat counters.
R9_TICKS = ('component_volume_queries', 'heat_faces', 'heat_faces_collected')
HEAT_TICKS = ('metric_identity_calls', 'closed_guard_certificates', 'closed_guard_admissible_tests')


def closed_guard_scan(theta):
    \"\"\"Stand-in for the closed guard's scan: the two nested functions its counters observe, by name.\"\"\"
    def certificate(value):
        return value
    def admissible(value):
        return value
    return certificate, admissible
""", ''),
    (""", r3_checks=True,
              guard_scan=closed_guard_scan):""", ', r3_checks=True):'),
    ("""cm('observe', stages=stages,
                                                                                       ticks=ticks)),""",
     "cm('observe', stages=stages)),"),
    ("""        FINISH=SimpleNamespace(finish='finish', C=SimpleNamespace(correct='correct'),
                               Q=SimpleNamespace(closed_guard='closed-guard', _guard=guard_scan),
                               I=SimpleNamespace(issue='issue'))),
        N=SimpleNamespace(project='project', R=SimpleNamespace(verified_private='decode', calculate='exact')),
        HEAT_LEDGER=SimpleNamespace(package_result='package-result'),
        INDEXED=SimpleNamespace(metric_identity='metric-identity'))""",
     """        FINISH=SimpleNamespace(finish='finish')), N=SimpleNamespace(project='project'),
        HEAT_LEDGER=SimpleNamespace(package_result='package-result'))"""),
]


def main():
    if TARGET.exists():
        print(TARGET, 'exists; refusing to overwrite it')
        return 1
    data = SOURCE.read_bytes()
    text = data.decode('utf8')
    newline = '\r\n' if '\r\n' in text else '\n'
    for new, old in UNDO:
        new, old = new.replace('\n', newline), old.replace('\n', newline)
        if text.count(new) != 1:
            print('edit not found exactly once:', new[:60])
            return 1
        text = text.replace(new, old)
    out = text.encode('utf8')
    digest = sha256(out).hexdigest()
    if not digest.startswith(EXPECTED):
        print('rebuilt copy is', digest[:8], 'not', EXPECTED, '; nothing written')
        return 1
    TARGET.write_bytes(out)
    print('before-copy', TARGET.name, digest[:8], 'written; current', sha256(data).hexdigest()[:8])
    return 0


if __name__ == '__main__':
    sys.exit(main())
