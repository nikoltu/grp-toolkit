#!/usr/bin/env python3
"""Dependency validator for AI-script transforms (the safety net for the scaler).

Two kinds of check, kept strictly apart by how trustworthy they are:

  STRUCTURAL (falsifiable, byte-checkable) - the transform must not corrupt the
  bytecode: re-assemble the edited instructions, re-decode, and require the same
  opcode sequence with every jump/call target still on an instruction boundary
  and 0 unknown opcodes. Argument values must stay in range. This is the Stage-5
  oracle and it either holds or it doesn't.

  ADVISORY (approximate, clearly labelled) - dependency hints the editor should
  surface but that cannot be proven from the bytecode alone: shared-script use
  (editing affects other missions), and the consequence caveat that a bigger
  wave is not automatically "harder" (it can make the AI gather longer before
  attacking). These are warnings, never pass/fail.

The structural check is what makes the scaler safe to run automatically; the
advisory notes are what the UI shows the user before they commit.
"""
from dataclasses import dataclass, field

import ai_disasm
import ai_asm


@dataclass
class Validation:
    ok: bool
    reason: str = ''
    warnings: list = field(default_factory=list)      # advisory strings


def validate_control_flow(orig_instrs, edited_instrs, data, entry_offset,
                          base=0x9000):
    """Assemble edited_instrs, re-decode from the (remapped) entry, and compare
    structure to orig_instrs. `entry_offset` is the script's real entry - it is
    NOT always the lowest address (code can sit before it, reached by a backward
    jump), so tracing must start there, not at instrs[0]. Returns Validation."""
    if len(edited_instrs) != len(orig_instrs):
        return Validation(False, 'instruction count changed')
    # argument range check
    for ins in edited_instrs:
        for a in ins.args:
            if a.size == 1 and not (0 <= a.value <= 0xFF):
                return Validation(False, 'byte arg out of range at 0x%x'
                                  % ins.address)
            if a.size == 2 and not (0 <= a.value <= 0xFFFF):
                return Validation(False, 'word arg out of range at 0x%x'
                                  % ins.address)
    try:
        code, amap = ai_asm.assemble(edited_instrs, base, data)
    except KeyError as e:
        return Validation(False, 'jump target lost: %s' % e)
    buf = bytes(base) + code
    if entry_offset not in amap:
        return Validation(False, 'entry offset not in assembled set')
    entry_new = amap[entry_offset]
    ok, info = ai_disasm.trace_reachable(buf, entry_new, base + len(code))
    if not ok:
        return Validation(False, 'edited script does not re-decode: %s'
                          % info.get('error'))
    new = [ai_disasm.decode_one(buf, p) for p in sorted(info['instr_starts'])]
    if len(new) != len(orig_instrs):
        return Validation(False, 'reachable count changed after edit')
    for a, b in zip(new, orig_instrs):
        if a.opcode != b.opcode:
            return Validation(False, 'opcode sequence changed at 0x%x'
                              % a.address)
    return Validation(True)


def advisory_notes(script_id, changes, usage=None):
    """Non-blocking dependency hints for the UI."""
    notes = []
    if usage and len(usage.get(script_id, [])) > 1:
        ms = sorted(set(u[0] for u in usage[script_id]))
        notes.append('SHARED: %s is run by %d missions (%s) - editing it '
                     'changes all of them; clone for this mission instead.'
                     % (script_id, len(ms), ', '.join(ms[:4])))
    grew = [c for c in changes if c[1] in ('attack_add', 'easy_attack')
            and c[4] > c[3]]
    if grew:
        notes.append('CONSEQUENCE (approx): %d attack-wave counts increased. '
                     'A bigger wave needs more supply/production time, so the '
                     'AI may attack LATER - verify max_force/supply and the '
                     'delay multiplier, do not assume "bigger = harder".'
                     % len(grew))
    return notes


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import ai_bin
    import ai_scaler
    bw = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    sid = sys.argv[2] if len(sys.argv) > 2 else 'Ter3'
    files = ai_bin.load_from_chain(mpq.MpqChain(bw))
    f = files['aiscript.bin']
    e = f.by_id()[sid]
    _, info = ai_disasm.trace_reachable(f.data, e.offset, f.table_offset)
    instrs = [ai_disasm.decode_one(f.data, p)
              for p in sorted(info['instr_starts'])]
    edited, changes = ai_scaler.scale_instructions(instrs, ai_scaler.Profile.named('hard'))
    v = validate_control_flow(instrs, edited, f.data, e.offset)
    print('%s: %d changes; structural %s %s'
          % (sid, len(changes), 'PASS' if v.ok else 'FAIL', v.reason))
    for n in advisory_notes(sid, changes):
        print('  note:', n)
