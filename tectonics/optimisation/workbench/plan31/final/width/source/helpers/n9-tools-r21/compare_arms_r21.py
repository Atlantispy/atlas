"""IV1 replay: compare the before and after arms field by field and write one verdict file.

Usage: compare_arms.py --before ATTEMPT DUMPS PROFILE PROFILE_SHA256 --after ATTEMPT DUMPS PROFILE PROFILE_SHA256
                       --observer-sha256 HEX [--field-contract PATH SHA256] --out NEW_JSON
  ATTEMPT  the arm's route (1) output directory (stage-root.json, stage-interval.json, run-*/, reader-*/)
  DUMPS    folder with i0/ and i1/, the dump_arm_r3.py outputs for intervals 0 and 1
  PROFILE, PROFILE_SHA256  the arm's pinned profile file; its output directory must be ATTEMPT
  --observer-sha256  the independently pinned dump_arm_r3.py SHA-256 (a dump's own claim is not enough)
  --field-contract   the affected-field/error contract for the selected composition (D01); without it no
                     non-exact change outside Addendum E has an applicable bound, so none can PASS
Imports nothing from the runtime (json and numpy only), so it may run with -I.

r19 (successor of r18 ec477f2b): an
evidenced observer interruption removes only that interval's dump comparison. Stage proofs, later stage
classification and FAIL rules, the cross-stage chain and the width gate are still checked, so an
established FAIL outranks VOID-OBSERVER (C1). The interrupted invocation must name an ordinary file with
the pinned observer bytes, and its retained termination record must echo the exact invocation (C2). An
external event explains a guarded stop only as an acknowledged/observed operator_cancel agreeing with the
guard's retained first trigger user_cancel, with confirmed exit and complete cleanup (guard r3 trigger()
keeps the first reason; guardian_failure overwrites it). host_restart has no independent host/execution
binding in this schema and a pre-start claim has no guard to agree with: both stay VOID-SUSPECT.

r20 (successor of r19 423467e0): an unresolved peer no longer ends
the stage walk. Every independently proved claimant keeps its stage proofs, its cross-stage chain and its own
interval width gate, and each later stage passes through the ordinary per-stage refusal/resource rules among
the arms still live there; observer, dump and cross-arm comparisons still need both corresponding proofs.
host_restart is an evidence path this schema does not support (no independent host/execution binding), not a
Policy v2 exclusion; a trace-free pre-start claim is retained as an explicit no-workload outcome, still
VOID-SUSPECT because the event label alone does not establish the refusal cause.

r18 (successor of r16 e507beee; causal schema r1, Policy v2): optional closed causal
evidence bundles (--causal-evidence ARM BUNDLE SHA256, with r2 selected pins naming each evidence producer and
the complete selected repeat-approval set). Any supplied record that is malformed,
unpinned, misbound to the arm/attempt/profile/manifest/step process or guard nonce, or whose retained files
changed, is FAIL (proof/integrity). A valid operator_cancel/host_restart that was acknowledged or independently
observed turns only a still-unresolved stop of its own bound step into VOID-ENVIRONMENT; a proven or
provenance-unproved stop FAIL, a missing stage, an automatic launcher action or a merely requested event is
unchanged. An observer interruption explains only an absent dump of that exact pinned observer, interval and
process, bound to an explaining external event and to the re-derived sealed proof pins: VOID-OBSERVER, and
later claimed stages are still proved. A present FAILED or malformed dump stays FAIL. One diagnostic repeat
(ordinal 1, new attempt, unchanged non-location profile keys, retained machine conditions and no-cheaper-
reproduction finding, exactly one approval per pinned approver) caps the verdict at REVIEW. Without evidence
r18 behaves as r16. VOID precedence: SUSPECT, then ENVIRONMENT, then OBSERVER; all exit 4.

r14 implements the accepted D1-D8 outcome (7972b757): typed, stage-bound capture maps; mandatory RUNNING
tracking; the fully proved r12 RSS-latch exception for cancel-present captures; complete applicable root
families even when omitted; explicit zero-row route REVIEW; and capped stable JSON reads. Both readiness
and scientific acceptance remain outside this isolated successor. Historical revision notes follow.

r13 (successor of compare_arms_r12 240e827b; N9 build under CAPTURE-INVENTORY-SCHEMA-r2 71b18315,
ROOT-PARTITION-ROUTES-r2 ea63af95 and CONTRACT-REVIEW-r2 d8f7be22, WORKING NON-CANON):
  Capture provenance. A stop-dependent FAIL (r12 stop_cause: a bound rss_limit or a ledger refusal) now also
  needs the launching parent's retained step capture (lf-r1 launch_fresh_interval): the arm's captures map
  (--captures ARM MAP SHA256), its entry, the exclusive capture and step launch record, the explicit
  arm/stage/interval/step/attempt/output binding, the selected generation pins (--selected-pins PATH SHA256:
  LF launcher, LM helper, guard and the runner/reader entry point), the retained launch digest, tracking
  launcher_pid, the lifecycle (RUNNING, a confirmed terminal guard status), every captured file's retained bytes
  and the guard/control/abort nonce. Any unmet check makes that claim VOID-SUSPECT naming the check; r12's own
  checks still run first and are never upgraded. File mtimes are diagnostic only. r14 narrows r13's blanket
  cancellation VOID only for a retained RSS latch satisfying every unchanged r12 proof and capture check.
  Deterministic, proof and numerical FAILs are unaffected.
  Root routes (interval 0). 'exterior-fv:' arrays bind to the reader-proved state and mesh records by the
  PreparedSpatialOwner._issue/restore snapshot identity (state_id). With the root runner record's published root
  and, when the interval stage is proved, its completed root_metadata (sha256 = root_metadata_sha256), a
  'root'-kind head also binds: the collar fields and 'exterior_heat:' arrays by RegionalCollarState.result_id
  (fields_id, native_state_id, exterior_heat_id); 'partition-record:' bytes by the differential_partition
  record_blobs refs; 'partition-dag:' and 'spatial-mesh:' alias name sets exactly against the one compact
  reference's array_bindings (a missing or extra alias FAILs). Exact alias targets need each alias's manifest
  descriptor digest, which r3 dumps do not record: those aliases stay REVIEW. Successor-only families at a
  proved 'root' head FAIL; a 'migrated-root' or unproved kind, or no proved root metadata, stays REVIEW.

r12 (successor of compare_arms_r11 ccc35caa): an unusable non-empty tracking output (for example
an escaped embedded NUL, on which Path.resolve raises ValueError) returns the named tracking-output binding
refusal instead of escaping; same_path itself is unchanged for the proof checks.

r11 (successor of compare_arms_r10 7cbcf7f6): LM _track always records output=str(p['out']), the guarded step directory of
Route 1 paths. guard_binding now requires a non-empty string tracking output naming attempt/<step folder>
(same_path); missing, non-string or another step's output is VOID-SUSPECT. Hash edges remain unauthenticated.

r10 (successor of compare_arms_r9 ae683759):
r8 proved a claimant only at the first unresolved stage and then stopped traversal, so a reference claiming an
adopted interval after a candidate root stop was never proved (VOID, fail empty). Each arm's claimed stages are now
proved from the first unresolved stage to the last stage, independently of whether a paired stage exists for the
numerical comparison; a never-reached stage is recorded, not proved, and demands no adoption proof. The arm's
traversal ends at its first unclaimed stage or proof failure; its chain is proved once every stage is claimed.

r9 (successor of compare_arms_r8 57fb338a, Plan 04 guard/abort binding): an rss_limit stop is FAIL only when
the guard receipt is bound to its own guarded run by the guard's lifecycle and identity records
(private_heat_continuation_guard_r3 supervise/_terminal_main, as copied in composed-r2 9a2d7e8b): workload exit
confirmed (HARD_STOP_FAILED leaves it unconfirmed and is no longer an exited status), an empty job after cleanup
with no cleanup error, the guard's recorded terminal update of the step receipt, a guard-control record with the
same nonce and registered parent, launcher tracking (LM _track) naming the same parent, job and guardian, a step
receipt whose supervisor block equals the guard receipt's and which carries the guard's own failure row. Any
unmet binding is VOID-SUSPECT naming it. Guard, control, tracking and abort files are still not authenticated by
a hash edge.

r8 (successor of compare_arms_r7 a8b2c503): when one arm has no usable outcome at a stage,
each arm claiming adoption (or a gate stop) there is still proved, with its proved stages chained: a missing or
broken proof is FAIL (proof/integrity) alongside the peer's retained stop evidence, never hidden by the VOID. An
arm that never adopted is not asked for an adoption proof, and an unattributed stop stays VOID-SUSPECT.

r7 (successor of compare_arms_r6 27861b4f, Plan 04 step 5): the 47 retained cases (test_cases_r7.py) found that
a reader-proved record identity whose record is not dumped (the partition) was mapped across the arms but
never compared, so a changed partition passed. Such an identity that differs between the arms is now REVIEW.

r6 (successor of compare_arms_r5 0dd06918, Plan 04 step 3 in part) binds the i1 composite arrays: the
'certification-force:' fields by recomputing RegionalMechanicalSnapshot.result_id from the reader-proved
certification record's force metadata and the dumped field digests, against that record's
solution.force_exchange_id; the 'differential-network:' fields by recomputing integration_sphere._identity from
the reader-proved differential record's endpoint_network descriptor (its arrays list fixes order, dtype and shape)
and the dumped bytes, against its network_id. A recomputed identity that differs is a FAIL; an incomplete or
foreign array set is a FAIL. 'exterior-fv:' rows are paired by the reader-proved state.json cells' cell_id
vectors (proof-schema-primary, cell order 1-2): identical vectors compare positionally; vectors that differ only
in order get one exact ID-join permutation (never the byte shortcut); differing ID sets, missing cells or an array
not indexing the cells are REVIEW/FAIL, never a value-derived match. Other families keep their own layouts.
R8 (Policy v2): a candidate-only stop after an adopted reference stage is FAIL
only on retained causal evidence of the guarded runner or reader: an rss_limit guard receipt whose bound trigger
sample exceeds the authorised unchanged limit, or a mandatory logical-ledger refusal shown by both the recorded
failure chain and a positive refusal counter of that same (byte or predicate) ledger at failure, with no guard
trigger. Everything else (cancel markers, free-floor trips, guardian failure, live descendants, raw MemoryError,
unclosed guards, missing records) stays VOID-SUSPECT with its retained reason. No schema yet records an external
event, an observer interruption or an approved diagnostic repeat, so VOID-ENVIRONMENT, VOID-OBSERVER and the
repeat REVIEW are never emitted. The root route remains open.

r5 (successor of compare_arms_r4 01927f18): a refusal flip in either direction FAILs (P1); every reader-checked i1 table
row of a directly dumped group must be dumped (P2); the reader receipt must satisfy the actual finaliser's
predicates (closed independent check set all True, independence, pid, zero reservations, retained scope and the
complete retained/live-producer accounting of reopen_prepared_restart, per the r5-1 refutation),
and the verdict must copy the reader's widths/gate/view/pid (P3, P5); the source proof is closed and bound
to the profile's pinned manifest and its native inventory (P4); widths are closed exact-width tables and the
interval gate is recomputed from the root and interval tables (P5); JSON and arrays carrying non-finite
values never reach equality (N1); field contracts v2 select a full path, not a leaf name (N2). Reader guard
receipts are not re-validated here (they are not in the proof set); the comparator still trusts that the
store-free finaliser ran the guard checks.

r4 (successor of compare_arms_r3 65529cbb, Plan 04 step 1 and part of step 3) re-derives the whole
adoption/verdict/runner/sealed/reader/producer/stage chain of every adopted stage from the proof files,
validates the closed r3 dump schema against it and the external observer pin, requires distinct arms with
common budgets and interpreter, builds the identity bijection only from reader-proved pairs, applies
D01 (field contracts, no generic epsilon) and Addendum E's header rule exactly, and binds i1 arrays to the
reader-checked producer table. Composite force/network bindings, root array bindings, cell-ID pairing and
the R8 causal classes are not implemented: unbound arrays are REVIEW and every non-adopted stage stays
VOID-SUSPECT. This public export keeps the guard below False, as the publication check requires; the
staged private successor sets it True for the two-arm width replay.

Verdict, most severe first:
  FAIL    a proof/integrity failure (a proof file, dump or binding missing, malformed, unknown-keyed, changed
          or inconsistent; wrong observer pin or interpreter; arms not distinct; budgets/interpreter differ);
          an Addendum E header violation; a covered field changed by |delta| >= 2**-11 * radius; the after
          arm's interval width gate failed or is missing; any compare error.
  VOID-SUSPECT  an arm has no independently established outcome (R8 is not implemented).
  REVIEW  structure, label, boolean or identity changes not proved by the reader; any changed value or array
          without an applicable bound from the field contract (historical 512-ulp/2**-20 figures are
          reported as diagnostics only); positional (weak) pairing changes; unbound array families.
  PASS    none of the above.
"""
# r16: Windows descriptor/path timestamps compared within their own APIs; r4 descriptors/typed chunks are checked before alias binding; r3 stays unbound.
# Current r24 integration supersedes the retained historical implementation notes
# above. Root/i1 proof, observer, array and causal repairs are implemented. The
# remaining guard is technical: actual selected composition, producer context and
# applicable source-bound field evidence are required. Collective review is
# deferred by the user and is not claimed as an executable or acceptance result.
import argparse
import copy
import importlib.util
import json
import math
import os
import re
import sys
import stat
from collections.abc import Mapping
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import numpy as np

SCHEMA = 'atlas.private.iv1-arm-compare.r22'
# Released for the condition-4 replay (owner clearance); run() refuses while this is False.
REPAIRS_COMPLETE = False
COMPONENT_PINS = {'field_contracts': '70f94541ca00d71990461207356cd7435f6171745ad2e9fa7c422c467a13689c', 'array_bindings_r5': 'a46c43d7bceae99df2f6a5b61e5a0f30fb1fc8efcace07aff8a71c0bc7f2222c', 'array_compare_r21': 'a010a0cd2cc9f4796f90b824041d2e52d834f555948d6e6ffac908bf876679b0', 'field_provenance': '6fed5ec20b9a7facac22b1afe80305cb1f838765ebb056709e7edd54f61d1071'}


def component(name):
    """Load only the exact selected sibling source bytes, never cached bytecode."""
    from types import ModuleType
    path = Path(__file__).resolve().parent / (name + '.py')
    expected = COMPONENT_PINS.get(name)
    if expected is None:
        raise RuntimeError('unselected comparator component: ' + name)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise RuntimeError('comparator component pin differs: ' + name)
    module = ModuleType('_n9_' + name)
    module.__file__ = str(path)
    module.__spec__ = importlib.util.spec_from_file_location(module.__name__, path)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module
KINDS = ('mesh', 'state')
STAGES = (('root', 0), ('interval', 1))
ADOPTED = 'ADOPTED'
GATE_STOP = 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2'
# R8 evidence (guard r3 and run_fresh_interval): authorised unchanged limits.
GUARD_SCHEMA = 'atlas.private.continuation-guard.r3'
GUARD_LIMITS = {'rss_bytes': 12 << 30, 'free_floor_bytes': 1 << 30}
LOGICAL_BYTES = 16 << 30
# r9: HARD_STOP_FAILED means the exact-handle wait did not confirm workload exit (guard r3 supervise), so it is
# not an exited status; GUARDIAN_FAILED overwrites the reason with guardian_failure.
GUARD_EXITED = frozenset(('PARENT_EXITED', 'HARD_STOPPED'))
GUARD_SUPERVISOR = ('status', 'reason', 'phase', 'cleanup', 'parent', 'guardian')
GUARD_CLEAN = {'remaining': [], 'action_errors': []}
TRACKING_SCHEMA = 'atlas.private.monitored-interval-tracking.r1'
BYTE_REFUSAL = 'projected combined workspace exceeds memory budget'
PREDICATE_REFUSAL = 'projected combined predicate work exceeds allowance'
STEP_RECORDS = {'runner': ('run-%s', 'run'), 'reader': ('reader-%s', 'reopen')}
PRESEAL_REFUSED = 'FAILED_PRESEAL_SEALED_FOR_REVIEW'
ADOPTING = ('adopted', 'gate_stop')
STAGE_STEPS = ('runner', 'reader', 'finalise', 'adopt')
# Route (1) record schemas and statuses (composed-r2 helpers run_fresh_interval / reopen_fresh_restart /
# launch_fresh_interval). Copied, not imported: the comparator stays runtime-free.
PROFILE_SCHEMA = 'atlas.fresh-interval-profile.v1'
PROFILE_KEYS = frozenset({'schema', 'workspace', 'source_manifest', 'native_root', 'import_roots', 'modules',
                          'advance_driver', 'output_directory', 'store_directory', 'completed_query_directory',
                          'completed_query_limits'})
# Keys that may differ between arms (sources and locations); every other profile key must be equal.
PROFILE_SOURCE_KEYS = frozenset({'workspace', 'source_manifest', 'native_root', 'import_roots', 'modules',
                                 'advance_driver', 'output_directory', 'store_directory',
                                 'completed_query_directory'})
RESULT_SCHEMA = 'atlas.fresh-interval-result.v1'
RUNNER_RECORD_SCHEMA = 'atlas.fresh-interval-runner-record.v1'
SEALED_SCHEMA = 'atlas.fresh-interval-sealed-awaiting-reader.v1'
VERDICT_SCHEMA = 'atlas.fresh-interval-reader-verdict.v1'
READER_SCHEMA = 'atlas.fresh-interval-reopen-result.v1'
ADOPTED_SCHEMA = 'atlas.fresh-interval-adopted.v1'
STAGE_SCHEMA = 'atlas.private.fresh-interval-stage.r1'
ADOPTED_STATUS = 'ADOPTED_AFTER_INDEPENDENT_READER'
SEALED_STATUS = {'root': 'SEALED_ROOT_AWAITING_READER', 'interval': 'SEALED_INTERVAL_AWAITING_READER'}
WORKLOAD_STATUS = {'root': 'PASS_ROOT_REOPENED_PENDING_FINALISE',
                   'interval': 'PASS_INTERVAL_REOPENED_PENDING_FINALISE'}
READER_PASS = {'root': 'PASS_ROOT_INDEPENDENT_REOPEN', 'interval': 'PASS_INTERVAL_INDEPENDENT_REOPEN'}
CATALOG = 'interval-catalog.json'
# dump_arm_r3's closed output.
DUMP_SCHEMA = 'atlas.private.iv1-arm-dump.r3-draft'
DUMP_SCHEMA_R4 = 'atlas.private.iv1-arm-dump.r4-draft'
DUMP_KEYS = frozenset({'schema', 'status', 'pid', 'interval', 'profile', 'observer', 'environment', 'errors',
                       'source_proof_before', 'bindings', 'widths', 'width_gate', 'interpreter', 'records',
                       'partition', 'arrays', 'head', 'store_token_before', 'store_token_after', 'loaded_audit',
                       'source_proof', 'environment_after'})
BINDING_NAMES = frozenset({'adopted', 'verdict', 'runner_record', 'reader_receipt', 'producer_receipt',
                           'stage_record', 'catalog'})
ENV_KEYS = frozenset({'executable', 'executable_sha256', 'version', 'version_info', 'implementation', 'cache_tag',
                      'prefix', 'base_prefix', 'platform', 'byteorder', 'flags', 'dont_write_bytecode', 'argv',
                      'cwd', 'path_at_start', 'python_environment'})
ALLOWED_PYTHON_ENV = {'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': None}
REQUIRED_FLAGS = {'no_user_site': 1, 'safe_path': True, 'isolated': 0, 'ignore_environment': 0,
                  'hash_randomization': 0, 'dont_write_bytecode': 1}
ARRAY_KEYS = frozenset({'name', 'file', 'dtype', 'shape', 'sha256', 'nbytes'})
ARRAY_KEYS_R4 = ARRAY_KEYS | {'descriptor', 'descriptor_sha256'}
DUMP_KEYS_R4 = DUMP_KEYS | {'store_limits'}
DUMP_KEYS_R5 = DUMP_KEYS_R4 | {'decoders'}      # r5 dumps: named decoder modules (array_bindings_r5)
RECORD_ARRAY = 'spatial-record:'
# The i1 reader-checked producer table (completed_endpoint.array_records) and how head names map to it.
GROUPS = frozenset({'collar', 'native', 'exterior', 'source_audit', 'full_collar', 'spatial_audit'})
DIRECT_PREFIXES = (('exterior_heat:', 'full_collar', False), ('exterior-fv:', 'exterior', True),
                   ('source-audit:', 'source_audit', True), ('spatial-audit:', 'spatial_audit', True))
FORCE_PREFIX, NETWORK_PREFIX = 'certification-force:', 'differential-network:'
COMPOSITE_PREFIXES = (FORCE_PREFIX, NETWORK_PREFIX)
NETWORK_ARRAY = 'sphere.'
EXTERIOR_PREFIX = 'exterior-fv:'
UNBOUND_PREFIXES = ('partition-record:',)
CAPTURES_MAP_SCHEMA = 'atlas.private.n9-captures-map.r1'
SELECTED_PINS_SCHEMA = 'atlas.private.n9-selected-pins.r1'
STEP_LAUNCH_SCHEMA = 'atlas.private.fresh-interval-step-launch.r1'
STEP_CAPTURE_SCHEMA = 'atlas.private.fresh-interval-step-capture.r1'
CAPTURE_FILES = ('launch', 'tracking', 'receipt', 'guard', 'control', 'abort', 'cancel', 'log')
CAPTURE_KEYS = frozenset({'schema', 'utc', 'capture_mode', 'writer', 'binding', 'launch_record_sha256',
                          'lifecycle', 'files', 'nonce'})
LAUNCH_KEYS = frozenset({'schema', 'utc', 'writer', 'binding', 'argv', 'env_names', 'guard', 'entry_point',
                         'profile', 'stage_record_before_step'})
LIFECYCLE_KEYS = frozenset({'launcher_outcome', 'process_exit_code', 'guard_status', 'guard_reason',
                            'workload_exit_confirmed', 'workload_exit_code', 'terminal_observed_utc'})
FILE_ROW_KEYS = frozenset({'present', 'sha256', 'bytes', 'mtime_ns'})
BINDING_KEYS = frozenset({'arm', 'stage', 'interval', 'step', 'attempt', 'output'})
CONFIRMED_TERMINAL = frozenset(('PARENT_EXITED', 'HARD_STOPPED', 'STOPPED'))
ROOT_KINDS = frozenset(('root', 'migrated-root'))
COLLAR_STATE_SCHEMA = 'atlas.regional-collar-state.v1'
SPATIAL_STATE_SCHEMA = 'atlas.spatial-exterior-state.v1'
HEAT_PREFIX = 'exterior_heat:'
PARTITION_RECORD = 'partition-record:'
PARTITION_ALIAS = 'partition-dag:'       # partition_workflow_patch.PREFIX
MESH_ALIAS = 'spatial-mesh:'             # spatial_workflow_patch.PREFIX
SUCCESSOR_PREFIXES = ('source-audit:', 'spatial-audit:', 'certification-', 'differential-network:',
                      'differential-record:')
