"""Fresh complete cache inventories with shared ancestor checks.

Every new write and startup still walks every record under the native lock.
Only repeated ancestor traversal is removed: lexical root ancestors are checked
before and after the walk, namespace identity is checked around each child walk,
and each child receives a fresh lstat for its type, links and size. There is no
persistent byte index, mtime-based trust or batch lock spanning producer calls.

The R12 local-owner/hostile-concurrent-ancestor-replacement limitations remain;
this is not a filesystem security boundary. Cooperating stores retain the same
cross-process lock, including older stores sharing this root. Saved content is
still authenticated by the unchanged read/write bodies inherited through R23.
"""

import stat

from work.generator_runtime_r12 import store as native
from work.generator_upgrade_r23.storage import Store as PreviousStore


def _entry(path, *, directory):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise native.CacheError("Linked or reparse cache paths are forbidden")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise native.CacheError("Cache directory is not a directory")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise native.CacheError("Cache files must be unlinked regular files")
    return info


def _same_directory(path, before):
    after = _entry(path, directory=True)
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise native.CacheError("Cache directory changed during inventory")


class Store(PreviousStore):
    """R23-compatible store; full inventories avoid repeated ancestor stats."""

    def _inventory_bytes(self):
        native._check_path(self.root, directory=True)
        root_before = _entry(self.root, directory=True)
        total = 0
        try:
            for path in self.root.iterdir():
                if path.name in (native._KEY_NAME, native._LOCK_NAME):
                    total += _entry(path, directory=False).st_size
                elif native._SHA.fullmatch(path.name):
                    before = _entry(path, directory=True)
                    try:
                        for record in path.iterdir():
                            if record.suffix != ".json" or native._SHA.fullmatch(record.stem) is None:
                                raise native.CacheError("Unexpected file in dedicated cache namespace")
                            size = _entry(record, directory=False).st_size
                            if size > native.MAX_RECORD_BYTES:
                                raise native.CacheError("Saved cache file exceeds its byte limit")
                            total += size
                    finally:
                        _same_directory(path, before)
                else:
                    raise native.CacheError("Unexpected file in dedicated cache root")
            return total
        finally:
            native._check_path(self.root, directory=True)
            _same_directory(self.root, root_before)
