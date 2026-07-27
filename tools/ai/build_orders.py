#!/usr/bin/env python3
"""Compile a pro build-order card (assets/build_orders.json) into a training-bot
aiscript via ai_gen. The Python twin of the browser's Botų kūrėjas library.

The build order is a HUMAN execution plan in supply-count terms. The aiscript VM
has no "at supply N" gate, so this maps the ORDER: each producible row becomes a
build (buildings) or train (units) with a target count, and upgrades/actions are
dropped (the town-management AI and the human timing they encode are out of the
VM's reach). Building/unit ids come from the MEASURED name->id map
(assets/unit_ids.json, cut from stat_txt.tbl - see tools/gen_unit_ids.py), so the
emitted ids are real. The result is an approximation of the build order that
COMPILES CLEAN - which tests/ai/test_build_orders.py verifies for all 22 cards,
the same guarantee the browser twin shows.
"""
import json
import os
import re

from ai_gen import Tactic, build_bin

_HERE = os.path.dirname(os.path.abspath(__file__))
_ASSETS = os.path.join(_HERE, '..', '..', 'assets')

_UPG = re.compile(r'\b(range|speed|mode|mines?|pack|upgrade|carapace|attack|'
                  r'maelstrom)\b', re.I)
_LEAD = re.compile(r'^(pump\s+|save\s+larvae\s*|natural\s+|take\s+|add\s+|'
                   r'extra\s+|1st\s+|2nd\s+|3rd\s+|\d+[-\dx]*\s+|\+\d+\s+)', re.I)
_SUF = re.compile(r'\s+(at\s+.*|when\s+.*|if\s+.*|\d+)$', re.I)
_ALIAS = {'Cannon': 'Photon Cannon', 'Cannons': 'Photon Cannon'}
_NONARMY = {'SCV', 'Probe', 'Drone', 'Overlord'}


def load():
    bo = json.load(open(os.path.join(_ASSETS, 'build_orders.json'),
                        encoding='utf-8'))['build_orders']
    ids = json.load(open(os.path.join(_ASSETS, 'unit_ids.json'),
                         encoding='utf-8'))
    return bo, ids['names'], ids['kinds']


def normalize(nm, names):
    """Reduce a build-row label to a core unit/building name (mirror of the JS
    boNormalize + tools/gen_unit_ids.py)."""
    s = nm.strip()
    while True:
        t = _LEAD.sub('', s)
        if t == s:
            break
        s = t
    s = s.split('/')[0].strip()
    s = _SUF.sub('', s).strip()
    if s.endswith('ies'):
        s = s[:-3] + 'y'
    elif s.endswith('s') and s[:-1] in names:
        s = s[:-1]
    s = _ALIAS.get(s, s)
    if s.endswith('s') and s[:-1] in names:
        s = s[:-1]
    return s


def _count(nm):
    if re.match(r'^pump', nm, re.I):
        return 20
    m = re.match(r'^(\d+)(?:-(\d+|x))?', nm, re.I)
    if m:
        return int(m.group(2)) if (m.group(2) and m.group(2).isdigit()) \
            else int(m.group(1))
    return 1


def fourcc(bo):
    return (bo['race'] + re.sub(r'[^A-Za-z0-9]', '', bo['name']))[:4].ljust(4, '0')


def to_tactic(bo, names, kinds):
    """Build order -> ai_gen.Tactic (buildings->build, units->train, upgrades/
    actions dropped)."""
    t = Tactic(fourcc(bo))
    t.setup(farms='timing', transports=False)
    bcount, tcount, army = {}, {}, []
    for row in bo['build']:
        if row['action'] or _UPG.search(row['name']):
            continue
        core = normalize(row['name'], names)
        if core not in names:
            continue
        uid, kind = names[core], kinds[core]
        c = max(1, _count(row['name']))
        if kind == 'building':
            bcount[uid] = bcount.get(uid, 0) + c
            t.build(bcount[uid], uid, 100)
        else:
            tcount[uid] = max(tcount.get(uid, 0), c)
            if core not in _NONARMY and uid not in army:
                army.append(uid)
            t.train(tcount[uid], uid)
    t.label('main')
    if army:
        t.attack_wave([(12, a) for a in army])
    t.wait(600)
    t.goto('main')
    return t


def compile_bot(bo, names, kinds):
    """Build order -> standalone aiscript.bin bytes (one script)."""
    return build_bin([to_tactic(bo, names, kinds)])


if __name__ == '__main__':
    import sys
    sys.path.insert(0, _HERE)
    import ai_bin
    import ai_disasm
    bos, names, kinds = load()
    ok = 0
    for bo in bos:
        data = compile_bot(bo, names, kinds)
        f = ai_bin.parse(data, ai_bin.AISCRIPT)
        clean, info = ai_disasm.coverage(f)
        ok += clean
        print('%-42s %s  %d instr'
              % (bo['id'], 'CLEAN' if clean else 'DESYNC',
                 info.get('n_instructions', 0)))
    print('%d/%d clean' % (ok, len(bos)))
