#!/usr/bin/env python3
"""Disassembler for StarCraft AI-script bytecode (aiscript.bin / bwscript.bin).

Two things are provided:

  disassemble_stream(data, start, end)  - linearly decode a byte range into a
      list of Instruction, advancing opcode + argument sizes per ai_opcodes.

  linear_coverage(ai_file)              - the CORPUS ORACLE. StarCraft stores
      every script's bytecode back-to-back in one region [first_offset ..
      table_offset); a correct opcode/argument-size table decodes that whole
      region into a whole number of instructions that ends EXACTLY on the entry
      table, with every opcode valid and every jump/address landing on an
      instruction boundary. That is the AI equivalent of VP8's "each residual
      partition ends exactly on its boundary" - one wrong argument size shifts
      everything after it, so hitting the table boundary to the byte is a
      statement about the entire decode.

Arguments are decoded little-endian. 'address' args are absolute offsets within
the file (the same space as entry.offset), NOT relative.
"""
from dataclasses import dataclass, field
import struct

from ai_opcodes import OPCODES, MAX_OPCODE


@dataclass
class Argument:
    type: str
    value: int
    size: int


@dataclass
class Instruction:
    address: int                 # byte offset of this opcode within the file
    opcode: int
    name: str
    args: list = field(default_factory=list)   # list[Argument]
    size: int = 0                # total bytes consumed (opcode + args)
    control_flow: str = ''

    @property
    def targets(self):
        """Absolute jump/call target offsets referenced by this instruction."""
        return [a.value for a in self.args if a.type == 'address']


class DisasmError(Exception):
    pass


def decode_one(data, pos):
    """Decode a single instruction at data[pos]. Returns an Instruction.
    Raises DisasmError on an invalid opcode or a truncated argument."""
    n = len(data)
    if pos >= n:
        raise DisasmError('opcode read past end at 0x%x' % pos)
    op = data[pos]
    if op > MAX_OPCODE:
        raise DisasmError('invalid opcode 0x%02x at 0x%x' % (op, pos))
    spec = OPCODES[op]
    args = []
    o = pos + 1
    for typ, sz in spec.args:
        if sz < 0:                       # variable: null-terminated string
            end = data.find(b'\x00', o)
            if end < 0:
                raise DisasmError('unterminated string arg at 0x%x' % o)
            args.append(Argument(typ, o, end + 1 - o))     # value = str start
            o = end + 1
        else:
            if o + sz > n:
                raise DisasmError('truncated %s arg for %s at 0x%x'
                                  % (typ, spec.name, o))
            if sz == 1:
                v = data[o]
            elif sz == 2:
                v = struct.unpack_from('<H', data, o)[0]
            elif sz == 4:
                v = struct.unpack_from('<I', data, o)[0]
            else:
                raise DisasmError('unexpected arg size %d' % sz)
            args.append(Argument(typ, v, sz))
            o += sz
    return Instruction(address=pos, opcode=op, name=spec.name, args=args,
                       size=o - pos, control_flow=spec.control_flow)


def disassemble_stream(data, start, end):
    """Linearly decode [start, end). Returns list[Instruction]; raises if the
    stream does not land exactly on `end`."""
    out = []
    pos = start
    while pos < end:
        ins = decode_one(data, pos)
        out.append(ins)
        pos += ins.size
    if pos != end:
        raise DisasmError('stream overran boundary: ended 0x%x != 0x%x'
                          % (pos, end))
    return out


# control-flow classes that STOP linear fall-through (the block ends here)
_BLOCK_END = frozenset(('jump', 'terminate'))


def trace_reachable(data, start, table_offset):
    """Follow control flow from `start`, collecting every reachable instruction.

    StarCraft AI scripts are NOT a single linear stream: a script is a graph of
    basic blocks reached by jumps/calls, and unrelated code may sit between them.
    So coverage is by reachability, not linear scan. `jump`/`terminate` end a
    block's fall-through; `cond_jump`/`call`/`multi_jump`/`spawn` add their
    target(s) and also fall through.

    Returns (ok, info) where info has instr_starts (set of instruction offsets),
    n, and on failure an 'error'. A target/opcode that lands mid-instruction or
    past the table is a desync - the same guarantee as VB8 partition slack."""
    seen = set()
    work = [start]
    while work:
        pos = work.pop()
        while True:
            if pos in seen:
                break
            if not (start <= pos < table_offset) and pos != start:
                if pos >= table_offset or pos < 0:
                    return False, {'instr_starts': seen, 'n': len(seen),
                                   'error': 'flow left code region at 0x%x' % pos}
            try:
                ins = decode_one(data, pos)
            except DisasmError as e:
                return False, {'instr_starts': seen, 'n': len(seen),
                               'error': str(e)}
            seen.add(pos)
            for t in ins.targets:
                work.append(t)
            if ins.control_flow in _BLOCK_END:
                break
            pos += ins.size
    return True, {'instr_starts': seen, 'n': len(seen)}


def coverage(ai_file):
    """Trace every used script of an AiScriptFile and merge the reachable sets.

    Returns (ok, info): info has instr_starts, n_instructions, n_scripts,
    bad_targets (jump/call targets that miss an instruction boundary), and on
    failure the first 'error'/'script'. This is the corpus oracle."""
    all_starts = set()
    n_scripts = 0
    for e in ai_file.entries:
        if not e.used:
            continue
        n_scripts += 1
        ok, info = trace_reachable(ai_file.data, e.offset, ai_file.table_offset)
        all_starts |= info['instr_starts']
        if not ok:
            return False, {'instr_starts': all_starts, 'script': e.fourcc,
                           'error': info['error']}
    # every referenced target must be an instruction boundary
    bad = []
    for pos in all_starts:
        ins = decode_one(ai_file.data, pos)
        for t in ins.targets:
            if t not in all_starts:
                bad.append((ins.address, t))
    return (len(bad) == 0), {'instr_starts': all_starts,
                             'n_instructions': len(all_starts),
                             'n_scripts': n_scripts, 'bad_targets': bad,
                             'source': ai_file.source}


