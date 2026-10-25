"""S1 Stage A: guarded freshness (sealed_guard_set) for sealed interval readers on Windows/NTFS.

Synthetic data only (plain files and real native SQLite files under the tree's _t folder); no timing assertions.
Each test names the fault cases of the S1 freshness design (r2, section 6) it kills. Error 32 is the sharing
violation the guards cause; NTFS itself answers 5 (access denied) for a read-only file or an ancestor of an open
file, so asserting 32 shows that the guard, not something else, refused.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
import ctypes
import gc
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import interval_store_set as ISS
import sealed_guard_set as G
import test_interval_store_set as ist
import test_s1_sealed_read as s1
import test_segment_store as fixture
from compact_contracts import ContractError
from interval_catalog import file_token
from interval_store_set import ReadOnlyNative

TMP = fixture.TASK / '_t'
CHUNK = s1.CHUNK
WINDOWS_ONLY = unittest.skipUnless(os.name == 'nt', 'Stage A guards are Windows-only; elsewhere readers walk')


def handle_count():
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    count = wintypes.DWORD()
    if not kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    return count.value


def changed(info, **fields):
    """A stat double: info's fields, some replaced."""
    names = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink', 'st_file_attributes')
    values = {name: getattr(info, name, 0) for name in names}
    values.update(fields)
    return SimpleNamespace(**values)


def refused_by_guard(test, attempt):
    with test.assertRaises(PermissionError) as caught:
        attempt()
    test.assertEqual(caught.exception.winerror, 32, caught.exception)


def write_open(path, access=0x40000000):
    """Open path for writing (GENERIC_WRITE by default), sharing everything; keeps the Windows error open() drops."""
    handle = G._open(str(path), access, 0x7, 0)
    G._kernel()[2].CloseHandle(handle)


