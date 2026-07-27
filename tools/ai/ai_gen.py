#!/usr/bin/env python3
"""Generator for StarCraft AI scripts - the compile side of the toolkit.

This is the *inverse direction* of ai_disasm/ai_bin: instead of reading a real
aiscript.bin into opcodes, it takes a high-level tactic description and emits a
byte-exact, disassembler-clean aiscript.bin (or merges new scripts into the
stock file). It is what a training-bot generator compiles down to.

Two layers, so that what is MEASURED stays separate from what is CONVENTION:

  * Layer 1 - a symbolic assembler (`layout_script`, `build_bin`, `merge_into`).
    Steps are `(opcode_name, arg, ...)` tuples plus `('label', name)` markers;
    an address-typed argument is a label NAME (str) resolved to an absolute file
    offset in a two-pass layout. Every non-address argument is the raw numeric
    bytecode value. This layer is fully general and is the byte-verifiable part:
    generate -> ai_bin.parse -> ai_disasm.coverage must be CLEAN, and
    ai_asm.encode_instruction must round-trip every instruction we emitted. See
    tests/test_ai_gen.py.

  * Layer 2 - `Tactic`, a thin convenience builder that composes common bot
    patterns (setup, build order, adaptation branches, attack waves, defence)
    into Layer-1 steps. It adds no new encoding - it only sequences opcodes -
    so it inherits Layer 1's byte guarantee.

DELIBERATELY OUT OF SCOPE (and why): unit/building/upgrade/tech NAMES are not
resolved here. Those map to numeric ids through stat_txt.tbl / units.dat, which
are install-specific; baking a name table from memory would violate "measure,
never assume". The numeric id IS the bytecode value, so the generator encodes
it directly; a name->id resolver belongs in the browser UI, where the open
MPQ's real string table is available and measured.

Non-destructive by design: `merge_into` keeps every existing script's bytes
verbatim (existing jump targets are absolute offsets into the unchanged region,
so they stay valid) and appends new code + new table entries. That is the mod
path - the engine reads our aiscript.bin as the whole file, so it must still
contain all 293 stock scripts, not just the new bots.
"""
import struct

from ai_opcodes import OPCODE_BY_NAME


class AiGenError(Exception):
    pass


# argument types that carry a jump target (a label name in a generator step)
_ADDRESS_TYPES = frozenset(('address',))


def _arg_bytes(typ, size, value, labels):
    """Encode one argument to bytes. Address args resolve a label name through
    `labels`; string args accept str/bytes and get a null terminator; the rest
    are little-endian at their declared width."""
    if typ in _ADDRESS_TYPES:
        if not isinstance(value, str):
            raise AiGenError('address arg must be a label name, got %r' % (value,))
        if value not in labels:
            raise AiGenError('undefined label %r' % value)
        return struct.pack('<H', labels[value] & 0xFFFF)
    if size < 0:                                   # variable: string
        b = value.encode('latin1') if isinstance(value, str) else bytes(value)
        return b + b'\x00'
    if size == 1:
        return struct.pack('<B', int(value) & 0xFF)
    if size == 2:
        return struct.pack('<H', int(value) & 0xFFFF)
    if size == 4:
        return struct.pack('<I', int(value) & 0xFFFFFFFF)
    raise AiGenError('bad arg size %d' % size)


def _op_size(opname, args):
    """On-disk size of one op (1 opcode byte + arguments). Address args are
    always 2 bytes regardless of the (still unresolved) target, so sizes are
    computable before label resolution. String args depend only on content."""
    spec = OPCODE_BY_NAME.get(opname)
    if spec is None:
        raise AiGenError('unknown opcode name %r' % opname)
    if len(args) != len(spec.args):
        raise AiGenError('%s takes %d args, got %d'
                         % (opname, len(spec.args), len(args)))
    size = 1
    for (typ, sz), val in zip(spec.args, args):
        if sz < 0:
            b = val.encode('latin1') if isinstance(val, str) else bytes(val)
            size += len(b) + 1
        else:
            size += sz
    return size


def layout_script(steps, base_offset):
    """Two-pass layout of one script's steps at `base_offset`.

    `steps` is a list where each item is either `('label', name)` or
    `(opcode_name, *args)`. Returns (code_bytes, labels) where labels maps every
    defined label name to its absolute file offset. Address arguments in ops are
    label names, resolved in the second pass."""
    # pass 1: assign an absolute offset to every label
    labels = {}
    pos = base_offset
    for step in steps:
        if step[0] == 'label':
            name = step[1]
            if name in labels:
                raise AiGenError('duplicate label %r' % name)
            labels[name] = pos
        else:
            pos += _op_size(step[0], list(step[1:]))
    # pass 2: emit bytes, resolving address args
    out = bytearray()
    for step in steps:
        if step[0] == 'label':
            continue
        opname = step[0]
        args = list(step[1:])
        spec = OPCODE_BY_NAME[opname]
        out.append(spec.opcode)
        for (typ, sz), val in zip(spec.args, args):
            out += _arg_bytes(typ, sz, val, labels)
    return bytes(out), labels


