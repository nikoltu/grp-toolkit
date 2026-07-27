"""Corpus check for Stage 3: the CFG builder and semantic model run over every
AI script without error and produce consistent structure.

Inherits the disassembly oracle (build_cfg uses trace_reachable, so every block
boundary and edge target is a verified instruction start). This test additionally
asserts:
  * a CFG is built for every used script (no crash, entry block present),
  * every edge target is an existing block,
  * the semantic summary's counted instructions never exceed the script's
    reachable instruction count.

Reports aggregate behaviour stats (campaign scripts, total attack waves, loops).

    py test_ai_semantics.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import ai_bin                            # noqa: E402
import ai_disasm                         # noqa: E402
import ai_cfg                            # noqa: E402
import ai_semantics                      # noqa: E402


def main():
    need(BW, 'Brood War install')
    files = ai_bin.load_from_chain(mpq.MpqChain(BW))
    if not files:
        print('SKIP: no AI script files')
        sys.exit(77)
    ok = total = 0
    campaign = waves = loops = 0
    bad = []
    for source, f in sorted(files.items()):
        for e in f.entries:
            if not e.used:
                continue
            total += 1
            try:
                cfg = ai_cfg.build_cfg(f.data, e.offset, f.table_offset)
                # every edge target must be a real block
                edges_ok = all(t in cfg.blocks
                               for b in cfg.blocks.values() for _, t in b.succ)
                _, info = ai_disasm.trace_reachable(f.data, e.offset,
                                                    f.table_offset)
                instrs = [ai_disasm.decode_one(f.data, p)
                          for p in sorted(info['instr_starts'])]
                s = ai_semantics.summarize(instrs, e.fourcc, source,
                                           loops=cfg.loops)
                counted = (len(s.production) + len(s.tech) + len(s.defence)
                           + len(s.economy)
                           + sum(len(w) for w in s.attack_waves))
                if (cfg.entry in cfg.blocks and edges_ok
                        and counted <= len(instrs)):
                    ok += 1
                    if s.is_campaign:
                        campaign += 1
                    waves += len(s.attack_waves)
                    loops += cfg.loops
                else:
                    bad.append(e.fourcc)
            except Exception as ex:               # noqa: BLE001
                bad.append('%s:%s' % (e.fourcc, ex))
    rc = report('ai: CFG + semantics over corpus', ok, total,
                '(%d campaign, %d attack waves, %d loops; bad=%s)'
                % (campaign, waves, loops, bad[:5] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
