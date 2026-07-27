#!/usr/bin/env python3
"""Reader for scripts\\iscript.bin - StarCraft's animation-script container.

Structure - MEASURED against Brood War 1.16.1, not assumed:

  u16 @0            id_table_offset (points near EOF)
  at id_table_offset: an array of {u16 iscriptId, u16 headerOffset} entries,
                      terminated by an id of 0xffff.
  at each headerOffset: "SCPE" (4) + u8 type + 3 pad + ENTRY_TYPES[type] x u16
                      animation offsets (0 = that animation is absent). The
                      offsets point to opcode streams (the animations).

Measured on 1.16.1: 40482 B, id table @0x97e6, 398 entries; every one of the 393
distinct images.dat.iscript_id values resolves to an entry here (the falsifiable
cross-check that this table is read correctly). Header type -> animation count is
ENTRY_TYPES (borrowed from PyMS, verified: type 12 -> 14 offsets, and the header
sizes tile the file exactly under the disasm oracle).

Turning an animation's byte stream into opcodes is iscript_disasm.py.
"""
import struct
from dataclasses import dataclass, field

from iscript_opcodes import HEADER, ENTRY_TYPES


@dataclass
class IScriptEntry:
    id: int
    header_offset: int
    type: int
    animations: list = field(default_factory=list)   # [(anim_name, offset|None)]

    def used_animations(self):
        return [(n, o) for n, o in self.animations if o]


@dataclass
class IScriptFile:
    data: bytes
    id_table_offset: int
    entries: list = field(default_factory=list)

    def by_id(self):
        return {e.id: e for e in self.entries}

    def anim_entry_points(self):
        pts = set()
        for e in self.entries:
            for _, off in e.animations:
                if off:
                    pts.add(off)
        return pts


def _parse_header(data, iid, hoff):
    if data[hoff:hoff + 4] != b'SCPE':
        raise ValueError('iscript %d: missing SCPE header at 0x%x' % (iid, hoff))
    typ = data[hoff + 4]                       # single byte; +5..7 padding
    if typ not in ENTRY_TYPES:
        raise ValueError('iscript %d: unknown header type %d' % (iid, typ))
    n = ENTRY_TYPES[typ]
    offs = struct.unpack_from('<%dH' % n, data, hoff + 8)
    anims = [(HEADER[i] if i < len(HEADER) else 'anim%d' % i, (o or None))
             for i, o in enumerate(offs)]
    return IScriptEntry(id=iid, header_offset=hoff, type=typ, animations=anims)


def parse(data):
    """Parse an iscript.bin image into an IScriptFile."""
    if len(data) < 2:
        raise ValueError('iscript.bin too small (%d bytes)' % len(data))
    id_table = struct.unpack_from('<H', data, 0)[0]
    if not (0 < id_table <= len(data)):
        raise ValueError('id_table_offset 0x%x out of range' % id_table)
    entries = []
    off = id_table
    n = len(data)
    while off + 4 <= n:
        iid = struct.unpack_from('<H', data, off)[0]
        if iid == 0xffff:
            break
        hoff = struct.unpack_from('<H', data, off + 2)[0]
        entries.append(_parse_header(data, iid, hoff))
        off += 4
    return IScriptFile(data=data, id_table_offset=id_table, entries=entries)


def load_from_chain(mpq_chain):
    return parse(mpq_chain.read('scripts\\iscript.bin'))


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    isc = load_from_chain(mpq.MpqChain(base))
    print('iscript.bin: %d B, id table @0x%x, %d entries'
          % (len(isc.data), isc.id_table_offset, len(isc.entries)))
    for e in isc.entries[:3]:
        print('  id=%d type=%d anims=%s' % (e.id, e.type,
              [n for n, o in e.used_animations()]))
