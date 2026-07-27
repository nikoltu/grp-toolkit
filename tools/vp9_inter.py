#!/usr/bin/env python3
"""VP9 - stage 5 (Phase A): inter-frame ENTROPY decode over a whole sequence.

Continues tools/vp9_decode.py (3a: key-frame entropy) and tools/vp9_pixels.py
(3b + loop filter: key-frame pixels). This module decodes the *inter* frames'
bitstream - the part that consumes bits - and nothing else: inter mode info
(is_inter, reference frames, inter modes, motion vectors), the motion-vector
reference search (find_mv_refs, spec 6.5) that the entropy decode depends on,
and the non-key-frame partition / mode contexts. No pixels, no motion
compensation - that is Phase B.

Why entropy-only is a real, checkable milestone, exactly as it was for 3a: each
tile is a whole number of bytes and the arithmetic decoder must finish on zero
padding (exit_bool, spec 9.2.3). Inter prediction and the transforms read no
bits, so "every tile of every frame of the clip ends on zero padding" verifies
the whole inter parse - is_inter/ref/mode contexts, find_mv_refs (its result
feeds UseHp, which changes how many MV bits are read), and the MV decode.

Two facts, measured across the 1073 portrait clips, shape this (see ROADMAP 2):
  * Every inter frame has frame_parallel_decoding_mode == 1, so the backward
    probability adaptation of spec 9.4 is DISABLED. Instead the 4 frame contexts
    evolve only through the compressed-header forward updates: a frame loads
    frame_context[idx], applies its updates, decodes, and (if
    refresh_frame_context) saves the result back; a key frame resets all four to
    defaults. That removes the single largest inter sub-component.
  * reference_mode is SELECT / SINGLE / COMPOUND (measured 8466/2665/6), so the
    full compound path is needed.

Written from VP9 spec v0.6 (6.4.11-6.4.20, 6.5, 9.3.2). Independence holds: no
other decoder consulted.

    from vp9_inter import decode_clip_padding
    total_pad = decode_clip_padding(webm_doc, blob)   # 0 == clean whole clip
"""
import vp9
import vp9_tables as T
import vp9_decode as D
from vp9_decode import _read_tree, _pareto, _decode_term_subexp, _inv_remap_prob

# ---- enums ----
NONE, INTRA_FRAME, LAST_FRAME, GOLDEN_FRAME, ALTREF_FRAME = -1, 0, 1, 2, 3
DC_PRED, TM_PRED = 0, 9
NEARESTMV, NEARMV, ZEROMV, NEWMV = 10, 11, 12, 13
BLOCK_8X8 = 3
BLOCK_64X64 = 12
TX_4X4 = 0
ZERO_TOKEN = 0
SINGLE_REFERENCE, COMPOUND_REFERENCE, REFERENCE_MODE_SELECT = 0, 1, 2
MV_JOINT_ZERO, MV_JOINT_HNZVZ, MV_JOINT_HZVNZ, MV_JOINT_HNZVNZ = 0, 1, 2, 3
PARTITION_NONE, PARTITION_HORZ, PARTITION_VERT, PARTITION_SPLIT = 0, 1, 2, 3

MV_BORDER = 128
MI_SIZE = 8
CLASS0_SIZE = 2
COMPANDED_MVREF_THRESH = 8
BORDERINPIXELS, INTERP_EXTEND = 160, 4
MVREF_NEIGHBOURS = 8
MAX_MV_REF_CANDIDATES = 2

# ---- trees (spec 9.3.1) ----
INTER_MODE_TREE = [-2, 2, 0, 4, -1, -3]         # leaf = inter_mode index
INTERP_FILTER_TREE = [0, 2, -1, -2]
MV_JOINT_TREE = [0, 2, -1, 4, -2, -3]
MV_CLASS_TREE = [0, 2, -1, 4, 6, 8, -2, -3, 10, 12,
                 -4, -5, -6, 14, 16, 18, -7, -8, -9, -10]
MV_FR_TREE = [0, 2, -1, 4, -2, -3]
BINARY_TREE = [0, -1]

# ---- MV prediction tables (spec 6.5) ----
MV_REF_BLOCKS = [
    [[-1, 0], [0, -1], [-1, -1], [-2, 0], [0, -2], [-2, -1], [-1, -2], [-2, -2]],
    [[-1, 0], [0, -1], [-1, -1], [-2, 0], [0, -2], [-2, -1], [-1, -2], [-2, -2]],
    [[-1, 0], [0, -1], [-1, -1], [-2, 0], [0, -2], [-2, -1], [-1, -2], [-2, -2]],
    [[-1, 0], [0, -1], [-1, -1], [-2, 0], [0, -2], [-2, -1], [-1, -2], [-2, -2]],
    [[0, -1], [-1, 0], [1, -1], [-1, -1], [0, -2], [-2, 0], [-2, -1], [-1, -2]],
    [[-1, 0], [0, -1], [-1, 1], [-1, -1], [-2, 0], [0, -2], [-1, -2], [-2, -1]],
    [[-1, 0], [0, -1], [-1, 1], [1, -1], [-1, -1], [-3, 0], [0, -3], [-3, -3]],
    [[0, -1], [-1, 0], [2, -1], [-1, -1], [-1, 1], [0, -3], [-3, 0], [-3, -3]],
    [[-1, 0], [0, -1], [-1, 2], [-1, -1], [1, -1], [-3, 0], [0, -3], [-3, -3]],
    [[-1, 1], [1, -1], [-1, 2], [2, -1], [-1, -1], [-3, 0], [0, -3], [-3, -3]],
    [[0, -1], [-1, 0], [4, -1], [-1, 2], [-1, -1], [0, -3], [-3, 0], [2, -1]],
    [[-1, 0], [0, -1], [-1, 4], [2, -1], [-1, -1], [-3, 0], [0, -3], [-1, 2]],
    [[-1, 3], [3, -1], [-1, 4], [4, -1], [-1, -1], [-1, 0], [0, -1], [-1, 6]],
]
MODE_2_COUNTER = [9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 3, 1]
COUNTER_TO_CONTEXT = [2, 3, 4, 1, 3, 9, 0, 9, 9, 5, 5, 9, 5, 9, 9, 9, 9, 9, 6]
IDX_N_COLUMN_TO_SUBBLOCK = [[1, 2], [1, 3], [3, 2], [3, 3]]

