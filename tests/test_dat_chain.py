"""Oracle for the graphics DAT chain (flingy.dat, sprites.dat, images.dat).

The chain is what a unit's picture is made of:

    units.dat[unit].flingy -> flingy.dat.sprite -> sprites.dat.image
        -> images.dat.grp_file -> images.tbl  (the .grp filename)

Three SoA layouts are added at once, so a single-field sanity check isn't
enough. This verifies them the strongest way there is - END TO END:

  1. LAYOUT closes. Each file's arrays sum to its exact size (flingy 3135,
     sprites 3229, images 37962). A wrong width/count anywhere misses the total.

  2. CHAIN resolves. Following all four hops for known units lands on the real
     .grp name in images.tbl (Marine -> terran\\marine.grp, SCV -> terran\\SCV.grp,
     Zealot -> protoss\\zealot.grp, Zergling -> zerg\\zergling.grp). No single
     field offset could pass this by luck - every hop must be right, and it also
     pins the 1-based images.tbl indexing.

  3. ROUND-TRIP. Parse -> to_bytes() is byte-identical for all three files, and a
     single grp_file edit changes only that image's 4 bytes (retarget a unit's
     sprite without corrupting the rest).

    py test_dat_chain.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import BW, need, report      # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import mpq                               # noqa: E402
import dat                               # noqa: E402
import tbl                               # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    units = dat.load_from_chain(ch, 'units.dat')
    flingy = dat.load_from_chain(ch, 'flingy.dat')
    sprites = dat.load_from_chain(ch, 'sprites.dat')
    images = dat.load_from_chain(ch, 'images.dat')
    itbl = tbl.load(ch.read('arr\\images.tbl'))
    names = [itbl.text(i) for i in range(len(itbl))]

    ok = total = 0
    bad = []

    # 1. layout closure
    total += 1
    closes = all(sum(f.size for f in d.fields) == len(d.data)
                 for d in (flingy, sprites, images))
    if closes:
        ok += 1
    else:
        bad.append('layout does not close')

    # 2. chain resolves for known units (case-insensitive, backslash-normalised)
    total += 1
    want = {0: 'terran/marine.grp', 7: 'terran/scv.grp',
            65: 'protoss/zealot.grp', 37: 'zerg/zergling.grp'}
    misses = []
    for uid, exp in want.items():
        c = dat.graphics_chain(uid, units, flingy, sprites, images, names)
        got = (c['grp_name'] or '').replace('\\', '/').lower()
        if got != exp:
            misses.append('%d: %r != %r' % (uid, got, exp))
    if not misses:
        ok += 1
    else:
        bad.append('chain: %s' % misses[:2])

    # 3a. round-trip byte-identical
    total += 1
    rt = all(d.to_bytes() == ch.read('arr\\' + d.kind)
             for d in (flingy, sprites, images))
    if rt:
        ok += 1
    else:
        bad.append('round-trip differs')

    # 3b. a single grp_file edit touches only that image's 4 bytes
    total += 1
    src = ch.read('arr\\images.dat')
    im2 = dat.load('images.dat', src)
    marine_img = dat.graphics_chain(0, units, flingy, sprites, images)['image']
    im2.set('grp_file', marine_img, 300)
    a, b = bytes(src), im2.to_bytes()
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    off = im2.field('grp_file').offset + marine_img * 4
    if im2.get('grp_file', marine_img) == 300 \
            and diff and all(off <= i < off + 4 for i in diff):
        ok += 1
    else:
        bad.append('edit spread: %d bytes' % len(diff))

    rc = report('dat: graphics chain (flingy/sprites/images)', ok, total,
                '(%d images.tbl names; bad=%s)'
                % (len(names), bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
