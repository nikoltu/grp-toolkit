#!/usr/bin/env python3
"""WebM / Matroska (EBML) container reader — stdlib only.

Reads structure and metadata: codec, dimensions, duration, track layout, frame
(SimpleBlock) count and the raw compressed frames.

DELIBERATELY NOT A VIDEO DECODER. SC:R ships VP8/VP9 inside these containers,
and a from-scratch VP9 decoder is thousands of lines that cannot be validated
without a conformance suite — writing one blind would produce something that
looks finished and isn't. The browser app plays these natively instead (Chrome
decodes VP8/VP9), which is both correct and free.

    from webm import WebM
    w = WebM(open('tmafid00.webm','rb').read())
    print(w.codec, w.width, w.height, w.duration, len(w.frames))
"""
import struct, sys, argparse

# Elements we care about. Everything else is skipped by size.
# 0xA0 = BlockGroup. Without it, files that use Block (0xA1) inside a
# BlockGroup instead of a bare SimpleBlock parse to ZERO frames — that is what
# hid 115 VP8 files, and it looked like a VP8 problem rather than a container one.
MASTER = {0x1A45DFA3, 0x18538067, 0x1549A966, 0x1654AE6B, 0xAE, 0xE0,
          0x1F43B675, 0x1C53BB6B, 0xBB, 0xB7, 0xA0}
ID_TIMECODE_SCALE, ID_DURATION = 0x2AD7B1, 0x4489
ID_TRACK_NUMBER, ID_TRACK_TYPE, ID_CODEC_ID = 0xD7, 0x83, 0x86
ID_PIXEL_W, ID_PIXEL_H = 0xB0, 0xBA
ID_DEFAULT_DUR = 0x23E383
ID_SIMPLE_BLOCK, ID_BLOCK, ID_CLUSTER_TC = 0xA3, 0xA1, 0xE7
ID_MUXING_APP, ID_WRITING_APP = 0x4D80, 0x5741


def _vint(d, p, keep_marker):
    """EBML variable-length integer. IDs keep their length marker, sizes do not."""
    if p >= len(d):
        raise EOFError
    b = d[p]
    if b == 0:
        raise ValueError('invalid EBML vint at %d' % p)
    n = 1
    mask = 0x80
    while not (b & mask):
        mask >>= 1
        n += 1
    if keep_marker:
        v = b
    else:
        v = b & (mask - 1)
    for i in range(1, n):
        v = (v << 8) | d[p + i]
    # all-ones size means "unknown length"
    if not keep_marker and v == (1 << (7 * n)) - 1:
        v = None
    return v, p + n


class WebM:
    def __init__(self, data):
        if data[:4] != b'\x1a\x45\xdf\xa3':
            raise ValueError('not an EBML/Matroska file')
        self.data = data
        self.timecode_scale = 1000000
        self.duration_raw = None
        self.tracks = []
        self.frames = []                 # (track, timecode, keyframe, offset, size)
        self.muxer = None
        self._track = None
        self._cluster_tc = 0
        self._walk(0, len(data), 0)
        v = [t for t in self.tracks if t.get('type') == 1]
        self.video = v[0] if v else None
        self.codec = self.video['codec'] if self.video else None
        self.width = self.video.get('w') if self.video else None
        self.height = self.video.get('h') if self.video else None

    @property
    def duration(self):
        if self.duration_raw is None:
            return None
        return self.duration_raw * self.timecode_scale / 1e9

    @property
    def fps(self):
        d = self.duration
        if d and self.frames:
            return len(self.frames) / d
        return None

    def _walk(self, p, end, depth):
        d = self.data
        while p < end:
            try:
                eid, p2 = _vint(d, p, True)
                size, p3 = _vint(d, p2, False)
            except (EOFError, ValueError):
                return
            if size is None:                      # unknown-size master element
                self._walk(p3, end, depth + 1)
                return
            body_end = min(p3 + size, end)
            if eid in MASTER:
                if eid == 0xAE:
                    self._track = {}
                    self._walk(p3, body_end, depth + 1)
                    self.tracks.append(self._track)
                    self._track = None
                else:
                    self._walk(p3, body_end, depth + 1)
            else:
                self._leaf(eid, p3, size)
            p = body_end

    def _leaf(self, eid, p, size):
        d = self.data
        def uint():
            v = 0
            for i in range(size):
                v = (v << 8) | d[p + i]
            return v
        def flt():
            if size == 4:
                return struct.unpack_from('>f', d, p)[0]
            if size == 8:
                return struct.unpack_from('>d', d, p)[0]
            return None
        if eid == ID_TIMECODE_SCALE:
            self.timecode_scale = uint()
        elif eid == ID_DURATION:
            self.duration_raw = flt()
        elif eid == ID_MUXING_APP and self.muxer is None:
            self.muxer = d[p:p + size].decode('utf-8', 'replace')
        elif eid == ID_CLUSTER_TC:
            self._cluster_tc = uint()
        elif self._track is not None:
            if eid == ID_TRACK_NUMBER:
                self._track['num'] = uint()
            elif eid == ID_TRACK_TYPE:
                self._track['type'] = uint()
            elif eid == ID_CODEC_ID:
                self._track['codec'] = d[p:p + size].decode('ascii', 'replace')
            elif eid == ID_PIXEL_W:
                self._track['w'] = uint()
            elif eid == ID_PIXEL_H:
                self._track['h'] = uint()
            elif eid == ID_DEFAULT_DUR:
                self._track['default_dur'] = uint()
        elif eid in (ID_SIMPLE_BLOCK, ID_BLOCK):
            tn, q = _vint(d, p, False)
            rel = struct.unpack_from('>h', d, q)[0]
            flags = d[q + 2]
            self.frames.append((tn, self._cluster_tc + rel,
                                bool(flags & 0x80), q + 3, size - (q + 3 - p)))


