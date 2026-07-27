#!/usr/bin/env python3
"""StarCraft .tbl string table reader + writer (stat_txt.tbl, sfxdata.tbl,
images.tbl, ...).

Format (measured; also used by units.dat name lookups, CLAUDE.md):
    u16 count
    count x u16 offset   (byte offset from the start of the file)
    then the string blob

Indices in the game are usually 1-based (string N is entry N-1 here); callers do
their own +/-1 (e.g. unit names are stat_txt[unit_id + 1]). This reader is
0-based: strings[i] is the i-th entry.

MEASURED SUBTLETY (why the writer keeps two representations):
a .tbl entry is NOT just the text up to its first NUL. `stat_txt.tbl` entries
carry extra NUL-separated parts after the display name (tooltip / hotkey / extended
strings) -- 274 of its 1547 entries do. An entry's real bytes run from its offset
to the NEXT offset in the table. Reading only to the first NUL (the old reader) is
fine for *display* but drops 3801 bytes on a rewrite, which would corrupt the file.
So:
  * `strings[i]` / `text(i)` = bytes up to the first NUL  -> the display name
    (backward-compatible with every existing caller: unit names, etc.).
  * `raw[i]`                = the full slice to the next offset -> what the writer
    round-trips. Editing addresses `raw` (helper `set_text` keeps the extra parts).

Writer guarantees (the project's "measure, never assume" bar):
  * UNCHANGED: `to_bytes()` re-serialises from the parsed structure in OFFSET order
    and is BYTE-IDENTICAL to the source (verified on stat_txt / sfxdata / images).
    This is a real round-trip of the writer, not "return the original".
  * EDITED: `to_bytes()` rebuilds in index order (content-deduped). Byte-identity vs
    Blizzard is NOT claimed then (shared-suffix packing is a storage choice); the
    guarantee is a semantic round-trip -- parse(to_bytes()) reproduces every entry's
    bytes -- and a valid .tbl the game reads by its offset table.
"""
import struct


class Tbl:
    def __init__(self, data):
        self.data = bytes(data)
        n = struct.unpack_from('<H', self.data, 0)[0]
        self.count = n
        self.offs = list(struct.unpack_from('<%dH' % n, self.data, 2)) if n else []
        # full slice = [offset, next distinct offset) -> preserves extended parts
        uniq = sorted(set(self.offs))
        nextb = {o: (uniq[i + 1] if i + 1 < len(uniq) else len(self.data))
                 for i, o in enumerate(uniq)}
        self.raw = [self.data[o:nextb[o]] for o in self.offs]
        # display strings: up to the first NUL (backward-compatible)
        self.strings = [r.split(b'\x00', 1)[0] for r in self.raw]
        self._dirty = False

    # -- read API (unchanged) --------------------------------------------------
    def __len__(self):
        return len(self.strings)

    def __getitem__(self, i):
        return self.strings[i]

    def text(self, i, encoding='latin1'):
        """Entry i's display name as a str (empty for an out-of-range index)."""
        if 0 <= i < len(self.strings):
            return self.strings[i].decode(encoding, 'replace')
        return ''

    # -- edit API --------------------------------------------------------------
    def set_raw(self, i, value):
        """Replace entry i's FULL bytes (must include any trailing NUL/parts)."""
        if not (0 <= i < self.count):
            raise IndexError('entry %d out of range (count %d)' % (i, self.count))
        b = value.encode('latin1') if isinstance(value, str) else bytes(value)
        self.raw[i] = b
        self.strings[i] = b.split(b'\x00', 1)[0]
        self._dirty = True

    def set_text(self, i, name, encoding='latin1'):
        """Replace only the display name of entry i, PRESERVING its extended parts
        (everything after the first NUL). Ensures a terminating NUL."""
        if not (0 <= i < self.count):
            raise IndexError('entry %d out of range (count %d)' % (i, self.count))
        old = self.raw[i]
        rest = old.split(b'\x00', 1)
        tail = (b'\x00' + rest[1]) if len(rest) > 1 else b'\x00'
        nb = name.encode(encoding) if isinstance(name, str) else bytes(name)
        self.raw[i] = nb + tail
        self.strings[i] = nb
        self._dirty = True

    def append(self, value):
        """Add a new entry (full bytes); returns its index."""
        b = value.encode('latin1') if isinstance(value, str) else bytes(value)
        if b and not b.endswith(b'\x00'):
            b += b'\x00'
        self.raw.append(b)
        self.strings.append(b.split(b'\x00', 1)[0])
        self.offs.append(0)          # placeholder; real offset assigned on rebuild
        self.count += 1
        self._dirty = True
        return self.count - 1

    # -- write -----------------------------------------------------------------
    def _rebuild_offset_order(self):
        """Re-serialise from the parsed structure preserving the original offset
        layout -> byte-identical for an unedited file."""
        uniq = sorted(set(self.offs))
        first = {}
        for i, o in enumerate(self.offs):
            first.setdefault(o, i)          # a slice's canonical owner
        base = 2 + 2 * self.count
        pos = {}
        blob = b''
        for o in uniq:
            pos[o] = base + len(blob)
            blob += self.raw[first[o]]
        outoffs = [pos[o] for o in self.offs]
        return struct.pack('<H', self.count) + struct.pack('<%dH' % self.count, *outoffs) + blob

    def _rebuild_index_order(self):
        """Rebuild after edits: each entry in index order, content-deduped."""
        base = 2 + 2 * self.count
        pos = {}
        blob = b''
        outoffs = []
        for r in self.raw:
            if r not in pos:
                pos[r] = base + len(blob)
                blob += r
            outoffs.append(pos[r])
        return struct.pack('<H', self.count) + struct.pack('<%dH' % self.count, *outoffs) + blob

    def to_bytes(self):
        if not self._dirty:
            return self._rebuild_offset_order()
        return self._rebuild_index_order()


def load(data):
    return Tbl(data)


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    import mpq
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    t = Tbl(mpq.MpqChain(base).read('rez\\stat_txt.tbl'))
    print('stat_txt.tbl: %d strings, to_bytes byte-identical: %s'
          % (len(t), t.to_bytes() == t.data))
    for i in (0, 1, 2, 106, 1052):
        extra = len(t.raw[i]) - len(t.strings[i]) - 1
        print('  [%d] %r%s' % (i, t.text(i), (' (+%d extra bytes)' % extra) if extra > 0 else ''))
