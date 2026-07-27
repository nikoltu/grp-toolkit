#!/usr/bin/env python3
"""VP8 — a full decoder (stages c, d, e): intra + inter to pixels.

Continues tools/vp8.py (stages (a) bool decoder and (b) frame header) with mode
and coefficient decoding, dequantisation, the inverse WHT/DCT, all fourteen
intra prediction modes, the normal in-loop deblocking filter (d), and inter
frames (e): motion-vector decoding, 6-tap sub-pixel prediction, chroma-MV
derivation and reference-frame management.

Written from the prose of RFC 6386 (with the reference decoder consulted where
the prose is ambiguous). The constant tables are extracted from the spec
mechanically by tools/gen_vp8_tables.py — see that file for why.

Only the normal loop filter (filter_type 0) and non-full-pel (version 0) are
implemented; both cover the whole SC:R corpus. The simple filter and version
1/2/3 raise NotImplementedError rather than silently mis-decode.

A self-check that needs no external decoder: each residual partition must be
consumed to its exact declared length. An arithmetic decoder that mis-reads one
token desynchronises and lands elsewhere, so "ended on the boundary" is a real
statement about every token — and every mode and motion vector — before it.

    from vp8_decode import VP8Decoder, decode_video
    for fr in decode_video(list_of_frame_payloads):   # keyframe first
        fr.y, fr.u, fr.v      # planes, macroblock-aligned
        fr.rgb()              # cropped to the visible frame
"""
import sys
import struct
import argparse

from vp8 import BoolDecoder, parse_keyframe, parse_frame_tag
import vp8_tables as T

# Intra modes, then the five inter modes, in the order the spec's enum declares
# them (§9 prediction_mode).
DC_PRED, V_PRED, H_PRED, TM_PRED, B_PRED = range(5)
NEARESTMV, NEARMV, ZEROMV, NEWMV, SPLITMV = range(5, 10)
# Subblock modes: ten intra, then four inter (§9, second numbering).
(B_DC_PRED, B_TM_PRED, B_VE_PRED, B_HE_PRED, B_LD_PRED,
 B_RD_PRED, B_VR_PRED, B_VL_PRED, B_HD_PRED, B_HU_PRED) = range(10)
LEFT4X4, ABOVE4X4, ZERO4X4, NEW4X4 = range(10, 14)
# Reference frames.
CURRENT_FRAME, LAST_FRAME, GOLDEN_FRAME, ALTREF_FRAME = range(4)

# 16x16 luma modes imply a subblock mode, used only as context for a
# neighbouring B_PRED macroblock.
IMPLIED_B = {DC_PRED: B_DC_PRED, V_PRED: B_VE_PRED,
             H_PRED: B_HE_PRED, TM_PRED: B_TM_PRED}

# Segment id tree (RFC 6386 §9.3). Four leaves, two bits, no context.
MB_SEGMENT_TREE = [2, 4, -0, -1, -2, -3]

# Token values in the coefficient tree.
DCT_0, DCT_1, DCT_2, DCT_3, DCT_4 = 0, 1, 2, 3, 4
DCT_CAT1 = 5                    # ... through DCT_CAT6 = 10
DCT_EOB = 11
CAT_BASE = [5, 7, 11, 19, 35, 67]
CAT_PROBS = [T.PCAT1, T.PCAT2, T.PCAT3, T.PCAT4, T.PCAT5, T.PCAT6]

# Entropy context slots per macroblock: Y 0..3, U 4..5, V 6..7, Y2 8.
# Above is indexed by the block's column, left by its row.
ABOVE_CTX = ([i & 3 for i in range(16)] +
             [4 + (i & 1) for i in range(4)] +
             [6 + (i & 1) for i in range(4)] + [8])
LEFT_CTX = ([i >> 2 for i in range(16)] +
            [4 + ((i >> 1) & 1) for i in range(4)] +
            [6 + ((i >> 1) & 1) for i in range(4)] + [8])


def treed_read(bd, tree, probs, start=0):
    """RFC 6386 §8. Walk the tree until a non-positive entry is reached.

    A leaf is stored as the negated value, so leaf 0 and index 0 look the same
    — the spec resolves this by never using index 0 as a child, which is why
    the loop tests the value it just fetched rather than the one it starts on.
    """
    i = start
    while True:
        i = tree[i + bd.bool(probs[i >> 1])]
        if i <= 0:
            return -i


def clamp255(v):
    return 0 if v < 0 else (255 if v > 255 else v)


# ---------------------------------------------------------------- transforms

COSPI8SQRT2MINUS1 = 20091
SINPI8SQRT2 = 35468


def _mul1(x):
    return x + ((x * COSPI8SQRT2MINUS1) >> 16)


def _mul2(x):
    return (x * SINPI8SQRT2) >> 16


def idct4x4(b):
    """Inverse DCT (RFC 6386 §14.4). In and out are flat 16-element lists.

    The >>16 multiplies are part of the format, not an approximation: a decoder
    that uses floating point produces different pixels."""
    t = [0] * 16
    for i in range(4):                       # columns
        a1 = b[i] + b[i + 8]
        b1 = b[i] - b[i + 8]
        c1 = _mul2(b[i + 4]) - _mul1(b[i + 12])
        d1 = _mul1(b[i + 4]) + _mul2(b[i + 12])
        t[i] = a1 + d1
        t[i + 12] = a1 - d1
        t[i + 4] = b1 + c1
        t[i + 8] = b1 - c1
    o = [0] * 16
    for i in range(0, 16, 4):                # rows
        a1 = t[i] + t[i + 2]
        b1 = t[i] - t[i + 2]
        c1 = _mul2(t[i + 1]) - _mul1(t[i + 3])
        d1 = _mul1(t[i + 1]) + _mul2(t[i + 3])
        o[i] = (a1 + d1 + 4) >> 3
        o[i + 3] = (a1 - d1 + 4) >> 3
        o[i + 1] = (b1 + c1 + 4) >> 3
        o[i + 2] = (b1 - c1 + 4) >> 3
    return o


def iwht4x4(b):
    """Inverse Walsh-Hadamard for the Y2 block (RFC 6386 §14.3)."""
    t = [0] * 16
    for i in range(4):
        a1 = b[i] + b[i + 12]
        b1 = b[i + 4] + b[i + 8]
        c1 = b[i + 4] - b[i + 8]
        d1 = b[i] - b[i + 12]
        t[i] = a1 + b1
        t[i + 4] = c1 + d1
        t[i + 8] = a1 - b1
        t[i + 12] = d1 - c1
    o = [0] * 16
    for i in range(0, 16, 4):
        a1 = t[i] + t[i + 3]
        b1 = t[i + 1] + t[i + 2]
        c1 = t[i + 1] - t[i + 2]
        d1 = t[i] - t[i + 3]
        o[i] = (a1 + b1 + 3) >> 3
        o[i + 1] = (c1 + d1 + 3) >> 3
        o[i + 2] = (a1 - b1 + 3) >> 3
        o[i + 3] = (d1 - c1 + 3) >> 3
    return o


# -------------------------------------------------------------------- planes

