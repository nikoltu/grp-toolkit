#!/usr/bin/env python3
"""Disassembler + corpus oracle for iscript.bin animation bytecode.

decode_one(data, pos)          decode a single opcode -> Instruction.
trace_reachable(data, s, lim)  follow control flow from an animation entry point.
coverage(iscript_file)         THE ORACLE: trace every animation of every header
    and require the whole thing to be self-consistent - every opcode valid, every
    goto/call/condjmp target landing on an opcode boundary, no flow past the id
    table. One wrong argument size shifts everything after it, so a clean trace of
    the whole corpus is a statement about the argument-size table (the iscript
    analogue of tests/ai/test_ai_disasm.py).

'label' arguments are absolute file offsets (same space as the header animation
offsets), NOT relative. The variable 'sounds' argument (playsndrand/attackmelee)
is a 1-byte count followed by that many of the opcode's next argument.
"""
from dataclasses import dataclass, field

from iscript_opcodes import OPCODES, MAX_OPCODE


@dataclass
class Argument:
    type: str
    value: int
    size: int


@dataclass
class Instruction:
    address: int
    opcode: int
    name: str
    args: list = field(default_factory=list)
    size: int = 0
    control_flow: str = ''

    @property
    def targets(self):
        return [a.value for a in self.args if a.type == 'label']


class DisasmError(Exception):
    pass


def decode_one(data, pos):
    n = len(data)
    if pos >= n:
        raise DisasmError('opcode read past end at 0x%x' % pos)
    op = data[pos]
    if op > MAX_OPCODE:
        raise DisasmError('invalid opcode 0x%02x at 0x%x' % (op, pos))
    spec = OPCODES[op]
    args = []
    o = pos + 1
    sa = spec.args
    k = 0
    while k < len(sa):
        typ, sz = sa[k]
        if sz < 0:                             # variable 'sounds': count + N*next
            if o >= n:
                raise DisasmError('truncated sounds count at 0x%x' % o)
            cnt = data[o]
            args.append(Argument(typ, cnt, 1))
            o += 1
            ntyp, nsz = sa[k + 1]
            for _ in range(cnt):
                if o + nsz > n:
                    raise DisasmError('truncated sounds elem at 0x%x' % o)
                args.append(Argument(ntyp,
                                     int.from_bytes(data[o:o + nsz], 'little'),
                                     nsz))
                o += nsz
            k += 2
            continue
        if o + sz > n:
            raise DisasmError('truncated %s arg for %s at 0x%x'
                              % (typ, spec.name, o))
        args.append(Argument(typ, int.from_bytes(data[o:o + sz], 'little'), sz))
        o += sz
        k += 1
    return Instruction(address=pos, opcode=op, name=spec.name, args=args,
                       size=o - pos, control_flow=spec.control_flow)


_BLOCK_END = frozenset(('jump', 'terminate'))


def trace_reachable(data, start, limit):
    """Follow control flow from `start`, collecting reachable opcode offsets.
    `limit` is the id-table offset (code never runs into it). goto/end/return end
    a block; cond_jump/call add their target and also fall through."""
    seen = set()
    work = [start]
    while work:
        pos = work.pop()
        while True:
            if pos in seen:
                break
            if pos < 0 or pos >= limit:
                return False, {'instr_starts': seen,
                               'error': 'flow left region at 0x%x' % pos}
            try:
                ins = decode_one(data, pos)
            except DisasmError as e:
                return False, {'instr_starts': seen, 'error': str(e)}
            seen.add(pos)
            for t in ins.targets:
                work.append(t)
            if ins.control_flow in _BLOCK_END:
                break
            pos += ins.size
    return True, {'instr_starts': seen}


def coverage(isc):
    """Trace every animation of every header; merge reachable sets. Returns
    (ok, info) with n_instructions, n_anim, n_scripts, bad_targets."""
    limit = isc.id_table_offset
    all_starts = set()
    n_anim = 0
    for e in isc.entries:
        for name, off in e.animations:
            if not off:
                continue
            n_anim += 1
            ok, info = trace_reachable(isc.data, off, limit)
            all_starts |= info['instr_starts']
            if not ok:
                return False, {'instr_starts': all_starts, 'id': e.id,
                               'anim': name, 'error': info['error']}
    bad = []
    for pos in all_starts:
        ins = decode_one(isc.data, pos)
        for t in ins.targets:
            if t not in all_starts:
                bad.append((ins.address, t))
    return (len(bad) == 0), {'instr_starts': all_starts,
                             'n_instructions': len(all_starts),
                             'n_anim': n_anim, 'n_scripts': len(isc.entries),
                             'bad_targets': bad}


def format_instruction(ins, mark=False):
    parts = []
    for a in ins.args:
        parts.append('->0x%x' % a.value if a.type == 'label'
                     else '%s=%d' % (a.type, a.value))
    return '%s0x%05x  %-18s %s' % ('>> ' if mark else '   ', ins.address,
                                   ins.name, ' '.join(parts))


def disassemble_animation(data, start, limit):
    """Address-ordered Instruction list for one animation's reachable opcodes."""
    _, info = trace_reachable(data, start, limit)
    return [decode_one(data, p) for p in sorted(info['instr_starts'])]


if __name__ == '__main__':
    import sys
    import os
    import argparse
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import iscript_bin

    ap = argparse.ArgumentParser(
        description='iscript.bin disassembler. No --id: corpus coverage.')
    ap.add_argument('install', nargs='?',
                    default=r'C:\Git\Starcraft BroodWar  v1.1.61')
    ap.add_argument('--file', help='raw iscript.bin on disk (e.g. from extract.py)')
    ap.add_argument('--id', type=int, help='disassemble one iscript entry by id')
    args = ap.parse_args()

    if args.file:
        with open(args.file, 'rb') as fh:
            isc = iscript_bin.parse(fh.read())
    else:
        isc = iscript_bin.load_from_chain(mpq.MpqChain(args.install))

    if args.id is not None:
        e = isc.by_id().get(args.id)
        if e is None:
            print('no iscript entry %d' % args.id)
            sys.exit(1)
        print('== iscript %d  header@0x%x  type=%d ==' % (e.id, e.header_offset, e.type))
        for name, off in e.animations:
            if not off:
                continue
            print('%s:  (0x%x)' % (name, off))
            for ins in disassemble_animation(isc.data, off, isc.id_table_offset):
                print('  ' + format_instruction(ins))
        sys.exit(0)

    ok, info = coverage(isc)
    print('iscript.bin  %s  scripts=%d  anims=%d  reachable_opcodes=%d'
          % ('CLEAN' if ok else 'DESYNC', info.get('n_scripts', 0),
             info.get('n_anim', 0), info.get('n_instructions', 0)))
    if not ok:
        print('  ', info.get('error') or ('bad targets: %d'
              % len(info.get('bad_targets', []))))
