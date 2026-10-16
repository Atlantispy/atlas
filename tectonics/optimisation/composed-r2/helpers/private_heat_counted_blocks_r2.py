"""What an object that already exists occupies: its own blocks, counted.

The numerical stages reserve, before they compute, an upper limit for values
that do not exist yet. Such a limit has to assume the worst the allocators can
do: a new exact number may be handed a recycled block of up to 64 limbs a part,
and every slot may be as wide as the widest. Once a stage has returned, its
result exists, and nothing has to be assumed: each object reports what was
allocated for it. This module turns that report into the bytes of the object's
own blocks. It is used to charge completed results at what they occupy.

Each figure is an upper limit for one object's own storage, on the runtime
this was derived and measured on: CPython 3.12 on 64-bit Windows with its
default allocator and no tracing, gmpy2 2.3.2 on GMP 6.3.0. ``supported()``
refuses any other; what its users do then is said below. It follows the rules
derived for decoded JSON in issuer resources r4, extended to the other types
a completed heat stage holds:

- a block up to 512 bytes comes from pymalloc, rounded up to 16 bytes, and one
  sixteenth is added for the pool's own header and tail;
- a larger block comes from the C heap: rounded up to 16 bytes, a 16-byte
  header, and one eighth added;
- a small block of a type that can be resized (str, bytes, tuple, a list's
  item array, a Decimal's coefficient) may still be the block of an earlier,
  larger size. If that size was at most 512 bytes, pymalloc keeps a block of
  B bytes for a request of n whenever 4n > 3B, so the block is the largest
  multiple of 16 below four thirds of the size, or the size's own class if
  that is larger. If it was above 512 bytes the block is on the C heap and
  stays there however far it shrinks. ``kept`` is the larger of the two;
- a Python int is counted with one 30-bit digit beyond what it reports. That
  covers an int as a sum, a product, a quotient, a shift, a negation, a copy
  or a parse of text without padding allocates it: at most one digit more
  than the value needs. It does NOT cover an int that was left in a block as
  wide as an operand while its value is small: a remainder (``%``,
  ``divmod``), a mask or other bitwise result of wide operands, a greatest
  common divisor of wide numbers, a difference of two numbers across a digit
  boundary (their widths differ, or they cancel below their leading digits),
  and a parse of zero-padded text. Such an int reports 28 bytes and can hold
  several hundred, and nothing it reports shows that, so no rule here can
  count it. This list is of the histories that were found, not a proof that
  there are no others. The integers of a result that is charged by this
  count must not be made that way;
- a list, a dict and a Decimal keep their variable part in a block of its own;
- an instance with an instance dictionary keeps its attribute values in a
  block sized when the instance was created: 29 slots for a class's first
  instance and one fewer for each later one, down to one more than the class
  has attributes. Its dictionary reports the class's present, smaller figure
  for every instance. A walk cannot tell which instances are early, so it
  adds ``record_instance`` for each instance it meets: the whole of the
  largest such block, until it has added for one class what all that class's
  early instances hold together (``RECORD_CLASS``);
- a GMP integer is a 40-byte object and one block of limbs from the C heap; a
  GMP rational is a 56-byte object and two. ``sys.getsizeof`` reports the
  object and eight bytes for every limb ALLOCATED, which includes capacity
  left from a wider intermediate and capacity inherited from a recycled object.

R2 is R1 with the findings of the independent review repaired. R1's
``supported()`` did not look at how the interpreter allocates. With allocator
debug hooks (``-X dev``, ``PYTHONDEVMODE=1``, a debug build, ``PYTHONMALLOC``
set to ``debug``, ``pymalloc_debug`` or ``malloc_debug``) every block is 24
bytes larger, and with ``PYTHONMALLOC=malloc`` every block is a C-heap block;
R1's counts were then 10 to 29 % too low. R2 refuses those modes, by the test
issuer resources r4 uses, and refuses while tracemalloc is tracing. That test
reads what the interpreter was started with, so R2 also asks the interpreter
itself, at every call, which allocators it is using now; that catches a
process that removed ``PYTHONMALLOC`` from its own environment, and hooks put
in while it runs. A tracer's own records (about 80 bytes for every live block)
are the tracer's memory and are outside every rule, this one and the
predecessors'. R2 also adds the C-heap case to ``kept``, counts a Decimal's
coefficient by ``kept``, adds the allowance for record instances, and states
which Python integers are covered.

Where ``supported()`` refuses. What owned value r2 and stage lifetime r1 hold
for an object that is not an exact number is what ``sys.getsizeof`` reports,
which is below its blocks: no rounding, no header, no padding. So a refused
mode does not fall back to that figure alone. The blocks of the four
allocator layouts CPython 3.12 has are known from the allocators themselves
(Objects/obmalloc.c), and ``refused_bytes`` counts an object by them:

- debug hooks hand the allocator beneath them a request 24 bytes larger: two
  machine words in front of the block (its size; a letter for the domain and
  seven guard bytes) and one behind it (eight guard bytes). The serial number
  that would make it 32 is not compiled in;
- ``pymalloc_debug`` (``-X dev``, ``PYTHONDEVMODE``, ``PYTHONMALLOC=debug``):
  pymalloc serves the padded request if it is at most 512 bytes, so a block
  can move to the next 16-byte class. A larger one it passes to the raw
  allocator, whose own hook pads it a second time: 48 bytes on a C-heap block;
- ``malloc``: every block is a C-heap block, with the header and rounding of
  one; ``malloc_debug``: the same, padded once;
- a tracer changes no block. While tracemalloc is tracing the interpreter
  does not name its allocators, so they are taken to be the ones it was
  started with, by its own start-up record and not by the environment;
- GMP's limb blocks and a numpy array's data come from the C library, not
  from the interpreter's allocators, and are never padded. An array's
  dimensions are a raw block and are padded once.

``padding()`` answers which of these is in use now. Where neither the
interpreter nor that record names the allocators, every object is counted at
the most that any of the four takes; that is not a limit for an allocator
this module does not know. Owned value r4 and stage lifetime r3 then charge
each object the larger of that earlier figure for it and ``refused_bytes``,
which is itself never below ``own_bytes``: nothing is held below what a
predecessor of either transfer held, whether that one counted or not. LOW
solver r5 leaves every reservation as it is. Measured as the default mode's
counts are, against pymalloc's and the C heaps' own counts in a fresh
interpreter for each population: the lowest ratio over the 73 covered
populations was 1.064 under ``pymalloc_debug``, 1.125 under ``malloc`` and
under ``malloc_debug``, and 1.010 while tracing on the default allocator, as
in the default mode. On a runtime whose object layouts are not the ones
above nothing is claimed for these figures; the earlier figure is still the
least that is charged.

Nothing here is a limit for the process: the heap's unused reserve, native
libraries, scratch during an operation, and what the interpreter and gmpy2
keep for reuse after an object is freed (free lists, the gmpy2 object cache)
are outside it. A Windows debug heap, page heap or Application Verifier is not
detected. No value is created, converted or compared. The module holds one
small table of the interpreter's cached integers and the answer for the last
exact library it was asked about.
"""
from decimal import Decimal
from fractions import Fraction
import os
import sys