@WINDOWS_ONLY
class GuardSetTests(unittest.TestCase):
    """The guard set on plain files: what it holds, binds, refuses and releases."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='s1a-', dir=TMP))
        self.dir = self.root / 'a' / 'b'
        self.dir.mkdir(parents=True)
        self.file = self.dir / 'interval-0000.sqlite'
        self.file.write_bytes(b'x' * 100)
        os.chmod(self.file, stat.S_IREAD)
        self.sets, self.junctions = [], []
        self.stats = G.STATS.copy()

    def tearDown(self):
        for guards in self.sets:
            guards.close()
        for junction in self.junctions:
            os.rmdir(junction)   # removes the junction itself, never its target
        for path in self.root.rglob('*'):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        shutil.rmtree(self.root)

    def acquire(self, path=None):
        guards = G.acquire(self.file if path is None else path)
        if guards is not None:
            self.sets.append(guards)
        return guards

    def counted(self, key):
        return G.STATS[key] - self.stats[key]

    def test_engaged_on_a_plain_path_and_the_token_equals_the_walk(self):   # F17 (positive side), F12
        # A sealed file's attributes changed after creation, so its change time is later than its creation time
        # (fstat's st_ctime_ns and lstat's differ in Python 3.12); the binding must still hold.
        os.chmod(self.file, stat.S_IWRITE | stat.S_IREAD)
        time.sleep(0.02)
        os.chmod(self.file, stat.S_IREAD)
        guards = self.acquire()
        self.assertIsInstance(guards, G.GuardSet)
        self.assertEqual(self.counted('guarded'), 1)
        self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))
        guards.close()
        guards.close()
        self.assertEqual(self.counted('released'), 1)
        with self.assertRaisesRegex(ContractError, 'interval handle is closed'):
            guards.token()
        os.rename(self.root / 'a', self.root / 'a2')   # released: renames are allowed again
        os.rename(self.root / 'a2', self.root / 'a')

    def test_held_set_refuses_rename_delete_and_write_open(self):   # F1, F2, F3
        guards = self.acquire()
        os.chmod(self.file, stat.S_IWRITE | stat.S_IREAD)   # so the read-only attribute is not what refuses
        refused_by_guard(self, lambda: os.rename(self.root / 'a', self.root / 'a2'))
        refused_by_guard(self, lambda: os.rename(self.dir, self.dir.with_name('b2')))
        refused_by_guard(self, lambda: os.rename(self.file, self.file.with_name('moved.sqlite')))
        refused_by_guard(self, lambda: os.unlink(self.file))
        refused_by_guard(self, lambda: write_open(self.file))
        refused_by_guard(self, lambda: write_open(self.file, 0x4))   # FILE_APPEND_DATA
        with self.assertRaises(PermissionError):
            open(self.file, 'r+b').close()
        guards.close()
        with open(self.file, 'r+b'):
            pass
        os.rename(self.root / 'a', self.root / 'a2')
        os.rename(self.root / 'a2', self.root / 'a')

    def test_directory_guards_still_allow_publication_quarantine_and_moves(self):   # F4
        guards = self.acquire()
        temporary = self.dir / 'catalog.json.tmp-0'
        temporary.write_bytes(b'{}')
        os.replace(temporary, self.dir / 'catalog.json')                       # publication into a held directory
        temporary.write_bytes(b'{"next": 1}')
        os.replace(temporary, self.dir / 'catalog.json')                       # and over an existing entry
        os.rename(self.dir / 'catalog.json', self.dir / 'catalog.json.quarantined-1')   # quarantine rename
        outside = self.root / 'moved-in'
        outside.write_bytes(b'y')
        os.rename(outside, self.dir / 'moved-in')                              # move an entry in
        os.rename(self.dir / 'moved-in', self.root / 'a' / 'moved-out')        # and out, across held directories
        os.unlink(self.root / 'a' / 'moved-out')
        (self.dir / 'sub').mkdir()
        (self.dir / 'sub').rmdir()
        self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))

    def test_unbound_or_ineligible_sets_fall_back_with_nothing_held(self):   # F5, F16, F17
        self.acquire().close()   # warm-up: ctypes and the C runtime are loaded once
        before = handle_count()
        real_lstat, real_fstat = G._lstat, G._fstat

        def swapped_ancestor(path):
            info = real_lstat(path)
            return changed(info, st_ino=info.st_ino + 1) if Path(path) == self.root / 'a' else info

        def drifted_file(fd):
            info = real_fstat(fd)
            return changed(info, st_mtime_ns=info.st_mtime_ns + 1) if stat.S_ISREG(info.st_mode) else info

        def tagged_ancestor_at_bind(handle, real=G._tag):
            return real(handle) | 0x400

        elsewhere = '\\\\?\\' + str(self.file.with_name('interval-0001.sqlite'))
        for name, double, reason in (('_lstat', swapped_ancestor, 'binding'),
                                     ('_tag', tagged_ancestor_at_bind, 'binding'),
                                     ('_fstat', drifted_file, 'token-drift'),
                                     ('_created_ns', lambda handle, real=G._created_ns: real(handle) + 1,
                                      'token-drift'),
                                     ('_final_path', lambda handle: elsewhere, 'final-path'),
                                     ('_filesystem', lambda handle: 'FAT32', 'filesystem')):
            self.stats = G.STATS.copy()
            with self.subTest(name), patch.object(G, name, double):
                self.assertIsNone(self.acquire())
                self.assertEqual(self.counted('fallback:' + reason), 1)
                self.assertEqual(handle_count(), before)
                os.rename(self.root / 'a', self.root / 'a2')   # nothing stays held
                os.rename(self.root / 'a2', self.root / 'a')
        text = str(self.file)
        for path, reason in ((text[:3] + text[3:].swapcase(), 'final-path'),   # mixed case
                             (text.lower()[:1] + text[1:3] + text[3:].upper(), 'final-path'),
                             ('\\\\?\\' + text, 'path-form'),
                             (text.replace('\\', '/'), 'path-form'),
                             (os.path.relpath(text, os.getcwd()) if text[0].lower() == os.getcwd()[0].lower()
                              else 'relative\\interval-0000.sqlite', 'path-form')):
            self.stats = G.STATS.copy()
            with self.subTest(path):
                self.assertIsNone(self.acquire(path))
                self.assertEqual(self.counted('fallback:' + reason), 1)
        self.stats = G.STATS.copy()
        with patch.object(G, 'ENABLED', False):
            self.assertIsNone(self.acquire())
        with patch.object(G, 'os', SimpleNamespace(name='posix')):
            self.assertIsNone(self.acquire())
        self.assertEqual((self.counted('fallback:disabled'), self.counted('fallback:platform')), (1, 1))
        self.assertEqual(handle_count(), before)

    def test_short_name_component_falls_back(self):   # F16
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        long_dir = self.dir / 'a-long-directory-name'
        long_dir.mkdir()
        target = long_dir / 'interval-0000.sqlite'
        target.write_bytes(b'z')
        buffer = ctypes.create_unicode_buffer(1024)
        if not kernel.GetShortPathNameW(str(target), buffer, 1024) or buffer.value == str(target):
            self.skipTest('8.3 names are not generated on this volume')
        self.assertIsNone(self.acquire(buffer.value))
        self.assertEqual(self.counted('fallback:final-path'), 1)
        self.assertIsInstance(self.acquire(target), G.GuardSet)

    def test_junction_ancestor_falls_back_and_the_walk_still_refuses(self):   # F16, F15
        import _winapi
        junction = self.root / 'j'
        _winapi.CreateJunction(str(self.root / 'a'), str(junction))
        self.junctions.append(junction)
        through = junction / 'b' / 'interval-0000.sqlite'
        self.assertIsNone(self.acquire(through))
        self.assertEqual(self.counted('fallback:acquire'), 1)
        with self.assertRaisesRegex(ContractError, 'linked/reparse paths are forbidden'):
            file_token(through, reject_sidecars=True)

    def test_sharing_violation_part_way_closes_what_was_taken(self):   # F6, F13
        self.acquire().close()
        before = handle_count()
        os.chmod(self.file, stat.S_IWRITE | stat.S_IREAD)
        with open(self.file, 'r+b'):   # a writer: the file guard (sharing READ only) cannot be taken
            self.assertIsNone(self.acquire())
            self.assertEqual(self.counted('fallback:acquire'), 1)
        self.assertEqual(handle_count(), before)
        os.rename(self.root / 'a', self.root / 'a2')   # every directory guard taken first was released
        os.rename(self.root / 'a2', self.root / 'a')
        real_hold = G._hold
        for fail_at in (1, 2, 5):
            calls = [0]

            def failing(path, guard, fail_at=fail_at, calls=calls):
                calls[0] += 1
                if calls[0] == fail_at:
                    raise PermissionError(13, 'injected')
                return real_hold(path, guard)
            with self.subTest(fail_at=fail_at), patch.object(G, '_hold', failing):
                self.assertIsNone(self.acquire())
                self.assertEqual(handle_count(), before)

    def test_no_handle_leak_over_cycles_with_failures(self):   # F13
        self.acquire().close()
        before = handle_count()
        real_hold, calls = G._hold, [0]

        def sometimes(path, guard):
            calls[0] += 1
            if calls[0] % 37 == 0:   # about one acquisition in three fails, at a varying component
                raise PermissionError(13, 'injected')
            return real_hold(path, guard)
        engaged = 0
        with patch.object(G, '_hold', sometimes):
            for _ in range(100):
                guards = G.acquire(self.file)
                if guards is not None:
                    engaged += 1
                    guards.token()
                    guards.close()
        self.assertGreater(engaged, 0)
        self.assertLess(engaged, 100)
        del guards   # a live set keeps its lock's kernel handle until it is collected
        gc.collect()
        self.assertEqual(handle_count(), before)

    def test_token_is_taken_from_the_held_file_at_each_call(self):   # F8
        guards = self.acquire()
        first = guards.token()
        os.chmod(self.file, stat.S_IWRITE | stat.S_IREAD)   # attributes only: allowed while held
        second = guards.token()
        self.assertNotEqual(first, second)
        self.assertEqual(second, file_token(self.file, reject_sidecars=True))

    def test_per_batch_refusals_keep_todays_texts(self):   # F7, F8, F9, F10, F15, F19
        guards = self.acquire()
        real_lstat, real_fstat = G._lstat, G._fstat

        def path_only(double):
            return lambda path: double(real_lstat(path)) if str(path) == str(self.file) else real_lstat(path)
        cases = (
            ('_lstat', path_only(lambda info: (_ for _ in ()).throw(FileNotFoundError(2, 'gone'))),
             'required interval file is missing'),
            ('_lstat', path_only(lambda info: changed(info, st_file_attributes=info.st_file_attributes | 0x400)),
             'linked/reparse paths are forbidden'),
            ('_lstat', path_only(lambda info: changed(info, st_nlink=2)), 'hard-linked files are forbidden'),
            ('_lstat', path_only(lambda info: changed(info, st_mtime_ns=info.st_mtime_ns + 1)),
             'immutable interval file identity changed'),
            ('_lstat', path_only(lambda info: changed(info, st_mode=stat.S_IFDIR | 0o555)),
             'required path is not a regular file'),
            ('_tag', lambda handle: 0x400, 'linked/reparse paths are forbidden'),
            # The held file's own checks, with the path's lstat unchanged (each would be shadowed otherwise).
            ('_fstat', lambda fd: changed(real_fstat(fd), st_file_attributes=real_fstat(fd).st_file_attributes | 0x400),
             'linked/reparse paths are forbidden'),
            ('_fstat', lambda fd: changed(real_fstat(fd), st_nlink=2), 'hard-linked files are forbidden'),
            ('_fstat', lambda fd: changed(real_fstat(fd), st_mode=stat.S_IFDIR | 0o555),
             'required path is not a regular file'),
            ('_fstat', lambda fd: changed(real_fstat(fd), st_mtime_ns=real_fstat(fd).st_mtime_ns + 1),
             'immutable interval file identity changed'),
            ('_created_ns', lambda handle, real=G._created_ns: real(handle) + 100,
             'immutable interval file identity changed'),
        )
        for name, double, text in cases:
            with self.subTest(text=text, name=name), patch.object(G, name, double), \
                    self.assertRaisesRegex(ContractError, '^' + text + '$'):
                guards.token()
        self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(self.file) + suffix)
            sidecar.write_bytes(b'')
            with self.subTest(suffix), self.assertRaisesRegex(ContractError, 'sealed interval has a journal/WAL'):
                guards.token()
            sidecar.unlink()
        self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))
        os.link(self.file, self.dir / 'second-name.sqlite')   # a hard link can still be made to a held file
        with self.assertRaisesRegex(ContractError, 'hard-linked files are forbidden'):
            guards.token()
        guards.close()
        os.chmod(self.dir / 'second-name.sqlite', stat.S_IWRITE | stat.S_IREAD)
        os.unlink(self.dir / 'second-name.sqlite')

    def test_drive_remapping_answers_with_todays_walk(self):   # F11 (refuter r1 finding 3a)
        guards = self.acquire()
        walked = []

        def walk(path, **kwargs):
            walked.append((str(path), kwargs))
            return file_token(path, **kwargs)

        def refusing_walk(path, **kwargs):
            raise ContractError('linked/reparse paths are forbidden')
        moved = patch.object(G, '_dos_device', lambda drive: '\\Device\\Elsewhere\x00\x00')
        with patch.object(G, 'file_token', walk):
            self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))
            self.assertEqual(walked, [])   # mapping unchanged: the held objects answer
            with moved:
                self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))
            self.assertEqual(walked, [(str(self.file), {'reject_sidecars': True})])
        with moved, patch.object(G, 'file_token', refusing_walk), \
                self.assertRaisesRegex(ContractError, '^linked/reparse paths are forbidden$'):
            guards.token()   # the walk's own refusal, before any check on the held objects

    def test_late_fallback_releases_each_handle_once(self):   # F6, F13 (refuter r1 finding 1)
        real_release = G._release
        elsewhere = '\\\\?\\' + str(self.file.with_name('interval-0001.sqlite'))

        def refused_at_bind(path, **kwargs):
            raise ContractError('sealed interval has a journal/WAL sidecar')
        for case, double in (('final-path', patch.object(G, '_final_path', lambda handle: elsewhere)),
                             ('refused at bind', patch.object(G, 'file_token', refused_at_bind))):
            released = []

            def counting(held, released=released):
                released.append(len(held))
                real_release(held)
            with self.subTest(case), patch.object(G, '_release', counting), double:
                self.assertIsNone(self.acquire())
                gc.collect()   # a dropped set's finalizer must not close the same fds again
                self.assertEqual(len(released), 1, released)

    def test_interrupt_during_acquire_releases_everything(self):   # F13 (refuter r1 finding 4)
        self.acquire().close()
        before = handle_count()
        real_hold, calls = G._hold, [0]

        def interrupted_hold(path, guard):
            calls[0] += 1
            if calls[0] == 3:
                raise KeyboardInterrupt
            return real_hold(path, guard)

        def interrupted_bind(guards):
            raise KeyboardInterrupt
        for name, target, double in (('_hold', G, interrupted_hold), ('_bind', G.GuardSet, interrupted_bind)):
            with self.subTest(name), patch.object(target, name, double), self.assertRaises(KeyboardInterrupt):
                G.acquire(self.file)
            gc.collect()
            self.assertEqual(handle_count(), before)
        os.rename(self.root / 'a', self.root / 'a2')   # nothing stays held
        os.rename(self.root / 'a2', self.root / 'a')

    def test_handle_errors_raise_and_never_fall_back(self):   # F14, F19
        guards = self.acquire()
        fallbacks = sum(v for k, v in G.STATS.items() if k.startswith('fallback:'))
        real_lstat = G._lstat
        for name, double, error in (
                ('_lstat', lambda path: (_ for _ in ()).throw(PermissionError(13, 'denied'))
                 if str(path) == str(self.file) else real_lstat(path), PermissionError),
                ('_tag', lambda handle: (_ for _ in ()).throw(OSError(6, 'invalid handle')), OSError),
                ('_fstat', lambda fd: (_ for _ in ()).throw(OSError(9, 'bad fd')), OSError),
                ('_dos_device', lambda drive: (_ for _ in ()).throw(OSError(2, 'no device')), OSError)):
            with self.subTest(name), patch.object(G, name, double), self.assertRaises(error):
                guards.token()
        self.assertEqual(sum(v for k, v in G.STATS.items() if k.startswith('fallback:')), fallbacks)
        self.assertEqual(guards.token(), file_token(self.file, reject_sidecars=True))


@WINDOWS_ONLY
class GuardedReaderTests(unittest.TestCase):
    """Sealed interval readers through the store set, as the S1 suite builds them."""
    setUp = fixture.SegmentStoreTests.setUp
    tearDown = fixture.SegmentStoreTests.tearDown
    publish = fixture.SegmentStoreTests.publish
    open = fixture.SegmentStoreTests.open
    promote = fixture.SegmentStoreTests.promote
    sealed = s1.S1SealedReadTests.sealed

    def test_sealed_reader_holds_guards_and_batches_do_not_walk(self):   # mechanism; F12
        view, source, handle = self.sealed()
        self.assertIsInstance(handle._guards, G.GuardSet)
        walks, real = [0], ISS.file_token

        def counting(*args, **kwargs):
            walks[0] += 1
            return real(*args, **kwargs)
        with patch.object(ISS, 'file_token', counting), view.verified_read():
            for at in range(0, 40 * CHUNK, 5 * CHUNK + 3):
                with view.read('payload', at, at + 7, max_owned_bytes=7) as owned:
                    self.assertEqual(owned.value, s1._expected(source, at, at + 7))
        self.assertEqual(walks[0], 0)
        guards = handle._guards
        view.close()
        self.views.remove(view)
        self.candidate.close()
        self.stores.close()
        self.assertIsNone(handle._guards)
        with self.assertRaisesRegex(ContractError, 'interval handle is closed'):
            guards.token()

    def test_hard_link_mid_batch_refuses_at_batch_end(self):   # F7
        view, _, handle = self.sealed()
        second = handle.path.with_name('second-name.sqlite')
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass
        with self.assertRaisesRegex(ContractError, 'hard-linked files are forbidden'), view.verified_read():
            os.link(handle.path, second)   # the second name goes with the temporary folder at tearDown
            view.read('payload', 0, 9, max_owned_bytes=9).close()
        self.assertEqual(len(handle._memo), 0)
        with self.assertRaisesRegex(ContractError, 'hard-linked files are forbidden'):
            view.read('payload', 0, 9, max_owned_bytes=9)

    def test_write_into_a_held_sealed_file_is_refused_at_open(self):   # F18 (guarded variant), F3
        view, _, handle = self.sealed()
        path = handle.path
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass
        before = path.read_bytes()
        original = self.stores.resolve_chunk
        refusals = []

        def rewrite_after_first_chunk(*args, **kwargs):
            result = original(*args, **kwargs)
            if not refusals:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                try:
                    write_open(path)
                except PermissionError as error:
                    refusals.append(error.winerror)
                try:
                    db = sqlite3.connect(path)
                    try:
                        db.execute('CREATE TABLE intruder (value INTEGER)')
                        db.commit()
                    finally:
                        db.close()
                except sqlite3.Error as error:
                    refusals.append(type(error).__name__)
            return result
        try:
            with patch.object(self.stores, 'resolve_chunk', side_effect=rewrite_after_first_chunk), \
                    self.assertRaisesRegex(ContractError, 'identity changed'):
                view.read('payload', 2 * CHUNK, 5 * CHUNK, max_owned_bytes=3 * CHUNK)
        finally:
            os.chmod(path, stat.S_IREAD)
        self.assertEqual(refusals, [32, 'OperationalError'])   # the write was refused at open; nothing was written
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(handle._memo), 0)

    def test_path_errors_mid_life_invalidate_the_memo_and_raise(self):   # F19, F14
        view, _, handle = self.sealed()
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass
        self.assertGreater(len(handle._memo), 0)
        invalidations, real_lstat = handle.memo_invalidations, G._lstat
        text = str(handle.path)

        def denied(path):
            if str(path) == text:
                raise PermissionError(13, 'denied')
            return real_lstat(path)
        with patch.object(G, '_lstat', denied), self.assertRaises((PermissionError, ContractError)):
            view.read('payload', 0, 9, max_owned_bytes=9)
        self.assertEqual(len(handle._memo), 0)
        self.assertGreater(handle.memo_invalidations, invalidations)
        with view.read('payload', 0, 9, max_owned_bytes=9):   # the guards stay; the next batch is clean
            pass
        self.assertIsInstance(handle._guards, G.GuardSet)

    def test_reader_open_failures_release_guards(self):   # F13, F6
        _, _, handle = self.sealed()
        path, scope = handle.path, self.scope
        gc.collect()
        ReadOnlyNative(path, scope=scope).close()
        before, released = handle_count(), G.STATS['released']
        real, calls = ReadOnlyNative._open_checked, [0]

        def sometimes(reader, require_immutable):
            calls[0] += 1
            if calls[0] % 3 == 0:
                raise ContractError('injected after acquisition')
            return real(reader, require_immutable)
        with patch.object(ReadOnlyNative, '_open_checked', sometimes):
            for _ in range(30):
                try:
                    ReadOnlyNative(path, scope=scope).close()
                except ContractError as error:
                    self.assertEqual(str(error), 'injected after acquisition')
        self.assertEqual(G.STATS['released'] - released, 30)
        gc.collect()
        self.assertEqual(handle_count(), before)
        unsealed_route = ReadOnlyNative(path, scope=scope, require_immutable=False)
        try:
            self.assertIsNone(unsealed_route._guards)   # only sealed (require_immutable) readers take guards
        finally:
            unsealed_route.close()

    def test_each_identity_check_queries_held_objects_not_the_path_walk(self):   # E3 guarded variant; S1 counts
        view, _, handle = self.sealed()
        counts = Counter()

        def counting(name, real):
            def call(*args, **kwargs):
                counts[name] += 1
                return real(*args, **kwargs)
            return call
        with ExitStack() as stack:
            for name in ('_lstat', '_fstat', '_tag', '_created_ns', '_dos_device'):
                stack.enter_context(patch.object(G, name, counting(name, getattr(G, name))))
            stack.enter_context(patch.object(Path, 'lstat', counting('Path.lstat', Path.lstat)))
            stack.enter_context(patch.object(ISS, 'file_token', counting('file_token', ISS.file_token)))
            with self.stores.resolve_manifest(0, view.ref.root_key) as body:   # unbatched: checks before and after
                self.assertTrue(body.value)
        # Per check: one by-name lstat of the file and today's three sidecar lstats, instead of the walk's
        # len(parents) + 1 + 3 by-name lstats; the ancestors are judged by one tag query on each held handle.
        self.assertEqual(dict(counts), {'_lstat': 2, '_dos_device': 2, '_tag': 2 * len(handle.path.parents),
                                        '_fstat': 2, '_created_ns': 2, 'Path.lstat': 6})

    def test_in_place_rewrite_under_a_held_reader_is_refused_and_never_reads_absent(self):   # E2 guarded variant
        view, _, handle = self.sealed()
        s1.walk_only(view)
        handle._release_memo()
        before = handle.path.read_bytes()
        original, attempts, answers = self.stores.resolve_manifest, [], []

        def rewrite(requester, locator, *, cancel=None):
            result = original(requester, locator, cancel=cancel)
            if not attempts:   # the refuter's writer, after the first manifest
                os.chmod(handle.path, stat.S_IWRITE | stat.S_IREAD)
                try:
                    db = sqlite3.connect(handle.path)
                    try:
                        db.execute('DELETE FROM snapshots WHERE id != ?', (locator.snapshot_key,))
                        db.commit()
                    finally:
                        db.close()
                except sqlite3.Error as error:
                    attempts.append(type(error).__name__)
            return result

        def has_array(name):
            try:
                view.info.array(name).close()
                answers.append(True)
            except KeyError:
                answers.append(False)
        try:
            with patch.object(self.stores, 'resolve_manifest', side_effect=rewrite), \
                    self.assertRaisesRegex(ContractError, 'identity changed'):
                has_array('payload')
        finally:
            os.chmod(handle.path, stat.S_IREAD)
        self.assertEqual(attempts, ['OperationalError'])   # the in-place rewrite never happened
        self.assertEqual(handle.path.read_bytes(), before)
        self.assertNotIn(False, answers)

    def test_b17_directory_lookups_under_a_held_reader_refuse_the_rewrite_and_answer_truly(self):   # E4 variant
        for name in ('payload', 'absent-name'):
            with self.subTest(name=name):
                view, _, _ = self.sealed()
                reader = self.stores._handles[0].value
                self.assertIsNotNone(reader._guards)
                self.assertIsNotNone(view._directory)
                before = reader.path.read_bytes()
                original, attempts, calls = self.stores.read_batch, [], [0]

                @contextmanager
                def batch(*, cancel=None, original=original, attempts=attempts, calls=calls, reader=reader):
                    with original(cancel=cancel):
                        calls[0] += 1
                        if calls[0] == 1:   # B17's writer, right after the batch's opening check
                            os.chmod(reader.path, stat.S_IWRITE | stat.S_IREAD)
                            try:
                                db = sqlite3.connect(reader.path)
                                try:
                                    db.execute('DELETE FROM snapshots WHERE id != (SELECT MIN(id) FROM snapshots)')
                                    db.commit()
                                finally:
                                    db.close()
                            except sqlite3.Error as error:
                                attempts.append(type(error).__name__)
                            finally:
                                os.chmod(reader.path, stat.S_IREAD)
                        yield

                def has_array(view=view, name=name):
                    try:
                        view.info.array(name).close()
                        return True
                    except KeyError:
                        return False
                with patch.object(self.stores, 'read_batch', batch):
                    self.assertIs(has_array(), name == 'payload')   # the true answer, never a wrong 'absent'
                self.assertEqual((calls[0], attempts), (1, ['OperationalError']))
                self.assertEqual(reader.path.read_bytes(), before)
                self.assertIsNotNone(view._directory)
                self.tearDown()
                self.setUp()


@WINDOWS_ONLY
class L3S1ContractTests(unittest.TestCase):
    """Cross-lane contract C-L3S1: what L3's carried pages rely on from the store set's batch checks."""
    setUp = ist.IntervalTests.setUp
    tearDown = ist.IntervalTests.tearDown
    root_interval = ist.IntervalTests.root_interval

    def intervals(self, count):
        for i in range(count):
            candidate, ref, _ = ist.add_interval(self.stores, [bytes([i + 1]) * 20])
            ist.finish(self.stores, candidate, ref)
        self.stores.close()
        self.stores = ist.IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        for i in range(count):
            self.stores.borrow_handle(i).close()

    def batch_outcomes(self, rounds):
        """'ok' or the refusal text of each of `rounds` empty outermost batches; records whether bodies ran."""
        outcomes = []
        for _ in range(rounds):
            ran = []
            try:
                with self.stores.read_batch():
                    ran.append(True)
                outcomes.append('ok')
            except ContractError as error:
                outcomes.append(('ran ' if ran else 'entry ') + str(error))
        return outcomes

    def test_l3s1_a_outer_batch_checks_run_and_raise_inside_read_batch(self):
        self.root_interval()
        reader = self.stores._handle(0).value
        self.assertIsInstance(reader._guards, G.GuardSet)
        calls, real = [], ReadOnlyNative._check_identity

        def counted(handle):
            calls.append(handle)
            return real(handle)
        with patch.object(ReadOnlyNative, '_check_identity', counted):
            with self.stores.read_batch():
                self.assertEqual(len(calls), 1)            # the outermost batch's entry check
                with self.stores.read_batch():
                    pass
                self.assertEqual(len(calls), 1)            # a nested batch adds no check
            self.assertEqual(len(calls), 2)                # and its exit check
        path, reached = reader.path, []
        try:
            with self.assertRaisesRegex(ContractError, 'identity changed'), self.stores.read_batch():
                with self.stores.read_batch():
                    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)   # changes inside a nested batch
                reached.append('nested exit passed')           # refused only by the outermost exit
            self.assertEqual(reached, ['nested exit passed'])
            self.assertFalse(self.stores._batched())
            self.assertEqual(self.batch_outcomes(1), ['entry immutable interval file identity changed'])
        finally:
            os.chmod(path, stat.S_IREAD)

    def test_l3s1_b_evicted_intervals_stay_covered_by_the_walk(self):
        self.intervals(9)
        self.assertNotIn(0, self.stores._handles)
        self.assertIn(0, self.stores._verified_tokens)
        self.assertTrue(all(isinstance(owner.value._guards, G.GuardSet) for owner in self.stores._handles.values()))
        self.assertEqual(self.batch_outcomes(1), ['ok'])
        evicted, resident = self.root / 'interval-0000.sqlite', self.root / 'interval-0001.sqlite'
        copy = self.root / 'replacement.bin'
        shutil.copyfile(resident, copy)
        with self.assertRaises(PermissionError):   # a resident file is never replaced (open handles, today too)
            os.replace(copy, resident)
        shutil.copyfile(evicted, copy)
        os.chmod(copy, stat.S_IREAD)
        os.chmod(evicted, stat.S_IWRITE | stat.S_IREAD)   # MoveFileEx will not replace a read-only target
        os.replace(copy, evicted)          # unmocked: identical bytes, a new file, between batches
        self.assertEqual(self.batch_outcomes(2), ['entry previously verified interval file identity changed'] * 2)
        with self.assertRaisesRegex(ContractError, 'previously verified interval file identity changed'):
            self.stores.borrow_handle(0)

    def test_l3s1_c_changed_token_is_never_repinned_on_either_route(self):
        outcomes = {}
        for route in ('guarded', 'walk'):
            with patch.object(G, 'ENABLED', route == 'guarded'):
                self.stores.close()
                (self.root / route).mkdir()
                self.stores = ist.IntervalStoreSet.create_migration(
                    str(self.root / route / 'catalog.json'), workflow_id=ist.WORKFLOW, scope=self.sc)
                self.root_interval()
                reader = self.stores._handle(0).value
                self.assertEqual(reader._guards is not None, route == 'guarded')
                token, verified = reader.token, self.stores._verified_tokens[0]
                path = reader.path
                seen = self.batch_outcomes(1)
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                seen += self.batch_outcomes(3)
                try:
                    self.stores.borrow_handle(0).close()
                    seen.append('borrowed')
                except ContractError as error:
                    seen.append('borrow ' + str(error))
                self.assertEqual((reader.token, self.stores._verified_tokens[0]), (token, verified))
                os.chmod(path, stat.S_IREAD)   # restoring the attribute reproduces the token exactly
                seen += self.batch_outcomes(1)
                outcomes[route] = seen
        self.assertEqual(outcomes['guarded'], outcomes['walk'])
        self.assertEqual(outcomes['guarded'], ['ok'] + ['entry immutable interval file identity changed'] * 3
                         + ['borrow immutable interval file identity changed', 'ok'])

    def test_l3s1_d_guarded_token_and_sidecar_check_match_the_walk(self):
        self.intervals(3)
        for interval, owner in self.stores._handles.items():
            reader = owner.value
            with self.subTest(interval=interval):
                self.assertEqual(reader._guards.token(), file_token(reader.path, reject_sidecars=True))
                self.assertEqual(reader._guards.token(), self.stores._verified_tokens[interval])
        sidecar = Path(str(self.root / 'interval-0002.sqlite') + '-wal')
        try:
            with self.assertRaisesRegex(ContractError, 'sealed interval has a journal/WAL sidecar'), \
                    self.stores.read_batch():
                sidecar.write_bytes(b'')
        finally:
            sidecar.unlink()
        self.assertEqual(self.batch_outcomes(1), ['ok'])


if __name__ == '__main__':
    unittest.main()
