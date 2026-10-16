"""Explicit reviewed, source-bound compatibility for a state-only transfer.

A policy is an owner-reviewed build artifact, pinned by its enclosing launcher;
it is not generated from a passing status or from matching parameter names.
This module checks the entire enumerated code delta, evidence files, actual
executing source and closed scientific plan graph before issuing a capability.
Historical acceptance remains historical. Numerical proof caches NEVER cross
the runtime boundary through this policy. This is a provenance check, not a
sandbox against arbitrary Python code in the same process.
"""
from hashlib import sha256
import json
from pathlib import Path
import stat
import sys

import native_transfer as N
from workflow_transfer import HistoricalEndpointAdmission, RuntimeCompatibilityAdmission


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
MAX_POLICY_BYTES = 8 << 20


class RuntimeCompatibilityRefused(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise RuntimeCompatibilityRefused(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    _require(type(value) is str and len(value) == 64 and
             all(c in '0123456789abcdef' for c in value), 'explicit SHA-256 required')
    return value


def regular(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        _require(not stat.S_ISLNK(info.st_mode) and
                 not getattr(info, 'st_file_attributes', 0) & 0x400,
                 'linked/reparse compatibility operand refused')
    _require(path.is_file(), 'regular compatibility operand required')
    return path


def file_hash(path):
    value = sha256()
    with regular(path).open('rb') as stream:
        while block := stream.read(65536):
            value.update(block)
    return value.hexdigest()


def _path(root, relative):
    _require(type(relative) is str and bool(relative) and '\\' not in relative,
             'canonical relative path required')
    path = Path(relative)
    _require(not path.is_absolute() and '..' not in path.parts,
             'compatibility path escapes reviewed root')
    result = Path(root)/path
    _require(result.resolve().is_relative_to(Path(root).resolve()), 'compatibility path escaped')
    return regular(result)


def source_inventory(root):
    root = Path(root)
    package = root/'atlas_tectonics'
    _require(package.is_dir(), 'actual native package root required')
    paths = sorted(package.rglob('*.py'))
    _require(bool(paths), 'empty source inventory refused')
    return {path.relative_to(root).as_posix(): file_hash(path) for path in paths}


def check_policy(policy, *, historical, current):
    """Pure review-coverage check, never an admission or source observation."""
    _require(type(policy) is dict and set(policy) == {
        'schema', 'constraints', 'historical', 'current', 'reviewed_changes', 'evidence'},
        'closed runtime compatibility policy required')
    _require(policy['schema'] == SCHEMA and policy['constraints'] == CONSTRAINTS,
             'unsupported or weakened compatibility contract')
    for name, actual in (('historical', historical), ('current', current)):
        row = policy[name]
        _require(type(row) is dict and set(row) == {
            'source_hashes', 'native_source_digest', 'source_manifest_path', 'source_manifest_sha256',
            'execution_identity'},
            'complete reviewed source side required')
        _require(type(actual) is dict and actual and row['source_hashes'] == actual,
                 name+' source membership or bytes differ')
        for pin in actual.values():
            _digest(pin)
        _require(_digest(row['native_source_digest']) == sha256(canonical(actual)).hexdigest(),
                 name+' source digest differs')
        _digest(row['source_manifest_sha256'])
        _digest(row['execution_identity'])
    expected = {name: {'before': historical.get(name), 'after': current.get(name)}
                for name in set(historical)|set(current) if historical.get(name) != current.get(name)}
    changes = policy['reviewed_changes']
    _require(type(changes) is dict and set(changes) == set(expected),
             'every changed, added or removed source needs explicit review coverage')
    for name, pair in expected.items():
        row = changes[name]
        _require(type(row) is dict and set(row) == {'before', 'after', 'reason', 'evidence'},
                 'closed reviewed-change record required')
        _require(all(row[key] == value for key, value in pair.items()),
                 'reviewed delta does not match exact source bytes')
        _require(type(row['reason']) is str and bool(row['reason'].strip()) and
                 type(row['evidence']) is list and bool(row['evidence']), 'review rationale/evidence missing')
    evidence = policy['evidence']
    _require(type(evidence) is dict and bool(evidence), 'review evidence required')
    for path, pin in evidence.items():
        _require(type(path) is str and path, 'named evidence required')
        _digest(pin)
    _require(all(name in evidence for row in changes.values() for name in row['evidence']),
             'review cites an unbound evidence artifact')


def admit(*, policy_path, policy_sha256, evidence_root, historical_source_root,
          current_source_root, historical_admission, native_transfer, execution, budget):
    """Issue only for the pinned reviewed policy and actual current execution.

    The enclosing frozen launcher must pin policy_sha256 and this module. Passing
    a newly authored policy is NOT authorisation to call this from production.
    No world store is read and no numerical/equation check is waived here.
    """
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext
    _require(type(historical_admission) is HistoricalEndpointAdmission and
             type(native_transfer) is N.OwnedMigratedNativeCollar and
             type(execution) is ExecutionContext and type(budget) is WorkBudget,
             'actual historical admission, state transfer, execution and budget required')
    policy_path = regular(policy_path)
    size = policy_path.stat().st_size
    _require(size <= MAX_POLICY_BYTES, 'oversized compatibility policy refused')
    scratch = N._Allocation(budget, 65536+16*(size+len(native_transfer._record)+
                            len(historical_admission._record)), category='runtime-compatibility-scratch')
    raw = policy_path.read_bytes()
    _require(sha256(raw).hexdigest() == _digest(policy_sha256), 'review policy bytes changed')
    policy = json.loads(raw)
    execution.verify_boundary()
    loaded = sys.modules['atlas_tectonics']
    _require(Path(loaded.__file__).resolve().parent ==
             (Path(current_source_root)/'atlas_tectonics').resolve(), 'current runtime is not actually loaded')
    old_inventory, new_inventory = source_inventory(historical_source_root), source_inventory(current_source_root)
    check_policy(policy, historical=old_inventory, current=new_inventory)
    for side in ('historical', 'current'):
        row = policy[side]
        _require(file_hash(_path(evidence_root, row['source_manifest_path'])) == row['source_manifest_sha256'],
                 side+' source manifest changed')
    for path, pin in policy['evidence'].items():
        _require(file_hash(_path(evidence_root, path)) == pin, 'review evidence changed: '+path)
    capsule, transfer = historical_admission.record(), native_transfer.record()
    binding = historical_admission.binding()
    _require(binding['capsule_sha256'] == sha256(canonical(capsule)).hexdigest(), 'historical admission changed')
    comparison = N.compare_scientific_contract(transfer['input']['historical_plan_graph'],
                                              transfer['input']['current_plan_graph'])
    producer = capsule['producer']
    historical_execution = transfer['input']['historical_plan_graph']['native']['definition']['execution']
    current_execution = transfer['input']['current_plan_graph']['native']['definition']['execution']
    _require(producer['execution_identity'] == historical_execution == policy['historical']['execution_identity'] and
             producer['native_source_digest'] == policy['historical']['native_source_digest'] and
             producer['source_manifest_sha256'] == policy['historical']['source_manifest_sha256'],
             'review policy is not for this authenticated historical producer')
    _require(current_execution == policy['current']['execution_identity'] and
             execution.provenance == {'execution_identity': current_execution, 'execution_mode': 'strict'},
             'actual strict current execution differs from transferred plans')
    _require(comparison == transfer['input']['compatibility'], 'closed scientific contract differs')
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
    # Full checks bracket admission; timestamps and a successful first read are
    # insufficient to cover a source/evidence edit during inspection.
    execution.verify_boundary()
    _require(source_inventory(historical_source_root) == old_inventory and
             source_inventory(current_source_root) == new_inventory,
             'runtime source changed during compatibility admission')
    _require(file_hash(policy_path) == policy_sha256, 'policy changed during admission')
    for side in ('historical', 'current'):
        row = policy[side]
        _require(file_hash(_path(evidence_root, row['source_manifest_path'])) == row['source_manifest_sha256'],
                 side+' manifest changed during admission')
    for path, pin in policy['evidence'].items():
        _require(file_hash(_path(evidence_root, path)) == pin, 'evidence changed during admission: '+path)
    assert scratch.size > 0
    return result
