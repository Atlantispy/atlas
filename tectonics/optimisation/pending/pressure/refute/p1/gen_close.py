import sys
from contextlib import contextmanager
log = []
@contextmanager
def held():
    log.append('enter')
    try:
        yield
    finally:
        log.append('exit')
def gen(n):
    try:
        for i in range(n):
            yield i
    finally:
        log.append('gen-finally')
def stage():
    with held():
        for a, b in zip(range(3), gen(3)):
            if b == 1:
                raise KeyError('body')
try:
    stage()
except KeyError as e:
    keep = e   # traceback retained
print(sys.version.split()[0], log)
