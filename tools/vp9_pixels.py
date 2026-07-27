#!/usr/bin/env python3
"""VP9 - stage 3b: key-frame PIXELS (intra prediction + dequantisation +
inverse transforms + reconstruction).

Continues tools/vp9_decode.py (stage 3a: the entropy decode of a key frame -
partition tree, intra modes and coefficient tokens). Stage 3a proved the
bitstream is consumed correctly but produced no pixels; this stage turns the
decoded coefficients into a reconstructed frame.

It adds, all written from the VP9 spec v0.6 prose (sections 8.5.1, 8.6, 8.7):
  * intra prediction, all ten modes (spec 8.5.1),
  * dequantisation with the dc_q / ac_q lookup tables (spec 8.6.1),
  * the 1D inverse transforms - DCT 4..32, ADST 4..16, WHT 4 - built from the
    butterfly / Hadamard primitives (spec 8.7.1), and the separable 2D
    transform (spec 8.7.2),
  * the reconstruct step: predicted + residual, clamped (spec 8.6.2).

The loop filter (spec 8.8) runs *after* reconstruction and is a separate stage;
this module produces the pre-loop-filter frame. That is directly verifiable:
the browser's libvpx applies the loop filter, but a frame whose
loop_filter_level is 0 is filtered by a no-op, so those frames give a byte-exact
oracle for reconstruction on its own - the same way VP8's unfiltered subset
validated intra prediction before the filter was written.

    from vp9_pixels import decode_keyframe
    hdr, planes = decode_keyframe(frame_bytes)   # planes = [Y, U, V] aligned

The independence rule (CLAUDE.md 6) holds: every line here is from the published
spec, transcribed by hand from its prose, with no reference to libvpx or any
other decoder. The byte-exact comparison against the browser's libvpx is what
makes that transcription checkable.
"""
import vp9
import vp9_tables as T
import vp9_decode as D
from vp9_decode import (DC_PRED, TM_PRED, DCT_DCT, ADST_DCT, DCT_ADST,
                        ADST_ADST, BLOCK_8X8, TX_4X4, TX_32X32, ZERO_TOKEN,
                        _read_tree, _pareto)

# intra mode enums (spec 6.4.x); order fixed by INTRA_MODE_TREE / MODE2TXFM
V_PRED, H_PRED = 1, 2
D45_PRED, D135_PRED, D117_PRED, D153_PRED, D207_PRED, D63_PRED = 3, 4, 5, 6, 7, 8

SINPI_1_9, SINPI_2_9, SINPI_3_9, SINPI_4_9 = 5283, 9929, 13377, 15212

# spec 8.7.1.1 - cos64_lookup[33] = round(16384 * cos(angle*pi/64))
COS64 = [16384, 16364, 16305, 16207, 16069, 15893, 15679, 15426,
         15137, 14811, 14449, 14053, 13623, 13160, 12665, 12140,
         11585, 11003, 10394, 9760, 9102, 8423, 7723, 7005,
         6270, 5520, 4756, 3981, 3196, 2404, 1606, 804, 0]


# ---- primitives (spec 8.7.1.1) ----

def _round2(x, n):
    if n == 0:
        return x
    return (x + (1 << (n - 1))) >> n


def _brev(numbits, x):
    t = 0
    for i in range(numbits):
        t |= ((x >> i) & 1) << (numbits - 1 - i)
    return t


def _cos64(angle):
    a = angle & 127
    if a <= 32:
        return COS64[a]
    if a <= 64:
        return -COS64[64 - a]
    if a <= 96:
        return -COS64[a - 64]
    return COS64[128 - a]


def _sin64(angle):
    return _cos64(angle - 32)


def _B(Tr, a, b, angle, flip):
    ca, sa = _cos64(angle), _sin64(angle)
    x = Tr[a] * ca - Tr[b] * sa
    y = Tr[a] * sa + Tr[b] * ca
    Tr[a] = _round2(x, 14)
    Tr[b] = _round2(y, 14)
    if flip:
        Tr[a], Tr[b] = Tr[b], Tr[a]


def _H(Tr, a, b, flip):
    if flip:
        a, b = b, a
    x, y = Tr[a], Tr[b]
    Tr[a] = x + y
    Tr[b] = x - y


def _SB(S, Tr, a, b, angle, flip):
    ca, sa = _cos64(angle), _sin64(angle)
    S[a] = Tr[a] * ca - Tr[b] * sa
    S[b] = Tr[a] * sa + Tr[b] * ca
    if flip:
        S[a], S[b] = S[b], S[a]


def _SH(S, Tr, a, b):
    Tr[a] = _round2(S[a] + S[b], 14)
    Tr[b] = _round2(S[a] - S[b], 14)


# ---- inverse DCT (spec 8.7.1.2 / 8.7.1.3) ----

