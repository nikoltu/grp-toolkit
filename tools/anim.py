#!/usr/bin/env python3
"""Reader for SC:R `.anim` sprite files (the HD asset side).

Structure - MEASURED (CLAUDE.md 4, cross-checked with the browser's parseAnim):

    "ANIM" (4)
    u8 scale        1 = SD, 2 = HD2, 4 = full HD
    u8 type
    u16 (unused)
    u16 layerCount  (<= 10)
    u16 entryCount
    0x0C: layer-name table, 10 slots x 32 B
    0x14C (= 0x0C + 10*32): entry table, entryCount x 12:
        u16 frameCount, u16 refId, u16 w, u16 h, u32 frameTableOffset
    then TexRef x layerCount, 12 B each:
        u32 ddsOffset, u32 ddsSize, u16 w, u16 h
    frame record (in a frame table), 16 B: u16 atlasX, atlasY, i16 xoff, yoff,
        u16 w, h, u32 flags

`refId != 0xffff` on an entry means the sprite borrows another file's texture
(so its own TexRef ddsOffset is 0). Each TexRef's DDS blob starts with "DDS "
and carries its DXT FourCC at +0x54 (DXT1/DXT3/DXT5). This reader is what the HD
asset inventory (anim_inventory.py) scans; it does NOT decode DXT pixels (that is
the C++ dxt.hpp / the browser). No third-party libraries.
"""
import struct
from dataclasses import dataclass, field

NAME_TABLE = 0x0C
NAME_SLOTS = 10
ENTRY_OFF = NAME_TABLE + NAME_SLOTS * 32          # 0x14C
SCALE_NAME = {1: 'SD', 2: 'HD2', 4: 'HD'}


@dataclass
class TexRef:
    # dds_offset == 0 means this layer's texture is NOT in this file: it is
    # refId-SHARED and lives in another .anim (the one the entry's refId points
    # at). MEASURED: many HD `.anim` carry only the diffuse DDS in-file and share
    # the other six layers (bright/teamcolor/emissive/normal/specular/ao_depth)
    # this way. An HD renderer must follow refId to sample those - a 0 offset is
    # "texture elsewhere", not "layer absent". See anim_render.decode_layer_atlas.
    dds_offset: int
    dds_size: int
    w: int
    h: int
    dxt: str = ''                                 # 'DXT1'/'DXT3'/'DXT5'/''


@dataclass
class AnimEntry:
    frame_count: int
    ref_id: int
    w: int
    h: int
    frame_table_offset: int

    @property
    def shared(self):
        return self.ref_id != 0xFFFF


@dataclass
class Anim:
    scale: int
    type: int
    layer_count: int
    entry_count: int
    layers: list = field(default_factory=list)    # layer names (str)
    texrefs: list = field(default_factory=list)   # TexRef
    entries: list = field(default_factory=list)   # AnimEntry
    size: int = 0
    ok: bool = True                               # structural layout in bounds

    @property
    def tier(self):
        return SCALE_NAME.get(self.scale, '?%d' % self.scale)

    @property
    def dxt_formats(self):
        return sorted({t.dxt for t in self.texrefs if t.dxt})


def _cstr(data, off, maxlen):
    end = off
    while end < off + maxlen and end < len(data) and data[end]:
        end += 1
    return data[off:end].decode('latin1', 'replace')


def _dxt_fourcc(data, dds_off):
    if dds_off <= 0 or dds_off + 0x58 > len(data):
        return ''
    if data[dds_off:dds_off + 4] != b'DDS ':
        return ''
    fourcc = data[dds_off + 0x54:dds_off + 0x58]
    return fourcc.decode('latin1', 'replace').strip() \
        if fourcc[:3] == b'DXT' else ''


def parse(data):
    """Parse .anim bytes into an Anim. Raises ValueError on a bad magic; sets
    .ok=False (but still returns) if the layer/texref layout runs out of bounds
    (a corrupt or unusual file the inventory should flag, not crash on)."""
    if data[:4] != b'ANIM':
        raise ValueError('not an ANIM file (magic %r)' % data[:4])
    scale = data[4]
    typ = data[5]
    layer_count = struct.unpack_from('<H', data, 8)[0]
    entry_count = struct.unpack_from('<H', data, 10)[0]
    a = Anim(scale=scale, type=typ, layer_count=layer_count,
             entry_count=entry_count, size=len(data))

    texref_off = ENTRY_OFF + entry_count * 12
    a.ok = (0 < layer_count <= NAME_SLOTS and entry_count > 0
            and texref_off + layer_count * 12 <= len(data))

    for i in range(min(layer_count, NAME_SLOTS)):
        a.layers.append(_cstr(data, NAME_TABLE + i * 32, 32))

    for e in range(entry_count):
        eo = ENTRY_OFF + e * 12
        if eo + 12 > len(data):
            a.ok = False
            break
        fc, rid, w, h = struct.unpack_from('<HHHH', data, eo)
        ft = struct.unpack_from('<I', data, eo + 8)[0]
        a.entries.append(AnimEntry(fc, rid, w, h, ft))

    if a.ok:
        for i in range(layer_count):
            o = texref_off + i * 12
            doff, dsize = struct.unpack_from('<II', data, o)
            w, h = struct.unpack_from('<HH', data, o + 8)
            a.texrefs.append(TexRef(doff, dsize, w, h, _dxt_fourcc(data, doff)))
    return a


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    import casc
    scr = sys.argv[1] if len(sys.argv) > 1 else r'C:\Git\StarCraft Remastered'
    name = sys.argv[2] if len(sys.argv) > 2 \
        else 'anim/main/hd2/unit/terran/marine.anim'
    st = casc.NamedStorage(os.path.join(scr, 'data', 'data'), install_root=scr)
    a = parse(st.read_name(name))
    print('%s  tier=%s type=%d layers=%d entries=%d dxt=%s'
          % (name, a.tier, a.type, a.layer_count, a.entry_count, a.dxt_formats))
    print('  layers:', a.layers)
    for e in a.entries[:3]:
        print('  entry frames=%d refId=0x%x %dx%d shared=%s'
              % (e.frame_count, e.ref_id, e.w, e.h, e.shared))
