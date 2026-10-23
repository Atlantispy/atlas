"""Bounded CLI/decoder controls only; no full arithmetic suite or production imports."""
import argparse
import copy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

PIN = 'bcabef407a99aae01af82f9ec7d50d7d9378b1bce76a7885db89f4f0bcfbfa5a'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'control assertions must be enabled')
    require(hashlib.sha256(args.probe.read_bytes()).hexdigest() == PIN, 'probe changed')
    args.out_dir.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location('chart_probe_control_target', args.probe)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.SOURCE, probe.VECTOR = args.repo/probe.SOURCE_REL, args.repo/probe.VECTOR_REL
    ns = probe.build()
    controls = []
    q = {'type': 'Fraction', 'n': '1', 'd': '3'}
    integer = {'type': 'int', 'n': '-2', 'd': '1'}
    require(type(probe.decode(q, ns)) is Fraction and probe.decode(q, ns) == Fraction(1, 3), 'Fraction changed')
    require(type(probe.decode(integer, ns)) is int and probe.decode(integer, ns) == -2, 'integer changed')
    controls.append('exact numeric types preserved')
    bad = [0, 1.5, {'type': 'Fraction', 'n': 1, 'd': '3'},
           {'type': 'Fraction', 'n': '1', 'd': 3},
           {'type': 'Fraction', 'n': '1', 'd': '0'},
           {'type': 'Fraction', 'n': '1', 'd': '-3'},
           {'type': 'Fraction', 'n': '2', 'd': '6'},
           {'type': 'Fraction', 'n': '01', 'd': '3'},
           {'type': 'Fraction', 'n': str(1 << 4096), 'd': '1'},
           {'type': 'int', 'n': '1', 'd': '2'},
           {'type': 'tuple', 'items': (), 'extra': True},
           {'type': 'unknown', 'items': []},
           {'type': 'tuple', 'items': [None]*257}]
    deep = None
    for _ in range(34):
        deep = {'type': 'tuple', 'items': [deep]}
    bad.append(deep)
    for index, value in enumerate(bad):
        try:
            probe.decode(value, ns)
        except ValueError:
            controls.append('decoder rejected malformed input '+str(index))
        else:
            raise AssertionError('malformed input accepted '+str(index))
    a, b, normal = tuple(map(Fraction, (1, 0, 0))), tuple(map(Fraction, (0, 1, 0))), tuple(map(Fraction, (0, 0, 1)))
    rows = []
    for left, right in ((Fraction(0), Fraction(1)), (Fraction(1, 2), Fraction(1, 2))):
        values = (a, b, normal, left, right, 96)
        ns['_JET_PRECISION'].set(96)
        expected = ns['_radial_chart_jets'](*values)
        rows.append(dict(function='_radial_chart_jets', precision=96,
                         argument_names=['a', 'b', 'normal', 'left', 'right', 'bits'],
                         arguments=probe.encoded(values), expected=probe.encoded(expected)))
    fixture = dict(verdict='PASS', synthetic_fixture=True, source_pins=dict(coupling=dict(sha256=probe.PIN)), captures=rows)
    capture = args.out_dir/'synthetic-captures.json'
    capture.write_text(json.dumps(fixture)+'\n', encoding='utf-8')
    def invoke(label, capture_path, extra=()):
        output = args.out_dir/(label+'.json')
        command = [sys.executable, '-B', *extra, str(args.probe), '--repo', str(args.repo),
                   '--captures', str(capture_path), '--out', str(output)]
        process = subprocess.run(command, capture_output=True, text=True, timeout=30)
        (args.out_dir/(label+'.stdout.log')).write_text(process.stdout, encoding='utf-8')
        (args.out_dir/(label+'.stderr.log')).write_text(process.stderr, encoding='utf-8')
        return process, output
    success, output = invoke('synthetic-replay', capture)
    require(success.returncode == 0, 'changed CLI failed; preserved stderr')
    replay = json.loads(output.read_text())
    require(replay['status'] == 'PASS' and replay['actual_replay']['captures'] == 2
            and replay['actual_replay']['bindings'] == 1 and replay['actual_replay']['synthetic_fixture'], 'capture replay result wrong')
    require('C:/' not in output.read_text() and 'C:\\' not in output.read_text(), 'private path in replay result')
    controls.append('changed CLI two synthetic captures, one binding, full output witness equality')
    mutated = copy.deepcopy(fixture)
    mutated['captures'][0]['arguments']['items'][-1] = {'type': 'int', 'n': '193', 'd': '2'}
    malformed = args.out_dir/'malformed-capture.json'
    malformed.write_text(json.dumps(mutated)+'\n', encoding='utf-8')
    refused, refused_output = invoke('malformed-refusal', malformed)
    require(refused.returncode != 0 and not refused_output.exists()
            and 'captured integer has a denominator' in refused.stderr, 'malformed CLI did not fail closed')
    controls.append('malformed CLI nonzero, exact refusal, no success artifact')
    optimised, optimised_output = invoke('optimised-refusal', capture, ('-O',))
    require(optimised.returncode != 0 and not optimised_output.exists()
            and 'assertions must remain enabled' in optimised.stderr, '-O accepted')
    controls.append('-O nonzero refusal before acceptance, no success artifact')
    require(hashlib.sha256(args.probe.read_bytes()).hexdigest() == PIN, 'probe finality failed')
    result = dict(status='PASS', scope='synthetic CLI and decoder only; no actual pressure capture or stage',
                  probe_sha256=PIN, control_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  controls=controls, cli_exit_codes=dict(replay=success.returncode, malformed=refused.returncode,
                                                        optimised=optimised.returncode),
                  source_sha256=probe.PIN, vector_sha256=probe.VPIN,
                  full_arithmetic_suite_repeated=False)
    (args.out_dir/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
