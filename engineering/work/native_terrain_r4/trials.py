"""Reuse immediate ancestry once; bounded trial scheduling has no history IO.

The retained substep bytecode and channel checks are unchanged. Mapping capture
belongs to one synchronous substep, never to another call or accepted state.
Trial scheduling stays serial: the measured cold process path was slower.
"""
from fractions import Fraction as F
from types import FunctionType, SimpleNamespace

from work.native_terrain_r1 import domain as retained_domain
from work.native_terrain_r2 import channel, evolve as numerical


def _adapt(function, **overrides):
    return FunctionType(function.__code__, dict(function.__globals__, **overrides),
                        function.__name__, function.__defaults__, function.__closure__)


def substep(self, state, palette, lineage, exports, duration, operation, water_before=F()):
    """Consume the ancestry already checked by the retained channel wrapper."""
    captured = []

    def capture(before, trial):
        mapping = retained_domain.channel_layer_sources(before, trial)
        captured.append((before, trial, mapping))
        return mapping

    def consume(before, trial):
        # The original second mapping call began with these source/backend
        # checks. Keep their order even though its immutable data is validated.
        retained_domain._verify_source()
        retained_domain.g1.ground_gate.backend()
        if (len(captured) != 1 or captured[0][0] is not before
                or captured[0][1] is not trial):
            raise ValueError('one exact validated channel ancestry result required')
        return captured.pop()[2]

    domain_scope = SimpleNamespace(**dict(vars(retained_domain), channel_layer_sources=capture))
    channel_trial = _adapt(channel.trial, retained_domain=domain_scope)
    step = _adapt(numerical.Executor._substep,
                  channel=SimpleNamespace(trial=channel_trial), channel_layer_sources=consume)
    return step(self, state, palette, lineage, exports, duration, operation, water_before)


def triplet(executor, state, palette, lineage, exports, duration, operation_id,
            water_before=F()):
    """Serial full/a/b trials, useful for bounded measurements without IO."""
    args = (state, palette, lineage, exports)
    full = executor._substep(*args, duration, operation_id + '/full', water_before)
    first = executor._substep(*args, duration / 2, operation_id + '/a', water_before)
    second = executor._substep(first[0], palette, first[1], first[2], duration / 2,
                               operation_id + '/b', first[3]['surface_water_exported_m3'])
    return full, first, second


class MappingExecutor(numerical.Executor):
    """Narrow adapter usable by standalone measurements and focused tests."""
    _substep = substep


def from_executor(executor):
    if type(executor) is not numerical.Executor:
        raise ValueError('exact retained R2 executor required')
    result = object.__new__(MappingExecutor)
    result.__dict__.update(executor.__dict__)
    return result
