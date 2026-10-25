"""Reproducibly derive the corrected Tier 1 owner and both runner successors.

Inputs are explicitly supplied, exact-byte pinned predecessors. No Atlas code is
imported or executed. --check performs the complete derivation without writing.
The output must be new; historical sources, receipts and defaults stay unchanged.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path

INPUT_PINS = {
    'integration_endpoint_checkpoints.py': '5d96c05dd88f8a9abdb1bc167a5e37284208596f90289ebf797e6fd1513d5a05',
    'run_fresh_interval.py': '34fb7c887252d7ff3539e76a89212e525691f6f8c9c6c7c27a71f1530f81cb9c',
    'run_prepared_restart.py': '6898a35c1a81fca8e4e5979ead6b359e5c34d59112c85ae8c37c49f5f0a6e34a',
}
OUTPUT_PINS = {
    'integration_endpoint_checkpoints.py': '2f4ad424e4a2d7d6ce9a73b5c85e1ff4bc412d564994c2eaf01332902d73f176',
    'run_fresh_interval.py': '8efc3a8cb76195cff5d4c637291b1d1eeb5b89122ea36b0bb9bca2c092d67466',
    'run_prepared_restart.py': '051008ad29fc56d42393c33b7dfcde622a39b5e9cce03a4900b91934ee066ce9',
}
CROSSCHECK_PIN = '73d9b2d9849f9c6d2dd0cb94e3f5af4ae425dbe4c6bfb6aa4c4de759fbc06fdf'

OWNER_EDITS = [
    ("    full_checks/cached_checks count completed strict checks by route; they are\n"
     "    observations only and never enter a key, binding or result.\n"
     '    """\n',
     "    full_checks/cached_checks count completed strict checks by route; they are\n"
     "    observations only and never enter a key, binding or result.\n"
     "    hits_restart/hits_after_write/hits_warm split ``hits`` by the key's history\n"
     "    in this open (WP17 Tier 1; observations only, likewise): the first hit on\n"
     "    a key written in this open is after-write, held or committed; a later hit\n"
     "    on an already hit key is warm; any other first hit is restart. Keys are\n"
     "    kept as 64-bit prefixes, at most min(max_entries, SPLIT_MAX_KEYS) of them\n"
     "    (the keys one open can touch, E + w, never exceed the quota; 2**18 keys\n"
     "    measured about 20 MiB); past that bound split_status is TRUNCATED and the\n"
     "    split stops, hits does not. entries_at_open is the committed *.query count\n"
     "    of the open's scan (None for columnar: its rows are counted by its backend).\n"
     '    """\n'
     "    SPLIT_MAX_KEYS = 1 << 18  # the Tier 1 map bound, with max_entries (about 80 B per key, measured)\n"),
    ("        self.full_checks = self.cached_checks = 0\n",
     "        self.full_checks = self.cached_checks = 0\n"
     "        self.hits_restart = self.hits_after_write = self.hits_warm = 0\n"
     "        # Key prefix -> False (written in this open, not hit yet) or True (hit in this open).\n"
     "        self.split_status, self.entries_at_open, self._seen = 'COMPLETE', None, {}\n"),
    ("            with os.scandir(self.directory) as entries:\n"
     "                for entry in entries:\n"
     "                    if entry.name == 'owner.lock':\n",
     "            committed = 0\n"
     "            with os.scandir(self.directory) as entries:\n"
     "                for entry in entries:\n"
     "                    if entry.name == 'owner.lock':\n"),
    ("                            ('completed.sqlite', 'completed.sqlite-journal')):\n"
     "                        self._entries += 1\n",
     "                            ('completed.sqlite', 'completed.sqlite-journal')):\n"
     "                        self._entries += 1\n"
     "                        if entry.name.endswith('.query'):\n"
     "                            committed += 1\n"),
    ("                        raise CheckpointRefused('checkpoint store exceeds configured disk bounds')\n"
     "            # The columnar helper is imported only when selected, before the\n",
     "                        raise CheckpointRefused('checkpoint store exceeds configured disk bounds')\n"
     "            self.entries_at_open = None if self.storage == 'columnar' else committed\n"
     "            # The columnar helper is imported only when selected, before the\n"),
    ("        self._sources_seen = None\n"
     "        self.context = self.budget = self.cancel = None\n",
     "        self._sources_seen = None\n"
     "        self._seen = {}\n"
     "        self.context = self.budget = self.cancel = None\n"),
    ("    def before(self, support, request, budget):\n",
     "    def _split_full(self):\n"
     "        # The Tier 1 memory bound (class docstring): past it the split stops.\n"
     "        if len(self._seen) < min(self.max_entries, self.SPLIT_MAX_KEYS):\n"
     "            return False\n"
     "        self.split_status, self._seen = 'TRUNCATED', {}\n"
     "        return True\n"
     "\n"
     "    def _split_hit(self, key):\n"
     "        \"\"\"Observation only: classify one counted hit by its key's history in this open.\"\"\"\n"
     "        if self.split_status == 'COMPLETE':\n"
     "            prefix = int(key[:16], 16)\n"
     "            state = self._seen.get(prefix)\n"
     "            if state is None and self._split_full():\n"
     "                return\n"
     "            if state is None:\n"
     "                self.hits_restart += 1\n"
     "            elif state:\n"
     "                self.hits_warm += 1\n"
     "            else:\n"
     "                self.hits_after_write += 1\n"
     "            self._seen[prefix] = True\n"
     "\n"
     "    def _split_written(self, key):\n"
     "        \"\"\"Observation only: a key written in this open, held or committed.\"\"\"\n"
     "        if self.split_status == 'COMPLETE':\n"
     "            prefix = int(key[:16], 16)\n"
     "            if prefix not in self._seen and not self._split_full():\n"
     "                self._seen[prefix] = False\n"
     "\n"
     "    def before(self, support, request, budget):\n"),
    ("        self._pending = (binding, key, True)\n"
     "        self.hits += 1\n",
     "        self._pending = (binding, key, True)\n"
     "        self.hits += 1\n"
     "        self._split_hit(key)\n"),
    ("                self._compact.write(binding, key, payload, arena, self._check)\n"
     "                self.written += 1\n",
     "                self._compact.write(binding, key, payload, arena, self._check)\n"
     "                self.written += 1\n"
     "                self._split_written(key)\n"),
    ("            self._used += size\n"
     "            self.written += 1\n",
     "            self._used += size\n"
     "            self.written += 1\n"
     "            self._split_written(key)\n"),
]

