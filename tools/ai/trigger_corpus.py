#!/usr/bin/env python3
"""Full trigger corpus for the campaign - every trigger's conditions AND actions,
resolved, for every mission, plus the campaign-wide type vocabulary.

The Revolution finding (control transfer = rescue OWNR + CreateUnitWithProperties,
not GiveUnits/alliance) came from reading a mission's WHOLE trigger set. This does
that systematically for the entire campaign: it is the AI-disasm coverage oracle's
analogue for CHK triggers. `chk.py` now parses conditions (type@+15) alongside
actions, so a trigger is fully described by (players, [conditions], [actions]).

MEASURED over V's install (tests/ai/test_trigger_corpus.py): 64 missions, ~1850
triggers, ~2767 conditions, ~9666 actions; **13 distinct condition types and 47
action types, 0 unknown** - the COND_TYPES (chk.py) + TRIGGER_ACTIONS
(mission_actions.py) tables cover the whole campaign, so this is a complete
trigger reference an engine port can diff its interpretation against.

Action-parameter layout (32 B, measured): loc@0 str@4 wav@8 time@12 player@16
group2@20 unit@24 id@26 modifier@27. Only the fields meaningful for each action
are shown. Names/ids are the borrowed format-data (attributed in mission_actions).
"""
import os
import sys
import struct
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chk as chkmod
import mission_actions as MA

# action ids whose second-group u32 (@20) is a TARGET PLAYER, an ORDER type, etc.
_ACT_GIVE = 48
_ACT_ORDER = 46
_ACT_AI = (15, 16)
_ACT_TRANSMISSION = 7
_ACT_PLAYWAV = 8
_QUANT_CONDS = {'Bring', 'Command', 'Accumulate', 'Kills', 'Deaths', 'Opponents',
                'CommandsTheMostAt', 'CommandsTheLeastAt', 'Score'}


def describe_condition(c, chk, uname):
    t = c.type_name
    if t in _QUANT_CONDS:
        loc = chk.location_name(c.location)
        return '%s(P%d %s %d %s%s)' % (t, c.player, c.comparison_name, c.quantity,
                                       uname(c.unit_type), ' @' + loc if loc else '')
    if t in ('CountdownTimer', 'ElapsedTime'):
        return '%s(%s %ds)' % (t, c.comparison_name, c.quantity)
    if t == 'Switch':
        return 'Switch'
    return t


def describe_action(a, chk, uname):
    name = MA.action_name(a.action_id)
    raw = a.raw
    parts = []
    if a.action_id in _ACT_AI:
        parts.append('script=' + a.script_id)
        if a.player:
            parts.append('P%d' % a.player)
        if a.location:
            parts.append('@' + chk.location_name(a.location))
    elif a.action_id == _ACT_GIVE:
        to_p = struct.unpack_from('<I', raw, 20)[0]
        parts.append('P%d->P%d' % (a.player, to_p))
        parts.append('%s x%s' % (uname(a.unit_type), raw[27] or 'all'))
        if a.location:
            parts.append('@' + chk.location_name(a.location))
    elif a.action_id == _ACT_ORDER:
        parts.append('P%d %s x%s' % (a.player, uname(a.unit_type), raw[27] or ''))
        parts.append(MA.ORDER_TYPES.get(raw[27], 'order%d' % raw[27]))
        if a.location:
            parts.append('@' + chk.location_name(a.location))
    elif a.action_id in (_ACT_TRANSMISSION, 29):        # transmission / talking portrait
        if a.unit_type:
            parts.append('speaker=' + uname(a.unit_type))
        if a.string:
            parts.append('"%s"' % chk.string(a.string).replace('\n', ' ')[:40])
    else:
        if a.player:
            parts.append('P%d' % a.player)
        if a.unit_type:
            parts.append(uname(a.unit_type))
        if a.location:
            parts.append('@' + chk.location_name(a.location))
        if a.string:
            parts.append('"%s"' % chk.string(a.string).replace('\n', ' ')[:40])
    return name + ('(' + ' '.join(parts) + ')' if parts else '')


