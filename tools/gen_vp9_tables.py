#!/usr/bin/env python3
"""Generates tools/vp9_tables.py by extracting the constant tables from the
text of the VP9 Bitstream & Decoding Process Specification (v0.6, 2016).

Same rule and same reason as tools/gen_vp8_tables.py: VP9's probability, scan,
quantiser and lookup tables are format data — thousands of numbers that cannot
be derived and must not be typed from memory. They are cut out of the spec text
mechanically and every array's length is asserted against the shape the spec
declares, so a page-break artefact or a dropped digit fails the run.

    py tools/gen_vp9_tables.py vp9spec.txt -o tools/vp9_tables.py

Extract the spec text first (it is a PDF):
    pdftotext -raw vp9-bitstream-specification-v0.6.pdf vp9spec.txt

Only the tables are taken; the decoding algorithms in tools/vp9*.py are written
from the spec's prose and syntax.
"""
import re
import sys
import argparse

# Token enum for the coefficient trees (spec §? token table). The spec spells
# the leaf names two ways (DCT_VAL_CATEGORY1 in the tree, DCT_VAL_CAT1 in the
# value table); both map to the same value.
TOKENS = {
    'ZERO_TOKEN': 0, 'ONE_TOKEN': 1, 'TWO_TOKEN': 2, 'THREE_TOKEN': 3,
    'FOUR_TOKEN': 4,
    'DCT_VAL_CATEGORY1': 5, 'DCT_VAL_CATEGORY2': 6, 'DCT_VAL_CATEGORY3': 7,
    'DCT_VAL_CATEGORY4': 8, 'DCT_VAL_CATEGORY5': 9, 'DCT_VAL_CATEGORY6': 10,
    'DCT_VAL_CAT1': 5, 'DCT_VAL_CAT2': 6, 'DCT_VAL_CAT3': 7,
    'DCT_VAL_CAT4': 8, 'DCT_VAL_CAT5': 9, 'DCT_VAL_CAT6': 10,
}

# Jagged tables: rows of unequal length (name -> row lengths). cat_probs holds
# only the meaningful extra-bit probabilities per token category.
JAGGED = {
    'cat_probs': ('CAT_PROBS', [1, 1, 2, 3, 4, 5, 14]),
}

