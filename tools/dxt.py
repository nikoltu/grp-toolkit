#!/usr/bin/env python3
"""DXT / S3TC decoder (DXT1 / DXT3 / DXT5) + minimal DDS reader.

Decode is the DETERMINISTIC direction (unlike DXT encode, which is lossy), so
this is a byte-exact reference: the endpoint 565->888 expansion, the 1/3 and 2/3
colour interpolation, and the DXT3/DXT5 alpha are all spec-fixed. The rounding
matches JavaScript's Math.round (round half up: `int(x + 0.5)`, valid because all
values are non-negative), so this reader is byte-identical to the browser's
ddsToImageData - the independent cross-check in tests/test_dxt.py, alongside
synthetic blocks whose RGBA is computed by hand.

This is the pixel oracle the SC:R HD engine can diff its texture pipeline against
(decode a `.anim` layer's DDS to a golden PNG). No third-party libraries; the
S3TC block layout is public format knowledge, the interpolation is arithmetic.
"""
import struct


def color565(c):
    """Expand a 16-bit 565 colour to 8-bit RGB by bit replication."""
    r = (c >> 11) & 31
    g = (c >> 5) & 63
    b = c & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _r(x):
    """Round half up (matches JS Math.round for x >= 0)."""
    return int(x + 0.5)


def _decode_block(data, coff, dxt, alpha):
    """Decode one 4x4 colour block -> list of 16 (r,g,b,a). `alpha` is a
    16-entry list (DXT3/DXT5) or None (DXT1, alpha from the 1-bit mode)."""
    c0, c1 = struct.unpack_from('<HH', data, coff)
    rgb0, rgb1 = color565(c0), color565(c1)
    pal = [rgb0, rgb1, (0, 0, 0), (0, 0, 0)]
    onebit = (dxt == 1 and c0 <= c1)
    if onebit:
        pal[2] = ((rgb0[0] + rgb1[0]) >> 1, (rgb0[1] + rgb1[1]) >> 1,
                  (rgb0[2] + rgb1[2]) >> 1)
        pal[3] = (0, 0, 0)
    else:
        pal[2] = (_r((2 * rgb0[0] + rgb1[0]) / 3), _r((2 * rgb0[1] + rgb1[1]) / 3),
                  _r((2 * rgb0[2] + rgb1[2]) / 3))
        pal[3] = (_r((rgb0[0] + 2 * rgb1[0]) / 3), _r((rgb0[1] + 2 * rgb1[1]) / 3),
                  _r((rgb0[2] + 2 * rgb1[2]) / 3))
    idx = struct.unpack_from('<I', data, coff + 4)[0]
    out = []
    for k in range(16):
        ci = (idx >> (2 * k)) & 3
        col = pal[ci]
        if onebit and ci == 3:
            a = 0
        elif alpha is not None:
            a = alpha[k]
        else:
            a = 255
        out.append((col[0], col[1], col[2], a))
    return out


def _dxt5_alpha(data, p):
    a0, a1 = data[p], data[p + 1]
    at = [a0, a1] + [0] * 6
    if a0 > a1:
        for k in range(1, 7):
            at[k + 1] = _r(((7 - k) * a0 + k * a1) / 7)
    else:
        for k in range(1, 5):
            at[k + 1] = _r(((5 - k) * a0 + k * a1) / 5)
        at[6] = 0
        at[7] = 255
    bits = int.from_bytes(data[p + 2:p + 8], 'little')
    return [at[(bits >> (3 * k)) & 7] for k in range(16)]


def _dxt3_alpha(data, p):
    out = []
    for k in range(16):
        nib = (data[p + (k >> 1)] >> ((k & 1) * 4)) & 0xF
        out.append(nib * 17)
    return out


def decode(data, off, w, h, fourcc):
    """Decode a compressed block region -> RGBA bytes (w*h*4). `fourcc` is
    'DXT1'/'DXT3'/'DXT5'."""
    dxt = 1 if fourcc == 'DXT1' else 3 if fourcc == 'DXT3' else 5
    blk = 8 if dxt == 1 else 16
    out = bytearray(w * h * 4)
    bx_n, by_n = (w + 3) // 4, (h + 3) // 4
    p = off
    for by in range(by_n):
        for bx in range(bx_n):
            if dxt == 5:
                alpha = _dxt5_alpha(data, p)
                coff = p + 8
            elif dxt == 3:
                alpha = _dxt3_alpha(data, p)
                coff = p + 8
            else:
                alpha = None
                coff = p
            texels = _decode_block(data, coff, dxt, alpha)
            for k in range(16):
                lx, ly = bx * 4 + (k & 3), by * 4 + (k >> 2)
                if lx >= w or ly >= h:
                    continue
                di = (ly * w + lx) * 4
                out[di:di + 4] = bytes(texels[k])
            p += blk
    return bytes(out)


def decode_dds(data, off=0):
    """Decode a DDS blob at `off` -> (w, h, fourcc, rgba bytes). Header layout:
    height @12, width @16, pixel-format FourCC @84, pixel data @128."""
    if data[off:off + 4] != b'DDS ':
        raise ValueError('not a DDS at 0x%x' % off)
    h = struct.unpack_from('<I', data, off + 12)[0]
    w = struct.unpack_from('<I', data, off + 16)[0]
    fourcc = data[off + 84:off + 88].decode('latin1', 'replace')
    rgba = decode(data, off + 128, w, h, fourcc)
    return w, h, fourcc, rgba