class Plane:
    """A macroblock-aligned plane with the out-of-frame border the spec asks
    for: 127 above, 129 left, 127 in the corner, plus four spare columns on the
    right that hold the "above-right" pixels for subblock prediction."""
    __slots__ = ('w', 'h', 'stride', 'buf')

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.stride = w + 1 + 4
        self.buf = bytearray(self.stride * (h + 1))
        for i in range(self.stride):
            self.buf[i] = 127                       # row -1, incl. corner
        for r in range(1, h + 1):
            self.buf[r * self.stride] = 129         # column -1

    def at(self, x, y):
        return self.buf[(y + 1) * self.stride + (x + 1)]

    def sample(self, x, y):
        """A reference pixel with coordinates clamped to the plane. This is
        edge replication, which is exactly what the reference decoder's
        build_mc_border produces; and for motion vectors that stay comfortably
        inside the frame it never clamps, so it matches the direct read path
        too (RFC 6386 §18)."""
        if x < 0:
            x = 0
        elif x >= self.w:
            x = self.w - 1
        if y < 0:
            y = 0
        elif y >= self.h:
            y = self.h - 1
        return self.buf[(y + 1) * self.stride + (x + 1)]

    def row_off(self, y):
        return (y + 1) * self.stride + 1

    def extend_right(self, y):
        """Fill the spare columns of row y by replicating its last pixel.

        Used for the rightmost macroblock: subblocks 3, 7, 11 and 15 read four
        pixels above and to the right of the macroblock, which do not exist
        there. Above the top row they are 127 (already set); elsewhere the spec
        says to repeat the rightmost visible pixel of the row above."""
        o = self.row_off(y)
        v = self.buf[o + self.w - 1]
        for i in range(4):
            self.buf[o + self.w + i] = v


class Frame:
    def __init__(self, hdr, mb_cols, mb_rows):
        self.hdr = hdr
        self.width, self.height = hdr['width'], hdr['height']
        self.mb_cols, self.mb_rows = mb_cols, mb_rows
        self.y = Plane(mb_cols * 16, mb_rows * 16)
        self.u = Plane(mb_cols * 8, mb_rows * 8)
        self.v = Plane(mb_cols * 8, mb_rows * 8)

    def rgb(self):
        """BT.601 studio-range YUV 4:2:0 to packed RGB, cropped to the visible
        frame. Chroma is sampled nearest-neighbour; a player may interpolate,
        so expect small differences at colour edges when comparing."""
        w, h = self.width, self.height
        out = bytearray(w * h * 3)
        k = 0
        for j in range(h):
            yo = self.y.row_off(j)
            uo = self.u.row_off(j >> 1)
            vo = self.v.row_off(j >> 1)
            for i in range(w):
                c = self.y.buf[yo + i] - 16
                d = self.u.buf[uo + (i >> 1)] - 128
                e = self.v.buf[vo + (i >> 1)] - 128
                out[k] = clamp255((298 * c + 409 * e + 128) >> 8)
                out[k + 1] = clamp255((298 * c - 100 * d - 208 * e + 128) >> 8)
                out[k + 2] = clamp255((298 * c + 516 * d + 128) >> 8)
                k += 3
        return bytes(out)


# ---------------------------------------------------------------- prediction

def pred_dc(pl, x, y, size, have_above, have_left):
    """DC_PRED for a 16x16 or 8x8 block.

    The edge cases are not the same as substituting the 127/129 border values:
    with no neighbour at all the block is filled with 128, and with only one
    neighbour only that one is averaged (RFC 6386 §12.2)."""
    s, n = 0, 0
    if have_above:
        o = pl.row_off(y - 1)
        s += sum(pl.buf[o + x:o + x + size])
        n += size
    if have_left:
        for j in range(size):
            s += pl.at(x - 1, y + j)
        n += size
    if not n:
        return 128
    shf = (size.bit_length() - 1) + (1 if n == 2 * size else 0)
    return (s + (1 << (shf - 1))) >> shf


def predict_block(pl, x, y, size, mode, have_above, have_left):
    """16x16 luma or 8x8 chroma whole-block prediction."""
    if mode == DC_PRED:
        v = pred_dc(pl, x, y, size, have_above, have_left)
        for j in range(size):
            o = pl.row_off(y + j) + x
            pl.buf[o:o + size] = bytes([v]) * size
    elif mode == V_PRED:
        o = pl.row_off(y - 1) + x
        row = bytes(pl.buf[o:o + size])
        for j in range(size):
            o2 = pl.row_off(y + j) + x
            pl.buf[o2:o2 + size] = row
    elif mode == H_PRED:
        for j in range(size):
            o = pl.row_off(y + j) + x
            pl.buf[o:o + size] = bytes([pl.at(x - 1, y + j)]) * size
    elif mode == TM_PRED:
        p = pl.at(x - 1, y - 1)
        ao = pl.row_off(y - 1) + x
        above = pl.buf[ao:ao + size]
        for j in range(size):
            left = pl.at(x - 1, y + j)
            o = pl.row_off(y + j) + x
            for i in range(size):
                pl.buf[o + i] = clamp255(left + above[i] - p)
    else:
        raise ValueError('bad whole-block mode %d' % mode)


