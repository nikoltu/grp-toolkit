#!/usr/bin/env python3
"""SD <-> HD asset bridge: pair a unit's classic SD GRP with its SC:R HD `.anim`.

The OpenBW HD engine has to render the SAME unit from two completely different
asset pipelines - the 1998 palette-indexed GRP and the Remastered DXT `.anim`.
This tool is the oracle that proves the two are frame-aligned, and hands the
engine both handles + the mapping so it can pair SD frame i with HD frame i.

MEASURED (see tests/test_sd_hd_bridge.py, run against V's BW + SC:R installs):

  * Addressing. A unit's HD anim is `anim/main_%03d.anim` where the index is the
    unit's images.dat image id - the SAME id the SD graphics chain resolves
    (units.dat.flingy -> flingy.sprite -> sprites.image). So one image id names
    both assets; no separate HD lookup table is needed.
  * Frame correspondence is 1:1. Over every unit whose chain resolves to both an
    SD GRP and an `anim/main_*.anim`, the GRP frame count EQUALS the HD anim
    entry's frame count - 214/214 units, 0 mismatches. Frame i is the same
    logical frame in both tiers, so the engine can swap art without remapping
    animation indices (iscript playfram N addresses frame N in either tier).
  * Scale is the anim tier (1=SD, 2=HD2, 4=HD), nominally 4x for full HD. Per
    frame the width ratio is only ~4x on AVERAGE (measured mean ~4.2, spread
    3.1-8.4): the SD RLE and the HD atlas each trim transparent margins
    independently, so a frame's tight w/h differ between tiers. This tool
    therefore does NOT claim a clean per-pixel placement multiplier - it reports
    both coordinate sets and the tier, and the 1:1 frame index is the reliable
    bridge, not a coordinate transform.
  * 14 units resolve an SD GRP but no `main_` HD anim (hero/alt image ids like
    img246 marine, tileset doodads under thingy\\, neutral resource chunks). SC:R
    renders those through a different anim, so they are reported as "no direct
    HD main_ anim", never silently matched.

No third-party libraries. Reuses tools/dat.py (chain), tools/grp.py (SD),
tools/anim.py (HD structure).
"""
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dat
import grp
import anim


def hd_anim_name(image_id):
    """The full-HD anim name for an images.dat image id (the measured convention;
    HD2 tier lives at 'HD2/' + this)."""
    return 'anim/main_%03d.anim' % image_id


@dataclass
class Bridge:
    unit_id: int
    image_id: int
    grp_name: str = None
    anim_name: str = None
    sd_frames: int = 0
    hd_frames: int = 0
    sd_canvas: tuple = (0, 0)
    hd_size: tuple = (0, 0)                 # anim entry w,h
    hd_tier: str = ''
    status: str = ''                       # 'ok' | 'frame-mismatch' | 'no-sd' | 'no-hd' | 'no-grp'

    @property
    def frames_match(self):
        return self.status == 'ok'

    @property
    def scale(self):
        """Nominal linear scale from the anim tier (SD=1, HD2=2, HD=4)."""
        return {'SD': 1, 'HD2': 2, 'HD': 4}.get(self.hd_tier, 0)


def _chain_dats(mpq_chain):
    """Load the four graphics-chain DATs + images.tbl from a BW MPQ chain."""
    return {
        'units': dat.load_from_chain(mpq_chain, 'units.dat'),
        'flingy': dat.load_from_chain(mpq_chain, 'flingy.dat'),
        'sprites': dat.load_from_chain(mpq_chain, 'sprites.dat'),
        'images': dat.load_from_chain(mpq_chain, 'images.dat'),
    }


