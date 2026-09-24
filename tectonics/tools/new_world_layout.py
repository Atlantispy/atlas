"""Seeded candidate plate geometry, not a complete physical world.

SPDX-License-Identifier: AGPL-3.0-only
This adapter deliberately stays outside the native source-bound package. It
reuses its spherical builder and sparse connected cuts without modifying old
recipes, cached products or W12 source identities.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import asdict, dataclass, replace
import hashlib
import math
from pathlib import Path
import time

from new_world_contract import ContractError, canonical_bytes, validate_plan

METHOD = 'atlas.variable-plate-layout.v1'
SIZE_PRIOR = 'pb2002-ranked-log-uniform-perturbation-v1'
_SOURCE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class LayoutPolicy:
    """Explicit engineering prior width; NOT an empirically fitted uncertainty.

    exp(+/-0.35) multiplies exposed PB2002 weights before ranking/normalisation.
    Zero selects the original size spectrum. Accuracy bounds retain the existing
    candidate route's limits; insufficient resolution is refused, never repaired
    by removing small plates, widening tolerances or choosing another seed.
    """
    size_log_spread: float = .35
    max_area_l1_error: float = .04
    max_relative_area_error: float = .25

    def __post_init__(self):
        for name, low, high in (('size_log_spread', 0., 1.),
                                ('max_area_l1_error', 0., .04),
                                ('max_relative_area_error', 0., .25)):
            value = getattr(self, name)
            if (type(value) not in (float, int) or not math.isfinite(value)
                    or not low <= value <= high or (name != 'size_log_spread' and value == 0)):
                raise ContractError('INVALID_LAYOUT_POLICY', 'Unsupported layout policy value: ' + name)
            object.__setattr__(self, name, float(value))


@dataclass(frozen=True, slots=True)
class LayoutCandidate:
    atlas: object | None
    report: dict


def _source_hash():
    digest = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()
    if digest != _LOADED_HASH:
        raise ContractError('SOURCE_MISMATCH', 'Layout adapter changed while loaded; restart explicitly.')
    return digest


def sample_area_spectrum(count, sizes_seed, *, spread=.35):
    """O(N) independent rank draws; no global RNG and no geometry/shape fitting."""
    from atlas_tectonics.plate_reference import reference_area_fractions, plate_reference_record
    if (type(sizes_seed) is not str or len(sizes_seed) != 32
            or any(c not in '0123456789abcdef' for c in sizes_seed)):
        raise ContractError('INVALID_LAYOUT_SEED', 'The size stream must contain 128-bit lowercase hex.')
    spread = LayoutPolicy(size_log_spread=spread).size_log_spread
    baseline = reference_area_fractions(count)
    logarithms = []
    for rank, base in enumerate(baseline):
        payload = (SIZE_PRIOR.encode('ascii') + b'\0' + bytes.fromhex(sizes_seed)
                   + rank.to_bytes(4, 'big'))
        word = int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big')
        unit = (word >> 11) * 2.**-53
        logarithms.append(spread * (2*unit-1))
    weights = sorted((float(base)*math.exp(delta)
                      for base, delta in zip(baseline, logarithms)), reverse=True)
    # Preserve the previous exact target bytes for the explicitly selected zero
    # spread case, rather than introducing another floating-point normalisation.
    total = math.fsum(weights)
    targets = baseline.tolist() if spread == 0 else [weight/total for weight in weights]
    return dict(prior=SIZE_PRIOR, status='UNCALIBRATED_ENGINEERING_PRIOR',
        reference_id=plate_reference_record()['reference_sha256'],
        baseline_fractions=baseline.tolist(), log_perturbations=logarithms,
        size_log_spread=spread, sizes_seed=sizes_seed, target_fractions=targets,
        interpretation='Variation about exposed Earth area ranks; not a universal planetary law.')


class _Cancellation:
    def __init__(self, seconds, external):
        if external is not None and not callable(getattr(external, 'is_set', None)):
            raise ContractError('INVALID_CANCEL', 'Cancellation must provide is_set().')
        self.end = time.perf_counter() + seconds
        self.external = external
        self.reason = None

    def is_set(self):
        if self.external is not None and self.external.is_set():
            self.reason = 'CANCELLED'
        elif time.perf_counter() >= self.end:
            self.reason = 'TIME_LIMIT'
        return self.reason is not None


def generate_layout_candidate(plan, *, policy=None, cancel=None):
    """One explicit candidate, with identified refusals and no hidden seed retry.

    The full scientific plan identity is retained even where a setting currently
    has no geometric effect (gravity/continental fraction). This is not a promise
    of independent physics or a complete downstream cache key. Steps 3-4 must
    reconcile the geometry with generated crust/thermal structure and motion.

    Invalid plans/source drift raise. Expected geometry, memory and cooperative
    time/cancellation refusals return atlas=None and their complete attempt record.
    Wall time is cooperative, not a hard OS/native-call interruption guarantee.
    """
    started = time.perf_counter()
    plan = validate_plan(plan)
    if policy is None:
        policy = LayoutPolicy()
    if type(policy) is not LayoutPolicy:
        raise ContractError('INVALID_LAYOUT_POLICY', 'Explicit LayoutPolicy required.')
    adapter_hash = _source_hash()
    cancellation = _Cancellation(plan['request']['resources']['max_wall_seconds'], cancel)
    # Native imports are lazy: seed/settings preparation needs only stdlib.
    import numpy as np
    from atlas_tectonics import SphericalFrame
    from atlas_tectonics.geometry import GeometryError, _check_cancel
    from atlas_tectonics.resources import WorkBudget, MemoryLimitError
    from atlas_tectonics.planetary_generation import PlanetPartitionSettings, generate_planetary_partition, _runtime
    from atlas_tectonics.plate_layout import _graph, _assign
    from atlas_tectonics.spherical_atlas import build_spherical_atlas
    from atlas_tectonics.reuse import ExecutionContext

    budget = WorkBudget(plan['request']['resources']['max_work_bytes'])
    values = plan['resolved_settings']
    seed = int(plan['streams']['plate_layout'], 16)
    spectrum = sample_area_spectrum(values['plate_count'], plan['streams']['plate_sizes'],
                                   spread=policy.size_log_spread)
    spec = dict(schema=METHOD, status='WORKING NON-CANON',
        scientific_id=plan['scientific_id'], adapter_sha256=adapter_hash,
        contract_binding=plan['binding'], policy=asdict(policy),
        sphere=dict(radius_m=values['radius_m'], frame_id=plan['request']['frame']['id']),
        epoch=plan['request']['epoch'], plate_count=values['plate_count'],
        support_cells=plan['request']['resolution']['support_cells'],
        geometry_seed=plan['streams']['plate_layout'], area_spectrum=spectrum,
        capabilities=dict(candidate_geometry=True, generate_world=False,
                          evolve_world=False, native_restart=False),
        acceptance=dict(geometry='NOT_CHECKED', outline_morphology='NOT_ACCEPTED',
                        motion_history='NOT_ACCEPTED', geological_validation=False))
    report = dict(schema='atlas.layout-candidate-result.v1', plan_id=plan['plan_id'],
                  attempt=1, specification=spec, status='NOT_STARTED', atlas_id=None,
                  geometry_id=None, rejection=None)
    atlas = None
    # Same native identity admission as generate_plate_layout. Exact runtime/code
    # guards cover the reused private cut helpers; no copied/monkeypatched method.
    import atlas_tectonics.plate_layout as native_layout
    source_bytes = sum(p.stat().st_size for p in Path(native_layout.__file__).parent.glob('*.py'))
    try:
        _check_cancel(cancellation)
        with budget.reserve(8*source_bytes+262144, category='new-layout-identity'):
            with ExecutionContext() as context:
                spec['execution_id'] = context.identity
                spec['runtime'] = _runtime()
                try:
                    sphere = SphericalFrame(values['radius_m'], plan['request']['frame']['id'])
                    support = generate_planetary_partition(sphere,
                        PlanetPartitionSettings(spec['support_cells'], seed),
                        budget=budget, cancel=cancellation)
                    spec['support_geometry_id'] = support.geometry_id
                    spec['support_generation'] = support.descriptor()['source_bindings']
                    with budget.reserve(support.retained_bytes_estimate+4096*len(support.patches)+65536,
                                        category='new-layout-cut'):
                        targets = np.asarray(spectrum['target_fractions'])
                        labels = _assign(_graph(support), support.patch_areas_sr,
                                         targets, seed, cancellation)
                        fractions = np.bincount(labels, weights=support.patch_areas_sr,
                            minlength=values['plate_count'])/(4*math.pi)
                        relative = np.abs(fractions-targets)/targets
                        error = float(np.abs(fractions-targets).sum())
                        spec.update(realised_area_fractions=fractions.tolist(),
                                    area_l1_error=error, relative_area_errors=relative.tolist(),
                                    poorly_resolved_ranks=[int(i) for i,t in enumerate(targets)
                                        if 4*math.pi*t < 4*support.patch_areas_sr.max()])
                        if float(relative.max()) > policy.max_relative_area_error:
                            raise GeometryError('Small plate unresolved: relative area error exceeds requested limit.')
                        if error > policy.max_area_l1_error:
                            raise GeometryError('Area spectrum unresolved: L1 error exceeds requested limit.')
                        patches = tuple(replace(p, region_id=f'plate-{labels[i]:06d}',
                                                plate_id=f'plate-{labels[i]:06d}')
                                        for i,p in enumerate(support.patches))
                        spec['acceptance']['geometry'] = 'CHECKED'
                        candidate = build_spherical_atlas(sphere,
                            dict(zip(support.vertex_ids, support.vertex_directions)), patches,
                            budget=budget, cancel=cancellation,
                            source_bindings={'new_world_layout': spec})
                        _check_cancel(cancellation)
                        _source_hash()
                        validate_plan(plan)
                        atlas = candidate
                finally:
                    context.verify()
        report.update(status='CANDIDATE_NOT_GEOLOGICALLY_ACCEPTED', atlas_id=atlas.atlas_id,
                      geometry_id=atlas.geometry_id)
    except (GeometryError, MemoryLimitError, CancelledError) as exc:
        atlas = None
        if isinstance(exc, MemoryLimitError):
            reason = 'MEMORY_LIMIT'
        elif isinstance(exc, CancelledError):
            reason = cancellation.reason or 'CANCELLED'
        else:
            reason = 'GEOMETRY_REFUSED'
        report.update(status='REJECTED', rejection=dict(code=reason, message=str(exc)))
        if hasattr(exc, 'attempts') and hasattr(exc, 'rejections'):
            report['rejection']['support_attempts'] = exc.attempts
            report['rejection']['support_rejections'] = dict(exc.rejections)
        spec['acceptance']['geometry'] = 'NOT_PUBLISHED'
    _source_hash()
    report['candidate_request_id'] = hashlib.sha256(canonical_bytes(dict(
        scientific_id=plan['scientific_id'], policy=asdict(policy), method=METHOD,
        adapter_sha256=adapter_hash))).hexdigest()
    # This request key alone is not a cache admission identity. Successful native
    # atlases bind the complete execution/runtime and exact geometry bytes.
    report['request_id_is_cache_key'] = False
    report['elapsed_seconds'] = time.perf_counter()-started
    report['resources'] = budget.statistics()
    return LayoutCandidate(atlas, report)
