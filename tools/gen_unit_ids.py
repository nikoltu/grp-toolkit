"""Build a MEASURED build-order-name -> units.dat id map from the real
stat_txt.tbl (unit name for id = stat_txt[id+1]). Each id is looked up by an
exact 'Race Core' match, so no id is transcribed from memory - it comes from the
install. Emits JSON for embedding in tools + the browser; reports any unresolved
core name and cross-checks every producible row of build_orders.json."""
import sys
import os
import json
import struct
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mpq

ch = mpq.MpqChain(r'C:\Git\Starcraft BroodWar  v1.1.61')
raw = ch.read('rez\\stat_txt.tbl')
n = struct.unpack_from('<H', raw, 0)[0]
names = []
for i in range(1, n + 1):
    o = struct.unpack_from('<H', raw, 2 + (i - 1) * 2)[0]
    e = o
    while e < len(raw) and raw[e]:
        e += 1
    names.append(raw[o:e].decode('latin1', 'replace'))
unit_name = {i: names[i] for i in range(228) if i < len(names)}

# core building/unit names that appear in the 22 build orders (from the cards)
CORES = [
    # Terran buildings / units
    'Barracks', 'Supply Depot', 'Refinery', 'Command Center', 'Factory',
    'Machine Shop', 'Starport', 'Control Tower', 'Bunker', 'Academy',
    'Engineering Bay', 'Marine', 'Firebat', 'Medic', 'Vulture', 'Siege Tank',
    'Goliath', 'Wraith', 'SCV',
    # Protoss
    'Pylon', 'Gateway', 'Assimilator', 'Nexus', 'Forge', 'Photon Cannon',
    'Cybernetics Core', 'Robotics Facility', 'Robotics Support Bay',
    'Observatory', 'Citadel of Adun', 'Templar Archives', 'Zealot', 'Dragoon',
    'Dark Templar', 'Reaver', 'Observer', 'Shuttle', 'Probe',
    # Zerg
    'Hatchery', 'Lair', 'Spawning Pool', 'Extractor', 'Evolution Chamber',
    'Hydralisk Den', 'Spire', 'Sunken Colony', 'Creep Colony', 'Drone',
    'Overlord', 'Zergling', 'Hydralisk', 'Mutalisk', 'Scourge',
]

# whether each core is a producible unit (train) or a building (build)
BUILDINGS = {
    'Barracks', 'Supply Depot', 'Refinery', 'Command Center', 'Factory',
    'Machine Shop', 'Starport', 'Control Tower', 'Bunker', 'Academy',
    'Engineering Bay', 'Pylon', 'Gateway', 'Assimilator', 'Nexus', 'Forge',
    'Photon Cannon', 'Cybernetics Core', 'Robotics Facility',
    'Robotics Support Bay', 'Observatory', 'Citadel of Adun', 'Templar Archives',
    'Hatchery', 'Lair', 'Spawning Pool', 'Extractor', 'Evolution Chamber',
    'Hydralisk Den', 'Spire', 'Sunken Colony', 'Creep Colony',
}

id_by_name = {i: unit_name[i] for i in unit_name}
name_map = {}
unresolved = []
for core in CORES:
    hit = None
    for i, nm in id_by_name.items():
        if nm in ('Terran ' + core, 'Protoss ' + core, 'Zerg ' + core):
            hit = i
            break
    if hit is None:
        unresolved.append(core)
    else:
        name_map[core] = {'id': hit, 'kind': 'building' if core in BUILDINGS
                          else 'unit', 'full': id_by_name[hit]}

print('resolved %d/%d cores' % (len(name_map), len(CORES)))
if unresolved:
    print('UNRESOLVED:', unresolved)

# cross-check: every producible (action=false, non-upgrade) build row resolves
bo = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'assets',
                                 'build_orders.json'), encoding='utf-8'))
UPGRADE_KW = re.compile(r'\b(range|speed|mode|mines?|pack|upgrade|carapace|'
                        r'attack|maelstrom)\b', re.I)
LEAD = re.compile(r'^(pump\s+|save\s+larvae\s*|natural\s+|take\s+|add\s+|'
                  r'extra\s+|1st\s+|2nd\s+|3rd\s+|\d+[-\dx]*\s+|\+\d+\s+)', re.I)
SUFFIX = re.compile(r'\s+(at\s+.*|when\s+.*|if\s+.*|\d+)$', re.I)
ALIAS = {'Cannon': 'Photon Cannon', 'Cannons': 'Photon Cannon'}


def normalize(nm):
    s = nm.strip()
    while True:                              # peel repeated leading tokens
        t = LEAD.sub('', s)
        if t == s:
            break
        s = t
    s = s.split('/')[0].strip()              # "Marine/Medic" -> "Marine"
    s = SUFFIX.sub('', s).strip()
    if s.endswith('ies'):
        s = s[:-3] + 'y'                     # Colonies -> Colony
    elif s.endswith('s') and s[:-1] in name_map:
        s = s[:-1]                           # Marines -> Marine
    s = ALIAS.get(s, s)
    if s.endswith('s') and s[:-1] in name_map:
        s = s[:-1]
    return s


unmatched_rows = set()
matched = 0
for b in bo['build_orders']:
    for row in b['build']:
        if row['action']:
            continue
        raw_nm = row['name']
        if UPGRADE_KW.search(raw_nm):
            continue                      # upgrade/tech: shown, not compiled
        core = normalize(raw_nm)
        if core in name_map:
            matched += 1
        else:
            unmatched_rows.add(raw_nm)

print('producible rows matched:', matched)
if unmatched_rows:
    print('rows not matched (shown-only in bot):')
    for r in sorted(unmatched_rows):
        print('   ', repr(r))

out = os.path.join(os.path.dirname(__file__), '..', 'assets', 'unit_ids.json')
json.dump({'_source': 'stat_txt.tbl (BW 1.16.1), measured; id = stat_txt[id+1]',
           'names': {k: v['id'] for k, v in name_map.items()},
           'kinds': {k: v['kind'] for k, v in name_map.items()}},
          open(out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print('wrote', out)
