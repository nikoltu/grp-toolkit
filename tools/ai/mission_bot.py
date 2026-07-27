#!/usr/bin/env python3
"""Per-mission bot behaviour, derived from the mission's AI scripts.

This is the GROUND TRUTH half of "what does the enemy actually do?": a campaign
mission's triggers run named AI scripts (chk_ai_links); each script's bytecode
says exactly what its bot builds, trains, researches and attacks with
(ai_semantics). This aggregates those into one behaviour profile per mission -
the objective record a human walkthrough is then cross-checked against
(tools/ai/walkthrough.py). No opinion, no web: straight out of the bytecode V's
install ships.

The unit id in a build/train/attack opcode is the arg whose TYPE is one of the
unit-like types below (the preceding `byte` is the count). Unit AND building ids
are both indices into units.dat, so stat_txt.tbl[id] names either.

Reuses chk_ai_links + ai_semantics + ai_bin. No third-party libraries.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chk_ai_links
import ai_semantics

UNIT_ARG_TYPES = {'building', 'military', 'unit', 'gg_military', 'ag_military',
                  'ga_military', 'aa_military'}
BUILD_OPS = {'build', 'defensebuild_gg', 'defensebuild_ag', 'defensebuild_ga',
             'defensebuild_aa', 'build_bunkers', 'build_turrets'}
TRAIN_OPS = {'train', 'do_morph', 'wait_train', 'create_unit', 'define_max'}


def _unit_id(rec):
    for typ, val in rec['args']:
        if typ in UNIT_ARG_TYPES:
            return val
    return None


def _count(rec):
    for typ, val in rec['args']:
        if typ == 'byte':
            return val
    return None


def script_behavior(ai_files, script_id):
    """Summary for a script id, found across the loaded .bin sources (or None)."""
    for _src, f in ai_files.items():
        e = f.by_id().get(script_id)
        if e and e.offset:
            return ai_semantics.summarize_script(f, e, script_id)
    return None


def _acc(d, key, n):
    d[key] = d.get(key, 0) + (n or 1)


def mission_behavior(chk, ai_tables, ai_files, uname):
    """Aggregate the mission's AI scripts into a behaviour profile.

    Returns a JSON-serialisable dict:
      scripts:   [{script_id, players, resolved}]
      builds/trains/attacks: [{unit, name, count}]  (unit type totals)
      tech:      [ids], upgrades: [{id, count}], towns: int
      unit_types: sorted set of every unit-type id the bots produce/field
    """
    links = chk_ai_links.extract_links(chk, getattr(chk, 'fmt_label', ''), ai_tables)
    seen = {}
    scripts = []
    for l in links:
        scripts.append({'script_id': l.script_id, 'players': l.players,
                        'resolved': l.resolved})
        if l.script_id in seen:
            continue
        seen[l.script_id] = script_behavior(ai_files, l.script_id)

    builds, trains, attacks, upgrades = {}, {}, {}, {}
    tech = set()
    towns = 0
    for sid, s in seen.items():
        if not s:
            continue
        towns += s.towns
        for rec in s.production:
            uid = _unit_id(rec)
            if uid is None:
                continue
            tgt = builds if rec['op'] in BUILD_OPS else trains
            _acc(tgt, uid, _count(rec))
        for rec in s.tech:
            if rec['op'] == 'upgrade':
                uid = next((v for t, v in rec['args'] if t == 'upgrade'), None)
                if uid is not None:
                    _acc(upgrades, uid, _count(rec))
            else:
                tid = next((v for t, v in rec['args'] if t == 'technology'), None)
                if tid is not None:
                    tech.add(tid)
        for wave in s.attack_waves:
            for rec in wave:
                uid = _unit_id(rec)
                if uid is not None:
                    _acc(attacks, uid, _count(rec))

    def named(d):
        return sorted(({'unit': k, 'name': uname(k), 'count': v}
                       for k, v in d.items()), key=lambda r: -r['count'])

    unit_types = sorted(set(builds) | set(trains) | set(attacks))
    return {
        'scripts': scripts,
        'builds': named(builds),
        'trains': named(trains),
        'attacks': named(attacks),
        'tech': sorted(tech),
        'upgrades': sorted(({'id': k, 'count': v} for k, v in upgrades.items()),
                           key=lambda r: -r['count']),
        'towns': towns,
        'unit_types': unit_types,
        'unit_names': {u: uname(u) for u in unit_types},
    }


if __name__ == '__main__':
    import json
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import tbl
    import ai_bin
    import chk as chk_mod
    import campaign_index
    bw = sys.argv[1] if len(sys.argv) > 1 else r'C:\Git\Starcraft BroodWar  v1.1.61'
    want = sys.argv[2] if len(sys.argv) > 2 else 'expterran/terran03'
    ch = mpq.MpqChain(bw)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    tables = chk_ai_links.load_ai_tables(bw)
    ai_files = ai_bin.load_from_chain(ch)
    for label, data in campaign_index.find_mpq_campaigns(ch):
        if label != want:
            continue
        chk = chk_mod.parse(data)
        chk.fmt_label = label
        prof = mission_behavior(chk, tables, ai_files, uname)
        print('=== %s ===' % label)
        print('scripts:', len(prof['scripts']), ' towns:', prof['towns'])
        print('builds :', [(r['name'], r['count']) for r in prof['builds']])
        print('trains :', [(r['name'], r['count']) for r in prof['trains']])
        print('attacks:', [(r['name'], r['count']) for r in prof['attacks']])
        break
