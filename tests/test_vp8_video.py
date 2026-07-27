"""Proves the VP8 inter-frame decoder (stage e) matches libvpx over whole
video sequences, not just the first keyframe.

Two independent checks, same shape as test_vp8_pixels.py but across every frame
of every clip:

1. **Partition boundary** (here, no browser). Every frame's residual
   partition must be consumed to exactly its declared length. For an inter
   frame this exercises the whole mode/MV/token machinery in one number: a
   single mis-read motion vector or mode shifts every later token.

2. **Pixel identity** (needs a browser). Each decoded frame is compared to
   libvpx through WebCodecs, in I420. A drifting motion-compensation or
   reference-frame bug would diverge within a few frames, so matching a long
   sequence frame-for-frame is a real test of the inter path.

Run:

    py test_vp8_video.py                 # check 1 over the whole corpus
    py test_vp8_video.py --export        # write tests/_vp8vid/ for check 2
    py test_vp8_video.py --export N      # only the first N clips (smaller)

Then serve the repo root (py tests/_serve.py) and open tests/vp8-video-oracle.html.
"""
import sys, os, json, argparse, hashlib
from common import CASC_DATA, need, report
import casc
import webm
from vp8 import parse_frame_tag
from vp8_decode import VP8Decoder

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_vp8vid')


def vp8_frames(blob):
    """Every frame payload in decode order, or None if not a VP8 clip."""
    try:
        d = webm.WebM(blob)
    except Exception:
        return None
    if d.codec != 'V_VP8':
        return None
    return [blob[o:o + s] for _, _, _, o, s in d.frames]


def planes_i420(fr):
    w, h = fr.width, fr.height
    cw, ch = (w + 1) // 2, (h + 1) // 2
    buf = bytearray()
    for pl, pw, ph in ((fr.y, w, h), (fr.u, cw, ch), (fr.v, cw, ch)):
        for j in range(ph):
            o = pl.row_off(j)
            buf += pl.buf[o:o + pw]
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export', nargs='?', const=-1, type=int, default=None,
                    metavar='N', help='write tests/_vp8vid/ (optionally cap '
                    'to the first N clips)')
    ap.add_argument('--maxpix', type=int, default=0, metavar='WH',
                    help='skip clips whose width*height exceeds this, to keep '
                    'the pure-Python run tractable (0 = no limit)')
    a = ap.parse_args()

    need(CASC_DATA, 'SC:R CASC data')
    st = casc.NamedStorage(CASC_DATA)

    if a.export is not None:
        os.makedirs(OUT, exist_ok=True)
        bundle = open(os.path.join(OUT, 'frames.bin'), 'wb')
    manifest = []

    ok_clips = clips = total_frames = bad = 0
    slack_bad = 0
    off = 0
    names = sorted(n for n in st.root if n.endswith('.webm'))
    for name in names:
        try:
            blob = st.read_name(name)
        except Exception:
            continue
        frames = vp8_frames(blob)
        if not frames:
            continue
        if a.maxpix:
            d = webm.WebM(blob)
            if (d.width or 0) * (d.height or 0) > a.maxpix:
                continue
        clips += 1
        dec = VP8Decoder()
        clip_ok = True
        entries = []
        try:
            for data in frames:
                fr = dec.decode_frame(data)
                total_frames += 1
                if any(s != 0 for s in fr.partition_slack):
                    slack_bad += 1
                if a.export is not None:
                    bundle.write(data)
                    entries.append({'off': off, 'len': len(data),
                                    'w': fr.width, 'h': fr.height,
                                    'sha': hashlib.sha256(planes_i420(fr))
                                    .hexdigest()})
                    off += len(data)
        except Exception as e:
            clip_ok = False
            bad += 1
            print('   %-48s %s' % (name, str(e)[:55]))
        if clip_ok:
            ok_clips += 1
        if a.export is not None and clip_ok:
            manifest.append({'name': name, 'frames': entries})
        if a.export == -1:
            pass
        elif a.export is not None and len(manifest) >= a.export:
            break

    if a.export is not None:
        bundle.close()
        json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'))
        print('   exported %d clips, %d frames to tests/_vp8vid/frames.bin '
              '(%d bytes)' % (len(manifest),
                              sum(len(m['frames']) for m in manifest), off))

    extra = '(%d frames)' % total_frames
    if slack_bad:
        extra = '(%d frames ended off-boundary)' % slack_bad
    rc = report('vp8: video decode + partitions',
                ok_clips if not slack_bad else 0, clips, extra)
    sys.exit(rc)


if __name__ == '__main__':
    main()
