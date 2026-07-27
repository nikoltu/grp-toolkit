#!/usr/bin/env python3
"""Basic-block control-flow graph for a decoded AI script (AICF).

Built from the reachable instruction set (ai_disasm.trace_reachable), so it
inherits that oracle: every block boundary is a real instruction start and every
edge target is one too. Block leaders are the entry, any jump/call/branch
target, and any instruction that falls through from a branch. Edges:

  fallthrough  a non-branching / non-terminating instruction to the next
  jump         unconditional goto -> target only
  cond_jump    conditional -> target AND fallthrough
  multi_jump   race_jump -> its (up to 3) targets, no fallthrough
  call         -> callee target AND fallthrough (control returns)
  terminate    stop / return / kill_thread -> no successor

A back edge (target block start <= source block start) marks a loop.
"""
from dataclasses import dataclass, field

import ai_disasm


@dataclass
class Block:
    start: int
    instrs: list = field(default_factory=list)   # list[Instruction]
    succ: list = field(default_factory=list)      # list[(kind, target_start)]
    pred: list = field(default_factory=list)

    @property
    def end(self):
        last = self.instrs[-1]
        return last.address + last.size


@dataclass
class Cfg:
    entry: int
    blocks: dict = field(default_factory=dict)    # {start: Block}
    back_edges: list = field(default_factory=list)  # [(src_start, dst_start)]

    @property
    def loops(self):
        return len(self.back_edges)

    def calls(self):
        return [(b.start, t) for b in self.blocks.values()
                for k, t in b.succ if k == 'call']


def _successors(ins, next_addr):
    """(kind, target) successor edges for one instruction."""
    cf = ins.control_flow
    tgts = ins.targets
    if cf == 'terminate':
        return []
    if cf == 'jump':
        return [('jump', t) for t in tgts]
    if cf == 'multi_jump':
        return [('jump', t) for t in tgts]     # race_jump: always to a target
    out = []
    if cf == 'cond_jump':
        out += [('cond', t) for t in tgts]
        out.append(('fall', next_addr))
    elif cf == 'call':
        out += [('call', t) for t in tgts]
        out.append(('fall', next_addr))
    elif cf == 'spawn':                          # multirun: forks; main falls through
        out += [('spawn', t) for t in tgts]
        out.append(('fall', next_addr))
    else:                                        # plain instruction
        out.append(('fall', next_addr))
    return out


def build_cfg(data, entry, table_offset):
    ok, info = ai_disasm.trace_reachable(data, entry, table_offset)
    starts = sorted(info['instr_starts'])
    ins_at = {p: ai_disasm.decode_one(data, p) for p in starts}
    nexts = {p: ins_at[p].address + ins_at[p].size for p in starts}

    # leaders: entry, any jump/call target, any fallthrough-after-branch start
    leaders = {entry}
    for p in starts:
        ins = ins_at[p]
        # a branch/call target is a leader; a plain fallthrough is NOT
        for kind, t in _successors(ins, nexts[p]):
            if kind != 'fall' and t in ins_at:
                leaders.add(t)
        # the instruction after a branch/terminate starts a new block
        if ins.control_flow in ('jump', 'cond_jump', 'call', 'multi_jump',
                                'terminate', 'spawn'):
            if nexts[p] in ins_at:
                leaders.add(nexts[p])

    leaders = sorted(l for l in leaders if l in ins_at)
    # assign each instruction to the block of the nearest leader <= it
    cfg = Cfg(entry=entry)
    for li, lead in enumerate(leaders):
        stop = leaders[li + 1] if li + 1 < len(leaders) else None
        blk = Block(start=lead)
        p = lead
        while p in ins_at and (stop is None or p < stop):
            blk.instrs.append(ins_at[p])
            # a branch inside ends the block even before the next leader
            if ins_at[p].control_flow in ('jump', 'cond_jump', 'call',
                                          'multi_jump', 'terminate', 'spawn'):
                p = nexts[p]
                break
            p = nexts[p]
        cfg.blocks[lead] = blk

    # edges
    for blk in cfg.blocks.values():
        last = blk.instrs[-1]
        for kind, t in _successors(last, last.address + last.size):
            if t in cfg.blocks:
                blk.succ.append((kind, t))
                cfg.blocks[t].pred.append((kind, blk.start))
                if t <= blk.start and kind in ('jump', 'cond', 'fall', 'spawn'):
                    cfg.back_edges.append((blk.start, t))
    return cfg


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import ai_bin
    bw = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    sid = sys.argv[2] if len(sys.argv) > 2 else 'Ter3'
    files = ai_bin.load_from_chain(mpq.MpqChain(bw))
    for src, f in files.items():
        e = f.by_id().get(sid)
        if not e:
            continue
        cfg = build_cfg(f.data, e.offset, f.table_offset)
        print('%s (%s): %d blocks, %d loops, %d calls'
              % (sid, src, len(cfg.blocks), cfg.loops, len(cfg.calls())))
        for b in sorted(cfg.blocks.values(), key=lambda x: x.start):
            succ = ' '.join('%s->0x%x' % (k, t) for k, t in b.succ)
            print('  0x%05x [%d ins] %s' % (b.start, len(b.instrs), succ))
        break
