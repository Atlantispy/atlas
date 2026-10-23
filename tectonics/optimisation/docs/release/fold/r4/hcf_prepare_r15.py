"""Prepare the reviewed heat control on a frozen composition whose r13 issuer is a later revision (R2 proposal).

  python -B hcf_prepare_r15.py HCF COMPOSITION_JSON WORKDIR NATIVE_ROOT HELPERS_DIR [HELPERS_DIR ...]

heat_control_on_frozen.py (HCF) refuses every r13 but composed-r2's (EXPECTED_R13 dbaeecae). p20c-r1 carries Plan 20's
later r13. This loads HCF unchanged, checks its bytes and the composition record's bytes against the pins below, and
replaces exactly one value, EXPECTED_R13, with the r13 sha that the record names. HCF's prepare then runs as reviewed:
it still refuses any r13 that is not the recorded one, still needs the reference MARKER once, and still records the
value it checked in control.json. HCF's child is unchanged and needs no wrapper (it never reads EXPECTED_R13).

r14 (23 Oct): hcf_prepare_r13 with one change, the reviewed records: p20c-r1's and p20c-r2's (staged by Plan 20,
r11 accepted by the coordinator 23 Oct). Both name the same r13 issuer (10c40a13).

r15 (23 Oct): r14 with one change: the staged successor's composition record is accepted too: p20c-r4 (p20c-r3
was superseded before staging).
FOLD.md §13 item 6 planned a second replacement here: physical_cell_id added to HCF's KEY_FIELDS. It is not made.
KEY_FIELDS is read only by HCF's child (_save_cell_keys), never by prepare. A wrapper that ran HCF's child in its own
process would itself be a module loaded from the workspace outside the frozen layout, which HCF's child lists and
fails on. The cell keys with physical_cell_id are therefore saved by the arms harness (arms_r7, revision 7), at the
same return as HCF's saver.
"""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

HCF_SHA256 = 'eed6bf241a843537746ce8b643c83635489089d0959e2b112fa8983724461f76'
COMPOSITION_SHA256 = ('e14c05a8c1f81f91767cc5cd8f77a4c1119b30683998bddc5c8d777738f540b2',   # p20c-r1
                      '5ff62b90f38059a76323f4b7387774c96f602ec46a414bb091d212b428b5f0b1',   # p20c-r2
                      '21e666b83bd213bb97878b32a69081887eaea0dbc305fe02b18f64cfe8cc0950',   # p20c-r4 (staged 23 Oct)
                      )
ISSUER = 'private_heat_native_issuer_r13.py'


def main(hcf, composition, workdir, native_root, *helpers):
    raw = Path(hcf).read_bytes()
    if sha256(raw).hexdigest() != HCF_SHA256:
        raise SystemExit('HCF is not the reviewed harness: ' + sha256(raw).hexdigest())
    record = Path(composition).read_bytes()
    if sha256(record).hexdigest() not in COMPOSITION_SHA256:
        raise SystemExit('the composition record is not the reviewed one: ' + sha256(record).hexdigest())
    if not helpers:
        raise SystemExit(__doc__)
    recorded = json.loads(record)['helpers'][ISSUER]
    spec = importlib.util.spec_from_file_location('heat_control_on_frozen', hcf)
    if spec is None or spec.loader is None:
        raise SystemExit('HCF does not load as a module')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.ISSUER != ISSUER:
        raise SystemExit('HCF names another issuer')
    print(json.dumps(dict(expected_r13_reviewed=module.EXPECTED_R13, expected_r13_recorded=recorded)), flush=True)
    module.EXPECTED_R13 = recorded
    module.prepare(workdir, native_root, list(helpers))
    if json.loads((Path(workdir)/'control.json').read_text(encoding='utf8'))[
            'composed_r13_sha256_before_reference_insert'] != recorded:
        raise SystemExit('control.json does not record the recorded r13')
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 6:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
