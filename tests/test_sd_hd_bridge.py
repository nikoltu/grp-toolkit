"""Oracle for the SD<->HD asset bridge (tools/sd_hd_bridge.py).

The HD engine renders each unit from two unrelated asset pipelines (palette GRP
and DXT .anim). This proves they are frame-aligned so the engine can pair SD
frame i with HD frame i without a remap:

  1. ADDRESSING. A unit's HD anim is `anim/main_<imageid>.anim`, the image id its
     SD graphics chain already resolves - one id names both assets.
  2. FRAME 1:1. Every unit that resolves both an SD GRP and an HD main_ anim has
     EQUAL frame counts (0 mismatches) - the core bridge claim.
  3. KNOWN UNITS. Marine / SCV / Zealot / Probe each resolve to their real GRP,
     the expected HD anim, matching frames, HD tier.
  4. HONEST GAPS. Units with no main_ HD anim are reported (status no-hd), never
     silently matched; the frame-match claim is only over the resolved set.

    py test_sd_hd_bridge.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import BW, SCR, CASC_DATA, need, report      # noqa: E402
import mpq                                                # noqa: E402
import casc                                               # noqa: E402
import tbl                                                # noqa: E402
import sd_hd_bridge as B                                  # noqa: E402


def main():
    need(BW, 'Brood War install')
    need(SCR, 'SC:R install')
    ch = mpq.MpqChain(BW)
    st = casc.NamedStorage(CASC_DATA, install_root=SCR)
    it = tbl.load(ch.read('arr\\images.tbl'))
    images_tbl = [it.text(i) for i in range(len(it))]

    ok = total = 0
    bad = []

    bridges, summ = B.bridge_corpus(ch, st, images_tbl)

    # 1. addressing: every bridge's anim name is main_<imageid>
    total += 1
    addr_ok = all(b.anim_name == B.hd_anim_name(b.image_id)
                  for b in bridges if b.anim_name)
    if addr_ok:
        ok += 1
    else:
        bad.append('addressing')

    # 2. frame 1:1 over the resolved set, 0 mismatches
    total += 1
    if summ['frame-mismatch'] == 0 and summ['ok'] > 150:
        ok += 1
    else:
        bad.append('ok %d mismatch %d' % (summ['ok'], summ['frame-mismatch']))

    # 3. known units
    total += 1
    dats = B._chain_dats(ch)
    expect = {0: ('terran\\marine.grp', 'anim/main_239.anim'),
              7: ('terran\\SCV.grp', 'anim/main_247.anim'),
              65: ('protoss\\zealot.grp', 'anim/main_151.anim'),
              64: ('protoss\\probe.grp', 'anim/main_137.anim')}
    known_ok = True
    for uid, (grpn, animn) in expect.items():
        b = B.bridge_unit(uid, dats, images_tbl, ch, st)
        if not (b.grp_name == grpn and b.anim_name == animn
                and b.frames_match and b.hd_tier == 'HD'):
            known_ok = False
            bad.append('u%d %s/%s %s' % (uid, b.grp_name, b.anim_name, b.status))
    if known_ok:
        ok += 1

    # 4. gaps reported, not silently matched: no bridge in state ok has unequal frames
    total += 1
    if all(b.sd_frames == b.hd_frames for b in bridges if b.status == 'ok') \
            and summ['no-hd'] >= 1:
        ok += 1
    else:
        bad.append('gap handling')

    rc = report('sd_hd: SD<->HD frame bridge', ok, total,
                '(%d units: %d ok 1:1, %d no-hd; mismatch %d; bad=%s)'
                % (len(bridges), summ['ok'], summ['no-hd'],
                   summ['frame-mismatch'], bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
