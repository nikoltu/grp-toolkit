"""Proves two structural claims the rest of the project leans on.

1. CASC completeness: every name resolves, and everything unavailable locally
   is under locales/ for a non-English language. Graphics must be 100 %.
   Expected: 52498 names, 21161 reachable, graphics 1260 .grp / 3510 .anim /
   1704 .dds / 313 .pcx, and zero unreachable files outside locales/.

2. SD assets are identical between BW and SC:R (SHA-256, not size). This is why
   a reference dump made from the MPQ can be compared against what an engine
   loaded from CASC.
"""
import sys, os, re, glob, hashlib
from collections import Counter
from common import BW, CASC_DATA, need, report
import casc
from mpq import MpqChain

need(BW, 'Brood War install')
need(CASC_DATA, 'SC:R CASC data')
st = casc.NamedStorage(CASC_DATA)
mc = MpqChain(BW)

have = set()
for p in glob.glob(os.path.join(CASC_DATA, 'data.*')):
    m = re.search(r'data\.(\d{3})$', p)
    if m:
        have.add(int(m.group(1)))

reachable = 0
outside = []
by_ext = Counter()
for name, ck in st.root.items():
    ek = st.enc.get(ck)
    e = st.index.get(ek[:18]) if ek else None
    if e and e[0] in have:
        reachable += 1
        by_ext[os.path.splitext(name)[1].lower()] += 1
    elif not name.startswith('locales/'):
        outside.append(name)

print('   names %d, reachable %d (%.1f%%)'
      % (len(st.root), reachable, 100.0 * reachable / len(st.root)))
print('   graphics: .grp %d  .anim %d  .dds %d  .pcx %d'
      % (by_ext['.grp'], by_ext['.anim'], by_ext['.dds'], by_ext['.pcx']))
for n in outside[:5]:
    print('   unreachable OUTSIDE locales/: %s' % n)
rc1 = report('casc: gaps only in locales/', 0 if outside else 1, 1,
             '(%d offenders)' % len(outside))

PAIRS = [
    ('unit/wirefram/wirefram.grp', r'unit\wirefram\wirefram.grp'),
    ('unit/cmdicons/cmdicons.grp', r'unit\cmdbtns\cmdicons.grp'),
    ('game/icons.grp', r'game\icons.grp'),
    ('game/twire.pcx', r'game\twire.pcx'),
    ('game/tunit.pcx', r'game\tunit.pcx'),
    ('arr/units.dat', r'arr\units.dat'),
    ('arr/sfxdata.dat', r'arr\sfxdata.dat'),
    ('arr/portdata.dat', r'arr\portdata.dat'),
    ('tileset/badlands.wpe', r'tileset\badlands.wpe'),
]
same = 0
for cp, mp in PAIRS:
    try:
        a, b = st.read_name(cp), mc.read(mp)
    except Exception as e:
        print('   %-30s unavailable: %s' % (cp, str(e)[:40]))
        continue
    if hashlib.sha256(a).digest() == hashlib.sha256(b).digest():
        same += 1
    else:
        print('   %-30s DIFFERS (CASC %d vs MPQ %d)' % (cp, len(a), len(b)))
rc2 = report('shared: SD assets identical', same, len(PAIRS))
sys.exit(rc1 or rc2)
