"""Package-relative source identity (R1 fold, FOLD.md §2-§3, §11.4). Every recorded source key is built by relkey
and every file read by key goes through resolve, so no record and no check depends on the folder the package sits
in. Written by the fold; the parity gate requires these exact bytes."""
import os
from pathlib import Path

PKG_PARENT = Path(__file__).resolve().parent.parent
_PACKAGE = PKG_PARENT/'atlas_tectonics'
_PRIVATE = 'atlas_tectonics._private.'
_REPARSE_POINT = 0x400


class IdentityError(ValueError):
    pass


def _inside(real):
    return real == _PACKAGE or _PACKAGE in real.parents


def _is_key(value):
    return isinstance(value, str) and value.startswith('atlas_tectonics/') and '\\' not in value and ':' not in value


def resolve(key):
    """The real path of a package-relative key; anything that is not such a key is refused."""
    if not isinstance(key, str) or '\\' in key or ':' in key or key.startswith('/'):
        raise IdentityError('not a package-relative key: %r' % (key,))
    parts = key.split('/')
    if parts[0] != 'atlas_tectonics' or any(part in ('', '.', '..') for part in parts):
        raise IdentityError('not a package-relative key: %r' % (key,))
    real = (PKG_PARENT/key).resolve()
    if not _inside(real):
        raise IdentityError('key leaves the package: %r' % (key,))
    return real


def as_path(value):
    """A key as its authenticated lexical package path; any other value as Path(value).

    Keep the lexical spelling so the ordinary-source reader can refuse linked or
    reparsed ancestors. Path(key) inputs retain the same package-key meaning.
    """
    key = value.as_posix() if isinstance(value, Path) and not value.anchor else value
    if _is_key(key):
        resolve(key)  # Validate canonical key spelling and package containment.
        return PKG_PARENT/key
    return Path(value)


def relkey(path):
    """The POSIX key of a path (or a key) inside the package, relative to the folder that contains the package."""
    real = as_path(path).resolve()
    if not _inside(real):
        raise IdentityError('not inside the atlas_tectonics package: %s' % Path(path).name)
    return real.relative_to(PKG_PARENT).as_posix()


def join(base, name):
    """base/name, except that a key names its package file; a name with a drive or root is refused."""
    if _is_key(name):
        return resolve(name)
    if Path(name).anchor:
        raise IdentityError('an absolute name cannot be joined: %s' % Path(name).name)
    return base/name


_HEAT = _PRIVATE + 'integration.heat.'
_HEAT_OTHER_OWNERS = frozenset(('cold_bridge', 'cold_transport', 'heat_cold_patch', 'heat_interval_spec',
                                'heat_ledger_issuer_patch', 'heat_payload_indexed_patch',
                                'historical_compact_heat', 'runtime_radial_fixture'))


def is_private_heat_module(name):
    """The former private_heat family, including its retained and regrouped members."""
    if name.startswith(_HEAT):
        return name[len(_HEAT):] not in _HEAT_OTHER_OWNERS
    return name.startswith(_PRIVATE + 'private_heat_')


def module_name(source_key):
    """A qualified module name from a package source key."""
    key = Path(source_key)
    if (not _is_key(source_key) or key.as_posix() != source_key or key.suffix != '.py'
            or not all(part.isidentifier() for part in key.with_suffix('').parts)):
        raise IdentityError('not a Python package source key: %r' % (source_key,))
    return '.'.join(key.with_suffix('').parts)


def members(items):
    """The items of a package source walk outside atlas_tectonics/_private: the folded helpers are bound by their
    pins, as the unfolded helpers were, not by package membership. A reparse point at that folder is refused."""
    for item in items:
        parts = [os.path.normcase(part) for part in Path(os.fspath(item)).parts]
        if any(a == 'atlas_tectonics' and b == '_private' for a, b in zip(parts, parts[1:])):
            if isinstance(item, os.DirEntry) and \
                    getattr(item.stat(follow_symlinks=False), 'st_file_attributes', 0) & _REPARSE_POINT:
                raise IdentityError('the private helper folder is a reparse point')
            continue
        yield item
