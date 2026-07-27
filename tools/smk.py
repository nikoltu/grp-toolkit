#!/usr/bin/env python3
"""Smacker (SMK2/SMK4) video decoder — stdlib only.

Written from the public format description and validated against the 519
portrait clips in the retail StarCraft archives. No code was taken from
libsmacker or FFmpeg; that is deliberate, because this toolkit's whole point is
to be an INDEPENDENT second implementation.

Implemented: header, the four Huffman code books (MMAP/MCLR/FULL/TYPE) with
their 3-slot MRU cache, palette chunks, and the four block modes
(MONO / FULL / SKIP / FILL) including SMK4's extra FULL sub-modes.
Audio is parsed only far enough to skip it.

    from smk import Smacker
    s = Smacker(open('TMaFid00.smk','rb').read())
    for i in range(s.frames):
        idx = s.decode_frame()      # bytearray, w*h palette indices
        rgb = s.rgb()               # bytes, w*h*3
"""
import struct, zlib, sys, os, argparse

SMK_NODE = 0x80000000

# Run lengths addressed by (type >> 2) & 0x3F.
BLOCK_RUNS = list(range(1, 60)) + [128, 256, 512, 1024, 2048]

# 6-bit palette component -> 8-bit.
PAL6 = bytes([
    0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C,
    0x20, 0x24, 0x28, 0x2C, 0x30, 0x34, 0x38, 0x3C,
    0x41, 0x45, 0x49, 0x4D, 0x51, 0x55, 0x59, 0x5D,
    0x61, 0x65, 0x69, 0x6D, 0x71, 0x75, 0x79, 0x7D,
    0x82, 0x86, 0x8A, 0x8E, 0x92, 0x96, 0x9A, 0x9E,
    0xA2, 0xA6, 0xAA, 0xAE, 0xB2, 0xB6, 0xBA, 0xBE,
    0xC3, 0xC7, 0xCB, 0xCF, 0xD3, 0xD7, 0xDB, 0xDF,
    0xE3, 0xE7, 0xEB, 0xEF, 0xF3, 0xF7, 0xFB, 0xFF])


class Bits:
    """Smacker reads bits LSB-first within each byte."""
    __slots__ = ('d', 'pos')

    def __init__(self, data, start=0):
        self.d = data
        self.pos = start * 8

    def bit(self):
        p = self.pos
        self.pos = p + 1
        return (self.d[p >> 3] >> (p & 7)) & 1

    def bits(self, n):
        v = 0
        for i in range(n):
            v |= self.bit() << i
        return v


def _tree8(bits, out):
    """8-bit code book: 1 = node, 0 = leaf carrying a byte. Returns a nested
    tuple tree; `out` collects leaf values in stream order."""
    if bits.bit():
        a = _tree8(bits, out)
        b = _tree8(bits, out)
        return (a, b)
    v = bits.bits(8)
    out.append(v)
    return v


def _walk8(bits, tree):
    while isinstance(tree, tuple):
        tree = tree[bits.bit()]
    return tree


class BigTree:
    """The 16-bit code book. Stored flat: a node holds SMK_NODE | (relative
    offset of its right child), a leaf holds the value. Three leaves are
    'escape' slots whose contents are rewritten as an MRU cache while decoding —
    that cache is why the same bit pattern can mean different things over time.
    """
    __slots__ = ('vals', 'last')

    def __init__(self, bits, size):
        # A 16-bit book carries its OWN leading "present" bit before the two
        # 8-bit sub-books. Missing it shifts the whole stream by one bit and the
        # tree collapses after a handful of entries -- which is exactly what
        # happened first time round.
        self.vals = [0]
        self.last = [0, 0, 0]
        if not bits.bit():
            return
        lo_vals, hi_vals = [], []
        lo = hi = None
        if bits.bit():
            lo = _tree8(bits, lo_vals)
            bits.bit()                      # terminator
        if bits.bit():
            hi = _tree8(bits, hi_vals)
            bits.bit()
        esc = [bits.bits(8) | (bits.bits(8) << 8) for _ in range(3)]

        self.vals = []
        self.last = [-1, -1, -1]

        def build():
            if not bits.bit():              # leaf
                a = _walk8(bits, lo) if lo is not None else 0
                b = _walk8(bits, hi) if hi is not None else 0
                v = a | (b << 8)
                for k in range(3):
                    if v == esc[k]:
                        self.last[k] = len(self.vals)
                        v = 0
                        break
                self.vals.append(v)
                return 1
            t = len(self.vals)
            self.vals.append(0)             # placeholder for the node
            r = build()
            self.vals[t] = SMK_NODE | r
            return r + 1 + build()

        build()
        bits.bit()
        for k in range(3):
            if self.last[k] == -1:
                self.last[k] = len(self.vals)
                self.vals.append(0)

    def reset(self):
        """The 3-slot MRU cache is per frame, not per file. Carrying it over
        decodes correctly for a while and then silently diverges — measured as
        frames consuming 32/180/228 bytes more than their declared size."""
        for k in self.last:
            self.vals[k] = 0

    def get(self, bits):
        v = self.vals
        i = 0
        while v[i] & SMK_NODE:
            if bits.bit():
                i += v[i] & ~SMK_NODE
            i += 1
        r = v[i]
        last = self.last
        if r != v[last[0]]:
            v[last[2]] = v[last[1]]
            v[last[1]] = v[last[0]]
            v[last[0]] = r
        return r