def _idct_permute(Tr, n):
    c = Tr[:]
    for i in range(1 << n):
        Tr[i] = c[_brev(n, i)]


def _idct(Tr, n):
    n0 = 1 << n
    n1 = 1 << (n - 1)
    n2 = 1 << (n - 2)
    n3 = (1 << (n - 3)) if n >= 3 else 0
    # 1
    if n == 2:
        _B(Tr, 0, 1, 16, 1)
    else:
        _idct(Tr, n - 1)
    # 2
    for i in range(n2):
        _B(Tr, n1 + i, n0 - 1 - i, 32 - _brev(5, n1 + i), 0)
    # 3
    if n >= 3:
        for i in range(n3):
            for j in range(2):
                _H(Tr, n1 + 4 * i + 2 * j, n1 + 1 + 4 * i + 2 * j, j)
    # 4
    if n == 5:
        for i in range(2):
            for j in range(2):
                _B(Tr, n0 - n + 3 - n2 * j - 4 * i, n1 + n - 4 + n2 * j + 4 * i,
                   28 - 16 * i + 56 * j, 1)
        for i in range(2):
            for j in range(4):
                _H(Tr, n1 + n3 * j + i, n1 + n2 - 5 + n3 * j - i, j & 1)
    # 5
    if n >= 4:
        for i in range(2 if n == 5 else 1):
            for j in range(2):
                _B(Tr, n0 - n + 2 - i - n2 * j, n1 + n - 3 + i + n2 * j,
                   24 + 48 * j, 1)
        for i in range(2 * n - 6):          # i = 0..(2n-7)
            for j in range(2):
                _H(Tr, n1 + n2 * j + i, n1 + n2 - 1 + n2 * j - i, j & 1)
    # 6
    if n >= 3:
        for i in range(n3):
            _B(Tr, n0 - n3 - 1 - i, n1 + n3 + i, 16, 1)
    # 7
    for i in range(n1):
        _H(Tr, i, n0 - 1 - i, 0)


# ---- inverse ADST (spec 8.7.1.4 - 8.7.1.9) ----

def _adst_in_perm(Tr, n):
    n0 = 1 << n
    n1 = 1 << (n - 1)
    c = Tr[:]
    for i in range(n1):
        Tr[2 * i] = c[n0 - 1 - 2 * i]
        Tr[2 * i + 1] = c[2 * i]


def _adst_out_perm(Tr, n):
    c = Tr[:]
    if n == 4:
        for a in range(2):
            for b in range(2):
                for cc in range(2):
                    for d in range(2):
                        Tr[8 * a + 4 * b + 2 * cc + d] = \
                            c[8 * (d ^ cc) + 4 * (cc ^ b) + 2 * (b ^ a) + a]
    else:
        for a in range(2):
            for b in range(2):
                for cc in range(2):
                    Tr[4 * a + 2 * b + cc] = c[4 * (cc ^ b) + 2 * (b ^ a) + a]


def _iadst4(Tr):
    s0 = SINPI_1_9 * Tr[0]
    s1 = SINPI_2_9 * Tr[0]
    s2 = SINPI_3_9 * Tr[1]
    s3 = SINPI_4_9 * Tr[2]
    s4 = SINPI_1_9 * Tr[2]
    s5 = SINPI_2_9 * Tr[3]
    s6 = SINPI_4_9 * Tr[3]
    v = Tr[0] - Tr[2] + Tr[3]
    s7 = SINPI_3_9 * v
    x0 = s0 + s3 + s5
    x1 = s1 - s4 - s6
    x2 = s7
    x3 = s2
    s0 = x0 + x3
    s1 = x1 + x3
    s2 = x2
    s3 = x0 + x1 - x3
    Tr[0] = _round2(s0, 14)
    Tr[1] = _round2(s1, 14)
    Tr[2] = _round2(s2, 14)
    Tr[3] = _round2(s3, 14)


def _iadst8(Tr):
    S = [0] * 8
    _adst_in_perm(Tr, 3)
    for i in range(4):
        _SB(S, Tr, 2 * i, 1 + 2 * i, 30 - 8 * i, 1)
    for i in range(4):
        _SH(S, Tr, i, 4 + i)
    for i in range(2):
        _SB(S, Tr, 4 + 3 * i, 5 + i, 24 - 16 * i, 1)
    for i in range(2):
        _SH(S, Tr, 4 + i, 6 + i)
    for i in range(2):
        _H(Tr, i, 2 + i, 0)
    for i in range(2):
        _B(Tr, 2 + 4 * i, 3 + 4 * i, 16, 1)
    _adst_out_perm(Tr, 3)
    for i in range(4):
        Tr[1 + 2 * i] = -Tr[1 + 2 * i]


