"""Original funding/current runtime binding for differential pressure only.

No allocation is booked, refreshed or relabelled. The capability retains an
actual admitted spatial owner and its original immutable funding, with the
complete native/scientific transfer proof. It is not a workflow acceptance or
advance capability. Historical admission remains the workflow root's duty.
"""
import hashlib
import json

import geometry_transfer as G
import native_transfer as N
import spatial_transfer as S


class FundingTransferRefused(ValueError):
    pass


def _stream_hash(record):
    from atlas_tectonics.integration_differential_geometry import _record_hash
    return _record_hash(record)


def _validate_current_pair(owner, state, spatial_state):
    from atlas_tectonics.regional_collar3d import RegionalCollarState
    from atlas_tectonics.integration_spatial_owner import SpatialExteriorState
    if type(state) is not RegionalCollarState or type(spatial_state) is not SpatialExteriorState:
        raise FundingTransferRefused('actual current native/spatial state pair required')
    S.validate_current_parent(owner, state, spatial_state)


class OriginalFundingTransfer:
    __slots__ = ('_spatial', '_record', '_budget')

    def __init__(self, *args, **kwargs):
        raise TypeError('use bind_original_funding with the actual migrated spatial owner')

    def __setattr__(self, name, value):
        raise FundingTransferRefused('original funding transfer is immutable')

    def record(self):
        return json.loads(self._record)

    def matches(self, record, *, funding, collar, budget, state=None, spatial_state=None):
        if (funding is not self._spatial.funding or collar is not self._spatial.owner._collar
                or budget is not self._budget or self._spatial.owner._funding is not funding):
            return False
        if (state is None) != (spatial_state is None):
            raise FundingTransferRefused('current native/spatial states must be supplied together')
        scratch = N._Allocation(budget, 65536+G._json_decode_bytes(self._record)
            +G._plan_graph_scratch_bytes(collar)+4*N._width(record), category='funding-transfer-match-scratch')
        self._spatial.owner._verify()
        expected = self.record()
        with collar._operation(None):
            current = N.current_plan_graph(collar._native, collar)
            if (_stream_hash(current) != expected['current_plan_graph_sha256']
                    or self._spatial.native_transfer.transfer_id != expected['native_transfer_id']
                    or self._spatial.transfer_id != expected['spatial_transfer_id']
                    or funding.funding_id != expected['funding_id']
                    or collar.plan_id != expected['current_collar_plan_id']):
                raise FundingTransferRefused('actual owner or native/scientific transfer changed')
            body = {k: v for k, v in record.items() if k != 'funding_id'}
            valid = (record.get('funding_id') == funding.funding_id
                and record.get('collar_plan_id') == expected['historical_collar_plan_id']
                and _stream_hash(body) == expected['original_funding_metadata_sha256']
                and hashlib.sha256(funding._snapshot._metadata).hexdigest()
                    == expected['original_funding_metadata_sha256'])
            if valid and state is not None:
                _validate_current_pair(self._spatial.owner, state, spatial_state)
        assert scratch.size > 0
        return valid


