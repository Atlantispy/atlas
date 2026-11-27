"""The heat-finish door record (design heat-finish-save-point-r1.md 1b9cd010 part 1).

The forward kernel calls offer() with FINISH's ten inputs just before FINISH is entered. While ``folder`` is None
offer returns at once, so the kernel's code and ids are the same with the record on or off. The driver sets
``folder`` (the attempt's run folder) and ``context`` (plain fields for the record) before the advance and reads
``last`` after it. Lower-case values stay outside the loaded identity, which takes functions and upper-case values.

The record is read by the replay tool's door mode only; no part of the chain reads it. Floats are written as hex of
float(v), as FINISH takes them; exact values as [numerator, denominator] in hex, through FINISH's own conversion
(private_heat_finish_arithmetic_r1.rational), which reads such a pair back to the same number. Only a disk error is
caught (recorded in ``last``; the heat goes on); any other error stops the heat, as code inside it should.
The boundary and raw face entries retain their supplied order and values. A booking the budget refuses skips
the record, noted in
``last`` (FINISH's own first booking is far smaller, so the door must not be what stops the heat).
r3 (the Reviewer's B-1, ruled in the design 878db1f0): the booking is no fixed figure. Before anything is built, offer
sums the lengths of the texts it will write (the exact values' hex digits from their bit lengths, the floats' hex, the
ids, the context) and ALLOWANCE bytes for each entry, and books that sum times COPIES: at the peak the
body's lists, the JSON text and the text with its newline are held at once, then that text and its bytes (offer below).
r4 (the Reviewer, Addendum 6 N-2): ``last`` gives the seconds of the whole offer, for run.json; never in the record.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from contextlib import ExitStack

from atlas_tectonics._private.integration.heat import finish_arithmetic as ARITHMETIC
from atlas_tectonics.integration.resources import MemoryLimitError

SCHEMA = 'atlas.private.heat-door-record.r1'
NAME = 'heat-door-record.json'
COPIES = 3                       # held at once at the peak (offer: body + json.dumps text + text with its newline; then + bytes)
ALLOWANCE = 256                  # bytes per entry: a Python list and str heads in the body, the JSON's brackets, quotes
FLOAT_HEX = 24                   # longest float(v).hex(): '-0x1.' 13 digits 'p-1022'

folder = None                    # set by the driver before the advance; None: no record
context = None                   # plain fields from the driver, written as they are
last = None                      # this process's last offer: {'path', 'sha256', 'bytes', 'booked', 'seconds'}, {'error'} or {'skipped'}


def _exact(value):
    q = ARITHMETIC.rational(value)
    return [format(int(q.numerator), 'x'), format(int(q.denominator), 'x')]


def _hex_length(value):
    q = ARITHMETIC.rational(value)
    return sum(max(1, (abs(int(n)).bit_length() + 3) // 4) + (n < 0) for n in (q.numerator, q.denominator))


def _size(old, capacity, source, boundary, face_ids, low, high, target):
    """Bytes to book: the written texts' lengths plus ALLOWANCE an entry, times COPIES (nothing is built here)."""
    exact = [target, low['evidence']['absolute_target_decimal'], high['evidence']['absolute_target_decimal'],
             *low['energy']]
    raws = [e for view in (low, high) for raw in view['evidence']['raw_outward_energy_decimal'] for e in raw]
    text = (sum(_hex_length(v) for v in exact) + sum(_hex_length(e[2]) + len(str(e[0])) + len(str(e[1])) + 12 for e in raws)
            + FLOAT_HEX * (len(old) + len(capacity) + len(source) + len(boundary) + 1)
            + sum(len(str(fid)) + len(str(kind)) for fid, (kind, _) in dict(boundary).items())
            + sum(len(str(fid)) for fid in face_ids)
            + len(json.dumps(context)))
    entries = len(exact) + len(raws) + len(old) + len(capacity) + len(source) + 2 * len(boundary) + len(face_ids)
    return COPIES * (text + ALLOWANCE * entries)


def _view(view, energy):
    evidence = view['evidence']
    out = {'evidence': {'absolute_target_decimal': _exact(evidence['absolute_target_decimal']),
                        'raw_outward_energy_decimal': [[[int(i), middle, _exact(e)] for i, middle, e in raw]
                                                       for raw in evidence['raw_outward_energy_decimal']]}}
    if energy:
        out['energy'] = [_exact(e) for e in view['energy']]
    return out


def offer(old, capacity, dt, source, boundary, face_ids, low, high, target, *, budget):
    """Write FINISH's ten inputs to <folder>/heat-door-record.json, before FINISH runs."""
    global last
    if folder is None:
        return
    began = time.perf_counter()
    size = _size(old, capacity, source, boundary, face_ids, low, high, target)
    booking = ExitStack()
    try:
        booking.enter_context(budget.reserve(size, category='heat-door-record'))
    except MemoryLimitError as error:
        last = {'skipped': f'the budget refused {size} bytes: {error}'}
        return
    with booking:
        body = {'schema': SCHEMA, 'never_a_chain_result': True, 'context': context,
                'old': [float(v).hex() for v in old], 'capacity': [float(v).hex() for v in capacity],
                'source': [float(v).hex() for v in source], 'dt': float(dt).hex(), 'target': _exact(target),
                'boundary': [[str(fid), kind, float(value).hex()] for fid, (kind, value) in dict(boundary).items()],
                'face_ids': [str(fid) for fid in face_ids], 'low': _view(low, True), 'high': _view(high, False)}
        data = (json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
        body = None
        path = Path(folder)/NAME
        try:
            with open(path.with_suffix('.tmp'), 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path.with_suffix('.tmp'), path)
        except OSError as error:                     # a diagnosis: the heat goes on, the driver notes it
            last = {'error': f'{type(error).__name__}: {error}'}
            return
        last = {'path': str(path), 'sha256': sha256(data).hexdigest(), 'bytes': len(data), 'booked': size,
                'seconds': time.perf_counter() - began}


def read(path):
    """The record as FINISH's arguments (the replay tool's door mode): (args, kwargs-free extras)."""
    body = json.loads(Path(path).read_bytes())

    def exact(pair):
        return [int(pair[0], 16), int(pair[1], 16)]

    def view(v):
        out = {'evidence': {'absolute_target_decimal': exact(v['evidence']['absolute_target_decimal']),
                            'raw_outward_energy_decimal': [[(i, middle, exact(e)) for i, middle, e in raw]
                                                           for raw in v['evidence']['raw_outward_energy_decimal']]}}
        if 'energy' in v:
            out['energy'] = [exact(e) for e in v['energy']]
        return out
    floats = {n: [float.fromhex(x) for x in body[n]] for n in ('old', 'capacity', 'source')}
    boundary = {fid: (kind, float.fromhex(value)) for fid, kind, value in body['boundary']}
    args = (floats['old'], floats['capacity'], float.fromhex(body['dt']), floats['source'], boundary,
            body['face_ids'], view(body['low']), view(body['high']), exact(body['target']))
    return args, body['context']
