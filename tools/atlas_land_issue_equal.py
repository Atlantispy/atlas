"""Use a selected native issuer for a change with the same member roster."""

import argparse
from hashlib import sha256
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_land import decode, digest, fingerprint, require, save
from atlas_land_export import selected


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for option in ("input-tree", "output-tree", "report", "settings", "composition"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--composition-sha256", required=True)
    args = parser.parse_args()
    settings = args.settings.resolve()
    spec = decode(settings.read_bytes())
    _, issuer = selected(spec["issuer"], settings)
    parent = (settings.parent / spec["parent"]).resolve(strict=True)
    require(parent.is_dir(), "Selected native parent is not a directory")
    require(re.fullmatch(r"[0-9a-f]{64}", spec["parent_tree"]), "Native parent requires a full SHA-256")
    issuer.C1 = parent
    issuer.C1_DIGEST = spec["parent_tree"]

    composition_bytes = args.composition.read_bytes()
    require(sha256(composition_bytes).hexdigest() == args.composition_sha256, "Reviewed composition report differs")
    reviewed = decode(composition_bytes)
    input_root = args.input_tree.resolve()
    require(Path(reviewed["root"]).resolve() == input_root, "Reviewed composition root differs")
    expected = reviewed["members"]
    read_members = issuer.files
    source_tree = None

    def checked_members(root):
        nonlocal source_tree
        files = read_members(root)
        if root == input_root:
            require(files.keys() == expected.keys(), "Reviewed composition member roster differs")
            for name, data in files.items():
                require(sha256(data).hexdigest() == expected[name], f"Reviewed composition member differs: {name}")
            source_tree = fingerprint(expected)
            require(source_tree == reviewed["tree"], "Reviewed composition tree differs")
        return files

    issuer.files = checked_members
    old_report_path = args.report.with_name("issuer-native.json")
    output_tree = args.output_tree.resolve()
    issuer.main(input_root, args.output_tree, old_report_path)
    require(source_tree is not None, "Selected issuer did not read the reviewed composition")
    raw = decode(old_report_path.read_bytes())

    def artifact(relative):
        path = (output_tree / relative).resolve(strict=True)
        require(path.is_relative_to(output_tree), "Issued artifact escaped the native tree")
        return {"path": str(path), "sha256": digest(path)}

    diff = spec["diff"]
    diff_path = (settings.parent / diff["path"]).resolve(strict=True)
    require(digest(diff_path) == diff["sha256"], "Reviewed landing diff differs")
    save(args.report, {
        "source_tree": source_tree, "native": str(output_tree), "native_tree_sha256": raw["tree"],
        "diff": {**diff, "path": str(diff_path)}, "declaration": artifact(spec["declaration"]),
        "seal": artifact(spec["seal"]), "record": artifact(spec["record"]),
        "version_disposition": spec["version_disposition"],
    })


if __name__ == "__main__":
    main()
