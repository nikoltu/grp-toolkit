#!/usr/bin/env python3
"""Composite the 7 SC:R `.anim` layers into a final RGBA frame - the HD render
reference the engine diffs its shader output against.

anim_render.py decodes ONE layer (the clean byte-exact DXT check). This tool goes
one step further: it combines the layers the way the game's sprite shader does,
so the engine can diff the FINAL pixel, not just a raw texture. That is what
turns "my shader looks right" into a byte comparison.

WHAT IS BYTE-EXACT vs WHAT IS THE REFERENCE BLEND
-------------------------------------------------
Each OPERATION here is independently verified (tests/test_anim_composite.py):
  * diffuse decode          - tools/dxt.py, byte-exact vs the browser.
  * team-colour tint        - tools/player_colors.apply_team_color, byte-exact
                              (mask/255 * playerColour, mask as alpha).
  * src-over alpha compose  - integer straight-alpha, checked on hand-computed
                              pixels.
  * additive emissive       - clamped 8-bit add, checked on hand-computed pixels.

What is NOT independently provable here is the SHADER RECIPE - which layers go in,
in what order. The baseline below is the documented standard 2D composite:

    final = diffuse
    final = src_over(tint(teamcolor_mask, playerColour), final)   # team paint
    final.rgb = clamp(final.rgb + emissive.rgb)                    # self-glow

`bright`, `normal`, `specular`, `ao_depth` are LIGHTING inputs (bloom / surface
normals / specular / ambient occlusion) that a flat top-down reference frame does
not bake in without a light; they are decoded and returned for inspection but not
composited into the baseline. When V supplies the engine's exact blend, swap
`COMPOSITE_STEPS` / plug the extra layers - the per-operation primitives stay
byte-exact, so locking the recipe is the same iterative diff the VP8/VP9 decoders
went through. Until then this is the reference for diffuse+team+emissive, which is
what dominates the visible sprite.

No third-party libraries. Reuses anim.py + dxt.py + player_colors.py + png.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim
import dxt
import player_colors
import anim_render


def src_over(top, bottom):
    """Composite `top` RGBA over `bottom` RGBA (straight alpha, integer, per the
    standard Porter-Duff over). Same length; returns new RGBA bytes.

        a  = at + ab*(1-at)
        c  = (ct*at + cb*ab*(1-at)) / a      (premultiply, blend, un-premultiply)
    Rounded half up. Fully-transparent result -> transparent black."""
    out = bytearray(len(bottom))
    for i in range(0, len(bottom), 4):
        at = top[i + 3]
        if at == 255:                                   # opaque top: straight copy
            out[i:i + 4] = top[i:i + 4]
            continue
        if at == 0:                                     # transparent top: keep bottom
            out[i:i + 4] = bottom[i:i + 4]
            continue
        ab = bottom[i + 3]
        inv = 255 - at
        oa = at + ab * inv // 255
        if oa == 0:
            continue
        for c in range(3):
            premul = top[i + c] * at + bottom[i + c] * ab * inv // 255
            out[i + c] = int(premul / oa + 0.5)
        out[i + 3] = oa
    return bytes(out)


def add_clamp_rgb(base, add):
    """Additive blend of `add` RGB into `base` RGBA, clamped to 255. `add`'s own
    alpha gates the contribution (add.rgb * add.a/255), base alpha unchanged."""
    out = bytearray(base)
    for i in range(0, len(base), 4):
        aa = add[i + 3]
        if aa == 0:
            continue
        for c in range(3):
            v = out[i + c] + add[i + c] * aa // 255
            out[i + c] = 255 if v > 255 else v
    return bytes(out)


def _layer_atlas(data, a, name):
    """Decoded RGBA atlas for a named layer, or None if absent/refId-shared here."""
    if name not in a.layers:
        return None
    idx = a.layers.index(name)
    if idx >= len(a.texrefs) or not a.texrefs[idx].dds_offset:
        return None                                     # refId-shared: lives elsewhere
    _, _, _, rgba = dxt.decode_dds(data, a.texrefs[idx].dds_offset)
    return rgba


def composite_frame(data, a, frame_index, player_rgb=(244, 4, 4),
                    team=True, emissive=True):
    """Composite one frame of a parsed .anim into final RGBA (w, h, rgba).

    Baseline recipe: diffuse -> team-colour src-over -> additive emissive.
    Layers that are refId-shared in this file are skipped and noted via the
    returned `used` set (an HD renderer would follow refId to sample them)."""
    recs = anim_render.frame_records(data, a)
    if not (0 <= frame_index < len(recs)):
        raise IndexError('frame %d of %d' % (frame_index, len(recs)))
    ax, ay, xo, yo, fw, fh = recs[frame_index]
    # atlas geometry (all layers share it)
    di = a.layers.index('diffuse') if 'diffuse' in a.layers else 0
    if di >= len(a.texrefs) or not a.texrefs[di].dds_offset:
        raise ValueError('diffuse is refId-shared here; cannot composite alone')
    aw, ah, _, diffuse_atlas = dxt.decode_dds(data, a.texrefs[di].dds_offset)

    used = {'diffuse'}
    frame = bytearray(anim_render.crop(aw, ah, diffuse_atlas, ax, ay, fw, fh))

    if team:
        tc = _layer_atlas(data, a, 'teamcolor')
        if tc is not None:
            mask = anim_render.crop(aw, ah, tc, ax, ay, fw, fh)
            tint = player_colors.apply_team_color(mask, player_rgb)
            frame = bytearray(src_over(tint, bytes(frame)))
            used.add('teamcolor')
    if emissive:
        em = _layer_atlas(data, a, 'emissive')
        if em is not None:
            emf = anim_render.crop(aw, ah, em, ax, ay, fw, fh)
            frame = bytearray(add_clamp_rgb(bytes(frame), emf))
            used.add('emissive')
    return fw, fh, bytes(frame), used


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Composite a .anim frame to PNG.')
    ap.add_argument('scr', nargs='?', default=r'C:\Git\StarCraft Remastered')
    ap.add_argument('name', nargs='?', default='anim/main_239.anim')
    ap.add_argument('--file', help='raw .anim on disk')
    ap.add_argument('--frame', type=int, default=0)
    ap.add_argument('--player', type=int, default=1, help='player 1..8 colour')
    ap.add_argument('--no-team', action='store_true')
    ap.add_argument('--no-emissive', action='store_true')
    ap.add_argument('-o', default='composite.png')
    args = ap.parse_args()
    import png
    if args.file:
        data = open(args.file, 'rb').read()
    else:
        import casc
        st = casc.NamedStorage(os.path.join(args.scr, 'data', 'data'),
                               install_root=args.scr)
        data = st.read_name(args.name)
    a = anim.parse(data)
    prgb = player_colors.PLAYER_COLORS[(args.player - 1) % 8][1]
    fw, fh, rgba, used = composite_frame(data, a, args.frame, prgb,
                                         team=not args.no_team,
                                         emissive=not args.no_emissive)
    png.write_rgba(args.o, fw, fh, rgba)
    print('composite frame %d: %dx%d player %d layers=%s -> %s'
          % (args.frame, fw, fh, args.player, sorted(used), args.o))