# name in the spec -> (python name, shape). Shape is the assertion.
WANTED = [
    ('inv_map_table', 'INV_MAP_TABLE', (255,)),
    ('default_scan_4x4', 'DEFAULT_SCAN_4X4', (16,)),
    ('col_scan_4x4', 'COL_SCAN_4X4', (16,)),
    ('row_scan_4x4', 'ROW_SCAN_4X4', (16,)),
    ('default_scan_8x8', 'DEFAULT_SCAN_8X8', (64,)),
    ('col_scan_8x8', 'COL_SCAN_8X8', (64,)),
    ('row_scan_8x8', 'ROW_SCAN_8X8', (64,)),
    ('default_scan_16x16', 'DEFAULT_SCAN_16X16', (256,)),
    ('col_scan_16x16', 'COL_SCAN_16X16', (256,)),
    ('row_scan_16x16', 'ROW_SCAN_16X16', (256,)),
    ('default_scan_32x32', 'DEFAULT_SCAN_32X32', (1024,)),
    ('coefband_4x4', 'COEFBAND_4X4', (16,)),
    ('coefband_8x8plus', 'COEFBAND_8X8PLUS', (1024,)),
    ('energy_class', 'ENERGY_CLASS', (12,)),
    ('pareto_table', 'PARETO_TABLE', (128, 8)),
    ('extra_bits', 'EXTRA_BITS', (11, 3)),
    ('size_group_lookup', 'SIZE_GROUP_LOOKUP', (13,)),
    ('kf_partition_probs', 'KF_PARTITION_PROBS', (16, 3)),
    ('kf_y_mode_probs', 'KF_Y_MODE_PROBS', (10, 10, 9)),
    ('kf_uv_mode_probs', 'KF_UV_MODE_PROBS', (10, 9)),
    ('default_partition_probs', 'DEFAULT_PARTITION_PROBS', (16, 3)),
    ('default_y_mode_probs', 'DEFAULT_Y_MODE_PROBS', (4, 9)),
    ('default_uv_mode_probs', 'DEFAULT_UV_MODE_PROBS', (10, 9)),
    ('default_skip_prob', 'DEFAULT_SKIP_PROB', (3,)),
    ('default_is_inter_prob', 'DEFAULT_IS_INTER_PROB', (4,)),
    ('default_comp_mode_prob', 'DEFAULT_COMP_MODE_PROB', (5,)),
    ('default_comp_ref_prob', 'DEFAULT_COMP_REF_PROB', (5,)),
    ('default_single_ref_prob', 'DEFAULT_SINGLE_REF_PROB', (5, 2)),
    ('default_tx_probs', 'DEFAULT_TX_PROBS', (4, 2, 3)),
    ('default_inter_mode_probs', 'DEFAULT_INTER_MODE_PROBS', (7, 3)),
    ('default_interp_filter_probs', 'DEFAULT_INTERP_FILTER_PROBS', (4, 2)),
    ('default_mv_joint_probs', 'DEFAULT_MV_JOINT_PROBS', (3,)),
    ('default_mv_sign_prob', 'DEFAULT_MV_SIGN_PROB', (2,)),
    ('default_mv_class_probs', 'DEFAULT_MV_CLASS_PROBS', (2, 10)),
    ('default_mv_class0_bit_prob', 'DEFAULT_MV_CLASS0_BIT_PROB', (2,)),
    ('default_mv_bits_prob', 'DEFAULT_MV_BITS_PROB', (2, 10)),
    ('default_mv_class0_fr_probs', 'DEFAULT_MV_CLASS0_FR_PROBS', (2, 2, 3)),
    ('default_mv_fr_probs', 'DEFAULT_MV_FR_PROBS', (2, 3)),
    ('default_mv_class0_hp_prob', 'DEFAULT_MV_CLASS0_HP_PROB', (2,)),
    ('default_mv_hp_prob', 'DEFAULT_MV_HP_PROB', (2,)),
    ('default_coef_probs', 'DEFAULT_COEF_PROBS', (4, 2, 2, 6, 6, 3)),
    ('dc_qlookup', 'DC_QLOOKUP', (3, 256)),
    ('ac_qlookup', 'AC_QLOOKUP', (3, 256)),
]
TREES = [
    ('token_tree', 'TOKEN_TREE', (20,)),
    ('small_token_tree', 'SMALL_TOKEN_TREE', (6,)),
    ('partition_tree', 'PARTITION_TREE', (6,)),
    ('cols_partition_tree', 'COLS_PARTITION_TREE', (2,)),
    ('rows_partition_tree', 'ROWS_PARTITION_TREE', (2,)),
    ('intra_mode_tree', 'INTRA_MODE_TREE', (18,)),
    ('tx_size_32_tree', 'TX_SIZE_32_TREE', (6,)),
    ('tx_size_16_tree', 'TX_SIZE_16_TREE', (4,)),
    ('tx_size_8_tree', 'TX_SIZE_8_TREE', (2,)),
    ('segment_tree', 'SEGMENT_TREE', (14,)),
]

# Block/tx/txfm/partition/intra enums, for the geometry tables and trees whose
# entries are symbolic.
ENUMS = {}
for i, n in enumerate(['BLOCK_4X4', 'BLOCK_4X8', 'BLOCK_8X4', 'BLOCK_8X8',
                       'BLOCK_8X16', 'BLOCK_16X8', 'BLOCK_16X16', 'BLOCK_16X32',
                       'BLOCK_32X16', 'BLOCK_32X32', 'BLOCK_32X64',
                       'BLOCK_64X32', 'BLOCK_64X64']):
    ENUMS[n] = i
ENUMS['BLOCK_INVALID'] = 14
for i, n in enumerate(['TX_4X4', 'TX_8X8', 'TX_16X16', 'TX_32X32']):
    ENUMS[n] = i
for i, n in enumerate(['DCT_DCT', 'ADST_DCT', 'DCT_ADST', 'ADST_ADST']):
    ENUMS[n] = i
for i, n in enumerate(['PARTITION_NONE', 'PARTITION_HORZ', 'PARTITION_VERT',
                       'PARTITION_SPLIT']):
    ENUMS[n] = i
for i, n in enumerate(['DC_PRED', 'V_PRED', 'H_PRED', 'D45_PRED', 'D135_PRED',
                       'D117_PRED', 'D153_PRED', 'D207_PRED', 'D63_PRED',
                       'TM_PRED']):
    ENUMS[n] = i

# Geometry lookup tables whose entries are symbolic block/tx enums.
ENUM_TABLES = [
    ('num_8x8_blocks_wide_lookup', 'NUM_8X8_W', (13,)),
    ('num_8x8_blocks_high_lookup', 'NUM_8X8_H', (13,)),
    ('num_4x4_blocks_wide_lookup', 'NUM_4X4_W', (13,)),
    ('num_4x4_blocks_high_lookup', 'NUM_4X4_H', (13,)),
    ('b_width_log2_lookup', 'B_WIDTH_LOG2', (13,)),
    ('b_height_log2_lookup', 'B_HEIGHT_LOG2', (13,)),
    ('mi_width_log2_lookup', 'MI_WIDTH_LOG2', (13,)),
    ('max_txsize_lookup', 'MAX_TXSIZE', (13,)),
    ('mode2txfm_map', 'MODE2TXFM', (14,)),
    ('subsize_lookup', 'SUBSIZE_LOOKUP', (4, 13)),
    ('ss_size_lookup', 'SS_SIZE_LOOKUP', (13, 2, 2)),
]


