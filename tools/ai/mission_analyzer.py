#!/usr/bin/env python3
"""Full campaign-mission analyzer - one normalized per-mission report the engine
port diffs against to verify AI, triggers, briefing, heroes and players.

Integrates the measured pieces:
  * briefing timeline      (briefing.py, MBRF)
  * unit commands          (mission_actions.py, TRIG unit-orders)
  * AI-script links        (TRIG actions 15/16 -> script FourCC + location)
  * HEROES                 units used in the mission (pre-placed UNIT section OR
                           referenced by a trigger command) that carry the
                           units.dat Hero flag (special_ability_flags bit 6 =
                           0x40, MEASURED: 37 hero ids - Raynor/Kerrigan/Zeratul/…)
  * players                OWNR (controller) + SIDE (race) per slot

`to_dict()` is JSON-serialisable; the CLI writes it. Unit names via stat_txt
(unit u = stat_txt.tbl[u+1] == tbl.text(u), 0-based).
"""
import struct

import chk as chk_mod
import briefing as brf
import mission_actions as MA

HERO_FLAG = 0x40                                     # special_ability_flags bit 6


def hero_set_from_dat(units_dat):
    """Set of unit ids with the units.dat Hero flag."""
    out = set()
    for i in range(228):
        saf = units_dat.get('special_ability_flags', i)
        if saf is not None and (saf & HERO_FLAG):
            out.add(i)
    return out


def ai_links(chk):
    """Trigger AI-script actions (15 RunAIScript / 16 RunAIScriptAtLocation)."""
    links = []
    for tr in chk.triggers:
        for a in tr.actions:
            if a.action_id in (15, 16):
                links.append({'trigger': tr.index,
                              'at_location': a.action_id == 16,
                              'script': a.fourcc.decode('latin1', 'replace'),
                              'location': a.location,
                              'location_name': chk.location_name(a.location)})
    return links


def analyze(chk, unit_name=None, hero_set=None):
    un = unit_name or (lambda u: 'unit %d' % u)
    hero_set = hero_set or set()

    commands = MA.classify(chk, un)
    briefs = brf.analyze(chk, un)
    links = ai_links(chk)

    # heroes: pre-placed + trigger-referenced, filtered to the Hero flag
    hero_use = {}
    for uid, owner, x, y in chk.units:
        if uid in hero_set:
            h = hero_use.setdefault(uid, {'unit': uid, 'name': un(uid),
                                          'placed': 0, 'commanded': 0,
                                          'owners': set()})
            h['placed'] += 1
            h['owners'].add(owner)
    for c in commands:
        if c['unit'] in hero_set:
            h = hero_use.setdefault(c['unit'], {'unit': c['unit'],
                                                'name': c['unit_name'],
                                                'placed': 0, 'commanded': 0,
                                                'owners': set()})
            h['commanded'] += 1
    heroes = []
    for uid in sorted(hero_use):
        h = hero_use[uid]
        heroes.append({'unit': h['unit'], 'name': h['name'],
                       'placed': h['placed'], 'commanded': h['commanded'],
                       'owners': sorted(h['owners'])})

    return {
        'triggers': len(chk.triggers),
        'players': {'owners': chk.owners, 'sides': chk.sides},
        'placed_units': len(chk.units),
        'briefing': briefs,
        'commands': commands,
        'command_summary': MA.summary(commands),
        'ai_scripts': links,
        'heroes': heroes,
    }


if __name__ == '__main__':
    import sys
    import os
    import json
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import tbl
    import dat
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    mission = sys.argv[2] if len(sys.argv) > 2 \
        else 'campaign\\terran\\terran02\\staredit\\scenario.chk'
    out_json = sys.argv[3] if len(sys.argv) > 3 else None
    ch = mpq.MpqChain(base)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    heroes = hero_set_from_dat(dat.load_from_chain(ch, 'units.dat'))
    chk = chk_mod.parse(ch.read(mission))
    rep = analyze(chk, lambda u: stat.text(u) or 'unit %d' % u, heroes)
    print('== %s ==' % mission.split('\\')[-3])
    print('triggers %d, placed units %d, AI scripts %d, commands %s'
          % (rep['triggers'], rep['placed_units'], len(rep['ai_scripts']),
             rep['command_summary']['by_kind']))
    print('briefing: %s' % [(b['n_lines'], b['total_ms']) for b in rep['briefing']])
    print('heroes:', [(h['name'], 'placed' if h['placed'] else 'commanded')
                      for h in rep['heroes']])
    if out_json:
        json.dump(rep, open(out_json, 'w', encoding='utf-8'), indent=1)
        print('wrote', out_json)
