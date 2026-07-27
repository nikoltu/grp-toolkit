#!/usr/bin/env python3
"""Minimal PNG writer (stdlib zlib only) - RGB and RGBA, 8-bit.

Just enough to dump decoded textures/frames as golden images for the HD engine
to diff against. No compression tuning; correctness over size.
"""
import struct
import zlib


def _chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))


def _write(path, w, h, pixels, channels):
    color_type = 2 if channels == 3 else 6      # 2 = RGB, 6 = RGBA
    raw = bytearray()
    stride = w * channels
    for y in range(h):
        raw.append(0)                           # filter type 0 (none)
        raw += pixels[y * stride:(y + 1) * stride]
    png = (b'\x89PNG\r\n\x1a\n'
           + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, color_type, 0, 0, 0))
           + _chunk(b'IDAT', zlib.compress(bytes(raw), 9))
           + _chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def write_rgba(path, w, h, rgba):
    _write(path, w, h, rgba, 4)


def write_rgb(path, w, h, rgb):
    _write(path, w, h, rgb, 3)