def _iadst16(Tr):
    S = [0] * 16
    _adst_in_perm(Tr, 4)
    for i in range(8):
        _SB(S, Tr, 2 * i, 1 + 2 * i, 31 - 4 * i, 1)
    for i in range(8):
        _SH(S, Tr, i, 8 + i)
    for i in range(4):
        _SB(S, Tr, 8 + 2 * i, 9 + 2 * i, 28 - 16 * i, 1)
    for i in range(4):
        _SH(S, Tr, 8 + i, 12 + i)
    for i in range(4):
        _H(Tr, i, 4 + i, 0)
    for i in range(2):
        for j in range(2):
            _SB(S, Tr, 4 + 8 * i + 3 * j, 5 + 8 * i + j, 24 - 16 * j, 1)
    for i in range(2):
        for j in range(2):
            _SH(S, Tr, 4 + 8 * j + i, 6 + 8 * j + i)
    for i in range(2):
        for j in range(2):
            _H(Tr, 8 * j + i, 2 + 8 * j + i, 0)
    for i in range(2):
        for j in range(2):
            _B(Tr, 2 + 4 * j + 8 * i, 3 + 4 * j + 8 * i, 48 + 64 * (i ^ j), 0)
    _adst_out_perm(Tr, 4)
    for i in range(2):
        for j in range(2):
            Tr[1 + 12 * j + 2 * i] = -Tr[1 + 12 * j + 2 * i]


def _iadst(Tr, n):
    if n == 2:
        _iadst4(Tr)
    elif n == 3:
        _iadst8(Tr)
    else:
        _iadst16(Tr)


def _iwht(Tr, shift):
    a = Tr[0] >> shift
    c = Tr[1] >> shift
    d = Tr[2] >> shift
    b = Tr[3] >> shift
    a += c
    d -= b
    e = (a - d) >> 1
    b = e - b
    c = e - c
    a -= b
    d += c
    Tr[0], Tr[1], Tr[2], Tr[3] = a, b, c, d


def _inverse_transform_2d(Dequant, n, tx_type, lossless):
    """spec 8.7.2 - separable 2D inverse transform, in place on Dequant."""
    n0 = 1 << n
    # row transforms
    for i in range(n0):
        row = Dequant[i]
        Tr = list(row)
        if lossless:
            _iwht(Tr, 2)
        elif tx_type in (DCT_DCT, ADST_DCT):
            _idct_permute(Tr, n)
            _idct(Tr, n)
        else:
            _iadst(Tr, n)
        Dequant[i] = Tr
    # column transforms
    sh = min(6, n + 2)
    for j in range(n0):
        Tr = [Dequant[i][j] for i in range(n0)]
        if lossless:
            _iwht(Tr, 0)
        elif tx_type in (DCT_DCT, DCT_ADST):
            _idct_permute(Tr, n)
            _idct(Tr, n)
        else:
            _iadst(Tr, n)
        if lossless:
            for i in range(n0):
                Dequant[i][j] = Tr[i]
        else:
            for i in range(n0):
                Dequant[i][j] = _round2(Tr[i], sh)


def _trunc_div(a, b):
    """Integer division truncating toward zero (spec '/' operator)."""
    if b == 1:
        return a
    q = abs(a) // b
    return q if a >= 0 else -q


# ---- pixel decoder ----

