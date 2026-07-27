#!/usr/bin/env python3
"""Classic StarCraft GRP reader + writer (the graphics-mod export side).

A GRP is a palette-indexed sprite sheet:

    u16 frameCount, u16 canvasW, u16 canvasH
    frameCount x { u8 x, u8 y, u8 w, u8 h, u32 dataOffset }
    per frame, at dataOffset: h x u16 row offsets (relative to dataOffset),
      then RLE per row:
        b >= 0x80 -> skip (b-0x80) transparent pixels
        b >= 0x40 -> run  (b-0x40) copies of the next byte
        else      -> copy  b  literal bytes
    Index 0 is transparent.

Reader and writer are inverses in PIXELS: decode(encode(frames)) reproduces the
same index grids exactly (the guaranteed oracle, tests/test_grp_writer.py). Byte
identity against Blizzard's own files is NOT guaranteed - the RLE run/literal
split is a compression choice and the game reads any valid encoding - but the
test also REPORTS the byte-match rate on real GRPs so the gap is measured, not
assumed. (Flat, uncompressed GRPs like game\\icons.grp have no row table; this
writer emits the RLE form, which is what unit/wireframe/icon overrides use.)
"""
import struct

TRANSPARENT = 0


class GrpFrame:
    """One frame: placement (x, y) on the canvas, size (w, h), and a w*h list of
    palette indices in row-major order (0 = transparent)."""
    __slots__ = ('x', 'y', 'w', 'h', 'pixels')

    def __init__(self, x, y, w, h, pixels):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.pixels = pixels

    def at(self, px, py):
        return self.pixels[py * self.w + px]


class Grp:
    def __init__(self, canvas_w, canvas_h, frames):
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.frames = frames


# ---------------------------------------------------------------- reader ----
def _decode_frame(data, off, w, h):
    pixels = [0] * (w * h)
    for row in range(h):
        line_off = struct.unpack_from('<H', data, off + row * 2)[0]
        p = off + line_off
        x = 0
        while x < w:
            b = data[p]
            p += 1
            if b >= 0x80:                       # transparent skip
                x += b - 0x80
            elif b >= 0x40:                     # run
                cnt = b - 0x40
                val = data[p]
                p += 1
                for _ in range(cnt):
                    if x < w:
                        pixels[row * w + x] = val
                        x += 1
            else:                               # literal
                for _ in range(b):
                    if x < w:
                        pixels[row * w + x] = data[p]
                    p += 1
                    x += 1
    return pixels


def read(data):
    """Parse an RLE GRP into a Grp. Raises on a frame that runs past EOF."""
    fc, cw, ch = struct.unpack_from('<HHH', data, 0)
    frames = []
    for i in range(fc):
        x, y, w, h, off = struct.unpack_from('<BBBBI', data, 6 + i * 8)
        frames.append(GrpFrame(x, y, w, h, _decode_frame(data, off, w, h)))
    return Grp(cw, ch, frames)


# ---------------------------------------------------------------- writer ----
def _run_len(row, x, w, val):
    n = 0
    while x + n < w and row[x + n] == val and n < 0x3F:
        n += 1
    return n


def _encode_row(row, w):
    """RLE-encode one row of indices. Greedy: transparent -> skip; a repeat of
    >=2 -> run; otherwise a literal segment up to the next run/transparent."""
    out = bytearray()
    x = 0
    while x < w:
        v = row[x]
        if v == TRANSPARENT:
            cnt = 0
            while x < w and row[x] == TRANSPARENT and cnt < 0x7F:
                cnt += 1
                x += 1
            out.append(0x80 | cnt)
            continue
        rep = _run_len(row, x, w, v)
        if rep >= 2:
            out.append(0x40 | rep)
            out.append(v)
            x += rep
            continue
        # literal: accumulate single pixels until a run (>=2) or transparent
        lit = bytearray()
        while x < w and row[x] != TRANSPARENT and len(lit) < 0x3F \
                and _run_len(row, x, w, row[x]) < 2:
            lit.append(row[x])
            x += 1
        out.append(len(lit))
        out += lit
    return out


def _encode_frame(frame):
    """Frame -> (row_table_bytes + rle_bytes). Row offsets are relative to the
    start of this block (i.e. include the 2*h table itself)."""
    h = frame.h
    rows = [_encode_row(frame.pixels[r * frame.w:(r + 1) * frame.w], frame.w)
            for r in range(h)]
    table_size = 2 * h
    offsets = []
    body = bytearray()
    for rb in rows:
        offsets.append(table_size + len(body))
        body += rb
    out = bytearray()
    for o in offsets:
        out += struct.pack('<H', o)
    out += body
    return bytes(out)


def write(grp, dedup=True):
    """Serialise a Grp to RLE GRP bytes. `dedup` shares one data block between
    frames that encode identically (the same trick Blizzard's GRPs use for
    repeated/empty frames), which shrinks the file without changing pixels."""
    fc = len(grp.frames)
    header = bytearray(struct.pack('<HHH', fc, grp.canvas_w, grp.canvas_h))
    table = bytearray()
    blocks = bytearray()
    data_start = 6 + fc * 8
    seen = {}                                    # block bytes -> offset
    for fr in grp.frames:
        blk = _encode_frame(fr)
        if dedup and blk in seen:
            off = seen[blk]
        else:
            off = data_start + len(blocks)
            blocks += blk
            if dedup:
                seen[blk] = off
        table += struct.pack('<BBBBI', fr.x, fr.y, fr.w, fr.h, off)
    return bytes(header + table + blocks)


def build(canvas_w, canvas_h, frames):
    """frames: list of (x, y, w, h, pixels) tuples -> GRP bytes."""
    return write(Grp(canvas_w, canvas_h,
                     [GrpFrame(*f) for f in frames]))


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    import mpq
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    for name in ('unit\\wirefram\\wirefram.grp', 'unit\\cmdbtns\\cmdicons.grp'):
        try:
            data = mpq.MpqChain(base).read(name)
        except Exception as e:                       # noqa: BLE001
            print('%-32s ERR %s' % (name, e))
            continue
        g = read(data)
        re = write(g)
        g2 = read(re)
        px_ok = all(a.pixels == b.pixels for a, b in zip(g.frames, g2.frames))
        byte_ok = re == data
        print('%-32s %d frames %dx%d  px-roundtrip=%s  byte-identical=%s '
              '(%d->%d B)' % (name, len(g.frames), g.canvas_w, g.canvas_h,
                              px_ok, byte_ok, len(data), len(re)))
