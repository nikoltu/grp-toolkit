#!/usr/bin/env python3
"""CHK (StarCraft scenario) reader - only what the AI-mission linkage needs.

A .scm/.scx map is an MPQ; the scenario lives in it as staredit\\scenario.chk.
The CHK itself is a flat stream of sections:  4-char name + i32 length + data.
A section name may repeat; the LAST instance wins (StarCraft applies them in
order). All measured against maps\\campaign\\(1)Enslavers01.scm (BW 1.16.1).

Sections decoded here:
  STR   u16 count, count x u16 offset (1-based; offset from section start),
        then null-terminated strings.
  MRGN  locations, 20 bytes each: u32 left, top, right, bottom; u16 name
        (STR index); u16 elevation flags.
  OWNR  12 bytes, one controller byte per slot (raw kept; see OWNR_LABEL).
  SIDE  12 bytes, one race byte per slot (0 Zerg, 1 Terran, 2 Protoss, ...).
  TRIG  2400-byte triggers: conditions[16] x 20 @0, actions[64] x 32 @320,
        u32 flags @2368, players[27] @2372 (slot != 0 == the trigger runs for
        that slot), current_action @2399.
        Action (32 B): u32 location @0 (1-based MRGN), u32 string @4,
        u32 wav @8, u32 time @12, u32 player/group @16, u32 fourcc @20 (AI
        script id as 4 bytes), u16 unit_type @24, u8 action_id @26, u8 type @27,
        u8 flags @28...

Only structure is decoded; nothing is interpreted beyond what is measured.
"""
import struct
from dataclasses import dataclass, field

TRIGGER_SIZE = 2400
COND_SIZE = 20
ACTION_SIZE = 32
N_CONDITIONS = 16
N_ACTIONS = 64
ACTIONS_OFFSET = N_CONDITIONS * COND_SIZE          # 320
PLAYERS_OFFSET = ACTIONS_OFFSET + N_ACTIONS * ACTION_SIZE + 4   # 2372

# action_id values relevant to AI scripts
ACT_RUN_AI_SCRIPT = 15
ACT_RUN_AI_SCRIPT_AT_LOCATION = 16

# Trigger CONDITION types (borrowed nomenclature, community/PyMS CHK spec). A
# condition's type byte sits at +15 in its 20-byte record; these are what a
# mission's victory/defeat triggers test.
COND_TYPES = {
    0: 'NoCondition', 1: 'CountdownTimer', 2: 'Command', 3: 'Bring',
    4: 'Accumulate', 5: 'Kills', 6: 'CommandTheMost', 7: 'CommandsTheMostAt',
    8: 'MostKills', 9: 'HighestScore', 10: 'MostResources', 11: 'Switch',
    12: 'ElapsedTime', 13: 'Never?', 14: 'Opponents', 15: 'Deaths',
    16: 'CommandTheLeast', 17: 'CommandsTheLeastAt', 18: 'LeastKills',
    19: 'LowestScore', 20: 'LeastResources', 21: 'Score', 22: 'Always',
    23: 'Never',
}
# comparison byte (+14) for numeric conditions
COMPARISON = {0: 'AtLeast', 1: 'AtMost', 10: 'Exactly'}

# OWNR controller byte -> best-effort label. Measured values on campaign maps
# are 5 and 6; the exact human/computer mapping is convention-sensitive, so the
# raw byte is always kept and this is only a hint (verify before relying on it).
OWNR_LABEL = {0: 'inactive', 1: 'computer_game', 2: 'occupied', 3: 'rescue',
              4: 'unused', 5: 'computer', 6: 'human', 7: 'neutral'}
SIDE_LABEL = {0: 'Zerg', 1: 'Terran', 2: 'Protoss', 3: 'Independent',
              4: 'Neutral', 5: 'UserSelect', 7: 'Inactive'}


@dataclass
class Location:
    index: int                   # 1-based (MRGN order)
    left: int
    top: int
    right: int
    bottom: int
    name_string: int
    elevation: int
    name: str = ''


