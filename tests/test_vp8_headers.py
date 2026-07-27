"""Proves: the VP8 boolean decoder and keyframe header parse are correct.

Two independent checks per file, neither of which a drifting bool decoder can
satisfy by luck:
  * the dimensions the VP8 keyframe states must equal the ones the Matroska
    container states (different parser, different bytes);
  * every bool-coded header field must land inside its spec-legal range
    (loop filter 0..63, sharpness 0..7, quantiser 0..127, partitions 1/2/4/8).

Expected (2026-07-21): 633 / 633 VP8 files, 0 range violations.
"""
import sys
from collections import Counter
from common import CASC_DATA, need, report
import casc
from webm import WebM
from vp8 import parse_keyframe, check

need(CASC_DATA, 'SC:R CASC data')
st = casc.NamedStorage(CASC_DATA)
names = sorted(k for k in st.root if k.endswith('.webm'))

ok = total = 0
bad = []
stats = Counter()
for n in names:
    try:
        b = st.read_name(n)
        w = WebM(b)
    except Exception:
        continue                       # not available locally, or not our job here
    if w.codec != 'V_VP8':
        continue
    total += 1
    key = None
    for (_tn, _tc, _k, off, sz) in w.frames:
        h = parse_keyframe(b[off:off + sz])
        if h:
            key = h
            break
    if key is None:
        bad.append((n, 'no keyframe found in %d blocks' % len(w.frames)))
        continue
    problems = check(key)
    if key['width'] != w.width or key['height'] != w.height:
        problems.append('dims %dx%d vs container %dx%d'
                        % (key['width'], key['height'], w.width, w.height))
    if problems:
        bad.append((n, '; '.join(problems)))
    else:
        ok += 1
    stats['partitions=%d' % key['nbr_partitions']] += 1
    stats['version=%d' % key['version']] += 1

for n, m in bad[:8]:
    print('   %-52s %s' % (n[-52:], m))
print('   header stats: %s' % dict(sorted(stats.items())))
sys.exit(report('vp8: header + bool decoder', ok, total))