try:
    from _tracemalloc import is_tracing as _tracing
except ImportError:                    # no way to ask whether blocks are traced: refuse
    def _tracing():
        return True

try:
    import ctypes
    # CPython's own name for the allocators in use; by index, so that this is the module's own function object.
    _in_use = ctypes.pythonapi['_PyMem_GetCurrentAllocatorName']
    _in_use.argtypes, _in_use.restype = (), ctypes.c_char_p
except (ImportError, AttributeError):  # it cannot be asked here: what was requested at start is all there is
    _in_use = None

SMALL = 512            # pymalloc's largest block
HEADER = 16            # the C heap's header in front of a block
SMALL_SHARE = 4        # one sixteenth on pymalloc blocks
HEAP_SHARE = 3         # one eighth on C-heap blocks
INT_SPARE = 4          # one 30-bit digit
LIST_OBJECT = 56       # sys.getsizeof([])
DICT_OBJECT = 64       # sys.getsizeof({})
SET_OBJECT = 216       # sys.getsizeof(set()), eight entries inline
DECIMAL_OBJECT = 104   # sys.getsizeof(Decimal(0)), four coefficient words inline
MPZ_OBJECT = 40        # gmpy2.mpz.__basicsize__
MPQ_OBJECT = 56        # gmpy2.mpq.__basicsize__
LIMB = 8
RECORD_CLASS = 8192    # the larger attribute blocks of one class's first instances, all together
RECORD_INSTANCE = 289  # the largest attribute block of one instance: 272 bytes and pymalloc's share
HOOKS = 24             # what allocator debug hooks add to a request: three machine words
_CACHED = tuple(range(-5, 257))


