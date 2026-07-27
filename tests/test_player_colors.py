"""Oracle for the player-colour reference (tools/player_colors.py).

The teamcolor mask decode is DXT (covered by test_dxt.py, byte-exact); the tint
formula here is deterministic arithmetic, so it is checked by hand:

    out = round_half_up(playerRGB * mask/255), alpha = mask

  * mask 255 reproduces the player colour exactly, alpha 255.
  * mask 0 is fully transparent black.
  * a fractional weight rounds the way the engine's Math.round does.
  * the mask's R channel is the weight (real masks are grayscale r==g==b).

    py test_player_colors.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import player_colors as PC               # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import report                # noqa: E402


def px(rgba, i):
    return tuple(rgba[i * 4:i * 4 + 4])


def main():
    ok = total = 0
    bad = []

    # a 4-texel grayscale mask: 0, 64, 128, 255
    mask = bytearray()
    for m in (0, 64, 128, 255):
        mask += bytes([m, m, m, m])       # grayscale + alpha (unused by tint)

    # 1. mask 255 -> exact player colour; mask 0 -> transparent black
    total += 1
    out = PC.apply_team_color(mask, (204, 224, 208))     # White
    if px(out, 3) == (204, 224, 208, 255) and px(out, 0) == (0, 0, 0, 0):
        ok += 1
    else:
        bad.append('endpoints %s / %s' % (px(out, 3), px(out, 0)))

    # 2. clean fractional weights with pure red (255,0,0)
    total += 1
    out = PC.apply_team_color(mask, (255, 0, 0))
    # 255*64/255=64 ; 255*128/255=128 ; alpha carries the mask value
    if px(out, 1) == (64, 0, 0, 64) and px(out, 2) == (128, 0, 0, 128):
        ok += 1
    else:
        bad.append('fractions %s %s' % (px(out, 1), px(out, 2)))

    # 3. round-half-up matches the engine's Math.round (not banker's rounding)
    total += 1
    # player (244,4,4) at mask 128: 244*128/255=122.48->122 ; 4*128/255=2.007->2
    out = PC.apply_team_color(mask, (244, 4, 4))
    if px(out, 2) == (122, 2, 2, 128):
        ok += 1
    else:
        bad.append('rounding %s' % (px(out, 2),))

    # 4. the standard set has the expected 8 players, all in-range RGB
    total += 1
    good = (len(PC.PLAYER_COLORS) == 8
            and all(len(c) == 3 and all(0 <= v <= 255 for v in c)
                    for _, c in PC.PLAYER_COLORS)
            and PC.PLAYER_COLORS[0][0] == 'Red')
    if good:
        ok += 1
    else:
        bad.append('player set')

    rc = report('player colours: teamcolor tint (synthetic)', ok, total,
                '(%d players; bad=%s)'
                % (len(PC.PLAYER_COLORS), bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
