"""W01 fixed-duration units and explicit forward-time/age axes.

All internal timestamps are SI seconds in a named epoch, increasing forwards.
These are numerical model-time conversions, NOT UTC/TAI calendars or leap seconds.
The optional Julian unit is exactly 365.25 fixed 86400-second days; selecting it
is explicit. No planetary rotation period or 'year' duration is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math

import numpy as np

from ._validation import FloatArray, TectonicsError, frozen, input_shape, read_array, scalar
from .coordinates import _identity, _label
from .resources import elements, select_budget


@dataclass(frozen=True, slots=True)
class TimeUnit:
    """A named fixed positive duration, not a calendar or unspecified 'year'."""
    name: str
    seconds_per_unit: float

    def __post_init__(self) -> None:
        _label(self.name, 'time unit name')
        object.__setattr__(self, 'seconds_per_unit',
                           scalar(self.seconds_per_unit,'seconds_per_unit',positive=True))

    def descriptor(self) -> dict:
        return {'name': self.name, 'seconds_per_unit': self.seconds_per_unit}


# Metrological definitions, not material parameters. All non-SI use is explicit.
SECOND = TimeUnit('SI second', 1.)
JULIAN_YEAR = TimeUnit('Julian year (365.25 fixed days)', 31_557_600.)
JULIAN_MEGAYEAR = TimeUnit('million Julian years', 31_557_600_000_000.)


@dataclass(frozen=True, slots=True)
class EpochOffset:
    """Explicit correspondence t_target = t_source + offset_s, in SI seconds.

    This is a supplied relationship, not an inference from epoch labels. Reversing
    a conversion requires the inverse offset. Identical labels require zero offset.
    """
    source_epoch_id: str
    target_epoch_id: str
    offset_s: float

    def __post_init__(self) -> None:
        _label(self.source_epoch_id, 'source epoch'); _label(self.target_epoch_id, 'target epoch')
        object.__setattr__(self,'offset_s',scalar(self.offset_s,'epoch offset'))
        if self.source_epoch_id == self.target_epoch_id and self.offset_s != 0:
            raise TectonicsError('one named epoch cannot have a nonzero offset to itself')

    def inverse(self) -> EpochOffset:
        return EpochOffset(self.target_epoch_id,self.source_epoch_id,-self.offset_s)


def _affine_time(values: Any, scale: float, offset: float, *, nonnegative=False,
                 check_lost_offset=False, budget=None) -> FloatArray:
    shape = input_shape(values,'time values')
    n = elements(shape)
    if not n:
        raise TectonicsError('nonempty time values required')
    with select_budget(budget).reserve(56*n+8192,category='time-conversion'):
        a = read_array(values,'time values',nonnegative=nonnegative)
        try:
            with np.errstate(over='raise',invalid='raise',under='ignore'):
                scaled = a * scale
                if np.any((a != 0) & (scaled == 0)):
                    raise TectonicsError('time scale underflows a nonzero value')
                result = scaled + offset
            if check_lost_offset and np.any((scaled != 0) & (result == offset)):
                raise TectonicsError('time offset loses a nonzero interval; use a nearer epoch')
            return frozen(result)
        except FloatingPointError as exc:
            raise TectonicsError('time conversion exceeds binary64 range') from exc


@dataclass(frozen=True, slots=True)
class TimeAxis:
    """Mapping t_s = zero_time_s + direction * value * unit.seconds_per_unit.

    direction='before' is a geological look-back axis, not reverse integration.
    zero_time_s identifies its reference instant within epoch_id (e.g. the chosen
    model 'present'). Durations never reverse sign; derivatives with respect to a
    before-axis do. Callers must use convert() for cross-axis timestamps.
    """
    epoch_id: str
    unit: TimeUnit
    zero_time_s: float
    direction: str = 'forward'

    def __post_init__(self) -> None:
        _label(self.epoch_id,'epoch_id')
        if type(self.unit) is not TimeUnit:
            raise TectonicsError('explicit fixed TimeUnit required')
        object.__setattr__(self,'zero_time_s',scalar(self.zero_time_s,'zero_time_s'))
        if self.direction not in ('forward','before'):
            raise TectonicsError('direction must be forward or before')

    @property
    def _sign(self) -> float:
        return 1. if self.direction == 'forward' else -1.

    def descriptor(self) -> dict:
        return {'schema':'atlas.time-axis.v1','epoch_id':self.epoch_id,
                'unit':self.unit.descriptor(),'zero_time_s':self.zero_time_s,
                'direction':self.direction,'internal_time':'SI seconds increasing forward'}

    @property
    def identity(self) -> str:
        return _identity(self.descriptor())

    def to_seconds(self, values, *, budget=None) -> FloatArray:
        """Convert coordinates to forward timestamps; reject wholly lost intervals."""
        return _affine_time(values,self._sign*self.unit.seconds_per_unit,self.zero_time_s,
                            check_lost_offset=True,budget=budget)

    def from_seconds(self, times_s, *, budget=None) -> FloatArray:
        """Interpret times_s in THIS epoch. Subtract origin before dividing for range."""
        shape = input_shape(times_s,'timestamps'); n = elements(shape)
        if not n: raise TectonicsError('nonempty timestamps required')
        with select_budget(budget).reserve(56*n+8192,category='time-conversion'):
            values = read_array(times_s,'timestamps')
            try:
                with np.errstate(over='raise',invalid='raise',under='ignore'):
                    delta = values - self.zero_time_s
                    result = delta / self.unit.seconds_per_unit * self._sign
                if np.any((delta != 0) & (result == 0)):
                    raise TectonicsError('timestamp difference underflows selected time unit')
                return frozen(result)
            except FloatingPointError as exc:
                raise TectonicsError('timestamp difference exceeds binary64 range') from exc

    def convert(self, values, target: TimeAxis, *, epoch_offset: EpochOffset | None = None,
                budget=None) -> FloatArray:
        """Direct axis conversion avoiding a huge intermediate absolute timestamp.

        A supplied inter-epoch correspondence must match both labels exactly. The
        checked mapping is included by callers in their invocation/source metadata.
        """
        if type(target) is not TimeAxis:
            raise TectonicsError('explicit target TimeAxis required')
        offset = 0.
        if epoch_offset is not None:
            if (type(epoch_offset) is not EpochOffset or
                    epoch_offset.source_epoch_id != self.epoch_id or
                    epoch_offset.target_epoch_id != target.epoch_id):
                raise TectonicsError('epoch correspondence does not match the axes')
            offset = epoch_offset.offset_s
        elif self.epoch_id != target.epoch_id:
            raise TectonicsError('different epochs require an explicit EpochOffset')
        try:
            # Accurate cancellation of supplied origin offsets before scaling.
            delta = math.fsum((self.zero_time_s,offset,-target.zero_time_s))
            scale = self._sign*target._sign * self.unit.seconds_per_unit/target.unit.seconds_per_unit
            shift = delta/target.unit.seconds_per_unit*target._sign
        except OverflowError as exc:
            raise TectonicsError('epoch mapping exceeds binary64 range') from exc
        if not math.isfinite(scale) or scale == 0 or not math.isfinite(shift):
            raise TectonicsError('time-axis scale outside supported binary64 range')
        if delta != 0 and shift == 0:
            raise TectonicsError('epoch shift underflows the target unit')
        return _affine_time(values,scale,shift,check_lost_offset=True,budget=budget)

    def duration_to_seconds(self, duration, *, budget=None) -> FloatArray:
        """Positive elapsed time is independent of a look-back axis's orientation."""
        return _affine_time(duration,self.unit.seconds_per_unit,0.,nonnegative=True,budget=budget)

    def rate_to_per_second(self, rate_per_axis_unit, *, budget=None) -> FloatArray:
        """Convert derivatives to forward-SI-time rates, including before-axis sign."""
        reciprocal = self._sign/self.unit.seconds_per_unit
        if not math.isfinite(reciprocal) or reciprocal == 0:
            raise TectonicsError('time-unit reciprocal outside binary64 range')
        return _affine_time(rate_per_axis_unit,reciprocal,0.,budget=budget)


def advance_time(time_s: float, duration_s: float) -> float:
    """Advance an absolute timestamp without silently accepting a lost positive step.

    Use this admission helper before expensive state construction. It does not
    change W02's existing time interpretation or relabel historical epochs.
    """
    start = scalar(time_s,'time_s')
    duration = scalar(duration_s,'duration_s',nonnegative=True)
    end = scalar(start+duration,'end_time_s')
    if duration > 0 and end <= start:
        raise TectonicsError('positive interval is not resolvable at this epoch; choose a nearer epoch')
    return end
