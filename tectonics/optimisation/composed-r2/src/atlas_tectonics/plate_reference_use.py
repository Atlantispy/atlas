"""Audited PB2002 use restrictions, separate from unchanged strict checks.

A source can support labelled observations without being an exact two-owner mesh.
This module never repairs a source, changes a tolerance, or accepts a generator.
The fixed post-audit policy is bound to exact source and protocol identities.
Prepare once, then reuse immutable indexes for bounded reference selections.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType

import numpy as np

from .geometry import _check_cancel
from .plate_reference import AREA_ROWS
from .plate_reference_acceptance import (
    OBSERVATION_SCALES_M, WITHHELD_MORPHOLOGY_PLATES, _edge_key,
    compare_distributions, evaluation_record, reference_dataset_report,
    reference_protocol, record_role, write_report_snapshot,
)
from .plate_reference_dataset import (
    PB2002_COMMIT, PB2002Dataset, ReferenceDataError,
    _json, load_pb2002, step_motion,
)
from .resources import select_budget

_POLICY_PATH = Path(__file__).resolve().parents[2] / 'cases' / 'plate_reference_use_policy.json'
_POLICY_SHA256 = '89c7ad4421b0a796234f24650b1e0fa9c27e520eb4caaf85fd5988fb9aa6b26d'
_SHAPE_FIELDS = {
    'compactness': 'sampled_compactness',
    'reflex_turning_radians': 'reflex_turning_radians',
    'boundary_length_radians': 'sampled_perimeter_radians',
}
_ALL_USES = frozenset((
    'source_diagnostics', 'published_area_calibration', 'outline_area_diagnostics',
    'ordinary_surface_morphology', 'table_outline_equivalence',
    'source_boundary_kinematics', 'surface_neighbour_count', 'closed_orogen_metrics',
    'unique_surface_topology', 'complete_deformation_mask', 'historical_validation',
    'independent_model_validation', 'geological_generator_acceptance',
))


def _hash(value) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _freeze(value):
    """Freeze a shared JSON tree once; indexes retain references, not duplicate rows."""
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _detach(value):
    if isinstance(value, Mapping):
        return {k: _detach(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_detach(v) for v in value]
    return value


def reference_use_policy() -> dict:
    """Return the identified policy, refusing unreviewed local changes.

    This checksum is version/integrity control, not a security signature. A new
    policy requires a separately reviewed version, not editing exclusions at run
    time to improve a candidate's score.
    """
    if any(p.is_symlink() for p in (_POLICY_PATH, *_POLICY_PATH.parents)):
        raise ReferenceDataError('linked reference-use policy is refused')
    with _POLICY_PATH.open('rb') as stream:
        raw = stream.read(131073)
    if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != _POLICY_SHA256:
        raise ReferenceDataError('reference-use policy identity mismatch; review a new version')
    policy = json.loads(raw)
    policy['policy_id'] = _POLICY_SHA256
    return policy


def _validate_reviewed_report(report: dict, policy: dict) -> None:
    """Fail closed on an unknown finding or a changed reference-processing contract.

    Known *source-use* restrictions are not numerical waivers. In particular,
    independent area formulae, motion checks and closure keep their original
    bounds. The expected ON table disagreement is never called a strict pass.
    """
    expected = policy['expected_strict_findings']
    if (report.get('schema') != 'atlas.plate-reference-report.r1.v1'
            or report.get('status') != 'REFERENCE_DISCREPANCIES_REQUIRE_REVIEW'
            or report.get('full_dataset_tested') is not True
            or report.get('reference_processing_completed') is not True
            or report.get('generated_planet_assessed') is not False
            or report.get('geological_model_accepted') is not False
            or report.get('purpose') != 'SOURCE_AND_NUMERICAL_VERIFICATION_ONLY'):
        raise ReferenceDataError('unexpected strict report state; no scoped use approved')
    if (report['dataset']['dataset_id'] != policy['dataset_id']
            or report['dataset']['commit'] != PB2002_COMMIT
            or policy['source_commit'] != PB2002_COMMIT
            or report['protocol'] != reference_protocol()
            or report['protocol']['protocol_id'] != policy['protocol_id']):
        raise ReferenceDataError('dataset or protocol changed; new source-use review required')
    if report['measurement_coverage'] != expected['measurement_coverage']:
        raise ReferenceDataError('reference coverage changed')
    actual = sorted(_hash(x) for x in report['connectivity']['incidence_discrepancies'])
    if actual != expected['incidence_fingerprints']:
        raise ReferenceDataError('unknown or changed connectivity finding')
    geometry = report['source_geometry']
    if (sorted(x['source_id'] for x in geometry['unresolved'])
            != sorted(expected['unresolved_source_ids'])
            or geometry['exact_repeated_coordinate_count'] != expected['exact_repeated_coordinates']):
        raise ReferenceDataError('unknown or changed source geometry finding')
    if (report['motion']['issues'] or report['motion']['steps_checked'] != 5819
            or report['source_step_alignment_issues']):
        raise ReferenceDataError('motion or step alignment failed; cannot qualify source use')
    closure = report['area_closure_error_sr']
    if (closure is None or not math.isfinite(closure)
            or abs(closure) > report['source_rounding_area_envelope_sr']):
        raise ReferenceDataError('planetary area closure failed')
    numeric = report['numerical_issues']
    if (len(numeric) != 1 or numeric[0]['kind'] != 'area'
            or numeric[0]['plate'] != 'ON'):
        raise ReferenceDataError('unknown numerical finding')
    table = dict(AREA_ROWS)
    if table.get('ON') != policy['decisions'][0]['table_area_sr']:
        raise ReferenceDataError('reviewed table transcription changed')
    if {row['plate_id'] for row in report['plates']} != set(table):
        raise ReferenceDataError('reference plate inventory changed')
    for row in report['plates']:
        area_values = (row['metrics']['area_steradians'], row['metrics']['independent_area_steradians'],
                       row['metrics']['area_formula_disagreement_sr'], row['area_formula_bound_sr'],
                       row['area_difference_sr'], row['source_area_rounding_bound_sr'])
        if (not all(math.isfinite(v) for v in area_values)
                or row['status'] != 'MEASURED' or row['table_area_sr'] != table[row['plate_id']]
                or row['metrics']['area_formula_disagreement_sr'] < 0
                or row['area_formula_bound_sr'] <= 0 or row['source_area_rounding_bound_sr'] <= 0
                or row['metrics']['area_formula_disagreement_sr'] > row['area_formula_bound_sr']):
            raise ReferenceDataError('independent area check failed')
        discrepancy = abs(row['area_difference_sr']) > row['source_area_rounding_bound_sr']
        if discrepancy != (row['plate_id'] == 'ON'):
            raise ReferenceDataError('table/outline discrepancy changed')
        scales = row.get('multiscale', {}).get('scales', [])
        if [s['scale_m'] for s in scales] != list(OBSERVATION_SCALES_M):
            raise ReferenceDataError('complete registered scale observations required')
        for scale in scales:
            if [p['phase'] for p in scale['phases']] != [0., .5]:
                raise ReferenceDataError('registered sampling phases changed')
            for p in scale['phases']:
                if p['status'] == 'UNRESOLVED_AT_SCALE':
                    continue
                if p['status'] != 'MEASURED':
                    raise ReferenceDataError('unknown scale-measurement outcome')
                # MS is not a simple surface ring. Its diagnostic values remain
                # in the strict report but must never enter ordinary morphology.
                if row['plate_id'] != 'MS':
                    c = p['sampled_compactness']
                    if not math.isfinite(c) or not 0 <= c <= 1 + 64*np.finfo(float).eps:
                        raise ReferenceDataError('nonphysical compactness outside reviewed quarantine')


@dataclass(frozen=True, slots=True, init=False)
class ReferenceUsePlan:
    """Caller-owned, immutable source/use indexes built from verified bytes.

    Construction allocations join WorkBudget; returned capacity is caller-owned,
    as for PB2002Dataset. This is not a promise to cap process RSS. No global
    cache, online lookup, persistent index or additional numerical backend exists.
    """
    _dataset: PB2002Dataset
    _report: Mapping
    _policy: Mapping
    _plate_rows: Mapping
    _orogen_rows: Mapping
    _curves: Mapping
    _poles: Mapping
    _issues_by_edge: Mapping
    _boundary_edges: frozenset
    _scope_ids: Mapping
    report_id: str
    policy_id: str
    dataset_id: str

    def __init__(self, directory, *, budget=None, cancel=None):
        _check_cancel(cancel)
        with select_budget(budget).reserve(16 << 20, category='plate-reference-use'):
            policy = reference_use_policy()
            dataset = load_pb2002(directory, budget=budget, cancel=cancel)
            report = reference_dataset_report(dataset, budget=budget, cancel=cancel)
            _validate_reviewed_report(report, policy)
            frozen = _freeze(report)
            # Exact canonical keys are prepared once. Repeated eligibility
            # queries do not walk all 5,819 source steps or allocate geometry.
            boundary_edges = set()
            for curve in dataset.boundaries:
                _check_cancel(cancel)
                xy = curve.coordinates
                boundary_edges.update(_edge_key(a, b) for a, b in zip(xy[:-1], xy[1:]))
            values = {
                '_dataset': dataset, '_report': frozen, '_policy': _freeze(policy),
                '_boundary_edges': frozenset(boundary_edges),
                '_plate_rows': MappingProxyType({p['plate_id']: p for p in frozen['plates']}),
                '_orogen_rows': MappingProxyType({p['source_record']: p for p in frozen['orogens']}),
                '_curves': MappingProxyType({(c.kind, c.record_number): c
                    for c in dataset.plates + dataset.boundaries + dataset.orogens}),
                '_poles': MappingProxyType({p.plate_id: p for p in dataset.poles}),
                '_issues_by_edge': MappingProxyType({tuple(tuple(v) for v in x['finding']['edge']): _freeze(x)
                    for x in policy['connectivity_decisions']}),
                '_scope_ids': MappingProxyType({s: tuple(sorted(p['plate_id'] for p in report['plates']
                    if s == 'source-verification' or
                    (p['plate_id'] in WITHHELD_MORPHOLOGY_PLATES) == (s == 'withheld')))
                    for s in ('development', 'withheld', 'source-verification')}),
                'report_id': _hash(report), 'policy_id': policy['policy_id'],
                'dataset_id': dataset.dataset_id,
            }
            for name, value in values.items():
                object.__setattr__(self, name, value)
            _check_cancel(cancel)

    def strict_report(self) -> dict:
        """Detached original report, including every failed check and raw metric."""
        return _detach(self._report)

    def _plate(self, plate_id):
        if not isinstance(plate_id, str) or plate_id not in self._plate_rows:
            raise ReferenceDataError('known plate identifier required')
        return self._plate_rows[plate_id]

    def require_use(self, use: str, *, plate_id=None, orogen_record=None) -> None:
        """Refuse unsupported semantics, not just unavailable numerical values."""
        if not isinstance(use, str) or use not in _ALL_USES:
            raise ReferenceDataError('unknown reference use')
        restrictions = self._policy['restrictions']
        if use in restrictions['unavailable_global_uses']:
            raise ReferenceDataError(f'{use}: not supported by this reference-use policy')
        plate_use = {
            'ordinary_surface_morphology': 'ordinary_surface_morphology_excluded',
            'table_outline_equivalence': 'table_outline_equivalence_excluded',
            'surface_neighbour_count': 'surface_neighbour_count_excluded',
        }
        if use in plate_use:
            self._plate(plate_id)
            if orogen_record is not None:
                raise ReferenceDataError('unexpected orogen selector')
            if plate_id in restrictions[plate_use[use]]:
                raise ReferenceDataError(f'{plate_id}: {use} restricted by source review')
        elif use == 'closed_orogen_metrics':
            if plate_id is not None or type(orogen_record) is not int or orogen_record not in self._orogen_rows:
                raise ReferenceDataError('known integer orogen record required')
            if orogen_record in restrictions['closed_orogen_metrics_excluded']:
                raise ReferenceDataError('open orogen: closed-polygon use is unavailable')
        elif plate_id is not None or orogen_record is not None:
            raise ReferenceDataError('unexpected record selector for dataset-level use')

    def raw_curve(self, kind: str, number: int):
        """Explicit raw-evidence route; no eligibility claim or coordinate repair."""
        if kind not in ('plate', 'boundary', 'orogen') or type(number) is not int:
            raise ReferenceDataError('known curve kind and integer record required')
        try:
            return self._curves[kind, number]
        except KeyError as exc:
            raise ReferenceDataError('unknown source curve record') from exc

    def orogen_metrics(self, number: int) -> dict:
        self.require_use('closed_orogen_metrics', orogen_record=number)
        return dict(source_record=number, metrics=_detach(self._orogen_rows[number]['metrics']),
                    policy_id=self.policy_id, role='WITHHELD_WITHIN_MODEL',
                    use='SOURCE_NUMERICAL_DIAGNOSTICS_ONLY', complete_global_mask=False)

    def source_step(self, number: int) -> dict:
        if type(number) is not int or not 1 <= number <= len(self._dataset.steps):
            raise ReferenceDataError('known integer source step required')
        step = self._dataset.steps[number-1]
        value = step_motion(step, self._poles)
        return dict(source_number=number, source_boundary=step.boundary,
                    source_class=step.kind, source_in_orogen=step.in_orogen,
                    source_flag_recomputed=False, metrics=value,
                    evidence_role=record_role(observable='motion', boundary=step.boundary, step_number=number),
                    use='SOURCE_KINEMATIC_RECORD_NOT_UNIQUE_SURFACE_EDGE',
                    policy_id=self.policy_id, dataset_id=self.dataset_id)

    def require_surface_edge(self, a, b) -> None:
        """Local two-owner incidence only; never a global-mesh approval.

        Coordinates must match an existing exact source edge; near points are not
        snapped. All five problematic spans are refused, including the 2 m gap.
        """
        from .plate_reference_dataset import lonlat_vectors
        from ._validation import input_shape
        # Inspect before conversion: an oversized array, a masked value or a
        # string/bool must not allocate workspace or become a real coordinate.
        if input_shape(a, 'edge start') != (2,) or input_shape(b, 'edge end') != (2,):
            raise ReferenceDataError('two real coordinates per source-edge endpoint required')
        points = np.asarray([a, b], dtype=float)
        lonlat_vectors(points)  # Finite two-coordinate and latitude validation.
        key = _edge_key(points[0], points[1])
        if key in self._issues_by_edge:
            raise ReferenceDataError('reviewed nonstandard/missing source edge; surface use refused')
        if key not in self._boundary_edges:
            raise ReferenceDataError('unknown exact source boundary edge')

    def summary(self) -> dict:
        restrictions = _detach(self._policy['restrictions'])
        return dict(
            schema='atlas.plate-reference-use-assessment.r1.v1',
            status='ACCEPTED_FOR_SCOPED_REFERENCE_USE',
            dataset_id=self.dataset_id, policy_id=self.policy_id,
            protocol_id=self._policy['protocol_id'], strict_report_sha256=self.report_id,
            strict_status=self._report['status'], strict_reference_gate_passed=False,
            geological_model_accepted=False, r2_started=False,
            coverage=dict(self._policy['coverage_requirements'],
                surface_neighbour_count_eligible=52-len(restrictions['surface_neighbour_count_excluded'])),
            restrictions=restrictions,
            decisions=_detach(self._policy['decisions']),
            connectivity_decisions=_detach(self._policy['connectivity_decisions']),
            sources=_detach(self._policy['sources']),
            interpretation='Reference-use review complete for these finite scopes; not perfect source geometry or accepted generated tectonics.',
            missing_later_validation=_detach(self._report['unavailable_gates']),
        )

    def observations(self, *, metric: str, split: str, run_id: str,
                     scale_m=None, phase=None, area_basis=None, budget=None, cancel=None) -> dict:
        """Select every eligible reference in a registered split, disclosing omissions.

        Areas require explicit table/outline provenance and always use the full
        previously-exposed 52-record calibration inventory. They are NOT silently
        renormalised after a quality exclusion. Morphology requires one physical
        scale AND sampling phase; MS never enters that population.
        """
        _check_cancel(cancel)
        if not isinstance(metric, str) or metric not in ('area_fraction', 'neighbour_count', *_SHAPE_FIELDS):
            raise ReferenceDataError('unsupported qualified observable')
        if not isinstance(split, str) or split not in self._scope_ids:
            raise ReferenceDataError('explicit registered split required')
        purpose = 'source-verification' if split == 'source-verification' else 'validation' if split == 'withheld' else 'calibration'
        audit = evaluation_record(self.dataset_id, self.dataset_id, split=split, run_id=run_id, purpose=purpose)
        if metric == 'area_fraction':
            if split == 'withheld' or area_basis not in ('published_table', 'source_outline'):
                raise ReferenceDataError('areas are exposed; explicit table or outline basis required')
            ids = tuple(sorted(self._plate_rows))
        else:
            if area_basis is not None:
                raise ReferenceDataError('area basis applies only to area observations')
            ids = self._scope_ids[split]
        if metric in _SHAPE_FIELDS:
            if (isinstance(scale_m, (bool, str)) or scale_m not in OBSERVATION_SCALES_M
                    or isinstance(phase, (bool, str)) or phase not in (0., .5)):
                raise ReferenceDataError('registered physical observation scale and phase required')
        elif scale_m is not None or phase is not None:
            raise ReferenceDataError('area/adjacency do not take morphology sampling settings')
        with select_budget(budget).reserve(256 << 10, category='plate-reference-selection'):
            values, selected, excluded, unresolved = [], [], [], []
            for pid in ids:
                _check_cancel(cancel)
                row = self._plate_rows[pid]
                if metric == 'area_fraction':
                    value = row['table_area_sr'] if area_basis == 'published_table' else row['metrics']['area_steradians']
                    value /= 4*math.pi  # Physical sphere, NOT sum of surviving records.
                else:
                    use = 'surface_neighbour_count' if metric == 'neighbour_count' else 'ordinary_surface_morphology'
                    key = use + '_excluded'
                    if pid in self._policy['restrictions'][key]:
                        excluded.append(dict(plate_id=pid, reason=use + ': restricted by source review'))
                        continue
                    if metric == 'neighbour_count':
                        value = len(self._report['connectivity']['neighbours'][pid])
                    else:
                        scale = next(s for s in row['multiscale']['scales'] if s['scale_m'] == scale_m)
                        item = next(p for p in scale['phases'] if p['phase'] == phase)
                        if item['status'] == 'UNRESOLVED_AT_SCALE':
                            unresolved.append(dict(plate_id=pid, reason='UNRESOLVED_AT_SCALE'))
                            continue
                        value = item[_SHAPE_FIELDS[metric]]
                if not math.isfinite(value) or value < 0:
                    raise ReferenceDataError('invalid qualified reference observation')
                values.append(value); selected.append(pid)
            return dict(schema='atlas.qualified-reference-observations.r1.v1',
                metric=metric, values=values, plate_ids=selected, split=split,
                expected_population_count=len(ids), included_count=len(selected),
                excluded=excluded, unresolved=unresolved, observation_scale_m=scale_m,
                sampling_phase=phase, area_basis=area_basis, normalisation='4*pi for area; no subset renormalisation',
                policy_id=self.policy_id, strict_report_sha256=self.report_id, audit=audit,
                warnings=['Within-PB2002 evidence, not an independent model.',
                          'ON published area and source-outline area remain different; never interchangeable.',
                          'Exclusions are source-structural, not chosen from candidate errors.'],
                geological_model_accepted=False)

    def compare(self, candidate_values, *, candidate_id: str, candidate_count: int,
                unresolved_candidate: int, metric: str, split: str, run_id: str,
                reference_scale_m=None, candidate_scale_m=None, reference_phase=None,
                candidate_phase=None, area_basis=None, budget=None, cancel=None) -> dict:
        """Qualified comparison; original generic numerical primitive stays unchanged.

        Candidate inputs must include every resolved object in the declared
        population. Counts make missing results explicit, but are not a claim to
        authenticate the scientific provenance of caller-supplied candidates.
        """
        from ._validation import input_shape, read_array
        _check_cancel(cancel)
        shape = input_shape(candidate_values, 'candidate population')
        if (len(shape) != 1 or type(candidate_count) is not int or candidate_count <= 0
                or type(unresolved_candidate) is not int or unresolved_candidate < 0
                or shape[0] + unresolved_candidate != candidate_count):
            raise ReferenceDataError('candidate population and explicit unresolved counts disagree')
        if metric in _SHAPE_FIELDS:
            if (isinstance(candidate_scale_m, (bool, str))
                    or isinstance(candidate_phase, (bool, str))
                    or candidate_scale_m != reference_scale_m or candidate_phase != reference_phase):
                raise ReferenceDataError('candidate and reference observation scale/phase must match')
        elif candidate_scale_m is not None or candidate_phase is not None:
            raise ReferenceDataError('unexpected candidate morphology settings')
        observations = self.observations(metric=metric, split=split, run_id=run_id,
            scale_m=reference_scale_m, phase=reference_phase, area_basis=area_basis, budget=budget, cancel=cancel)
        if split == 'source-verification':
            raise ReferenceDataError('candidate comparison requires development or withheld, not source inspection')
        with select_budget(budget).reserve(32*shape[0] + 16384, category='plate-reference-candidate'):
            candidate = read_array(candidate_values, 'candidate values', ndim=1, nonnegative=True)
            if metric == 'compactness' and np.any(candidate > 1 + 64*np.finfo(float).eps):
                raise ReferenceDataError('candidate compactness exceeds a simple spherical region bound')
            if metric == 'area_fraction' and np.any(candidate > 1):
                raise ReferenceDataError('candidate area fraction exceeds the entire sphere')
            if metric == 'neighbour_count' and np.any(candidate != np.floor(candidate)):
                raise ReferenceDataError('candidate neighbour counts must be integers')
            result = compare_distributions(observations['values'], candidate, metric=metric,
                dataset_id=self.dataset_id, candidate_id=candidate_id, split=split, run_id=run_id,
                reference_scale_m=reference_scale_m, candidate_scale_m=candidate_scale_m,
                unresolved_reference=len(observations['excluded'])+len(observations['unresolved']),
                unresolved_candidate=unresolved_candidate, budget=budget, cancel=cancel)
        result.update(reference_use_policy_id=self.policy_id, qualified_reference=observations,
                      candidate_population_count=candidate_count, sampling_phase=reference_phase,
                      scientific_coverage='restricted reference scope, not full-planet validation')
        # The original evaluation identity predates the extra policy fields;
        # bind the complete qualified result for persistence/downstream cache keys.
        result['qualified_comparison_id'] = _hash(result)
        return result

    def save_strict_report(self, store, *, budget=None, cancel=None) -> dict:
        """Reuse ArrayStore's lossless report path; never store an unversioned waiver."""
        key = write_report_snapshot(self.strict_report(), store, budget=budget, cancel=cancel)
        return dict(strict_report_key=key, reference_use_policy_id=self.policy_id,
                    dataset_id=self.dataset_id, scoped_assessment=self.summary())


def prepare_reference_use(directory, *, budget=None, cancel=None) -> ReferenceUsePlan:
    """Verify original bytes, rerun strict checks, then prepare the reviewed scope."""
    return ReferenceUsePlan(directory, budget=budget, cancel=cancel)
