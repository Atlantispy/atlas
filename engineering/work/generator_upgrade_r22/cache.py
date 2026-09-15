"""Existing bounded authenticated stage cache; no new storage policy."""
from pathlib import Path
from work.generator_upgrade_r20.cache import StageCache as Existing
from . import provenance as p

DEFAULT_ROOT = Path(__file__).resolve().parents[2]/'c22'


class StageCache:
    def __init__(self, name, binding, root=None, *, moving_ground=False):
        self.execution = p.identity(moving_ground=moving_ground)
        self.store = Existing('r22-'+name, {'execution': self.execution, 'binding': binding},
                              DEFAULT_ROOT if root is None else Path(root))

    def reuse(self, invocation, producer, validator):
        p.verify(self.execution)
        result = self.store.reuse(invocation, producer, validator)
        p.verify(self.execution)
        return result

    @property
    def stats(self):
        return self.store.stats

    @property
    def warnings(self):
        return self.store.warnings
