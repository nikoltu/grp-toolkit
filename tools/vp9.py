#!/usr/bin/env python3
"""VP9 — stage 1: superframe split and the uncompressed frame header.

Written from the VP9 Bitstream & Decoding Process Specification v0.6 (Grange,
de Rivaz, Hunt; Google/Argon, 2016). This is the first of several stages: it
parses the *uncompressed* header of every frame — both profiles, key / intra /
inter — and the superframe index that packs several frames in one block. It
does NOT decode the compressed header or any pixels yet.

Why this alone is a real, checkable milestone (same idea as VP8 stage a/b):
the uncompressed header carries fields with spec-legal ranges and the frame
dimensions, which the Matroska container also states independently. A wrong bit
offset drifts these out of range or away from the container almost immediately.
It is stateful because an inter frame's size can be inherited from a reference
frame (frame_size_with_refs), so the parser remembers each reference slot's
dimensions across frames, exactly as a decoder must.

    from vp9 import VP9HeaderParser, superframe_split
    p = VP9HeaderParser()
    for lo, hi in superframe_split(block):
        h = p.parse(block[lo:hi])

The big constant tables (probabilities, scans, quant) belong to later stages
and are extracted mechanically from the spec by tools/gen_vp9_tables.py.
"""

# --- constants (VP9 spec §3) ---
KEY_FRAME = 0
CS_UNKNOWN, CS_BT_601, CS_RGB = 0, 1, 7
LAST_FRAME = 1
MAX_SEGMENTS, SEG_LVL_MAX = 8, 4
MIN_TILE_WIDTH_B64, MAX_TILE_WIDTH_B64 = 4, 64
REFS_PER_FRAME = 3
NUM_REF_FRAMES = 8

SEG_FEATURE_BITS = (8, 6, 2, 0)
SEG_FEATURE_SIGNED = (1, 1, 0, 0)
# read_interpolation_filter's literal_to_type
INTERP_LITERAL_TO_TYPE = (1, 0, 2, 3)   # EIGHTTAP_SMOOTH, EIGHTTAP, SHARP, BILINEAR
VP9_SYNC = (0x49, 0x83, 0x42)


def superframe_split(buf):
    """Byte ranges of the sub-frames packed in one VP9 block (VP9 spec Annex B).
    Returns [(0, len)] when there is no superframe index."""
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


class _Bits:
    """MSB-first bit reader for the uncompressed header (descriptors f(n)/s(n))."""
    __slots__ = ('d', 'pos')

    def __init__(self, data):
        self.d = data
        self.pos = 0

    def f(self, n):
        v = 0
        for _ in range(n):
            byte = self.d[self.pos >> 3] if (self.pos >> 3) < len(self.d) else 0
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def s(self, n):
        """s(n): an n-bit magnitude followed by a sign bit (spec §4.9.2)."""
        v = self.f(n)
        return -v if self.f(1) else v

    @property
    def byte_pos(self):
        return (self.pos + 7) >> 3


