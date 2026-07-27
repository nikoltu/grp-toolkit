"""Proves the VP9 key-frame pixel decoder (stage 3b) matches libvpx.

Stage 3a proved the entropy decode is in sync (every tile ends on zero padding).
This stage turns the decoded coefficients into pixels - intra prediction,
dequantisation, the inverse DCT/ADST/WHT transforms and reconstruction - and the
only way to know those are right is to compare the reconstructed samples against
an independent decoder. That is the browser's own libvpx, through WebCodecs.

The loop filter (stage 8.8 of the spec) is a separate stage and is not applied
here, so this compares only the frames whose loop_filter_level is 0: for those,
libvpx's filter is a no-op and the comparison is exact. That is the same tactic
that validated VP8 intra before its loop filter existed. Of the 1073 portrait
key frames, 559 have lf==0 (18 profile-0 4:2:0, 541 profile-1 4:4:4 sRGB).

The comparison is plane-for-plane in the decoder's *native* buffer - I420 for
4:2:0, I444 for 4:4:4 - never RGB, so nothing is measured except the decode.

    py test_vp9_pixels.py --export      # writes tests/_vp9cmp/ for the browser

Then serve the repo root (py tests/_serve.py) and open tests/vp9-oracle.html.
Only a SHA-256 of the Python planes travels in the manifest; the page decodes
each key frame with libvpx, hashes its planes the same way and compares digests,
so the whole thing is a single keyframes.bin fetch (the preview proxy drops
per-file requests under load).
"""
import sys, os, json, argparse, hashlib
from common import CASC_DATA, need, report
import casc
import webm
import vp9
import vp9_pixels

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_vp9cmp')


def first_keyframe(blob):
    """Return (blk, lo, hi, header) for the file's first VP9 key frame, decided
    by the bitstream, or None."""
    try:
        d = webm.WebM(blob)
    except Exception:
        return None
    if d.codec != 'V_VP9' or not d.frames:
        return None
    off, size = d.frames[0][3], d.frames[0][4]
    blk = blob[off:off + size]
    subs = vp9.superframe_split(blk)
    if not subs:
        return None
    lo, hi = subs[0]
    h = vp9.VP9HeaderParser().parse(blk[lo:hi])
    if not h or not h.get('keyframe'):
        return None
    return blk, lo, hi, h


def planes_native(planes, h):
    """Tight plane bytes cropped to the display size, plane 0 then 1 then 2.
    Chroma dims follow the subsampling (4:2:0 -> half; 4:4:4 -> full)."""
    w, ht = h['width'], h['height']
    sx, sy = h.get('subsampling', (1, 1))
    cw, ch = (w + sx) >> sx, (ht + sy) >> sy
    dims = [(w, ht), (cw, ch), (cw, ch)]
    buf = bytearray()
    for p in range(3):
        pw, ph = dims[p]
        plane = planes[p]
        for j in range(ph):
            row = plane[j]
            buf += bytes(row[:pw])
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export', action='store_true',
                    help='write tests/_vp9cmp/ for the browser comparison')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--lf0-only', action='store_true',
                    help='only unfiltered frames (isolates reconstruction from '
                         'the loop filter)')
    a = ap.parse_args()

    need(CASC_DATA, 'SC:R CASC data')
    st = casc.NamedStorage(CASC_DATA)

    if a.export:
        os.makedirs(OUT, exist_ok=True)
        bundle = open(os.path.join(OUT, 'keyframes.bin'), 'wb')

    ok = total = 0
    manifest = []
    off = 0
    for name in sorted(n for n in st.root if '/portrait/' in n
                       and n.endswith('.webm')):
        try:
            blob = st.read_name(name)
        except Exception:
            continue
        fk = first_keyframe(blob)
        if fk is None:
            continue
        blk, lo, hi, h = fk
        if a.lf0_only and h['loop_filter_level'] != 0:
            continue
        total += 1
        try:
            hh, planes = vp9_pixels.decode_keyframe(blk, lo, hi)
            ok += 1
        except Exception as e:
            print('   %-40s %s' % (name.split('/')[-1], str(e)[:60]))
            continue
        if a.export:
            kf = blk[lo:hi]
            bundle.write(kf)
            manifest.append({'name': name.split('/')[-1], 'off': off,
                             'len': len(kf), 'w': h['width'], 'h': h['height'],
                             'profile': h['profile'],
                             'subx': h.get('subsampling', (1, 1))[0],
                             'suby': h.get('subsampling', (1, 1))[1],
                             'lf': h['loop_filter_level'],
                             'sha': hashlib.sha256(planes_native(planes, h)).hexdigest()})
            off += len(kf)
        if a.limit and total >= a.limit:
            break

    if a.export:
        bundle.close()
        json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'))
        p0 = sum(1 for m in manifest if m['profile'] == 0)
        nlf = sum(1 for m in manifest if m['lf'])
        print('   exported %d frames to tests/_vp9cmp/keyframes.bin '
              '(%d profile-0 4:2:0, %d profile-1 4:4:4, %d loop-filtered, %d bytes)'
              % (len(manifest), p0, len(manifest) - p0, nlf, off))
    sys.exit(report('vp9: keyframe pixels decode', ok, total,
                    '(reconstruction + loop filter ran; byte-exactness in browser)'))


if __name__ == '__main__':
    main()
