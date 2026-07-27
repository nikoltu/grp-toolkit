#!/usr/bin/env python3
"""AIML - AI Mission Link. Extracts, from a campaign map's CHK triggers, every
"Run AI Script [At Location]" action and resolves it into a neutral record:

    mission, trigger_index, players[], script_id (FourCC), source (which .bin),
    location_id, location_name, action ('run' | 'run_at_location').

Cross-checks each script id against the aiscript.bin / bwscript.bin tables
(ai_bin). That resolution is the linkage oracle: a campaign that references a
script id absent from both tables would mean a wrong FourCC field or endianness.
Measured 2026-07 on (1)Enslavers01.scm: 6 AI actions, 6/6 resolve.
"""
from dataclasses import dataclass, field, asdict

import chk as chkmod


@dataclass
class AiLink:
    mission: str
    trigger_index: int
    players: list
    action: str                  # 'run' | 'run_at_location'
    script_id: str
    location_id: int
    location_name: str
    source: str = ''             # 'aiscript.bin' | 'bwscript.bin' | '' (unresolved)
    resolved: bool = False


def extract_links(chk, mission, ai_tables=None):
    """ai_tables: {'aiscript.bin': AiScriptFile, 'bwscript.bin': ...} or None.
    Returns list[AiLink]."""
    by_id = {}
    if ai_tables:
        for src, f in ai_tables.items():
            for fid in f.by_id():
                by_id.setdefault(fid, src)     # aiscript first if both present
    links = []
    for tr in chk.triggers:
        for a in tr.actions:
            if not a.is_ai_script:
                continue
            sid = a.script_id
            src = by_id.get(sid, '')
            links.append(AiLink(
                mission=mission, trigger_index=tr.index, players=list(tr.players),
                action=('run_at_location' if a.action_id == 16 else 'run'),
                script_id=sid, location_id=a.location,
                location_name=chk.location_name(a.location),
                source=src, resolved=bool(src)))
    return links


def links_to_json(links):
    return [asdict(l) for l in links]


def load_ai_tables(bw_dir):
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import ai_bin
    return ai_bin.load_from_chain(mpq.MpqChain(bw_dir))


if __name__ == '__main__':
    import sys
    import os
    bw = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    mappath = sys.argv[2] if len(sys.argv) > 2 \
        else os.path.join(bw, 'maps', 'campaign', '(1)Enslavers01.scm')
    tables = load_ai_tables(bw)
    chk = chkmod.read_scm(mappath)
    links = extract_links(chk, os.path.basename(mappath), tables)
    ok = sum(1 for l in links if l.resolved)
    print('%s: %d AI-script links, %d/%d resolve in the script table'
          % (os.path.basename(mappath), len(links), ok, len(links)))
    for l in links:
        print('  P%s  %-16s %-6s @%d %-14s [%s]'
              % (l.players, l.script_id, l.action, l.location_id,
                 l.location_name, l.source or 'UNRESOLVED'))
