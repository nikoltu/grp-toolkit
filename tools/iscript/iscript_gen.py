#!/usr/bin/env python3
"""Text assembler for iscript animation entries - author or edit one iscript
entry from text and MERGE it into the stock iscript.bin.

This is to iscript what tools/ai/ai_gen.py is to aiscript: the compile side. It
does NOT rebuild the whole 398-entry file; it assembles ONE entry's header +
animation bytecode and appends it, updating that id's id-table slot to point at
the new header. Every existing script keeps its exact bytes (their offsets live
in the untouched [0, old_id_table) region), so the merge is non-destructive - the
file still contains all stock animations plus the new/edited one.

Text format (simple, not PyMS-exact):

    # a comment
    .header id=0 type=12
    Init    -> lbl_init
    Walking -> lbl_walk
    .code
    lbl_init:
        imgul 1 0 42
        playfram 0
        wait 3
        goto lbl_init
    lbl_walk:
        playfram 17
        wait 2
        goto lbl_walk

Header line gives the iscript id + type; the `Anim -> label` lines map animation
slots (names from iscript_opcodes.HEADER) to labels (unlisted slots are absent).
Opcodes take numeric args; a `label` arg is a label name. The variable 'sounds'
opcodes (playsndrand/attackmelee) are written `op COUNT s1 s2 ... sCOUNT`.

Oracle: tests/iscript/test_iscript_gen.py assembles text, merges into the real
file, and requires the stock region byte-identical, the corpus to trace clean,
and the new entry to disassemble back to the intended opcodes.
"""
import struct

from iscript_opcodes import OPCODE_BY_NAME, HEADER, ENTRY_TYPES
import iscript_bin
import iscript_disasm as D


class IScriptAsmError(Exception):
    pass


def parse_text(text):
    """Parse the text format -> (id, type, {anim_name: label}, [(label|None,
    opname, [args])...]). Label args stay as strings; others become ints."""
    iid = itype = None
    anim_map = {}
    steps = []
    section = 'header'
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('.header'):
            for tok in line.split()[1:]:
                if tok.startswith('id='):
                    iid = int(tok[3:], 0)
                elif tok.startswith('type='):
                    itype = int(tok[5:], 0)
            if itype not in ENTRY_TYPES:
                raise IScriptAsmError('line %d: type must be one of %s'
                                      % (lineno, sorted(ENTRY_TYPES)))
            continue
        if line == '.code':
            section = 'code'
            continue
        if section == 'header' and '->' in line:
            name, label = [s.strip() for s in line.split('->', 1)]
            if name not in HEADER:
                raise IScriptAsmError('line %d: unknown animation %r' % (lineno, name))
            anim_map[name] = label
            continue
        if line.endswith(':'):                      # a label
            steps.append((line[:-1].strip(), None, None))
            continue
        tok = line.split()
        opname = tok[0]
        spec = OPCODE_BY_NAME.get(opname)
        if spec is None:
            raise IScriptAsmError('line %d: unknown opcode %r' % (lineno, opname))
        args = []
        raw_args = tok[1:]
        ai = 0
        for typ, sz in spec.args:
            if sz < 0:                              # sounds: count + count*next
                cnt = int(raw_args[ai], 0)
                args.append(('count', cnt))
                ai += 1
                ntyp, nsz = spec.args[spec.args.index((typ, sz)) + 1]
                for _ in range(cnt):
                    args.append((ntyp, int(raw_args[ai], 0)))
                    ai += 1
                break
            if typ == 'label':
                args.append(('label', raw_args[ai]))
            else:
                args.append((typ, int(raw_args[ai], 0)))
            ai += 1
        steps.append((None, opname, args))
    if iid is None or itype is None:
        raise IScriptAsmError('missing ".header id=.. type=.."')
    return iid, itype, anim_map, steps


