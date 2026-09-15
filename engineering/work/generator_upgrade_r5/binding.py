"""Isolated exact-source R4/R3 execution with only the R5 Water dependency.

No retained source is rewritten; no canonical module, builtins table or global
import hook is patched. Private names exist in sys.modules only while defining
dataclasses. Source identities deliberately exclude those random private names.
"""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys
import types
import uuid

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
R4_SEAL = TASK / 'outputs/generator-upgrade-r4/connected-reference-01/VERIFICATION.json'
R4_SEAL_SHA256 = 'f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'
R4_SOURCE_SHA256 = 'd17c5bb4bf45c07731ed114baddff0a808e9bb6106e4e864eb5aa998b91e41cf'
MAX_BYTES = 8 * 1024 * 1024
MAX_SOURCE_FILES = 128
RECIPE_SCHEMA = 'diadem.precision-diagnostic-recipe.r5'
RESULT_SCHEMA = 'diadem.precision-diagnostic-result.r5'
CHECKPOINT_SCHEMA = 'diadem.precision-diagnostic-checkpoint.r5'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def canonical(path):
    return str(Path(path).resolve())


def plain_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute bounded source path required')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked/reparse source refused')
    return path


def checked(path, expected=None):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('bounded regular source file required')
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or (expected is not None and sha(raw) != expected):
        raise ValueError('source changed; no silent repin: ' + str(path))
    return raw


def current_sources():
    result = {}
    for path in sorted(HERE.rglob('*')):
        plain_path(path)
        if '__pycache__' in path.parts:
            continue
        if path.is_file() and path.suffix in ('.py', '.json', '.md'):
            result[str(path)] = sha(checked(path))
    if not result or len(result) > MAX_SOURCE_FILES:
        raise ValueError('bounded nonempty R5 source inventory required')
    return result


def retained_record():
    record = json.loads(checked(R4_SEAL, R4_SEAL_SHA256))
    if (record.get('status') != 'BOUNDED_CONNECTED_REFERENCE_VERIFIED'
            or record.get('source_sha256') != R4_SOURCE_SHA256
            or sha(encoded(record.get('source_identity'))) != R4_SOURCE_SHA256
            or record.get('source_snapshot') != record['source_identity']['r4_sources']):
        raise ValueError('retained R4 seal/source identity differs')
    return record


class PrivateGraph:
    """Module-local explicit imports; every module executes exact captured bytes."""
    def __init__(self, nodes):
        # logical import name -> (actual source path, exact source hash)
        self.nodes = dict(nodes)
        self.modules = {}
        self.executed = {}
        self.active = set()
        self.prefix = '_diadem_r5_' + uuid.uuid4().hex

    def import_module(self, name, globals=None, locals=None, fromlist=(), level=0):
        resolved = importlib.util.resolve_name('.' * level + name, globals['__package__']) if level else name
        if resolved.startswith('work.') or resolved == 'work':
            if resolved in self.nodes:
                if not fromlist:
                    raise ValueError('project dependencies require explicit from-imports')
                return self.load(resolved)
            if not fromlist or any(item == '*' for item in fromlist):
                raise ValueError('unbounded project import refused')
            package = types.ModuleType(resolved)
            package.__path__ = []
            for item in fromlist:
                target = resolved + '.' + item
                if target not in self.nodes:
                    raise ValueError('undeclared private dependency: ' + target)
                setattr(package, item, self.load(target))
            return package
        return builtins.__import__(name, globals, locals, fromlist, level)

    def load(self, logical):
        if logical in self.modules:
            return self.modules[logical]
        if logical not in self.nodes or logical in self.active:
            raise ValueError('unknown or cyclic private dependency')
        path, expected = self.nodes[logical]
        raw = checked(path, expected)
        private_name = self.prefix + '_' + logical.replace('.', '_')
        module = types.ModuleType(private_name)
        module.__file__ = str(path)
        module.__package__ = logical.rpartition('.')[0]
        module.__builtins__ = dict(vars(builtins), __import__=self.import_module)
        if private_name in sys.modules:
            raise ValueError('private namespace occupied')
        self.active.add(logical)
        sys.modules[private_name] = module
        try:
            exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
        finally:
            del sys.modules[private_name]
            self.active.remove(logical)
        checked(path, expected)
        self.modules[logical] = module
        self.executed[logical] = {'path': str(path), 'sha256': expected}
        return module

    def verify(self):
        for record in self.executed.values():
            checked(record['path'], record['sha256'])


def _nodes(record, r5_sources):
    identity = record['source_identity']
    pins = {}
    for key in ('r4_sources', 'r3_sources', 'protected_sources', 'executed_dependency_sources'):
        for path, value in identity[key].items():
            key_path = canonical(path)
            if key_path in pins and pins[key_path] != value:
                raise ValueError('conflicting retained source pin')
            pins[key_path] = value
    modules = {
        'work.generator_upgrade_r2': ('bindings', 'soil_physics'),
        'work.generator_upgrade_r3': ('deps', 'soil_inputs', 'terrain_transport', 'storage', 'pipeline', 'reference'),
        'work.generator_upgrade_r4': ('climate', 'hydromet', 'storage', 'provenance', 'pipeline', 'reference'),
    }
    nodes = {}
    for package, names in modules.items():
        for name in names:
            logical = package + '.' + name
            path = TASK.joinpath(*logical.split('.')).with_suffix('.py')
            nodes[logical] = (path, pins[canonical(path)])
    solver = HERE / 'soil_water.py'
    nodes['work.generator_upgrade_r5.soil_water'] = (solver, r5_sources[str(solver)])
    nodes['work.generator_upgrade_r3.soil_water'] = nodes['work.generator_upgrade_r5.soil_water']
    tests = TASK / 'work/generator_upgrade_r3/test_soil_water.py'
    nodes['work.generator_upgrade_r5.retained_soil_water_tests'] = (tests, pins[canonical(tests)])
    return nodes


