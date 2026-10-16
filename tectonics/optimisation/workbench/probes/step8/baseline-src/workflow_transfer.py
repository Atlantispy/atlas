"""Nonzero workflow-root contract and same-store publication fence.

The root-only reader below adopts actual typed transfers and restores their
nonzero workflow position. Historical scientific validation belongs to the
original reader. Two nonconstructible admission types require separately
reviewed adapters: authenticated historical endpoint and explicit runtime
science compatibility. Matching six plan definitions alone cannot grant either.

Publication adds one immutable root through the existing transaction fence;
no reset, initial_state call or funding debit occurs here. The
exact source generator keeps ordinary create/open unchanged and uses the
existing current-runtime validators for successors after the migrated base.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path


BASE_SOURCE_SHA256 = 'ddb8d1b20aab4898e8b3a3ed3a0242b4bec538b5f902beea8b32778ed27b007a'
WORKFLOW_SCHEMA = 'atlas.funded-collar-workflow.v2'
DESCRIPTOR_SCHEMA = 'atlas.migrated-workflow-root-proposal.v1'
MAX_INTERVALS = 256
MAX_METADATA_BYTES = 8 << 20


class WorkflowTransferRefused(ValueError):
    pass


class HistoricalEndpointAdmission:
    """Reserved for the reviewed original-reader export IMPORT adapter.

    No issuer is implemented here. Export JSON, receipt status and caller hashes
    are insufficient. The eventual issuer authenticates source/context pins,
    full successful original validation receipt and complete snapshot inventory.
    _record is immutable canonical capsule bytes; _binding is immutable JSON
    linking capsule_sha256 and authenticated producer/export/reader source pins.
    Required origin equals the authenticated native transfer input origin;
    _source_audit is the actual original-metadata RegionalMechanicalSnapshot.
    """
    __slots__ = ('_record', '_binding', '_source_audit')

    def __init__(self, *args, **kwargs):
        raise TypeError('authenticated original-reader import adapter must issue this admission')

    def __setattr__(self, name, value):
        raise WorkflowTransferRefused('historical endpoint admission is immutable')

    def record(self):
        return json.loads(self._record)

    def binding(self):
        return json.loads(self._binding)


class RuntimeCompatibilityAdmission:
    """Reserved for source-bound, explicit reviewed runtime compatibility.

    No issuer exists here. Required record fields: schema
    atlas.restart-runtime-compatibility.v1; historical_execution_identity;
    current_execution_identity; scientific_contract_id; historical and current
    source_manifest_sha256; validation_evidence (the exact review/test artifacts).
    This is separate from matching parameters or accepting historical science.
    """
    __slots__ = ('_record',)

    def __init__(self, *args, **kwargs):
        raise TypeError('reviewed runtime compatibility adapter must issue this admission')

    def __setattr__(self, name, value):
        raise WorkflowTransferRefused('runtime compatibility admission is immutable')

    def record(self):
        return json.loads(self._record)


# The live issuer must return these ACTUAL objects on the ONE caller budget;
# dictionaries, a RestartCatalog entry and a success boolean cannot replace it.
LIVE_BASE_RETURN_CONTRACT = {
    'collar_state': 'RegionalCollarState from OwnedMigratedNativeCollar.state',
    'native_ownership': 'Retained OwnedMigratedNativeCollar; preserve escaped-buffer charges',
    'spatial_state': 'SpatialExteriorState from the actual spatial transfer issuer',
    'spatial_owner': 'PreparedSpatialOwner bound to the current collar/runtime',
    'funding': 'Original FullCellFunding identity and complete bytes; no second debit',
    'spatial_ownership': 'Adopted spatial-transfer owner, funding and state leases',
    'differential_interval': 'Original accepted DifferentialInterval including endpoint network and complete trajectory',
    'differential_partition': 'Original DifferentialPartition and all exact support/history records',
    'current_geometry': 'CurrentGeometry derived from that accepted interval, not initial funding',
    'historical_validation': 'Authenticated original-runtime complete cold-reader result tied to the source root/head/manifest and all original heat/certification artifacts',
    'source_audit': 'Original source audit retained as historical evidence; do not reissue under current execution',
    'shared_budget': 'Actual shared WorkBudget retained by all returned resource owners',
}


# Exact validation contract across this seam and its caller/adapters. Entries
# include implemented checks and external obligations, not an assertion that
# every line remains unwired or that metadata checks validate the science.
REMAINING_REFRESH_CHECKS = (
    'Original reader must validate the complete original chain, source-audit payload, composed-heat checkpoint, final differential certification and exact persisted conservation/tracer accounts; preserve that result with original identities.',
    'Current native+spatial typed transfer must validate unchanged field bytes, positive/nonnegative/finite fields, exact clocks and intervals, full projection/finite/admission accounts and owner/collar compatibility; retain all actual leases.',
    'Create/open migrated entrypoints must bypass only _inputs/create/open fresh-owner and initial_state_from_funding logic. They must use transferred FullCellFunding without invoking fund or initial_state and retain original funding/source identity.',
    'Migrated _verify must verify current collar/native/exterior implementations and transfer ownership. It must not invent PreparedRegionalOwner initial state solely to satisfy the fresh-admission owner slot. Ordinary advance should refuse this spatial-only route.',
    'At the base root, restore through the authenticated historical endpoint plus current transfer issuer. Do not run old exterior_advance/heat/certification through current plan or owner IDs. Set _state/_exterior_state/_differential_interval/_differential_partition/_source_audit from the returned capsule after immutable-root and store-token checks.',
    'Start _refresh traversal at base_sequence+1 with the unchanged absolute MAX_INTERVALS=256 limit. Preserve exact parent_key/parent_digest, clock/source-audit, native/exterior parent IDs and cumulative exterior intervals.',
    'For the first new successor, prior_network is the preserved accepted interval endpoint_network_id and certification current_geometry_id is its endpoint_current_geometry_id. Do not use the original funding source network or an initial-current partition.',
    'For every new successor, reuse existing _refresh actual collar restore, spatial restore/validate_parent, source-audit identity, composed cold heat validation, graph/trajectory, certification and partition validation. accepted_parent must be the migrated root or previous new successor, never None.',
    'The migration root must retain endpoint geometry and original certification references as historical evidence. Its transferred collar/spatial IDs supply the parent for new certification; original heat/force IDs are not rewritten into current IDs.',
    'Original partition collar_plan_id remains historical. Add an explicit exact scientific-contract compatibility issuer/reader seam for DifferentialPartition.restore, prepare_interval_partition and next force/partition consumers; do not relabel its records or relax unrelated equality checks.',
    'Root payload must include every native/collar field, spatial/finite stock and accumulated projection account, original complete trajectory/support/partition, endpoint thermal mesh/heat state and all provenance. Preserve immutable original snapshots, including all predecessors, in the same exclusive working copy or explicitly bound read-only original.',
    'Atomic publication must preserve ArrayStore.put immutable invocation conflict handling and publication_check within its SQLite transaction. Recheck all retained original chain metadata/head absence and current runtime before commit. Root and next-head publication are separate new identities; no overwriting historical metadata.',
    'A fresh-process migrated open must reconstruct the same current transfer from immutable source bytes and check the root current state/owner/plan/transfer IDs, full accounts and source bindings. New descendants then use the existing current-runtime cold validation path.',
)


def canonical(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise WorkflowTransferRefused('finite JSON metadata required') from error
    if len(raw) > MAX_METADATA_BYTES:
        raise WorkflowTransferRefused('bounded migration metadata exceeds 8 MiB')
    return raw


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _decode_allocation(budget, *buffers):
    """Conservatively admit JSON trees/codecs before decoding immutable bytes."""
    import native_transfer as N
    from geometry_transfer import _json_decode_bytes
    size = 65536
    for raw in buffers:
        if not isinstance(raw, bytes):
            raise WorkflowTransferRefused('canonical immutable admission bytes required')
        size += _json_decode_bytes(raw)
    return N._Allocation(budget, size, category='workflow-transfer-metadata-scratch')


def _sha(value, label):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise WorkflowTransferRefused(label+' must be lowercase SHA-256')
    return value


def workflow_key(kind, identity):
    return digest(dict(schema=WORKFLOW_SCHEMA, kind=kind, identity=identity))


def successor_sequence_range(base_sequence):
    if type(base_sequence) is not int or not 0 <= base_sequence <= MAX_INTERVALS:
        raise WorkflowTransferRefused('absolute completed interval count must be in 0..256')
    # The extra iteration is the existing overflow-detection probe, not an
    # additional permitted interval. _refresh refuses an actual record at 257.
    return range(base_sequence+1, MAX_INTERVALS+2)


def validate_historical_chain(chain):
    """Check complete header linkage only; authenticate payload/science elsewhere."""
    if type(chain) not in (list, tuple) or not 2 <= len(chain) <= MAX_INTERVALS+1:
        raise WorkflowTransferRefused('complete nonzero original root-to-endpoint chain required')
    canonical(chain)
    root = chain[0]
    if (type(root) is not dict or root.get('schema') != WORKFLOW_SCHEMA or
            root.get('kind') != 'root' or type(root.get('sequence')) is not int or root['sequence'] != 0):
        raise WorkflowTransferRefused('original sequence-zero root required')
    identity = _sha(root.get('workflow_id'), 'historical workflow')
    if root.get('key') != workflow_key('root', identity):
        raise WorkflowTransferRefused('historical root key differs')
    _sha(root.get('funding_id'), 'original funding')
    previous = root
    for sequence, current in enumerate(chain[1:], 1):
        if (type(current) is not dict or current.get('schema') != WORKFLOW_SCHEMA or
                current.get('kind') != 'successor' or type(current.get('sequence')) is not int or
                current['sequence'] != sequence or current.get('workflow_id') != identity or
                current.get('key') != workflow_key('successor', previous['key']) or
                current.get('parent_key') != previous['key'] or current.get('parent_digest') != digest(previous) or
                current.get('funding_id') != root['funding_id']):
            raise WorkflowTransferRefused('historical chain link, sequence or funding differs')
        try:
            state, parent = current['state'], previous['state']
            fields, prior = state['fields'], parent['fields']
            duration = current['advance']['duration_s']
            audit, exterior = current['source_audit'], current['exterior_state']
            if (type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0 or
                    fields['time_s'] != prior['time_s']+duration or fields['parent_id'] != parent['result_id'] or
                    audit['parent_state_id'] != previous['native_state_id'] or
                    state['native']['parent_state_id'] != previous['native_state_id'] or
                    audit['start_time_s'] != prior['time_s'] or audit['duration_s'] != duration or
                    exterior['parent_state_id'] != previous['exterior_state']['state_id'] or
                    exterior['time_s'] != fields['time_s'] or exterior['intervals'] != sequence or
                    exterior['collar_state_id'] != state['result_id']):
                raise WorkflowTransferRefused('historical native/exterior clock or parent linkage differs')
            for key in ('differential_geometry', 'differential_partition', 'differential_certification', 'exterior_advance'):
                if type(current[key]) is not dict or not current[key]:
                    raise WorkflowTransferRefused('complete historical differential endpoint headers required')
        except (KeyError, TypeError) as error:
            raise WorkflowTransferRefused('historical differential endpoint header missing') from error
        previous = current
    return tuple(dict(key=row['key'], sequence=row['sequence'], metadata_sha256=digest(row)) for row in chain)


def describe_migrated_root(*, chain, source_head_manifest, source_store_token,
                          historical_validation_sha256, native_transfer_record,
                          current_execution):
    """Prepare a reviewable root descriptor; this deliberately conveys NO permit.

    The complete original head manifest retains ALL payload descriptors, not a
    handpicked field subset. All original predecessor header hashes are retained.
    Native transfer is checked for exact source/state/clock linkage only; its
    scientific issuer and the historical receipt must still be authenticated.
    """
    links = validate_historical_chain(chain)
    root, head = chain[0], chain[-1]
    if (type(source_head_manifest) is not dict or
            source_head_manifest.get('invocation') != head['key'] or
            source_head_manifest.get('metadata') != head or
            type(source_head_manifest.get('arrays')) is not dict or not source_head_manifest['arrays']):
        raise WorkflowTransferRefused('exact complete original endpoint manifest required')
    if (type(source_store_token) not in (tuple, list) or len(source_store_token) != 2 or
            any(type(x) is not int or x < 0 for x in source_store_token)):
        raise WorkflowTransferRefused('exact original ArrayStore change token required')
    _sha(historical_validation_sha256, 'original-runtime historical validation')
    if (type(current_execution) is not dict or set(current_execution) != {'execution_identity', 'execution_mode'} or
            current_execution['execution_mode'] not in ('strict', 'release')):
        raise WorkflowTransferRefused('actual successor execution provenance required')
    _sha(current_execution['execution_identity'], 'successor runtime identity')
    try:
        transfer = native_transfer_record
        incoming, current = transfer['input'], transfer['current_collar']
        if (transfer['schema'] != 'atlas.native-collar-migrated-state.v1' or
                incoming['historical_collar'] != head['state'] or
                incoming['historical_native_id'] != head['native_state_id'] or
                incoming['historical_native'] != head['state']['native'] or
                transfer['elapsed_time_s'] != 0 or transfer['funding_debit_applied'] is not False or
                transfer['scientific_acceptance'] is not False or transfer['continuation_authorised'] is not False or
                current['fields']['time_s'] != head['state']['fields']['time_s'] or
                current['fields']['parent_id'] != head['state']['result_id'] or
                current['native']['parent_state_id'] != head['native_state_id'] or
                current['native'] != transfer['current_native']):
            raise WorkflowTransferRefused('native transfer does not preserve the exact historical endpoint')
        graph = incoming['current_plan_graph']
        if (graph['collar']['plan_id'] != current['fields']['plan_id'] or
                graph['native']['plan_id'] != current['native']['plan_id'] or
                graph['native']['definition']['execution'] != current_execution['execution_identity']):
            raise WorkflowTransferRefused('current native/collar definitions or execution differ')
    except (KeyError, TypeError) as error:
        raise WorkflowTransferRefused('complete native transfer record required') from error
    proposal = dict(schema=DESCRIPTOR_SCHEMA, kind='migrated-root-description',
        status='EVIDENCE_ONLY_REQUIRES_AUTHENTICATED_TYPED_BASE',
        may_open=False, may_advance=False, scientific_acceptance=False,
        sequence=head['sequence'], time_s=head['state']['fields']['time_s'],
        predecessor=dict(workflow_id=root['workflow_id'], root_key=root['key'], head_key=head['key'],
            next_key=workflow_key('successor', head['key']), chain=list(links),
            store_token=list(source_store_token), head_manifest=source_head_manifest,
            historical_validation_sha256=historical_validation_sha256),
        original_funding=dict(funding_id=root['funding_id'], definition=root['funding']),
        current_execution=current_execution, native_transfer_id=digest(transfer),
        native_state=transfer['current_native'], native_state_id=transfer['current_native_id'],
        collar_state=current, current_plan_graph=graph,
        historical_endpoint=dict(source_audit=head['source_audit'], advance=head['advance'],
            exterior_state=head['exterior_state'], exterior_advance=head['exterior_advance'],
            differential_geometry=head['differential_geometry'],
            differential_partition=head['differential_partition'],
            differential_certification=head['differential_certification']),
        missing_live_return_contract=LIVE_BASE_RETURN_CONTRACT,
        remaining_refresh_checks=list(REMAINING_REFRESH_CHECKS))
    return dict(descriptor_id=digest(proposal), **deepcopy(proposal))


def chain_publication_fence(store, descriptor):
    """Return same-store metadata CAS check for ArrayStore.put publication_check.

    The original immutable snapshots must already exist in this exclusive
    successor store. The callback requires its *active SQLite transaction*;
    metadata checks thus share publication's writer lock. It adds no writer and
    cannot replace payload, historical science, current runtime or source checks.
    The recorded old connection token is provenance only: a copied store or the
    target's own inserted rows cannot truthfully have that same token.
    """
    from atlas_tectonics.storage import ArrayStore, StoreConflict
    if type(store) is not ArrayStore:
        raise WorkflowTransferRefused('actual ArrayStore required')
    expected = deepcopy(descriptor)
    identity = expected.pop('descriptor_id', None)
    if (identity != digest(expected) or expected.get('schema') != DESCRIPTOR_SCHEMA or
            expected.get('may_open') is not False or expected.get('may_advance') is not False):
        raise WorkflowTransferRefused('unchanged non-authorising root descriptor required')
    predecessor = expected['predecessor']

    def check():
        if not store._db.in_transaction:
            raise WorkflowTransferRefused('migration chain fence must run inside ArrayStore publication transaction')
        for link in predecessor['chain']:
            metadata = store.metadata(link['key'])
            if metadata is None or digest(metadata) != link['metadata_sha256']:
                raise StoreConflict('original predecessor metadata changed or is missing')
        if store.metadata(predecessor['next_key']) is not None:
            raise StoreConflict('original workflow has advanced beyond selected migration endpoint')
        with store._read_scope():
            manifest = store._manifest(predecessor['head_key'])
            if manifest != predecessor['head_manifest']:
                raise StoreConflict('original endpoint manifest changed')
    return check


def _parent_geometry_matches(bridge, partition, *, funding, collar, budget):
    """M7: the bound compact parent's bounded identity, or the ordinary record match.

    matches_compact never re-streams the view, so verify() stays cheap inside
    store writer transactions. Both routes enter collar._operation (non-reentrant).
    """
    view = getattr(partition, '_compact', None)
    if view is not None:
        return bridge.matches_compact(view, funding=funding, collar=collar, budget=budget)
    return bridge.matches(partition.record(), funding=funding, collar=collar, budget=budget)


class MigratedWorkflowBase:
    """Owned, validated current endpoint plus separately admitted old history."""
    __slots__ = ('_native', '_spatial', '_bridge', '_interval', '_partition', '_current',
                 '_historical', '_runtime', '_record', '_endpoint', '_budget')

    def __init__(self, *args, **kwargs):
        raise TypeError('use bind_migrated_base with both actual admissions')

    def __setattr__(self, name, value):
        raise WorkflowTransferRefused('migrated base ownership is immutable')

    def record(self):
        return json.loads(self._record)

    def verify(self):
        import native_transfer as N
        import spatial_transfer as S
        scratch = _decode_allocation(self._budget, self._record, self._native._record,
            self._spatial._record, self._partition._json)
        collar, owner = self._spatial.owner._collar, self._spatial.owner
        collar._verify()
        owner._verify()
        current = N.current_plan_graph(collar._native, collar)
        native, spatial = self._native.record(), self._spatial.record()
        if current != native['input']['current_plan_graph']:
            raise WorkflowTransferRefused('current native/collar source graph changed')
        if (spatial['schema'] != S.TRANSFER_SCHEMA or
                owner.descriptor() != spatial['current_owner_definition'] or
                self._native.state.record() != native['current_collar'] or
                self._spatial.state.state_id != spatial['current_spatial_header']['state_id'] or
                not S.snapshot_metadata_matches(self._spatial.state._snapshot, spatial['current_spatial_metadata']) or
                not _parent_geometry_matches(self._bridge, self._partition, funding=self._spatial.funding,
                                             collar=collar, budget=self._budget)):
            raise WorkflowTransferRefused('transferred endpoint or parent geometry changed')
        S.validate_current_parent(owner, self._native.state, self._spatial.state)
        row = self.record()
        if (hashlib.sha256(self._historical._record).hexdigest() != row['historical_capsule_sha256'] or
                hashlib.sha256(self._historical._binding).hexdigest() != row['historical_admission_id'] or
                hashlib.sha256(self._runtime._record).hexdigest() != row['runtime_admission_id']):
            raise WorkflowTransferRefused('migration admission changed')
        assert scratch.size > 0


def bind_migrated_base(*, native_transfer, spatial_transfer, geometry_transfer,
        interval, partition, historical_admission, runtime_admission, budget):
    """Issue a live base only after both externally authenticated admissions.

    Historical/runtime admissions come from separately reviewed adapters.
    Capsule dictionaries and caller-provided hashes alone cannot grant a run.
    The caller retains this adopted base and owns its spatial owner's closure.
    """
    import native_transfer as N
    import spatial_transfer as S
    import geometry_transfer as G
    from atlas_tectonics import integration_differential_geometry as D
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    if (type(native_transfer) is not N.OwnedMigratedNativeCollar or
            type(spatial_transfer) is not S.OwnedMigratedSpatial or
            type(geometry_transfer) is not G.ParentGeometryTransfer or
            type(interval) is not D.DifferentialInterval or type(partition) is not D.DifferentialPartition or
            type(historical_admission) is not HistoricalEndpointAdmission or
            type(runtime_admission) is not RuntimeCompatibilityAdmission or
            spatial_transfer.native_transfer is not native_transfer or
            any(value is not budget for value in (spatial_transfer.owner._budget,
                spatial_transfer.state._budget, spatial_transfer.funding._resource,
                interval._resource, partition._resource))):
        raise WorkflowTransferRefused('actual shared-budget transfers and both authenticated admissions required')
    scratch = _decode_allocation(budget, historical_admission._record, historical_admission._binding,
        runtime_admission._record, native_transfer._record, spatial_transfer._record, partition._json)
    capsule, admission = historical_admission.record(), historical_admission.binding()
    if (capsule.get('schema') != 'atlas.restart-historical-endpoint.v1' or
            admission.get('capsule_sha256') != hashlib.sha256(historical_admission._record).hexdigest()):
        raise WorkflowTransferRefused('authenticated historical capsule binding differs')
    chain = capsule['chain_metadata']
    links = validate_historical_chain(chain)
    head = chain[-1]
    source = capsule['source']
    if (source['root_key'] != chain[0]['key'] or source['head_key'] != head['key'] or
            source['workflow_id'] != head['workflow_id'] or source['sequence'] != head['sequence'] or
            source['time_s'] != head['state']['fields']['time_s'] or
            capsule['snapshot_manifests'][head['key']]['metadata'] != head):
        raise WorkflowTransferRefused('historical capsule endpoint differs from complete chain')
    evidence, spatial = native_transfer.record(), spatial_transfer.record()
    compatibility = runtime_admission.record()
    producer = capsule['producer']['execution_identity']
    current = evidence['input']['current_plan_graph']['native']['definition']['execution']
    if (compatibility.get('schema') != 'atlas.restart-runtime-compatibility.v1' or
            compatibility.get('historical_execution_identity') != producer or
            compatibility.get('current_execution_identity') != current or
            compatibility.get('scientific_contract_id') != evidence['input']['compatibility']['scientific_contract_id'] or
            evidence['input']['historical_plan_graph']['native']['definition']['execution'] != producer or
            not compatibility.get('validation_evidence')):
        raise WorkflowTransferRefused('separate reviewed old/current runtime compatibility is missing')
    for name in ('historical_source_manifest_sha256', 'current_source_manifest_sha256'):
        _sha(compatibility.get(name), name)
    if (admission.get('origin') != evidence['input']['origin'] or
            compatibility['historical_source_manifest_sha256'] != capsule['producer']['source_manifest_sha256']):
        raise WorkflowTransferRefused('authenticated transfer origin or historical runtime source differs')
    if (evidence['input']['historical_collar'] != head['state'] or
            evidence['input']['historical_native_id'] != head['native_state_id'] or
            spatial['schema'] != S.TRANSFER_SCHEMA or
            spatial['historical_spatial_header']['state_id'] != head['exterior_state']['state_id'] or
            spatial['current_spatial_header']['intervals'] != head['sequence'] or
            spatial['current_spatial_header']['time_s'] != head['state']['fields']['time_s'] or
            interval.interval_id != head['differential_geometry']['interval_id'] or
            partition.partition_id != head['differential_partition']['partition_id'] or
            spatial_transfer.funding.funding_id != chain[0]['funding_id']):
        raise WorkflowTransferRefused('typed endpoint does not preserve its actual original chain')
    audit = historical_admission._source_audit
    if (type(audit) is not RegionalMechanicalSnapshot or
            audit.result_id != head['advance']['source_audit_id'] or audit.descriptor() != head['source_audit']):
        raise WorkflowTransferRefused('actual original source audit snapshot is missing')
    current_geometry = D.current_geometry_from_interval(interval, budget=budget)
    if current_geometry.geometry_id != head['differential_certification']['endpoint_current_geometry_id']:
        raise WorkflowTransferRefused('endpoint current geometry differs from original certification')
    row = dict(schema='atlas.migrated-workflow-base.v1', sequence=head['sequence'],
        time_s=head['state']['fields']['time_s'], historical_head_key=head['key'],
        historical_chain=list(links), historical_capsule_sha256=hashlib.sha256(historical_admission._record).hexdigest(),
        historical_admission_id=hashlib.sha256(historical_admission._binding).hexdigest(),
        runtime_admission_id=hashlib.sha256(runtime_admission._record).hexdigest(),
        native_transfer_id=native_transfer.transfer_id, spatial_transfer_id=spatial_transfer.transfer_id,
        geometry_transfer_id=digest(geometry_transfer.record()), current_execution_identity=current,
        current_geometry_id=current_geometry.geometry_id)
    raw = canonical(row)
    endpoint = canonical(dict(root=chain[0], head=head, head_manifest=capsule['snapshot_manifests'][head['key']],
        original_database_path=admission.get('original_database_path')))
    allocation = N._Allocation(budget, len(raw)+len(endpoint)+8192, category='migrated-workflow-base-retained')
    result = object.__new__(MigratedWorkflowBase)
    for name, value in dict(_native=native_transfer, _spatial=spatial_transfer, _bridge=geometry_transfer,
            _interval=interval, _partition=partition, _current=current_geometry,
            _historical=historical_admission, _runtime=runtime_admission,
            _record=N._RecordBytes(raw, allocation), _endpoint=N._RecordBytes(endpoint, allocation), _budget=budget).items():
        object.__setattr__(result, name, value)
    result.verify()
    assert scratch.size > 0
    return result


@contextmanager
def migrated_root_payload(base, *, store=None, persist_mesh=False, cancel=None):
    """Prepare a fresh immutable root and borrowed payload; never publish it."""
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    if type(base) is not MigratedWorkflowBase:
        raise WorkflowTransferRefused('issued migrated workflow base required')
    base.verify()
    scratch = _decode_allocation(base._budget, base._endpoint, base._record, base._spatial._record,
        base._spatial.state._snapshot._metadata, base._spatial.funding._snapshot._metadata)
    endpoint = json.loads(base._endpoint)
    old_root, old_head = endpoint['root'], endpoint['head']
    native, spatial = base._native.state, base._spatial
    owner, collar, funding = spatial.owner, spatial.owner._collar, spatial.funding
    binding = base.record()
    identity = CollarWorkflow._key('migrated-history', binding)
    options = {}
    if type(spatial.state._snapshot).__module__ == 'spatial_indexed_patch':
        import spatial_workflow_patch as X
        saved = spatial.state
        options = dict(store=store, source_producer=X.producer(collar), persist_mesh=persist_mesh, cancel=cancel)
    else:
        saved = spatial.state.record()
    partition_ref, partition_aliases = None, {}
    if getattr(base._partition, '_compact', None) is not None:
        # The root pins the converted historical partition: one top-level
        # reference plus 'partition-dag:' aliases sharing its immutable chunks.
        import partition_workflow_patch as PW
        import spatial_workflow_patch as X
        if store is None:
            raise WorkflowTransferRefused('compact base partition requires its actual working store')
        partition_ref, partition_aliases = PW.root_partition(store, base._partition, X.producer(collar),
                                                             persist=persist_mesh, cancel=cancel)
    with CollarWorkflow._spatial_records(saved, None, base._budget, **options) as (header, _, blobs):
        root = dict(schema=WORKFLOW_SCHEMA, workflow_id=identity,
            key=CollarWorkflow._key('root', identity), kind='migrated-root',
            sequence=old_head['sequence'], collar_plan=collar.descriptor(),
            funding=funding.descriptor(), funding_id=funding.funding_id,
            state=native.record(), native_state_id=native.native_state.result_id,
            exterior_owner=owner.descriptor(), exterior_state=header,
            exterior_remainder=old_root['exterior_remainder'],
            outer_material_boundary='paired space-time flux; carried finite exterior inventories',
            geometry_family='differential-plate-component-partition-v1', source_status='WORKING NON-CANON',
            differential_geometry=old_head['differential_geometry'],
            differential_partition=old_head['differential_partition'],
            differential_certification=old_head['differential_certification'],
            migration=binding, historical_payload_key=old_head['key'])
        if partition_ref is not None:
            root['compact_partition'] = partition_ref
            blobs = dict(blobs, **partition_aliases)
        # The old geometry/certification headers explicitly refer to the old
        # immutable endpoint payload. Current collar/spatial arrays and headers
        # are separate and can be restored as a parent by the new heat reader.
        try:
            yield root, dict(CollarWorkflow._payload(native, spatial.state), **blobs)
        finally:
            base.verify()
            assert scratch.size > 0


def verify_migrated_workflow(workflow):
    base = getattr(workflow, '_migration', None)
    if (type(base) is not MigratedWorkflowBase or workflow._closed or
            workflow._budget is not base._budget or workflow._collar is not base._spatial.owner._collar or
            workflow._exterior_owner is not base._spatial.owner or workflow._funding is not base._spatial.funding):
        raise WorkflowTransferRefused('workflow has no actual owned migrated base')
    base.verify()
    # This also runs from the ordinary _publish publication_check while its
    # SQLite writer transaction is held, preserving the original-chain fence.
    _check_preserved_chain(workflow._store, base)


def _check_preserved_chain(store, base):
    scratch = _decode_allocation(base._budget, base._endpoint, base._record)
    row, endpoint = base.record(), json.loads(base._endpoint)
    for link in row['historical_chain']:
        if digest(store.metadata(link['key'])) != link['metadata_sha256']:
            raise WorkflowTransferRefused('original preserved chain metadata changed')
    key = row['historical_head_key']
    if store.metadata(workflow_key('successor', key)) is not None:
        raise WorkflowTransferRefused('original chain advanced beyond admitted migration point')
    with store._read_scope():
        if store._manifest(key) != endpoint['head_manifest']:
            raise WorkflowTransferRefused('original endpoint manifest changed')
    assert scratch.size > 0


def restore_migrated_root(workflow, root, token):
    """Restore only the transferred base; new successors use ordinary validators."""
    from atlas_tectonics.storage import StoreConflict
    import native_transfer as N
    verify_migrated_workflow(workflow)
    base, store = workflow._migration, workflow._store
    _check_preserved_chain(store, base)
    with migrated_root_payload(base, store=store) as (expected, arrays):
        if root != expected:
            raise WorkflowTransferRefused('saved migration root differs from actual transferred endpoint')
        from atlas_tectonics.storage import ArrayReference
        compact_manifest_owner = (N._Allocation(base._budget, 65536+16*store.limits.max_manifest_bytes,
            category='migrated-compact-manifest-read') if any(type(a) is ArrayReference for a in arrays.values()) else None)
        with store._read_scope():
            manifest = store._manifest(root['key'])
        if manifest is None or set(manifest['arrays']) != set(arrays):
            raise WorkflowTransferRefused('complete migrated root payload is missing')
        source_key, source = None, None
        for name, array in arrays.items():
            description = manifest['arrays'][name]
            if type(array) is ArrayReference:
                if source_key != array.invocation:
                    with store._read_scope():
                        source = store._manifest(array.invocation)
                    source_key = array.invocation
                if (array.store_path != str(store.path) or source is None or
                        source['arrays'].get(array.array_name) != description or
                        digest(description) != array.descriptor_sha256):
                    raise WorkflowTransferRefused('migrated compact geometry reference changed')
                continue
            if description['dtype'] != array.dtype.str or description['shape'] != list(array.shape):
                raise WorkflowTransferRefused('migrated root field layout changed')
            expected_bytes = memoryview(array).cast('B')
            count = 0
            for offset, values in store.iter_chunks(root['key'], name, budget=base._budget):
                raw = memoryview(values).cast('B')
                begin = offset*array.dtype.itemsize
                if begin != count or raw != expected_bytes[begin:begin+len(raw)]:
                    raise WorkflowTransferRefused('migrated root payload differs from actual transferred bytes')
                count += len(raw)
            if count != len(expected_bytes):
                raise WorkflowTransferRefused('migrated root payload coverage is incomplete')
        _ = compact_manifest_owner
    if token != store.change_token():
        raise StoreConflict('migrated root changed during inspection')
    workflow._head, workflow._state, workflow._token = root, base._native.state, token
    workflow._exterior_state = base._spatial.state
    workflow._differential_interval, workflow._differential_partition = base._interval, base._partition
    workflow._initial_current_geometry = None
    workflow._source_audit = base._historical._source_audit


def open_migrated_root(cls, store, workflow_id, base, *, budget):
    """Read an already-published migrated root; no store writes or fresh funding."""
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.storage import ArrayStore
    if (cls is not CollarWorkflow or type(store) is not ArrayStore or
            type(base) is not MigratedWorkflowBase or store._budget is not budget or base._budget is not budget):
        raise WorkflowTransferRefused('actual CollarWorkflow, store, typed base and shared budget required')
    base.verify()
    with migrated_root_payload(base, store=store) as (expected, _arrays):
        if workflow_id != expected['workflow_id']:
            raise WorkflowTransferRefused('migration workflow identity differs')
        root = store.metadata(expected['key'])
        if root != expected:
            raise WorkflowTransferRefused('bound migrated root is absent or changed')
    spatial = base._spatial
    result = cls._issued(store, spatial.owner._collar, None, spatial.funding, root, budget, spatial.owner)
    result._migration = base
    result._refresh()
    return result


def publish_migrated_root(store, base, *, budget, cancel=None):
    """Add one restart root to an exclusive working copy and reopen it.

    The complete immutable original chain/payloads must already be retained in
    this store. This does not copy, rewrite or advance the original chain. The
    caller must provide the designated working copy, not the readonly original.
    Both authenticated admissions and actual transfer objects remain mandatory.
    Existing ArrayStore.put handles immutable/idempotent writes and rolls back
    if the original head or current runtime changes before the writer commits.
    """
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.storage import ArrayStore
    if (type(store) is not ArrayStore or type(base) is not MigratedWorkflowBase or
            store._budget is not budget or base._budget is not budget or store._db.in_transaction):
        raise WorkflowTransferRefused('exclusive actual store, issued base and shared budget required')
    scratch = _decode_allocation(base._budget, base._endpoint)
    original_path = json.loads(base._endpoint).get('original_database_path')
    if type(original_path) is not str or not Path(original_path).is_absolute():
        raise WorkflowTransferRefused('authenticated original database path is required')
    original = Path(original_path).resolve()
    if (store.path.resolve() == original or
            (original.exists() and store.path.samefile(original))):
        raise WorkflowTransferRefused('migration publication must not write the original database')
    base.verify()
    _check_preserved_chain(store, base)
    with migrated_root_payload(base, store=store, persist_mesh=True, cancel=cancel) as (root, arrays):
        def check():
            if not store._db.in_transaction:
                raise WorkflowTransferRefused('migration publication requires the writer transaction')
            base.verify()
            _check_preserved_chain(store, base)
            if store.metadata(root['key']) != root:
                raise WorkflowTransferRefused('migration root changed within publication')
        store.put(root['key'], arrays, root, publication_check=check, cancel=cancel, budget=budget)
        identity = root['workflow_id']
    assert scratch.size > 0
    return CollarWorkflow.open_migrated(store, identity, base, budget=budget)


_CURSOR_OLD = '''        previous, accepted_parent = root, None
        for sequence in range(1, MAX_INTERVALS+2):
            key = self._key('successor', previous['key'])
'''
_CURSOR_NEW = '''        # Nonzero roots require their own typed transfer restore. This exact
        # boundary does not treat an evidence-only descriptor as admission.
        base_sequence = root.get('sequence')
        if type(base_sequence) is not int or not 0 <= base_sequence <= MAX_INTERVALS:
            raise RegionalOwnerRefused('invalid absolute workflow base sequence')
        if root.get('kind') == 'migrated-root':
            from workflow_transfer import verify_migrated_workflow
            verify_migrated_workflow(self)
            if root.get('migration') != self._migration.record() or base_sequence != self._migration.record()['sequence']:
                raise RegionalOwnerRefused('migration root is not its actual admitted base')
        elif root.get('kind') != 'root' or base_sequence != 0:
            raise RegionalOwnerRefused('ordinary root must retain sequence zero')
        previous, accepted_parent = root, None
        for sequence in range(base_sequence+1, MAX_INTERVALS+2):
            key = self._key('successor', previous['key'])
'''


def nonzero_cursor_source(source):
    """Exact additive root-only seam; ordinary create/open remain unchanged.

    Return proposed source text only. No source/store writes or loaded-function
    patches. Actual current state comes only from both admitted transfer types;
    capsule/export metadata alone cannot use this route.
    """
    if (type(source) is not str or hashlib.sha256(source.encode()).hexdigest() != BASE_SOURCE_SHA256 or
            source.count(_CURSOR_OLD) != 1):
        raise WorkflowTransferRefused('regional workflow source differs from exact reviewed base')
    changes = (
        (_CURSOR_OLD, _CURSOR_NEW),
        ('''        arrays = self._store.get(previous['key'], budget=self._budget)
        if arrays is None:
            raise RegionalOwnerRefused('funded collar accepted payload is missing')
''', '''        if previous['kind'] == 'migrated-root':
            from workflow_transfer import restore_migrated_root
            restore_migrated_root(self, previous, token)
            return
        arrays = self._store.get(previous['key'], budget=self._budget)
        if arrays is None:
            raise RegionalOwnerRefused('funded collar accepted payload is missing')
'''),
        ('''    def _verify(self):
        if self._closed:
            raise RegionalOwnerRefused('funded collar workflow is closed')
        self._collar._verify()
''', '''    @classmethod
    def open_migrated(cls, store, workflow_id, base, *, budget):
        from workflow_transfer import open_migrated_root
        return open_migrated_root(cls, store, workflow_id, base, budget=budget)

    def _verify(self):
        if self._closed:
            raise RegionalOwnerRefused('funded collar workflow is closed')
        if getattr(self, '_migration', None) is not None:
            from workflow_transfer import verify_migrated_workflow
            verify_migrated_workflow(self)
            return
        self._collar._verify()
'''),
        ('''    def advance(self, duration_s, *, wall_measures=None, **driving):
        self._refresh()
        if self._owner.descriptor().get('basal_side') is not None:
''', '''    def advance(self, duration_s, *, wall_measures=None, **driving):
        self._refresh()
        if getattr(self, '_migration', None) is not None:
            raise RegionalOwnerRefused('migrated spatial workflow requires source_flow_stage and advance_spatial')
        if self._owner.descriptor().get('basal_side') is not None:
'''),
    )
    for old, new in changes:
        if source.count(old) != 1:
            raise WorkflowTransferRefused('regional workflow seam is missing or ambiguous')
        source = source.replace(old, new, 1)
    return source


def private_heat_cold_source(source):
    """Permit the first NEW heat interval's actually verified migrated parent.

    The calling restore_checkpoint still requires the actual CollarWorkflow,
    invokes its patched _verify, rereads immutable parent/head and restores their
    actual current fields. No old heat checkpoint is reissued under new IDs.
    """
    expected = '82d90e8f717f9f2dea06a36a53086298b74f7a4788e6ca825e3678259d48f729'
    old = "parent.get('kind') not in ('root', 'successor')"
    new = "parent.get('kind') not in ('root', 'successor', 'migrated-root')"
    if type(source) is not str or hashlib.sha256(source.encode()).hexdigest() != expected or source.count(old) != 1:
        raise WorkflowTransferRefused('private cold-reader source differs from exact reviewed base')
    return source.replace(old, new, 1)