def predict_subblock(pl, x, y, mode, above_right):
    """One 4x4 luma subblock, ten modes (RFC 6386 §12.3).

    A[0..3] is the row above, A[4..7] the four pixels above and to the right
    (passed in, because for subblocks 7/11/15 they come from the row above the
    macroblock, not the row above the subblock), L[0..3] the column to the
    left, P the corner."""
    A = [pl.at(x + i, y - 1) for i in range(4)] + list(above_right)
    L = [pl.at(x - 1, y + j) for j in range(4)]
    P = pl.at(x - 1, y - 1)
    b = [0] * 16

    def avg3(a, b_, c):
        return (a + 2 * b_ + c + 2) >> 2

    def avg2(a, b_):
        return (a + b_ + 1) >> 1

    if mode == B_DC_PRED:
        v = (sum(A[:4]) + sum(L) + 4) >> 3
        b = [v] * 16
    elif mode == B_TM_PRED:
        for j in range(4):
            for i in range(4):
                b[j * 4 + i] = clamp255(L[j] + A[i] - P)
    elif mode == B_VE_PRED:
        e = [avg3(P, A[0], A[1]), avg3(A[0], A[1], A[2]),
             avg3(A[1], A[2], A[3]), avg3(A[2], A[3], A[4])]
        for j in range(4):
            b[j * 4:j * 4 + 4] = e
    elif mode == B_HE_PRED:
        e = [avg3(P, L[0], L[1]), avg3(L[0], L[1], L[2]),
             avg3(L[1], L[2], L[3]), avg3(L[2], L[3], L[3])]
        for j in range(4):
            b[j * 4:j * 4 + 4] = [e[j]] * 4
    elif mode == B_LD_PRED:
        e = [avg3(A[i], A[i + 1], A[i + 2]) for i in range(6)] + \
            [avg3(A[6], A[7], A[7])]
        for j in range(4):
            for i in range(4):
                b[j * 4 + i] = e[i + j]
    elif mode == B_RD_PRED:
        e = [avg3(L[3], L[2], L[1]), avg3(L[2], L[1], L[0]),
             avg3(L[1], L[0], P), avg3(L[0], P, A[0]),
             avg3(P, A[0], A[1]), avg3(A[0], A[1], A[2]),
             avg3(A[1], A[2], A[3])]
        for j in range(4):
            for i in range(4):
                b[j * 4 + i] = e[i - j + 3]
    elif mode == B_VR_PRED:
        e = [avg3(L[2], L[1], L[0]), avg3(L[1], L[0], P),
             avg3(L[0], P, A[0]), avg2(P, A[0]),
             avg3(P, A[0], A[1]), avg2(A[0], A[1]),
             avg3(A[0], A[1], A[2]), avg2(A[1], A[2]),
             avg3(A[1], A[2], A[3]), avg2(A[2], A[3])]
        idx = [3, 5, 7, 9,
               2, 4, 6, 8,
               1, 3, 5, 7,
               0, 2, 4, 6]
        b = [e[i] for i in idx]
    elif mode == B_VL_PRED:
        e = [avg2(A[0], A[1]), avg3(A[0], A[1], A[2]),
             avg2(A[1], A[2]), avg3(A[1], A[2], A[3]),
             avg2(A[2], A[3]), avg3(A[2], A[3], A[4]),
             avg2(A[3], A[4]), avg3(A[3], A[4], A[5]),
             avg3(A[4], A[5], A[6]), avg3(A[5], A[6], A[7])]
        # Each diagonal steps two entries per row, so a row is the previous
        # one shifted by one. The last two entries break that pattern (the
        # spec says so explicitly) and only rows 2 and 3 reach them.
        idx = [0, 2, 4, 6,
               1, 3, 5, 7,
               2, 4, 6, 8,
               3, 5, 7, 9]
        b = [e[i] for i in idx]
    elif mode == B_HD_PRED:
        e = [avg2(L[3], L[2]), avg3(L[3], L[2], L[1]),
             avg2(L[2], L[1]), avg3(L[2], L[1], L[0]),
             avg2(L[1], L[0]), avg3(L[1], L[0], P),
             avg2(L[0], P), avg3(L[0], P, A[0]),
             avg3(P, A[0], A[1]), avg3(A[0], A[1], A[2])]
        idx = [6, 7, 8, 9,
               4, 5, 6, 7,
               2, 3, 4, 5,
               0, 1, 2, 3]
        b = [e[i] for i in idx]
    elif mode == B_HU_PRED:
        e = [avg2(L[0], L[1]), avg3(L[0], L[1], L[2]),
             avg2(L[1], L[2]), avg3(L[1], L[2], L[3]),
             avg2(L[2], L[3]), avg3(L[2], L[3], L[3]),
             L[3], L[3], L[3], L[3]]
        idx = [0, 1, 2, 3,
               2, 3, 4, 5,
               4, 5, 6, 7,
               6, 7, 8, 9]
        b = [e[i] for i in idx]
    else:
        raise ValueError('bad subblock mode %d' % mode)

    for j in range(4):
        o = pl.row_off(y + j) + x
        pl.buf[o:o + 4] = bytes(b[j * 4:j * 4 + 4])


def add_residue(pl, x, y, res):
    for j in range(4):
        o = pl.row_off(y + j) + x
        for i in range(4):
            pl.buf[o + i] = clamp255(pl.buf[o + i] + res[j * 4 + i])


# ------------------------------------------------------- inter prediction (e)

def inter_block(dst, ref, bx, by, mvx, mvy, res):
    """Motion-compensate one 4x4 block from `ref` into `dst` at (bx,by), then
    add the residual. RFC 6386 §18: a whole-pel offset plus a 6-tap sub-pel
    filter, horizontal then vertical, each rounded `(sum + 64) >> 7`."""
    ix, iy = mvx >> 3, mvy >> 3          # whole-pel part (floor)
    mx, my = mvx & 7, mvy & 7            # sub-pel phase, 0..7
    ox, oy = bx + ix, by + iy

    if mx == 0 and my == 0:
        pred = [ref.sample(ox + c, oy + r) for r in range(4) for c in range(4)]
    else:
        fh, fv = T.SIXTAP_FILTERS[mx], T.SIXTAP_FILTERS[my]
        # Horizontal pass over 9 rows (the 4 output rows plus two above and
        # three below, for the vertical filter's taps).
        tmp = []
        for r in range(-2, 7):
            row = []
            for c in range(4):
                s = (ref.sample(ox + c - 2, oy + r) * fh[0]
                     + ref.sample(ox + c - 1, oy + r) * fh[1]
                     + ref.sample(ox + c, oy + r) * fh[2]
                     + ref.sample(ox + c + 1, oy + r) * fh[3]
                     + ref.sample(ox + c + 2, oy + r) * fh[4]
                     + ref.sample(ox + c + 3, oy + r) * fh[5] + 64) >> 7
                row.append(clamp255(s))
            tmp.append(row)
        pred = []
        for r in range(4):
            for c in range(4):
                s = (tmp[r][c] * fv[0] + tmp[r + 1][c] * fv[1]
                     + tmp[r + 2][c] * fv[2] + tmp[r + 3][c] * fv[3]
                     + tmp[r + 4][c] * fv[4] + tmp[r + 5][c] * fv[5] + 64) >> 7
                pred.append(clamp255(s))

    for j in range(4):
        o = dst.row_off(by + j) + bx
        for i in range(4):
            dst.buf[o + i] = clamp255(pred[j * 4 + i] + res[j * 4 + i])


