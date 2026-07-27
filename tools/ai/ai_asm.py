#!/usr/bin/env python3
"""Assembler for AI-script bytecode - the exact inverse of ai_disasm.

Two round-trip guarantees, both falsifiable against the real files:

  encode_instruction(ins, data)  re-emits one instruction's bytes; for every
      reachable instruction in the corpus it must equal the original bytes
      (proves the opcode + argument encoding inverts the decoder).

  encode_table(ai_file)          rebuilds the entry table bytes; it must equal
      the original table region (proves the 16-B / 8-B entry layout).

Together: decode(original) -> encode(no changes) -> byte-identical, section by
section, which is the Stage-4 acceptance test. Editing (offset recalculation)
builds on encode_instruction but is a separate concern from this no-op proof.

Unknown opcodes never occur in this corpus (the disasm oracle is 0-unknown), but
the encoder still round-trips raw bytes for any opcode it is given.
"""
import struct

from ai_opcodes import OPCODES


def encode_instruction(ins, data=None):
    """Bytes for one Instruction. Non-string args are packed little-endian at
    their declared size; a string arg re-emits its original null-terminated
    bytes from `data` (its value is that byte's offset)."""
    out = bytearray([ins.opcode])
    for a in ins.args:
        if a.type == 'string':
            if data is None:
                raise ValueError('string arg needs the source data to re-emit')
            end = data.find(b'\x00', a.value)
            out += data[a.value:end + 1]
        elif a.size == 1:
            out.append(a.value & 0xFF)
        elif a.size == 2:
            out += struct.pack('<H', a.value & 0xFFFF)
        elif a.size == 4:
            out += struct.pack('<I', a.value & 0xFFFFFFFF)
        else:
            raise ValueError('bad arg size %d' % a.size)
    return bytes(out)


def encode_entry(entry, entry_size):
    out = bytearray(entry.id[:4].ljust(4, b'\x00'))
    out += struct.pack('<I', entry.offset)
    if entry_size >= 16:
        out += struct.pack('<II', entry.string_id, entry.flags)
    return bytes(out)


def encode_table(ai_file):
    """Rebuild the entry-table region (from table_offset to EOF), including the
    null terminator, exactly as stored."""
    out = bytearray()
    for e in ai_file.entries:
        out += encode_entry(e, ai_file.entry_size)
    out += b'\x00\x00\x00\x00'                 # terminator id
    return bytes(out)


def assemble(instrs, base_offset, data=None):
    """Lay out `instrs` (address-ordered Instruction list) CONTIGUOUSLY starting
    at base_offset and recompute every address argument to the new layout. This
    is the offset/jump recalculation an editor needs: instruction sizes are
    invariant (an address arg is always 2 bytes regardless of value), so the
    only thing that moves is position, and each jump target is remapped through
    old_addr -> new_addr.

    Returns (bytes, addr_map). A target that is not among the assembled
    instructions (a jump out of this set) raises - callers assemble a whole
    self-contained script, whose jumps all stay inside it."""
    # first pass: assign new addresses
    addr_map = {}
    pos = base_offset
    for ins in instrs:
        addr_map[ins.address] = pos
        pos += ins.size
    # second pass: emit with remapped address args
    out = bytearray()
    for ins in instrs:
        out.append(ins.opcode)
        for a in ins.args:
            if a.type == 'address':
                if a.value not in addr_map:
                    raise KeyError('jump target 0x%x outside assembled set'
                                   % a.value)
                out += struct.pack('<H', addr_map[a.value])
            elif a.type == 'string':
                if data is None:
                    raise ValueError('string arg needs source data')
                end = data.find(b'\x00', a.value)
                out += data[a.value:end + 1]
            elif a.size == 1:
                out.append(a.value & 0xFF)
            elif a.size == 2:
                out += struct.pack('<H', a.value & 0xFFFF)
            elif a.size == 4:
                out += struct.pack('<I', a.value & 0xFFFFFFFF)
    return bytes(out), addr_map


def assemble_script(ai_file, entry, base_offset):
    """Extract a script's reachable instructions and assemble them contiguously
    at base_offset. Returns (bytes, new_entry_offset=base_offset, addr_map)."""
    import ai_disasm
    _, info = ai_disasm.trace_reachable(ai_file.data, entry.offset,
                                        ai_file.table_offset)
    instrs = [ai_disasm.decode_one(ai_file.data, p)
              for p in sorted(info['instr_starts'])]
    code, addr_map = assemble(instrs, base_offset, ai_file.data)
    return code, base_offset, addr_map


def roundtrip_instructions(ai_file):
    """Re-encode every reachable instruction of every script; return
    (n_checked, mismatches[])."""
    import ai_disasm
    data = ai_file.data
    checked = 0
    bad = []
    for e in ai_file.entries:
        if not e.used:
            continue
        ok, info = ai_disasm.trace_reachable(data, e.offset,
                                             ai_file.table_offset)
        for p in info['instr_starts']:
            ins = ai_disasm.decode_one(data, p)
            enc = encode_instruction(ins, data)
            checked += 1
            if enc != data[p:p + ins.size]:
                bad.append((e.fourcc, p, enc.hex(),
                            data[p:p + ins.size].hex()))
    return checked, bad


def roundtrip_table(ai_file):
    """Rebuild the table; return (ok, rebuilt_len, original_len). The original
    table region runs from table_offset to EOF."""
    rebuilt = encode_table(ai_file)
    original = ai_file.data[ai_file.table_offset:]
    return rebuilt == original, len(rebuilt), len(original)


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import ai_bin
    bw = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    files = ai_bin.load_from_chain(mpq.MpqChain(bw))
    for src, f in files.items():
        n, bad = roundtrip_instructions(f)
        tok, rl, ol = roundtrip_table(f)
        print('%-14s instr round-trip %d/%d ok; table %s (%d vs %d B)'
              % (src, n - len(bad), n, 'MATCH' if tok else 'DIFF', rl, ol))
        if bad:
            print('   first mismatch:', bad[0])