def bridge_unit(unit_id, dats, images_tbl, mpq_chain, casc_storage):
    """Resolve and compare one unit's SD GRP and HD anim.

    dats: dict from _chain_dats. images_tbl: list[str] (tbl names, 1-based grp id).
    mpq_chain: reads the SD GRP. casc_storage: casc.NamedStorage for the HD anim.
    """
    c = dat.graphics_chain(unit_id, dats['units'], dats['flingy'],
                           dats['sprites'], dats['images'], images_tbl)
    b = Bridge(unit_id=unit_id, image_id=c['image'], grp_name=c['grp_name'])
    if not c['grp_name']:
        b.status = 'no-grp'
        return b
    try:
        g = grp.read(mpq_chain.read('unit\\' + c['grp_name'].replace('/', '\\')))
        b.sd_frames = len(g.frames)
        b.sd_canvas = (g.canvas_w, g.canvas_h)
    except Exception:                                       # noqa: BLE001
        b.status = 'no-sd'
        return b
    b.anim_name = hd_anim_name(c['image'])
    try:
        A = anim.parse(casc_storage.read_name(b.anim_name))
    except Exception:                                       # noqa: BLE001
        b.status = 'no-hd'
        return b
    e = A.entries[0] if A.entries else None
    b.hd_frames = e.frame_count if e else 0
    b.hd_size = (e.w, e.h) if e else (0, 0)
    b.hd_tier = A.tier
    b.status = 'ok' if b.sd_frames == b.hd_frames else 'frame-mismatch'
    return b


def bridge_corpus(mpq_chain, casc_storage, images_tbl=None, n_units=228):
    """Bridge every unit id. Returns (bridges, summary)."""
    dats = _chain_dats(mpq_chain)
    if images_tbl is None:
        import tbl as _tbl
        it = _tbl.load(mpq_chain.read('arr\\images.tbl'))
        images_tbl = [it.text(i) for i in range(len(it))]
    bridges = []
    summ = {'ok': 0, 'frame-mismatch': 0, 'no-hd': 0, 'no-sd': 0, 'no-grp': 0}
    for uid in range(n_units):
        try:
            b = bridge_unit(uid, dats, images_tbl, mpq_chain, casc_storage)
        except Exception:                                   # noqa: BLE001
            continue
        bridges.append(b)
        summ[b.status] = summ.get(b.status, 0) + 1
    return bridges, summ


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='SD GRP <-> HD anim bridge.')
    ap.add_argument('bw', nargs='?', default=r'C:\Git\Starcraft BroodWar  v1.1.61')
    ap.add_argument('scr', nargs='?', default=r'C:\Git\StarCraft Remastered')
    ap.add_argument('--unit', type=int, help='one unit id (else whole corpus)')
    args = ap.parse_args()
    import mpq
    import casc
    import tbl
    ch = mpq.MpqChain(args.bw)
    st = casc.NamedStorage(os.path.join(args.scr, 'data', 'data'),
                           install_root=args.scr)
    it = tbl.load(ch.read('arr\\images.tbl'))
    images_tbl = [it.text(i) for i in range(len(it))]
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    if args.unit is not None:
        dats = _chain_dats(ch)
        b = bridge_unit(args.unit, dats, images_tbl, ch, st)
        print('%s (u%d)  img %d  [%s]' % (stat.text(args.unit), b.unit_id,
                                          b.image_id, b.status))
        print('  SD  %s: %d frames, canvas %dx%d' %
              (b.grp_name, b.sd_frames, *b.sd_canvas))
        print('  HD  %s: %d frames, %dx%d, tier %s (x%d)' %
              (b.anim_name, b.hd_frames, b.hd_size[0], b.hd_size[1],
               b.hd_tier, b.scale))
    else:
        bridges, summ = bridge_corpus(ch, st, images_tbl)
        print('SD<->HD bridge over %d units:' % len(bridges))
        print('  ok(1:1 frames) %d | frame-mismatch %d | no-hd %d | no-sd %d | no-grp %d'
              % (summ['ok'], summ['frame-mismatch'], summ['no-hd'],
                 summ['no-sd'], summ['no-grp']))
        for b in bridges:
            if b.status == 'frame-mismatch':
                print('  MISMATCH u%d %s sd=%d hd=%d'
                      % (b.unit_id, b.grp_name, b.sd_frames, b.hd_frames))
