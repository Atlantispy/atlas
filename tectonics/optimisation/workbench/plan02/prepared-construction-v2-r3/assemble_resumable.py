"""Candidate prepared composer for explicitly selected gen-r3/s4 bytes (inputs v3).

The legacy construct_successor route is retained. Measuring stages is a separate
non-building operation; only a selected complete measurement can be built.
Profile writing requires real, pinned complete-package review evidence.

construct() is pure construction. It authenticates every input against the
reviewed-inputs document and the frozen I/F manifests, executes the reviewed
transformers under their REAL module names (then audits sys.modules), applies
each canonical per-file chain with asserted input and stage digests (staging
files only inside a private temporary directory), composes the private heat
helpers and the successor guard, and returns bytes. write_composition() writes
a NEW target exactly once with an explicit allow-list manifest (the
predecessor's files map is never inherited). write_review() writes the helper
review, runtime-compatibility policy and restart profile for an already frozen
target, after its execution identity has been measured.

Nothing here reads a world store, opens a database, launches science, grants
historical admission, authorises migration or accepts a scientific result.
"""
import argparse
import ast
import builtins
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys
import tempfile
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
OPTIMISATION = HERE.parent
BASE = OPTIMISATION/'runtime-integration-r1'
FILTERED = OPTIMISATION/'filtered-exact-r1'
WORKSPACE = HERE.parents[3]
EVIDENCE_ROOT = 'fidelity-integration-20261005'
HISTORICAL_RELATIVE = EVIDENCE_ROOT+'/heat-repair-20261007'
HISTORICAL = WORKSPACE/HISTORICAL_RELATIVE
HISTORICAL_TESTS_RELATIVE = HISTORICAL_RELATIVE+'/source/tectonics/tests'
HISTORICAL_TESTS = WORKSPACE/HISTORICAL_TESTS_RELATIVE
HISTORICAL_NATIVE_RELATIVE = HISTORICAL_RELATIVE+'/native-composed-r7/tectonics/src'
DOCUMENT_SCHEMA = 'atlas.private.resumable-reviewed-inputs.v3'
ROUTE = 'legacy-prepared-construct_successor'
COMPLETED_QUERY_STORE = 'files'
SOURCE_SELECTION_SHA256 = '0f2662815f38c4d1f82502d169e0e07ac9d583e51e28307389c402fd9254e163'
SELECTED_INPUT_PINS = {
    "bounded_preseal.py": "9b3b38590aeaa515bdde5040dd3ae8c5c2ccee357c9678128ada4c186710bb49",
    "compact-geometry-r1/compact_contracts.py": "0aabad86c1ccffd79b79f8aa320c7406a0406c659105f21838beb37c5bc69f6e",
    "compact-geometry-r1/compact_store.py": "18553383347e2a881178736e68903a85b79dd21f169e20a015cd01060fd990fb",
    "compact-geometry-r1/content_cache.py": "de7d3e454b41e78916a2c98cf76efe531e981be9a232915d6d152d6ad61e05bb",
    "compact-geometry-r1/exchange_record_patch.py": "c594d8a5c0d1372dbc823488422fcc9ca44fbed03afe3bc042d950adc79f2a0a",
    "compact-geometry-r1/exterior_mesh_patch.py": "84367f31a6cb1cc32e8d111fa21f1b21f1dcaa12f82aa94266c00888a6a6d890",
    "compact-geometry-r1/heat_ledger_tables.py": "d2738a40e2c4378901bdb803fd8e4ad6c6e8f48755e26625dc96392d1ac72d77",
    "compact-geometry-r1/heat_payload_indexed_patch.py": "7925a13d39e23d78b9a1eac8d93ec9abfb70d166bf76b978f5094ec2a64ef21d",
    "compact-geometry-r1/interval_catalog.py": "51a5010e2a92aa325a0cc7f34fc9af27e86a3c12e5f69e35bf4a5197601d31e0",
    "compact-geometry-r1/interval_store_set.py": "699ae4438c7ab05e71994d30533096eb2d404d74315637c08181ea94536b1af7",
    "compact-geometry-r1/live_composite.py": "8ef80a9a276a5403bada049ee82403c8b6b39865a67e0b22d6388e70d8071e89",
    "compact-geometry-r1/live_finite_patch.py": "411513a999da23212e29cd99473a99e4448c86f6af14435218eb19094d8c3382",
    "compact-geometry-r1/live_spatial_patch.py": "b53445f80d49ab5812beba52866ad85220125dc97251c7f75d82ea5bcf0c629f",
    "compact-geometry-r1/live_transport_result.py": "5289f216df642140dfb21243726ba8e487fcfbd4bbf6b2499107999ebfb5fb76",
    "compact-geometry-r1/mesh_tables.py": "5fd2afcde6064fcd004a041d0ecfa4a40da90c84f8b36e9c24df0f011cd897ab",
    "compact-geometry-r1/mimetic_patch.py": "25fa352575e6f611bd98e9e7ebe828ce279c05c64d7fb9433899f98ab1b1e4d1",
    "compact-geometry-r1/partition_native_patch.py": "516aeea679af01628f4f8cf91367c6a352dbb06e31ce37296363efe07e099daa",
    "compact-geometry-r1/partition_routing_patch.py": "c7eebabf9c1bf1292661248ee6797e4aeaf59041b0fe2003d1143a5ff4b2695a",
    "compact-geometry-r1/partition_routing_transform.py": "065ee811ccfb32bac2eecc497b33a7d586eca2240ca795389e4a353ca13f072a",
    "compact-geometry-r1/partition_store.py": "a013e2c3e7cb8676d0bb81ad7303a5edab7afa9bf70d9e701f6d45f901816ea7",
    "compact-geometry-r1/partition_tables.py": "91b346b29ced03a4fd9d21feb755ba369ce99a70b740ba78cf8437dcc20ab87b",
    "compact-geometry-r1/partition_v2.py": "d5154d3f26aa95324941be33f8e13043bbfbd933fe8e6dfbd018f374886043d9",
    "compact-geometry-r1/partition_workflow_patch.py": "7ccb25fae2288af60a43454291796e8dc49cc9824d357d89d4a0bdc8ca285515",
    "compact-geometry-r1/partition_workflow_transform.py": "32f677c838d0f649f1b345d6384dc39e2dfc8022e4ce0d475c11ea2634ae2fb7",
    "compact-geometry-r1/pressure_indexed_patch.py": "315537284fd3aa4d461a0983bb087c78453de0811e432503ad59a585ba4f1c16",
    "compact-geometry-r1/private_heat_bundle.py": "bf0ca2d5578d5107a981bbed26a392ecb67bf6a606d069f36a752a5be887bf3b",
    "compact-geometry-r1/private_heat_indexed_runtime.py": "997277d845d81db007933f7e0d21531044571d09b7b7de31ac567e84f3c65ead",
    "compact-geometry-r1/private_heat_mesh_patch.py": "be9df67b4ffba66a582273a2901a2ce7678fdd5285ef33a888732cc1692d3380",
    "compact-geometry-r1/private_heat_snapshot_store_r4.py": "8d2069737d55533f352a566b7b83fb46ea415a5fb58d57f10f66d14ec9aa1d49",
    "compact-geometry-r1/ram_context_indexed_patch.py": "59d134beb2229c00f54607a6256079c54f2283491e60df7b1a8b7f0f21414cff",
    "compact-geometry-r1/record_tables.py": "eef9795cbec817b394d9b1a7cb0dec9d5f303dcbbc9e8d62b0409a24585d4a65",
    "compact-geometry-r1/record_views.py": "a6bbb81dcc88c7f4b84272929922a8e4f702694163b18d18c26d3b76a86f89bd",
    "compact-geometry-r1/segment_store.py": "a90ef8f3e519ee77ea4332380428ce2694c16134ec69603ccaf93ce95cea6cd9",
    "compact-geometry-r1/spatial_indexed_patch.py": "83ca173c950094c45c5d10922fd93a27f1b9cc8d6cd525be345442df21ae6c83",
    "compact-geometry-r1/spatial_record_recipes.py": "364283d64f5cde0d88e263ed076600358294944ed3d66261663845ec9bef0331",
    "compact-geometry-r1/spatial_records_patch.py": "77abd1a2e9a76071f4997ee5ff2237b3af13db6b9d12da0eaa60e6b4fb23a1b7",
    "compact-geometry-r1/spatial_validation_patch.py": "556f2242cd269b01538267222ff958a60fc1dce43478b656fcfb0177187cd674",
    "compact-geometry-r1/spatial_workflow_patch.py": "a13366d507b7ce260f9decbda37ab7453327d0c16ee6f85038dafd44b91d61b4",
    "compact-geometry-r1/support_source.py": "60897be3ab6a7a7b46400a51cd1ead3a88eed2935c6fa8817fbda6c4ef05049a",
    "compact_restart_patch.py": "9d076c80a6b431e65886e0f387923a51e139be9089bdbc2c7bc8ac39e3c6540d",
    "compact_restart_store.py": "29c6ec1891e59717f4ab5f0d2ca600858b397271cd6915e75d8ed16a9318be13",
    "continuation_transfer.py": "607991aaa4370828042e978dd402fa2c351cf532e23f3a3d2c5027788b37b797",
    "dev_stage_timing.py": "0eeaca3906f5f718ef0e9ed0a93a639f7fc849e31a86958da46130699ce67811",
    "endpoint-checkpoints/integration_endpoint_checkpoints.py": "5d96c05dd88f8a9abdb1bc167a5e37284208596f90289ebf797e6fd1513d5a05",
    "endpoint-checkpoints/patch_endpoint_scheduler.py": "203ad8cc743ed4ed181d0d952df49e0dee38a9592dad759505f97086c714abb6",
    "endpoint-checkpoints/patch_endpoint_seam.py": "597b5ae52520806a8dfc7f06a19c99415b643eb04549d8304c3eacb365329542",
    "fresh_interval_driver.py": "5b288b60c99cb26cfc89c836aa6e6c77e6cb20769b54c998ac559e2b76ce25ae",
    "funding_transfer.py": "3f02bf290ffe9f239dc571f5d831320f3da360ae6e205ef09cb96b4dd528c90b",
    "geometry_transfer.py": "51cad40f94e77437e1a2f43c619afc2e8c9e95d54b04fcafafb81d80ada1bf8a",
    "historical_admission.py": "614d1ceab3d04d33bb791e494383f710b24a5e4901fff36e6de89cf0826f4710",
    "historical_compact_heat.py": "5e0bfbe17ed590894bc3a03c8e5ca5f8da830264d07a61aef72abbcc9bc7e79f",
    "initial_workload.py": "9ca14a156149ba45080c8ff1dbbd5b044a6c8cdabc6368b51dbb80e66922c528",
    "materialise_endpoint.py": "e13df064f349a288d6927cf5960f397dc19ed7c459f0df017560e4bb7b5f1706",
    "native_transfer.py": "7588e9790ff4fe41475b467661e1122e308d0194d45586bc13c2ec080313c2d1",
    "patch_ale_checkpoints.py": "c4ef0f17e3219b50bdd5ace85098740b8d2392c548139755cb072fb181377eea",
    "plan_preparation.py": "b14e756e184ddca5a6a034bcb5e4da72ab043602fc7e94150b0fad719b851d1f",
    "prepared_interval_driver.py": "4dcc0719784bc45b9dd2967c735e0f1c7ab93263935eb136638ae23b21f21351",
    "probe_execution_identity.py": "5470acc64e3ded77784ef2b18662f885f95a36e1dad24d7bd9902af898a097bd",
    "reopen_prepared_restart.py": "c203542faaa000f0e40d54665a5ec7ea70a0fa8c9a259b846bce846d41408864",
    "resource_guard_patch.py": "60ed930cc7dfeff6e2c0fe449693ce4aa62db061f25c3afe2ba7e5e98a06b0a2",
    "route2_gate.py": "235bf0450d73f205fe6a3879cc32bbede2e01a9a604f5e871b1c33080c0b3b86",
    "run_prepared_restart.py": "051008ad29fc56d42393c33b7dfcde622a39b5e9cce03a4900b91934ee066ce9",
    "runtime_compatibility.py": "b0b3742cc6a8aca5dc86bb534210e4abd6edeb30863e12ce50be9f508542e6ae",
    "spatial_transfer.py": "36110d22fd75a9d81f5961a65c65d9becbe8a191189959c7cb0c87c8a74b88f7",
    "start_gate.py": "16e448d60556acabc337c4ff7b39649d7ab8110aa5585ec6a82262e1838f6345",
    "workflow_transfer.py": "f727aea496a9faa97472587e9ec5f9577da83f06a96709d58967b6c753ac9ad3"
}
MANIFEST_SCHEMA = 'atlas.private.resumable-runtime-source.v2'
PREDECESSOR = '597c00328bb8aede225a8a936dcea2edab42d3c894eb87caeb974fdfd576979d'
FILTERED_MANIFEST = '43effbdb044218524c178518d155d7ff9d387d9b3859a4127e211a9cc5681683'
FILTER_DELTA = frozenset(('atlas_tectonics/integration_exact_gmp.py',
    'atlas_tectonics/integration_volume_bounds.py',
    'atlas_tectonics/integration_filtered_predicates.py'))
TARGET_PATTERN = re.compile(r'composed-r[1-9][0-9]*')
# Target-relative layout. The historical tests directory is the only H import
# root (M13): no H root, no H/source/tectonics/src, no H/native-composed-*.
LAYOUT = {'native_root': 'runtime-src', 'helpers': 'helpers', 'ram': 'ram',
          'historical_tests': HISTORICAL_TESTS_RELATIVE,
          'import_root_order': ['helpers', 'ram', 'historical_tests']}

