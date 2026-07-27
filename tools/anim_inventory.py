#!/usr/bin/env python3
"""HD asset inventory + validator - scan every .anim in an SC:R CASC install and
map the full space of ANIM variations the HD engine must handle.

For each `.anim` it records the tier (SD/HD2/HD from the scale byte), type, layer
count + layer-name set, entry count, DXT formats used, whether any entry shares
another file's texture (refId != 0xffff), and the diffuse-atlas resolution. It
then aggregates the distributions and FLAGS anomalies: a structurally out-of-
bounds file, a non-standard layer set, an unusual layer/entry count. The point is
robustness - the engine sees not just the common case (7-layer HD2) but every
variant present, so nothing surprises it at runtime.

    py anim_inventory.py [SCR_DIR] [--json out.json] [--limit N]

Uses tools/anim.py (independent reader) + tools/casc.py. No DXT pixel decode.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casc
import anim

# the canonical HD layer set (CLAUDE.md 4)
STD_LAYERS = ('diffuse', 'bright', 'teamcolor', 'emissive', 'normal',
              'specular', 'ao_depth')


def scan(storage, names, limit=None):
    """Parse every name; return (records, aggregate). records is a list of dicts
    (small), aggregate is the distribution + anomaly report."""
    by_tier = Counter()
    by_type = Counter()
    by_layercount = Counter()
    by_entrycount = Counter()
    layer_sets = Counter()
    dxt_use = Counter()
    resolutions = Counter()
    shared = 0
    ok = 0
    anomalies = []
    records = []
    scanned = 0

    for name in names:
        if limit and scanned >= limit:
            break
        scanned += 1
        try:
            a = anim.parse(storage.read_name(name))
        except Exception as e:                       # noqa: BLE001
            anomalies.append((name, 'parse error: %s' % e))
            continue
        by_tier[a.tier] += 1
        by_type[a.type] += 1
        by_layercount[a.layer_count] += 1
        by_entrycount[a.entry_count] += 1
        lset = tuple(a.layers)
        layer_sets[lset] += 1
        for t in a.texrefs:
            if t.dxt:
                dxt_use[t.dxt] += 1
        res = (a.texrefs[0].w, a.texrefs[0].h) if a.texrefs else (0, 0)
        resolutions[res] += 1
        any_shared = any(e.shared for e in a.entries)
        if any_shared:
            shared += 1
        if a.ok:
            ok += 1
        else:
            anomalies.append((name, 'structural layout out of bounds'))
        # non-standard layer set (only flag the ones that decode ok)
        if a.ok and tuple(a.layers) != STD_LAYERS and a.layer_count == 7:
            anomalies.append((name, 'non-standard 7-layer names: %s' % (a.layers,)))
        records.append({'name': name, 'tier': a.tier, 'type': a.type,
                        'layers': a.layer_count, 'entries': a.entry_count,
                        'dxt': a.dxt_formats, 'shared': any_shared,
                        'res': list(res), 'ok': a.ok})

    agg = {'scanned': scanned, 'ok': ok, 'shared': shared,
           'by_tier': dict(by_tier), 'by_type': dict(by_type),
           'by_layer_count': dict(by_layercount),
           'by_entry_count': dict(by_entrycount),
           'dxt_use': dict(dxt_use),
           'distinct_layer_sets': len(layer_sets),
           'top_layer_sets': layer_sets.most_common(3),
           'distinct_resolutions': len(resolutions),
           'top_resolutions': resolutions.most_common(6),
           'anomalies': anomalies}
    return records, agg


def anim_names(storage):
    return sorted(n for n in storage.root.keys() if n.endswith('.anim'))


def main():
    ap = argparse.ArgumentParser(description='SC:R HD .anim inventory + validator')
    ap.add_argument('scr', nargs='?', default=r'C:\Git\StarCraft Remastered')
    ap.add_argument('--json', help='write full per-file records to this JSON')
    ap.add_argument('--limit', type=int, help='scan only the first N (quick look)')
    args = ap.parse_args()

    st = casc.NamedStorage(os.path.join(args.scr, 'data', 'data'),
                           install_root=args.scr)
    names = anim_names(st)
    print('scanning %d .anim files...' % len(names))
    records, agg = scan(st, names, args.limit)

    print('\n== HD ANIM inventory ==')
    print('scanned %d, parsed ok %d, texture-sharing (refId) %d'
          % (agg['scanned'], agg['ok'], agg['shared']))
    print('tier      :', agg['by_tier'])
    print('type      :', agg['by_type'])
    print('layers    :', agg['by_layer_count'])
    print('entries   :', agg['by_entry_count'])
    print('dxt (per layer):', agg['dxt_use'])
    print('distinct layer sets:', agg['distinct_layer_sets'])
    for lset, n in agg['top_layer_sets']:
        print('   %4d x %s' % (n, list(lset)))
    print('distinct atlas resolutions:', agg['distinct_resolutions'])
    for res, n in agg['top_resolutions']:
        print('   %4d x %dx%d' % (n, res[0], res[1]))
    print('anomalies : %d' % len(agg['anomalies']))
    for name, why in agg['anomalies'][:12]:
        print('   %s  -- %s' % (name, why))

    if args.json:
        json.dump({'aggregate': agg, 'records': records},
                  open(args.json, 'w', encoding='utf-8'), indent=1)
        print('wrote', args.json)


if __name__ == '__main__':
    main()
