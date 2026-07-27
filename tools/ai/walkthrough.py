#!/usr/bin/env python3
"""Cross-reference a mission's AI-script attack composition against a curated
community walkthrough (assets/campaign_walkthroughs.json).

Two independent descriptions of the same enemy: the bytecode (what the AI is
programmed to attack with, tools/ai/mission_bot.py - objective) and a human
walkthrough (what a player observed and wrote down - curated facts, attributed).
Cross-referencing them:
  * CONFIRMS the script analysis where both agree (a real oracle - two unrelated
    sources landing on the same unit set),
  * SURFACES discrepancies that are themselves informative: a `walkthrough_only`
    unit that the AI never attacks with is usually trigger-spawned or purely
    defensive (not run by an attack script); a `script_only` unit is one the AI
    fields that a terse walkthrough glossed over.

FACTS ONLY: the JSON holds enemy faction / unit types / attack pattern /
objective + source URLs, never walkthrough prose. Names are normalised (race
prefix and trailing plural stripped) so "Zerg Zergling" (script) matches
"Zerglings" (walkthrough).

No third-party libraries.
"""
import os
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON = os.path.join(_HERE, '..', '..', 'assets', 'campaign_walkthroughs.json')
_RACES = ('zerg ', 'terran ', 'protoss ')


def load(path=DEFAULT_JSON):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def norm_unit(name):
    """'Zerg Zergling' / 'Zerglings' -> 'zergling'; 'Terran Siege Tank' -> 'siege tank'."""
    s = name.strip().lower()
    for r in _RACES:
        if s.startswith(r):
            s = s[len(r):]
            break
    if s.endswith('s') and not s.endswith('ss'):
        s = s[:-1]
    return s


def cross_reference(mission_label, script_profile, book=None):
    """Compare mission_bot's profile (its 'attacks' list) to the walkthrough.

    Returns a dict: has_walkthrough, and if present name/objective/enemy_factions/
    attack_pattern/sources plus confirmed/script_only/walkthrough_only unit lists.
    """
    book = book if book is not None else load()
    entry = book.get('missions', {}).get(mission_label)
    script_units = {norm_unit(r['name']): r['name'] for r in script_profile.get('attacks', [])}
    if not entry:
        return {'has_walkthrough': False,
                'script_attack_units': sorted(script_units.values())}
    wt_units = {norm_unit(u): u for u in entry.get('enemy_units', [])}
    s, w = set(script_units), set(wt_units)
    return {
        'has_walkthrough': True,
        'name': entry.get('name'),
        'objective': entry.get('objective'),
        'enemy_factions': entry.get('enemy_factions', []),
        'attack_pattern': entry.get('attack_pattern'),
        'sources': entry.get('sources', []),
        'confirmed': sorted(script_units[u] for u in (s & w)),
        'script_only': sorted(script_units[u] for u in (s - w)),
        'walkthrough_only': sorted(wt_units[u] for u in (w - s)),
    }


if __name__ == '__main__':
    import sys
    sys.path.insert(0, _HERE)
    sys.path.insert(0, os.path.join(_HERE, '..'))
    import mpq
    import tbl
    import ai_bin
    import chk as chk_mod
    import campaign_index
    import chk_ai_links
    import mission_bot
    bw = sys.argv[1] if len(sys.argv) > 1 else r'C:\Git\Starcraft BroodWar  v1.1.61'
    ch = mpq.MpqChain(bw)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))
    uname = lambda u: stat.text(u) or ('unit %d' % u)      # noqa: E731
    tables = chk_ai_links.load_ai_tables(bw)
    ai_files = ai_bin.load_from_chain(ch)
    book = load()
    for label, data in campaign_index.find_mpq_campaigns(ch):
        if label not in book['missions']:
            continue
        chk = chk_mod.parse(data); chk.fmt_label = label
        prof = mission_bot.mission_behavior(chk, tables, ai_files, uname)
        x = cross_reference(label, prof, book)
        print('=== %s (%s) ===' % (x['name'], label))
        print('  objective :', x['objective'])
        print('  factions  :', ', '.join(x['enemy_factions']))
        print('  CONFIRMED :', ', '.join(x['confirmed']) or '-')
        print('  script>wt :', ', '.join(x['script_only']) or '-')
        print('  wt>script :', ', '.join(x['walkthrough_only']) or '-')
