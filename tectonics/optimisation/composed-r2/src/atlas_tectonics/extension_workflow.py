"""W05 requested-output workflow with atomic, lossless, source-bound recovery.

Snapshots contain both transported material and its derived support. Only the
latest output is retained in RAM; ArrayStore deduplicates/compresses disk chunks.
No pickle, automatic source migration, trial history or new storage subsystem.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import numpy as np

from ._validation import TectonicsError, scalar
from .extension import (PreparedListricExtension, ExtensionState, _state, _within_budget,
                        MAX_EXTENSION_INTERVALS)
from .extension_support import PreparedExtensionSupport, ExtensionSupportResult
from .materials import _json, _account, restore_material_state
from .remapping import _inventories
from .column_loads import column_load_change
from .regional import _cancelled
from .resources import select_budget
from .storage import ArrayStore


@dataclass(frozen=True, slots=True)
class ExtensionWorkflowCheckpoint:
    checkpoint_id: str
    output_index: int
    state: ExtensionState
    support: ExtensionSupportResult


class PreparedExtensionWorkflow:
    """Borrow motion/store; own one prepared support and one current output.

    The explicit, strictly increasing schedule may include the initial time.
    It is part of the identity: changing it starts a NEW run, never repins old
    checkpoints. A supplied store means every completed output is durable; cheap
    one-off calculations can omit it. Returned buffers retained by callers need
    their own memory allowance, as with W02 MaterialState.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared extension workflow is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, motion, policy, output_times_s, *, store=None, budget=None, cancel=None):
        _cancelled(cancel)
        if type(motion) is not PreparedListricExtension:
            raise TectonicsError('prepared extension motion required')
        if type(output_times_s) not in (tuple, list) or not 1 <= len(output_times_s) <= MAX_EXTENSION_INTERVALS:
            raise TectonicsError('one to 256 explicit requested outputs required')
        times = tuple(scalar(t, 'output time') for t in output_times_s)
        initial = motion.initial.material.time_s
        if times[0] < initial or any(b <= a for a, b in zip(times, times[1:])):
            raise TectonicsError('output times must increase strictly from the initial time')
        previous = initial
        for t in times:
            if previous+(t-previous) != t or initial+(t-initial) != t:
                raise TectonicsError('output endpoint is not representable')
            previous = t
        if store is not None and not isinstance(store, ArrayStore):
            raise TectonicsError('ArrayStore required')
        owner = motion._budget if store is None else store._budget
        resource = owner if budget is None else select_budget(budget)
        _within_budget(owner, motion._budget)
        _within_budget(resource, owner)
        self.motion, self.store, self.output_times_s = motion, store, times
        self._budget, self._closed, self._current = resource, False, None
        self._support = None
        # Holds one output, plus the old/new pair during a transition and restore.
        n, c = motion.grid.cells, len(motion.initial.material.cohorts)
        self._lease = resource.reserve((32*c+768)*n+65536, category='extension-workflow-retained')
        self._lease.__enter__()
        try:
            self._support = PreparedExtensionSupport(motion, policy, budget=resource, cancel=cancel)
            self.plan_id = hashlib.sha256(_json(dict(method='w05-output-workflow-v1',
                motion=motion.plan_id, support=self._support.plan_id, times_s=times,
                initial=motion.initial.state_id, execution=motion.execution_id))).hexdigest()
            self._sealed = True
        except BaseException:
            if self._support is not None:
                self._support.close()
            self._lease.__exit__(None, None, None)
            raise

    def _check(self, cancel=None):
        if self._closed:
            raise TectonicsError('extension workflow is closed')
        self.motion._check(self.motion.initial)
        _cancelled(cancel)
        self.motion._context.verify()

    def _index(self, index):
        if type(index) is not int or not 0 <= index < len(self.output_times_s):
            raise TectonicsError('output index outside the declared schedule')
        return index

    def _invocation(self, index):
        return dict(schema='atlas.w05-output.v1', workflow=self.plan_id,
                    output_index=self._index(index), time_s=self.output_times_s[index])

    def checkpoint_id(self, index):
        return hashlib.sha256(_json(self._invocation(index))).hexdigest()

    def _pack(self, checkpoint):
        state, result = checkpoint.state, checkpoint.support
        arrays = dict(thickness=state.material.thickness_m, exchange=state.exchange_m2,
                      mean_w=result.cell_means[:, 1], points=result.face_centre_response)
        # Fixed edges are authenticated by the prepared motion plan. They are
        # already available at restart, so do not create another stored copy.
        # Geometry/load fields are reconstructed by the mandatory restore checks;
        # store only w rather than duplicating nine cheap derived mean columns.
        meta = dict(invocation=self._invocation(checkpoint.output_index),
            execution=self.motion.execution_id, material=state.material.descriptor(),
            material_id=state.material.state_id, state_id=state.state_id,
            intervals=state.intervals, max_courant=state.max_courant,
            support=result.descriptor(), support_id=result.result_id)
        return arrays, meta

    def _restore(self, index, arrays, meta):
        motion, prepared = self.motion, self._support
        n, c = motion.grid.cells, len(motion.initial.material.cohorts)
        shapes = dict(thickness=(c, n), exchange=(c, 2), mean_w=(n,), points=(2*n+1, 4))
        if (set(arrays) != set(shapes) or type(meta) is not dict or set(meta) != {
                'invocation', 'execution', 'material', 'material_id', 'state_id',
                'intervals', 'max_courant', 'support', 'support_id'} or
                meta['invocation'] != self._invocation(index) or meta['execution'] != motion.execution_id):
            raise TectonicsError('incompatible W05 checkpoint/source binding')
        for name, shape in shapes.items():
            a = arrays[name]
            if a.shape != shape or a.dtype != np.dtype('float64') or not np.isfinite(a).all():
                raise TectonicsError('invalid W05 checkpoint field shape/dtype/values')
        material = restore_material_state(meta['material'], arrays['thickness'], meta['material_id'],
                                         edges_m=motion.grid.edges_m, budget=self._budget)
        count = index+1-int(self.output_times_s[0] == motion.initial.material.time_s)
        if (type(meta['intervals']) is not int or meta['intervals'] != count or
                material.time_s != self.output_times_s[index]):
            raise TectonicsError('W05 checkpoint clock/count mismatch')
        maximum = 0.
        previous = motion.initial.material.time_s
        for t in self.output_times_s[:index+1]:
            maximum = max(maximum, motion.velocity_m_s*(t-previous)/float(np.min(motion.grid.widths_m)))
            previous = t
        if meta['max_courant'] != maximum:
            raise TectonicsError('W05 checkpoint swept-cell bound mismatch')
        state = _state(motion.plan_id, material, count, maximum, arrays['exchange'])
        motion._check(state)
        if state.state_id != meta['state_id']:
            raise TectonicsError('W05 checkpoint material/exchange identity mismatch')
        if count == 0:
            if state.state_id != motion.initial.state_id:
                raise TectonicsError('W05 initial checkpoint differs from declared reference')
        else:
            receipt = material.transition_record
            elapsed = material.time_s-motion.initial.material.time_s
            prior_time = motion.initial.material.time_s if index == 0 else self.output_times_s[index-1]
            swept = motion.velocity_m_s*(material.time_s-prior_time)/float(np.min(motion.grid.widths_m))
            before = np.frombuffer(motion._initial_inventory, dtype=np.float64)
            after = _inventories(material.thickness_m, motion.grid, motion.backend)
            accounts = [_account(float(b), float(a), float(l), float(r), swept)
                        for b, a, (l, r) in zip(before, after, state.exchange_m2)]
            expected = dict(operation='listric-characteristic-v1', plan=motion.plan_id,
                initial_material=motion.initial.material.state_id,
                displacement_m=motion.velocity_m_s*elapsed, cumulative_cohort_accounts=accounts,
                account_reference='initial_material', execution=motion.execution_id,
                parent=material.parent_state_id)
            if _json(receipt) != _json(expected) or (count == 1 and
                    material.parent_state_id != motion.initial.material.state_id):
                raise TectonicsError('W05 characteristic receipt/account mismatch')
        # Verify cheap geometry/load contracts and bounds, but never rerun either
        # Green convolution to accept a hit. Store checksums authenticate payloads;
        # these checks bind them to this physical reference and output semantics.
        points = arrays['points']
        fields = motion.geometry_fields(state, budget=self._budget)
        current = prepared._load(state, fields[:, 0], None)
        q = column_load_change(prepared._reference_load, current,
            prepared.policy.elastic.gravity_m_s2, budget=self._budget)[:, 3]
        w = arrays['mean_w']
        values = np.column_stack((q, w, fields[:, 3], fields[:, 3]-w,
            -motion.geometry.crust_thickness_m-w,
            motion.footwall_thickness_m-motion.geometry.crust_thickness_m-w,
            motion.geometry.crust_thickness_m+fields[:, 3], fields[:, 0], fields[:, 1],
            -prepared.support.area_m2*w))
        qright, tail = prepared._tail(state)
        scale = float(np.max(np.abs(q)))/prepared.policy.elastic.restoring_pa_per_m
        bound, derivatives = np.sqrt(2.)*scale, []
        for _ in range(3):
            bound = bound/prepared.operator.alpha_m*np.sqrt(2.)
            derivatives.append(float(bound))
        valid = tuple(float(np.max(np.abs(points[:, d])))+
            prepared.operator.grid.spacing_m/4*derivatives[d]+tail[d] for d in range(3))
        strain = prepared.policy.elastic.elastic_thickness_m/2*valid[2]
        if (tail[0] > prepared.policy.max_omitted_displacement_m or
                valid[0] > prepared.policy.max_abs_displacement_m or
                valid[1] > prepared.policy.max_abs_slope or strain > prepared.policy.max_bending_strain):
            raise TectonicsError('W05 restored output exceeds support validity bounds')
        record = dict(schema='atlas.w05-support-result.v1', plan=prepared.plan_id,
            initial=motion.initial.state_id, current=state.state_id,
            load_reference=prepared._reference_load.state_id, load_current=current.state_id,
            frame_id=motion.grid.frame_id, datum_id=motion.datum_id,
            epoch_id=material.epoch_id, time_s=material.time_s, execution=motion.execution_id,
            exterior_right_bound_pa=qright, omitted_response_bounds=tail,
            continuous_validity_bounds=valid, max_bending_strain_bound=strain,
            mean_output='exact-cell-load-and-output-integrals',
            mantle='hydrostatic reservoir; -A*w, not transported crust',
            reference='total change from initial; never accumulated onto earlier output')
        metadata, payload, point_payload = _json(record), values.tobytes(), points.tobytes()
        digest = hashlib.sha256(metadata+payload+point_payload).hexdigest()
        if _json(meta['support']) != metadata or meta['support_id'] != digest:
            raise TectonicsError('W05 checkpoint support identity/semantics mismatch')
        result = object.__new__(ExtensionSupportResult)
        for name, value in (('_metadata', metadata), ('_fields', payload),
                            ('_points', point_payload), ('result_id', digest)):
            object.__setattr__(result, name, value)
        return ExtensionWorkflowCheckpoint(self.checkpoint_id(index), index, state, result)

    def load(self, index, *, cancel=None):
        """Read a complete output; corruption is an error, never a cache miss."""
        self._index(index); self._check(cancel)
        if self.store is None:
            result = self._current if self._current is not None and self._current.output_index == index else None
        else:
            with self._budget.reserve((32*len(self.motion.initial.material.cohorts)+512)*self.motion.grid.cells+
                                      65536, category='extension-workflow-restore'):
                key = self.checkpoint_id(index)
                arrays = self.store.get(key, budget=self._budget)
                result = None if arrays is None else self._restore(index, arrays, self.store.metadata(key))
        self._check(cancel)
        return result

    def run(self, *, through=None, cancel=None):
        """Complete through an inclusive output index, reusing the saved prefix.

        Only the most recent required payload is decoded on resume. Earlier
        manifests must exist contiguously, and their bytes are verified when
        individually loaded; this is not an archive-wide integrity scan.
        """
        self._check(cancel)
        end = len(self.output_times_s)-1 if through is None else self._index(through)
        current = self._current
        if self.store is not None:
            latest, gap = -1, False
            for i in range(end+1):
                _cancelled(cancel)
                exists = self.store.contains(self.checkpoint_id(i))
                if exists and gap:
                    raise TectonicsError('W05 output history has a missing requested checkpoint')
                if exists:
                    latest = i
                else:
                    gap = True
            current = self.load(latest, cancel=cancel) if latest >= 0 else None
        elif current is not None and current.output_index > end:
            raise TectonicsError('earlier in-memory output was not retained; supply a store to recover it')
        state = self.motion.initial if current is None else current.state
        start = 0 if current is None else current.output_index+1
        for index in range(start, end+1):
            self._check(cancel)
            state = self.motion.advance(state, time_s=self.output_times_s[index],
                                        budget=self._budget, cancel=cancel)
            result = self._support.solve(state, cancel=cancel)
            candidate = ExtensionWorkflowCheckpoint(self.checkpoint_id(index), index, state, result)
            if self.store is not None:
                arrays, meta = self._pack(candidate)
                self.store.put(candidate.checkpoint_id, arrays, meta, budget=self._budget,
                    cancel=cancel, publication_check=lambda: self._check(cancel))
            # Only advance visible state AFTER durable publication succeeds.
            current = candidate
            object.__setattr__(self, '_current', current)
        self._check(cancel)
        object.__setattr__(self, '_current', current)
        return current

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            object.__setattr__(self, '_current', None)
            try:
                self._support.close()
            finally:
                self._lease.__exit__(None, None, None)

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *args):
        self.close()
