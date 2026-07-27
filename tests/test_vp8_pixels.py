"""Proves the VP8 intra decoder produces the same pixels as libvpx.

Two independent checks, and they are checking different things:

1. **Partition boundary** (runs here, no browser). Every residual partition
   must be consumed to exactly its declared length. The bool decoder is an
   arithmetic coder: mis-read one token and every later read is shifted, so
   the endpoint lands somewhere else. "Ended on the boundary" is therefore a
   statement about every token before it, not just the last one.

2. **Pixel identity** (needs a browser, see below). The frame is compared
   against the browser's own libvpx through WebCodecs, in the codec's native
   I420 — not RGB. That matters: an RGB comparison also measures colour
   conversion and chroma interpolation, which differ legitimately, and it
   turned a byte-exact decode into a 2.9-mean-error blur.

   With the loop filter (stage d) implemented, the comparison is exact over
   the **whole** corpus — all 633 keyframes, 490 of them loop-filtered — not
   just the 143 unfiltered frames it started with.

Run:

    py test_vp8_pixels.py            # check 1 over the whole corpus
    py test_vp8_pixels.py --export   # also write tests/_vp8cmp/ for check 2

Then, for check 2, serve the repo root and open tests/vp8-oracle.html; it
loops over the exported frames and prints one PASS/FAIL line per file plus a
total. The result as of 2026-07-22 is in tests/README.md.
"""
import sys, os, json, argparse, hashlib
from common import CASC_DATA, need, report
import casc
import webm
from vp8 import parse_frame_tag, parse_keyframe
from vp8_decode import decode_keyframe

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_vp8cmp')


def keyframe_of(blob):
    """The first keyframe, decided by the bitstream rather than the container.

    Files that wrap Block in a BlockGroup carry no keyframe flag at all, so
    trusting the container here would skip a quarter of the corpus."""
    try:
        d = webm.WebM(blob)
    except Exception:
        return None
    if d.codec != 'V_VP8':
        return None
    for _, _, _, off, size in d.frames:
        t = parse_frame_tag(blob[off:off + size])
        if t and t['keyframe']:
            return blob[off:off + size]
    return None


def planes_i420(fr):
    w, h = fr.width, fr.height
    cw, ch = (w + 1) // 2, (h + 1) // 2
    buf = bytearray()
    for pl, pw, ph in ((fr.y, w, h), (fr.u, cw, ch), (fr.v, cw, ch)):
        for j in range(ph):
            o = pl.row_off(j)
            buf += pl.buf[o:o + pw]
    return bytes(buf)


def sha(data):
    """SHA-256 of the I420 planes. The browser recomputes the same over its
    own libvpx output (crypto.subtle) and only the digests travel back — so the
    whole comparison is one fetch of the concatenated keyframes, not two large
    fetches per file through a flaky preview proxy."""
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export', action='store_true',
                    help='write tests/_vp8cmp/ for the browser comparison')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    need(CASC_DATA, 'SC:R CASC data')
    st = casc.NamedStorage(CASC_DATA)

    if a.export:
        os.makedirs(OUT, exist_ok=True)
        bundle = open(os.path.join(OUT, 'keyframes.bin'), 'wb')

    ok = total = 0
    slack_other = 0
    manifest = []
    off = 0
    for name in sorted(n for n in st.root if n.endswith('.webm')):
        try:
            blob = st.read_name(name)
        except Exception:
            continue
        kf = keyframe_of(blob)
        if kf is None:
            continue
        total += 1
        try:
            fr = decode_keyframe(kf)      # raises if a partition desyncs
            ok += 1
        except Exception as e:
            print('   %-50s %s' % (name, str(e)[:60]))
            continue
        if any(s != 0 for s in fr.partition_slack):
            slack_other += 1
        if a.export:
            # All keyframes go into one file, and only a SHA-256 of our I420
            # travels to the browser — one fetch instead of two-per-file
            # through the preview proxy, which drops requests under load.
            bundle.write(kf)
            manifest.append({'name': name, 'off': off, 'len': len(kf),
                             'w': fr.width, 'h': fr.height,
                             'lf': fr.hdr['loop_filter_level'],
                             'sha': sha(planes_i420(fr))})
            off += len(kf)
        if a.limit and total >= a.limit:
            break

    if a.export:
        bundle.close()
        json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'))
        nlf = sum(1 for m in manifest if m['lf'])
        print('   exported %d frames to tests/_vp8cmp/keyframes.bin '
              '(%d loop-filtered, %d bytes)' % (len(manifest), nlf, off))
    extra = ('(every partition ended exactly on its boundary)'
             if not slack_other else '(%d files ended off-boundary)' % slack_other)
    sys.exit(report('vp8: intra decode + partitions', ok, total, extra))


if __name__ == '__main__':
    main()
