#!/usr/bin/env python3
"""VP9 - stage 5 Phase B: inter-frame PIXELS (motion compensation + compound +
reconstruction + inter loop filter) over a whole sequence.

Builds on vp9_inter.py (Phase A: inter entropy) and vp9_pixels.py (key-frame
pixels + loop filter). Adds:
  * inter prediction: 8-tap sub-pixel motion compensation (spec 8.5.2.4), MV
    selection / clamping / scaling (8.5.2.1-3), compound averaging,
  * reconstruction of inter blocks (residual added to the motion-compensated
    prediction, reusing the dequant + inverse transforms from vp9_pixels),
  * a reference-frame store, and the general (non-key-frame) loop filter with
    ref/mode level deltas.

This is also the debugging oracle for Phase A: reconstructed shown frames are
compared byte-for-byte against a reference decoder (PyAV / ffmpeg's libvpx,
`pip install av`) - the first differing block pinpoints where the entropy decode
diverged. All from VP9 spec v0.6; no other decoder's algorithm consulted.
"""
import vp9
import vp9_tables as T
import vp9_pixels as P
import vp9_inter as I
from vp9_pixels import _round2, _clip3, _trunc_div
from vp9_inter import (NONE, INTRA_FRAME, LAST_FRAME, NEARESTMV, NEARMV, NEWMV,
                       ZEROMV, BLOCK_8X8)

REF_SCALE_SHIFT = 14
SUBPEL_BITS = 4
SUBPEL_SHIFTS = 16
SUBPEL_MASK = 15
INTERP_EXTEND = 4
MI_SIZE = 8

# spec 8.5.2.4 subpel_filters[4][16][8]: EIGHTTAP, EIGHTTAP_SMOOTH,
# EIGHTTAP_SHARP, BILINEAR
SUBPEL_FILTERS = [
    [[0, 0, 0, 128, 0, 0, 0, 0], [0, 1, -5, 126, 8, -3, 1, 0],
     [-1, 3, -10, 122, 18, -6, 2, 0], [-1, 4, -13, 118, 27, -9, 3, -1],
     [-1, 4, -16, 112, 37, -11, 4, -1], [-1, 5, -18, 105, 48, -14, 4, -1],
     [-1, 5, -19, 97, 58, -16, 5, -1], [-1, 6, -19, 88, 68, -18, 5, -1],
     [-1, 6, -19, 78, 78, -19, 6, -1], [-1, 5, -18, 68, 88, -19, 6, -1],
     [-1, 5, -16, 58, 97, -19, 5, -1], [-1, 4, -14, 48, 105, -18, 5, -1],
     [-1, 4, -11, 37, 112, -16, 4, -1], [-1, 3, -9, 27, 118, -13, 4, -1],
     [0, 2, -6, 18, 122, -10, 3, -1], [0, 1, -3, 8, 126, -5, 1, 0]],
    [[0, 0, 0, 128, 0, 0, 0, 0], [-3, -1, 32, 64, 38, 1, -3, 0],
     [-2, -2, 29, 63, 41, 2, -3, 0], [-2, -2, 26, 63, 43, 4, -4, 0],
     [-2, -3, 24, 62, 46, 5, -4, 0], [-2, -3, 21, 60, 49, 7, -4, 0],
     [-1, -4, 18, 59, 51, 9, -4, 0], [-1, -4, 16, 57, 53, 12, -4, -1],
     [-1, -4, 14, 55, 55, 14, -4, -1], [-1, -4, 12, 53, 57, 16, -4, -1],
     [0, -4, 9, 51, 59, 18, -4, -1], [0, -4, 7, 49, 60, 21, -3, -2],
     [0, -4, 5, 46, 62, 24, -3, -2], [0, -4, 4, 43, 63, 26, -2, -2],
     [0, -3, 2, 41, 63, 29, -2, -2], [0, -3, 1, 38, 64, 32, -1, -3]],
    [[0, 0, 0, 128, 0, 0, 0, 0], [-1, 3, -7, 127, 8, -3, 1, 0],
     [-2, 5, -13, 125, 17, -6, 3, -1], [-3, 7, -17, 121, 27, -10, 5, -2],
     [-4, 9, -20, 115, 37, -13, 6, -2], [-4, 10, -23, 108, 48, -16, 8, -3],
     [-4, 10, -24, 100, 59, -19, 9, -3], [-4, 11, -24, 90, 70, -21, 10, -4],
     [-4, 11, -23, 80, 80, -23, 11, -4], [-4, 10, -21, 70, 90, -24, 11, -4],
     [-3, 9, -19, 59, 100, -24, 10, -4], [-3, 8, -16, 48, 108, -23, 10, -4],
     [-2, 6, -13, 37, 115, -20, 9, -4], [-2, 5, -10, 27, 121, -17, 7, -3],
     [-1, 3, -6, 17, 125, -13, 5, -2], [0, 1, -3, 8, 127, -7, 3, -1]],
    [[0, 0, 0, 128, 0, 0, 0, 0], [0, 0, 0, 120, 8, 0, 0, 0],
     [0, 0, 0, 112, 16, 0, 0, 0], [0, 0, 0, 104, 24, 0, 0, 0],
     [0, 0, 0, 96, 32, 0, 0, 0], [0, 0, 0, 88, 40, 0, 0, 0],
     [0, 0, 0, 80, 48, 0, 0, 0], [0, 0, 0, 72, 56, 0, 0, 0],
     [0, 0, 0, 64, 64, 0, 0, 0], [0, 0, 0, 56, 72, 0, 0, 0],
     [0, 0, 0, 48, 80, 0, 0, 0], [0, 0, 0, 40, 88, 0, 0, 0],
     [0, 0, 0, 32, 96, 0, 0, 0], [0, 0, 0, 24, 104, 0, 0, 0],
     [0, 0, 0, 16, 112, 0, 0, 0], [0, 0, 0, 8, 120, 0, 0, 0]],
]