def bind_original_funding(spatial_transfer, *, collar, budget):
    from atlas_tectonics.integration_collar_geometry import FullCellFunding
    from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner
    if (type(spatial_transfer) is not S.OwnedMigratedSpatial
            or type(spatial_transfer.owner) is not PreparedSpatialOwner
            or type(spatial_transfer.funding) is not FullCellFunding
            or type(spatial_transfer.native_transfer) is not N.OwnedMigratedNativeCollar
            or spatial_transfer.owner._collar is not collar
            or spatial_transfer.owner._funding is not spatial_transfer.funding
            or any(value is not budget for value in (collar._budget, spatial_transfer.owner._budget,
                spatial_transfer.funding._resource, spatial_transfer.state._budget))):
        raise FundingTransferRefused('actual transferred spatial owner/funding on one current budget required')
    owner, funding, native = spatial_transfer.owner, spatial_transfer.funding, spatial_transfer.native_transfer
    scratch = N._Allocation(budget, 65536+sum(G._json_decode_bytes(raw) for raw in
        (spatial_transfer._record, native._record))
        +G._plan_graph_scratch_bytes(collar)+4*N._width(owner._definition), category='funding-transfer-bind-scratch')
    owner._verify()
    with collar._operation(None):
        spatial, evidence = spatial_transfer.record(), native.record()
        current = N.current_plan_graph(collar._native, collar)
        G._validate_transfer_contract(native, evidence, current, budget)
        comparison = evidence['input']['compatibility']
        original = spatial['original_funding_header']
        binding = spatial['funding_binding']
        if (spatial['schema'] != S.TRANSFER_SCHEMA
                or spatial['native_transfer_id'] != native.transfer_id
                or spatial['scientific_contract_id'] != comparison['scientific_contract_id']
                or spatial['origin'] != evidence['input']['origin']
                or spatial['funding_debits_applied'] != 0 or spatial['elapsed_time_s'] != 0
                or binding['funding_id'] != funding.funding_id
                or type(binding['debit_count']) is not int or binding['debit_count'] != 1
                or original['funding_id'] != funding.funding_id
                or not S.snapshot_metadata_matches(funding._snapshot, spatial['original_funding_metadata'])
                or original['collar_plan_id'] != comparison['plan_id_correspondence']['collar']['historical']
                or owner.descriptor() != spatial['current_owner_definition']
                or spatial_transfer.state.state_id != spatial['current_spatial_header']['state_id']
                or not S.snapshot_metadata_matches(spatial_transfer.state._snapshot, spatial['current_spatial_metadata'])
                or S._bindings(funding.arrays()) != spatial['original_funding_arrays']
                or S._bindings(spatial_transfer.state.arrays()) != spatial['spatial_arrays']):
            raise FundingTransferRefused('complete original funding/spatial/native transfer correspondence differs')
        N._digest(binding['ledger_sha256'], 'original funding ledger binding')
        _validate_current_pair(owner, native.state, spatial_transfer.state)
        record = dict(schema='atlas.original-funding-runtime-transfer.v1',
            spatial_transfer_id=spatial_transfer.transfer_id, native_transfer_id=native.transfer_id,
            current_plan_graph_sha256=_stream_hash(current), scientific_contract_id=comparison['scientific_contract_id'],
            historical_collar_plan_id=original['collar_plan_id'], current_collar_plan_id=collar.plan_id,
            funding_id=funding.funding_id,
            original_funding_metadata_sha256=hashlib.sha256(funding._snapshot._metadata).hexdigest(),
            funding_binding=binding, funding_debits_applied=0, scientific_acceptance=False)
        raw = N._json(record)
        allocation = N._Allocation(budget, len(raw)+4096, category='funding-transfer-retained')
        result = object.__new__(OriginalFundingTransfer)
        for key, value in dict(_spatial=spatial_transfer, _record=N._RecordBytes(raw, allocation), _budget=budget).items():
            object.__setattr__(result, key, value)
    assert scratch.size > 0
    return result


def funding_binding_matches(record, funding, collar, budget, transfer, *, state=None, spatial_state=None):
    if record.get('collar_plan_id') == collar.plan_id:
        return True
    return (type(transfer) is OriginalFundingTransfer and transfer.matches(record, funding=funding,
        collar=collar, budget=budget, state=state, spatial_state=spatial_state))


def for_workflow(workflow):
    """One binding per current-force factory; retain it across both builders."""
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from workflow_transfer import MigratedWorkflowBase
    if type(workflow) is not CollarWorkflow:
        raise FundingTransferRefused('actual workflow required, not an arbitrary migration token')
    base = getattr(workflow, '_migration', None)
    if base is None:
        return None
    if (type(base) is not MigratedWorkflowBase or workflow._funding is not base._spatial.funding
            or workflow._exterior_owner is not base._spatial.owner
            or workflow._collar is not base._spatial.owner._collar or workflow._budget is not base._budget):
        raise FundingTransferRefused('workflow and retained migrated funding owner differ')
    # The existing factory has already called workflow.inspect(); ordinary
    # workflow verification, historical acceptance and CAS authority stay there.
    return bind_original_funding(base._spatial, collar=workflow._collar, budget=workflow._budget)


