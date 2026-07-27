#!/usr/bin/env python3
"""Minimal MPQ *writer* — the export side that lets the toolkit's editors save a
playable mod. Builds a StarCraft/BW-compatible MPQ (v1 header, encrypted hash +
block tables) from a {name: bytes} dict, typically written out as a
``patch_rt.mpq`` that the engine applies over StarDat/BrooDat.

Storage is UNCOMPRESSED, single block per file (flags = FLAG_EXISTS only, no
sector-offset table, no encryption) — exactly how BW's own StarDat stores the
portrait files, so it is a format the retail Storm.dll is proven to read (see
CLAUDE.md §4 MPQ). That keeps the writer free of every sector/compression edge
case; a zlib-sectored path can come later if size matters.

Oracle: build_mpq() output is read straight back by tools/mpq.py and every file
must come out byte-identical (tests/test_mpq_writer.py). The ultimate check is
the game loading it — that is V's to run.

Only structure/crypto here; nothing borrowed beyond the StormLib crypt table and
hash already in mpq.py (format data, attributed there).
"""
import struct

from mpq import _T, hash_string, FLAG_EXISTS

MPQ_MAGIC = b'MPQ\x1a'
HEADER_SIZE = 32


def encrypt_words(words, key):
    """Inverse of mpq.decrypt_words: encrypt a u32 list in place-style, returning
    the ciphertext list. The s2 feedback uses the PLAINTEXT word, mirroring the
    decryptor (whose feedback uses the just-recovered plaintext)."""
    k = key & 0xFFFFFFFF
    s2 = 0xEEEEEEEE
    out = []
    for p in words:
        p &= 0xFFFFFFFF
        s2 = (s2 + _T[0x400 + (k & 0xFF)]) & 0xFFFFFFFF
        out.append((p ^ ((k + s2) & 0xFFFFFFFF)) & 0xFFFFFFFF)
        k = ((((~k & 0xFFFFFFFF) << 0x15) + 0x11111111) | (k >> 0x0B)) & 0xFFFFFFFF
        s2 = (p + s2 + ((s2 << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    return out


def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def build_mpq(files, with_listfile=True, hash_headroom=2):
    """files: dict {name(str): bytes}. Returns the MPQ archive as bytes.

    Names use backslashes internally (forward slashes are normalised by the
    hash, matching the reader). A (listfile) is added so tools can enumerate."""
    files = {k.replace('/', '\\'): v for k, v in files.items()}
    if with_listfile:
        listing = '\r\n'.join(list(files.keys()) + ['(listfile)'])
        files = dict(files)
        files['(listfile)'] = listing.encode('latin-1')

    names = list(files.keys())
    hts = max(16, _next_pow2(len(names) * hash_headroom))

    # ---- lay out file data right after the header ----
    data = bytearray()
    block = []                                   # (offset, packed, fsize, flags)
    file_offsets = {}
    for name in names:
        payload = files[name]
        off = HEADER_SIZE + len(data)
        data += payload
        file_offsets[name] = len(block)
        block.append((off, len(payload), len(payload), FLAG_EXISTS))

    # ---- hash table (flat u32 array, 4 per entry) ----
    ht = [0xFFFFFFFF] * (hts * 4)                 # all free (blockIndex 0xFFFFFFFF)
    for i in range(hts):
        ht[i * 4 + 2] = 0xFFFF0000                # locale 0 / platform 0xFFFF-ish; unread
    for name in names:
        a = hash_string(name, 'nameA')
        b = hash_string(name, 'nameB')
        start = hash_string(name, 'hash') % hts
        for probe in range(hts):
            e = (start + probe) % hts
            if ht[e * 4 + 3] == 0xFFFFFFFF:       # free slot
                ht[e * 4] = a
                ht[e * 4 + 1] = b
                ht[e * 4 + 2] = 0                 # locale 0, platform 0
                ht[e * 4 + 3] = file_offsets[name]
                break
        else:
            raise ValueError('hash table full (raise hash_headroom)')

    # ---- block table (flat u32 array, 4 per entry) ----
    bt = []
    for (off, packed, fsize, flags) in block:
        bt += [off, packed, fsize, flags]

    hash_off = HEADER_SIZE + len(data)
    block_off = hash_off + hts * 16
    archive_size = block_off + len(block) * 16

    ht_enc = encrypt_words(ht, hash_string('(hash table)', 'key'))
    bt_enc = encrypt_words(bt, hash_string('(block table)', 'key'))

    out = bytearray()
    out += MPQ_MAGIC
    out += struct.pack('<IIHHIIII', HEADER_SIZE, archive_size, 0, 3,
                       hash_off, block_off, hts, len(block))
    out += data
    out += struct.pack('<%dI' % len(ht_enc), *ht_enc)
    out += struct.pack('<%dI' % len(bt_enc), *bt_enc)
    return bytes(out)


def write_mpq(path, files, **kw):
    with open(path, 'wb') as f:
        f.write(build_mpq(files, **kw))


if __name__ == '__main__':
    import sys
    import os
    # demo: pack the given files into out.mpq under their basenames
    if len(sys.argv) < 3:
        print('usage: mpq_writer.py out.mpq file1 [file2 ...]')
        sys.exit(1)
    out = sys.argv[1]
    files = {}
    for p in sys.argv[2:]:
        files[os.path.basename(p)] = open(p, 'rb').read()
    write_mpq(out, files)
    print('wrote %s (%d files, %d bytes)' % (out, len(files), os.path.getsize(out)))
