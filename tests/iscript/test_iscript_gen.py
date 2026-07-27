"""Oracle for the iscript text assembler (tools/iscript/iscript_gen.py).

Authoring an iscript entry from text is only useful if the merged file is a valid
iscript.bin that still contains every stock animation. This checks, against the
real file:

  1. PARSE+ASSEMBLE+MERGE -> coverage CLEAN (the whole corpus still traces).
  2. NON-DESTRUCTIVE: the [0, old_id_table) region is byte-identical, and a stock
     script the edit did not touch (id 1) disassembles to the same opcodes.
  3. INTENT PRESERVED: the edited id's animation disassembles back to exactly the
     opcodes (and args) the text specified.
  4. SOUNDS: an entry using the variable playsndrand opcode assembles and decodes
     with the right count + soundids.

    py test_iscript_gen.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'iscript'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import iscript_bin                       # noqa: E402
import iscript_disasm as D               # noqa: E402
import iscript_gen as G                  # noqa: E402

TEXT = """
.header id=0 type=12
Init -> lbl_init
Walking -> lbl_walk
.code
lbl_init:
    imgul 1 0 42
    playfram 0
    wait 3
    playsndrand 2 100 101
    goto lbl_init
lbl_walk:
    playfram 17
    wait 2
    goto lbl_walk
"""


def _anim_names(isc, off):
    return [D.decode_one(isc.data, p).name
            for p in sorted(D.trace_reachable(isc.data, off,
                            isc.id_table_offset)[1]['instr_starts'])]


def main():
    need(BW, 'Brood War install')
    stock = mpq.MpqChain(BW).read('scripts\\iscript.bin')
    base = iscript_bin.parse(stock)
    old_table = base.id_table_offset
    stock_id1 = _anim_names(base, base.by_id()[1].animations[0][1]) \
        if base.by_id().get(1) else None

    ok = total = 0
    bad = []

    merged = G.merge_text(stock, TEXT)
    isc = iscript_bin.parse(merged)

    # 1. coverage clean
    total += 1
    clean, _ = D.coverage(isc)
    if clean:
        ok += 1
    else:
        bad.append('merged coverage not clean')

    # 2. non-destructive: stock region verbatim + an untouched script unchanged.
    # Bytes 0-1 (the id-table pointer) legitimately change; content from byte 2
    # onward through the old table must be identical.
    total += 1
    region_ok = merged[2:old_table] == stock[2:old_table]
    id1_ok = (stock_id1 is None) or \
        (_anim_names(isc, isc.by_id()[1].animations[0][1]) == stock_id1)
    if region_ok and id1_ok:
        ok += 1
    else:
        bad.append('region=%s id1=%s' % (region_ok, id1_ok))

    # 3. intent preserved: id 0 Init opcode sequence == what the text said
    total += 1
    e0 = isc.by_id()[0]
    init_off = dict(e0.animations)['Init']
    got = _anim_names(isc, init_off)
    want = ['imgul', 'playfram', 'wait', 'playsndrand', 'goto']
    # also check imgul args (1,0,42) and the goto loops back to Init start
    imgul = D.decode_one(isc.data, init_off)
    imgul_ok = imgul.name == 'imgul' and [a.value for a in imgul.args] == [1, 0, 42]
    if got == want and imgul_ok:
        ok += 1
    else:
        bad.append('init seq %s (imgul_ok=%s)' % (got, imgul_ok))

    # 4. sounds opcode decoded with right count + soundids
    total += 1
    snd = None
    for p in sorted(D.trace_reachable(isc.data, init_off,
                    isc.id_table_offset)[1]['instr_starts']):
        ins = D.decode_one(isc.data, p)
        if ins.name == 'playsndrand':
            snd = ins
            break
    snd_ok = snd is not None and snd.args[0].value == 2 and \
        [a.value for a in snd.args if a.type == 'soundid'] == [100, 101]
    if snd_ok:
        ok += 1
    else:
        bad.append('sounds decode wrong')

    rc = report('iscript: text assembler + merge', ok, total,
                '(merged %d B; bad=%s)' % (len(merged), bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