class _PixelDecoder(D._KeyFrameDecoder):
    def __init__(self, hdr, probs):
        super().__init__(hdr, probs)
        self.bit_depth = hdr.get('bit_depth', 8)
        self.lossless = hdr.get('lossless', False)
        # dequant values per plane (spec 8.6.1)
        base = hdr['base_q_idx']
        bd_idx = (self.bit_depth - 8) >> 1
        dyc = hdr.get('delta_q_y_dc', 0)
        duc = hdr.get('delta_q_uv_dc', 0)
        dua = hdr.get('delta_q_uv_ac', 0)

        def dcq(b):
            return T.DC_QLOOKUP[bd_idx][max(0, min(255, b))]

        def acq(b):
            return T.AC_QLOOKUP[bd_idx][max(0, min(255, b))]

        self.dc_quant = [dcq(base + dyc), dcq(base + duc), dcq(base + duc)]
        self.ac_quant = [acq(base), acq(base + dua), acq(base + dua)]
        # Reconstructed planes. Sized to the *superblock*-aligned dimensions,
        # not just MiCols*8: VP9 partitions cover whole 64x64 superblocks, so a
        # transform block whose top-left is on-screen can straddle the frame
        # edge and write into the off-screen remainder (rows >= MiRows*8). Those
        # samples are never read (prediction clamps to MiCols*8-1) nor output
        # (cropped), but the buffer must hold them or the write goes OOB.
        aw = ((self.mi_cols + 7) & ~7) * 8
        ah = ((self.mi_rows + 7) & ~7) * 8
        self.cur = []
        for pl in range(3):
            sx = self.sub_x if pl > 0 else 0
            sy = self.sub_y if pl > 0 else 0
            self.cur.append([[0] * (aw >> sx) for _ in range(ah >> sy)])

    # override: produce pixels (predict + tokens + reconstruct)
    def _residual(self, bd):
        bsize = BLOCK_8X8 if self.MiSize < BLOCK_8X8 else self.MiSize
        for plane in range(3):
            txsz = self._uv_tx_size() if plane > 0 else self.tx_size
            step = 1 << txsz
            plane_sz = self._plane_block_size(bsize, plane)
            n4w = T.NUM_4X4_W[plane_sz]
            n4h = T.NUM_4X4_H[plane_sz]
            subx = self.sub_x if plane > 0 else 0
            suby = self.sub_y if plane > 0 else 0
            base_x = (self.MiCol * 8) >> subx
            base_y = (self.MiRow * 8) >> suby
            maxx = (self.mi_cols * 8) >> subx
            maxy = (self.mi_rows * 8) >> suby
            block_idx = 0
            y = 0
            while y < n4h:
                x = 0
                while x < n4w:
                    start_x = base_x + 4 * x
                    start_y = base_y + 4 * y
                    nonzero = 0
                    if start_x < maxx and start_y < maxy:
                        self._predict_intra(plane, start_x, start_y,
                                            self.AvailL or x > 0,
                                            self.AvailU or y > 0,
                                            (x + step) < n4w, txsz, block_idx)
                        if not self.skip:
                            nonzero = self._tokens(bd, plane, start_x, start_y,
                                                   txsz, block_idx)
                            self._reconstruct(plane, start_x, start_y, txsz)
                    for i in range(step):
                        self.above_nz[plane][(start_x >> 2) + i] = nonzero
                        self.left_nz[plane][(start_y >> 2) + i] = nonzero
                    block_idx += 1
                    x += step
                y += step

    # override tokens: keep the coefficient values (self.Tokens) and TxType
    def _tokens(self, bd, plane, start_x, start_y, txsz, block_idx):
        seg_eob = 16 << (txsz << 1)
        tx_type = self._tx_type(plane, txsz, block_idx)
        self.TxType = tx_type
        scan = self._get_scan(tx_type, txsz)
        self.Tokens = [0] * seg_eob
        n = 4 << txsz
        pl_type = 1 if plane > 0 else 0
        cbook = self.p.coef[txsz][pl_type][0]
        token_cache = [0] * seg_eob
        check_eob = 1
        c = 0
        subx = self.sub_x if plane > 0 else 0
        suby = self.sub_y if plane > 0 else 0
        maxX = (2 * self.mi_cols) >> subx
        maxY = (2 * self.mi_rows) >> suby
        x4 = start_x >> 2
        y4 = start_y >> 2
        while c < seg_eob:
            pos = scan[c]
            band = T.COEFBAND_4X4[c] if txsz == TX_4X4 else T.COEFBAND_8X8PLUS[c]
            if c == 0:
                numpts = 1 << txsz
                above = left = 0
                for i in range(numpts):
                    if x4 + i < maxX:
                        above |= self.above_nz[plane][x4 + i]
                    if y4 + i < maxY:
                        left |= self.left_nz[plane][y4 + i]
                ctx = above + left
            else:
                nb0, nb1 = self._neighbors(pos, n, tx_type)
                ctx = (1 + token_cache[nb0] + token_cache[nb1]) >> 1
            probs = cbook[band][ctx]
            if check_eob:
                if not bd.read_bool(probs[0]):
                    break
            token = _read_tree(bd, T.TOKEN_TREE,
                               lambda nd: _pareto(nd, probs[min(2, 1 + nd)]))
            token_cache[pos] = T.ENERGY_CLASS[token]
            if token == ZERO_TOKEN:
                self.Tokens[pos] = 0
                check_eob = 0
            else:
                coef = self._read_coef(bd, token)
                sign = bd.read_literal(1)
                self.Tokens[pos] = -coef if sign else coef
                check_eob = 1
            c += 1
        return 1 if c > 0 else 0

    # spec 8.6.2 reconstruct
    def _reconstruct(self, plane, x, y, txsz):
        dq_denom = 2 if txsz == TX_32X32 else 1
        n = 2 + txsz
        n0 = 1 << n
        acq = self.ac_quant[plane]
        dcq = self.dc_quant[plane]
        tok = self.Tokens
        Dequant = [[0] * n0 for _ in range(n0)]
        for i in range(n0):
            row = Dequant[i]
            base = i * n0
            for j in range(n0):
                row[j] = _trunc_div(tok[base + j] * acq, dq_denom)
        Dequant[0][0] = _trunc_div(tok[0] * dcq, dq_denom)
        _inverse_transform_2d(Dequant, n, self.TxType, self.lossless)
        frame = self.cur[plane]
        maxv = (1 << self.bit_depth) - 1
        for i in range(n0):
            frow = frame[y + i]
            drow = Dequant[i]
            for j in range(n0):
                v = frow[x + j] + drow[j]
                frow[x + j] = 0 if v < 0 else (maxv if v > maxv else v)

    # spec 8.5.1 intra prediction
    def _predict_intra(self, plane, x, y, have_left, have_above,
                       not_on_right, txsz, block_idx):
        frame = self.cur[plane]
        bd = self.bit_depth
        if plane > 0:
            mode = self.uv_mode
        elif self.MiSize >= BLOCK_8X8:
            mode = self.y_mode
        else:
            mode = self.sub_mode[block_idx]
        log2size = txsz + 2
        size = 1 << log2size
        subx = self.sub_x if plane > 0 else 0
        suby = self.sub_y if plane > 0 else 0
        maxX = ((self.mi_cols * 8) >> subx) - 1
        maxY = ((self.mi_rows * 8) >> suby) - 1
        half = 1 << (bd - 1)
        # aboveRow: store with +1 offset so A[k+1] == aboveRow[k], k = -1..2size-1
        A = [0] * (2 * size + 1)
        if not have_above:
            for i in range(size):
                A[i + 1] = half - 1
        else:
            arow = frame[y - 1]
            for i in range(size):
                A[i + 1] = arow[min(maxX, x + i)]
        if have_above and not_on_right and txsz == 0:
            arow = frame[y - 1]
            for i in range(size, 2 * size):
                A[i + 1] = arow[min(maxX, x + i)]
        else:
            for i in range(size, 2 * size):
                A[i + 1] = A[size]           # = aboveRow[size-1]
        if have_above and have_left:
            A[0] = frame[y - 1][min(maxX, x - 1)]
        elif have_above:
            A[0] = half + 1
        else:
            A[0] = half - 1
        L = [0] * size
        if have_left:
            for i in range(size):
                L[i] = frame[min(maxY, y + i)][x - 1]
        else:
            for i in range(size):
                L[i] = half + 1

        def ar(k):
            return A[k + 1]

        pred = [[0] * size for _ in range(size)]
        if mode == V_PRED:
            for i in range(size):
                for j in range(size):
                    pred[i][j] = ar(j)
        elif mode == H_PRED:
            for i in range(size):
                Li = L[i]
                for j in range(size):
                    pred[i][j] = Li
        elif mode == D207_PRED:
            for j in range(size):
                pred[size - 1][j] = L[size - 1]
            for i in range(size - 1):
                pred[i][0] = _round2(L[i] + L[i + 1], 1)
            for i in range(size - 2):
                pred[i][1] = _round2(L[i] + 2 * L[i + 1] + L[i + 2], 2)
            if size >= 2:
                pred[size - 2][1] = _round2(L[size - 2] + 3 * L[size - 1], 2)
            for i in range(size - 2, -1, -1):
                for j in range(2, size):
                    pred[i][j] = pred[i + 1][j - 2]
        elif mode == D45_PRED:
            for i in range(size):
                for j in range(size):
                    if i + j + 2 < size * 2:
                        pred[i][j] = _round2(ar(i + j) + 2 * ar(i + j + 1)
                                             + ar(i + j + 2), 2)
                    else:
                        pred[i][j] = ar(2 * size - 1)
        elif mode == D63_PRED:
            for i in range(size):
                for j in range(size):
                    k = i // 2 + j
                    if i & 1:
                        pred[i][j] = _round2(ar(k) + 2 * ar(k + 1) + ar(k + 2), 2)
                    else:
                        pred[i][j] = _round2(ar(k) + ar(k + 1), 1)
        elif mode == D117_PRED:
            for j in range(size):
                pred[0][j] = _round2(ar(j - 1) + ar(j), 1)
            pred[1][0] = _round2(L[0] + 2 * ar(-1) + ar(0), 2)
            for j in range(1, size):
                pred[1][j] = _round2(ar(j - 2) + 2 * ar(j - 1) + ar(j), 2)
            if size >= 3:
                pred[2][0] = _round2(ar(-1) + 2 * L[0] + L[1], 2)
            for i in range(3, size):
                pred[i][0] = _round2(L[i - 3] + 2 * L[i - 2] + L[i - 1], 2)
            for i in range(2, size):
                for j in range(1, size):
                    pred[i][j] = pred[i - 2][j - 1]
        elif mode == D135_PRED:
            pred[0][0] = _round2(L[0] + 2 * ar(-1) + ar(0), 2)
            for j in range(1, size):
                pred[0][j] = _round2(ar(j - 2) + 2 * ar(j - 1) + ar(j), 2)
            if size >= 2:
                pred[1][0] = _round2(ar(-1) + 2 * L[0] + L[1], 2)
            for i in range(2, size):
                pred[i][0] = _round2(L[i - 2] + 2 * L[i - 1] + L[i], 2)
            for i in range(1, size):
                for j in range(1, size):
                    pred[i][j] = pred[i - 1][j - 1]
        elif mode == D153_PRED:
            pred[0][0] = _round2(L[0] + ar(-1), 1)
            for i in range(1, size):
                pred[i][0] = _round2(L[i - 1] + L[i], 1)
            if size >= 2:
                pred[0][1] = _round2(L[0] + 2 * ar(-1) + ar(0), 2)
                pred[1][1] = _round2(ar(-1) + 2 * L[0] + L[1], 2)
            for i in range(2, size):
                pred[i][1] = _round2(L[i - 2] + 2 * L[i - 1] + L[i], 2)
            for j in range(2, size):
                pred[0][j] = _round2(ar(j - 3) + 2 * ar(j - 2) + ar(j - 1), 2)
            for i in range(1, size):
                for j in range(2, size):
                    pred[i][j] = pred[i - 1][j - 2]
        elif mode == TM_PRED:
            am1 = ar(-1)
            for i in range(size):
                Li = L[i]
                for j in range(size):
                    v = ar(j) + Li - am1
                    pred[i][j] = 0 if v < 0 else ((1 << bd) - 1 if v > (1 << bd) - 1 else v)
        else:                                # DC_PRED
            if have_left and have_above:
                s = 0
                for k in range(size):
                    s += L[k] + ar(k)
                avg = (s + size) >> (log2size + 1)
            elif have_left:
                s = sum(L)
                avg = (s + (1 << (log2size - 1))) >> log2size
            elif have_above:
                s = 0
                for k in range(size):
                    s += ar(k)
                avg = (s + (1 << (log2size - 1))) >> log2size
            else:
                avg = 1 << (bd - 1)
            for i in range(size):
                for j in range(size):
                    pred[i][j] = avg
        for i in range(size):
            frow = frame[y + i]
            prow = pred[i]
            for j in range(size):
                frow[x + j] = prow[j]

    # -- loop filter (spec 8.8), key-frame form --
    def _uv_tx_size_of(self, mi_size, tx_size):
        if mi_size < BLOCK_8X8:
            return TX_4X4
        return min(tx_size, T.MAX_TXSIZE[T.SS_SIZE_LOOKUP[mi_size][self.sub_x][self.sub_y]])

    def _filter_size(self, txsz, is32, pass_, x, y, subx, suby):
        if txsz == TX_4X4 and is32:
            base = TX_8X8
        else:
            base = min(TX_16X16, txsz)
        if (pass_ == 0 and subx == 1 and base == TX_16X16
                and (x >> 3) == self.mi_cols - 1):
            return TX_8X8
        if (pass_ == 1 and suby == 1 and base == TX_16X16
                and (y >> 3) == self.mi_rows - 1):
            return TX_8X8
        return base

    def _loop_filter(self):
        h = self.h
        level = h['loop_filter_level']
        if level == 0:
            return
        sharp = h['loop_filter_sharpness']
        # key frame: segment 0, ref INTRA_FRAME, modeType 0 -> one lvl value.
        n_shift = level >> 5
        if h['loop_filter_delta_enabled']:
            lvl = _clip3(0, 63, level + (h['loop_filter_ref_deltas'][0] << n_shift))
        else:
            lvl = level
        if lvl <= 0:
            return
        shift = 2 if sharp > 4 else (1 if sharp > 0 else 0)
        if sharp > 0:
            limit = _clip3(1, 9 - sharp, lvl >> shift)
        else:
            limit = max(1, lvl >> shift)
        blimit = 2 * (lvl + 2) + limit
        thresh = lvl >> 4
        bd = self.bit_depth
        for row in range(0, self.mi_rows, 8):
            for col in range(0, self.mi_cols, 8):
                for plane in range(3):
                    self._sb_loop_filter(plane, 0, row, col, limit, blimit, thresh, bd)
                    self._sb_loop_filter(plane, 1, row, col, limit, blimit, thresh, bd)

    def _sb_loop_filter(self, plane, pass_, row, col, limit, blimit, thresh, bd):
        frame = self.cur[plane]
        if plane == 0:
            subx = suby = 0
        else:
            subx, suby = self.sub_x, self.sub_y
        if pass_ == 0:
            dx, dy, sub, edge_len = 1, 0, subx, 64 >> suby
        else:
            dx, dy, sub, edge_len = 0, 1, suby, 64 >> subx
        for edge in range(16 >> sub):
            for i in range(edge_len):
                if pass_ == 0:
                    x = col * 8 + edge * (4 << subx)
                    y = row * 8 + (i << suby)
                else:
                    x = col * 8 + (i << subx)
                    y = row * 8 + edge * (4 << suby)
                # onScreen: off-grid or first row/col edge -> not filtered
                if x >= 8 * self.mi_cols or y >= 8 * self.mi_rows:
                    continue
                if pass_ == 0 and x == 0:
                    continue
                if pass_ == 1 and y == 0:
                    continue
                loop_col = ((x >> 3) >> subx) << subx
                loop_row = ((y >> 3) >> suby) << suby
                mi_size = self.mi_sizes[loop_row][loop_col]
                tx_size = self.tx_sizes[loop_row][loop_col]
                txsz = self._uv_tx_size_of(mi_size, tx_size) if plane > 0 else tx_size
                sb_size = mi_size if sub == 0 else max(BLOCK_16X16, mi_size)
                if pass_ == 0:
                    is_block_edge = 1 if x % (8 * T.NUM_8X8_W[sb_size]) == 0 else 0
                else:
                    is_block_edge = 1 if y % (8 * T.NUM_8X8_H[sb_size]) == 0 else 0
                if (pass_ == 1 and subx == 1 and (self.mi_cols & 1)
                        and (edge & 1) and (x + 8) >= self.mi_cols * 8):
                    is_tx_edge = 0
                elif edge % (1 << txsz) == 0:
                    is_tx_edge = 1
                else:
                    is_tx_edge = 0
                is32 = 1 if edge % 8 == 0 else 0
                # key frame: isIntra always 1, so a tx edge always applies
                if not (is_block_edge or is_tx_edge):
                    continue
                fs = self._filter_size(txsz, is32, pass_, x, y, subx, suby)
                _lf_sample(frame, x >> subx, y >> suby, limit, blimit, thresh,
                           dx, dy, fs, bd)


