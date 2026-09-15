"""Live, exact preservation of sealed R3 and explicit R4 owner bindings.

The retained 209 checks are not rerun or counted as new R4 checks. The seal's
source maps are verified as bytes, separately from executed-code verification.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import platform

from .storage import decoded, encoded, digest, plain_path, sha

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
R3_ROOT = TASK / 'work/generator_upgrade_r3'
R3_SEAL = TASK / 'outputs/generator-upgrade-r3/connected-reference-01/VERIFICATION.json'
R3_SEAL_SHA256 = '0e87efa805e965aa68ced76bcdd678001f957d7be30719ff9812dd734b679de5'
R3_IDENTITY_SHA256 = '3e197845a535eb00093f40f9adeae9d8ebeddb3279ad0c6acbbf350e07d0e8a9'
EXPECTED_R3_COUNT = 25
EXPECTED_PROTECTED_COUNT = 161
EXPECTED_DEPENDENCY_COUNT = 2
EXPECTED_CATEGORY_COUNT = 4
MAX_SOURCE_FILES = 256
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_EXTERNAL_SOURCE_BYTES = 64 * 1024 * 1024
MAX_EXTERNAL_TOTAL_BYTES = 128 * 1024 * 1024
SOURCE_SUFFIXES = frozenset(('.py', '.json', '.md'))
W = Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace')
CLIMATE_DECISIONS = W / '02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1'
CLIMATE_BINDINGS = {
    str(CLIMATE_DECISIONS / 'CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md'):
        'ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19',
    str(CLIMATE_DECISIONS / 'CLIMATE_SOILS_SOURCE_BINDINGS_2026-09-10_R1.md'):
        'b71dc5050baf8f1cedfa6e31473de476fdf1b3e7faee4b842792accc3c244512',
}


def captured(path, expected=None):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('bounded regular source file required: ' + str(path))
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('source grew beyond bounded capture')
    if expected is not None and sha(raw) != digest(expected):
        raise ValueError('bound source changed; no silent repin: ' + str(path))
    return raw


def capture_sources(root=None):
    root = plain_path(HERE if root is None else root)
    if not root.is_dir():
        raise ValueError('source directory required')
    result = {}
    total = 0
    for path in sorted(root.rglob('*')):
        # Inspect links before filtering suffixes so an unvisited linked source
        # directory cannot disguise a changed inventory.
        plain_path(path)
        if '__pycache__' in path.relative_to(root).parts:
            continue
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            raw = captured(path)
            total += len(raw)
            result[str(path)] = sha(raw)
            if len(result) > MAX_SOURCE_FILES or total > MAX_CAPTURE_BYTES:
                raise ValueError('scoped source inventory exceeds resource bound')
    if not result:
        raise ValueError('empty source inventory')
    return result


def verify_map(mapping, *, count=None):
    if type(mapping) is not dict or not mapping or len(mapping) > MAX_SOURCE_FILES:
        raise ValueError('bounded nonempty source identity map required')
    if count is not None and len(mapping) != count:
        raise ValueError('retained source inventory count differs')
    total = 0
    for path, expected in mapping.items():
        if type(path) is not str:
            raise ValueError('source path must be a string')
        total += len(captured(path, expected))
        if total > MAX_CAPTURE_BYTES:
            raise ValueError('source map capture exceeds resource bound')
    return dict(mapping)


def _owner_bindings():
    # This module is itself in the checked 161-source map. The final verifier
    # additionally proves its freshly compiled bytes actually executed.
    from work.generator_upgrade_r2.bindings import owner_bindings
    return owner_bindings()


def _hydromet_bindings():
    from .hydromet import PINS
    return verify_map(PINS, count=5)


def climate_source_bindings():
    """Hash only the manifest's explicit small sources, never whole archives.

    The retained monthly NPZ exceeds the text-source envelope. Stream hashing
    keeps its data verification separate from source compilation/read claims.
    """
    path = HERE / 'CLIMATE_SOURCE_BINDINGS.json'
    raw = captured(path)
    record = decoded(raw)
    if (type(record) is not dict or set(record) != {'schema', 'status', 'reviewed_sources', 'retained_bridge'}
            or record['schema'] != 'diadem.r4.climate-source-bindings'
            or record['status'] != 'EXPLICIT_REVIEW_AND_RETAINED_FIXED_FORCING_BINDINGS_NOT_CANON'):
        raise ValueError('climate source manifest schema/status differs')
    reviewed = record['reviewed_sources']
    bridge = record['retained_bridge']
    if (type(reviewed) is not dict or not 1 <= len(reviewed) <= 32
            or type(bridge) is not dict
            or set(bridge) != {'monthly', 'geometry', 'manifest', 'parameter_card', 'G_launcher', 'G_gate'}):
        raise ValueError('climate source manifest inventory differs')
    sources = {}
    canonical = {}
    for group, detail in ((reviewed, 'review_scope'), (bridge, 'role')):
        for name, item in group.items():
            if type(name) is not str or not 1 <= len(name) <= 128:
                raise ValueError('bounded climate source label required')
            if (type(item) is not dict or set(item) != {'path', 'sha256', detail}
                    or type(item['path']) is not str or type(item[detail]) is not str
                    or not 1 <= len(item[detail]) <= 4096):
                raise ValueError('climate source record differs')
            source = plain_path(item['path'])
            expected = digest(item['sha256'])
            key = str(source.resolve())
            if key in canonical and canonical[key] != expected:
                raise ValueError('conflicting climate source hashes')
            canonical[key] = expected
            sources[item['path']] = expected
    total = 0
    for name, expected in sources.items():
        source = plain_path(name)
        if not source.is_file() or source.stat().st_size > MAX_EXTERNAL_SOURCE_BYTES:
            raise ValueError('bounded regular climate source required')
        hasher = hashlib.sha256()
        size = 0
        with source.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                total += len(block)
                if size > MAX_EXTERNAL_SOURCE_BYTES or total > MAX_EXTERNAL_TOTAL_BYTES:
                    raise ValueError('climate source capture exceeds resource bound')
                hasher.update(block)
        if hasher.hexdigest() != expected:
            raise ValueError('climate source changed; no silent repin: ' + name)
    if captured(path) != raw:
        raise ValueError('climate source manifest changed during capture')
    return {'manifest': {'path': str(path), 'sha256': sha(raw)}, 'record': record, 'sources': sources}


def retained_identity():
    record = decoded(captured(R3_SEAL, R3_SEAL_SHA256))
    if (type(record) is not dict or record.get('status') != 'BOUNDED_CONNECTED_REFERENCE_VERIFIED'
            or record.get('source_sha256') != R3_IDENTITY_SHA256):
        raise ValueError('retained R3 seal identity/status differs')
    identity = record.get('source_identity')
    if type(identity) is not dict or sha(encoded(identity)) != R3_IDENTITY_SHA256:
        raise ValueError('retained R3 source identity digest differs')
    expected_keys = {'r3_sources', 'predecessors', 'protected_sources', 'physical_interfaces',
                     'category_contracts', 'owner_bindings', 'executed_dependency_sources', 'runtime'}
    if set(identity) != expected_keys or record.get('source_snapshot') != identity['r3_sources']:
        raise ValueError('retained R3 source identity schema differs')
    if any(record.get(key) is not False for key in ('production_installed', 'canon_changed',
            'new_world_generated', 'whole_generator_upgraded', 'prior_tests_rerun_or_recounted')):
        raise ValueError('retained R3 status boundary differs')
    verify_map(identity['r3_sources'], count=EXPECTED_R3_COUNT)
    if capture_sources(R3_ROOT) != identity['r3_sources']:
        raise ValueError('retained R3 exact directory inventory differs')
    verify_map(identity['protected_sources'], count=EXPECTED_PROTECTED_COUNT)
    verify_map(identity['executed_dependency_sources'], count=EXPECTED_DEPENDENCY_COUNT)
    verify_map(identity['category_contracts'], count=EXPECTED_CATEGORY_COUNT)
    verify_map(identity['physical_interfaces'])
    predecessors = identity['predecessors']
    if type(predecessors) is not list or len(predecessors) != 3:
        raise ValueError('retained predecessor seal chain differs')
    for predecessor in predecessors:
        if (type(predecessor) is not dict
                or set(predecessor) != {'path', 'sha256', 'source_files', 'tests_rerun'}
                or predecessor['tests_rerun'] is not False):
            raise ValueError('retained predecessor record differs')
        captured(predecessor['path'], predecessor['sha256'])
    owners = _owner_bindings()
    if owners != identity['owner_bindings']:
        raise ValueError('current owner bindings differ from retained R3; no silent repin')
    return identity


def source_identity():
    retained = retained_identity()
    climate = verify_map(CLIMATE_BINDINGS, count=2)
    import numpy
    import scipy
    identity = {
        'r4_sources': capture_sources(),
        'r3_preservation': {'path': str(R3_SEAL), 'sha256': R3_SEAL_SHA256,
                            'source_sha256': R3_IDENTITY_SHA256, 'source_files': EXPECTED_R3_COUNT,
                            'prior_tests_rerun_or_recounted': False},
        'r3_sources': retained['r3_sources'],
        'predecessors': retained['predecessors'],
        'protected_sources': retained['protected_sources'],
        'executed_dependency_sources': retained['executed_dependency_sources'],
        'category_contracts': retained['category_contracts'],
        'physical_interfaces': retained['physical_interfaces'],
        'owner_bindings': retained['owner_bindings'],
        'climate_owner_bindings': climate,
        'climate_source_bindings': climate_source_bindings(),
        'hydromet_source_bindings': _hydromet_bindings(),
        'runtime': {'python': platform.python_version(), 'numpy': numpy.__version__, 'scipy': scipy.__version__},
    }
    return identity, sha(encoded(identity))


def verify_identity(expected):
    if type(expected) is not dict:
        raise ValueError('complete source identity required')
    current, actual_sha256 = source_identity()
    if current != expected:
        raise ValueError('source identity changed during operation')
    return actual_sha256
