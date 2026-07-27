"""Oracle for the combat (damage) reference (tools/combat.py).

The provenance split is the whole point (CLAUDE.md "measure, never assume"):
the numeric INPUTS are byte-read from the real .dat, so those checks are
falsifiable against V's files; the factor TABLE is the documented Compendium
mechanic, checked by reproducing its own worked examples.

  1. INPUTS are byte-facts. A unit's resolved weapon (following the turret
     subunit for Siege Tank / Goliath) has the exact damage / type / hit count
     the game stores: Marine Gauss 6 Normal x1, Zealot Psi Blades 8 Normal x2,
     Firebat Flame Thrower 8 Concussive x3, Dragoon Phase Disruptor 20 Explosive,
     Siege Tank -> turret Arclite 30 Explosive, Goliath -> turret Twin
     Autocannons 12 Normal (ground) + Hellfire 10 Explosive (air). One wrong
     field would move one of these off its known value.

  2. FACTOR TABLE reproduces the documented mechanic. Explosive 50/75/100 and
     Concussive 100/50/25 over Small/Medium/Large, Normal flat 100, shields 100%.

  3. MULTI-HIT ARMOR. Armor is subtracted PER HIT, so Firebat (8 x3) loses 3x the
     armor a single-hit weapon would: vs a 1-armor Small target = (8-1)*3 = 21,
     not 8*3 - 1 = 23. This is the measured consequence the Compendium calls out.

  4. DETERMINISM + REFERENCE FILE. The calculation is a pure function of its
     inputs (same call, same number, twice), and assets/combat_reference.json
     round-trips to combat.reference_dict() (the committed file matches the code).

    py test_combat.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import BW, ROOT, need, report      # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import mpq                                      # noqa: E402
import combat                                   # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    m = combat.CombatModel.from_chain(ch)
    ok = total = 0
    bad = []

    def W(uid, mode):
        return next((w for w in m.unit_weapons(uid) if w['mode'] == mode), None)

    # 1. inputs are byte-facts (weapon resolution incl. turret subunit)
    total += 1
    want = [
        (0,  'ground', 'Gauss Rifle',       'Normal',     6,  1, 0),
        (65, 'ground', 'Psi Blades',        'Normal',     8,  2, 65),
        (32, 'ground', 'Flame Thrower',     'Concussive', 8,  3, 32),
        (66, 'ground', 'Phase Disruptor',   'Explosive',  20, 1, 66),
        (5,  'ground', 'Arclite Cannon',    'Explosive',  30, 1, 6),   # via turret
        (3,  'ground', 'Twin Autocannons',  'Normal',     12, 1, 4),   # via turret
        (3,  'air',    'Hellfire Missile Pack', 'Explosive', 10, 1, 4),
    ]
    imiss = []
    for uid, mode, name, typ, dmg, hits, host in want:
        w = W(uid, mode)
        if not (w and w['name'] == name and w['type'] == typ
                and w['damage'] == dmg and w['hits'] == hits and w['host'] == host):
            imiss.append('%s/%s got %s' % (m.unit_name(uid), mode,
                                           None if not w else (w['name'], w['type'],
                                                               w['damage'], w['hits'], w['host'])))
    if not imiss:
        ok += 1
    else:
        bad.append('inputs: %s' % imiss[:3])

    # 2. factor table reproduces the documented mechanic
    total += 1
    fp = combat.size_factor_pct
    ftab_ok = (fp('Explosive', 'Small') == 50 and fp('Explosive', 'Medium') == 75
               and fp('Explosive', 'Large') == 100
               and fp('Concussive', 'Small') == 100 and fp('Concussive', 'Medium') == 50
               and fp('Concussive', 'Large') == 25
               and fp('Normal', 'Small') == fp('Normal', 'Large') == 100)
    # Dragoon Explosive 20: vs Small=10, Medium=15, Large(a1)=(20-1)=19
    dg = W(66, 'ground')
    ex_ok = (m.effective(dg['weapon_id'], 1, 0) == 10       # Marine (Small,0)
             and m.effective(dg['weapon_id'], 1, 2) == 15   # Vulture (Medium,0)
             and m.effective(dg['weapon_id'], 1, 66) == 19)  # Dragoon (Large,1)
    if ftab_ok and ex_ok:
        ok += 1
    else:
        bad.append('factor table ftab=%s ex=%s' % (ftab_ok, ex_ok))

    # 3. multi-hit armor is subtracted per hit
    total += 1
    fb = W(32, 'ground')            # Flame Thrower Concussive 8 x3
    # vs Zealot (Small, 1 armor): (8-1)*100%*3 = 21   (NOT 8*3-1 = 23)
    per_hit_first = m.breakdown(fb['weapon_id'], fb['hits'], 65)['after_armor']
    mh = m.effective(fb['weapon_id'], fb['hits'], 65)
    # vs Dragoon (Large, 1 armor): (8-1)*25%*3 = 5.25
    mh_l = m.effective(fb['weapon_id'], fb['hits'], 66)
    if per_hit_first == 7 and mh == 21 and abs(mh_l - 5.25) < 1e-9:
        ok += 1
    else:
        bad.append('multi-hit armor: after=%s total=%s large=%s'
                   % (per_hit_first, mh, mh_l))

    # 4. determinism + committed reference file matches the code
    total += 1
    d1 = m.breakdown(dg['weapon_id'], 1, 66)
    d2 = m.breakdown(dg['weapon_id'], 1, 66)
    det_ok = d1 == d2
    ref_path = os.path.join(ROOT, 'assets', 'combat_reference.json')
    file_ok = False
    if os.path.exists(ref_path):
        on_disk = json.load(open(ref_path, encoding='utf-8'))
        # JSON keys are strings; compare via a JSON round-trip of the code's dict
        code_ref = json.loads(json.dumps(combat.reference_dict()))
        file_ok = on_disk == code_ref
    if det_ok and file_ok:
        ok += 1
    else:
        bad.append('determinism=%s reference_file=%s' % (det_ok, file_ok))

    # 5. golden fixture: deterministic, spot values correct, committed file matches
    total += 1
    fx = combat.combat_fixture(m)
    fx2 = combat.combat_fixture(m)
    det = json.dumps(fx, sort_keys=True) == json.dumps(fx2, sort_keys=True)
    # spot: Marine ground Small a0/u0 = 6; Firebat Small a1/u0 = 21; Large = 5.25
    mar = fx['units']['0']['attacks'][0]['vs']['Small']['a0_u0']
    fb_s = fx['units']['32']['attacks'][0]['vs']['Small']['a1_u0']
    fb_l = fx['units']['32']['attacks'][0]['vs']['Large']['a1_u0']
    spot = (mar == 6 and fb_s == 21 and abs(fb_l - 5.25) < 1e-9)
    fx_path = os.path.join(ROOT, 'assets', 'combat_fixture.json')
    file_ok = False
    if os.path.exists(fx_path):
        on_disk = json.load(open(fx_path, encoding='utf-8'))
        code_fx = json.loads(json.dumps(fx))          # normalise tuples→lists
        file_ok = on_disk == code_fx
    if det and spot and file_ok:
        ok += 1
    else:
        bad.append('fixture: det=%s spot=%s(mar=%s fbS=%s fbL=%s) file=%s'
                   % (det, spot, mar, fb_s, fb_l, file_ok))

    rc = report('combat: damage inputs + factor + fixture', ok, total,
                '(bad=%s)' % (bad[:4] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