RUNNER_EDITS = [
    ("QUERY_STAGE_FIELDS = ('hits', 'misses', 'written', 'incomplete')\n",
     "QUERY_STAGE_FIELDS = ('hits', 'misses', 'written', 'incomplete')\n"
     "QUERY_SPLIT_FIELDS = ('hits_restart', 'hits_after_write', 'hits_warm')  # WP17 Tier 1 owners only\n"),
    ("    An Exception here is recorded (status INCOMPLETE, error) and stops only this\n",
     "    Schema v2 adds the owner's hit split (QUERY_SPLIT_FIELDS, WP17 Tier 1) and its\n"
     "    split_status to each row, summed the same way but only from an owner that\n"
     "    has them: with an older owner they stay null and its opened_with entries keep\n"
     "    the v1 shape. A split owner's opened_with entry also carries its split_status\n"
     "    and entries_at_open.\n"
     "\n"
     "    An Exception here is recorded (status INCOMPLETE, error) and stops only this\n"),
    ("            'schema': 'atlas.completed-queries-by-stage.v1', 'fields': list(QUERY_STAGE_FIELDS),\n",
     "            'schema': 'atlas.completed-queries-by-stage.v2', 'fields': list(QUERY_STAGE_FIELDS+QUERY_SPLIT_FIELDS),\n"),
    ("        return dict(stage=self.stage, opens=0, unflushed=None, **dict.fromkeys(QUERY_STAGE_FIELDS))\n",
     "        return dict(stage=self.stage, opens=0, unflushed=None, split_status=None,\n"
     "                    **dict.fromkeys(QUERY_STAGE_FIELDS+QUERY_SPLIT_FIELDS))\n"),
    ("    def _counts(owner):\n"
     "        return {name: getattr(owner, name) for name in QUERY_STAGE_FIELDS}\n",
     "    def _counts(owner):\n"
     "        counts = {name: getattr(owner, name) for name in QUERY_STAGE_FIELDS}\n"
     "        if hasattr(owner, 'split_status'):  # a Tier 1 owner: its split is read as strictly\n"
     "            counts.update({name: getattr(owner, name) for name in QUERY_SPLIT_FIELDS})\n"
     "        return counts\n"),
    ("            sums = {name: (self.row[name] or 0)+now[name]-self.base[name] for name in QUERY_STAGE_FIELDS}\n"
     "            self.row.update(sums, unflushed=unflushed)\n",
     "            sums = {name: (self.row[name] or 0)+now[name]-self.base[name] for name in now}\n"
     "            # A later open cannot make an earlier truncated contribution complete.\n"
     "            split = {}\n"
     "            if 'hits_warm' in now:\n"
     "                status = self.owner.split_status\n"
     "                if self.row['split_status'] == 'TRUNCATED':\n"
     "                    status = 'TRUNCATED'\n"
     "                split['split_status'] = status\n"
     "            self.row.update(sums, unflushed=unflushed, **split)\n"),
    ("            self.value['opened_with'].append(dict(stage=self.stage, **base))\n"
     "            self.row.update({name: self.row[name] or 0 for name in QUERY_STAGE_FIELDS}, opens=self.row['opens']+1)\n",
     "            opened = dict(stage=self.stage, **base)\n"
     "            if 'hits_warm' in base:\n"
     "                opened.update(split_status=owner.split_status, entries_at_open=getattr(owner, 'entries_at_open', None))\n"
     "            self.value['opened_with'].append(opened)\n"
     "            self.row.update({name: self.row[name] or 0 for name in base}, opens=self.row['opens']+1)\n"),
    ("                    'incomplete': owner.incomplete, 'unflushed': getattr(owner, 'unflushed', 0),\n",
     "                    'incomplete': owner.incomplete, 'unflushed': getattr(owner, 'unflushed', 0),\n"
     "                    'hits_restart': getattr(owner, 'hits_restart', None),\n"
     "                    'hits_after_write': getattr(owner, 'hits_after_write', None),\n"
     "                    'hits_warm': getattr(owner, 'hits_warm', None),\n"
     "                    'split_status': getattr(owner, 'split_status', None),\n"
     "                    'entries_at_open': getattr(owner, 'entries_at_open', None),\n"),
]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(path, pin):
    raw = Path(path).read_bytes()
    if digest(raw) != pin:
        raise ValueError('base differs: %s %s' % (path, digest(raw)))
    return raw


