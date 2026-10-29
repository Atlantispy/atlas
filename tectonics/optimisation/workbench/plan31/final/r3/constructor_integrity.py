"""Pinned constructor integrity primitives; no payload execution."""
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat


COMPOSITION_FIELDS = {'codec_policy', 'completed_query_store', 'frozen', 'helpers', 'outputs',
                      'reviewed_inputs', 'reviewed_inputs_sha256', 'root', 'root_rule', 'schema', 'staged', 'stages'}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def digest(raw):
    return sha256(raw).hexdigest()

def pin(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'exact lowercase SHA-256 required')
    return value

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def exists(path):
    return os.path.lexists(path)

def ordinary(path, *, directory=False):
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(), 'canonical absolute path required: ' + str(path))
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked/reparse path refused: ' + str(item))
    require(path.is_dir() if directory else path.is_file(), 'ordinary path required: ' + str(path))
    return path

def member(root, name):
    require(type(name) is str and name and '\\' not in name and ':' not in name, 'noncanonical member: ' + str(name))
    parts = PurePosixPath(name).parts
    require(not PurePosixPath(name).is_absolute() and '/'.join(parts) == name and
            all(p not in ('.', '..') and p.rstrip(' .') == p for p in parts), 'member escape/alias refused: ' + name)
    path = ordinary(root / name)
    require(path.is_relative_to(root), 'member escaped its explicit root: ' + name)
    return path

def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result

class Inputs:
    def __init__(self):
        self.pins = {}
        self.inventories = []

    def raw(self, path, expected):
        path = ordinary(path)
        before = path.stat()
        data = path.read_bytes()
        after = ordinary(path).stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'source changed during read: ' + str(path))
        actual = digest(data)
        require(actual == pin(expected), 'source differs from its explicit pin: ' + str(path))
        require(self.pins.get(str(path), actual) == actual, 'source changed between reads: ' + str(path))
        self.pins[str(path)] = actual
        return data

    def doc(self, path, expected):
        return json.loads(self.raw(path, expected), object_pairs_hook=unique,
                          parse_constant=lambda text: require(False, 'nonfinite JSON: ' + text))

    def verify(self, path, expected):
        known = self.pins.get(str(path))
        if known is None:
            self.raw(path, expected)
        else:
            require(known == pin(expected), 'conflicting source binding: ' + str(path))

    def recheck(self):
        for path, expected in tuple(self.pins.items()):
            self.raw(path, expected)
        for root, names in self.inventories:
            require(set(inventory(root)) == names, 'composition membership changed: ' + str(root))

def inventory(root, inputs=None, expected=None):
    """Traverse only an explicit src/helpers root; read bytes only under declared pins."""
    ordinary(root, directory=True)
    names = {}
    folded = set()
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            ordinary(Path(folder) / name, directory=True)
        for name in files:
            path = ordinary(Path(folder) / name)
            key = path.relative_to(root).as_posix()
            require(key.casefold() not in folded, 'case-alias inventory collision: ' + key)
            folded.add(key.casefold())
            if inputs is None:
                names[key] = None
            else:
                require(type(expected) is dict and key in expected, 'unrecorded composition member: ' + key)
                names[key] = digest(inputs.raw(path, expected[key]))
    if expected is not None:
        require(set(names) == set(expected), 'missing or extra composition members: ' + str(root))
    return names

def composition(inputs, root, value, reviewed_path, reviewed_pin):
    doc = inputs.doc(root / 'composition.json', pin(value))
    require(type(doc) is dict and set(doc) == COMPOSITION_FIELDS and
            doc['schema'] == 'atlas.private.resumable-composition.r3' and doc['root'] == str(root) and
            doc['frozen'] is False and doc['completed_query_store'] == 'files', 'composition contract differs')
    require({p.name for p in root.iterdir()} == {'src', 'helpers', 'composition.json'}, 'unexpected composition-root entries')
    require(doc['reviewed_inputs'] == str(reviewed_path) and doc['reviewed_inputs_sha256'] == reviewed_pin,
            'composition reviewed-input binding differs')
    reviewed = inputs.doc(reviewed_path, pin(reviewed_pin))
    native = inventory(root / 'src', inputs, doc['outputs'])
    helpers = inventory(root / 'helpers', inputs, doc['helpers'])
    inputs.inventories.extend(((root / 'src', set(native)), (root / 'helpers', set(helpers))))
    require(reviewed['outputs'] == native and {name: row['sha256'] for name, row in reviewed['helpers'].items()} == helpers and
            reviewed['staged'] == doc['staged'] and reviewed['stages'] == doc['stages'] and
            reviewed['target_root'] == str(root) and reviewed['target'] == root.name,
            'reviewed record differs from actual composition')
    return doc, reviewed, native, helpers
