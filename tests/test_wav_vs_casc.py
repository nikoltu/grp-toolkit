"""Proves: MPQ WAVE decompression (StormLib Huffman + ADPCM) is byte-exact.

The oracle shares no code with the decoder under test: SC:R stores the same
1998 audio uncompressed under sd/sound/, reached through CASC .idx -> BLTE ->
encoding -> root. If the Huffman tree or the ADPCM predictor drifted by one
sample, the comparison fails immediately.

Expected (2026-07-21): every file compared matches byte for byte.
Pass a count to limit the run:  py tests/test_wav_vs_casc.py 300
"""
import sys, struct
from common import BW, CASC_DATA, need, report
import casc
from mpq import MpqChain

need(BW, 'Brood War install')
need(CASC_DATA, 'SC:R CASC data')
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300

st = casc.NamedStorage(CASC_DATA)
mc = MpqChain(BW)
tbl = mc.read(r'arr\sfxdata.tbl')
n = struct.unpack_from('<H', tbl, 0)[0]

ok = total = skipped = 0
bad = []
for i in range(1, n + 1):
    if total >= limit:
        break
    o = struct.unpack_from('<H', tbl, 2 + (i - 1) * 2)[0]
    rel = tbl[o:tbl.index(b'\x00', o)].decode('latin-1')
    if not rel:
        continue
    mp = 'sound\\' + rel
    cp = 'sd/sound/' + rel.replace('\\', '/').lower()
    if not mc.exists(mp) or cp not in st.root:
        skipped += 1
        continue
    try:
        a = mc.read(mp)
        b = st.read_name(cp)
    except Exception as e:
        total += 1
        bad.append((rel, 'error: %s' % str(e)[:50]))
        continue
    total += 1
    if a == b:
        ok += 1
    else:
        d = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
                 min(len(a), len(b)))
        bad.append((rel, 'MPQ %d vs CASC %d, first diff @%d' % (len(a), len(b), d)))

for r, m in bad[:8]:
    print('   %-42s %s' % (r, m))
if skipped:
    print('   skipped (missing on one side): %d' % skipped)
sys.exit(report('wav: MPQ decode == CASC bytes', ok, total))