ZERO_MV = (0, 0)


def _copy(x):
    return [_copy(e) for e in x] if isinstance(x, list) else x


# ---- per-frame probability set (loaded from a context, forward-updated) ----

class FrameProbs:
    _FIELDS = ('coef', 'tx_probs', 'skip', 'inter_mode', 'interp_filter',
               'is_inter', 'comp_mode', 'single_ref', 'comp_ref', 'y_mode',
               'uv_mode', 'partition', 'mv_joint', 'mv_sign', 'mv_class',
               'mv_class0_bit', 'mv_bits', 'mv_class0_fr', 'mv_fr',
               'mv_class0_hp', 'mv_hp')

    @classmethod
    def default(cls):
        p = cls.__new__(cls)
        p.coef = _copy(T.DEFAULT_COEF_PROBS)
        p.tx_probs = _copy(T.DEFAULT_TX_PROBS)
        p.skip = list(T.DEFAULT_SKIP_PROB)
        p.inter_mode = _copy(T.DEFAULT_INTER_MODE_PROBS)
        p.interp_filter = _copy(T.DEFAULT_INTERP_FILTER_PROBS)
        p.is_inter = list(T.DEFAULT_IS_INTER_PROB)
        p.comp_mode = list(T.DEFAULT_COMP_MODE_PROB)
        p.single_ref = _copy(T.DEFAULT_SINGLE_REF_PROB)
        p.comp_ref = list(T.DEFAULT_COMP_REF_PROB)
        p.y_mode = _copy(T.DEFAULT_Y_MODE_PROBS)
        p.uv_mode = _copy(T.DEFAULT_UV_MODE_PROBS)
        p.partition = _copy(T.DEFAULT_PARTITION_PROBS)
        p.mv_joint = list(T.DEFAULT_MV_JOINT_PROBS)
        p.mv_sign = list(T.DEFAULT_MV_SIGN_PROB)
        p.mv_class = _copy(T.DEFAULT_MV_CLASS_PROBS)
        p.mv_class0_bit = list(T.DEFAULT_MV_CLASS0_BIT_PROB)
        p.mv_bits = _copy(T.DEFAULT_MV_BITS_PROB)
        p.mv_class0_fr = _copy(T.DEFAULT_MV_CLASS0_FR_PROBS)
        p.mv_fr = _copy(T.DEFAULT_MV_FR_PROBS)
        p.mv_class0_hp = list(T.DEFAULT_MV_CLASS0_HP_PROB)
        p.mv_hp = list(T.DEFAULT_MV_HP_PROB)
        p.tx_mode = 0
        return p

    def copy(self):
        q = FrameProbs.__new__(FrameProbs)
        for f in self._FIELDS:
            setattr(q, f, _copy(getattr(self, f)))
        q.tx_mode = self.tx_mode
        return q


def _du(bd, cur):
    """diff_update_prob (spec 9.2.4): B(252) then term-subexp remap."""
    if bd.read_bool(252):
        return _inv_remap_prob(_decode_term_subexp(bd), cur)
    return cur


def _umv(bd, cur):
    """update_mv_prob (spec 6.3.17): B(252) then L(7) -> (v<<1)|1."""
    if bd.read_bool(252):
        return (bd.read_literal(7) << 1) | 1
    return cur


