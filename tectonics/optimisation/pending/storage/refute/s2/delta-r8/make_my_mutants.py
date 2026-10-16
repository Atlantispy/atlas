"""Own planted mutants of r8 ledger_fresh_interval.py (copy into delta-r8/m/<name>/ with the r8 tests)."""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2]/'s2/r8'
FILES = ('compact_restart_patch.py', 'ledger_fresh_interval.py', 'test_ledger_fresh_interval.py',
         'test_step8_coverage.py', 'test_wp16_preadvance.py')
MID = "                require(read <= size, 'legacy pre-advance capture changed while it was read: '+str(path))\n"
FIN = "    require(read == size, 'legacy pre-advance capture changed while it was read: '+str(path))\n"
M = {
 'd1_no_midloop_size_check': [(MID, '')],
 'd2_no_final_size_check': [(FIN, '')],
 'd3_no_size_checks': [(MID, ''), (FIN, '')],
 'w1_lstrip_whitespace': [("data = data.lstrip(b'"+chr(92)+"0')", "data = data.lstrip()")],
 'b1_block_1p5_mib': [("handle.read(1 << 20)", "handle.read(3 << 19)")],
 'b2_block_2_mib': [("handle.read(1 << 20)", "handle.read(1 << 21)")],
 'y1_padding_end_not_handled': [("                            if not data:"+chr(10)+"                                break"+chr(10), "")],
 'y4_read_count_wrong': [("read += len(data)", "read += 1")],
 'y6_accept_zlib_format': [("zlib.decompressobj(wbits=31)", "zlib.decompressobj(wbits=47)")],
 'w2_lstrip_nul_and_space': [("data = data.lstrip(b'"+chr(92)+"0')", "data = data.lstrip(b'"+chr(92)+"0 "+chr(92)+"t"+chr(92)+"n')")],
 'x1_max_length_no_remaining': [("raw_bytes+1-len(out))", "raw_bytes+1)")],
 'x2_eof_check_skipped_on_block_end': [("    require(member is None, 'legacy pre-advance capture is not a whole gzip stream: '+str(path))\n",
                                        "    require(member is None or not out, 'legacy pre-advance capture is not a whole gzip stream: '+str(path))\n")],
 'x3_ended_not_set_on_eof_with_unused': [("data, member, ended = member.unused_data, None, True",
                                          "data, member, ended = member.unused_data, None, not member.unused_data")],
 'x4_raw_exact_off_by_one': [("raw_bytes+1-len(out)", "raw_bytes+2-len(out)")],
 'x5_exceeds_gt_to_ge': [("require(len(out) <= raw_bytes, 'legacy pre-advance capture exceeds", "require(len(out) < raw_bytes or not out, 'legacy pre-advance capture exceeds")],
 'x6_padding_allows_leading_zero_when_empty_out': [("                        if ended:  # zero padding", "                        if ended or not out:  # zero padding")],
}
only = sys.argv[1:]
for name, edits in M.items():
    if only and name not in only:
        continue
    text = (SRC/'ledger_fresh_interval.py').read_text(encoding='utf8')
    for old, new in edits:
        assert text.count(old) == 1, (name, old[:50], text.count(old))
        text = text.replace(old, new)
    compile(text, name, 'exec')
    folder = HERE/'m'/name
    folder.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copyfile(SRC/f, folder/f)
    (folder/'ledger_fresh_interval.py').write_text(text, encoding='utf8', newline='\n')
    print('planted', name)