ROOT_PREFIXES = (EXTERIOR_PREFIX, HEAT_PREFIX, PARTITION_RECORD, PARTITION_ALIAS, MESH_ALIAS, RECORD_ARRAY)
ENDPOINT_IDS = ('workflow_id', 'root_key', 'head_key', 'collar_result_id', 'native_result_id', 'exterior_state_id',
                'source_audit_id', 'joined_heat_id')
FIELD_CONTRACT_SCHEMA = 'atlas.private.n9-field-contract.v2'
# r18 causal evidence (causal schema r1, Policy v2 0aa6bc32). Closed records, pinned producers.
SELECTED_PINS_SCHEMA_R2 = 'atlas.private.n9-selected-pins.r2'
EVIDENCE_BUNDLE_SCHEMA = 'atlas.private.n9-causal-evidence.r1'
EVIDENCE_KINDS = {'external_event': 'atlas.private.n9-external-event.r1',
                  'observer_interruption': 'atlas.private.n9-observer-interruption.r1',
                  'diagnostic_repeat': 'atlas.private.n9-diagnostic-repeat.r1'}
EVIDENCE_KEYS = frozenset({'schema', 'evidence_id', 'kind', 'binding', 'process', 'guard', 'producer',
                           'source_evidence', 'payload'})
EVIDENCE_BINDING_KEYS = frozenset({'arm', 'attempt', 'profile_sha256', 'source_manifest_sha256', 'stage',
                                   'interval', 'step'})
EVIDENCE_STEPS = frozenset(('runner', 'reader', 'observer'))
EXTERNAL_EVENTS = frozenset(('operator_cancel', 'host_restart'))
AUTOMATIC_EVENTS = frozenset(('automatic_launcher_action',))   # e.g. the 60 s startup timeout: never external
EVENT_OUTCOMES = frozenset(('requested', 'delivered', 'acknowledged', 'independently_observed'))
EXPLAINING_OUTCOMES = frozenset(('acknowledged', 'independently_observed'))
# r19: only a cancellation the guard itself retained can explain a stop; host_restart lacks host binding
EXPLAINING_EVENTS = frozenset(('operator_cancel',))
OBSERVER_TERMINATION_SCHEMA = 'atlas.private.n9-observer-termination.r1'
OBSERVER_TERMINATION_KEYS = frozenset({'schema', 'invocation', 'observed_by', 'exit_or_signal'})
EVENT_PAYLOAD_KEYS = frozenset({'event_type', 'occurred_utc', 'actor_or_source', 'action_or_event_id',
                                'request_outcome'})
OBSERVER_PAYLOAD_KEYS = frozenset({'observer_invocation', 'termination', 'external_event_ref', 'sealed_arm_refs'})
REPEAT_PAYLOAD_KEYS = frozenset({'repeat_id', 'repeat_ordinal', 'original', 'eligibility', 'approvals'})
REPEAT_LOCATION_KEYS = frozenset({'output_directory', 'store_directory', 'completed_query_directory'})
REPEAT_REQUIRED_APPROVER = 'OWNER'
# The actual reader finaliser's closed checks (chain-r3 reopen_fresh_restart CHECKS, non-review).
READER_CHECKS = {
    'root': frozenset(('pending_file_verified', 'source_bound_admission', 'root_identity', 'root_record_identities',
                       'widths_recorded', 'store_unchanged', 'retained_scope_released')),
    'interval': frozenset(('pending_file_verified', 'source_bound_admission', 'root_identity', 'successor_identity',
                           'state_identities', 'all_six_field_groups_identical', 'compact_record_identities_identical',
                           'fresh_lineage', 'widths_recorded', 'width_gate_evaluated', 'store_unchanged',
                           'retained_scope_released'))}
ROOT_RECORDS = frozenset(('state', 'mesh'))
SOURCE_PROOF_KEYS = frozenset(('source_manifest_sha256', 'native_source_digest'))
# width_gate.py (composed-r2 helpers), copied: closed exact-width table and the approved interval-1 gate.
WIDTH_TABLE_SCHEMA = 'atlas.exact-width-table.v1'
WIDTH_TABLE_KEYS = frozenset(('schema', 'interval', 'trajectory_steps', 'limit_bits', 'records'))
WIDTH_ROW_KEYS = frozenset(('count', 'integers', 'max_numerator_bits', 'max_denominator_bits'))
WIDTH_GATE_SCHEMA = 'atlas.exact-width-gate.v1'
LIMIT_BITS = 8*(1 << 20)
INTERVAL2_SHARE, INTERVAL3_SHARE = 0.5, 1.0
# i1 table groups whose rows are dumped one-to-one under DIRECT_PREFIXES (unprefixed names are full_collar).
DUMPED_GROUPS = frozenset({'full_collar', 'exterior', 'source_audit', 'spatial_audit'})
DESIGN_BOUND = 'DESIGN-5-strict-2^-11'
DESIGN_SHIFT = 11         # strict |delta| < 2**-11 * r (DESIGN section 5)
DEVIATION_SHIFT = 64      # Addendum E: stored - exact < 2**-64 * exact
DEVIATION_FIELD = 'geometry_volume_max_deviation_m3'
WIDTH_FIELD = 'max_geometry_volume_error_m3'
DIAGNOSTIC_ULPS = 2**9    # historical figures; reported, never a PASS allowance (D01)
DIAGNOSTIC_REL = 2.0**-20
MAX_FIELDS = 20000
MAX_ITEMS = 200
MAX_PROOF_BYTES = 1 << 26
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
# Retained accounting, restated from R/reopen_prepared_restart.py (sha256 5b7f13bf...8f24, lines 75-78 and 593-652)
# as invoked on both reader observations by the bound restart reader.
RETAINED_LIMIT = 256 << 20
RETAINED_SCALARS = ('retained_bytes', 'peak_retained_bytes', 'pinned_bytes', 'pending_bytes',
                    'evictable_bytes', 'non_cache_owned_bytes', 'optional_declines', 'required_refusals')
RETAINED_MAPPINGS = ('hits', 'misses', 'evictions', 'insertions', 'entries', 'reclaimed_bytes',
                     'category_bytes', 'category_peak_bytes', 'purpose_bytes', 'purpose_peak_bytes')
PRODUCER_SCALARS = ('producer_limit_bytes', 'producer_bytes', 'producer_peak_bytes', 'producer_refusals')
PRODUCER_MAPPINGS = ('producer_purpose_bytes', 'producer_purpose_peak_bytes')
HEX64_ANY = re.compile(r'(?<![0-9a-fx])[0-9a-f]{64}(?![0-9a-f])')
HEXINT = re.compile(r'-?0x[0-9a-f]+\Z')
BIG = sys.float_info.max
# Magnitude tables: diagnostics for the structured review of REVIEW quantities; no verdict reads them.
MAGNITUDES_SCHEMA = 'atlas.private.n9-magnitudes.r1'
SMALL_VALUES = 8          # a quantity with at most this many compared elements lists every value pair


class CompareError(RuntimeError):
    pass


class ProofError(CompareError):
    """A proof/integrity failure (FAIL), never a scientific divergence by itself."""


def require(condition, message):
    if not condition:
        raise CompareError(message)


def prove(condition, message):
    if not condition:
        raise ProofError(message)


def file_sha(path):
    digest = sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 22), b''):
            digest.update(block)
    return digest.hexdigest()


def _reject_constant(name):
    raise ProofError('non-finite JSON constant %s' % name)


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ProofError('non-finite JSON number %s' % text[:40])
    return value


def strict_json(raw, where):
    try:
        return json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float)
    except ValueError as error:
        raise ProofError('malformed JSON %s: %s' % (where, error)) from None


