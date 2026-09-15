"""Forecast-only parallel eligibility, before executing any calibration jobs.

``expected_seconds`` is the caller's estimate for the planned run in serial,
not an observed timing, an estimate per job, or a promise of parallel savings.
The executor submits only uncached jobs whose dependencies are already ready.
"""
import math
import time

from work.generator_upgrade_r25.adaptive import AdaptiveBackend


def _duration(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(name + ' must be a finite number')
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ValueError(name + ' must be a finite number') from None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(name + ' must be finite and ' + ('positive' if positive else 'nonnegative'))
    return value


class ForecastBackend(AdaptiveBackend):
    def __init__(self, local_worker, pool, *, expected_seconds=None,
                 parallel_threshold_s=120, startup_budget_s=1.5,
                 clock=time.perf_counter):
        expected = None if expected_seconds is None else _duration(
            expected_seconds, 'expected_seconds')
        threshold = _duration(parallel_threshold_s, 'parallel_threshold_s', positive=True)
        super().__init__(local_worker, pool, startup_budget_s=startup_budget_s, clock=clock)
        self._expected_seconds, self._parallel_threshold_s = expected, threshold
        self._reason = 'NO_UNCACHED_READY_JOBS'

    @property
    def selection(self):
        return {
            'decision': self._decision,
            'reason': self._reason,
            'promoted': self._promoted,
            'policy': 'FORECAST_PLANNED_SERIAL_DURATION',
            'expected_seconds': self._expected_seconds,
            'parallel_threshold_s': self._parallel_threshold_s,
            'estimate_scope': 'PLANNED_RUN_SERIAL_DURATION',
            'estimate_basis': ('CALLER_SUPPLIED_ESTIMATE' if self._expected_seconds is not None
                               else 'NOT_SUPPLIED'),
            'estimate_is_measured': False,
            'sample_runs_required': 0,
            'observed_timings_used_for_selection': False,
            'local_executed_stage_ids': list(self._local_ids),
        }

    def _should_promote(self):
        if self._capacity < 2:
            self._reason = 'CANDIDATE_CAPACITY_ONE'
        elif len(self._queue) < 2:
            self._reason = 'FEWER_THAN_TWO_READY_JOBS'
        elif self._expected_seconds is None:
            self._reason = 'NO_DURATION_ESTIMATE'
        elif self._expected_seconds <= self._parallel_threshold_s:
            self._reason = 'EXPECTED_DURATION_NOT_ABOVE_THRESHOLD'
        else:
            self._decision, self._reason = 'PARALLEL', 'EXPECTED_DURATION_ABOVE_THRESHOLD'
            return True
        return False