# Transformers, executed from authenticated bytes under their REAL module names
# in dependency order. spatial_workflow_patch imports atlas_tectonics at module
# level, so only its require()/transform() are AST-extracted (E18).
TRANSFORMERS = (
    ('mesh_tables', 'compact-geometry-r1/mesh_tables.py'),
    ('partition_tables', 'compact-geometry-r1/partition_tables.py'),
    ('partition_native_patch', 'compact-geometry-r1/partition_native_patch.py'),
    ('native_transfer', 'native_transfer.py'),
    ('spatial_transfer', 'spatial_transfer.py'),
    ('geometry_transfer', 'geometry_transfer.py'),
    ('workflow_transfer', 'workflow_transfer.py'),
    ('funding_transfer', 'funding_transfer.py'),
    ('continuation_transfer', 'continuation_transfer.py'),
    ('spatial_indexed_patch', 'compact-geometry-r1/spatial_indexed_patch.py'),
    ('partition_routing_transform', 'compact-geometry-r1/partition_routing_transform.py'),
    ('partition_workflow_transform', 'compact-geometry-r1/partition_workflow_transform.py'),
    ('pressure_indexed_patch', 'compact-geometry-r1/pressure_indexed_patch.py'),
    ('private_heat_indexed_runtime', 'compact-geometry-r1/private_heat_indexed_runtime.py'),
    ('heat_payload_indexed_patch', 'compact-geometry-r1/heat_payload_indexed_patch.py'),
    ('ram_context_indexed_patch', 'compact-geometry-r1/ram_context_indexed_patch.py'),
    ('private_heat_bundle', 'compact-geometry-r1/private_heat_bundle.py'),
    ('exterior_mesh_patch', 'compact-geometry-r1/exterior_mesh_patch.py'),
    ('mimetic_patch', 'compact-geometry-r1/mimetic_patch.py'),
    ('resource_guard_patch', 'resource_guard_patch.py'),
    ('patch_endpoint_seam', 'endpoint-checkpoints/patch_endpoint_seam.py'),
    ('patch_endpoint_scheduler', 'endpoint-checkpoints/patch_endpoint_scheduler.py'),
    ('patch_ale_checkpoints', 'patch_ale_checkpoints.py'),
)
SPATIAL_WORKFLOW = 'compact-geometry-r1/spatial_workflow_patch.py'
ENDPOINT_COMPANION = 'endpoint-checkpoints/integration_endpoint_checkpoints.py'
# The heat bundle's HELPER_COPIES and COMPANION_HELPERS (the observer is I-pinned).
BUNDLE_HELPER_SOURCES = {
    'heat_payload_indexed_patch.py': 'compact-geometry-r1/heat_payload_indexed_patch.py',
    'private_heat_indexed_runtime.py': 'compact-geometry-r1/private_heat_indexed_runtime.py',
    'private_heat_mesh_patch.py': 'compact-geometry-r1/private_heat_mesh_patch.py',
    'partition_routing_transform.py': 'compact-geometry-r1/partition_routing_transform.py',
    'partition_routing_patch.py': 'compact-geometry-r1/partition_routing_patch.py',
    'funding_transfer.py': 'funding_transfer.py',
    'geometry_transfer.py': 'geometry_transfer.py',
    'native_transfer.py': 'native_transfer.py',
    'spatial_transfer.py': 'spatial_transfer.py',
    'partition_native_patch.py': 'compact-geometry-r1/partition_native_patch.py',
    'partition_tables.py': 'compact-geometry-r1/partition_tables.py',
    'mesh_tables.py': 'compact-geometry-r1/mesh_tables.py',
    'spatial_indexed_patch.py': 'compact-geometry-r1/spatial_indexed_patch.py',
    'pressure_indexed_patch.py': 'compact-geometry-r1/pressure_indexed_patch.py',
    'continuation_transfer.py': 'continuation_transfer.py',
    'exterior_mesh_patch.py': 'compact-geometry-r1/exterior_mesh_patch.py',
}
OBSERVER = 'private_heat_geometry_observer_r1.py'
# Remaining runtime helpers, copied verbatim under their plain module names: the
# restart route (runner, driver, reader, identity probe) and its closure.
COPIED_HELPERS = {
    'bounded_preseal.py': 'bounded_preseal.py',
    'compact_contracts.py': 'compact-geometry-r1/compact_contracts.py',
    'content_cache.py': 'compact-geometry-r1/content_cache.py',
    'exchange_record_patch.py': 'compact-geometry-r1/exchange_record_patch.py',
    'heat_ledger_tables.py': 'compact-geometry-r1/heat_ledger_tables.py',
    'interval_catalog.py': 'compact-geometry-r1/interval_catalog.py',
    'interval_store_set.py': 'compact-geometry-r1/interval_store_set.py',
    'live_composite.py': 'compact-geometry-r1/live_composite.py',
    'live_finite_patch.py': 'compact-geometry-r1/live_finite_patch.py',
    'live_spatial_patch.py': 'compact-geometry-r1/live_spatial_patch.py',
    'live_transport_result.py': 'compact-geometry-r1/live_transport_result.py',
    'partition_v2.py': 'compact-geometry-r1/partition_v2.py',
    'private_heat_snapshot_store_r4.py': 'compact-geometry-r1/private_heat_snapshot_store_r4.py',
    'record_tables.py': 'compact-geometry-r1/record_tables.py',
    'record_views.py': 'compact-geometry-r1/record_views.py',
    'segment_store.py': 'compact-geometry-r1/segment_store.py',
    'spatial_record_recipes.py': 'compact-geometry-r1/spatial_record_recipes.py',
    'spatial_records_patch.py': 'compact-geometry-r1/spatial_records_patch.py',
    'spatial_validation_patch.py': 'compact-geometry-r1/spatial_validation_patch.py',
    'support_source.py': 'compact-geometry-r1/support_source.py',
    'compact_restart_patch.py': 'compact_restart_patch.py',
    'compact_restart_store.py': 'compact_restart_store.py',
    'fresh_interval_driver.py': 'fresh_interval_driver.py',
    'historical_compact_heat.py': 'historical_compact_heat.py',
    'route2_gate.py': 'route2_gate.py',
    'start_gate.py': 'start_gate.py',
    'workflow_transfer.py': 'workflow_transfer.py',
    'historical_admission.py': 'historical_admission.py',
    'runtime_compatibility.py': 'runtime_compatibility.py',
    'materialise_endpoint.py': 'materialise_endpoint.py',
    'plan_preparation.py': 'plan_preparation.py',
    'initial_workload.py': 'initial_workload.py',
    'run_prepared_restart.py': 'run_prepared_restart.py',
    'prepared_interval_driver.py': 'prepared_interval_driver.py',
    'dev_stage_timing.py': 'dev_stage_timing.py',
    'reopen_prepared_restart.py': 'reopen_prepared_restart.py',
    'probe_execution_identity.py': 'probe_execution_identity.py',
    'compact_store.py': 'compact-geometry-r1/compact_store.py',
    'spatial_workflow_patch.py': 'compact-geometry-r1/spatial_workflow_patch.py',
    'partition_store.py': 'compact-geometry-r1/partition_store.py',
    'partition_workflow_patch.py': 'compact-geometry-r1/partition_workflow_patch.py',
}
# mimetic_patch is a composition transformer only: no shipped module imports it
# (WORKER_RUNTIME_HELPERS merely names it), so it is not on the allow-list.
REVIEWED_FILES = tuple(sorted({relative for _, relative in TRANSFORMERS} | set(BUNDLE_HELPER_SOURCES.values()) |
                              set(COPIED_HELPERS.values()) | {SPATIAL_WORKFLOW, ENDPOINT_COMPANION}))
GUARD_INPUTS = {  # workspace-relative: the guard and job are I-pinned, the diagnostics external
    'guard': HISTORICAL_RELATIVE+'/private_heat_continuation_guard_r3.py',
    'job': HISTORICAL_RELATIVE+'/windows_workload_job.py',
    'diagnostics': EVIDENCE_ROOT+'/continuation-repair-20261013/optimisation-20261014/monitored-continuation-r1/'
                   'private_heat_resource_diagnostics_r1.py',
}
# Outside both frozen manifests. Each is ALSO pinned by the reviewed module that
# reads it (bundle EXTERNAL_PINS / REFERENCE_PINS, resource_guard_patch).
EXTERNAL_FILES = {
    HISTORICAL_RELATIVE+'/private_heat_original_coverage_r1.py':
        '90113110a3c7a37c70ea16df6de6166d61ed728d2bc974f6e2e3dbd49409c688',
    HISTORICAL_RELATIVE+'/private_heat_original_coverage_r2.py':
        '078a4a730d0cbac4c60b9e9e4f992859883af9ce282a089a9471125e214690c3',
    GUARD_INPUTS['diagnostics']: 'c0430517414e7b8aa2bc3a7a9e82143be8351bd0a03f3fd08daa993b64e5ee72',
    HISTORICAL_RELATIVE+'/source/tectonics/src/atlas_tectonics/integration_mimetic_newton.py':
        'ef0f3b48ec1c992f2887f53b21c054d69439e58be2d3d445069162f29a51a0f0',
    HISTORICAL_RELATIVE+'/source/tectonics/src/atlas_tectonics/integration_mimetic_heat.py':
        '4eb824b472c977d3c6b57693f966566f243f1a1d253472886a82b5b377bc1c94',
    HISTORICAL_RELATIVE+'/source/tectonics/src/atlas_tectonics/integration_spatial_transport.py':
        '70cdfc9a5b0a4e6b518f6354550fc2a23b333a0474c07dfac55f670cdffde230',
    HISTORICAL_RELATIVE+'/source/tectonics/src/atlas_tectonics/integration_exact_gmp.py':
        '1cecc336d4584f44ba3ae97636e22e4048638d627d656ab2cc766dc6b46d5f8f',
    HISTORICAL_TESTS_RELATIVE+'/i04_differential_spatial_fixture.py':
        'f13d48b68e0b6f0b2de92e2bb903c71fe6beb92e56f2795be131ea2488b760ee',
}
# Preserved accounting references that are ALSO imported as code on the restart
# route stay in files (still exactly pinned): data_only refuses an import.
# test_i04_spatial_workflow is imported at module level by the derived joined
# control; i04_differential_joined_control by the non-compact trace-retention
# path while the runner sets ATLAS_FOCUSED_ARTIFACT_DIR. The rest are data_only.
IMPORTED_REFERENCES = frozenset((HISTORICAL_TESTS_RELATIVE+'/test_i04_spatial_workflow.py',
                                 HISTORICAL_TESTS_RELATIVE+'/i04_differential_joined_control.py'))
# Metadata validators historical_admission executes by path from H. They are
# never shipped as helpers (M13); executed code, so pinned in files.
HISTORICAL_VALIDATORS = {
    'private_heat_reader_memory_r3.py': 'cfec1f1ea62e3bf0fc2e3d1d9d9ca7d7be408fa1949e571baaf443dc4a324155',
    'private_heat_recovery_consumer_r4.py': 'f78b73eb28b172dbb82f357d1373f08434707a6b1bc885d2062d7cfdec219485',
    'private_heat_recovery_admission_r1.py': '8da3151edd7e624b2453d2c170db93371d9694c51e1d65e212d1100aff9fbe36',
}
PREPARATION = HISTORICAL_TESTS_RELATIVE+'/i04_differential_fixture.py'
DRIVER_MODULE = 'prepared_interval_driver'
# The .r44-env distributions the shipped code imports (strict ExecutionContext
# binds the third-party environment; the source fence binds workspace files).
THIRD_PARTY = frozenset(('numpy', 'scipy', 'psutil', 'gmpy2', 'threadpoolctl', 'numba', 'llvmlite', 'shapely',
                         'blosc2'))