def _opcode_size(opname, args):
    spec = OPCODE_BY_NAME[opname]
    size = 1
    ai = 0
    for typ, sz in spec.args:
        if sz < 0:
            cnt = args[ai][1]
            size += 1 + cnt * spec.args[spec.args.index((typ, sz)) + 1][1]
            break
        size += sz
        ai += 1
    return size


def assemble_entry(iid, itype, anim_map, steps, base):
    """Lay the opcode blocks out from `base`, resolve labels, and return
    (bytecode, header_bytes, header_offset) for merging. header goes right after
    the bytecode."""
    # pass 1: assign an absolute address to each label
    labels = {}
    pos = base
    for lbl, opname, args in steps:
        if lbl is not None:
            if lbl in labels:
                raise IScriptAsmError('duplicate label %r' % lbl)
            labels[lbl] = pos
        else:
            pos += _opcode_size(opname, args)
    code_len = pos - base
    # pass 2: emit bytecode with resolved label args
    code = bytearray()
    for lbl, opname, args in steps:
        if lbl is not None:
            continue
        spec = OPCODE_BY_NAME[opname]
        code.append(spec.opcode)
        for typ, val in args:
            if typ == 'label':
                if val not in labels:
                    raise IScriptAsmError('undefined label %r' % val)
                code += struct.pack('<H', labels[val])
            elif typ == 'count':
                code.append(val & 0xFF)
            else:
                # size from the opcode registry for this arg type
                size = next(sz for t, sz in spec.args if t == typ)
                code += int(val).to_bytes(size, 'little')
    # header at base + code_len
    header_off = base + code_len
    hdr = bytearray(b'SCPE') + bytes([itype & 0xFF]) + b'\x00\x00\x00'
    for i in range(ENTRY_TYPES[itype]):
        name = HEADER[i] if i < len(HEADER) else None
        lbl = anim_map.get(name)
        hdr += struct.pack('<H', labels[lbl] if lbl and lbl in labels else 0)
    return bytes(code), bytes(hdr), header_off


def merge_text(stock_data, text):
    """Assemble the text entry and merge it into stock_data (bytes). Existing
    scripts keep their bytes; the target id's id-table slot points at the new
    header (a new id is appended if it did not exist). Returns the new file."""
    iid, itype, anim_map, steps = parse_text(text)
    base = struct.unpack_from('<H', stock_data, 0)[0]      # old id_table_offset
    code, hdr, header_off = assemble_entry(iid, itype, anim_map, steps, base)

    isc = iscript_bin.parse(stock_data)
    new_table = header_off + len(hdr)
    if new_table > 0xFFFF:
        raise IScriptAsmError('merged iscript.bin exceeds u16 space (%d B)'
                              % new_table)
    out = bytearray(stock_data[:base]) + code + hdr
    seen = False
    for e in isc.entries:
        off = header_off if e.id == iid else e.header_offset
        if e.id == iid:
            seen = True
        out += struct.pack('<HH', e.id, off)
    if not seen:
        out += struct.pack('<HH', iid, header_off)
    out += struct.pack('<HH', 0xFFFF, 0)
    struct.pack_into('<H', out, 0, new_table)
    return bytes(out)


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    demo = """
    .header id=0 type=12
    Init -> lbl
    .code
    lbl:
        imgul 1 0 42
        playfram 0
        wait 3
        goto lbl
    """
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    stock = mpq.MpqChain(base).read('scripts\\iscript.bin')
    merged = merge_text(stock, demo)
    isc = iscript_bin.parse(merged)
    ok, info = D.coverage(isc)
    e = isc.by_id()[0]
    names = [D.decode_one(isc.data, p).name
             for p in sorted(D.trace_reachable(isc.data,
                             e.animations[0][1], isc.id_table_offset)[1]['instr_starts'])]
    print('merged %d B (stock %d), coverage %s, id0 Init = %s'
          % (len(merged), len(stock), 'CLEAN' if ok else 'DESYNC', names))