@dataclass
class Action:
    index: int
    action_id: int
    location: int                # 1-based MRGN index (0 = none)
    string: int
    wav: int
    time: int
    player: int                  # group/player field (+16)
    fourcc: bytes                # +20 as 4 raw bytes (AI script id / number)
    unit_type: int
    raw: bytes = b''

    @property
    def is_ai_script(self):
        return self.action_id in (ACT_RUN_AI_SCRIPT,
                                  ACT_RUN_AI_SCRIPT_AT_LOCATION)

    @property
    def script_id(self):
        return self.fourcc.decode('latin1')


@dataclass
class Condition:
    index: int
    cond_type: int
    location: int                # 1-based MRGN (0 = none)
    player: int                  # group/player
    quantity: int
    unit_type: int
    comparison: int
    raw: bytes = b''

    @property
    def type_name(self):
        return COND_TYPES.get(self.cond_type, 'cond%d' % self.cond_type)

    @property
    def comparison_name(self):
        return COMPARISON.get(self.comparison, 'cmp%d' % self.comparison)


@dataclass
class Trigger:
    index: int
    actions: list = field(default_factory=list)      # list[Action]
    players: list = field(default_factory=list)       # slot indices (0..26) set
    conditions: list = field(default_factory=list)    # list[Condition]

    def has_action(self, action_id):
        return any(a.action_id == action_id for a in self.actions)


# MBRF (Mission Briefing) uses the SAME 2400-B trigger / 32-B action layout as
# TRIG, with its own action ids (measured against the campaign). The briefing is
# a SEQUENCE - actions run top to bottom, and Wait/PlayWAV/Transmission advance a
# clock by their `time` (ms). Transmission is the spoken line (text + wav + a
# duration); ShowPortrait sets which portrait is on screen (the speaker).
BRIEFING_ACTIONS = {
    0: 'NoAction', 1: 'Wait', 2: 'PlayWAV', 3: 'TextMessage',
    4: 'MissionObjectives', 5: 'ShowPortrait', 6: 'HidePortrait',
    7: 'DisplaySpeakingPortrait', 8: 'Transmission',
}
# actions whose `time` field advances the briefing clock (blocking duration)
BRIEFING_TIMED = {1, 2, 8}


@dataclass
class Chk:
    sections: dict               # {bytes name: bytes body} (last wins)
    strings_count: int = 0
    locations: list = field(default_factory=list)  # list[Location]
    triggers: list = field(default_factory=list)    # list[Trigger]
    briefings: list = field(default_factory=list)   # list[Trigger] (MBRF, ordered)
    owners: list = field(default_factory=list)
    sides: list = field(default_factory=list)
    units: list = field(default_factory=list)       # pre-placed: (unit_id, owner, x, y)

    def string(self, i):
        body = self.sections.get(b'STR ', b'')
        if not body or i < 1 or i > self.strings_count:
            return ''
        o = struct.unpack_from('<H', body, 2 + (i - 1) * 2)[0]
        e = body.find(b'\x00', o)
        if e < 0:
            e = len(body)
        return body[o:e].decode('latin1')

    def location_name(self, idx):
        if 1 <= idx <= len(self.locations):
            return self.locations[idx - 1].name
        return ''


def split_sections(chk_bytes):
    """{name: body} with last-instance-wins semantics."""
    secs = {}
    off = 0
    n = len(chk_bytes)
    while off + 8 <= n:
        name = chk_bytes[off:off + 4]
        ln = struct.unpack_from('<i', chk_bytes, off + 4)[0]
        off += 8
        if ln < 0:
            break
        secs[name] = chk_bytes[off:off + ln]
        off += ln
    return secs


def _parse_condition(body, base, idx):
    # 20 B: u32 location, u32 player, u32 quantity, u16 unit, u8 comparison,
    #        u8 condType, u8 resType, u8 flags, u16 mask
    loc, player, qty = struct.unpack_from('<3I', body, base)
    unit = struct.unpack_from('<H', body, base + 12)[0]
    comparison = body[base + 14]
    cond_type = body[base + 15]
    return Condition(index=idx, cond_type=cond_type, location=loc, player=player,
                     quantity=qty, unit_type=unit, comparison=comparison,
                     raw=body[base:base + COND_SIZE])