# Stage digests the packages delivered (wave-1/2 receipts). Always asserted, in
# addition to the reviewed document's complete stage_digests.
PACKAGE_DIGESTS = {
    'atlas_tectonics/integration_differential_geometry.py@input':
        '7d93bae4aef24b1124a05930a49a921662aff9aa36d4995ab62fac2bd19b1034',
    'atlas_tectonics/integration_differential_geometry.py@partition_native_patch.transform':
        '29443f86c8dce100af71072426f9848a5cc7ed4f20cbbb323d98a6ec0c725924',
    'atlas_tectonics/integration_differential_geometry.py@patch_endpoint_seam.candidate_sources':
        '213d1ebb5ef4d072f65ae3c08b99a4537f61985e46fe802e54c58a1b6ac471fd',
    'atlas_tectonics/integration_differential_geometry.py@geometry_transfer.transform(compact=True)':
        'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253',
    'atlas_tectonics/integration_endpoint_checkpoints.py@patch_endpoint_seam.companion':
        '5d96c05dd88f8a9abdb1bc167a5e37284208596f90289ebf797e6fd1513d5a05',
    'atlas_tectonics/integration_differential_coupling.py@input':
        '9938992a75e5a70323810a055be1e7e0b8519f44c04c56c0142ac1df90d327c7',
    'atlas_tectonics/integration_differential_coupling.py@partition_native_patch.transform_coupling':
        '0ef4c17d3c66fdd9d766c8f8ff75d34e89018e4c349e3ca6a220c584d06e19a5',
    'atlas_tectonics/integration_differential_coupling.py@continuation_transfer.coupling_source':
        '05f2414de10b89217f362da70966718f69a3a1aeb1e3c3a8a3895ce85d389779',
    'atlas_tectonics/integration_routing_views.py@input':
        'bd2f65ad8218bab51d90a9df765a7f0368a702ee4d4caf1a37cefe1268e6eb40',
    'atlas_tectonics/integration_routing_views.py@partition_routing_transform.transform':
        '8bcfb2f92c091024817f81e7c6a16718130547df7c3088f342a0578deffc032d',
    'atlas_tectonics/integration_parallel_dispatch.py@input':
        '2b17c8d95f254b66c44e75cf9fde1d7ee2c67b03c5d286c95997d401d06a4bab',
    'atlas_tectonics/integration_parallel_dispatch.py@partition_routing_transform.transform':
        '2545cb43b9dfac6a47b8b6c99147206c3542ea945bdde460534bf37043347782',
    'atlas_tectonics/integration_parallel_selection.py@input':
        'b7b153d90003670b4d47179353a2d1d0fe8fa5ff060bf553deb502aaaa84a007',
    'atlas_tectonics/integration_parallel_selection.py@partition_routing_transform.transform':
        '536c3e3e9328db0758e6f9d1821a68e729ef2cf023d45d01d02b5cbbc446926c',
    'atlas_tectonics/integration_differential_trace.py@input':
        'df20e7f1eb9059ccbd6c1637a5f7b0f0eb88fe616f88aef367692fe0a8b272e7',
    'atlas_tectonics/integration_differential_trace.py@partition_routing_transform.transform':
        '4519d95cdbcc3afa7053ac8813190f1987e4db64a19519eda620c512dd6fb545',
    'atlas_tectonics/integration_differential_ale.py@input':
        '8c5de47212a73548ecba1f759d884851b62b9b94c3f5b14e27268e5cda898529',
    'atlas_tectonics/integration_differential_ale.py@partition_routing_transform.transform':
        'f3885ba120d83da6f1414f17583294a376510f8d3099e40317f71f8daee16dab',
    'atlas_tectonics/integration_differential_ale.py@patch_ale_checkpoints.candidate_source':
        '9d20f9f2217e23839270cca1ca3daf9530dc9a9da68f701cb185b085d41ed644',
    'atlas_tectonics/integration_component_volume_auto.py@input':
        '5ade97ccca1afd5c933fb5993d7e3500b3efd64d6e3bf76906b84f024f94205c',
    'atlas_tectonics/integration_component_volume_auto.py@partition_routing_transform.transform':
        '789f1f70d79a8c3ed66df721c017184a2a39eac767f2436dcf7bd9501a7471d9',
    'atlas_tectonics/integration_component_volume_auto.py@patch_endpoint_scheduler.transform_auto':
        '72cb051ecc3a3be369891add19922e3c62f57f0367995c8dffedd2770e12c3b9',
    'atlas_tectonics/integration_parallel_rolling.py@patch_endpoint_scheduler.transform_rolling':
        '6daa2d3a84a224fe9e4724cd0212d0195c474a044440a5f6df36c9cd37c7981a',
    'atlas_tectonics/integration_differential_pressure.py@input':
        '8615d60bd46ccb822b7fa1089d487997f40c110bc7c6865d7e16eaebad6663d2',
    'atlas_tectonics/integration_differential_pressure.py@pressure_indexed_patch.transform':
        '65d9095fde5fe685a78e1b15d113a7f3e830c6f4895508abd58983144519c551',
    'atlas_tectonics/integration_differential_pressure.py@funding_transfer.pressure_source':
        '8d3d8f3dd11d632ce6a75380a17fdcd19b281fafa03b68401a2726d228c02a33',
    'atlas_tectonics/integration_regional_workflow.py@input':
        'ddb8d1b20aab4898e8b3a3ed3a0242b4bec538b5f902beea8b32778ed27b007a',
    'atlas_tectonics/integration_regional_workflow.py@workflow_transfer.nonzero_cursor_source':
        '61888439a0acd5484279cce374f23939550e81b38da73991d4f82c7c5e3c9916',
    'atlas_tectonics/integration_regional_workflow.py@spatial_workflow_patch.transform':
        '26ebf01ad7c5ecbdb2170092b8899d6c174e9c0169641426ade69449ee48cdc7',
    'atlas_tectonics/integration_regional_workflow.py@partition_workflow_transform.transform':
        'b81752611b3860b26666467227582c3decee1ef7a1e91e5977ea6b04133542f9',
    'atlas_tectonics/integration_private_heat_cold.py@input':
        '82d90e8f717f9f2dea06a36a53086298b74f7a4788e6ca825e3678259d48f729',
    'atlas_tectonics/integration_private_heat_cold.py@workflow_transfer.private_heat_cold_source':
        'd8a76d4d0287e8334dfe279b66ee91eb808dd1bf3bcc1ba13cae20ab935c50b4',
    'atlas_tectonics/integration_private_heat_cold.py@partition_workflow_transform.cold_source':
        'ed202b4b0834a0317cf644f7d5f9b68060bfe37408cfea7740bf3719cc569a7f',
    'atlas_tectonics/integration_private_heat_cold.py@private_heat_bundle.cold_binding_source':
        '701e190e8d81585a2d4eedbea795a5380d30b7d82aafd3dbbde47e1692c7696b',
    'atlas_tectonics/integration_spatial_owner.py@spatial_transfer.spatial_owner_source':
        '04a5945032e55a91add2ae57e65baa22983613aff66b8927d8e891c548f36c3b',
    'atlas_tectonics/integration_exterior_mesh.py@input':
        'd1d2abefa7ae4cc5a83d64b80c036475669284002b10eef9bc591f3e2a117503',
    'atlas_tectonics/integration_mimetic_heat.py@input':
        '4eb824b472c977d3c6b57693f966566f243f1a1d253472886a82b5b377bc1c94',
    'atlas_tectonics/integration_extremum_heat.py@input':
        '9288970827dc90b37fa381f95fee01f1f5ef4aa98df0d6f641c26d26a7de2089',
    'helpers/private_heat_original_joined_r6.py@private_heat_bundle.joined_successor_source':
        'c7239e2d1982082eeda02de67da036c776194a41560486ec89152242b5dd7498',
    'helpers/private_heat_original_continuation_r1.py@partition_routing_transform.original_continuation_source':
        '3d859c53c9b731fccbba09609b9c86c3104f445cc9c5f46367f63ef6ebc144df',
    'ram/private_heat_restored_binding_ram_context_r1.py@ram_context_indexed_patch.transform':
        '85c9ed5fa7cc0f3b32101b99edf16f4e949d4b2e38e7becdd3e03fbc4fa196b7',
    'ram/private_heat_restored_binding_ram_context_r1.py@output':
        '3ba60e2866a9f8fbb18473db6b85eb38529ae4f7a1d2a14185a0ccdf04a71f2f',
    'ram/private_heat_restored_binding_ram_recovery_r1.py@output':
        '71f821917cc4c5e68642133f1648b5379aa7b355f0b48958b899c7d3df8fd110',
    'helpers/private_heat_continuation_guard_r3.py@input':
        '2d23f4bbc3b31b5aad3d68ef6e9b1a9800042fc75b12475b51dff468492ad796',
    'helpers/private_heat_continuation_guard_r3.py@resource_guard_patch.transform':
        '9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772',
}
RUNTIME_WORKSPACE = (b'WORKSPACE = HERE.parents[3]', b'WORKSPACE = HERE.parents[4]')
RUNTIME_ROOTS = (b"        sys.path[:0] = [str(self.source), str(HERE / 'ram'), str(HERE / 'helpers'),\n"
                 b"                       str(HEAT), str(HEAT / 'source/tectonics/tests')]\n",
                 b"        sys.path[:0] = [str(self.source), str(HERE / 'helpers'), str(HERE / 'ram'),\n"
                 b"                       str(HEAT / 'source/tectonics/tests')]\n")


class CompositionRefused(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise CompositionRefused(message)


def digest(raw):
    return sha256(raw if type(raw) is bytes else raw.encode('utf8')).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pin(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'exact SHA-256 required')
    return value


def read(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise CompositionRefused('regular reviewed source required: '+str(path))
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != _pin(expected):
        raise CompositionRefused('reviewed source changed: '+str(path))
    return raw


def workspace_relative(path):
    return Path(path).resolve().relative_to(WORKSPACE).as_posix()


def reviewed_document(path=None):
    """The checked-in reviewed-inputs record and its sha256."""
    raw = Path(path or HERE/'reviewed-inputs.json').read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def _check_document(document, *, check_stages):
    fields = {'schema', 'predecessor_manifest_sha256', 'filtered_manifest_sha256', 'files', 'external_files',
              'stage_digests', 'target', 'layout', 'authority', 'accuracy', 'source_selection_sha256',
              'stage_measurement', 'stage_selection', 'package_stage_changes'}
    _require(type(document) is dict and set(document) == fields and document['schema'] == DOCUMENT_SCHEMA,
             'closed reviewed-inputs v3 document required')
    _require(document['predecessor_manifest_sha256'] == PREDECESSOR and
             document['filtered_manifest_sha256'] == FILTERED_MANIFEST, 'frozen I/F manifest pins differ')
    files = document['files']
    _require(type(files) is dict and set(files) == set(REVIEWED_FILES),
             'reviewed files must name exactly the composer inputs')
    _require(files == SELECTED_INPUT_PINS and document['source_selection_sha256'] == SOURCE_SELECTION_SHA256,
             'prepared inputs differ from the explicit gen-r3/s4 selection')
    for name, pin in files.items():
        _pin(pin)
        _require(not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name and
                 (HERE/name).resolve().is_relative_to(HERE), 'input path escapes the private successor: '+name)
    _require(document['external_files'] == EXTERNAL_FILES, 'external inputs differ from the reviewed set')
    _require(document['layout'] == LAYOUT, 'composed layout differs from the reviewed layout')
    _require(type(document['target']) is str and TARGET_PATTERN.fullmatch(document['target']) is not None,
             'explicit new composed revision required')
    _require(type(document['authority']) is str and document['authority'].strip() != '' and
             type(document['accuracy']) is str and document['accuracy'].strip() != '',
             'authority and accuracy statements required')
    stages = document['stage_digests']
    _require(type(stages) is dict, 'stage digest record required')
    if check_stages:
        _require(bool(stages), 'complete reviewed stage digests required')
        for pin in stages.values():
            _pin(pin)
    changes = document['package_stage_changes']
    _require(type(changes) is dict, 'explicit package-stage delta map required')
    for key, row in changes.items():
        _require(key in PACKAGE_DIGESTS and type(row) is dict and set(row) == {'before', 'after', 'reason'} and
                 row['before'] == PACKAGE_DIGESTS[key] and row['after'] == stages.get(key) and
                 row['after'] != row['before'] and type(row['reason']) is str and bool(row['reason'].strip()),
                 'unexplained package-stage reconciliation: '+str(key))
        _pin(row['after'])
    for field in ('stage_measurement', 'stage_selection'):
        row = document[field]
        _require(type(row) is dict and set(row) == {'path', 'sha256'} and
                 row['path'] == field.replace('_', '-')+'.json', 'fixed local '+field+' record required')
        _pin(row['sha256'])


class _Stages:
    """Ordered per-file chains; delivered and reviewed digests are asserted on record."""

    def __init__(self, reviewed, *, package=None, measuring=False):
        self.chains, self.flat, self._reviewed = {}, {}, reviewed
        self.package = PACKAGE_DIGESTS if package is None else package
        self.measuring, self.package_drift = measuring, {}

    def record(self, path, label, value):
        key = path+'@'+label
        _require(key not in self.flat, 'duplicate composition stage: '+key)
        value = _pin(value)
        expected = self.package.get(key)
        if expected is not None and expected != value:
            _require(self.measuring, 'stage digest differs from the selected package: '+key)
            self.package_drift[key] = dict(before=expected, after=value)
        if self._reviewed is not None:
            _require(self._reviewed.get(key) == value, 'stage digest differs from the reviewed record: '+key)
        self.chains.setdefault(path, []).append([label, value])
        self.flat[key] = value
        return value

    def chain(self, path, text, *steps):
        """The input digest of every step is recorded and asserted before it runs."""
        self.record(path, 'input', digest(text))
        for label, transform in steps:
            text = transform(text)
            self.record(path, label, digest(text))
        return text


def _audit(before, loaded):
    for name, module in tuple(sys.modules.items()):
        if name in loaded:
            _require(module is loaded[name], 'authenticated transformer was replaced: '+name)
            continue
        if name in before:
            continue
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        path = Path(filename).resolve()
        _require(not path.is_relative_to(WORKSPACE) or path.is_relative_to(WORKSPACE/'.r44-env'),
                 'unauthenticated workspace module imported during composition: '+name)


@contextmanager
def authenticated_modules(blobs):
    """Execute reviewed transformer bytes under their real names; audit; then retire them."""
    present = [name for name, _ in TRANSFORMERS if name in sys.modules]
    _require(not present, 'transformer names already loaded from elsewhere: '+', '.join(present))
    before = set(sys.modules)
    loaded = {}
    try:
        for name, relative in TRANSFORMERS:
            path = HERE/relative
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = loaded[name] = module
            # Execute exactly the authenticated bytes, never a second read or a pyc.
            exec(compile(blobs[relative], str(path), 'exec', dont_inherit=True), module.__dict__)
        _audit(before, loaded)
        yield SimpleNamespace(**loaded)
        _audit(before, loaded)
    finally:
        for name, module in loaded.items():
            if sys.modules.get(name) is module:
                del sys.modules[name]


def spatial_workflow_transform(raw, indexed):
    """AST-extracted require()+transform() from authenticated bytes; no module import."""
    tree = ast.parse(raw.decode('utf8'))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('require', 'transform')]
    _require(sorted(n.name for n in body) == ['require', 'transform'], 'spatial workflow transform not found once')
    loads, stores = set(), set()
    for function in body:
        for node in ast.walk(function):
            if isinstance(node, ast.Name):
                (loads if isinstance(node.ctx, ast.Load) else stores).add(node.id)
            elif isinstance(node, ast.arg):
                stores.add(node.arg)
    free = loads-stores-set(dir(builtins))-{'require', 'transform'}
    _require(free == {'X'}, 'spatial workflow transform reaches unreviewed globals: '+repr(sorted(free)))
    namespace = {'X': indexed, '__name__': 'spatial_workflow_patch[transform]'}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(HERE/SPATIAL_WORKFLOW), 'exec',
                 dont_inherit=True), namespace)
    return namespace['transform']


def filtered_sources(sources, prior):
    """Merge only the reviewed F delta; never overwrite other restart changes."""
    record = json.loads(read(FILTERED/'manifest.json', FILTERED_MANIFEST))
    _require(record['source_inputs']['predecessor_manifest'] == PREDECESSOR,
             'filtered package has a different predecessor')
    expected = record['source_hashes']
    actual = {p.relative_to(FILTERED/'native-src').as_posix() for p in (FILTERED/'native-src').rglob('*.py')}
    _require(actual == set(expected), 'filtered package membership changed')
    base = prior['source_hashes']
    changed = {name for name in set(base) | set(expected) if base.get(name) != expected.get(name)}
    _require(changed == FILTER_DELTA and set(record['changed_from_predecessor']) == changed,
             'filtered package differs outside the reviewed delta')
    result = dict(sources)
    for name, pin in expected.items():
        raw = read(FILTERED/'native-src'/name, pin)
        if name not in changed:
            continue
        if name in base:
            _require(name in sources and digest(sources[name]) == base[name],
                     'filtered delta conflicts with another source change: '+name)
        else:
            _require(name not in sources, 'filtered helper already exists in source composition')
        result[name] = raw
    return result


