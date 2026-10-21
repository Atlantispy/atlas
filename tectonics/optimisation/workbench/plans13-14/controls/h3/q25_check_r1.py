"""Read-only Plan13 q25 preflight/result checks; no Atlas runtime imports.

The launch subcommand is deliberately absent. Root owns queue authority, log archival
and launch. Preflight reports the pending log rename; it never performs it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

HELPER_SHA = 'e0be3a309c8ab9ccee3c1a36525f72da27e816b1ce984651dbd85a3c072a14aa'
OLD_LOG_SHA = 'd4e5571c8542f6583102974ee9e0767d3cc8fb3882d1e5a29e052ec8e39ff027'
INPUT = 'W4 same-call control (C/step7_same_call_heat_control.py)'
BOOKED_GIB = 2.0
SOURCE_PINS = {
    'ck/transforms/h3_compiled_dot.py': '9ce7ac9d96a5606118977ee2a835b460202210abea5175f6c9f7452e10d4c3aa',
    'ck/h3/private_heat_compiled_dot_r1.py': HELPER_SHA,
    'ck/h3/job_h3r3.sh': 'a2e44aa697e16bc571c7cd2ac5ed2f001151a7bfa2e4a952de0335f35eb2ecd5',
    'ck/l3r3/control.json': 'c21268d48b28ee6c2406066dc2535b2b0d8aae1ce9be3726a7d819bd8af98b01',
    'ck/l3r3/helpers/private_heat_certification_kernel_r1.py': '4099a297a8423a6213761ab4f305d442dda647ec6c7a46ee4d4734d253041f71',
    'ck/l3r3/helpers/private_heat_certification_resources_r1.py': '3c8f97250c25ce13caff3122d1b78dd9d9c2a2dab110c9ab0673eefe6c3f1b31',
    'ck/l3r3/helpers/private_heat_compiled_dot_r1.py': HELPER_SHA,
    'ck/l2/helpers/private_heat_certification_kernel_r1.py': '3be44650802e629bedeaf20ce2b70cd88a14f12ee83571e8560e10a5b1157241',
    'ck/l2/helpers/private_heat_certification_resources_r1.py': '8b451aa8d4e44175ecf24508a88245b00778a40a693111d5bfed5d8860cf167e',
    'ck/h3/identity/guard_proof.py': 'b86a478378811ae21f1f1264cf90d9719045e7827f6a8703a023b8c885377ebf',
    'ck/work/h3guard-s0/report.json': '830c3a7db51e42c6034794d640b3d9ba7dae5148873e6f44842f0419e8ca5bbd',
    'ck/h3/refute-r3/report.md': '1b8a5b445e4e4998cc4f033a74eb0abadb6a2868a0b6c3df86d90973a47b4e79',
}
HARNESS_PINS = {
    'ab_heat_r5.py': '790be9283501d49b15dcea9cf64ac60641532691d4a58ca67fbbdb74e37e807a',
    'compare_ab_r2.py': 'f67dbb662b66fc0c8559a5df7f92c3f8789210fbe4cf3892a57f7bdb26f5e7da',
    'check_arms.py': 'b8e7fe7f29ee50c49886b0dba125760678311381a17cf3c3e09a64be85587139',
}
MANIFEST_LINE = re.compile(r'^([a-f0-9]{64}) [ *](.+)$')


class Refusal(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise Refusal(message)


def digest(path):
    need(path.is_file(), f'missing file: {path}')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        need(key not in out, f'duplicate JSON key: {key}')
        out[key] = value
    return out


def load(path):
    def invalid(value):
        raise Refusal(f'non-finite JSON value: {value}')
    need(path.is_file(), f'missing JSON: {path}')
    return json.loads(path.read_text(encoding='utf8'), object_pairs_hook=_pairs, parse_constant=invalid)


def number(value, label, *, positive=False):
    need(type(value) in (int, float) and math.isfinite(value), f'{label}: not a finite number')
    need(value > 0 if positive else value >= 0, f'{label}: invalid sign')
    return value


def source_pins(ck):
    pins = {**SOURCE_PINS, **{'hs/scripts/'+name: sha for name, sha in HARNESS_PINS.items()}}
    for relative, expected in pins.items():
        need(digest(ck.parent/relative) == expected, f'source pin differs: {relative}')
    return pins


def byte_scope(paths):
    """Only the named evidence paths; allocated/compressed disk bytes are not measured."""
    out = {}
    for path in paths:
        if path.is_dir():
            total = sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
        else:
            total = path.stat().st_size
        out[path.name] = total
    return dict(scope='ab3* plus named current/archive q25 logs; logical file bytes',
                per_path=out, total_bytes=sum(out.values()))


def verify_input_manifest(path):
    value = load(path)
    need(type(value) is dict and value.get('schema') == 'plan13.q25-inputs.r1', 'input manifest schema differs')
    files = value.get('files')
    need(type(files) is list and files, 'input manifest has no files')
    seen = set()
    for row in files:
        need(type(row) is dict and type(row.get('path')) is str and type(row.get('sha256')) is str,
             'invalid input manifest row')
        target = Path(row['path'])
        need(target.is_absolute() and str(target) not in seen, 'relative/duplicate input manifest path')
        seen.add(str(target))
        need(digest(target) == row['sha256'], f'input readiness identity changed: {target}')
    return dict(manifest=str(path.resolve()), sha256=digest(path), files=len(files),
                scope=value.get('scope'), acceptance='readiness identity snapshot; no new scientific acceptance')


def preflight(ck, h13l1, archive, git_bash, git_cygpath, input_manifest=None):
    ck, h13l1, archive = ck.resolve(), h13l1.resolve(), archive.resolve()
    need(ck.name == 'ck', 'CK must be the canonical ck directory')
    need(archive.parent == ck and archive.name != 'q25.log', 'archive must be a new sibling of q25.log')
    need(not archive.exists(), 'archive target already exists; preserve it')
    need(not list(ck.glob('ab3*')), 'ab3-prefixed evidence exists; preserve it and refuse launch')
    need(digest(ck/'q25.log') == OLD_LOG_SHA, 'historical q25 waiter log differs or is missing')
    pins = source_pins(ck)
    control = load(h13l1/'control.json')
    need(type(control) is dict and type(control.get('paths')) is list, 'H13L1 has no paths list')
    expected = [str(h13l1/name) for name in ('runtime-src', 'helpers', 'ram')]
    need(control['paths'][:3] == expected, 'H13L1 canonical paths differ')
    need(all((h13l1/name).is_dir() for name in ('runtime-src', 'helpers', 'ram')), 'H13L1 paths missing')
    need(git_bash.is_file() and git_cygpath.is_file(), 'explicit Git Bash/cygpath is unavailable')
    observed = None if input_manifest is None else verify_input_manifest(input_manifest)
    return dict(status='PREFLIGHT PASS', launch_authority='root must separately obtain GO',
                ck=str(ck), h13l1=str(h13l1), h13l1_control_sha256=digest(h13l1/'control.json'),
                pending_log_rename=dict(source=str(ck/'q25.log'), destination=str(archive), sha256=OLD_LOG_SHA),
                source_pins=pins, readiness_inputs=observed,
                git_bash=str(git_bash.resolve()), git_cygpath=str(git_cygpath.resolve()),
                environment=dict(remove='all inherited PYTHON*', PYTHONHASHSEED='0',
                                 H13L1=str(h13l1), prepend_path=[str(git_bash.parent), str(git_cygpath.parent)]),
                disk_free_bytes=shutil.disk_usage(ck).free,
                disk=byte_scope([ck/'q25.log']))


def manifest(path):
    rows = {}
    for line in path.read_text(encoding='utf8').splitlines():
        found = MANIFEST_LINE.fullmatch(line)
        need(found is not None, f'invalid sha256sum line: {path.name}')
        sha, name = found.groups()
        need(name not in rows, f'duplicate manifest path: {name}')
        rows[name] = sha
    need(bool(rows), f'empty manifest: {path.name}')
    return rows


def freezes(ck):
    start, end = (ck/f'ab3-frozen-{part}.sha256' for part in ('start', 'end'))
    need(start.read_bytes() == end.read_bytes(), 'source freeze start/end differ')
    rows = manifest(start)
    current = {p.relative_to(ck).as_posix(): p for name in ('l2', 'l3r3')
               for p in (ck/name).rglob('*') if p.is_file() and not p.name.endswith('.pyc')}
    need(set(rows) == set(current), 'freeze does not cover the exact current l2/l3r3 non-pyc file set')
    for name, path in current.items():
        need(digest(path) == rows[name], f'frozen source differs: {name}')
    pin_rows = manifest(ck/'ab3-pins.sha256')
    expected = {(ck.parent/'hs'/'scripts'/name).as_posix(): sha for name, sha in HARNESS_PINS.items()}
    need(pin_rows == expected, 'recorded Heat harness pins differ')
    return dict(files=len(rows), scope='l2/l3r3 non-pyc files; exact start=end and current hashes',
                start_sha256=digest(start), end_sha256=digest(end))


def arms_check(ck, arms):
    need(type(arms) is list and len(arms) == 4, 'exactly four complete arms required')
    metrics = []
    for k, (arm, mode, label, layout) in enumerate(zip(
            arms, ('proof', 'proof', 'time', 'time'), ('h2', 'h3', 'h3', 'h2'),
            ('l2', 'l3r3', 'l3r3', 'l2'), strict=True)):
        need(type(arm) is dict, f'arm {k}: not an object')
        need(type(arm.get('arm')) is int and arm['arm'] == k, f'arm {k}: wrong index')
        need((arm.get('mode'), arm.get('label'), arm.get('layout'), arm.get('input')) ==
             (mode, label, str((ck/layout).resolve()), INPUT), f'arm {k}: wrong mode/label/layout/input')
        need(arm.get('status') == 'PASS' and type(arm.get('exit_code')) is int and arm['exit_code'] == 0
             and type(arm.get('leaks')) is int and arm['leaks'] == 0 and 'stopped' not in arm,
             f'arm {k}: partial/failed/leaking/stopped arm')
        need(arm.get('used') == [6, 6] and all(type(v) is int for v in arm['used'])
             and arm.get('fallback') == [None, None], f'arm {k}: wrong workers or fallback')
        child = load(ck/'ab3'/f'arm-{k}.json')
        need(type(child) is dict and child.get('status') == 'PASS', f'arm {k}: missing child PASS')
        ab = child.get('ab')
        need(type(ab) is dict and (ab.get('mode'), ab.get('layout'), ab.get('leaks'), ab.get('fallbacks')) ==
             (mode, arm['layout'], [], []) and ab.get('workers_configured') == 6,
             f'arm {k}: child mode/layout/leak/fallback mismatch')
        calls = ab.get('calls')
        need(type(calls) is list and len(calls) == 2 and all(
             type(c) is dict and c.get('workers') == 6 and c.get('fallback') is None for c in calls),
             f'arm {k}: child workers/fallback mismatch')
        need(type(child.get('arrays')) is dict and child['arrays'] and child['arrays'] == arm.get('arrays'),
             f'arm {k}: array identities absent/inconsistent')
        need((ck/'ab3'/f'arm-{k}.log').is_file(), f'arm {k}: missing log')
        wall = number(arm.get('arm_wall_seconds'), f'arm {k} wall', positive=True)
        peak = number(arm.get('tree_peak_mib'), f'arm {k} tree peak', positive=True)
        low = number(arm.get('available_low_mib'), f'arm {k} available low', positive=True)
        need(peak <= 12*1024 and low >= 1024, f'arm {k}: recorded in-run memory guard breach')
        predicted = number(arm.get('predicted_peak_gib'), f'arm {k} prediction', positive=True)
        gate = number(arm.get('start_gate_gib'), f'arm {k} start gate', positive=True)
        free = number(arm.get('free_gib_at_start'), f'arm {k} free at start', positive=True)
        # r5 rounds prediction to .001 and gate/free to .01 GiB in its records.
        need(abs(gate-(predicted*1.2+2)) <= .011 and free+.01 >= gate, f'arm {k}: inconsistent start gate')
        need(type(arm.get('prediction_basis')) is str and arm['prediction_basis'], f'arm {k}: missing gate basis')
        need(type(arm.get('other_load_cpus')) in (int, float) and math.isfinite(arm['other_load_cpus']),
             f'arm {k}: missing observed load')
        metrics.append(dict(arm=k, mode=mode, label=label, arm_wall_seconds=wall,
                            tree_peak_mib=peak, available_low_mib=low,
                            parent_peak_mib=number(arm.get('parent_peak_mib'), f'arm {k} parent peak'),
                            worker_peak_mib=number(arm.get('worker_peak_mib'), f'arm {k} worker peak'),
                            other_load_cpus=arm['other_load_cpus'], booked_gib=BOOKED_GIB,
                            exceeds_booking=peak > BOOKED_GIB*1024))
    return metrics


def proof_captures(ck, arms):
    import numpy as np
    paths = [ck/'ab3'/f'arm-{k}' for k in (0, 1)]
    manifests = [load(p/'arrays.json') for p in paths]
    need(all(type(m) is dict and m for m in manifests), 'empty proof array capture')
    need(list(manifests[0]) == list(manifests[1]), 'proof array manifest names/order differ')
    need(all(set(m) == set(arms[k]['arrays']) for k, m in enumerate(manifests)),
         'proof manifest/result array sets differ')
    for name in manifests[0]:
        need(type(name) is str and name and Path(name).name == name and '/' not in name and '\\' not in name,
             'unsafe array capture name')
        values = [np.load(p/(name+'.npy'), allow_pickle=False) for p in paths]
        need(all(list(v.shape) == m[name] for v, m in zip(values, manifests, strict=True)),
             f'proof array manifest shape differs: {name}')
        a, b = values
        need(a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes(),
             f'proof array differs: {name}')
    need(all(load(p/'legacy_metadata.json') for p in paths), 'empty/missing proof metadata')
    return list(manifests[0])


def metadata_diffs(ck):
    """All differing leaves, with full values; digest classification grants no approval."""
    before, after = (load(ck/'ab3'/f'arm-{k}'/'legacy_metadata.json') for k in (0, 1))
    left, right = str((ck/'l2').resolve()), str((ck/'l3r3').resolve())
    substitutions = ((left, right), (left.replace('\\', '\\\\'), right.replace('\\', '\\\\')),
                     (left.replace('\\', '/'), right.replace('\\', '/')))

    def translate(text):
        for old, new in substitutions:
            text = text.replace(old, new)
        return text

    differences = []

    def walk(a, b, path):
        need(type(a) is type(b), f'metadata type differs: {path}')
        if type(a) is dict:
            keys = {translate(k): k for k in a}
            need(len(keys) == len(a) and list(keys) == list(b), f'metadata structure differs: {path}')
            for key, old in keys.items():
                walk(a[old], b[key], path+'/'+key.replace('~', '~0').replace('/', '~1'))
        elif type(a) is list:
            need(len(a) == len(b), f'metadata list length differs: {path}')
            for k, (x, y) in enumerate(zip(a, b, strict=True)):
                walk(x, y, f'{path}/{k}')
        elif a != b:
            if type(a) is str and re.fullmatch('[a-f0-9]{64}', a) and re.fullmatch('[a-f0-9]{64}', b):
                kind = 'digest; owner approval required'
            elif type(a) is str and translate(a) == b:
                kind = 'layout-root translation'
            else:
                raise Refusal(f'metadata NUMERIC/OTHER difference: {path}')
            differences.append(dict(path=path, before=a, after=b, classification=kind))

    walk(before, after, '')
    return differences


def result(ck, archive, exit_code, input_manifest):
    ck, archive = ck.resolve(), archive.resolve()
    need(type(exit_code) is int and exit_code == 0, 'actual wrapper/queue exit was not zero')
    need(archive.parent == ck and archive.name != 'q25.log', 'archive must be a sibling of q25.log')
    need(digest(archive) == OLD_LOG_SHA, 'historical q25 waiter log not preserved exactly')
    source_pins(ck)
    observed = verify_input_manifest(input_manifest)
    summary = load(ck/'ab3'/'summary.json')
    need(type(summary) is dict, 'summary is not an object')
    arms = summary.get('arms')
    metrics = arms_check(ck, arms)
    checks = (ck/'ab3'/'check-arms.txt').read_text(encoding='utf8').splitlines()
    need(checks and checks[-1] == 'ARMS PASS' and 'ARMS FAIL' not in '\n'.join(checks), 'actual arms checker did not PASS')
    comparison = (ck/'ab3'/'compare-h2-h3.txt').read_text(encoding='utf8').splitlines()
    need(comparison and comparison[-1] == 'D-b PASS' and not any(
         token in '\n'.join(comparison) for token in ('D-b FAIL', 'NUMERIC/OTHER', 'DIFFERS', 'EMPTY ARRAY')),
         'actual proof comparator did not pass exact D-b')
    arrays = proof_captures(ck, arms)
    differences = metadata_diffs(ck)
    route = load(ck/'ab3'/'h3-route.json')
    need(type(route) is dict and type(route.get('kernel')) is str and
         Path(route['kernel']).resolve() == (ck/'l3r3'/'helpers'/'private_heat_certification_kernel_r1.py').resolve(),
         'route record kernel path differs')
    h3 = route.get('h3')
    need(type(h3) is dict and h3.get('route') == 'compiled' and h3.get('pinned_sha256') == HELPER_SHA,
         'H3 route is not compiled with the accepted helper pin')
    build = h3.get('build')
    need(type(build) is dict and build.get('module_sha256') == HELPER_SHA, 'compiled helper build identity differs')
    frozen = freezes(ck)
    need((ck/'ab3-cap').is_dir() and any((ck/'ab3-cap').iterdir()) and (ck/'ab3-w4').is_dir(),
         'worker capture/W4 evidence missing')
    need((ck/'ab3-capture.log').is_file(), 'capture log missing')
    log = (ck/'q25.log').read_text(encoding='utf8')
    need(re.search(r'^\d{2}:\d{2}:\d{2} capture exit 0, files [1-9]\d*$', log, re.MULTILINE) is not None,
         'capture success absent from launch log')
    need(re.search(r'^\d{2}:\d{2}:\d{2} end exit 0$', log, re.MULTILINE) is not None, 'wrapper final success absent')
    paths = sorted(ck.glob('ab3*'))+[ck/'q25.log', archive]
    return dict(status='Q25 EVIDENCE CHECKS PASS', proof_arms=[0, 1], arrays=arrays, frozen=frozen,
                readiness_inputs=observed,
                metadata_differences=differences,
                identity_disposition='owner must bind every identity difference to approved kernel/resources/helper graph',
                route_scope='separate fresh process; not a route record for each proof worker', arms=metrics,
                timing=dict(metric='arm_wall_seconds', h2_arm=3, h3_arm=2,
                            h2_seconds=metrics[3]['arm_wall_seconds'], h3_seconds=metrics[2]['arm_wall_seconds'],
                            h2_over_h3=metrics[3]['arm_wall_seconds']/metrics[2]['arm_wall_seconds'],
                            scope='one unmirrored time sample per side, imports/compilation included; component only'),
                resource_scope='sampled tree/parent/worker working sets, 2 GiB booking is not a strict guard',
                disk=byte_scope(paths), disposition='root decides timing/resource acceptance and enablement; C14 separate')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'result'))
    parser.add_argument('--ck', required=True, type=Path)
    parser.add_argument('--archive-log', required=True, type=Path)
    parser.add_argument('--h13l1', type=Path, default=Path('C:/Users/LOCAL_USER/h13l1'))
    parser.add_argument('--git-bash', type=Path, default=Path('C:/Program Files/Git/bin/bash.exe'))
    parser.add_argument('--git-cygpath', type=Path, default=Path('C:/Program Files/Git/usr/bin/cygpath.exe'))
    parser.add_argument('--exit-code', type=int)
    parser.add_argument('--input-manifest', type=Path, default=Path(__file__).with_name('q25_input_manifest_r1.json'))
    args = parser.parse_args()
    try:
        report = (preflight(args.ck, args.h13l1, args.archive_log, args.git_bash, args.git_cygpath, args.input_manifest)
                  if args.mode == 'preflight' else result(args.ck, args.archive_log, args.exit_code, args.input_manifest))
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        print(json.dumps(dict(status='REFUSED', reason=f'{type(error).__name__}: {error}')))
        return 1
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
