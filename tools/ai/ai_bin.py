#!/usr/bin/env python3
"""Reader for StarCraft AI script tables: scripts\\aiscript.bin (base game) and
scripts\\bwscript.bin (Brood War).

Structure - MEASURED against Brood War 1.16.1's real files, not assumed:

  u32 @0            table_offset  (little-endian, points near EOF)
  at table_offset:  a contiguous array of fixed-size entries, terminated by an
                    entry whose 4-byte id is all-zero.

  aiscript.bin entry = 16 bytes:
      char id[4]        FourCC script id, e.g. b'Ter3'
      u32  offset       byte offset of the opcode stream (0 == unused slot)
      u32  string_id    stat_txt.tbl index of the editor-visible name
      u32  flags         bitfield (see FLAG_* below)
  bwscript.bin entry = 8 bytes:
      char id[4]
      u32  offset

Measured on 1.16.1:
  aiscript.bin  len 62050  table@0xe00e  293 entries  (137 with code, 156 unused)
                string_id in 1048..1539 (matches stat_txt.tbl), flags in
                {7:157, 3:75, 1:24, 5:18, 2:16, 0:3}
  bwscript.bin  len 26458  table@0x6276  156 entries  (all with code)
The two files genuinely use different entry widths - do not assume one shape.

Only the *table* is decoded here; turning an entry's byte stream into opcodes is
ai_disasm.py (which needs the opcode registry, ai_opcodes.py).
"""
import struct
from dataclasses import dataclass, field

# aiscript.bin flag bits. The bitfield is measured; the meanings below follow
# the StarEdit / community reverse-engineering and are applied, not derived -
# treat as borrowed data until cross-checked against CHK usage (ai_disasm/tests).
FLAG_REQUIRES_LOCATION = 0x01   # invoked via "Run AI Script At Location"
FLAG_STAREDIT_HIDDEN = 0x02     # not shown in the StarEdit trigger list
FLAG_BROODWAR_ONLY = 0x04       # only valid in Brood War

AISCRIPT = 'aiscript.bin'
BWSCRIPT = 'bwscript.bin'


@dataclass
class AiScriptEntry:
    id: bytes                    # 4-byte FourCC, exactly as stored
    offset: int                  # byte offset of the opcode stream (0 = unused)
    string_id: int = 0           # stat_txt.tbl index (aiscript only; 0 for bw)
    flags: int = 0               # aiscript flag bitfield (0 for bw)
    source: str = ''             # 'aiscript.bin' or 'bwscript.bin'

    @property
    def fourcc(self):
        """The id as a str, using latin1 so every byte round-trips."""
        return self.id.decode('latin1')

    @property
    def used(self):
        return self.offset != 0

    @property
    def requires_location(self):
        return bool(self.flags & FLAG_REQUIRES_LOCATION)

    @property
    def broodwar_only(self):
        return bool(self.flags & FLAG_BROODWAR_ONLY)

    @property
    def staredit_hidden(self):
        return bool(self.flags & FLAG_STAREDIT_HIDDEN)


@dataclass
class AiScriptFile:
    source: str                  # basename, 'aiscript.bin' / 'bwscript.bin'
    data: bytes                  # the whole file, kept for raw-byte access
    table_offset: int
    entry_size: int
    entries: list = field(default_factory=list)   # list[AiScriptEntry]

    def by_id(self):
        """{fourcc_str: AiScriptEntry} for the used (offset != 0) entries.
        Later duplicate ids overwrite earlier ones, matching lookup order."""
        return {e.fourcc: e for e in self.entries if e.used}

    def raw_stream(self, entry, end=None):
        """Raw bytes from entry.offset to `end` (default: table_offset). The
        real script terminates earlier - the disassembler finds the end; this is
        just the safe upper bound (a script never runs into the entry table)."""
        if not entry.used:
            return b''
        stop = self.table_offset if end is None else end
        return self.data[entry.offset:stop]


def _detect_entry_size(source):
    if source.lower().startswith('bw'):
        return 8
    return 16


def parse(data, source):
    """Parse an aiscript.bin / bwscript.bin image. `source` selects the entry
    width (16 for aiscript, 8 for bwscript) and is recorded on every entry."""
    if len(data) < 4:
        raise ValueError('%s: too small (%d bytes)' % (source, len(data)))
    table_offset = struct.unpack_from('<I', data, 0)[0]
    if not (0 < table_offset <= len(data)):
        raise ValueError('%s: table_offset 0x%x out of range (len %d)'
                         % (source, table_offset, len(data)))
    esize = _detect_entry_size(source)
    entries = []
    off = table_offset
    n = len(data)
    while off + esize <= n:
        sid = data[off:off + 4]
        if sid == b'\x00\x00\x00\x00':
            break
        offset = struct.unpack_from('<I', data, off + 4)[0]
        if esize >= 16:
            string_id, flags = struct.unpack_from('<II', data, off + 8)
        else:
            string_id, flags = 0, 0
        if offset >= table_offset:
            raise ValueError('%s: entry %r offset 0x%x reaches the table (0x%x)'
                             % (source, sid, offset, table_offset))
        entries.append(AiScriptEntry(id=sid, offset=offset, string_id=string_id,
                                     flags=flags, source=source))
        off += esize
    return AiScriptFile(source=source, data=data, table_offset=table_offset,
                        entry_size=esize, entries=entries)


def load_from_chain(mpq_chain):
    """Read both AI script files from an open tools.mpq.MpqChain. Returns
    {'aiscript.bin': AiScriptFile, 'bwscript.bin': AiScriptFile}; a missing file
    (e.g. bwscript.bin absent in a vanilla-SC install) is simply skipped."""
    out = {}
    for name, source in [('scripts\\aiscript.bin', AISCRIPT),
                         ('scripts\\bwscript.bin', BWSCRIPT)]:
        try:
            data = mpq_chain.read(name)
        except Exception:
            continue
        out[source] = parse(data, source)
    return out


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    files = load_from_chain(mpq.MpqChain(base))
    for source, f in files.items():
        used = [e for e in f.entries if e.used]
        print('%-14s %d entries (%d with code)  table@0x%x  entry=%dB'
              % (source, len(f.entries), len(used), f.table_offset, f.entry_size))
        for e in used[:4]:
            print('    %-6s off=0x%05x str=%d flags=0x%x' %
                  (e.fourcc, e.offset, e.string_id, e.flags))
