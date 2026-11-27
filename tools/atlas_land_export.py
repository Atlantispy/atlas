"""Use the home decoder and carry its thermal mesh through the same traversal."""

import argparse
import ast
from hashlib import sha256
from pathlib import Path
import sys
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_land import decode, require

MESH = "atlas.source-bound-exterior-thermal-mesh.v1"


def selected(reference, settings):
    path = (settings.parent / reference["path"]).resolve()
    source = path.read_bytes()
    require(sha256(source).hexdigest() == reference["sha256"], f"Export source fingerprint differs: {path}")
    namespace = ModuleType(path.stem)
    namespace.__file__ = str(path)
    exec(compile(source, str(path), "exec", dont_inherit=True), vars(namespace))
    return source.decode("utf-8"), namespace


def replace_once(text, before, after):
    require(text.count(before) == 1, f"Selected export interface changed: {before.strip()}")
    return text.replace(before, after, 1)


def write_mesh(store, scope, refs, out, index):
    try:
        from atlas_tectonics._private.codecs.compact_store import CompactMeshStoreV3
    except ModuleNotFoundError as error:
        if error.name != 'atlas_tectonics._private.codecs':
            raise
        from atlas_tectonics._private.compact_store import CompactMeshStoreV3

    require(len(refs) == 1, f"Expected one thermal mesh reference, found {len(refs)}")
    ref = refs[0]
    identity = ref.identity
    name = "mesh-000.json"
    mesh = CompactMeshStoreV3(store.store_set, scope=scope).open(ref, expected_geometry_id=identity.sha256)
    measured = sha256()
    size = 0
    try:
        with (out / name).open("xb") as file:
            for part in mesh.iter_legacy_json():
                measured.update(part)
                size += len(part)
                file.write(part)
    finally:
        mesh.close()
    require((measured.hexdigest(), size) == (identity.sha256, identity.canonical_bytes), "Exported mesh identity differs")
    index["records"].append({"record_schema": MESH, "sha256": identity.sha256, "canonical_bytes": size, "file": name})


def complete_export(source, decoder, home, output):
    definition, = (node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "export")
    lines = source.splitlines()
    function = "\n".join(lines[definition.lineno - 1:definition.end_lineno]) + "\n"
    function = replace_once(function, "        for n, wire in enumerate(segment_refs(out/'store')):",
                            "        meshes = []\n        for n, wire in enumerate(segment_refs(out/'store')):")
    function = replace_once(function, "            segment = SegmentBackend().open(store.store_set, ref, scope=scope)",
                            "            if ref.identity.record_schema == MESH:\n"
                            "                meshes.append(ref)\n"
                            "                continue\n"
                            "            segment = SegmentBackend().open(store.store_set, ref, scope=scope)")
    function = replace_once(function, "    finally:\n        store.close()", "        write_mesh(store, scope, meshes, out, index)\n"
                            "    finally:\n        store.close()")
    scope = dict(vars(decoder), write_mesh=write_mesh, MESH=MESH)
    exec(compile(function, decoder.__file__, "exec", dont_inherit=True), scope)
    scope["export"](home, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--settings", required=True, type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("complete", "mesh"):
        action = sub.add_parser(name)
        if name == "mesh":
            action.add_argument("decoded_export", type=Path)
        action.add_argument("home", type=Path)
        action.add_argument("output", type=Path)
    args = parser.parse_args()
    settings = args.settings.resolve()
    binding = decode(settings.read_bytes())
    if args.operation == "complete":
        source, decoder = selected(binding["decoder"], settings)
        complete_export(source, decoder, args.home, args.output)
    else:
        _, reader = selected(binding["mesh_reader"], settings)
        reader.main(args.home, args.decoded_export, args.output)


if __name__ == "__main__":
    main()
