#!/usr/bin/env python3
"""VP9 — stage 3a: entropy decode of a key frame (partition + intra modes +
coefficient tokens), verified without producing pixels.

Continues tools/vp9.py (stages 1-2: headers). This module walks the tile's
partition tree, decodes the intra modes and the coefficient tokens for every
transform block, and maintains all the entropy contexts — everything that
*consumes bits*. It stops before intra prediction and the inverse transforms,
which produce pixels but read no bits.

Why that split is a real, checkable milestone: each tile is a whole number of
bytes and the arithmetic decoder must finish with the rest of the tile being
zero padding (exit_bool, spec §9.2.3). Predicting pixels and inverting
transforms cannot change that — so "the tile decodes to zero padding" verifies
the whole partition / mode / token entropy decode on its own, exactly the way
the compressed-header padding oracle verified stage 2. And unlike stage 2, this
one needs the real probability *values* (the tree decode's renormalisation
depends on them), so it exercises the default tables and the header updates too.

Key frame only for now (FrameIsIntra); inter blocks are a later stage.

    from vp9_decode import decode_keyframe_entropy
    pad = decode_keyframe_entropy(frame_bytes)   # 0 == clean, in-sync decode

Verified: all 1073 SC:R portrait key frames (both profile 1 4:4:4 and profile 0
4:2:0) decode to zero tile padding. The one bug found was the tx_size context —
a neighbour's transform size counts only if that neighbour was *not* skipped
(spec §9.3.2); using it unconditionally desynced on frames with skipped
neighbours, which is why it only surfaced on the larger 224x240 heads at first.
It presented as two failure clusters (HD profile-1 and all profile-0) that were
one bug.
"""
import vp9
import vp9_tables as T

# enums
DC_PRED = 0
TM_PRED = 9
DCT_DCT, ADST_DCT, DCT_ADST, ADST_ADST = 0, 1, 2, 3
PARTITION_NONE, PARTITION_HORZ, PARTITION_VERT, PARTITION_SPLIT = 0, 1, 2, 3
BLOCK_8X8 = 3
BLOCK_64X64 = 12
BLOCK_INVALID = 14
TX_4X4, TX_8X8, TX_16X16, TX_32X32 = 0, 1, 2, 3
TX_MODE_SELECT = 4
ZERO_TOKEN = 0


# ---- probability model: defaults + compressed-header updates ----

def _inv_recenter_nonneg(v, m):
    if v > 2 * m:
        return v
    if v & 1:
        return m - ((v + 1) >> 1)
    return m + (v >> 1)


def _inv_remap_prob(delta, prob):
    m = prob - 1
    v = T.INV_MAP_TABLE[delta]
    if (m << 1) <= 255:
        return 1 + _inv_recenter_nonneg(v, m)
    return 255 - _inv_recenter_nonneg(v, 254 - m)


def _copy(x):
    return [_copy(e) for e in x] if isinstance(x, list) else x


class Probs:
    """The frame's coefficient / tx / skip probabilities: defaults, with the
    compressed-header diff updates applied. (Key-frame mode and partition
    probabilities are the fixed kf_* tables, used directly from vp9_tables.)"""

    def __init__(self, hdr, data, start):
        self.coef = _copy(T.DEFAULT_COEF_PROBS)
        self.tx8 = _copy([[100, 0], [66, 0]])   # placeholder, replaced below
        self.tx_probs = _copy(T.DEFAULT_TX_PROBS)
        self.skip = list(T.DEFAULT_SKIP_PROB)
        self._parse_compressed(hdr, data, start)

    def _du(self, bd, cur):
        """diff_update_prob returning the new probability value."""
        if bd.read_bool(252):
            return _inv_remap_prob(_decode_term_subexp(bd), cur)
        return cur

    def _parse_compressed(self, hdr, data, start):
        bd = vp9.BoolDecoder(data, start, hdr['header_size_in_bytes'])
        lossless = hdr.get('lossless', False)
        # read_tx_mode
        if lossless:
            tx_mode = 0
        else:
            tx_mode = bd.read_literal(2)
            if tx_mode == 3:
                tx_mode += bd.read_literal(1)
        self.tx_mode = tx_mode
        if tx_mode == TX_MODE_SELECT:
            # tx_probs_8x8[2][1], 16x16[2][2], 32x32[2][3] live inside
            # DEFAULT_TX_PROBS[1..3]; update in place.
            for i in range(2):
                for j in range(1):
                    self.tx_probs[1][i][j] = self._du(bd, self.tx_probs[1][i][j])
            for i in range(2):
                for j in range(2):
                    self.tx_probs[2][i][j] = self._du(bd, self.tx_probs[2][i][j])
            for i in range(2):
                for j in range(3):
                    self.tx_probs[3][i][j] = self._du(bd, self.tx_probs[3][i][j])
        # read_coef_probs
        max_tx = vp9.TX_MODE_TO_BIGGEST[tx_mode]
        for txsz in range(max_tx + 1):
            if bd.read_literal(1):
                for i in range(2):
                    for j in range(2):
                        for k in range(6):
                            maxl = 3 if k == 0 else 6
                            for l in range(maxl):
                                for m in range(3):
                                    cur = self.coef[txsz][i][j][k][l][m]
                                    self.coef[txsz][i][j][k][l][m] = self._du(bd, cur)
        # read_skip_prob
        for i in range(vp9.SKIP_CONTEXTS):
            self.skip[i] = self._du(bd, self.skip[i])
        # (key frame: no inter-mode / mv probs follow)
        self.bd = bd
        self.pad = bd.exit_padding_nonzero() if bd.bits_left >= 0 else -1


