#!/usr/bin/env python3
"""MPQ WAVE decompression — StormLib Huffman (0x01) + IMA-style ADPCM (0x40/0x80).

This is how the 1998 archives store every voice line: sector 0 is PKWARE, the
rest are 0x41 (mono) or 0x81 (stereo).

PROVENANCE — read this before assuming the project's usual rules apply.
Everywhere else in this toolkit the implementations are deliberately written
without looking at anyone else's decoder, because the point is to be an
independent second opinion0)#0). This file is the one
exception, and only partly:

  * The nine 258-byte Huffman weight tables and the ADPCM step/index tables are
    FORMAT DATA. They cannot be derived or guessed, and without them the initial
    tree cannot be built at all. They are taken from StormLib
    (https://github.com/ladislav-zezula/StormLib, MIT, (c) 1999-2013 Ladislav
    Zezula) and are reproduced here under that licence.
  * The code below is written from the algorithm's structure, not copied.

Because it leans on StormLib for the tables, this decoder is NOT an independent
check of StormLib. It does not have to be: SC:R ships the same audio uncompressed
under sd/sound/, and 1123 of 1127 sizes match the MPQ declaration exactly, so
every file here can be verified byte-for-byte against a source that has nothing
to do with StormLib. That is the strongest oracle in this project.
"""
import struct

SPARSE = 0                      # data type 0 bumps weights on every output byte

WEIGHT_TABLES = (
    # sparse/generic
    (
        10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0
    ),
    # binary
    (
        84, 22, 22, 13, 12, 8, 6, 5, 6, 5, 6, 3, 4, 4, 3, 5, 14, 11, 20, 19, 19, 9, 11, 6, 5, 4,
        3, 2, 3, 2, 2, 2, 13, 7, 9, 6, 6, 4, 3, 2, 4, 3, 3, 3, 3, 3, 2, 2, 9, 6, 4, 4, 4, 4, 3,
        2, 3, 2, 2, 2, 2, 3, 2, 4, 8, 3, 4, 7, 9, 5, 3, 3, 3, 3, 2, 2, 2, 3, 2, 2, 3, 2, 2, 2,
        2, 2, 2, 2, 2, 1, 1, 1, 2, 1, 2, 2, 6, 10, 8, 8, 6, 7, 4, 3, 4, 4, 2, 2, 4, 2, 3, 3, 4,
        3, 7, 7, 9, 6, 4, 3, 3, 2, 1, 2, 2, 2, 2, 2, 10, 2, 2, 3, 2, 2, 1, 1, 2, 2, 2, 6, 3, 5,
        2, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 2, 4, 4, 4,
        7, 9, 8, 12, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 3, 4, 1, 2, 4, 5, 1, 1, 1,
        1, 1, 1, 1, 2, 1, 1, 1, 4, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1,
        1, 1, 1, 3, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 2, 2, 1, 1, 2, 2, 2, 6, 75, 0, 0
    ),
    # text
    (
        0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 39, 0, 0, 35, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 255, 1, 1, 1, 1, 1, 1, 1, 2, 2, 1, 1, 6, 14, 16, 4, 6, 8, 5, 4, 4, 3, 3, 2, 2,
        3, 3, 1, 1, 2, 1, 1, 1, 4, 2, 4, 2, 2, 2, 1, 1, 4, 1, 1, 2, 3, 3, 2, 3, 1, 3, 6, 4, 1,
        1, 1, 1, 1, 1, 2, 1, 2, 1, 1, 1, 41, 7, 22, 18, 64, 10, 10, 17, 37, 1, 3, 23, 16, 38,
        42, 16, 1, 35, 35, 47, 16, 6, 7, 2, 9, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0
    ),
    # general
    (
        255, 11, 7, 5, 11, 2, 2, 2, 6, 2, 2, 1, 4, 2, 1, 3, 9, 1, 1, 1, 3, 4, 1, 1, 2, 1, 1, 1,
        2, 1, 1, 1, 5, 1, 1, 1, 13, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 3, 1, 1, 1, 1, 1,
        1, 1, 2, 1, 1, 1, 1, 10, 4, 2, 1, 6, 3, 2, 1, 1, 1, 1, 1, 3, 1, 1, 1, 5, 2, 3, 4, 3, 3,
        3, 2, 1, 1, 1, 2, 1, 2, 3, 3, 1, 3, 1, 1, 2, 5, 1, 1, 4, 3, 5, 1, 3, 1, 3, 3, 2, 1, 4,
        3, 10, 6, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 1, 10, 2, 5, 1, 1, 2, 7, 2, 23, 1, 5, 1,
        1, 14, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
        1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 6, 2, 1, 4, 5, 1, 1, 2, 1,
        1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
        1, 1, 7, 1, 1, 2, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 17, 0, 0
    ),
    # ADPCM 4-bit
    (
        255, 251, 152, 154, 132, 133, 99, 100, 62, 62, 34, 34, 19, 19, 24, 23, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0
    ),
    # ADPCM 6-bit
    (
        255, 241, 157, 158, 154, 155, 154, 151, 147, 147, 140, 142, 134, 136, 128, 130, 124,
        124, 114, 115, 105, 107, 95, 96, 85, 86, 74, 75, 64, 65, 55, 55, 47, 47, 39, 39, 33, 33,
        27, 28, 23, 23, 19, 19, 16, 16, 13, 13, 11, 11, 9, 9, 8, 8, 7, 7, 6, 5, 5, 4, 4, 4, 25,
        24, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    ),
    # stereo 3-bit
    (
        195, 203, 245, 65, 255, 123, 247, 33, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 191, 204, 242, 64, 253, 124, 247, 34, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 122, 70, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0
    ),
    # stereo 4-bit
    (
        195, 217, 239, 61, 249, 124, 233, 30, 253, 171, 241, 44, 252, 91, 254, 23, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 189, 217, 236, 61, 245, 125, 232, 29, 251,
        174, 240, 44, 251, 92, 255, 24, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        112, 108, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    ),
    # stereo 5-bit
    (
        186, 197, 218, 51, 227, 109, 216, 24, 229, 148, 218, 35, 223, 74, 209, 16, 238, 175,
        228, 44, 234, 90, 222, 21, 244, 135, 233, 33, 246, 67, 252, 18, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 176, 199, 216,
        51, 227, 107, 214, 24, 231, 149, 216, 35, 219, 73, 208, 17, 233, 178, 226, 43, 232, 92,
        221, 21, 241, 135, 231, 32, 247, 68, 255, 19, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 95, 158, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0
    ),
)


