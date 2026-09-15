"""Public source-captured seasonal successor; no canonical predecessor imports."""
from . import provenance

RECIPE_SCHEMA = 'diadem.seasonal-consequences-recipe.r11'
RESULT_SCHEMA = 'diadem.seasonal-consequences-result.r11'
CHECKPOINT_SCHEMA = 'diadem.seasonal-consequences-checkpoint.r11'


class Bundle:
    def __init__(self):
        self.parent = provenance.load_parent()
        self.storage = self.parent.storage
        self.identity, self.source_sha256 = provenance.source_identity(self.parent)
        nodes = {}
        for path, digest in self.identity['r11_sources'].items():
            source = provenance.plain_path(path)
            if source.suffix == '.py':
                if source.parent != provenance.HERE:
                    raise ValueError('flat declared module layout required')
                nodes['work.generator_upgrade_r11.'+source.stem] = (source, digest)
        for path, digest in self.identity['extra_executable_sources'].items():
            source = provenance.plain_path(path)
            logical = '.'.join(source.relative_to(provenance.TASK).with_suffix('').parts)
            if logical in nodes:
                raise ValueError('duplicate module identity')
            nodes[logical] = (source, digest)
        self.graph = self.parent.graph.__class__(nodes)

    def verify(self):
        self.graph.verify()
        current, digest = provenance.source_identity(self.parent)
        if current != self.identity or digest != self.source_sha256:
            raise ValueError('R11 source inventory changed after binding')
        return digest

    def module(self, name):
        return self.graph.load('work.generator_upgrade_r11.'+name)

    @property
    def reference(self):
        return self.module('reference')

    @property
    def transport(self):
        return self.graph.load('work.generator_upgrade_r2.multicommodity')

    @property
    def agroclimate(self):
        return self.graph.load('work.generator_upgrade_r1.agroclimate')

    @property
    def organic(self):
        return self.parent.parent.parent.parent.graph.load('work.generator_upgrade_r7.organic')

    @property
    def fertility(self):
        return self.parent.parent.parent.parent.graph.load('work.generator_upgrade_r7.fertility')

    def run(self, recipe, *, stop_after=None, resume=None):
        self.verify()
        s = self.storage
        grouped = self.module('consequences')
        codec = self.parent.graph.load('work.generator_upgrade_r10.payloads')
        recipe = s.decoded(s.encoded(recipe))
        resume = None if resume is None else grouped.clone(resume, codec)
        result = self.module('pipeline').run(self, recipe, stop_after=stop_after, resume=resume)
        self.verify()
        return grouped.clone(result, codec)

    def checkpoint(self, result):
        self.verify()
        s = self.storage
        grouped = self.module('consequences')
        codec = self.parent.graph.load('work.generator_upgrade_r10.payloads')
        result = grouped.clone(result, codec)
        if result.get('schema') != RESULT_SCHEMA or result.get('source_sha256') != self.source_sha256:
            raise ValueError('this source-bound result required')
        state = result['state']
        return {'schema': CHECKPOINT_SCHEMA, 'recipe_sha256': s.digest(result['recipe_sha256']),
            'source_sha256': self.source_sha256, 'state_sha256': grouped.state_digest(state, codec), 'state': state}

    def run_workflow(self, recipe, *, stop_after=None, resume=None, supplied_parent=None):
        """Actual graph entrypoint; cursor counts graph stages, not scenarios.

        Returned scientific artifacts are individually bounded, content-addressed
        records. They must be stored separately, not flattened into one envelope.
        An explicitly supplied parent is never represented as freshly generated.
        """
        self.verify()
        s = self.storage
        clean = s.decoded(s.encoded(recipe))
        checkpoint = None if resume is None else s.decoded(s.encoded(resume))
        parent = None if supplied_parent is None else s.decoded(s.encoded(supplied_parent))
        result = self.module('workflow').run(self, clean, stop_after=stop_after,
            resume=checkpoint, supplied_parent=parent)
        self.verify()
        return result


def load():
    return Bundle()