def _decode_term_subexp(bd):
    if bd.read_literal(1) == 0:
        return bd.read_literal(4)
    if bd.read_literal(1) == 0:
        return bd.read_literal(4) + 16
    if bd.read_literal(1) == 0:
        return bd.read_literal(5) + 32
    v = bd.read_literal(7)
    if v < 65:
        return v + 64
    return (v << 1) - 1 + bd.read_literal(1)


def _read_tree(bd, tree, prob_fn):
    """Tree decode (spec §9.3.3): n = T[n + read_bool(P(n>>1))] until n<=0."""
    n = 0
    while True:
        n = tree[n + bd.read_bool(prob_fn(n >> 1))]
        if n <= 0:
            return -n


# ---- key-frame entropy decode over one frame ----

class _KeyFrameDecoder:
    def __init__(self, hdr, probs):
        self.h = hdr
        self.p = probs
        self.mi_cols = (hdr['width'] + 7) >> 3
        self.mi_rows = (hdr['height'] + 7) >> 3
        self.sub_x, self.sub_y = hdr.get('subsampling', (1, 1))
        # partition context, per mode-info column / superblock-relative row
        self.above_part = [0] * (self.mi_cols + 8)
        self.left_part = [0] * 8
        # nonzero context per plane, absolute 4x4 index (left context is
        # cleared per superblock row, so absolute indexing is fine)
        self.above_nz = [[0] * (2 * self.mi_cols + 16) for _ in range(3)]
        self.left_nz = [[0] * (2 * self.mi_rows + 16) for _ in range(3)]
        # sub-modes grid: two edge rows are enough but keep full for clarity
        self.sub_modes = [[[DC_PRED] * 4 for _ in range(self.mi_cols)]
                          for _ in range(self.mi_rows)]
        self.skips = [[0] * self.mi_cols for _ in range(self.mi_rows)]
        self.tx_sizes = [[0] * self.mi_cols for _ in range(self.mi_rows)]
        # MiSize per 8x8 cell — needed by the loop filter (block-edge test).
        self.mi_sizes = [[BLOCK_64X64] * self.mi_cols for _ in range(self.mi_rows)]

    # -- tile driver
    def decode_tile(self, bd, r0, r1, c0, c1):
        self.MiRowStart, self.MiRowEnd = r0, r1
        self.MiColStart, self.MiColEnd = c0, c1
        for r in range(r0, r1, 8):
            for p in range(3):
                for i in range(len(self.left_nz[p])):
                    self.left_nz[p][i] = 0
            self.left_part = [0] * 8
            for c in range(c0, c1, 8):
                self._partition(bd, r, c, BLOCK_64X64)

    def _partition(self, bd, r, c, bsize):
        if r >= self.mi_rows or c >= self.mi_cols:
            return
        num8x8 = T.NUM_8X8_W[bsize]
        half = num8x8 >> 1
        has_rows = (r + half) < self.mi_rows
        has_cols = (c + half) < self.mi_cols
        part = self._read_partition(bd, r, c, bsize, num8x8, has_rows, has_cols)
        subsize = T.SUBSIZE_LOOKUP[part][bsize]
        if subsize < BLOCK_8X8 or part == PARTITION_NONE:
            self._block(bd, r, c, subsize)
        elif part == PARTITION_HORZ:
            self._block(bd, r, c, subsize)
            if has_rows:
                self._block(bd, r + half, c, subsize)
        elif part == PARTITION_VERT:
            self._block(bd, r, c, subsize)
            if has_cols:
                self._block(bd, r, c + half, subsize)
        else:
            self._partition(bd, r, c, subsize)
            self._partition(bd, r, c + half, subsize)
            self._partition(bd, r + half, c, subsize)
            self._partition(bd, r + half, c + half, subsize)
        if bsize == BLOCK_8X8 or part != PARTITION_SPLIT:
            aw = 15 >> T.B_WIDTH_LOG2[subsize]
            ah = 15 >> T.B_HEIGHT_LOG2[subsize]
            for i in range(num8x8):
                self.above_part[c + i] = aw
                self.left_part[(r + i) & 7] = ah

    def _read_partition(self, bd, r, c, bsize, num8x8, has_rows, has_cols):
        bsl = T.MI_WIDTH_LOG2[bsize]
        boffset = T.MI_WIDTH_LOG2[BLOCK_64X64] - bsl
        above = left = 0
        for i in range(num8x8):
            above |= self.above_part[c + i]
            left |= self.left_part[(r + i) & 7]
        above = 1 if (above & (1 << boffset)) else 0
        left = 1 if (left & (1 << boffset)) else 0
        ctx = bsl * 4 + left * 2 + above
        probs = T.KF_PARTITION_PROBS[ctx]      # key frame

        def P(node):
            node2 = node if (has_rows and has_cols) else (1 if has_cols else 2)
            return probs[node2]

        if has_rows and has_cols:
            return _read_tree(bd, T.PARTITION_TREE, P)
        if has_cols:
            return _read_tree(bd, T.COLS_PARTITION_TREE, P)
        if has_rows:
            return _read_tree(bd, T.ROWS_PARTITION_TREE, P)
        return PARTITION_SPLIT

    def _block(self, bd, r, c, subsize):
        self.MiRow, self.MiCol, self.MiSize = r, c, subsize
        self.AvailU = r > 0
        self.AvailL = c > self.MiColStart
        self._intra_mode_info(bd)
        self._residual(bd)
        num_h = T.NUM_8X8_H[subsize]
        num_w = T.NUM_8X8_W[subsize]
        for y in range(num_h):
            for x in range(num_w):
                if r + y < self.mi_rows and c + x < self.mi_cols:
                    self.skips[r + y][c + x] = self.skip
                    self.tx_sizes[r + y][c + x] = self.tx_size
                    self.mi_sizes[r + y][c + x] = subsize
                    for b in range(4):
                        self.sub_modes[r + y][c + x][b] = self.sub_mode[b]

    # -- intra_frame_mode_info (key frame)
    def _intra_mode_info(self, bd):
        # intra_segment_id: segmentation off in this corpus -> 0
        self.segment_id = 0
        # read_skip
        self.skip = self._read_skip(bd)
        # read_tx_size(1)
        self.tx_size = self._read_tx_size(bd, True)
        self.sub_mode = [DC_PRED] * 4
        r, c = self.MiRow, self.MiCol
        if self.MiSize >= BLOCK_8X8:
            mode = self._read_kf_y_mode(bd, 0, 0)
            self.y_mode = mode
            self.sub_mode = [mode] * 4
        else:
            n4w = T.NUM_4X4_W[self.MiSize]
            n4h = T.NUM_4X4_H[self.MiSize]
            idy = 0
            while idy < 2:
                idx = 0
                while idx < 2:
                    mode = self._read_kf_y_mode(bd, idx, idy)
                    for y2 in range(n4h):
                        for x2 in range(n4w):
                            self.sub_mode[(idy + y2) * 2 + idx + x2] = mode
                    idx += n4w
                idy += n4h
            self.y_mode = mode
        # default_uv_mode
        uv_probs = T.KF_UV_MODE_PROBS[self.y_mode]
        self.uv_mode = _read_tree(bd, T.INTRA_MODE_TREE, lambda n: uv_probs[n])

    def _read_kf_y_mode(self, bd, idx, idy):
        r, c = self.MiRow, self.MiCol
        if self.MiSize >= BLOCK_8X8:
            above = self.sub_modes[r - 1][c][2] if self.AvailU else DC_PRED
            left = self.sub_modes[r][c - 1][1] if self.AvailL else DC_PRED
        else:
            if idy:
                above = self.sub_mode[idx]
            else:
                above = self.sub_modes[r - 1][c][2 + idx] if self.AvailU else DC_PRED
            if idx:
                left = self.sub_mode[idy * 2]
            else:
                left = self.sub_modes[r][c - 1][1 + idy * 2] if self.AvailL else DC_PRED
        probs = T.KF_Y_MODE_PROBS[above][left]
        return _read_tree(bd, T.INTRA_MODE_TREE, lambda n: probs[n])

    def _read_skip(self, bd):
        ctx = 0
        r, c = self.MiRow, self.MiCol
        if self.AvailU:
            ctx += self.skips[r - 1][c]
        if self.AvailL:
            ctx += self.skips[r][c - 1]
        return bd.read_bool(self.p.skip[ctx])

    def _read_tx_size(self, bd, allow_select):
        max_tx = T.MAX_TXSIZE[self.MiSize]
        if (allow_select and self.p.tx_mode == TX_MODE_SELECT
                and self.MiSize >= BLOCK_8X8):
            ctx = self._tx_size_ctx()
            probs = self.p.tx_probs[max_tx + 1 - 1]  # tx_probs[maxTx] group
            # tx_probs index: DEFAULT_TX_PROBS[maxTxSize][ctx]
            probs = self.p.tx_probs[max_tx][ctx]
            if max_tx == TX_32X32:
                return _read_tree(bd, T.TX_SIZE_32_TREE, lambda n: probs[n])
            if max_tx == TX_16X16:
                return _read_tree(bd, T.TX_SIZE_16_TREE, lambda n: probs[n])
            return _read_tree(bd, T.TX_SIZE_8_TREE, lambda n: probs[n])
        return min(max_tx, vp9.TX_MODE_TO_BIGGEST[self.p.tx_mode])

    def _tx_size_ctx(self):
        # spec §9.3.2 tx_size: a neighbour's tx size counts only if that
        # neighbour was NOT skipped; otherwise fall back to maxTxSize.
        r, c = self.MiRow, self.MiCol
        max_tx = T.MAX_TXSIZE[self.MiSize]
        above = left = max_tx
        if self.AvailU and not self.skips[r - 1][c]:
            above = self.tx_sizes[r - 1][c]
        if self.AvailL and not self.skips[r][c - 1]:
            left = self.tx_sizes[r][c - 1]
        if not self.AvailL:
            left = above
        if not self.AvailU:
            above = left
        return 1 if (above + left) > max_tx else 0

    # -- residual: tokens for each transform block
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
                        if not self.skip:
                            nonzero = self._tokens(bd, plane, start_x, start_y,
                                                   txsz, block_idx)
                    for i in range(step):
                        self.above_nz[plane][(start_x >> 2) + i] = nonzero
                        self.left_nz[plane][(start_y >> 2) + i] = nonzero
                    block_idx += 1
                    x += step
                y += step

    def _uv_tx_size(self):
        if self.MiSize < BLOCK_8X8:
            return TX_4X4
        return min(self.tx_size,
                   T.MAX_TXSIZE[self._plane_block_size(self.MiSize, 1)])

    def _plane_block_size(self, subsize, plane):
        sx = self.sub_x if plane > 0 else 0
        sy = self.sub_y if plane > 0 else 0
        return T.SS_SIZE_LOOKUP[subsize][sx][sy]

    def _tx_type(self, plane, txsz, block_idx):
        if plane > 0 or txsz == TX_32X32:
            return DCT_DCT
        if txsz == TX_4X4:
            if self.h.get('lossless'):
                return DCT_DCT
            m = self.sub_mode[block_idx] if self.MiSize < BLOCK_8X8 else self.y_mode
            return T.MODE2TXFM[m]
        return T.MODE2TXFM[self.y_mode]

    def _get_scan(self, tx_type, txsz):
        if txsz == TX_4X4:
            return (T.ROW_SCAN_4X4 if tx_type == ADST_DCT else
                    T.COL_SCAN_4X4 if tx_type == DCT_ADST else T.DEFAULT_SCAN_4X4)
        if txsz == TX_8X8:
            return (T.ROW_SCAN_8X8 if tx_type == ADST_DCT else
                    T.COL_SCAN_8X8 if tx_type == DCT_ADST else T.DEFAULT_SCAN_8X8)
        if txsz == TX_16X16:
            return (T.ROW_SCAN_16X16 if tx_type == ADST_DCT else
                    T.COL_SCAN_16X16 if tx_type == DCT_ADST else T.DEFAULT_SCAN_16X16)
        return T.DEFAULT_SCAN_32X32

    def _tokens(self, bd, plane, start_x, start_y, txsz, block_idx):
        seg_eob = 16 << (txsz << 1)
        tx_type = self._tx_type(plane, txsz, block_idx)
        scan = self._get_scan(tx_type, txsz)
        n = 4 << txsz
        pl_type = 1 if plane > 0 else 0
        is_inter = 0
        cbook = self.p.coef[txsz][pl_type][is_inter]
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
                more = bd.read_bool(probs[0])
                if not more:
                    break
            token = _read_tree(bd, T.TOKEN_TREE,
                               lambda nd: _pareto(nd, probs[min(2, 1 + nd)]))
            token_cache[pos] = T.ENERGY_CLASS[token]
            if token == ZERO_TOKEN:
                check_eob = 0
            else:
                self._read_coef(bd, token)
                bd.read_literal(1)          # sign
                check_eob = 1
            c += 1
        return 1 if c > 0 else 0

    @staticmethod
    def _neighbors(pos, n, tx_type):
        i = pos // n
        j = pos % n
        if i > 0 and j > 0:
            a = (i - 1) * n + j
            a2 = i * n + j - 1
            if tx_type == DCT_ADST:
                return a, a
            if tx_type == ADST_DCT:
                return a2, a2
            return a, a2
        if i > 0:
            v = (i - 1) * n + j
            return v, v
        v = i * n + j - 1
        return v, v

    def _read_coef(self, bd, token):
        cat, num_extra, coef = T.EXTRA_BITS[token]
        if token == 10:                     # DCT_VAL_CATEGORY6
            for e in range(self.h.get('bit_depth', 8) - 8):
                coef += bd.read_bool(255) << (5 + self.h.get('bit_depth', 8) - e)
        for e in range(num_extra):
            coef += bd.read_bool(T.CAT_PROBS[cat][e]) << (num_extra - 1 - e)
        return coef


