"""Source-bound R8 entry point; sealed soil and physical parents are immutable.

Checkpoint checksums prove representation/binding only. The stage driver must
validate its complete state, source-exposure support and stage cursor by replay.
"""
from . import provenance

RECIPE_SCHEMA = 'diadem.biomes-vegetation-recipe.r8'
RESULT_SCHEMA = 'diadem.biomes-vegetation-result.r8'
CHECKPOINT_SCHEMA = 'diadem.biomes-vegetation-checkpoint.r8'


def module_nodes(sources):
    """Explicit flat module map; refuse silent basename/path aliasing."""
    nodes={}
    for path,digest in sources.items():
        source=provenance.plain_path(path)
        if source.suffix!='.py': continue
        if source.parent!=provenance.HERE:
            raise ValueError('bounded R8 Python module layout must be flat')
        logical='work.generator_upgrade_r8.'+source.stem
        if logical in nodes: raise ValueError('duplicate R8 private module identity')
        nodes[logical]=(source,digest)
    return nodes


class Bundle:
    def __init__(self):
        self.parent=provenance.load_parent()
        self.storage=self.parent.storage
        self.identity,self.source_sha256=provenance.source_identity(self.parent)
        self.graph=self.parent.graph.__class__(module_nodes(self.identity['r8_sources']))

    def verify(self):
        self.graph.verify()
        current,digest=provenance.source_identity(self.parent)
        if current!=self.identity or digest!=self.source_sha256:
            raise ValueError('R8 source inventory changed after binding')
        return digest

    @property
    def pipeline(self):
        return self.graph.load('work.generator_upgrade_r8.pipeline')

    @property
    def reference(self):
        return self.graph.load('work.generator_upgrade_r8.reference')

    def run(self, recipe, *, stop_after=None, resume=None):
        self.verify()
        s=self.storage
        recipe=s.decoded(s.encoded(recipe))
        resume=None if resume is None else s.decoded(s.encoded(resume))
        result=self.pipeline.run(self,recipe,stop_after=stop_after,resume=resume)
        self.verify()
        return s.decoded(s.encoded(result))

    def checkpoint(self, result):
        self.verify()
        s=self.storage
        result=s.decoded(s.encoded(result))
        if (type(result) is not dict or result.get('schema')!=RESULT_SCHEMA
                or result.get('source_sha256')!=self.source_sha256):
            raise ValueError('this exact source-bound R8 result required')
        state=s.decoded(s.encoded(result['state']))
        return {'schema':CHECKPOINT_SCHEMA,'recipe_sha256':s.digest(result['recipe_sha256']),
            'source_sha256':self.source_sha256,'state_sha256':s.sha(s.encoded(state)),'state':state}


def load():
    return Bundle()