def python_imports(raw):
    """(module, level) for every import statement at any depth."""
    found = set()
    for node in ast.walk(ast.parse(raw)):
        if isinstance(node, ast.Import):
            found.update((a.name, 0) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or '', node.level))
    return found


def literal(raw, name):
    """A module-level literal constant, read without executing the module."""
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise CompositionRefused('reviewed constant missing: '+name)


@dataclass(frozen=True)
class Composition:
    native: dict
    helpers: dict
    ram: dict
    runtime_py: bytes
    heat_report: dict
    guard_sha256: str
    stage_digests: dict
    chains: dict
    origins: dict
    required_modules: tuple
    historical_tests: dict
    data_only: dict
    historical_validators: dict
    import_review: dict
    stages_verified: bool
    package_stage_drift: dict


@contextmanager
def _legacy_bundle_import_closure(bundle, blobs):
    """Declare only authenticated, actually emitted companions to the legacy bundle.

    Selected companion sources now import additional C helpers. The bundle checks
    imports before A appends COPIED_HELPERS. Scope that existing composer-supplied
    group to those exact bytes, then restore it. No compact transform is enabled.
    The final assembled import check remains mandatory.
    """
    original = bundle.EXTERNAL_IMPORTS
    _require(all(relative in blobs and digest(blobs[relative]) == SELECTED_INPUT_PINS[relative]
                 for relative in COPIED_HELPERS.values()), 'unauthenticated supplied helper closure')
    supplied = set(original['composer_supplied']) | {Path(name).stem for name in COPIED_HELPERS}
    bundle.EXTERNAL_IMPORTS = {**original, 'composer_supplied': tuple(sorted(supplied))}
    try:
        yield
    finally:
        bundle.EXTERNAL_IMPORTS = original


def _compose_heat(M, prior, blobs, external, stages, origins):
    B = M.private_heat_bundle
    _require(B.EXTERNAL_PINS == {Path(k).name: v for k, v in EXTERNAL_FILES.items()
                                 if Path(k).name in B.EXTERNAL_PINS} and len(B.EXTERNAL_PINS) == 2,
             'bundle coverage pins differ from the reviewed external inputs')
    bound = {k[len(HISTORICAL_RELATIVE)+1:]: v for k, v in {**prior['files'], **EXTERNAL_FILES}.items()
             if k.startswith(HISTORICAL_RELATIVE+'/source/') and k[len(HISTORICAL_RELATIVE)+1:] in B.REFERENCE_PINS}
    _require(bound == B.REFERENCE_PINS, 'preserved accounting references are not all authenticated inputs')
    inputs = {}
    for name, pin in prior['files'].items():
        path = WORKSPACE/name
        if path.parent == HISTORICAL and path.suffix == '.py' and (
                path.name.startswith('private_heat_') or path.name in B.VERBATIM_ROOTS):
            inputs[path.name] = read(path, pin)
    ram = {name: read(BASE/'ram'/name, prior['files'][workspace_relative(BASE/'ram'/name)])
           for name in B.RAM_PINS}
    observer = BASE/'helpers'/OBSERVER
    copies = {name: blobs[relative] for name, relative in BUNDLE_HELPER_SOURCES.items()}
    copies[OBSERVER] = read(observer, prior['files'][workspace_relative(observer)])
    coverage = {Path(k).name: external[k] for k in EXTERNAL_FILES if Path(k).name in B.EXTERNAL_PINS}
    with _legacy_bundle_import_closure(B, blobs):
        helpers_out, ram_out, report = B.construct_successor(inputs, reference_root=HISTORICAL,
            reference_pins=B.REFERENCE_PINS, external=coverage, ram=ram, helpers=copies)
    _require(report['schema'] == 'atlas.private.indexed-heat-successor-composition.v2' and
             'renamed' not in report and 'compact_helpers' not in report,
             'prepared route changed from the selected legacy heat construction')
    labels = {'joined_successor_source': 'private_heat_bundle.joined_successor_source',
              'original_continuation_source': 'partition_routing_transform.original_continuation_source',
              'ram_context_indexed_patch': 'ram_context_indexed_patch.transform'}
    for key, value in report['stage_digests'].items():
        name, label = key.split('@', 1)
        stages.record(('ram/' if name in B.RAM_PINS else 'helpers/')+name, labels[label], value)
    for name, raw in ram_out.items():
        stages.record('ram/'+name, 'output', digest(raw))
    recovery = digest(ram_out[B.RAM_RECOVERY])
    _require(report['ram_recovery_sha256'] == recovery and
             report['cold_binding_sha256'] == dict(predecessor=B.RAM_PINS[B.RAM_RECOVERY], successor=recovery),
             'composed cold binding differs from the reconciled RAM recovery')
    _require(report['copied_helpers'] == {name: digest(raw) for name, raw in copies.items()} and
             all(helpers_out[name] == raw for name, raw in copies.items()),
             'bundle shipped helper bytes differ from the authenticated copies')
    pins = literal(ram_out['private_heat_restored_binding_ram_context_r1.py'].decode('utf8'), '_PINS')
    _require(pins == {name: digest(helpers_out[name]) for name in pins}, 'ram_context pins are not the composed hashes')
    for name, raw in helpers_out.items():
        if name in copies:
            source = (workspace_relative(observer) if name == OBSERVER else
                      workspace_relative(HERE/BUNDLE_HELPER_SOURCES[name]))
            origins['helpers/'+name] = dict(kind='verbatim-copy', source=source, source_sha256=digest(raw))
        else:
            source = next((k for k in EXTERNAL_FILES if Path(k).name == name), HISTORICAL_RELATIVE+'/'+name)
            origins['helpers/'+name] = dict(
                kind='bundle-transformed' if name in report['changed'] else 'bundle-verbatim', source=source,
                source_sha256=report['original'][name], transformer='compact-geometry-r1/private_heat_bundle.py')
    for name in ram_out:
        origins['ram/'+name] = dict(kind='bundle-transformed', source=workspace_relative(BASE/'ram'/name),
                                    source_sha256=report['original'][name],
                                    transformer='compact-geometry-r1/private_heat_bundle.py')
    return helpers_out, ram_out, report


def _compose_guard(M, prior, external, stages, origins):
    G, B = M.resource_guard_patch, M.private_heat_bundle
    guard = read(WORKSPACE/GUARD_INPUTS['guard'], prior['files'][GUARD_INPUTS['guard']])
    job = read(WORKSPACE/GUARD_INPUTS['job'], prior['files'][GUARD_INPUTS['job']])
    stages.record('helpers/'+G.GUARD_NAME, 'input', digest(guard))
    files = G.successor_files(guard, job, external[GUARD_INPUTS['diagnostics']])
    guard_sha = stages.record('helpers/'+G.GUARD_NAME, 'resource_guard_patch.transform', digest(files[G.GUARD_NAME]))
    _require(guard_sha == G.SUCCESSOR_PIN == B.SUCCESSOR_GUARD_SHA, 'successor guard differs from its pins')
    for name, key in ((G.GUARD_NAME, 'guard'), (G.JOB_NAME, 'job'), (G.DIAGNOSTICS_NAME, 'diagnostics')):
        origins['helpers/'+name] = dict(kind='guard-successor' if key == 'guard' else 'verbatim-copy',
            source=GUARD_INPUTS[key], source_sha256=digest(guard if key == 'guard' else files[name]),
            **({'transformer': 'resource_guard_patch.py'} if key == 'guard' else {}))
    return files, guard_sha


def _compose_native(M, frozen, blobs, report, stages, staging):
    """Plan section 2: every chain starts from the frozen I text."""
    N, S, X, PN, G = (M.native_transfer, M.spatial_transfer, M.spatial_indexed_patch,
                      M.partition_native_patch, M.geometry_transfer)
    W, FT, CT, ROUTING, PWT = (M.workflow_transfer, M.funding_transfer, M.continuation_transfer,
                               M.partition_routing_transform, M.partition_workflow_transform)
    B, SC = M.private_heat_bundle, M.patch_endpoint_scheduler
    text = {name: raw.decode('utf8') for name, raw in frozen.items()}
    out = dict(text)

    def key(stem):
        return 'atlas_tectonics/'+stem+'.py'

    name = key('regional_execution')
    out[name] = stages.chain(name, text[name], ('native_transfer.retained_snapshot_source', N.retained_snapshot_source))
    name = key('integration_spatial_owner')
    out[name] = stages.chain(name, text[name], ('spatial_transfer.spatial_owner_source', S.spatial_owner_source),
                             ('spatial_indexed_patch.transform', X.transform))
    _require(stages.flat[name+'@spatial_transfer.spatial_owner_source'] == X.TRANSFER_SOURCE_SHA256,
             'spatial owner transfer differs from the indexed patch base')
    # The endpoint and ALE checkpoint seams read package files: stage exact bytes.
    geometry, batch, ale = (key('integration_differential_geometry'), key('integration_component_volume_batch'),
                            key('integration_differential_ale'))
    stages.record(geometry, 'input', digest(text[geometry]))
    staged_geometry = PN.transform(text[geometry])
    stages.record(geometry, 'partition_native_patch.transform', digest(staged_geometry))
    stages.record(batch, 'input', digest(text[batch]))
    stages.record(ale, 'input', digest(text[ale]))
    staged_ale = ROUTING.transform('integration_differential_ale', text[ale])
    stages.record(ale, 'partition_routing_transform.transform', digest(staged_ale))
    staged = {'integration_differential_geometry.py': staged_geometry,
              'integration_component_volume_batch.py': text[batch],
              'integration_differential_ale.py': staged_ale}
    with tempfile.TemporaryDirectory(prefix='w3-stage-', dir=staging) as directory:
        stage = Path(directory)
        for filename, value in staged.items():
            with (stage/filename).open('x', encoding='utf8', newline='\n') as stream:
                stream.write(value)
        seam = M.patch_endpoint_seam.candidate_sources(stage)
        ale_text = M.patch_ale_checkpoints.candidate_source(stage)
        _require(all((stage/filename).read_text(encoding='utf8') == value for filename, value in staged.items()),
                 'staged composition input changed')
    _require(set(seam) == {'integration_component_volume_batch.py', 'integration_differential_geometry.py',
                           'integration_endpoint_checkpoints.py'}, 'endpoint seam output set differs')
    _require(seam['integration_endpoint_checkpoints.py'].encode('utf8') == blobs[ENDPOINT_COMPANION],
             'endpoint seam companion differs from its authenticated bytes')
    stages.record(geometry, 'patch_endpoint_seam.candidate_sources', digest(seam['integration_differential_geometry.py']))
    out[geometry] = G.transform(seam['integration_differential_geometry.py'], compact=True)
    stages.record(geometry, 'geometry_transfer.transform(compact=True)', digest(out[geometry]))
    out[batch] = seam['integration_component_volume_batch.py']
    stages.record(batch, 'patch_endpoint_seam.candidate_sources', digest(out[batch]))
    companion = key('integration_endpoint_checkpoints')
    _require(companion not in out, 'endpoint checkpoint companion already exists in the predecessor')
    out[companion] = seam['integration_endpoint_checkpoints.py']
    stages.record(companion, 'patch_endpoint_seam.companion', digest(out[companion]))
    out[ale] = ale_text
    stages.record(ale, 'patch_ale_checkpoints.candidate_source', digest(ale_text))
    name = key('integration_differential_coupling')
    out[name] = stages.chain(name, text[name],
        ('partition_native_patch.transform_coupling', PN.transform_coupling),
        ('continuation_transfer.coupling_source', CT.coupling_source))
    for stem in ('integration_routing_views', 'integration_parallel_selection', 'integration_differential_trace',
                 'integration_parallel_dispatch'):
        out[key(stem)] = stages.chain(key(stem), text[key(stem)],
            ('partition_routing_transform.transform', lambda source, stem=stem: ROUTING.transform(stem, source)))
    name = key('integration_component_volume_auto')
    out[name] = stages.chain(name, text[name],
        ('partition_routing_transform.transform',
         lambda source: ROUTING.transform('integration_component_volume_auto', source)),
        ('patch_endpoint_scheduler.transform_auto', SC.transform_auto))
    name = key('integration_parallel_rolling')
    out[name] = stages.chain(name, text[name], ('patch_endpoint_scheduler.transform_rolling', SC.transform_rolling))
    name = key('integration_differential_pressure')
    out[name] = stages.chain(name, text[name],
        ('pressure_indexed_patch.transform', M.pressure_indexed_patch.transform),
        ('funding_transfer.pressure_source', FT.pressure_source))
    name = key('integration_regional_workflow')
    out[name] = stages.chain(name, text[name],
        ('workflow_transfer.nonzero_cursor_source', W.nonzero_cursor_source),
        ('spatial_workflow_patch.transform', spatial_workflow_transform(blobs[SPATIAL_WORKFLOW], X)),
        ('partition_workflow_transform.transform', PWT.transform))
    name = key('integration_private_heat_cold')
    out[name] = stages.chain(name, text[name],
        ('workflow_transfer.private_heat_cold_source', W.private_heat_cold_source),
        ('partition_workflow_transform.cold_source', PWT.cold_source),
        ('private_heat_bundle.cold_binding_source', lambda source: B.cold_binding_source(source, report)))
    _require(out[name].count("_BINDING_SHA = '"+report['ram_recovery_sha256']+"'\n") == 1,
             'cold reader does not bind the composed RAM recovery')
    for stem, label, transform in (
            ('integration_exterior_mesh', 'exterior_mesh_patch.transform', M.exterior_mesh_patch.transform),
            ('integration_mimetic_heat', 'mimetic_patch.mimetic_source', M.mimetic_patch.mimetic_source),
            ('integration_extremum_heat', 'mimetic_patch.extremum_source', M.mimetic_patch.extremum_source)):
        out[key(stem)] = stages.chain(key(stem), text[key(stem)], (label, transform))
    return {name: value.encode('utf8') for name, value in out.items()}