def _pareto(node, prob):
    if node < 2:
        return prob
    x = (prob - 1) // 2
    if prob & 1:
        return T.PARETO_TABLE[x][node - 2]
    return (T.PARETO_TABLE[x][node - 2] + T.PARETO_TABLE[x + 1][node - 2]) >> 1


def _tile_offset(tile_num, mis, log2):
    sbs = (mis + 7) >> 3
    return min(((tile_num * sbs) >> log2) << 3, mis)


def decode_keyframe_entropy(data, lo=0, hi=None):
    """Decode the entropy of a VP9 key frame (partition + modes + tokens) over
    all tiles and return the total non-zero padding across the tiles' exit_bool
    (0 == a clean, fully in-sync decode). Raises if the frame is not a key
    frame this stage handles."""
    if hi is None:
        hi = len(data)
    p = vp9.VP9HeaderParser()
    h = p.parse(data[lo:hi])
    if h is None or 'show_existing' in h:
        raise ValueError('not a decodable frame')
    if not h.get('keyframe'):
        raise ValueError('stage 3a is key-frame only')
    probs = Probs(h, data, lo + h['uncompressed_bytes'])
    if probs.pad != 0:
        return -1000 + probs.pad          # compressed header itself desynced

    dec = _KeyFrameDecoder(h, probs)
    tile_start = lo + h['uncompressed_bytes'] + h['header_size_in_bytes']
    tile_cols = 1 << h['tile_cols_log2']
    tile_rows = 1 << h['tile_rows_log2']
    mi_rows, mi_cols = dec.mi_rows, dec.mi_cols
    total_pad = 0
    pos = tile_start
    for tr in range(tile_rows):
        for tc in range(tile_cols):
            last = (tr == tile_rows - 1) and (tc == tile_cols - 1)
            if last:
                size = hi - pos
            else:
                size = int.from_bytes(data[pos:pos + 4], 'big')
                pos += 4
            r0 = _tile_offset(tr, mi_rows, h['tile_rows_log2'])
            r1 = _tile_offset(tr + 1, mi_rows, h['tile_rows_log2'])
            c0 = _tile_offset(tc, mi_cols, h['tile_cols_log2'])
            c1 = _tile_offset(tc + 1, mi_cols, h['tile_cols_log2'])
            bd = vp9.BoolDecoder(data, pos, size)
            for pl in range(3):
                dec.above_nz[pl] = [0] * len(dec.above_nz[pl])
            dec.above_part = [0] * len(dec.above_part)
            dec.decode_tile(bd, r0, r1, c0, c1)
            if bd.bits_left < 0:
                return -1
            total_pad += bd.exit_padding_nonzero()
            pos += size
    return total_pad


def main():
    import sys
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
    pad = decode_keyframe_entropy(data, lo, hi)
    print('key-frame entropy padding: %d (%s)'
          % (pad, 'clean' if pad == 0 else 'DESYNC'))


if __name__ == '__main__':
    main()
