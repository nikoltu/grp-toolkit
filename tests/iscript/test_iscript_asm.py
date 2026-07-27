"""Oracle for the iscript assembler (tools/iscript/iscript_asm.py).

The Stage-4 acceptance test for iscript, mirroring tests/ai/test_ai_roundtrip.py:

  1. OPCODE round-trip. Every reachable opcode re-encodes to its exact original
     bytes (the encoder is the exact inverse of the decoder, incl. the variable
     'sounds' arg).
  2. HEADER round-trip. Every SCPE header re-encodes byte-identically.
  3. ID-TABLE round-trip. The id-table region (id_table_offset..EOF) re-encodes
     byte-identically, terminator included.
  4. RELOCATION. reassemble() -> a new iscript.bin that re-parses CLEAN and, for
     every entry and every animation, disassembles to the SAME opcode-name
     sequence as the original (offsets moved, meaning preserved). This proves the
     relocating compiler an editor needs when opcode sizes change.

    py test_iscript_asm.py
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
import iscript_asm as A                  # noqa: E402


def _anim_opcodes(isc, off):
    _, info = D.trace_reachable(isc.data, off, isc.id_table_offset)
    return [D.decode_one(isc.data, p).name for p in sorted(info['instr_starts'])]


def main():
    need(BW, 'Brood War install')
    isc = iscript_bin.load_from_chain(mpq.MpqChain(BW))
    ok = total = 0
    bad = []

    # 1. opcode round-trip
    total += 1
    n, mism = A.roundtrip_opcodes(isc)
    if not mism and n > 0:
        ok += 1
    else:
        bad.append('opcode rt %d/%d' % (n - len(mism), n))

    # 2. header round-trip
    total += 1
    hn, hmism = A.roundtrip_headers(isc)
    if not hmism and hn > 0:
        ok += 1
    else:
        bad.append('header rt %d/%d' % (hn - len(hmism), hn))

    # 3. id-table round-trip
    total += 1
    if A.encode_id_table(isc) == isc.data[isc.id_table_offset:]:
        ok += 1
    else:
        bad.append('id-table differs')

    # 4. relocation preserves every animation's opcode sequence
    total += 1
    ra = A.reassemble(isc)
    isc2 = iscript_bin.parse(ra)
    clean, _ = D.coverage(isc2)
    seqs_ok = clean and len(isc2.entries) == len(isc.entries)
    if seqs_ok:
        by2 = isc2.by_id()
        for e in isc.entries:
            e2 = by2.get(e.id)
            if e2 is None:
                seqs_ok = False
                bad.append('entry %d missing after reassemble' % e.id)
                break
            for (name, off), (_, off2) in zip(e.animations, e2.animations):
                if bool(off) != bool(off2):
                    seqs_ok = False
                    bad.append('%d/%s presence changed' % (e.id, name))
                    break
                if off and _anim_opcodes(isc, off) != _anim_opcodes(isc2, off2):
                    seqs_ok = False
                    bad.append('%d/%s opcode sequence changed' % (e.id, name))
                    break
            if not seqs_ok:
                break
    else:
        bad.append('reassembled reparse not clean')
    if seqs_ok:
        ok += 1

    rc = report('iscript: assembler round-trip + relocation', ok, total,
                '(%d opcodes, %d headers; reasm %d B; bad=%s)'
                % (n, hn, len(ra), bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
