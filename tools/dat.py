#!/usr/bin/env python3
"""Reader/writer for StarCraft .dat tables (units.dat, weapons.dat).

A .dat is a STRUCT OF ARRAYS: for N entities, every property is stored as its
own contiguous array (all N flingy ids, then all N subunits, ...), NOT entity by
entity. Widths differ per property (u8/u16/u32) and a few properties cover only
a SUBSET of the entities (sounds only for real units, addon offsets only for
buildings), so the file is a concatenation of arrays of mixed length.

The field TABLE (order, width, count) is borrowed format data - the same status
as ai_opcodes (from PyMS) and the StormLib tables: there is no normative spec for
.dat, so the layout comes from the community reverse-engineering (DatEdit / PyMS).
But unlike a blind transcription, EVERY offset here is re-derived and checked:
tests/test_dat.py asserts the cumulative field offsets hit the four independently
MEASURED anchors from CLAUDE.md (hitpoints@3156, ready_sound@9312, portrait@14404,
group_flags@16684) and that the arrays sum to the exact file size (units 19876,
weapons 5460). A wrong width or count anywhere shifts a later anchor or misses the
total - so a clean oracle is a statement about the whole layout, not just one
field. That is what makes this "measured", not "assumed".

Fixed point: unit hitpoints are stored as 1/256 (display = raw >> 8); shields too.
Raw values are what is stored and edited; DISPLAY_SCALE marks the ones to divide
for a human view. Round-trip is byte-identical (write == read source), which the
oracle also proves - an editor built on it cannot corrupt an untouched field.
"""
import struct

# entity counts and the subset boundaries (measured against BW 1.16.1)
UNIT_COUNT = 228
WEAPON_COUNT = 130
# reduced-count fields: sound fields cover the 106 "real unit" ids (0..105);
# addon/infestation fields cover the 96 "building" ids (106..201).
UNITS_SUBSET = 106            # base index 0
BUILDINGS_SUBSET = 96        # base index 106
BUILDINGS_BASE = 106


class Field:
    """One SoA array: name, element width (bytes), element count, and the entity
    index its element 0 corresponds to (0 for full/units fields, 106 for building
    fields). `scale` marks a 1/256 fixed-point display field."""
    __slots__ = ('name', 'width', 'count', 'base', 'scale', 'offset')

    def __init__(self, name, width, count, base=0, scale=1):
        self.name = name
        self.width = width
        self.count = count
        self.base = base
        self.scale = scale
        self.offset = -1         # filled in by _resolve_offsets

    @property
    def size(self):
        return self.width * self.count

    def covers(self, entity_id):
        return self.base <= entity_id < self.base + self.count

    def index_of(self, entity_id):
        return entity_id - self.base


# ---- units.dat: 59 arrays, verified to close at exactly 19876 bytes ----
# The four MEASURED anchors (CLAUDE.md §4) are noted inline; the oracle re-checks
# them by cumulative offset, so this ordering is confirmed, not trusted.
_UNITS_FIELDS = [
    Field('flingy', 1, 228),
    Field('subunit1', 2, 228),
    Field('subunit2', 2, 228),
    Field('infestation', 2, 96, base=BUILDINGS_BASE),      # buildings only
    Field('construction_animation', 4, 228),
    Field('unit_direction', 1, 228),
    Field('shield_enable', 1, 228),
    Field('shield_amount', 2, 228, scale=256),
    Field('hitpoints', 4, 228, scale=256),                 # anchor @3156
    Field('elevation_level', 1, 228),
    Field('movement_flags', 1, 228),
    Field('rank', 1, 228),
    Field('comp_ai_idle', 1, 228),
    Field('human_ai_idle', 1, 228),
    Field('return_to_idle', 1, 228),
    Field('attack_unit', 1, 228),
    Field('attack_move', 1, 228),
    Field('ground_weapon', 1, 228),
    Field('max_ground_hits', 1, 228),
    Field('air_weapon', 1, 228),
    Field('max_air_hits', 1, 228),
    Field('ai_internal', 1, 228),
    Field('special_ability_flags', 4, 228),
    Field('target_acquisition_range', 1, 228),
    Field('sight_range', 1, 228),
    Field('armor_upgrade', 1, 228),
    Field('unit_size', 1, 228),
    Field('armor', 1, 228),
    Field('right_click_action', 1, 228),
    Field('ready_sound', 2, 106),                          # anchor @9312
    Field('what_sound_first', 2, 228),
    Field('what_sound_last', 2, 228),
    Field('piss_sound_first', 2, 106),
    Field('piss_sound_last', 2, 106),
    Field('yes_sound_first', 2, 106),
    Field('yes_sound_last', 2, 106),
    Field('placement_box_width', 2, 228),
    Field('placement_box_height', 2, 228),
    Field('addon_horizontal', 2, 96, base=BUILDINGS_BASE),
    Field('addon_vertical', 2, 96, base=BUILDINGS_BASE),
    Field('dimension_left', 2, 228),
    Field('dimension_up', 2, 228),
    Field('dimension_right', 2, 228),
    Field('dimension_down', 2, 228),
    Field('portrait', 2, 228),                             # anchor @14404
    Field('mineral_cost', 2, 228),
    Field('vespene_cost', 2, 228),
    Field('build_time', 2, 228),
    Field('requirements', 2, 228),
    Field('group_flags', 1, 228),                          # anchor @16684
    Field('supply_provided', 1, 228),
    Field('supply_required', 1, 228),
    Field('space_required', 1, 228),
    Field('space_provided', 1, 228),
    Field('build_score', 2, 228),
    Field('destroy_score', 2, 228),
    Field('unit_map_string', 2, 228),
    Field('broodwar_flag', 1, 228),
    Field('staredit_availability', 2, 228),
]