def _default_allocator():
    """No allocator debug hooks or replacement were requested for this process.

    The test of issuer resources r4. Debug hooks pad every block and
    ``PYTHONMALLOC=malloc`` moves every block to the C heap; the figures below
    have no room for either. It reads what the interpreter was started with,
    not what it is doing: a process that removes ``PYTHONMALLOC`` from its own
    environment before this module is imported passes this test.
    ``plain_allocator`` asks the interpreter as well.
    """
    if sys.flags.dev_mode or hasattr(sys, 'gettotalrefcount'):
        return False
    return (bool(sys.flags.ignore_environment)
            or os.environ.get('PYTHONMALLOC', '') in ('', 'default', 'pymalloc'))


DEFAULT_ALLOCATOR = _default_allocator()   # fixed when the interpreter starts: asked once, at import
# Lower-case because it is rebound: the issuer's loaded identity records every upper-case
# module name at import and refuses the next forward call if one has changed.
_asked = (None, False)                     # the last exact library asked about, and the answer


def plain_allocator():
    """The interpreter allocates as these figures assume: asked for at start, and in use now.

    The interpreter names its allocators ``pymalloc`` only while all three
    of its domains are the plain defaults: not with debug hooks, not with
    ``malloc`` in pymalloc's place, and not while any other hook (a tracer's)
    is installed. Where it cannot be asked, the answer is what was requested
    when it started.
    """
    return DEFAULT_ALLOCATOR and (_in_use is None or _in_use() == b'pymalloc')


def _layouts(G):
    """The object layouts and the exact library these figures were derived on."""
    return (sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12)
            and sys.platform == 'win32' and sys.maxsize == (1 << 63)-1
            and sys.getsizeof([]) == LIST_OBJECT and sys.getsizeof({}) == DICT_OBJECT
            and sys.getsizeof(set()) == SET_OBJECT == sys.getsizeof(frozenset())
            and sys.getsizeof(Decimal(0)) == DECIMAL_OBJECT and sys.getsizeof(0.) == 24
            and (G.version(), G.mp_version(), G.mp_limbsize()) == ('2.3.2', 'GMP 6.3.0', 64)
            and (G.mpz.__basicsize__, G.mpz.__itemsize__) == (MPZ_OBJECT, 0)
            and (G.mpq.__basicsize__, G.mpq.__itemsize__) == (MPQ_OBJECT, 0)
            # The report follows the allocation, not the value: a one-limb
            # difference of two 20-limb numbers keeps more than twenty limbs.
            and sys.getsizeof((G.mpz(1) << 1279)-((G.mpz(1) << 1279)-5)) >= MPZ_OBJECT+20*LIMB)


def supported(G):
    """The runtime these layouts were derived and measured on.

    False with a debug or replaced allocator, and while tracemalloc is tracing.
    Tracing and other hooks can start and stop while a process runs, so both
    are asked at every call. The layouts cannot change while a process runs,
    so they are probed once for each exact library and the answer is kept.
    """
    global _asked
    if not plain_allocator() or _tracing():
        return False
    asked = _asked
    if asked[0] is not G:
        asked = _asked = (G, bool(_layouts(G)))
    return asked[1]