class Bundle:
    def __init__(self):
        record = retained_record()
        sources = current_sources()
        self.graph = PrivateGraph(_nodes(record, sources))
        provenance = self.graph.load('work.generator_upgrade_r4.provenance')
        current, digest = provenance.source_identity()
        if current != record['source_identity'] or digest != R4_SOURCE_SHA256:
            raise ValueError('retained R4/inherited live sources differ from sealed identity')
        self.identity = {'schema': 'diadem.isolated-diagnostic-binding.r5', 'r5_sources': sources,
            'retained_r4_seal': {'path': str(R4_SEAL), 'sha256': R4_SEAL_SHA256, 'source_sha256': R4_SOURCE_SHA256},
            'retained_source_identity': current,
            'dependency_binding': {'scientific_replacement': 'R3 pipeline .soil_water -> exact R5 soil_water bytes',
                'R4_pipeline': 'unchanged source -> private unchanged R3 pipeline',
                'other_dependencies': 'fresh private copies of exact preserved sources; no global patch/source rewrite'},
            'runtime': current['runtime']}
        self.source_sha256 = sha(encoded(self.identity))
        self.solver = self.graph.load('work.generator_upgrade_r3.soil_water')
        # Both logical routes must resolve to ONE successor class identity.
        self.graph.modules['work.generator_upgrade_r5.soil_water'] = self.solver
        self.r3 = self.graph.load('work.generator_upgrade_r3.pipeline')
        self.pipeline = self.graph.load('work.generator_upgrade_r4.pipeline')
        self.reference = self.graph.load('work.generator_upgrade_r4.reference')
        self.storage = self.graph.load('work.generator_upgrade_r4.storage')
        self.verify()

    def verify(self):
        if current_sources() != self.identity['r5_sources']:
            raise ValueError('R5 source inventory changed after binding')
        self.graph.verify()
        current, digest = self.graph.load('work.generator_upgrade_r4.provenance').source_identity()
        if current != self.identity['retained_source_identity'] or digest != R4_SOURCE_SHA256:
            raise ValueError('retained sources changed after binding')
        return self.source_sha256

    def wrap_recipe(self, retained_recipe, *, evidence):
        if type(evidence) is not str or not evidence.strip() or len(evidence) > 4096:
            raise ValueError('explicit bounded R5 experiment evidence required')
        return self.storage.decoded(self.storage.encoded({'schema': RECIPE_SCHEMA,
            'source_status': 'WORKING NON-CANON', 'evidence': evidence,
            'source_sha256': self.source_sha256, 'retained_recipe': retained_recipe}))

    def run(self, recipe, *, stop_after=None, resume=None):
        self.verify()
        s = self.storage
        recipe = s.decoded(s.encoded(recipe))
        if (type(recipe) is not dict or set(recipe) != {'schema', 'source_status', 'evidence', 'source_sha256', 'retained_recipe'}
                or recipe['schema'] != RECIPE_SCHEMA or recipe['source_status'] != 'WORKING NON-CANON'
                or recipe['source_sha256'] != self.source_sha256
                or type(recipe['evidence']) is not str or not recipe['evidence'].strip() or len(recipe['evidence']) > 4096):
            raise ValueError('exact source-bound R5 wrapper recipe required')
        recipe_hash = sha(s.encoded(recipe))
        inner_resume = None
        if resume is not None:
            resume = s.decoded(s.encoded(resume))
            if (type(resume) is not dict or set(resume) != {'schema', 'recipe_sha256', 'source_sha256', 'state_sha256', 'state'}
                    or resume['schema'] != CHECKPOINT_SCHEMA or resume['recipe_sha256'] != recipe_hash
                    or resume['source_sha256'] != self.source_sha256
                    or resume['state_sha256'] != sha(s.encoded(resume['state']))):
                raise ValueError('R5 restart identity differs; old checkpoints are not successors')
            inner_resume = s.checkpoint(resume['state'], recipe_sha256=sha(s.encoded(recipe['retained_recipe'])),
                                        source_sha256=self.source_sha256)
        result = self.pipeline.run(recipe['retained_recipe'], stop_after=stop_after,
                                   resume=inner_resume, source_sha256=self.source_sha256)
        self.verify()
        return {'schema': RESULT_SCHEMA, 'status': 'BOUNDED_DIAGNOSTIC_SUCCESSOR',
            'source_status': 'WORKING NON-CANON', 'recipe_sha256': recipe_hash, 'source_sha256': self.source_sha256,
            'state': result['state'], 'retained_result': result, 'production_installed': False, 'canon_changed': False,
            'scope': 'unchanged R4/R3 scientific pipeline; only R5 soil-water diagnostics; strict limits are not silently relaxed'}

    def checkpoint(self, result):
        self.verify()
        if (type(result) is not dict or result.get('schema') != RESULT_SCHEMA
                or result.get('source_sha256') != self.source_sha256):
            raise ValueError('this source-bound R5 result required')
        s = self.storage
        state = s.decoded(s.encoded(result['state']))
        return {'schema': CHECKPOINT_SCHEMA, 'recipe_sha256': s.digest(result['recipe_sha256']),
                'source_sha256': self.source_sha256, 'state_sha256': sha(s.encoded(state)), 'state': state}

    def retained_soil_tests(self):
        return self.graph.load('work.generator_upgrade_r5.retained_soil_water_tests')


def load():
    return Bundle()