def parse_compressed(p, h, data, start):
    """Apply the compressed-header forward updates to FrameProbs p in place, and
    return the non-zero exit padding (0 == clean). Handles key and inter frames.
    reference_mode / CompFixedRef / CompVarRef are stored on p for the tile
    decode."""
    bd = vp9.BoolDecoder(data, start, h['header_size_in_bytes'])
    lossless = h.get('lossless', False)
    frame_is_intra = h.get('keyframe') or h.get('intra_only')
    interp = h.get('interp_filter')
    sign_bias = h.get('ref_frame_sign_bias', [0, 0, 0, 0])
    hp_mv = h.get('allow_high_precision_mv', 0)

    # read_tx_mode
    if lossless:
        tx_mode = 0
    else:
        tx_mode = bd.read_literal(2)
        if tx_mode == 3:
            tx_mode += bd.read_literal(1)
    p.tx_mode = tx_mode
    if tx_mode == vp9.TX_MODE_SELECT:
        for i in range(2):
            for j in range(1):
                p.tx_probs[1][i][j] = _du(bd, p.tx_probs[1][i][j])
        for i in range(2):
            for j in range(2):
                p.tx_probs[2][i][j] = _du(bd, p.tx_probs[2][i][j])
        for i in range(2):
            for j in range(3):
                p.tx_probs[3][i][j] = _du(bd, p.tx_probs[3][i][j])
    # read_coef_probs
    max_tx = vp9.TX_MODE_TO_BIGGEST[tx_mode]
    for txsz in range(max_tx + 1):
        if bd.read_literal(1):
            for i in range(2):
                for j in range(2):
                    for k in range(6):
                        for l in range(3 if k == 0 else 6):
                            for m in range(3):
                                p.coef[txsz][i][j][k][l][m] = _du(
                                    bd, p.coef[txsz][i][j][k][l][m])
    # read_skip_prob
    for i in range(vp9.SKIP_CONTEXTS):
        p.skip[i] = _du(bd, p.skip[i])

    p.reference_mode = SINGLE_REFERENCE
    p.comp_fixed_ref = 0
    p.comp_var_ref = [0, 0]
    if not frame_is_intra:
        for i in range(vp9.INTER_MODE_CONTEXTS):
            for j in range(vp9.INTER_MODES - 1):
                p.inter_mode[i][j] = _du(bd, p.inter_mode[i][j])
        if interp == 'SWITCHABLE':
            for j in range(vp9.INTERP_FILTER_CONTEXTS):
                for i in range(vp9.SWITCHABLE_FILTERS - 1):
                    p.interp_filter[j][i] = _du(bd, p.interp_filter[j][i])
        for i in range(vp9.IS_INTER_CONTEXTS):
            p.is_inter[i] = _du(bd, p.is_inter[i])
        # frame_reference_mode
        comp_allowed = any(sign_bias[i + 1] != sign_bias[1]
                           for i in range(1, vp9.REFS_PER_FRAME))
        if comp_allowed:
            if bd.read_literal(1) == 0:
                p.reference_mode = SINGLE_REFERENCE
            else:
                p.reference_mode = (COMPOUND_REFERENCE if bd.read_literal(1) == 0
                                    else REFERENCE_MODE_SELECT)
                _setup_compound_reference_mode(p, sign_bias)
        # frame_reference_mode_probs
        if p.reference_mode == REFERENCE_MODE_SELECT:
            for i in range(vp9.COMP_MODE_CONTEXTS):
                p.comp_mode[i] = _du(bd, p.comp_mode[i])
        if p.reference_mode != COMPOUND_REFERENCE:
            for i in range(vp9.REF_CONTEXTS):
                p.single_ref[i][0] = _du(bd, p.single_ref[i][0])
                p.single_ref[i][1] = _du(bd, p.single_ref[i][1])
        if p.reference_mode != SINGLE_REFERENCE:
            for i in range(vp9.REF_CONTEXTS):
                p.comp_ref[i] = _du(bd, p.comp_ref[i])
        # read_y_mode_probs
        for i in range(vp9.BLOCK_SIZE_GROUPS):
            for j in range(vp9.INTRA_MODES - 1):
                p.y_mode[i][j] = _du(bd, p.y_mode[i][j])
        # read_partition_probs
        for i in range(vp9.PARTITION_CONTEXTS):
            for j in range(vp9.PARTITION_TYPES - 1):
                p.partition[i][j] = _du(bd, p.partition[i][j])
        # mv_probs
        for j in range(vp9.MV_JOINTS - 1):
            p.mv_joint[j] = _umv(bd, p.mv_joint[j])
        for i in range(2):
            p.mv_sign[i] = _umv(bd, p.mv_sign[i])
            for j in range(vp9.MV_CLASSES - 1):
                p.mv_class[i][j] = _umv(bd, p.mv_class[i][j])
            p.mv_class0_bit[i] = _umv(bd, p.mv_class0_bit[i])
            for j in range(vp9.MV_OFFSET_BITS):
                p.mv_bits[i][j] = _umv(bd, p.mv_bits[i][j])
        for i in range(2):
            for j in range(CLASS0_SIZE):
                for k in range(vp9.MV_FR_SIZE - 1):
                    p.mv_class0_fr[i][j][k] = _umv(bd, p.mv_class0_fr[i][j][k])
            for k in range(vp9.MV_FR_SIZE - 1):
                p.mv_fr[i][k] = _umv(bd, p.mv_fr[i][k])
        if hp_mv:
            for i in range(2):
                p.mv_class0_hp[i] = _umv(bd, p.mv_class0_hp[i])
                p.mv_hp[i] = _umv(bd, p.mv_hp[i])

    if bd.bits_left < 0:
        return -1
    return bd.exit_padding_nonzero()


def _setup_compound_reference_mode(p, sb):
    if sb[LAST_FRAME] == sb[GOLDEN_FRAME]:
        p.comp_fixed_ref = ALTREF_FRAME
        p.comp_var_ref = [LAST_FRAME, GOLDEN_FRAME]
    elif sb[LAST_FRAME] == sb[ALTREF_FRAME]:
        p.comp_fixed_ref = GOLDEN_FRAME
        p.comp_var_ref = [LAST_FRAME, ALTREF_FRAME]
    else:
        p.comp_fixed_ref = LAST_FRAME
        p.comp_var_ref = [GOLDEN_FRAME, ALTREF_FRAME]


# ---- the frame decoder (extends the 3a key-frame entropy decoder) ----

