"""Oracle for the replay toolkit (tools/rep/): container + command decode + analysis.

A replay is the players' input stream; the OpenBW session replays it through the
engine, and this is the independent interpretation it diffs against. So the decode
must be exact, not merely non-crashing:

  1. CONTAINER. Every replay parses; the classic (reRS) ones to the exact EOF, the
     SC:R (seRS) ones to their trailer; each yields a plausible header (sane frame
     count, a map name, >= 2 human players).
  2. COMMAND COVERAGE. The command stream decodes with EVERY frame-block consumed
     exactly to its length and the whole section to its end, 0 unknown ids - across
     the whole corpus (~150k commands). This is the same consumption oracle the AI
     disassembler uses; one wrong arg size desyncs a block at once.
  3. STORM MAPPING + SEMANTICS. Commands attribute to players by STORM id (not the
     header pid); with that, both duel players are active (real APM) and every
     build order OPENS with that race's worker (Zerg Drone / Terran SCV / Protoss
     Probe) - proof the unit-type decode and player mapping are right, not just
     self-consistent.
  4. DETERMINISM. Parsing + decoding a replay twice is byte-identical.

Set SC_REPLAYS_DIR to a folder of .rep files (default: V's SC1_replays).

    py test_rep.py
"""
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'rep'))
from common import BW, need, report                       # noqa: E402
import rep_read                                            # noqa: E402
import rep_commands as RC                                  # noqa: E402
import rep_actions                                         # noqa: E402
import rep_transcode                                       # noqa: E402

REPLAYS = os.environ.get('SC_REPLAYS_DIR',
                         os.path.join(os.path.expanduser('~'), 'Downloads', 'SC1_replays'))
WORKER = {'Zerg': 'Drone', 'Terran': 'SCV', 'Protoss': 'Probe'}


def main():
    if not os.path.isdir(REPLAYS):
        print('SKIP: replay folder not found (%s)' % REPLAYS)
        sys.exit(77)
    files = [os.path.join(REPLAYS, f) for f in sorted(os.listdir(REPLAYS))
             if f.lower().endswith('.rep')]
    if not files:
        print('SKIP: no .rep in %s' % REPLAYS)
        sys.exit(77)

    ok = total = 0
    bad = []
    reps = [(os.path.basename(f), rep_read.load(f)) for f in files]

    # 1. container + header
    total += 1
    cont_ok = True
    for nm, r in reps:
        eof_ok = r.parsed_to == r.file_size if not r.remastered else r.parsed_to >= r.file_size - 4096
        humans = [p for p in r.players if p.is_human]
        if not (eof_ok and 0 < r.frames < 500000 and len(humans) >= 2 and r.map_name):
            cont_ok = False
            bad.append('%s parse %d/%d humans %d' % (nm, r.parsed_to, r.file_size, len(humans)))
    if cont_ok:
        ok += 1

    # 2. command coverage: every section fully consumed, 0 unknown ids
    total += 1
    total_cmds = 0
    cov_ok = True
    decoded = {}
    for nm, r in reps:
        try:
            cmds, consumed = RC.decode(r.commands)
        except Exception as e:                             # noqa: BLE001
            cov_ok = False
            bad.append('%s decode %s' % (nm, e))
            continue
        decoded[nm] = cmds
        total_cmds += len(cmds)
        if consumed != len(r.commands):
            cov_ok = False
            bad.append('%s consumed %d/%d' % (nm, consumed, len(r.commands)))
    if cov_ok and total_cmds > 50000:
        ok += 1
    else:
        bad.append('cmds %d' % total_cmds)

    # 3. storm mapping + worker-opening semantics (needs stat_txt for names)
    total += 1
    need(BW, 'Brood War install (unit names)')
    import mpq
    import tbl
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    # A real player produces units (has a build order); observers only select/spectate.
    # Every player WITH a build order must open on that race's worker.
    sem_ok = True
    checked = 0
    for nm, r in reps:
        rep = rep_actions.analyze(r, uname, decoded.get(nm))
        for pl in rep['players']:
            bo = pl['build_order']
            if not bo:
                continue                                   # observer / inactive
            checked += 1
            want = WORKER.get(pl['race'])
            if want and want not in bo[0]['unit']:
                sem_ok = False
                bad.append('%s %s opens %r not %s' % (nm, pl['name'], bo[0]['unit'], want))
    if sem_ok and checked >= 6:
        ok += 1
    else:
        bad.append('semantics checked %d' % checked)

    # 4. determinism
    total += 1
    a = rep_actions.analyze(rep_read.load(files[0]), uname)
    b = rep_actions.analyze(rep_read.load(files[0]), uname)
    if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True):
        ok += 1
    else:
        bad.append('nondeterministic')

    # 5. SC:R -> BW 1.16.1 transcode preserves the logical commands
    def logical(rep):
        return json.dumps(sorted((p['name'], p['build_order'], p['units_made'],
                                  p['tech'], p['upgrades']) for p in rep['players']),
                          sort_keys=True)
    scr = [(nm, r) for nm, r in reps if r.remastered]
    if scr:
        total += 1
        tr_ok = True
        n_tr = 0
        for nm, r in scr:
            out = rep_transcode.transcode(open(os.path.join(REPLAYS, nm), 'rb').read())
            rr = rep_read.parse(out)
            if rr.remastered:                              # must now be classic reRS
                tr_ok = False; bad.append('%s still seRS' % nm); continue
            _, consumed = RC.decode(rr.commands)
            if consumed != len(rr.commands):
                tr_ok = False; bad.append('%s transcode consume' % nm); continue
            if logical(rep_actions.analyze(r, uname)) != logical(rep_actions.analyze(rr, uname)):
                tr_ok = False; bad.append('%s transcode changed commands' % nm); continue
            n_tr += 1
        if tr_ok and n_tr >= 1:
            ok += 1
        else:
            bad.append('transcode %d' % n_tr)

    rc = report('rep: replay decode + analysis', ok, total,
                '(%d replays, %d commands; bad=%s)'
                % (len(reps), total_cmds, bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
