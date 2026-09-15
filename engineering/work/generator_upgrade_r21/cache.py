"""Reuse R20's tested adapter and unchanged R12 store; no cache redesign."""
from pathlib import Path
from work.generator_upgrade_r20.cache import StageCache as ExistingStageCache
from . import provenance as p

DEFAULT_ROOT = Path(__file__).resolve().parents[2]/'c21'


class StageCache:
    def __init__(self, stage, binding, root=None):
        self.execution = p.identity()
        self.cache = ExistingStageCache('r21-'+stage,
            {'execution': self.execution, 'binding': binding}, DEFAULT_ROOT if root is None else root)

    def reuse(self, invocation, producer, validator):
        p.verify(self.execution)
        value, hit = self.cache.reuse(invocation, producer, validator)
        p.verify(self.execution)
        return value, hit

    @property
    def stats(self):
        return self.cache.stats

    @property
    def warnings(self):
        return self.cache.warnings
