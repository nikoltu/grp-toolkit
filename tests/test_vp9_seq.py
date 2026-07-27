"""Compares the VP9 inter decoder (stage 5) against a reference decoder,
frame for frame, over whole portrait clips.

The reference is ffmpeg's VP9 decoder via PyAV (`pip install av`) - a local,
fast, independent oracle (the same role the browser's libvpx plays for VP8/VP9
key frames, but runnable headless). For every shown frame, every plane is
compared byte-for-byte in the frame's own native format (yuv420p for 4:2:0,
gbrp for the sRGB 4:4:4 heads) - no colour conversion.

    py test_vp9_seq.py            # sample of clips
    py test_vp9_seq.py --all      # whole portrait corpus (slow)

Status (2026-07): COMPLETE - byte-exact vs PyAV over the whole portrait inter
corpus, both profiles (4:2:0 profile-0 and 4:4:4 profile-1 sRGB). The last bug
was a colour-config inheritance fault: inter frames don't re-signal chroma
subsampling (spec 7.2), so 4:4:4 inter chroma was decoded at 4:2:0 resolution
and desynced; fixed in tools/vp9.py. This test remains the oracle for any future
regression - the first differing block in the first differing shown frame is
where the entropy diverged.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
from common import CASC_DATA, need, report
import casc
import webm
import vp9
import vp9_inter
import vp9_inter_pixels as PB


def _pyav_planes(frame):
    """Native planes of a decoded frame: 3 full planes for gbrp/i444, Y + half
    chroma for yuv420p. No reformat (which would be lossy for RGB)."""
    fmt = frame.format.name
    out = []
    for pi in range(len(frame.planes)):
        pl = frame.planes[pi]
        stride = pl.line_size
        if fmt.startswith('yuv420') and pi > 0:
            pw, ph = (frame.width + 1) // 2, (frame.height + 1) // 2
        else:
            pw, ph = frame.width, frame.height
        buf = bytes(pl)
        out.append([list(buf[r * stride:r * stride + pw]) for r in range(ph)])
    return out


def compare_clip(doc, blob):
    """Return (frames_compared, frames_exact, first_mismatch or None)."""
    import av
    import io
    mine = PB.decode_sequence(doc, blob)
    cont = av.open(io.BytesIO(blob))
    ref = [_pyav_planes(f) for f in cont.decode(cont.streams.video[0])]
    n = min(len(mine), len(ref))
    exact = 0
    first = None
    for fi in range(n):
        ok = True
        for p in range(3):
            M, A = mine[fi][p], ref[fi][p]
            if M == A:
                continue
            ok = False
            if first is None:
                for r in range(min(len(M), len(A))):
                    for c in range(min(len(M[r]), len(A[r]))):
                        if M[r][c] != A[r][c]:
                            first = (fi, p, r, c, M[r][c], A[r][c])
                            break
                    if first:
                        break
            break
        if ok:
            exact += 1
    return n, exact, first


def main():
    all_clips = '--all' in sys.argv
    need(CASC_DATA, 'SC:R CASC data')
    try:
        import av  # noqa: F401
    except ImportError:
        print('   PyAV not installed (pip install av); cannot compare')
        sys.exit(77)
    st = casc.NamedStorage(CASC_DATA)
    names = sorted(n for n in st.root if '/portrait/' in n and n.endswith('.webm'))
    if not all_clips:
        names = names[::37]
    ok = total = 0
    for name in names:
        try:
            blob = st.read_name(name)
            d = webm.WebM(blob)
        except Exception:
            continue
        if d.codec != 'V_VP9' or not d.frames:
            continue
        pad, _ = vp9_inter.decode_clip_padding(d, blob)
        n, exact, first = compare_clip(d, blob)
        total += 1
        clip_ok = (exact == n and n > 0)
        if clip_ok:
            ok += 1
        else:
            print('   %-32s pad=%d  %d/%d frames exact  first=%s'
                  % (name.split('/portrait/')[-1][:30], pad, exact, n, first))
        if total >= (10 ** 9 if all_clips else 12):
            break
    sys.exit(report('vp9: inter sequence vs PyAV (byte-exact)', ok, total,
                    '(Phase B verified where Phase A entropy is clean)'))


if __name__ == '__main__':
    main()
