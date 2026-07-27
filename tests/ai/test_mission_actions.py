"""Oracle for the mission unit-command classifier (mission_actions.py).

Classifies every campaign mission's TRIG actions into per-unit commands and
requires them to be well-formed - the byte-derived reference an engine diffs its
trigger interpretation against:

  1. COVERAGE. Missions parse and yield unit commands in bulk.
  2. ORDERS. Order actions decode to the three real order types (Move / Patrol /
     Attack), all present across the campaign - a wrong order-type byte would
     leave one missing or produce junk types.
  3. FIELDS. Every command's unit resolves to a name; Order/Move targets resolve
     to real MRGN locations (a wrong field offset would give empty/garbage).

    py test_mission_actions.py
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
import mission_actions as MA             # noqa: E402
import campaign_index                    # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)   # noqa: E731

    ok = total = 0
    bad = []

    n_cmd = 0
    order_types = set()
    bad_unit = 0
    bad_target = 0
    missions = 0
    for path in campaign_index.campaign_chk_names():
        try:
            data = ch.read(path)
        except Exception:                            # noqa: BLE001
            continue
        missions += 1
        chk = chk_mod.parse(data)
        for r in MA.classify(chk, uname):
            n_cmd += 1
            if not r['unit_name']:
                bad_unit += 1
            if r['kind'] == 'order':
                order_types.add(r['order'])
                if not r['target_loc_name'] and r['target_loc']:
                    bad_target += 1

    # 1. coverage
    total += 1
    if missions > 20 and n_cmd > 500:
        ok += 1
    else:
        bad.append('missions %d cmds %d' % (missions, n_cmd))

    # 2. all three order types decode
    total += 1
    if {'Move', 'Patrol', 'Attack'} <= order_types:
        ok += 1
    else:
        bad.append('order types %s' % sorted(order_types))

    # 3. units + order targets resolve
    total += 1
    if bad_unit == 0 and bad_target == 0:
        ok += 1
    else:
        bad.append('%d bad units, %d bad targets' % (bad_unit, bad_target))

    rc = report('mission: unit-command classify', ok, total,
                '(%d missions, %d commands, orders=%s; bad=%s)'
                % (missions, n_cmd, sorted(order_types), bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