def _import_review(native, helpers, ram, tests, off_route):
    """Every import of the shipped code resolves to a reviewed, shipped or pinned module."""
    stems = {Path(n).stem for n in (*helpers, *ram)}
    test_stems = {Path(n).stem for n in tests}
    on_disk_tests = {p.stem for p in HISTORICAL_TESTS.glob('*.py')}
    unresolved, unpinned = {}, {}
    for group, files in (('native', native), ('helpers', helpers), ('ram', ram)):
        for name, raw in files.items():
            for module, level in python_imports(raw):
                top = module.split('.')[0]
                if (level or top in sys.stdlib_module_names or top in THIRD_PARTY or top == 'atlas_tectonics' or
                        top in stems or top in test_stems):
                    continue
                target = unpinned if (top in on_disk_tests or top in off_route) else unresolved
                target.setdefault(top, set()).add(group+'/'+name)
    _require(not unresolved, 'unreviewed imports in shipped code: '+repr({k: sorted(v) for k, v in unresolved.items()}))
    return {name: sorted(users) for name, users in sorted(unpinned.items())}


def _route_reachable(native, helpers, ram, tests):
    """Static import closure from the restart route (runner, driver, reader) and the natives."""
    universe = {Path(n).stem: raw for n, raw in {**tests, **helpers, **ram}.items()}
    pending = {'run_prepared_restart', DRIVER_MODULE, 'reopen_prepared_restart'}
    for raw in native.values():
        pending |= {m.split('.')[0] for m, level in python_imports(raw) if not level}
    seen = set()
    while pending:
        name = pending.pop()
        if name in universe and name not in seen:
            seen.add(name)
            pending |= {m.split('.')[0] for m, level in python_imports(universe[name]) if not level}-seen
    return seen


def _references(report):
    """The bundle's preserved references as workspace-relative paths with exact pins."""
    return {workspace_relative(Path(path)): pin for path, pin in report['preserved_accounting_references'].items()}


def construct(document, *, staging=None, check_stages=True):
    """Pure construction from authenticated bytes; refuses on any input or stage drift."""
    _require(check_stages is True, 'use measure_stages for non-building measurement; no unchecked construction')
    _check_document(document, check_stages=check_stages)
    measured = json.loads(read(HERE/document['stage_measurement']['path'], document['stage_measurement']['sha256']))
    selected = json.loads(read(HERE/document['stage_selection']['path'], document['stage_selection']['sha256']))
    check_stage_measurement(measured)
    _require(selected.get('schema') == 'atlas.private.prepared-stage-selection.v1' and
             selected.get('status') == 'SELECTED_FOR_SOURCE_BUILD' and
             selected.get('measurement_sha256') == document['stage_measurement']['sha256'] and
             selected.get('assembler_sha256') == digest(Path(__file__).read_bytes()) and
             selected.get('source_selection_sha256') == SOURCE_SELECTION_SHA256 and
             selected.get('package_stage_changes') == document['package_stage_changes'] and
             selected.get('authority') == document['authority'] and selected.get('accuracy') == document['accuracy'],
             'stage selection does not bind this prepared document')
    _require(measured['stage_digests'] == document['stage_digests'] and
             measured['package_stage_drift'] == {key: {k: v for k, v in row.items() if k != 'reason'}
                 for key, row in document['package_stage_changes'].items()}, 'measured stage map/delta differs')
    package = {**PACKAGE_DIGESTS, **{key: row['after'] for key, row in document['package_stage_changes'].items()}}
    return _construct(staging=staging, reviewed=document['stage_digests'], package=package, measuring=False)


def check_stage_measurement(measured):
    fields = {'schema', 'status', 'route', 'assembler_sha256', 'source_selection_sha256', 'files',
              'package_baseline_sha256', 'stage_digests', 'package_stage_drift'}
    _require(type(measured) is dict and set(measured) == fields and
             measured['schema'] == 'atlas.private.prepared-stage-measurement.v1' and
             measured['status'] == 'MEASURED_NOT_SELECTED' and measured['route'] == ROUTE and
             measured['assembler_sha256'] == digest(Path(__file__).read_bytes()) and
             measured['source_selection_sha256'] == SOURCE_SELECTION_SHA256 and
             measured['files'] == SELECTED_INPUT_PINS and
             measured['package_baseline_sha256'] == digest(canonical(PACKAGE_DIGESTS)),
             'stage measurement belongs to different source bytes or route')
    _require(type(measured['stage_digests']) is dict and bool(measured['stage_digests']) and
             type(measured['package_stage_drift']) is dict, 'complete measured stage map required')
    for value in measured['stage_digests'].values():
        _pin(value)
    expected = {key: dict(before=pin, after=measured['stage_digests'][key]) for key, pin in PACKAGE_DIGESTS.items()
                if key in measured['stage_digests'] and pin != measured['stage_digests'][key]}
    _require(set(PACKAGE_DIGESTS) <= set(measured['stage_digests']) and
             measured['package_stage_drift'] == expected, 'package drift is incomplete or unexplained')


def measure_stages(*, staging=None):
    """Execute source transforms only; return evidence, never a buildable Composition or input seed."""
    composition = _construct(staging=staging, reviewed=None, package=PACKAGE_DIGESTS, measuring=True)
    result = dict(schema='atlas.private.prepared-stage-measurement.v1', status='MEASURED_NOT_SELECTED',
        route=ROUTE, assembler_sha256=digest(Path(__file__).read_bytes()),
        source_selection_sha256=SOURCE_SELECTION_SHA256, files=dict(SELECTED_INPUT_PINS),
        package_baseline_sha256=digest(canonical(PACKAGE_DIGESTS)), stage_digests=composition.stage_digests,
        package_stage_drift=composition.package_stage_drift)
    check_stage_measurement(result)
    return result


def _construct(*, staging, reviewed, package, measuring):
    read(HERE/'prepared-source-selection.json', SOURCE_SELECTION_SHA256)
    blobs = {name: read(HERE/name, pin) for name, pin in SELECTED_INPUT_PINS.items()}
    external = {name: read(WORKSPACE/name, pin) for name, pin in EXTERNAL_FILES.items()}
    prior = json.loads(read(BASE/'manifest.json', PREDECESSOR))
    native_package = BASE/'runtime-src'/'atlas_tectonics'
    frozen = {name: read(BASE/'runtime-src'/name, pin) for name, pin in prior['source_hashes'].items()}
    _require({p.relative_to(BASE/'runtime-src').as_posix() for p in native_package.rglob('*.py')} == set(frozen),
             'predecessor package membership changed')
    stages, origins = _Stages(reviewed, package=package, measuring=measuring), {}
    with authenticated_modules(blobs) as M:
        helpers, ram, report = _compose_heat(M, prior, blobs, external, stages, origins)
        guard_files, guard_sha = _compose_guard(M, prior, external, stages, origins)
        native = _compose_native(M, frozen, blobs, report, stages, staging)
        off_route = frozenset(M.private_heat_bundle.EXTERNAL_IMPORTS['off_route'])
        reference_pins = {HISTORICAL_RELATIVE+'/'+k: v for k, v in M.private_heat_bundle.REFERENCE_PINS.items()}
    # The F delta last; nothing above touched its three files.
    native = filtered_sources(native, prior)
    for name in sorted(FILTER_DELTA):
        stages.record(name, 'filtered_exact_delta', digest(native[name]))
    for name in native:
        source = ('F' if name in FILTER_DELTA else 'endpoint-companion' if name not in prior['source_hashes'] else 'I')
        origins['runtime-src/'+name] = dict(kind='native', source=source, chain=stages.chains.get(name, []))
    for name, raw in guard_files.items():
        _require(name not in helpers and name not in ram, 'guard set collides with a composed helper: '+name)
        helpers[name] = raw
    for name, relative in COPIED_HELPERS.items():
        if name in helpers:
            _require(helpers[name] == blobs[relative], 'helper supplied twice with different bytes: '+name)
            continue
        helpers[name] = blobs[relative]
        origins['helpers/'+name] = dict(kind='verbatim-copy', source=workspace_relative(HERE/relative),
                                        source_sha256=digest(blobs[relative]))
    _require(not set(HISTORICAL_VALIDATORS) & (set(helpers) | set(ram)),
             'historical metadata validators must not be shipped as helpers')
    _require(not set(helpers) & set(ram), 'duplicate helper/ram basename')
    _require(not (set(helpers) | set(ram)) & {p.name for p in HISTORICAL_TESTS.glob('*.py')},
             'a composed helper shadows a historical test module')
    _require('atlas_tectonics.py' not in helpers and 'atlas_tectonics.py' not in ram, 'helper shadows the package')
    # Historical tests (importable, pinned) and data-only references.
    references = _references(report)
    _require(references == reference_pins, 'preserved references differ from the bundle record')
    data_only = {name: pin for name, pin in references.items() if name not in IMPORTED_REFERENCES}
    data_only.update({name: pin for name, pin in prior['files'].items()
                      if name.startswith(HISTORICAL_RELATIVE+'/source/tectonics/cases/')})
    tests = {name: pin for name, pin in prior['files'].items()
             if name.startswith(HISTORICAL_TESTS_RELATIVE+'/') and name.endswith('.py') and name not in data_only}
    for name in IMPORTED_REFERENCES:
        _require(tests.get(name) == references[name], 'imported reference is not the I-pinned test module: '+name)
    for name, pin in (*tests.items(), *data_only.items()):
        read(WORKSPACE/name, pin)
    _require(PREPARATION in tests, 'prepared fixture missing from the historical tests')
    admission = helpers['historical_admission.py'].decode('utf8')
    validators = {}
    for name, pin in HISTORICAL_VALIDATORS.items():
        relative = HISTORICAL_RELATIVE+'/'+name
        _require(prior['files'].get(relative) == pin and admission.count("'"+pin+"'") == 1,
                 'historical validator pin differs: '+name)
        validators[relative] = digest(read(WORKSPACE/relative, pin))
    for constant, name in (('GUARD_PIN', 'private_heat_continuation_guard_r3.py'),
                           ('JOB_PIN', 'windows_workload_job.py'),
                           ('DIAGNOSTICS_PIN', 'private_heat_resource_diagnostics_r1.py')):
        _require(literal(admission, constant) == digest(helpers[name]),
                 'historical_admission '+constant+' is not the composed '+name)
    # runtime.py: workspace depth for <R>/<target> and the M13 import roots.
    runtime = read(BASE/'runtime.py', prior['files'][workspace_relative(BASE/'runtime.py')])
    stages.record('runtime.py', 'input', digest(runtime))
    for old, new in (RUNTIME_WORKSPACE, RUNTIME_ROOTS):
        _require(runtime.count(old) == 1, 'unexpected runtime layout')
        runtime = runtime.replace(old, new, 1)
    stages.record('runtime.py', 'workspace-depth-and-import-roots', digest(runtime))
    origins['runtime.py'] = dict(kind='transformed', source=workspace_relative(BASE/'runtime.py'),
                                 source_sha256=stages.chains['runtime.py'][0][1], transformer='assemble_resumable.py')
    required = tuple(literal(helpers['run_prepared_restart.py'].decode('utf8'), 'REQUIRED_MODULES'))
    test_files = {Path(name).name: (WORKSPACE/name).read_bytes() for name in tests}
    review = dict(historical_imports_outside_files=_import_review(native, helpers, ram, test_files, off_route))
    reachable = _route_reachable(native, helpers, ram, test_files)
    review['required_modules_not_statically_reached'] = sorted(n for n in required if n not in reachable)
    review['shipped_modules_not_statically_reached'] = sorted(
        Path(n).stem for n in (*helpers, *ram) if Path(n).stem not in reachable)
    for name, raw in {**native, **helpers, **ram, 'runtime.py': runtime}.items():
        compile(raw, name, 'exec', dont_inherit=True)
    outputs = {'runtime-src/'+n: digest(r) for n, r in native.items()}
    outputs.update({'helpers/'+n: digest(r) for n, r in helpers.items()})
    outputs.update({'ram/'+n: digest(r) for n, r in ram.items()})
    outputs['runtime.py'] = digest(runtime)
    stages.record('composition', 'outputs', sha256(canonical(outputs)).hexdigest())
    if reviewed is not None:
        _require(set(reviewed) == set(stages.flat), 'reviewed stage digests name different composition steps')
    return Composition(native=native, helpers=helpers, ram=ram, runtime_py=runtime, heat_report=report,
        guard_sha256=guard_sha, stage_digests=dict(stages.flat), chains=stages.chains, origins=origins,
        required_modules=required, historical_tests=tests, data_only=data_only,
        historical_validators=validators, import_review=review, stages_verified=reviewed is not None and not measuring,
        package_stage_drift=stages.package_drift)


def _module_path(composition, target_relative, name):
    if name+'.py' in composition.helpers:
        return target_relative+'/helpers/'+name+'.py'
    if name+'.py' in composition.ram:
        return target_relative+'/ram/'+name+'.py'
    path = HISTORICAL_TESTS_RELATIVE+'/'+name+'.py'
    _require(path in composition.historical_tests, 'required module is not a shipped runtime helper: '+name)
    return path


