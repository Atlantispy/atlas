"""Assemble a relocatable Windows app; no installs, native edits or old-output overwrite."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import zipfile

ELECTRON_SHA256 = '11c395820a5aaa8ebcc0686b476d0ac98a730274ebfbdc8cf5538a7c2815cb5d'
ROOT = Path(__file__).resolve().parents[1]
UI_FILES = '''index.html styles.css fonts.css app.mjs state.mjs views.mjs project.mjs
persistence.mjs image-source.mjs result-data.mjs saved-result.mjs job-ui.mjs
section-data.mjs section-ui.mjs new-world-data.mjs new-world-ui.mjs world-data.mjs
world-ui.mjs world-views.mjs world-structure-ui.mjs world-motion-ui.mjs
evolution-data.mjs evolution-ui.mjs evolution-views.mjs serve.mjs result-reader.mjs
job-manager.mjs view-reader.mjs new-world-bridge.mjs world-manager.mjs
evolution-manager.mjs native-launch.mjs bundle-data.mjs'''.split()
UI_PIN = ROOT / 'desktop' / 'ui-snapshot.json'      # tracked name -> SHA-256 pin of the UI owner's snapshot
UI_PIN_SCHEMA = 'atlas.desktop-ui-snapshot.v1'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plain_path(path):
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('Linked build paths are unsupported.')
    return path


def copy_file(source, target):
    if source.is_symlink() or source.is_junction() or not source.is_file():
        raise ValueError(f'Not a plain source file: {source.name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)


def copy_tree(source, target, select=lambda p: True):
    for item in source.rglob('*'):
        if item.is_symlink() or item.is_junction():
            raise ValueError(f'Symlink in payload: {item.name}')
        if item.is_file() and '__pycache__' not in item.parts and select(item):
            copy_file(item, target / item.relative_to(source))


def ui_snapshot(ui, pin=UI_PIN):
    """Digests of the 33 UI files, which must equal the pinned snapshot exactly; checked before any output."""
    try:
        record = json.loads(pin.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise ValueError('No pinned UI snapshot: create desktop/ui-snapshot.json from the accepted '
                         "build's manifest (see desktop/README.md).") from None
    if type(record) is not dict or record.get('schema') != UI_PIN_SCHEMA:
        raise ValueError('Unsupported UI snapshot pin.')
    files = record.get('files')
    if type(files) is not dict or sorted(files) != sorted(UI_FILES):
        raise ValueError('The UI snapshot pin must list exactly the 33 UI files.')
    found = {}
    for name in UI_FILES:
        source = ui / name
        if source.is_symlink() or source.is_junction() or not source.is_file():
            raise ValueError(f'Not a plain UI file: {name}')
        found[name] = digest(source)
    changed = [name for name in UI_FILES if found[name] != files[name]]
    if changed:
        raise ValueError('UI files differ from the pinned snapshot: ' + ', '.join(changed))
    return found


def seal(output):
    files = {p.relative_to(output).as_posix(): digest(p)
             for p in sorted(output.rglob('*')) if p.is_file() and p != output / 'build-manifest.json'}
    manifest = {'schema': 'atlas.desktop-build.v1', 'electron': '44.4.5',
                'status': 'WORKING NON-CANON', 'scientific_acceptance': False, 'files': files}
    (output / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['electron', 'python', 'ui', 'output']:
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--refresh-launcher', type=Path, help='Update only desktop-owned files of an existing development build')
    args = parser.parse_args()
    if args.refresh_launcher:
        output = plain_path(args.refresh_launcher)
        manifest = json.loads((output / 'build-manifest.json').read_text(encoding='utf-8'))
        if manifest.get('schema') != 'atlas.desktop-build.v1' or digest(output / 'Atlas.exe') != manifest['files']['Atlas.exe']:
            raise ValueError('Not the expected existing Atlas development build.')
        for name in ['package.json', 'main.cjs', 'runtime.cjs', 'smoke.cjs']:
            target = plain_path(output / 'resources' / 'app' / name)
            shutil.copyfile(ROOT / 'desktop' / name, target)
        shutil.copyfile(ROOT / 'desktop' / 'README.md', plain_path(output / 'README.md'))
        print(json.dumps({'status': 'launcher refreshed', 'files': seal(output)}))
        return
    if any(getattr(args, name) is None for name in ['electron', 'python', 'ui', 'output']):
        parser.error('--electron, --python, --ui and --output are required for a new build')
    for name in ['electron', 'python', 'ui', 'output']:
        setattr(args, name, plain_path(getattr(args, name)))
    if args.output.exists():
        raise ValueError('Use a new output directory; existing builds are never removed.')
    copied_roots = [args.python, args.ui] + [ROOT / 'tectonics' / p for p in ['src', 'tools', 'cases', 'requirements']]
    if any(args.output.is_relative_to(p) or p.is_relative_to(args.output) for p in copied_roots):
        raise ValueError('Build output must not overlap copied source trees.')
    if digest(args.electron) != ELECTRON_SHA256:
        raise ValueError('Electron checksum mismatch.')
    pinned_ui = ui_snapshot(args.ui)
    args.output.mkdir(parents=True)
    with zipfile.ZipFile(args.electron) as archive:
        for info in archive.infolist():
            path = Path(info.filename)
            if path.is_absolute() or '..' in path.parts or ':' in info.filename or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Unsafe Electron archive member.')
        archive.extractall(args.output)
    (args.output / 'electron.exe').rename(args.output / 'Atlas.exe')
    app = args.output / 'resources' / 'app'
    for name in ['package.json', 'main.cjs', 'runtime.cjs', 'smoke.cjs']:
        copy_file(ROOT / 'desktop' / name, app / name)
    # UI is the owner's pinned source snapshot, with tests/private records excluded.
    for name in UI_FILES:
        copy_file(args.ui / name, app / 'ui' / name)
    if {name: digest(app / 'ui' / name) for name in UI_FILES} != pinned_ui:
        raise ValueError('Copied UI files differ from the pinned snapshot.')
    native = args.output / 'resources' / 'atlas'
    for name in ['src', 'tools']:
        copy_tree(ROOT / 'tectonics' / name, native / 'tectonics' / name, lambda p: p.suffix == '.py')
    copy_tree(ROOT / 'tectonics' / 'cases', native / 'tectonics' / 'cases', lambda p: p.suffix == '.json')
    copy_tree(ROOT / 'tectonics' / 'requirements', native / 'tectonics' / 'requirements')
    for name in ['LICENSE', 'LICENSING.md']:
        copy_file(ROOT / name, native / name)
    copy_file(ROOT / 'tectonics' / 'LICENSE', native / 'tectonics' / 'LICENSE')
    copy_file(ROOT / 'tectonics' / 'pyproject.toml', native / 'tectonics' / 'pyproject.toml')
    copy_file(ROOT / 'desktop' / 'README.md', args.output / 'README.md')
    copy_tree(args.python, args.output / 'resources' / 'python')
    # Bind this build's actual delivered bytes; no historical receipt is repinned.
    count = seal(args.output)
    print(json.dumps({'status': 'built', 'files': count,
                      'bytes': sum(p.stat().st_size for p in args.output.rglob('*') if p.is_file()),
                      'executable': str(args.output / 'Atlas.exe')}))


if __name__ == '__main__':
    main()
