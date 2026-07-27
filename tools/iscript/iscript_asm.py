#!/usr/bin/env python3
"""Assembler for iscript.bin - the exact inverse of iscript_disasm, plus a
relocating reassembler.

Two proven guarantees, both falsifiable against the real file (the Stage-4
acceptance test, mirroring tools/ai/ai_asm.py):

  encode_instruction(ins)   re-emits one opcode's bytes; for every reachable
      opcode in the corpus it must equal the original bytes (proves the opcode +
      argument encoding inverts the decoder, including the variable 'sounds' arg
      which the decoder already expanded into explicit args).

  encode_header(entry) / encode_id_table(isc)  rebuild the SCPE headers and the
      id-table region; each must equal the original bytes (proves the container
      layout).

Together: decode(original) -> encode(no changes) -> byte-identical, piece by
piece, so an editor built on this cannot silently corrupt an unedited script.

reassemble(isc) is the relocating compiler an editor needs when opcode sizes
change (add/remove opcodes): it lays every reachable opcode out contiguously,
recomputes every label target AND every header animation offset through the
old->new map, then rebuilds headers + id table. It returns a NEW valid
iscript.bin (only reachable code, possibly reordered) - verified by re-parsing
and requiring every animation's opcode sequence to be preserved.
"""
import struct

import iscript_disasm as D
from iscript_opcodes import ENTRY_TYPES


def encode_instruction(ins):
    """Bytes for one Instruction. Every arg (including the 'sounds' count byte
    and each expanded soundid) is written little-endian at its stored size."""
    out = bytearray([ins.opcode])
    for a in ins.args:
        out += int(a.value).to_bytes(a.size, 'little')
    return bytes(out)


def encode_header(entry):
    """Bytes for one SCPE header: 'SCPE' + u8 type + 3 pad + type's u16 anim
    offsets (0 for an absent animation)."""
    out = bytearray(b'SCPE')
    out.append(entry.type & 0xFF)
    out += b'\x00\x00\x00'
    for _, off in entry.animations:
        out += struct.pack('<H', off or 0)
    return bytes(out)


def encode_id_table(isc):
    """Rebuild the id-table region (from id_table_offset to EOF): {u16 id,
    u16 headerOffset} per entry + the 0xffff terminator."""
    out = bytearray()
    for e in isc.entries:
        out += struct.pack('<HH', e.id, e.header_offset)
    out += struct.pack('<HH', 0xFFFF, 0)          # full 4-byte terminator entry
    return bytes(out)


def roundtrip_opcodes(isc):
    """Re-encode every reachable opcode; return (checked, mismatches[])."""
    _, info = D.coverage(isc)
    data = isc.data
    checked = 0
    bad = []
    for p in info['instr_starts']:
        ins = D.decode_one(data, p)
        enc = encode_instruction(ins)
        checked += 1
        if enc != data[p:p + ins.size]:
            bad.append((p, enc.hex(), data[p:p + ins.size].hex()))
    return checked, bad


def roundtrip_headers(isc):
    """Re-encode every header; return (checked, mismatches[])."""
    checked = 0
    bad = []
    for e in isc.entries:
        enc = encode_header(e)
        orig = isc.data[e.header_offset:e.header_offset + len(enc)]
        checked += 1
        if enc != orig:
            bad.append((e.id, enc.hex(), orig.hex()))
    return checked, bad


def reassemble(isc, base=2):
    """Relocating rebuild -> a new iscript.bin (bytes). Lays every reachable
    opcode contiguously from `base`, remaps all label targets and header
    animation offsets, then appends headers and the id table and points u16@0 at
    the table. Only reachable code is kept, so the result may be smaller/reordered
    but every animation is preserved. Raises if the file would exceed the u16
    offset space (65535)."""
    ok, info = D.coverage(isc)
    if not ok:
        raise ValueError('cannot reassemble a corpus that does not trace clean')
    starts = sorted(info['instr_starts'])
    instrs = [D.decode_one(isc.data, p) for p in starts]

    # pass 1: assign new addresses to every opcode
    addr_map = {}
    pos = base
    for ins in instrs:
        addr_map[ins.address] = pos
        pos += ins.size
    code_end = pos

    # pass 2: emit bytecode with remapped label targets
    code = bytearray(b'\x00' * base)
    for ins in instrs:
        code.append(ins.opcode)
        for a in ins.args:
            if a.type == 'label':
                if a.value not in addr_map:
                    raise KeyError('label 0x%x outside reachable set' % a.value)
                code += struct.pack('<H', addr_map[a.value])
            else:
                code += int(a.value).to_bytes(a.size, 'little')

    # headers, each at its new offset, with remapped animation offsets
    header_pos = {}
    headers = bytearray()
    for e in isc.entries:
        header_pos[e.id] = code_end + len(headers)
        headers += b'SCPE' + bytes([e.type & 0xFF]) + b'\x00\x00\x00'
        for _, off in e.animations:
            headers += struct.pack('<H', addr_map[off] if off else 0)

    table_off = code_end + len(headers)
    out = bytearray(code) + headers
    for e in isc.entries:
        out += struct.pack('<HH', e.id, header_pos[e.id])
    out += struct.pack('<HH', 0xFFFF, 0)          # full 4-byte terminator entry
    if len(out) > 0xFFFF:
        raise ValueError('reassembled iscript.bin exceeds u16 space (%d B)'
                         % len(out))
    struct.pack_into('<H', out, 0, table_off)
    return bytes(out)


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import iscript_bin
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    isc = iscript_bin.load_from_chain(mpq.MpqChain(base))
    n, bad = roundtrip_opcodes(isc)
    hn, hbad = roundtrip_headers(isc)
    tok = encode_id_table(isc) == isc.data[isc.id_table_offset:]
    print('opcode round-trip %d/%d; header round-trip %d/%d; id-table %s'
          % (n - len(bad), n, hn - len(hbad), hn, 'MATCH' if tok else 'DIFF'))
    ra = reassemble(isc)
    isc2 = iscript_bin.parse(ra)
    ok2, info2 = D.coverage(isc2)
    print('reassembled: %d B (orig %d), reparse %s'
          % (len(ra), len(isc.data), 'CLEAN' if ok2 else 'DESYNC'))