def _round_q2(v):
    return _trunc_div(v - 1 if v < 0 else v + 1, 2)


def _round_q4(v):
    return _trunc_div(v - 2 if v < 0 else v + 2, 4)


class _FramePixelDecoder(I._FrameDecoder):
    def __init__(self, hdr, probs, frame_is_intra, prev, store):
        super().__init__(hdr, probs, frame_is_intra, prev)
        self.bit_depth = hdr.get('bit_depth', 8)
        self.lossless = hdr.get('lossless', False)
        base = hdr['base_q_idx']
        bd_idx = (self.bit_depth - 8) >> 1
        dyc = hdr.get('delta_q_y_dc', 0)
        duc = hdr.get('delta_q_uv_dc', 0)
        dua = hdr.get('delta_q_uv_ac', 0)
        self.dc_quant = [T.DC_QLOOKUP[bd_idx][max(0, min(255, base + dyc))],
                         T.DC_QLOOKUP[bd_idx][max(0, min(255, base + duc))],
                         T.DC_QLOOKUP[bd_idx][max(0, min(255, base + duc))]]
        self.ac_quant = [T.AC_QLOOKUP[bd_idx][max(0, min(255, base))],
                         T.AC_QLOOKUP[bd_idx][max(0, min(255, base + dua))],
                         T.AC_QLOOKUP[bd_idx][max(0, min(255, base + dua))]]
        aw = ((self.mi_cols + 7) & ~7) * 8
        ah = ((self.mi_rows + 7) & ~7) * 8
        self.cur = []
        for pl in range(3):
            sx = self.sub_x if pl > 0 else 0
            sy = self.sub_y if pl > 0 else 0
            self.cur.append([[0] * (aw >> sx) for _ in range(ah >> sy)])
        self.store = store                    # FrameStore: 8 slots or None
        self.ref_frame_idx = hdr.get('ref_frame_idx', [0, 0, 0])
        self.ref_w = [s['w'] if s else hdr['width'] for s in store]
        self.ref_h = [s['h'] if s else hdr['height'] for s in store]

    # reuse intra prediction + reconstruct from vp9_pixels (same attributes)
    def _predict_intra(self, *a):
        return P._PixelDecoder._predict_intra(self, *a)

    def _reconstruct(self, *a):
        return P._PixelDecoder._reconstruct(self, *a)

    def _uv_tx_size_of(self, *a):
        return P._PixelDecoder._uv_tx_size_of(self, *a)

    def _filter_size(self, *a):
        return P._PixelDecoder._filter_size(self, *a)

    # residual: intra predict OR inter predict, then tokens + reconstruct
    def _residual(self, bd):
        bsize = BLOCK_8X8 if self.MiSize < BLOCK_8X8 else self.MiSize
        for plane in range(3):
            txsz = self._uv_tx_size_of(self.MiSize, self.tx_size) if plane > 0 \
                else self.tx_size
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
            if self.is_inter:
                if self.MiSize < BLOCK_8X8:
                    for yy in range(n4h):
                        for xx in range(n4w):
                            self._predict_inter(plane, base_x + 4 * xx,
                                                base_y + 4 * yy, 4, 4,
                                                yy * n4w + xx)
                else:
                    self._predict_inter(plane, base_x, base_y, n4w * 4,
                                        n4h * 4, 0)
            block_idx = 0
            y = 0
            while y < n4h:
                x = 0
                while x < n4w:
                    start_x = base_x + 4 * x
                    start_y = base_y + 4 * y
                    nonzero = 0
                    if start_x < maxx and start_y < maxy:
                        if not self.is_inter:
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

    # tokens: capture coefficients (self.Tokens) AND use the is_inter coef book
    def _tokens(self, bd, plane, start_x, start_y, txsz, block_idx):
        seg_eob = 16 << (txsz << 1)
        tx_type = self._tx_type(plane, txsz, block_idx)
        self.TxType = tx_type
        scan = self._get_scan(tx_type, txsz)
        self.Tokens = [0] * seg_eob
        n = 4 << txsz
        pl_type = 1 if plane > 0 else 0
        cbook = self.p.coef[txsz][pl_type][1 if self.is_inter else 0]
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
            band = T.COEFBAND_4X4[c] if txsz == 0 else T.COEFBAND_8X8PLUS[c]
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
            token = I._read_tree(bd, T.TOKEN_TREE,
                                 lambda nd: I._pareto(nd, probs[min(2, 1 + nd)]))
            token_cache[pos] = T.ENERGY_CLASS[token]
            if token == 0:
                self.Tokens[pos] = 0
                check_eob = 0
            else:
                coef = self._read_coef(bd, token)
                sign = bd.read_literal(1)
                self.Tokens[pos] = -coef if sign else coef
                check_eob = 1
            c += 1
        return 1 if c > 0 else 0

    # -- inter prediction (spec 8.5.2) --
    def _predict_inter(self, plane, x, y, w, h, block_idx):
        is_compound = self.ref_frame[1] > NONE
        preds = []
        for rl in range(1 + is_compound):
            mv = self._mv_select(plane, rl, block_idx)
            cmv = self._mv_clamp(plane, mv)
            sx, sy, stepx, stepy = self._mv_scale(plane, rl, x, y, cmv)
            preds.append(self._block_inter_predict(plane, rl, sx, sy,
                                                   stepx, stepy, w, h))
        frame = self.cur[plane]
        if not is_compound:
            p0 = preds[0]
            for i in range(h):
                frame[y + i][x:x + w] = p0[i]
        else:
            p0, p1 = preds
            for i in range(h):
                row = frame[y + i]
                a, b = p0[i], p1[i]
                for j in range(w):
                    row[x + j] = _round2(a[j] + b[j], 1)

    def _mv_select(self, plane, rl, block_idx):
        if plane == 0 or self.MiSize >= BLOCK_8X8:
            return self.block_mvs[rl][block_idx]
        sx, sy = self.sub_x, self.sub_y
        bm = self.block_mvs[rl]
        if sx == 0 and sy == 0:
            return bm[block_idx]
        if sx == 0 and sy == 1:
            return tuple(_round_q2(bm[block_idx][c] + bm[block_idx + 2][c])
                         for c in range(2))
        if sx == 1 and sy == 0:
            return tuple(_round_q2(bm[block_idx][c] + bm[block_idx + 1][c])
                         for c in range(2))
        return tuple(_round_q4(bm[0][c] + bm[1][c] + bm[2][c] + bm[3][c])
                     for c in range(2))

    def _mv_clamp(self, plane, mv):
        sx = 0 if plane == 0 else self.sub_x
        sy = 0 if plane == 0 else self.sub_y
        bh = T.NUM_8X8_H[self.MiSize]
        bw = T.NUM_8X8_W[self.MiSize]
        mb_top = (-(self.MiRow * MI_SIZE * 16)) >> sy
        mb_bot = ((self.mi_rows - bh - self.MiRow) * MI_SIZE * 16) >> sy
        mb_left = (-(self.MiCol * MI_SIZE * 16)) >> sx
        mb_right = ((self.mi_cols - bw - self.MiCol) * MI_SIZE * 16) >> sx
        spel_l = (INTERP_EXTEND + ((bw * MI_SIZE) >> sx)) << SUBPEL_BITS
        spel_r = spel_l - SUBPEL_SHIFTS
        spel_t = (INTERP_EXTEND + ((bh * MI_SIZE) >> sy)) << SUBPEL_BITS
        spel_b = spel_t - SUBPEL_SHIFTS
        c0 = _clip3(mb_top - spel_t, mb_bot + spel_b, (2 * mv[0]) >> sy)
        c1 = _clip3(mb_left - spel_l, mb_right + spel_r, (2 * mv[1]) >> sx)
        return (c0, c1)

    def _mv_scale(self, plane, rl, x, y, cmv):
        ref_idx = self.ref_frame_idx[self.ref_frame[rl] - LAST_FRAME]
        rw, rh = self.ref_w[ref_idx], self.ref_h[ref_idx]
        W, H = self.h['width'], self.h['height']
        x_scale = (rw << REF_SCALE_SHIFT) // W
        y_scale = (rh << REF_SCALE_SHIFT) // H
        base_x = (x * x_scale) >> REF_SCALE_SHIFT
        base_y = (y * y_scale) >> REF_SCALE_SHIFT
        if plane > 0:
            luma_x = x << self.sub_x
            luma_y = y << self.sub_y
        else:
            luma_x, luma_y = x, y
        frac_x = ((16 * luma_x * x_scale) >> REF_SCALE_SHIFT) & SUBPEL_MASK
        frac_y = ((16 * luma_y * y_scale) >> REF_SCALE_SHIFT) & SUBPEL_MASK
        dx = ((cmv[1] * x_scale) >> REF_SCALE_SHIFT) + frac_x
        dy = ((cmv[0] * y_scale) >> REF_SCALE_SHIFT) + frac_y
        step_x = (16 * x_scale) >> REF_SCALE_SHIFT
        step_y = (16 * y_scale) >> REF_SCALE_SHIFT
        return ((base_x << SUBPEL_BITS) + dx, (base_y << SUBPEL_BITS) + dy,
                step_x, step_y)

    def _block_inter_predict(self, plane, rl, x, y, step_x, step_y, w, h):
        ref_idx = self.ref_frame_idx[self.ref_frame[rl] - LAST_FRAME]
        ref = self.store[ref_idx]['planes'][plane]
        sx = 0 if plane == 0 else self.sub_x
        sy = 0 if plane == 0 else self.sub_y
        last_x = ((self.ref_w[ref_idx] + sx) >> sx) - 1
        last_y = ((self.ref_h[ref_idx] + sy) >> sy) - 1
        filt = SUBPEL_FILTERS[self.interp_filter]
        inter_h = (((h - 1) * step_y + 15) >> 4) + 8
        maxv = (1 << self.bit_depth) - 1
        inter = [[0] * w for _ in range(inter_h)]
        for r in range(inter_h):
            ry = _clip3(0, last_y, (y >> 4) + r - 3)
            rrow = ref[ry]
            irow = inter[r]
            for c in range(w):
                p = x + step_x * c
                f = filt[p & 15]
                b = (p >> 4) - 3
                s = (f[0] * rrow[_clip3(0, last_x, b)]
                     + f[1] * rrow[_clip3(0, last_x, b + 1)]
                     + f[2] * rrow[_clip3(0, last_x, b + 2)]
                     + f[3] * rrow[_clip3(0, last_x, b + 3)]
                     + f[4] * rrow[_clip3(0, last_x, b + 4)]
                     + f[5] * rrow[_clip3(0, last_x, b + 5)]
                     + f[6] * rrow[_clip3(0, last_x, b + 6)]
                     + f[7] * rrow[_clip3(0, last_x, b + 7)])
                v = _round2(s, 7)
                irow[c] = 0 if v < 0 else (maxv if v > maxv else v)
        pred = [[0] * w for _ in range(h)]
        for r in range(h):
            p = (y & 15) + step_y * r
            f = filt[p & 15]
            b = p >> 4
            prow = pred[r]
            for c in range(w):
                s = (f[0] * inter[b][c] + f[1] * inter[b + 1][c]
                     + f[2] * inter[b + 2][c] + f[3] * inter[b + 3][c]
                     + f[4] * inter[b + 4][c] + f[5] * inter[b + 5][c]
                     + f[6] * inter[b + 6][c] + f[7] * inter[b + 7][c])
                v = _round2(s, 7)
                prow[c] = 0 if v < 0 else (maxv if v > maxv else v)
        return pred

    # -- general loop filter (with ref/mode deltas) --
    def _loop_filter(self):
        h = self.h
        level = h['loop_filter_level']
        if level == 0:
            return
        sharp = h['loop_filter_sharpness']
        n_shift = level >> 5
        lvl_seg = level
        deltas_on = h.get('loop_filter_delta_enabled', 0)
        ref_d = h.get('loop_filter_ref_deltas', [1, 0, -1, -1])
        mode_d = h.get('loop_filter_mode_deltas', [0, 0])
        lut = {}
        if not deltas_on:
            for ref in range(4):
                for mode in range(2):
                    lut[(ref, mode)] = lvl_seg
        else:
            lut[(0, 0)] = _clip3(0, 63, lvl_seg + (ref_d[0] << n_shift))
            for ref in range(1, 4):
                for mode in range(2):
                    lut[(ref, mode)] = _clip3(0, 63, lvl_seg
                                              + (ref_d[ref] << n_shift)
                                              + (mode_d[mode] << n_shift))
        self._lut = lut
        self._strength = {}
        bd = self.bit_depth
        for row in range(0, self.mi_rows, 8):
            for col in range(0, self.mi_cols, 8):
                for plane in range(3):
                    self._sb_loop_filter(plane, 0, row, col, bd)
                    self._sb_loop_filter(plane, 1, row, col, bd)

    def _lvl_at(self, r, c):
        ref = self.ref_grid[r][c][0]
        if ref <= INTRA_FRAME:
            return self._lut[(0, 0)]
        mode = self.y_modes[r][c]
        mt = 1 if mode in (NEARESTMV, NEARMV, NEWMV) else 0
        return self._lut[(ref, mt)]

    def _strength_of(self, lvl, sharp):
        s = self._strength.get(lvl)
        if s is None:
            shift = 2 if sharp > 4 else (1 if sharp > 0 else 0)
            if sharp > 0:
                limit = _clip3(1, 9 - sharp, lvl >> shift)
            else:
                limit = max(1, lvl >> shift)
            s = (limit, 2 * (lvl + 2) + limit, lvl >> 4)
            self._strength[lvl] = s
        return s

    def _sb_loop_filter(self, plane, pass_, row, col, bd):
        frame = self.cur[plane]
        if plane == 0:
            subx = suby = 0
        else:
            subx, suby = self.sub_x, self.sub_y
        if pass_ == 0:
            dx, dy, sub, edge_len = 1, 0, subx, 64 >> suby
        else:
            dx, dy, sub, edge_len = 0, 1, suby, 64 >> subx
        sharp = self.h['loop_filter_sharpness']
        for edge in range(16 >> sub):
            for i in range(edge_len):
                if pass_ == 0:
                    x = col * 8 + edge * (4 << subx)
                    y = row * 8 + (i << suby)
                else:
                    x = col * 8 + (i << subx)
                    y = row * 8 + edge * (4 << suby)
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
                sb_size = mi_size if sub == 0 else max(P.BLOCK_16X16, mi_size)
                skip = self.skips[loop_row][loop_col]
                is_intra = self.ref_grid[loop_row][loop_col][0] <= INTRA_FRAME
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
                if is_block_edge:
                    apply = 1
                elif is_tx_edge and is_intra:
                    apply = 1
                elif is_tx_edge and not skip:
                    apply = 1
                else:
                    apply = 0
                if not apply:
                    continue
                lvl = self._lvl_at(loop_row, loop_col)
                if lvl <= 0:
                    continue
                limit, blimit, thresh = self._strength_of(lvl, sharp)
                fs = self._filter_size(txsz, is32, pass_, x, y, subx, suby)
                P._lf_sample(frame, x >> subx, y >> suby, limit, blimit,
                             thresh, dx, dy, fs, bd)