def _cdiv(a, b):
    """C integer division: truncate toward zero (Python // floors)."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def chroma_mv_from_luma(mvx, mvy):
    """Average-and-halve a luma MV into a chroma MV, exactly as the reference
    decoder does: `(v + 1 + (v>>31)*2) / 2` with truncating division."""
    def h(v):
        return _cdiv(v + 1 + (-2 if v < 0 else 0), 2)
    return h(mvx), h(mvy)


def chroma_splitmv(mvs, b):
    """Chroma MV for split mode: sum the four luma sub-MVs of the 2x2 group,
    round, and divide by 8 (RFC 6386 calculate_chroma_splitmv)."""
    def avg(vals):
        t = sum(vals)
        t += -4 if t < 0 else 4
        return _cdiv(t, 8)
    xs = [mvs[b][0], mvs[b + 1][0], mvs[b + 4][0], mvs[b + 5][0]]
    ys = [mvs[b][1], mvs[b + 1][1], mvs[b + 4][1], mvs[b + 5][1]]
    return avg(xs), avg(ys)


# ------------------------------------------------------------------ decoding

def dequant_factors(hdr, seg_id):
    """Six factors: Y1 dc/ac, UV dc/ac, Y2 dc/ac (RFC 6386 §14.1)."""
    def clamp_q(q):
        return 0 if q < 0 else (127 if q > 127 else q)

    q = hdr['y_ac_qi']
    if hdr.get('segmentation_enabled') and 'segment_quant' in hdr:
        sq = hdr['segment_quant'][seg_id]
        q = sq if hdr.get('segment_feature_mode') else q + sq
    dc = lambda d: T.DC_QLOOKUP[clamp_q(q + d)]
    ac = lambda d: T.AC_QLOOKUP[clamp_q(q + d)]
    y2ac = ac(hdr['y2_ac_delta']) * 155 // 100
    return {
        'y1': (dc(hdr['y_dc_delta']), ac(0)),
        'uv': (min(dc(hdr['uv_dc_delta']), 132), ac(hdr['uv_ac_delta'])),
        'y2': (dc(hdr['y2_dc_delta']) * 2, max(y2ac, 8)),
    }


def decode_coeffs(bd, probs, plane, ctx, dq, out):
    """One 4x4 block. Returns True if any coefficient was non-zero.

    `plane` follows RFC 6386 §13.3: 0 = Y after Y2 (starts at coefficient 1),
    1 = Y2, 2 = chroma, 3 = Y without Y2. Note the spec's own pseudo-code in
    §13.3 contradicts this and numbers Y2 as 0; the reference decoder agrees
    with the prose, so the prose wins."""
    i = 1 if plane == 0 else 0
    prev_zero = False
    nonzero = False
    tbl = probs[plane]
    while i < 16:
        p = tbl[T.COEFF_BANDS[i]][ctx]
        # After a zero token an end-of-block cannot follow, so the first branch
        # of the tree is skipped by entering it at index 2.
        tok = treed_read(bd, T.COEFF_TREE, p, 2 if prev_zero else 0)
        if tok == DCT_EOB:
            break
        if tok == DCT_0:
            ctx = 0
            prev_zero = True
            i += 1
            continue
        prev_zero = False
        nonzero = True
        if tok <= DCT_4:
            v = tok
        else:
            cat = tok - DCT_CAT1
            extra = 0
            for pr in CAT_PROBS[cat][:-1]:
                extra = extra + extra + bd.bool(pr)
            v = CAT_BASE[cat] + extra
        ctx = 1 if v == 1 else 2
        if bd.bool(128):
            v = -v
        out[T.ZIGZAG[i]] = v * (dq[0] if i == 0 else dq[1])
        i += 1
    return nonzero


# -------------------------------------------------------------- loop filter

def _s8(x):
    return -128 if x < -128 else (127 if x > 127 else x)


def _common_adjust(buf, pos, step, outer):
    """RFC 6386 §15.2 filter_common, in the reference decoder's integer form:
    it works directly in unsigned space with two saturations, avoiding the
    u2s/s2u round-trip the prose uses. p0 is buf[pos-step], q0 is buf[pos]."""
    p1 = buf[pos - 2 * step]; p0 = buf[pos - step]
    q0 = buf[pos]; q1 = buf[pos + step]
    a = 3 * (q0 - p0) + (_s8(p1 - q1) if outer else 0)
    a = _s8(a)
    f1 = min(a + 4, 127) >> 3
    f2 = min(a + 3, 127) >> 3
    buf[pos - step] = _clamp_u8(p0 + f2)
    buf[pos] = _clamp_u8(q0 - f1)
    if not outer:
        a = (f1 + 1) >> 1
        buf[pos + step] = _clamp_u8(q1 - a)
        buf[pos - 2 * step] = _clamp_u8(p1 + a)


def _clamp_u8(v):
    return 0 if v < 0 else (255 if v > 255 else v)


def _mb_edge(buf, pos, step):
    """§15.3 MBfilter's low-variance branch, integer form (filter_mb_edge)."""
    p2 = buf[pos - 3 * step]; p1 = buf[pos - 2 * step]; p0 = buf[pos - step]
    q0 = buf[pos]; q1 = buf[pos + step]; q2 = buf[pos + 2 * step]
    w = _s8(_s8(p1 - q1) + 3 * (q0 - p0))
    a = (27 * w + 63) >> 7
    buf[pos - step] = _clamp_u8(p0 + a); buf[pos] = _clamp_u8(q0 - a)
    a = (18 * w + 63) >> 7
    buf[pos - 2 * step] = _clamp_u8(p1 + a); buf[pos + step] = _clamp_u8(q1 - a)
    a = (9 * w + 63) >> 7
    buf[pos - 3 * step] = _clamp_u8(p2 + a); buf[pos + 2 * step] = _clamp_u8(q2 - a)


def _normal_pass(buf, pos, step):
    return abs(buf[pos] - buf[pos - step])


def _threshold_ok(buf, pos, step, E, I):
    p3 = buf[pos - 4 * step]; p2 = buf[pos - 3 * step]
    p1 = buf[pos - 2 * step]; p0 = buf[pos - step]
    q0 = buf[pos]; q1 = buf[pos + step]
    q2 = buf[pos + 2 * step]; q3 = buf[pos + 3 * step]
    if abs(p0 - q0) * 2 + (abs(p1 - q1) >> 1) > 2 * E + I:
        return False
    return (abs(p3 - p2) <= I and abs(p2 - p1) <= I and abs(p1 - p0) <= I
            and abs(q3 - q2) <= I and abs(q2 - q1) <= I and abs(q1 - q0) <= I)


def _hev(buf, pos, step, thr):
    return (abs(buf[pos - 2 * step] - buf[pos - step]) > thr
            or abs(buf[pos + step] - buf[pos]) > thr)


def _filter_edge(buf, start, step, run, count, E, I, hev, mb):
    """Filter one edge. `step` reaches across it (1 for a vertical edge, the
    plane stride for a horizontal one); `run` advances along it; `count`
    segments. `mb` selects the wider inter-macroblock filter."""
    pos = start
    for _ in range(count):
        if _threshold_ok(buf, pos, step, E, I):
            hv = _hev(buf, pos, step, hev)
            if mb:
                if hv:
                    _common_adjust(buf, pos, step, True)
                else:
                    _mb_edge(buf, pos, step)
            else:
                _common_adjust(buf, pos, step, hv)
        pos += run


def _filter_level(hdr, seg_id, ymode, ref_frame):
    lvl = hdr['loop_filter_level']
    if hdr.get('segmentation_enabled') and 'segment_lf' in hdr:
        sl = hdr['segment_lf'][seg_id]
        lvl = sl if hdr.get('segment_feature_mode') else lvl + sl
    lvl = max(0, min(63, lvl))
    if hdr.get('lf_adj_enable'):
        # Per-macroblock adjustment by reference frame and mode (RFC 6386
        # §15.4, dixie calculate_filter_parameters).
        lvl += hdr.get('ref_lf_deltas', [0, 0, 0, 0])[ref_frame]
        md = hdr.get('mode_lf_deltas', [0, 0, 0, 0])
        if ref_frame == CURRENT_FRAME:
            if ymode == B_PRED:
                lvl += md[0]
        elif ymode == ZEROMV:
            lvl += md[1]
        elif ymode == SPLITMV:
            lvl += md[3]
        else:
            lvl += md[2]
        lvl = max(0, min(63, lvl))
    return lvl


