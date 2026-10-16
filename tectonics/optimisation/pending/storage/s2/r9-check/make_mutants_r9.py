"""S2 r9 planted mutants: r8's 30 (from r8-check/make_mutants_r8.py, unchanged seams) plus l24-l30 for the r8
review's test findings, planted in the r9 modules with the r9 tests. Seams must occur exactly once; every
mutant compiles. Writes r9-check/mutants/<name>/ with both r9 modules (one mutated) and the three r9 test modules.
"""
import importlib.util
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent/'r9'
spec = importlib.util.spec_from_file_location('make_mutants_r8', HERE.parent/'r8-check'/'make_mutants_r8.py')
R8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R8)
TESTS, CRP, LG = R8.TESTS, R8.CRP, R8.LG
READ = "                data = handle.read(1 << 20)\n"
SIZE = "                require(read <= size, 'legacy pre-advance capture changed while it was read: '+str(path))\n"

MUTANTS = dict(R8.MUTANTS)
MUTANTS.update({
    # P3-c: the size the read began with
    'l24_no_midloop_size_check': (LG, [(SIZE, '')]),
    'l25_no_final_size_check': (LG, [("    require(read == size, 'legacy pre-advance capture changed while it was read: '"
                                      "+str(path))\n", '')]),
    # P3-d: accepts no more than gzip.decompress
    'l26_zlib_format_accepted': (LG, [('zlib.decompressobj(wbits=31)', 'zlib.decompressobj(wbits=47)')]),
    'l27_whitespace_padding': (LG, [("                            data = data.lstrip(b'\\0')\n",
                                     "                            data = data.lstrip(b'\\0 \\t\\n')\n")]),
    'l28_truncated_before_output': (LG, [("    require(member is None, 'legacy", "    require(member is None or not out, 'legacy")]),
    # P3-e: one block at a time over many
    'l29_blocks_kept': (LG, [("    out, member, ended, read = bytearray(), None, False, 0\n",
                              "    out, member, ended, read = bytearray(), None, False, 0\n    kept = []\n"),
                             (READ, READ+"                kept.append(data)\n")]),
    'l30_block_one_and_a_half_mib': (LG, [(READ, READ.replace('1 << 20', '3 << 19'))]),
})


def main():
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
    print('planted', len(MUTANTS))


if __name__ == '__main__':
    main()