def pressure_source(source):
    """Exact two optional pressure guards; all other source checks unchanged."""
    replacements = (
        ('                                gradient_pa_m, origin_world_m, source, budget):',
         '                                gradient_pa_m, origin_world_m, source, budget, _runtime_funding_transfer=None):'),
        ('                                  max_operator_error, max_leaves, budget):',
         '                                  max_operator_error, max_leaves, budget, _runtime_funding_transfer=None):'),
        ("f['collar_plan_id'] != collar.plan_id or tuple(force_plan['cells']) != collar.cells or",
         "not _transferred_funding_binding(f, funding, collar, budget, _runtime_funding_transfer) or tuple(force_plan['cells']) != collar.cells or"),
        ("f['collar_plan_id'] != collar.plan_id or pressure['collar_plan_id'] != collar.plan_id or",
         "not _transferred_funding_binding(f, funding, collar, budget, _runtime_funding_transfer, state=state, spatial_state=spatial_state) or pressure['collar_plan_id'] != collar.plan_id or"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise FundingTransferRefused('pressure funding seam missing or ambiguous: '+old[:70])
        source = source.replace(old, new)
    source += '\n\ndef _transferred_funding_binding(record, funding, collar, budget, transfer, *, state=None, spatial_state=None):\n'
    source += "    if record.get('collar_plan_id') == collar.plan_id:\n        return True\n"
    source += '    if transfer is None:\n        return False\n'
    source += '    from funding_transfer import funding_binding_matches\n'
    source += '    return funding_binding_matches(record, funding, collar, budget, transfer, state=state, spatial_state=spatial_state)\n'
    return source


def continuation_control_source(source):
    """Pass only the actual reopened workflow's funding binding, once."""
    marker = '    datum = RadialDatum(10., 1., 1., 7., 1.1, 0.,\n'
    replacements = ((marker, '    from funding_transfer import for_workflow\n'
        '    _funding_transfer = for_workflow(workflow)\n'+marker),
        ("source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget)",
         "source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget,\n            _runtime_funding_transfer=_funding_transfer)"),
        ('max_operator_error=Q(1, 10**20), max_leaves=4096, budget=budget)',
         'max_operator_error=Q(1, 10**20), max_leaves=4096, budget=budget,\n            _runtime_funding_transfer=_funding_transfer)'),
    )
    if 'from funding_transfer import for_workflow' in source:
        raise FundingTransferRefused('continuation funding seam is already applied')
    for old, new in replacements:
        if source.count(old) != 1:
            raise FundingTransferRefused('continuation funding caller missing or ambiguous: '+old[:70])
        source = source.replace(old, new)
    return source


def continuation_control_source_after_limits(source):
    """The same seam on the work-ceiling derivative actually executed.

    private_heat_original_continuation_r1's 'pressure-work-ceiling' edit makes
    the endpoint pressure call read max_leaves=pressure_max_leaves, so the
    literal anchor above is absent there (and this one absent in the source).
    Apply after that helper's edits and the compact routing edits. Binding
    creation and both forwarded keywords are those of continuation_control_source.
    """
    marker = '    datum = RadialDatum(10., 1., 1., 7., 1.1, 0.,\n'
    replacements = ((marker, '    from funding_transfer import for_workflow\n'
        '    _funding_transfer = for_workflow(workflow)\n'+marker),
        ("source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget)",
         "source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget,\n            _runtime_funding_transfer=_funding_transfer)"),
        ('max_operator_error=Q(1, 10**20), max_leaves=pressure_max_leaves, budget=budget)',
         'max_operator_error=Q(1, 10**20), max_leaves=pressure_max_leaves, budget=budget,\n            _runtime_funding_transfer=_funding_transfer)'),
    )
    if type(source) is not str or 'from funding_transfer import for_workflow' in source:
        raise FundingTransferRefused('continuation funding seam is already applied or source is not text')
    for old, new in replacements:
        if source.count(old) != 1:
            raise FundingTransferRefused('continuation funding caller missing or ambiguous: '+old[:70])
        source = source.replace(old, new)
    return source