class _FrameDecoder(D._KeyFrameDecoder):
    def __init__(self, hdr, probs, frame_is_intra, prev):
        super().__init__(hdr, probs)
        self.frame_is_intra = frame_is_intra
        self.ref_sign_bias = hdr.get('ref_frame_sign_bias', [0, 0, 0, 0])
        self.allow_hp = hdr.get('allow_high_precision_mv', 0)
        self.interp = hdr.get('interp_filter')
        self.reference_mode = probs.reference_mode
        self.comp_fixed_ref = probs.comp_fixed_ref
        self.comp_var_ref = probs.comp_var_ref
        self.prev = prev                      # previous frame's grids / UsePrev
        # per-8x8-cell inter grids
        R, C = self.mi_rows, self.mi_cols
        self.y_modes = [[DC_PRED] * C for _ in range(R)]
        self.ref_grid = [[[INTRA_FRAME, NONE] for _ in range(C)] for _ in range(R)]
        self.mv_grid = [[[ZERO_MV, ZERO_MV] for _ in range(C)] for _ in range(R)]
        self.submv_grid = [[[[ZERO_MV] * 4, [ZERO_MV] * 4] for _ in range(C)]
                           for _ in range(R)]
        self.interp_grid = [[0] * C for _ in range(R)]

    # partition probs: non-key frames use partition_probs, not kf_partition_probs
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
        probs = (T.KF_PARTITION_PROBS[ctx] if self.frame_is_intra
                 else self.p.partition[ctx])

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

    # dispatch mode info
    def _intra_mode_info(self, bd):
        if self.frame_is_intra:
            super()._intra_mode_info(bd)
            self.is_inter = 0
            self.ref_frame = [INTRA_FRAME, NONE]
            self.mv = [ZERO_MV, ZERO_MV]
            self.block_mvs = [[ZERO_MV] * 4, [ZERO_MV] * 4]
            self.interp_filter = 0
        else:
            self._inter_frame_mode_info(bd)

    def _block(self, bd, r, c, subsize):
        super()._block(bd, r, c, subsize)
        num_h = T.NUM_8X8_H[subsize]
        num_w = T.NUM_8X8_W[subsize]
        for y in range(num_h):
            for x in range(num_w):
                if r + y < self.mi_rows and c + x < self.mi_cols:
                    self.y_modes[r + y][c + x] = self.y_mode
                    self.ref_grid[r + y][c + x] = list(self.ref_frame)
                    self.mv_grid[r + y][c + x] = [self.block_mvs[0][3],
                                                  self.block_mvs[1][3]]
                    self.submv_grid[r + y][c + x] = [list(self.block_mvs[0]),
                                                     list(self.block_mvs[1])]
                    self.interp_grid[r + y][c + x] = self.interp_filter

    # -- inter_frame_mode_info (spec 6.4.11)
    def _inter_frame_mode_info(self, bd):
        r, c = self.MiRow, self.MiCol
        self.left_ref = [self.ref_grid[r][c - 1][0] if self.AvailL else INTRA_FRAME,
                         self.ref_grid[r][c - 1][1] if self.AvailL else NONE]
        self.above_ref = [self.ref_grid[r - 1][c][0] if self.AvailU else INTRA_FRAME,
                          self.ref_grid[r - 1][c][1] if self.AvailU else NONE]
        self.left_intra = self.left_ref[0] <= INTRA_FRAME
        self.above_intra = self.above_ref[0] <= INTRA_FRAME
        self.left_single = self.left_ref[1] <= NONE
        self.above_single = self.above_ref[1] <= NONE
        self.segment_id = 0                   # segmentation off in this corpus
        self.sub_mode = [DC_PRED] * 4         # overwritten by the intra path
        self.skip = self._read_skip(bd)
        self.is_inter = self._read_is_inter(bd)
        self.tx_size = self._read_tx_size(bd, (not self.skip) or (not self.is_inter))
        if self.is_inter:
            self._inter_block_mode_info(bd)
        else:
            self._intra_block_mode_info(bd)

    def _read_is_inter(self, bd):
        au, al = self.AvailU, self.AvailL
        if au and al:
            ctx = 3 if (self.left_intra and self.above_intra) else \
                int(self.left_intra or self.above_intra)
        elif au or al:
            ctx = 2 * (self.above_intra if au else self.left_intra)
        else:
            ctx = 0
        return bd.read_bool(self.p.is_inter[ctx])

    # -- non-key-frame intra block (spec 6.4.15)
    def _intra_block_mode_info(self, bd):
        self.ref_frame = [INTRA_FRAME, NONE]
        self.mv = [ZERO_MV, ZERO_MV]
        self.block_mvs = [[ZERO_MV] * 4, [ZERO_MV] * 4]
        self.interp_filter = 0
        if self.MiSize >= BLOCK_8X8:
            probs = self.p.y_mode[T.SIZE_GROUP_LOOKUP[self.MiSize]]
            mode = _read_tree(bd, T.INTRA_MODE_TREE, lambda n: probs[n])
            self.y_mode = mode
            self.sub_mode = [mode] * 4
        else:
            n4w = T.NUM_4X4_W[self.MiSize]
            n4h = T.NUM_4X4_H[self.MiSize]
            self.sub_mode = [DC_PRED] * 4
            probs = self.p.y_mode[0]
            idy = 0
            while idy < 2:
                idx = 0
                while idx < 2:
                    mode = _read_tree(bd, T.INTRA_MODE_TREE, lambda n: probs[n])
                    for y2 in range(n4h):
                        for x2 in range(n4w):
                            self.sub_mode[(idy + y2) * 2 + idx + x2] = mode
                    idx += n4w
                idy += n4h
            self.y_mode = mode
        uvp = self.p.uv_mode[self.y_mode]
        self.uv_mode = _read_tree(bd, T.INTRA_MODE_TREE, lambda n: uvp[n])

    # -- inter block (spec 6.4.16)
    def _inter_block_mode_info(self, bd):
        self._read_ref_frames(bd)
        self.nearest_mv = [ZERO_MV, ZERO_MV]
        self.near_mv = [ZERO_MV, ZERO_MV]
        self.best_mv = [ZERO_MV, ZERO_MV]
        self.mode_context = {}
        for j in range(2):
            if self.ref_frame[j] > INTRA_FRAME:
                self._find_mv_refs(self.ref_frame[j], -1)
                self._find_best_ref_mvs(j)
        is_compound = self.ref_frame[1] > INTRA_FRAME
        if self.MiSize >= BLOCK_8X8:
            probs = self.p.inter_mode[self.mode_context[self.ref_frame[0]]]
            im = _read_tree(bd, INTER_MODE_TREE, lambda n: probs[n])
            self.y_mode = NEARESTMV + im
        # interp_filter
        if self.interp == 'SWITCHABLE':
            self.interp_filter = self._read_interp_filter(bd)
        else:
            self.interp_filter = self.interp
        self.mv = [ZERO_MV, ZERO_MV]
        self.block_mvs = [[ZERO_MV] * 4, [ZERO_MV] * 4]
        if self.MiSize < BLOCK_8X8:
            n4w = T.NUM_4X4_W[self.MiSize]
            n4h = T.NUM_4X4_H[self.MiSize]
            idy = 0
            while idy < 2:
                idx = 0
                while idx < 2:
                    # ModeContext is updated by append_sub8x8_mvs (find_mv_refs
                    # side effect, spec 6.5.1), so each sub-block re-reads it.
                    probs = self.p.inter_mode[self.mode_context[self.ref_frame[0]]]
                    im = _read_tree(bd, INTER_MODE_TREE, lambda n: probs[n])
                    self.y_mode = NEARESTMV + im
                    if self.y_mode in (NEARESTMV, NEARMV):
                        for j in range(1 + is_compound):
                            self._append_sub8x8_mvs(idy * 2 + idx, j)
                    self._assign_mv(bd, is_compound)
                    for y2 in range(n4h):
                        for x2 in range(n4w):
                            b = (idy + y2) * 2 + idx + x2
                            for rl in range(1 + is_compound):
                                self.block_mvs[rl][b] = self.mv[rl]
                    idx += n4w
                idy += n4h
        else:
            self._assign_mv(bd, is_compound)
            for rl in range(1 + is_compound):
                for b in range(4):
                    self.block_mvs[rl][b] = self.mv[rl]

    def _read_interp_filter(self, bd):
        r, c = self.MiRow, self.MiCol
        left = (self.interp_grid[r][c - 1]
                if self.AvailL and self.left_ref[0] > INTRA_FRAME else 3)
        above = (self.interp_grid[r - 1][c]
                 if self.AvailU and self.above_ref[0] > INTRA_FRAME else 3)
        if left == above:
            ctx = left
        elif left == 3 and above != 3:
            ctx = above
        elif left != 3 and above == 3:
            ctx = left
        else:
            ctx = 3
        probs = self.p.interp_filter[ctx]
        return _read_tree(bd, INTERP_FILTER_TREE, lambda n: probs[n])

    # -- ref frames (spec 6.4.17)
    def _read_ref_frames(self, bd):
        if self.reference_mode == REFERENCE_MODE_SELECT:
            comp = bd.read_bool(self.p.comp_mode[self._comp_mode_ctx()])
        else:
            comp = 1 if self.reference_mode == COMPOUND_REFERENCE else 0
        if comp:
            idx = self.ref_sign_bias[self.comp_fixed_ref]
            cr = bd.read_bool(self.p.comp_ref[self._comp_ref_ctx()])
            self.ref_frame = [0, 0]
            self.ref_frame[idx] = self.comp_fixed_ref
            self.ref_frame[1 - idx] = self.comp_var_ref[cr]
        else:
            p1 = bd.read_bool(self.p.single_ref[self._single_ref_ctx(0)][0])
            if p1:
                p2 = bd.read_bool(self.p.single_ref[self._single_ref_ctx(1)][1])
                self.ref_frame = [ALTREF_FRAME if p2 else GOLDEN_FRAME, NONE]
            else:
                self.ref_frame = [LAST_FRAME, NONE]

    def _comp_mode_ctx(self):
        au, al = self.AvailU, self.AvailL
        cf = self.comp_fixed_ref
        if au and al:
            if self.above_single and self.left_single:
                return int((self.above_ref[0] == cf) ^ (self.left_ref[0] == cf))
            if self.above_single:
                return 2 + int(self.above_ref[0] == cf or self.above_intra)
            if self.left_single:
                return 2 + int(self.left_ref[0] == cf or self.left_intra)
            return 4
        if au:
            return int(self.above_ref[0] == cf) if self.above_single else 3
        if al:
            return int(self.left_ref[0] == cf) if self.left_single else 3
        return 1

    def _comp_ref_ctx(self):
        fix = self.ref_sign_bias[self.comp_fixed_ref]
        var = 1 - fix
        cv = self.comp_var_ref
        au, al = self.AvailU, self.AvailL
        ai, li = self.above_intra, self.left_intra
        asg, lsg = self.above_single, self.left_single
        ar, lr = self.above_ref, self.left_ref
        if au and al:
            if ai and li:
                return 2
            if li:
                return 1 + 2 * (int((ar[0] if asg else ar[var]) != cv[1]))
            if ai:
                return 1 + 2 * (int((lr[0] if lsg else lr[var]) != cv[1]))
            vrfa = ar[0] if asg else ar[var]
            vrfl = lr[0] if lsg else lr[var]
            if vrfa == vrfl and cv[1] == vrfa:
                return 0
            if lsg and asg:
                if ((vrfa == self.comp_fixed_ref and vrfl == cv[0]) or
                        (vrfl == self.comp_fixed_ref and vrfa == cv[0])):
                    return 4
                return 3 if vrfa == vrfl else 1
            if lsg or asg:
                vrfc = vrfa if lsg else vrfl
                rfs = vrfa if asg else vrfl
                if vrfc == cv[1] and rfs != cv[1]:
                    return 1
                if rfs == cv[1] and vrfc != cv[1]:
                    return 2
                return 4
            return 4 if vrfa == vrfl else 2
        if au:
            if ai:
                return 2
            if asg:
                return 3 * int(ar[0] != cv[1])
            return 4 * int(ar[var] != cv[1])
        if al:
            if li:
                return 2
            if lsg:
                return 3 * int(lr[0] != cv[1])
            return 4 * int(lr[var] != cv[1])
        return 2

    def _single_ref_ctx(self, which):
        au, al = self.AvailU, self.AvailL
        ai, li = self.above_intra, self.left_intra
        asg, lsg = self.above_single, self.left_single
        ar, lr = self.above_ref, self.left_ref
        L, G, A = LAST_FRAME, GOLDEN_FRAME, ALTREF_FRAME
        if which == 0:
            if au and al:
                if ai and li:
                    return 2
                if li:
                    if asg:
                        return 4 * int(ar[0] == L)
                    return 1 + int(ar[0] == L or ar[1] == L)
                if ai:
                    if lsg:
                        return 4 * int(lr[0] == L)
                    return 1 + int(lr[0] == L or lr[1] == L)
                if asg and lsg:
                    return 2 * int(ar[0] == L) + 2 * int(lr[0] == L)
                if not asg and not lsg:
                    return 1 + int(ar[0] == L or ar[1] == L or lr[0] == L or lr[1] == L)
                rfs = ar[0] if asg else lr[0]
                crf1 = lr[0] if asg else ar[0]
                crf2 = lr[1] if asg else ar[1]
                if rfs == L:
                    return 3 + int(crf1 == L or crf2 == L)
                return int(crf1 == L or crf2 == L)
            if au:
                if ai:
                    return 2
                if asg:
                    return 4 * int(ar[0] == L)
                return 1 + int(ar[0] == L or ar[1] == L)
            if al:
                if li:
                    return 2
                if lsg:
                    return 4 * int(lr[0] == L)
                return 1 + int(lr[0] == L or lr[1] == L)
            return 2
        # which == 1 (single_ref_p2)
        if au and al:
            if ai and li:
                return 2
            if li:
                if asg:
                    return 3 if ar[0] == L else 4 * int(ar[0] == G)
                return 1 + 2 * int(ar[0] == G or ar[1] == G)
            if ai:
                if lsg:
                    return 3 if lr[0] == L else 4 * int(lr[0] == G)
                return 1 + 2 * int(lr[0] == G or lr[1] == G)
            if asg and lsg:
                if ar[0] == L and lr[0] == L:
                    return 3
                if ar[0] == L:
                    return 4 * int(lr[0] == G)
                if lr[0] == L:
                    return 4 * int(ar[0] == G)
                return 2 * int(ar[0] == G) + 2 * int(lr[0] == G)
            if not asg and not lsg:
                if ar[0] == lr[0] and ar[1] == lr[1]:
                    return 3 * int(ar[0] == G or ar[1] == G)
                return 2
            rfs = ar[0] if asg else lr[0]
            crf1 = lr[0] if asg else ar[0]
            crf2 = lr[1] if asg else ar[1]
            if rfs == G:
                return 3 + int(crf1 == G or crf2 == G)
            if rfs == A:
                return int(crf1 == G or crf2 == G)
            return 1 + 2 * int(crf1 == G or crf2 == G)
        if au:
            if ai or (ar[0] == L and asg):
                return 2
            if asg:
                return 4 * int(ar[0] == G)
            return 3 * int(ar[0] == G or ar[1] == G)
        if al:
            if li or (lr[0] == L and lsg):
                return 2
            if lsg:
                return 4 * int(lr[0] == G)
            return 3 * int(lr[0] == G or lr[1] == G)
        return 2

    # -- assign_mv (spec 6.4.18) and read_mv (6.4.19-20)
    def _assign_mv(self, bd, is_compound):
        self.mv = [ZERO_MV, ZERO_MV]
        for i in range(1 + is_compound):
            if self.y_mode == NEWMV:
                self._read_mv(bd, i)
            elif self.y_mode == NEARESTMV:
                self.mv[i] = self.nearest_mv[i]
            elif self.y_mode == NEARMV:
                self.mv[i] = self.near_mv[i]
            else:
                self.mv[i] = ZERO_MV

    def _read_mv(self, bd, ref):
        use_hp = self.allow_hp and _use_mv_hp(self.best_mv[ref])
        joint = _read_tree(bd, MV_JOINT_TREE, lambda n: self.p.mv_joint[n])
        d0 = d1 = 0
        if joint in (MV_JOINT_HZVNZ, MV_JOINT_HNZVNZ):
            d0 = self._read_mv_component(bd, 0, use_hp)
        if joint in (MV_JOINT_HNZVZ, MV_JOINT_HNZVNZ):
            d1 = self._read_mv_component(bd, 1, use_hp)
        self.mv[ref] = (self.best_mv[ref][0] + d0, self.best_mv[ref][1] + d1)

    def _read_mv_component(self, bd, comp, use_hp):
        sign = bd.read_bool(self.p.mv_sign[comp])
        cls = _read_tree(bd, MV_CLASS_TREE, lambda n: self.p.mv_class[comp][n])
        if cls == 0:
            bit = bd.read_bool(self.p.mv_class0_bit[comp])
            fr = _read_tree(bd, MV_FR_TREE,
                            lambda n: self.p.mv_class0_fr[comp][bit][n])
            hp = bd.read_bool(self.p.mv_class0_hp[comp]) if use_hp else 1
            mag = ((bit << 3) | (fr << 1) | hp) + 1
        else:
            d = 0
            for i in range(cls):
                d |= bd.read_bool(self.p.mv_bits[comp][i]) << i
            mag = CLASS0_SIZE << (cls + 2)
            fr = _read_tree(bd, MV_FR_TREE, lambda n: self.p.mv_fr[comp][n])
            hp = bd.read_bool(self.p.mv_hp[comp]) if use_hp else 1
            mag += ((d << 3) | (fr << 1) | hp) + 1
        return -mag if sign else mag

    # -- find_mv_refs (spec 6.5)
    def _is_inside(self, r, c):
        return (0 <= r < self.mi_rows and self.MiColStart <= c < self.MiColEnd)

    def _find_mv_refs(self, ref_frame, block):
        self.ref_mv_count = 0
        self.ref_list_mv = [ZERO_MV, ZERO_MV]
        different_ref_found = 0
        context_counter = 0
        search = MV_REF_BLOCKS[self.MiSize]
        r, c = self.MiRow, self.MiCol
        for i in range(2):
            cr = r + search[i][0]
            cc = c + search[i][1]
            if self._is_inside(cr, cc):
                different_ref_found = 1
                context_counter += MODE_2_COUNTER[self.y_modes[cr][cc]]
                for j in range(2):
                    if self.ref_grid[cr][cc][j] == ref_frame:
                        cmv = self._get_sub_block_mv(cr, cc, j, search[i][1], block)
                        self._add_mv_ref_list(cmv)
                        break
        for i in range(2, MVREF_NEIGHBOURS):
            cr = r + search[i][0]
            cc = c + search[i][1]
            if self._is_inside(cr, cc):
                different_ref_found = 1
                self._if_same_ref_frame_add(cr, cc, ref_frame, 0)
        if self.use_prev_mvs:
            self._if_same_ref_frame_add(r, c, ref_frame, 1)
        if different_ref_found:
            for i in range(MVREF_NEIGHBOURS):
                cr = r + search[i][0]
                cc = c + search[i][1]
                if self._is_inside(cr, cc):
                    self._if_diff_ref_frame_add(cr, cc, ref_frame, 0)
        if self.use_prev_mvs:
            self._if_diff_ref_frame_add(r, c, ref_frame, 1)
        self.mode_context[ref_frame] = COUNTER_TO_CONTEXT[context_counter]
        for i in range(MAX_MV_REF_CANDIDATES):
            self.ref_list_mv[i] = (self._clamp_mv_row(self.ref_list_mv[i][0], MV_BORDER),
                                   self._clamp_mv_col(self.ref_list_mv[i][1], MV_BORDER))

    def _get_block_mv(self, cr, cc, rl, use_prev):
        if use_prev:
            self.cand_mv[rl] = self.prev['mv'][cr][cc][rl]
            self.cand_frame[rl] = self.prev['ref'][cr][cc][rl]
        else:
            self.cand_mv[rl] = self.mv_grid[cr][cc][rl]
            self.cand_frame[rl] = self.ref_grid[cr][cc][rl]

    def _get_sub_block_mv(self, cr, cc, rl, delta_col, block):
        idx = IDX_N_COLUMN_TO_SUBBLOCK[block][1 if delta_col == 0 else 0] if block >= 0 else 3
        return self.submv_grid[cr][cc][rl][idx]

    def _add_mv_ref_list(self, cmv):
        if self.ref_mv_count >= 2:
            return
        if self.ref_mv_count > 0 and cmv == self.ref_list_mv[0]:
            return
        self.ref_list_mv[self.ref_mv_count] = cmv
        self.ref_mv_count += 1

    def _if_same_ref_frame_add(self, cr, cc, ref_frame, use_prev):
        self.cand_mv = [ZERO_MV, ZERO_MV]
        self.cand_frame = [INTRA_FRAME, INTRA_FRAME]
        for j in range(2):
            self._get_block_mv(cr, cc, j, use_prev)
            if self.cand_frame[j] == ref_frame:
                self._add_mv_ref_list(self.cand_mv[j])
                return

    def _if_diff_ref_frame_add(self, cr, cc, ref_frame, use_prev):
        self.cand_mv = [ZERO_MV, ZERO_MV]
        self.cand_frame = [INTRA_FRAME, INTRA_FRAME]
        for j in range(2):
            self._get_block_mv(cr, cc, j, use_prev)
        mvs_same = self.cand_mv[0] == self.cand_mv[1]
        if self.cand_frame[0] > INTRA_FRAME and self.cand_frame[0] != ref_frame:
            self._scale_and_add(0, ref_frame)
        if (self.cand_frame[1] > INTRA_FRAME and self.cand_frame[1] != ref_frame
                and not mvs_same):
            self._scale_and_add(1, ref_frame)

    def _scale_and_add(self, rl, ref_frame):
        cand = self.cand_frame[rl]
        mv = self.cand_mv[rl]
        if self.ref_sign_bias[cand] != self.ref_sign_bias[ref_frame]:
            mv = (-mv[0], -mv[1])
        self._add_mv_ref_list(mv)

    def _clamp_mv_row(self, mvec, border):
        bh = T.NUM_8X8_H[self.MiSize]
        top = -((self.MiRow * MI_SIZE) * 8)
        bottom = ((self.mi_rows - bh - self.MiRow) * MI_SIZE) * 8
        return max(top - border, min(bottom + border, mvec))

    def _clamp_mv_col(self, mvec, border):
        bw = T.NUM_8X8_W[self.MiSize]
        left = -((self.MiCol * MI_SIZE) * 8)
        right = ((self.mi_cols - bw - self.MiCol) * MI_SIZE) * 8
        return max(left - border, min(right + border, mvec))

    def _find_best_ref_mvs(self, rl):
        border = (BORDERINPIXELS - INTERP_EXTEND) << 3
        for i in range(MAX_MV_REF_CANDIDATES):
            dr, dc = self.ref_list_mv[i]
            if not self.allow_hp or not _use_mv_hp(self.ref_list_mv[i]):
                if dr & 1:
                    dr += -1 if dr > 0 else 1
                if dc & 1:
                    dc += -1 if dc > 0 else 1
            self.ref_list_mv[i] = (self._clamp_mv_row(dr, border),
                                   self._clamp_mv_col(dc, border))
        self.nearest_mv[rl] = self.ref_list_mv[0]
        self.near_mv[rl] = self.ref_list_mv[1]
        self.best_mv[rl] = self.ref_list_mv[0]

    def _append_sub8x8_mvs(self, block, rl):
        self._find_mv_refs(self.ref_frame[rl], block)
        sub = []
        if block == 0:
            sub = [self.ref_list_mv[0], self.ref_list_mv[1]]
        elif block <= 2:
            sub = [self.block_mvs[rl][0]]
        else:
            sub = [self.block_mvs[rl][2]]
            for idx in (1, 0):
                if len(sub) >= 2:
                    break
                if self.block_mvs[rl][idx] != sub[0]:
                    sub.append(self.block_mvs[rl][idx])
        for n in range(2):
            if len(sub) >= 2:
                break
            if self.ref_list_mv[n] != sub[0]:
                sub.append(self.ref_list_mv[n])
        if len(sub) < 2:
            sub.append(ZERO_MV)
        self.nearest_mv[rl] = sub[0]
        self.near_mv[rl] = sub[1]

    # inter blocks index coef_probs[...][is_inter]; override the 3a token reader
    def _tokens(self, bd, plane, start_x, start_y, txsz, block_idx):
        seg_eob = 16 << (txsz << 1)
        tx_type = self._tx_type(plane, txsz, block_idx)
        scan = self._get_scan(tx_type, txsz)
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
                check_eob = 0
            else:
                self._read_coef(bd, token)
                bd.read_literal(1)
                check_eob = 1
            c += 1
        return 1 if c > 0 else 0


