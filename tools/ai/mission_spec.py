#!/usr/bin/env python3
"""Per-mission SPEC SHEET - the machine-readable "what the engine must do".

The oracle already reads a mission's triggers, conditions, pre-placed units, AI
and briefing. This turns them into one normalized spec per mission: the win/lose
conditions, the scripted ownership transfers, the pre-placed roster and the AI -
the reference the OpenBW engine diffs its actual playthrough against. A campaign
bug is then a divergence between this ENCODED truth and the engine's OBSERVED
behaviour (victory never fires, a unit not spawned, a transfer that made an ally
instead of giving control), localised to one trigger/condition/unit.

Grounded example (Revolution / terran05): the Antigan base becomes YOURS, and V
confirmed you control the units rather than them turning allied. The spec shows
WHY: the mission uses NO SetAllianceStatus action and NO GiveUnitsToPlayer action
- the transfer is the RESCUE owner mechanic (a player whose OWNR type is 'rescue')
plus CreateUnitWithProperties. An engine that modelled the takeover as an alliance
or a give-units action would be wrong; the spec says where to look.

Reuses chk.py (now with conditions), mission_actions (names), mission_bot (AI).
Borrowed nomenclature is attributed in those modules.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chk as chkmod
import mission_actions as MA
import mission_bot

# trigger player-field groups (the id a condition/action is scoped to)
PLAYER_GROUP = {13: 'CurrentPlayer', 14: 'Foes', 15: 'Allies', 16: 'NeutralPlayers',
                17: 'AllPlayers', 18: 'Force1', 19: 'Force2', 20: 'Force3',
                21: 'Force4', 26: 'NonAlliedVictoryPlayers'}
ACT_VICTORY, ACT_DEFEAT, ACT_OBJECTIVES = 1, 2, 12
ACT_GIVE, ACT_ALLIANCE, ACT_CREATE_PROPS, ACT_CREATE = 48, 57, 11, 44
ACT_RUN_AI, ACT_RUN_AI_AT = 15, 16
_QUANT_CONDS = {'Bring', 'Command', 'Accumulate', 'Kills', 'Deaths', 'CommandTheMost',
                'CommandTheLeast', 'Opponents'}


def _pgroup(p):
    return PLAYER_GROUP.get(p, 'P%d' % (p + 1) if p < 12 else 'grp%d' % p)


def describe_condition(c, chk, uname):
    t = c.type_name
    if t in _QUANT_CONDS:
        loc = chk.location_name(c.location)
        return '%s: %s %s %d %s%s' % (t, _pgroup(c.player), c.comparison_name,
                                      c.quantity, uname(c.unit_type),
                                      ' @%s' % loc if loc else '')
    if t in ('CountdownTimer', 'ElapsedTime'):
        return '%s %s %d s' % (t, c.comparison_name, c.quantity)
    if t == 'Switch':
        return 'Switch set'
    if t == 'Always':
        return 'Always'
    return t


def _win_lose(chk, uname, action_id):
    out = []
    for tr in chk.triggers:
        if tr.has_action(action_id):
            out.append({
                'players': [_pgroup(p) for p in tr.players],
                'conditions': [describe_condition(c, chk, uname) for c in tr.conditions],
            })
    return out


def spec(chk, uname, hero_set=None, ai_tables=None, ai_files=None):
    """Build the normalized spec sheet for one parsed Chk. Returns a JSON dict."""
    secs = chk.sections
    # objectives text (MBRF action 4 or TRIG action 12)
    objectives = []
    for tr in chk.briefings:
        for a in tr.actions:
            if a.action_id == 4 and a.string:
                s = chk.string(a.string)
                if s:
                    objectives.append(s.strip())
    for tr in chk.triggers:
        for a in tr.actions:
            if a.action_id == ACT_OBJECTIVES and a.string:
                s = chk.string(a.string)
                if s and s.strip() not in objectives:
                    objectives.append(s.strip())

    # ownership: OWNR types (flag rescue) + pre-placed roster
    owners = {}
    for i, o in enumerate(chk.owners):
        if o and o not in (0,):
            owners[i] = chkmod.OWNR_LABEL.get(o, 'owner%d' % o)
    rescue_players = [i for i, o in enumerate(chk.owners) if o == 3]   # 'rescue' byte
    placed = {}
    for (uid, owner, x, y) in chk.units:
        placed.setdefault(owner, {})
        placed[owner][uname(uid)] = placed[owner].get(uname(uid), 0) + 1

    # transfers / alliance (how control changes hands)
    give_units, alliance = [], 0
    for tr in chk.triggers:
        for a in tr.actions:
            if a.action_id == ACT_GIVE:
                import struct
                to_p = struct.unpack_from('<I', a.raw, 20)[0]
                give_units.append({'from': _pgroup(a.player), 'to': _pgroup(to_p),
                                   'unit': uname(a.unit_type), 'count': a.raw[27] or 'all',
                                   'at': chk.location_name(a.location)})
            elif a.action_id == ACT_ALLIANCE:
                alliance += 1

    # scripted event tallies
    from collections import Counter
    act_hist = Counter()
    for tr in chk.triggers:
        for a in tr.actions:
            act_hist[MA.action_name(a.action_id)] += 1

    out = {
        'objectives': objectives,
        'victory': _win_lose(chk, uname, ACT_VICTORY),
        'defeat': _win_lose(chk, uname, ACT_DEFEAT),
        'owners': owners,
        'rescue_players': rescue_players,
        'transfers': {
            'give_units': give_units,
            'set_alliance_actions': alliance,
            'create_with_properties': act_hist.get('CreateUnitWithProperties', 0),
            'create_unit': act_hist.get('CreateUnit', 0),
        },
        'pre_placed': {o: dict(sorted(u.items(), key=lambda kv: -kv[1]))
                       for o, u in sorted(placed.items())},
        'action_hist': dict(sorted(act_hist.items(), key=lambda kv: -kv[1])),
        'n_triggers': len(chk.triggers),
    }
    if hero_set is not None:
        out['heroes'] = sorted({uname(uid) for (uid, o, x, y) in chk.units if uid in hero_set})
    if ai_tables is not None and ai_files is not None:
        prof = mission_bot.mission_behavior(chk, ai_tables, ai_files, uname)
        out['ai_attack'] = prof['attacks']
        out['ai_builds'] = prof['builds']
    return out


def render_text(sp, name=''):
    L = ['=== SPEC: %s ===' % name]
    L.append('Objectives:')
    for o in sp['objectives']:
        for line in o.split('\n'):
            if line.strip():
                L.append('  - ' + line.strip())
    L.append('WIN when:')
    for v in sp['victory']:
        L.append('  [%s] %s' % (','.join(v['players']), ' & '.join(v['conditions']) or 'Always'))
    L.append('LOSE when:')
    for d in sp['defeat']:
        L.append('  [%s] %s' % (','.join(d['players']), ' & '.join(d['conditions']) or 'Always'))
    t = sp['transfers']
    L.append('Ownership transfer: give_units=%d set_alliance=%d create_props=%d  rescue_players=%s'
             % (len(t['give_units']), t['set_alliance_actions'], t['create_with_properties'],
                sp['rescue_players']))
    for g in t['give_units']:
        L.append('  GIVE %s -> %s : %s x%s @%s' % (g['from'], g['to'], g['unit'], g['count'], g['at']))
    if 'heroes' in sp:
        L.append('Heroes: ' + ', '.join(sp['heroes']))
    if 'ai_attack' in sp:
        L.append('Enemy attacks with: ' + ', '.join('%s x%d' % (r['name'], r['count'])
                                                     for r in sp['ai_attack'][:6]))
    return '\n'.join(L)


if __name__ == '__main__':
    import json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    import mpq
    import tbl
    import dat
    import chk_ai_links
    import ai_bin
    import campaign_index
    bw = sys.argv[1] if len(sys.argv) > 1 else r'C:\Git\Starcraft BroodWar  v1.1.61'
    want = sys.argv[2] if len(sys.argv) > 2 else None
    as_json = '--json' in sys.argv
    ch = mpq.MpqChain(bw)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    udat = dat.load_from_chain(ch, 'units.dat')
    hero_set = {i for i in range(228) if (udat.get('special_ability_flags', i) >> 6) & 1}
    tables = chk_ai_links.load_ai_tables(bw)
    ai_files = ai_bin.load_from_chain(ch)
    for label, data in campaign_index.find_mpq_campaigns(ch):
        if want and want not in label:
            continue
        chk = chkmod.parse(data)
        sp = spec(chk, uname, hero_set, tables, ai_files)
        if as_json:
            print(json.dumps({label: sp}, ensure_ascii=False, indent=1))
        else:
            print(render_text(sp, label))
            print()
