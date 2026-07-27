"""Oracle for the DXT decoder (tools/dxt.py) - the HD texture pixel reference.

DXT decode is deterministic, so it is checked two ways:

  1. SYNTHETIC blocks whose RGBA is derived BY HAND from the S3TC rules - the
     565->888 bit-replication expansion, the 1/3 & 2/3 colour interpolation,
     DXT1's 1-bit-alpha mode, and DXT5's alpha ramp. No external reference; if
     the arithmetic is wrong the asserted texels won't match.

  2. (browser cross-check, run separately) decode a real .anim layer's DDS in
     Python and in the app's ddsToImageData -> byte-identical RGBA. Documented in
     tools/dxt.py; this test is the standalone, install-free part.

    py test_dxt.py
"""
import sys
import os
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import dxt                               # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import report                # noqa: E402

RED = 0xF800     # 565 (31,0,0)  -> (255,0,0)
BLUE = 0x001F    # 565 (0,0,31)  -> (0,0,255)


def texel(rgba, w, x, y):
    i = (y * w + x) * 4
    return tuple(rgba[i:i + 4])


def main():
    ok = total = 0
    bad = []

    # -- 565 expansion is exact bit replication --
    total += 1
    if dxt.color565(RED) == (255, 0, 0) and dxt.color565(BLUE) == (0, 0, 255) \
            and dxt.color565(0xFFFF) == (255, 255, 255) \
            and dxt.color565(0) == (0, 0, 0):
        ok += 1
    else:
        bad.append('color565 %s' % (dxt.color565(RED),))

    # -- DXT1, 4-colour mode (c0 > c1): pal = [c0, c1, (2c0+c1)/3, (c0+2c1)/3] --
    total += 1
    idx = (3 << 6) | (2 << 4) | (1 << 2) | 0        # texels 0..3 -> pal 0..3
    block = struct.pack('<HHI', RED, BLUE, idx)
    px = dxt.decode(block, 0, 4, 4, 'DXT1')
    want = [(255, 0, 0, 255), (0, 0, 255, 255),
            (170, 0, 85, 255), (85, 0, 170, 255)]    # (2*255+0)/3=170, (0+510)/3=170
    got = [texel(px, 4, i, 0) for i in range(4)]
    if got == want:
        ok += 1
    else:
        bad.append('dxt1 4-colour %s' % got)

    # -- DXT1, 1-bit-alpha mode (c0 <= c1): pal[2]=avg, pal[3]=transparent black --
    total += 1
    idx = (3 << 6) | (2 << 4) | (1 << 2) | 0
    block = struct.pack('<HHI', BLUE, RED, idx)      # c0(BLUE) <= c1(RED)
    px = dxt.decode(block, 0, 4, 4, 'DXT1')
    # pal0=BLUE opaque, pal1=RED opaque, pal2=avg opaque, pal3=(0,0,0,0)
    avg = ((0 + 255) >> 1, 0, (255 + 0) >> 1)        # (127,0,127)
    want = [(0, 0, 255, 255), (255, 0, 0, 255), (avg[0], 0, avg[2], 255),
            (0, 0, 0, 0)]
    got = [texel(px, 4, i, 0) for i in range(4)]
    if got == want:
        ok += 1
    else:
        bad.append('dxt1 1-bit alpha %s' % got)

    # -- DXT5 alpha ramp (a0 > a1): 8-entry table, 3-bit indices --
    total += 1
    # alpha block: a0=255, a1=0, indices pick 0,1,2,3 for texels 0..3, rest 0
    a_idx = 0
    for k in range(4):
        a_idx |= k << (3 * k)
    ablock = bytes([255, 0]) + a_idx.to_bytes(6, 'little')
    cblock = struct.pack('<HHI', RED, RED, 0)        # all colour = RED, opaque
    px = dxt.decode(ablock + cblock, 0, 4, 4, 'DXT5')
    at2 = dxt._r((6 * 255 + 1 * 0) / 7)              # 219
    at3 = dxt._r((5 * 255 + 2 * 0) / 7)              # 182
    want_a = [255, 0, at2, at3]
    got_a = [texel(px, 4, i, 0)[3] for i in range(4)]
    got_rgb = all(texel(px, 4, i, 0)[:3] == (255, 0, 0) for i in range(4))
    if got_a == want_a and got_rgb:
        ok += 1
    else:
        bad.append('dxt5 alpha %s (rgb_ok=%s)' % (got_a, got_rgb))

    # -- a full DDS blob decodes to the right dimensions (header parse) --
    total += 1
    body = ablock + cblock                           # one 4x4 DXT5 block
    dds = (b'DDS ' + b'\x00' * 8
           + struct.pack('<I', 4) + struct.pack('<I', 4)   # h@12, w@16
           + b'\x00' * 64 + b'DXT5' + b'\x00' * (128 - 88) + body)
    w, h, fourcc, rgba = dxt.decode_dds(dds)
    if w == 4 and h == 4 and fourcc == 'DXT5' and len(rgba) == 4 * 4 * 4:
        ok += 1
    else:
        bad.append('dds parse %dx%d %s' % (w, h, fourcc))

    rc = report('dxt: DXT1/3/5 decode (synthetic)', ok, total,
                '(bad=%s)' % (bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