def build_manifest(composition, target, document_sha256):
    """Explicit allow-list manifest; files workspace-relative, source_hashes native-root-relative."""
    _require(composition.stages_verified and not composition.package_stage_drift,
             'measurement-only or unreconciled composition cannot be written')
    target = Path(target).resolve()
    relative = workspace_relative(target)
    _require(target.parents[4] == WORKSPACE, 'composed runtime.py WORKSPACE would not resolve to the workspace')
    files = {relative+'/runtime-src/'+name: digest(raw) for name, raw in composition.native.items()}
    files.update({relative+'/helpers/'+name: digest(raw) for name, raw in composition.helpers.items()})
    files.update({relative+'/ram/'+name: digest(raw) for name, raw in composition.ram.items()})
    files[relative+'/runtime.py'] = digest(composition.runtime_py)
    files.update(composition.historical_tests)
    files.update(composition.historical_validators)
    data_only = dict(composition.data_only)
    _require(not set(files) & set(data_only), 'data-only references overlap importable sources')
    composed_names = set(composition.helpers) | set(composition.ram)
    for name in files:
        _require(name.startswith(relative+'/') or name.startswith(HISTORICAL_TESTS_RELATIVE+'/') or
                 name in composition.historical_validators, 'file outside the composed allow-list: '+name)
        _require(not (name.startswith(HISTORICAL_RELATIVE+'/') and Path(name).name in composed_names),
                 'historical original of a composed helper pinned: '+name)
        _require('/atlas_tectonics/' not in name or name.startswith(relative+'/runtime-src/atlas_tectonics/'),
                 'native module outside the composed native root: '+name)
    references = _references(composition.heat_report)
    for name, pin in references.items():
        _require((files.get(name) or data_only.get(name)) == pin, 'preserved reference not exactly bound: '+name)
    modules = {name: _module_path(composition, relative, name) for name in composition.required_modules}
    for path in (*modules.values(), relative+'/helpers/'+DRIVER_MODULE+'.py', relative+'/helpers/run_prepared_restart.py',
                 relative+'/helpers/reopen_prepared_restart.py', PREPARATION):
        _require(path in files, 'restart route file not pinned: '+path)
    hashes = {name: digest(raw) for name, raw in sorted(composition.native.items())}
    report = json.loads(json.dumps(composition.heat_report))
    report['preserved_accounting_references'] = references
    return dict(schema=MANIFEST_SCHEMA, completed_query_store=COMPLETED_QUERY_STORE,
        status='SOURCE_COMPOSED_PENDING_REVIEW_AND_AUTHENTICATED_MIGRATION',
        source_hashes=hashes, files=dict(sorted(files.items())), data_only=dict(sorted(data_only.items())),
        native_source_digest=sha256(canonical(hashes)).hexdigest(),
        reviewed_inputs_sha256=_pin(document_sha256), predecessor_manifest_sha256=PREDECESSOR,
        prepared_route=ROUTE, source_selection_sha256=SOURCE_SELECTION_SHA256,
        filtered_manifest_sha256=FILTERED_MANIFEST, composer_sha256=digest(Path(__file__).read_bytes()),
        layout=dict(native_root=relative+'/runtime-src',
                    import_roots=[relative+'/helpers', relative+'/ram', HISTORICAL_TESTS_RELATIVE]),
        required_modules=modules, advance_driver=relative+'/helpers/'+DRIVER_MODULE+'.py',
        restart_runner=relative+'/helpers/run_prepared_restart.py', preparation=PREPARATION,
        stage_digests=composition.stage_digests, origins=composition.origins,
        successor_guard_sha256=composition.guard_sha256, heat_composition=report,
        import_review=composition.import_review,
        guard_limits=json.loads(read(BASE/'manifest.json', PREDECESSOR))['guard_limits'],
        scientific_acceptance=False, production_acceptance=False, checkpoint_migrated=False,
        full_run_launched=False, historical_runtime_modified=False,
        capabilities=['completed endpoint query restart (one strict check per query)',
                      'explicit native, spatial, geometry, funding and continuation transfer',
                      'compact partition, mesh and spatial persistence with migrated-root publication',
                      'compact partition routing, pressure and private-heat consumers',
                      'certified filtered exact predicates', 'passive resource diagnostics in the successor guard'],
        limitations=['no historical admission, compatibility admission or migration is granted by this manifest',
                     'no unfinished adaptive-query frontier restart', 'no arbitrary cross-version proof reuse',
                     'production RAM, time and storage of the compact route are unmeasured'])


def write_composition(composition, target, document_sha256):
    """Exclusive write of a NEW composed tree; returns the manifest sha256."""
    target = Path(target)
    if target.exists():
        raise FileExistsError('preserve frozen successor; use a new explicit revision')
    manifest = build_manifest(composition, target.parent.resolve()/target.name, document_sha256)
    outputs = {'runtime-src/'+n: r for n, r in composition.native.items()}
    outputs.update({'helpers/'+n: r for n, r in composition.helpers.items()})
    outputs.update({'ram/'+n: r for n, r in composition.ram.items()})
    outputs['runtime.py'] = composition.runtime_py
    target.mkdir(parents=False)
    for name, raw in outputs.items():
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    encoded = (json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode('utf8')
    with (target/'manifest.json').open('xb') as stream:
        stream.write(encoded)
    for name, raw in outputs.items():
        _require((target/name).read_bytes() == raw, 'written composed file differs: '+name)
    return sha256(encoded).hexdigest()


# ------------------------------------------------------------------ review records
POLICY_SCHEMA = 'atlas.reviewed-runtime-state-transfer.v1'
PROFILE_SCHEMA = 'atlas.prepared-restart-launch.v2'
PROFILE_NAME = 'restart-profile-s2-r1.json'
HISTORICAL_EXECUTION = '6aa7a30cbe577a80d0a4f93d23b22a09525bb509e1e3f8f0f57e6fe09bc9ccad'
HISTORICAL_NATIVE_DIGEST = '746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28'
HISTORICAL_SOURCE_MANIFEST = ('heat-repair-20261007/continuation-preparation-r3.json',
                              'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c')
HISTORICAL_RECEIPT = ('heat-original-connected-20261013-r9.json',
                      'ca35700a8106d46eb67c876cd15fb5bf86d6abee7480cc94a23acbef68bb4f0d')
QUERY_LIMITS = {'max_entries': 2_000_000, 'max_store_bytes': 8 << 30}
RETAINED_AUXILIARY_PINS = {
    'I-preflight': '26f83272c12856118d054ddd7f67f45e2565b7f86814ba30db096dfd0f5ef67f',
    'filtered-review': '41b91f6cac765fbd4a072b7ec411f028213725960a2582fc97948b21372d48bb',
    'w2k-suite': '5cf0f943bf8e06b6e41c9c543c30ec5c5420f3a15ce44a5e1fcbabe2416e382d',
}
LAUNCH_ENVIRONMENT = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                      'PYTHONHASHSEED': '0'}
RECEIPTS = ('q1', 'q2', 'w1a', 'w1b', 'w1c', 'w1d', 'w1f', 'w1g', 'w2b', 'w2e', 'w2k', 'wave1-retest',
            'wave2-retest')
RETAINED_RECEIPT_PINS = {
    "q1": "639cd6c24cf4b0aebe052dc874b4b638b735c869d0ade264fe2131d126ea575d",
    "q2": "d07c36c86c05186d87df8aeeb1be40b94196b41e3ce8a5da142d23d1ca410e88",
    "w1a": "f2cd0859b69ffbcbd658e8893074e51a766d98cdd344ac62190ad2b3026d8c05",
    "w1b": "ea333871b86bb98a69f551c017d214723b6ebd06c63c9a57e8182a57eedd58a0",
    "w1c": "60b74fc263d3423905dbfb835de469e6addf7f0471182e15dfa7d74b33b6935c",
    "w1d": "9b2cf612029488c11354ebeb1d3dde221087c58414001d213f5689deadb89d73",
    "w1f": "5ddb727d931273bb19cf73666fabb42d369cd95f5229851df172c0e8cf1af820",
    "w1g": "ee8c76ae2dbf84c3d7545d4fe89ac33f30e5e621d39a0d6771edbb0c07a86b91",
    "w2b": "2f2c365d15ae914f2577aa8dc1486a40dda0671e944ec15aa2c36013d4bb59cc",
    "w2e": "7f898ae27cec288308f56268396adcc475f27ee10ce9a2327fbd789cdada22fd",
    "w2k": "faaf693329df47f2854237fad9c4a41da15c17fb6f27303078412e2d7c3e177e",
    "wave1-retest": "f944887f3082fc172dd3b66dd6aac518d3cd312554d1d72dda984f8330553d11",
    "wave2-retest": "90b991f3a709461ce34c5e9f077a4c7a4b5c25d0061c98389c5f8fa44783a59b"
}



def _evidence_relative(path, evidence_root):
    return Path(path).resolve().relative_to((WORKSPACE/evidence_root).resolve()).as_posix()


def _write_exclusive(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True)+'\n').encode('utf8')
    with Path(path).open('xb') as stream:
        stream.write(raw)
    return raw


def native_inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted((root/'atlas_tectonics').rglob('*.py'))}


def validate_review_record(record, manifest, manifest_sha256, historical):
    """Check explicit attribution/coverage; hashing evidence does not create human review authority."""
    fields = {'schema', 'status', 'route', 'subject', 'reviews', 'native_reasons'}
    subject = dict(source_manifest_sha256=manifest_sha256,
        reviewed_inputs_sha256=manifest['reviewed_inputs_sha256'], composer_sha256=manifest['composer_sha256'],
        source_selection_sha256=SOURCE_SELECTION_SHA256)
    _require(type(record) is dict and set(record) == fields and
             record['schema'] == 'atlas.private.prepared-delta-review.v1' and
             record['status'] == 'ACCEPTED_FOR_PREPARED_C2' and record['route'] == ROUTE and
             record['subject'] == subject, 'actual review must bind the complete prepared package')
    reviews = record['reviews']
    _require(type(reviews) is list and len(reviews) == 2, 'two actual complete-package reviews required')
    names = []
    for row in reviews:
        _require(type(row) is dict and set(row) == {'reviewer', 'role', 'scope', 'disposition', 'evidence'} and
                 row['scope'] == 'complete-prepared-package' and row['disposition'] == 'ACCEPT' and
                 all(type(row[k]) is str and bool(row[k].strip()) for k in ('reviewer', 'role')),
                 'review attribution, scope and explicit acceptance required')
        names.append(row['reviewer'].strip().casefold())
        ev = row['evidence']
        _require(type(ev) is dict and set(ev) == {'path', 'sha256'}, 'pinned review evidence required')
        _pin(ev['sha256'])
    _require(len(set(names)) == 2, 'distinct named participants must supply the two reviews')
    current = manifest['source_hashes']
    delta = {name for name in set(historical) | set(current) if historical.get(name) != current.get(name)}
    reasons = record['native_reasons']
    _require(type(reasons) is dict and set(reasons) == delta, 'actual reasons must cover the exact native delta')
    for name, row in reasons.items():
        _require(type(row) is dict and set(row) == {'before', 'after', 'reason'} and
                 row['before'] == historical.get(name) and row['after'] == current.get(name) and
                 type(row['reason']) is str and bool(row['reason'].strip()),
                 'native delta reason does not bind the actual bytes: '+name)
    return [row['reviewer']+': '+row['role'] for row in reviews]


def _ordinary(path, *, directory=False):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        _require(not stat.S_ISLNK(info.st_mode) and
                 not getattr(info, 'st_file_attributes', 0) & 0x400, 'linked/reparsed path refused')
    _require(path.is_dir() if directory else path.is_file(), 'ordinary file/directory required')
    return path.resolve()


def _contained(workspace, value, *, directory=False):
    _require(type(value) is str and value and '\\' not in value and ':' not in value and
             not Path(value).is_absolute() and '..' not in Path(value).parts,
             'explicit contained workspace-relative path required')
    root = _ordinary(workspace, directory=True)
    path = _ordinary(root/value, directory=directory)
    _require(path.is_relative_to(root), 'path outside the reviewed workspace')
    return path


def _historical_root(workspace, value, source_root):
    _require(value == HISTORICAL_RELATIVE, 'explicit reviewed historical root required')
    root = _contained(workspace, value, directory=True)
    _require(source_root == value+'/native-composed-r7/tectonics/src' and
             _contained(workspace, source_root, directory=True) == root/'native-composed-r7/tectonics/src',
             'historical source root must belong to the explicit reviewed tree')
    return root


def _query_store(manifest):
    _require(type(manifest) is dict and type(manifest.get('completed_query_store')) is str and
             manifest['completed_query_store'] == COMPLETED_QUERY_STORE,
             'selected completed_query_store must explicitly declare files')
    return manifest['completed_query_store']


def refuse_rehearsal(*documents):
    """Plan31 generation-document rule: literal purpose presence and casefolded markers."""
    pending = list(documents)
    while pending:
        value = pending.pop()
        if type(value) is dict:
            _require('purpose' not in value, 'generation document contains a purpose key')
            _require(not any(type(key) is str and key.casefold().startswith('plan31:rehearsal-')
                             for key in value), 'generation document contains a rehearsal key')
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
        elif type(value) is str:
            _require(not value.casefold().startswith('plan31:rehearsal-'),
                     'generation document contains a rehearsal value')


def admissible_construction(receipt, derivation, composition):
    """Source preparation is admissible only under the selected replay contract."""
    _require(all(type(row) is dict and row.get('status') == 'PREPARED_SOURCE_NOT_QUALIFIED'
                 for row in (receipt, derivation)), 'receipt and derivation must be prepared')
    _require(type(composition) is dict and type(composition.get('stages')) is list and
             type(composition.get('staged')) is dict and
             all(type(row) is dict and type(row.get('stage')) is str for row in composition['stages']) and
             all(type(row) is dict or (name == 'root' and type(row) is str and
                 bool(row) and Path(row).is_absolute()) for name, row in composition['staged'].items()),
             'prepared composition stage records required')
    refuse_rehearsal(receipt, derivation, composition)


def _reference_path(workspace, value, *, external=False):
    """Resolve a supplied path, allowing the producer's absolute ordinary references."""
    _require(type(value) is str and bool(value), 'explicit selected record path required')
    try:
        path = _ordinary(value) if Path(value).is_absolute() else _contained(workspace, value)
    except OSError as exc:
        raise CompositionRefused('selected record is unavailable: '+value) from exc
    _require(external or path.is_relative_to(workspace), 'runtime record is outside the profile workspace')
    return path


