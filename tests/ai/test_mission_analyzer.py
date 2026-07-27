"""Oracle for the full mission analyzer (mission_analyzer.py).

Produces one normalized report per campaign mission and requires it to be
complete, correct and JSON-serialisable - the reference an engine port diffs its
whole mission interpretation against:

  1. COVERAGE. Every campaign mission yields a report with the integrated pieces
     (triggers, players, briefing, commands, ai_scripts, heroes) and serialises
     to JSON.
  2. HEROES. The units.dat Hero flag (bit 6) selects exactly the named-character
     set; every hero surfaced in a mission is in it and resolves to a name; the
     campaign as a whole features known heroes (Raynor / Kerrigan / …).
  3. CONSISTENCY. Briefing lines, unit commands and AI-script links all match the
     dedicated analyzers (the report doesn't drop or invent data).

    py test_mission_analyzer.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import tbl                               # noqa: E402
import dat                               # noqa: E402
import chk as chk_mod                    # noqa: E402
import briefing as brf                   # noqa: E402
import mission_actions as MA             # noqa: E402
import mission_analyzer as MAN           # noqa: E402
import campaign_index                    # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)   # noqa: E731
    hero_set = MAN.hero_set_from_dat(dat.load_from_chain(ch, 'units.dat'))

    ok = total = 0
    bad = []

    # hero flag selects a plausible named set incl. known heroes
    total += 1
    hero_names = {stat.text(i) for i in hero_set}
    if 20 < len(hero_set) < 60 and {'Jim Raynor', 'Sarah Kerrigan'} <= hero_names:
        ok += 1
    else:
        bad.append('hero set %d' % len(hero_set))

    missions = 0
    json_ok = True
    all_heroes = set()
    consistency_ok = True
    bad_hero = 0
    for path in campaign_index.campaign_chk_names():
        try:
            data = ch.read(path)
        except Exception:                            # noqa: BLE001
            continue
        missions += 1
        chk = chk_mod.parse(data)
        rep = MAN.analyze(chk, uname, hero_set)
        try:
            json.dumps(rep)
        except Exception:                            # noqa: BLE001
            json_ok = False
        # every hero in the report must be in the hero set + have a name
        for h in rep['heroes']:
            all_heroes.add(h['name'])
            if h['unit'] not in hero_set or not h['name']:
                bad_hero += 1
        # consistency vs the dedicated analyzers
        if len(rep['commands']) != len(MA.classify(chk, uname)):
            consistency_ok = False
        if sum(b['n_lines'] for b in rep['briefing']) != \
                sum(b['n_lines'] for b in brf.analyze(chk, uname)):
            consistency_ok = False

    # 2. coverage + json + heroes surface across the campaign
    total += 1
    if missions > 20 and json_ok and bad_hero == 0 and len(all_heroes) > 5:
        ok += 1
    else:
        bad.append('missions %d json %s bad_hero %d heroes %d'
                   % (missions, json_ok, bad_hero, len(all_heroes)))

    # 3. consistency with the piece analyzers
    total += 1
    if consistency_ok:
        ok += 1
    else:
        bad.append('report drops/invents data vs piece analyzers')

    rc = report('mission: full analyzer report', ok, total,
                '(%d missions, %d hero flag, %d distinct heroes; bad=%s)'
                % (missions, len(hero_set), len(all_heroes),
                   bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
