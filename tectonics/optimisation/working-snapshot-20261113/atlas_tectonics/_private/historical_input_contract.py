"""One fixed external historical-input contract; importing reads no input data.

This contract supplies names and pins, never historical admission or a replacement
review. Runtime profiles explicitly bind its ordinary workspace-contained file.
The descriptor itself is private data and is never installed in the package.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


CATALOGUE_SHA256 = '019944bf42007397c3cacb8756ea2e62862afa5170c79e28601d7a914cd86d22'
CATALOGUE_SCHEMA = 'atlas.fixed-historical-inputs.v1'
MAX_CATALOGUE_BYTES = 64 << 10
ROLES = ('producer', 'producer_guard', 'reader', 'reader_guard', 'preparation')
_SEAL = object()
_HEX = re.compile(r'[0-9a-f]{64}')


class HistoricalInputsRefused(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise HistoricalInputsRefused(message)


def _pin(value):
    _require(type(value) is str and _HEX.fullmatch(value) is not None, 'Exact lowercase SHA-256 required')
    return value


def _relative(value):
    _require(type(value) is str and value and '\\' not in value and ':' not in value and '\0' not in value,
             'Plain relative POSIX name required')
    parts = value.split('/')
    _require(all(p not in ('', '.', '..') for p in parts) and not PurePosixPath(value).is_absolute()
             and PurePosixPath(value).as_posix() == value, 'Noncanonical relative input name')
    return value


def _ordinary(value, *, directory=False):
    _require(isinstance(value, (str, Path)), 'Explicit ordinary path required')
    path = Path(value)
    _require(path.is_absolute() and not path.drive.startswith('\\\\')
             and '..' not in path.parts and ':' not in str(path)[2:]
             and not any(p.casefold() == 'bridge' for p in path.parts), 'Local absolute non-bridge path required')
    try:
        for part in (path, *path.parents):
            info = os.lstat(part)
            _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                     'Linked or reparse input refused')
        info = os.lstat(path)
        _require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
                 'Ordinary directory required' if directory else 'Ordinary file required')
        return path.resolve(strict=True)
    except OSError as error:
        raise HistoricalInputsRefused('Ordinary input is unavailable') from error


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_fixed(path):
    path = _ordinary(path)
    before = os.stat(path)
    _require(before.st_size <= MAX_CATALOGUE_BYTES, 'Historical input catalogue exceeds bound')
    try:
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            _require(_identity(opened) == _identity(before), 'Historical input catalogue replaced before read')
            raw = stream.read(MAX_CATALOGUE_BYTES+1)
            _require(len(raw) <= MAX_CATALOGUE_BYTES, 'Historical input catalogue exceeds bound')
            _require(_identity(os.fstat(stream.fileno())) == _identity(opened),
                     'Historical input catalogue changed during read')
        _require(_identity(os.stat(_ordinary(path))) == _identity(before),
                 'Historical input catalogue replaced after read')
    except OSError as error:
        raise HistoricalInputsRefused('Historical input catalogue could not be read') from error
    _require(sha256(raw).hexdigest() == CATALOGUE_SHA256, 'Fixed historical input catalogue digest differs')
    return raw


def _pairs(rows):
    result = {}
    for key, value in rows:
        _require(key not in result, 'Duplicate historical input key')
        result[key] = value
    return result


def _invalid_number(_value):
    raise HistoricalInputsRefused('Nonfinite historical input number')


def _parse(raw):
    try:
        row = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_number)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise HistoricalInputsRefused('Malformed historical input catalogue') from error
    _require(type(row) is dict and set(row) == {'schema', 'historical_relative', 'historical_native_relative',
        'reviewed_original', 'evidence_roles', 'initial_cache'} and row['schema'] == CATALOGUE_SCHEMA,
        'Closed historical input catalogue schema required')
    historical = _relative(row['historical_relative'])
    native = _relative(row['historical_native_relative'])
    review = row['reviewed_original']
    _require(type(review) is dict and set(review) == {'metadata_sources', 'evidence', 'database_name',
        'database_sha256'}, 'Closed historical review required')

    def pair_table(value, count, *, modules=False):
        _require(type(value) is list and len(value) == count, 'Complete historical input table required')
        result = []
        for pair in value:
            _require(type(pair) is list and len(pair) == 2, 'Historical input pair required')
            name = _relative(pair[0])
            _require(not modules or name.isidentifier(), 'Plain historical metadata module required')
            result.append((name, _pin(pair[1])))
        _require(len({p[0] for p in result}) == count, 'Historical input names must be unique')
        return tuple(result)

    metadata = pair_table(review['metadata_sources'], 3, modules=True)
    evidence = pair_table(review['evidence'], len(ROLES))
    roles = row['evidence_roles']
    _require(type(roles) is dict and set(roles) == set(ROLES), 'Exact historical evidence roles required')
    _require(all(type(roles[k]) is str and roles[k] == evidence[i][0] for i, k in enumerate(ROLES)),
             'Historical role/order binding differs')
    database = _relative(review['database_name'])
    database_pin = _pin(review['database_sha256'])
    cache = row['initial_cache']
    _require(type(cache) is dict and set(cache) == {'relative_to_original_source_directory', 'sha256'},
             'Closed initial-cache binding required')
    cache_name = _relative(cache['relative_to_original_source_directory'])
    cache_pin = _pin(cache['sha256'])
    return (historical, native, metadata, evidence, database, database_pin, cache_name, cache_pin)


@dataclass(frozen=True, slots=True, init=False)
class HistoricalInputs:
    """Immutable authenticated data, scoped to one explicit workspace and file."""
    workspace: Path
    path: Path
    relative_path: str
    _values: tuple
    _seal: object

    def verify(self):
        _require(type(self) is HistoricalInputs and getattr(self, '_seal', None) is _SEAL,
                 'Verified fixed historical inputs required')
        _require(self.path == self.workspace/self.relative_path,
                 'Historical input catalogue workspace binding changed')
        _require(_parse(_read_fixed(self.path)) == self._values,
                 'Historical input catalogue value binding changed')
        return self

    @property
    def historical_relative(self):
        return self._values[0]

    @property
    def historical_native_relative(self):
        return self._values[1]

    def reviewed_original(self):
        """Reconstruct exactly the original four fields and tuple-valued tables."""
        return dict(metadata_sources=self._values[2], evidence=self._values[3],
                    database_name=self._values[4], database_sha256=self._values[5])

    def evidence_name(self, role):
        _require(type(role) is str and role in ROLES, 'Known historical evidence role required')
        return self._values[3][ROLES.index(role)][0]

    @property
    def initial_cache_relative(self):
        return self._values[6]

    @property
    def initial_cache_sha256(self):
        return self._values[7]

    def expected_root(self):
        """The spelling only: fresh callers never need this directory to exist."""
        return self.workspace/self.historical_relative

    def historical_root(self, explicit):
        """Current-workspace anchor and original suffix; never discover a root."""
        self.verify()
        root = _ordinary(explicit, directory=True)
        _require(root == self.expected_root(), 'Historical root differs from the current workspace binding')
        suffix = tuple(self.historical_relative.split('/'))
        _require(tuple(p.casefold() for p in root.parts[-len(suffix):]) == tuple(p.casefold() for p in suffix),
                 'Historical root suffix differs')
        return root

    def contains_historical_tree(self, value):
        """Preserve the copied-tree refusal wherever its component sequence occurs."""
        parts = tuple(p.casefold() for p in Path(value).parts)
        suffix = tuple(p.casefold() for p in self.historical_relative.split('/'))
        return any(parts[i:i+len(suffix)] == suffix for i in range(len(parts)-len(suffix)+1))

    def historical_import_path(self, entry):
        """The original import-path test, using only the verified root spelling."""
        root = self.expected_root()
        path = Path(entry or '.').resolve()
        if not path.is_relative_to(root):
            return False
        relative = path.relative_to(root).parts
        native = tuple(self.historical_native_relative.split('/'))
        # Retain the original native-source sibling and composed-generation rule.
        source_native = ('source', 'tectonics', 'src')
        prefix = native[0].rsplit('-r', 1)[0]+'-r'
        return not relative or relative == source_native or relative[0].startswith(prefix)


def verified(value):
    _require(type(value) is HistoricalInputs and getattr(value, '_seal', None) is _SEAL,
             'Verified fixed historical inputs required')
    return value.verify()


def load(workspace, binding, manifest):
    """Read one explicitly pinned data-only descriptor; no alternate review SHA."""
    workspace = _ordinary(workspace, directory=True)
    _require(type(binding) is dict and set(binding) == {'path', 'sha256'},
             'Exact historical-input path/sha256 reference required')
    relative = _relative(binding['path'])
    _require(_pin(binding['sha256']) == CATALOGUE_SHA256, 'Only the fixed historical input digest is accepted')
    _require(type(manifest) is dict and type(manifest.get('files')) is dict
             and type(manifest.get('data_only')) is dict, 'Executable/data manifest tables required')
    _require(relative not in manifest['files'] and manifest['data_only'].get(relative) == CATALOGUE_SHA256,
             'Historical input descriptor must be pinned as data-only')
    _require(CATALOGUE_SHA256 not in manifest['files'].values(),
             'Historical input descriptor bytes alias an executable source')
    path = _ordinary(workspace/relative)
    _require(path.is_relative_to(workspace) and path == workspace/relative, 'Historical input descriptor outside workspace')
    values = _parse(_read_fixed(path))
    result = object.__new__(HistoricalInputs)
    for name, value in dict(workspace=workspace, path=path, relative_path=relative, _values=values, _seal=_SEAL).items():
        object.__setattr__(result, name, value)
    return result
