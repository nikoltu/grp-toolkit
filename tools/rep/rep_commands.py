#!/usr/bin/env python3
"""Disassemble a replay's command (player-input) stream.

STREAM FRAMING - MEASURED (rep_read gives the decompressed command section):
    a sequence of frame-blocks, each:
        u32 frame, u8 blockLength, then blockLength bytes of commands.
    a command = u8 playerId, u8 commandId, args...   (many per block, same frame)
Verified independently: every block boundary lands cleanly, frames rise
monotonically, and each section is consumed to the exact byte on all of V's
replays.

COMMAND TABLE - the argument SIZES were MEASURED by a tiling constraint solve
over ~107 000 blocks (a command's size is fixed, so the size that makes every
block tile exactly is forced), then found to match the community table byte for
byte. The size table is therefore independently derived here; the NAMES are the
borrowed format-data (screp, github.com/icza/screp, MIT (c) Andras Belicza -
attributed like the PyMS AI/iscript opcode names). Two lessons the measurement
caught, exactly the class CLAUDE.md warns about: 0x2f is Lift-Off not Tech, and
0x35 is Building-Morph not Stim - guessing from memory would have desynced.

Coverage oracle (tests/rep/test_rep.py): every block consumes exactly to its
length and the whole section to its end - a wrong size desyncs a block at once,
so a clean pass over the whole corpus proves the table.

Variable-length: the Select families - classic 0x09/0x0a/0x0b use 2-byte unit
tags (1 + n*2), the SC:R "121" ones 0x63/0x64/0x65 use 4-byte tags (1 + n*4).

No third-party libraries.
"""
import os
import sys
import struct
from dataclasses import dataclass

SEL2 = {0x09: 'select', 0x0A: 'select_add', 0x0B: 'select_remove'}
SEL4 = {0x63: 'select_121', 0x64: 'select_add_121', 0x65: 'select_remove_121'}

# id -> (name, fixed arg size). Select families are variable (handled below);
# they carry size -1 here just to be listed as known ids.
CMD = {
    0x05: ('keep_alive', 0),
    0x06: ('save_game', -2),            # u32 + null-terminated name
    0x07: ('load_game', -2),
    0x08: ('restart_game', 0),
    0x09: ('select', -1), 0x0A: ('select_add', -1), 0x0B: ('select_remove', -1),
    0x0C: ('build', 7),                 # u8 order, u16 x, u16 y, u16 unitType
    0x0D: ('vision', 2),
    0x0E: ('alliance', 8),
    0x0F: ('game_speed', 1),
    0x10: ('pause', 0),
    0x11: ('resume', 0),
    0x12: ('cheat', 4),
    0x13: ('hotkey', 2),                # u8 type(0 assign / 1 select), u8 group
    0x14: ('right_click', 9),           # u16 x, u16 y, u16 unitTag, u16 unitType, u8 queued
    0x15: ('targeted_order', 10),       # + u8 order
    0x18: ('cancel_build', 0),
    0x19: ('cancel_morph', 0),
    0x1A: ('stop', 1),
    0x1B: ('carrier_stop', 0),
    0x1C: ('reaver_stop', 0),
    0x1D: ('order_nothing', 0),
    0x1E: ('return_cargo', 1),
    0x1F: ('train', 2),                 # u16 unitType
    0x20: ('cancel_train', 2),
    0x21: ('cloak', 1),
    0x22: ('decloak', 1),
    0x23: ('unit_morph', 2),            # u16 unitType (zerg / larva morph)
    0x25: ('unsiege', 1),
    0x26: ('siege', 1),
    0x27: ('train_fighter', 0),         # build interceptor / scarab
    0x28: ('unload_all', 1),
    0x29: ('unload', 2),
    0x2A: ('merge_archon', 0),
    0x2B: ('hold_position', 1),
    0x2C: ('burrow', 1),
    0x2D: ('unburrow', 1),
    0x2E: ('cancel_nuke', 0),
    0x2F: ('lift_off', 4),              # u16 x, u16 y
    0x30: ('tech', 1),                  # u8 techType (research)
    0x31: ('cancel_tech', 0),
    0x32: ('upgrade', 1),               # u8 upgradeType
    0x33: ('cancel_upgrade', 0),
    0x34: ('cancel_addon', 0),
    0x35: ('building_morph', 2),        # u16 unitType (terran/protoss building)
    0x36: ('stim', 0),
    0x37: ('sync', 6),
    0x38: ('voice_enable', 0), 0x39: ('voice_disable', 0),
    0x3A: ('voice_squelch', 1), 0x3B: ('voice_unsquelch', 1),
    0x3C: ('start_game', 0), 0x3D: ('download_pct', 1),
    0x3E: ('change_game_slot', 5), 0x3F: ('new_net_player', 7),
    0x40: ('joined_game', 17), 0x41: ('change_race', 2),
    0x42: ('team_game_team', 1), 0x43: ('ums_team', 1),
    0x44: ('melee_team', 2), 0x45: ('swap_players', 2), 0x48: ('saved_data', 12),
    0x54: ('briefing_start', 0), 0x55: ('latency', 1), 0x56: ('replay_speed', 9),
    0x57: ('leave_game', 1),            # u8 reason
    0x58: ('minimap_ping', 4),          # u16 x, u16 y
    0x5A: ('merge_dark_archon', 0), 0x5B: ('make_game_public', 0),
    0x5C: ('chat', 81),                 # u8 sender + 80-byte message
    0x60: ('right_click_121', 11), 0x61: ('targeted_order_121', 12),
    0x62: ('unload_121', 4),
    0x63: ('select_121', -1), 0x64: ('select_add_121', -1), 0x65: ('select_remove_121', -1),
}