def mission_triggers(chk, uname):
    """Full resolved trigger list for one mission (JSON-serialisable)."""
    out = []
    for tr in chk.triggers:
        out.append({
            'index': tr.index,
            'players': tr.players,
            'conditions': [describe_condition(c, chk, uname) for c in tr.conditions],
            'actions': [describe_action(a, chk, uname) for a in tr.actions],
        })
    return out


def survey(missions_iter, uname):
    """Campaign-wide type vocabulary + per-mission counts. missions_iter yields
    (label, Chk)."""
    cond_hist, act_hist = Counter(), Counter()
    per_mission = []
    unknown_cond, unknown_act = Counter(), Counter()
    n_trig = n_cond = n_act = 0
    for label, chk in missions_iter:
        mt = mc = ma = 0
        for tr in chk.triggers:
            mt += 1
            n_trig += 1
            for c in tr.conditions:
                mc += 1; n_cond += 1
                cond_hist[c.type_name] += 1
                if c.cond_type not in chkmod.COND_TYPES:
                    unknown_cond[c.cond_type] += 1
            for a in tr.actions:
                ma += 1; n_act += 1
                act_hist[MA.action_name(a.action_id)] += 1
                if a.action_id >= len(MA.TRIGGER_ACTIONS):
                    unknown_act[a.action_id] += 1
        per_mission.append({'mission': label, 'triggers': mt,
                            'conditions': mc, 'actions': ma})
    return {
        'missions': len(per_mission),
        'triggers': n_trig, 'conditions': n_cond, 'actions': n_act,
        'condition_types': dict(cond_hist.most_common()),
        'action_types': dict(act_hist.most_common()),
        'unknown_condition_types': dict(unknown_cond),
        'unknown_action_ids': dict(unknown_act),
        'per_mission': per_mission,
    }


if __name__ == '__main__':
    import argparse
    import json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    import mpq
    import tbl
    import campaign_index
    ap = argparse.ArgumentParser(description='Campaign trigger corpus + type survey.')
    ap.add_argument('bw', nargs='?', default=r'C:\Git\Starcraft BroodWar  v1.1.61')
    ap.add_argument('--mission', help='dump full triggers of one mission (substring of label)')
    ap.add_argument('--survey', action='store_true', help='campaign-wide type histogram')
    ap.add_argument('--json', help='write survey/dump JSON here')
    args = ap.parse_args()
    ch = mpq.MpqChain(args.bw)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731

    def missions():
        for label, data in campaign_index.find_mpq_campaigns(ch):
            yield label, chkmod.parse(data)

    if args.mission:
        for label, chk in missions():
            if args.mission not in label:
                continue
            trigs = mission_triggers(chk, uname)
            if args.json:
                json.dump({label: trigs}, open(args.json, 'w'), indent=1, ensure_ascii=False)
            print('=== %s: %d triggers ===' % (label, len(trigs)))
            for t in trigs:
                print('T%-3d P%s' % (t['index'], ','.join(map(str, t['players'][:4]))))
                for c in t['conditions']:
                    print('   IF  ' + c)
                for a in t['actions']:
                    print('   DO  ' + a)
            break
    else:
        s = survey(missions(), uname)
        if args.json:
            json.dump(s, open(args.json, 'w'), indent=1, ensure_ascii=False)
            print('wrote survey -> %s' % args.json)
        print('missions=%d triggers=%d conditions=%d actions=%d'
              % (s['missions'], s['triggers'], s['conditions'], s['actions']))
        print('condition types (%d), action types (%d); unknown cond=%s act=%s'
              % (len(s['condition_types']), len(s['action_types']),
                 s['unknown_condition_types'] or 'none', s['unknown_action_ids'] or 'none'))
        print('CONDITIONS:', s['condition_types'])
        print('ACTIONS:', s['action_types'])