class VP9HeaderParser:
    """Parses uncompressed headers across a frame sequence, carrying the
    reference-frame dimensions an inter frame may inherit."""

    def __init__(self):
        self.ref_w = [0] * NUM_REF_FRAMES
        self.ref_h = [0] * NUM_REF_FRAMES
        self.frame_type = KEY_FRAME
        # Colour config (subsampling / bit depth / colour space) is signalled
        # only on key frames and intra-only frames; inter frames inherit the
        # sequence's config. Carry the last-seen values so an inter frame gets
        # the right chroma resolution (else 4:4:4 clips desync as 4:2:0).
        self.subsampling = (1, 1)
        self.bit_depth = 8
        self.color_space = CS_BT_601

    def parse(self, buf):
        """Return the uncompressed header of one frame as a dict, or None if the
        frame marker / sync code is not what the spec requires."""
        b = _Bits(buf)
        h = {}
        if b.f(2) != 2:                       # frame_marker
            return None
        prof = b.f(1) | (b.f(1) << 1)
        if prof == 3:
            b.f(1)                            # reserved_zero
        h['profile'] = prof
        if b.f(1):                            # show_existing_frame
            h['show_existing'] = b.f(3)
            h['header_size_in_bytes'] = 0
            return h

        ft = b.f(1)
        h['keyframe'] = (ft == KEY_FRAME)
        h['show_frame'] = b.f(1)
        h['error_resilient'] = b.f(1)
        h['intra_only'] = ft == KEY_FRAME
        refresh = 0

        if ft == KEY_FRAME:
            if not self._sync(b):
                return None
            self._color_config(b, prof, h)
            self._frame_size(b, h)
            self._render_size(b, h)
            refresh = 0xFF
            h['frame_is_intra'] = True
        else:
            intra_only = b.f(1) if h['show_frame'] == 0 else 0
            h['intra_only'] = bool(intra_only)
            h['frame_is_intra'] = bool(intra_only)
            if h['error_resilient'] == 0:
                b.f(2)                        # reset_frame_context
            if intra_only:
                if not self._sync(b):
                    return None
                if prof > 0:
                    self._color_config(b, prof, h)
                else:
                    h['color_space'] = CS_BT_601
                    h['subsampling'] = (1, 1)
                    h['bit_depth'] = 8
                refresh = b.f(8)
                self._frame_size(b, h)
                self._render_size(b, h)
            else:
                refresh = b.f(8)
                idx = []
                sign_bias = [0, 0, 0, 0]
                for i in range(REFS_PER_FRAME):
                    idx.append(b.f(3))
                    sign_bias[LAST_FRAME + i] = b.f(1)
                h['ref_frame_idx'] = idx
                h['ref_frame_sign_bias'] = sign_bias
                self._frame_size_with_refs(b, h, idx)
                h['allow_high_precision_mv'] = b.f(1)
                self._interp_filter(b, h)

        if h['error_resilient'] == 0:
            h['refresh_frame_context'] = b.f(1)
            h['frame_parallel_decoding_mode'] = b.f(1)
        else:
            h['refresh_frame_context'] = 0
            h['frame_parallel_decoding_mode'] = 1
        h['frame_context_idx'] = b.f(2)

        h['refresh_frame_flags'] = refresh
        h['ref_frame_idx'] = h.get('ref_frame_idx', [0, 0, 0])
        self._loop_filter(b, h)
        self._quant(b, h)
        self._segmentation(b, h)
        self._tile_info(b, h)
        h['header_size_in_bytes'] = b.f(16)

        # Commit dimensions to every reference slot this frame refreshes, so a
        # later inter frame can inherit them.
        for i in range(NUM_REF_FRAMES):
            if refresh & (1 << i):
                self.ref_w[i] = h['width']
                self.ref_h[i] = h['height']
        self.frame_type = ft
        # Persist / inherit colour config across the sequence. A frame that read
        # its own color_config updated self.* below; an inter frame inherits it.
        if 'subsampling' in h:
            self.subsampling = h['subsampling']
            self.bit_depth = h['bit_depth']
            self.color_space = h['color_space']
        else:
            h['subsampling'] = self.subsampling
            h['bit_depth'] = self.bit_depth
            h['color_space'] = self.color_space
        h['uncompressed_bytes'] = b.byte_pos
        return h

    # -- sub-syntax --------------------------------------------------------
    def _sync(self, b):
        return (b.f(8), b.f(8), b.f(8)) == VP9_SYNC

    def _color_config(self, b, prof, h):
        h['bit_depth'] = (12 if b.f(1) else 10) if prof >= 2 else 8
        cs = b.f(3)
        h['color_space'] = cs
        if cs != CS_RGB:
            h['color_range'] = b.f(1)
            if prof in (1, 3):
                h['subsampling'] = (b.f(1), b.f(1))
                b.f(1)                        # reserved_zero
            else:
                h['subsampling'] = (1, 1)
        else:
            h['color_range'] = 1
            if prof in (1, 3):
                h['subsampling'] = (0, 0)
                b.f(1)                        # reserved_zero
            else:
                h['subsampling'] = (0, 0)

    def _frame_size(self, b, h):
        h['width'] = b.f(16) + 1
        h['height'] = b.f(16) + 1
        self._image_size(h)

    def _render_size(self, b, h):
        if b.f(1):
            h['render'] = (b.f(16) + 1, b.f(16) + 1)
        else:
            h['render'] = (h['width'], h['height'])

    def _frame_size_with_refs(self, b, h, idx):
        found = 0
        for i in range(REFS_PER_FRAME):
            found = b.f(1)
            if found:
                h['width'] = self.ref_w[idx[i]]
                h['height'] = self.ref_h[idx[i]]
                break
        if not found:
            h['width'] = b.f(16) + 1
            h['height'] = b.f(16) + 1
        self._image_size(h)
        self._render_size(b, h)

    def _image_size(self, h):
        mi_cols = (h['width'] + 7) >> 3
        mi_rows = (h['height'] + 7) >> 3
        h['sb64_cols'] = (mi_cols + 7) >> 3
        h['sb64_rows'] = (mi_rows + 7) >> 3

    def _interp_filter(self, b, h):
        if b.f(1):
            h['interp_filter'] = 'SWITCHABLE'
        else:
            h['interp_filter'] = INTERP_LITERAL_TO_TYPE[b.f(2)]

    def _loop_filter(self, b, h):
        h['loop_filter_level'] = b.f(6)
        h['loop_filter_sharpness'] = b.f(3)
        # Defaults from setup_past_independence (applied on key/intra frames).
        ref_deltas = [1, 0, -1, -1]           # INTRA, LAST, GOLDEN, ALTREF
        mode_deltas = [0, 0]
        enabled = b.f(1)                      # delta_enabled
        if enabled:
            if b.f(1):                        # delta_update
                for i in range(4):
                    if b.f(1):
                        ref_deltas[i] = b.s(6)
                for i in range(2):
                    if b.f(1):
                        mode_deltas[i] = b.s(6)
        h['loop_filter_delta_enabled'] = enabled
        h['loop_filter_ref_deltas'] = ref_deltas
        h['loop_filter_mode_deltas'] = mode_deltas

    def _read_delta_q(self, b):
        return b.s(4) if b.f(1) else 0

    def _quant(self, b, h):
        h['base_q_idx'] = b.f(8)
        dc_y = self._read_delta_q(b)
        dc_uv = self._read_delta_q(b)
        ac_uv = self._read_delta_q(b)
        h['delta_q_y_dc'] = dc_y
        h['delta_q_uv_dc'] = dc_uv
        h['delta_q_uv_ac'] = ac_uv
        h['lossless'] = (h['base_q_idx'] == 0 and dc_y == 0
                         and dc_uv == 0 and ac_uv == 0)

    def _read_prob(self, b):
        return b.f(8) if b.f(1) else 255

    def _segmentation(self, b, h):
        h['segmentation_enabled'] = b.f(1)
        if not h['segmentation_enabled']:
            return
        if b.f(1):                            # update_map
            for _ in range(7):
                self._read_prob(b)            # tree_probs
            temporal = b.f(1)
            for _ in range(3):
                if temporal:
                    self._read_prob(b)        # pred_prob
        if b.f(1):                            # update_data
            b.f(1)                            # abs_or_delta_update
            for _ in range(MAX_SEGMENTS):
                for j in range(SEG_LVL_MAX):
                    if b.f(1):                # feature_enabled
                        bits = SEG_FEATURE_BITS[j]
                        if bits:
                            b.f(bits)
                        if SEG_FEATURE_SIGNED[j]:
                            b.f(1)

    def _tile_info(self, b, h):
        sb64_cols = h['sb64_cols']
        min_log2 = 0
        while (MAX_TILE_WIDTH_B64 << min_log2) < sb64_cols:
            min_log2 += 1
        max_log2 = 1
        while (sb64_cols >> max_log2) >= MIN_TILE_WIDTH_B64:
            max_log2 += 1
        max_log2 -= 1
        cols_log2 = min_log2
        while cols_log2 < max_log2:
            if b.f(1):
                cols_log2 += 1
            else:
                break
        rows_log2 = b.f(1)
        if rows_log2 == 1:
            rows_log2 += b.f(1)
        h['tile_cols_log2'] = cols_log2
        h['tile_rows_log2'] = rows_log2


