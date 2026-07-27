"""Oracle for the canonical replay dump (tools/rep/rep_canonical.py).

The dump is the stable reference the engine's replay parser diffs against, so the
falsifiable properties are: it is a pure function of the stream, it accounts for
every command, and every line is well-formed.

  1. DETERMINISTIC. canonical_lines(replay) twice gives identical output — a diff
     target that isn't stable is useless.

  2. COMPLETE. One line per decoded command; the count equals rep_commands.decode,
     and the stream is fully consumed (consumed == total). Reuses the command
     coverage the main rep oracle already proves.

  3. WELL-FORMED. Every line matches `f<int> p<int> <2-hex> <name> <hex-even>`, and
     the summary's player storm_ids match the header — so an engine diffing against
     this knows the exact schema.

    py test_rep_canonical.py
"""
import sys
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'rep'))
from common import report                                   # noqa: E402
import rep_read                                             # noqa: E402
import rep_commands as RC                                   # noqa: E402
import rep_canonical as CAN                                 # noqa: E402

REPLAYS = os.environ.get('SC_REPLAYS_DIR',
                         os.path.join(os.path.expanduser('~'), 'Downloads', 'SC1_replays'))
LINE = re.compile(r'^f\d+ p\d+ [0-9a-f]{2} \S+ (?:[0-9a-f]{2})*$')


def main():
    if not os.path.isdir(REPLAYS):
        print('SKIP: replay folder not found (%s)' % REPLAYS)
        sys.exit(77)
    files = [os.path.join(REPLAYS, f) for f in sorted(os.listdir(REPLAYS))
             if f.lower().endswith('.rep')]
    if not files:
        print('SKIP: no .rep in %s' % REPLAYS)
        sys.exit(77)
    reps = [(os.path.basename(f), rep_read.load(f)) for f in files]

    ok = total = 0
    bad = []

    # 1. deterministic
    total += 1
    det_ok = all(CAN.canonical_lines(r) == CAN.canonical_lines(r) for _, r in reps)
    if det_ok:
        ok += 1
    else:
        bad.append('non-deterministic dump')

    # 2. complete: line count == decoded command count; stream fully consumed
    total += 1
    n_lines = n_cmds = 0
    comp_ok = True
    for nm, r in reps:
        cmds, consumed = RC.decode(r.commands)
        lines = CAN.canonical_lines(r)
        n_lines += len(lines)
        n_cmds += len(cmds)
        if len(lines) != len(cmds) or consumed != len(r.commands):
            comp_ok = False
            bad.append('%s lines=%d cmds=%d consumed=%d/%d'
                       % (nm, len(lines), len(cmds), consumed, len(r.commands)))
    if comp_ok:
        ok += 1

    # 3. well-formed lines + summary storm ids match the header
    total += 1
    form_ok = True
    for nm, r in reps:
        for ln in CAN.canonical_lines(r):
            if not LINE.match(ln):
                form_ok = False
                bad.append('%s bad line %r' % (nm, ln[:40]))
                break
        s = CAN.summary(r)
        if {p['storm_id'] for p in s['players']} != {p.storm_id for p in r.players}:
            form_ok = False
            bad.append('%s storm-id mismatch' % nm)
    if form_ok:
        ok += 1

    rc = report('rep_canonical: stable command dump', ok, total,
                '(%d replays, %d lines; bad=%s)' % (len(reps), n_lines, bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