# ---- loop filter (spec 8.8) ----

TX_8X8, TX_16X16 = 1, 2
BLOCK_16X16 = 6


def _clip3(lo, hi, v):
    return lo if v < lo else (hi if v > hi else v)


def _lf_narrow(frame, x, y, dx, dy, hev, bd):
    """Narrow filter (spec 8.8.5.2)."""
    half = 0x80 << (bd - 8)
    lim = 1 << (bd - 1)

    def cl(v):
        return -lim if v < -lim else (lim - 1 if v > lim - 1 else v)

    q0 = frame[y][x]
    q1 = frame[y + dy][x + dx]
    p0 = frame[y - dy][x - dx]
    p1 = frame[y - dy * 2][x - dx * 2]
    ps1 = p1 - half
    ps0 = p0 - half
    qs0 = q0 - half
    qs1 = q1 - half
    filt = cl(ps1 - qs1) if hev else 0
    filt = cl(filt + 3 * (qs0 - ps0))
    filter1 = cl(filt + 4) >> 3
    filter2 = cl(filt + 3) >> 3
    frame[y][x] = cl(qs0 - filter1) + half
    frame[y - dy][x - dx] = cl(ps0 + filter2) + half
    if not hev:
        f = _round2(filter1, 1)
        frame[y + dy][x + dx] = cl(qs1 - f) + half
        frame[y - dy * 2][x - dx * 2] = cl(ps1 + f) + half


