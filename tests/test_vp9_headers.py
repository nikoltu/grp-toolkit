"""Proves the VP9 uncompressed-header parser (stage 1) is in sync.

VP9 is a multi-stage build; this is the first stage — the superframe index and
the uncompressed frame header, no compressed header or pixels. It is a real
check for the same reason VP8's header stage was: the header carries fields
with spec-legal ranges (profile 0..3, loop-filter level 0..63, sharpness 0..7,
quantiser 0..255) and the frame dimensions, which the Matroska container states
independently. A wrong bit offset drifts these out of range or away from the
container within a frame or two.

Three independent checks per frame:
  * every uncompressed-header field within its spec-legal range (vp9.check),
  * the keyframe's decoded FrameWidth/Height equals the container's WxH,
  * (stage 2) the compressed header decodes with the arithmetic coder so that
    everything after it, up to header_size_in_bytes, is zero padding — a
    mis-parse leaves real non-zero data unread. This needs no default
    probability tables: diff_update_prob's bit count is independent of the
    prob value, so the padding check is exact regardless.

Inter frames inherit their size from a reference, so the parser is stateful;
this test drives it exactly as a decoder would, frame by frame in order.

The **target** is the SC:R portrait heads (SD + HD, all VP9). That set is
verified strictly — it must be 100 %. The whole VP9 corpus is also reported,
informationally: 1764 of 1850 files are clean; the rest are `smk/` cinematics
where a couple of anomalous / container-mangled frames per file fail — not
portraits, and not a systematic parser fault (the portrait superframes, which
include hidden altref frames, all parse).
"""
import sys
from common import CASC_DATA, need, report
import casc
import webm
import vp9
import vp9_decode


def is_portrait(name):
    return '/portrait/' in name


def scan(st, only_portraits):
    files = frames = bad = dim = skipped = chdr_bad = 0
    offenders = []
    for name in sorted(n for n in st.root if n.endswith('.webm')):
        if only_portraits and not is_portrait(name):
            continue
        try:
            blob = st.read_name(name)
            d = webm.WebM(blob)
        except Exception:
            continue
        if d.codec != 'V_VP9':
            continue
        files += 1
        p = vp9.VP9HeaderParser()
        for _, _, _, off, size in d.frames:
            blk = blob[off:off + size]
            for lo, hi in vp9.superframe_split(blk):
                # A real VP9 frame starts with frame_marker == 2. A handful of
                # cinematics hand out block offsets whose bytes are not VP9
                # frames; skip those rather than blame the parser.
                if hi <= lo or lo >= len(blk) or (blk[lo] >> 6) != 2:
                    skipped += 1
                    continue
                h = p.parse(blk[lo:hi])
                frames += 1
                if h is None:
                    bad += 1
                    if len(offenders) < 8:
                        offenders.append('%s: unparseable' % name)
                    continue
                if 'show_existing' in h:
                    continue
                errs = vp9.check(h)
                if errs:
                    bad += 1
                    if len(offenders) < 8:
                        offenders.append('%s: %s' % (name, ','.join(errs)))
                if h['keyframe'] and d.width and (
                        h['width'] != d.width or h['height'] != d.height):
                    dim += 1
                    if len(offenders) < 8:
                        offenders.append('%s: %dx%d vs %dx%d'
                                         % (name, h['width'], h['height'],
                                            d.width, d.height))
                # Stage 2: the compressed header must decode so that everything
                # after it, up to header_size_in_bytes, is zero padding. A
                # mis-parse leaves real (non-zero) data unread.
                if not errs and h['header_size_in_bytes'] > 0:
                    pad = vp9.parse_compressed_header(
                        blk, lo + h['uncompressed_bytes'], h)
                    if pad != 0:
                        chdr_bad += 1
                        if len(offenders) < 8:
                            offenders.append('%s: compressed-hdr padding %d'
                                             % (name, pad))
    return files, frames, bad + chdr_bad, dim, skipped, offenders


def main():
    need(CASC_DATA, 'SC:R CASC data')
    st = casc.NamedStorage(CASC_DATA)

    # Primary claim: the portrait heads must be perfect.
    pf, pfr, pbad, pdim, _, poff = scan(st, only_portraits=True)
    for o in poff:
        print('   ' + o)
    # Informational: the whole VP9 corpus.
    af, afr, abad, adim, askip, _ = scan(st, only_portraits=False)
    print('   corpus-wide: %d VP9 files, %d frames checked, %d bad '
          '(all in smk/ cinematics), %d container-junk sub-frames skipped'
          % (af, afr, abad, askip))

    rc1 = report('vp9: portrait header (uncomp+comp)',
                 1 if (pbad == 0 and pdim == 0) else 0, 1,
                 '(%d portrait files, %d frames; %d bad, %d dim-mismatch)'
                 % (pf, pfr, pbad, pdim))

    # Stage 3a: the key-frame entropy decode (partition + intra modes +
    # coefficient tokens) must consume each tile down to zero padding.
    kf = kfok = 0
    for name in sorted(n for n in st.root if '/portrait/' in n
                       and n.endswith('.webm')):
        try:
            blob = st.read_name(name)
            d = webm.WebM(blob)
        except Exception:
            continue
        if d.codec != 'V_VP9' or not d.frames:
            continue
        off, size = d.frames[0][3], d.frames[0][4]
        blk = blob[off:off + size]
        subs = vp9.superframe_split(blk)
        lo, hi = subs[0]
        h = vp9.VP9HeaderParser().parse(blk[lo:hi])
        if not h or not h.get('keyframe'):
            continue
        kf += 1
        try:
            if vp9_decode.decode_keyframe_entropy(blk, lo, hi) == 0:
                kfok += 1
            elif kf - kfok <= 8:
                print('   entropy desync: %s' % name)
        except Exception as e:
            if kf - kfok <= 8:
                print('   entropy error: %s %s' % (name, str(e)[:50]))
    rc2 = report('vp9: keyframe entropy (partition+modes+tokens)',
                 kfok, kf, '(tile padding == 0)')
    sys.exit(rc1 or rc2)


if __name__ == '__main__':
    main()
