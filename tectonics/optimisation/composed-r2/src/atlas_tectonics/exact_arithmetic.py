"""Selected exact-rational backend for complete geometry operations.

Every Atlas geometric predicate, cut and volume is an exact rational number.
Python int and fractions.Fraction remain the reference representation and the
only one that is stored, hashed, encoded or passed through a public interface.
With the optional gmpy2 package, a complete clipping/volume operation may hold
its intermediate rationals as GMP values and convert only what leaves it. Both
routes evaluate the same field operations on the same canonical values (lowest
terms, positive denominator): results are equal, not merely close. This is not
a floating-point, rounded or reduced-precision path, and no tolerance exists.

The backend is chosen once, when this module is first imported, and is then a
constant of the process. ATLAS_EXACT_ARITHMETIC selects it:

  auto    (default) gmpy2 when an exactly tested build imports from a wheel
          that carries its own GMP library and passes the canary below;
          otherwise Python, with the reason kept by selection();
  python  never import gmpy2;
  gmpy2   require it: an unavailable, untested, failing or unsealed library is
          an error, never a silent fallback or a bypass of native-file binding.

A calculation never changes backend. A native failure is not retried on the
Python route; the caller sees the original error. A child process inherits the
variable and must reproduce the parent's whole runtime record, which carries
this backend, its versions and its bound native files (reuse._runtime_record),
so a worker cannot run a different backend from its parent unnoticed, and
cached results are keyed apart by backend although their values are identical.
The native files are bound by path, as every other extension of that record
is. On Windows the loader is also asked which file it mapped under each bound
library name; a different file leaves the installation unsealed. Elsewhere
that is not asked.

Memory. GMP obtains limb storage from the C allocator, outside Python's object
accounting, and this build ends the process when the operating system refuses
it: unlike MemoryError that failure cannot be caught and unwound. Each step of
a kernel therefore takes its arithmetic lease on the caller's WorkBudget BEFORE
building that step's native intermediates, with the reference route's formula;
retained native coordinates are charged the reference amount plus a surcharge
for the blocks gmpy2 can hold them on; and an operation's native values die
with it (on a failure, when its error is released). The measurements and the
exceptions are in docs/EXACT_ARITHMETIC_BACKEND.md. As for every other ledger
in this package, admission is accounting, not an operating-system limit.
Process supervision must treat an abrupt exit as a failed calculation.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from fractions import Fraction
import os
from pathlib import Path
import re
import sys

from ._validation import TectonicsError


ENVIRONMENT = 'ATLAS_EXACT_ARITHMETIC'
CHOICES = ('auto', 'python', 'gmpy2')
# (gmpy2, GMP) versions whose complete-operation parity was actually measured.
# Another pair is not assumed equivalent: auto declines it, an explicit request
# fails. Measured on Windows x86-64 CPython 3.12 only; the platform is already
# part of the runtime record.
TESTED_GMPY2 = (('2.3.2', 'GMP 6.3.0'),)


def _canary(native):
    """Cheap exactness contract of the loaded library; not a test suite.

    The kernels rely on canonical rationals, exact integer division, bit
    lengths that equal Python's and variadic lcm. A build that differs must
    not be used at all.
    """
    mpq, mpz = native.mpq, native.mpz
    big = (1 << 2000)+12345
    value = mpq(-6*big, 4*big)
    checks = (
        native.numer(value) == -3 and native.denom(value) == 2,
        native.numer(mpq(3, -9)) == -1 and native.denom(mpq(3, -9)) == 3,
        value == Fraction(-3, 2) and mpq(1, 3)+mpq(1, 6) == Fraction(1, 2),
        mpq(Fraction(-7, big)) == Fraction(-7, big),
        mpz(big).bit_length() == big.bit_length() and mpz(0).bit_length() == 0,
        mpz(-big).bit_length() == big.bit_length(),
        native.lcm(mpz(4), mpz(6), mpz(10)) == 60 and native.lcm(mpz(1), mpz(1), mpz(1)) == 1,
        (mpz(7*big)//mpz(7)) == big and int(mpz(-big)) == -big,
        not mpq(0) and bool(mpq(1, big)) and mpq(1, big) > 0 > mpq(-1, big),
        mpq(1, 3) < mpq(1, 2) and (mpq(1, 2), mpq(-1)) > (mpq(1, 2), mpq(-2)),
        mpq(5, 3)/6 == Fraction(5, 18) and -mpq(5, 3)*mpq(3, 5) == -1,
    )
    if not all(checks):
        raise TectonicsError('gmpy2 exact-arithmetic canary failed: check %d' % checks.index(False))
    try:
        mpq(1, 0)
    except ZeroDivisionError:
        return
    raise TectonicsError('gmpy2 exact-arithmetic canary failed: zero denominator accepted')


_VERSIONED_SO = re.compile(r'\.so(\.[0-9]+)+\Z')


def _shared_library(path):
    name = path.name.lower()
    return name.endswith(('.dll', '.dylib', '.so')) or _VERSIONED_SO.search(name) is not None


def _mapped_file(name):
    """The file the Windows loader has mapped under this library name.

    '' when no module of that name is mapped; None where the loader is not
    asked (not Windows). Windows resolves a dependency by base name against
    the modules already mapped, so a library of the same name loaded earlier,
    from anywhere, is the one the extension executes.
    """
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    kernel.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    kernel.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    handle = kernel.GetModuleHandleW(name)
    if not handle:
        return ''
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise TectonicsError('the loader did not name the file mapped as '+name)
    return buffer.value


def _native_files(native):
    """The extension and the shared libraries bundled with it, each a regular unlinked file.

    reuse hashes every one into the runtime record and refuses a link, so a
    library whose files cannot be bound is decided here as unavailable. An
    official wheel keeps GMP beside the extension in gmpy2.libs; only shared
    libraries there are bound (import libraries and stray files are not
    loaded). The set is sealed only if a GMP library is among them and, where
    the loader can be asked, the GMP library is mapped from that bound file
    and no other bound library is mapped from a different one. Anything else
    is unsealed and refused by selection in every mode. The files are
    bound by path; apart from that question to the Windows loader nothing
    proves the bound bytes are the executing ones.
    """
    import gmpy2.gmpy2 as extension
    files = {'gmpy2_extension': Path(extension.__file__)}
    bundled = Path(native.__file__).parent.parent/'gmpy2.libs'
    if bundled.is_dir():
        for path in sorted(bundled.glob('*')):
            if _shared_library(path):
                files['gmpy2:'+path.name] = path
    for path in files.values():
        if path.is_symlink() or not path.is_file():
            raise TectonicsError('gmpy2 native file is linked or not a regular file: '+path.name)
    sealed = False
    displaced = False
    for label, path in files.items():
        if label == 'gmpy2_extension':
            continue
        mapped = _mapped_file(path.name)
        if mapped is None:
            here = True
        elif not mapped:
            here = False
        else:
            try:
                here = os.path.samefile(mapped, path)
            except OSError:
                # A mapped file that can no longer be examined is not shown to be this one.
                here = False
        if mapped and not here:
            displaced = True
        if 'gmp' in path.name.lower() and here:
            sealed = True
    return {label: str(path) for label, path in files.items()}, sealed and not displaced


def _select():
    requested = os.environ.get(ENVIRONMENT, 'auto')
    if requested not in CHOICES:
        raise TectonicsError(ENVIRONMENT+' must be one of auto, python or gmpy2')
    if requested == 'python':
        return requested, 'python', None, {}, False, 'Python exact arithmetic requested'
    try:
        import gmpy2
        pair = (gmpy2.version(), gmpy2.mp_version())
        if pair not in TESTED_GMPY2:
            raise TectonicsError('gmpy2 %s with %s has no measured parity; tested: %s' % (
                *pair, ', '.join('%s with %s' % row for row in TESTED_GMPY2)))
        _canary(gmpy2)
        files, sealed = _native_files(gmpy2)
        if not sealed:
            raise TectonicsError('gmpy2 has no bundled GMP library that this process maps and can bind; '
                                 'an explicit request cannot bypass native-file binding')
    except (MemoryError, RecursionError):
        # These describe this process at this moment, not the library. The
        # route, and with it every execution identity, is not decided by them.
        raise
    except Exception as exc:
        # Whatever stops the library being used (absent, a module of that name
        # that is not the library, a failed load, an untested or failing build,
        # files that cannot be bound) is one outcome: it is not used.
        try:
            detail = type(exc).__name__+': '+str(exc)
        except Exception:
            detail = type(exc).__name__
        if requested == 'gmpy2':
            raise TectonicsError('requested gmpy2 exact arithmetic is unavailable: '+detail) from exc
        return requested, 'python', None, {}, False, 'gmpy2 not used: '+detail
    return requested, 'gmpy2', gmpy2, files, sealed, 'gmpy2 %s (%s)' % pair


# Only the executing route is an upper-case (identity-bound) constant. How it
# was requested, and why a fallback happened, are provenance held privately:
# two processes on the same route must not receive different identities.
_requested, BACKEND, _library, _files, _sealed, _reason = _select()


def selection():
    """Requested mode, executing backend and the recorded reason."""
    return {'requested': _requested, 'backend': BACKEND, 'reason': _reason}


def library():
    """The loaded gmpy2 module, or None on the Python route."""
    return _library


def runtime():
    """Versions and native file paths of the SELECTED backend for runtime identity.

    Paths, not digests: reuse hashes them under its own process-lifetime rule.
    """
    if _library is None:
        return {'versions': {'exact_arithmetic': 'python-fraction'}, 'binaries': {}}
    return {'versions': {'exact_arithmetic': 'gmpy2', 'gmpy2': _library.version(),
                         'gmp': _library.mp_version(),
                         'gmp_binary_scope': ('wheel-libraries' if _sealed
                                              else 'extension-only; external GMP unsealed')},
            'binaries': dict(_files)}
