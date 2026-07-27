#!/usr/bin/env python3
"""Classify a campaign mission's TRIG actions into per-unit COMMANDS - what the
mission's triggers order units to do (create / move / order to Move-Patrol-Attack
/ give / kill / remove / modify), where, for whom.

The trigger action id -> name table is borrowed format data (PyMS TRG.py, MIT,
attributed like ai_opcodes); the binary FIELD layout of each command is MEASURED
against the campaign (32-byte action: location@0, player@16, second@20,
unitType@24, actionId@26, count/orderType@27):

  Order (46): order player@16's unit@24 at location@0 to <order@27> to the target
              location@20 (order 0=Move, 1=Patrol, 2=Attack).
  MoveUnit(39): move count@27 of unit@24 from location@0 to dest location@20.
  CreateUnit(44)/WithProps(11): create count@27 unit@24 at location@0 for player@16.
  GiveUnits(48): give count@27 unit@24 at location@0 from player@16 to player@20.
  Kill/Remove(22-25): remove unit@24 (at location@0) for player@16.

This is a normalized per-mission list the engine port diffs against to check its
trigger interpretation - the mission analogue of the briefing timeline.
"""
import struct

import chk as chk_mod

# NORMAL_TRIGGERS action names by id (from PyMS FileFormats/TRG.py, attributed).
TRIGGER_ACTIONS = [
    'NoAction', 'Victory', 'Defeat', 'PreserveTrigger', 'Wait', 'PauseGame',
    'UnpauseGame', 'Transmission', 'PlayWAV', 'DisplayTextMessage', 'CenterView',
    'CreateUnitWithProperties', 'SetMissionObjectives', 'SetSwitch',
    'SetCountdownTimer', 'RunAIScript', 'RunAIScriptAtLocation',
    'LeaderBoardControl', 'LeaderBoardControlAtLocation', 'LeaderBoardResources',
    'LeaderBoardKills', 'LeaderBoardPoints', 'KillUnit', 'KillUnitsAtLocation',
    'RemoveUnit', 'RemoveUnitAtLocation', 'SetResources', 'SetScore',
    'MinimapPing', 'TalkingPortrait', 'MuteUnitSpeech', 'UnmuteUnitSpeech',
    'LeaderboardComputerPlayers', 'LeaderboardGoalControl',
    'LeaderboardGoalControlAtLocation', 'LeaderboardGoalResources',
    'LeaderboardGoalKills', 'LeaderboardGoalPoints', 'MoveLocation', 'MoveUnit',
    'LeaderboardGreed', 'SetNextScenario', 'SetDoodadState', 'SetInvincibility',
    'CreateUnit', 'SetDeaths', 'Order', 'Comment', 'GiveUnitstoPlayer',
    'ModifyUnitHitPoints', 'ModifyUnitEnergy', 'ModifyUnitShieldPoints',
    'ModifyUnitResourceAmount', 'ModifyUnitHangerCount', 'PauseTimer',
    'UnpauseTimer', 'Draw', 'SetAllianceStatus', 'DisableDebugMode',
    'EnableDebugMode',
]

ORDER_TYPES = {0: 'Move', 1: 'Patrol', 2: 'Attack'}

# action id -> our command 'kind'
UNIT_COMMANDS = {
    11: 'create', 22: 'kill', 23: 'kill', 24: 'remove', 25: 'remove',
    39: 'move', 44: 'create', 45: 'deaths', 46: 'order', 48: 'give',
    49: 'modify', 50: 'modify', 51: 'modify', 52: 'modify', 53: 'modify',
}


def action_name(action_id):
    return TRIGGER_ACTIONS[action_id] if action_id < len(TRIGGER_ACTIONS) \
        else 'act%d' % action_id


def classify(chk, unit_name=None):
    """Return the per-unit command list for a parsed Chk. `unit_name`: optional
    callable id -> str."""

    def uname(uid):
        return unit_name(uid) if unit_name else str(uid)

    out = []
    for tr in chk.triggers:
        for a in tr.actions:
            kind = UNIT_COMMANDS.get(a.action_id)
            if kind is None:
                continue
            second = struct.unpack_from('<I', a.raw, 20)[0]      # @20
            n27 = a.raw[27]                                      # count / order
            rec = {'trigger': tr.index, 'action': action_name(a.action_id),
                   'kind': kind, 'player': a.player, 'unit': a.unit_type,
                   'unit_name': uname(a.unit_type),
                   'source_loc': a.location,
                   'source_loc_name': chk.location_name(a.location)}
            if kind == 'order':
                rec['order'] = ORDER_TYPES.get(n27, 'order%d' % n27)
                rec['target_loc'] = second
                rec['target_loc_name'] = chk.location_name(second)
            elif kind == 'move':
                rec['dest_loc'] = second
                rec['dest_loc_name'] = chk.location_name(second)
                rec['count'] = 'All' if n27 == 0 else n27
            elif kind == 'give':
                rec['to_player'] = second
                rec['count'] = 'All' if n27 == 0 else n27       # 0 = all matching
            elif kind in ('kill', 'remove'):
                rec['count'] = 'All' if n27 == 0 else n27       # 0 = all matching
            else:                                                # create/deaths/modify
                rec['count'] = n27                               # a literal count/amount
            out.append(rec)
    return out


def summary(records):
    """Group the commands by kind and by unit for a quick overview."""
    by_kind = {}
    by_unit = {}
    for r in records:
        by_kind[r['kind']] = by_kind.get(r['kind'], 0) + 1
        by_unit[r['unit_name']] = by_unit.get(r['unit_name'], 0) + 1
    return {'total': len(records), 'by_kind': by_kind, 'by_unit': by_unit}


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import tbl
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    mission = sys.argv[2] if len(sys.argv) > 2 \
        else 'campaign\\terran\\terran02\\staredit\\scenario.chk'
    ch = mpq.MpqChain(base)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    chk = chk_mod.parse(ch.read(mission))
    recs = classify(chk, lambda u: stat.text(u) or 'unit %d' % u)  # text(u) = stat_txt[u+1]
    print('== %s: %d unit commands ==' % (mission.split('\\')[-3], len(recs)))
    print('   summary:', summary(recs)['by_kind'])
    for r in recs[:30]:
        if r['kind'] == 'order':
            tgt = ' -> %s %s' % (r['order'], r['target_loc_name'] or r['target_loc'])
        elif r['kind'] == 'move':
            tgt = ' -> %s' % (r['dest_loc_name'] or r['dest_loc'])
        elif r['kind'] == 'give':
            tgt = ' -> player %d' % r['to_player']
        else:
            tgt = ''
        print('  T%-4d P%-2d %-12s %-16s @%-12s x%s%s'
              % (r['trigger'], r['player'], r['action'], r['unit_name'][:16],
                 (r['source_loc_name'] or r['source_loc']), r.get('count', ''), tgt))
