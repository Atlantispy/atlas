"""Add passive CPU/private/OS-peak summaries to the unchanged job guard policy.

Outputs belong in a new source-bound directory. This changes no guard interval,
RAM/free-floor/timeout decision, process ownership, cancellation or cleanup.
The existing diagnostic helper reads the same exact member handles and returns
the original RSS fields plus explicitly labelled sampled resource statistics.

Diagnostics stay passive. A summary invariant/serialisation failure records a
bounded resource_summary_error once and disables only the summary; every limit,
trigger, sample, save, cleanup and exit decision is the original guard's. The
membership sample itself still feeds the unchanged RSS/free-floor triggers, so
its OSError contract is exactly the original job.sample contract.
"""
from hashlib import sha256

GUARD_PIN = '2d23f4bbc3b31b5aad3d68ef6e9b1a9800042fc75b12475b51dff468492ad796'  # original r3 input
JOB_PIN = '56f66b8826b148a31b85d490c75766422eb210fdfb35c665c449d2e73788f0b4'
DIAGNOSTICS_PIN = 'c0430517414e7b8aa2bc3a7a9e82143be8351bd0a03f3fd08daa993b64e5ee72'
SUCCESSOR_PIN = '9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772'  # reviewed output
GUARD_NAME = 'private_heat_continuation_guard_r3.py'
JOB_NAME = 'windows_workload_job.py'
DIAGNOSTICS_NAME = 'private_heat_resource_diagnostics_r1.py'


def _replace(source, before, after):
    if source.count(before) != 1:
        raise ValueError('resource guardian seam missing or ambiguous')
    return source.replace(before, after, 1)


def transform(raw):
    if type(raw) is not bytes or sha256(raw).hexdigest() != GUARD_PIN:
        raise ValueError('exact original guardian source required')
    source = raw.decode()
    source = _replace(source, 'import psutil\n',
        'import psutil\nimport private_heat_resource_diagnostics_r1 as RESOURCE_DIAGNOSTICS\n')
    source = _replace(source, '    startup_handles = []\n',
        '    startup_handles = []\n    resource_summary = RESOURCE_DIAGNOSTICS.ResourceSummary()\n')
    source = _replace(source, '            sample = job.sample(None if parent is None else parent.pid)\n',
        '            sample = RESOURCE_DIAGNOSTICS.sample_job(job,\n'
        "                None if parent is None else parent.pid, receipt.get('launch_cohort'))\n")
    # The snapshot must also serialise under the receipt writer's allow_nan=False,
    # otherwise a later save() could still turn a diagnostic value into an abort.
    source = _replace(source, "            receipt['latest_sample'] = sample\n",
        '            if resource_summary is not None:\n'
        '                # Passive: a diagnostic failure disables only this summary.\n'
        '                try:\n'
        "                    resource_summary.observe(sample, str(receipt['phase']), tick-started)\n"
        '                    resource_snapshot = resource_summary.snapshot()\n'
        '                    json.dumps(resource_snapshot, allow_nan=False)\n'
        "                    receipt['resource_summary'] = resource_snapshot\n"
        '                except Exception as diagnostic_error:\n'
        '                    resource_summary = None\n'
        "                    receipt['resource_summary_error'] = repr(diagnostic_error)[:1024]\n"
        "            receipt['latest_sample'] = sample\n")
    source = _replace(source, '        return receipt\n\n    def check(self, force=False):\n',
        "        if 'resource_summary' in receipt:\n"
        "            self.record['resource_summary'] = receipt['resource_summary']\n"
        "        if 'resource_summary_error' in receipt:\n"
        "            self.record['resource_summary_error'] = receipt['resource_summary_error']\n"
        '        return receipt\n\n    def check(self, force=False):\n')
    compile(source, 'private_heat_continuation_guard_r3.py[resource-summary-successor]', 'exec')
    result = source.encode()
    if sha256(result).hexdigest() != SUCCESSOR_PIN:
        raise ValueError('successor guardian bytes differ from the reviewed successor')
    return result


def successor_files(guard, job, diagnostics):
    """The exact one-directory successor set; pure, writes nothing.

    The supervisor runs the guard file as a script, so its plain-name imports
    resolve only from that directory: write all three files together.
    """
    for raw, pin, name in ((job, JOB_PIN, JOB_NAME), (diagnostics, DIAGNOSTICS_PIN, DIAGNOSTICS_NAME)):
        if type(raw) is not bytes or sha256(raw).hexdigest() != pin:
            raise ValueError('exact pinned guardian dependency required: '+name)
    return {GUARD_NAME: transform(guard), JOB_NAME: job, DIAGNOSTICS_NAME: diagnostics}
