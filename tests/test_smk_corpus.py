"""Proves: the Smacker decoder handles every portrait in the retail archives.

Expected (2026-07-21): 519 / 519 files, 5369 frames, no exceptions, no clip
whose frames are all black. A silent divergence shows up as a decode error on
the last frame, because the over-consumed bits run past the end of the file.
"""
import sys, struct
from common import BW, need, report
from mpq import MpqChain
from smk import Smacker

need(BW, 'Brood War install')
c = MpqChain(BW)
tbl = c.read(r'arr\portdata.tbl')
n = struct.unpack_from('<H', tbl, 0)[0]
stems = []
for i in range(1, n + 1):
    o = struct.unpack_from('<H', tbl, 2 + (i - 1) * 2)[0]
    stems.append(tbl[o:tbl.index(b'\x00', o)].decode('latin-1'))

ok = total = frames = 0
blank = []
errs = {}
for stem in stems:
    for v in range(10):
        p = 'portrait\\%s%d.smk' % (stem, v)
        if not c.exists(p):
            continue
        total += 1
        try:
            s = Smacker(c.read(p))
            lit = 0
            for i in range(s.frames):
                s.decode_frame(i)
                if any(s.pixels):
                    lit += 1
            frames += s.frames
            if lit == 0:
                blank.append(p)
            else:
                ok += 1
        except Exception as e:
            errs.setdefault('%s: %s' % (type(e).__name__, str(e)[:50]), []).append(p)

for k, v in errs.items():
    print('   error %-52s %d, e.g. %s' % (k, len(v), v[0]))
for p in blank[:5]:
    print('   all-black clip: %s' % p)
print('   frames decoded: %d' % frames)
sys.exit(report('smk: portraits decode', ok, total))
