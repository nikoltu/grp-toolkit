#!/usr/bin/env python3
"""Difficulty scaler for AI scripts - the SEMANTIC, dependency-aware kind, not
"multiply every number".

What is scaled (the relatively-safe categories, spec proposal 14.1):
  attack_add / easy_attack count   (byte arg 0)   x wave_size
  defensebuild_* / defenseuse_*    (byte arg 0)   x defense
  define_max / wait_train count    (byte arg 0)   x production
  max_force                        (word)         x max_force
  wait                             (word)         x delay   (round; <1 keeps 1)

What is NEVER touched (spec 14.3): jump/call addresses, script FourCC, location
ids, unit/building/tech/upgrade ids, start_campaign / start_town, and every
opcode with an 'address' arg. Because argument sizes are invariant, changing a
count or duration never moves an instruction, so no jump ever needs relocation -
the scaler cannot corrupt control flow by construction, and ai_validate proves
it (re-decode stays clean).

IMPORTANT: this transforms the script's NUMBERS. Whether the result is actually
"harder" is a separate, approximate question (a bigger wave can also mean the AI
waits longer to gather it) - see ai_validate's consequence notes. This module
only does the safe numeric transform and reports what it changed.
"""
import copy
from dataclasses import dataclass

# opcodes whose byte arg 0 is a "count" we may scale, and by which knob
COUNT_OPS = {
    'attack_add': 'wave_size', 'easy_attack': 'wave_size',
    'defensebuild_gg': 'defense', 'defensebuild_ag': 'defense',
    'defensebuild_ga': 'defense', 'defensebuild_aa': 'defense',
    'defenseuse_gg': 'defense', 'defenseuse_ag': 'defense',
    'defenseuse_ga': 'defense', 'defenseuse_aa': 'defense',
    'define_max': 'production', 'wait_train': 'production',
}
WORD_OPS = {'max_force': 'max_force', 'wait': 'delay'}


@dataclass
class Profile:
    wave_size: float = 1.35
    defense: float = 1.20
    production: float = 1.20
    max_force: float = 1.25
    delay: float = 0.85              # <1 = faster (harder); wait shrinks

    @classmethod
    def named(cls, name):
        return {
            'off': cls(1, 1, 1, 1, 1),
            'hard': cls(),
            'brutal': cls(1.6, 1.4, 1.3, 1.5, 0.7),
        }.get(name, cls())


def _scale_byte(v, mul):
    return max(0, min(255, int(round(v * mul))))


def _scale_word(v, mul, keep_min1=False):
    r = int(round(v * mul))
    if keep_min1:
        r = max(1, r)
    return max(0, min(65535, r))


def scale_instructions(instrs, profile):
    """Return (new_instrs, changes[]). new_instrs is a deep copy with scaled
    args; changes is a list of (addr, op, arg_index, old, new)."""
    out = copy.deepcopy(instrs)
    changes = []
    for ins in out:
        if ins.name in COUNT_OPS and ins.args and ins.args[0].type == 'byte':
            mul = getattr(profile, COUNT_OPS[ins.name])
            old = ins.args[0].value
            new = _scale_byte(old, mul)
            if new != old:
                ins.args[0].value = new
                changes.append((ins.address, ins.name, 0, old, new))
        elif ins.name in WORD_OPS and ins.args and ins.args[0].type == 'word':
            knob = WORD_OPS[ins.name]
            mul = getattr(profile, knob)
            old = ins.args[0].value
            new = _scale_word(old, mul, keep_min1=(ins.name == 'wait'))
            if new != old:
                ins.args[0].value = new
                changes.append((ins.address, ins.name, 0, old, new))
    return out, changes


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import ai_bin
    import ai_disasm
    bw = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    sid = sys.argv[2] if len(sys.argv) > 2 else 'Ter3'
    prof = Profile.named(sys.argv[3] if len(sys.argv) > 3 else 'hard')
    files = ai_bin.load_from_chain(mpq.MpqChain(bw))
    for src, f in files.items():
        e = f.by_id().get(sid)
        if not e:
            continue
        _, info = ai_disasm.trace_reachable(f.data, e.offset, f.table_offset)
        instrs = [ai_disasm.decode_one(f.data, p)
                  for p in sorted(info['instr_starts'])]
        _, changes = scale_instructions(instrs, prof)
        print('%s: %d changes' % (sid, len(changes)))
        for addr, op, i, old, new in changes[:20]:
            print('  0x%05x %-14s %d -> %d' % (addr, op, old, new))
        break
