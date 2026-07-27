#!/usr/bin/env python3
"""Golden-frame regression harness + determinism checker for the decoders.

Two oracle mechanisms an engine port (or this toolkit) uses to stay honest as the
code changes:

  * GOLDEN. Decode a declared list of assets to their final bytes, hash each, and
    write a manifest {label: sha256}. Re-run later and diff: any decoder change
    that alters a single output pixel shows up as a `changed` line, a removed
    asset as `missing`, a new one as `new`. This is the regression net - it turns
    "did my refactor change any output?" into a byte diff instead of eyeballing.
  * DETERMINISM. Decode each target N times in one run and assert every run is
    byte-identical. A decoder that leaks dict/set ordering, uninitialised buffer
    bytes, or time/random into its output fails here even when it matches its own
    golden (which was captured from the same nondeterministic run). The engine
    needs this because a desync between two machines is exactly a decoder that is
    not a pure function of its input.

The two share one DECODERS registry so every target is exercised the same way by
both. Outputs are the FINAL decoded bytes (index grids / RGBA / composited
frames), not container bytes - the point is to pin the decode, not the file.

No third-party libraries. Reuses grp/dxt/anim/anim_composite/tbl.
"""
import os
import sys
import json
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _sha(b):
    return hashlib.sha256(b).hexdigest()


# ---- decoders: each returns the FINAL decoded bytes for a target ----
def dec_grp(t, ctx):
    import grp
    g = grp.read(ctx['mpq'].read(t['name']))
    out = bytearray([g.canvas_w & 255, g.canvas_w >> 8, g.canvas_h & 255, g.canvas_h >> 8])
    for f in g.frames:
        out += bytes([f.x, f.y, f.w, f.h])
        out += bytes(f.pixels)
    return bytes(out)


def dec_anim_layer(t, ctx):
    import anim
    import anim_render
    data = ctx['casc'].read_name(t['name'])
    a = anim.parse(data)
    _, _, _, rgba = anim_render.decode_layer_atlas(data, a, t.get('layer', 'diffuse'))
    return rgba


def dec_composite(t, ctx):
    import anim
    import anim_composite
    import player_colors
    data = ctx['casc'].read_name(t['name'])
    a = anim.parse(data)
    prgb = player_colors.PLAYER_COLORS[(t.get('player', 1) - 1) % 8][1]
    _, _, rgba, _ = anim_composite.composite_frame(data, a, t.get('frame', 0), prgb)
    return rgba


def dec_palette_tbl(t, ctx):
    import tbl
    b = ctx['mpq'].read(t['name'])
    it = tbl.load(b)
    return ('\n'.join(it.text(i) for i in range(len(it)))).encode('utf-8')


DECODERS = {'grp': dec_grp, 'anim_layer': dec_anim_layer,
            'composite': dec_composite, 'tbl': dec_palette_tbl}


def label(t):
    extra = ''
    if t['kind'] == 'anim_layer':
        extra = ':' + t.get('layer', 'diffuse')
    elif t['kind'] == 'composite':
        extra = ':f%d:p%d' % (t.get('frame', 0), t.get('player', 1))
    return '%s:%s%s' % (t['kind'], t['name'], extra)


def decode_one(t, ctx):
    return DECODERS[t['kind']](t, ctx)


def manifest(targets, ctx):
    """{label: sha256} over targets. Missing/erroring targets get an 'ERR:...'
    value so a broken asset is recorded, not silently dropped."""
    out = {}
    for t in targets:
        try:
            out[label(t)] = _sha(decode_one(t, ctx))
        except Exception as ex:                          # noqa: BLE001
            out[label(t)] = 'ERR:%s' % type(ex).__name__
    return out


def check_golden(targets, golden, ctx):
    """Compare a fresh manifest to a stored golden dict. Returns
    (results, n_changed) where results is [(label, status)] with status in
    match/changed/missing(new)/gone."""
    cur = manifest(targets, ctx)
    results = []
    changed = 0
    for k, v in cur.items():
        if k not in golden:
            results.append((k, 'new'))
            changed += 1
        elif golden[k] != v:
            results.append((k, 'changed'))
            changed += 1
        else:
            results.append((k, 'match'))
    for k in golden:
        if k not in cur:
            results.append((k, 'gone'))
            changed += 1
    return results, changed


def check_determinism(targets, ctx, runs=3):
    """Decode each target `runs` times; return [(label, stable_bool)]."""
    out = []
    for t in targets:
        lb = label(t)
        try:
            hashes = {_sha(decode_one(t, ctx)) for _ in range(runs)}
            out.append((lb, len(hashes) == 1))
        except Exception:                                # noqa: BLE001
            out.append((lb, None))                       # errored, not a stability verdict
    return out


def default_targets():
    """A representative, deterministic target set spanning the pixel decoders."""
    return [
        {'kind': 'grp', 'name': 'unit\\terran\\marine.grp'},
        {'kind': 'grp', 'name': 'unit\\protoss\\zealot.grp'},
        {'kind': 'grp', 'name': 'unit\\zerg\\zergling.grp'},
        {'kind': 'tbl', 'name': 'rez\\stat_txt.tbl'},
        {'kind': 'anim_layer', 'name': 'anim/main_239.anim', 'layer': 'diffuse'},
        {'kind': 'anim_layer', 'name': 'anim/main_239.anim', 'layer': 'teamcolor'},
        {'kind': 'composite', 'name': 'anim/main_239.anim', 'frame': 0, 'player': 1},
    ]


def make_ctx(bw=None, scr=None):
    ctx = {}
    if bw:
        import mpq
        ctx['mpq'] = mpq.MpqChain(bw)
    if scr:
        import casc
        ctx['casc'] = casc.NamedStorage(os.path.join(scr, 'data', 'data'),
                                        install_root=scr)
    return ctx


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Golden regression + determinism harness.')
    ap.add_argument('verb', choices=['build', 'check', 'determinism'])
    ap.add_argument('--bw', default=r'C:\Git\Starcraft BroodWar  v1.1.61')
    ap.add_argument('--scr', default=r'C:\Git\StarCraft Remastered')
    ap.add_argument('--golden', default='golden.json', help='manifest path')
    args = ap.parse_args()
    ctx = make_ctx(args.bw, args.scr)
    targets = default_targets()
    if args.verb == 'build':
        m = manifest(targets, ctx)
        json.dump(m, open(args.golden, 'w'), indent=2, sort_keys=True)
        print('wrote %d target hashes -> %s' % (len(m), args.golden))
        for k, v in sorted(m.items()):
            print('  %-52s %s' % (k, v[:16]))
    elif args.verb == 'check':
        golden = json.load(open(args.golden))
        results, changed = check_golden(targets, golden, ctx)
        for k, s in sorted(results):
            if s != 'match':
                print('  %-8s %s' % (s.upper(), k))
        print('%d/%d match, %d changed vs %s'
              % (len(results) - changed, len(results), changed, args.golden))
        sys.exit(1 if changed else 0)
    else:
        res = check_determinism(targets, ctx)
        stable = sum(1 for _, s in res if s)
        for k, s in res:
            if s is not True:
                print('  %-8s %s' % ('UNSTABLE' if s is False else 'ERR', k))
        print('%d/%d targets deterministic' % (stable, len(res)))
        sys.exit(0 if stable == len(res) else 1)