def format_instruction(ins, data=None, mark=False):
    """One-line disassembly of an Instruction: `>> 0x00708c  enemyowns_jump
    unit=9 ->0x7090`. `data` lets a string arg be shown decoded; `mark` flags
    the pc the caller was asked about."""
    parts = []
    for a in ins.args:
        if a.type == 'address':
            parts.append('->0x%x' % a.value)
        elif a.type == 'string':
            if data is not None:
                s = data[a.value:a.value + a.size - 1].decode('latin1', 'replace')
                parts.append('%r' % s)
            else:
                parts.append('<str@0x%x>' % a.value)
        else:
            parts.append('%s=%d' % (a.type, a.value))
    return '%s0x%06x  %-22s %s' % ('>> ' if mark else '   ', ins.address,
                                   ins.name, ' '.join(parts))


def scripts_reaching(ai_file, off):
    """Every used script whose reachable set includes `off` (an instruction
    start). Usually one; a shared subroutine can be reached by several."""
    hits = []
    for e in ai_file.entries:
        if not e.used:
            continue
        _, info = trace_reachable(ai_file.data, e.offset, ai_file.table_offset)
        if off in info['instr_starts']:
            hits.append(e)
    return hits


def disassemble_script(ai_file, entry):
    """(address-ordered) list of Instruction for one script's reachable set."""
    _, info = trace_reachable(ai_file.data, entry.offset, ai_file.table_offset)
    return [decode_one(ai_file.data, p) for p in sorted(info['instr_starts'])]


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(
        description='Disassemble StarCraft AI scripts (aiscript.bin / '
                    'bwscript.bin). No flags: corpus coverage over the install.')
    ap.add_argument('install', nargs='?',
                    default=r'C:\Git\Starcraft BroodWar  v1.1.61',
                    help='BW install dir (ignored when --file is given)')
    ap.add_argument('--file', help='a raw aiscript.bin / bwscript.bin on disk '
                    '(e.g. one extracted with tools/extract.py)')
    ap.add_argument('--source', choices=['aiscript.bin', 'bwscript.bin'],
                    default='aiscript.bin', help='which table --file is')
    ap.add_argument('--at', type=lambda s: int(s, 0), metavar='OFF',
                    help='disassemble the script containing this pc offset '
                    '(decimal or 0x..), marking that instruction')
    ap.add_argument('--script', metavar='ID',
                    help='disassemble one whole script by FourCC')
    ap.add_argument('--which', type=lambda s: int(s, 0), metavar='OFF',
                    help='just report which script(s) reach this offset')
    ap.add_argument('--context', type=int, default=8,
                    help='instructions of context each side of --at (0 = whole '
                    'script)')
    args = ap.parse_args(argv)

    if args.file:
        with open(args.file, 'rb') as fh:
            files = {args.source: ai_bin.parse(fh.read(), args.source)}
    else:
        import mpq
        files = ai_bin.load_from_chain(mpq.MpqChain(args.install))

    def pick():
        return (files.get(args.source) or files.get('aiscript.bin')
                or next(iter(files.values())))

    # --- targeted modes ---
    if args.which is not None:
        f = pick()
        hits = scripts_reaching(f, args.which)
        if not hits:
            print('0x%x (%d): not an instruction start in any script'
                  % (args.which, args.which))
        for e in hits:
            print('0x%x reached by %-6s (script offset 0x%x, string_id %d)'
                  % (args.which, e.fourcc, e.offset, e.string_id))
        return 0

    if args.at is not None or args.script:
        f = pick()
        data = f.data
        if args.script:
            entry = f.by_id().get(args.script)
            if entry is None:
                print('no script %r in %s' % (args.script, f.source))
                return 1
            mark = None
        else:
            hits = scripts_reaching(f, args.at)
            if not hits:                       # not a boundary in any script
                try:
                    ins = decode_one(data, args.at)
                    print('(0x%x is in no script\'s reachable set; standalone '
                          'decode)' % args.at)
                    print(format_instruction(ins, data, mark=True))
                    return 0
                except DisasmError as ex:
                    print('0x%x: %s' % (args.at, ex))
                    return 1
            entry = hits[0]
            mark = args.at

        instrs = disassemble_script(f, entry)
        print('== %s  script offset 0x%x  (%d instr, string_id %d) =='
              % (entry.fourcc, entry.offset, len(instrs), entry.string_id))
        if mark is not None and args.context > 0:
            idx = next((i for i, ins in enumerate(instrs)
                        if ins.address == mark), None)
            if idx is not None:
                lo = max(0, idx - args.context)
                hi = min(len(instrs), idx + args.context + 1)
                instrs = instrs[lo:hi]
        for ins in instrs:
            print(format_instruction(ins, data, mark=(ins.address == mark)))
        return 0

    # --- default: corpus coverage ---
    for source, f in files.items():
        ok, info = coverage(f)
        print('%-14s %s  scripts=%d  reachable_instr=%d'
              % (source, 'CLEAN' if ok else 'DESYNC',
                 info.get('n_scripts', 0), info.get('n_instructions', 0)))
        if not ok:
            print('   %s: %s' % (info.get('script', '?'),
                                 info.get('error', 'bad targets: %d'
                                          % len(info.get('bad_targets', [])))))
    return 0


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import ai_bin
    sys.exit(_cli(sys.argv[1:]))
