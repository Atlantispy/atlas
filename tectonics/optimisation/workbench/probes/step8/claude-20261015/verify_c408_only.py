"""Prove the live content_cache.py differs from the recorded D2-A hash only by the C408 edit.

Reverses the 02:26 dict-literal edit (Ruff C408) on the live text and checks the
result hashes to the D2-A hash recorded at 02:24 (8a41d97e...). Read-only.
"""
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE.parents[2]/'compact-geometry-r1'/'content_cache.py'
RECORDED = '8a41d97ee442439cc53c70fe7b74ca0dbf79da5ae33144507baa43e11fc530f9'
NEW = """            producer = {'producer_limit_bytes': self._producer_limit,
                        'producer_bytes': own['reserved_bytes'],
                        'producer_peak_bytes': own['peak_reserved_bytes'],
                        'producer_refusals': own['refusals'],
                        'producer_purpose_bytes': MappingProxyType(own['categories']),
                        'producer_purpose_peak_bytes': MappingProxyType(own['category_peaks'])}"""
OLD = """            producer = dict(producer_limit_bytes=self._producer_limit,
                producer_bytes=own['reserved_bytes'], producer_peak_bytes=own['peak_reserved_bytes'],
                producer_refusals=own['refusals'],
                producer_purpose_bytes=MappingProxyType(own['categories']),
                producer_purpose_peak_bytes=MappingProxyType(own['category_peaks']))"""


def main():
    raw = LIVE.read_bytes()
    text = raw.decode('utf8')
    crlf = '\r\n' in text
    new, old = (NEW.replace('\n', '\r\n'), OLD.replace('\n', '\r\n')) if crlf else (NEW, OLD)
    if text.count(new) != 1:
        raise SystemExit('C408 edit not found exactly once')
    reversed_hash = sha256(text.replace(new, old).encode('utf8')).hexdigest()
    print('live', sha256(raw).hexdigest())
    print('live with C408 edit reversed', reversed_hash)
    print('equals recorded D2-A hash:', reversed_hash == RECORDED)


if __name__ == '__main__':
    main()
