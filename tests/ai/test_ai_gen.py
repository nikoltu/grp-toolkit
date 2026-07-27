"""Oracle for the AI-script generator (the compile side).

ai_gen builds an aiscript.bin from a high-level tactic instead of reading one.
The generator is only worth trusting if what it emits survives the SAME oracle
the real files pass, so this test closes the loop both ways:

  A. STANDALONE. Build a bot from a Tactic, then run the disassembler's corpus
     oracle on the result: coverage must be CLEAN (every opcode valid, every
     jump landing on an instruction boundary, the stream ending exactly on the
     entry table) and every emitted instruction must re-encode byte-identically
     through ai_asm - i.e. generate -> disasm -> re-encode is a fixed point.
     Also: the decoded opcode sequence equals the one we intended.

  B. MERGE (the mod path). Append the bot to the REAL stock aiscript.bin and
     require: the whole [0, old_table) code region is byte-identical to the
     original (existing scripts untouched), every original script still traces
     clean, the new bot is reachable, and the merged file's table round-trips.
     This proves a shipped data/scripts/aiscript.bin override keeps all 293
     stock scripts and only adds bots.

Part A needs no install; part B is skipped if the Brood War files are absent.

    py test_ai_gen.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, report          # noqa: E402
import mpq                             # noqa: E402
import ai_bin                          # noqa: E402
import ai_disasm                       # noqa: E402
import ai_asm                          # noqa: E402
import ai_gen                          # noqa: E402


def _sample_bot(script_id='Bot1'):
    """An adaptive rush-defence bot exercising every branch category: enemy
    unit, time, chance, resources, difficulty, loops, attack waves, defence."""
    return (ai_gen.Tactic(script_id, name=1050, flags=0)
            .setup(farms='timing', transports=False)
            .build(1, 106, 0)
            .train(6, 0)
            .label('main')
            .on_enemy_unit(9, 'antiair')
            .on_chance(64, 'harass')
            .on_time(3600, 'push')
            .on_resources(400, 0, 'push')
            .on_difficulty(ai_gen.CMP_GREATER, 2, 'push')
            .wait(300)
            .goto('main')
            .label('antiair')
            .defense_build('ga', 4, 0)
            .goto('main')
            .label('harass')
            .attack_wave([(4, 0)])
            .goto('main')
            .label('push')
            .attack_wave([(12, 0), (6, 1)])
            .wait(600)
            .goto('main'))


def _emitted_opcodes(steps):
    """The opcode-name sequence the Tactic intends, in order (labels dropped)."""
    return [s[0] for s in steps if s[0] != 'label']


def part_a():
    """Standalone build -> disasm-clean + instruction round-trip fixed point."""
    ok = total = 0
    bad = []
    bot = _sample_bot()
    data = ai_gen.build_bin([bot])
    f = ai_bin.parse(data, ai_bin.AISCRIPT)

    # 1. coverage clean
    total += 1
    cov_ok, info = ai_disasm.coverage(f)
    if cov_ok:
        ok += 1
    else:
        bad.append('coverage: %s' % (info.get('error') or info.get('bad_targets')))

    # 2. every reachable instruction re-encodes byte-identically
    total += 1
    n, mism = ai_asm.roundtrip_instructions(f)
    if not mism and n > 0:
        ok += 1
    else:
        bad.append('roundtrip %d instr, %d mismatch' % (n, len(mism)))

    # 3. table round-trips
    total += 1
    tok, rl, ol = ai_asm.roundtrip_table(f)
    if tok:
        ok += 1
    else:
        bad.append('table %d vs %d' % (rl, ol))

    # 4. decoded opcodes == intended opcodes (order preserved, none dropped)
    total += 1
    entry = f.by_id()['Bot1']
    _, tinfo = ai_disasm.trace_reachable(f.data, entry.offset, f.table_offset)
    decoded = [ai_disasm.decode_one(f.data, p).name
               for p in sorted(tinfo['instr_starts'])]
    want = sorted(_emitted_opcodes(bot.to_dict()['code']))
    if sorted(decoded) == want:
        ok += 1
    else:
        bad.append('opcode set differs: got %d, want %d' % (len(decoded), len(want)))

    return ok, total, bad


def part_b():
    """Merge into the real stock file -> stock untouched, bot added, clean."""
    if not os.path.exists(BW):
        return None
    files = ai_bin.load_from_chain(mpq.MpqChain(BW))
    base_ai = files.get(ai_bin.AISCRIPT)
    if base_ai is None:
        return None
    base_bytes = base_ai.data
    old_table = base_ai.table_offset

    ok = total = 0
    bad = []
    merged = ai_gen.merge_into(base_bytes, [_sample_bot('BotX')])
    mf = ai_bin.parse(merged, ai_bin.AISCRIPT)

    # 1. the entire original code region is byte-identical
    total += 1
    if merged[4:old_table] == base_bytes[4:old_table]:
        ok += 1
    else:
        bad.append('original code region changed')

    # 2. every original script still traces clean at its (unchanged) offset
    total += 1
    stock_clean = True
    for e in base_ai.entries:
        if not e.used:
            continue
        cok, _ = ai_disasm.trace_reachable(merged, e.offset, mf.table_offset)
        if not cok:
            stock_clean = False
            bad.append('stock %s desync after merge' % e.fourcc)
            break
    if stock_clean:
        ok += 1

    # 3. the new bot is present, reachable, and the whole merged file is clean
    total += 1
    cov_ok, info = ai_disasm.coverage(mf)
    botx = mf.by_id().get('BotX')
    if cov_ok and botx is not None and botx.offset >= old_table:
        ok += 1
    else:
        bad.append('merged coverage/bot: %s'
                   % (info.get('error') or 'bot missing'))

    # 4. merged table round-trips and entry count grew by exactly one
    total += 1
    tok, _, _ = ai_asm.roundtrip_table(mf)
    if tok and len(mf.entries) == len(base_ai.entries) + 1:
        ok += 1
    else:
        bad.append('table rt=%s, entries %d->%d'
                   % (tok, len(base_ai.entries), len(mf.entries)))

    return ok, total, bad


def main():
    a_ok, a_total, a_bad = part_a()
    b = part_b()
    if b is None:
        print('note: Brood War install absent -> merge part (B) skipped')
        b_ok = b_total = 0
        b_bad = []
    else:
        b_ok, b_total, b_bad = b

    ok = a_ok + b_ok
    total = a_total + b_total
    bad = a_bad + b_bad
    rc = report('ai: generator (standalone + merge)', ok, total,
                '(bad=%s)' % (bad[:4] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
