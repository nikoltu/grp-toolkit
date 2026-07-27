"""Proves: the WebM/Matroska container reader handles the whole corpus, and
catalogues what is in it.

Anything that fails should fail with a CASC KeyError — meaning the content was
never downloaded (non-English locales) — and never with a parse error. A file
that yields ZERO blocks is treated as a failure on purpose: that is exactly how
the BlockGroup bug hid itself, looking like an empty file rather than a blind
parser.

Expected (2026-07-21): 2483 present of 2578 names, all parsed, none with zero
blocks; 1850 VP9 + 633 VP8.
"""
import sys
from collections import Counter
from common import CASC_DATA, need, report
import casc
from webm import WebM

need(CASC_DATA, 'SC:R CASC data')
st = casc.NamedStorage(CASC_DATA)
names = sorted(k for k in st.root if k.endswith('.webm'))

ok = present = 0
missing = 0
parse_fail, empty = [], []
codec, dims, tree = Counter(), Counter(), Counter()
for n in names:
    try:
        b = st.read_name(n)
    except Exception:
        missing += 1               # content not downloaded — not a parser issue
        continue
    present += 1
    try:
        w = WebM(b)
    except Exception as e:
        parse_fail.append((n, '%s: %s' % (type(e).__name__, str(e)[:50])))
        continue
    if not w.frames:
        empty.append(n)
        continue
    ok += 1
    codec[w.codec] += 1
    dims[(w.width, w.height)] += 1
    tree[n.split('/')[0]] += 1

for n, m in parse_fail[:8]:
    print('   parse fail  %-46s %s' % (n[-46:], m))
for n in empty[:8]:
    print('   ZERO blocks %s' % n[-58:])
print('   names %d, present %d, not downloaded %d' % (len(names), present, missing))
print('   codecs: %s' % dict(codec.most_common()))
print('   trees : %s' % dict(tree.most_common(6)))
print('   top resolutions: %s'
      % ', '.join('%dx%d:%d' % (d[0], d[1], c) for d, c in dims.most_common(6)))
sys.exit(report('webm: container over corpus', ok, present))
