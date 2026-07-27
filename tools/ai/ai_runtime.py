#!/usr/bin/env python3
"""AITR - AI Runtime Trace: the format an OpenBW-based engine emits per AI step,
and a comparator that aligns a runtime trace against the static disassembly.

The real traces come from the engine (the parallel OpenBW session logs one event
per AI VM step: frame, player, script id, thread, pc, opcode, wait timer, blocked
reason). This module owns the neutral FORMAT and the COMPARATOR; it does not need
the engine to be useful or testable, because the comparator's guarantee is
checkable without one:

    every runtime pc must be the address of a static instruction, and the opcode
    logged there must equal the statically-decoded opcode.

A divergence is the bug locator the proposal wants: "static says opcode X at pc,
runtime executed Y" means either the engine's VM or our decoder is wrong at that
pc. To exercise the comparator without the engine, simulate_trace() walks the
static CFG and emits a synthetic AITR stream; feeding it back must align 100%
(tests/ai/test_ai_runtime.py). When real engine logs arrive, they parse into the
same AITR events and use the same compare().
"""
import json
from dataclasses import dataclass, field, asdict

import ai_disasm


@dataclass
class AitrEvent:
    frame: int
    player: int
    script_id: str
    thread: int
    pc: int                      # byte offset of the executing opcode
    opcode: int
    blocked_reason: str = ''     # '' when running


@dataclass
class TraceDiff:
    aligned: int = 0
    total: int = 0
    mismatches: list = field(default_factory=list)   # [(pc, static_op, runtime_op)]
    unknown_pc: list = field(default_factory=list)    # pcs with no static instr

    @property
    def ok(self):
        return not self.mismatches and not self.unknown_pc


def compare(ai_file, entry, trace):
    """Align an AITR trace (list[AitrEvent]) for one script against the static
    disassembly. Returns TraceDiff."""
    _, info = ai_disasm.trace_reachable(ai_file.data, entry.offset,
                                        ai_file.table_offset)
    static_op = {}
    for p in info['instr_starts']:
        static_op[p] = ai_disasm.decode_one(ai_file.data, p).opcode
    diff = TraceDiff(total=len(trace))
    for ev in trace:
        if ev.pc not in static_op:
            diff.unknown_pc.append(ev.pc)
        elif static_op[ev.pc] != ev.opcode:
            diff.mismatches.append((ev.pc, static_op[ev.pc], ev.opcode))
        else:
            diff.aligned += 1
    return diff


# terminal / blocking opcodes for the tiny simulator
_WAITS = {'wait', 'wait_build', 'wait_buildstart', 'wait_train', 'wait_force',
          'wait_upgrades', 'wait_turrets', 'wait_bunkers', 'wait_secure',
          'wait_finishattack'}


def simulate_trace(ai_file, entry, player=0, max_steps=400):
    """Walk the static instructions from the entry to produce a SYNTHETIC AITR
    trace (stand-in for the engine). Follows fall-through, takes goto, takes the
    first target of a conditional, stops at terminate or when a wait would loop.
    Purely for exercising compare(); not a real VM."""
    _, info = ai_disasm.trace_reachable(ai_file.data, entry.offset,
                                        ai_file.table_offset)
    starts = info['instr_starts']
    trace = []
    pc = entry.offset
    frame = 0
    seen_wait = set()
    for _ in range(max_steps):
        if pc not in starts:
            break
        ins = ai_disasm.decode_one(ai_file.data, pc)
        blocked = ''
        if ins.name in _WAITS:
            if pc in seen_wait:
                break                          # would loop on a wait; stop
            seen_wait.add(pc)
            blocked = 'WAIT'
        trace.append(AitrEvent(frame=frame, player=player,
                               script_id=entry.fourcc, thread=0, pc=pc,
                               opcode=ins.opcode, blocked_reason=blocked))
        frame += 1
        cf = ins.control_flow
        if cf == 'terminate':
            break
        if cf in ('jump', 'multi_jump') and ins.targets:
            pc = ins.targets[0]
        elif cf in ('cond_jump', 'call', 'spawn') and ins.targets:
            # follow fall-through for the simulation (deterministic path)
            pc = ins.address + ins.size
        else:
            pc = ins.address + ins.size
    return trace


def trace_to_json(trace):
    return [asdict(e) for e in trace]


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
        trace = simulate_trace(f, e)
        diff = compare(f, e, trace)
        print('%s: simulated %d steps, aligned %d/%d, mismatches %d, unknown_pc %d'
              % (sid, len(trace), diff.aligned, diff.total,
                 len(diff.mismatches), len(diff.unknown_pc)))
        print('  first 6 events:', [(e2.pc, e2.opcode, e2.blocked_reason)
                                    for e2 in trace[:6]])
        break
