#!/usr/bin/env python3
"""Canonical replay command dump — the stable, byte-diffable reference the engine's
replay parser diffs against.

The engine plays a `.rep` back through the sim (its `aidump replay` gate checks the
resulting LCG hash), but it does NOT currently cross-check the *decoded command
stream* it parsed. This module emits that stream in one canonical form for BOTH
container variants:

  * classic `reRS` (1.16.1, PKWARE chunks)
  * Remastered `seRS` (zlib chunks + `_121` commands 0x60-0x65)

so it is directly the oracle for the engine's OPEN "SC:R seRS replay loader" item:
decode a known-good `.rep` here, have the engine decode the same file, and diff the
two command dumps line-for-line — a divergence points at the exact frame/command the
parser got wrong, unlike the LCG hash which only says "diverged somewhere".

Line format (one command, stable): `f<frame> p<storm_id> <cmd_id:02x> <name> <args-hex>`
  - `storm_id` is the header struct +4 id the command is attributed to (NOT display pid).
  - args are the raw little-endian argument bytes, lowercase hex (empty if none).

    py -m rep.rep_canonical <file.rep>           # print header + canonical lines
    py -m rep.rep_canonical <file.rep> --summary # just counts (frames, cmds, players)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rep_read                              # noqa: E402
import rep_commands as RC                    # noqa: E402


def canonical_lines(replay):
    """Deterministic list[str], one line per command, in stream (frame) order.
    A pure function of the decoded stream — same replay in, same lines out."""
    cmds, _consumed = RC.decode(replay.commands)
    return ['f%d p%d %02x %s %s'
            % (c.frame, c.player, c.cmd_id, c.name, c.args.hex())
            for c in cmds]


def canonical_text(replay):
    return '\n'.join(canonical_lines(replay))


def summary(replay):
    """Header-level facts the engine can also assert (magic, players, counts)."""
    cmds, consumed = RC.decode(replay.commands)
    return {
        'engine_version': replay.engine,  # header engine byte (container magic is
                                          # resolved by rep_read on load: reRS/seRS)
        'frames': replay.frames,
        'players': [{'storm_id': p.storm_id, 'name': p.name, 'race': p.race}
                    for p in replay.players],
        'command_count': len(cmds),
        'command_bytes_consumed': consumed,
        'command_bytes_total': len(replay.commands),
    }


def _cli(argv):
    if not argv:
        print('usage: py -m rep.rep_canonical <file.rep> [--summary]', file=sys.stderr)
        return 2
    r = rep_read.load(argv[0])
    if '--summary' in argv:
        import json
        print(json.dumps(summary(r), indent=2, ensure_ascii=False))
        return 0
    s = summary(r)
    print('# engine_v%d  frames=%d  players=%d  commands=%d  consumed=%d/%d'
          % (s['engine_version'], s['frames'], len(s['players']), s['command_count'],
             s['command_bytes_consumed'], s['command_bytes_total']))
    for p in s['players']:
        print('# p%d %-24s %s' % (p['storm_id'], p['name'], p['race']))
    print(canonical_text(r))
    return 0


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
