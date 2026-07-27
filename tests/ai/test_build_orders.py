"""Oracle for the build-order library (assets/build_orders.json + the compiler).

The 22 pro build orders (transcribed from V's Miro cards) are only useful as bot
presets if each one COMPILES to a valid aiscript. This checks, with no install
needed (pure JSON + generator):

  1. DATA. build_orders.json parses, has 22 entries, and every entry carries the
     required fields (id, race, name, matchup, aggression, economy, build[]).
  2. NAME MAP. unit_ids.json resolves every producible build row (action=false,
     not an upgrade) to a real units.dat id - the measured name->id map covers
     the whole corpus.
  3. COMPILE. Each build order -> a Tactic -> aiscript.bin that is disasm-CLEAN
     (partition/jump oracle) AND whose every instruction re-encodes byte-
     identically (generate->disasm->re-encode fixed point). This is the same
     guarantee the browser twin shows for all 22.

    py test_build_orders.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import report              # noqa: E402
import ai_bin                          # noqa: E402
import ai_disasm                       # noqa: E402
import ai_asm                          # noqa: E402
import build_orders as bo              # noqa: E402


def main():
    bos, names, kinds = bo.load()
    ok = total = 0
    bad = []

    # 1. data shape
    total += 1
    need = ('id', 'race', 'name', 'matchup', 'aggression', 'economy', 'build')
    shape_ok = (len(bos) == 22 and all(all(k in b for k in need) for b in bos)
                and all(b['race'] in ('T', 'P', 'Z') for b in bos))
    if shape_ok:
        ok += 1
    else:
        bad.append('data shape: %d entries' % len(bos))

    # 2. every producible row resolves via the measured name map
    total += 1
    unresolved = set()
    producible = 0
    for b in bos:
        for row in b['build']:
            if row['action'] or bo._UPG.search(row['name']):
                continue
            producible += 1
            core = bo.normalize(row['name'], names)
            if core not in names:
                unresolved.add(row['name'])
    if not unresolved and producible > 100:
        ok += 1
    else:
        bad.append('unresolved rows: %s' % (list(unresolved)[:4]))

    # 3. each build order compiles disasm-clean and round-trips
    total += 1
    fails = []
    for b in bos:
        data = bo.compile_bot(b, names, kinds)
        f = ai_bin.parse(data, ai_bin.AISCRIPT)
        clean, _ = ai_disasm.coverage(f)
        n, mism = ai_asm.roundtrip_instructions(f)
        if not (clean and not mism and n > 0):
            fails.append(b['id'])
    if not fails:
        ok += 1
    else:
        bad.append('compile/roundtrip fails: %s' % fails[:4])

    rc = report('ai: build-order library compiles', ok, total,
                '(%d cards, %d rows resolved; bad=%s)'
                % (len(bos), producible, bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