def _lf_wide(frame, x, y, dx, dy, log2size):
    """Wide filter (spec 8.8.5.3): low-pass over 2n+1 taps."""
    n = (1 << (log2size - 1)) - 1
    F = {}
    for i in range(-n, n):
        t = frame[y + i * dy][x + i * dx]
        for j in range(-n, n + 1):
            p = _clip3(-(n + 1), n, i + j)
            t += frame[y + p * dy][x + p * dx]
        F[i] = _round2(t, log2size)
    for i in range(-n, n):
        frame[y + i * dy][x + i * dx] = F[i]


def _lf_sample(frame, x, y, limit, blimit, thresh, dx, dy, filter_size, bd):
    """Filter mask (spec 8.8.5.1) then the selected filter (8.8.5)."""
    def S(k):
        return frame[y + dy * k][x + dx * k]
    # q0..q3 / p0..p3 are always in-bounds at an applied edge; q4..q7 / p4..p7
    # are read (and are only in-bounds) when filterSize == TX_16X16.
    q = [S(k) for k in range(4)]
    p = [S(-1 - k) for k in range(4)]
    if filter_size >= TX_16X16:
        q += [S(k) for k in range(4, 8)]
        p += [S(-1 - k) for k in range(4, 8)]
    tb = thresh << (bd - 8)
    hev = 1 if (abs(p[1] - p[0]) > tb or abs(q[1] - q[0]) > tb) else 0
    lb = limit << (bd - 8)
    bb = blimit << (bd - 8)
    m = (abs(p[3] - p[2]) > lb or abs(p[2] - p[1]) > lb or abs(p[1] - p[0]) > lb
         or abs(q[1] - q[0]) > lb or abs(q[2] - q[1]) > lb
         or abs(q[3] - q[2]) > lb
         or abs(p[0] - q[0]) * 2 + abs(p[1] - q[1]) // 2 > bb)
    if m:
        return                                # filterMask == 0
    thr = 1 << (bd - 8)
    flat = 0
    if filter_size >= TX_8X8:
        flat = 0 if (abs(p[1] - p[0]) > thr or abs(q[1] - q[0]) > thr
                     or abs(p[2] - p[0]) > thr or abs(q[2] - q[0]) > thr
                     or abs(p[3] - p[0]) > thr or abs(q[3] - q[0]) > thr) else 1
    flat2 = 0
    if filter_size >= TX_16X16:
        flat2 = 0 if any(abs(p[k] - p[0]) > thr or abs(q[k] - q[0]) > thr
                         for k in (4, 5, 6, 7)) else 1
    if filter_size == TX_4X4 or flat == 0:
        _lf_narrow(frame, x, y, dx, dy, hev, bd)
    elif filter_size == TX_8X8 or flat2 == 0:
        _lf_wide(frame, x, y, dx, dy, 3)
    else:
        _lf_wide(frame, x, y, dx, dy, 4)


def decode_keyframe(data, lo=0, hi=None):
    """Decode a VP9 key frame to reconstructed (pre-loop-filter) planes.

    Returns (hdr, [Y, U, V]) where each plane is a 2D list of ints aligned to
    (MiCols*8) x (MiRows*8), chroma shifted by the subsampling. The caller crops
    to hdr['width'] x hdr['height'] (chroma sub-sampled). Raises on a frame this
    stage does not handle."""
    if hi is None:
        hi = len(data)
    h = vp9.VP9HeaderParser().parse(data[lo:hi])
    if h is None or 'show_existing' in h:
        raise ValueError('not a decodable frame')
    if not h.get('keyframe'):
        raise ValueError('stage 3b is key-frame only')
    probs = D.Probs(h, data, lo + h['uncompressed_bytes'])
    if probs.pad != 0:
        raise ValueError('compressed header desync (pad=%d)' % probs.pad)

    dec = _PixelDecoder(h, probs)
    tile_start = lo + h['uncompressed_bytes'] + h['header_size_in_bytes']
    tile_cols = 1 << h['tile_cols_log2']
    tile_rows = 1 << h['tile_rows_log2']
    mi_rows, mi_cols = dec.mi_rows, dec.mi_cols
    pos = tile_start
    for tr in range(tile_rows):
        for tc in range(tile_cols):
            last = (tr == tile_rows - 1) and (tc == tile_cols - 1)
            if last:
                size = hi - pos
            else:
                size = int.from_bytes(data[pos:pos + 4], 'big')
                pos += 4
            r0 = D._tile_offset(tr, mi_rows, h['tile_rows_log2'])
            r1 = D._tile_offset(tr + 1, mi_rows, h['tile_rows_log2'])
            c0 = D._tile_offset(tc, mi_cols, h['tile_cols_log2'])
            c1 = D._tile_offset(tc + 1, mi_cols, h['tile_cols_log2'])
            bd = vp9.BoolDecoder(data, pos, size)
            for pl in range(3):
                dec.above_nz[pl] = [0] * len(dec.above_nz[pl])
            dec.above_part = [0] * len(dec.above_part)
            dec.decode_tile(bd, r0, r1, c0, c1)
            pos += size
    dec._loop_filter()                        # spec 8.8; no-op if level == 0
    return h, dec.cur


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('file', help='.webm')
    ap.add_argument('--frame', type=int, default=0)
    a = ap.parse_args()
    data = open(a.file, 'rb').read()
    from webm import WebM
    doc = WebM(data)
    keys = []
    for _, _, _, off, size in doc.frames:
        blk = data[off:off + size]
        for lo, hi in vp9.superframe_split(blk):
            keys.append((off + lo, off + hi))
    lo, hi = keys[a.frame]
    h, planes = decode_keyframe(data, lo, hi)
    w, ht = h['width'], h['height']
    y = planes[0]
    print('key frame %dx%d, lf=%d, q=%d, profile %d'
          % (w, ht, h['loop_filter_level'], h['base_q_idx'], h['profile']))
    print('Y[0][:8] =', y[0][:8])
    print('Y mean =', sum(sum(r[:w]) for r in y[:ht]) / (w * ht))


if __name__ == '__main__':
    main()
