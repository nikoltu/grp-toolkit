#!/usr/bin/env python3
"""Turn a replay's decoded command stream into per-player analysis.

This is the human-readable / engine-diffable layer on top of rep_commands: what
each player built, trained, morphed, teched and upgraded and WHEN, their APM, and
who left first. The OpenBW session replays the same command stream through the
engine; this is the independent interpretation it can diff its own against - the
replay analogue of mission_bot (bytecode -> what the side does).

Unit type ids are resolved to names by a caller-supplied `uname` (stat_txt.tbl),
exactly as the DAT/mission tools do. Tech/upgrade ids get names from the small
borrowed tables in rep_names (attributed there); everything else is measured.

No third-party libraries.
"""
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rep_read
import rep_commands as RC
import rep_names

# actions that count as "effective" for EAPM (drop pure selection/spam).
NONEFFECTIVE = {'select', 'select_add', 'select_remove', 'select_121',
                'select_add_121', 'select_remove_121', 'keep_alive', 'sync',
                'chat', 'vision', 'minimap_ping'}


@dataclass
class PlayerReport:
    pid: int
    name: str
    race: str
    apm: float = 0.0
    eapm: float = 0.0
    total_actions: int = 0
    build_order: list = field(default_factory=list)   # [{t, frame, action, unit}]
    units_made: dict = field(default_factory=dict)     # name -> count
    tech: list = field(default_factory=list)           # [{t, name}]
    upgrades: list = field(default_factory=list)
    left_frame: int = None
    action_hist: dict = field(default_factory=dict)


def analyze(replay, uname, commands=None):
    """Analyse a parsed Replay. uname: unit_id -> name. Returns a dict report."""
    cmds = commands if commands is not None else RC.decode(replay.commands)[0]
    minutes = max(replay.duration_seconds / 60.0, 1e-9)
    reps = {}
    for p in replay.players:
        # key by STORM id - that is what the command stream tags actions with
        reps[p.storm_id] = PlayerReport(pid=p.storm_id, name=p.name, race=p.race_name)

    for c in cmds:
        pr = reps.get(c.player)
        if pr is None:
            continue
        pr.total_actions += 1
        pr.action_hist[c.name] = pr.action_hist.get(c.name, 0) + 1

        if c.name in RC.PRODUCE and c.unit_type is not None:
            uname_s = uname(c.unit_type)
            # de-dup a burst of the identical build/morph order at ~same frame
            bo = pr.build_order
            if not (bo and bo[-1]['unit'] == uname_s and bo[-1]['action'] == c.name
                    and c.frame - bo[-1]['frame'] < 24):
                bo.append({'frame': c.frame, 't': replay.frame_to_time(c.frame),
                           'action': c.name, 'unit': uname_s, 'unit_id': c.unit_type})
                pr.units_made[uname_s] = pr.units_made.get(uname_s, 0) + 1
        elif c.name == 'tech':
            tid = c.args[0] if c.args else None
            pr.tech.append({'frame': c.frame, 't': replay.frame_to_time(c.frame),
                            'id': tid, 'name': rep_names.tech_name(tid)})
        elif c.name == 'upgrade':
            uid = c.args[0] if c.args else None
            pr.upgrades.append({'frame': c.frame, 't': replay.frame_to_time(c.frame),
                                'id': uid, 'name': rep_names.upgrade_name(uid)})
        elif c.name == 'leave_game' and pr.left_frame is None:
            pr.left_frame = c.frame

    out_players = []
    for pid, pr in reps.items():
        pr.apm = round(pr.total_actions / minutes, 1)
        eff = sum(v for k, v in pr.action_hist.items() if k not in NONEFFECTIVE)
        pr.eapm = round(eff / minutes, 1)
        out_players.append({
            'pid': pr.pid, 'name': pr.name, 'race': pr.race,
            'apm': pr.apm, 'eapm': pr.eapm, 'total_actions': pr.total_actions,
            'left_frame': pr.left_frame,
            'left_time': replay.frame_to_time(pr.left_frame) if pr.left_frame else None,
            'units_made': dict(sorted(pr.units_made.items(), key=lambda kv: -kv[1])),
            'build_order': pr.build_order[:40],
            'tech': pr.tech, 'upgrades': pr.upgrades,
            'action_hist': dict(sorted(pr.action_hist.items(), key=lambda kv: -kv[1])),
        })

    matchup = 'v'.join(p.race_name[0] for p in replay.players if p.is_human)
    # loser = first human to leave (heuristic); winner = the other, if 1v1
    leavers = [pl for pl in out_players if pl['left_frame'] is not None]
    leavers.sort(key=lambda pl: pl['left_frame'])
    return {
        'remastered': replay.remastered,
        'map': replay.map_name, 'matchup': matchup,
        'frames': replay.frames, 'duration': replay.frame_to_time(replay.frames),
        'players': out_players,
        'first_to_leave': leavers[0]['name'] if leavers else None,
    }