# --------------------------------------------------------------- Huffman
class _Node:
    __slots__ = ('prev', 'nxt', 'parent', 'child_lo', 'weight', 'value')

    def __init__(self, value=0, weight=0):
        self.prev = self.nxt = None
        self.parent = None
        self.child_lo = None
        self.weight = weight
        self.value = value


class _Bits:
    """LSB-first, byte at a time, exactly as the format reads it."""
    __slots__ = ('d', 'p', 'buf', 'cnt')

    def __init__(self, d):
        self.d, self.p, self.buf, self.cnt = d, 0, 0, 0

    def bit(self):
        if self.cnt == 0:
            if self.p >= len(self.d):
                return None
            self.buf = self.d[self.p]; self.p += 1; self.cnt = 8
        v = self.buf & 1
        self.buf >>= 1
        self.cnt -= 1
        return v

    def byte(self):
        if self.cnt < 8:
            if self.p >= len(self.d):
                return None
            self.buf |= self.d[self.p] << self.cnt
            self.p += 1
            self.cnt += 8
        v = self.buf & 0xFF
        self.buf >>= 8
        self.cnt -= 8
        return v


class _Tree:
    """Adaptive Huffman kept as a weight-ordered circular list (descending from
    the head) with tree links layered on top. A node's two children are adjacent
    in that list: child_lo, and child_lo.prev as the higher-weight sibling."""

    def __init__(self, data_type):
        self.head = _Node()
        self.head.prev = self.head.nxt = self.head
        self.by_value = {}
        self._build(data_type & 0x0F)

    # -- list primitives
    @staticmethod
    def _unlink(n):
        if n.prev is not None:
            n.prev.nxt = n.nxt
            n.nxt.prev = n.prev
        n.prev = n.nxt = None

    @staticmethod
    def _link_after(a, b):
        b.nxt = a.nxt
        b.prev = a
        a.nxt.prev = b
        a.nxt = b

    def _find_ge(self, node, weight):
        """First node at or before `node` whose weight >= weight."""
        while node is not None and node is not self.head:
            if node.weight >= weight:
                return node
            node = node.prev
        return self.head

    def _new(self, value, weight, before):
        n = _Node(value, weight)
        self._link_after(self.head.prev if before else self.head, n)
        return n

    def _fixup(self, node, max_weight):
        if node.weight < max_weight:
            higher = self._find_ge(self.head.prev, node.weight)
            self._unlink(node)
            self._link_after(higher, node)
            return max_weight
        return node.weight

    def _build(self, data_type):
        table = WEIGHT_TABLES[data_type]
        mw = 0
        for i in range(256):
            if table[i]:
                n = self._new(i, table[i], before=False)
                self.by_value[i] = n
                mw = self._fixup(n, mw)
        self.by_value[0x100] = self._new(0x100, 1, before=True)
        self.by_value[0x101] = self._new(0x101, 1, before=True)

        lo = self.head.prev
        while lo is not self.head:
            hi = lo.prev
            if hi is self.head:
                break
            parent = self._new(0, hi.weight + lo.weight, before=False)
            lo.parent = parent
            hi.parent = parent
            parent.child_lo = lo
            mw = self._fixup(parent, mw)
            lo = hi.prev

    def inc_weights(self, node):
        while node is not None:
            node.weight += 1
            higher = self._find_ge(node.prev, node.weight)
            sib = higher.nxt
            if sib is not node:
                self._unlink(sib)
                self._link_after(node, sib)
                self._unlink(node)
                self._link_after(higher, node)
                sib_parent_lo = sib.parent.child_lo if sib.parent else None
                parent = node.parent
                if parent is not None and parent.child_lo is node:
                    parent.child_lo = sib
                if sib_parent_lo is sib and sib.parent is not None:
                    sib.parent.child_lo = node
                node.parent, sib.parent = sib.parent, node.parent
            node = node.parent

    def insert_branch(self, value1, value2):
        last = self.head.prev
        hi = self._new(value1, last.weight, before=True)
        hi.parent = last
        self.by_value[value1] = hi
        lo = self._new(value2, 0, before=True)
        lo.parent = last
        last.child_lo = lo
        self.by_value[value2] = lo
        self.inc_weights(lo)

    def decode(self, bits):
        node = self.head.nxt
        if node is self.head:
            return None
        while node.child_lo is not None:
            b = bits.bit()
            if b is None:
                return None
            node = node.child_lo.prev if b else node.child_lo
        return node.value


