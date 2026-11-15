"""Reuse-previous-run, reader form (designs/reuse-previous-run-r1.md section 3, errata 1).

A fixed reader reads the previous run's sealed interval when the two trees differ only in files that bind no
producer output. The record is never adoptable. NOT SCIENTIFICALLY PERMISSIBLE.
"""
from hashlib import sha256

from atlas_tectonics._private import run_fresh_interval as F
from atlas_tectonics._private import run_prepared_restart as RUN

require = F.require
STATUS = 'DIAGNOSTIC_REUSE_PREVIOUS_RUN_NOT_ADOPTABLE'
DIAGNOSTIC = 'DIAGNOSTIC_UNCERTIFIED_NO_QUALIFICATION'
BRAND = 'NOT SCIENTIFICALLY PERMISSIBLE'
# The only files a reusing reader may differ in: outside the execution identity and the heat source binding.
FREE = frozenset('atlas_tectonics/_private/'+name for name in (
    'reopen_fresh_restart.py', 'reopen_prepared_restart.py', 'overlap_reader.py',
    'reader_overlap_gate.py', 'reuse_previous_run.py'))
# Written by the package build from the tree's own files; `changed` compares every file they list.
DERIVED = frozenset('atlas_tectonics/'+name for name in ('_application_sources.json', '_application_sources.sha256'))

# Design chain-arm-r3-override-reuse-r1 s5: public files the heat restore binds; never excused by the override.
# shortcut: a copy of the heat issuer's public sources; TA11 fails when that list changes
HEAT_PUBLIC = frozenset('atlas_tectonics/'+name for name in (
    'integration_exact_gmp.py', 'integration_mimetic_newton.py', 'integration_spatial_transport.py'))


def _inside(table, root):
    """A manifest table with the entries under the native root keyed from that root, so that two trees compare."""
    return {name[len(root)+1:] if name.startswith(root+'/') else name: value for name, value in table.items()}


def _paths_inside(value, root):
    """Review E-1: fixture_source_map ({'by_path': .., 'modules': ..}) with every tree-folder path, key or value,
    at any depth, made relative to the native root."""
    if type(value) is dict:
        return {_paths_inside(name, root): _paths_inside(item, root) for name, item in value.items()}
    return value[len(root)+1:] if type(value) is str and value.startswith(root+'/') else value


def plan(profile, sources, path, pin, override=False):
    require(type(override) is bool, 'explicit identity-override flag required')
    previous = F.FreshProfile.read(path, pin)
    row, old = profile.record(), previous.record()
    require(previous.sha256 != profile.sha256 and old['workspace'] == row['workspace'] and
            old['historical_inputs'] == row['historical_inputs'],
            'a previous run of this workspace and inputs required')
    mine = RUN.pinned_json(sources.manifest_path, sources.manifest_pin)
    theirs = RUN.pinned_json(sources.path(old['source_manifest']['path']), old['source_manifest']['sha256'])
    require(all(m['installed_binding']['qualification_status'] == DIAGNOSTIC for m in (mine, theirs)),
            'reuse-previous-run is for diagnostic trees only')
    data, old_data = (_inside(m['data_only'], r['native_root']) for m, r in ((mine, row), (theirs, old)))
    fixtures, old_fixtures = (_paths_inside(m['fixture_source_map'], r['native_root'])
                              for m, r in ((mine, row), (theirs, old)))
    require(all(mine[key] == theirs[key] for key in ('composition', F.QUERY_STORE_FLAG)) and
            {k: v for k, v in data.items() if k not in DERIVED} ==
            {k: v for k, v in old_data.items() if k not in DERIVED} and fixtures == old_fixtures,
            'the two runs differ in data, composition or query store')

    def files(manifest, root):
        require(all(name.startswith(root+'/') for name in manifest['files']), 'source outside the native root')
        return _inside(manifest['files'], root)
    a, b = files(mine, row['native_root']), files(theirs, old['native_root'])
    require({name: b.get(name) for name in theirs['source_hashes']} == theirs['source_hashes'],
            'previous manifest is not self-consistent')
    changed = {name: {'previous': b.get(name), 'this': a.get(name)}
               for name in sorted(set(a) | set(b)) if a.get(name) != b.get(name)}
    public = {name for name in changed if override and name.startswith('atlas_tectonics/')
              and not name.startswith('atlas_tectonics/_private/')} - HEAT_PUBLIC
    bound = sorted(set(changed) - FREE - public)
    require(not bound, 'reuse-previous-run refused, these changed files bind the producer output: '+', '.join(bound))
    proof = {'source_manifest_sha256': old['source_manifest']['sha256'],
             'native_source_digest': sha256(F.canonical(theirs['source_hashes'])).hexdigest()}
    return {'previous': previous, 'source_proof': proof,
            'record': {'previous_profile_sha256': previous.sha256, 'previous_source_proof': proof,
                       'changed': changed, 'adoptable': False, 'brand': BRAND, 'identity_override': override}}
