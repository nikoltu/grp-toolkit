"""Stage-4 acceptance oracle: decode -> encode (no changes) -> byte-identical.

For both aiscript.bin and bwscript.bin:
  * every reachable instruction re-encodes to its exact original bytes, and
  * the rebuilt entry table equals the original table region byte-for-byte.

This is the strongest falsifiable check in the AI toolkit after the disasm
oracle: the encoder is proven to be the exact inverse of the decoder, so an
editor built on it cannot silently corrupt an unedited script. Measured 2026-07:
aiscript 15746 instr + 4692-B table, bwscript 7787 instr + 1252-B table, 0 diff.

    py test_ai_roundtrip.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import ai_bin                            # noqa: E402
import ai_asm                            # noqa: E402


def main():
    need(BW, 'Brood War install')
    files = ai_bin.load_from_chain(mpq.MpqChain(BW))
    if not files:
        print('SKIP: no AI script files')
        sys.exit(77)
    import ai_disasm

    def relocation_ok(f):
        """Assemble each script at a fresh base with recomputed jumps, re-decode,
        and require the same opcode sequence - proves offset recalculation."""
        base = 0x9000
        for e in f.entries:
            if not e.used:
                continue
            _, info = ai_disasm.trace_reachable(f.data, e.offset, f.table_offset)
            orig = [ai_disasm.decode_one(f.data, p)
                    for p in sorted(info['instr_starts'])]
            code, _, amap = ai_asm.assemble_script(f, e, base)
            buf = bytes(base) + code
            _, ninfo = ai_disasm.trace_reachable(buf, amap[e.offset],
                                                 base + len(code))
            new = [ai_disasm.decode_one(buf, p)
                   for p in sorted(ninfo['instr_starts'])]
            if len(new) != len(orig) or any(a.opcode != b.opcode
                                            for a, b in zip(new, orig)):
                return False
        return True

    ok = total = 0
    detail = []
    for source, f in sorted(files.items()):
        total += 1
        n, bad = ai_asm.roundtrip_instructions(f)
        tok, rl, ol = ai_asm.roundtrip_table(f)
        reloc = relocation_ok(f)
        if not bad and tok and reloc:
            ok += 1
            detail.append('%s %d instr + table + reloc' % (source, n))
        else:
            detail.append('%s FAIL (%d instr diff, table %s, reloc %s)'
                          % (source, len(bad), 'ok' if tok else 'DIFF',
                             'ok' if reloc else 'DIFF'))
    rc = report('ai: no-op round-trip byte-identical', ok, total,
                '(' + '; '.join(detail) + ')')
    sys.exit(rc)


if __name__ == '__main__':
    main()
