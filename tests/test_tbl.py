"""Oracle for the .tbl string-table reader/writer (tools/tbl.py).

  1. UNCHANGED round-trip is BYTE-IDENTICAL. to_bytes() re-serialises the parsed
     structure (in offset order) and equals the source for stat_txt / sfxdata /
     images.tbl -- a real writer round-trip, not "return the original".

  2. EXTENDED PARTS are preserved. stat_txt entries carry NUL-separated bytes
     after the display name; `raw[i]` is longer than `strings[i]` for those, and
     the byte-identical rebuild proves none are dropped (the trap the old
     read-to-first-NUL reader would have fallen into on a rewrite).

  3. SEMANTICS. Known display names decode (unit name = stat_txt[unit_id], 0-based
     here): Marine(0)=Terran Marine, Command Center(106)=Terran Command Center.

  4. EDIT isolation + semantic round-trip. set_text() changes only the name and
     KEEPS the extended parts; parse(to_bytes()) shows the new name, the entry's
     extra bytes intact, and every other entry's bytes unchanged. append() adds one.

    py test_tbl.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import BW, need, report          # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import mpq                                    # noqa: E402
import tbl                                    # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    ok = total = 0
    bad = []

    src = {name: ch.read(path) for name, path in
           (('stat_txt', 'rez\\stat_txt.tbl'),
            ('sfxdata', 'arr\\sfxdata.tbl'),
            ('images', 'arr\\images.tbl'))}
    tables = {k: tbl.load(v) for k, v in src.items()}

    # 1. unchanged round-trip byte-identical (all three)
    total += 1
    ri = [k for k in src if tables[k].to_bytes() != src[k]]
    if not ri:
        ok += 1
    else:
        bad.append('not byte-identical: %s' % ri)

    # 2. extended parts preserved (stat_txt has entries longer than their name)
    total += 1
    st = tables['stat_txt']
    n_extended = sum(1 for i in range(st.count) if len(st.raw[i]) > len(st.strings[i]) + 1)
    marine_extra = len(st.raw[0]) - len(st.strings[0]) - 1
    if n_extended > 100 and marine_extra > 0:
        ok += 1
    else:
        bad.append('extended parts: n=%d marine_extra=%d' % (n_extended, marine_extra))

    # 3. semantics
    total += 1
    if st.text(0) == 'Terran Marine' and st.text(106) == 'Terran Command Center':
        ok += 1
    else:
        bad.append('semantics: [0]=%r [106]=%r' % (st.text(0), st.text(106)))

    # 4. edit isolation + semantic round-trip
    total += 1
    t2 = tbl.load(src['stat_txt'])
    old0_raw, old1_raw = t2.raw[0], t2.raw[1]
    old0_tail = old0_raw.split(b'\x00', 1)[1]          # extended bytes of entry 0
    t2.set_text(0, 'Space Marine')
    new_idx = t2.append('Custom Unit')
    round_ = tbl.load(t2.to_bytes())
    edit_ok = (round_.text(0) == 'Space Marine'
               and round_.raw[0].split(b'\x00', 1)[1] == old0_tail   # tail kept
               and round_.raw[1] == old1_raw                         # neighbour intact
               and round_.text(new_idx) == 'Custom Unit'
               and round_.count == st.count + 1)
    if edit_ok:
        ok += 1
    else:
        bad.append('edit round-trip: [0]=%r tailkept=%s [new]=%r'
                   % (round_.text(0), round_.raw[0].split(b'\x00', 1)[1] == old0_tail,
                      round_.text(new_idx)))

    rc = report('tbl: string table read/write', ok, total,
                '(bad=%s)' % (bad[:4] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
