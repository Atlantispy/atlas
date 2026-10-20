"""Store-free reader seam for Plan11; integrated callers retain all native checks.

Only an independently rebuilt admission may cross this seam. Producer preflight
is deliberately a deferred callable. Neither this module nor the gate module
opens the catalog, pending view or sealed member. The actual reader continues
through its unchanged independent comparisons after this context yields.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
import stat
from pathlib import Path
import time

import reader_overlap_gate as G


SPEC_SCHEMA = 'atlas.reader-admission-wait.v1'
SPEC_FIELDS = frozenset(('schema', 'gate_path', 'attempt', 'stage', 'interval', 'profile_sha256',
                         'launcher', 'launcher_nonce', 'timeout_seconds', 'wait_basis'))


def read_json(path, *, limit=8 << 20, pin=None):
    """Bounded, complete, identity-stable JSON read with the repaired sharing retry."""
    path = Path(path)
    def complete():
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and not path.is_symlink() and
                not (getattr(before, 'st_file_attributes', 0) & 0x400), 'ordinary JSON record required')
        require(before.st_size <= limit, 'JSON record exceeds its bounded size')
        with path.open('rb') as stream:
            require(G._fingerprint(os.fstat(stream.fileno())) == G._fingerprint(before), 'JSON record replaced')
            raw = stream.read(limit+1)
            after = os.fstat(stream.fileno())
        require(len(raw) <= limit and len(raw) == after.st_size and
                G._fingerprint(before) == G._fingerprint(after) == G._fingerprint(path.lstat()),
                'JSON record changed during bounded read')
        digest = sha256(raw).hexdigest()
        require(pin is None or digest == pin, 'JSON record differs from its explicit pin')
        try:
            value = json.loads(raw, object_pairs_hook=G._pairs, parse_constant=G._nonfinite,
                               parse_float=G._finite_float)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise G.GateRefused('malformed bounded JSON record') from error
        require(type(value) is dict, 'JSON record must be an object')
        return value, digest
    return G._retry_sharing(complete, 'bounded JSON record')


def failure_reason(error):
    if isinstance(error, G.WaitFailure):
        return error.reason
    if type(error).__name__ == 'GuardAborted':
        return {'Independent guard: user_cancel': 'cancelled',
                'Independent guard: free_memory_floor': 'free_floor'}.get(str(error))
    return None


def validate_fallback_claim(path, *, pin, original, directory, receipt_limit=64 << 20,
                            alive=None, guardian_alive=None):
    """Authenticate one fixed coordinator claim and actual non-data failure/exit evidence.

    Missing or ambiguous failed-process evidence refuses; this never launches a
    fallback. The launcher separately authenticates the valid sealed producer.
    """
    G._digest(pin, 'fallback claim pin')
    original, directory, path = Path(original), Path(directory), Path(path)
    require(original.is_absolute() and str(original.resolve()) == str(original) and
            path == original/'sequential-fallback.claim.json' and
            directory == original.with_name(original.name+'-fallback'), 'fixed failed-reader claim and sibling required')
    claim, _ = read_json(path, limit=65536, pin=pin)
    fields = {'failed_attempt', 'reason', 'fresh_directory', 'coordinator_approval'}
    require(set(claim) == fields and claim['failed_attempt'] == str(original) and
            claim['fresh_directory'] == str(directory) and
            claim['reason'] in {'launcher_lost', 'wait_expired', 'cancelled', 'free_floor'} and
            type(claim['coordinator_approval']) is str and claim['coordinator_approval'].strip(),
            'closed specific coordinator fallback claim required')
    evidence = validate_failed_overlap(original, reason=claim['reason'], directory=directory,
        receipt_limit=receipt_limit, alive=alive, guardian_alive=guardian_alive)
    return {'claim': claim, 'claim_sha256': pin, **evidence}


def validate_failed_overlap(original, *, reason, directory, receipt_limit=64 << 20,
                            alive=None, guardian_alive=None):
    """The same failed-reader proof, available before the once-only claim is written."""
    original, directory = Path(original), Path(directory)
    require(original.is_absolute() and str(original.resolve()) == str(original) and
            directory == original.with_name(original.name+'-fallback') and
            reason in {'launcher_lost', 'wait_expired', 'cancelled', 'free_floor'},
            'fixed original overlap reader, sibling and eligible reason required')
    failed, failed_pin = read_json(original/'reopen.json', limit=receipt_limit)
    guard, guard_pin = read_json(original/'reopen.guard.json')
    control, _ = read_json(original/'reopen.guard-control.json')
    parent = G._identity(guard.get('parent'), 'failed reader')
    native_reason = guard.get('reason')
    require(failed.get('schema') == 'atlas.fresh-interval-reopen-result.v1' and
            failed.get('status') in {'FAILED', 'INTERRUPTED'} and failed.get('admitted_ahead') is True and
            failed.get('pid') == parent['pid'] and control.get('parent') == parent and
            guard.get('schema') == 'atlas.private.continuation-guard.r3' and
            type(guard.get('nonce')) is str and guard['nonce'] and control.get('nonce') == guard['nonce'] and
            guard.get('limits') == control.get('limits') == {'rss_bytes': 12 << 30, 'free_floor_bytes': 1 << 30} and
            guard.get('workload_exit_confirmed') is True and
            guard.get('cleanup') == {'remaining': [], 'action_errors': []},
            'failed overlap reader and confirmed empty-job guard evidence required')
    require(native_reason == {'cancelled': 'user_cancel', 'free_floor': 'free_memory_floor'}.get(reason) and
            guard.get('status') in ({'STOPPED'} if native_reason is None else
                                   {'PARENT_EXITED', 'HARD_STOPPED', 'COOPERATIVE_ABORT'}),
            'failed guard does not substantiate the approved non-data reason')
    errors = failed.get('errors')
    require(type(errors) is list and errors, 'actual failed reader errors required')
    def eligible(error):
        if type(error) is not dict:
            return False
        if error.get('type') in {'WaitFailure', 'GuardAborted'} and error.get('first_raised') != {
            'type': error.get('type'), 'message': error.get('message')
        }:
            return False  # A causal data/identity failure cannot be hidden by a later abort.
        if error.get('type') == 'WaitFailure':
            return reason in {'launcher_lost', 'wait_expired'} and str(error.get('message', '')).startswith(reason+':')
        if error.get('type') == 'GuardAborted':
            messages = {'Independent guard: '+str(native_reason)} | {
                'Independent guard closed with '+status+': '+str(native_reason)
                for status in ('PARENT_EXITED', 'HARD_STOPPED', 'COOPERATIVE_ABORT')}
            return native_reason is not None and error.get('message') in messages
        return (set(error) == {'source', 'failure'} and error['source'] == 'continuation_guard' and
                native_reason is not None and error['failure'] == 'Independent continuation guard: '+native_reason)
    require(all(eligible(error) for error in errors) and
            (failed.get('overlap_failure_reason') == reason or native_reason is not None),
            'gate/data/identity/unknown failures cannot become a sequential fallback')
    spec = failed.get('overlap_wait_spec')
    validate_spec(spec)
    require(Path(spec['gate_path']).parent.parent == original.parent and
            original.name == 'reader-'+spec['stage']+('' if spec['interval'] <= 1 else f"-{spec['interval']:04d}") and
            failed.get('profile_sha256') == spec['profile_sha256'] and failed.get('mode') == spec['stage'] and
            failed.get('review_only') is False and 'reader_fallback' not in failed and
            (failed.get('interval') == spec['interval'] if spec['interval'] >= 2 else 'interval' not in failed),
            'failed overlap wait specification differs from the original reader')
    alive = G.process_alive if alive is None else alive
    if guardian_alive is None:
        import psutil
        guardian_alive = psutil.pid_exists
    guardian = guard.get('guardian')
    require(type(guardian) is dict and type(guardian.get('pid')) is int and guardian['pid'] > 0,
            'failed guardian identity required')
    require(alive(parent) is False and guardian_alive(guardian['pid']) is False,
            'failed reader or guardian has not exited')
    return {'failed_receipt_sha256': failed_pin,
            'failed_guard_sha256': guard_pin, 'profile_sha256': failed.get('profile_sha256'),
            'stage': spec['stage'], 'interval': spec['interval']}


def require(condition, message):
    if not condition:
        raise G.GateRefused(message)


def gate_path(attempt, stage, number):
    return Path(attempt)/('overlap-'+stage+('' if number <= 1 else f'-{number:04d}'))/'GATE'


def encode_spec(spec):
    validate_spec(spec)
    return json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode_spec(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate wait-spec key')
            result[key] = value
        return result
    try:
        spec = json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(G.GateRefused('nonfinite wait spec')))
    except (TypeError, json.JSONDecodeError) as error:
        raise G.GateRefused('invalid wait specification') from error
    validate_spec(spec)
    return spec


def validate_spec(spec):
    require(type(spec) is dict and set(spec) == SPEC_FIELDS and spec['schema'] == SPEC_SCHEMA,
            'closed overlap wait specification required')
    require(type(spec['attempt']) is str and Path(spec['attempt']).is_absolute() and
            str(Path(spec['attempt']).resolve()) == spec['attempt'], 'canonical absolute attempt required')
    require(spec['stage'] in ('root', 'interval') and type(spec['interval']) is int and
            (spec['interval'] == 0 if spec['stage'] == 'root' else spec['interval'] >= 1),
            'wait specification stage/interval mismatch')
    require(type(spec['gate_path']) is str and
            spec['gate_path'] == str(gate_path(spec['attempt'], spec['stage'], spec['interval'])),
            'wait specification must use this attempt stage gate')
    require(type(spec['timeout_seconds']) in (int, float) and math.isfinite(spec['timeout_seconds']) and
            spec['timeout_seconds'] > 0 and type(spec['wait_basis']) is str and spec['wait_basis'].strip(),
            'bounded advance-sized wait with recorded basis required')
    # Reuse the complete gate validator for digest/process/nonce syntax. Unknown
    # producer pins are placeholders only for validating this store-free spec.
    identity = {'pid': 1, 'created_ticks': 1}
    expected = {name: spec[name] for name in ('attempt', 'stage', 'interval', 'profile_sha256',
                                             'launcher', 'launcher_nonce')}
    expected['waiter'] = identity
    value = dict(expected, schema=G.SCHEMA, producer_receipt_sha256='0'*64,
                 guard_receipt_sha256='0'*64, runner_sha256='0'*64, sealed_sha256='0'*64)
    G.validate_gate(value, expected)
    return spec


def expected_gate(spec, waiter):
    validate_spec(spec)
    return {**{name: spec[name] for name in ('attempt', 'stage', 'interval', 'profile_sha256',
                                            'launcher', 'launcher_nonce')}, 'waiter': waiter}


@contextmanager
def admitted_before_gate(*, admission, spec, record, save, guard, verify_sources,
                         producer_inputs, producer_pins, memory_admit, available_memory,
                         waiter=None, clock=time.monotonic, source_check_seconds=10.0):
    """Enter independent serial admission, wait, authenticate, re-admit memory.

    admission is the caller's FRESH.admission(... initial_workers=0) context,
    created from its own budget and fresh output. producer_inputs is the original
    store-free validator with only the receipt SHA supplied later. producer_pins
    obtains the actual referenced immutable bytes after that preflight; it must
    return all four pins. memory_admit uses the reader's own by-need prediction.
    """
    validate_spec(spec)
    require(type(source_check_seconds) in (int, float) and math.isfinite(source_check_seconds) and
            0 < source_check_seconds <= 10, 'bounded source-check cadence required')
    waiter = G.process_identity(os.getpid()) if waiter is None else waiter
    expected = expected_gate(spec, waiter)
    began = clock()
    record['overlap_wait_spec'] = dict(spec)
    record['admitted_ahead'] = True
    save()
    with admission as rebuilt:
        record['admission_seconds'] = clock()-began
        verify_sources()  # Forced after admission, before waiting on producer output.
        guard.phase('wait-for-producer-gate')
        wait_started = clock()
        next_check = clock()+source_check_seconds
        def waiting_sources():
            nonlocal next_check
            now = clock()
            if now >= next_check:
                verify_sources()
                next_check = now+source_check_seconds
        value = G.wait_gate(spec['gate_path'], expected, launcher=spec['launcher'],
                            timeout_seconds=spec['timeout_seconds'],
                            check=lambda: guard.check(force=True), verify_sources=waiting_sources)
        verify_sources()  # A complete forced fence before producer-dependent reads.
        record['gate_wait_seconds'] = clock()-wait_started
        binding = {'gate': value, 'gate_sha256': G.gate_sha256(value)}
        G.validate_receipt_binding(binding, expected)
        # This is the first producer-dependent call; keep its implementation and
        # validations unchanged. No producer values supplied the admission above.
        guard.phase('authenticate-producer-after-gate')
        producer = producer_inputs(value['producer_receipt_sha256'])
        pins = producer_pins(producer)
        fields = {'producer_receipt_sha256', 'guard_receipt_sha256', 'runner_sha256', 'sealed_sha256'}
        require(type(pins) is dict and set(pins) == fields and all(value[name] == pins[name] for name in fields),
                'gate producer/STOPPED guard/runner/sealed pins differ from authenticated records')
        require(producer.get('review') is False and producer.get('mode') == spec['stage'] and
                producer.get('interval') == spec['interval'], 'gate requires this ordinary completed producer')
        verify_sources()
        guard.check(force=True)
        admitted = memory_admit(available_memory())
        record.update(overlap_gate=binding, producer_receipt_sha256=value['producer_receipt_sha256'],
                      memory_before_open_pending=admitted)
        save()
        yield rebuilt, producer


def validate_finalise(record, *, expected, path, pin, producer_pins, waiter, memory_validator):
    """Required by overlap finalise even if the entire receipt binding is absent."""
    require(type(pin) is str and len(pin) == 64, 'explicit finalise gate pin required')
    gate = G.read_gate(path)
    # read_gate checks the complete canonical bytes and retries sharing violations.
    require(pin == G.gate_sha256(gate),
            'published gate bytes differ from finalise pin')
    fields = {'producer_receipt_sha256', 'guard_receipt_sha256', 'runner_sha256', 'sealed_sha256'}
    require(type(producer_pins) is dict and set(producer_pins) == fields,
            'complete closed producer/guard/runner/sealed pins required by finalise')
    expected = dict(expected, waiter=waiter, **producer_pins)
    binding = G.validate_receipt_binding(record.get('overlap_gate'), expected)
    require(binding['gate_sha256'] == pin and binding['gate'] == gate and record.get('admitted_ahead') is True and
            record.get('producer_receipt_sha256') == gate['producer_receipt_sha256'] and
            record.get('pid') == waiter['pid'], 'reader receipt is not bound to the exact published overlap gate')
    spec = record.get('overlap_wait_spec')
    validate_spec(spec)
    require(str(Path(path)) == spec['gate_path'], 'finalise gate path differs from the validated wait specification')
    require(expected_gate(spec, waiter) == {name: expected[name] for name in expected_gate(spec, waiter)},
            'reader wait specification differs from the published attempt')
    memory, start = record.get('memory_before_open_pending'), record.get('start_gate')
    for observation in (start, memory):
        require(type(observation) is dict and observation.get('schema') == 'atlas.private.start-gate.r1' and
                all(type(observation.get(name)) is int and observation[name] > 0 for name in
                    ('gate_bytes', 'predicted_peak_bytes', 'available_bytes')) and
                observation['available_bytes'] >= observation['gate_bytes'] and
                type(observation.get('hash_randomization')) is int and observation['hash_randomization'] == 0,
                'complete admitted by-need observations required at start and before pending-store access')
        # The selected existing SG.admit performs the authoritative prediction,
        # formula and seed validation. Do not introduce a second memory policy.
        require(callable(memory_validator), 'selected start-gate validator required')
        memory_validator(observation, observation['available_bytes'])
    require({k: v for k, v in start.items() if k != 'available_bytes'} ==
            {k: v for k, v in memory.items() if k != 'available_bytes'},
            'the repeated memory gate changed the reader prediction or basis')
    return binding
