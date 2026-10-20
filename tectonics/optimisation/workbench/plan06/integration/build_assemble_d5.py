"""Create an additive D5 successor of the exact retained assemble_r3 entry point.

Text construction only: no Atlas imports, composition, queue or runtime launch.
The output must be new. The resulting assembler retains its existing pin/compose
CLI and accepts an optional explicitly selected D5 contract (see CONTRACT.txt).
"""
import argparse
from hashlib import sha256
from pathlib import Path

BASE_SHA256 = "b9433b5a29946ecb0203599ab6a4a0ec06baef31cbd260c59193db5f9ba9ae80"
HERE = Path(__file__).resolve().parent


def build(raw, extension):
    if sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError("assembler source differs from the selected retained source")
    text = raw.decode("utf8")
    replacements = (
        ("def compose(pins=None):\n", extension + "\n\ndef compose(pins=None):\n"),
        (
            "    # boundary r2 (1): only selected files (with their pinned bytes) or the explicit exceptions took part\n",
            "    # Preserve every baseline byte for the original complete d2 parity assertion.\n"
            "    global PLAN06_D5_BASE_SOURCES\n"
            "    PLAN06_D5_BASE_SOURCES = dict(sources)\n"
            "    if PLAN06_D5 is not None:\n"
            "        plan06_apply_d5(sources, stage, replace, load)\n"
            "    if expected is not None:\n"
            "        require(next(expected, None) is None, 'unexpected remaining reviewed stage')\n"
            "    # boundary r2 (1): only selected files (with their pinned bytes) or the explicit exceptions took part\n",
        ),
        (
            "    for key, value in sources.items():\n"
            "        digest = text_sha(value) if isinstance(value, str) else sha256(value).hexdigest()\n"
            "        require(key == cold or dry_files.get(key) == digest, 'composition differs from the reviewed dry run: ' + key)\n"
            "    require(set(dry_files) == set(sources), 'composition file set differs from the reviewed dry run')",
            "    baseline = PLAN06_D5_BASE_SOURCES\n"
            "    for key, value in baseline.items():\n"
            "        digest = text_sha(value) if isinstance(value, str) else sha256(value).hexdigest()\n"
            "        require(key == cold or dry_files.get(key) == digest, 'composition differs from the reviewed dry run: ' + key)\n"
            "    require(set(dry_files) == set(baseline), 'composition file set differs from the reviewed dry run')",
        ),
        (
            "    files.update(loaded)\n",
            "    files.update(loaded)\n"
            "    if PLAN06_D5 is not None:\n"
            "        files.update({rel(path): pin for path, pin in PLAN06_D5_ASSETS.values()})\n",
        ),
        (
            "    args = parser.parse_args(argv)\n",
            "    parser.add_argument('--d5-contract')\n"
            "    parser.add_argument('--d5-contract-sha256')\n"
            "    args = parser.parse_args(argv)\n",
        ),
        (
            "    if args.check:\n",
            "    d5 = plan06_select_d5(args.d5_contract, args.d5_contract_sha256)\n"
            "    if d5 is not None:\n"
            "        staged['plan06_d5'] = d5\n"
            "    if args.check:\n",
        ),
    )
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError("assembler anchor missing or repeated: " + old[:100])
        text = text.replace(old, new)
    compile(text, "assemble_r3_plan06.py", "exec")
    return text.encode("utf8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = build(args.source.read_bytes(), (HERE / "d5_extension.txt").read_text(encoding="utf8"))
    # Exclusive file creation prevents overwriting any retained composer.
    with args.output.open("xb") as stream:
        stream.write(candidate)
    print(sha256(candidate).hexdigest(), str(args.output.resolve()))


if __name__ == "__main__":
    main()
