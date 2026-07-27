#!/usr/bin/env python3
"""Player-colour reference for SC:R HD team colouring.

MEASURED: the `teamcolor` layer of an HD `.anim` is a GRAYSCALE MASK (every
texel r==g==b; ~white where the player colour fully applies, black/transparent
where it does not) - the blend weight the engine's shader uses to tint a unit
with its owner's colour. So a byte-exact player-colour reference has two exact
parts and one input:

  * exact: the teamcolor mask decode (tools/dxt.py, byte-exact).
  * exact: the tint formula below - out = playerColour * (mask/255), the mask
    value carried as alpha, rounded half-up.
  * input: the player-colour RGB values. PLAYER_COLORS is the well-documented
    classic BW set (SC:R adds more); pass your own to match the engine exactly -
    the byte-exact claim is about the mask+formula, not these numbers.

For each player this yields the pure team-colour contribution the engine adds
over the diffuse layer; the engine diffs its player-colour shader output against
these. NOTE (see tools/anim.py TexRef): the teamcolor layer is often refId-shared
- if this file's teamcolor has ddsOffset 0 the mask lives in another .anim.
"""

# (name, (r, g, b)) - the standard StarCraft player colours P1..P8.
PLAYER_COLORS = [
    ('Red',    (244, 4, 4)),
    ('Blue',   (12, 72, 204)),
    ('Teal',   (44, 180, 148)),
    ('Purple', (136, 64, 156)),
    ('Orange', (248, 140, 20)),
    ('Brown',  (112, 48, 20)),
    ('White',  (204, 224, 208)),
    ('Yellow', (252, 252, 56)),
]


def apply_team_color(mask_rgba, player_rgb):
    """Tint a decoded teamcolor mask by one player colour.

    mask_rgba: RGBA bytes of the teamcolor layer (grayscale; the R channel is the
    weight). Returns RGBA bytes: player_rgb * (mask/255), with the mask value as
    alpha. Round half up to match the browser/engine's Math.round convention."""
    pr, pg, pb = player_rgb
    out = bytearray(len(mask_rgba))
    for i in range(0, len(mask_rgba), 4):
        m = mask_rgba[i]                     # grayscale mask value (r==g==b)
        out[i] = int(pr * m / 255 + 0.5)
        out[i + 1] = int(pg * m / 255 + 0.5)
        out[i + 2] = int(pb * m / 255 + 0.5)
        out[i + 3] = m                       # weight carried as alpha
    return bytes(out)


if __name__ == '__main__':
    import argparse
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import anim
    import dxt
    import png

    ap = argparse.ArgumentParser(
        description='Dump per-player team-colour reference for a .anim.')
    ap.add_argument('scr', nargs='?', default=r'C:\Git\StarCraft Remastered')
    ap.add_argument('name', nargs='?', help='anim name (CASC)')
    ap.add_argument('--file', help='raw .anim on disk')
    ap.add_argument('--outdir', default='.', help='where to write P1..P8 PNGs')
    args = ap.parse_args()

    if args.file:
        data = open(args.file, 'rb').read()
    else:
        import casc
        st = casc.NamedStorage(os.path.join(args.scr, 'data', 'data'),
                               install_root=args.scr)
        data = st.read_name(args.name)
    a = anim.parse(data)
    if 'teamcolor' not in a.layers:
        raise SystemExit('no teamcolor layer')
    tr = a.texrefs[a.layers.index('teamcolor')]
    if not tr.dds_offset:
        raise SystemExit('teamcolor is refId-shared here (mask lives in another '
                         '.anim - see tools/anim.py TexRef)')
    w, h, fourcc, mask = dxt.decode_dds(data, tr.dds_offset)
    os.makedirs(args.outdir, exist_ok=True)
    for i, (name, rgb) in enumerate(PLAYER_COLORS, 1):
        tint = apply_team_color(mask, rgb)
        out = os.path.join(args.outdir, 'P%d_%s.png' % (i, name))
        png.write_rgba(out, w, h, tint)
    print('teamcolor mask %dx%d %s -> %d player references in %s'
          % (w, h, fourcc, len(PLAYER_COLORS), args.outdir))
