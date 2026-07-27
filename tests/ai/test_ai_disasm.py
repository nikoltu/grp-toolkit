"""Corpus oracle for the AI-script disassembler.

Proves, against Brood War 1.16.1's real scripts\\aiscript.bin and
scripts\\bwscript.bin, that the opcode table + argument sizes are correct - the
same way VP8's "every residual partition ends exactly on its boundary" proves
its bit reader: from each script's entry offset we follow control flow (jumps,
calls, branches) and require

  * every reached byte to decode to a valid opcode with in-range arguments, and
  * every jump / call / branch target to land EXACTLY on an instruction
    boundary (never mid-instruction).

One wrong argument size would shift everything after it and drop a jump target
off a boundary, so 0 bad targets across ~1000 targets is a statement about the
whole table. Measured 2026-07: aiscript 137 scripts / 15319 instr / 937 targets,
bwscript 156 scripts / 7628 instr / 131 targets, 0 bad.

    py test_ai_disasm.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import ai_bin                            # noqa: E402
import ai_disasm                         # noqa: E402


def main():
    need(BW, 'Brood War install')
    need(os.path.join(BW, 'StarDat.mpq'), 'StarDat.mpq')
    files = ai_bin.load_from_chain(mpq.MpqChain(BW))
    if not files:
        print('SKIP: no AI script files found in the MPQ chain')
        sys.exit(77)
    ok_files = 0
    total_files = 0
    detail = []
    for source, f in sorted(files.items()):
        total_files += 1
        ok, info = ai_disasm.coverage(f)
        n_scr = info.get('n_scripts', 0)
        n_ins = info.get('n_instructions', 0)
        n_bad = len(info.get('bad_targets', []))
        if ok:
            ok_files += 1
            detail.append('%s %d scr/%d instr' % (source, n_scr, n_ins))
        else:
            detail.append('%s FAIL %s (%s)' % (
                source, info.get('script', '?'),
                info.get('error', '%d bad targets' % n_bad)))
    rc = report('ai: disasm coverage (all targets on boundary)',
                ok_files, total_files, '(' + '; '.join(detail) + ')')
    sys.exit(rc)


if __name__ == '__main__':
    main()