def edit(raw, pairs, name):
    # Line endings are preserved: a base is either all LF (the owner) or all CRLF (the r4 runner copies).
    crlf = raw.count(b'\r\n')
    if crlf not in (0, raw.count(b'\n')) or raw.count(b'\r') != crlf:
        raise ValueError('mixed line endings: '+name)
    eol = b'\r\n' if crlf else b'\n'
    for old, new in pairs:
        old, new = old.encode().replace(b'\n', eol), new.encode().replace(b'\n', eol)
        if raw.count(old) != 1:
            raise ValueError('anchor count %d in %s: %r' % (raw.count(old), name, old[:70]))
        raw = raw.replace(old, new)
    ast.parse(raw)
    return raw


def segments(raw, names=('QUERY_STAGE_FIELDS', 'QUERY_SPLIT_FIELDS', 'QueryStages', 'completed_queries')):
    text = raw.decode('utf-8')
    found = {}
    for node in ast.parse(text).body:
        targets = [getattr(t, 'id', None) for t in getattr(node, 'targets', [])]
        for name in names:
            if getattr(node, 'name', None) == name or name in targets:
                found[name] = ast.get_source_segment(text, node)
    return found


def derive(inputs, crosscheck=None):
    if set(inputs) != set(INPUT_PINS):
        raise ValueError('exactly the owner, fresh and accepted restart bases are required')
    built = {}
    for name, pin in INPUT_PINS.items():
        pairs = OWNER_EDITS if name == 'integration_endpoint_checkpoints.py' else RUNNER_EDITS
        raw = edit(pinned(inputs[name], pin), pairs, name)
        if digest(raw) != OUTPUT_PINS[name]:
            raise ValueError('derived output differs: ' + name)
        built[name] = raw
    fresh = segments(built['run_fresh_interval.py'])
    if segments(built['run_prepared_restart.py']) != fresh or len(fresh) != 4:
        raise ValueError('fresh/restart query definitions differ or are missing')
    if crosscheck is not None:
        raw = edit(pinned(crosscheck, CROSSCHECK_PIN), RUNNER_EDITS, 'g1 restart crosscheck')
        if segments(raw) != fresh:
            raise ValueError('g1 restart query definitions differ')
    return built


def write_outputs(output, built):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new directory')
    for parent in output.parents:
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('linked output ancestors are refused')
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in built.items():
        (output / name).write_bytes(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-base', required=True, type=Path)
    parser.add_argument('--fresh-base', required=True, type=Path)
    parser.add_argument('--restart-base', required=True, type=Path)
    parser.add_argument('--restart-crosscheck', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.check and args.output is None:
        parser.error('--output is required unless --check is selected')
    inputs = dict(zip(INPUT_PINS, (args.owner_base, args.fresh_base, args.restart_base), strict=True))
    try:
        built = derive(inputs, args.restart_crosscheck)
        if not args.check:
            write_outputs(args.output, built)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Tier 1 construction refused: ' + str(error) + '\n')
    print(json.dumps(dict(status='CHECKED' if args.check else 'BUILT',
        inputs=INPUT_PINS, outputs={name: digest(raw) for name, raw in built.items()},
        runtime_admission=False, default_changed=False, scientific_acceptance=False)))


if __name__ == '__main__':
    main()
