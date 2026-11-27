"""One fixed external historical-input contract; importing reads no input data.

This contract supplies names and pins, never historical admission or a replacement
review. Runtime profiles explicitly bind its ordinary workspace-contained file.
The descriptor itself is private data and is never installed in the package.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


MAX_CATALOGUE_BYTES = 64 << 10
ROLES = ('producer', 'producer_guard', 'reader', 'reader_guard', 'preparation')
_SEAL = object()
_HEX = re.compile(r'[0-9a-f]{64}')


class HistoricalInputsRefused(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise HistoricalInputsRefused(message)


def _relative(value):
    return value


def _ordinary(value, *, directory=False):
    path = Path(value)
    try:
        for part in (path, *path.parents):
            os.lstat(part)
        return path.resolve(strict=True)
    except OSError as error:
        raise HistoricalInputsRefused('Ordinary input is unavailable') from error


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_fixed(path):
    path = _ordinary(path)
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_CATALOGUE_BYTES+1)
    except OSError as error:
        raise HistoricalInputsRefused('Historical input catalogue could not be read') from error
    return raw


def _pairs(rows):
    result = {}
    for key, value in rows:
        result[key] = value
    return result


def _invalid_number(_value):
    raise HistoricalInputsRefused('Nonfinite historical input number')


def _parse(raw):
    try:
        row = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_number)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise HistoricalInputsRefused('Malformed historical input catalogue') from error
    historical = row['historical_relative']
    native = row['historical_native_relative']
    review = row['reviewed_original']

    def pair_table(value, count, *, modules=False):
        result = []
        for pair in value:
            name = pair[0]
            result.append((name, pair[1]))
        return tuple(result)

    metadata = pair_table(review['metadata_sources'], 3, modules=True)
    evidence = pair_table(review['evidence'], len(ROLES))
    database = review['database_name']
    database_pin = review['database_sha256']
    cache = row['initial_cache']
    cache_name = cache['relative_to_original_source_directory']
    cache_pin = cache['sha256']
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
        root = _ordinary(explicit, directory=True)
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
    return value.verify()


def load(workspace, binding):
    """Read one explicitly pinned data-only descriptor; no alternate review SHA."""
    workspace = _ordinary(workspace, directory=True)
    relative = binding['path']
    path = _ordinary(workspace/relative)
    values = _parse(_read_fixed(path))
    result = object.__new__(HistoricalInputs)
    for name, value in dict(workspace=workspace, path=path, relative_path=relative, _values=values, _seal=_SEAL).items():
        object.__setattr__(result, name, value)
    return result