def loop_filter(fr):
    """Normal in-loop deblocking filter (RFC 6386 §15) over a decoded frame.

    Only the normal filter is implemented; every file in this corpus uses it
    (filter_type == 0). A simple-filter frame would need §15.2's luma-only
    path — not written, because nothing here exercises it."""
    hdr = fr.hdr
    if hdr.get('filter_type') != 0:
        raise NotImplementedError('simple loop filter (filter_type=1) '
                                  'not implemented')
    sharp = hdr['sharpness_level']
    key = hdr['keyframe']
    yst, cst = fr.y.stride, fr.u.stride

    for mby in range(fr.mb_rows):
        for mbx in range(fr.mb_cols):
            ymode, seg_id, has_coeffs, ref_frame = fr.mb[mby][mbx]
            lvl = _filter_level(hdr, seg_id, ymode, ref_frame)
            if lvl == 0:
                continue

            interior = lvl
            if sharp:
                interior >>= 2 if sharp > 4 else 1
                interior = min(interior, 9 - sharp)
            interior = max(1, interior)
            # High-edge-variance threshold. The RFC gives different values for
            # key frames and inter frames (§15.4); dixie's code collapses them
            # to one formula, which is right for key frames but wrong for inter
            # frames at level 15..39 — the browser's libvpx uses the split
            # version, and it is what made split-MB edges differ.
            if key:
                hev = (1 if lvl >= 15 else 0) + (1 if lvl >= 40 else 0)
            elif lvl >= 40:
                hev = 3
            elif lvl >= 20:
                hev = 2
            elif lvl >= 15:
                hev = 1
            else:
                hev = 0
            inner = has_coeffs or ymode == B_PRED or ymode == SPLITMV

            yx, yy = mbx * 16, mby * 16
            cx, cy = mbx * 8, mby * 8

            # 1. left inter-macroblock edge (vertical)
            if mbx:
                _filter_edge(fr.y.buf, fr.y.row_off(yy) + yx, 1, yst, 16,
                             lvl + 2, interior, hev, True)
                _filter_edge(fr.u.buf, fr.u.row_off(cy) + cx, 1, cst, 8,
                             lvl + 2, interior, hev, True)
                _filter_edge(fr.v.buf, fr.v.row_off(cy) + cx, 1, cst, 8,
                             lvl + 2, interior, hev, True)
            # 2. internal vertical subblock edges
            if inner:
                for dx in (4, 8, 12):
                    _filter_edge(fr.y.buf, fr.y.row_off(yy) + yx + dx, 1, yst,
                                 16, lvl, interior, hev, False)
                _filter_edge(fr.u.buf, fr.u.row_off(cy) + cx + 4, 1, cst, 8,
                             lvl, interior, hev, False)
                _filter_edge(fr.v.buf, fr.v.row_off(cy) + cx + 4, 1, cst, 8,
                             lvl, interior, hev, False)
            # 3. top inter-macroblock edge (horizontal)
            if mby:
                _filter_edge(fr.y.buf, fr.y.row_off(yy) + yx, yst, 1, 16,
                             lvl + 2, interior, hev, True)
                _filter_edge(fr.u.buf, fr.u.row_off(cy) + cx, cst, 1, 8,
                             lvl + 2, interior, hev, True)
                _filter_edge(fr.v.buf, fr.v.row_off(cy) + cx, cst, 1, 8,
                             lvl + 2, interior, hev, True)
            # 4. internal horizontal subblock edges
            if inner:
                for dy in (4, 8, 12):
                    _filter_edge(fr.y.buf, fr.y.row_off(yy + dy) + yx, yst, 1,
                                 16, lvl, interior, hev, False)
                _filter_edge(fr.u.buf, fr.u.row_off(cy + 4) + cx, cst, 1, 8,
                             lvl, interior, hev, False)
                _filter_edge(fr.v.buf, fr.v.row_off(cy + 4) + cx, cst, 1, 8,
                             lvl, interior, hev, False)


class MBInfo:
    """What a macroblock's neighbours need to know about it during mode/MV
    decoding: its Y mode, reference frame, base MV, and (for split mode) the
    per-subblock modes and MVs."""
    __slots__ = ('ymode', 'uvmode', 'ref', 'mv', 'seg', 'skip',
                 'has_coeffs', 'smodes', 'smvs')

    def __init__(self):
        self.ymode = DC_PRED
        self.uvmode = DC_PRED
        self.ref = CURRENT_FRAME
        self.mv = (0, 0)
        self.seg = 0
        self.skip = False
        self.has_coeffs = False
        self.smodes = [B_DC_PRED] * 16
        self.smvs = [(0, 0)] * 16


def _implied_bmode(ymode):
    """The 4x4 mode a whole-block intra mode implies, for a neighbour that is
    B_PRED (RFC 6386 §11.2, dixie above_block_mode/left_block_mode)."""
    return {DC_PRED: B_DC_PRED, V_PRED: B_VE_PRED,
            H_PRED: B_HE_PRED, TM_PRED: B_TM_PRED}.get(ymode, B_DC_PRED)


def _read_mv_component(bd, mvc):
    """One signed MV component in eighth-pel units (RFC 6386 §17, dixie
    read_mv_component)."""
    IS_SHORT, SIGN, SHORT, BITS, LONG_W = 0, 1, 2, 9, 10
    if bd.bool(mvc[IS_SHORT]):                     # long
        x = 0
        for i in range(3):
            x += bd.bool(mvc[BITS + i]) << i
        for i in range(LONG_W - 1, 3, -1):
            x += bd.bool(mvc[BITS + i]) << i
        if not (x & 0xFFF0) or bd.bool(mvc[BITS + 3]):
            x += 8
    else:                                          # short
        x = treed_read(bd, T.SMALL_MV_TREE, mvc[SHORT:])
    if x and bd.bool(mvc[SIGN]):
        x = -x
    return x << 1


def _read_mv(bd, mvp):
    y = _read_mv_component(bd, mvp[0])
    x = _read_mv_component(bd, mvp[1])
    return (x, y)