def grab_enum(text, name):
    body = initialiser(text, name)
    out = []
    for tok in re.findall(r'-?\w+', body):
        if tok.lstrip('-').isdigit():
            out.append(int(tok))
        elif tok in ENUMS:
            out.append(ENUMS[tok])
    return out


def clean(text):
    out = []
    for line in text.split('\n'):
        if re.search(r'VP9 Bitstream|Copyright|Rights Reserved', line):
            continue
        out.append(re.sub(r'//.*$', '', line))
    return re.sub(r'/\*.*?\*/', ' ', '\n'.join(out), flags=re.S)


def initialiser(text, name):
    """The brace-balanced initialiser of `name`, choosing the fullest one."""
    best = None
    pat = r'\b%s\s*(\[[^\]\[;{]*\]\s*)*=' % re.escape(name)
    for m in re.finditer(pat, text):
        i = text.find('{', m.end())
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(text):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[i:j + 1]
        if best is None or len(body) > len(best):
            best = body
    if best is None:
        raise KeyError('no initialiser for %s' % name)
    return best


def grab(text, name):
    return [int(v) for v in re.findall(r'-?\d+', initialiser(text, name))]


def grab_tree(text, name):
    body = initialiser(text, name)
    out = []
    for tok in re.findall(r'-?\w+', body):
        if tok.lstrip('-').isdigit():
            out.append(int(tok))
        else:
            neg = tok.startswith('-')
            key = tok[1:] if neg else tok
            v = TOKENS.get(key, ENUMS.get(key))
            if v is None:
                raise KeyError('unknown leaf %r in %s' % (tok, name))
            out.append(-v if neg else v)
    return out


def shape(vals, dims):
    n = 1
    for d in dims:
        n *= d
    if len(vals) != n:
        raise ValueError('expected %d values %s, got %d'
                         % (n, 'x'.join(map(str, dims)), len(vals)))
    for d in reversed(dims[1:]):
        vals = [vals[i:i + d] for i in range(0, len(vals), d)]
    return vals


def fmt(v, indent=0):
    if not isinstance(v, list):
        return str(v)
    if not v or not isinstance(v[0], list):
        return '[' + ', '.join(str(x) for x in v) + ']'
    pad = ' ' * (indent + 1)
    return ('[\n' + ',\n'.join(pad + fmt(x, indent + 1) for x in v)
            + '\n' + ' ' * indent + ']')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', help='vp9spec.txt (pdftotext -raw output)')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    text = clean(open(a.spec, encoding='utf-8', errors='replace').read())

    parts = ['"""VP9 constant tables — GENERATED, do not edit by hand.\n\n'
             'Extracted from the VP9 spec v0.6 text by tools/gen_vp9_tables.py.\n'
             'Bitstream format data, machine-extracted and shape-checked; see\n'
             'that script for why they are not typed by hand.\n"""\n']
    tree_names = {s for s, _, _ in TREES}
    enum_names = {s for s, _, _ in ENUM_TABLES}
    for spec_name, py_name, dims in WANTED + TREES + ENUM_TABLES:
        if spec_name in tree_names:
            raw = grab_tree(text, spec_name)
        elif spec_name in enum_names:
            raw = grab_enum(text, spec_name)
        else:
            raw = grab(text, spec_name)
        vals = shape(raw, dims)
        parts.append('%s = %s\n' % (py_name, fmt(vals)))
        print('  %-28s %s ok' % (spec_name, 'x'.join(map(str, dims))))

    for spec_name, (py_name, rowlens) in JAGGED.items():
        raw = grab(text, spec_name)
        if len(raw) != sum(rowlens):
            raise ValueError('%s: expected %d values, got %d'
                             % (spec_name, sum(rowlens), len(raw)))
        rows, i = [], 0
        for rl in rowlens:
            rows.append(raw[i:i + rl])
            i += rl
        parts.append('%s = %s\n' % (py_name, fmt(rows)))
        print('  %-28s jagged %s ok' % (spec_name, rowlens))

    open(a.out, 'w', encoding='utf-8').write('\n'.join(parts))
    print('wrote %s' % a.out)


if __name__ == '__main__':
    main()
