#!/usr/bin/env python3
"""Generates tools/vp8_tables.py by extracting the constant tables from the
text of RFC 6386.

Why a generator instead of typed-in tables: VP8's probability tables are
thousands of numbers that cannot be derived from anything — they are format
data, the same category as the PKWARE and StormLib tables (see CLAUDE.md §6).
Typing them from memory is exactly the failure mode this project forbids, and
proof-reading 1056 numbers by eye is not a check. So they are cut out of the
normative spec mechanically, and every array's length is asserted against the
shape the spec declares: a page-break artefact or a dropped digit changes the
count and the run fails.

    py tools/gen_vp8_tables.py rfc6386.txt -o tools/vp8_tables.py

RFC 6386 is an IETF Informational RFC (Bankoski, Koleszar, Quillio, Salonen,
Wilkins, Xu, November 2011) and the tables are the published bitstream
constants. Only the tables are taken; every algorithm in tools/vp8.py is
written from the prose.
"""
import re
import sys
import argparse

# name in the RFC -> (python name, shape). The shape is the assertion: it is
# what the RFC's own declaration says the dimensions are, so a mis-parse cannot
# pass silently.
WANTED = [
    ('kf_ymode_tree',       'KF_YMODE_TREE',    (8,)),
    ('kf_ymode_prob',       'KF_YMODE_PROB',    (4,)),
    ('uv_mode_tree',        'UV_MODE_TREE',     (6,)),
    ('kf_uv_mode_prob',     'KF_UV_MODE_PROB',  (3,)),
    ('bmode_tree',          'BMODE_TREE',       (18,)),
    ('kf_bmode_prob',       'KF_BMODE_PROB',    (10, 10, 9)),
    ('coeff_tree',          'COEFF_TREE',       (22,)),
    ('coeff_bands',         'COEFF_BANDS',      (16,)),
    ('default_coeff_probs', 'DEFAULT_COEFF_PROBS', (4, 8, 3, 11)),
    ('coeff_update_probs',  'COEFF_UPDATE_PROBS', (4, 8, 3, 11)),
    ('dc_qlookup',          'DC_QLOOKUP',       (128,)),
    ('ac_qlookup',          'AC_QLOOKUP',       (128,)),
    ('zigzag',              'ZIGZAG',           (16,)),
    ('Pcat1', 'PCAT1', (2,)),
    ('Pcat2', 'PCAT2', (3,)),
    ('Pcat3', 'PCAT3', (4,)),
    ('Pcat4', 'PCAT4', (5,)),
    ('Pcat5', 'PCAT5', (6,)),
    ('Pcat6', 'PCAT6', (12,)),
    # --- inter frames (stage e): from modemv_data.h and vp8_prob_data.h
    ('y_mode_tree',        'Y_MODE_TREE',       (8,)),
    ('small_mv_tree',      'SMALL_MV_TREE',     (14,)),
    ('mv_ref_tree',        'MV_REF_TREE',       (8,)),
    ('submv_ref_tree',     'SUBMV_REF_TREE',    (6,)),
    ('split_mv_tree',      'SPLIT_MV_TREE',     (6,)),
    ('k_default_y_mode_probs',  'DEFAULT_Y_MODE_PROBS',  (4,)),
    ('k_default_uv_mode_probs', 'DEFAULT_UV_MODE_PROBS', (3,)),
    ('default_b_mode_probs',    'DEFAULT_B_MODE_PROBS',  (9,)),
    ('mv_counts_to_probs', 'MV_COUNTS_TO_PROBS', (6, 4)),
    ('split_mv_probs',     'SPLIT_MV_PROBS',    (3,)),
    ('submv_ref_probs2',   'SUBMV_REF_PROBS2',  (5, 3)),
    ('mv_partitions',      'MV_PARTITIONS',     (4, 16)),
    ('k_default_mv_probs', 'DEFAULT_MV_PROBS',  (2, 19)),
    ('k_mv_entropy_update_probs', 'MV_UPDATE_PROBS', (2, 19)),
    ('sixtap_filters',     'SIXTAP_FILTERS',    (8, 6)),
]

# Lines the RFC inserts for pagination. They carry digits ("[Page 74]",
# "RFC 6386", "November 2011"), so leaving them in would inject numbers into
# the middle of an array.
NOISE = re.compile(
    r'^\s*(Bankoski|RFC 6386\b)|\[Page \d+\]|-{4} (Begin|End) code block')