class VP8Decoder:
    """A stateful VP8 decoder. Persists the probability tables, reference
    frames and per-frame headers that inter frames build on. Feed it frames in
    order via decode_frame(); a keyframe resets everything."""

    def __init__(self):
        self.refs = {}                 # LAST/GOLDEN/ALTREF -> Frame
        self.entropy = None            # coeff/mv/ymode/uvmode probs
        self.segment = None
        self.lf = None
        self.mb_cols = self.mb_rows = 0

    # -- header ------------------------------------------------------------
    def _parse_header(self, data):
        tag = parse_frame_tag(data)
        if tag is None:
            raise ValueError('short frame')
        h = dict(tag)
        key = tag['keyframe']
        if key:
            if data[3:6] != b'\x9d\x01\x2a':
                raise ValueError('bad keyframe start code')
            w_raw, h_raw = struct.unpack_from('<HH', data, 6)
            self.width = w_raw & 0x3FFF
            self.height = h_raw & 0x3FFF
            self.mb_cols = (self.width + 15) // 16
            self.mb_rows = (self.height + 15) // 16
        # Only keyframes carry dimensions; inter frames inherit them.
        h['width'] = self.width
        h['height'] = self.height
        part0_at = 10 if key else 3
        b = BoolDecoder(data, part0_at)

        if key:
            b.literal(2)                        # colour space + clamping type

        # -- segmentation (persists across frames; reset on keyframe)
        seg = self.segment = ({} if key else self.segment)
        seg['enabled'] = b.literal(1)
        seg['update_map'] = 0
        if seg['enabled']:
            seg['update_map'] = b.literal(1)
            update_data = b.literal(1)
            if update_data:
                seg['abs'] = b.literal(1)
                seg['quant'] = [b.flagged(7) for _ in range(4)]
                seg['lf'] = [b.flagged(6) for _ in range(4)]
            if seg['update_map']:
                seg['tree'] = [b.literal(8) if b.bool(128) else 255
                               for _ in range(3)]

        # -- loop filter (persists; reset on keyframe)
        lf = self.lf = ({} if key else self.lf)
        lf['type'] = b.literal(1)
        lf['level'] = b.literal(6)
        lf['sharpness'] = b.literal(3)
        lf['delta_enabled'] = b.literal(1)
        if 'ref_deltas' not in lf:
            lf['ref_deltas'] = [0, 0, 0, 0]
            lf['mode_deltas'] = [0, 0, 0, 0]
        if lf['delta_enabled'] and b.literal(1):
            lf['ref_deltas'] = [b.flagged(6) for _ in range(4)]
            lf['mode_deltas'] = [b.flagged(6) for _ in range(4)]

        # -- token partitions (sizes live after part0)
        nparts = 1 << b.literal(2)
        first = part0_at + h['first_part_size']
        off = first + 3 * (nparts - 1)
        parts = []
        for i in range(nparts):
            if i < nparts - 1:
                p = data[first + 3 * i:first + 3 * i + 3]
                sz = p[0] | (p[1] << 8) | (p[2] << 16)
            else:
                sz = len(data) - off
            if sz < 0 or off + sz > len(data):
                raise ValueError('partition %d out of range' % i)
            parts.append((off, sz))
            off += sz

        # -- quantiser (fresh every frame)
        h['y_ac_qi'] = b.literal(7)
        h['y_dc_delta'] = b.flagged(4)
        h['y2_dc_delta'] = b.flagged(4)
        h['y2_ac_delta'] = b.flagged(4)
        h['uv_dc_delta'] = b.flagged(4)
        h['uv_ac_delta'] = b.flagged(4)

        # -- reference header
        if key:
            refresh_gf = refresh_arf = refresh_last = 1
            copy_gf = copy_arf = 0
            sign_bias = [0, 0, 0, 0]
            refresh_entropy = b.literal(1)
        else:
            refresh_gf = b.literal(1)
            refresh_arf = b.literal(1)
            copy_gf = b.literal(2) if not refresh_gf else 0
            copy_arf = b.literal(2) if not refresh_arf else 0
            sign_bias = [0, 0, b.literal(1), b.literal(1)]
            refresh_entropy = b.literal(1)
            refresh_last = b.literal(1)
        h['sign_bias'] = sign_bias
        h['refresh'] = (refresh_last, refresh_gf, refresh_arf,
                        copy_gf, copy_arf)

        # -- entropy (persists; defaults restored on keyframe)
        if key or self.entropy is None:
            self.entropy = {
                'coeff': [[[list(r) for r in blk] for blk in typ]
                          for typ in T.DEFAULT_COEFF_PROBS],
                'mv': [list(T.DEFAULT_MV_PROBS[0]),
                       list(T.DEFAULT_MV_PROBS[1])],
                'ymode': list(T.DEFAULT_Y_MODE_PROBS),
                'uvmode': list(T.DEFAULT_UV_MODE_PROBS),
            }
        saved = None
        if not refresh_entropy:
            saved = {k: _deepcopy_probs(v) for k, v in self.entropy.items()}
        ent = self.entropy

        for i in range(4):
            for j in range(8):
                for k in range(3):
                    for t in range(11):
                        if b.bool(T.COEFF_UPDATE_PROBS[i][j][k][t]):
                            ent['coeff'][i][j][k][t] = b.literal(8)
        h['mb_no_coeff_skip'] = b.literal(1)
        h['prob_skip_false'] = b.literal(8) if h['mb_no_coeff_skip'] else 0
        if not key:
            h['prob_intra'] = b.literal(8)
            h['prob_last'] = b.literal(8)
            h['prob_gf'] = b.literal(8)
            if b.literal(1):
                ent['ymode'] = [b.literal(8) for _ in range(4)]
            if b.literal(1):
                ent['uvmode'] = [b.literal(8) for _ in range(3)]
            for i in range(2):
                for j in range(19):
                    if b.bool(T.MV_UPDATE_PROBS[i][j]):
                        x = b.literal(7)
                        ent['mv'][i][j] = (x << 1) if x else 1

        # Translate persistent headers into the flat keys the shared
        # reconstruction / dequant / loop-filter helpers expect.
        h['filter_type'] = lf['type']
        h['loop_filter_level'] = lf['level']
        h['sharpness_level'] = lf['sharpness']
        h['lf_adj_enable'] = lf['delta_enabled']
        h['ref_lf_deltas'] = lf['ref_deltas']
        h['mode_lf_deltas'] = lf['mode_deltas']
        h['segmentation_enabled'] = seg['enabled']
        h['update_mb_seg_map'] = seg['update_map']
        h['segment_tree_probs'] = seg.get('tree', [255, 255, 255])
        if seg.get('enabled') and 'quant' in seg:
            h['segment_quant'] = seg['quant']
            h['segment_lf'] = seg['lf']
            h['segment_feature_mode'] = seg['abs']
        return h, b, parts, saved, refresh_entropy

    # -- neighbour MV helpers ---------------------------------------------
    @staticmethod
    def _above_block_mv(this, above, b):
        if b < 4:
            return above.smvs[b + 12] if above.ymode == SPLITMV else above.mv
        return this.smvs[b - 4]

    @staticmethod
    def _left_block_mv(this, left, b):
        if not (b & 3):
            return left.smvs[b + 3] if left.ymode == SPLITMV else left.mv
        return this.smvs[b - 1]

    def _find_near_mvs(self, this, left, above, aboveleft, sign_bias):
        near = [(0, 0), (0, 0), (0, 0), (0, 0)]
        cnt = [0, 0, 0, 0]
        mi = ci = 0

        def biased(mb):
            x, y = mb.mv
            if sign_bias[mb.ref] ^ sign_bias[this.ref]:
                return (-x, -y)
            return (x, y)

        if above.ref != CURRENT_FRAME:
            if above.mv != (0, 0):
                mi += 1
                near[mi] = biased(above)
                ci += 1
            cnt[ci] += 2
        if left.ref != CURRENT_FRAME:
            if left.mv != (0, 0):
                m = biased(left)
                if m != near[mi]:
                    mi += 1
                    near[mi] = m
                    ci += 1
                cnt[ci] += 2
            else:
                cnt[0] += 2
        if aboveleft.ref != CURRENT_FRAME:
            if aboveleft.mv != (0, 0):
                m = biased(aboveleft)
                if m != near[mi]:
                    mi += 1
                    near[mi] = m
                    ci += 1
                cnt[ci] += 1
            else:
                cnt[0] += 1

        if cnt[3] and near[mi] == near[1]:
            cnt[1] += 1
        cnt[3] = ((above.ymode == SPLITMV) + (left.ymode == SPLITMV)) * 2 \
            + (aboveleft.ymode == SPLITMV)
        if cnt[2] > cnt[1]:
            cnt[1], cnt[2] = cnt[2], cnt[1]
            near[1], near[2] = near[2], near[1]
        if cnt[1] >= cnt[0]:
            near[0] = near[1]
        return near, cnt

    @staticmethod
    def _clamp_mv(mv, bounds):
        x, y = mv
        lo_x, hi_x, lo_y, hi_y = bounds
        return (min(max(x, lo_x), hi_x), min(max(y, lo_y), hi_y))

    def _submv_ref(self, bd, l, a):
        lez, aez, lea = (l == (0, 0)), (a == (0, 0)), (l == a)
        if lea and lez:
            ctx = 4
        elif lea:
            ctx = 3
        elif aez:
            ctx = 2
        elif lez:
            ctx = 1
        else:
            ctx = 0
        return treed_read(bd, T.SUBMV_REF_TREE, T.SUBMV_REF_PROBS2[ctx])

    def _decode_split_mv(self, bd, this, left, above, best, mvp):
        pid = treed_read(bd, T.SPLIT_MV_TREE, T.SPLIT_MV_PROBS)
        part = T.MV_PARTITIONS[pid]
        mask = 0
        j = 0
        while mask < 0xFFFF:
            k = 0
            while part[k] != j:
                k += 1
            lm = self._left_block_mv(this, left, k)
            am = self._above_block_mv(this, above, k)
            sub = self._submv_ref(bd, lm, am)
            if sub == LEFT4X4:
                mv = lm
            elif sub == ABOVE4X4:
                mv = am
            elif sub == ZERO4X4:
                mv = (0, 0)
            else:
                dx, dy = _read_mv(bd, mvp)
                mv = (dx + best[0], dy + best[1])
            for kk in range(16):
                if part[kk] == j:
                    this.smvs[kk] = mv
                    mask |= 1 << kk
            j += 1

    def _decode_mvs(self, bd, this, left, above, aboveleft, bounds):
        ent = self.entropy
        this.ref = (2 + bd.bool(self.hdr['prob_gf'])) \
            if bd.bool(self.hdr['prob_last']) else 1
        near, cnt = self._find_near_mvs(this, left, above, aboveleft,
                                        self.hdr['sign_bias'])
        probs = [T.MV_COUNTS_TO_PROBS[cnt[i]][i] for i in range(4)]
        mode = treed_read(bd, T.MV_REF_TREE, probs)
        this.ymode = mode
        this.uvmode = mode
        if mode == NEARESTMV:
            this.mv = self._clamp_mv(near[1], bounds)
        elif mode == NEARMV:
            this.mv = self._clamp_mv(near[2], bounds)
        elif mode == ZEROMV:
            this.mv = (0, 0)
        elif mode == NEWMV:
            best = self._clamp_mv(near[0], bounds)
            dx, dy = _read_mv(bd, ent['mv'])
            this.mv = (dx + best[0], dy + best[1])
        else:                              # SPLITMV
            best = self._clamp_mv(near[0], bounds)
            self._decode_split_mv(bd, this, left, above, best, ent['mv'])
            this.mv = this.smvs[15]

    def _decode_intra_mb_mode(self, bd, this):
        ent = self.entropy
        this.ymode = treed_read(bd, T.Y_MODE_TREE, ent['ymode'])
        if this.ymode == B_PRED:
            this.smodes = [treed_read(bd, T.BMODE_TREE, T.DEFAULT_B_MODE_PROBS)
                           for _ in range(16)]
        else:
            this.smodes = [_implied_bmode(this.ymode)] * 16
        this.uvmode = treed_read(bd, T.UV_MODE_TREE, ent['uvmode'])
        this.ref = CURRENT_FRAME
        this.mv = (0, 0)

    def _decode_kf_mb_mode(self, bd, this, left, above):
        this.ymode = treed_read(bd, T.KF_YMODE_TREE, T.KF_YMODE_PROB)
        if this.ymode == B_PRED:
            for i in range(16):
                a = above.smodes[i + 12] if i < 4 else this.smodes[i - 4]
                if i < 4 and above.ymode != B_PRED:
                    a = _implied_bmode(above.ymode)
                l = left.smodes[i + 3] if not (i & 3) else this.smodes[i - 1]
                if not (i & 3) and left.ymode != B_PRED:
                    l = _implied_bmode(left.ymode)
                this.smodes[i] = treed_read(bd, T.BMODE_TREE,
                                            T.KF_BMODE_PROB[a][l])
        else:
            this.smodes = [_implied_bmode(this.ymode)] * 16
        this.uvmode = treed_read(bd, T.UV_MODE_TREE, T.KF_UV_MODE_PROB)
        this.ref = CURRENT_FRAME
        this.mv = (0, 0)

    # -- main --------------------------------------------------------------
    def decode_frame(self, data, verify=True, filtered=True):
        h, bd, parts, saved, refresh_entropy = self._parse_header(data)
        self.hdr = h
        key = h['keyframe']
        if not key and not self.refs:
            raise ValueError('inter frame before any keyframe')
        mb_cols, mb_rows = self.mb_cols, self.mb_rows
        fr = Frame(h, mb_cols, mb_rows)
        fr.mb = [[None] * mb_cols for _ in range(mb_rows)]

        res = [BoolDecoder(data[o:o + s]) for o, s in parts]
        n = len(parts)
        ent = self.entropy
        coeff_probs = ent['coeff']
        skip_prob = h['prob_skip_false']
        dqs = [dequant_factors(h, s) for s in range(4)]

        above_ctx = [[0] * 9 for _ in range(mb_cols)]
        # A row of macroblock info plus a one-column left/above-left border of
        # default (intra, zero-MV) macroblocks.
        border = MBInfo()
        above_row = [border] + [MBInfo() for _ in range(mb_cols)]

        for mby in range(mb_rows):
            left_ctx = [0] * 9
            rbd = res[mby & (n - 1)]
            cur_row = [border]
            left = border

            for mbx in range(mb_cols):
                this = MBInfo()
                above = above_row[mbx + 1]
                aboveleft = above_row[mbx]

                if h['update_mb_seg_map']:
                    this.seg = self._read_segment_id(bd)
                if h['mb_no_coeff_skip']:
                    this.skip = bool(bd.bool(skip_prob))

                if key:
                    self._decode_kf_mb_mode(bd, this, left, above)
                else:
                    bounds = (-((mbx + 1) << 7), (mb_cols - mbx) << 7,
                              -((mby + 1) << 7), (mb_rows - mby) << 7)
                    if bd.bool(h['prob_intra']):
                        self._decode_mvs(bd, this, left, above, aboveleft,
                                         bounds)
                    else:
                        self._decode_intra_mb_mode(bd, this)

                self._reconstruct_mb(fr, mbx, mby, this, rbd, coeff_probs,
                                     dqs, above_ctx, left_ctx)
                fr.mb[mby][mbx] = (this.ymode, this.seg, this.has_coeffs,
                                   this.ref)
                cur_row.append(this)
                left = this

            above_row = cur_row
            for pl in (fr.y, fr.u, fr.v):
                pl.extend_right(mby * (16 if pl is fr.y else 8) +
                                (15 if pl is fr.y else 7))

        fr.partition_slack = [r.bytes_used - s for r, (o, s) in zip(res, parts)]
        if verify:
            for i, slack in enumerate(fr.partition_slack):
                if slack > 2 or slack < -2:
                    raise ValueError('partition %d ended %+d bytes from its '
                                     'boundary — token desync' % (i, slack))
        if filtered and h['loop_filter_level']:
            loop_filter(fr)

        if not refresh_entropy:
            self.entropy = saved
        self._update_refs(fr)
        return fr

    def _read_segment_id(self, bd):
        tp = self.segment.get('tree', [255, 255, 255])
        if bd.bool(tp[0]):
            return 2 + bd.bool(tp[2])
        return bd.bool(tp[1])

    def _reconstruct_mb(self, fr, mbx, mby, this, rbd, coeff_probs, dqs,
                        above_ctx, left_ctx):
        ymode = this.ymode
        has_y2 = ymode != B_PRED and ymode != SPLITMV
        coeffs = [[0] * 16 for _ in range(25)]
        dq = dqs[this.seg]
        has_coeffs = False

        if this.skip:
            for k in range(8):
                above_ctx[mbx][k] = left_ctx[k] = 0
            if has_y2:
                above_ctx[mbx][8] = left_ctx[8] = 0
        else:
            if has_y2:
                c = above_ctx[mbx][8] + left_ctx[8]
                nz = decode_coeffs(rbd, coeff_probs, 1, c, dq['y2'], coeffs[24])
                above_ctx[mbx][8] = left_ctx[8] = int(nz)
                has_coeffs |= nz
            yplane = 0 if has_y2 else 3
            for b in range(24):
                if b < 16:
                    pl, f = yplane, dq['y1']
                else:
                    pl, f = 2, dq['uv']
                c = above_ctx[mbx][ABOVE_CTX[b]] + left_ctx[LEFT_CTX[b]]
                nz = decode_coeffs(rbd, coeff_probs, pl, c, f, coeffs[b])
                above_ctx[mbx][ABOVE_CTX[b]] = int(nz)
                left_ctx[LEFT_CTX[b]] = int(nz)
                has_coeffs |= nz
        this.has_coeffs = bool(has_coeffs)

        if has_y2:
            dc = iwht4x4(coeffs[24])
            for b in range(16):
                coeffs[b][0] = dc[b]

        px, py = mbx * 16, mby * 16
        cx, cy = mbx * 8, mby * 8

        if ymode <= B_PRED:                     # intra
            have_a, have_l = mby > 0, mbx > 0
            if ymode == B_PRED:
                top_right = [fr.y.at(px + 16 + i, py - 1) for i in range(4)]
                for b in range(16):
                    bx, by = px + (b & 3) * 4, py + (b >> 2) * 4
                    ar = top_right if (b & 3) == 3 else \
                        [fr.y.at(bx + 4 + i, by - 1) for i in range(4)]
                    predict_subblock(fr.y, bx, by, this.smodes[b], ar)
                    add_residue(fr.y, bx, by, idct4x4(coeffs[b]))
            else:
                predict_block(fr.y, px, py, 16, ymode, have_a, have_l)
                for b in range(16):
                    add_residue(fr.y, px + (b & 3) * 4, py + (b >> 2) * 4,
                                idct4x4(coeffs[b]))
            for pl, base in ((fr.u, 16), (fr.v, 20)):
                predict_block(pl, cx, cy, 8, this.uvmode, have_a, have_l)
                for k in range(4):
                    add_residue(pl, cx + (k & 1) * 4, cy + (k >> 1) * 4,
                                idct4x4(coeffs[base + k]))
        else:                                   # inter
            ref = self.refs[this.ref]
            if ymode != SPLITMV:
                mvx, mvy = this.mv
                cmvx, cmvy = chroma_mv_from_luma(mvx, mvy)
                for b in range(16):
                    inter_block(fr.y, ref.y, px + (b & 3) * 4,
                                py + (b >> 2) * 4, mvx, mvy, idct4x4(coeffs[b]))
                cmvs = [(cmvx, cmvy)] * 4
            else:
                for b in range(16):
                    mvx, mvy = this.smvs[b]
                    inter_block(fr.y, ref.y, px + (b & 3) * 4,
                                py + (b >> 2) * 4, mvx, mvy, idct4x4(coeffs[b]))
                cmvs = [chroma_splitmv(this.smvs, g) for g in (0, 2, 8, 10)]
            for pl, base in ((fr.u, 16), (fr.v, 20)):
                rpl = ref.u if pl is fr.u else ref.v
                for k in range(4):
                    cmvx, cmvy = cmvs[k]
                    inter_block(pl, rpl, cx + (k & 1) * 4, cy + (k >> 1) * 4,
                                cmvx, cmvy, idct4x4(coeffs[base + k]))

    def _update_refs(self, fr):
        refresh_last, refresh_gf, refresh_arf, copy_gf, copy_arf = fr.hdr['refresh']
        if copy_arf == 1:
            self.refs[ALTREF_FRAME] = self.refs[LAST_FRAME]
        elif copy_arf == 2:
            self.refs[ALTREF_FRAME] = self.refs[GOLDEN_FRAME]
        if copy_gf == 1:
            self.refs[GOLDEN_FRAME] = self.refs[LAST_FRAME]
        elif copy_gf == 2:
            self.refs[GOLDEN_FRAME] = self.refs[ALTREF_FRAME]
        if refresh_gf:
            self.refs[GOLDEN_FRAME] = fr
        if refresh_arf:
            self.refs[ALTREF_FRAME] = fr
        if refresh_last:
            self.refs[LAST_FRAME] = fr


