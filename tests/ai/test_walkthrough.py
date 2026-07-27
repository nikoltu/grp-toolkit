"""Oracle for the walkthrough cross-reference (tools/ai/walkthrough.py).

The claim is that two INDEPENDENT descriptions of a mission's enemy - the AI
bytecode and a human-written walkthrough - corroborate each other. If they do,
each confirms the other; where they differ, the difference is explainable. This
proves the mechanism and the corroboration:

  1. NORMALISATION. Race prefix + plural stripping makes script and walkthrough
     names comparable ('Zerg Zergling' == 'Zerglings' == 'zergling').
  2. WELL-FORMED. Every curated mission has name/objective/enemy_units/sources,
     and its label resolves to a real campaign mission.
  3. CORROBORATION. Across the curated set, the walkthrough's enemy units are
     overwhelmingly CONFIRMED by the script's attack composition (the oracle: two
     unrelated sources agree). A high confirmed-vs-total ratio, and at least one
     mission fully confirmed.
  4. DISCREPANCIES EXPLAINED. Any walkthrough_only / script_only unit is reported,
     not hidden - the tool surfaces them for a human to judge.

    py test_walkthrough.py
"""
import sys
import os

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
import walkthrough as WT                                  # noqa: E402


def main():
    ok = total = 0
    bad = []
    book = WT.load()

    # 1. normalisation (no install needed)
    total += 1
    n = WT.norm_unit
    if (n('Zerg Zergling') == 'zergling' and n('Zerglings') == 'zergling'
            and n('Terran Siege Tank') == 'siege tank'
            and n('Protoss Dragoon') == n('Dragoons') == 'dragoon'):
        ok += 1
    else:
        bad.append('normalise')

    # 2. well-formed JSON
    total += 1
    wf = True
    for label, e in book['missions'].items():
        if not (e.get('name') and e.get('objective') and e.get('enemy_units')
                and e.get('sources')):
            wf = False
            bad.append('incomplete %s' % label)
    if wf:
        ok += 1

    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    tables = chk_ai_links.load_ai_tables(BW)
    ai_files = ai_bin.load_from_chain(ch)

    profiles = {}
    for label, data in campaign_index.find_mpq_campaigns(ch):
        if label in book['missions']:
            chk = chk_mod.parse(data); chk.fmt_label = label
            profiles[label] = mission_bot.mission_behavior(chk, tables, ai_files, uname)

    # 3. every curated label resolves + corroboration ratio
    total += 1
    resolved = all(lb in profiles for lb in book['missions'])
    confirmed_units = wt_total = fully = 0
    for label in book['missions']:
        x = WT.cross_reference(label, profiles.get(label, {'attacks': []}), book)
        n_conf = len(x['confirmed'])
        n_wt = n_conf + len(x['walkthrough_only'])
        confirmed_units += n_conf
        wt_total += n_wt
        if x['walkthrough_only'] == [] and n_conf > 0:
            fully += 1
    ratio = confirmed_units / wt_total if wt_total else 0
    if resolved and ratio >= 0.8 and fully >= 3:
        ok += 1
    else:
        bad.append('resolved %s ratio %.2f fully %d' % (resolved, ratio, fully))

    # 4. discrepancies are reported (structure present) - terran07 has both kinds
    total += 1
    x7 = WT.cross_reference('terran/terran07',
                            profiles.get('terran/terran07', {'attacks': []}), book)
    if ('script_only' in x7 and 'walkthrough_only' in x7
            and (x7['script_only'] or x7['walkthrough_only'])):
        ok += 1
    else:
        bad.append('discrepancy reporting')

    rc = report('walkthrough: script<->guide xref', ok, total,
                '(%d missions, %d/%d units confirmed; bad=%s)'
                % (len(book['missions']), confirmed_units, wt_total,
                   bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