# ---- weapons.dat: 24 arrays, verified to close at exactly 5460 bytes ----
_WEAPONS_FIELDS = [
    Field('label', 2, 130),
    Field('graphics', 4, 130),
    Field('unused', 1, 130),
    Field('target_flags', 2, 130),
    Field('min_range', 4, 130),
    Field('max_range', 4, 130),
    Field('damage_upgrade', 1, 130),
    Field('weapon_type', 1, 130),
    Field('weapon_behavior', 1, 130),
    Field('remove_after', 1, 130),
    Field('weapon_effect', 1, 130),
    Field('inner_splash_range', 2, 130),
    Field('median_splash_range', 2, 130),
    Field('outer_splash_range', 2, 130),
    Field('damage_amount', 2, 130),
    Field('damage_bonus', 2, 130),
    Field('weapon_cooldown', 1, 130),
    Field('damage_factor', 1, 130),
    Field('attack_angle', 1, 130),
    Field('launch_spin', 1, 130),
    Field('forward_offset', 1, 130),
    Field('upward_offset', 1, 130),
    Field('target_error_message', 2, 130),
    Field('icon', 2, 130),
]

# ---- the GRAPHICS CHAIN: units.dat.flingy -> flingy.dat.sprite ->
# sprites.dat.image -> images.dat.grp_file -> images.tbl (GRP filename). Each
# layout is verified two ways in tests/test_dat_chain.py: the arrays close at the
# exact file size, AND the whole chain resolves a known unit (Marine) to a real
# GRP name - an end-to-end falsifiable check no single field could pass by luck.

FLINGY_COUNT = 209
SPRITE_COUNT = 517
IMAGE_COUNT = 999
# sprites.dat has 3 fields that only cover the 387 "unit" sprites (ids 130..516)
SPRITES_SUBSET = 387
SPRITES_BASE = 130

# flingy.dat: 209 x 15 B = 3135
_FLINGY_FIELDS = [
    Field('sprite', 2, 209),
    Field('top_speed', 4, 209),
    Field('acceleration', 2, 209),
    Field('halt_distance', 4, 209),
    Field('turn_radius', 1, 209),
    Field('unused', 1, 209),
    Field('move_control', 1, 209),
]

# sprites.dat: 517 sprites, closes at 3229 B (health-bar / selection-circle
# fields cover only the 387 unit sprites 130..516)
_SPRITES_FIELDS = [
    Field('image', 2, 517),
    Field('health_bar', 1, 387, base=SPRITES_BASE),
    Field('unknown_0', 1, 517),
    Field('is_visible', 1, 517),
    Field('selection_circle_image', 1, 387, base=SPRITES_BASE),
    Field('selection_circle_offset', 1, 387, base=SPRITES_BASE),
]

# images.dat: 999 x 38 B = 37962 (all arrays full-length)
_IMAGES_FIELDS = [
    Field('grp_file', 4, 999),                 # 1-based index into images.tbl
    Field('graphic_turns', 1, 999),
    Field('clickable', 1, 999),
    Field('use_full_iscript', 1, 999),
    Field('draw_if_cloaked', 1, 999),
    Field('draw_function', 1, 999),
    Field('remapping', 1, 999),
    Field('iscript_id', 4, 999),
    Field('shield_overlay', 4, 999),
    Field('attack_overlay', 4, 999),
    Field('damage_overlay', 4, 999),
    Field('special_overlay', 4, 999),
    Field('landing_dust_overlay', 4, 999),
    Field('liftoff_dust_overlay', 4, 999),
]

