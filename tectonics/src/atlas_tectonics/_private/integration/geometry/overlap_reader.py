"""Store-free reader seam for Plan11; integrated callers retain all native checks.

Before the gate the admission uses one producer value, its closed measurement store's
published record, at the point of use; the caller tests it against the authenticated
receipt after the gate. Producer preflight
is deliberately a deferred callable. Neither this module nor the gate module
opens the catalog, pending view or sealed member. The actual reader continues
through its unchanged independent comparisons after this context yields.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from atlas_tectonics._private.integration.geometry import reader_overlap_gate as G


SPEC_SCHEMA = 'atlas.reader-admission-wait.v1'


def read_json(path, *, limit=8 << 20, pin=None, canonical=None):
    """Bounded, complete, identity-stable JSON read with the repaired sharing retry."""
    path = Path(path)
    def complete():
        with path.open('rb') as stream:
            raw = stream.read(limit+1)
        digest = sha256(raw).hexdigest()
        try:
            value = json.loads(raw, object_pairs_hook=G._pairs, parse_constant=G._nonfinite,
                               parse_float=G._finite_float)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise G.GateRefused('malformed bounded JSON record') from error
        require(canonical is None or canonical(value) == raw, 'JSON record must be canonical')
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
            type(guard.get('limits')) is dict and guard['limits'] == control.get('limits') and
            guard.get('workload_exit_confirmed') is True and
            guard.get('cleanup') == {'remaining': [], 'action_errors': []},
            'failed overlap reader and confirmed empty-job guard evidence required')
    require(native_reason == {'cancelled': 'user_cancel', 'free_floor': 'free_memory_floor'}.get(reason) and
            guard.get('status') in ({'STOPPED'} if native_reason is None else
                                   {'PARENT_EXITED', 'HARD_STOPPED', 'COOPERATIVE_ABORT'}),
            'failed guard does not substantiate the approved non-data reason')
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
    spec = failed.get('overlap_wait_spec')
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
    return json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode_spec(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            result[key] = value
        return result
    try:
        spec = json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(G.GateRefused('nonfinite wait spec')))
    except (TypeError, json.JSONDecodeError) as error:
        raise G.GateRefused('invalid wait specification') from error
    return spec


def validate_spec(spec):
    # Reuse the complete gate validator for digest/process/nonce syntax. Unknown
    # producer pins are placeholders only for validating this store-free spec.
    identity = {'pid': 1, 'created_ticks': 1}
    expected = {name: spec[name] for name in ('attempt', 'stage', 'interval', 'profile_sha256',
                                             'launcher', 'launcher_nonce')}
    expected['waiter'] = identity
    return spec


def expected_gate(spec, waiter):
    return {**{name: spec[name] for name in ('attempt', 'stage', 'interval', 'profile_sha256',
                                            'launcher', 'launcher_nonce')}, 'waiter': waiter}


@contextmanager
def admitted_before_gate(*, admission, spec, record, save, guard,
                         producer_inputs, memory_admit, available_memory,
                         waiter=None, clock=time.monotonic):
    """Enter independent admission, wait, authenticate, re-admit memory.

    admission is the caller's FRESH.admission(... initial_workers=0) context,
    created from its own budget and fresh output. producer_inputs is the original
    store-free validator with only the receipt SHA supplied later. Its result
    carries the four checked file pins. memory_admit uses the reader's own by-need prediction.
    """
    waiter = G.process_identity(os.getpid()) if waiter is None else waiter
    expected = expected_gate(spec, waiter)
    began = clock()
    record['overlap_wait_spec'] = dict(spec)
    record['admitted_ahead'] = True
    save()
    with admission as rebuilt:
        record['admission_seconds'] = clock()-began
        guard.phase('wait-for-producer-gate')
        wait_started = clock()
        value = G.wait_gate(spec['gate_path'], expected, launcher=spec['launcher'],
                            timeout_seconds=spec['timeout_seconds'],
                            check=lambda: guard.check(force=True))
        record['gate_wait_seconds'] = clock()-wait_started
        binding = {'gate': value, 'gate_sha256': G.gate_sha256(value)}
        # The caller tests the earlier measurement-store publication against this receipt.
        guard.phase('authenticate-producer-after-gate')
        producer = producer_inputs(value['producer_receipt_sha256'])
        guard.check(force=True)
        admitted = memory_admit(available_memory())
        record.update(overlap_gate=binding, producer_receipt_sha256=value['producer_receipt_sha256'],
                      memory_before_open_pending=admitted)
        save()
        yield rebuilt, producer


def validate_finalise(record, *, expected, path, pin, producer_pins, waiter, memory_validator):
    """Required by overlap finalise even if the entire receipt binding is absent."""
    gate = G.read_gate(path)
    expected = {'launcher': gate['launcher'], 'launcher_nonce': gate['launcher_nonce'],
                **expected, 'waiter': waiter, **producer_pins}
    binding = G.validate_receipt_binding(record.get('overlap_gate'), expected)
    spec = record.get('overlap_wait_spec')
    waited_for = expected_gate(spec, waiter)
    require(waited_for == {name: expected[name] for name in waited_for},
            'reader wait specification differs from the published attempt')
    memory, start = record.get('memory_before_open_pending'), record.get('start_gate')
    for observation in (start, memory):
        require(type(observation) is dict and observation.get('schema') == 'atlas.private.start-gate.r1' and
                all(type(observation.get(name)) is int and observation[name] > 0 for name in
                    ('gate_bytes', 'predicted_peak_bytes', 'available_bytes')) and
                observation['available_bytes'] >= observation['gate_bytes'] and
                type(observation.get('hash_randomization')) is int and observation['hash_randomization'] == 0,
                'complete admitted by-need observations required at start and before pending-store access')
        memory_validator(observation, observation['available_bytes'])
    return binding