def _started():
    """The allocators this interpreter was started with, in its own name for them; None if not known.

    From the interpreter's start-up record, which a process cannot change as
    it can its environment. The record holds a number of CPython 3.12's
    ``PyMemAllocatorName``: 0 nothing asked for, 1 ``default``, 2 ``debug``,
    3 ``malloc``, 4 ``malloc_debug``, 5 ``pymalloc``, 6 ``pymalloc_debug``. On
    a release build with pymalloc, which the Windows build is, the first two
    are pymalloc and ``debug`` is pymalloc with debug hooks.
    """
    if sys.version_info[:2] != (3, 12) or hasattr(sys, 'gettotalrefcount'):
        return None
    try:
        record = ctypes.pythonapi['_Py_GetConfigsAsDict']
        record.argtypes, record.restype = (), ctypes.py_object
        asked = record()['pre_config']['allocator']
    except (NameError, AttributeError, KeyError, TypeError):    # no ctypes (its import failed above), or no record
        return None
    names = (b'pymalloc', b'pymalloc', b'pymalloc_debug', b'malloc', b'malloc_debug', b'pymalloc', b'pymalloc_debug')
    return names[asked] if type(asked) is int and 0 <= asked < len(names) else None


def padding():
    """``(pad, heap)``: what the allocators in use now do with a request, for ``refused_bytes``; or None.

    ``pad`` is what debug hooks add to a request, ``HOOKS`` or nothing.
    ``heap`` is true if every block is a C-heap block and false if pymalloc
    serves requests up to 512 bytes. The interpreter is asked for its
    allocators' name, as ``plain_allocator`` asks it. It gives none while a
    hook that is not its own stands in front of them. A tracer is such a hook
    and changes no block, so while tracemalloc is tracing they are taken to
    be the allocators the interpreter was started with. With no name and no
    tracer, or no start-up record, the answer is None: the refused figures
    then take the most that any of the four layouts does, which is no limit
    for an allocator that is none of them.
    """
    name = _in_use() if _in_use is not None else None
    if name is None and _tracing():
        name = _started()
    if name == b'pymalloc':
        return 0, False
    if name == b'pymalloc_debug':
        return HOOKS, False
    if name == b'malloc':
        return 0, True
    if name == b'malloc_debug':
        return HOOKS, True
    return None


_named = ((0, False), (HOOKS, False), (0, True), (HOOKS, True))    # every answer of ``padding`` but None


def _small(size):
    size = (size+15) & ~15
    return size+(size >> SMALL_SHARE)


def _heap(size):
    size = max(16, (size+15) & ~15)+HEADER
    return size+(size >> HEAP_SHARE)


def block(size):
    """One allocation of ``size`` requested bytes, with its allocator's share."""
    return _small(size) if size <= SMALL else _heap(size)