def command_log(replay, uname, commands=None):
    """The whole replay as readable text lines: one per command, in order.
    'time  Pn name  command  detail' - what V asked for, the full sequence in
    text. Select spam is included but compacted (unit count only)."""
    cmds = commands if commands is not None else RC.decode(replay.commands)[0]
    who = {p.storm_id: p for p in replay.players}
    lines = []
    for c in cmds:
        p = who.get(c.player)
        tag = p.name if p else 'P%d' % c.player
        detail = ''
        if c.name in RC.PRODUCE and c.unit_type is not None:
            detail = uname(c.unit_type)
        elif c.name == 'tech':
            detail = rep_names.tech_name(c.args[0]) if c.args else ''
        elif c.name == 'upgrade':
            detail = rep_names.upgrade_name(c.args[0]) if c.args else ''
        elif c.name in RC.ORDER_CMDS and c.position:
            detail = '@(%s,%s)' % c.position
        elif c.name in ('select', 'select_add', 'select_remove',
                        'select_121', 'select_add_121', 'select_remove_121'):
            detail = '%d unit(s)' % (c.args[0] if c.args else 0)
        elif c.name == 'leave_game':
            detail = 'reason %d' % (c.args[0] if c.args else -1)
        lines.append('%-9s %-14s %-18s %s'
                     % (replay.frame_to_time(c.frame), tag, c.name, detail))
    return lines


if __name__ == '__main__':
    import json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    import mpq
    import tbl
    import argparse
    ap = argparse.ArgumentParser(description='Replay analysis / full command log.')
    ap.add_argument('replays', nargs='+')
    ap.add_argument('--log', action='store_true', help='print the full command log')
    ap.add_argument('--json', action='store_true', help='print the analysis JSON')
    _args = ap.parse_args()
    bw = os.environ.get('SC_BW_DIR', r'C:\Git\Starcraft BroodWar  v1.1.61')
    ch = mpq.MpqChain(bw)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    for path in _args.replays:
        r = rep_read.load(path)
        if _args.log:
            for line in command_log(r, uname):
                print(line)
            continue
        rep = analyze(r, uname)
        if _args.json:
            print(json.dumps(rep, indent=1, ensure_ascii=False))
            continue
        print('=== %s  [%s]  %s  (%s)' % (os.path.basename(path), rep['matchup'],
                                          rep['map'], rep['duration']))
        for pl in rep['players']:
            print('  %-14s %-8s APM %-6.1f EAPM %-6.1f  %s'
                  % (pl['name'], pl['race'], pl['apm'], pl['eapm'],
                     'LEFT ' + pl['left_time'] if pl['left_time'] else ''))
            bo = ' > '.join('%s %s' % (b['t'].split('.')[0], b['unit'].split()[-1])
                            for b in pl['build_order'][:12])
            print('     BO:', bo)
