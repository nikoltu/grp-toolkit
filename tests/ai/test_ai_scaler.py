"""Stage-5 oracle: scaling never corrupts a script.

Applies the 'brutal' difficulty profile (the most aggressive multipliers) to
EVERY script in aiscript.bin + bwscript.bin, then runs the structural validator:
re-assemble the scaled instructions, re-decode, and require the same opcode
sequence with all jumps still on instruction boundaries and args in range.

Because the scaler only changes count/duration values (never sizes or
addresses), a correct implementation cannot move an instruction or break a jump
- so 293/293 structural PASS is the proof that the transform is layout-safe. The
"is it actually harder" question is deliberately NOT tested (it is approximate;
the validator emits it as an advisory note, not a pass/fail).

    py test_ai_scaler.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import ai_bin                            # noqa: E402
import ai_disasm                         # noqa: E402
import ai_scaler                         # noqa: E402
import ai_validate                       # noqa: E402


def main():
    need(BW, 'Brood War install')
    files = ai_bin.load_from_chain(mpq.MpqChain(BW))
    if not files:
        print('SKIP: no AI script files')
        sys.exit(77)
    profile = ai_scaler.Profile.named('brutal')
    ok = total = 0
    changed_scripts = total_changes = 0
    bad = []
    for source, f in sorted(files.items()):
        for e in f.entries:
            if not e.used:
                continue
            total += 1
            _, info = ai_disasm.trace_reachable(f.data, e.offset, f.table_offset)
            instrs = [ai_disasm.decode_one(f.data, p)
                      for p in sorted(info['instr_starts'])]
            edited, changes = ai_scaler.scale_instructions(instrs, profile)
            v = ai_validate.validate_control_flow(instrs, edited, f.data, e.offset)
            if v.ok:
                ok += 1
                if changes:
                    changed_scripts += 1
                    total_changes += len(changes)
            else:
                bad.append('%s:%s' % (e.fourcc, v.reason))
    rc = report('ai: scaler is layout-safe (brutal)', ok, total,
                '(%d scripts scaled, %d value changes; bad=%s)'
                % (changed_scripts, total_changes, bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