_SPECS = {
    'units.dat': (_UNITS_FIELDS, UNIT_COUNT, 19876),
    'weapons.dat': (_WEAPONS_FIELDS, WEAPON_COUNT, 5460),
    'flingy.dat': (_FLINGY_FIELDS, FLINGY_COUNT, 3135),
    'sprites.dat': (_SPRITES_FIELDS, SPRITE_COUNT, 3229),
    'images.dat': (_IMAGES_FIELDS, IMAGE_COUNT, 37962),
}

_UNPACK = {1: '<B', 2: '<H', 4: '<I'}


def _resolve_offsets(fields):
    off = 0
    for f in fields:
        f.offset = off
        off += f.size
    return off


class DatFile:
    """Editable SoA .dat. `get(field, id)` / `set(field, id, value)` address a
    property by name and entity id; `to_bytes()` serialises back byte-identically
    when unchanged. `kind` is 'units.dat' or 'weapons.dat'."""

    def __init__(self, kind, data):
        if kind not in _SPECS:
            raise ValueError('unknown dat kind %r' % kind)
        fields, count, expect = _SPECS[kind]
        if len(data) != expect:
            raise ValueError('%s: expected %d bytes, got %d'
                             % (kind, expect, len(data)))
        self.kind = kind
        self.count = count
        self.data = bytearray(data)
        self.fields = fields
        self.by_name = {f.name: f for f in fields}
        _resolve_offsets(fields)

    def field(self, name):
        f = self.by_name.get(name)
        if f is None:
            raise KeyError('%s has no field %r' % (self.kind, name))
        return f

    def get(self, name, entity_id):
        """Raw stored value, or None if the field does not cover this id."""
        f = self.field(name)
        if not f.covers(entity_id):
            return None
        pos = f.offset + f.index_of(entity_id) * f.width
        return struct.unpack_from(_UNPACK[f.width], self.data, pos)[0]

    def set(self, name, entity_id, value):
        f = self.field(name)
        if not f.covers(entity_id):
            raise IndexError('field %r does not cover id %d (base %d, count %d)'
                             % (name, entity_id, f.base, f.count))
        mask = (1 << (f.width * 8)) - 1
        pos = f.offset + f.index_of(entity_id) * f.width
        struct.pack_into(_UNPACK[f.width], self.data, pos, int(value) & mask)

    def display(self, name, entity_id):
        """Human value: raw / scale for fixed-point fields (hitpoints, shields)."""
        raw = self.get(name, entity_id)
        if raw is None:
            return None
        f = self.field(name)
        return raw // f.scale if f.scale != 1 else raw

    def row(self, entity_id):
        """{field_name: raw value} for every field that covers this id."""
        return {f.name: self.get(f.name, entity_id)
                for f in self.fields if f.covers(entity_id)}

    def to_bytes(self):
        return bytes(self.data)


def load(kind, data):
    return DatFile(kind, data)


def load_from_chain(mpq_chain, kind):
    """Read arr\\<kind> from an open MpqChain and parse it."""
    data = mpq_chain.read('arr\\' + kind)
    return DatFile(kind, data)


def graphics_chain(unit_id, units, flingy, sprites, images, images_tbl=None):
    """Walk the graphics chain for a unit:
        units.dat[unit].flingy -> flingy.dat.sprite -> sprites.dat.image
        -> images.dat.grp_file -> images.tbl name.
    Returns every hop; `grp_name` needs `images_tbl` (a list of strings, as read
    by tools/tbl.py). The grp_file value is a 1-based index into images.tbl."""
    fl = units.get('flingy', unit_id)
    sp = flingy.get('sprite', fl)
    im = sprites.get('image', sp)
    grp_idx = images.get('grp_file', im)
    name = None
    if images_tbl and grp_idx and 1 <= grp_idx <= len(images_tbl):
        name = images_tbl[grp_idx - 1]
    return {'unit': unit_id, 'flingy': fl, 'sprite': sp, 'image': im,
            'grp_file': grp_idx, 'grp_name': name}


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    import mpq
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    ch = mpq.MpqChain(base)
    for kind in ('units.dat', 'weapons.dat'):
        f = load_from_chain(ch, kind)
        total = _resolve_offsets(f.fields)
        print('%-12s %d fields, %d B (arrays sum %d)'
              % (kind, len(f.fields), len(f.data), total))
    u = load_from_chain(ch, 'units.dat')
    # Marine = id 0: 40 HP; SCV = id 7: 60 HP
    print('  anchors: hitpoints@%d ready_sound@%d portrait@%d group_flags@%d'
          % (u.field('hitpoints').offset, u.field('ready_sound').offset,
             u.field('portrait').offset, u.field('group_flags').offset))
    print('  Marine(0) HP=%d  SCV(7) HP=%d  Marine cost min=%d'
          % (u.display('hitpoints', 0), u.display('hitpoints', 7),
             u.get('mineral_cost', 0)))
