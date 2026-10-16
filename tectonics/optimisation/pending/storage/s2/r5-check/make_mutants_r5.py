"""S2 r5 planted mutants: one changed route or bound each; seams must occur exactly once; every mutant compiles.

Writes r5-check/mutants/<name>/ with both r5 modules (one mutated) and the three r5 test modules.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R5 = HERE.parent/'r5'
TESTS = ('test_wp16_preadvance.py', 'test_ledger_fresh_interval.py', 'test_step8_coverage.py')
CRP, LG = 'compact_restart_patch.py', 'ledger_fresh_interval.py'

MUTANTS = {
    # compact_restart_patch.require_capture_route
    'c1_find_spec_only': (CRP, [("    import importlib\n    try:", "    import importlib.util\n    try:"),
                                ("            importlib.import_module(name)\n",
                                 "            if importlib.util.find_spec(name) is None:\n"
                                 "                raise ImportError(name)\n")]),
    'c2_checks_every_store': (CRP, [("    if not is_compact_restart_store(store):\n        return None\n", '')]),
    'c3_no_library_load': (CRP, [("    return capture_backend().library_sha256\n", "    return CAPTURE_LIBRARY_SHA256\n")]),
    'c4_import_time_capture': (CRP, [("import sys\n", "import sys\nimport capture_store  # noqa: F401\n")]),
    'c5_subclass_accepted': (CRP, [("    from compact_restart_store import is_compact_restart_store\n"
                                    "    if not is_compact_restart_store(store):\n",
                                    "    from compact_restart_store import CompactRestartStore\n"
                                    "    if not isinstance(store, CompactRestartStore):\n")]),
    'c6_route_error_swallowed': (CRP, [("        raise ImportError('WP16 pre-advance capture route incomplete: '+str(error)) from error\n",
                                        "        return None\n")]),
    # ledger_fresh_interval.captured_bytes / capture
    'l1_no_raw_ceiling': (LG, [("0 <= raw_bytes <= CAPTURE_MAX_BYTES and", "0 <= raw_bytes and")]),
    'l2_no_stored_ceiling': (LG, [("            0 < stored_bytes <= CAPTURE_MAX_BYTES,\n", "            0 < stored_bytes,\n")]),
    'l3_no_container_form': (LG, [("    require(type(container_sha256) is str and len(container_sha256) == 64 and set(container_sha256) <= _HEX,\n"
                                   "            'capture receipt container_sha256 required (64 lowercase hex): '+str(path))\n", '')]),
    'l4_no_size_equality': (LG, [("    require(Path(path).stat().st_size == stored_bytes, 'pre-advance capture size differs from its receipt: '+str(path))\n", '')]),
    'l5_allocate_first': (LG, [("    try:\n        from atlas_tectonics.resources import WorkBudget\n",
                                "    _early = bytearray(raw_bytes) if type(raw_bytes) is int else None\n"
                                "    try:\n        from atlas_tectonics.resources import WorkBudget\n")]),
    'l6_legacy_eof_uncaught': (LG, [("        except (EOFError, zlib.error) as error:", "        except zlib.error as error:")]),
    'l7_legacy_zlib_uncaught': (LG, [("        except (EOFError, zlib.error) as error:", "        except EOFError as error:")]),
    'l8_hex_any_case': (LG, [("set(container_sha256) <= _HEX", "set(container_sha256.lower()) <= _HEX")]),
}


def main():
    root = HERE/'mutants'
    for name, (module, edits) in MUTANTS.items():
        text = (R5/module).read_text(encoding='utf8')
        for old, new in edits:
            if text.count(old) != 1:
                sys.exit('%s: seam count %d: %r' % (name, text.count(old), old[:70]))
            text = text.replace(old, new)
        compile(text, name, 'exec')
        folder = root/name
        folder.mkdir(parents=True, exist_ok=False)
        for other in (CRP, LG)+TESTS:
            shutil.copyfile(R5/other, folder/other)
        (folder/module).write_text(text, encoding='utf8', newline='\n')
        print('planted', name)


if __name__ == '__main__':
    main()