def _use_mv_hp(mv):
    return (abs(mv[0]) >> 3) < COMPANDED_MVREF_THRESH and \
           (abs(mv[1]) >> 3) < COMPANDED_MVREF_THRESH


# ---- sequence driver: frame contexts + prev-frame state ----

def _decode_frame_padding(data, lo, hi, probs, h, frame_is_intra, prev, use_prev):
    dec = _FrameDecoder(h, probs, frame_is_intra, prev)
    dec.use_prev_mvs = use_prev
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
            r0 = D._tile_offset(tr, mi_rows, h['tile_rows_log2'])
            r1 = D._tile_offset(tr + 1, mi_rows, h['tile_rows_log2'])
            c0 = D._tile_offset(tc, mi_cols, h['tile_cols_log2'])
            c1 = D._tile_offset(tc + 1, mi_cols, h['tile_cols_log2'])
            bd = vp9.BoolDecoder(data, pos, size)
            for pl in range(3):
                dec.above_nz[pl] = [0] * len(dec.above_nz[pl])
            dec.above_part = [0] * len(dec.above_part)
            dec.decode_tile(bd, r0, r1, c0, c1)
            if bd.bits_left < 0:
                return -1, dec
            total_pad += bd.exit_padding_nonzero()
            pos += size
    return total_pad, dec


