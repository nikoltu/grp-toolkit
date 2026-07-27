"""Oracle for the GRP writer (tools/grp.py) - the graphics-mod export side.

The guarantee is a PIXEL round-trip: for every real GRP and for a battery of
synthetic edge cases, decode(encode(frames)) reproduces the exact index grids.
Byte identity against Blizzard's files is NOT claimed (the RLE run/literal split
is a compression choice; the game reads any valid encoding) - but the test
REPORTS the byte-match/size ratio on real files so the gap is measured.

Synthetic cases exercise the parts a real sprite may not: a fully transparent
row, a run longer than one 0x3F chunk, a transparent gap longer than 0x7F, a
pure-literal row, and single-pixel widths.

    py test_grp_writer.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import BW, need, report      # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import mpq                               # noqa: E402
import grp                               # noqa: E402


def _synthetic():
    """A GRP with deliberately awkward frames. Returns (Grp, frames-as-tuples)."""
    frames = []
    # 1. fully transparent 5x3
    frames.append((0, 0, 5, 3, [0] * 15))
    # 2. long single-colour run (200 wide -> exceeds 0x3F, forces >1 run op)
    frames.append((1, 2, 200, 1, [7] * 200))
    # 3. long transparent gap (240 -> exceeds 0x7F skip) with pixels at the ends
    row = [9] + [0] * 240 + [9]                  # width 242 (<=255, GRP u8 limit)
    frames.append((3, 4, len(row), 1, row))
    # 4. pure literal (no two adjacent equal, none transparent)
    frames.append((0, 0, 8, 1, [1, 2, 3, 4, 5, 6, 8, 10]))
    # 5. single-pixel width, mixed transparent/opaque down a column
    frames.append((0, 0, 1, 6, [0, 4, 0, 4, 4, 0]))
    # 6. run exactly 0x3F then one more (boundary)
    frames.append((0, 0, 0x40, 1, [11] * 0x40))
    return grp.Grp(64, 64, [grp.GrpFrame(*f) for f in frames]), frames


def main():
    ok = total = 0
    bad = []

    # ---- synthetic edge cases (no install needed) ----
    g, _ = _synthetic()
    data = grp.write(g)
    g2 = grp.read(data)
    for i, (a, b) in enumerate(zip(g.frames, g2.frames)):
        total += 1
        if a.w == b.w and a.h == b.h and a.pixels == b.pixels:
            ok += 1
        else:
            bad.append('synthetic frame %d differs' % i)

    # ---- real GRPs: pixel round-trip + size report ----
    if os.path.exists(BW):
        ch = mpq.MpqChain(BW)
        sizes = []
        for name in ('unit\\wirefram\\wirefram.grp',
                     'unit\\cmdbtns\\cmdicons.grp',
                     'unit\\thingy\\tbunker.grp'):
            try:
                raw = ch.read(name)
            except Exception:                     # noqa: BLE001
                continue
            total += 1
            g = grp.read(raw)
            re = grp.write(g)
            g2 = grp.read(re)
            px_ok = all(a.pixels == b.pixels and a.w == b.w and a.h == b.h
                        for a, b in zip(g.frames, g2.frames)) \
                and len(g.frames) == len(g2.frames)
            if px_ok:
                ok += 1
            else:
                bad.append('%s pixel round-trip failed' % name)
            sizes.append('%s %d frames %.0f%% of orig'
                         % (name.split('\\')[-1], len(g.frames),
                            100.0 * len(re) / len(raw)))
        extra = '(' + '; '.join(sizes) + ')' if sizes else '(no real GRPs read)'
    else:
        extra = '(synthetic only; BW install absent)'

    if bad:
        extra = '(bad=%s)' % bad[:3]
    rc = report('grp: writer pixel round-trip', ok, total, extra)
    sys.exit(rc)


if __name__ == '__main__':
    main()
