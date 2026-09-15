"""Execute the R7 corrected hillslope successor from exact pinned bytes."""
import hashlib
from pathlib import Path
import stat
import sys
import types
import uuid

ROOT=Path(__file__).resolve().parent
PINS={'hillslope_kernel.py':'2b003cfdbbf4b59df9a8b731cad57ffb643aabafa86c0cdf9ac2892f60bbad9e',
      'NUMERICAL_CONTRACT.json':'131b131067b9d0c4327a4130ec1e2d15e88fe56ee4e19c7b5219b2cb1ae708e5'}


def _read(name):
    path=ROOT/name
    for part in (path,*path.parents):
        s=part.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
            raise ValueError('linked/reparse hillslope predecessor')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>16*1024*1024:
        raise ValueError('bounded plain hillslope predecessor required')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PINS[name]:raise ValueError('repaired-R2 hillslope source changed')
    return raw


RAW={name:_read(name) for name in PINS}
kernel=types.ModuleType('_r7_corrected_hillslope_'+uuid.uuid4().hex)
kernel.__file__=str(ROOT/'hillslope_kernel.py')
sys.modules[kernel.__name__]=kernel
exec(compile(RAW['hillslope_kernel.py'],kernel.__file__,'exec',dont_inherit=True,optimize=0),kernel.__dict__)


def verify():
    if sys.modules.get(kernel.__name__) is not kernel:raise ValueError('hillslope module identity changed')
    for name,raw in RAW.items():
        if _read(name)!=raw:raise ValueError('hillslope bytes changed after capture')
    return [{'name':'R7-corrected-hillslope/'+name,'bytes':len(raw),'sha256':PINS[name]}
            for name,raw in sorted(RAW.items())]


verify()