def _norm_script(s):
    """Accept a Tactic or a dict; return (id_bytes, string_id, flags, steps)."""
    if isinstance(s, Tactic):
        s = s.to_dict()
    sid = s['id']
    if isinstance(sid, str):
        sid = sid.encode('latin1')
    if len(sid) != 4:
        raise AiGenError('script id must be 4 bytes, got %r' % (s['id'],))
    return sid, int(s.get('name', 0)), int(s.get('flags', 0)), s['code']


def _pack_entry(sid, offset, string_id, flags):
    return sid + struct.pack('<III', offset, string_id, flags)


def build_bin(scripts, base_offset=4):
    """Build a standalone aiscript.bin from scratch.

    `scripts` is a list of Tactic or dicts {id, name?, flags?, code}. Layout:
      [0:4]              u32 table_offset
      [4:table_offset]   each script's code, contiguous
      [table_offset:]    16-byte entries (id, offset, string_id, flags) + a
                         zeroed terminator id.
    Returns the file bytes. Labels are script-local; a jump target must be a
    label defined within the same script."""
    code = bytearray(b'\x00' * base_offset)       # room for the length word
    entries = []
    for s in scripts:
        sid, string_id, flags, steps = _norm_script(s)
        start = len(code)
        body, _ = layout_script(steps, start)
        code += body
        entries.append((sid, start, string_id, flags))
    table_offset = len(code)
    out = bytearray(code)
    for sid, off, string_id, flags in entries:
        out += _pack_entry(sid, off, string_id, flags)
    out += b'\x00\x00\x00\x00'                     # terminator id
    struct.pack_into('<I', out, 0, table_offset)
    return bytes(out)


def merge_into(base_bytes, scripts):
    """Append new scripts to an existing aiscript.bin WITHOUT disturbing it.

    Every existing script keeps its exact bytes (its jump targets are absolute
    offsets into the unchanged [4, old_table_offset) region), so this is safe to
    ship as a loose data/scripts/aiscript.bin override: the file still contains
    all stock scripts plus the new bots.

    New code is inserted at the old table position (shifting the table later);
    new 16-byte entries are appended after the existing ones. Returns the merged
    file bytes. Raises on a duplicate id (the launcher/engine would see two
    entries with the same FourCC)."""
    import ai_bin
    base = ai_bin.parse(base_bytes, ai_bin.AISCRIPT)
    old_table = base.table_offset
    existing_ids = {e.id for e in base.entries}

    # new code starts where the old table was; existing offsets are untouched
    new_code = bytearray()
    new_entries = []
    for s in scripts:
        sid, string_id, flags, steps = _norm_script(s)
        if sid in existing_ids:
            raise AiGenError('id %r already exists in the base file' % sid)
        existing_ids.add(sid)
        start = old_table + len(new_code)
        body, _ = layout_script(steps, start)
        new_code += body
        new_entries.append((sid, start, string_id, flags))

    new_table = old_table + len(new_code)
    out = bytearray(base_bytes[:old_table])        # verbatim code region
    out += new_code
    # rebuild the full entry table: existing (re-encoded identically) + new
    for e in base.entries:
        out += _pack_entry(e.id, e.offset, e.string_id, e.flags)
    for sid, off, string_id, flags in new_entries:
        out += _pack_entry(sid, off, string_id, flags)
    out += b'\x00\x00\x00\x00'
    struct.pack_into('<I', out, 0, new_table)
    return bytes(out)


# --------------------------------------------------------------------------
# Layer 2: the tactic builder. Pure sequencing of Layer-1 steps - no new bytes.
# --------------------------------------------------------------------------

# comparison codes for if_dif (compare arg). Measured semantics are the engine's;
# these names are the community convention and are applied, not derived.
CMP_GREATER = 0
CMP_LESS = 1
CMP_EQUAL = 2

# defence direction -> build/use opcode names (the 4 defence axes in the registry)
_DEF_BUILD = {'gg': 'defensebuild_gg', 'ag': 'defensebuild_ag',
              'ga': 'defensebuild_ga', 'aa': 'defensebuild_aa'}
_DEF_USE = {'gg': 'defenseuse_gg', 'ag': 'defenseuse_ag',
            'ga': 'defenseuse_ga', 'aa': 'defenseuse_aa'}