def _crop(planes, h):
    w, ht = h['width'], h['height']
    sx, sy = h.get('subsampling', (1, 1))
    cw, ch = (w + sx) >> sx, (ht + sy) >> sy
    Y = [row[:w] for row in planes[0][:ht]]
    U = [row[:cw] for row in planes[1][:ch]]
    V = [row[:cw] for row in planes[2][:ch]]
    return [Y, U, V]


def decode_sequence(doc, blob, want_shown=True):
    """Decode a whole VP9 clip to pixels. Returns a list of shown frames, each a
    [Y,U,V] list of 2D int planes cropped to display size (in display order,
    i.e. skipping hidden frames), matching what a reference decoder outputs."""
    store = [None] * 8                        # FrameStore slots
    contexts = [I.FrameProbs.default() for _ in range(4)]
    prev = None
    parser = vp9.VP9HeaderParser()
    shown = []
    for _, _, _, off, size in doc.frames:
        block = blob[off:off + size]
        for lo, hi in vp9.superframe_split(block):
            if hi <= lo or lo >= len(block) or (block[lo] >> 6) != 2:
                continue
            h = parser.parse(block[lo:hi])
            if h is None:
                continue
            if 'show_existing' in h:
                # output an existing frame
                if want_shown:
                    idx = h.get('frame_to_show', 0)
                    if store[idx]:
                        shown.append(store[idx]['crop'])
                continue
            fi = bool(h.get('keyframe') or h.get('intra_only'))
            if fi or h.get('error_resilient'):
                contexts = [I.FrameProbs.default() for _ in range(4)]
            ci = h.get('frame_context_idx', 0)
            probs = contexts[ci].copy()
            pad = I.parse_compressed(probs, h, block, lo + h['uncompressed_bytes'])
            use_prev = (prev is not None and prev['w'] == h['width']
                        and prev['h'] == h['height'] and prev['show'] == 1
                        and not h.get('error_resilient') and not fi)
            dec = _FramePixelDecoder(h, probs, fi, prev, store)
            dec.use_prev_mvs = use_prev
            _run_tiles(dec, block, lo, hi, h)
            dec._loop_filter()
            crop = _crop(dec.cur, h)
            if h.get('refresh_frame_context'):
                contexts[ci] = probs.copy()
            entry = {'planes': dec.cur, 'crop': crop, 'w': h['width'],
                     'h': h['height'], 'sub': h.get('subsampling', (1, 1))}
            rf = h.get('refresh_frame_flags', 0)
            for i in range(8):
                if rf & (1 << i):
                    store[i] = entry
            if want_shown and h.get('show_frame', 1) == 1:
                shown.append(crop)
            prev = {'mv': dec.mv_grid, 'ref': dec.ref_grid, 'w': h['width'],
                    'h': h['height'], 'show': h.get('show_frame', 1)}
    return shown


