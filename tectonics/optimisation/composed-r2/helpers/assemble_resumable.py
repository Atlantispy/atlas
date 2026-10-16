"""Compose the reviewed resumable successor from authenticated bytes (inputs v2).

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
DOCUMENT_SCHEMA = 'atlas.private.resumable-reviewed-inputs.v2'
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
        '4a835dc34f840fd12298a676ddae209966b378257e2693b04f7f681e65a7e451',
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
              'stage_digests', 'target', 'layout', 'authority', 'accuracy'}
    _require(type(document) is dict and set(document) == fields and document['schema'] == DOCUMENT_SCHEMA,
             'closed reviewed-inputs v2 document required')
    _require(document['predecessor_manifest_sha256'] == PREDECESSOR and
             document['filtered_manifest_sha256'] == FILTERED_MANIFEST, 'frozen I/F manifest pins differ')
    files = document['files']
    _require(type(files) is dict and set(files) == set(REVIEWED_FILES),
             'reviewed files must name exactly the composer inputs')
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


class _Stages:
    """Ordered per-file chains; delivered and reviewed digests are asserted on record."""

    def __init__(self, reviewed):
        self.chains, self.flat, self._reviewed = {}, {}, reviewed

    def record(self, path, label, value):
        key = path+'@'+label
        _require(key not in self.flat, 'duplicate composition stage: '+key)
        value = _pin(value)
        expected = PACKAGE_DIGESTS.get(key)
        _require(expected is None or expected == value, 'stage digest differs from the delivered package: '+key)
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
    helpers_out, ram_out, report = B.construct_successor(inputs, reference_root=HISTORICAL,
        reference_pins=B.REFERENCE_PINS, external=coverage, ram=ram, helpers=copies)
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
    _check_document(document, check_stages=check_stages)
    reviewed = document['stage_digests'] if check_stages else None
    blobs = {name: read(HERE/name, pin) for name, pin in document['files'].items()}
    external = {name: read(WORKSPACE/name, pin) for name, pin in document['external_files'].items()}
    prior = json.loads(read(BASE/'manifest.json', PREDECESSOR))
    package = BASE/'runtime-src'/'atlas_tectonics'
    frozen = {name: read(BASE/'runtime-src'/name, pin) for name, pin in prior['source_hashes'].items()}
    _require({p.relative_to(BASE/'runtime-src').as_posix() for p in package.rglob('*.py')} == set(frozen),
             'predecessor package membership changed')
    stages, origins = _Stages(reviewed), {}
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
        historical_validators=validators, import_review=review)


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
    return dict(schema=MANIFEST_SCHEMA,
        status='SOURCE_COMPOSED_PENDING_REVIEW_AND_AUTHENTICATED_MIGRATION',
        source_hashes=hashes, files=dict(sorted(files.items())), data_only=dict(sorted(data_only.items())),
        native_source_digest=sha256(canonical(hashes)).hexdigest(),
        reviewed_inputs_sha256=_pin(document_sha256), predecessor_manifest_sha256=PREDECESSOR,
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
PROFILE_SCHEMA = 'atlas.prepared-restart-launch.v1'
PROFILE_NAME = 'restart-profile-s2-r1.json'
HISTORICAL_EXECUTION = '6aa7a30cbe577a80d0a4f93d23b22a09525bb509e1e3f8f0f57e6fe09bc9ccad'
HISTORICAL_NATIVE_DIGEST = '746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28'
HISTORICAL_SOURCE_MANIFEST = ('heat-repair-20261007/continuation-preparation-r3.json',
                              'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c')
HISTORICAL_RECEIPT = ('heat-original-connected-20261013-r9.json',
                      'ca35700a8106d46eb67c876cd15fb5bf86d6abee7480cc94a23acbef68bb4f0d')
QUERY_LIMITS = {'max_entries': 2_000_000, 'max_store_bytes': 8 << 30}
LAUNCH_ENVIRONMENT = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                      'PYTHONHASHSEED': '0'}
RECEIPTS = ('q1', 'q2', 'w1a', 'w1b', 'w1c', 'w1d', 'w1f', 'w1g', 'w2b', 'w2e', 'w2k', 'wave1-retest',
            'wave2-retest')
I_REASON = ('Integrated optimisation runtime I (manifest 597c0032): the 23 selected r16 serial optimisations, '
            'both cold-reader RAM repairs and automatic endpoint-volume selection; I-pinned bytes; physics, '
            'tolerances and approved accuracy limits unchanged.')
NATIVE_REASONS = {
    'regional_execution.py': ('native_transfer.retained_snapshot_source: retained snapshot bytes for the explicit '
                              'native state transfer; numerical path unchanged.', ('wave2-retest',)),
    'integration_spatial_owner.py': ('spatial_transfer.spatial_owner_source then spatial_indexed_patch.transform: '
                                     'migrated spatial-owner entry and indexed (compact) snapshots.',
                                     ('w2e', 'wave2-retest')),
    'integration_differential_geometry.py': ('partition_native_patch.transform (compact partition admission), then '
                                             'the endpoint checkpoint seam, then geometry_transfer.transform('
                                             'compact=True) (parent geometry transfer binding).', ('w1a', 'w2k')),
    'integration_component_volume_batch.py': ('endpoint checkpoint seam: completed-query restart hook for exact '
                                              'positive-witness queries only.', ('w2k', 'q1')),
    'integration_endpoint_checkpoints.py': ('new endpoint checkpoint companion 4a835dc3: one strict runtime check '
                                            'per hit and per published miss; binding and refusals unchanged.',
                                            ('w2k', 'w2k-suite', 'q1')),
    'integration_differential_coupling.py': ('partition_native_patch.transform_coupling then '
                                             'continuation_transfer.coupling_source.', ('w1a',)),
    'integration_routing_views.py': ('partition_routing_transform.transform: compact routing views.', ('w1c',)),
    'integration_parallel_selection.py': ('partition_routing_transform.transform: compact routing.', ('w1c',)),
    'integration_differential_trace.py': ('partition_routing_transform.transform: compact routing and bounded '
                                          'diagnostic retention.', ('w1c',)),
    'integration_parallel_dispatch.py': ('partition_routing_transform.transform: compact routing.', ('w1c',)),
    'integration_differential_ale.py': ('partition_routing_transform.transform then the ALE checkpoint seam '
                                        '(caller-owned completed-query store).', ('w1c', 'w2k')),
    'integration_component_volume_auto.py': ('partition_routing_transform.transform then patch_endpoint_scheduler.'
                                             'transform_auto (checkpoint consumption).', ('w1c', 'w2k')),
    'integration_parallel_rolling.py': ('patch_endpoint_scheduler.transform_rolling: checkpoint consumption '
                                        'counters only.', ('w1c', 'w2k')),
    'integration_differential_pressure.py': ('pressure_indexed_patch.transform (indexed pressure consumer) then '
                                             'funding_transfer.pressure_source.', ('w1d', 'w1c')),
    'integration_regional_workflow.py': ('workflow_transfer.nonzero_cursor_source, spatial_workflow_patch.transform '
                                         'and partition_workflow_transform.transform: migrated root with compact '
                                         'spatial and partition workflow.', ('w1b', 'w2b')),
    'integration_private_heat_cold.py': ('workflow_transfer.private_heat_cold_source, partition_workflow_transform.'
                                         'cold_source and cold_binding_source (_BINDING_SHA 84a7a048 -> composed '
                                         'ram_recovery 71f82191).', ('w1b', 'w2e')),
    'integration_exterior_mesh.py': ('exterior_mesh_patch.transform: indexed exact exterior mesh reader.',
                                     ('wave2-retest',)),
    'integration_mimetic_heat.py': ('mimetic_patch.mimetic_source: indexed exact mimetic metrics.', ('wave2-retest',)),
    'integration_extremum_heat.py': ('mimetic_patch.extremum_source: indexed exact extremum heat reader.',
                                     ('wave2-retest',)),
    'integration_exact_gmp.py': ('reviewed filtered-exact delta F (manifest 43effbdb).', ('filtered', 'filtered-review')),
    'integration_volume_bounds.py': ('reviewed filtered-exact delta F (manifest 43effbdb).',
                                     ('filtered', 'filtered-review')),
    'integration_filtered_predicates.py': ('reviewed filtered-exact delta F: certified filtered predicates with exact '
                                           'escalation.', ('filtered', 'filtered-review')),
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


def write_review(target, manifest_sha256, measurement, *, output_directory, completed_query_directory,
                 evidence_root=EVIDENCE_ROOT, query_limits=QUERY_LIMITS):
    """Helper review, compatibility policy and restart profile for a frozen target.

    measurement is the probe_execution_identity output for exactly this manifest.
    Records are written exclusively, in dependency order; returns their sha256.
    """
    target = Path(target).resolve()
    relative = workspace_relative(target)
    manifest = json.loads(read(target/'manifest.json', manifest_sha256))
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
    review_dir = target/'review'
    review_dir.mkdir(exist_ok=False)
    receipts, owners = {}, {}
    for name in RECEIPTS:
        path = HERE/'test-results'/(name+'.json')
        raw = path.read_bytes()
        receipts[name] = dict(path=workspace_relative(path), sha256=digest(raw))
        record = json.loads(raw)
        for row in record.get('files') or ():
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
        delivered = [dict(file=name, **row) for name in local for row in owners.get(name, [])]
        entries[key] = dict(sha256=pin, **origin, delivering_receipts=delivered,
            reviewed_by=['Claude W3 composer: authenticated source bytes, transform chain and digests',
                         'Claude adversarial verifier of the delivering package (wave-1/wave-2 verdict pass)'])
    helper_review = dict(schema='atlas.private.composed-helper-review.v1', target=relative,
        source_manifest_sha256=manifest_sha256, reviewed_inputs_sha256=manifest['reviewed_inputs_sha256'],
        native_source_digest=manifest['native_source_digest'], entries=entries,
        required_modules=manifest['required_modules'], import_review=manifest['import_review'],
        historical_validators_executed_from_h=sorted(n for n in manifest['files']
                                                     if Path(n).name in HISTORICAL_VALIDATORS),
        data_only=manifest['data_only'], execution_identity_measurement=measurement, receipts=receipts,
        notes=['Helpers are outside the native execution identity (C-D15); they are bound by the manifest, '
               'RestartSources.check_imported, the end-of-run verify() and this review.',
               'The historical guard r3 (2d23f4bb) is not shipped; its receipts remain pinned evidence.',
               'Reconciling the RAM binding changes the agreed fixed sources for NEW heat CAS references only; '
               'restore_migrated_root does not re-verify first-interval heat against the new pins.',
               'Composed heat-bundle bytes embed absolute H paths and are machine-specific.',
               'run_prepared_restart/reopen_prepared_restart: W3 passes phase=guard.phase to materialise '
               '(W2-B request); the forced check stays unwrapped.'],
        production_acceptance=False)
    helper_raw = _write_exclusive(review_dir/'helper-review.json', helper_review)
    historical = native_inventory(WORKSPACE/HISTORICAL_NATIVE_RELATIVE)
    _require(sha256(canonical(historical)).hexdigest() == HISTORICAL_NATIVE_DIGEST, 'historical inventory differs')
    receipt = json.loads(read(HISTORICAL/HISTORICAL_RECEIPT[0], HISTORICAL_RECEIPT[1]))
    _require(receipt['completed_endpoint']['execution_provenance'] ==
             {'execution_identity': HISTORICAL_EXECUTION, 'execution_mode': 'strict'} and
             receipt['native_source_digest'] == HISTORICAL_NATIVE_DIGEST and
             receipt['preparation_manifest_sha256'] == HISTORICAL_SOURCE_MANIFEST[1],
             'historical producer identity differs from the pinned r9 receipt')
    read(WORKSPACE/EVIDENCE_ROOT/HISTORICAL_SOURCE_MANIFEST[0], HISTORICAL_SOURCE_MANIFEST[1])

    def ev(path):
        return _evidence_relative(path, evidence_root)

    paths = {'I': BASE/'manifest.json', 'I-preflight': BASE/'preflight-result.json',
             'filtered': FILTERED/'manifest.json', 'filtered-review': FILTERED/'review.md',
             'w2k-suite': HERE/'endpoint-checkpoints'/'test-results-w2k.json',
             'reviewed-inputs': HERE/'reviewed-inputs.json', 'helper-review': review_dir/'helper-review.json'}
    paths.update({name: HERE/'test-results'/(name+'.json') for name in RECEIPTS})
    keys = {name: ev(path) for name, path in paths.items()}
    evidence = {keys[name]: digest(path.read_bytes()) for name, path in paths.items()}
    _require(evidence[keys['I']] == PREDECESSOR and evidence[keys['filtered']] == FILTERED_MANIFEST and
             evidence[keys['reviewed-inputs']] == manifest['reviewed_inputs_sha256'] and
             evidence[keys['helper-review']] == digest(helper_raw), 'review evidence differs from the composition')
    i_sources = json.loads(read(BASE/'manifest.json', PREDECESSOR))['source_hashes']
    current = manifest['source_hashes']
    changes = {}
    for name in sorted(set(historical) | set(current)):
        before, after = historical.get(name), current.get(name)
        if before == after:
            continue
        reasons, cited = [], {'reviewed-inputs', 'helper-review', 'wave2-retest'}
        if name in i_sources and i_sources[name] != before:
            reasons.append(I_REASON)
            cited |= {'I', 'I-preflight'}
        if i_sources.get(name) != after:
            stem = Path(name).name
            _require(stem in NATIVE_REASONS, 'composed native change without a review reason: '+name)
            text, packages = NATIVE_REASONS[stem]
            reasons.append('Composed successor W3 (stage digests in reviewed-inputs.json): '+text)
            cited |= set(packages)
        _require(bool(reasons), 'unexplained native delta: '+name)
        changes[name] = dict(before=before, after=after, reason=' '.join(reasons),
                             evidence=sorted(keys[c] for c in cited))
    constraints = literal(read(target/'helpers'/'runtime_compatibility.py',
                               manifest['files'][relative+'/helpers/runtime_compatibility.py']).decode('utf8'),
                          'CONSTRAINTS')
    historical_manifest = (HISTORICAL_SOURCE_MANIFEST[0] if evidence_root == EVIDENCE_ROOT else
                           ev(WORKSPACE/EVIDENCE_ROOT/HISTORICAL_SOURCE_MANIFEST[0]))
    policy = dict(schema=POLICY_SCHEMA, constraints=constraints,
        historical=dict(source_hashes=historical, native_source_digest=HISTORICAL_NATIVE_DIGEST,
                        source_manifest_path=historical_manifest, source_manifest_sha256=HISTORICAL_SOURCE_MANIFEST[1],
                        execution_identity=HISTORICAL_EXECUTION),
        current=dict(source_hashes=current, native_source_digest=sha256(canonical(current)).hexdigest(),
                     source_manifest_path=ev(target/'manifest.json'), source_manifest_sha256=manifest_sha256,
                     execution_identity=identity),
        reviewed_changes=changes, evidence=dict(sorted(evidence.items())))
    policy_raw = _write_exclusive(review_dir/'runtime-compatibility-policy.json', policy)
    completed = receipt['completed_endpoint']
    output = str(output_directory)
    _require(Path(output).is_absolute() and str(Path(output)) == output == str(Path(output).resolve()) and
             not Path(output).exists() and Path(output).resolve().is_relative_to(WORKSPACE),
             'fresh canonical absolute output directory inside the workspace required')
    _require(type(completed_query_directory) is str and not Path(completed_query_directory).is_absolute() and
             '\\' not in completed_query_directory and '..' not in Path(completed_query_directory).parts and
             not (WORKSPACE/completed_query_directory).resolve().is_relative_to(Path(output)),
             'contained completed-query directory outside the attempt output required')
    profile = dict(schema=PROFILE_SCHEMA, workspace=str(WORKSPACE),
        source_manifest=dict(path=relative+'/manifest.json', sha256=manifest_sha256),
        native_root=manifest['layout']['native_root'], import_roots=manifest['layout']['import_roots'],
        modules=manifest['required_modules'],
        preparation=dict(path=PREPARATION, sha256=manifest['files'][PREPARATION]),
        compatibility_policy=dict(path=relative+'/review/runtime-compatibility-policy.json',
                                  sha256=digest(policy_raw)),
        evidence_root=evidence_root, historical_source_root=HISTORICAL_NATIVE_RELATIVE,
        advance_driver=dict(module=DRIVER_MODULE, path=manifest['advance_driver'],
                            sha256=manifest['files'][manifest['advance_driver']]),
        output_directory=output, store_limits=completed['store_limits'], compression=completed['store_compression'],
        completed_query_directory=completed_query_directory, completed_query_limits=dict(query_limits))
    profile_raw = _write_exclusive(review_dir/PROFILE_NAME, profile)
    return {'helper-review.json': digest(helper_raw), 'runtime-compatibility-policy.json': digest(policy_raw),
            PROFILE_NAME: digest(profile_raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed-inputs-sha256', required=True)
    args = parser.parse_args(argv)
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
