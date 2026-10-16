"""The owner's narrow delta+zstd space/time exception; no enabling side effects.

Callers still validate all real-class adoption, exactness and workspace gates.
The report owner authenticates the supplied report identity and observations.
"""
from decimal import Decimal
import math
import re


TRADEOFF_ID = 'wp10-delta-zstd-space-tradeoff-20261015'
TRADEOFF_FIELDS = frozenset({
    'tradeoff_id', 'comparator_codec', 'comparator_level', 'comparator_shuffle',
    'comparator_physical_bytes', 'candidate_physical_bytes',
})
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def _time(value, name):
    try:
        valid = type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(name + ' must be a finite nonnegative number')
    return value


def time_gate_passes(codec, level, shuffle, evidence):
    """Return the ordinary time gate or the explicitly qualified exception.

    Missing/malformed exception evidence raises ValueError. Complete valid
    evidence outside its 20% space / 8.75% time envelope returns False. Decimal
    time inputs are interpreted using Python's shortest round-trip spelling,
    then compared as integers so the documented decimal boundary is inclusive.
    """
    if type(evidence) is not dict:
        raise ValueError('adoption evidence must be a plain mapping')
    baseline = _time(evidence.get('baseline_total_seconds'), 'baseline total')
    candidate = _time(evidence.get('candidate_total_seconds'), 'candidate total')
    present = TRADEOFF_FIELDS.intersection(evidence)
    if not present:
        return candidate < baseline
    if present != TRADEOFF_FIELDS:
        raise ValueError('complete accepted-tradeoff evidence required')
    if (type(evidence['tradeoff_id']) is not str or evidence['tradeoff_id'] != TRADEOFF_ID or type(codec) is not str
            or codec != 'delta-zstd-v1' or type(level) is not int or level != 1
            or type(shuffle) is not str or shuffle != 'byte'
            or type(evidence['comparator_codec']) is not str or evidence['comparator_codec'] != 'zstd'
            or type(evidence['comparator_level']) is not int
            or evidence['comparator_level'] != 1 or type(evidence['comparator_shuffle']) is not str
            or evidence['comparator_shuffle'] != 'byte'):
        raise ValueError('accepted tradeoff applies only to delta-zstd-v1 byte/1 versus zstd byte/1')
    report = evidence.get('report_sha256')
    if (evidence.get('scope') != 'real' or type(report) is not str
            or not _SHA.fullmatch(report) or baseline <= 0):
        raise ValueError('accepted tradeoff requires a real report identity and positive baseline')
    before, after = evidence['comparator_physical_bytes'], evidence['candidate_physical_bytes']
    if type(before) is not int or type(after) is not int or before <= 0 or after <= 0:
        raise ValueError('accepted tradeoff physical sizes must be positive integers')
    base_n, base_d = Decimal(str(baseline)).as_integer_ratio()
    cand_n, cand_d = Decimal(str(candidate)).as_integer_ratio()
    return after * 5 <= before * 4 and cand_n * base_d * 80 <= base_n * cand_d * 87
