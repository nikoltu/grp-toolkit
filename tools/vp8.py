#!/usr/bin/env python3
"""VP8 — stage (a)+(b): boolean entropy decoder and keyframe header.

Written from RFC 6386 ("VP8 Data Format and Decoding Guide"). This is the first
two milestones of the staged plan; it does NOT decode
pixels yet. It stops right after `refresh_entropy_probs`, before the token
probability tables.

Why stop there and still call it useful: the header carries values with
spec-legal ranges (filter level 0..63, sharpness 0..7, quantiser index 0..127,
1/2/4/8 partitions) and the frame dimensions, which the Matroska container also
states independently. If the boolean decoder were wrong, those fields would
drift out of range almost immediately — so parsing every VP8 file in the corpus
and finding no violation is a real test of stage (a), not a smoke test.

    from vp8 import parse_keyframe
    h = parse_keyframe(frame_bytes)
"""
import struct


class BoolDecoder:
    """RFC 6386 §7. Range coder: `range` stays in 128..255, `value` holds the
    position inside the interval, `bit_count` tracks shifts since the last
    byte refill."""
    __slots__ = ('d', 'p', 'value', 'range', 'bit_count')

    def __init__(self, data, start=0):
        self.d = data
        self.p = start
        self.value = 0
        for _ in range(2):
            self.value = (self.value << 8) | self._next()
        self.range = 255
        self.bit_count = 0

    def _next(self):
        if self.p < len(self.d):
            b = self.d[self.p]
            self.p += 1
            return b
        self.p += 1
        return 0                       # past the end reads as zero

    def bool(self, prob):
        split = 1 + (((self.range - 1) * prob) >> 8)
        SPLIT = split << 8
        if self.value >= SPLIT:
            ret = 1
            self.range -= split
            self.value -= SPLIT
        else:
            ret = 0
            self.range = split
        while self.range < 128:
            self.value <<= 1
            self.range <<= 1
            self.bit_count += 1
            if self.bit_count == 8:
                self.bit_count = 0
                self.value |= self._next()
        return ret

    def literal(self, n):
        """L(n): n bools at probability 128, most significant first."""
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bool(128)
        return v

    def signed(self, n):
        """Magnitude then sign, as the header deltas are coded."""
        v = self.literal(n)
        return -v if self.bool(128) else v

    def flagged(self, n):
        """Optional signed value: a flag, then magnitude+sign if set."""
        return self.signed(n) if self.bool(128) else 0

    @property
    def bytes_used(self):
        return self.p


def parse_frame_tag(data):
    """The 3-byte tag every VP8 frame starts with (RFC 6386 §9.1)."""
    if len(data) < 3:
        return None
    t = data[0] | (data[1] << 8) | (data[2] << 16)
    return {
        'keyframe': (t & 1) == 0,          # 0 means keyframe
        'version': (t >> 1) & 7,
        'show_frame': bool((t >> 4) & 1),
        'first_part_size': (t >> 5) & 0x7FFFF,
    }


def parse_keyframe(data, full=False):
    """Full uncompressed chunk + the bool-coded header up to
    refresh_entropy_probs. Returns None if this is not a VP8 keyframe.

    With full=True it continues to the end of the header — the token
    probability updates and the skip flag — and returns the live BoolDecoder
    under 'bd', which is what tools/vp8_decode.py needs to carry on reading
    macroblock modes from the same partition."""
    tag = parse_frame_tag(data)
    if not tag or not tag['keyframe']:
        return None
    if len(data) < 10 or data[3:6] != b'\x9d\x01\x2a':
        return None                      # start code missing -> not a keyframe

    w_raw, h_raw = struct.unpack_from('<HH', data, 6)
    h = dict(tag)
    h['width'] = w_raw & 0x3FFF
    h['horiz_scale'] = w_raw >> 14
    h['height'] = h_raw & 0x3FFF
    h['vert_scale'] = h_raw >> 14

    b = BoolDecoder(data, 10)
    h['color_space'] = b.literal(1)
    h['clamping_type'] = b.literal(1)

    h['segmentation_enabled'] = b.literal(1)
    h['update_mb_seg_map'] = 0
    h['segment_tree_probs'] = [255, 255, 255]
    if h['segmentation_enabled']:
        update_map = h['update_mb_seg_map'] = b.literal(1)
        update_data = b.literal(1)
        if update_data:
            h['segment_feature_mode'] = b.literal(1)
            h['segment_quant'] = [b.flagged(7) for _ in range(4)]
            h['segment_lf'] = [b.flagged(6) for _ in range(4)]
        if update_map:
            h['segment_tree_probs'] = [b.literal(8) if b.bool(128) else 255
                                       for _ in range(3)]

    h['filter_type'] = b.literal(1)
    h['loop_filter_level'] = b.literal(6)
    h['sharpness_level'] = b.literal(3)

    h['lf_adj_enable'] = b.literal(1)
    if h['lf_adj_enable']:
        if b.literal(1):                          # mode_ref_lf_delta_update
            h['ref_lf_deltas'] = [b.flagged(6) for _ in range(4)]
            h['mode_lf_deltas'] = [b.flagged(6) for _ in range(4)]

    h['nbr_partitions'] = 1 << b.literal(2)

    h['y_ac_qi'] = b.literal(7)
    h['y_dc_delta'] = b.flagged(4)
    h['y2_dc_delta'] = b.flagged(4)
    h['y2_ac_delta'] = b.flagged(4)
    h['uv_dc_delta'] = b.flagged(4)
    h['uv_ac_delta'] = b.flagged(4)

    h['refresh_entropy_probs'] = b.literal(1)
    h['header_bytes_used'] = b.bytes_used
    if not full:
        return h

    import vp8_tables as T
    probs = [[[list(row) for row in blk] for blk in typ]
             for typ in T.DEFAULT_COEFF_PROBS]
    for i in range(4):
        for j in range(8):
            for k in range(3):
                for t in range(11):
                    if b.bool(T.COEFF_UPDATE_PROBS[i][j][k][t]):
                        probs[i][j][k][t] = b.literal(8)
    h['coeff_probs'] = probs

    h['mb_no_coeff_skip'] = b.literal(1)
    h['prob_skip_false'] = b.literal(8) if h['mb_no_coeff_skip'] else 0
    h['bd'] = b
    return h


def check(h):
    """Spec-legal ranges. Any violation means the bool decoder drifted."""
    bad = []
    if not (0 <= h['loop_filter_level'] <= 63):
        bad.append('loop_filter_level=%d' % h['loop_filter_level'])
    if not (0 <= h['sharpness_level'] <= 7):
        bad.append('sharpness=%d' % h['sharpness_level'])
    if not (0 <= h['y_ac_qi'] <= 127):
        bad.append('y_ac_qi=%d' % h['y_ac_qi'])
    if h['nbr_partitions'] not in (1, 2, 4, 8):
        bad.append('partitions=%d' % h['nbr_partitions'])
    if h['version'] > 3:
        bad.append('version=%d' % h['version'])
    if h['color_space'] != 0:
        bad.append('color_space=%d' % h['color_space'])
    if h['header_bytes_used'] > 10 + h['first_part_size']:
        bad.append('header ran past first partition (%d > %d)'
                   % (h['header_bytes_used'], 10 + h['first_part_size']))
    return bad