def huff_decompress(data, out_size):
    bits = _Bits(data)
    dtype = bits.byte()
    if dtype is None:
        return b''
    sparse = (dtype == SPARSE)
    tree = _Tree(dtype)
    out = bytearray()
    while len(out) < out_size:
        v = tree.decode(bits)
        if v is None or v == 0x100:
            break
        if v == 0x101:                       # escape: a byte not yet in the tree
            v = bits.byte()
            if v is None:
                break
            tree.insert_branch(tree.head.prev.value, v)
            if not sparse:
                tree.inc_weights(tree.by_value[v])
        out.append(v & 0xFF)
        if sparse:
            tree.inc_weights(tree.by_value[v])
    return bytes(out)


# ----------------------------------------------------------------- ADPCM
STEP_SIZE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
    32767)
NEXT_STEP = (-1, 0, -1, 4, -1, 2, -1, 6, -1, 1, -1, 5, -1, 3, -1, 7,
             -1, 1, -1, 5, -1, 3, -1, 7, -1, 2, -1, 4, -1, 6, -1, 8)
INITIAL_STEP_INDEX = 0x2C


def adpcm_decompress(data, channels):
    out = bytearray()
    if len(data) < 2:
        return bytes(out)
    p = 1
    shift = data[p]; p += 1                  # byte 0 unused, byte 1 = bit shift
    pred = [0, 0]
    step_idx = [INITIAL_STEP_INDEX, INITIAL_STEP_INDEX]
    for c in range(channels):
        if p + 2 > len(data):
            return bytes(out)
        s = struct.unpack_from('<h', data, p)[0]; p += 2
        pred[c] = s
        out += struct.pack('<h', s)
    ch = channels - 1
    while p < len(data):
        enc = data[p]; p += 1
        ch = (ch + 1) % channels
        if enc == 0x80:                      # repeat, decay the step
            if step_idx[ch]:
                step_idx[ch] -= 1
            out += struct.pack('<h', pred[ch])
        elif enc == 0x81:                    # widen the step, same channel next
            step_idx[ch] += 8
            if step_idx[ch] > 0x58:
                step_idx[ch] = 0x58
            ch = (ch + 1) % channels
        else:
            si = step_idx[ch]
            step = STEP_SIZE[si]
            diff = step >> shift
            for b in range(6):
                if enc & (1 << b):
                    diff += step >> b
            v = pred[ch]
            if enc & 0x40:
                v -= diff
                if v <= -32768:
                    v = -32768
            else:
                v += diff
                if v >= 32767:
                    v = 32767
            pred[ch] = v
            out += struct.pack('<h', v)
            si += NEXT_STEP[enc & 0x1F]
            step_idx[ch] = 0 if si < 0 else (88 if si > 88 else si)
    return bytes(out)


def wave_decompress(data, out_size, mask):
    """mask: 0x01 Huffman, 0x40 ADPCM mono, 0x80 ADPCM stereo (combined 0x41/0x81)."""
    if mask & 0x01:
        data = huff_decompress(data, out_size if not (mask & 0xC0) else out_size)
    if mask & 0x80:
        data = adpcm_decompress(data, 2)
    elif mask & 0x40:
        data = adpcm_decompress(data, 1)
    return data[:out_size]