# --- compressed header (stage 2) -----------------------------------------
# Constants from the spec §3.
TX_SIZE_CONTEXTS, TX_SIZES, TX_MODES = 2, 4, 5
TX_MODE_SELECT = 4
TX_MODE_TO_BIGGEST = (0, 1, 2, 3, 3)     # TX_4X4..TX_32X32, TX_32X32
SKIP_CONTEXTS = 3
INTER_MODE_CONTEXTS, INTER_MODES = 7, 4
INTERP_FILTER_CONTEXTS, SWITCHABLE_FILTERS = 4, 3
IS_INTER_CONTEXTS = 4
COMP_MODE_CONTEXTS, REF_CONTEXTS = 5, 5
BLOCK_SIZE_GROUPS, INTRA_MODES = 4, 10
PARTITION_CONTEXTS, PARTITION_TYPES = 16, 4
MV_JOINTS, MV_CLASSES, CLASS0_SIZE = 4, 11, 2
MV_OFFSET_BITS, MV_FR_SIZE = 10, 4
SINGLE_REFERENCE, COMPOUND_REFERENCE, REFERENCE_MODE_SELECT = 0, 1, 2
GOLDEN_FRAME, ALTREF_FRAME = 2, 3


class BoolDecoder:
    """VP9 arithmetic ('boolean') decoder (spec §9.2). Reads the compressed
    header. `bits_left` (BoolMaxBits) is the conformance tripwire: it must never
    go negative, and after the syntax the remainder must be zero padding."""
    __slots__ = ('d', 'pos', 'end', 'value', 'rng', 'bits_left')

    def __init__(self, data, start, sz):
        self.d = data
        self.pos = start * 8
        self.end = (start + sz) * 8
        self.value = self._f(8)
        self.rng = 255
        self.bits_left = 8 * sz - 8
        # init_bool reads a marker bool that must be 0 (spec §9.2.1). Omitting
        # it leaves every later read misaligned by one bool — which small
        # headers survive by luck but a keyframe's coefficient updates do not.
        self.read_bool(128)

    def _f(self, n):
        v = 0
        for _ in range(n):
            bit = 0
            if self.pos < self.end and (self.pos >> 3) < len(self.d):
                bit = (self.d[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
            v = (v << 1) | bit
            self.pos += 1
        return v

    def read_bool(self, p):
        split = 1 + (((self.rng - 1) * p) >> 8)
        if self.value < split:
            self.rng = split
            bit = 0
        else:
            self.rng -= split
            self.value -= split
            bit = 1
        while self.rng < 128:
            nb = 0
            if self.bits_left > 0:
                nb = self._f(1)
                self.bits_left -= 1
            self.rng <<= 1
            self.value = (self.value << 1) + nb
        return bit

    def read_literal(self, n):
        x = 0
        for _ in range(n):
            x = (x << 1) | self.read_bool(128)
        return x

    def exit_padding_nonzero(self):
        """Read the remaining bits (exit_bool's padding). The spec requires them
        to be zero; a non-zero bit means real data was left unparsed — i.e. the
        header structure was decoded wrongly."""
        bad = 0
        while self.bits_left > 0:
            if self._f(1):
                bad += 1
            self.bits_left -= 1
        return bad


def _decode_term_subexp(bd):
    """spec §6.3.4 — variable-length prob delta. Only the bit consumption
    matters for the header-size oracle."""
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


def _diff_update_prob(bd):
    if bd.read_bool(252):
        _decode_term_subexp(bd)


def _update_mv_prob(bd):
    if bd.read_bool(252):
        bd.read_literal(7)


def parse_compressed_header(data, start, h):
    """Parse the compressed header of one frame (spec §6.3) and return the
    number of non-zero padding bits after it (0 == a clean, in-sync parse).

    This verifies the arithmetic decoder and the whole probability-update
    structure without needing the default probability *values*: the number of
    bits each diff_update_prob consumes does not depend on the current prob, so
    the header-size / padding oracle is exact regardless."""
    sz = h['header_size_in_bytes']
    bd = BoolDecoder(data, start, sz)

    lossless = h.get('lossless', False)
    frame_is_intra = h.get('frame_is_intra', True)
    interp = h.get('interp_filter')
    sign_bias = h.get('ref_frame_sign_bias', [0, 0, 0, 0])
    hp_mv = h.get('allow_high_precision_mv', 0)

    # read_tx_mode
    if lossless:
        tx_mode = 0
    else:
        tx_mode = bd.read_literal(2)
        if tx_mode == 3:                      # ALLOW_32X32
            tx_mode += bd.read_literal(1)
    if tx_mode == TX_MODE_SELECT:
        for _ in range(TX_SIZE_CONTEXTS):
            for _ in range(TX_SIZES - 3):
                _diff_update_prob(bd)
        for _ in range(TX_SIZE_CONTEXTS):
            for _ in range(TX_SIZES - 2):
                _diff_update_prob(bd)
        for _ in range(TX_SIZE_CONTEXTS):
            for _ in range(TX_SIZES - 1):
                _diff_update_prob(bd)

    # read_coef_probs
    max_tx = TX_MODE_TO_BIGGEST[tx_mode]
    for _txsz in range(0, max_tx + 1):
        if bd.read_literal(1):
            for _i in range(2):
                for _j in range(2):
                    for k in range(6):
                        maxl = 3 if k == 0 else 6
                        for _l in range(maxl):
                            for _m in range(3):
                                _diff_update_prob(bd)

    # read_skip_prob
    for _ in range(SKIP_CONTEXTS):
        _diff_update_prob(bd)

    if not frame_is_intra:
        for _ in range(INTER_MODE_CONTEXTS):
            for _ in range(INTER_MODES - 1):
                _diff_update_prob(bd)
        if interp == 'SWITCHABLE':
            for _ in range(INTERP_FILTER_CONTEXTS):
                for _ in range(SWITCHABLE_FILTERS - 1):
                    _diff_update_prob(bd)
        for _ in range(IS_INTER_CONTEXTS):
            _diff_update_prob(bd)

        # frame_reference_mode
        compound_allowed = any(sign_bias[i + 1] != sign_bias[1]
                               for i in range(1, REFS_PER_FRAME))
        if compound_allowed:
            if bd.read_literal(1) == 0:
                ref_mode = SINGLE_REFERENCE
            else:
                ref_mode = (COMPOUND_REFERENCE if bd.read_literal(1) == 0
                            else REFERENCE_MODE_SELECT)
        else:
            ref_mode = SINGLE_REFERENCE
        # frame_reference_mode_probs
        if ref_mode == REFERENCE_MODE_SELECT:
            for _ in range(COMP_MODE_CONTEXTS):
                _diff_update_prob(bd)
        if ref_mode != COMPOUND_REFERENCE:
            for _ in range(REF_CONTEXTS):
                _diff_update_prob(bd)
                _diff_update_prob(bd)
        if ref_mode != SINGLE_REFERENCE:
            for _ in range(REF_CONTEXTS):
                _diff_update_prob(bd)

        # read_y_mode_probs
        for _ in range(BLOCK_SIZE_GROUPS):
            for _ in range(INTRA_MODES - 1):
                _diff_update_prob(bd)
        # read_partition_probs
        for _ in range(PARTITION_CONTEXTS):
            for _ in range(PARTITION_TYPES - 1):
                _diff_update_prob(bd)
        # mv_probs
        for _ in range(MV_JOINTS - 1):
            _update_mv_prob(bd)
        for _ in range(2):
            _update_mv_prob(bd)                        # sign
            for _ in range(MV_CLASSES - 1):
                _update_mv_prob(bd)                    # class
            _update_mv_prob(bd)                        # class0_bit
            for _ in range(MV_OFFSET_BITS):
                _update_mv_prob(bd)                    # bits
        for _ in range(2):
            for _ in range(CLASS0_SIZE):
                for _ in range(MV_FR_SIZE - 1):
                    _update_mv_prob(bd)                # class0_fr
            for _ in range(MV_FR_SIZE - 1):
                _update_mv_prob(bd)                    # fr
        if hp_mv:
            for _ in range(2):
                _update_mv_prob(bd)                    # class0_hp
                _update_mv_prob(bd)                    # hp

    if bd.bits_left < 0:
        return -1                              # over-read: definite desync
    return bd.exit_padding_nonzero()


def check(h):
    """Spec-legal ranges for the uncompressed header. A drifted bit offset
    trips one of these almost immediately."""
    bad = []
    if h.get('show_existing') is not None:
        return bad
    if not (0 <= h['profile'] <= 3):
        bad.append('profile=%d' % h['profile'])
    if not (0 <= h['loop_filter_level'] <= 63):
        bad.append('lf_level=%d' % h['loop_filter_level'])
    if not (0 <= h['loop_filter_sharpness'] <= 7):
        bad.append('lf_sharp=%d' % h['loop_filter_sharpness'])
    if not (0 <= h['base_q_idx'] <= 255):
        bad.append('q=%d' % h['base_q_idx'])
    if 'color_space' in h and not (0 <= h['color_space'] <= 7):
        bad.append('cs=%d' % h['color_space'])
    if h.get('color_space') == CS_RGB and h['profile'] in (0, 2):
        bad.append('RGB in profile %d' % h['profile'])   # conformance rule
    if not (1 <= h['width'] <= 65536) or not (1 <= h['height'] <= 65536):
        bad.append('dim=%dx%d' % (h['width'], h['height']))
    if h['header_size_in_bytes'] == 0 and not h.get('show_existing'):
        bad.append('header_size_in_bytes=0')
    return bad


def main():
    import sys
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('file', help='.webm')
    a = ap.parse_args()
    data = open(a.file, 'rb').read()
    from webm import WebM
    doc = WebM(data)
    if doc.codec != 'V_VP9':
        sys.exit('%s is %s, not VP9' % (a.file, doc.codec))
    p = VP9HeaderParser()
    nfr = 0
    for _, _, _, off, size in doc.frames:
        blk = data[off:off + size]
        for lo, hi in superframe_split(blk):
            h = p.parse(blk[lo:hi])
            nfr += 1
            if h is None:
                print('frame %d: not a VP9 frame' % nfr)
                continue
            if 'show_existing' in h:
                print('frame %d: show_existing %d' % (nfr, h['show_existing']))
                continue
            bad = check(h)
            tag = 'KEY' if h['keyframe'] else ('INTRA' if h['intra_only'] else 'inter')
            print('frame %2d %-5s prof%d %dx%d q=%d lf=%d hdr=%dB%s'
                  % (nfr, tag, h['profile'], h['width'], h['height'],
                     h['base_q_idx'], h['loop_filter_level'],
                     h['header_size_in_bytes'],
                     ('  BAD:' + ','.join(bad)) if bad else ''))


if __name__ == '__main__':
    main()