def _bound_record(workspace, binding, *, external=False):
    """Authenticate an explicit ordinary reference; runtime records stay inside T."""
    _require(type(binding) is dict and set(binding) == {'path', 'sha256'}, 'exact selected record binding required')
    _pin(binding['sha256'])
    path = _reference_path(workspace, binding['path'], external=external)
    return path, read(path, binding['sha256'])


def _same_reference(workspace, left, right, *, external=False):
    for row in (left, right):
        _require(type(row) is dict and set(row) == {'path', 'sha256'}, 'exact selected reference required')
        _pin(row['sha256'])
    return left['sha256'] == right['sha256'] and (
        _reference_path(workspace, left['path'], external=external) ==
        _reference_path(workspace, right['path'], external=external))


def _paired_profiles(workspace, config, records, manifest, receipt, derivation):
    """Keep the fresh-v1 primary profile and explicitly bind its prepared-v2 companion."""
    fresh, prepared = records['constructor_profile'], records['prepared_profile']
    fields = {'schema', 'workspace', 'source_manifest', 'native_root', 'import_roots', 'modules',
              'advance_driver', 'output_directory', 'store_directory', 'completed_query_directory',
              'completed_query_limits'}
    _require(type(fresh) is dict and set(fresh) == fields and
             fresh['schema'] == 'atlas.fresh-interval-profile.v1', 'closed primary fresh-v1 profile required')
    refuse_rehearsal(fresh)
    for row in (receipt, derivation):
        _require(_same_reference(workspace, row.get('prepared_profile'), config['prepared_profile']) and
                 row.get('completed_query_store') == COMPLETED_QUERY_STORE,
                 'both construction records must bind the actual prepared companion and files store')
    for field in ('workspace', 'native_root', 'import_roots'):
        _require(fresh[field] == prepared[field], 'fresh/prepared shared binding differs: '+field)
    _require(_same_reference(workspace, fresh['source_manifest'], prepared['source_manifest']),
             'fresh/prepared source manifest differs')
    _contained(workspace, fresh['source_manifest']['path'])
    files = manifest['files']
    for key, row, module_field in (('fresh_runner', fresh, 'FRESH_MODULES'),
                                   ('prepared_runner', prepared, 'REQUIRED_MODULES')):
        binding = config[key]
        path, raw = _bound_record(workspace, binding)
        relative = path.relative_to(workspace).as_posix()
        _require(files.get(relative) == binding['sha256'], 'paired runner is outside the source manifest')
        text = raw.decode('utf8')
        _require(literal(text, 'PROFILE_SCHEMA') == row['schema'] and type(row['modules']) is dict and
                 set(row['modules']) == set(literal(text, module_field)),
                 'paired profile must bind its complete selected runner module map')
        if key == 'fresh_runner':
            _require(literal(text, 'DRIVER') == 'fresh_interval_driver', 'selected fresh driver contract differs')
            fresh_modes = literal(text, 'MODES')
        for name in row['modules'].values():
            _require(type(name) is str and name in files, 'paired module is outside the shared source manifest')
    for name in fresh['modules'].keys() & prepared['modules'].keys():
        _require(fresh['modules'][name] == prepared['modules'][name],
                 'fresh/prepared shared module differs: '+name)
    driver = fresh['advance_driver']
    _require(type(driver) is dict and set(driver) == {'module', 'path', 'sha256'} and
             driver['module'] == 'fresh_interval_driver' and files.get(driver['path']) == _pin(driver['sha256']) and
             prepared['advance_driver']['module'] == DRIVER_MODULE and
             fresh['modules'].get(DRIVER_MODULE) == prepared['advance_driver']['path'],
             'explicit fresh and prepared driver mapping differs')
    output, store = (Path(fresh[key]) for key in ('output_directory', 'store_directory'))
    _require(all(type(fresh[key]) is str and path.is_absolute() and str(path) == fresh[key] == str(path.resolve()) and
                 path.is_relative_to(workspace) for key, path in
                 (('output_directory', output), ('store_directory', store))) and
             not output.is_relative_to(store) and not any(store.is_relative_to(output/('run-'+mode))
                                                        for mode in fresh_modes),
             'canonical contained fresh destinations required')
    query = fresh['completed_query_directory']
    _require(type(query) is str and query and '\\' not in query and ':' not in query and
             not Path(query).is_absolute() and '..' not in Path(query).parts and
             (workspace/query).resolve().is_relative_to(workspace) and
             not (workspace/query).is_relative_to(output),
             'contained fresh query destination outside its attempt required')
    _ordinary((workspace/query).parent, directory=True)
    quota = fresh['completed_query_limits']
    _require(type(quota) is dict and set(quota) == set(QUERY_LIMITS) and
             all(type(value) is int and value > 0 for value in quota.values()),
             'explicit positive fresh query limits required')


def build_restart_profile(*, workspace, source_manifest, native_root, import_roots, modules,
                          preparation, compatibility_policy, compatibility_policy_raw, evidence_root, historical_root,
                          historical_source_root, advance_driver, output_directory, store_limits,
                          compression, completed_query_directory, completed_query_limits):
    """Build the same explicit v2 record for legacy construction and a selected receiver.

    This is metadata construction, not review, qualification, historical admission
    or execution authority. The owning constructor supplies exact selected bindings.
    No source root is discovered and no output is created here.
    """
    workspace = _ordinary(workspace, directory=True)
    _historical_root(workspace, historical_root, historical_source_root)
    _require(type(source_manifest) is dict and set(source_manifest) == {'path', 'sha256'},
             'explicit source manifest binding required')
    manifest = json.loads(read(_contained(workspace, source_manifest['path']), source_manifest['sha256']))
    _query_store(manifest)
    files = manifest.get('files')
    _require(type(files) is dict and bool(files) and type(manifest.get('source_hashes')) is dict and
             bool(manifest['source_hashes']) and type(manifest.get('data_only')) is dict and
             not files.keys() & manifest['data_only'].keys(), 'complete disjoint source/data manifest required')
    native_path = _contained(workspace, native_root, directory=True)
    for name, pin in (*files.items(), *manifest['data_only'].items()):
        read(_contained(workspace, name), pin)
    actual_native = native_inventory(native_path)
    _require(actual_native == manifest['source_hashes'] and all(
        files.get(native_root+'/'+name) == pin for name, pin in actual_native.items()),
        'complete native inventory differs from the selected source manifest')
    _require(type(import_roots) is list and bool(import_roots), 'explicit import roots required')
    for root in import_roots:
        _contained(workspace, root, directory=True)
    _require(type(modules) is dict and bool(modules), 'explicit module bindings required')
    for binding in (preparation, compatibility_policy):
        _require(type(binding) is dict and set(binding) == {'path', 'sha256'}, 'explicit pinned path required')
        _pin(binding['sha256'])
    read(_contained(workspace, preparation['path']), preparation['sha256'])
    _require(type(compatibility_policy_raw) is bytes and digest(compatibility_policy_raw) ==
             compatibility_policy['sha256'], 'compatibility policy bytes differ from the profile pin')
    policy_path = compatibility_policy['path']
    _require(type(policy_path) is str and policy_path and '\\' not in policy_path and ':' not in policy_path and
             not Path(policy_path).is_absolute() and '..' not in Path(policy_path).parts and
             (workspace/policy_path).resolve().is_relative_to(workspace), 'contained compatibility policy required')
    _contained(workspace, evidence_root, directory=True)
    _require(type(advance_driver) is dict and set(advance_driver) == {'module', 'path', 'sha256'},
             'explicit driver binding required')
    for path in (*modules.values(), preparation['path'], advance_driver['path']):
        _require(path in files, 'profile member is not in the source manifest: '+str(path))
        read(_contained(workspace, path), files[path])
    _require(files[preparation['path']] == preparation['sha256'] and
             files[advance_driver['path']] == advance_driver['sha256'], 'profile source pins differ from manifest')
    output = str(output_directory)
    _require(Path(output).is_absolute() and output == str(Path(output)) == str(Path(output).resolve()) and
             Path(output).is_relative_to(workspace) and not Path(output).exists(),
             'fresh canonical output inside the reviewed workspace required')
    _require(type(completed_query_directory) is str and completed_query_directory and
             '\\' not in completed_query_directory and ':' not in completed_query_directory and
             not Path(completed_query_directory).is_absolute() and '..' not in Path(completed_query_directory).parts and
             (workspace/completed_query_directory).resolve().is_relative_to(workspace) and
             not (workspace/completed_query_directory).resolve().is_relative_to(Path(output)),
             'contained completed-query directory outside the attempt output required')
    _require(type(completed_query_limits) is dict and set(completed_query_limits) == set(QUERY_LIMITS) and
             all(type(v) is int and v > 0 for v in completed_query_limits.values()),
             'explicit positive completed-query limits required')
    _require(type(store_limits) is dict and type(compression) is dict, 'explicit native store settings required')
    return dict(schema=PROFILE_SCHEMA, workspace=str(workspace), source_manifest=dict(source_manifest),
        native_root=native_root, import_roots=list(import_roots), modules=dict(modules),
        preparation=dict(preparation), compatibility_policy=dict(compatibility_policy), evidence_root=evidence_root,
        historical_root=historical_root, historical_source_root=historical_source_root,
        advance_driver=dict(advance_driver), output_directory=output, store_limits=dict(store_limits),
        compression=dict(compression), completed_query_directory=completed_query_directory,
        completed_query_limits=dict(completed_query_limits))


def selected_restart_profile(config):
    """Consume an exact prepared-construction receipt, derivation and composition.

    The shared constructor owns these records and the destination. This consumer
    never composes or changes its sources, and refuses rehearsal before any write.
    """
    fields = {'schema', 'construction_receipt', 'derivation', 'composition',
              'constructor_profile', 'profile', 'compatibility_policy'}
    paired_fields = {'prepared_profile', 'fresh_runner', 'prepared_runner'}
    _require(type(config) is dict and set(config) in (fields, fields | paired_fields) and
             config['schema'] == 'atlas.prepared-restart-construction.v2',
             'closed selected prepared-construction v2 input required')
    bindings = dict(config['profile'])
    _require(set(bindings) == {'workspace', 'source_manifest', 'native_root', 'import_roots', 'modules',
             'preparation', 'compatibility_policy', 'evidence_root', 'historical_root', 'historical_source_root',
             'advance_driver', 'output_directory', 'store_limits', 'compression', 'completed_query_directory',
             'completed_query_limits'}, 'complete closed prepared-profile bindings required')
    workspace = _ordinary(bindings['workspace'], directory=True)
    paired = set(config) == fields | paired_fields
    records = {}
    selected = ('construction_receipt', 'derivation', 'composition', 'constructor_profile', 'compatibility_policy')
    for key in (*selected, *(('prepared_profile',) if paired else ())):
        row = config[key]
        _, raw = _bound_record(workspace, row, external=key == 'construction_receipt')
        records[key] = json.loads(raw)
        if key == 'compatibility_policy':
            bindings['compatibility_policy_raw'] = raw
    receipt, derivation, composition = (records[k] for k in ('construction_receipt', 'derivation', 'composition'))
    admissible_construction(receipt, derivation, composition)
    _require(receipt.get('input_finality') is True and receipt.get('output_finality') is True,
             'completed input and output construction finality required')
    for field in ('composition_sha256', 'manifest_sha256', 'profile_sha256', 'reviewed_inputs', 'bootstrap', 'selection'):
        _require(field in receipt and derivation.get(field) == receipt[field], 'construction records disagree: '+field)
    _require(receipt['composition_sha256'] == config['composition']['sha256'] and
             receipt.get('derivation_sha256') == config['derivation']['sha256'] and
             receipt['manifest_sha256'] == bindings['source_manifest']['sha256'] and
             _pin(receipt['profile_sha256']) == config['constructor_profile']['sha256'] and
             _same_reference(workspace, bindings['compatibility_policy'], config['compatibility_policy']),
             'selected construction/profile pins disagree')
    _require(_same_reference(workspace,
             dict(path=composition.get('reviewed_inputs'), sha256=composition.get('reviewed_inputs_sha256')),
             receipt['reviewed_inputs'], external=True),
             'composition does not bind its reviewed inputs')
    for field in ('reviewed_inputs', 'bootstrap', 'selection'):
        _, raw = _bound_record(workspace, receipt[field], external=True)
        if field != 'bootstrap':
            records[field] = json.loads(raw)
    manifest = json.loads(read(_contained(workspace, bindings['source_manifest']['path']),
                               bindings['source_manifest']['sha256']))
    _require(_same_reference(workspace,
             dict(path=manifest.get('composition', {}).get('composition_json'),
                  sha256=manifest.get('composition', {}).get('composition_sha256')), config['composition']) and
             composition.get('completed_query_store') == _query_store(manifest),
             'manifest does not bind the selected construction and store')
    producer_profile = records['prepared_profile' if paired else 'constructor_profile']
    # The final producer emits v2 using build_restart_profile. Historical replay
    # fresh profiles are a different schema; this intake performs no implicit conversion.
    _require(type(producer_profile) is dict and set(producer_profile) == set(config['profile']) | {'schema'} and
             producer_profile['schema'] == PROFILE_SCHEMA and
             {k: v for k, v in producer_profile.items() if k != 'schema'} == config['profile'],
             'supplied restart bindings must equal the actual emitted v2 constructor profile')
    refuse_rehearsal(records['selection'], records['reviewed_inputs'], manifest, producer_profile)
    if paired:
        _paired_profiles(workspace, config, records, manifest, receipt, derivation)
    profile = build_restart_profile(**bindings)
    _require(profile == producer_profile, 'restart profile derivation changed a constructor binding')
    return profile


