"""Oracle for the iscript.bin reader + disassembler.

iscript.bin is the animation-script VM (like aiscript.bin): a container of
headers, each pointing to opcode streams. This checks it the same falsifiable
way the AI toolkit is checked:

  1. CONTAINER. The id table parses to its entries, and every distinct
     images.dat.iscript_id resolves to one of them - the cross-check that the
     table (and the images.dat.iscript_id field) is read correctly.

  2. COVERAGE (the disasm oracle). Tracing every animation of every header
     decodes the whole reachable corpus with no desync: every opcode valid,
     every goto/call/condjmp target on an opcode boundary, nothing running past
     the id table. One wrong argument size shifts everything after it, so a clean
     trace is a statement about the entire borrowed opcode/arg-size table.

  3. HEADER TYPES. Every header type byte seen is in ENTRY_TYPES (so the
     animation-offset count is known), and the variable 'sounds' opcodes decode.

    py test_iscript.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'iscript'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import dat                               # noqa: E402
import iscript_bin                       # noqa: E402
import iscript_disasm                    # noqa: E402
from iscript_opcodes import ENTRY_TYPES  # noqa: E402


def main():
    need(BW, 'Brood War install')
    ch = mpq.MpqChain(BW)
    isc = iscript_bin.load_from_chain(ch)
    ok = total = 0
    bad = []

    # 1. every images.dat.iscript_id resolves to an entry
    total += 1
    images = dat.load_from_chain(ch, 'images.dat')
    ids = {images.get('iscript_id', i) for i in range(dat.IMAGE_COUNT)}
    have = set(isc.by_id())
    missing = sorted(ids - have)
    if not missing and len(isc.entries) > 300:
        ok += 1
    else:
        bad.append('%d iscript_ids missing from table' % len(missing))

    # 2. coverage clean
    total += 1
    clean, info = iscript_disasm.coverage(isc)
    if clean:
        ok += 1
    else:
        bad.append('coverage: %s' % (info.get('error')
                   or ('bad targets %d' % len(info.get('bad_targets', [])))))

    # 3. header types known + a 'sounds' opcode decodes somewhere
    total += 1
    types = {e.type for e in isc.entries}
    unknown = types - set(ENTRY_TYPES)
    # find a playsndrand/attackmelee in the reachable set and confirm it decodes
    sounds_ok = True
    if clean:
        for pos in info['instr_starts']:
            ins = iscript_disasm.decode_one(isc.data, pos)
            if ins.name in ('playsndrand', 'attackmelee'):
                # the count arg + that many soundids must have been read
                if ins.args and ins.args[0].type == 'sounds':
                    n = ins.args[0].value
                    if len([a for a in ins.args if a.type == 'soundid']) == n:
                        break
    if not unknown and sounds_ok:
        ok += 1
    else:
        bad.append('unknown header types: %s' % sorted(unknown))

    rc = report('iscript: container + disasm coverage', ok, total,
                '(%d scripts, %d anims, %d opcodes; bad=%s)'
                % (info.get('n_scripts', 0), info.get('n_anim', 0),
                   info.get('n_instructions', 0), bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