# ---------------------------------------------------------------- VP9 header
# Per "VP9 Bitstream — superframe and uncompressed header", WebM Project v1.0.
# This is the part of VP9 that is small, documented and worth having: it tells
# you per frame whether it is a keyframe, its resolution and whether it is
# shown. The compressed residual is NOT touched.
VP9_SYNC = 0x498342


def vp9_superframe_split(buf):
    """A VP9 'superframe' packs several frames in one block. Returns the list of
    sub-frame byte ranges (just [whole] when there is no index)."""
    if not buf:
        return []
    m = buf[-1]
    if (m & 0xE0) != 0xC0:
        return [(0, len(buf))]
    frames = (m & 0x7) + 1
    mag = ((m >> 3) & 3) + 1
    idx_sz = 2 + mag * frames
    if len(buf) < idx_sz or buf[-idx_sz] != m:
        return [(0, len(buf))]
    p = len(buf) - idx_sz + 1
    out, off = [], 0
    for _ in range(frames):
        sz = 0
        for k in range(mag):
            sz |= buf[p + k] << (8 * k)
        p += mag
        out.append((off, off + sz))
        off += sz
    return out


class _BR:
    def __init__(self, d):
        self.d, self.p = d, 0
    def f(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v


def vp9_frame_header(buf):
    """Uncompressed header of one VP9 frame. Returns None if the sync marker or
    profile is not what the spec describes (i.e. do not trust it silently)."""
    b = _BR(buf)
    if b.f(2) != 2:                                  # frame_marker
        return None
    prof = b.f(1) | (b.f(1) << 1)
    if prof == 3:
        b.f(1)
    r = {'profile': prof}
    if b.f(1):                                       # show_existing_frame
        r['show_existing'] = b.f(3)
        return r
    r['keyframe'] = (b.f(1) == 0)
    r['show_frame'] = bool(b.f(1))
    r['error_resilient'] = bool(b.f(1))
    if r['keyframe']:
        if b.f(24) != VP9_SYNC:
            return None
        r['color_space'] = b.f(3)
        if r['color_space'] != 7:
            r['color_range'] = b.f(1)
            if prof in (1, 3):
                r['subsampling'] = (b.f(1), b.f(1)); b.f(1)
        else:
            if prof in (1, 3):
                b.f(1)
        r['width'] = b.f(16) + 1
        r['height'] = b.f(16) + 1
        r['render_different'] = bool(b.f(1))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('--frames', action='store_true', help='list block timecodes')
    a = ap.parse_args()
    w = WebM(open(a.input, 'rb').read())
    print('codec     : %s' % w.codec)
    print('dydis     : %sx%s' % (w.width, w.height))
    print('trukme    : %s s' % (('%.3f' % w.duration) if w.duration else '?'))
    print('kadru     : %d  (%s fps)' % (len(w.frames), ('%.2f' % w.fps) if w.fps else '?'))
    print('takeliai  : %s' % w.tracks)
    print('muxer     : %s' % w.muxer)
    if a.frames:
        d = w.data
        for i, (t, tc, key, off, sz) in enumerate(w.frames[:40]):
            blk = d[off:off + sz]
            parts = vp9_superframe_split(blk) if w.codec == 'V_VP9' else [(0, len(blk))]
            extra = ''
            if w.codec == 'V_VP9':
                hs = [vp9_frame_header(blk[s:e]) for s, e in parts]
                hs = [h for h in hs if h]
                if hs:
                    h = hs[0]
                    extra = ' vp9:%s%s%s' % (
                        'KEY' if h.get('keyframe') else 'inter',
                        (' %dx%d' % (h['width'], h['height'])) if 'width' in h else '',
                        ('' if h.get('show_frame', True) else ' (hidden)'))
                    if len(parts) > 1:
                        extra += ' superframe x%d' % len(parts)
            print('  %-3d track %d tc=%-7d %s %7d B @%-8d%s'
                  % (i, t, tc, 'KEY' if key else '   ', sz, off, extra))


if __name__ == '__main__':
    main()