def write_review(target, manifest_sha256, measurement, *, historical_root, output_directory, completed_query_directory,
                 review_record, review_sha256, evidence_root=EVIDENCE_ROOT, query_limits=QUERY_LIMITS):
    """Write a profile only after measurement and actual pinned complete-package review.

    Retained receipts are historical evidence, never invented review attribution.
    Validate all inputs before creating review/. Output remains exclusive.
    """
    target = Path(target).resolve()
    relative = workspace_relative(target)
    manifest = json.loads(read(target/'manifest.json', manifest_sha256))
    _query_store(manifest)
    _historical_root(WORKSPACE, historical_root, HISTORICAL_NATIVE_RELATIVE)
    _require(manifest.get('prepared_route') == ROUTE and
             manifest.get('source_selection_sha256') == SOURCE_SELECTION_SHA256 and
             manifest['composer_sha256'] == digest(Path(__file__).read_bytes()),
             'manifest is not this selected prepared composer/route')
    document = json.loads(read(HERE/'reviewed-inputs.json', manifest['reviewed_inputs_sha256']))
    _check_document(document, check_stages=True)
    _require(document['stage_digests'] == manifest['stage_digests'] and target == (HERE/document['target']).resolve(),
             'prepared manifest differs from the selected record/target')
    provenance = measurement.get('execution_provenance') if type(measurement) is dict else None
    _require(type(measurement) is dict and measurement.get('schema') == 'atlas.execution-identity-probe.v1' and
             measurement.get('status') == 'MEASURED_NOT_REVIEWED' and measurement.get('backend') == 'scipy' and
             measurement.get('source_manifest_sha256') == manifest_sha256 and
             measurement.get('native_source_digest') == manifest['native_source_digest'] and
             measurement.get('native_root') == manifest['layout']['native_root'] and
             measurement.get('import_roots') == manifest['layout']['import_roots'] and
             measurement.get('launch_environment') == LAUNCH_ENVIRONMENT and
             measurement.get('fresh_process') is True and type(provenance) is dict and
             provenance.get('execution_mode') == 'strict', 'execution identity measurement is not for this manifest')
    identity = _pin(provenance['execution_identity'])
    _require(native_inventory(target/'runtime-src') == manifest['source_hashes'],
             'composed native inventory differs from its manifest')
    for name, pin in {**manifest['files'], **manifest['data_only']}.items():
        read(WORKSPACE/name, pin)
    historical = native_inventory(WORKSPACE/HISTORICAL_NATIVE_RELATIVE)
    _require(sha256(canonical(historical)).hexdigest() == HISTORICAL_NATIVE_DIGEST, 'historical inventory differs')
    acceptance = json.loads(read(review_record, review_sha256))
    reviewed_by = validate_review_record(acceptance, manifest, manifest_sha256, historical)
    review_dir = target/'review'
    _require(not review_dir.exists(), 'preserve existing profile/review directory; choose a new revision')

    def ev(path):
        return _evidence_relative(path, evidence_root)

    def reference(row):
        name = row['path']
        _require(type(name) is str and name and not Path(name).is_absolute() and
                 '\\' not in name and '..' not in Path(name).parts and
                 (WORKSPACE/name).resolve().is_relative_to(WORKSPACE), 'contained review evidence path required')
        path = WORKSPACE/name
        read(path, row['sha256'])
        ev(path)  # requires containment within the actual evidence root
        return path

    paths = {'I': BASE/'manifest.json', 'I-preflight': BASE/'preflight-result.json',
             'filtered': FILTERED/'manifest.json', 'filtered-review': FILTERED/'review.md',
             'w2k-suite': HERE/'endpoint-checkpoints'/'test-results-w2k.json',
             'reviewed-inputs': HERE/'reviewed-inputs.json', 'source-selection': HERE/'prepared-source-selection.json',
             'stage-measurement': HERE/document['stage_measurement']['path'],
             'stage-selection': HERE/document['stage_selection']['path'], 'delta-review': Path(review_record)}
    for index, row in enumerate(acceptance['reviews']):
        paths['review-'+str(index+1)] = reference(row['evidence'])
    for name, pin in RETAINED_AUXILIARY_PINS.items():
        read(paths[name], pin)
    for field in ('stage_measurement', 'stage_selection'):
        read(HERE/document[field]['path'], document[field]['sha256'])
    read(paths['source-selection'], SOURCE_SELECTION_SHA256)
    receipts, owners = {}, {}
    for name in RECEIPTS:
        path = HERE/'test-results'/(name+'.json')
        raw = read(path, RETAINED_RECEIPT_PINS[name])
        receipts[name] = dict(path=workspace_relative(path), sha256=digest(raw), scope='historical-delivery-only')
        paths[name] = path
        for row in json.loads(raw).get('files') or ():
            if type(row) is dict and type(row.get('path')) is str and row['path'].startswith('R/'):
                owners.setdefault(row['path'][2:], []).append(dict(package=name, sha256_after=row.get('sha256_after')))
    r_relative = workspace_relative(HERE)
    entries = {}
    for name, pin in manifest['files'].items():
        if not name.startswith(relative+'/') or name.startswith(relative+'/runtime-src/'):
            continue
        key = name[len(relative)+1:]
        origin = manifest['origins'][key]
        local = [origin['source'][len(r_relative)+1:]] if origin['source'].startswith(r_relative+'/') else []
        local += [origin['transformer']] if 'transformer' in origin else []
        delivered = [dict(file=source, **row) for source in local for row in owners.get(source, [])]
        entries[key] = dict(sha256=pin, **origin, delivering_receipts=delivered, reviewed_by=list(reviewed_by))
    helper_review = dict(schema='atlas.private.composed-helper-review.v1', target=relative,
        source_manifest_sha256=manifest_sha256, reviewed_inputs_sha256=manifest['reviewed_inputs_sha256'],
        native_source_digest=manifest['native_source_digest'], entries=entries,
        required_modules=manifest['required_modules'], import_review=manifest['import_review'],
        historical_validators_executed_from_h=sorted(n for n in manifest['files']
                                                     if Path(n).name in HISTORICAL_VALIDATORS),
        data_only=manifest['data_only'], execution_identity_measurement=measurement, receipts=receipts,
        accepted_delta_review=dict(path=workspace_relative(review_record), sha256=review_sha256),
        review_evidence=acceptance['reviews'], prepared_route=ROUTE,
        notes=['The legacy indexed heat construction is retained; complete compact/S2 construction is not selected.',
               'Historical delivering receipts do not review changed source bytes. The pinned delta review does.',
               'Added verbatim helpers close syntactic imports, including dormant alternatives; no launch is granted.',
               'Helpers are bound by the manifest and source fence, outside the native execution identity.',
               'No production/scientific acceptance, historical admission, migration or interval launch is granted.'],
        production_acceptance=False)
    helper_raw = (json.dumps(helper_review, indent=2, sort_keys=True, allow_nan=False)+'\n').encode('utf8')
    receipt = json.loads(read(HISTORICAL/HISTORICAL_RECEIPT[0], HISTORICAL_RECEIPT[1]))
    _require(receipt['completed_endpoint']['execution_provenance'] ==
             {'execution_identity': HISTORICAL_EXECUTION, 'execution_mode': 'strict'} and
             receipt['native_source_digest'] == HISTORICAL_NATIVE_DIGEST and
             receipt['preparation_manifest_sha256'] == HISTORICAL_SOURCE_MANIFEST[1],
             'historical producer identity differs from the pinned r9 receipt')
    read(WORKSPACE/EVIDENCE_ROOT/HISTORICAL_SOURCE_MANIFEST[0], HISTORICAL_SOURCE_MANIFEST[1])
    keys = {name: ev(path) for name, path in paths.items()}
    evidence = {keys[name]: digest(path.read_bytes()) for name, path in paths.items()}
    keys['helper-review'] = ev(review_dir/'helper-review.json')
    evidence[keys['helper-review']] = digest(helper_raw)
    _require(evidence[keys['I']] == PREDECESSOR and evidence[keys['filtered']] == FILTERED_MANIFEST and
             evidence[keys['reviewed-inputs']] == manifest['reviewed_inputs_sha256'] and
             evidence[keys['delta-review']] == review_sha256, 'review evidence differs from the selected composition')
    changes = {name: dict(row, evidence=[keys[k] for k in
                 ('delta-review', 'review-1', 'review-2', 'reviewed-inputs', 'stage-measurement', 'helper-review')])
               for name, row in acceptance['native_reasons'].items()}
    constraints = literal(read(target/'helpers'/'runtime_compatibility.py',
                               manifest['files'][relative+'/helpers/runtime_compatibility.py']).decode('utf8'),
                          'CONSTRAINTS')
    historical_manifest = (HISTORICAL_SOURCE_MANIFEST[0] if evidence_root == EVIDENCE_ROOT else
                           ev(WORKSPACE/EVIDENCE_ROOT/HISTORICAL_SOURCE_MANIFEST[0]))
    policy = dict(schema=POLICY_SCHEMA, constraints=constraints,
        historical=dict(source_hashes=historical, native_source_digest=HISTORICAL_NATIVE_DIGEST,
                        source_manifest_path=historical_manifest, source_manifest_sha256=HISTORICAL_SOURCE_MANIFEST[1],
                        execution_identity=HISTORICAL_EXECUTION),
        current=dict(source_hashes=manifest['source_hashes'], native_source_digest=manifest['native_source_digest'],
                     source_manifest_path=ev(target/'manifest.json'), source_manifest_sha256=manifest_sha256,
                     execution_identity=identity), reviewed_changes=changes, evidence=dict(sorted(evidence.items())))
    policy_raw = (json.dumps(policy, indent=2, sort_keys=True, allow_nan=False)+'\n').encode('utf8')
    completed = receipt['completed_endpoint']
    output = str(output_directory)
    _require(Path(output).is_absolute() and str(Path(output)) == output == str(Path(output).resolve()) and
             not Path(output).exists() and Path(output).resolve().is_relative_to(WORKSPACE),
             'fresh canonical absolute output directory inside the workspace required')
    _require(type(completed_query_directory) is str and bool(completed_query_directory) and
             not Path(completed_query_directory).is_absolute() and '\\' not in completed_query_directory and
             '..' not in Path(completed_query_directory).parts and
             (WORKSPACE/completed_query_directory).resolve().is_relative_to(WORKSPACE) and
             not (WORKSPACE/completed_query_directory).resolve().is_relative_to(Path(output)),
             'contained completed-query directory outside the attempt output required')
    _require(query_limits == QUERY_LIMITS, 'retain the selected completed-query limits')
    profile = build_restart_profile(workspace=WORKSPACE,
        source_manifest=dict(path=relative+'/manifest.json', sha256=manifest_sha256),
        native_root=manifest['layout']['native_root'], import_roots=manifest['layout']['import_roots'],
        modules=manifest['required_modules'], preparation=dict(path=PREPARATION, sha256=manifest['files'][PREPARATION]),
        compatibility_policy=dict(path=relative+'/review/runtime-compatibility-policy.json', sha256=digest(policy_raw)),
        compatibility_policy_raw=policy_raw,
        evidence_root=evidence_root, historical_root=historical_root,
        historical_source_root=HISTORICAL_NATIVE_RELATIVE,
        advance_driver=dict(module=DRIVER_MODULE, path=manifest['advance_driver'],
                            sha256=manifest['files'][manifest['advance_driver']]),
        output_directory=output, store_limits=completed['store_limits'], compression=completed['store_compression'],
        completed_query_directory=completed_query_directory, completed_query_limits=dict(query_limits))
    # Validation above is read-only. Preserve any failure after mkdir; never retry/delete in place.
    review_dir.mkdir(exist_ok=False)
    _require(_write_exclusive(review_dir/'helper-review.json', helper_review) == helper_raw, 'helper encoding changed')
    _require(_write_exclusive(review_dir/'runtime-compatibility-policy.json', policy) == policy_raw, 'policy encoding changed')
    profile_raw = _write_exclusive(review_dir/PROFILE_NAME, profile)
    return {'helper-review.json': digest(helper_raw), 'runtime-compatibility-policy.json': digest(policy_raw),
            PROFILE_NAME: digest(profile_raw)}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--reviewed-inputs-sha256')
    mode.add_argument('--measure-stages', action='store_true')
    mode.add_argument('--selected-restart', type=Path)
    parser.add_argument('--selected-restart-sha256')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    if args.selected_restart is not None:
        _require(args.selected_restart_sha256 is not None and args.out is not None and not args.out.exists(),
                 'pinned selected input and exclusive profile output required')
        config = json.loads(read(args.selected_restart, args.selected_restart_sha256))
        profile = selected_restart_profile(config)
        parent = _ordinary(args.out.parent, directory=True)
        _require(parent == (Path(profile['workspace'])/profile['source_manifest']['path']).parent and
                 not args.out.is_symlink(), 'profile must be written beside its selected runtime manifest')
        _, raw = _bound_record(Path(profile['workspace']),
                               config['prepared_profile' if 'prepared_profile' in config else 'constructor_profile'])
        _require(json.loads(raw) == profile, 'constructor profile changed before exclusive output')
        with args.out.open('xb') as stream:
            stream.write(raw)
        print(json.dumps(dict(status='PREPARED_RESTART_PROFILE_WRITTEN_NO_RUN_AUTHORITY',
                              path=str(args.out), sha256=digest(raw))))
        return 0
    _require(args.selected_restart_sha256 is None, '--selected-restart-sha256 requires --selected-restart')
    if args.measure_stages:
        _require(args.out is not None and not args.out.exists(), 'exclusive measurement output required')
        raw = _write_exclusive(args.out, measure_stages())
        print(json.dumps(dict(status='MEASURED_NOT_SELECTED', path=str(args.out), sha256=digest(raw))))
        return 0
    _require(args.out is None, '--out is only for non-building stage measurement')
    document = json.loads(read(HERE/'reviewed-inputs.json', args.reviewed_inputs_sha256))
    _check_document(document, check_stages=True)
    target = HERE/document['target']
    if target.exists():
        raise FileExistsError('preserve frozen successor; use a new explicit revision')
    composition = construct(document)
    manifest_sha256 = write_composition(composition, target, args.reviewed_inputs_sha256)
    manifest = json.loads((target/'manifest.json').read_bytes())
    print(json.dumps(dict(status=manifest['status'], target=workspace_relative(target),
        sources=len(manifest['source_hashes']), native_source_digest=manifest['native_source_digest'],
        manifest_sha256=manifest_sha256, composition=composition.stage_digests['composition@outputs'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