# commands that request producing/teching/upgrading something (for analysis)
PRODUCE = {'build', 'train', 'unit_morph', 'building_morph', 'train_fighter'}
ORDER_CMDS = {'right_click', 'targeted_order', 'right_click_121', 'targeted_order_121'}


@dataclass
class Command:
    frame: int
    player: int
    cmd_id: int
    name: str
    args: bytes

    def u16(self, o):
        return struct.unpack_from('<H', self.args, o)[0] if o + 2 <= len(self.args) else None

    @property
    def unit_type(self):
        """The produced/target unit type for build/train/morph commands."""
        if self.name in ('train', 'unit_morph', 'building_morph', 'cancel_train'):
            return self.u16(0)
        if self.name == 'build':                # u8 order, u16 x, u16 y, u16 unitType
            return self.u16(5)
        return None

    @property
    def position(self):
        if self.name == 'build':
            return (self.u16(1), self.u16(3))   # x, y
        if self.name in ('right_click', 'targeted_order', 'right_click_121',
                         'targeted_order_121', 'minimap_ping', 'lift_off'):
            return (self.u16(0), self.u16(2))
        return None


def _sel_size(cmd_id, body, ao):
    per = 2 if cmd_id in SEL2 else 4
    return 1 + body[ao] * per


def _var_size(cmd_id, body, ao):
    if cmd_id in SEL2 or cmd_id in SEL4:
        return _sel_size(cmd_id, body, ao)
    if cmd_id in (0x06, 0x07):              # save/load: u32 + null-terminated name
        e = body.index(0, ao + 4)
        return (e - ao) + 1
    raise KeyError(cmd_id)


def decode_block(frame, body):
    """Yield Command for one frame-block body; raise on unknown id / overrun."""
    o, n = 0, len(body)
    while o < n:
        if o + 2 > n:
            raise ValueError('dangling byte at frame %d' % frame)
        player = body[o]
        cmd_id = body[o + 1]
        if cmd_id not in CMD:
            raise ValueError('unknown command 0x%02x (frame %d, off %d)' % (cmd_id, frame, o))
        name, size = CMD[cmd_id]
        ao = o + 2
        if size < 0:
            size = _var_size(cmd_id, body, ao)
        if ao + size > n:
            raise ValueError('command 0x%02x overruns block (frame %d)' % (cmd_id, frame))
        yield Command(frame, player, cmd_id, name, bytes(body[ao:ao + size]))
        o = ao + size


def decode(commands):
    """Decode the whole command section -> (list[Command], bytes_consumed)."""
    out = []
    o, n = 0, len(commands)
    while o + 5 <= n:
        frame = struct.unpack_from('<I', commands, o)[0]
        ln = commands[o + 4]
        o += 5
        if o + ln > n:
            raise ValueError('block truncated at frame %d' % frame)
        out.extend(decode_block(frame, commands[o:o + ln]))
        o += ln
    return out, o


def decode_blocks(commands):
    """Like decode() but preserves frame-block grouping: yields (frame, [Command])."""
    o, n = 0, len(commands)
    while o + 5 <= n:
        frame = struct.unpack_from('<I', commands, o)[0]
        ln = commands[o + 4]
        o += 5
        yield frame, list(decode_block(frame, commands[o:o + ln]))
        o += ln


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rep_read
    for path in sys.argv[1:]:
        r = rep_read.load(path)
        cmds, consumed = decode(r.commands)
        counts = {}
        for c in cmds:
            counts[c.name] = counts.get(c.name, 0) + 1
        print('%s: %d commands, consumed %d/%d %s'
              % (os.path.basename(path), len(cmds), consumed, len(r.commands),
                 'OK' if consumed == len(r.commands) else 'SHORT'))
        print('   ', ', '.join('%s=%d' % kv for kv in
                               sorted(counts.items(), key=lambda kv: -kv[1])[:12]))
