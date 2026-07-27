#!/usr/bin/env python3
"""Semantic model over a decoded AI script: turn the opcode stream into a
higher-level plan (production goals, tech, defence, attack waves) and an
"AI behaviour fingerprint". Purely derived from the instruction list + CFG; it
interprets opcode MEANING (which is the borrowed-data part), never re-measures
the format.

The categorisation is by opcode name, grouped the way the game's AI actually
uses them:
  production : build, train, define_max, wait_train, do_morph, create_unit
  tech       : tech, upgrade, wait_upgrades
  defence    : defensebuild_*, defenseuse_*, build_bunkers, build_turrets
  attack     : attack_add, easy_attack (accumulate) -> attack_prepare/do (wave)
  economy    : start_town, start_areatown, expand, get_oldpeons, farms_*, creep
  campaign   : start_campaign
"""
from dataclasses import dataclass, field, asdict

PRODUCTION = {'build', 'train', 'define_max', 'wait_train', 'do_morph',
              'create_unit', 'wait_buildstart', 'wait_build', 'player_need'}
TECH = {'tech', 'upgrade', 'wait_upgrades'}
DEFENCE = {'defensebuild_gg', 'defensebuild_ag', 'defensebuild_ga',
           'defensebuild_aa', 'defenseuse_gg', 'defenseuse_ag',
           'defenseuse_ga', 'defenseuse_aa', 'build_bunkers', 'build_turrets'}
ATTACK_ADD = {'attack_add', 'easy_attack'}
ATTACK_GO = {'attack_prepare', 'attack_do', 'attack_clear'}
ECONOMY = {'start_town', 'start_areatown', 'expand', 'get_oldpeons',
           'farms_timing', 'farms_notiming', 'creep', 'target_expansion'}


@dataclass
class Summary:
    script_id: str
    source: str
    is_campaign: bool = False
    towns: int = 0
    production: list = field(default_factory=list)   # [{op,args}]
    tech: list = field(default_factory=list)
    defence: list = field(default_factory=list)
    attack_waves: list = field(default_factory=list)  # [[member ops]]
    economy: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def fingerprint(self):
        return {
            'script_id': self.script_id,
            'campaign_mode': self.is_campaign,
            'towns': self.towns,
            'production_goals': len(self.production),
            'tech_goals': len(self.tech),
            'defence_rules': len(self.defence),
            'attack_waves': len(self.attack_waves),
        }


def _arg_summary(ins):
    return [(a.type, a.value) for a in ins.args]


def summarize(instrs, script_id='', source='', loops=0):
    """instrs: list[Instruction] in address order. Returns a Summary."""
    s = Summary(script_id=script_id, source=source)
    counts = {}
    wave = []
    for ins in instrs:
        n = ins.name
        counts[n] = counts.get(n, 0) + 1
        rec = {'op': n, 'addr': ins.address, 'args': _arg_summary(ins)}
        if n == 'start_campaign':
            s.is_campaign = True
        elif n in ('start_town', 'start_areatown'):
            s.towns += 1
            s.economy.append(rec)
        elif n in PRODUCTION:
            s.production.append(rec)
        elif n in TECH:
            s.tech.append(rec)
        elif n in DEFENCE:
            s.defence.append(rec)
        elif n in ECONOMY:
            s.economy.append(rec)
        elif n in ATTACK_ADD:
            wave.append(rec)
        elif n in ATTACK_GO:
            if n == 'attack_do' and wave:
                s.attack_waves.append(wave)
                wave = []
            elif n == 'attack_clear':
                wave = []
    if wave:
        s.attack_waves.append(wave)
    s.counts = counts
    s.counts['_loops'] = loops
    return s


def summarize_script(ai_file, entry, script_id=''):
    import ai_disasm
    import ai_cfg
    cfg = ai_cfg.build_cfg(ai_file.data, entry.offset, ai_file.table_offset)
    ok, info = ai_disasm.trace_reachable(ai_file.data, entry.offset,
                                         ai_file.table_offset)
    instrs = [ai_disasm.decode_one(ai_file.data, p)
              for p in sorted(info['instr_starts'])]
    return summarize(instrs, script_id or entry.fourcc, ai_file.source,
                     loops=cfg.loops)


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
        s = summarize_script(f, e, sid)
        import json
        print('fingerprint:', json.dumps(s.fingerprint()))
        print('production goals:', len(s.production),
              ' tech:', len(s.tech), ' defence:', len(s.defence),
              ' attack waves:', len(s.attack_waves))
        for i, w in enumerate(s.attack_waves):
            print('  wave %d: %s' % (i, [(r['op'],) + tuple(v for _, v in r['args']) for r in w]))
        break
