"""Differential fuzz: S/r8 ledger_fresh_interval.legacy_bytes vs gzip.decompress.

The module's one block literal (handle.read(1 << 20)) is replaced by a variable so small chunk sizes put every
boundary inside headers, trailers and padding. A spy on zlib asserts max_length >= 1 and bounds the call count.
Deterministic seeds; writes only under T/so/refute/s2/delta-r8/w.
"""
import gzip
import importlib.util
import os
import random
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = HERE.parents[3]
SRC = T/'so/s2/r8/ledger_fresh_interval.py'
WORK = HERE/'w'
WORK.mkdir(exist_ok=True)

LITERAL = 'data = handle.read(1 << 20)'


class SpyObj:
    def __init__(self, real, stats):
        self.real, self.stats = real, stats

    def decompress(self, data, max_length=0):
        assert type(max_length) is int and max_length >= 1, 'max_length %r' % (max_length,)
        self.stats['calls'] += 1
        assert self.stats['calls'] <= self.stats['limit'], 'call count exceeded: infinite loop?'
        return self.real.decompress(data, max_length)

    eof = property(lambda self: self.real.eof)
    unused_data = property(lambda self: self.real.unused_data)
    unconsumed_tail = property(lambda self: self.real.unconsumed_tail)


class SpyZlib:
    error = zlib.error

    def __init__(self, stats):
        self.stats = stats

    def decompressobj(self, wbits):
        return SpyObj(zlib.decompressobj(wbits=wbits), self.stats)


def load(block):
    text = SRC.read_text(encoding='utf8')
    assert text.count(LITERAL) == 1
    text = text.replace(LITERAL, 'data = handle.read(%d)' % block)
    spec = importlib.util.spec_from_loader('lg_%d' % block, loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(text, str(SRC), 'exec'), module.__dict__)
    stats = {'calls': 0, 'limit': 0}
    module.zlib = SpyZlib(stats)
    return module, stats


def member(rng, payload, shape):
    level = rng.choice((0, 1, 6, 9))
    co = zlib.compressobj(level, zlib.DEFLATED, -15)
    body = co.compress(payload)+co.flush()
    flg = 0
    parts = []
    if shape == 'plain':
        return gzip.compress(payload, compresslevel=level, mtime=rng.randrange(1 << 32))
    head = b'\x1f\x8b\x08'
    flags = 0
    extra = name = comment = None
    if rng.random() < .5:
        flags |= 4
        extra = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
    if rng.random() < .5:
        flags |= 8
        name = bytes(rng.randrange(1, 256) for _ in range(rng.randrange(0, 30)))+b'\0'
    if rng.random() < .5:
        flags |= 16
        comment = bytes(rng.randrange(1, 256) for _ in range(rng.randrange(0, 30)))+b'\0'
    if rng.random() < .5:
        flags |= 2
    if rng.random() < .3:
        flags |= 1
    header = head+bytes([flags])+struct.pack('<IBB', rng.randrange(1 << 32), 0, 3)
    if extra is not None:
        header += struct.pack('<H', len(extra))+extra
    if name is not None:
        header += name
    if comment is not None:
        header += comment
    if flags & 2:
        header += struct.pack('<H', zlib.crc32(header) & 0xffff)
    return header+body+struct.pack('<II', zlib.crc32(payload), len(payload) & 0xffffffff)


def payload(rng):
    kind = rng.randrange(4)
    if kind == 0:
        return b''
    if kind == 1:
        return bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
    if kind == 2:
        return (b'abcab' * rng.randrange(1, 400))[:rng.randrange(1, 2000)]
    return bytes(rng.randrange(4) for _ in range(rng.randrange(1, 3000)))


def case(rng):
    members = [member(rng, payload(rng), rng.choice(('plain', 'custom'))) for _ in range(rng.choice((0, 1, 1, 2, 2, 3, 4)))]
    data = b''
    if rng.random() < .08:
        data += bytes(rng.randrange(1, 6))
    for index, one in enumerate(members):
        data += one
        if index+1 < len(members) or rng.random() < .3:
            data += bytes(rng.choice((0, 0, 1, 2, 5, 9)))
    tag = 'ok'
    roll = rng.random()
    if roll < .12 and data:
        data = data[:rng.randrange(len(data))]
        tag = 'trunc'
    elif roll < .24 and data:
        index = rng.randrange(len(data))
        data = data[:index]+bytes([data[index] ^ (1 << rng.randrange(8))])+data[index+1:]
        tag = 'flip'
    elif roll < .32:
        data += rng.choice((b'\x1f', b'\x1f\x8b', b'xyz', b'\x1f\x8b\x08', b'\x1f\x8b\x08\x00', bytes(3)+b'q'))
        tag = 'tail'
    return tag, data


def oracle(data):
    try:
        return True, gzip.decompress(data)
    except Exception as error:  # noqa
        return False, type(error).__name__


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    blocks = (1, 2, 3, 5, 7, 11, 64, 1 << 20)
    path = WORK/'case.bin'
    mods = {block: load(block) for block in blocks}
    stats = {'cases': 0, 'calls': 0, 'agree_ok': 0, 'agree_refuse': 0, 'bound_refuse': 0, 'looser': [], 'stricter': [],
             'bytes_differ': [], 'other_exc': [], 'bound_wrong': [], 'spy': []}
    for seed in range(seeds):
        rng = random.Random(seed)
        tag, data = case(rng)
        ok, expected = oracle(data)
        path.write_bytes(data)
        # block sizes that land exactly on member ends (first member boundary) as well
        extra_blocks = {}
        for block in blocks:
            module, spy = mods[block]
            raws = [0, 3, 10**6] if not ok else sorted({len(expected), len(expected)+7, max(len(expected)-1, 0)})
            for raw in raws:
                spy['calls'], spy['limit'] = 0, 8*len(data)+50
                stats['calls'] += 1
                try:
                    got = bytes(module.legacy_bytes(path, raw))
                    result = ('ok', got)
                except module.LedgerRefused as error:
                    result = ('refused', str(error))
                except AssertionError as error:
                    stats['spy'].append((seed, block, raw, str(error)))
                    continue
                except Exception as error:  # noqa
                    stats['other_exc'].append((seed, block, raw, type(error).__name__, str(error)[:80]))
                    continue
                if ok:
                    if raw >= len(expected):
                        if result[0] == 'ok':
                            if result[1] != expected:
                                stats['bytes_differ'].append((seed, block, raw))
                            else:
                                stats['agree_ok'] += 1
                        else:
                            stats['stricter'].append((seed, block, raw, tag, result[1][:90]))
                    else:  # raw < len(expected): must refuse with the raw_bytes message
                        if result[0] == 'refused' and 'exceeds its receipt raw_bytes' in result[1]:
                            stats['bound_refuse'] += 1
                        else:
                            stats['bound_wrong'].append((seed, block, raw, result[0], result[1][:90] if result[0] == 'refused' else ''))
                else:
                    if result[0] == 'ok':
                        stats['looser'].append((seed, block, raw, tag, expected))
                    else:
                        stats['agree_refuse'] += 1
        stats['cases'] += 1
    for key, value in stats.items():
        if isinstance(value, list):
            print(key, len(value), value[:6])
        else:
            print(key, value)


if __name__ == '__main__':
    main()
