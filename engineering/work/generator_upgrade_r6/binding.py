"""Isolated exact-source R4/R3 execution with only the R6 Water dependency.

No retained source is rewritten; no canonical module, builtins table or global
import hook is patched. Private names exist in sys.modules only while defining
dataclasses. Source identities deliberately exclude those random private names.
"""
from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
import sys
import types
import uuid

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
from . import provenance as provenance_r6

sha = provenance_r6.sha
encoded = provenance_r6.encoded
canonical = provenance_r6.canonical
plain_path = provenance_r6.plain_path
checked = provenance_r6.checked
retained_record = provenance_r6.retained_record
RECIPE_SCHEMA = 'diadem.strict-soil-water-recipe.r6'
RESULT_SCHEMA = 'diadem.strict-soil-water-result.r6'
CHECKPOINT_SCHEMA = 'diadem.strict-soil-water-checkpoint.r6'


def current_sources():
    return provenance_r6.source_snapshot(HERE)


class PrivateGraph:
    """Module-local explicit imports; every module executes exact captured bytes."""
    def __init__(self, nodes):
        # logical import name -> (actual source path, exact source hash)
        self.nodes = dict(nodes)
        self.modules = {}
        self.executed = {}
        self.active = set()
        self.prefix = '_diadem_r6_' + uuid.uuid4().hex

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


def _nodes(record, r6_sources):
    identity = record['source_identity']['retained_source_identity']
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
    nodes['work.generator_upgrade_r6.soil_water'] = (solver, r6_sources[str(solver)])
    nodes['work.generator_upgrade_r3.soil_water'] = nodes['work.generator_upgrade_r6.soil_water']
    helper = HERE / 'hydraulic_jacobian.py'
    nodes['work.generator_upgrade_r6.hydraulic_jacobian'] = (helper,r6_sources[str(helper)])
    tests = TASK / 'work/generator_upgrade_r3/test_soil_water.py'
    nodes['work.generator_upgrade_r6.retained_soil_water_tests'] = (tests, pins[canonical(tests)])
    return nodes


class Bundle:
    def __init__(self):
        record = retained_record()
        sources = current_sources()
        self.graph = PrivateGraph(_nodes(record, sources))
        provenance = self.graph.load('work.generator_upgrade_r4.provenance')
        current, digest = provenance.source_identity()
        self.identity, self.source_sha256 = provenance_r6.source_identity(sources,current,digest)
        self.solver = self.graph.load('work.generator_upgrade_r6.soil_water')
        # Both logical routes must resolve to ONE successor class identity.
        self.graph.modules['work.generator_upgrade_r3.soil_water'] = self.solver
        self.r3 = self.graph.load('work.generator_upgrade_r3.pipeline')
        self.pipeline = self.graph.load('work.generator_upgrade_r4.pipeline')
        self.reference = self.graph.load('work.generator_upgrade_r4.reference')
        self.storage = self.graph.load('work.generator_upgrade_r4.storage')
        self.verify()

    def verify(self):
        if current_sources() != self.identity['r6_sources']:
            raise ValueError('R6 source inventory changed after binding')
        self.graph.verify()
        current, digest = self.graph.load('work.generator_upgrade_r4.provenance').source_identity()
        identity, verified_digest = provenance_r6.source_identity(current_sources(),current,digest)
        if identity != self.identity or verified_digest != self.source_sha256:
            raise ValueError('retained sources changed after binding')
        return self.source_sha256

    def wrap_recipe(self, retained_recipe, *, evidence):
        if type(evidence) is not str or not evidence.strip() or len(evidence) > 4096:
            raise ValueError('explicit bounded R6 experiment evidence required')
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
            raise ValueError('exact source-bound R6 wrapper recipe required')
        recipe_hash = sha(s.encoded(recipe))
        inner_resume = None
        if resume is not None:
            resume = s.decoded(s.encoded(resume))
            if (type(resume) is not dict or set(resume) != {'schema', 'recipe_sha256', 'source_sha256', 'state_sha256', 'state'}
                    or resume['schema'] != CHECKPOINT_SCHEMA or resume['recipe_sha256'] != recipe_hash
                    or resume['source_sha256'] != self.source_sha256
                    or resume['state_sha256'] != sha(s.encoded(resume['state']))):
                raise ValueError('R6 restart identity differs; old checkpoints are not successors')
            inner_resume = s.checkpoint(resume['state'], recipe_sha256=sha(s.encoded(recipe['retained_recipe'])),
                                        source_sha256=self.source_sha256)
        result = self.pipeline.run(recipe['retained_recipe'], stop_after=stop_after,
                                   resume=inner_resume, source_sha256=self.source_sha256)
        self.verify()
        return {'schema': RESULT_SCHEMA, 'status': 'BOUNDED_STRICT_SOLVER_SUCCESSOR',
            'source_status': 'WORKING NON-CANON', 'recipe_sha256': recipe_hash, 'source_sha256': self.source_sha256,
            'state': result['state'], 'retained_result': result, 'production_installed': False, 'canon_changed': False,
            'scope': 'unchanged R4/R3 scientific pipeline; R6 soil-water numerical correction; declared strict limits are not silently relaxed'}

    def checkpoint(self, result):
        self.verify()
        if (type(result) is not dict or result.get('schema') != RESULT_SCHEMA
                or result.get('source_sha256') != self.source_sha256):
            raise ValueError('this source-bound R6 result required')
        s = self.storage
        state = s.decoded(s.encoded(result['state']))
        return {'schema': CHECKPOINT_SCHEMA, 'recipe_sha256': s.digest(result['recipe_sha256']),
                'source_sha256': self.source_sha256, 'state_sha256': sha(s.encoded(state)), 'state': state}

    def retained_soil_tests(self):
        return self.graph.load('work.generator_upgrade_r6.retained_soil_water_tests')


def load():
    return Bundle()
