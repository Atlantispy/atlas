"""Write an exclusive, strict and bounded capture map from LF's retained step evidence.

No capture is produced here. Each included launch/capture pair must match the stage's own
digests, explicit arm/stage/step/attempt/output bindings and the requested profile identity.
Missing successful captures are listed as skipped; malformed or contradictory evidence refuses.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from types import ModuleType

COMPARATOR_SHA256 = '5f6d97aa222d7a06d12bf87a49d3c5a59a4d271301bb16dc887530e25d3c62cf'
_comparator = Path(__file__).resolve().with_name('compare_arms_r21.py')
_raw = _comparator.read_bytes()
if sha256(_raw).hexdigest() != COMPARATOR_SHA256:
    raise RuntimeError('selected comparator bytes differ')
C = ModuleType('_n9_capture_comparator')
C.__file__ = str(_comparator)
sys.modules[C.__name__] = C
exec(compile(_raw, str(_comparator), 'exec'), C.__dict__)


def entries(attempt, arm, profile_sha256):
    C.prove(arm in ('before', 'after') and type(profile_sha256) is str and
            C.HEX64.fullmatch(profile_sha256), 'map arm/profile digest malformed')
    attempt = Path(attempt).resolve()
    found, skipped = [], []
    for stage, interval in C.STAGES:
        path = attempt/('stage-'+stage+'.json')
        if not path.exists():
            skipped.append(stage+': no stage record')
            continue
        record, _, _ = C.pinned(path, stage+' capture map stage')
        profile, steps = record.get('profile'), record.get('steps')
        C.prove(record.get('schema') == C.STAGE_SCHEMA and record.get('stage') == stage and
                type(record.get('interval')) is int and record['interval'] == interval and
                type(profile) is dict and profile.get('sha256') == profile_sha256 and
                type(steps) is list and all(type(row) is dict for row in steps),
                stage+': stage profile/identity/steps malformed')
        seen = set()
        for row in steps:
            step = row.get('name')
            C.prove(type(step) is str and step not in seen, stage+': malformed or repeated step')
            seen.add(step)
            if step not in C.STEP_RECORDS:
                continue
            evidence = row.get('capture')
            if evidence is None or (type(evidence) is dict and evidence.get('ok') is False):
                skipped.append(stage+'/'+step+': no successful launching-parent capture')
                continue
            C.prove(type(evidence) is dict and evidence.get('ok') is True,
                    stage+'/'+step+': capture success evidence malformed')
            p = C.step_paths(attempt, stage, step)
            launch, launch_sha, _ = C.pinned(p['launch'], stage+'/'+step+' launch')
            capture, capture_sha, _ = C.pinned(p['capture'], stage+'/'+step+' capture')
            entry = {'stage': stage, 'interval': interval, 'step': step,
                     'launch': {'path': str(p['launch']), 'sha256': launch_sha},
                     'capture': {'path': str(p['capture']), 'sha256': capture_sha}}
            C.prove(row.get('launch_sha256') == launch_sha and evidence.get('sha256') == capture_sha,
                    stage+'/'+step+': launch/capture differs from stage digests')
            C.prove(set(launch) == C.LAUNCH_KEYS and launch.get('schema') == C.STEP_LAUNCH_SCHEMA and
                    set(capture) == C.CAPTURE_KEYS and capture.get('schema') == C.STEP_CAPTURE_SCHEMA and
                    capture.get('capture_mode') == 'launching-parent' and
                    capture.get('launch_record_sha256') == launch_sha and
                    capture.get('writer') == launch.get('writer'),
                    stage+'/'+step+': launch/capture identity malformed')
            binding, launch_profile = launch.get('binding'), launch.get('profile')
            C.prove(type(binding) is dict and set(binding) == C.BINDING_KEYS and
                    capture.get('binding') == binding and binding['arm'] == arm and
                    binding['stage'] == stage and type(binding['interval']) is int and
                    binding['interval'] == interval and binding['step'] == step and
                    type(binding['attempt']) is str and C.same_path(binding['attempt'], attempt) and
                    type(binding['output']) is str and C.same_path(binding['output'], p['out']) and
                    type(launch_profile) is dict and launch_profile.get('sha256') == profile_sha256,
                    stage+'/'+step+': records do not bind the requested arm/profile/stage/step/attempt')
            found.append(entry)
    return found, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', choices=('before', 'after'), required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    attempt = args.attempt.resolve()
    try:
        found, skipped = entries(attempt, args.arm, args.profile_sha256)
        value = {'schema': C.CAPTURES_MAP_SCHEMA, 'arm': args.arm, 'profile_sha256': args.profile_sha256,
                 'attempt': str(attempt), 'entries': found}
        raw = (json.dumps(value, indent=1, sort_keys=True, allow_nan=False)+'\n').encode()
        C.prove(len(raw) <= C.MAX_PROOF_BYTES, 'capture map exceeds byte cap')
        with args.output.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except (C.ProofError, OSError, ValueError) as error:
        print('capture map refused: '+str(error), file=sys.stderr)
        return 1
    print(json.dumps({'map': str(args.output), 'sha256': sha256(raw).hexdigest(),
                      'entries': len(found), 'skipped': skipped}, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
