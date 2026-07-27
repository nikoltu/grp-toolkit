"""Oracle for the .dat reader/writer (units.dat, weapons.dat).

The field TABLE is borrowed layout data (DatEdit/PyMS), so it only counts as
"measured" if it survives falsifiable checks against V's real files:

  1. LAYOUT closes exactly. Field arrays sum to the exact file size (units 19876,
     weapons 5460), and the four independently MEASURED offset anchors from
     CLAUDE.md land to the byte (hitpoints@3156, ready_sound@9312, portrait@14404,
     group_flags@16684). One wrong width/count shifts a later anchor or misses
     the total, so this is a statement about the whole ordering.

  2. SEMANTICS sanity. Known unit values decode correctly (Marine=40 HP, SCV=60,
     Marine mineral cost 50; hitpoints are 1/256 fixed point) - proves the field
     maps to reality, not just to a self-consistent size.

  3. ROUND-TRIP byte-identical. Parse -> to_bytes() equals the source, and a
     single set() changes ONLY that field's bytes (everything else identical) -
     an editor built on it cannot corrupt an untouched field.

  4. SUBSET fields. A building-only field is None for a unit id and vice-versa
     (the reduced 106/96 arrays are addressed with the right base index).

    py test_dat.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import BW, need, report      # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import mpq                               # noqa: E402
import dat                               # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    ok = total = 0
    bad = []

    u = dat.load_from_chain(ch, 'units.dat')
    w = dat.load_from_chain(ch, 'weapons.dat')

    # 1. layout closes + anchors
    total += 1
    usum = sum(f.size for f in u.fields)
    wsum = sum(f.size for f in w.fields)
    anchors = {'hitpoints': 3156, 'ready_sound': 9312,
               'portrait': 14404, 'group_flags': 16684}
    amiss = [n for n, o in anchors.items() if u.field(n).offset != o]
    if usum == 19876 and wsum == 5460 and not amiss:
        ok += 1
    else:
        bad.append('layout: usum=%d wsum=%d anchors_miss=%s' % (usum, wsum, amiss))

    # 2. semantics (fixed-point HP, known costs)
    total += 1
    checks = [('hitpoints', 0, 40), ('hitpoints', 7, 60)]   # Marine, SCV (display)
    sem_ok = all(u.display(n, i) == v for n, i, v in checks) \
        and u.get('mineral_cost', 0) == 50 \
        and u.get('hitpoints', 0) == 40 * 256                # raw is 1/256
    if sem_ok:
        ok += 1
    else:
        bad.append('semantics: Marine HP raw=%s disp=%s cost=%s'
                   % (u.get('hitpoints', 0), u.display('hitpoints', 0),
                      u.get('mineral_cost', 0)))

    # 3a. round-trip byte-identical (no edits)
    total += 1
    src_u = ch.read('arr\\units.dat')
    src_w = ch.read('arr\\weapons.dat')
    if u.to_bytes() == src_u and w.to_bytes() == src_w:
        ok += 1
    else:
        bad.append('round-trip not identical')

    # 3b. a single edit touches ONLY that field's bytes
    total += 1
    u2 = dat.load('units.dat', src_u)
    u2.set('hitpoints', 0, 80 * 256)          # Marine 40 -> 80 HP
    a, b = bytes(src_u), u2.to_bytes()
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    off = u2.field('hitpoints').offset            # id 0 => first 4 bytes of array
    # every changed byte must fall inside this field's u32 slot for id 0, and at
    # least one must change (40->80 flips only the high byte of 0x2800->0x5000)
    in_slot = diff and all(off <= i < off + 4 for i in diff)
    if u2.display('hitpoints', 0) == 80 and in_slot:
        ok += 1
    else:
        bad.append('edit spread: %d bytes changed at %s' % (len(diff), diff[:6]))

    # 4. subset fields (building-only vs unit-only)
    total += 1
    # infestation is buildings-only (base 106); ready_sound is units-only (0..105)
    unit_id, building_id = 0, 130            # 0 = Marine (unit), 130 = a building
    sub_ok = (u.get('infestation', unit_id) is None
              and u.get('ready_sound', building_id) is None
              and u.get('ready_sound', unit_id) is not None
              and u.get('infestation', building_id) is not None)
    if sub_ok:
        ok += 1
    else:
        bad.append('subset addressing wrong')

    rc = report('dat: units/weapons layout + edit round-trip', ok, total,
                '(bad=%s)' % (bad[:4] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
