"""Explicit reviewed, source-bound compatibility for a state-only transfer.

A policy is an owner-reviewed build artifact, pinned by its enclosing launcher;
it is not generated from a passing status or from matching parameter names.
This module checks the historical source tree against the policy, the stored evidence files, the historical
producer and the closed scientific plan graph before issuing a capability; the running code is not hashed (1809).
Historical acceptance remains historical. Numerical proof caches NEVER cross
the runtime boundary through this policy. This is a provenance check, not a
sandbox against arbitrary Python code in the same process.
"""
from hashlib import sha256
import json
from pathlib import Path

from atlas_shared.errors import AtlasError
from atlas_tectonics._private.integration import native_transfer as N
from atlas_tectonics._private.integration.workflow_transfer import RuntimeCompatibilityAdmission


SCHEMA = 'atlas.reviewed-runtime-state-transfer.v1'
CONSTRAINTS = {
    'transfer': 'unchanged accepted physical state only',
    'history': 'retain original producer and complete historical acceptance',
    'funding': 'no reset and no additional debit',
    'physics': 'identical closed scientific plan graph',
    'numeric_acceptance': 'existing approved accuracy limits unchanged',
    'cached_proofs': 'not reusable across runtime identities',
    'new_intervals': 'actual current runtime validation required',
}


class RuntimeCompatibilityRefused(ValueError, AtlasError):
    pass


def _require(condition, message):
    if not condition:
        raise RuntimeCompatibilityRefused(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return value


def regular(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        item.lstat()
    return path


def file_hash(path):
    value = sha256()
    with regular(path).open('rb') as stream:
        while block := stream.read(65536):
            value.update(block)
    return value.hexdigest()


def _path(root, relative):
    path = Path(relative)
    result = Path(root)/path
    return regular(result)


def source_inventory(root):
    root = Path(root)
    package = root/'atlas_tectonics'
    paths = sorted(package.rglob('*.py'))
    return {path.relative_to(root).as_posix(): file_hash(path) for path in paths}


def check_policy(policy, *, historical):
    """Pure review-coverage check, never an admission or source observation."""
    for name in ('historical', 'current'):
        row = policy[name]
        row['source_manifest_sha256']
        row['execution_identity']
    row = policy['historical']
    _require(type(historical) is dict and historical and row['source_hashes'] == historical,
             'historical source membership or bytes differ')
    _require(row['native_source_digest'] == sha256(canonical(historical)).hexdigest(),
             'historical source digest differs')
    changes = policy['reviewed_changes']
    _require(type(changes) is dict, 'closed reviewed-change records required')
    for name, row in changes.items():
        _require(row['before'] == historical.get(name), 'reviewed delta does not match historical source bytes')
    policy['evidence']


def admit(*, policy_path, policy_sha256, evidence_root, historical_source_root,
          historical_admission, native_transfer, execution, budget):
    """Issue only for the pinned reviewed policy and actual current execution.

    The enclosing frozen launcher must pin policy_sha256 and this module. Passing
    a newly authored policy is NOT authorisation to call this from production.
    No world store is read and no numerical/equation check is waived here.
    """
    policy_path = regular(policy_path)
    size = policy_path.stat().st_size
    scratch = N._Allocation(budget, 65536+16*(size+len(native_transfer._record)+
                            len(historical_admission._record)), category='runtime-compatibility-scratch')
    raw = policy_path.read_bytes()
    policy = json.loads(raw)
    check_policy(policy, historical=source_inventory(historical_source_root))
    for side in ('historical', 'current'):
        row = policy[side]
    capsule, transfer = historical_admission.record(), native_transfer.record()
    comparison = N.compare_scientific_contract(transfer['input']['historical_plan_graph'],
                                              transfer['input']['current_plan_graph'])
    producer = capsule['producer']
    historical_execution = transfer['input']['historical_plan_graph']['native']['definition']['execution']
    current_execution = transfer['input']['current_plan_graph']['native']['definition']['execution']
    _require(producer['execution_identity'] == historical_execution == policy['historical']['execution_identity'] and
             producer['native_source_digest'] == policy['historical']['native_source_digest'] and
             producer['source_manifest_sha256'] == policy['historical']['source_manifest_sha256'],
             'review policy is not for this authenticated historical producer')
    row = dict(schema='atlas.restart-runtime-compatibility.v1',
        historical_execution_identity=historical_execution, current_execution_identity=current_execution,
        scientific_contract_id=comparison['scientific_contract_id'],
        historical_source_manifest_sha256=policy['historical']['source_manifest_sha256'],
        current_source_manifest_sha256=policy['current']['source_manifest_sha256'],
        validation_evidence=dict(policy_sha256=policy_sha256, artifacts=policy['evidence']),
        scope=CONSTRAINTS, historical_acceptance_reissued=False)
    encoded = canonical(row)
    allocation = N._Allocation(budget, len(encoded)+4096, category='runtime-compatibility-retained')
    result = object.__new__(RuntimeCompatibilityAdmission)
    object.__setattr__(result, '_record', N._RecordBytes(encoded, allocation))
    del scratch
    return result
