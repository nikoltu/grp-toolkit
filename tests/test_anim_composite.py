"""Oracle for the HD layer composite (tools/anim_composite.py).

The composite's SHADER RECIPE (which layers, what order) is a documented
reference until V supplies the engine's exact blend - but every OPERATION it is
built from is proven here, so locking the recipe later is a pure diff:

  1. src_over - integer straight-alpha compositing, on hand-computed pixels.
  2. add_clamp_rgb - additive emissive, clamped, alpha-gated, hand-computed.
  3. DIFFUSE ANCHOR - a diffuse-only composite of a real frame is byte-identical
     to anim_render's diffuse crop (the composite adds nothing when team+emissive
     are off).
  4. TEAM ANCHOR - on a real frame, every pixel where the diffuse is transparent
     but the teamcolor mask is set equals player_colors.apply_team_color exactly
     (src_over of the tint over nothing IS the tint) - and at least one such
     pixel exists, so team colour genuinely contributes.
  5. DETERMINISM - compositing the same frame twice is byte-identical.

Steps 1-2 need no install; 3-5 use V's SC:R.

    py test_anim_composite.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import SCR, CASC_DATA, need, report          # noqa: E402
import anim_composite as AC                               # noqa: E402
import player_colors                                      # noqa: E402


def main():
    ok = total = 0
    bad = []

    # 1. src_over on hand-computed pixels
    total += 1
    #  a) opaque top over anything -> top
    a = AC.src_over(bytes([10, 20, 30, 255]), bytes([99, 99, 99, 255]))
    #  b) transparent top over bottom -> bottom
    b = AC.src_over(bytes([10, 20, 30, 0]), bytes([99, 88, 77, 255]))
    #  c) half red over black: oa=255, r=round(255*128/255)=128 -> (128,0,0,255)
    c = AC.src_over(bytes([255, 0, 0, 128]), bytes([0, 0, 0, 255]))
    if (a == bytes([10, 20, 30, 255]) and b == bytes([99, 88, 77, 255])
            and c == bytes([128, 0, 0, 255])):
        ok += 1
    else:
        bad.append('src_over %s' % list(c))

    # 2. add_clamp_rgb: overflow clamps; small add; alpha-0 add is a no-op;
    #    half-alpha add contributes half
    total += 1
    over = AC.add_clamp_rgb(bytes([200, 10, 0, 255]), bytes([100, 5, 0, 255]))
    zero = AC.add_clamp_rgb(bytes([50, 60, 70, 255]), bytes([255, 255, 255, 0]))
    half = AC.add_clamp_rgb(bytes([0, 0, 0, 255]), bytes([100, 100, 100, 128]))
    if (over == bytes([255, 15, 0, 255]) and zero == bytes([50, 60, 70, 255])
            and half == bytes([50, 50, 50, 255])):     # 100*128//255 = 50
        ok += 1
    else:
        bad.append('add %s %s %s' % (list(over), list(zero), list(half)))

    # ---- real-frame anchors ----
    if os.path.exists(SCR):
        import casc
        import anim
        import anim_render
        import dxt
        st = casc.NamedStorage(CASC_DATA, install_root=SCR)
        data = st.read_name('anim/main_239.anim')       # marine HD, all layers in-file
        A = anim.parse(data)
        recs = anim_render.frame_records(data, A)
        ax, ay, xo, yo, fw, fh = recs[0]
        di = A.layers.index('diffuse')
        aw, ah, _, diff_atlas = dxt.decode_dds(data, A.texrefs[di].dds_offset)
        diff_crop = anim_render.crop(aw, ah, diff_atlas, ax, ay, fw, fh)

        # 3. diffuse anchor
        total += 1
        _, _, only, used = AC.composite_frame(data, A, 0, team=False, emissive=False)
        if only == diff_crop and used == {'diffuse'}:
            ok += 1
        else:
            bad.append('diffuse anchor')

        # 4. team anchor
        total += 1
        ti = A.layers.index('teamcolor')
        _, _, _, tc_atlas = dxt.decode_dds(data, A.texrefs[ti].dds_offset)
        mask_crop = anim_render.crop(aw, ah, tc_atlas, ax, ay, fw, fh)
        prgb = player_colors.PLAYER_COLORS[0][1]        # Red
        tint = player_colors.apply_team_color(mask_crop, prgb)
        _, _, comp, cused = AC.composite_frame(data, A, 0, prgb,
                                               team=True, emissive=False)
        team_ok = True
        contributed = 0
        for i in range(0, len(diff_crop), 4):
            if diff_crop[i + 3] == 0 and mask_crop[i] > 0:   # transparent diffuse, masked
                contributed += 1
                if comp[i:i + 4] != tint[i:i + 4]:
                    team_ok = False
                    break
        if team_ok and contributed > 0 and 'teamcolor' in cused:
            ok += 1
        else:
            bad.append('team anchor (contrib %d)' % contributed)

        # 5. determinism
        total += 1
        _, _, c1, _ = AC.composite_frame(data, A, 3, prgb)
        _, _, c2, _ = AC.composite_frame(data, A, 3, prgb)
        if c1 == c2:
            ok += 1
        else:
            bad.append('nondeterministic')
    else:
        print('SKIP: SC:R real-frame anchors (install not found)')

    rc = report('anim_composite: layer composite', ok, total,
                '(ops + real-frame anchors; bad=%s)' % (bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
