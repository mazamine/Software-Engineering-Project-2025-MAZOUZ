
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple, Protocol
import math

WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1

def ceil_div(a: int, b: int) -> int:
    return -(-a // b)

def ceil_log2(x: int) -> int:
    if x <= 1: 
        return 0
    return (x-1).bit_length()

class ZigZag:
    """Signed<->Unsigned zigzag transform (like Protocol Buffers)."""
    @staticmethod
    def encode(n: int) -> int:
        return (n << 1) ^ (n >> 31)

    @staticmethod
    def decode(u: int) -> int:
        return (u >> 1) ^ -(u & 1)

class BitPacker(Protocol):
    def compress(self, arr: List[int]) -> None: ...
    def decompress(self, out: List[int]) -> None: ...
    def get(self, i: int) -> int: ...
    def compressed_words(self) -> List[int]: ...
    def bits_per_value(self) -> int: ...
    def size(self) -> int: ...

@dataclass
class _BaseState:
    k: int = 0
    n: int = 0
    words: List[int] = None
    signed: bool = False
    use_zigzag: bool = False

    def _prep_values(self, arr: List[int]) -> Tuple[List[int], int]:
        """Return (unsigned_values, k) where k is minimal bits to represent max value."""
        if self.use_zigzag:
            u = [ZigZag.encode(x) for x in arr]
        elif self.signed:
            # two's complement width
            if not arr: 
                return [], 0
            max_abs = max(abs(x) for x in arr)
            # +1 for sign bit when using two's complement
            k = max(1, max_abs.bit_length() + 1)
            # map negatives to two's complement in k bits
            mod = 1 << k
            mask = mod - 1
            u = [(x + mod) & mask if x < 0 else x for x in arr]
            return u, k
        else:
            u = arr[:]
        k = 0 if not u else max(1, max(x for x in u).bit_length())
        return u, k

    def _restore_value(self, u: int) -> int:
        if self.use_zigzag:
            return ZigZag.decode(u)
        if self.signed:
            # interpret as two's complement with current k bits
            sign_bit = 1 << (self.k - 1)
            if u & sign_bit:
                u = u - (1 << self.k)
        return u

class CrossBoundaryPacker(_BaseState):
    """Bit packing that allows values to cross 32-bit word boundaries."""
    def __init__(self, signed: bool=False, use_zigzag: bool=False):
        super().__init__(signed=signed, use_zigzag=use_zigzag)
        self.k = 0
        self.n = 0
        self.words = []

    def compress(self, arr: List[int]) -> None:
        vals, k_auto = self._prep_values(arr)
        self.k = k_auto if self.k == 0 else self.k
        k = max(1, self.k)
        self.n = len(vals)
        if self.n == 0:
            self.words = []
            return

        bit_len = self.n * k
        num_words = ceil_div(bit_len, WORD_BITS)
        words = [0] * num_words

        bitpos = 0
        for v in vals:
            v &= (1 << k) - 1
            w_idx = bitpos // WORD_BITS
            offset = bitpos % WORD_BITS
            if offset + k <= WORD_BITS:
                words[w_idx] |= v << offset
            else:
                lo = WORD_BITS - offset
                hi = k - lo
                words[w_idx] |= (v & ((1 << lo) - 1)) << offset
                words[w_idx + 1] |= v >> lo
            bitpos += k

        self.words = [w & WORD_MASK for w in words]

    def _get_unsigned(self, i: int) -> int:
        if i < 0 or i >= self.n:
            raise IndexError("index out of range")
        k = self.k
        bitpos = i * k
        w_idx = bitpos // WORD_BITS
        offset = bitpos % WORD_BITS
        if offset + k <= WORD_BITS:
            chunk = (self.words[w_idx] >> offset) & ((1 << k) - 1)
            return chunk
        else:
            lo = WORD_BITS - offset
            hi = k - lo
            low_part = (self.words[w_idx] >> offset) & ((1 << lo) - 1)
            high_part = self.words[w_idx + 1] & ((1 << hi) - 1)
            return (high_part << lo) | low_part

    def get(self, i: int) -> int:
        return self._restore_value(self._get_unsigned(i))

    def decompress(self, out: List[int]) -> None:
        if len(out) < self.n:
            raise ValueError("output buffer too small")
        for i in range(self.n):
            out[i] = self.get(i)

    def compressed_words(self) -> List[int]:
        return self.words[:]

    def bits_per_value(self) -> int:
        return self.k

    def size(self) -> int:
        return self.n

class NoCrossPacker(_BaseState):
    """Bit packing that forbids values from crossing 32-bit word boundaries."""
    def __init__(self, signed: bool=False, use_zigzag: bool=False):
        super().__init__(signed=signed, use_zigzag=use_zigzag)
        self.k = 0
        self.n = 0
        self.words = []

    def compress(self, arr: List[int]) -> None:
        vals, k_auto = self._prep_values(arr)
        self.k = k_auto if self.k == 0 else self.k
        k = max(1, self.k)
        self.n = len(vals)
        if self.n == 0:
            self.words = []
            return

        slots_per_word = WORD_BITS // k
        num_words = ceil_div(self.n, slots_per_word)
        words = [0] * num_words
        for i, v in enumerate(vals):
            v &= (1 << k) - 1
            w_idx = i // slots_per_word
            slot = i % slots_per_word
            offset = slot * k
            words[w_idx] |= v << offset

        self.words = [w & WORD_MASK for w in words]

    def _get_unsigned(self, i: int) -> int:
        if i < 0 or i >= self.n:
            raise IndexError("index out of range")
        k = self.k
        slots_per_word = WORD_BITS // k
        w_idx = i // slots_per_word
        slot = i % slots_per_word
        offset = slot * k
        return (self.words[w_idx] >> offset) & ((1 << k) - 1)

    def get(self, i: int) -> int:
        return self._restore_value(self._get_unsigned(i))

    def decompress(self, out: List[int]) -> None:
        if len(out) < self.n:
            raise ValueError("output buffer too small")
        for i in range(self.n):
            out[i] = self.get(i)

    def compressed_words(self) -> List[int]:
        return self.words[:]

    def bits_per_value(self) -> int:
        return self.k

    def size(self) -> int:
        return self.n

class OverflowBitPacker:
    """
    Bit packing with overflow area.
    - Choose k_small that minimizes total bits.
    - Encode main area with B_main = 1 + max(k_small, ceil_log2(m))
      where first bit is flag: 0=inline value, 1=overflow index.
    - Overflow area stores the outliers using k_over bits (enough for max overflow value).
    - Supports CrossBoundary or NoCross strategy in both main and overflow parts (same k).
    """
    def __init__(self, base: str="cross", signed: bool=False, use_zigzag: bool=False):
        self.signed = signed
        self.use_zigzag = use_zigzag
        self.base_kind = base
        self.main_packer: Optional[BitPacker] = None
        self.overflow_packer: Optional[BitPacker] = None
        self.k_small = 0
        self.B_main = 0
        self.k_over = 0
        self.n = 0
        self.m = 0  # number of overflow values
        self.index_map: List[int] = []  # maps overflow positions as we encode

    def _make_base(self) -> BitPacker:
        if self.base_kind == "cross":
            return CrossBoundaryPacker(signed=False, use_zigzag=False)
        elif self.base_kind == "nocross":
            return NoCrossPacker(signed=False, use_zigzag=False)
        else:
            raise ValueError("base must be 'cross' or 'nocross'")

    def _prep(self, arr: List[int]) -> List[int]:
        if self.use_zigzag:
            return [ZigZag.encode(x) for x in arr]
        if self.signed:
            if not arr: return []
            max_abs = max(abs(x) for x in arr)
            k_all = max(1, max_abs.bit_length() + 1)
            mod = 1 << k_all
            return [(x + mod) & (mod-1) if x < 0 else x for x in arr]
        return arr[:]

    def _choose_params(self, u: List[int]) -> None:
        n = len(u)
        if n == 0:
            self.k_small = self.B_main = self.k_over = self.m = self.n = 0
            return
        max_u = max(u)
        best = None
        best_tuple = None

        for k_small in range(1, max(1, max_u.bit_length()) + 1):
            threshold = (1 << k_small) - 1
            overflow_vals = [x for x in u if x > threshold]
            m = len(overflow_vals)
            idx_bits = ceil_log2(m)
            B_main = 1 + max(k_small, idx_bits)
            k_over = 0 if m == 0 else max(1, max(overflow_vals).bit_length())
            total_bits = n * B_main + m * k_over
            candidate = (total_bits, -B_main, -k_over, -m)
            if best is None or candidate < best:
                best = candidate
                best_tuple = (k_small, B_main, k_over, m)

        self.k_small, self.B_main, self.k_over, self.m = best_tuple
        self.n = n

    def compress(self, arr: List[int]) -> None:
        u = self._prep(arr)
        self._choose_params(u)
        if self.n == 0:
            self.main_packer = self._make_base()
            self.main_packer.compress([])
            self.overflow_packer = self._make_base()
            self.overflow_packer.compress([])
            return

        threshold = (1 << self.k_small) - 1
        idx_bits = self.B_main - 1
        main_entries = []
        overflow_vals = []
        index_map = []
        next_idx = 0
        for x in u:
            if x <= threshold:
                main_entries.append((0 << idx_bits) | x)
            else:
                main_entries.append((1 << idx_bits) | next_idx)
                overflow_vals.append(x)
                index_map.append(next_idx)
                next_idx += 1

        self.main_packer = self._make_base()
        self.main_packer.k = self.B_main
        self.main_packer.compress(main_entries)

        self.overflow_packer = self._make_base()
        self.overflow_packer.k = max(1, self.k_over)
        self.overflow_packer.compress(overflow_vals)

        self.index_map = index_map

    def _get_unsigned(self, i: int) -> int:
        if i < 0 or i >= self.n:
            raise IndexError("index out of range")
        entry = self.main_packer.get(i)
        idx_bits = self.B_main - 1
        flag = entry >> idx_bits
        payload = entry & ((1 << idx_bits) - 1)
        if flag == 0:
            return payload
        else:
            return self.overflow_packer.get(payload)

    def get(self, i: int) -> int:
        u = self._get_unsigned(i)
        if self.use_zigzag:
            return ZigZag.decode(u)
        if self.signed:
            k = max(self.k_small + 1, self.k_over)
            sign_bit = 1 << (k - 1) if k > 0 else 0
            if sign_bit and (u & sign_bit):
                u = u - (1 << k)
        return u

    def decompress(self, out: List[int]) -> None:
        if len(out) < self.n:
            raise ValueError("output buffer too small")
        for i in range(self.n):
            out[i] = self.get(i)

    def bits_per_value(self) -> int:
        total_bits = self.n * self.B_main + self.m * self.k_over
        return math.ceil(total_bits / max(1, self.n))

    def compressed_words(self) -> List[int]:
        return self.main_packer.compressed_words() + self.overflow_packer.compressed_words()

    def size(self) -> int:
        return self.n

class PackerFactory:
    @staticmethod
    def create(kind: str, signed: bool=False, zigzag: bool=False) -> "BitPacker":
        if kind == "cross":
            return CrossBoundaryPacker(signed=signed, use_zigzag=zigzag)
        if kind == "nocross":
            return NoCrossPacker(signed=signed, use_zigzag=zigzag)
        if kind == "overflow-cross":
            return OverflowBitPacker(base="cross", signed=signed, use_zigzag=zigzag)
        if kind == "overflow-nocross":
            return OverflowBitPacker(base="nocross", signed=signed, use_zigzag=zigzag)
        raise ValueError("Unknown kind: " + kind)
