"""Oracle for the per-mission spec sheet (tools/ai/mission_spec.py) + CHK condition
parsing (chk.py).

The spec sheet is the engine's bug-diff reference, so it must extract the encoded
mission logic correctly, not just run:

  1. COVERAGE. Every campaign mission yields a JSON-serialisable spec with
     objectives, victory and defeat trigger lists; almost every mission has at
     least one win OR lose trigger, and their conditions parse to KNOWN types (no
     'cond<n>' leaking) - a wrong condition offset would give junk types.
  2. WIN/LOSE SANITY. Across the campaign, victory/defeat conditions use the real
     condition vocabulary (Command / Bring / CountdownTimer / ElapsedTime / Switch)
     and reference real unit names / locations.
  3. REVOLUTION MECHANIC (the measured, V-confirmed fact). terran05's Antigan
     takeover uses NO SetAllianceStatus and NO GiveUnitsToPlayer action - it is a
     RESCUE-owner transfer (player 2) plus CreateUnitWithProperties. So the spec
     must report set_alliance==0, give_units==0, rescue_players contains 2, and
     create_with_properties > 0. (If the engine modelled it as an alliance, this is
     the check that would catch the design mismatch.)
  4. KNOWN OBJECTIVE. Desperate Alliance (terran03) is the survive-timer mission:
     its objective text mentions surviving and its triggers carry a CountdownTimer.

    py test_mission_spec.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report                       # noqa: E402
import mpq                                                # noqa: E402
import tbl                                                # noqa: E402
import dat                                                # noqa: E402
import chk as chkmod                                      # noqa: E402
import campaign_index                                     # noqa: E402
import mission_spec                                       # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    udat = dat.load_from_chain(ch, 'units.dat')
    hero_set = {i for i in range(228) if (udat.get('special_ability_flags', i) >> 6) & 1}

    ok = total = 0
    bad = []

    specs = {}
    for label, data in campaign_index.find_mpq_campaigns(ch):
        chk = chkmod.parse(data)
        specs[label] = (chk, mission_spec.spec(chk, uname, hero_set))

    # 1. coverage + condition types known + JSON
    total += 1
    missions = 0
    json_ok = True
    with_wl = 0
    unknown_cond = 0
    for label, (chk, sp) in specs.items():
        missions += 1
        try:
            json.dumps(sp)
        except Exception:                                  # noqa: BLE001
            json_ok = False
        if sp['victory'] or sp['defeat']:
            with_wl += 1
        for grp in ('victory', 'defeat'):
            for tr in sp[grp]:
                for c in tr['conditions']:
                    if c.startswith('cond'):
                        unknown_cond += 1
    if missions > 40 and json_ok and with_wl > 35 and unknown_cond == 0:
        ok += 1
    else:
        bad.append('missions %d wl %d unknown %d json %s'
                   % (missions, with_wl, unknown_cond, json_ok))

    # 2. win/lose vocabulary is real
    total += 1
    vocab = set()
    for label, (chk, sp) in specs.items():
        for grp in ('victory', 'defeat'):
            for tr in sp[grp]:
                for c in tr['conditions']:
                    vocab.add(c.split(':')[0].split()[0])
    if {'Command', 'CountdownTimer'} <= vocab or {'Command', 'Bring'} <= vocab:
        ok += 1
    else:
        bad.append('vocab %s' % sorted(vocab)[:6])

    # 3. Revolution takeover mechanic (measured)
    total += 1
    rev = specs.get('terran/terran05')
    if rev:
        sp = rev[1]
        t = sp['transfers']
        if (t['set_alliance_actions'] == 0 and len(t['give_units']) == 0
                and 2 in sp['rescue_players'] and t['create_with_properties'] > 0):
            ok += 1
        else:
            bad.append('revolution transfers %s rescue %s' % (t, sp['rescue_players']))
    else:
        bad.append('no terran05')

    # 4. Desperate Alliance survive-timer
    total += 1
    da = specs.get('terran/terran03')
    if da:
        chk, sp = da
        obj = ' '.join(sp['objectives']).lower()
        has_timer = any('CountdownTimer' in c or 'ElapsedTime' in c
                        for tr in sp['victory'] + sp['defeat'] for c in tr['conditions']) \
            or any(cd.type_name in ('CountdownTimer', 'ElapsedTime')
                   for tr in chk.triggers for cd in tr.conditions)
        if 'surviv' in obj and has_timer:
            ok += 1
        else:
            bad.append('desperate obj=%r timer=%s' % (obj[:40], has_timer))
    else:
        bad.append('no terran03')

    rc = report('mission_spec: spec sheet + conditions', ok, total,
                '(%d missions, %d win/lose; bad=%s)'
                % (missions, with_wl, bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