def _parse_action(body, base, idx):
    (loc, strn, wav, tm, player, fourcc_u32) = struct.unpack_from('<6I', body, base)
    unit_type = struct.unpack_from('<H', body, base + 24)[0]
    action_id = body[base + 26]
    return Action(index=idx, action_id=action_id, location=loc, string=strn,
                  wav=wav, time=tm, player=player,
                  fourcc=struct.pack('<I', fourcc_u32), unit_type=unit_type,
                  raw=body[base:base + ACTION_SIZE])


def parse(chk_bytes):
    secs = split_sections(chk_bytes)
    chk = Chk(sections=secs)
    strd = secs.get(b'STR ', b'')
    if len(strd) >= 2:
        chk.strings_count = struct.unpack_from('<H', strd, 0)[0]
    mrgn = secs.get(b'MRGN', b'')
    for i in range(len(mrgn) // 20):
        l, t, r, b, nm, el = struct.unpack_from('<4IHH', mrgn, i * 20)
        loc = Location(i + 1, l, t, r, b, nm, el)
        loc.name = chk.string(nm)
        chk.locations.append(loc)
    chk.owners = list(secs.get(b'OWNR', b'')[:12])
    chk.sides = list(secs.get(b'SIDE', b'')[:12])
    trig = secs.get(b'TRIG', b'')
    for t in range(len(trig) // TRIGGER_SIZE):
        tb = trig[t * TRIGGER_SIZE:(t + 1) * TRIGGER_SIZE]
        actions = []
        for a in range(N_ACTIONS):
            base = ACTIONS_OFFSET + a * ACTION_SIZE
            act = _parse_action(tb, base, a)
            if act.action_id != 0:
                actions.append(act)
        conditions = []
        for c in range(N_CONDITIONS):
            cond = _parse_condition(tb, c * COND_SIZE, c)
            if cond.cond_type != 0:
                conditions.append(cond)
        players = [i for i in range(27) if tb[PLAYERS_OFFSET + i] != 0]
        chk.triggers.append(Trigger(index=t, actions=actions, players=players,
                                    conditions=conditions))
    # MBRF - mission briefing (same layout; actions kept IN ORDER, they are a
    # timeline, not a set)
    mbrf = secs.get(b'MBRF', b'')
    for t in range(len(mbrf) // TRIGGER_SIZE):
        tb = mbrf[t * TRIGGER_SIZE:(t + 1) * TRIGGER_SIZE]
        actions = []
        for a in range(N_ACTIONS):
            base = ACTIONS_OFFSET + a * ACTION_SIZE
            act = _parse_action(tb, base, a)
            if act.action_id != 0:
                actions.append(act)
        chk.briefings.append(Trigger(index=t, actions=actions, players=[]))
    # UNIT - pre-placed units (36-byte records: unitId@8, owner@16, x@4, y@6)
    un = secs.get(b'UNIT', b'')
    for i in range(len(un) // 36):
        o = i * 36
        x, y = struct.unpack_from('<HH', un, o + 4)
        uid = struct.unpack_from('<H', un, o + 8)[0]
        owner = un[o + 16]
        chk.units.append((uid, owner, x, y))
    return chk


def read_scm(path):
    """Read a .scm/.scx (an MPQ) and parse its scenario.chk."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    arc = mpq.Mpq(path)
    for nm in ('staredit\\scenario.chk', 'staredit/scenario.chk'):
        try:
            return parse(arc.read(nm))
        except Exception:
            continue
    raise KeyError('scenario.chk not found in %s' % path)


if __name__ == '__main__':
    import sys
    chk = read_scm(sys.argv[1])
    print('%d sections, %d strings, %d locations, %d triggers'
          % (len(chk.sections), chk.strings_count, len(chk.locations),
             len(chk.triggers)))
    for tr in chk.triggers:
        for a in tr.actions:
            if a.is_ai_script:
                print('  trig %d players=%s  %s %r @loc %d (%s)'
                      % (tr.index, tr.players,
                         'run@loc' if a.action_id == 16 else 'run',
                         a.script_id, a.location, chk.location_name(a.location)))