def _run_tiles(dec, data, lo, hi, h):
    import vp9_decode as D
    tile_start = lo + h['uncompressed_bytes'] + h['header_size_in_bytes']
    tile_cols = 1 << h['tile_cols_log2']
    tile_rows = 1 << h['tile_rows_log2']
    pos = tile_start
    for tr in range(tile_rows):
        for tc in range(tile_cols):
            last = (tr == tile_rows - 1) and (tc == tile_cols - 1)
            if last:
                size = hi - pos
            else:
                size = int.from_bytes(data[pos:pos + 4], 'big')
                pos += 4
            r0 = D._tile_offset(tr, dec.mi_rows, h['tile_rows_log2'])
            r1 = D._tile_offset(tr + 1, dec.mi_rows, h['tile_rows_log2'])
            c0 = D._tile_offset(tc, dec.mi_cols, h['tile_cols_log2'])
            c1 = D._tile_offset(tc + 1, dec.mi_cols, h['tile_cols_log2'])
            bd = vp9.BoolDecoder(data, pos, size)
            for pl in range(3):
                dec.above_nz[pl] = [0] * len(dec.above_nz[pl])
            dec.above_part = [0] * len(dec.above_part)
            dec.decode_tile(bd, r0, r1, c0, c1)
            pos += size


if __name__ == '__main__':
    import sys
    from webm import WebM
    data = open(sys.argv[1], 'rb').read()
    frames = decode_sequence(WebM(data), data)
    print('decoded %d shown frames' % len(frames))
    if frames:
        Y = frames[0][0]
        print('frame0 %dx%d Y[0][:8]=%s' % (len(Y[0]), len(Y), Y[0][:8]))
