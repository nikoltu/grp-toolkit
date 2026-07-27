"""Oracle for the script-derived mission bot behaviour (tools/ai/mission_bot.py).

The profile is the OBJECTIVE record of what a mission's enemy does, straight from
the AI bytecode - so it must be correct and complete, not merely non-empty:

  1. COVERAGE. Every campaign mission yields a JSON-serialisable profile; the ones
     that run attack scripts produce non-empty attack compositions.
  2. NAMED. Every unit id in builds/trains/attacks resolves to a stat_txt name
     (no 'unit N' fallbacks leaking through) and every attack count is positive.
  3. KNOWN MISSION. terran/terran05 (Revolution, Confederate) attacks with the
     Marine/Vulture/Wraith set; protoss/protoss01 (First Strike, Zerg) with
     Zergling/Hydralisk - the compositions the bytecode actually encodes.

    py test_mission_bot.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report                       # noqa: E402
import mpq                                                # noqa: E402
import tbl                                                # noqa: E402
import ai_bin                                             # noqa: E402
import chk as chk_mod                                     # noqa: E402
import campaign_index                                     # noqa: E402
import chk_ai_links                                       # noqa: E402
import mission_bot                                        # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    tables = chk_ai_links.load_ai_tables(BW)
    ai_files = ai_bin.load_from_chain(ch)

    ok = total = 0
    bad = []

    missions = 0
    json_ok = True
    named_ok = True
    with_attacks = 0
    profiles = {}
    for label, data in campaign_index.find_mpq_campaigns(ch):
        chk = chk_mod.parse(data); chk.fmt_label = label
        prof = mission_bot.mission_behavior(chk, tables, ai_files, uname)
        profiles[label] = prof
        missions += 1
        try:
            json.dumps(prof)
        except Exception:                                  # noqa: BLE001
            json_ok = False
        if prof['attacks']:
            with_attacks += 1
        for grp in ('builds', 'trains', 'attacks'):
            for r in prof[grp]:
                if not r['name'] or r['name'].startswith('unit ') or r['count'] <= 0:
                    named_ok = False

    # 1. coverage
    total += 1
    if missions > 40 and json_ok and with_attacks > 30:
        ok += 1
    else:
        bad.append('missions %d attacks %d json %s' % (missions, with_attacks, json_ok))

    # 2. named + positive counts
    total += 1
    if named_ok:
        ok += 1
    else:
        bad.append('unnamed/zero-count unit in a profile')

    # 3. known missions
    total += 1
    def atk_names(label):
        return {r['name'] for r in profiles.get(label, {}).get('attacks', [])}
    t5 = atk_names('terran/terran05')
    p1 = atk_names('protoss/protoss01')
    if ({'Terran Marine', 'Terran Vulture', 'Terran Wraith'} <= t5
            and {'Zerg Zergling', 'Zerg Hydralisk'} <= p1):
        ok += 1
    else:
        bad.append('t5=%s p1=%s' % (sorted(t5)[:3], sorted(p1)[:3]))

    rc = report('mission_bot: script bot behaviour', ok, total,
                '(%d missions, %d with attacks; bad=%s)'
                % (missions, with_attacks, bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
