"""Private r3 FINISH codec sizing; no encoder or numerical behaviour changes.

The digit bound is mathematical. Buffer capacity follows CPython 3.12.14's
append-only bytearray rule; the remaining live-object inventory is an explicit
accounting policy, NOT an allocator, native scratch or process-RSS guarantee.
No records or integers are serialised to obtain these prospective sizes.

The caller supplies the COMPLETE final-record character bound, including all
keys, literals, indices, floats, identifiers, source bindings and result_id.
JSONEncoder's default ensure_ascii=True makes those characters ASCII bytes.
Text lengths stay text lengths; they are never treated as numeric bit widths.

In r3 _issue, sha256(_encoded(record)).hexdigest() finishes before the second
_encoded call starts. The hash object does not retain its input bytes. Thus at
most ONE growing bytearray and ONE immutable whole-record copy coexist, not
two encoding passes' buffers. Rational defaults create two component strings;
current/previous quoted chunks are bounded by the largest scalar/text token,
not by the complete record. Keep work+retained funding until its owner closes,
including escaped frames on failure; this module neither releases nor admits.

Bytearray source (append-only offset is zero):
https://github.com/python/cpython/blob/v3.12.14/Objects/bytearrayobject.c
PyByteArray_Resize allocates size+1 or size+(size>>3)+(3 or 6). Its allocation
therefore never exceeds N+(N>>3)+6 for a monotone stream of final length <=N.
Realloc's hidden old/new blocks and allocator arenas are not Python live-object
capacity. The supervisor/native workspace policy must cover those separately.
"""
from dataclasses import dataclass
import struct
import sys


DIGIT_RATIO_NUMERATOR = 30103
DIGIT_RATIO_DENOMINATOR = 100000
RESULT_ID_FIELD_CHARS = 79  # ,"result_id":" followed by 64 hex digits and ".


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name+' must be a nonnegative integer')
    if value > sys.maxsize:
        raise OverflowError(name+' exceeds addressable accounting')
    return value


def decimal_digit_bound(bits):
    """Unsigned decimal digits for any integer with absolute bit_length<=bits.

    The exact integer inequality 2**100000 < 10**30103 proves
    log10(2) < 30103/100000, without floating-point logarithms. For b>0,
    |n| < 2**b < 10**(b*30103/100000) <= 10**ceil(b*30103/100000),
    so at most that many digits suffice. Zero needs one digit. The focused
    test verifies the constant inequality once, exactly; no large proof
    operands are constructed by each sizing call.
    """
    _count(bits, 'bits')
    return max(1, (bits*DIGIT_RATIO_NUMERATOR+DIGIT_RATIO_DENOMINATOR-1)
               // DIGIT_RATIO_DENOMINATOR)


def rational_json_chars(numerator_bits, denominator_bits):
    """Bound canonical [\"signed decimal numerator\",\"positive denominator\"]."""
    if _count(denominator_bits, 'denominator_bits') == 0:
        raise ValueError('A positive denominator requires at least one bit')
    # Two brackets, four quotes, one comma, at most one numerator minus sign.
    return _count(decimal_digit_bound(numerator_bits)
                  + decimal_digit_bound(denominator_bits)+8, 'rational JSON chars')


def json_text_chars(character_count):
    """Quoted ensure_ascii string bound, including astral surrogate pairs."""
    return _count(12*_count(character_count, 'text characters')+2, 'JSON text chars')


def bytearray_capacity_bound(final_chars):
    """Bound append-only CPython 3.12.14 allocation, including trailing NUL."""
    _count(final_chars, 'final_chars')
    return _count(final_chars+(final_chars >> 3)+6, 'bytearray capacity')


@dataclass(frozen=True, slots=True)
class CodecInventory:
    json_chars: int
    largest_chunk_chars: int
    bytearray_bytes: int
    immutable_bytes: int
    component_string_bytes: int
    chunk_buffer_bytes: int
    decimal_text_buffer_bytes: int
    whole_record_buffers: int = 2
    simultaneous_encoder_calls: int = 1
    allocator_or_rss_bound: bool = False

    @property
    def work_bytes(self):
        return _count(self.bytearray_bytes+self.component_string_bytes
                      +self.chunk_buffer_bytes+self.decimal_text_buffer_bytes,
                      'codec work bytes')

    @property
    def retained_bytes(self):
        return self.immutable_bytes

    @property
    def total_bytes(self):
        return _count(self.work_bytes+self.retained_bytes, 'codec total bytes')


def codec_inventory(total_chars, largest_component_chars, largest_text_chars=0):
    """Size the two SEQUENTIAL r3 encodings using their larger final record.

    largest_component_chars includes a possible minus sign. largest_text_chars
    is the largest RAW Unicode string length among keys, literals, identifiers,
    source paths/hashes and result_id; json_text_chars funds escaping. Include
    any non-rational integer's signed digits in largest_component_chars too.
    The minimum chunk size covers finite binary64 repr, literals and punctuation.

    Two rational strings can coexist. Charge three ASCII chunk strings for the
    previous yield, current escaped token and prefixed token, plus one UTF-8
    bytes chunk. This deliberately sums stage maxima even where their lifetimes
    do not overlap. One extra component-sized native decimal text buffer is
    charged; mpz getter/copy limbs and conversion scratch still require the
    caller's separate scalar-native allowance. Containers, sorted key arrays,
    encoder frames/markers and input/result graphs require its container policy.
    """
    if (sys.implementation.name != 'cpython'
            or sys.version_info[:3] != (3, 12, 14) or struct.calcsize('P') != 8):
        raise RuntimeError('Codec policy requires reviewed 64-bit CPython 3.12.14')
    _count(total_chars, 'total_chars')
    _count(largest_component_chars, 'largest_component_chars')
    _count(largest_text_chars, 'largest_text_chars')
    # A list's comma/open bracket adds one character to the quoted token.
    chunk = _count(max(32, largest_component_chars+3,
                       json_text_chars(largest_text_chars)+1), 'largest chunk')
    ascii_header, bytes_header = sys.getsizeof(''), sys.getsizeof(b'')
    result = CodecInventory(
        json_chars=total_chars,
        largest_chunk_chars=chunk,
        bytearray_bytes=sys.getsizeof(bytearray())+bytearray_capacity_bound(total_chars),
        immutable_bytes=bytes_header+total_chars,
        component_string_bytes=2*(ascii_header+largest_component_chars),
        chunk_buffer_bytes=3*(ascii_header+chunk)+bytes_header+chunk,
        # NUL plus one decimal size-estimation slack character; other native
        # conversion allocations belong to the caller's scalar policy.
        decimal_text_buffer_bytes=largest_component_chars+2,
    )
    result.total_bytes
    return result
