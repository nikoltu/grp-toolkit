#!/usr/bin/env python3
"""Decode an SC:R `.anim` layer to a golden RGBA image - the HD texture oracle.

Ties tools/anim.py (structure) + tools/dxt.py (byte-exact DXT decode) + tools/
png.py: for a chosen layer it decodes that layer's DDS atlas, and can crop a
single frame using the frame records (atlasX/Y, w/h). The engine diffs its own
HD texture pipeline against these PNGs. Per-LAYER on purpose - this isolates the
DXT decode from the engine's shader (which composites diffuse+teamcolor+emissive
etc.); comparing raw layer textures is the clean byte-exact check.

    py anim_render.py <SCR_DIR> <anim_name> --layer diffuse --atlas -o atlas.png
    py anim_render.py <SCR_DIR> <anim_name> --layer teamcolor --frame 0 -o f0.png
    py anim_render.py --file some.anim --layer 0 --atlas -o out.png
"""
import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim
import dxt
import png


def decode_layer_atlas(data, a, layer):
    """(w, h, fourcc, rgba) for a layer given by index or name."""
    if isinstance(layer, str) and not layer.isdigit():
        if layer not in a.layers:
            raise SystemExit('no layer %r (have %s)' % (layer, a.layers))
        layer = a.layers.index(layer)
    layer = int(layer)
    tr = a.texrefs[layer]
    if not tr.dds_offset:
        # MEASURED, important for an HD engine: MANY HD `.anim` files carry only
        # the diffuse DDS in-file; the other layers (bright/teamcolor/emissive/
        # normal/specular/ao_depth) have ddsOffset == 0 and are refId-SHARED -
        # their pixels live in a DIFFERENT .anim (the one the entry's refId points
        # at), NOT in this file. So "layer has no DDS here" does not mean the
        # sprite lacks that layer; it means the renderer must follow refId to the
        # sharing file and sample the texture from there. Decoding this file alone
        # cannot produce the shared layers.
        raise SystemExit('layer %d (%s) has no DDS in this file - refId-shared '
                         '(texture lives in another .anim; follow the entry '
                         'refId)' % (layer, a.layers[layer] if layer < len(a.layers)
                                     else '?'))
    return dxt.decode_dds(data, tr.dds_offset)


def frame_records(data, a):
    """All frame records across every entry: (atlasX, atlasY, xoff, yoff, w, h)."""
    recs = []
    for e in a.entries:
        ft = e.frame_table_offset
        for i in range(e.frame_count):
            o = ft + i * 16
            if o + 16 > len(data):
                break
            ax, ay, xo, yo, w, h = struct.unpack_from('<HHhhHH', data, o)
            recs.append((ax, ay, xo, yo, w, h))
    return recs


def crop(atlas_w, atlas_h, rgba, ax, ay, w, h):
    """Crop a w*h frame out of the atlas at (ax, ay) -> RGBA bytes."""
    out = bytearray(w * h * 4)
    for row in range(h):
        sy = ay + row
        if sy >= atlas_h:
            break
        s = (sy * atlas_w + ax) * 4
        n = min(w, atlas_w - ax) * 4
        out[row * w * 4:row * w * 4 + n] = rgba[s:s + n]
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description='Decode a .anim layer to PNG.')
    ap.add_argument('scr', nargs='?', default=r'C:\Git\StarCraft Remastered')
    ap.add_argument('name', nargs='?', help='anim name in the CASC (e.g. anim/main_509.anim)')
    ap.add_argument('--file', help='a raw .anim on disk instead of CASC')
    ap.add_argument('--layer', default='diffuse', help='layer index or name')
    ap.add_argument('--atlas', action='store_true', help='whole atlas (default)')
    ap.add_argument('--frame', type=int, help='crop this frame index instead')
    ap.add_argument('-o', default='anim_layer.png')
    args = ap.parse_args()

    if args.file:
        data = open(args.file, 'rb').read()
    else:
        import casc
        st = casc.NamedStorage(os.path.join(args.scr, 'data', 'data'),
                               install_root=args.scr)
        data = st.read_name(args.name)
    a = anim.parse(data)
    w, h, fourcc, rgba = decode_layer_atlas(data, a, args.layer)

    if args.frame is not None:
        recs = frame_records(data, a)
        if not (0 <= args.frame < len(recs)):
            raise SystemExit('frame %d out of range (%d frames)'
                             % (args.frame, len(recs)))
        ax, ay, xo, yo, fw, fh = recs[args.frame]
        fr = crop(w, h, rgba, ax, ay, fw, fh)
        png.write_rgba(args.o, fw, fh, fr)
        print('frame %d: %dx%d @atlas(%d,%d) offset(%d,%d) %s -> %s'
              % (args.frame, fw, fh, ax, ay, xo, yo, fourcc, args.o))
    else:
        png.write_rgba(args.o, w, h, rgba)
        print('atlas %dx%d %s (layer %s) -> %s' % (w, h, fourcc, args.layer, args.o))


if __name__ == '__main__':
    main()
