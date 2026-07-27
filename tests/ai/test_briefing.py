"""Oracle for the mission-briefing analyzer (chk.py MBRF + briefing.py).

Runs the analyzer over every campaign mission the MPQ carries and requires the
briefing timeline to be well-formed - the byte-derived reference an engine port
diffs its briefing playback against:

  1. COVERAGE. Campaign missions parse and most carry an MBRF briefing.
  2. TRANSMISSIONS. Every spoken line (Transmission) resolves to a non-empty
     text AND a .wav AND a positive duration (ms) - a wrong action-field offset
     would give empty strings or zero times.
  3. SPEAKERS. Each transmission is attributed to a portrait unit that resolves
     to a name via stat_txt, and at least one hero speaker (a person, e.g. a unit
     whose name contains a space and no 'Terran/Zerg/Protoss' prefix) appears -
     proving the ShowPortrait unit field is read correctly.

    py test_briefing.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import tbl                               # noqa: E402
import chk as chk_mod                    # noqa: E402
import briefing                          # noqa: E402
import campaign_index                    # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))

    def uname(uid):
        return stat.text(uid) or ('unit %d' % uid)

    ok = total = 0
    bad = []

    missions_with_brief = 0
    n_transmissions = 0
    malformed = 0
    speakers = set()
    parsed = 0
    for path in campaign_index.campaign_chk_names():
        try:
            data = ch.read(path)
        except Exception:                            # noqa: BLE001
            continue
        parsed += 1
        chk = chk_mod.parse(data)
        briefs = briefing.analyze(chk, uname)
        got_line = False
        for b in briefs:
            for e in b['events']:
                if e['action'] != 'Transmission':
                    continue
                got_line = True
                n_transmissions += 1
                if not (e.get('text') and e.get('wav') and e.get('dur_ms', 0) > 0):
                    malformed += 1
                if e.get('speaker_name'):
                    speakers.add(e['speaker_name'])
        if got_line:
            missions_with_brief += 1

    # 1. coverage
    total += 1
    if parsed > 20 and missions_with_brief > 10:
        ok += 1
    else:
        bad.append('parsed %d, with-brief %d' % (parsed, missions_with_brief))

    # 2. every transmission well-formed
    total += 1
    if n_transmissions > 50 and malformed == 0:
        ok += 1
    else:
        bad.append('%d/%d transmissions malformed' % (malformed, n_transmissions))

    # 3. hero speakers resolve (a named person, not a generic unit)
    total += 1
    heroes = [s for s in speakers
              if ' ' in s and not s.split()[0] in ('Terran', 'Zerg', 'Protoss')]
    if heroes:
        ok += 1
    else:
        bad.append('no hero speakers among %s' % sorted(speakers)[:4])

    rc = report('briefing: campaign MBRF timeline', ok, total,
                '(%d missions, %d with briefing, %d lines, %d speakers; heroes=%s; bad=%s)'
                % (parsed, missions_with_brief, n_transmissions, len(speakers),
                   sorted(heroes)[:3], bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