class Tactic:
    """Fluent builder for one bot script. Every method appends Layer-1 steps and
    returns self, so a build order reads top-to-bottom. Numeric ids are the raw
    bytecode values (see the module docstring on name resolution)."""

    def __init__(self, script_id, name=0, flags=0):
        self.id = script_id
        self.name = name
        self.flags = flags
        self.steps = []

    # -- raw escape hatch + labels/jumps -----------------------------------
    def raw(self, opname, *args):
        self.steps.append((opname,) + args)
        return self

    def label(self, name):
        self.steps.append(('label', name))
        return self

    def goto(self, label):
        return self.raw('goto', label)

    def stop(self):
        return self.raw('stop')

    def wait(self, ticks):
        return self.raw('wait', ticks)

    # -- setup -------------------------------------------------------------
    def setup(self, campaign=False, area_town=True, farms='timing',
              transports=False):
        """Standard town-management preamble. `farms` in {'timing','notiming'};
        transports=False emits transports_off (most melee bots want that)."""
        if campaign:
            self.raw('start_campaign')
        self.raw('start_town')
        if area_town:
            self.raw('start_areatown')
        if farms == 'timing':
            self.raw('farms_timing')
        elif farms == 'notiming':
            self.raw('farms_notiming')
        if not transports:
            self.raw('transports_off')
        return self

    # -- build order (numeric ids) -----------------------------------------
    def build(self, count, building_id, priority=0):
        return self.raw('build', count, building_id, priority)

    def build_needed(self, count, building_id):
        return self.raw('player_need', count, building_id)

    def train(self, count, military_id):
        return self.raw('train', count, military_id)

    def wait_build(self, count, building_id):
        return self.raw('wait_build', count, building_id)

    def wait_train(self, count, unit_id):
        return self.raw('wait_train', count, unit_id)

    def upgrade(self, count, upgrade_id, priority=0):
        return self.raw('upgrade', count, upgrade_id, priority)

    def tech(self, tech_id, priority=0):
        return self.raw('tech', tech_id, priority)

    def define_max(self, count, unit_id):
        return self.raw('define_max', count, unit_id)

    # -- attack composition ------------------------------------------------
    def attack_wave(self, units):
        """units: iterable of (count, military_id). Clears the attack party,
        adds each group, prepares and launches."""
        self.raw('attack_clear')
        for count, mil in units:
            self.raw('attack_add', count, mil)
        self.raw('attack_prepare')
        self.raw('attack_do')
        return self

    # -- defence -----------------------------------------------------------
    def defense_build(self, axis, count, military_id):
        return self.raw(_DEF_BUILD[axis], count, military_id)

    def defense_use(self, axis, count, military_id):
        return self.raw(_DEF_USE[axis], count, military_id)

    # -- adaptation branches (the training part) ---------------------------
    def on_enemy_unit(self, unit_id, goto_label):
        """Jump if the enemy commands >=1 of unit_id (enemyowns_jump)."""
        return self.raw('enemyowns_jump', unit_id, goto_label)

    def on_owned_unit(self, unit_id, goto_label):
        return self.raw('if_owned', unit_id, goto_label)

    def on_time(self, ticks, goto_label):
        return self.raw('time_jump', ticks, goto_label)

    def on_chance(self, percent, goto_label):
        return self.raw('random_jump', percent, goto_label)

    def on_resources(self, minerals, gas, goto_label):
        return self.raw('resources_jump', minerals, gas, goto_label)

    def on_enemy_resources(self, minerals, gas, goto_label):
        return self.raw('enemyresources_jump', minerals, gas, goto_label)

    def on_difficulty(self, compare, value, goto_label):
        return self.raw('if_dif', compare, value, goto_label)

    def on_attacked(self, goto_label):
        return self.raw('panic', goto_label)

    def on_enemy_reachable_ground(self, goto_label):
        return self.raw('groundmap_jump', goto_label)

    # -- serialise ---------------------------------------------------------
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'flags': self.flags,
                'code': list(self.steps)}


# --------------------------------------------------------------------------
# self-check: build a tiny bot, round-trip it through the disassembler.
# --------------------------------------------------------------------------
if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    import ai_bin
    import ai_disasm

    # a small adaptive bot: expand, build a barracks-equivalent (id given
    # numerically), then loop watching for an enemy air unit to switch to a
    # ground-to-air defence, else keep sending attack waves.
    bot = (Tactic('Bot1', name=0, flags=0)
           .setup(farms='timing', transports=False)
           .build(1, 106, 0)               # 106 = some building id (numeric)
           .train(6, 0)                    # 0 = some military-group id
           .label('main')
           .on_enemy_unit(9, 'antiair')    # enemy commands unit 9 -> antiair
           .on_time(3600, 'push')          # after a while -> push
           .wait(300)
           .goto('main')
           .label('antiair')
           .defense_build('ga', 4, 0)
           .goto('push')
           .label('push')
           .attack_wave([(12, 0)])
           .wait(600)
           .goto('main'))

    data = build_bin([bot])
    f = ai_bin.parse(data, ai_bin.AISCRIPT)
    ok, info = ai_disasm.coverage(f)
    print('standalone: %d bytes, table@0x%x, scripts=%d, reachable=%d, %s'
          % (len(data), f.table_offset, info.get('n_scripts', 0),
             info.get('n_instructions', 0), 'CLEAN' if ok else 'DESYNC'))
    if not ok:
        print('   ', info.get('error') or info.get('bad_targets'))
        sys.exit(1)
    print('OK')
