"""Source-bound R7 entry point; sealed predecessors remain immutable."""
from . import provenance

RECIPE_SCHEMA = 'diadem.soil-formation-recipe.r7'
RESULT_SCHEMA = 'diadem.soil-formation-result.r7'
CHECKPOINT_SCHEMA = 'diadem.soil-formation-checkpoint.r7'


class Bundle:
    def __init__(self):
        self.parent = provenance.load_parent()
        self.storage = self.parent.storage
        self.identity,self.source_sha256 = provenance.source_identity(self.parent)
        # The public entry point, not only its verifier, executes captured bytes.
        nodes={}
        for path,digest in self.identity['r7_sources'].items():
            source=provenance.plain_path(path)
            if source.suffix=='.py':
                nodes['work.generator_upgrade_r7.'+source.stem]=(source,digest)
        self.graph=self.parent.graph.__class__(nodes)

    def verify(self):
        self.graph.verify()
        current,digest = provenance.source_identity(self.parent)
        if current!=self.identity or digest!=self.source_sha256:
            raise ValueError('R7 source inventory changed after binding')
        return digest

    def run(self, recipe, *, stop_after=None, resume=None):
        return self.pipeline.run(self,recipe,stop_after=stop_after,resume=resume)

    @property
    def pipeline(self):
        return self.graph.load('work.generator_upgrade_r7.pipeline')

    @property
    def reference(self):
        return self.graph.load('work.generator_upgrade_r7.reference')

    def checkpoint(self, result):
        self.verify()
        if (type(result) is not dict or result.get('schema')!=RESULT_SCHEMA
                or result.get('source_sha256')!=self.source_sha256):
            raise ValueError('this exact source-bound R7 result required')
        s = self.storage
        state = s.decoded(s.encoded(result['state']))
        return {'schema':CHECKPOINT_SCHEMA,'recipe_sha256':s.digest(result['recipe_sha256']),
            'source_sha256':self.source_sha256,'state_sha256':s.sha(s.encoded(state)),'state':state}


def load():
    return Bundle()
