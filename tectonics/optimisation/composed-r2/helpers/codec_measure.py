"""Bounded, opt-in WP10 measurements; never enables or rewrites codec policy.

Real samples must be supplied by the already-authorised census owner. This
module neither discovers nor opens historical stores. Synthetic observations
are component evidence only, never production adoption evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from types import MappingProxyType

import numpy as np


SCHEMA = 'atlas.codec-measure.v1'
ARRAY_CLASSES = (
    'csr_offsets', 'sorted_lookup', 'child_refs', 'integer_offsets',
    'ordinals', 'float_fields', 'indices', 'integer_magnitudes', 'tags',
    'string_pool', 'metadata', 'support_blobs',
)
MAX_SAMPLE_BYTES = 64 << 10
MAX_CLASS_SAMPLES = 16
STORE_BYTES = 4 << 30
DICT_GAP = ('Blosc2 CParams exposes only per-frame use_dict; no supported '
            'training API or reusable external dictionary argument is exposed '
            'by compress2/decompress2. DictionarySpec is categorical string '
            'encoding, not a Zstandard compression dictionary.')
WORKSPACE_GAP = ('Blosc2 exposes no supported compress/decompress native '
                 'workspace bound API. Its output-size and block-size values '
                 'do not bound allocator workspace; the configured 8 MiB cap '
                 'is not a measured or proved native allocation bound.')


class MeasurementRefused(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise MeasurementRefused(reason)


def _number(value, *, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def capability_report(module=None):
    """Inspect the installed Python API and run four tiny lossless probes.

    Exposed filters are not evidence of a bounded native working allocation.
    Unknown future API versions remain unqualified until explicitly reviewed.
    """
    try:
        b = importlib.import_module('blosc2') if module is None else module
    except ImportError as error:
        return dict(schema=SCHEMA, status='BLOCKED', version=None,
                    capabilities={}, error=str(error), enabled=False)
    cfields = sorted(getattr(b.CParams, '__dataclass_fields__', {}))
    dfields = sorted(getattr(b.DParams, '__dataclass_fields__', {}))
    raw = np.arange(512, dtype='<u8').tobytes()
    capabilities = {}
    for name, filter_name in (('zstd', 'NOFILTER'), ('byte_shuffle', 'SHUFFLE'),
                              ('bit_shuffle', 'BITSHUFFLE'), ('delta_filter', 'DELTA')):
        try:
            encoded = b.compress2(raw, codec=b.Codec.ZSTD, clevel=1, typesize=8,
                                  nthreads=1, filters=[getattr(b.Filter, filter_name)])
            _require(b.decompress2(encoded, nthreads=1) == raw, 'bytes differ')
            capabilities[name] = dict(status='SUPPORTED', roundtrip=True,
                                      raw_bytes=len(raw), encoded_bytes=len(encoded))
        except (AttributeError, RuntimeError, ValueError, TypeError) as error:
            capabilities[name] = dict(status='BLOCKED', roundtrip=False,
                                      reason=f'{type(error).__name__}: {error}')
    capabilities['trained_external_dictionary'] = dict(status='BLOCKED', reason=DICT_GAP,
        next_action='Provide a supported reusable dictionary API and bounded workspace proof; no installation is authorised.')
    capabilities['native_workspace_bound'] = dict(status='BLOCKED', reason=WORKSPACE_GAP,
        next_action='Provide an authoritative bound for this native version and parameters, then validate charged admission.')
    return dict(schema=SCHEMA, status='PARTIAL', version=str(b.__version__),
                module_path=str(getattr(b, '__file__', 'UNKNOWN')),
                compress2_signature=str(inspect.signature(b.compress2)),
                decompress2_signature=str(inspect.signature(b.decompress2)),
                cparams_fields=cfields, dparams_fields=dfields,
                workspace_related_exports=sorted(n for n in dir(b)
                    if any(word in n.lower() for word in ('workspace', 'estimate', 'bound', 'train'))),
                dictionary_related_exports=sorted(n for n in dir(b) if 'dict' in n.lower()),
                capabilities=capabilities, enabled=False)


@dataclass(frozen=True)
class CodecSample:
    array_class: str
    dtype: str
    raw: bytes
    provenance: str
    source_kind: str = 'synthetic'

    def __post_init__(self):
        _require(self.array_class in ARRAY_CLASSES, 'unknown array class')
        dt = np.dtype(self.dtype)
        _require(dt.kind in 'biuf' and dt.itemsize in (1, 2, 4, 8), 'unsupported dtype')
        _require(type(self.raw) is bytes and 0 < len(self.raw) <= MAX_SAMPLE_BYTES
                 and len(self.raw) % dt.itemsize == 0, 'one aligned <=64 KiB chunk required')
        _require(self.source_kind in ('synthetic', 'real') and bool(self.provenance),
                 'explicit source kind and provenance required')


@dataclass(frozen=True)
class CodecCandidate:
    name: str
    rule: object = None

    def __post_init__(self):
        _require(type(self.name) is str and bool(self.name), 'candidate name required')
        if self.rule is not None:
            _require(type(self.rule) is dict, 'candidate rule must be a plain mapping')
            object.__setattr__(self, 'rule', MappingProxyType(dict(self.rule)))


def default_candidates():
    """Experimental requests; these are never written to codec_policy.json."""
    basic = (CodecCandidate('native-baseline'), CodecCandidate('raw', {'codec': 'raw', 'enabled': True}),
            CodecCandidate('palette', {'codec': 'palette', 'enabled': True}),
            CodecCandidate('delta-v1', {'codec': 'delta-v1', 'enabled': True}))
    native = tuple(CodecCandidate(f'zstd-{shuffle}-{level}',
        {'codec': 'zstd', 'enabled': True, 'level': level, 'shuffle': shuffle})
        for shuffle in ('none', 'byte', 'bit') for level in (1, 3, 9))
    combined = tuple(CodecCandidate(f'delta-zstd-v1-{shuffle}-{level}',
        {'codec': 'delta-zstd-v1', 'enabled': True, 'level': level, 'shuffle': shuffle})
        for shuffle in ('none', 'byte', 'bit') for level in (1, 3, 9))
    return basic + native + combined + (CodecCandidate('trained-dictionary',
        {'codec': 'trained-zstd-v1', 'enabled': True}),)


def _codec_runtime():
    return importlib.import_module('storage_codec_runtime')


def measure_class(store, samples, candidates=None, *, repeats=3, warmups=1,
                  encode_candidate=None, decode_candidate=None, workspace_bound=None,
                  read_frequency=None, backend_capabilities=None):
    """Measure the injected store's encoder/decoder and immutable candidates.

    Timings include only codec calls, excluding identity checks, sample loading
    and persistence. Retained sample input is capped at 1 MiB per call. The
    caller owns these input bytes and any wider census memory budget.
    """
    samples = tuple(samples)
    candidates = tuple(default_candidates() if candidates is None else candidates)
    _require(0 < len(samples) <= MAX_CLASS_SAMPLES, 'bounded nonempty sample collection required')
    _require(all(type(s) is CodecSample for s in samples), 'validated CodecSample inputs required')
    _require(len({s.array_class for s in samples}) == 1, 'one class per measurement required')
    _require(1 <= repeats <= 9 and 0 <= warmups <= 2, 'repeats/warmups exceed measurement bounds')
    _require(0 < len(candidates) <= 24 and len({c.name for c in candidates}) == len(candidates),
             'bounded unique candidates required')
    _require(all(len(s.raw) <= store.limits.chunk_bytes for s in samples), 'sample exceeds store chunk bound')
    if any(c.rule is not None for c in candidates):
        if encode_candidate is None or decode_candidate is None or workspace_bound is None:
            patch = _codec_runtime()
            encode_candidate = encode_candidate or patch.encode_candidate
            decode_candidate = decode_candidate or patch.decode_candidate
            workspace_bound = workspace_bound or patch.workspace_bound
    frequency = {'hot_reads': None, 'cold_reads': None, 'observation': None}
    if read_frequency is not None:
        _require(type(read_frequency) is dict and set(read_frequency) == set(frequency),
                 'frequency requires hot_reads, cold_reads and observation')
        _require(all(v is None or type(v) is int and v >= 0 for k, v in read_frequency.items()
                     if k != 'observation'), 'read counts must be observed nonnegative integers')
        _require(bool(read_frequency['observation']), 'frequency observation source required')
        frequency.update(read_frequency)
    compression_before = repr(store.compression)
    if backend_capabilities is not None:
        _require(type(backend_capabilities) is dict, 'explicit backend capability mapping required')
        for value in backend_capabilities.values():
            _require(type(value) is dict and value.get('status') in ('AVAILABLE', 'BLOCKED')
                     and bool(value.get('provenance')), 'backend capability needs status and evidence provenance')
    total = sum(len(s.raw) for s in samples)
    rows = []
    for candidate in candidates:
        enc_times, dec_times, expected, bounds = [], [], None, []
        for iteration in range(warmups + repeats):
            enc_time = dec_time = 0.0
            encoded_bytes, labels = 0, []
            for sample in samples:
                dt = np.dtype(sample.dtype)
                count = len(sample.raw) // dt.itemsize
                rule = None if candidate.rule is None else dict(candidate.rule)
                if rule is not None:
                    backend = getattr(store, '_codec_backend', None)
                    bound = (workspace_bound(len(sample.raw), dt, rule) if backend is None else
                             workspace_bound(len(sample.raw), dt, rule, backend=backend))
                    _require(bound is None or type(bound) is int and bound >= 0,
                             'workspace hook must return a byte bound or None')
                    _require(bound is None or bound <= store.limits.codec_workspace_bytes,
                             'candidate exceeds unchanged codec workspace limit')
                    bounds.append(bound)
                started = time.perf_counter_ns()
                label, payload = (store._encode(sample.raw, dt) if rule is None
                                  else encode_candidate(store, sample.raw, dt, rule))
                enc_time += (time.perf_counter_ns() - started) / 1e9
                started = time.perf_counter_ns()
                decoded = (store._decode(label, payload, dt, count) if rule is None
                           else decode_candidate(store, label, payload, dt, count))
                dec_time += (time.perf_counter_ns() - started) / 1e9
                _require(type(label) is str and type(payload) is bytes and len(payload) > 0,
                         'invalid encoded payload')
                _require(decoded == sample.raw, 'candidate changed decoded raw bytes')
                descriptor = json.dumps({'dtype': dt.str, 'count': count}, sort_keys=True,
                                        separators=(',', ':'), ensure_ascii=True).encode()
                _require(store._blob_id(descriptor, decoded) == store._blob_id(descriptor, sample.raw),
                         'candidate changed typed chunk identity')
                encoded_bytes += len(payload)
                labels.append(label)
            fingerprint = (encoded_bytes, tuple(labels))
            _require(expected is None or expected == fingerprint, 'candidate representation is unstable')
            expected = fingerprint
            if iteration >= warmups:
                enc_times.append(enc_time)
                dec_times.append(dec_time)
        encode_seconds, decode_seconds = statistics.median(enc_times), statistics.median(dec_times)
        requested = None if candidate.rule is None else candidate.rule.get('codec')
        blockers = ([WORKSPACE_GAP] if requested in ('zstd', 'delta-zstd-v1') else
                    [DICT_GAP, WORKSPACE_GAP] if requested == 'trained-zstd-v1' else [])
        backend_evidence = None if backend_capabilities is None else backend_capabilities.get(requested)
        if backend_evidence is not None:
            blockers = ([] if backend_evidence['status'] == 'AVAILABLE' else
                        [backend_evidence.get('reason', 'explicit backend capability is blocked')])
        rows.append(dict(candidate=candidate.name, requested_rule=None if candidate.rule is None else dict(candidate.rule),
            effective_labels=list(expected[1]), raw_bytes=total, encoded_bytes=expected[0],
            encoded_over_raw=expected[0] / total, raw_over_encoded=total / expected[0],
            encode_seconds_median=encode_seconds, decode_seconds_median=decode_seconds,
            encode_MB_s=total / 1e6 / encode_seconds if encode_seconds else None,
            decode_MB_s=total / 1e6 / decode_seconds if decode_seconds else None,
            encode_seconds_runs=enc_times, decode_seconds_runs=dec_times,
            workspace_bound_bytes=max(bounds) if bounds and all(b is not None for b in bounds) else None,
            workspace_status='VERIFIED_BOUND' if bounds and all(b is not None for b in bounds) else 'INCOMPLETE',
            workspace_scope='conservative candidate buffer admission; not measured native RSS',
            declared_codec_workspace_limit_bytes=store.limits.codec_workspace_bytes,
            codec_capability_status='BLOCKED' if blockers else 'AVAILABLE', capability_gaps=blockers,
            backend_capability_evidence=backend_evidence,
            exact_raw_and_chunk_identity=True, persistence_seconds=None, enabled=False))
    _require(repr(store.compression) == compression_before, 'measurement mutated store compression')
    return dict(schema=SCHEMA, array_class=samples[0].array_class,
        source_kind='real' if all(s.source_kind == 'real' for s in samples) else 'synthetic',
        sample_count=len(samples), input_bytes=total, sample_sha256=[sha256(s.raw).hexdigest() for s in samples],
        provenance=[s.provenance for s in samples], read_frequency=frequency, candidates=rows,
        measurement_scope='in-memory codecs only; no persistence or representative run-path observation',
        production_adoption='INCOMPLETE', enabled=False)


def assess_adoption(measurement, candidate_name, evidence=None):
    """Return a reviewable gate decision, never an enabling operation.

    Required run evidence is measured for this full class, not extrapolated
    from synthetic chunks. End-to-end wall times include encode, decode and
    persistence under matched run conditions; persistence is also itemised.
    """
    from codec_tradeoff import TRADEOFF_FIELDS, time_gate_passes
    evidence = {} if evidence is None else dict(evidence)
    rows = [row for row in measurement['candidates'] if row['candidate'] == candidate_name]
    _require(len(rows) == 1, 'one matching candidate required')
    row = rows[0]
    missing, failed = [], []
    if measurement['source_kind'] != 'real':
        missing.append('representative real class samples')
    if row['workspace_status'] != 'VERIFIED_BOUND':
        missing.append('verified decoder workspace bound')
    if not evidence.get('matched_real_run_provenance'):
        missing.append('matched real run provenance')
    needed = ('class_read_path_seconds', 'added_decode_seconds', 'cold_raw_bytes',
              'cold_encoded_bytes', 'baseline_total_seconds', 'candidate_total_seconds',
              'baseline_persistence_seconds', 'candidate_persistence_seconds',
              'hot_reads', 'cold_reads')
    for name in needed:
        if not _number(evidence.get(name), positive=name in ('class_read_path_seconds', 'baseline_total_seconds')):
            missing.append(name)
    exception_requested = bool(TRADEOFF_FIELDS.intersection(evidence))
    if exception_requested:
        missing.extend(sorted(TRADEOFF_FIELDS - evidence.keys()))
        if not evidence.get('report_sha256'):
            missing.append('report_sha256')
    if row['encoded_over_raw'] > 0.8:
        failed.append('encoded/raw ratio exceeds 0.8')
    if 'class_read_path_seconds' not in missing and 'added_decode_seconds' not in missing:
        if evidence['added_decode_seconds'] > .05 * evidence['class_read_path_seconds']:
            failed.append('added decode exceeds 5% of class read path')
    if 'cold_raw_bytes' not in missing and 'cold_encoded_bytes' not in missing:
        if evidence['cold_raw_bytes'] - evidence['cold_encoded_bytes'] < .01 * STORE_BYTES:
            failed.append('cold saving is below 1% of 4 GiB')
    accepted_tradeoff = None
    if 'baseline_total_seconds' not in missing and 'candidate_total_seconds' not in missing:
        requested = row.get('requested_rule') or {}
        try:
            time_ok = time_gate_passes(requested.get('codec'), requested.get('level', 1),
                requested.get('shuffle', 'byte'), dict(evidence, scope=measurement['source_kind']))
        except ValueError as error:
            time_ok = False
            failed.append('invalid approved trade-off evidence: ' + str(error))
        if not time_ok:
            failed.append('outside approved time/space trade-off' if exception_requested else
                          'no positive measured end-to-end time gain')
        elif exception_requested:
            accepted_tradeoff = evidence['tradeoff_id']
    for prefix in ('baseline', 'candidate'):
        total, persistence = f'{prefix}_total_seconds', f'{prefix}_persistence_seconds'
        if total not in missing and persistence not in missing:
            _require(evidence[persistence] <= evidence[total], 'persistence exceeds enclosing total')
    blocked = list(row['capability_gaps'])
    status = ('BLOCKED' if blocked else 'INCOMPLETE' if missing else
              'TESTED_DISABLED' if failed else 'READY_FOR_OWNER_REVIEW')
    return dict(schema=SCHEMA, array_class=measurement['array_class'], candidate=candidate_name,
        status=status, missing_evidence=missing, failed_gates=failed, capability_gaps=blocked,
        enabled=False, policy_written=False, accepted_time_tradeoff=accepted_tradeoff,
        note='Only the policy owner may enable after reviewing all matched real evidence.')


def synthetic_samples(chunk_bytes=MAX_SAMPLE_BYTES):
    """A deterministic adversarially varied fixture covering every planned class."""
    _require(type(chunk_bytes) is int and 1024 <= chunk_bytes <= MAX_SAMPLE_BYTES
             and chunk_bytes % 8 == 0, 'aligned 1..64 KiB synthetic chunk required')
    count = chunk_bytes // 8
    rng = np.random.default_rng(20261015)
    rows = {
        'csr_offsets': np.arange(count, dtype='<u8') * 3,
        'sorted_lookup': np.arange(count, dtype='<u8') * 7,
        'child_refs': np.repeat(np.arange((count + 3)//4, dtype='<u8'), 4)[:count],
        'integer_offsets': np.cumsum(np.arange(count, dtype='<u8') % 13),
        'ordinals': np.arange(count, dtype='<i8') - count//2,
        'float_fields': np.linspace(-1., 1., count, dtype='<f8'),
        'indices': np.arange(chunk_bytes//4, dtype='<u4') * 2,
        'integer_magnitudes': rng.integers(0, 256, chunk_bytes, dtype='u1'),
        'tags': np.arange(chunk_bytes, dtype='<u4').astype('u1') % 9,
    }
    for name, text in (('string_pool', b'plate/support/cell/material/'),
                       ('metadata', b'{"kind":"support","ordinal":123,"exact":true}\n'),
                       ('support_blobs', b'{"support":"hex-id","weights":["1/3","2/3"]}\n')):
        rows[name] = np.frombuffer((text * (chunk_bytes // len(text) + 1))[:chunk_bytes], dtype='u1')
    return tuple(CodecSample(name, rows[name].dtype.str, rows[name].tobytes(),
                            'deterministic synthetic WP10 component fixture') for name in ARRAY_CLASSES)


def sampling_manifest(descriptors):
    """Plan bounded sample locations from explicit metadata, without payload I/O.

    The census owner supplies authenticated array descriptors and class names;
    this helper neither infers a class from an ambiguous name nor authenticates
    a caller's source reference. Sample indices are discovery, not coverage of
    a complete real class or a permission to open its source.
    """
    descriptors = tuple(descriptors)
    _require(0 < len(descriptors) <= 256, 'one to 256 explicit descriptors required')
    rows, represented = [], set()
    for descriptor in descriptors:
        _require(type(descriptor) is dict and set(descriptor) ==
            {'array_name', 'array_class', 'dtype', 'shape', 'source_ref'}, 'exact descriptor fields required')
        name, family = descriptor['array_name'], descriptor['array_class']
        _require(type(name) is str and 0 < len(name) <= 256 and family in ARRAY_CLASSES,
                 'explicit array name and known class required')
        dt, shape = np.dtype(descriptor['dtype']), descriptor['shape']
        _require(dt.kind in 'biuf' and dt.itemsize in (1, 2, 4, 8), 'unsupported sample dtype')
        _require(type(shape) in (tuple, list) and len(shape) <= 8
                 and all(type(n) is int and n >= 0 for n in shape), 'bounded nonnegative shape required')
        reference = json.dumps(descriptor['source_ref'], sort_keys=True, allow_nan=False)
        _require(descriptor['source_ref'] and len(reference.encode()) <= 4096,
                 'bounded explicit authenticated-source reference required')
        nbytes = math.prod(shape) * dt.itemsize
        _require(nbytes <= 512 << 20, 'descriptor exceeds unchanged max_array bound')
        chunks = (nbytes + MAX_SAMPLE_BYTES - 1) // MAX_SAMPLE_BYTES
        indices = sorted({0, chunks//2, chunks-1}) if chunks else []
        rows.append(dict(descriptor, logical_bytes=nbytes, proposed_chunk_indices=indices,
                         payload_read=False, source_authentication='CALLER_REQUIRED'))
        if chunks:
            represented.add(family)
    return dict(schema=SCHEMA, status='INCOMPLETE', arrays=rows,
                missing_classes=sorted(set(ARRAY_CLASSES)-represented), payload_reads=0,
                enabled=False, note='Metadata-only sampling plan; real reads remain with the census owner.')


def measure_fixture(store, *, repeats=3, warmups=1, capabilities=None, candidates=None,
                    backend_capabilities=None, encode_candidate=None,
                    decode_candidate=None, workspace_bound=None):
    """One small synthetic report over all classes; no store writes or opens."""
    reports = [measure_class(store, [sample], candidates=candidates, repeats=repeats, warmups=warmups,
               backend_capabilities=backend_capabilities, encode_candidate=encode_candidate,
               decode_candidate=decode_candidate, workspace_bound=workspace_bound)
               for sample in synthetic_samples()]
    return dict(schema=SCHEMA, status='SYNTHETIC_ONLY', enabled=False,
        capabilities=capability_report() if capabilities is None else capabilities,
        expected_classes=list(ARRAY_CLASSES), covered_classes=[r['array_class'] for r in reports],
        missing_classes=sorted(set(ARRAY_CLASSES)-{r['array_class'] for r in reports}),
        classes=reports, persistence_seconds=None, physical_database_bytes=None,
        process_peak_rss_bytes=None, production_adoption='INCOMPLETE',
        limitations=['No real compact census, representative read counts or end-to-end persistence run.',
                     'Effective labels identify actual encoders; raw fallback timing is not native codec timing.',
                     'Workspace is conservative candidate admission, not measured process RSS.'])


def _receiver(runtime_src):
    """Construct a database-free native codec receiver in a fresh CLI process."""
    runtime_src = Path(runtime_src).resolve()
    source = runtime_src / 'atlas_tectonics' / 'storage.py'
    _require(source.is_file(), 'explicit native runtime source required')
    _require('atlas_tectonics.storage' not in sys.modules, 'CLI requires a fresh native runtime import')
    sys.path.insert(0, str(runtime_src))
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    from atlas_tectonics.resources import WorkBudget

    class MemoryReceiver(ArrayStore):
        _codec_original_decode = ArrayStore._decode

        def __init__(self):
            # No ArrayStore constructor: no SQLite path or database is opened.
            self.compression = Compression(codec='raw', palette=True)
            self.limits = StoreLimits(chunk_bytes=65536, max_array_bytes=512 << 20,
                                     max_store_bytes=4 << 30, max_staging_bytes=1 << 30)
            self._budget = WorkBudget(64 << 20)
            self._stats = {'encodes': 0}

    return MemoryReceiver(), dict(path=str(source), sha256=sha256(source.read_bytes()).hexdigest())


def _write_new(path, value):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--capabilities', action='store_true')
    modes.add_argument('--synthetic', action='store_true')
    parser.add_argument('--runtime-src')
    parser.add_argument('--native-library', help='explicit private WP10 DLL; never discovered or installed')
    parser.add_argument('--native-sha256', help='required trusted DLL identity')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    _require(bool(args.native_library) == bool(args.native_sha256),
             'native library and expected SHA-256 must be supplied together')
    output = Path(args.output).resolve()
    bundle = output.with_suffix('.bundle')
    _require(not os.path.lexists(output), 'measurement output already exists')
    if args.synthetic:
        _require(bundle != output and not os.path.lexists(bundle),
                 'completed bundle destination must be new and distinct')
    if args.capabilities:
        result = capability_report()
    else:
        _require(args.runtime_src is not None, '--synthetic requires explicit --runtime-src')
        store, native_source = _receiver(args.runtime_src)
        capabilities = None
        if args.native_library:
            from storage_zstd_backend import ZstdBackend
            store._codec_backend = ZstdBackend(args.native_library, expected_sha256=args.native_sha256)
            capabilities = {'zstd': {'status': 'AVAILABLE', 'provenance': args.native_sha256},
                            'delta-zstd-v1': {'status': 'AVAILABLE', 'provenance': args.native_sha256},
                            'trained-zstd-v1': {'status': 'BLOCKED', 'provenance': args.native_sha256,
                                               'reason': 'class-specific retained dictionary not supplied'}}
        # Dictionary trials require separately trained, class-bound inputs; the
        # generic synthetic suite must not silently use another class's dictionary.
        candidates = tuple(c for c in default_candidates() if c.name != 'trained-dictionary') if capabilities else None
        result = measure_fixture(store, candidates=candidates, backend_capabilities=capabilities)
        result['native_source'] = native_source
        _require(store._budget.reserved_bytes == 0, 'measurement still owns workspace')
    _write_new(output, result)
    completion = {'output': str(output), 'status': result['status'], 'enabled': False}
    if args.synthetic and output.stat().st_size >= 64 << 10:
        # Closed diagnostic export is a separate bounded phase. Keep the JSON
        # even if archive selection or publication fails; never time it as codec work.
        from atlas_tectonics.resources import WorkBudget
        from cold_archive import finalise_completed_bundle
        offline_budget = WorkBudget(256 << 20)
        here = Path(__file__).resolve().parent
        # A report plus the configuration/provenance needed to interpret it is
        # a useful multi-file bundle. Do not tar a lone JSON file for its suffix.
        with tempfile.TemporaryDirectory(prefix='wp10-export-', dir=output.parent) as directory:
            staging = Path(directory)
            sources = [(output, 'measurement.json'), (here/'codec_policy.json', 'policy-snapshot.json')]
            build = here/'native/build_manifest.json'
            if args.native_library and build.is_file():
                with build.open('rb') as source:
                    metadata = source.read((256 << 10) + 1)
                _require(len(metadata) <= 256 << 10, 'build provenance exceeds export bound')
                if json.loads(metadata)['codec']['output_sha256'] == args.native_sha256:
                    sources.append((build, 'native-build.json'))
            # Stream copies; these are explicit completed artefacts, not a sweep
            # of the working directory or an archive of live control files.
            with offline_budget.reserve(1 << 20, category='cold-export-staging'):
                for source_path, name in sources:
                    _require(source_path.stat().st_size <= 64 << 20, 'export source exceeds bundle bound')
                    with source_path.open('rb') as source, (staging/name).open('xb') as target:
                        total = 0
                        while block := source.read(65536):
                            total += len(block)
                            _require(total <= 64 << 20, 'export source grew beyond bundle bound')
                            target.write(block)
            receipt = finalise_completed_bundle(staging, [name for _, name in sources], bundle,
                kind='completed-diagnostics', budget=offline_budget)
        _require(offline_budget.reserved_bytes == 0, 'completed export still owns workspace')
        completion['bundle'] = {key: receipt[key] for key in
            ('receipt_path', 'selected_format', 'receipt_sha256')}
    elif args.synthetic:
        completion['bundle'] = {'status': 'SKIPPED', 'reason': 'report is smaller than 64 KiB'}
    print(json.dumps(completion))
    return 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