def kept(size):
    """One allocation that may have been shrunk in place from a larger size.

    At 512 bytes or less it is either a pymalloc block of up to four thirds of
    the size or, if it was ever above 512 bytes, still a C-heap block.
    """
    if size > SMALL:
        return _heap(size)
    return max(_small(max(size, min(SMALL, ((4*size-1)//3) & ~15))), _heap(size))


def record_instance(kind, given):
    """The allowance for one instance of a record class that a walk meets.

    ``given`` is the walk's own dict of what it has added for each class so
    far. Returns ``RECORD_INSTANCE`` until the walk has added ``RECORD_CLASS``
    for ``kind``, then what is left of that, then 0.

    A walker counts every instance's attribute values at the size its
    dictionary reports, which is the class's present figure. An early
    instance's block is larger: at most 30 slots, a 32-byte prefix and 240
    bytes, 289 with pymalloc's share (a first instance's 29 slots take the
    same block). ``RECORD_INSTANCE`` is the whole of that block, so it is more
    than any one instance holds beyond what is counted. All the early
    instances of one class together hold at most 406 value slots beyond it (a
    class with no attributes; 325 with three): with their prefixes, rounding
    and pymalloc's share just under 3.5 KB by arithmetic, and 2.9 KB
    measured. ``RECORD_CLASS`` is more than twice that, so a walk that has
    added it for a class has covered every instance of the class it can meet.
    An instance without an instance dictionary (slots) has no such block and
    needs none of this.
    """
    added = given.get(kind, 0)
    amount = min(RECORD_INSTANCE, RECORD_CLASS-added)
    given[kind] = added+amount
    return amount


def record_class(kind, seen):
    """The allowance for the early instances of one record class, all at once.

    ``seen`` is the walk's own set of the record classes it has met. Returns
    ``RECORD_CLASS`` the first time ``kind`` is met and adds it to ``seen``;
    returns 0 afterwards. It is ``record_instance`` at its limit, for a walk
    that keeps no figure for each class: sound, and 8,192 bytes on every walk
    that meets the class, however few of its instances are there. The walkers
    of this generation use ``record_instance``.
    """
    if kind in seen:
        return 0
    seen.add(kind)
    return RECORD_CLASS


def array_bytes(reported, data):
    """A one-dimensional numpy array that owns its data: the object and the data block.

    ``reported`` is ``sys.getsizeof`` of the array, which contains the data;
    ``data`` is its ``nbytes``. The data comes from the C heap.
    """
    return _small(max(16, reported-data))+_heap(data)


def own_bytes(value, G):
    """Upper limit for the blocks of this one object, not of what it refers to.

    Supported: None, bool, int, float, str, bytes, tuple, list, dict, set,
    frozenset, Decimal, Fraction, GMP mpz and mpq. A Fraction's two integers
    are objects of their own and are not included. Returns 0 for the
    interpreter's shared singletons. For an int the limit holds for the
    histories the module's note lists and for no other.
    """
    kind = type(value)
    if value is None or kind is bool:
        return 0
    size = sys.getsizeof(value)
    if kind is int:
        if -5 <= value <= 256 and value is _CACHED[value+5]:
            return 0
        return block(size+INT_SPARE)
    if kind is float:
        return _small(size)
    if kind is str:
        if not value:
            return 0
        # A non-ASCII string may carry its UTF-8 form in a second block.
        return kept(size)+(0 if value.isascii() else _small(HEADER))
    if kind is bytes:
        return kept(size) if value else 0
    if kind is tuple:
        return kept(size) if value else 0
    if kind is list:
        return _small(LIST_OBJECT)+(kept(size-LIST_OBJECT) if size > LIST_OBJECT else 0)
    if kind is dict:
        # The key table, and for an instance dictionary the value array, are
        # blocks of their own: one block for the sum and one header more.
        return _small(DICT_OBJECT)+(block(size-DICT_OBJECT)+_small(HEADER) if size > DICT_OBJECT else 0)
    if kind in (set, frozenset):
        # Eight entries are inline; a larger table is a block of its own.
        return _small(SET_OBJECT)+(block(size-SET_OBJECT) if size > SET_OBJECT else 0)
    if kind is Decimal:
        # The coefficient is resized in place as a result is rounded.
        return _small(DECIMAL_OBJECT)+(kept(size-DECIMAL_OBJECT) if size > DECIMAL_OBJECT else 0)
    if kind is Fraction:
        return _small(size)
    if kind is G.mpz:
        return _small(MPZ_OBJECT)+(_heap(size-MPZ_OBJECT) if size > MPZ_OBJECT else 0)
    if kind is G.mpq:
        # Two limb blocks whose sizes are reported together. Each is a whole
        # number of limbs, so rounding to 16 adds at most 8 bytes to each.
        if size <= MPQ_OBJECT:
            return _small(MPQ_OBJECT)
        limbs = size-MPQ_OBJECT+2*(LIMB+HEADER)
        return _small(MPQ_OBJECT)+limbs+(limbs >> HEAP_SHARE)
    raise TypeError('Unsupported counted object '+kind.__name__)


def refused_block(size, padding):
    """``block`` where ``supported()`` refuses: one allocation of ``size`` requested bytes under ``padding``.

    ``padding`` is an answer of ``padding()``. For None the figure is the
    most that any of the four layouts gives, here and in ``refused_array``
    and ``refused_bytes``.
    """
    if padding is None:
        return max(refused_block(size, each) for each in _named)
    pad, heap = padding
    size += pad
    if heap:
        return _heap(size)
    # Above 512 bytes pymalloc passes the padded request to the raw allocator, whose hook pads it again.
    return _small(size) if size <= SMALL else _heap(size+pad)


def _refused_kept(size, padding):
    """``kept`` under ``padding``: an allocation that may have been shrunk in place from a larger size.

    The padded request is what pymalloc compares with the block it has, and
    what stays on the C heap if it was ever above 512 bytes. Where every
    block is a C-heap block none is kept at four thirds of its size; the
    figure is still not below ``kept``, because a predecessor counted by that
    in every mode and nothing is to be held below what it held.
    """
    pad, heap = padding
    if heap:
        return max(_heap(size+pad), kept(size))
    size += pad
    if size > SMALL:
        return _heap(size+pad)
    return max(_small(max(size, min(SMALL, ((4*size-1)//3) & ~15))), _heap(size+pad))


def _further(padding):
    """A second block of one object, where the object is counted as ONE block of the two sizes together.

    Two blocks take more than one of their sum by the second one's own
    padding, rounding and header. The most that can be is on the C heap:
    a header and a 16-byte step, and the padding of a C-heap block.
    """
    pad, heap = padding
    return _heap(HEADER+(pad if heap else 2*pad))


def refused_array(reported, data, padding):
    """``array_bytes`` where ``supported()`` refuses: the object, its dimensions and its data.

    The object is padded as any other block. The dimensions are a raw block
    of their own and are padded once. The data comes from the C library, not
    from the interpreter's allocators, and is never padded.
    """
    if padding is None:
        return max(refused_array(reported, data, each) for each in _named)
    pad, heap = padding
    if not pad and not heap:
        return array_bytes(reported, data)
    return refused_block(max(16, reported-data), padding)+_heap(HEADER+pad)+_heap(data)


def refused_bytes(value, G, padding):
    """``own_bytes`` where ``supported()`` refuses: this one object's blocks as the allocators in use make them.

    ``padding`` is what ``padding()`` answered for the walk. Where nothing is
    added to a block the figure is ``own_bytes`` itself. Otherwise every block
    the interpreter's allocators hand out is counted with that padding. GMP's
    limb blocks are not theirs and are counted as they are. A non-ASCII
    string may carry its UTF-8 form in a second block, and how what it
    reports divides between the two is not known: each is counted at the
    whole. The types, the shared singletons and the integers covered are
    those of ``own_bytes``, and the figure is never below ``own_bytes``.
    """
    if padding is None:
        return max(refused_bytes(value, G, each) for each in _named)
    pad, heap = padding
    if not pad and not heap:
        return own_bytes(value, G)
    kind = type(value)
    if value is None or kind is bool:
        return 0
    size = sys.getsizeof(value)
    if kind is int:
        if -5 <= value <= 256 and value is _CACHED[value+5]:
            return 0
        return refused_block(size+INT_SPARE, padding)
    if kind is float or kind is Fraction:
        return refused_block(size, padding)
    if kind is str:
        if not value:
            return 0
        return _refused_kept(size, padding)+(0 if value.isascii() else refused_block(size, padding))
    if kind is bytes or kind is tuple:
        return _refused_kept(size, padding) if value else 0
    if kind is list:
        return refused_block(LIST_OBJECT, padding)+(
            _refused_kept(size-LIST_OBJECT, padding) if size > LIST_OBJECT else 0)
    if kind is dict:
        return refused_block(DICT_OBJECT, padding)+(
            refused_block(size-DICT_OBJECT, padding)+_further(padding) if size > DICT_OBJECT else 0)
    if kind in (set, frozenset):
        return refused_block(SET_OBJECT, padding)+(refused_block(size-SET_OBJECT, padding) if size > SET_OBJECT else 0)
    if kind is Decimal:
        return refused_block(DECIMAL_OBJECT, padding)+(
            _refused_kept(size-DECIMAL_OBJECT, padding) if size > DECIMAL_OBJECT else 0)
    if kind is G.mpz:
        return refused_block(MPZ_OBJECT, padding)+(_heap(size-MPZ_OBJECT) if size > MPZ_OBJECT else 0)
    if kind is G.mpq:
        if size <= MPQ_OBJECT:
            return refused_block(MPQ_OBJECT, padding)
        limbs = size-MPQ_OBJECT+2*(LIMB+HEADER)
        return refused_block(MPQ_OBJECT, padding)+limbs+(limbs >> HEAP_SHARE)
    raise TypeError('Unsupported counted object '+kind.__name__)