def decode_clip_padding(doc, blob, max_frames=None):
    """Decode every frame of one VP9 clip (key frame + inter frames) for its
    entropy only, and return the total non-zero tile padding across all frames
    (0 == a clean, fully in-sync decode of the whole clip). Tracks the 4 frame
    contexts and the previous frame's MV grids exactly as a decoder would."""
    contexts = [FrameProbs.default() for _ in range(4)]
    prev = None
    parser = vp9.VP9HeaderParser()
    total = 0
    nfr = 0
    for _, _, _, off, size in doc.frames:
        block = blob[off:off + size]
        for lo, hi in vp9.superframe_split(block):
            if hi <= lo or lo >= len(block) or (block[lo] >> 6) != 2:
                continue
            h = parser.parse(block[lo:hi])
            if h is None or 'show_existing' in h:
                continue
            frame_is_intra = bool(h.get('keyframe') or h.get('intra_only'))
            # setup_past_independence: reset all contexts on intra frames
            if frame_is_intra or h.get('error_resilient'):
                contexts = [FrameProbs.default() for _ in range(4)]
            idx = h.get('frame_context_idx', 0)
            probs = contexts[idx].copy()
            pad = parse_compressed(probs, h, block, lo + h['uncompressed_bytes'])
            if pad != 0:
                return -100000 + pad, nfr
            # UsePrevFrameMvs (spec compute_image_size step 2)
            use_prev = (prev is not None and prev['w'] == h['width']
                        and prev['h'] == h['height'] and prev['show'] == 1
                        and not h.get('error_resilient') and not frame_is_intra)
            fpad, dec = _decode_frame_padding(block, lo, hi, probs, h,
                                              frame_is_intra, prev, use_prev)
            total += fpad
            if h.get('refresh_frame_context'):
                contexts[idx] = probs.copy()
            # previous-frame state for UsePrevFrameMvs on the next frame
            prev = {'mv': dec.mv_grid, 'ref': dec.ref_grid,
                    'w': h['width'], 'h': h['height'],
                    'show': h.get('show_frame', 1)}
            nfr += 1
            if max_frames and nfr >= max_frames:
                return total, nfr
    return total, nfr


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('file')
    a = ap.parse_args()
    data = open(a.file, 'rb').read()
    from webm import WebM
    doc = WebM(data)
    pad, n = decode_clip_padding(doc, data)
    print('clip: %d frames, total tile padding %d (%s)'
          % (n, pad, 'clean' if pad == 0 else 'DESYNC'))


if __name__ == '__main__':
    main()