def _deepcopy_probs(v):
    if isinstance(v, list):
        return [_deepcopy_probs(x) for x in v]
    return v


def decode_keyframe(data, verify=True, filtered=True):
    """Decode a single VP8 keyframe to pixels. Returns a Frame.

    A thin wrapper over VP8Decoder for callers that only want the first frame;
    it asserts the frame is a keyframe."""
    tag = parse_frame_tag(data)
    if tag is None or not tag['keyframe']:
        raise ValueError('not a VP8 keyframe')
    return VP8Decoder().decode_frame(data, verify=verify, filtered=filtered)


def decode_video(frames, verify=True, filtered=True):
    """Decode a sequence of VP8 frame payloads (keyframe first) in order,
    yielding a Frame each. State carries across frames, so inter frames
    reference their predecessors."""
    dec = VP8Decoder()
    for data in frames:
        yield dec.decode_frame(data, verify=verify, filtered=filtered)


# ------------------------------------------------------------------ CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('file', help='.webm, or a raw VP8 keyframe')
    ap.add_argument('-o', '--out', help='write a PNG here')
    ap.add_argument('--frame', type=int, default=0,
                    help='which keyframe from a .webm (default 0)')
    a = ap.parse_args()

    data = open(a.file, 'rb').read()
    if data[:4] == b'\x1a\x45\xdf\xa3':
        from webm import WebM
        doc = WebM(data)
        if doc.codec != 'V_VP8':
            sys.exit('%s is %s, not VP8' % (a.file, doc.codec))
        # Not doc.frames' keyframe flag: files that wrap Block in a BlockGroup
        # carry no such flag, so the bitstream's own tag is the authority.
        from vp8 import parse_frame_tag
        keys = []
        for _, _, _, off, size in doc.frames:
            t = parse_frame_tag(data[off:off + size])
            if t and t['keyframe']:
                keys.append((off, size))
        if not keys:
            sys.exit('no keyframes in %s' % a.file)
        off, size = keys[a.frame]
        data = data[off:off + size]

    fr = decode_keyframe(data)
    print('%dx%d  %d x %d macroblocks  q=%d  loop_filter=%d'
          % (fr.width, fr.height, fr.mb_cols, fr.mb_rows,
             fr.hdr['y_ac_qi'], fr.hdr['loop_filter_level']))
    print('partition slack: %s (bytes past the declared end)'
          % fr.partition_slack)
    print('This is the first (key) frame only; use decode_video() for the '
          'whole sequence.')
    if a.out:
        from smk import write_png
        write_png(a.out, fr.width, fr.height, fr.rgb())
        print('wrote %s' % a.out)


if __name__ == '__main__':
    main()
