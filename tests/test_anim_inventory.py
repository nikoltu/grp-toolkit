"""Oracle for the HD ANIM reader + inventory (tools/anim.py, anim_inventory.py).

Scans every .anim in the SC:R CASC install and asserts the measured facts an HD
engine relies on - and, just as importantly, that the reader parses the WHOLE
corpus (a wrong field offset would desync and either crash or mis-tier a file):

  1. COVERAGE. Every .anim parses; the reader never errors on a real file.
  2. TIERS. Both HD (scale 4) and HD2 (scale 2) are present in bulk (the engine
     ships paired tiers); the scale byte -> tier mapping holds.
  3. STANDARD SHAPE. The canonical 7-layer set
     (diffuse/bright/teamcolor/emissive/normal/specular/ao_depth) dominates, and
     the DXT formats are the expected DXT1/DXT5.
  4. EDGE CASES SURFACED. The inventory captures the non-7-layer files and the
     entry-count outliers (this is the robustness point: the engine must handle
     them, so the tool must find them).

Skipped if the SC:R install is absent.

    py test_anim_inventory.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import SCR, CASC_DATA, need, report      # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import casc                                           # noqa: E402
import anim_inventory as INV                          # noqa: E402
from anim import SCALE_NAME                           # noqa: E402


def main():
    need(CASC_DATA, 'SC:R CASC data')
    st = casc.NamedStorage(CASC_DATA, install_root=SCR)
    names = INV.anim_names(st)
    records, agg = INV.scan(st, names)

    ok = total = 0
    bad = []

    # 1. full parse coverage (no reader errors on any real file)
    total += 1
    parse_errors = [w for _, w in agg['anomalies'] if 'parse error' in w]
    if agg['scanned'] == len(names) and not parse_errors and len(names) > 500:
        ok += 1
    else:
        bad.append('%d parse errors / %d' % (len(parse_errors), agg['scanned']))

    # 2. both tiers present in bulk; scale->tier mapping is the documented one
    total += 1
    t = agg['by_tier']
    if t.get('HD', 0) > 500 and t.get('HD2', 0) > 500 \
            and set(SCALE_NAME.values()) >= {'SD', 'HD2', 'HD'}:
        ok += 1
    else:
        bad.append('tiers: %s' % t)

    # 3. standard 7-layer set dominates; DXT formats are DXT1/DXT5
    total += 1
    top_set, top_n = agg['top_layer_sets'][0]
    std = tuple(INV.STD_LAYERS)
    dxt_ok = set(agg['dxt_use']) <= {'DXT1', 'DXT3', 'DXT5'} and agg['dxt_use']
    if tuple(top_set) == std and top_n > 1000 and dxt_ok:
        ok += 1
    else:
        bad.append('top layer set %s x%d; dxt %s'
                   % (list(top_set), top_n, agg['dxt_use']))

    # 4. the inventory surfaces variation (not everything is 7-layer/1-entry)
    total += 1
    lc = agg['by_layer_count']
    ec = agg['by_entry_count']
    if len(lc) > 1 and len(ec) > 1:      # edge-case layer counts / entry counts exist and were captured
        ok += 1
    else:
        bad.append('no variation captured (lc=%s ec=%s)' % (lc, ec))

    rc = report('anim: HD inventory + reader coverage', ok, total,
                '(%d anims; tiers %s; layer-sets %d; res %d; share %d; bad=%s)'
                % (agg['scanned'], agg['by_tier'], agg['distinct_layer_sets'],
                   agg['distinct_resolutions'], agg['shared'],
                   bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
