"""S2 r10 planted mutants: r9's 37 (r9-check/make_mutants_r9.py, unchanged seams) plus l31/l32 for the
module-relative library path, planted in the r10 modules with the r10 tests. Each mutant folder mirrors the
tree's layout: its compact-geometry-r1/native/wp10_zstd.dll is a hard link to r10's sha-checked copy.
Seams must occur exactly once; every mutant compiles. Writes r10-check/mutants/<name>/.
"""
import hashlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent/'r10'
LIBRARY = Path('compact-geometry-r1', 'native', 'wp10_zstd.dll')
LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'
spec = importlib.util.spec_from_file_location('make_mutants_r9', HERE.parent/'r9-check'/'make_mutants_r9.py')
R9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R9)
TESTS, CRP, LG = R9.TESTS, R9.CRP, R9.LG
PATH = "CAPTURE_LIBRARY = Path(__file__).resolve().parent/'compact-geometry-r1'"

MUTANTS = dict(R9.MUTANTS)
MUTANTS.update({
    # the library is taken from the module's own folder, not from wherever the process stands
    'l31_library_from_cwd': (CRP, [(PATH, "CAPTURE_LIBRARY = Path.cwd()/'compact-geometry-r1'")]),
    'l32_reader_library_from_cwd': (LG, [(PATH, "CAPTURE_LIBRARY = Path.cwd()/'compact-geometry-r1'")]),
})


def main():
    if hashlib.sha256((SOURCE/LIBRARY).read_bytes()).hexdigest() != LIBRARY_SHA256:
        sys.exit('r10 library copy changed: refusing')
    root = HERE/'mutants'
    for name, (module, edits) in MUTANTS.items():
        text = (SOURCE/module).read_text(encoding='utf8')
        for old, new in edits:
            if text.count(old) != 1:
                sys.exit('%s: seam count %d: %r' % (name, text.count(old), old[:70]))
            text = text.replace(old, new)
        compile(text, name, 'exec')
        folder = root/name
        folder.mkdir(parents=True, exist_ok=False)
        for other in (CRP, LG)+TESTS:
            shutil.copyfile(SOURCE/other, folder/other)
        (folder/module).write_text(text, encoding='utf8', newline='\n')
        (folder/LIBRARY).parent.mkdir(parents=True)
        os.link(SOURCE/LIBRARY, folder/LIBRARY)
    print('planted', len(MUTANTS))


if __name__ == '__main__':
    main()
