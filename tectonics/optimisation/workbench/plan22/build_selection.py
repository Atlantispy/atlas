"""Construct the public Plan22 L3 source selection in a NEW directory.

The additive pinned candidate builder supplies the complete 647-member public L3
candidate with the current port-r3 reader. SELECTION-MAP.json selects exactly that candidate and enables L3 on
the recorded interval-1 A/B comparison (D10) for the same reader bytes. D10
timed that reader on the private comparison stack; this selection's
content_cache, interval_store_set and record_tables differ and were not timed.
D22r requires a fresh SELECTED result with at least 0.2009 improvement.
The D10 record is pinned by digest and its predeclared rule, including the
exactness and accounting conditions, is recomputed from its recorded rows; its
arms are bound to the compared compositions and its timed and selected stacks
to the measured reader and the materialised files. L3 has no runtime switch: it is active wherever the selected
record_views is the reader. No selected source is executed, and no runtime
admission, default, scientific or interval authority is granted.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
import types


PREFIX = 'tectonics/optimisation/workbench/plan22/'
BASE_TOOL = PREFIX + 'build_candidate_r4.py'
BASE_TOOL_SHA = '64f414777255efaa0513814a83e3455ace0d5ae01cab13b17ec75eca9073a134'
SELECTION_MAP = PREFIX + 'SELECTION-MAP.json'
SELECTION_MAP_SHA = 'ae3735066df5830d996bdd33e9f65ded614a5b6e618d1283f48378563ddd363b'
RESULTS = PREFIX + 'RETAINED-RESULTS-r4.json'
SCHEMA = 'atlas.public.plan22.selection-map.r1'
SHA256_HEX = 64
IDENTITY_KIND = 'NEW_PUBLIC_SOURCE_SELECTION_NOT_RUNTIME_ADMISSION'
GRANTED = ('selected', 'enablement')
WITHHELD = ('runtime_admission', 'default_changed', 'scientific_acceptance', 'interval_authority',
            'installed_package_changed', 'public_runtime_compatibility', 'runtime_policy_adopted', 's9_selected')
MEMBER_FIELDS = ('member', 'public_path', 'public_sha256', 'public_base', 'public_base_sha256')
READER = 'source/helpers/record_views.py'
D10_FIELDS = ('verdict', 'comparison', 'label', 'date', 'baseline_reader_sha256', 'candidate_reader_sha256',
              'baseline_private_composition_sha256', 'candidate_private_composition_sha256',
              'improvement_seconds', 'improvement_fraction')
CROSS_KEYS = ('baseline_reader_sha256', 'candidate_reader_sha256', 'baseline_private_composition_sha256',
              'candidate_private_composition_sha256')
ARMS = ('A', 'B')
SAMPLES_PER_ARM = 2
RSS_ALLOWANCE = (32 + 16) << 20  # the frozen rule: process carry cap plus RSS slack
MIN_IMPROVEMENT_FRACTION = 0.2009  # D22r condition 5; no rounded-summary shortcut
DECLARED_DIFFERING_MODULES = frozenset({'content_cache', 'interval_store_set', 'record_tables'})
ROUNDING = 0.0002  # recorded seconds carry four decimals


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def hex_digest(value):
    return isinstance(value, str) and len(value) == SHA256_HEX and all(c in '0123456789abcdef' for c in value)


def d10_digest(d10):
    """Canonical digest of the recorded D10 object (the whole results file names this tool, so it cannot)."""
    text = json.dumps(d10, sort_keys=True, indent=2, ensure_ascii=True) + '\n'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def pinned(raw, pin, name):
    require(hex_digest(pin), 'Reviewed SHA256 required: ' + name)
    require(hashlib.sha256(raw).hexdigest() == pin, 'Pinned input changed: ' + name)
    return raw


def load_base(repo):
    path = repo / BASE_TOOL
    raw = pinned(path.read_bytes(), BASE_TOOL_SHA, BASE_TOOL)
    module = types.ModuleType('plan22_pinned_candidate_builder')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def check_selection(mapping, candidate, candidate_map):
    """The selection map may only select and enable the exact reviewed candidate."""
    require(mapping.get('schema') == SCHEMA and mapping.get('identity_kind') == IDENTITY_KIND,
            'A Plan22 public selection map is required')
    require(set(candidate.FLAGS) == set(GRANTED) | set(WITHHELD) and not set(GRANTED) & set(WITHHELD),
            'Selection flags do not cover the candidate flags')
    require(all(mapping.get(key) is True for key in GRANTED), 'Selection map does not select and enable L3')
    require(all(mapping.get(key) is False for key in WITHHELD), 'Selection map grants withheld authority')
    require(mapping.get('candidate_source_map') == {'path': candidate.PREFIX + getattr(candidate, 'MAP_FILE', 'SOURCE-MAP.json'),
                                                    'sha256': candidate.MAP_SHA},
            'Selection map does not name the reviewed candidate map')
    require(hex_digest(mapping.get('candidate_overlay_identity_sha256'))
            and mapping['candidate_overlay_identity_sha256'] == candidate_map.get('public_overlay_identity_sha256'),
            'Candidate overlay identity differs')
    require(all(hex_digest(mapping.get(key)) for key in ('candidate_selection_sha256', 'base_selection_sha256')),
            'Selection map lacks the candidate selection identities')
    expected = [{key: entry.get(key) for key in MEMBER_FIELDS} for entry in candidate_map['entries']]
    require(mapping.get('members') == expected, 'Selected members differ from the candidate')


ROW_KINDS = {  # seconds are finite and positive; counts are non-negative ints; flags are booleans
    'seconds': lambda x: type(x) in (int, float) and math.isfinite(x) and x > 0,
    'count': lambda x: type(x) is int and x >= 0,
    'flag': lambda x: type(x) is bool,
}


def samples(value, kind, count, key):
    require(isinstance(value, list) and len(value) == count and all(ROW_KINDS[kind](x) for x in value),
            'Recorded D10 rows are malformed: ' + key)
    return value


def rows(record, key, kind='count'):
    value = record.get(key)
    require(isinstance(value, dict) and set(value) == set(ARMS), 'Recorded D10 rows are malformed: ' + key)
    for arm in ARMS:
        samples(value[arm], kind, SAMPLES_PER_ARM, key)
    return value


def valid_run(d10):
    """The exactness and accounting conditions, recomputed from the recorded per-sample rows: the same result
    identity and field count in every sample, strict source, a closed scope with nothing reserved after it, and no
    carried bytes booked or raw after close."""
    valid = d10.get('valid_run')
    require(isinstance(valid, dict), 'Recorded D10 rows are malformed: valid_run')
    flags = [rows(valid, key, 'flag') for key in ('result_id_equal', 'strict_source', 'scope_closed')]
    fields, reserved = rows(valid, 'fields'), rows(valid, 'budget_reserved_after_close')
    after = valid.get('carry_after_close_b')
    require(isinstance(after, dict) and set(after) == {'booked', 'raw'},
            'Recorded D10 rows are malformed: carry_after_close_b')
    carried = [*samples(after['booked'], 'count', SAMPLES_PER_ARM, 'carry_after_close_b'),
               *samples(after['raw'], 'count', SAMPLES_PER_ARM, 'carry_after_close_b')]
    return (all(x is True for flag in flags for arm in ARMS for x in flag[arm])
            and len({x for arm in ARMS for x in fields[arm]}) == 1
            and not any(x for arm in ARMS for x in reserved[arm]) and not any(carried))


def frozen_rule(d10):
    """The predeclared D10 rule, recomputed from the recorded rows rather than taken from the verdict."""
    seconds = rows(d10, 'reopen_seconds', 'seconds')
    misses, refusals, rss = (rows(d10, key) for key in ('page_misses', 'required_refusals', 'peak_rss_bytes'))
    carry = samples(d10.get('carry_refusals'), 'count', SAMPLES_PER_ARM, 'carry_refusals')
    mean = {arm: sum(seconds[arm]) / SAMPLES_PER_ARM for arm in ARMS}
    improvement = mean['A'] - mean['B']
    for key, value in (('improvement_seconds', improvement), ('improvement_fraction', improvement / mean['A'])):
        recorded = d10.get(key)
        require(type(recorded) in (int, float) and abs(recorded - value) <= ROUNDING,
                'Recorded D10 summary differs from its rows: ' + key)
    return (improvement / mean['A'] >= MIN_IMPROVEMENT_FRACTION
            and max(seconds['B']) < min(seconds['A'])
            and improvement > max(max(values) - min(values) for values in seconds.values())
            and max(misses['B']) <= min(misses['A']) and max(refusals['B']) <= min(refusals['A'])
            and not any(carry) and max(rss['B']) <= max(rss['A']) + RSS_ALLOWANCE and valid_run(d10))


def stack_modules(d10, key):
    stack = d10.get(key)
    modules = stack.get('modules') if isinstance(stack, dict) else None
    if not isinstance(modules, dict):
        raise ValueError('Recorded D10 stack is malformed: ' + key)
    require('record_views' in modules
            and all(isinstance(name, str) and name.isidentifier() and hex_digest(pin) for name, pin in modules.items()),
            'Recorded D10 stack is malformed: ' + key)
    return modules


def check_evidence(mapping, results, candidate_map):
    """D10 must be recorded as SELECTED for the same reader bytes and the recorded private comparison
    compositions; its record must match the pinned digest and its rows must satisfy the frozen rule."""
    d10 = results.get('d10')
    require(isinstance(d10, dict) and d10.get('run') is True and d10.get('verdict') == 'SELECTED'
            and d10.get('all_conditions_true') is True and d10.get('inputs_unchanged') is True,
            'Recorded D10 comparison does not select L3')
    claimed = (mapping.get('evidence') or {}).get('d10')
    claimed = claimed if isinstance(claimed, dict) else {}
    require(claimed.get('record') == RESULTS
            and all(key in claimed and key in d10 and claimed[key] == d10[key] for key in D10_FIELDS),
            'Selection evidence differs from the recorded D10 comparison')
    require(hex_digest(claimed.get('d10_record_sha256')) and claimed['d10_record_sha256'] == d10_digest(d10),
            'Recorded D10 comparison differs from the pinned record')
    require(frozen_rule(d10), 'Recorded D10 rows do not satisfy the frozen selection rule')
    require(all(hex_digest(d10.get(key)) for key in CROSS_KEYS), 'Recorded D10 identities are not digests')
    reader = next((entry for entry in mapping['members'] if entry['member'] == READER), None)
    require(reader is not None and d10['candidate_reader_sha256'] == reader['public_sha256']
            and d10['baseline_reader_sha256'] == reader['public_base_sha256'],
            'D10 did not measure the selected reader bytes')
    require(d10['candidate_private_composition_sha256'] == candidate_map.get('candidate_private_composition_sha256')
            and d10['baseline_private_composition_sha256'] == candidate_map.get('base_private_composition_sha256'),
            'D10 did not compare the candidate compositions')
    require(d10.get('arm_compositions') == {'A': d10['baseline_private_composition_sha256'],
                                            'B': d10['candidate_private_composition_sha256']},
            'D10 arms are not bound to the compared compositions')
    require(stack_modules(d10, 'timed_stack')['record_views'] == d10['candidate_reader_sha256'],
            'D10 timed stack does not hold the measured reader')
    timed = stack_modules(d10, 'timed_stack')
    selected = stack_modules(d10, 'selected_stack')
    require(set(selected) == set(timed), 'D10 selected and timed stack key sets differ')
    declared = d10.get('differing_modules')
    require(isinstance(declared, list) and len(declared) == len(set(declared))
            and set(declared) == DECLARED_DIFFERING_MODULES,
            'D10 declared differing-module set differs')
    require({name for name in timed if timed[name] != selected[name]} == DECLARED_DIFFERING_MODULES,
            'D10 actual differing-module set differs')
    return claimed['d10_record_sha256'], selected


def materialise(repo, destination):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    candidate = load_base(repo)
    require(candidate.FROZEN is True, 'The candidate builder is not frozen')
    combined = candidate.load_base(repo).combined(repo)
    utilities = combined.shared(repo)
    for path in (repo, destination):
        utilities.inside(Path(path.anchor), path.relative_to(path.anchor).as_posix())
    utilities.refuse_existing(destination)
    pinned(utilities.read_source(repo, BASE_TOOL), BASE_TOOL_SHA, BASE_TOOL)
    map_path = candidate.PREFIX + getattr(candidate, 'MAP_FILE', 'SOURCE-MAP.json')
    candidate_map = utilities.read_map(pinned(utilities.read_source(repo, map_path), candidate.MAP_SHA, map_path))
    mapping = utilities.read_map(pinned(utilities.read_source(repo, SELECTION_MAP), SELECTION_MAP_SHA,
                                        SELECTION_MAP))
    check_selection(mapping, candidate, candidate_map)
    d10_record, selected_stack = check_evidence(mapping, utilities.read_map(utilities.read_source(repo, RESULTS)),
                                                candidate_map)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.plan22-selection-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        candidate.materialise(repo, stage)
        prior_raw = utilities.read_source(stage, 'SOURCE-MANIFEST.json')
        prior = utilities.read_map(prior_raw)
        require(prior.get('status') == 'PREPARED_SOURCE_NOT_QUALIFIED'
                and prior.get('source_map_sha256') == candidate.MAP_SHA
                and prior.get('selection_sha256') == mapping.get('candidate_selection_sha256')
                and prior.get('base_selection_sha256') == mapping.get('base_selection_sha256')
                and prior.get('overlay_identity_sha256') == mapping['candidate_overlay_identity_sha256']
                and all(prior.get(key) is False for key in candidate.FLAGS),
                'Materialised candidate differs from the selected candidate')
        files = prior['files']
        require(len(files) == prior.get('source_members') == sum(candidate.COUNTS.values()),
                'Materialised candidate member count differs')
        for member, pin in files.items():
            pinned(utilities.read_source(stage, member), pin, member)
        require(all(files.get(f'helpers/{name}.py') == pin for name, pin in selected_stack.items()),
                'Recorded selected stack differs from the materialised selection')
        manifest = dict(schema='atlas.public.plan22.materialised-selection.r1',
            status='SELECTED_SOURCE_L3_ENABLED', identity_kind=IDENTITY_KIND,
            selection_map={'path': SELECTION_MAP, 'sha256': SELECTION_MAP_SHA},
            candidate_manifest_sha256=utilities.digest(prior_raw), source_map_sha256=candidate.MAP_SHA,
            base_selection_sha256=prior['base_selection_sha256'], selection_sha256=prior['selection_sha256'],
            source_members=len(files), overlay_identity_sha256=prior['overlay_identity_sha256'],
            source_maps=[{'path': SELECTION_MAP, 'sha256': SELECTION_MAP_SHA}, *prior['source_maps']],
            source_tools=[{'path': BASE_TOOL, 'sha256': BASE_TOOL_SHA}, *prior['source_tools']],
            replaced_public_sources=prior['replaced_public_sources'], evidence=mapping['evidence'],
            d10_record_sha256=d10_record,
            files=files, **candidate.COUNTS, **dict.fromkeys(GRANTED, True), **dict.fromkeys(WITHHELD, False))
        (stage / 'SOURCE-MANIFEST.json').write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return dict(status=manifest['status'], files=len(files), selection_sha256=manifest['selection_sha256'],
                **dict.fromkeys(GRANTED, True), **dict.fromkeys(WITHHELD, False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output)
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
        parser.exit(1, 'Plan22 selection construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
