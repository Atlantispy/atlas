"""S2 r6 planted mutants: r5's c1-c6 and l1-l8 rebased onto r6 (the legacy l6/l7 now on legacy_bytes), plus one per
r6 change (c7, l9-l18). Seams must occur exactly once; every mutant compiles.

Writes r6-check/mutants/<name>/ with both r6 modules (one mutated) and the three r6 test modules.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R6 = HERE.parent/'r6'
TESTS = ('test_wp16_preadvance.py', 'test_ledger_fresh_interval.py', 'test_step8_coverage.py')
CRP, LG = 'compact_restart_patch.py', 'ledger_fresh_interval.py'
GUARD = "    if crs is None or not crs.is_compact_restart_store(store):\n"
MINIMUM = "            PREAMBLE.size+32+FOOTER.size <= stored_bytes <= CAPTURE_MAX_BYTES,\n"

MUTANTS = {
    # compact_restart_patch.require_capture_route
    'c1_find_spec_only': (CRP, [("    import importlib\n    try:", "    import importlib.util\n    try:"),
                                ("            importlib.import_module(name)\n",
                                 "            if importlib.util.find_spec(name) is None:\n"
                                 "                raise ImportError(name)\n")]),
    'c2_checks_every_store': (CRP, [(GUARD+"        return None\n", '')]),
    'c3_no_library_load': (CRP, [("    return capture_backend().library_sha256\n", "    return CAPTURE_LIBRARY_SHA256\n")]),
    'c4_import_time_capture': (CRP, [("import sys\n", "import sys\nimport capture_store  # noqa: F401\n")]),
    'c5_subclass_accepted': (CRP, [(GUARD, "    if crs is None or not isinstance(store, crs.CompactRestartStore):\n")]),
    'c6_route_error_swallowed': (CRP, [("        raise ImportError('WP16 pre-advance capture route incomplete: '+str(error)) from error\n",
                                        "        return None\n")]),
    'c7_route_imports_store': (CRP, [("    crs = sys.modules.get('compact_restart_store')\n",
                                      "    import compact_restart_store as crs\n")]),
    # ledger_fresh_interval.captured_bytes / _container_pinned
    'l1_no_raw_ceiling': (LG, [("0 <= raw_bytes <= CAPTURE_MAX_BYTES and", "0 <= raw_bytes and")]),
    'l2_no_stored_ceiling': (LG, [(MINIMUM, "            PREAMBLE.size+32+FOOTER.size <= stored_bytes,\n")]),
    'l3_no_container_form': (LG, [("    require(type(container_sha256) is str and len(container_sha256) == 64 and set(container_sha256) <= _HEX,\n"
                                   "            'capture receipt container_sha256 required (64 lowercase hex): '+str(path))\n", '')]),
    'l4_no_size_equality': (LG, [("    require(Path(path).stat().st_size == stored_bytes, 'pre-advance capture size differs from its receipt: '+str(path))\n", '')]),
    'l5_allocate_first': (LG, [("    try:\n        from atlas_tectonics.resources import WorkBudget\n",
                                "    _early = bytearray(raw_bytes) if type(raw_bytes) is int else None\n"
                                "    try:\n        from atlas_tectonics.resources import WorkBudget\n")]),
    'l8_hex_any_case': (LG, [("set(container_sha256) <= _HEX", "set(container_sha256.lower()) <= _HEX")]),
    'l9_allocate_before_hash': (LG, [("    _container_pinned(path, container_sha256, raw_bytes, stored_bytes, FOOTER)\n"
                                      "    buffer, filled = bytearray(raw_bytes), 0\n",
                                      "    buffer, filled = bytearray(raw_bytes), 0\n"
                                      "    _container_pinned(path, container_sha256, raw_bytes, stored_bytes, FOOTER)\n")]),
    'l10_no_footer_check': (LG, [("    require(tag == b'F' and footer_raw_bytes == raw_bytes,\n", "    require(tag == b'F',\n")]),
    'l15_no_container_compare': (LG, [("    require(digest.hexdigest() == container_sha256, ", "    require(True, ")]),
    'l16_no_format_minimum': (LG, [(MINIMUM, "            0 < stored_bytes <= CAPTURE_MAX_BYTES,\n")]),
    # ledger_fresh_interval.capture / legacy_bytes
    'l6_legacy_eof_unchecked': (LG, [("            require(member.eof, 'legacy pre-advance capture is not a whole gzip stream: '"
                                      "+str(path))\n", '')]),
    'l7_legacy_zlib_uncaught': (LG, [("    except zlib.error as error:  # a damaged r9 operand",
                                      "    except EOFError as error:  # a damaged r9 operand")]),
    'l11_path_not_contained': (LG, [("    require(type(name) is str and name not in ('', '.', '..') and Path(name).name == name,\n"
                                     "            'pre-advance capture path must be a plain file name: %r' % (name,))\n", '')]),
    'l12_legacy_unbounded': (LG, [("            out += member.decompress(data, raw_bytes+1-len(out))\n",
                                   "            out += member.decompress(data)\n")]),
    'l13_gzip_bytes_unchecked': (LG, [("    require(gzip_bytes is None or (type(gzip_bytes) is int and gzip_bytes == size),\n",
                                       "    require(True,\n")]),
    'l14_legacy_raw_unchecked': (LG, [("    require(type(raw_bytes) is int and 0 <= raw_bytes <= CAPTURE_MAX_BYTES,\n"
                                       "            'legacy capture", "    require(True,\n            'legacy capture")]),
    'l17_no_legacy_file_ceiling': (LG, [("    require(size <= CAPTURE_MAX_BYTES, 'legacy", "    require(True, 'legacy")]),
    'l18_dotdot_name': (LG, [("name not in ('', '.', '..') and ", "name not in ('', '.') and ")]),
}


def main():
    root = HERE/'mutants'
    for name, (module, edits) in MUTANTS.items():
        text = (R6/module).read_text(encoding='utf8')
        for old, new in edits:
            if text.count(old) != 1:
                sys.exit('%s: seam count %d: %r' % (name, text.count(old), old[:70]))
            text = text.replace(old, new)
        compile(text, name, 'exec')
        folder = root/name
        folder.mkdir(parents=True, exist_ok=False)
        for other in (CRP, LG)+TESTS:
            shutil.copyfile(R6/other, folder/other)
        (folder/module).write_text(text, encoding='utf8', newline='\n')
        print('planted', name)


if __name__ == '__main__':
    main()