def clean(text):
    out = []
    for line in text.replace('\f', '\n').split('\n'):
        if NOISE.search(line):
            continue
        out.append(re.sub(r'//.*$', '', line))
    # Block comments must go too: the tree tables annotate every entry with its
    # bit string ("11100"), which reads as a number otherwise.
    return re.sub(r'/\*.*?\*/', ' ', '\n'.join(out), flags=re.S)


def enums(text):
    """Ordinal for every enumerator declared in the RFC's C enums.

    The trees are written with symbolic leaves (-B_PRED, -dct_eob), so the
    tables cannot be read without them. Parsed rather than typed for the same
    reason as the tables themselves.
    """
    vals = {}
    # Both `typedef enum {...}` and `enum name {...}` forms appear.
    for m in re.finditer(r'\benum\b[^{;]*\{(.*?)\}', text, re.S):
        block, nxt = {}, 0
        try:
            for item in m.group(1).split(','):
                item = item.strip()
                if not item:
                    continue
                if '=' in item:
                    nm, rhs = (s.strip() for s in item.split('=', 1))
                    # right-hand sides are constant expressions over earlier
                    # enumerators, e.g. "mv_split + 1 - mv_nearest"
                    scope = dict(vals, **block)
                    nxt = eval(rhs, {'__builtins__': {}}, scope)
                else:
                    nm = item
                if not re.fullmatch(r'\w+', nm):
                    continue
                block[nm] = nxt
                nxt += 1
        except Exception:
            # An enum this parser cannot follow is dropped whole rather than
            # half-applied — a partly-numbered enum would silently shift every
            # ordinal after it. Anything actually needed fails loudly later,
            # when a tree looks its leaves up.
            continue
        vals.update(block)
    return vals


def grab_tree(text, name, syms):
    """A tree table: entries are either an index or a negated enumerator."""
    body = initialiser(text, name)
    out = []
    for tok in re.findall(r'-?\w+', body):
        if tok.lstrip('-').isdigit():
            out.append(int(tok))
        else:
            neg = tok.startswith('-')
            out.append(-syms[tok[1:]] if neg else syms[tok])
    return out


def initialiser(text, name):
    """The brace-balanced initialiser of `name`.

    Takes the declaration with the *most* content: the RFC repeats several
    declarations for exposition (kf_bmode_prob appears truncated in Section
    11.2 and in full in Section 11.5) and only the fullest carries the table.
    """
    best = None
    # Dimensions only, never a subscript expression: `b_tokens[zigzag[c]] = v`
    # would otherwise look like a declaration of zigzag.
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
        raise KeyError('no initialiser found for %s' % name)
    return best


def grab(text, name):
    return [int(v) for v in re.findall(r'-?\d+', initialiser(text, name))]


def shape(vals, dims):
    n = 1
    for d in dims:
        n *= d
    if len(vals) != n:
        raise ValueError('expected %d values %s, extracted %d'
                         % (n, 'x'.join(map(str, dims)), len(vals)))
    for d in reversed(dims[1:]):
        vals = [vals[i:i + d] for i in range(0, len(vals), d)]
    return vals


def fmt(v, indent=0):
    if not isinstance(v, list):
        return str(v)
    if not isinstance(v[0], list):
        return '[' + ', '.join(str(x) for x in v) + ']'
    pad = ' ' * (indent + 1)
    return '[\n' + ',\n'.join(pad + fmt(x, indent + 1) for x in v) + '\n' + ' ' * indent + ']'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rfc', help='rfc6386.txt')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()

    text = clean(open(a.rfc, encoding='utf-8', errors='replace').read())

    parts = ['"""VP8 constant tables — GENERATED, do not edit by hand.\n\n'
             'Extracted from the text of RFC 6386 by tools/gen_vp8_tables.py.\n'
             'These are bitstream format data, not algorithm: see that script\n'
             'for why they are machine-extracted rather than typed.\n"""\n']
    syms = enums(text)
    print('  %d enumerators parsed' % len(syms))
    for rfc_name, py_name, dims in WANTED:
        raw = (grab_tree(text, rfc_name, syms) if rfc_name.endswith('_tree')
               else grab(text, rfc_name))
        vals = shape(raw, dims)
        parts.append('%s = %s\n' % (py_name, fmt(vals)))
        print('  %-22s %s ok' % (rfc_name, 'x'.join(map(str, dims))))

    open(a.out, 'w', encoding='utf-8').write('\n'.join(parts))
    print('wrote %s' % a.out)


if __name__ == '__main__':
    main()
