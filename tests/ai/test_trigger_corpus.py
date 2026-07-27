"""Oracle for the campaign trigger corpus (tools/ai/trigger_corpus.py + chk.py
conditions).

The Revolution control-transfer finding came from reading a mission's whole
trigger set; this proves the toolkit can do that for the ENTIRE campaign, with no
gaps - the CHK analogue of the AI-disasm coverage oracle:

  1. COVERAGE. Over every campaign mission, every trigger's conditions and actions
     resolve to a KNOWN type - 0 unknown condition-type bytes and 0 unknown
     action ids across ~1850 triggers / ~2767 conditions / ~9666 actions. A wrong
     offset or a missing table entry would surface as an unknown type.
  2. VOCABULARY. The campaign uses the expected condition set (Bring / Switch /
     Command / CountdownTimer / ElapsedTime dominate) and action set (SetSwitch /
     CreateUnit(WithProperties) / RunAIScript / GiveUnits / Victory / Defeat present).
  3. RESOLUTION. Every condition and action of a real mission (Revolution) renders
     to a non-empty description, and the known mechanic is visible: a Defeat
     trigger, RunAIScript actions, and no GiveUnits (control transfer is rescue,
     confirmed elsewhere).
  4. DETERMINISM. The survey is identical across runs.

    py test_trigger_corpus.py
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
import chk as chkmod                                      # noqa: E402
import campaign_index                                     # noqa: E402
import trigger_corpus as TC                               # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731

    def missions():
        for label, data in campaign_index.find_mpq_campaigns(ch):
            yield label, chkmod.parse(data)

    ok = total = 0
    bad = []

    s = TC.survey(missions(), uname)

    # 1. coverage: 0 unknown types, sane counts
    total += 1
    if (s['missions'] > 40 and s['triggers'] > 1500 and s['conditions'] > 2000
            and s['actions'] > 8000 and not s['unknown_condition_types']
            and not s['unknown_action_ids']):
        ok += 1
    else:
        bad.append('counts m%d t%d unkC%s unkA%s' % (s['missions'], s['triggers'],
                   s['unknown_condition_types'], s['unknown_action_ids']))

    # 2. vocabulary present
    total += 1
    ct = set(s['condition_types'])
    at = set(s['action_types'])
    if ({'Bring', 'Switch', 'Command', 'CountdownTimer'} <= ct
            and {'SetSwitch', 'CreateUnitWithProperties', 'RunAIScriptAtLocation',
                 'GiveUnitstoPlayer', 'Victory', 'Defeat'} <= at):
        ok += 1
    else:
        bad.append('vocab C%s A%s' % (sorted(ct)[:4], sorted(at)[:4]))

    # 3. resolution on a real mission (Revolution)
    total += 1
    rev = None
    for label, chk in missions():
        if label == 'terran/terran05':
            rev = TC.mission_triggers(chk, uname)
            break
    res_ok = False
    if rev:
        all_rendered = all(c for t in rev for c in t['conditions']) and \
            all(a for t in rev for a in t['actions'])
        has_defeat = any('Defeat' in a for t in rev for a in t['actions'])
        has_ai = any(a.startswith('RunAIScript') for t in rev for a in t['actions'])
        no_give = not any('GiveUnits' in a for t in rev for a in t['actions'])
        res_ok = all_rendered and has_defeat and has_ai and no_give
    if res_ok:
        ok += 1
    else:
        bad.append('revolution resolution')

    # 4. determinism
    total += 1
    s2 = TC.survey(missions(), uname)
    if json.dumps(s, sort_keys=True) == json.dumps(s2, sort_keys=True):
        ok += 1
    else:
        bad.append('nondeterministic')

    rc = report('trigger corpus: full campaign', ok, total,
                '(%d missions, %d triggers, %d cond types, %d act types; bad=%s)'
                % (s['missions'], s['triggers'], len(s['condition_types']),
                   len(s['action_types']), bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