def bounded_bytes(path, where):
    """Read one stable JSON snapshot, retaining at most MAX_PROOF_BYTES (including growth races)."""
    path = Path(path)
    before = path.stat()
    prove(before.st_size <= MAX_PROOF_BYTES, 'oversized record '+where)
    raw = bytearray()
    with path.open('rb') as stream:
        while True:
            block = stream.read(min(1 << 20, MAX_PROOF_BYTES-len(raw)+1))
            if not block:
                break
            prove(len(raw)+len(block) <= MAX_PROOF_BYTES, 'record grew beyond byte cap '+where)
            raw.extend(block)
        after = os.fstat(stream.fileno())
    prove((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
          (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == after.st_size,
          'record changed while read '+where)
    return bytes(raw)


def pinned(path, where):
    """(value, sha256, nbytes) of a bounded proof JSON file."""
    path = Path(path)
    prove(path.is_file(), 'missing proof file %s: %s' % (where, path))
    raw = bounded_bytes(path, where)
    value = strict_json(raw, where)
    prove(type(value) is dict, 'proof file %s is not an object' % where)
    return value, sha256(raw).hexdigest(), len(raw)


def same_path(a, b):
    return Path(a).resolve() == Path(b).resolve()


def rational(value):
    if (type(value) is list and len(value) == 2 and type(value[0]) is str and type(value[1]) is str
            and HEXINT.match(value[0]) and HEXINT.match(value[1])):
        den = int(value[1], 16)
        if den > 0:
            return int(value[0], 16), den
    return None


def number(value):
    """An exact (num, den) for a rational, int or finite binary64 leaf; None otherwise."""
    r = rational(value)
    if r is not None:
        return r
    if type(value) is int:
        return value, 1
    if type(value) is float and math.isfinite(value):
        return value.as_integer_ratio()
    return None


def quotient(num, den):
    """|num/den| as a finite float (capped, may underflow to 0.0) and a log2 estimate (None for 0)."""
    num = abs(num)
    if num == 0:
        return 0.0, None
    try:
        value = num/den
    except OverflowError:
        value = BIG
    return min(value, BIG), num.bit_length()-den.bit_length()


def ident(value):
    """Hashable form of an id-like value (strings and ints only; None if it holds numbers or rationals)."""
    if type(value) is str:
        return None if HEXINT.match(value) else value
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is list:
        parts = tuple(ident(v) for v in value)
        return None if any(p is None and v is not None for p, v in zip(parts, value, strict=True)) else ('L',)+parts
    if type(value) is dict:
        parts = tuple((k, ident(v)) for k, v in sorted(value.items()))
        return None if any(p is None and value[k] is not None for k, p in parts) else ('D',)+parts
    return None


def identity_tokens(value, found=None):
    """All candidate identities, including dictionary keys; exact integers are excluded."""
    found = set() if found is None else found
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            if not HEXINT.fullmatch(item):
                found.update(HEX64_ANY.findall(item))
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return found


def token_pairs(before, after, where):
    """Reader-proved identity pairs from two proof values with the same template; refuses otherwise."""
    if before is None and after is None:
        return []
    prove(type(before) is str and type(after) is str, 'proved identity %s is not a string on both arms' % where)
    xs, ys = HEX64_ANY.findall(before), HEX64_ANY.findall(after)
    prove(len(xs) == len(ys) and HEX64_ANY.sub('#', before) == HEX64_ANY.sub('#', after),
          'proved identity %s has different templates' % where)
    return list(zip(xs, ys, strict=True))


def checked_identity_map(reader_pairs, before_tokens, after_tokens):
    """Bijection from independently re-derived reader identities plus unchanged tokens.

    Callers must supply reader_pairs from validated proof records, never from
    changed payload values. Unknown content identities remain unmapped.
    """
    mapping = {}
    for before, after in reader_pairs:
        require(type(before) is str and HEX64.fullmatch(before) and
                type(after) is str and HEX64.fullmatch(after), 'malformed reader identity')
        require(mapping.setdefault(before, after) == after, 'reader identity maps to multiple targets')
    for value in before_tokens & after_tokens:
        require(mapping.setdefault(value, value) == value,
                'reader translation conflicts with an unchanged content identity')
    require(len(set(mapping.values())) == len(mapping), 'identity map is not bijective')
    return mapping


# ---- Addendum E header rule

def headers(value):
    """Every dict carrying the exterior/differential mesh header pair (deviation sum and width)."""
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            if DEVIATION_FIELD in item and WIDTH_FIELD in item and 'cells' in item:
                yield item
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def addendum_e(header):
    """('zero'|'exact'|'outward', None), ('violation', why) or ('uncheckable', why); exact Fractions only."""
    stored, width, cells = rational(header[DEVIATION_FIELD]), rational(header[WIDTH_FIELD]), header['cells']
    if stored is None or width is None or type(cells) is not list:
        return 'uncheckable', 'header deviation, width or cells not exact'
    total = Fraction(0)
    for cell in cells:
        value = rational(cell.get(DEVIATION_FIELD)) if type(cell) is dict else None
        if value is None or value[0] < 0:
            return 'uncheckable', 'a cell deviation is missing or not an exact non-negative rational'
        total += Fraction(*value)
    stored, width = Fraction(*stored), Fraction(*width)
    if total > width:
        return 'violation', 'exact deviation total exceeds the width (the unchanged pre-check)'
    if total == 0:
        return ('zero', None) if stored == 0 else ('violation', 'exact zero total stored as non-zero')
    if stored == total:
        return 'exact', None
    if stored < total:
        return 'violation', 'stored header below the exact total (not outward)'
    if (stored-total)*2**DEVIATION_SHIFT >= total:
        return 'violation', 'stored excess not strictly below 2**-64 of the exact total'
    if stored > width:
        return 'violation', 'stored header above the width'
    return 'outward', None


class Comparer:
    def __init__(self, ids, coverage, *, legacy_headers=True):
        self.fields, self.overflow = {}, 0
        self.ids, self.coverage = ids, coverage
        self.legacy_headers = legacy_headers
        self.structure, self.labels = [], []
        self.counts = {'structure': 0, 'labels': 0, 'identity_changes': 0, 'weak_pairings': 0,
                       'keyed_pairings': 0, 'addendum_e_headers': 0}
        # Magnitude bookkeeping per field name, kept apart from self.fields so its rows are unchanged.
        self.magnitudes, self.worst, self.samples = {}, {}, {}
        self.radii = {}         # field name -> (largest ratio, the radius it was compared with); tables only

    # ---- bookkeeping
    def field(self, path, kind):
        return self.field_named(path, kind)[0]

    def field_named(self, path, kind):
        name = '.'.join(path)
        entry = self.fields.get(name)
        if entry is None and len(self.fields) >= MAX_FIELDS:
            self.overflow += 1
            name, entry = '<overflow>', self.fields.get('<overflow>')
        if entry is None:
            entry = self.fields[name] = {
                'kinds': [], 'compared': 0, 'changed': 0, 'weak_changed': 0, 'max_abs': 0.0,
                'max_abs_log2': None, 'max_rel': 0.0, 'max_ulps': 0, 'radius': None, 'max_ratio': None,
                'covered_changes': 0, 'bound_violations': 0, 'unbound_changes': 0}
        if kind not in entry['kinds']:
            entry['kinds'].append(kind)
        return entry, name

    def sample(self, name, entry, at, before, after):
        """Keep every value pair of a field while it has at most SMALL_VALUES compared elements."""
        if entry['compared'] <= SMALL_VALUES:
            self.samples.setdefault(name, []).append((at, before, after))

    def magnitude_scale(self, name, ra, rb):
        """Per-arm maximum absolute numeric value, including unchanged finite compared leaves."""
        m = self.magnitudes.get(name)
        if m is None:
            m = self.magnitudes[name] = {'increased': 0, 'decreased': 0, 'abs_log2': {}, 'rel_log2': {},
                                         'scale': [0.0, 0.0], 'worst': None, 'exact_ulps': 0}
        m['scale'][0] = max(m['scale'][0], quotient(*ra)[0])
        m['scale'][1] = max(m['scale'][1], quotient(*rb)[0])

    def magnitude(self, name, num, den, rel, at, ra, rb):
        """Sign, log2 bins, per-arm scale and the first largest change of one changed leaf.

        num/den is (before - after) exactly and rel = (rn, rd) the relative change the walk reports; the
        bins are exact floors of log2. Ties keep the first location in walk order (sorted keys, list order).
        """
        m = self.magnitudes[name]
        m['decreased' if num > 0 else 'increased'] += 1
        size = abs(num)
        e = floor_log2(size, den)
        m['abs_log2'][e] = m['abs_log2'].get(e, 0)+1
        if rel[0]:
            r = floor_log2(abs(rel[0]), rel[1])
            m['rel_log2'][r] = m['rel_log2'].get(r, 0)+1
        best = self.worst.get(name)
        if best is None or size*best[1] > best[0]*den:
            self.worst[name] = (size, den)
            m['worst'] = {'at': located(at), 'before': signed(ra), 'after': signed(rb),
                          'abs': quotient(size, den)[0], 'rel': quotient(*rel)[0]}

    def magnitude_table(self):
        """One magnitude row per field the walk leaves REVIEW (or FAIL), sorted by field name."""
        table = {}
        for name in sorted(self.fields):
            f = self.fields[name]
            if not (f['unbound_changes'] or f['weak_changed'] or f['bound_violations']):
                continue
            m = self.magnitudes[name]
            row = {'status': 'FAIL' if f['bound_violations'] else 'REVIEW', 'kinds': sorted(f['kinds']),
                   'compared': f['compared'], 'changed': f['changed'], 'weak_changed': f['weak_changed'],
                   'unbound_changes': f['unbound_changes'], 'bound_violations': f['bound_violations'],
                   'increased': m['increased'], 'decreased': m['decreased'],
                   'max_abs': f['max_abs'], 'max_rel': f['max_rel'], 'max_ulps': max(f['max_ulps'], m['exact_ulps']),
                   'worst': m['worst'], 'scale': {'before': m['scale'][0], 'after': m['scale'][1]},
                   'abs_log2_bins': [[e, m['abs_log2'][e]] for e in sorted(m['abs_log2'])],
                   'rel_log2_bins': [[e, m['rel_log2'][e]] for e in sorted(m['rel_log2'])]}
            row.update(radius_columns(f, self.radii.get(name)))
            if f['compared'] <= SMALL_VALUES:
                row['values'] = [{'at': located(at), 'before': x, 'after': y}
                                 for at, x, y in self.samples.get(name, ())]
            table[name] = row
        return table

    def note(self, bucket, path, message):
        self.counts[bucket] += 1
        items = self.structure if bucket == 'structure' else self.labels
        if len(items) < MAX_ITEMS:
            items.append({'path': '.'.join(path), 'what': message})

    def learn(self, before, after):
        """Recognise only independently authorised identity translations; never learn content."""
        if type(before) is not str or type(after) is not str:
            return False
        if HEXINT.fullmatch(before) or HEXINT.fullmatch(after):
            return False
        xs, ys = HEX64_ANY.findall(before), HEX64_ANY.findall(after)
        if not xs or len(xs) != len(ys) or HEX64_ANY.sub('#', before) != HEX64_ANY.sub('#', after):
            return False
        return all(self.ids.get(x, x) == y for x, y in zip(xs, ys, strict=True))

    def translate(self, value):
        if type(value) is str:
            return HEX64_ANY.sub(lambda m: self.ids.get(m.group(0), m.group(0)), value)
        if type(value) is tuple:
            return tuple(self.translate(v) for v in value)
        return value

    # ---- walk
    def compare(self, a, b, path, weak=False, radius=None, scale=None, at=None):
        # Container equality hides nested type changes and signed zero.
        # 'at' is the concrete location, a (parent, segment) chain that costs O(1) per node.
        if at is None:
            at = (None, '.'.join(path))
        if type(a) is not type(b):
            return self.note('labels', path, 'type %s -> %s' % (type(a).__name__, type(b).__name__))
        if type(a) is float and a == b == 0.0 and math.copysign(1.0, a) != math.copysign(1.0, b):
            return self.note('labels', path, 'signed zero changed')
        if type(a) not in (dict, list) and a == b:
            entry, name = self.field_named(path, type(a).__name__)
            entry['compared'] += 1
            self.sample(name, entry, at, a, b)
            numeric = number(a)
            if numeric is None and type(a) is str and HEXINT.fullmatch(a):
                numeric = (int(a, 16), 1)
            if numeric is not None:
                self.magnitude_scale(name, numeric, numeric)
            return
        if type(a) is dict and type(b) is dict:
            return self.dicts(a, b, path, weak, at)
        if type(a) is list and type(b) is list:
            ra, rb = rational(a), rational(b)
            if ra and rb:
                return self.exact(ra, rb, path, weak, radius, scale, 'rational', at, (a, b))
            if ra or rb:
                return self.note('structure', path, 'rational on one side only')
            return self.lists(a, b, path, weak, radius, at)
        if type(a) is str and type(b) is str:
            if HEXINT.match(a) and HEXINT.match(b):
                return self.exact((int(a, 16), 1), (int(b, 16), 1), path, weak, radius, scale, 'hex-int', at,
                                  (a, b))
            if self.learn(a, b):
                self.counts['identity_changes'] += 1
                return
            return self.note('labels', path, 'string %r -> %r' % (a[:80], b[:80]))
        if type(a) is bool and type(b) is bool:
            return self.note('labels', path, 'boolean %s -> %s' % (a, b))
        if type(a) is int and type(b) is int:
            return self.exact((a, 1), (b, 1), path, weak, radius, scale, 'int', at, (a, b))
        if type(a) is float and type(b) is float:
            return self.binary64(a, b, path, weak, radius, scale, at)
        self.note('structure', path, 'type %s -> %s' % (type(a).__name__, type(b).__name__))

    @staticmethod
    def segment(key):
        if HEX64.match(key):
            return '#'
        return re.sub(r':\d+$', ':#', key)

    def dicts(self, a, b, path, weak, at=None):
        keyed = bool(a) and bool(b) and all(HEX64.match(k) for k in a) and all(HEX64.match(k) for k in b)
        pairs = None
        if keyed and set(a) != set(b):
            moved = {self.ids.get(k, k): k for k in a}
            if len(moved) == len(a) and set(moved) == set(b):
                pairs = [(moved[k], k) for k in sorted(b)]
        if pairs is None:
            only = sorted(set(a) ^ set(b))
            for k in (only[:3] if keyed else only):
                self.note('structure', path+(self.segment(k),), 'key only in %s' % ('before' if k in a else 'after'))
            if keyed and len(only) > 3:
                self.counts['structure'] += len(only)-3
            pairs = [(k, k) for k in sorted(set(a) & set(b))]
        # Addendum E governs a valid header sum on each arm (checked in run()); its change is accounted there.
        header = (self.legacy_headers and not keyed and DEVIATION_FIELD in a and DEVIATION_FIELD in b and
                  all(WIDTH_FIELD in x and 'cells' in x for x in (a, b)) and
                  all(addendum_e(x)[0] in ('zero', 'exact', 'outward') for x in (a, b)))
        common = [kb for _, kb in pairs]
        for ka, kb in pairs:
            if header and kb == DEVIATION_FIELD:
                self.counts['addendum_e_headers'] += 1
                self.field(path+(kb,), 'addendum-e')['compared'] += 1
                continue
            radius = None if keyed else self.radius_of(kb, a, b, common, path)
            self.compare(a[ka], b[kb], path+(self.segment(kb),), weak, radius,
                         at=(at, kb if ka == kb else ka+'->'+kb))

    def radius_of(self, key, a, b, common, path):
        name = self.coverage.get(path+(self.segment(key),))
        if name is None:
            return None
        if name not in common:
            return 'missing', None
        values = [number(side[name]) for side in (a, b)]
        if not all(v is not None and v[0] >= 0 for v in values):
            return 'invalid', None
        x, y = values
        return name, x if x[0]*y[1] <= y[0]*x[1] else y

    def lists(self, a, b, path, weak, radius, at=None):
        sub = path+('[]',)
        if a and b and all(type(x) is dict for x in a) and all(type(x) is dict for x in b):
            found = self.pairing(a, b)
            if found is not None:
                key, found = found
                self.counts['keyed_pairings'] += 1
                for x, y in found:
                    self.compare(x, y, sub, weak, None, at=(at, (key, x[key])))
                return
            if len(a) != len(b):
                return self.note('structure', sub, 'list of objects %d -> %d, no stable key' % (len(a), len(b)))
            self.counts['weak_pairings'] += 1
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                self.compare(x, y, sub, True, None, at=(at, i))
            return
        if len(a) != len(b):
            return self.note('structure', sub, 'list length %d -> %d' % (len(a), len(b)))
        scale = None
        values = [number(x) for x in a+b if type(x) is not bool]
        if values and len(values) == len(a)+len(b) and all(values):
            top = max(values, key=lambda v: quotient(v[0], v[1])[0])
            scale = (abs(top[0]), top[1]) if top[0] else None
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            self.compare(x, y, sub, weak, radius, scale, at=(at, i))

    def pair(self, a, b):
        found = self.pairing(a, b)
        return None if found is None else found[1]

    def pairing(self, a, b):
        """The stable key and the (before, after) object pairs of two lists, or None."""
        if len(a) != len(b):
            return None
        keys = set(a[0]).intersection(*a[1:], *b)
        order = sorted(keys, key=lambda k: (not k.endswith('id'), k))
        for key in order:
            va, vb = [ident(x[key]) for x in a], [ident(x[key]) for x in b]
            if None in va or None in vb or len(set(va)) != len(va) or len(set(vb)) != len(vb):
                continue
            index = dict(zip(vb, b, strict=True))
            for before in (va, [self.translate(v) for v in va]):
                if all(v in index for v in before):
                    return key, [(x, index[v]) for v, x in zip(before, a, strict=True)]
        return None

    # ---- leaves
    def exact(self, ra, rb, path, weak, radius, scale, kind, at=None, raw=None):
        (na, da), (nb, db) = ra, rb
        entry, name = self.field_named(path, kind)
        entry['compared'] += 1
        if raw is not None:
            self.sample(name, entry, at, *raw)
        self.magnitude_scale(name, ra, rb)
        num = na*db-nb*da
        if num == 0:
            return
        den = da*db
        entry['changed'] += 1
        if weak:
            entry['weak_changed'] += 1
        value, log2 = quotient(num, den)
        entry['max_abs'] = max(entry['max_abs'], value)
        if log2 is not None and (entry['max_abs_log2'] is None or log2 > entry['max_abs_log2']):
            entry['max_abs_log2'] = log2
        if scale is not None:
            relq = (num*scale[1], den*scale[0])
            rel = quotient(*relq)[0]
        else:
            top = max(abs(na)*db, abs(nb)*da)
            relq = (num, top) if top else (0, 1)
            rel = quotient(num, top)[0] if top else BIG
        entry['max_rel'] = max(entry['max_rel'], rel)
        self.magnitude(name, num, den, relq, (None, '.'.join(path)) if at is None else at, ra, rb)
        if kind != 'binary64':
            # Tables only: an exact value's change in binary64 steps between its correctly rounded values.
            m = self.magnitudes[name]
            m['exact_ulps'] = max(m['exact_ulps'], ulps(signed(ra), signed(rb)))
        if radius is None or weak:
            entry['unbound_changes'] += 1
            return
        source, r = radius
        entry['radius'] = source
        if r is None:                         # covered field whose radius is missing or invalid
            entry['bound_violations'] += 1
            return
        nr, dr = r
        # Exact strict bound: |num/den| < 2**-11 * nr/dr  <=>  |num|*dr*2**11 < den*nr.
        entry['covered_changes'] += 1
        if abs(num)*dr*2**DESIGN_SHIFT >= den*nr:
            entry['bound_violations'] += 1
        ratio = BIG if nr == 0 else quotient(num*dr, den*nr)[0]
        entry['max_ratio'] = ratio if entry['max_ratio'] is None else max(entry['max_ratio'], ratio)
        if name not in self.radii or ratio > self.radii[name][0]:
            self.radii[name] = (ratio, (nr, dr))

    def binary64(self, x, y, path, weak, radius, scale, at=None):
        # strict_json admits no non-finite values; a finite change is exact rational arithmetic.
        self.exact(x.as_integer_ratio(), y.as_integer_ratio(), path, weak, radius, scale, 'binary64', at, (x, y))
        entry = self.field(path, 'binary64')
        entry['max_ulps'] = max(entry['max_ulps'], ulps(x, y))


def floor_log2(num, den):
    """Exact floor(log2(num/den)) for positive integers."""
    e = num.bit_length()-den.bit_length()
    if (num << -e if e < 0 else num) < (den << e if e > 0 else den):
        e -= 1
    return e


def signed(r):
    """A rational (num, den > 0) as a signed float, capped and rounded as quotient() does."""
    value = quotient(r[0], r[1])[0]
    return -value if r[0] < 0 else value


def radius_columns(f, best):
    """The certified radius a field's largest change was compared with, its source and the ratio.

    'best' is the walk's (largest ratio, radius) for the field, or None. The bound is strict: |change| <
    2**-11 * radius, i.e. max_ratio < 2**-11. A field that no contract binds says so; it never gets a
    substitute tolerance.
    """
    if f['radius'] is None:
        return {'certified_radius': None, 'radius_source': None, 'max_ratio': None,
                'radius_status': 'none: no field contract binds a certified radius to this field'}
    if best is None:                          # radius_of found the contract's radius 'missing' or 'invalid'
        return {'certified_radius': None, 'radius_source': 'field contract (radius %s)' % f['radius'],
                'max_ratio': None, 'radius_status': 'covered field whose radius is missing or invalid'}
    ratio, (num, den) = best
    return {'certified_radius': {'value': signed((num, den)), 'exact': '%d/%d' % (num, den)},
            'radius_source': 'field contract sibling field %s (the smaller of the two arms)' % f['radius'],
            'max_ratio': ratio, 'ratio_limit': 2.0**-DESIGN_SHIFT, 'radius_status': 'certified'}


def located(at):
    """The concrete location string of a Comparer (parent, segment) chain.

    A str segment is a dict key, an int a list position and a (key, value) pair a keyed list item.
    """
    parts = []
    while at is not None:
        at, segment = at
        parts.append(segment)
    text = ''
    for segment in reversed(parts):
        if type(segment) is int:
            text += '[%d]' % segment
        elif type(segment) is tuple:
            key, value = segment
            text += '[%s=%s]' % (key, value if type(value) is str else json.dumps(value, sort_keys=True))
        else:
            text += ('.' if text else '')+segment
    return text


def ulps(x, y):
    def ordered(v):
        bits = int(np.float64(v).view(np.int64))
        return bits if bits >= 0 else -(bits & 0x7fffffffffffffff)
    return abs(ordered(x)-ordered(y))


def array_ulps(u, v):
    """Largest ulp distance between two float64 arrays of equal shape (exact, no int64 overflow)."""
    iu, iv = u.view(np.int64), v.view(np.int64)
    mask = iu != iv
    if not mask.any():
        return 0
    iu, iv = iu[mask], iv[mask]
    low = np.int64(0x7fffffffffffffff)
    ou = np.where(iu < 0, -(iu & low), iu)
    ov = np.where(iv < 0, -(iv & low), iv)
    same = (ou >= 0) == (ov >= 0)
    best = 0
    if same.any():
        best = int(np.max(np.abs(ou[same]-ov[same])))
    if (~same).any():
        best = max(best, max(abs(int(p))+abs(int(q)) for p, q in zip(ou[~same], ov[~same], strict=True)))
    return best


def guard_binding(attempt, stage, step, guard, receipt):
    """r9: the first unmet lifecycle/identity binding of a guard receipt to its own guarded run, else None."""
    folder, stem = STEP_RECORDS[step]
    parent, guardian = guard.get('parent'), guard.get('guardian')
    if not (type(parent) is dict and set(parent) == {'pid', 'created_ticks'} and
            all(type(value) is int for value in parent.values())):
        return 'no registered workload parent identity'
    if not (type(guardian) is dict and type(guardian.get('pid')) is int and
            type(guard.get('nonce')) is str and guard['nonce'] and
            type(guard.get('job_name')) is str and guard['job_name']):
        return 'no guardian, nonce or job identity'
    if guard.get('workload_exit_confirmed') is not True:
        return 'workload exit not confirmed'
    if guard.get('cleanup') != GUARD_CLEAN or 'cleanup_error' in guard:
        return 'job cleanup incomplete'
    if guard.get('main_output_update') != {'updated': True}:
        return 'guard did not record its terminal update of the step receipt'
    try:
        control = strict_json(bounded_bytes(attempt/(folder % stage)/(stem+'.guard-control.json'), step+' guard control'),
                              step+' guard control')
        tracking = strict_json(bounded_bytes(attempt/((folder % stage)+'.tracking.json'), step+' tracking'), step+' tracking')
    except (OSError, ProofError) as error:
        return 'guard control or launcher tracking missing or malformed: %s' % error
    if not (type(control) is dict and control.get('nonce') == guard['nonce'] and control.get('parent') == parent):
        return 'guard control nonce or parent differs'
    if not (type(tracking) is dict and tracking.get('schema') == TRACKING_SCHEMA and
            tracking.get('parent') == parent and tracking.get('job_name') == guard['job_name'] and
            type(tracking.get('guardian')) is dict and tracking['guardian'].get('pid') == guardian['pid']):
        return 'launcher tracking parent, job or guardian differs'
    output = tracking.get('output')
    try:  # untrusted path text: an unusable path is a refused binding, never an escaping error
        bound = type(output) is str and bool(output) and same_path(output, attempt/(folder % stage))
    except (ValueError, OSError):
        bound = False
    if not bound:
        return 'launcher tracking output is not this guarded step directory'
    if receipt.get('status') != 'FAILED' or receipt.get('supervisor') != {
            key: guard.get(key) for key in GUARD_SUPERVISOR}:
        return 'step receipt supervisor does not equal the guard receipt'
    row = {'source': 'continuation_guard', 'failure': 'Independent continuation guard: '+str(guard.get('reason'))}
    if type(receipt.get('errors')) is not list or row not in receipt['errors']:
        return 'step receipt lacks the guard failure row'
    return None


def stop_cause(attempt, stage, record, profile_sha256):
    """('FAIL', cause) only on retained causal evidence of the failed guarded step; else ('VOID-SUSPECT', why)."""
    step = record.get('failed_step')
    if type(step) is not str or step not in STEP_RECORDS:
        return 'VOID-SUSPECT', 'failed step %r has no guarded stop evidence' % (step,)
    folder, stem = STEP_RECORDS[step]
    base = attempt/(folder % stage)
    try:
        guard = strict_json(bounded_bytes(base/(stem+'.guard.json'), step+' guard receipt'), step+' guard receipt')
        receipt = strict_json(bounded_bytes(base/(stem+'.json'), step+' receipt'), step+' receipt')
    except (OSError, ProofError) as error:
        return 'VOID-SUSPECT', '%s stop records missing or malformed: %s' % (step, error)
    if not (type(guard) is dict and guard.get('schema') == GUARD_SCHEMA and type(receipt) is dict):
        return 'VOID-SUSPECT', '%s guard receipt is not a guard r3 receipt' % step
    if guard.get('limits') != GUARD_LIMITS or receipt.get('profile_sha256') != profile_sha256:
        return 'VOID-SUSPECT', '%s ran under other limits or another profile: not the unchanged workload' % step
    reason, status = guard.get('reason'), guard.get('status')
    abort = base/(stem+'.guard-abort.json')
    if reason == 'rss_limit':
        sample = guard.get('detail')
        tree = sample.get('process_tree_rss_bytes') if type(sample) is dict else None
        notice = None
        if abort.is_file():
            try:
                notice = strict_json(bounded_bytes(abort, 'guard abort notice'), 'guard abort notice')
            except (OSError, ProofError):
                notice = {}
        if not (status in GUARD_EXITED and type(tree) is int and tree > GUARD_LIMITS['rss_bytes'] and
                (notice is None or (type(notice) is dict and notice.get('reason') == 'rss_limit' and
                                    notice.get('nonce') == guard.get('nonce')))):
            return 'VOID-SUSPECT', '%s rss_limit reason without an exited guard and bound breaching sample' % step
        unbound = guard_binding(attempt, stage, step, guard, receipt)
        if unbound is not None:
            return 'VOID-SUSPECT', '%s rss_limit stop not bound to its guarded run: %s' % (step, unbound)
        return 'FAIL', ('resource/robustness: %s own process tree %d bytes > unchanged RSS limit %d '
                        '(guard trigger sample)' % (step, tree, GUARD_LIMITS['rss_bytes']))
    if reason is not None or abort.is_file() or (base/(stem+'.cancel')).exists():
        return 'VOID-SUSPECT', '%s guard reason %r (status %r): cause not established' % (step, reason, status)
    errors = receipt.get('errors')
    first = errors[0] if type(errors) is list and errors and type(errors[0]) is dict else {}
    origin = first.get('first_raised') if type(first.get('first_raised')) is dict else {}
    ledger = receipt.get('logical_budget_at_failure')
    if type(ledger) is dict and ledger.get('max_bytes') == LOGICAL_BYTES:
        predicate = ledger.get('predicate_work') if type(ledger.get('predicate_work')) is dict else {}
        if (first.get('type') == 'PredicateWorkLimitError' and str(first.get('message', '')).startswith(
                PREDICATE_REFUSAL) and type(predicate.get('refusals')) is int and predicate['refusals'] > 0):
            return 'FAIL', 'resource/robustness: %s predicate-work ledger refused the unchanged workload' % step
        if (first.get('type') != 'PredicateWorkLimitError' and origin.get('type') == 'MemoryLimitError' and
                origin.get('message') == BYTE_REFUSAL and type(ledger.get('refusals')) is int and
                ledger['refusals'] > 0):
            return 'FAIL', 'resource/robustness: %s logical byte ledger refused the unchanged workload' % step
    return 'VOID-SUSPECT', '%s stopped with %s (first raised %s): cause not established' % (
        step, first.get('type'), origin.get('type'))


def step_paths(attempt, stage, step):
    """lf-r1 paths of one guarded step (launch_fresh_interval.paths, interval 0/1 names)."""
    folder, stem = STEP_RECORDS[step]
    out = attempt/(folder % stage)
    sibling = lambda suffix: attempt/((folder % stage)+suffix)     # noqa: E731
    return {'out': out, 'launch': sibling('.launch.json'), 'capture': sibling('.capture.json'),
            'tracking': sibling('.tracking.json'), 'log': sibling('.log'), 'receipt': out/(stem+'.json'),
            'guard': out/(stem+'.guard.json'), 'control': out/(stem+'.guard-control.json'),
            'abort': out/(stem+'.guard-abort.json'), 'cancel': out/(stem+'.cancel')}


def load_captures(arm, spec):
    """Typed capture evidence errors are unmet stop-dependent checks, not global proof failures."""
    bad = lambda why: (None, 'check 1 map: '+why)
    if spec is None:
        return bad('no captures map for this arm')
    if not (type(spec) in (list, tuple) and len(spec) == 2 and
            type(spec[0]) is str and type(spec[1]) is str and HEX64.fullmatch(spec[1])):
        return bad('malformed path/digest specification')
    path, digest = spec
    try:
        value, found, _ = pinned(path, arm['name']+' captures map')
    except (ProofError, OSError, ValueError) as error:
        return bad(str(error))
    if found != digest:
        return bad('bytes differ from the supplied digest')
    if not (type(value) is dict and set(value) == {'schema', 'arm', 'profile_sha256', 'attempt', 'entries'} and
            value['schema'] == CAPTURES_MAP_SCHEMA and value['arm'] == arm['name'] and
            value['profile_sha256'] == arm['sha256'] and type(value['attempt']) is str and
            type(value['entries']) is list):
        return bad("not this arm's closed captures map")
    try:
        matches = same_path(value['attempt'], arm['attempt'])
    except (ValueError, OSError):
        matches = False
    if not matches:
        return bad("attempt is not this arm's directory")
    result = {}
    for entry in value['entries']:
        if not (type(entry) is dict and set(entry) == {'stage', 'interval', 'step', 'launch', 'capture'} and
                type(entry['stage']) is str and type(entry['interval']) is int and
                (entry['stage'], entry['interval']) in STAGES and type(entry['step']) is str and
                entry['step'] in STEP_RECORDS and
                all(type(entry[k]) is dict and set(entry[k]) == {'path', 'sha256'} and
                    type(entry[k]['path']) is str and type(entry[k]['sha256']) is str and
                    HEX64.fullmatch(entry[k]['sha256']) for k in ('launch', 'capture')) and
                (entry['stage'], entry['step']) not in result):
            return bad('malformed or repeated entry')
        result[(entry['stage'], entry['step'])] = entry
    return result, None


def stage_capture_evidence(attempt, stage, step, entry, profile_sha256):
    """Bind the anchored map to the mutable stage's actual step digests, not its historical pre-step hash."""
    record, _, _ = pinned(Path(attempt)/('stage-'+stage+'.json'), stage+' capture stage')
    profile, steps = record.get('profile'), record.get('steps')
    prove(record.get('schema') == STAGE_SCHEMA and record.get('stage') == stage and
          type(record.get('interval')) is int and record['interval'] == dict(STAGES)[stage] and
          type(profile) is dict and profile.get('sha256') == profile_sha256 and type(steps) is list and
          all(type(row) is dict for row in steps), 'capture stage identity/profile/steps malformed')
    selected = [row for row in steps if row.get('name') == step]
    prove(len(selected) == 1, 'capture stage must have exactly one named step')
    row = selected[0]
    capture = row.get('capture')
    prove(type(capture) is dict and capture.get('ok') is True and
          row.get('launch_sha256') == entry['launch']['sha256'] and
          capture.get('sha256') == entry['capture']['sha256'],
          'capture map differs from the stage step launch/capture digests')
    return record


def load_selected_pins(spec):
    """The selected generation's launcher, helper, guard and entry-point pins (closed), or None.

    r18: the r2 schema adds the causal-evidence producer pins and complete pinned repeat-approval set.
    The r1 pins remain valid and admit no causal evidence.
    """
    if spec is None:
        return None
    value, digest, _ = pinned(spec[0], 'selected pins')
    prove(digest == spec[1], 'selected pins bytes differ from the supplied digest')
    points = value.get('entry_points')
    r2 = value.get('schema') == SELECTED_PINS_SCHEMA_R2
    keys = {'schema', 'launcher', 'helper', 'guard', 'entry_points'} | (
        {'evidence_producers', 'repeat_approvers'} if r2 else set())
    prove(set(value) == keys and value['schema'] in (SELECTED_PINS_SCHEMA, SELECTED_PINS_SCHEMA_R2) and
          type(points) is dict and set(points) == set(STEP_RECORDS) and
          all(type(v) is str and HEX64.fullmatch(v) for v in
              (value['launcher'], value['helper'], value['guard'], *points.values())),
          'selected pins are not closed')
    if r2:
        producers, approvers = value['evidence_producers'], value['repeat_approvers']
        prove(type(producers) is dict and set(producers) == set(EVIDENCE_KINDS) and
              all(type(v) is str and HEX64.fullmatch(v) for v in producers.values()),
              'selected pins evidence producers are not closed')
        prove(type(approvers) is list and all(type(p) is str and p for p in approvers) and
              len(set(approvers)) == len(approvers) >= 3 and REPEAT_REQUIRED_APPROVER in approvers,
              'selected pins repeat approvers must be at least three distinct principals including %s' %
              REPEAT_REQUIRED_APPROVER)
    return value


# ---- r18 causal evidence (G1): external events, observer interruptions, one diagnostic repeat

def _evidence_file(row, where):
    """A retained {path, sha256} reference whose current bytes match; any other state is proof/integrity."""
    prove(type(row) is dict and set(row) == {'path', 'sha256'} and type(row['path']) is str and row['path'] and
          type(row['sha256']) is str and HEX64.fullmatch(row['sha256']), where+' reference malformed')
    path = Path(row['path'])
    prove(path.is_file(), where+' retained file missing: '+row['path'])
    prove(file_sha(path) == row['sha256'], where+' retained file bytes differ from its reference')
    return path


def _retained_step_identity(arm, stage, step):
    """The step's registered parent {pid, created_ticks} and guard nonce from its own records, or (None, None)."""
    p = step_paths(arm['attempt'], stage, step)
    parent = nonce = None
    for key in ('guard', 'tracking'):
        if p[key].is_file():
            value = strict_json(bounded_bytes(p[key], step+' '+key), step+' '+key)
            if type(value) is dict and parent is None:
                parent = value.get('parent')
            if key == 'guard' and type(value) is dict:
                nonce = value.get('nonce')
    return parent, nonce


def _check_record(arm, record, pins, where):
    """Closed shared binding of one causal evidence record to this arm; returns its kind."""
    prove(type(record) is dict and set(record) == EVIDENCE_KEYS, where+' is not a closed causal evidence record')
    kind = record['kind']
    prove(kind in EVIDENCE_KINDS and record['schema'] == EVIDENCE_KINDS[kind] and
          type(record['evidence_id']) is str and record['evidence_id'], where+' kind/schema/id malformed')
    binding = record['binding']
    prove(type(binding) is dict and set(binding) == EVIDENCE_BINDING_KEYS, where+' binding not closed')
    try:
        same = type(binding['attempt']) is str and same_path(binding['attempt'], arm['attempt'])
    except (ValueError, OSError):
        same = False
    prove(binding['arm'] == arm['name'] and same and binding['profile_sha256'] == arm['sha256'] and
          binding['source_manifest_sha256'] == arm['row']['source_manifest']['sha256'],
          where+' is bound to another arm, attempt, profile or source manifest')
    if kind == 'diagnostic_repeat':
        prove(binding['stage'] is None and binding['interval'] is None and binding['step'] == 'arm',
              where+' repeat binding must name the whole arm')
    else:
        prove((binding['stage'], binding['interval']) in STAGES and binding['step'] in EVIDENCE_STEPS,
              where+' stage/interval/step not a guarded step or the observer')
    producer = record['producer']
    prove(type(producer) is dict and set(producer) == {'schema', 'entry_path', 'entry_sha256', 'pid'} and
          producer['schema'] == record['schema'] and type(producer['pid']) is int and
          type(producer['entry_path']) is str and producer['entry_path'],
          where+' producer identity malformed')
    prove(pins is not None and pins['schema'] == SELECTED_PINS_SCHEMA_R2,
          where+' supplied without selected r2 producer pins')
    prove(producer['entry_sha256'] == pins['evidence_producers'][kind],
          where+' producer differs from the selected pin (a self-declared hash is not enough)')
    rows = record['source_evidence']
    prove(type(rows) is list and rows, where+' has no retained source evidence')
    for index, row in enumerate(rows):
        _evidence_file(row, '%s source_evidence[%d]' % (where, index))
    process, guard = record['process'], record['guard']
    if kind != 'diagnostic_repeat' and binding['step'] in STEP_RECORDS:
        parent, nonce = _retained_step_identity(arm, binding['stage'], binding['step'])
        if process == {'pre_start': True}:
            # a pre-start claim is refuted by any trace that the guarded step started or was captured
            p = step_paths(arm['attempt'], binding['stage'], binding['step'])
            started = [key for key in ('tracking', 'guard', 'control', 'receipt', 'capture') if p[key].exists()]
            prove(parent is None and guard is None and not started,
                  where+' claims pre-start but the step process was registered or captured: %s' % started)
        else:
            prove(parent is not None and process == parent, where+' process differs from the retained step parent')
            prove(guard == ({'nonce': nonce} if nonce is not None else None),
                  where+' guard nonce differs from the step guard receipt')
    else:
        prove(type(process) is dict and set(process) == {'pid', 'created_ticks'} and
              all(type(v) is int for v in process.values()) and guard is None,
              where+' observer/repeat process identity malformed')
    return kind


def _check_event(record, where):
    payload = record['payload']
    prove(type(payload) is dict and set(payload) == EVENT_PAYLOAD_KEYS and
          payload['event_type'] in EXTERNAL_EVENTS | AUTOMATIC_EVENTS and
          payload['request_outcome'] in EVENT_OUTCOMES and
          all(type(payload[k]) is str and payload[k] for k in ('occurred_utc', 'actor_or_source',
                                                                'action_or_event_id')),
          where+' external event payload not closed')


def _check_observer(arm, record, events, observer_pin, where):
    payload = record['payload']
    binding = record['binding']
    prove(binding['step'] == 'observer' and type(payload) is dict and set(payload) == OBSERVER_PAYLOAD_KEYS,
          where+' observer interruption payload not closed')
    invocation, termination = payload['observer_invocation'], payload['termination']
    prove(type(invocation) is dict and set(invocation) == {'path', 'sha256', 'interval', 'output', 'process'} and
          invocation['sha256'] == observer_pin and invocation['interval'] == binding['interval'] and
          invocation['process'] == record['process'],
          where+' observer invocation is not the pinned observer of this interval and process')
    try:
        here = type(invocation['output']) is str and same_path(invocation['output'],
                                                              arm['dumps']/('i%d' % binding['interval']))
    except (ValueError, OSError):
        here = False
    prove(here, where+' observer output is not this arm\'s interval dump folder')
    try:
        entry = (_ordinary_dump_file(invocation['path'], 'observer entry')
                 if type(invocation['path']) is str and invocation['path'] else None)
    except OSError:
        entry = None
    prove(entry is not None and file_sha(entry) == observer_pin,
          where+' observer invocation path is not an ordinary file with the pinned observer bytes')
    prove(type(termination) is dict and set(termination) == {'observed_by', 'exit_or_signal', 'record'} and
          type(termination['observed_by']) is str and termination['observed_by'] and
          type(termination['exit_or_signal']) in (int, str), where+' observer termination malformed')
    retained, _, _ = pinned(_evidence_file(termination['record'], where+' termination record'),
                            where+' termination record')
    prove(set(retained) == OBSERVER_TERMINATION_KEYS and retained['schema'] == OBSERVER_TERMINATION_SCHEMA and
          retained['invocation'] == invocation and retained['observed_by'] == termination['observed_by'] and
          retained['exit_or_signal'] == termination['exit_or_signal'],
          where+' retained termination record does not bind this observer invocation')
    ref = payload['external_event_ref']
    event = events.get(ref) if type(ref) is str else None
    prove(event is not None, where+' names no external event in this arm\'s evidence')
    prove(event['binding']['step'] == 'observer' and event['binding']['interval'] == binding['interval'] and
          event['process'] == record['process'], where+' external event targeted another process or step')
    return event


def _check_repeat(arm, record, pins, where):
    payload = record['payload']
    prove(type(payload) is dict and set(payload) == REPEAT_PAYLOAD_KEYS and type(payload['repeat_id']) is str and
          payload['repeat_id'], where+' repeat payload not closed')
    prove(payload['repeat_ordinal'] == 1 and type(payload['repeat_ordinal']) is int,
          where+' only one diagnostic repeat is admitted (Policy v2)')
    original = payload['original']
    prove(type(original) is dict and set(original) == {'attempt', 'profile', 'outcome'},
          where+' original attempt reference malformed')
    try:
        distinct = type(original['attempt']) is str and not same_path(original['attempt'], arm['attempt'])
    except (ValueError, OSError):
        distinct = False
    prove(distinct, where+' repeat must be a new attempt, never the original overwritten')
    profile = _evidence_file(original['profile'], where+' original profile')
    _evidence_file(original['outcome'], where+' original outcome')
    row, _, _ = pinned(profile, where+' original profile')
    prove(type(row) is dict and set(row) == PROFILE_KEYS, where+' original profile not closed')
    changed = sorted(k for k in PROFILE_KEYS - REPEAT_LOCATION_KEYS if row[k] != arm['row'][k])
    prove(not changed, where+' repeat changes source/input/profile/budget keys: %s' % changed)
    eligibility = payload['eligibility']
    prove(type(eligibility) is dict and set(eligibility) == {'machine_conditions', 'no_cheaper_reproduction'},
          where+' eligibility not closed')
    for key in sorted(eligibility):
        _evidence_file(eligibility[key], where+' eligibility '+key)
    approvals = payload['approvals']
    required = set(pins['repeat_approvers'])
    prove(type(approvals) is list and all(type(a) is dict and set(a) == {'principal', 'decision', 'utc', 'record'}
                                          for a in approvals), where+' approvals malformed')
    principals = [a['principal'] for a in approvals]
    prove(len(set(principals)) == len(principals) and set(principals) == required,
          where+' approvals must be exactly one from each pinned approver %s' % sorted(required))
    for a in approvals:
        prove(a['decision'] == 'approve' and type(a['utc']) is str and a['utc'],
              where+' approval by %s is not an approval' % a['principal'])
        _evidence_file(a['record'], where+' approval record of '+a['principal'])
    return {'repeat_id': payload['repeat_id'], 'original_attempt': original['attempt'],
            'approvers': sorted(required)}


def load_evidence(arm, spec, pins, observer_pin):
    """r18: this arm's closed causal-evidence bundle, all of it valid, or a proof/integrity FAIL; empty without one.

    Evidence never creates a PASS, never downgrades a proven FAIL and never excuses a broken binding.
    """
    empty = {'events': {}, 'observers': {}, 'repeat': None, 'bundle': None}
    if spec is None:
        return empty
    path, pin = spec
    bundle, digest, _ = pinned(path, arm['name']+' causal evidence bundle')
    prove(digest == pin, arm['name']+' causal evidence bundle bytes differ from the supplied digest')
    prove(type(bundle) is dict and set(bundle) == {'schema', 'arm', 'profile_sha256', 'records'} and
          bundle['schema'] == EVIDENCE_BUNDLE_SCHEMA and bundle['arm'] == arm['name'] and
          bundle['profile_sha256'] == arm['sha256'] and type(bundle['records']) is list and bundle['records'],
          arm['name']+' causal evidence bundle is not this arm\'s closed bundle')
    found = dict(empty, events={}, observers={}, bundle={'path': str(Path(path).resolve()), 'sha256': pin})
    seen, observers = set(), []
    for index, ref in enumerate(bundle['records']):
        where = '%s causal evidence[%d]' % (arm['name'], index)
        record_path = _evidence_file(ref, where)
        record, _, _ = pinned(record_path, where)
        kind = _check_record(arm, record, pins, where)
        prove(record['evidence_id'] not in seen, where+' repeats an evidence id')
        seen.add(record['evidence_id'])
        if kind == 'external_event':
            _check_event(record, where)
            found['events'][ref['sha256']] = record
        elif kind == 'observer_interruption':
            observers.append((record, where))
        else:
            prove(found['repeat'] is None, where+' a second diagnostic repeat record is not admitted')
            found['repeat'] = _check_repeat(arm, record, pins, where)
    for record, where in observers:
        event = _check_observer(arm, record, found['events'], observer_pin, where)
        key = record['binding']['interval']
        prove(key not in found['observers'], where+' a second observer interruption for one interval')
        found['observers'][key] = {'record': record, 'event': event}
    return found


# r20: load_evidence already refused a pre-start claim with any trace of the guarded step, so no workload ran
PRESTART_NOTE = ('is a pre-start claim: no workload outcome (no guarded process was registered or captured); '
                 'the event alone does not establish the refusal cause')


def _unexplained(attempt, stage, step, event):
    """None when the event explains its bound step's stop, else why not (r19: the guard's first trigger governs).

    Guard r3 trigger() records only the first reason, cancel first within one sample; a later cancellation
    cannot explain an earlier free-floor, exit or descendant trigger, and guardian_failure overwrites the
    reason, so the original cause is unknown. The guard's trigger time is monotonic and never retained, so
    occurred_utc cannot order the event against the stop.
    """
    payload = event['payload']
    if payload['request_outcome'] not in EXPLAINING_OUTCOMES or payload['event_type'] in AUTOMATIC_EVENTS:
        return 'does not establish an external cause'
    if payload['event_type'] not in EXPLAINING_EVENTS:
        return ('has no independent host/execution binding in this evidence schema (an unsupported path, not a '
                'policy exclusion): cause not established')
    if event['process'] == {'pre_start': True}:
        return PRESTART_NOTE
    if step not in STEP_RECORDS:
        return 'has no retained guard receipt to agree with'
    try:
        guard = strict_json(bounded_bytes(step_paths(attempt, stage, step)['guard'], step+' guard receipt'),
                            step+' guard receipt')
    except (OSError, ProofError):
        return 'has no readable guard receipt to agree with'
    reason = guard.get('reason') if type(guard) is dict else None
    if reason != 'user_cancel':
        return 'does not explain the guard\'s retained first trigger %r' % (reason,)
    cleanup = guard.get('cleanup')
    if not (guard.get('status') in GUARD_EXITED and guard.get('workload_exit_confirmed') is True and
            type(cleanup) is dict and cleanup.get('remaining') == [] and cleanup.get('action_errors') == []):
        return 'cancelled workload exit or cleanup is not complete (status %r)' % (guard.get('status'),)
    return None


def apply_events(row, stage, evidence, attempt):
    """An evidenced external event explains only a still-unresolved stop of its own bound step and process.

    A FAIL (resource/robustness, proven by r12/r13) is never downgraded; an automatic launcher action, a
    request that was not acknowledged or observed, an event for another step, or one the retained guard
    receipt does not confirm (r19 _unexplained) leaves VOID-SUSPECT.
    """
    if (row.get('classification') != 'VOID-SUSPECT' or row.get('class') == 'missing' or
            row.get('unproved_stop_fail')):
        return row
    step = row.get('failed_step')
    notes, explained, no_workload = [], None, []
    for event in evidence['events'].values():
        binding, payload = event['binding'], event['payload']
        if binding['stage'] != stage or binding['step'] != step:
            continue
        why = _unexplained(attempt, stage, step, event)
        if why is None:
            explained = explained or event
        else:
            notes.append('%s %s (%s) %s' % (event['evidence_id'], payload['event_type'],
                                            payload['request_outcome'], why))
            if why == PRESTART_NOTE:
                no_workload.append(event['evidence_id'])
    if explained is None:
        if notes:
            row = dict(row, causality='%s; %s' % (row['causality'], '; '.join(notes)))
        if no_workload:
            # r20: not an executed-workload stop; kept distinct so it is never read as a workload regression
            row = dict(row, workload_outcome={'outcome': 'no_workload_started', 'evidence': no_workload,
                                              'cause_established': False})
        return row
    payload = explained['payload']
    return dict(row, classification='VOID-ENVIRONMENT', causality='external %s %s by %s (%s), evidence %s; '
                'earlier unresolved cause: %s' % (payload['event_type'], payload['action_or_event_id'],
                                                  payload['actor_or_source'], payload['request_outcome'],
                                                  explained['evidence_id'], row['causality']))


def _now(path):
    if not path.exists():
        return {'present': False, 'sha256': None, 'bytes': None}
    if path.suffix == '.json':
        raw = bounded_bytes(path, 'retained '+str(path))
        return {'present': True, 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
    return {'present': True, 'sha256': file_sha(path), 'bytes': path.stat().st_size}


def capture_provenance(arm, stage, step, captures, pins):
    """CAPTURE-INVENTORY-SCHEMA-r2 section 3 checks 1-7 for one stop-dependent FAIL: None, or the first unmet check.

    Check 8 (the r12 checks) has already passed in the caller; nothing here can upgrade a VOID or REVIEW.
    Retained-byte provenance under the trusted-code local-host model, not authentication.
    """
    entries, missing = captures if captures is not None else (None, 'check 1 map: no captures map for this arm')
    if entries is None:
        return missing
    if pins is None:
        return 'check 3 pins: no selected generation pins supplied'
    entry = entries.get((stage, step))
    if entry is None or entry['interval'] != dict(STAGES)[stage]:
        return 'check 1 map: no entry for this stage, interval and step'
    p = step_paths(arm['attempt'], stage, step)
    try:
        if not (same_path(entry['capture']['path'], p['capture']) and same_path(entry['launch']['path'], p['launch'])):
            return 'check 1 map: entry paths are not this step\'s lf-r1 records'
        stage_capture_evidence(arm['attempt'], stage, step, entry, arm['sha256'])
        if not p['capture'].is_file():
            return 'check 2 capture: no launching-parent capture'
        raw = bounded_bytes(p['capture'], step+' capture')
        if sha256(raw).hexdigest() != entry['capture']['sha256']:
            return 'check 2 capture: bytes differ from the map entry'
        cap = strict_json(raw, step+' capture')
        if not (type(cap) is dict and set(cap) == CAPTURE_KEYS and cap['schema'] == STEP_CAPTURE_SCHEMA):
            return 'check 2 capture: not a closed lf-r1 capture'
        if cap['capture_mode'] != 'launching-parent':
            return 'check 2 capture: mode %r is not the launching parent' % (cap['capture_mode'],)
        binding, writer, files = cap['binding'], cap['writer'], cap['files']
        expected = {'arm': arm['name'], 'stage': stage, 'interval': dict(STAGES)[stage], 'step': step}
        if not (type(binding) is dict and set(binding) == BINDING_KEYS and
                all(binding[k] == v for k, v in expected.items())):
            return 'check 3 binding: capture names another arm, stage, interval or step'
        if not (type(binding['attempt']) is str and same_path(binding['attempt'], arm['attempt']) and
                type(binding['output']) is str and same_path(binding['output'], p['out'])):
            return 'check 3 binding: attempt or output is not this guarded step'
        if not p['launch'].is_file():
            return 'check 4 launch record: missing'
        launch_raw = bounded_bytes(p['launch'], step+' launch')
        digest = sha256(launch_raw).hexdigest()
        if not (type(files) is dict and set(files) == set(CAPTURE_FILES) and
                all(type(r) is dict and set(r) == FILE_ROW_KEYS for r in files.values())):
            return 'check 2 capture: file rows not closed'
        if not (digest == cap['launch_record_sha256'] == entry['launch']['sha256'] == files['launch']['sha256']):
            return 'check 4 retained launch digest: the launch record differs from the captured digest'
        launch = strict_json(launch_raw, step+' launch record')
        if not (type(launch) is dict and set(launch) == LAUNCH_KEYS and launch['schema'] == STEP_LAUNCH_SCHEMA and
                launch['binding'] == binding and launch['writer'] == writer):
            return 'check 4 launch record: not the closed record of this capture\'s writer and binding'
        if launch['profile'].get('sha256') != arm['sha256']:
            return 'check 3 pins: launch record names another profile'
        if not (writer['launcher']['sha256'] == pins['launcher'] and writer['helper']['sha256'] == pins['helper']):
            return 'check 3 pins: LF launcher or LM helper is not the selected pin'
        if launch['guard']['sha256'] != pins['guard']:
            return 'check 3 pins: guard source is not the selected pin'
        if launch['entry_point']['sha256'] != pins['entry_points'][step]:
            return 'check 3 pins: %s entry point is not the selected pin' % step
        argv = launch['argv']
        if not (type(argv) is list and len(argv) > 9 and same_path(argv[2], launch['guard']['path']) and
                same_path(argv[9], launch['entry_point']['path'])):
            return 'check 3 pins: launch argv does not run the pinned guard and entry point'
        if files['tracking']['present']:
            tracking = strict_json(bounded_bytes(p['tracking'], step+' tracking'), step+' tracking')
            if type(tracking) is not dict or tracking.get('launcher_pid') != writer['pid']:
                return 'check 4 tracking: launcher_pid is not the capturing parent'
        life = cap['lifecycle']
        if not (type(life) is dict and set(life) == LIFECYCLE_KEYS):
            return 'check 5 lifecycle: not closed'
        if life['launcher_outcome'] != 'RUNNING':
            return 'check 5 lifecycle: launcher outcome %s' % (life['launcher_outcome'],)
        if files['tracking']['present'] is not True:
            return 'check 4 tracking: RUNNING requires retained launcher tracking'
        if life['guard_status'] not in CONFIRMED_TERMINAL or life['workload_exit_confirmed'] is not True:
            return 'check 5 lifecycle: guard %s without a confirmed workload exit' % (life['guard_status'],)
        for name in CAPTURE_FILES:
            row, now = files[name], _now(p[name])
            if row['present'] is not now['present'] or (row['present'] and (
                    row['sha256'], row['bytes']) != (now['sha256'], now['bytes'])):
                return 'check 6 retained bytes: %s changed, appeared or vanished since the capture' % name
        guard = strict_json(bounded_bytes(p['guard'], step+' guard'), step+' guard') if files['guard']['present'] else {}
        control = strict_json(bounded_bytes(p['control'], step+' control'), step+' control') if files['control']['present'] else {}
        abort = strict_json(bounded_bytes(p['abort'], step+' abort'), step+' abort') if files['abort']['present'] else None
        if not (type(guard) is dict and guard.get('status') == life['guard_status'] and
                guard.get('workload_exit_confirmed') is True and guard.get('reason') == life['guard_reason']):
            return 'check 5 lifecycle: the retained guard receipt is not the captured terminal state'
        if not (type(cap['nonce']) is str and cap['nonce'] and type(control) is dict and
                guard.get('nonce') == control.get('nonce') == cap['nonce'] and
                (abort is None or (type(abort) is dict and abort.get('nonce') == cap['nonce']))):
            return 'check 7 nonce: guard, control and abort do not carry the captured nonce'
        if files['cancel']['present']:
            # A reason string is insufficient. Reuse every unchanged r12 RSS predicate.
            classification, _ = stop_cause(arm['attempt'], stage, {'failed_step': step}, arm['sha256'])
            if guard.get('reason') != 'rss_limit' or life['guard_reason'] != 'rss_limit' or classification != 'FAIL':
                return 'check 6 chronology: cancel present without the fully proved r12 RSS latch'
    except (ProofError, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return 'capture provenance unreadable: %s %s' % (type(error).__name__, error)
    return None


def outcome(attempt, stage, profile_sha256=None, provenance=None):
    """Observe a stage; unverified stop records never establish causal attribution.

    Adopted rows still need the independent proof checks in the caller. Every
    other outcome remains VOID-SUSPECT until the R8 causal path is complete. A
    marker or a guard reason alone is not external-event evidence.
    """
    require(stage in {name for name, _ in STAGES}, 'unknown outcome stage')
    path = attempt/('stage-%s.json' % stage)
    evidence = []
    for folder, stem in (('run-'+stage, 'run'), ('reader-'+stage, 'reopen')):
        for suffix, role in (('.guard-abort.json', 'guard-abort'), ('.cancel', 'cancel-marker'),
                             ('.guard-control.json', 'guard-control'), ('.guard.json', 'guard'),
                             ('.json', 'workload-receipt')):
            observed = attempt/folder/(stem+suffix)
            if observed.is_file():
                evidence.append({'role': role, 'path': str(observed),
                                 'sha256': file_sha(observed), 'nbytes': observed.stat().st_size})
        observed = attempt/(folder+'.tracking.json')
        if observed.is_file():
            evidence.append({'role': 'launcher-tracking', 'path': str(observed),
                             'sha256': file_sha(observed), 'nbytes': observed.stat().st_size})
    row = {'class': 'missing', 'classification': 'VOID-SUSPECT',
           'causality': 'unresolved; stop evidence has not been independently bound',
           'path': str(path), 'stop_evidence': evidence}
    if not path.is_file():
        return row
    record, digest, _ = pinned(path, 'stage-'+stage)
    steps = record.get('steps', [])
    prove(type(steps) is list and all(type(step) is dict for step in steps),
          'stage steps must be objects: '+str(path))
    status = record.get('status')
    row.update(status=status, failed_step=record.get('failed_step'), reason=record.get('reason'),
               sha256=digest, width_gate_passed=record.get('width_gate_passed'),
               steps={step.get('name'): {key: value for key, value in step.items()
                      if key.endswith('sha256') or key in ('ok', 'exit')} for step in steps})
    if status in (ADOPTED, GATE_STOP):
        row.update({'class': 'adopted' if status == ADOPTED else 'gate_stop',
                    'classification': None, 'causality': None})
    else:
        row['class'] = 'unresolved' if status in (PRESEAL_REFUSED, 'FAILED') else 'incomplete'
        if status == 'FAILED' and profile_sha256 is not None:
            row['classification'], row['causality'] = stop_cause(attempt, stage, record, profile_sha256)
            if row['classification'] == 'FAIL':
                # r13: the stop-dependent FAIL also needs the launching parent's retained capture
                unmet = 'check 1 map: no capture provenance' if provenance is None else provenance(
                    stage, record.get('failed_step'))
                if unmet is None:
                    row['class'] = 'resource_fail'
                else:
                    row['classification'] = 'VOID-SUSPECT'
                    row['causality'] = 'capture provenance %s; r12 cause %s' % (unmet, row['causality'])
                    row['unproved_stop_fail'] = True   # r18: no external event may excuse this stop
    return row


# ---- arms and the proof chain

def load_arm(name, attempt, dumps, profile, profile_sha256):
    row, digest, _ = pinned(profile, name+' profile')
    prove(digest == profile_sha256, name+' profile bytes differ from the given sha256')
    prove(row.get('schema') == PROFILE_SCHEMA and set(row) == PROFILE_KEYS, name+' profile is not a closed v1 profile')
    for key in ('output_directory', 'store_directory'):
        prove(type(row[key]) is str and Path(row[key]).is_absolute(), name+' profile %s is not absolute' % key)
    prove(same_path(row['output_directory'], attempt), name+' attempt is not the profile output directory')
    manifest = row['source_manifest']
    prove(type(manifest) is dict and set(manifest) == {'path', 'sha256'} and type(manifest['sha256']) is str and
          HEX64.fullmatch(manifest['sha256']), name+' profile source manifest pin malformed')
    return {'name': name, 'attempt': Path(attempt), 'dumps': Path(dumps), 'profile': Path(profile),
            'sha256': profile_sha256, 'row': row, 'store': Path(row['store_directory'])}


def nonnegative(value):
    return type(value) is int and value >= 0


def prove_retained_accounting(value, pid, who):
    fields = {'limit_bytes', 'scope_id', 'process_epoch', *RETAINED_SCALARS, *RETAINED_MAPPINGS}
    prove(type(value) is dict and set(value) == fields and value['limit_bytes'] == RETAINED_LIMIT and
          type(value['scope_id']) is str and value['scope_id'] and
          value['process_epoch'] == 'prepared-restart-'+str(pid),
          who+'complete shared retained scope accounting required')
    prove(all(nonnegative(value[name]) for name in RETAINED_SCALARS) and
          value['retained_bytes'] <= value['peak_retained_bytes'] <= value['limit_bytes'] and
          sum(value[name] for name in ('pinned_bytes', 'pending_bytes', 'evictable_bytes',
                                       'non_cache_owned_bytes')) == value['retained_bytes'],
          who+'retained held/cache accounting does not reconcile')
    for name in RETAINED_MAPPINGS:
        prove(type(value[name]) is dict and len(value[name]) <= 4096 and
              all(type(key) is str and key and nonnegative(count) for key, count in value[name].items()),
              who+'bounded retained held/cache counter maps required')
    prove(sum(value['purpose_bytes'].values()) == value['retained_bytes'],
          who+'retained purpose accounting does not reconcile')


def prove_retained_producer(reader, scope_id, who):
    """Optional S8 field: absent in older receipts; when present both observations must be complete."""
    if 'retained_producer' not in reader:
        return
    producer = reader['retained_producer']
    prove(type(producer) is dict and set(producer) == {'before_close', 'after_close'},
          who+'live-producer child accounting is incomplete')
    for value in producer.values():
        prove(type(value) is dict and set(value) == {'scope_id', *PRODUCER_SCALARS, *PRODUCER_MAPPINGS} and
              value['scope_id'] == scope_id and all(nonnegative(value[name]) for name in PRODUCER_SCALARS) and
              value['producer_bytes'] <= value['producer_peak_bytes'] <= value['producer_limit_bytes'],
              who+'live-producer child accounting does not reconcile')
        for name in PRODUCER_MAPPINGS:
            prove(type(value[name]) is dict and len(value[name]) <= 4096 and
                  all(type(key) is str and 0 < len(key) <= 256 and nonnegative(count)
                      for key, count in value[name].items()),
                  who+'bounded live-producer counter maps required')
        prove(sum(value['producer_purpose_bytes'].values()) == value['producer_bytes'],
              who+'live-producer purpose accounting does not reconcile')


def prove_stage(arm, mode, interval):
    """Every proof file of one adopted stage, each re-derived and bound to the next (FAIL on any break)."""
    at, st, who = arm['attempt'], arm['store'], '%s %s: ' % (arm['name'], mode)
    name = lambda kind: '%s-interval-%04d.json' % (kind, interval)       # noqa: E731
    paths = {'stage_record': at/('stage-%s.json' % mode), 'producer_receipt': at/('run-'+mode)/'run.json',
             'reader_receipt': at/('reader-'+mode)/'reopen.json', 'verdict': st/name('reader-verdict'),
             'runner_record': st/name('runner-record'), 'sealed': st/name('sealed-awaiting-reader'),
             'adopted': st/name('adopted')}
    files, pins = {}, {}
    for key, path in paths.items():
        files[key], pins[key], _ = pinned(path, who+key)
    stage, producer, reader = files['stage_record'], files['producer_receipt'], files['reader_receipt']
    verdict, runner, sealed, adopted = files['verdict'], files['runner_record'], files['sealed'], files['adopted']
    steps = stage.get('steps')
    prove(stage.get('schema') == STAGE_SCHEMA and type(steps) is list and
          [s.get('name') for s in steps if type(s) is dict] == list(STAGE_STEPS) and
          all(s.get('ok') is True for s in steps), who+'stage record lacks exactly one clean step of each kind')
    named = {s['name']: s for s in steps}
    prove(stage.get('status') in ((ADOPTED, GATE_STOP) if mode == 'interval' else (ADOPTED,)) and
          named['runner'].get('receipt_sha256') == pins['producer_receipt'] and
          named['reader'].get('receipt_sha256') == pins['reader_receipt'] and
          named['finalise'].get('verdict_sha256') == pins['verdict'] and
          named['adopt'].get('adopted_sha256') == pins['adopted'],
          who+'stage record does not name exactly these receipts, verdict and adoption')
    reference = producer.get('runner_record')
    prove(producer.get('schema') == RESULT_SCHEMA and producer.get('mode') == mode and
          producer.get('status') == SEALED_STATUS[mode] and producer.get('errors') == [] and
          producer.get('profile_sha256') == arm['sha256'] and type(reference) is dict and
          set(reference) == {'path', 'sha256'} and type(reference['path']) is str and
          same_path(reference['path'], paths['runner_record']) and reference['sha256'] == pins['runner_record'],
          who+'producer receipt is not a clean seal of this mode naming the runner record')
    prove(runner.get('schema') == RUNNER_RECORD_SCHEMA and runner.get('interval') == interval and
          runner.get('producer_identity') == arm['sha256'], who+'runner record is not this profile\'s interval')
    prove(sealed.get('schema') == SEALED_SCHEMA and sealed.get('interval') == interval and
          sealed.get('runner_record_sha256') == pins['runner_record'], who+'sealed record names another runner')
    prove(reader.get('schema') == READER_SCHEMA and reader.get('status') == WORKLOAD_STATUS[mode] and
          reader.get('mode') == mode and reader.get('errors') == [] and reader.get('review_only') is False and
          reader.get('profile_sha256') == arm['sha256'] and
          reader.get('producer_receipt_sha256') == pins['producer_receipt'] and
          reader.get('final_reserved_bytes') == 0 and reader.get('production_acceptance') is False and
          reader.get('independent_process_reopen') is True and reader.get('remaining_children') == [] and
          'interval' not in reader,
          who+'reader receipt is not a clean independent read of this producer receipt under this profile')
    pid, producer_pid = reader.get('pid'), producer.get('pid')
    prove(type(pid) is int and pid > 0 and type(producer_pid) is int and producer_pid > 0 and pid != producer_pid,
          who+'reader did not run in a process separate from the producer')
    checks = reader.get('independent_checks')
    prove(type(checks) is dict and set(checks) == READER_CHECKS[mode] and all(v is True for v in checks.values()),
          who+'reader independent checks are not the complete passed set')
    prove(type(reader.get('view_digest')) is str and HEX64.fullmatch(reader['view_digest']),
          who+'reader view digest malformed')
    width_table(reader.get('widths'), interval, who+'reader ')
    retained, supervisor = reader.get('retained_scope'), reader.get('supervisor')
    prove(type(retained) is dict and set(retained) == {'before_close', 'after_close'} and
          all(type(v) is dict for v in retained.values()) and retained['after_close'].get('retained_bytes') == 0 and
          retained['before_close'].get('scope_id') is not None and
          retained['before_close'].get('scope_id') == retained['after_close'].get('scope_id') and
          type(supervisor) is dict, who+'reader retained-scope release or supervisor evidence incomplete')
    for value in retained.values():
        prove_retained_accounting(value, pid, who+'reader ')
    prove_retained_producer(reader, retained['before_close']['scope_id'], who+'reader ')
    prove(verdict.get('schema') == VERDICT_SCHEMA and verdict.get('status') == READER_PASS[mode] and
          verdict.get('interval') == interval and 'review_only' not in verdict and
          verdict.get('entry') == sealed.get('entry') and type(sealed.get('entry')) is dict and
          verdict.get('runner_record_sha256') == pins['runner_record'] and
          verdict.get('producer_receipt_sha256') == pins['producer_receipt'] and
          verdict.get('reopen_receipt_sha256') == pins['reader_receipt'] and
          verdict.get('reader_pid') == reader['pid'] and verdict.get('view_digest') == reader['view_digest'] and
          'accepted_catalog_digest' in reader and
          verdict.get('accepted_catalog_digest') == reader['accepted_catalog_digest'] and
          verdict.get('widths') == reader['widths'] and ('width_gate' in verdict) == ('width_gate' in reader) and
          verdict.get('width_gate') == reader.get('width_gate'),
          who+'reader verdict does not bind exactly these records or is not a copy of the reader result')
    prove(adopted.get('schema') == ADOPTED_SCHEMA and adopted.get('status') == ADOPTED_STATUS and
          adopted.get('interval') == interval and adopted.get('entry') == verdict['entry'] and
          adopted.get('verdict_sha256') == pins['verdict'] and
          adopted.get('runner_record_sha256') == pins['runner_record'] and
          'review_approval_sha256' not in adopted and type(adopted.get('catalog_digest')) is str and
          type(adopted.get('catalog_sha256')) is str, who+'adoption does not bind exactly this verdict')
    key = 'root_record_identities' if mode == 'root' else 'record_identities'
    targets = reader.get(key)
    prove(mode != 'root' or (type(targets) is dict and set(targets) == ROOT_RECORDS),
          who+'root record identities are not exactly state and mesh')
    prove(type(targets) is dict and targets and all(
        type(v) is dict and set(v) == {'sha256', 'nbytes'} and type(v['sha256']) is str and
        HEX64.fullmatch(v['sha256']) and type(v['nbytes']) is int and v['nbytes'] > 0 for v in targets.values()),
        who+'reader receipt lacks closed record identities')
    if mode == 'interval':
        prove(runner.get('record_identities') == targets, who+'runner and reader record identities differ')
    prove_sources(arm, reader.get('source_proof'), who)
    gate = verdict.get('width_gate')
    if mode == 'interval':
        prove(type(gate) is dict and gate.get('schema') == WIDTH_GATE_SCHEMA and type(gate.get('passed')) is bool,
              who+'interval verdict lacks its evaluated width gate')
        prove(stage.get('width_gate_passed') is gate['passed'] and
              (gate['passed'] is False) == (stage['status'] == GATE_STOP),
              who+'stage record and reader verdict disagree on the width gate')
    else:
        prove(gate is None, who+'root verdict carries a width gate')
    return {'paths': paths, 'pins': pins, 'files': files, 'targets': targets, 'gate': gate}


def width_table(value, interval, who):
    """width_gate.WidthTable.from_wire's closed shape, for this interval."""
    prove(type(value) is dict and set(value) == WIDTH_TABLE_KEYS and value['schema'] == WIDTH_TABLE_SCHEMA and
          value['limit_bits'] == LIMIT_BITS and type(value['interval']) is int and value['interval'] == interval and
          (value['trajectory_steps'] is None or type(value['trajectory_steps']) is int) and
          type(value['records']) is dict and all(
              type(kind) is str and type(fields) is dict and all(
                  type(name) is str and type(row) is dict and set(row) == WIDTH_ROW_KEYS and
                  all(type(n) is int and n >= 0 for n in row.values()) for name, row in fields.items())
              for kind, fields in value['records'].items()),
          who+'widths are not a closed exact-width table of interval %d' % interval)
    return value


def recompute_gate(root, interval1):
    """width_gate.gate(root, interval1) from the two recorded tables (copied, same arithmetic)."""
    def widths(table):
        return {(kind, name): max(row['max_numerator_bits'], row['max_denominator_bits'])
                for kind, fields in table['records'].items() for name, row in fields.items()}
    before, after = widths(root), widths(interval1)
    rows, passed = [], True
    for key in sorted(after):
        w1, w0 = after[key], before.get(key, 0)
        w2, w3 = w1+(w1-w0), w1+2*(w1-w0)
        ok = w2 <= INTERVAL2_SHARE*LIMIT_BITS and w3 <= INTERVAL3_SHARE*LIMIT_BITS
        passed = passed and ok
        rows.append({'record': key[0], 'field': key[1], 'w0_bits': w0, 'w0_measured': key in before,
                     'w1_bits': w1, 'w2_projected_bits': w2, 'w3_projected_bits': w3,
                     'w2_share': w2/LIMIT_BITS, 'w3_share': w3/LIMIT_BITS, 'passed': ok})
    return {'schema': WIDTH_GATE_SCHEMA, 'passed': passed, 'limit_bits': LIMIT_BITS,
            'interval2_share': INTERVAL2_SHARE, 'interval3_share': INTERVAL3_SHARE,
            'root_trajectory_steps': root['trajectory_steps'],
            'interval1_trajectory_steps': interval1['trajectory_steps'], 'rows': rows}


def prove_sources(arm, proof, who):
    """FreshSources.verify's closed proof, bound to this profile's pinned manifest and its native inventory."""
    prove(type(proof) is dict and set(proof) == SOURCE_PROOF_KEYS and
          all(type(v) is str and HEX64.fullmatch(v) for v in proof.values()), who+'source proof is not closed')
    pin = arm['row']['source_manifest']
    prove(proof['source_manifest_sha256'] == pin['sha256'], who+'source proof names another manifest')
    name = pin['path']
    prove(type(name) is str and name and '\\' not in name and ':' not in name and not Path(name).is_absolute()
          and '..' not in Path(name).parts, who+'profile manifest path is not workspace-relative')
    manifest, digest, _ = pinned(Path(arm['row']['workspace'])/name, who+'source manifest')
    prove(digest == pin['sha256'], who+'source manifest bytes differ from the profile pin')
    inventory = manifest.get('source_hashes') if type(manifest) is dict else None
    prove(type(inventory) is dict and inventory and all(
        type(k) is str and type(v) is str and HEX64.fullmatch(v) for k, v in inventory.items()),
        who+'source manifest lacks its native inventory')
    raw = json.dumps(inventory, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    prove(sha256(raw).hexdigest() == proof['native_source_digest'],
          who+"source proof native digest is not the pinned manifest's inventory")


def prove_chain(arm, proofs):
    """The interval runner extends this arm's own root once, under one workflow."""
    root, interval = proofs['root'], proofs['interval']
    rr, ir = root['files']['runner_record'], interval['files']['runner_record']
    prove(ir.get('root_runner_record_sha256') == root['pins']['runner_record'],
          arm['name']+': interval runner names another root runner record')
    prove(type(rr.get('workflow_id')) is str and rr.get('workflow_id') == ir.get('workflow_id'),
          arm['name']+': root and interval workflows differ')
    gate = recompute_gate(root['files']['verdict']['widths'], interval['files']['verdict']['widths'])
    prove(interval['gate'] == gate, arm['name']+': interval width gate is not the gate of the recorded widths')
    completed = interval['files']['producer_receipt'].get('completed_endpoint')
    prove(type(completed) is dict and completed.get('workflow_id') == rr['workflow_id'],
          arm['name']+': interval producer lacks the completed endpoint of this workflow')


def check_environment(env, observer_path, where):
    prove(type(env) is dict and set(env) == ENV_KEYS, where+'environment observation is not closed')
    flags = env['flags']
    prove(type(flags) is dict and all(flags.get(k) == v for k, v in REQUIRED_FLAGS.items()) and
          env['dont_write_bytecode'] is True, where+'interpreter flags are not -B -s -P with seed 0')
    python = env['python_environment']
    prove(type(python) is dict and all(
        k.upper() in ALLOWED_PYTHON_ENV and ALLOWED_PYTHON_ENV[k.upper()] in (None, v) for k, v in python.items())
        and python.get('PYTHONHASHSEED') == '0', where+'PYTHON* environment is not the accepted clean one')
    argv = env['argv']
    prove(type(argv) is list and argv and type(argv[0]) is str and type(env['cwd']) is str and
          same_path(Path(env['cwd'])/argv[0], observer_path),
          where+'observer was not the __main__ entry')
    prove(type(env['executable_sha256']) is str and HEX64.fullmatch(env['executable_sha256']),
          where+'interpreter executable pin malformed')



def _ordinary_dump_file(path, label='array descriptor'):
    """Cooperative local files only: refuse links/reparse ancestors before reading."""
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        prove(not stat.S_ISLNK(info.st_mode) and
              not getattr(info, 'st_file_attributes', 0) & 0x400,
              label+' path uses a link/reparse point: '+str(ancestor))
        prove(stat.S_ISREG(info.st_mode) if ancestor == path else stat.S_ISDIR(info.st_mode),
              label+' path is not ordinary: '+str(ancestor))
    return path


def validate_dump_descriptors(record, folder, expected_chunk_bytes=None):
    """Bind r4 array bytes to typed chunks; this alone does not supply reader authority.

    One 64 KiB block is retained while hashing each native chunk and the whole
    array. Chunk geometry comes from the authenticated stage proof at load_dump.
    r3 retains the explicit absence of descriptor evidence.
    """
    rows = record.get('arrays')
    prove(type(rows) is list, 'descriptor arrays not a list')
    if record.get('schema') == DUMP_SCHEMA:
        prove('store_limits' not in record and all(type(row) is dict and
              not {'descriptor', 'descriptor_sha256'} & set(row) for row in rows),
              'r3 dump cannot carry unvalidated r4 descriptor evidence')
        return None
    prove(record.get('schema') in (DUMP_SCHEMA_R4, component('array_bindings_r5').SCHEMA), 'unknown descriptor dump schema')
    limits = record.get('store_limits')
    prove(type(limits) is dict and set(limits) == {'chunk_bytes'} and
          type(limits['chunk_bytes']) is int and 8 <= limits['chunk_bytes'] <= 16*1024*1024,
          'r4 requires closed native-range integer chunk_bytes')
    chunk_bytes = limits['chunk_bytes']
    if expected_chunk_bytes is not None:
        prove(type(expected_chunk_bytes) is int and 8 <= expected_chunk_bytes <= 16*1024*1024 and
              chunk_bytes == expected_chunk_bytes, 'r4 chunk_bytes differs from the proved store configuration')
    result = {}
    for index, row in enumerate(rows):
        prove(type(row) is dict and set(row) == ARRAY_KEYS_R4 and
              type(row.get('name')) is str and row['file'] == '%04d.bin' % index,
              'r4 descriptor array row %d not closed' % index)
        who = 'array '+row['name']+': '
        desc = row['descriptor']
        prove(type(desc) is dict and set(desc) == {'dtype', 'shape', 'chunks'},
              who+'descriptor keys differ')
        prove(type(desc['dtype']) is str and type(desc['shape']) is list and
              len(desc['shape']) <= 16 and all(type(n) is int and n >= 0 for n in desc['shape']) and
              desc['dtype'] == row['dtype'] and desc['shape'] == row['shape'],
              who+'descriptor dtype/shape differs')
        try:
            dtype = np.dtype(desc['dtype'])
        except (ValueError, TypeError):
            raise ProofError(who+'descriptor dtype unknown') from None
        prove(dtype.kind in 'biuf' and dtype.itemsize in (1, 2, 4, 8) and not dtype.fields and
              dtype.newbyteorder('<').str == desc['dtype'],
              who+'descriptor requires canonical little-endian fixed-width numeric dtype')
        count = math.prod(desc['shape'])
        width = chunk_bytes // dtype.itemsize
        prove(width > 0, who+'chunk_bytes smaller than one element')
        chunks = desc['chunks']
        prove(type(chunks) is list and len(chunks) == (count + width - 1)//width and
              all(type(pin) is str and HEX64.fullmatch(pin) for pin in chunks),
              who+'descriptor chunk inventory differs')
        descriptor_pin = sha256(producer_json(desc)).hexdigest()
        prove(type(row['descriptor_sha256']) is str and row['descriptor_sha256'] == descriptor_pin,
              who+'descriptor digest differs')
        size = count*dtype.itemsize
        prove(type(row['nbytes']) is int and row['nbytes'] == size and
              type(row['sha256']) is str and HEX64.fullmatch(row['sha256']),
              who+'descriptor byte length/hash malformed')
        path = _ordinary_dump_file(Path(folder)/'arrays'/row['file'])
        path_before = path.lstat()
        whole = sha256()
        with path.open('rb', buffering=0) as stream:
            before = os.fstat(stream.fileno())
            prove(before.st_size == size, who+'descriptor file length differs')
            for chunk_index, expected in enumerate(chunks):
                elements = min(width, count-chunk_index*width)
                digest = sha256(b'atlas-typed-chunk-v1\0')
                digest.update(producer_json({'dtype': dtype.str, 'count': elements}))
                digest.update(b'\0')
                remaining = elements*dtype.itemsize
                while remaining:
                    block = stream.read(min(65536, remaining))
                    prove(bool(block), who+'chunk %d truncated' % chunk_index)
                    digest.update(block)
                    whole.update(block)
                    remaining -= len(block)
                prove(digest.hexdigest() == expected,
                      who+'chunk %d bytes differ from bound typed chunk' % chunk_index)
            prove(stream.read(1) == b'', who+'descriptor file extended')
            after = os.fstat(stream.fileno())
        current = _ordinary_dump_file(path).lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        # Windows fstat and pathname stat can report different ctime semantics.
        # Keep full stability checks within each API, and bind both APIs by the
        # file identity, length and modification time rather than cross-API ctime.
        shared_identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        prove(identity(before) == identity(after) and
              identity(path_before) == identity(current) and
              shared_identity(before) == shared_identity(path_before),
              who+'descriptor file changed during read')
        prove(whole.hexdigest() == row['sha256'], who+'whole-array digest differs')
        prove(row['name'] not in result, who+'duplicate descriptor name')
        result[row['name']] = descriptor_pin
    return result


def load_dump(arm, interval, proof, observer_pin):
    """A closed r3/r4 PASS dump of the interval, unchanged since taken, bound to this arm's re-derived proof."""
    folder = arm['dumps']/('i%d' % interval)
    who = '%s i%d dump: ' % (arm['name'], interval)
    record, _, _ = pinned(folder/'dump.json', who+'dump.json')
    B = component('array_bindings_r5')
    r5 = record.get('schema') == B.SCHEMA
    r4 = record.get('schema') == DUMP_SCHEMA_R4 or r5
    keys = DUMP_KEYS_R5 if r5 else DUMP_KEYS_R4 if r4 else DUMP_KEYS
    prove(set(record) == keys, who+'dump keys differ from its closed schema: %s' % sorted(set(record) ^ keys))
    prove(record['schema'] in (DUMP_SCHEMA, DUMP_SCHEMA_R4, B.SCHEMA) and record['status'] == 'PASS' and record['errors'] == [] and
          record['interval'] == interval and type(record['pid']) is int, who+'dump did not pass')
    profile = record['profile']
    prove(type(profile) is dict and set(profile) == {'path', 'sha256'} and profile['sha256'] == arm['sha256'] and
          same_path(profile['path'], arm['profile']), who+'dump is from another profile')
    observer = record['observer']
    prove(type(observer) is dict and set(observer) == {'path', 'sha256', 'no_user_site', 'safe_path'} and
          observer['sha256'] == observer_pin and observer['no_user_site'] == 1 and observer['safe_path'] is True,
          who+'observer differs from the independently supplied pin')
    for key in ('environment', 'environment_after'):
        check_environment(record[key], observer['path'], who+key+' ')
    for key in ('executable', 'executable_sha256', 'version', 'flags', 'python_environment'):
        prove(record['environment'][key] == record['environment_after'][key], who+'interpreter changed: '+key)
    interp = record['interpreter']
    hooks = (interp or {}).get('instrumentation_at_start') if type(interp) is dict else None
    prove(type(interp) is dict and interp.get('interpreter_seed') == {'PYTHONHASHSEED': '0', 'hash_randomization': 0}
          and type(hooks) is dict and not hooks.get('trace') and not hooks.get('profile') and
          not hooks.get('monitoring_tools') and not hooks.get('tracemalloc'), who+'interpreter gate not clean')
    audit = record['loaded_audit']
    prove(type(audit) is dict and audit.get('exempt') == {'path': observer['path'], 'sha256': observer_pin} and
          all(audit.get(k) is True for k in ('data_only_exclusion', 'first_resolution', 'source_bytes_loader')),
          who+'observer fence audit incomplete')
    prove(record['source_proof'] == record['source_proof_before'] == proof['files']['reader_receipt']['source_proof'],
          who+'dump sources are not the reader-proved sources of the arm')
    bindings = record['bindings']
    prove(type(bindings) is dict and set(bindings) == BINDING_NAMES and all(
        type(v) is dict and set(v) == {'path', 'sha256', 'nbytes'} for v in bindings.values()),
        who+'dump bindings are not closed')
    adopted = proof['files']['adopted']
    for key in BINDING_NAMES - {'catalog'}:
        prove(bindings[key]['sha256'] == proof['pins'][key] and same_path(bindings[key]['path'], proof['paths'][key]),
              who+'dump %s binding differs from the re-derived proof' % key)
    prove(bindings['catalog']['sha256'] == adopted['catalog_sha256'] and
          same_path(bindings['catalog']['path'], arm['store']/CATALOG), who+'dump catalog is not the adopted one')
    verdict = proof['files']['verdict']
    prove(record['widths'] == verdict.get('widths') and record['width_gate'] == verdict.get('width_gate'),
          who+'dump widths or width gate differ from the reader verdict')
    targets = proof['targets']
    expected = {k: v for k, v in targets.items() if k != 'partition'}
    prove(record['records'] == expected, who+'dumped record identities differ from the reader-proved targets')
    partition = record['partition']
    dumped = r5 and interval == 0 and type(partition) is dict and partition.get('dumped') is True
    if dumped:
        # The root v2 descriptor itself (array_bindings_r5.root_partition_v2 binds it to the header).
        prove(set(partition) == {'dumped', 'route', 'reference', 'sha256', 'nbytes'} and
              partition['route'] == B.PARTITION_ROUTE and 'partition' not in targets and
              type(partition['reference']) is dict and type(partition['sha256']) is str and
              HEX64.fullmatch(partition['sha256']) and type(partition['nbytes']) is int and partition['nbytes'] > 0,
              who+'dumped partition entry not closed')
    else:
        prove(type(partition) is dict and set(partition) == {'dumped', 'identity', 'reason'} and
              partition['dumped'] is False and partition['identity'] == targets.get('partition') and
              type(partition['reason']) is str, who+'partition entry not closed')
    head = record['head']
    prove(type(head) is dict and set(head) == (B.HEAD_KEYS if r5 else {'key', 'kind', 'sequence'}) and type(head['key']) is str and
          head['sequence'] == interval and head['kind'] == ('root' if interval == 0 else 'successor'),
          who+'dump head is not the interval head')
    before, after = record['store_token_before'], record['store_token_after']
    prove(type(before) is list and before == after and before and before[0] == adopted['catalog_digest'],
          who+'store change token missing, changed during extraction, or not the adopted catalog')
    expected_files = {'dump.json'} | {'records/%s.json' % k for k in record['records']}
    if dumped:
        prove('partition' not in record['records'], who+'partition record name collides with the dumped partition')
        expected_files.add('records/partition.json')
    arrays = record['arrays']
    prove(type(arrays) is list, who+'arrays not a list')
    names = []
    for index, row in enumerate(arrays):
        prove(type(row) is dict and set(row) == (ARRAY_KEYS_R4 if r4 else ARRAY_KEYS) and row['file'] == '%04d.bin' % index and
              type(row['name']) is str and not row['name'].startswith(RECORD_ARRAY) and
              type(row['shape']) is list and all(type(n) is int and n >= 0 for n in row['shape']),
              who+'array row %d not closed' % index)
        try:
            itemsize = np.dtype(row['dtype']).itemsize
        except TypeError:
            raise ProofError(who+'array %s dtype unknown' % row['name']) from None
        prove(row['nbytes'] == math.prod(row['shape'])*itemsize, who+'array %s size differs' % row['name'])
        names.append(row['name'])
        expected_files.add('arrays/'+row['file'])
    prove(names == sorted(set(names)), who+'array names not unique and sorted')
    found = {Path(root, f).relative_to(folder).as_posix() for root, _, fs in os.walk(folder) for f in fs}
    prove(found == expected_files, who+'dump folder holds unaccounted or missing files: %s' %
          sorted(found ^ expected_files)[:5])
    for name, identity in record['records'].items():
        path = folder/'records'/(name+'.json')
        prove(path.stat().st_size == identity['nbytes'] and file_sha(path) == identity['sha256'],
              who+'dumped record changed since the dump: '+name)
    if dumped:
        path = folder/'records'/'partition.json'
        prove(path.stat().st_size == partition['nbytes'] and file_sha(path) == partition['sha256'],
              who+'dumped root partition changed since the dump')
    if r4:
        endpoint = (proof['files']['runner_record'].get('root') if interval == 0 else
                    proof['files']['producer_receipt'].get('completed_endpoint'))
        limits = endpoint.get('store_limits') if type(endpoint) is dict else None
        prove(type(limits) is dict and type(limits.get('chunk_bytes')) is int and
              8 <= limits['chunk_bytes'] <= 16*1024*1024,
              who+'proved endpoint lacks native-range chunk_bytes for r4')
        validate_dump_descriptors(record, folder, limits['chunk_bytes'])
    else:
        for row in arrays:
            path = folder/'arrays'/row['file']
            prove(path.stat().st_size == row['nbytes'] and file_sha(path) == row['sha256'],
                  who+'dumped array changed since the dump: '+row['name'])
    if interval == 1:
        completed = proof['files']['producer_receipt']['completed_endpoint']
        prove(head['key'] == completed.get('head_key'), who+'dump head is not the producer\'s completed head')
    B.validate_dump_evidence(sys.modules[__name__], record, arm, proof, observer_pin)
    return record


def distinct_arms(arms, proofs, dumps):
    """Different attempts, stores, profiles and dump folders; common budgets, limits and interpreter."""
    a, b = arms['before'], arms['after']
    for key in ('attempt', 'store', 'dumps'):
        prove(not same_path(a[key], b[key]) and not (a[key].exists() and b[key].exists() and
                                                    os.path.samefile(a[key], b[key])),
              'arms share their %s' % key)
    prove(a['sha256'] != b['sha256'], 'arms share one profile')
    differing = sorted(k for k in PROFILE_KEYS if a['row'][k] != b['row'][k])
    prove(set(differing) <= PROFILE_SOURCE_KEYS, 'arm profiles differ outside the source keys: %s' %
          sorted(set(differing)-PROFILE_SOURCE_KEYS))
    for mode in proofs['before']:
        pa, pb = proofs['before'][mode]['files'], proofs['after'][mode]['files']
        prove(pa['producer_receipt'].get('guard_limits') == pb['producer_receipt'].get('guard_limits'),
              '%s guard limits differ between arms' % mode)
        if mode == 'interval':
            ca, cb = pa['producer_receipt']['completed_endpoint'], pb['producer_receipt']['completed_endpoint']
            for key in ('store_limits', 'store_compression'):
                prove(ca.get(key) == cb.get(key), 'interval %s differ between arms' % key)
    for interval in dumps['before']:
        ea, eb = dumps['before'][interval]['environment'], dumps['after'][interval]['environment']
        for key in ('executable_sha256', 'version', 'implementation', 'flags'):
            prove(ea[key] == eb[key], 'arms used different interpreters (%s)' % key)
    return differing


def reader_pairs(proofs):
    """Identity pairs re-derived from the two arms' reader-checked proof records only."""
    pairs = []
    for mode, pa in proofs['before'].items():
        pb = proofs['after'][mode]
        for kind in sorted(set(pa['targets']) & set(pb['targets'])):
            pairs.append((pa['targets'][kind]['sha256'], pb['targets'][kind]['sha256']))
        pairs += token_pairs(pa['files']['runner_record'].get('workflow_id'),
                             pb['files']['runner_record'].get('workflow_id'), mode+' workflow_id')
        if mode == 'root':
            pairs += token_pairs(pa['files']['runner_record']['root'].get('root_key'),
                                 pb['files']['runner_record']['root'].get('root_key'),
                                 'reader-proved root_key')
        if mode == 'interval':
            ca = pa['files']['producer_receipt']['completed_endpoint']
            cb = pb['files']['producer_receipt']['completed_endpoint']
            for key in ENDPOINT_IDS:
                pairs += token_pairs(ca.get(key), cb.get(key), 'completed_endpoint.'+key)
            ra, rb = array_table(pa), array_table(pb)
            for group in sorted(GROUPS):
                xa = {n: r['sha256'] for n, r in ra[group].items()}
                xb = {n: r['sha256'] for n, r in rb[group].items()}
                pairs += [(xa[n], xb[n]) for n in sorted(set(xa) & set(xb))]
    return pairs


# ---- arrays

def array_table(proof):
    """The i1 reader-checked producer table: six closed groups of unique {name, shape, dtype, sha256} rows."""
    table = proof['files']['producer_receipt']['completed_endpoint'].get('array_records')
    prove(type(table) is dict and set(table) == GROUPS, 'i1 producer array table lacks its six groups')
    result = {}
    for group, rows in table.items():
        prove(type(rows) is list and rows and all(
            type(r) is dict and set(r) == {'name', 'shape', 'dtype', 'sha256'} and type(r['name']) is str and
            type(r['sha256']) is str and HEX64.fullmatch(r['sha256']) for r in rows),
            'i1 producer array table group %s malformed' % group)
        result[group] = {r['name']: r for r in rows}
        prove(len(result[group]) == len(rows), 'i1 producer array table group %s repeats a name' % group)
    return result


def producer_json(value):
    """constitutive._json / materials._json (identical bytes: sorted keys, compact, ASCII, finite)."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def dumped_record(dump, folder, kind):
    prove(kind in dump['records'], 'i1 composite arrays without their reader-proved %s record' % kind)
    return strict_json(bounded_bytes(folder/'records'/(kind+'.json'), 'dumped '+kind), 'dumped %s record' % kind)


def composite_bindings(dump, folder):
    """('bound', route) for each i1 composite array, after recomputing its producer identity; FAIL otherwise."""
    rows = {r['name']: r for r in dump['arrays']}
    force = {n: r for n, r in rows.items() if n.startswith(FORCE_PREFIX)}
    network = {n: r for n, r in rows.items() if n.startswith(NETWORK_PREFIX)}
    status = {}
    if force:
        cert = dumped_record(dump, folder, 'certification')
        prove(type(cert) is dict and type(cert.get('solution')) is dict and type(cert.get('force')) is dict and
              type(cert['solution'].get('force_exchange_id')) is str, 'certification record lacks its force link')
        fields = {}
        for name, row in force.items():
            prove(np.dtype(row['dtype']) == np.dtype('<f8'), 'force field %s is not binary64' % name)
            fields[name[len(FORCE_PREFIX):]] = {'shape': row['shape'], 'sha256': row['sha256']}
        identity = sha256(producer_json({'metadata': cert['force'], 'arrays': fields})).hexdigest()
        prove(identity == cert['solution']['force_exchange_id'],
              "i1 force arrays contradict the reader-proved certification's force_exchange_id")
        status.update((name, ('bound', 'force_exchange_id')) for name in force)
    if network:
        record = dumped_record(dump, folder, 'differential')
        desc = record.get('endpoint_network') if type(record) is dict else None
        prove(type(desc) is dict and type(desc.get('network_id')) is str and type(desc.get('arrays')) is list and
              all(type(a) is dict and set(a) == {'name', 'dtype', 'shape'} and type(a['name']) is str
                  for a in desc['arrays']), 'differential record lacks its endpoint network descriptor')
        order = [NETWORK_PREFIX+NETWORK_ARRAY+a['name'] for a in desc['arrays']]
        prove(len(set(order)) == len(order) and set(order) == set(network),
              'i1 network arrays are not exactly the endpoint descriptor\'s arrays')
        digest = sha256(producer_json({k: v for k, v in desc.items() if k != 'network_id'}))
        for entry, name in zip(desc['arrays'], order, strict=True):
            row = network[name]
            prove(row['dtype'] == entry['dtype'] and row['shape'] == entry['shape'],
                  'network array %s differs from its descriptor dtype/shape' % name)
            digest.update(b'\0'+producer_json([entry['name'], entry['dtype'], entry['shape']]))
            with open(folder/'arrays'/row['file'], 'rb') as handle:
                for chunk in iter(lambda: handle.read(1 << 24), b''):
                    digest.update(chunk)
        prove(digest.hexdigest() == desc['network_id'],
              "i1 network arrays contradict the reader-proved endpoint network_id")
        status.update((name, ('bound', 'network_id')) for name in network)
    return status


def bind_arrays(dump, proof, interval, folder):
    """Per head array: ('bound', group) with the reader-checked row, or ('unbound', why). FAIL on contradiction."""
    status, seen = {}, set()
    table = array_table(proof) if interval == 1 else None
    composite = composite_bindings(dump, folder) if table is not None else {}
    for row in dump['arrays']:
        name = row['name']
        if table is None:
            status[name] = ('unbound', 'root has no reader-checked array table')
            continue
        if name.startswith(UNBOUND_PREFIXES):
            status[name] = ('unbound', 'no independent binding route')
            continue
        if name.startswith(COMPOSITE_PREFIXES):
            status[name] = composite[name]
            continue
        group, key = 'full_collar', name
        for prefix, target, strip in DIRECT_PREFIXES:
            if name.startswith(prefix):
                group, key = target, name[len(prefix):] if strip else name
                break
        bound = table[group].get(key)
        if bound is None:
            status[name] = ('unbound', 'no %s row' % group)
            continue
        try:
            same_dtype = np.dtype(bound['dtype']) == np.dtype(row['dtype'])
        except TypeError:
            same_dtype = False
        prove(bound['sha256'] == row['sha256'] and list(bound['shape']) == row['shape'] and same_dtype,
              'i1 array %s contradicts its reader-checked %s row' % (name, group))
        status[name] = ('bound', group)
        seen.add((group, key))
    if table is not None:
        for group in sorted(DUMPED_GROUPS):
            missing = sorted(set(table[group]) - {key for g, key in seen if g == group})
            prove(not missing, 'i1 dump lacks reader-checked %s arrays: %s' % (group, missing[:5]))
    return status


def snapshot_id(metadata, rows, folder, where):
    """RegionalMechanicalSnapshot(metadata, arrays).result_id from dumped float64 rows (name -> dump row)."""
    arrays = {}
    for name, row in sorted(rows.items()):
        prove(np.dtype(row['dtype']) == np.dtype('<f8'), '%s array %s is not binary64' % (where, name))
        arrays[name] = {'shape': row['shape'], 'sha256': row['sha256']}
    return sha256(producer_json({'metadata': metadata, 'arrays': arrays})).hexdigest()


def root_metadata(proofs, who):
    """(kind, metadata or None, why): the proved published root kind and, from the proved interval stage, its
    complete root metadata (sha256 = the root runner record's root_metadata_sha256)."""
    root = proofs['root']['files']['runner_record'].get('root')
    if type(root) is not dict or root.get('kind') not in ROOT_KINDS or type(root.get('root_key')) is not str:
        return None, None, 'root runner record publishes no root kind'
    if 'interval' not in proofs:
        return root['kind'], None, 'root metadata is proved only with the interval stage'
    metadata = proofs['interval']['files']['producer_receipt']['completed_endpoint'].get('root_metadata')
    prove(type(metadata) is dict and type(root.get('root_metadata_sha256')) is str and
          sha256(producer_json(metadata)).hexdigest() == root['root_metadata_sha256'] and
          metadata.get('key') == root['root_key'] and metadata.get('kind') == root['kind'],
          who+'completed root metadata is not the published root')
    return root['kind'], metadata, None


def exterior_binding(dump, folder, rows):
    """Check the applicable spatial route even for zero rows; return 'bound' or the missing route evidence."""
    if not {'state', 'mesh'} <= set(dump['records']):
        return 'no reader-proved state and mesh records'
    state = dumped_record(dump, folder, 'state')
    mesh = dumped_record(dump, folder, 'mesh')
    if type(state) is not dict or state.get('schema') != SPATIAL_STATE_SCHEMA:
        return 'state record is not a spatial exterior state'
    body = {k: v for k, v in state.items() if k != 'state_id'}
    prove('thermal_mesh' not in body and type(body.get('thermal_mesh_id')) is str and
          sha256(producer_json(mesh)).hexdigest() == body['thermal_mesh_id'],
          'root mesh record is not the state record\'s thermal mesh')
    body['thermal_mesh'] = mesh
    cells, accounts = body.get('cells'), body.get('projection_accounts')
    prove(type(cells) is list and type(accounts) is dict, 'root state record lacks cells or projection accounts')
    fields = {name[len(EXTERIOR_PREFIX):]: row for name, row in rows.items()}
    prove(set(fields) == set(accounts) | {'volume_m3'}, 'root exterior-fv arrays are not exactly the projection '
          'accounts and volume_m3')
    prove(all(row['shape'] == [len(cells)] for row in fields.values()), 'root exterior-fv arrays do not index '
          'the state cells')
    prove(snapshot_id(body, fields, folder, 'root exterior-fv') == state.get('state_id'),
          'root exterior-fv arrays contradict the reader-proved state_id')
    return 'bound'


def alias_names(reference, prefix, rows, where):
    """The exact alias name set of one compact reference; FAIL on a missing or extra alias."""
    bindings = reference.get('array_bindings') if type(reference) is dict else None
    prove(type(bindings) is dict and all(type(v) is str for v in bindings.values()),
          '%s reference lacks its array bindings' % where)
    expected = {prefix+name for name in bindings}
    prove(set(rows) == expected, '%s aliases differ from the reference: missing %s, extra %s' % (
        where, sorted(expected-set(rows))[:5], sorted(set(rows)-expected)[:5]))
    return bindings


def alias_targets(bindings, prefix, descriptors):
    """r13 exact alias map: each alias's observed manifest descriptor digest equals its own bound target.

    r3 dumps observe no descriptor digests (descriptors None): the targets stay REVIEW. A swapped, missing or
    foreign descriptor is a FAIL.
    """
    if descriptors is None:
        return {prefix+name: ('unbound', 'alias descriptor digest not observed (r3 dump)') for name in bindings}
    prove(set(descriptors) == {prefix+name for name in bindings}, 'alias descriptors are not the alias set')
    for name, digest in bindings.items():
        prove(descriptors[prefix+name] == digest, 'alias %s%s does not name its bound target' % (prefix, name))
    return {prefix+name: ('bound', 'alias descriptor') for name in bindings}


def bind_root(dump, proofs, folder, descriptors=None):
    """Return (per-array bindings, route reviews); empty observations cannot hide incomplete route evidence."""
    who = 'root: '
    rows = {r['name']: r for r in dump['arrays']}
    exterior = {n: r for n, r in rows.items() if n.startswith(EXTERIOR_PREFIX)}
    status, issues = {}, []
    rest = {n: r for n, r in rows.items() if n not in exterior}
    kind, metadata, why = root_metadata(proofs, who)
    if kind != 'root' or metadata is None:
        reason = why or 'migrated-root route enumerated (workflow_transfer 625-711), not bound by this comparator'
        issues.append(reason)  # route incompleteness exists even when no array was supplied
        status.update((n, ('unbound', reason)) for n in rows)
        if exterior:
            bound = exterior_binding(dump, folder, exterior)
            status.update((n, ('bound', 'state_id') if bound == 'bound' else ('unbound', bound)) for n in exterior)
        return status, issues
    if 'exterior_state' in metadata:
        prove(type(metadata['exterior_state']) is dict, who+'exterior state metadata malformed')
        bound = exterior_binding(dump, folder, exterior)
        if bound != 'bound':
            issues.append('exterior route: '+str(bound))
        else:
            proved_state = dumped_record(dump, folder, 'state')
            prove(metadata['exterior_state'].get('state_id') == proved_state.get('state_id'),
                  'root exterior metadata differs from the reader-proved state_id')
        status.update((n, ('bound', 'state_id') if bound == 'bound' else ('unbound', bound)) for n in exterior)
    else:
        prove(not exterior, 'root exterior-fv arrays without applicable exterior_state metadata')
    late = sorted(n for n in rest if n.startswith(SUCCESSOR_PREFIXES))
    prove(not late, 'successor-only families at a proved root head: %s' % late[:5])
    heat = {n[len(HEAT_PREFIX):]: r for n, r in rest.items() if n.startswith(HEAT_PREFIX)}
    collar = {n: r for n, r in rest.items() if not n.startswith(ROOT_PREFIXES)}
    state = metadata.get('state')
    prove(type(state) is dict and state.get('schema') == COLLAR_STATE_SCHEMA and type(state.get('fields')) is dict
          and type(metadata.get('native_state_id')) is str and
          (type(state['exterior_heat']) is dict if 'exterior_heat' in state else not heat),
          who+'root metadata lacks its collar state or its exterior heat presence differs')
    identity = {'fields_id': snapshot_id(state['fields'], collar, folder, 'root collar'),
                'native_state_id': metadata['native_state_id']}
    if 'exterior_heat' in state:
        identity['exterior_heat_id'] = snapshot_id(state['exterior_heat'], heat, folder, 'root exterior heat')
    prove(sha256(producer_json(identity)).hexdigest() == state.get('result_id'),
          'root collar and exterior_heat arrays contradict the root collar state result_id')
    status.update((n, ('bound', 'collar result_id')) for n in collar)
    status.update((HEAT_PREFIX+n, ('bound', 'collar result_id')) for n in heat)
    partition = metadata.get('differential_partition')
    refs = partition.get('record_blobs') if type(partition) is dict else {}
    prove(type(refs) is dict, who+'differential partition record refs malformed')
    blobs = {n: r for n, r in rest.items() if n.startswith(PARTITION_RECORD)}
    expected = {ref.get('array'): ref for ref in refs.values() if type(ref) is dict}
    prove(set(blobs) == set(expected) and len(expected) == len(refs),
          'root partition-record arrays differ from the differential partition record refs')
    for name, row in blobs.items():
        ref = expected[name]
        prove(np.dtype(row['dtype']) == np.dtype('u1') and row['shape'] == [ref.get('bytes')] and
              row['sha256'] == ref.get('sha256'), 'root %s bytes contradict their record ref' % name)
        status[name] = ('bound', 'partition record ref')
    for prefix, reference, where in (
            (PARTITION_ALIAS, [r for r in (metadata.get('compact_partition'), (partition or {}).get(
                'compact_partition') if type(partition) is dict else None) if r is not None], 'partition-dag'),
            (MESH_ALIAS, [((metadata.get('exterior_state') or {}).get('compact_mesh'))], 'spatial-mesh')):
        aliases = {n: r for n, r in rest.items() if n.startswith(prefix)}
        reference = [r for r in reference if r is not None]
        if not reference:
            prove(not aliases, 'root %s aliases without a compact reference' % where)
            continue
        prove(len(reference) == 1, 'root has more than one compact %s reference location' % where)
        bindings = alias_names(reference[0], prefix, aliases, 'root '+where)
        status.update(alias_targets(bindings, prefix, None if descriptors is None else {
            n: d for n, d in descriptors.items() if n.startswith(prefix)}))
    stray = sorted(n for n in rows if n.startswith(RECORD_ARRAY))
    prove(not stray, 'spatial-record arrays in a root dump')
    return status, issues


def nonfinite_count(path, dtype):
    """Non-finite elements of a float/complex dump file, read in bounded chunks; 0 for other kinds."""
    if dtype.kind not in 'fc' or not path.stat().st_size:
        return 0
    data = np.memmap(path, dtype=dtype, mode='r')
    count, step = 0, max(1, (1 << 24)//dtype.itemsize)
    for start in range(0, data.size, step):
        count += int(np.count_nonzero(~np.isfinite(data[start:start+step])))
    del data
    return count


def state_cell_ids(dump, folder):
    """Ordered cell_id vector of the reader-proved state record (bytes authenticated by load_dump); None without."""
    if 'state' not in dump['records']:
        return None
    state = strict_json(bounded_bytes(folder/'records'/'state.json', 'dumped state'), 'dumped state record')
    cells = state.get('cells') if type(state) is dict else None
    if cells is None:
        return None
    prove(type(cells) is list and all(type(c) is dict and type(c.get('cell_id')) is str and c['cell_id']
                                      for c in cells), 'state cells lack nonempty cell IDs')
    ids = [c['cell_id'] for c in cells]
    prove(len(set(ids)) == len(ids), 'state cell IDs repeat')
    return ids


def cell_pairing(name, x, y, ids_b, ids_a):
    """('same', None), ('join', after-row index per before row) or ('none', why) for an exterior-fv array."""
    if ids_b is None or ids_a is None:
        return 'none', 'no reader-proved state cells for its rows'
    for row, ids, arm in ((x, ids_b, 'before'), (y, ids_a, 'after')):
        prove(len(row['shape']) >= 1 and row['shape'][0] == len(ids),
              '%s array %s does not index its %d state cells' % (arm, name, len(ids)))
    if ids_b == ids_a:
        return 'same', None
    if set(ids_b) != set(ids_a):
        return 'none', 'state cell ID sets differ (%d only before, %d only after): no row correspondence' % (
            len(set(ids_b)-set(ids_a)), len(set(ids_a)-set(ids_b)))
    where = {cell: i for i, cell in enumerate(ids_a)}
    return 'join', np.asarray([where[cell] for cell in ids_b], dtype=np.int64)


def compare_arrays(before, after, fb, fa, bound_b, bound_a, ids_b=None, ids_a=None):
    rows, review, unbound = {}, [], {}
    a = {x['name']: x for x in before['arrays']}
    b = {x['name']: x for x in after['arrays']}
    for name in sorted(set(a) ^ set(b)):
        review.append('array only in %s: %s' % ('before' if name in a else 'after', name))
    for name in sorted(set(a) & set(b)):
        x, y = a[name], b[name]
        kinds = (bound_b[name], bound_a[name])
        if any(k[0] != 'bound' for k in kinds):
            why = next(k[1] for k in kinds if k[0] != 'bound')
            unbound[why] = unbound.get(why, 0)+1
        if (x['dtype'], x['shape']) != (y['dtype'], y['shape']):
            review.append('array %s: %s%s -> %s%s' % (name, x['dtype'], x['shape'], y['dtype'], y['shape']))
            continue
        dtype = np.dtype(x['dtype'])
        nonfinite = [nonfinite_count(f/'arrays'/r['file'], dtype) for f, r in ((fb, x), (fa, y))]
        if any(nonfinite):
            review.append('array %s holds non-finite values (before %d, after %d): no finite equality' %
                          (name, *nonfinite))
            rows[name] = {'equal': None, 'nonfinite': nonfinite, 'binding': [k[0] for k in kinds]}
            continue
        pairing, join = cell_pairing(name, x, y, ids_b, ids_a) if name.startswith(EXTERIOR_PREFIX) else ('', None)
        if pairing == 'none':
            review.append('array %s: %s' % (name, join))
            rows[name] = {'equal': None, 'paired': None, 'binding': [k[0] for k in kinds]}
            continue
        if x['sha256'] == y['sha256'] and pairing != 'join':
            rows[name] = {'equal': True, 'binding': [k[0] for k in kinds]}
            continue
        u = np.fromfile(fb/'arrays'/x['file'], dtype=dtype)
        v = np.fromfile(fa/'arrays'/y['file'], dtype=dtype)
        if pairing == 'join':       # one joint permutation of the row axis, from the exact cell_id join only
            v = v.reshape(y['shape'])[join].reshape(-1)
            if np.array_equal(u.view(np.uint8), v.view(np.uint8)):
                rows[name] = {'equal': True, 'paired': 'cell_id', 'binding': [k[0] for k in kinds]}
                continue
        width = dtype.itemsize
        changed = np.any(u.view(np.uint8).reshape(-1, width) != v.view(np.uint8).reshape(-1, width), axis=1)
        row = {'equal': False, 'changed': int(np.count_nonzero(changed)), 'dtype': x['dtype'],
               'binding': [k[0] for k in kinds]}
        if pairing == 'join':
            row['paired'] = 'cell_id'
        if dtype.kind == 'f' and dtype.itemsize == 8:
            u, v = u.astype('<f8', copy=False), v.astype('<f8', copy=False)
            finite = np.isfinite(u) & np.isfinite(v)
            row.update(max_ulps=array_ulps(u[finite], v[finite]),
                       max_abs=float(np.max(np.abs(u[finite]-v[finite]), initial=0.0)),
                       nonfinite_changes=int(np.count_nonzero(~finite & changed)))
        # D01: no array field contract exists, so any changed array is REVIEW; ulps are diagnostics.
        review.append('array %s changed in %d elements without an applicable bound' % (name, row['changed']))
        rows[name] = row
    for why, count in sorted(unbound.items()):
        review.append('%d arrays unbound (%s)' % (count, why))
    return rows, review


# ---- field contract

def load_contract(spec, arms):
    """Covered fields {(record, field): radius} from the composition's field contract; empty without one."""
    if spec is None:
        return {}, None
    path, pin = spec
    contract, digest, _ = pinned(path, 'field contract')
    prove(digest == pin, 'field contract bytes differ from the given sha256')
    if contract.get('schema') == 'atlas.private.n9-field-contract.v3':
        return {'__v3__': contract}, {'path': str(Path(path).resolve()), 'sha256': pin,
                                     'schema': contract['schema']}
    prove(set(contract) == {'schema', 'composition', 'covered'} and contract['schema'] == FIELD_CONTRACT_SCHEMA,
          'field contract is not closed')
    composition = {arm: arms[arm]['row']['source_manifest']['sha256'] for arm in arms}
    prove(contract['composition'] == {'before_manifest_sha256': composition['before'],
                                      'after_manifest_sha256': composition['after']},
          'field contract is for another source composition')
    coverage = {}
    prove(type(contract['covered']) is list, 'field contract covered list malformed')
    for row in contract['covered']:
        # v2: 'path' is the full comparer path (record kind first, '#' for hex keys, '[]' for list items), so
        # two quantities sharing a leaf name are never confused (refutation N2).
        selector = row.get('path') if type(row) is dict else None
        prove(type(row) is dict and set(row) == {'path', 'radius', 'bound'} and row['bound'] == DESIGN_BOUND and
              type(row['radius']) is str and row['radius'] and type(selector) is list and len(selector) >= 2 and
              all(type(x) is str and x for x in selector) and selector[-1] != DEVIATION_FIELD and
              tuple(selector) not in coverage, 'field contract row malformed or duplicated')
        coverage[tuple(selector)] = row['radius']
    # v2's sibling scalar radius does not prove vector norm, source context or
    # correspondence. Retain readable historical input without granting coverage.
    return {}, {'path': str(Path(path).resolve()), 'sha256': pin, 'covered': 0,
                'legacy_rows': len(coverage), 'status': 'REVIEW',
                'reason': 'v2 lacks independently established quantity/norm/source semantics'}


def source_inventories(arms):
    inventories = {}
    for arm, value in arms.items():
        reference = value['row']['source_manifest']
        document, digest, _ = pinned(Path(value['row']['workspace']) / reference['path'],
                                    arm + ' field source inventory')
        prove(digest == reference['sha256'], 'field source inventory differs from profile')
        inventories[arm] = document['source_hashes']
    return inventories


def header_producer(header, inventory):
    """Select the E/M producer using its source-defined record discriminator."""
    if header.get('schema') != 'atlas.source-bound-exterior-thermal-mesh.v1':
        return None
    module = ('integration_differential_mesh.py'
              if header.get('physical_geometry_family') == 'differential-plate-component-partition-v1'
              else 'integration_exterior_mesh.py')
    matches = [(path, digest) for path, digest in inventory.items()
               if Path(path).name == module]
    prove(len(matches) <= 1, 'ambiguous mesh producer in source inventory')
    return matches[0] if matches else None


def scrub_quantities(record, paths):
    """Suppress only complete already-judged quantity subtrees in diagnostics."""
    if not paths:
        return record
    # Clone only changed ancestor containers, keeping the large record body
    # shared and read-only. A consumed quantity can contain a checked header.
    paths = sorted(set(paths), key=lambda path: (len(path), path))
    minimal = []
    for path in paths:
        if not any(path[:len(parent)] == parent for parent in minimal):
            minimal.append(path)
    result = record.copy()
    cloned = {()}
    for path in minimal:
        parent = result
        for i, key in enumerate(path[1:-1], 1):
            key = int(key) if type(parent) is list else key
            prefix = path[1:i+1]
            if prefix not in cloned:
                parent[key] = parent[key].copy()
                cloned.add(prefix)
            parent = parent[key]
        key = int(path[-1]) if type(parent) is list else path[-1]
        parent[key] = '<independently-judged-quantity>'
    return result


def header_paths(record, kind):
    """Concrete source-record paths, retaining indices rather than wildcard pairing."""
    pending = [((kind,), record)]
    while pending:
        path, value = pending.pop()
        if type(value) is dict:
            if DEVIATION_FIELD in value and WIDTH_FIELD in value and 'cells' in value:
                yield path, value
            pending.extend((path + (key,), child) for key, child in value.items())
        elif type(value) is list:
            pending.extend((path + (str(i),), child) for i, child in enumerate(value))


def judge_fields(fields, review, fail, where):
    for name, f in fields.items():
        if f['bound_violations']:
            fail.append('%s %s: %d changes not strictly below 2**-11 x radius %s (max ratio %s)' %
                        (where, name, f['bound_violations'], f['radius'], f['max_ratio']))
        if f['weak_changed']:
            review.append('%s %s: %d changes under positional pairing' % (where, name, f['weak_changed']))
        if f['unbound_changes'] > f['weak_changed']:
            review.append('%s %s: %d changes without an applicable bound (max %d ulps, rel %.3g; diagnostics)' %
                          (where, name, f['unbound_changes']-f['weak_changed'], f['max_ulps'], f['max_rel']))


def judge_items(items, review, fail, where):
    """Field-contract and design-row results: each FAIL or REVIEW item with its path and code."""
    for item in items:
        detail = '%s %s: %s' % (where, '.'.join(item['path']), item['code'])
        if item['verdict'] == 'FAIL':
            fail.append(detail)
        elif item['verdict'] == 'REVIEW':
            review.append(detail)


def width_rows(before, after):
    """Per record field: the widest numerator or denominator in bits, before -> after."""
    rows = []
    wb = (before.get('widths') or {}).get('records', {})
    wa = (after.get('widths') or {}).get('records', {})
    for kind in sorted(set(wb) | set(wa)):
        for name in sorted(set(wb.get(kind, {})) | set(wa.get(kind, {}))):
            x, y = wb.get(kind, {}).get(name) or {}, wa.get(kind, {}).get(name) or {}
            bits = [max(r.get('max_numerator_bits', 0), r.get('max_denominator_bits', 0)) if r else None
                    for r in (x, y)]
            rows.append({'record': kind, 'field': name, 'bits_before': bits[0], 'bits_after': bits[1],
                         'count_before': x.get('count'), 'count_after': y.get('count')})
    return rows


def load_record(folder, kind):
    return strict_json(bounded_bytes(folder/'records'/(kind+'.json'), 'record '+kind), 'record '+kind)


class ProvedRecordBytes(Mapping):
    """Expose one authenticated dump record at a time without retaining all raw bytes."""

    def __init__(self, folder, identities):
        self.folder = folder
        self.identities = identities

    def __iter__(self):
        return iter(self.identities)

    def __len__(self):
        return len(self.identities)

    def __getitem__(self, kind):
        identity = self.identities[kind]['sha256']
        raw = bounded_bytes(self.folder/'records'/(kind+'.json'), 'field provenance record '+kind)
        prove(sha256(raw).hexdigest() == identity, 'field provenance record differs from reader target')
        return {'identity': identity, 'raw': raw}


def run(args):
    require(REPAIRS_COMPLETE, 'N9 r14 repairs incomplete: not approved for replay or acceptance')
    return compare(args)


def compare(args):
    B = component('array_bindings_r5')
    Q = component('field_contracts')
    A = component('array_compare_r21')
    P = component('field_provenance')
    this = sys.modules[__name__]
    require(type(args.observer_sha256) is str and HEX64.fullmatch(args.observer_sha256),
            'independent observer pin required')
    arms = {arm: load_arm(arm, *v) for arm, v in (('before', args.before), ('after', args.after))}
    coverage, contract = load_contract(args.field_contract, arms)
    pins = load_selected_pins(getattr(args, 'selected_pins', None))
    specs = {}
    for arm, path, digest in getattr(args, 'captures', None) or ():
        prove(arm in arms and arm not in specs, 'captures map arm must be before or after, once each')
        specs[arm] = (path, digest)
    captures = {arm: load_captures(a, specs.get(arm)) for arm, a in arms.items()}
    provenance = {arm: (lambda stage, step, a=a, c=captures[arm]: capture_provenance(a, stage, step, c, pins))
                  for arm, a in arms.items()}
    evidence_specs = {}
    for arm, path, digest in getattr(args, 'causal_evidence', None) or ():
        prove(arm in arms and arm not in evidence_specs, 'causal evidence arm must be before or after, once each')
        evidence_specs[arm] = (path, digest)
    evidence = {arm: load_evidence(a, evidence_specs.get(arm), pins, args.observer_sha256)
                for arm, a in arms.items()}
    fail, void, review, info = [], [], [], []
    if contract and contract.get('status') == 'REVIEW':
        review.append(contract['reason'])
    void_kinds = set()
    stages, gates, records, arrays, widths, addendum = {}, {}, {}, {}, {}, {}
    proofs, dumps, folders = {'before': {}, 'after': {}}, {'before': {}, 'after': {}}, {}
    # r20: proofs holds paired stages only (pair helpers read it); claimed holds a claimant's stages proved
    # beside an unresolved peer; live arms have every earlier stage of their own proved
    claimed, live = {'before': {}, 'after': {}}, set(arms)
    for stage, interval in STAGES:
        rows = {arm: apply_events(outcome(a['attempt'], stage, a['sha256'], provenance[arm]), stage, evidence[arm],
                                  a['attempt']) for arm, a in arms.items()}
        stages[stage] = rows
        classes = {arm: row['class'] for arm, row in rows.items()}
        # r20: an arm with an earlier unresolved or refuted stage of its own is unreached here; its later
        # files are neither proved nor compared, so they can neither establish nor excuse a candidate outcome.
        effective = {arm: classes[arm] if arm in live else 'unreached' for arm in arms}
        if any(c not in ADOPTING for c in effective.values()):  # R8 classes per arm in stages
            if effective['before'] in ADOPTING and effective['after'] == 'resource_fail':
                fail.append('%s: candidate-only stop after an adopted reference: %s' % (
                    stage, rows['after']['causality']))
            elif any(c in ADOPTING for c in effective.values()) and any(
                    row['class'] == 'resource_fail' or row.get('status') == PRESEAL_REFUSED
                    for arm, row in rows.items() if arm in live):
                fail.append('refusal flip at %s: %s (D01; an attributed resource stop or a preseal checker refusal '
                            'against an adopted arm)' % (stage, classes))
            unresolved = {arm: row for arm, row in rows.items() if effective[arm] not in ADOPTING+('unreached',)}
            if unresolved:
                void.append('%s: no usable outcome %s; %s' % (stage, classes, {
                    arm: row['causality'] for arm, row in unresolved.items()}))
                void_kinds.update(row['classification'] for row in unresolved.values()
                                  if type(row.get('classification')) is str and
                                  row['classification'].startswith('VOID-'))
            live = {arm for arm in live if effective[arm] in ADOPTING}
            # r8/r10/r20: an unresolved peer never hides a claimant's own proof failure at this or any later
            # stage; the proved claimant stays live for its arm-local chain, width gate and later stage rules
            for arm in [arm for arm in arms if arm in live]:
                try:
                    claimed[arm][stage] = prove_stage(arms[arm], stage, interval)
                    own = dict(proofs[arm], **claimed[arm])
                    if set(own) == {name for name, _ in STAGES}:
                        prove_chain(arms[arm], own)
                except ProofError as error:
                    fail.append('proof/integrity: %s arm claims %s at %s despite its unresolved peer: %s' % (
                        arm, classes[arm], stage, error))
                    live.discard(arm)
            continue
        interrupted = {}
        for arm, a in arms.items():
            proofs[arm][stage] = prove_stage(a, stage, interval)
            observed = evidence[arm]['observers'].get(interval)
            if observed is not None and not (a['dumps']/('i%d' % interval)/'dump.json').exists():
                # r18: only an evidenced external interruption of this exact observer, with the sealed arm's
                # re-derived proof intact, explains an absent dump. A present dump is judged as before.
                prove(observed['record']['payload']['sealed_arm_refs'] == proofs[arm][stage]['pins'],
                      '%s i%d observer interruption names another sealed arm' % (arm, interval))
                event = observed['event']['payload']
                if event['event_type'] in EXPLAINING_EVENTS and event['request_outcome'] in EXPLAINING_OUTCOMES:
                    interrupted[arm] = '%s i%d observer interrupted by external %s %s (%s), evidence %s' % (
                        arm, interval, event['event_type'], event['action_or_event_id'], event['actor_or_source'],
                        observed['record']['evidence_id'])
                    continue
            dumps[arm][interval] = load_dump(a, interval, proofs[arm][stage], args.observer_sha256)
        if interrupted:
            # r19 C1: only this interval's dump comparison is unavailable. Its stage proofs stay, and later
            # stages run through the ordinary classification, FAIL rules, chain and width-gate checks below.
            void.extend(interrupted.values())
            void_kinds.add('VOID-OBSERVER')
            for arm in arms:
                dumps[arm].pop(interval, None)
            continue
        folders[interval] = {arm: a['dumps']/('i%d' % interval) for arm, a in arms.items()}
    for arm, a in arms.items():
        # r19 C1: every fully proved arm has its cross-stage chain checked, also beside an observer VOID
        if set(proofs[arm]) == {name for name, _ in STAGES}:
            prove_chain(a, proofs[arm])
    differing = distinct_arms(arms, proofs, dumps)
    info.append('profile keys differing between arms: %s' % differing)
    for stage, interval in STAGES:
        if stage not in proofs['before'] or interval not in dumps['before']:
            continue
        ta, tb = proofs['before'][stage]['targets'], proofs['after'][stage]['targets']
        dumped = set(dumps['before'][interval]['records']) | set(dumps['after'][interval]['records'])
        for kind in sorted((set(ta) | set(tb)) - dumped):
            if ta.get(kind) != tb.get(kind):
                review.append('%s %s identity differs between the arms and its record is not dumped: content not '
                              'compared' % (stage, kind))
    for arm in arms:
        proved = proofs[arm].get('interval') or claimed[arm].get('interval')
        if proved is not None:
            gates[arm] = {'verdict_sha256': proved['pins']['verdict'], 'passed': proved['gate']['passed'],
                          'width_gate': proved['gate']}
    if 'after' in gates and gates['after']['passed'] is not True:
        # r20: the candidate's own mandatory width failure needs no peer
        fail.append('after arm interval width gate %s' % gates['after']['passed'])
    if len(gates) == 2:
        if gates['before']['passed'] is not gates['after']['passed']:
            fail.append('refusal flip: interval width gate before %s, after %s (D01: zero flips)' %
                        (gates['before']['passed'], gates['after']['passed']))
        info.append('interval width gate: before %s, after %s' % (gates['before']['passed'],
                                                                   gates['after']['passed']))
    elif gates:
        info.append('interval width gate: %s only (its peer has no proved interval; no flip comparison)' %
                    ', '.join('%s %s' % (arm, row['passed']) for arm, row in gates.items()))
    inventories = source_inventories(arms)
    manifests = {arm: a['row']['source_manifest']['sha256'] for arm, a in arms.items()}
    provenance_sources = {}
    for arm, inventory in inventories.items():
        provenance_sources[arm] = {}
        for name in P.source_paths(inventory):
            path = Path(name)
            if not path.is_absolute():
                path = Path(arms[arm]['row']['workspace']) / path
            raw = bounded_bytes(path, arm+' field producer source')
            prove(sha256(raw).hexdigest() == inventory[name], 'field producer source changed')
            provenance_sources[arm][name] = raw
    supplied = coverage.get('__v3__')
    if supplied is not None:
        prove(set(supplied) == {'schema', 'composition', 'quantities'} and
              supplied.get('composition') == manifests,
              'v3 field contract top-level fields or selected composition differ')
    # Pass 1: source-bound per-arm totals, never a universal sum of cell fields.
    tokens = {'before': set(), 'after': set()}
    proved_headers = {}
    for interval, pair in folders.items():
        for arm, folder in pair.items():
            identity_tokens(dumps[arm][interval]['head'].get('root_metadata'), tokens[arm])
            for kind in sorted(dumps[arm][interval]['records']):
                value = load_record(folder, kind)
                identity_tokens(value, tokens[arm])
                proved_headers[(interval, arm, kind)] = set()
                for index, (header_path, header) in enumerate(header_paths(value, kind)):
                    producer = header_producer(header, inventories[arm])
                    checked = (Q.derive_header_total(header, Path(producer[0]).name, producer[1]) if producer else
                               {'verdict': 'REVIEW', 'code': 'UNBOUND_HEADER_PRODUCER'})
                    addendum['%s i%d/%s#%d' % (arm, interval, kind, index)] = checked
                    if checked['verdict'] == 'PASS':
                        proved_headers[(interval, arm, kind)].add(header_path + (DEVIATION_FIELD,))
                    if checked['verdict'] == 'FAIL':
                        fail.append('Addendum E %s i%d/%s: %s' % (arm, interval, kind, checked))
                    elif checked['verdict'] == 'REVIEW':
                        review.append('Addendum E %s i%d/%s not checkable: %s' %
                                      (arm, interval, kind, checked['code']))
                del value
    reader_correspondence = reader_pairs(proofs)
    ids = checked_identity_map(reader_correspondence, tokens['before'], tokens['after'])
    del tokens
    verified = {pin: proof['files'][key]
                for by_stage in proofs.values() for proof in by_stage.values()
                for key, pin in proof['pins'].items()}
    compiled_contracts = {}
    producer_provenance = {}
    # No v2 sibling-radius coverage reaches the production record walker.
    scalar_coverage = {}
    design_rows = {}
    # Magnitude tables (quantity key -> row), the REVIEW/FAIL row items that index them, and the
    # non-numeric record changes. Diagnostics only: nothing below reads them for a verdict.
    magnitudes, magnitude_items, magnitude_records = {}, [], {}
    # The contract addendum rows (field_contracts.AddendumRows), per interval. Their G-WU exclusion needs refusal
    # parity: no FAIL or VOID before the field pass (pass 1 records a refusal flip as a FAIL).
    contract_addendum, refusal_parity = {}, not fail and not void
    # Pass 2: the field comparison.
    for interval, pair in folders.items():
        db, da = dumps['before'][interval], dumps['after'][interval]
        provenance_records = {
            arm: ProvedRecordBytes(pair[arm], dumps[arm][interval]['records']) for arm in arms}
        assessed = P.assess_records(manifests, inventories, provenance_sources,
                                   provenance_records, reader_correspondence)
        producer_provenance['i%d' % interval] = assessed
        if assessed['verdict'] == 'FAIL':
            fail.append('i%d producer provenance: %s' % (interval, assessed['issues']))
        elif assessed['verdict'] == 'REVIEW':
            review.append('i%d producer provenance unresolved: %s' % (interval, assessed['issues']))
        else:
            # BOUND: every mandatory W/E invocation joined through the reader proof.
            # It certifies context only; field values still need their own rows below.
            prove(assessed['verdict'] in ('BOUND', 'NOT_APPLICABLE'), 'unknown producer provenance verdict')
        # Only reader-proved dump records and verified source inventory enter the
        # compiler. Candidate contract text cannot manufacture semantic evidence.
        record_pairs, selectors = {}, []
        for kind in sorted(set(db['records']) & set(da['records'])):
            items = {}
            for arm in arms:
                record = load_record(pair[arm], kind)
                producer = header_producer(record, inventories[arm])
                if producer:
                    items[arm] = {'record': record,
                                  'identity': dumps[arm][interval]['records'][kind]['sha256'],
                                  'producer': {'path': producer[0], 'sha256': producer[1]}}
            if set(items) == set(arms):
                record_pairs[kind] = items
                selectors.extend((kind, name) for name in ('time_s', 'max_geometry_volume_error_m3'))
                if all(Path(item['producer']['path']).name == 'integration_exterior_mesh.py'
                       for item in items.values()):
                    selectors.extend((kind, name) for name in Q.E_POSE_FIELDS)
        if supplied:
            selectors.extend(tuple(row['path']) for row in supplied['quantities'])
        compiled = Q.compile_source_evidence(manifests, inventories, record_pairs, sorted(set(selectors)))
        document = copy.deepcopy(compiled['document'])
        if supplied:
            supplied_paths = {tuple(row['path']) for row in supplied['quantities']}
            document['quantities'] = [row for row in document['quantities']
                                      if tuple(row['path']) not in supplied_paths]
            document['quantities'].extend(supplied['quantities'])
        quantity_contract = Q.FieldContracts(document, manifests, inventories,
                                             dict(verified, **compiled['verified_evidence']))
        compiled_contracts['i%d' % interval] = dict(quantity_contract.summary(),
                                                  unresolved=compiled['unresolved'])
        review.extend('i%d source field %s unresolved: %s' %
                      (interval, '.'.join(row['path']), row['code']) for row in compiled['unresolved'])
        del record_pairs
        # Per-arm authentication cannot excuse a cross-arm root metadata change.
        # Keep this outside field-contract suppression: no generic pose allowance
        # applies to root topology, exact inputs or persisted diagnostics.
        root_before = db['head'].get('root_metadata')
        root_after = da['head'].get('root_metadata')
        if root_before is not None or root_after is not None:
            root_compare = Comparer(ids, {}, legacy_headers=False)
            root_compare.compare(root_before, root_after, ('root_metadata',))
            records['i%d/root_metadata' % interval] = {
                'counts': root_compare.counts, 'structure': root_compare.structure,
                'labels': root_compare.labels, 'fields': root_compare.fields}
            if root_compare.counts['structure'] or root_compare.counts['labels'] or root_compare.overflow:
                review.append('i%d/root_metadata structural, label or accounting change' % interval)
                magnitude_records['i%d/root_metadata' % interval] = {
                    'structure': root_compare.counts['structure'], 'labels': root_compare.counts['labels'],
                    'field_overflow': root_compare.overflow}
            judge_fields(root_compare.fields, review, fail, 'i%d/root_metadata' % interval)
            magnitudes.update(('i%d/record/%s' % (interval, name), row)
                              for name, row in root_compare.magnitude_table().items())
        widths['i%d' % interval] = width_rows(db, da)
        names = [k for k in KINDS if k in db['records'] or k in da['records']]
        names += sorted((set(db['records']) | set(da['records'])) - set(names))
        # The design rows (field_contracts.DesignRows). The interval's motion inputs and the joined heat plan are
        # observed first, because certification and the exchange's own references are walked before them.
        design = Q.DesignRows(inventories)
        contract_rows = Q.AddendumRows(interval, ids, parity=refusal_parity)
        for kind in ('differential', 'exchange'):
            if kind in db['records'] and kind in da['records']:
                design.observe(kind, load_record(pair['before'], kind), load_record(pair['after'], kind))
        for kind in names:
            where = 'i%d/%s' % (interval, kind)
            ib, ia = db['records'].get(kind), da['records'].get(kind)
            if ib is None or ia is None:
                review.append('%s present in one arm only' % where)
                magnitude_records[where] = {'present_in': 'before' if ia is None else 'after'}
                continue
            if ib == ia and not quantity_contract.rows:
                # No cross-arm difference, but the design rows' per-arm writer checks (each arm's own producer
                # pins) and the context later rows read still run on the one record.
                shared = load_record(pair['before'], kind)
                design.observe(kind, shared, shared)
                shared_items = (design.evaluate(kind, shared, shared)[0] +
                                contract_rows.evaluate(kind, shared, shared)[0])
                judge_items(shared_items, review, fail, where)
                magnitude_items.extend((where, item, quantity_prefix(where, item['path'], shared))
                                       for item in shared_items if item['verdict'] in ('REVIEW', 'FAIL'))
                del shared
                records[where] = {'bytes_equal': True, 'nbytes': ib['nbytes']}
                continue
            sub = Comparer(ids, scalar_coverage, legacy_headers=False)
            a, b = load_record(pair['before'], kind), load_record(pair['after'], kind)
            quantity_correspondence = {path: {'before_identity': ib['sha256'], 'after_identity': ia['sha256']}
                              for path in quantity_contract.rows if path[0] == kind}
            quantity_correspondence.update({path: value for path, value in compiled['correspondence'].items()
                                   if path[0] == kind})
            quantities, consumed = quantity_contract.compare_record(kind, a, b, quantity_correspondence)
            design.observe(kind, a, b)
            designed, design_consumed = design.evaluate(kind, a, b)
            added, added_consumed = contract_rows.evaluate(kind, a, b)
            quantities = quantities+designed+added
            consumed = set(consumed) | design_consumed | added_consumed
            judge_items(quantities, review, fail, where)
            allowed_headers = (proved_headers[(interval, 'before', kind)] &
                               proved_headers[(interval, 'after', kind)])
            # The header rule has already been independently reconstructed from
            # the actual producer on each arm. Never recompute a universal sum
            # after scrubbing the exact width contract.
            suppressed = set(consumed) | allowed_headers
            sub.counts['addendum_e_headers'] = len(allowed_headers)
            sub.compare(scrub_quantities(a, suppressed), scrub_quantities(b, suppressed), (kind,))
            cascade = None
            if interval == 0:
                # G-MOD-initial_parallel (contract addendum): the replay route's i0 differences are the 5.10 mesh
                # header and the record-level cascade ids; the addendum attributes no other i0 change.
                changed = [name for name, f in sub.fields.items() if f['changed'] or f['weak_changed']]
                changed += [item['path'] for item in sub.structure+sub.labels]
                outside = Q.i0_outside(kind, changed)
                if sub.overflow or (len(sub.structure), len(sub.labels)) != (sub.counts['structure'],
                                                                           sub.counts['labels']):
                    outside.append('<unlisted changes>')
                cascade = {'changed': len(changed), 'outside': outside[:MAX_ITEMS]}
                if outside:
                    review.append('%s: %d changes outside the i0 header cascade (G-MOD-initial_parallel): %s' %
                                  (where, len(outside), ', '.join(outside[:8])))
            judged = {}
            for item in quantities:
                if item['verdict'] in ('REVIEW', 'FAIL'):
                    magnitude_items.append((where, item, quantity_prefix(where, item['path'], a, b)))
                    if tuple(item['path']) in consumed:
                        judged.setdefault(tuple(item['path']), []).append(item)
            # Quantities judged outside the walk (which holds no magnitudes for them) get their own tables.
            magnitudes.update(('i%d/judged/%s' % (interval, name), row)
                              for name, row in judged_tables(Q, ids, a, b, judged).items())
            magnitudes.update(('i%d/record/%s' % (interval, name), row)
                              for name, row in sub.magnitude_table().items())
            if sub.counts['structure'] or sub.counts['labels'] or sub.overflow:
                magnitude_records[where] = {'structure': sub.counts['structure'], 'labels': sub.counts['labels'],
                                            'field_overflow': sub.overflow}
            del a, b
            records[where] = {'bytes_equal': ib == ia, 'nbytes': [ib['nbytes'], ia['nbytes']], 'counts': sub.counts,
                              'structure': sub.structure, 'labels': sub.labels, 'field_overflow': sub.overflow,
                              'quantities': quantities,
                              'fields': dict(sorted(sub.fields.items(), key=lambda kv: (
                                  -kv[1]['bound_violations'], -kv[1]['changed'], kv[0])))}
            if cascade is not None:
                records[where]['i0_cascade'] = cascade
            if sub.counts['structure'] or sub.counts['labels']:
                review.append('%s: %d structure, %d label changes' % (where, sub.counts['structure'],
                                                                       sub.counts['labels']))
            if sub.overflow:
                review.append('%s: %d fields beyond the accounting limit' % (where, sub.overflow))
            judge_fields(sub.fields, review, fail, where)
        stage = STAGES[interval][0]
        bound, layouts = {}, {}
        for arm in arms:
            bound[arm], issues, layouts[arm] = B.bind_all(
                this, dumps[arm][interval], proofs[arm], folders[interval][arm])
            review.extend('i%d %s array route: %s' % (interval, arm, why) for why in issues)
        if interval == 0:
            review.extend('i0 '+why for why in B.compare_root_partitions({arm: dumps[arm][0] for arm in arms}))
        cells = {arm: state_cell_ids(dumps[arm][interval], folders[interval][arm]) for arm in arms}
        array_magnitudes = {}
        arrays['i%d' % interval], found = A.compare(
            this, db, da, pair['before'], pair['after'], bound['before'], bound['after'],
            cells['before'], cells['after'], layouts=(layouts['before'], layouts['after']),
            magnitudes=array_magnitudes)
        review.extend('i%d %s' % (interval, r) for r in found)
        magnitudes.update(('i%d/array/%s' % (interval, name), row) for name, row in array_magnitudes.items())
        if interval == 1:
            # Row 5.6: the joined-heat audit copy of the input source is a head array, not a record field.
            audit = design.audit_source('arrays', {'before': db['arrays'], 'after': da['arrays']}, pair)
            judge_items(audit, review, fail, 'i1')
            magnitude_items.extend(('i1', item, quantity_prefix('i1', item['path']))
                                   for item in audit if item['verdict'] in ('REVIEW', 'FAIL'))
        design_rows['i%d' % interval] = design.summary()
        contract_addendum['i%d' % interval] = contract_rows.summary()
    void_status = ('VOID-SUSPECT' if 'VOID-SUSPECT' in void_kinds or not void_kinds else
                   'VOID-ENVIRONMENT' if 'VOID-ENVIRONMENT' in void_kinds else 'VOID-OBSERVER')
    for arm in arms:
        repeat = evidence[arm]['repeat']
        if repeat is not None:
            # Policy v2: a completed repeat is REVIEW, never an automatic PASS or erasure of the earlier stop.
            review.append('%s arm is diagnostic repeat %s of %s: acceptance needs explicit resolution by %s' % (
                arm, repeat['repeat_id'], repeat['original_attempt'], ', '.join(repeat['approvers'])))
    # A helpers/*.py decoder must be byte-identical in both arms; an atlas_tectonics decoder difference is
    # record-only (decoder_summary).
    decoders = B.decoder_summary(dumps)
    review.extend('decoder %s differs across arms: DECODER_DIFFERS_ACROSS_ARMS' % B.DECODER_PATHS[name]
                  for name in decoders['helpers_differ_across_arms'])
    status = 'FAIL' if fail else void_status if void else 'REVIEW' if review else 'PASS'
    return {'schema': SCHEMA, 'status': status, 'fail': fail, 'void': void, 'review': review[:MAX_ITEMS],
            'review_count': len(review), 'info': info, 'stages': stages, 'width_gate': gates, 'widths': widths,
            'records': records, 'arrays': arrays, 'addendum_e': addendum, 'identity_translations': len(ids),
            'field_contract': contract, 'source_compiled_contracts': compiled_contracts,
            'producer_provenance': producer_provenance,
            'decoders': decoders,
            'design_rows': design_rows,
            'contract_addendum': contract_addendum,
            'magnitudes': magnitude_section(magnitudes, magnitude_items, magnitude_records),
            'causal_evidence': {arm: {'bundle': e['bundle'], 'events': len(e['events']),
                                      'observer_interruptions': sorted(e['observers']),
                                      'repeat': e['repeat']} for arm, e in evidence.items()},
            'thresholds': {'design_bound': DESIGN_BOUND, 'deviation_excess': '< 2**-64 * exact total',
                           'diagnostic_ulps': DIAGNOSTIC_ULPS, 'diagnostic_rel': DIAGNOSTIC_REL,
                           'pass_allowance': 'none outside Addendum E and contract-covered fields (D01)'},
            'proof': {arm: {mode: p['pins'] for mode, p in dict(proofs[arm], **claimed[arm]).items()}
                      for arm in arms},
            'inputs': {arm: {'attempt': str(a['attempt']), 'dumps': str(a['dumps']), 'profile': str(a['profile']),
                             'profile_sha256': a['sha256']} for arm, a in arms.items()},
            'observer_sha256': args.observer_sha256}


def resolve(path, *records):
    """The field-walk name parts and location chain of a concrete record path.

    'records' are the arms' records, which the path addresses below its first segment (the record kind).
    Each segment is read by the container it indexes in the first record still holding the path there, so
    a decimal dict key keeps its name; past every record an int or decimal segment (other than a 64-hex
    digest) is a list position.
    """
    parts, at, values = [str(path[0])], (None, str(path[0])), list(records)
    for p in path[1:]:
        p = str(p)
        container = next((v for v in values if type(v) in (dict, list)), None)
        position = type(container) is list or (container is None and p.isdecimal() and not HEX64.match(p))
        parts.append('[]' if position else Comparer.segment(p))
        at = (at, int(p) if position and p.isdecimal() else p)
        values = [v.get(p) if type(v) is dict else
                  v[int(p)] if type(v) is list and p.isdecimal() and int(p) < len(v) else None for v in values]
    return tuple(parts), at


def collapse(path, *records):
    """A concrete record path as the field walk names it (list positions '[]', hex keys '#')."""
    return resolve(path, *records)[0]


def quantity_prefix(where, path, *records):
    """The magnitude-table key, or key prefix, that an item's path names (see magnitude_section)."""
    interval = where.split('/', 1)[0]
    if not path:
        return '%s/record' % interval
    if path[0] == 'arrays' and len(path) > 1:
        return '%s/array/%s' % (interval, path[1])
    return '%s/record/%s' % (interval, '.'.join(collapse(path, *records)))


def judged_tables(Q, ids, before, after, judged):
    """Magnitude tables of the quantities that rows judged outside the field walk.

    'judged' maps each judged concrete path to its REVIEW/FAIL items. One diagnostics-only walk covers every
    path not inside another judged path, so the element paths of one field share its table. Each table row
    carries the worst verdict and the codes of the items whose path names that field or one above it.
    """
    walk = Comparer(ids, {}, legacy_headers=False)
    named, walked = {}, []
    for path in sorted(judged, key=lambda p: (len(p), [str(s) for s in p])):
        named[path] = '.'.join(collapse(path, before, after))
        key = [str(s) for s in path]
        if any(key[:len(w)] == w for w in walked):
            continue
        try:
            x, y = Q.at(before, key[1:]), Q.at(after, key[1:])
        except Q.ContractError:
            continue
        walked.append(key)
        parts, at = resolve(path, before, after)
        walk.compare(x, y, parts, at=at)
    tables = {}
    for name, row in walk.magnitude_table().items():
        items = [item for path, found in judged.items() for item in found
                 if name == named[path] or name.startswith(named[path]+'.')]
        tables[name] = dict(row, status='FAIL' if any(i['verdict'] == 'FAIL' for i in items) else 'REVIEW',
                            judged_by=sorted({i['code'] for i in items}))
        # The judging rule's own limit, where its item states one; this walk binds no radius.
        limits = sorted({(str(i.get('quantity')), str(i['strict_limit'])) for i in items if 'strict_limit' in i})
        if limits:
            tables[name].update(radius_source='the judging contract item', radius_status='contract strict limit',
                                contract_limits=[{'quantity': q, 'strict_limit': s} for q, s in limits])
        else:
            tables[name]['radius_status'] = 'none: the judging items state no certified radius'
    return tables


def sorted_tree(value):
    """Every mapping with sorted keys; sequences keep their order."""
    if type(value) is dict:
        return {k: sorted_tree(value[k]) for k in sorted(value)}
    if type(value) in (list, tuple):
        return [sorted_tree(v) for v in value]
    return value


def magnitude_section(quantities, items, records):
    """The magnitude tables for the structured review of the REVIEW quantities.

    'quantities' holds one row per record field or array the comparison left REVIEW (or FAIL); 'records' the
    non-numeric changes and one-arm records; 'rows' indexes each design or contract row's REVIEW/FAIL items
    (where, item, quantity_prefix of its path) to the tables under that prefix (navigation only);
    'unattributed' lists the tables no item points at. The section is key-sorted and carries the sha256 of
    its canonical JSON. No verdict reads it.
    """
    # Every key under each of its dot-boundary prefixes; a judged table answers to its record prefix.
    under = {}
    for k in quantities:
        match = k.replace('/judged/', '/record/', 1)
        for i in [i for i, c in enumerate(match) if c == '.'] + [len(match)]:
            under.setdefault(match[:i], set()).add(k)
    rows = {}
    for where, item, prefix in items:
        label = item.get('row') or ('D01:%s' % item['quantity'] if item.get('quantity') else item['code'])
        entry = rows.setdefault(label, {'items': [], 'quantities': set()})
        entry['items'].append({'where': where, 'verdict': item['verdict'], 'code': item['code'],
                               'path': '.'.join(str(p) for p in item['path'])})
        entry['quantities'].update(under.get(prefix, ()))
    for entry in rows.values():
        entry['items'].sort(key=lambda i: (i['where'], i['path'], i['code'], i['verdict']))
        entry['quantities'] = sorted(entry['quantities'])
    attributed = {k for entry in rows.values() for k in entry['quantities']}
    body = sorted_tree({
        'schema': MAGNITUDES_SCHEMA,
        'scope': ('diagnostics for the structured review: every record field and array the comparison left '
                  'REVIEW (or FAIL), keyed i<interval>/record/<field>, i<interval>/judged/<field> (a quantity a '
                  'row judged outside the field walk) or i<interval>/array/<name>; no verdict reads this section. '
                  'Each row gives max_abs, max_ulps (binary64 steps; correctly rounded for exact values; None for '
                  'non-float64 arrays), certified_radius with radius_source and max_ratio (strict bound: '
                  'max_ratio < 2**-11), or certified_radius None with radius_status saying why; no substitute '
                  'tolerance'),
        'quantities': quantities, 'records': records, 'rows': rows,
        'unattributed': sorted(set(quantities) - attributed)})
    body['sha256'] = sha256(json.dumps(finite_report(body), sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode()).hexdigest()
    return body


def finite_report(value):
    """Retain non-finite diagnostic values as explicit strings, not invalid JSON."""
    if type(value) is float and not math.isfinite(value):
        return repr(value)
    if type(value) is dict:
        return {k: finite_report(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return [finite_report(v) for v in value]
    return value


def verdict_text(verdict):
    """Serialise before opening the output, so a conversion failure cannot leave half a verdict."""
    return json.dumps(finite_report(verdict), indent=1, allow_nan=False)


def exit_code(status):
    if status == 'PASS':
        return 0
    if status == 'REVIEW':
        return 3
    if type(status) is str and status.startswith('VOID-'):
        return 4
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='IV1 replay: per-field compare of the before and after arms')
    parser.add_argument('--before', nargs=4, required=True, metavar=('ATTEMPT', 'DUMPS', 'PROFILE', 'PROFILE_SHA256'))
    parser.add_argument('--after', nargs=4, required=True, metavar=('ATTEMPT', 'DUMPS', 'PROFILE', 'PROFILE_SHA256'))
    parser.add_argument('--observer-sha256', required=True)
    parser.add_argument('--field-contract', nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--captures', nargs=3, action='append', metavar=('ARM', 'MAP', 'SHA256'),
                        help='r13: an arm\'s lf-r1 captures map; without it a stop-dependent FAIL is VOID-SUSPECT')
    parser.add_argument('--selected-pins', nargs=2, metavar=('PATH', 'SHA256'),
                        help='r13: the selected generation\'s launcher/helper/guard/entry-point pins')
    parser.add_argument('--causal-evidence', nargs=3, action='append', metavar=('ARM', 'BUNDLE', 'SHA256'),
                        help='r18: one arm\'s closed causal evidence bundle (needs r2 selected pins)')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise SystemExit('verdict file exists')
    try:
        verdict = run(args)
    except ProofError as error:
        verdict = {'schema': SCHEMA, 'status': 'FAIL', 'fail': ['proof/integrity: %s' % error],
                   'inputs': {'before': args.before, 'after': args.after}}
    except Exception as error:  # noqa: BLE001 - any compare error is a FAIL verdict, never a silent pass
        verdict = {'schema': SCHEMA, 'status': 'FAIL', 'fail': ['compare error %s: %s' % (type(error).__name__, error)],
                   'inputs': {'before': args.before, 'after': args.after}}
    here = Path(__file__).resolve()
    verdict['compare_tool'] = {'path': str(here), 'sha256': file_sha(here)}
    try:
        encoded = verdict_text(verdict)
    except Exception as error:
        verdict = {'schema': SCHEMA, 'status': 'FAIL',
                   'fail': ['verdict serialization error %s: %s' % (type(error).__name__, error)],
                   'compare_tool': {'path': str(here), 'sha256': file_sha(here)}}
        encoded = verdict_text(verdict)
    try:
        with open(out, 'x', encoding='utf8') as stream:
            stream.write(encoded)
    except OSError as error:
        print(json.dumps({'status': 'FAIL', 'fail': ['cannot save verdict: '+str(error)]}), flush=True)
        return 1
    print(json.dumps({'status': verdict['status'], 'fail': verdict.get('fail', [])[:5],
                      'void': verdict.get('void', []), 'review_count': verdict.get('review_count'),
                      'review': verdict.get('review', [])[:8]}), flush=True)
    return exit_code(verdict['status'])


if __name__ == '__main__':
    sys.exit(main())