class Smacker:
    def __init__(self, data):
        d = self.data = data
        if d[:4] not in (b'SMK2', b'SMK4'):
            raise ValueError('not a Smacker file')
        self.version = 4 if d[3:4] == b'4' else 2
        self.width, self.height, self.frames = struct.unpack_from('<III', d, 4)
        self.rate = struct.unpack_from('<i', d, 16)[0]
        self.flags = struct.unpack_from('<I', d, 20)[0]
        self.audio_size = struct.unpack_from('<7I', d, 24)
        trees, mmap_s, mclr_s, full_s, type_s = struct.unpack_from('<5I', d, 52)
        self.audio_rate = struct.unpack_from('<7I', d, 72)

        n = self.frames
        raw_sizes = struct.unpack_from('<%dI' % n, d, 104)
        self.frame_sizes = [x & 0xFFFFFFFC for x in raw_sizes]
        self.keyframe = [bool(x & 1) for x in raw_sizes]
        ft_off = 104 + n * 4
        self.frame_types = list(d[ft_off:ft_off + n])
        tree_off = ft_off + n

        bits = Bits(d, tree_off)
        self.t_mmap = BigTree(bits, mmap_s)
        self.t_mclr = BigTree(bits, mclr_s)
        self.t_full = BigTree(bits, full_s)
        self.t_type = BigTree(bits, type_s)

        self.frame_off = [tree_off + trees]
        for s in self.frame_sizes:
            self.frame_off.append(self.frame_off[-1] + s)

        self.pal = bytearray(768)
        self.pixels = bytearray(self.width * self.height)
        self.cur = 0

    @property
    def fps(self):
        if self.rate > 0:
            return 1000.0 / self.rate
        if self.rate < 0:
            return 100000.0 / -self.rate
        return 10.0

    def _palette(self, p):
        size = self.data[p] * 4
        end = p + size
        q = p + 1
        old = bytes(self.pal)
        pal = bytearray()
        while len(pal) < 768 and q < end:
            t = self.data[q]; q += 1
            if t & 0x80:                       # keep N entries
                cnt = (t & 0x7F) + 1
                off = len(pal)
                pal += old[off:off + cnt * 3]
            elif t & 0x40:                     # copy N entries from offset
                cnt = (t & 0x3F) + 1
                off = self.data[q] * 3; q += 1
                for _ in range(cnt):
                    pal += old[off:off + 3]
                    off += 3
            else:                              # literal RGB, 6 bits each
                r = PAL6[t & 0x3F]
                g = PAL6[self.data[q] & 0x3F]; q += 1
                b = PAL6[self.data[q] & 0x3F]; q += 1
                pal += bytes((r, g, b))
        pal += bytes(768 - len(pal))
        self.pal = pal[:768]
        return end

    def decode_frame(self, index=None):
        """Decode the next frame (or `index`) into self.pixels and return it.
        Frames are differential: SKIP blocks keep the previous contents."""
        if index is None:
            index = self.cur
        for t in (self.t_mmap, self.t_mclr, self.t_full, self.t_type):
            t.reset()
        p = self.frame_off[index]
        end = p + self.frame_sizes[index]
        ftype = self.frame_types[index]

        if ftype & 1:
            p = self._palette(p)
        for t in range(7):                     # audio tracks: parsed to skip
            if ftype & (2 << t):
                if p + 4 > end:
                    break
                p += struct.unpack_from('<I', self.data, p)[0]

        w, h = self.width, self.height
        bw, bh = (w + 3) // 4, (h + 3) // 4
        blocks = bw * bh
        px = self.pixels
        bits = Bits(self.data, p)
        blk = 0
        while blk < blocks:
            typ = self.t_type.get(bits)
            run = BLOCK_RUNS[(typ >> 2) & 0x3F]
            mode = typ & 3
            if mode == 0:                                   # MONO
                while run and blk < blocks:
                    clr = self.t_mclr.get(bits)
                    mp = self.t_mmap.get(bits)
                    hi, lo = clr >> 8, clr & 0xFF
                    ox, oy = (blk % bw) * 4, (blk // bw) * 4
                    for y in range(4):
                        row = (oy + y) * w + ox
                        for x in range(4):
                            px[row + x] = hi if (mp & 1) else lo
                            mp >>= 1
                    blk += 1; run -= 1
            elif mode == 1:                                 # FULL
                sub = 0
                if self.version == 4:
                    if bits.bit():
                        sub = 1
                    elif bits.bit():
                        sub = 2
                while run and blk < blocks:
                    ox, oy = (blk % bw) * 4, (blk // bw) * 4
                    if sub == 0:
                        for y in range(4):
                            row = (oy + y) * w + ox
                            v = self.t_full.get(bits)
                            px[row + 2] = v & 0xFF; px[row + 3] = v >> 8
                            v = self.t_full.get(bits)
                            px[row + 0] = v & 0xFF; px[row + 1] = v >> 8
                    elif sub == 1:                          # every other row
                        for y in range(0, 4, 2):
                            row = (oy + y) * w + ox
                            v = self.t_full.get(bits)
                            px[row + 2] = v & 0xFF; px[row + 3] = v >> 8
                            v = self.t_full.get(bits)
                            px[row + 0] = v & 0xFF; px[row + 1] = v >> 8
                            px[row + w:row + w + 4] = px[row:row + 4]
                    else:                                   # two-pixel columns
                        for y in range(4):
                            row = (oy + y) * w + ox
                            v = self.t_full.get(bits)
                            px[row + 0] = px[row + 1] = v & 0xFF
                            px[row + 2] = px[row + 3] = v >> 8
                    blk += 1; run -= 1
            elif mode == 2:                                 # SKIP
                while run and blk < blocks:
                    blk += 1; run -= 1
            else:                                           # FILL
                col = (typ >> 8) & 0xFF
                while run and blk < blocks:
                    ox, oy = (blk % bw) * 4, (blk // bw) * 4
                    for y in range(4):
                        row = (oy + y) * w + ox
                        px[row:row + 4] = bytes((col,)) * 4
                    blk += 1; run -= 1
        self.cur = index + 1
        return px

    def rgb(self):
        pal, px = self.pal, self.pixels
        out = bytearray(len(px) * 3)
        for i, v in enumerate(px):
            o, s = i * 3, v * 3
            out[o:o + 3] = pal[s:s + 3]
        return bytes(out)


def write_png(path, w, h, rgb):
    raw = b''.join(b'\x00' + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 9))
           + chunk(b'IEND', b''))
    open(path, 'wb').write(png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('-o', '--outdir', help='write every frame as PNG here')
    ap.add_argument('--sheet', help='write all frames side by side as one PNG')
    ap.add_argument('--info', action='store_true')
    a = ap.parse_args()

    s = Smacker(open(a.input, 'rb').read())
    print('%s %dx%d  %d frames  %.2f fps  flags=0x%x' %
          (s.data[:4].decode(), s.width, s.height, s.frames, s.fps, s.flags), file=sys.stderr)
    if a.info:
        return
    frames = []
    for i in range(s.frames):
        s.decode_frame(i)
        frames.append(s.rgb())
        if a.outdir:
            os.makedirs(a.outdir, exist_ok=True)
            write_png(os.path.join(a.outdir, 'f%03d.png' % i), s.width, s.height, frames[-1])
    if a.sheet:
        W, H, n = s.width, s.height, len(frames)
        row = bytearray(W * n * H * 3)
        for i, f in enumerate(frames):
            for y in range(H):
                d = (y * W * n + i * W) * 3
                row[d:d + W * 3] = f[y * W * 3:(y + 1) * W * 3]
        write_png(a.sheet, W * n, H, bytes(row))
        print('wrote %s (%dx%d)' % (a.sheet, W * n, H), file=sys.stderr)


if __name__ == '__main__':
    main()
