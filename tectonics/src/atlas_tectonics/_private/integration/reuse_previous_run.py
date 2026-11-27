"""Reuse-previous-run, reader form (designs/reuse-previous-run-r1.md section 3, errata 1).

A fixed reader reads the previous run's sealed interval when the two profiles name the same workspace, inputs
and query store and the earlier run's stored execution identity equals this run's; otherwise the reader
recomputes. The record is never adoptable. NOT SCIENTIFICALLY PERMISSIBLE.
"""
from atlas_tectonics._private.integration import run_fresh_interval as F

require = F.require
STATUS = 'DIAGNOSTIC_REUSE_PREVIOUS_RUN_NOT_ADOPTABLE'
DIAGNOSTIC = F.DIAGNOSTIC
BRAND = 'NOT SCIENTIFICALLY PERMISSIBLE'
MISS_STATUS = 'REUSE_MISS_RECOMPUTE'   # a difference is a miss, never a refusal (Michael 04:12, 27 Nov)
REUSE_MISS_EXIT = 76                   # 75 is the chain's pause (iv1_chain.PAUSED_EXIT), 1 a failure


def _case_files(workspace, native_root):
    from hashlib import sha256
    from pathlib import Path
    cases = Path(workspace)/native_root/'atlas_tectonics'/'_fixtures'/'cases'
    return {p.name: sha256(p.read_bytes()).hexdigest() for p in cases.iterdir() if p.is_file()}


def plan(profile, sources, path, pin, override=False, *, previous=None):
    require(type(override) is bool, 'explicit identity-override flag required')
    previous = F.FreshProfile.read(path, pin) if previous is None else previous
    require(previous.sha256 == pin, 'preselected previous profile differs from its pin')
    row, old = profile.record(), previous.record()
    require(previous.sha256 != profile.sha256 and old['workspace'] == row['workspace'] and
            old['historical_inputs'] == row['historical_inputs'],
            'a previous run of this workspace and inputs required')
    require(all(r['qualification_status'] == DIAGNOSTIC for r in (row, old)),
            'reuse-previous-run is for diagnostic trees only')
    require(row[F.QUERY_STORE_FLAG] == old[F.QUERY_STORE_FLAG], 'the two runs differ in query store')
    miss = None
    if old['native_root'] != row['native_root']:   # control case files are read unpinned (addendum 2, G1)
        new_cases, old_cases = (_case_files(row['workspace'], r['native_root']) for r in (row, old))
        changed = sorted(n for n in new_cases.keys() | old_cases.keys() if new_cases.get(n) != old_cases.get(n))
        if changed:
            miss = 'control case files differ: ' + ', '.join(changed)
    from atlas_tectonics.integration.reuse import execution_identity
    identity = execution_identity('scipy')   # compared with the earlier receipt's runtime_identity (reopen_fresh_restart.producer_inputs)
    return {'previous': previous, 'execution_identity': identity,
            'record': {'previous_profile_sha256': previous.sha256, 'execution_identity': identity,
                       'adoptable': False, 'brand': BRAND, 'identity_override': override, 'miss': miss}}


def identity_miss(reuse, stored):
    """The previous run's stored execution identity against this run's: a miss unless overridden."""
    if reuse['record']['identity_override'] or (
            type(stored) is dict and stored.get('runtime_identity') == reuse['execution_identity']):
        return None
    return 'previous run has another execution identity'


def miss_exit(reuse):
    """Print the miss as one JSON line and give its exit code. Nothing is written at the reader's paths, so the
    ordinary reader that follows the recomputed producer finds them free (review C-1)."""
    import json
    reason = reuse['record']['miss']
    print(json.dumps({'status': MISS_STATUS, 'message': f"reuse miss: {reason}; this run's producer must run (recompute)",
                      'reuse_previous_run': reuse['record'], 'errors': []}), flush=True)
    return REUSE_MISS_EXIT
