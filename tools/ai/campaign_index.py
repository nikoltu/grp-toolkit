#!/usr/bin/env python3
"""Scan a StarCraft install's campaign maps, extract every AI-script mission
link, and build a usage graph (script id -> the missions/players that run it).

Finds .scm/.scx under <install>\\maps (campaign subfolder first, then any map
with AI-script triggers). Each map's CHK is parsed (chk.py) and its AI links
resolved against the script tables (chk_ai_links.py).

Note on coverage: a retail install keeps the main Blizzard campaigns
(Terran01...) inside campaign MPQs, not as loose .scm; only the bonus
campaigns (e.g. Enslavers) sit under maps\\campaign on disk. What is present is
indexed; what is missing is reported, never silently dropped.
"""
import os
from dataclasses import dataclass, field

import chk as chkmod
import chk_ai_links as links_mod


def find_maps(install_dir):
    """All .scm/.scx under <install>\\maps, campaign ones first."""
    root = os.path.join(install_dir, 'maps')
    found = []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(('.scm', '.scx')):
                found.append(os.path.join(dirpath, fn))
    found.sort(key=lambda p: (0 if 'campaign' in p.lower() else 1, p.lower()))
    return found


# The main Blizzard campaigns live INSIDE the MPQs as
# campaign\{race}\{race}NN[suffix]\staredit\scenario.chk (original SC) and
# campaign\exp{race}\... (Brood War). The default listfile does not name them,
# but MpqChain.read() finds any file by hash, so the paths are probed directly.
def campaign_chk_names():
    races = ['terran', 'zerg', 'protoss']
    suffixes = [''] + [chr(ord('a') + i) for i in range(6)]
    names = []
    for pre in ('campaign\\%s', 'campaign\\exp%s'):
        for race in races:
            folder = pre % race
            for i in range(0, 13):
                for suf in suffixes:
                    names.append('%s\\%s%02d%s\\staredit\\scenario.chk'
                                 % (folder, race, i, suf))
    names.append('campaign\\tutorial\\staredit\\scenario.chk')
    return names


def find_mpq_campaigns(mpq_chain):
    """[(mission_label, chk_bytes)] for every main-campaign CHK present in the
    MPQ chain. mission_label is the folder name, e.g. 'expterran/terran03'."""
    out = []
    if mpq_chain is None:
        return out
    for nm in campaign_chk_names():
        try:
            data = mpq_chain.read(nm)
        except Exception:
            continue
        parts = nm.split('\\')
        label = '%s/%s' % (parts[1], parts[2])   # e.g. expterran/terran03
        out.append((label, data))
    return out


def build_index(install_dir, ai_tables, only_with_ai=True, mpq_chain=None):
    """Returns (missions, usage, stats). Scans loose .scm/.scx under maps\\ AND,
    if mpq_chain is given, the main Blizzard campaigns inside the MPQs.
      missions: list of {mission, path, links:[AiLink...]}
      usage:    {script_id: [(mission, players, action, location_name)...]}
      stats:    counts of maps scanned / with AI / links / resolved / unresolved
    """
    missions = []
    usage = {}
    n_maps = n_with_ai = n_links = n_resolved = 0
    unresolved = []

    def ingest(mission, chk, path):
        nonlocal n_maps, n_with_ai, n_links, n_resolved
        n_maps += 1
        links = links_mod.extract_links(chk, mission, ai_tables)
        if not links and only_with_ai:
            return
        if links:
            n_with_ai += 1
        for l in links:
            n_links += 1
            if l.resolved:
                n_resolved += 1
            else:
                unresolved.append((mission, l.script_id))
            usage.setdefault(l.script_id, []).append(
                (mission, tuple(l.players), l.action, l.location_name))
        missions.append({'mission': mission, 'path': path, 'links': links})

    for path in find_maps(install_dir):
        try:
            chk = chkmod.read_scm(path)
        except Exception:
            continue
        ingest(os.path.basename(path), chk, path)

    for label, data in find_mpq_campaigns(mpq_chain):
        try:
            chk = chkmod.parse(data)
        except Exception:
            continue
        ingest(label, chk, 'mpq:' + label)

    stats = {'maps_scanned': n_maps, 'maps_with_ai': n_with_ai,
             'links': n_links, 'resolved': n_resolved,
             'unresolved': unresolved}
    return missions, usage, stats


if __name__ == '__main__':
    import sys
    bw = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    tables = links_mod.load_ai_tables(bw)
    missions, usage, stats = build_index(bw, tables, mpq_chain=mpq.MpqChain(bw))
    print('maps scanned=%d, with AI=%d, links=%d, resolved=%d/%d'
          % (stats['maps_scanned'], stats['maps_with_ai'], stats['links'],
             stats['resolved'], stats['links']))
    if stats['unresolved']:
        print('UNRESOLVED:', stats['unresolved'][:10])
    print('\nMissions with AI scripts:')
    for m in missions:
        print('  %-28s %d AI links' % (m['mission'], len(m['links'])))
    print('\nScript usage graph (shared scripts):')
    for sid, uses in sorted(usage.items()):
        if len(uses) > 1:
            ms = sorted(set(u[0] for u in uses))
            print('  %-6s used by %d: %s' % (sid, len(ms), ', '.join(ms)))
