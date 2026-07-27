#!/usr/bin/env python3
"""Reader for StarCraft / Brood War replay (`.rep`) files - container + header.

A `.rep` is not game state; it is the players' INPUT (command) stream plus a
header and the map. This module cracks the container and header; rep_commands.py
disassembles the command stream; rep_actions.py turns it into per-player timelines.

CONTAINER - MEASURED against V's 9 real replays (5 classic + 4 SC:R), parses to
EOF on every classic file and to the SC:R trailer on the modern ones:

    file = a sequence of SECTIONS, each:
        u32 crc, u32 nChunks, then nChunks x (u32 compressedSize, bytes)
      each chunk decompresses to min(8192, remaining) bytes of the section's
      known size; a chunk stored raw when compressedSize == that output size.
    Section order: magic(4 "reRS"/"seRS") , header(633) , size(4)=cmdLen ,
                   commands(cmdLen) , size(4)=mapLen , map/CHK(mapLen).

Two container variants, distinguished by the magic at offset 12:
  * "reRS" - classic (1.16.1): chunks are PKWARE-imploded (tools/mpq.explode).
  * "seRS" - Remastered: chunks are zlib; and ONE extra u32 (total decompressed
    size) sits right after the magic section, before the header section. SC:R also
    appends extra trailing sections (skins/MMR) after the map - reported, not
    parsed (unknown layout), never silently claimed as read.

HEADER (633 bytes) - offsets MEASURED (names/races/map decode correctly on the
pro replays: By.herO, Bisu, Zero, Fighting Spirit, Destination, ...).

No third-party libraries; PKWARE explode + zlib are the same codecs the MPQ
reader already carries. The command-ID table (rep_commands.py) is the one piece
of borrowed format-data, attributed there.
"""
import os
import sys
import struct
import zlib
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import mpq

RACE = {0: 'Zerg', 1: 'Terran', 2: 'Protoss', 6: 'Random'}
PLAYER_TYPE = {0: 'inactive', 1: 'computer', 2: 'human', 3: 'rescue_passive',
               6: 'computer_defeated', 7: 'neutral'}
FRAMES_PER_SEC = 23.81                       # "fastest" game speed


def _u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def _cstr(b, o, n):
    return b[o:o + n].split(b'\x00')[0].decode('latin1', 'replace')


def _strip_colors(s):
    """Drop the in-game colour/ctrl bytes (< 0x20) BW embeds in map/game names."""
    return ''.join(c for c in s if ord(c) >= 0x20).strip()


@dataclass
class Player:
    slot: int
    pid: int
    storm_id: int          # the id the COMMAND stream tags actions with (struct +4)
    type: int
    race: int
    team: int
    name: str
    color: int = 0

    @property
    def race_name(self):
        return RACE.get(self.race, '?%d' % self.race)

    @property
    def type_name(self):
        return PLAYER_TYPE.get(self.type, '?%d' % self.type)

    @property
    def is_human(self):
        return self.type == 2


@dataclass
class Replay:
    remastered: bool
    engine: int
    frames: int
    title: str
    map_name: str
    map_w: int
    map_h: int
    game_type: int
    players: list = field(default_factory=list)   # Player (active only)
    header: bytes = b''
    commands: bytes = b''
    chk: bytes = b''
    parsed_to: int = 0
    file_size: int = 0

    @property
    def duration_frames(self):
        return self.frames

    @property
    def duration_seconds(self):
        return self.frames / FRAMES_PER_SEC

    def frame_to_time(self, frame):
        s = frame / FRAMES_PER_SEC
        return '%d:%05.2f' % (int(s // 60), s % 60)

    def player_by_storm(self, storm_id):
        """Look up the player a command belongs to (commands tag by storm id)."""
        for p in self.players:
            if p.storm_id == storm_id:
                return p
        return None


def _unpack_section(data, o, expected, use_zlib):
    """Read one section at o with known decompressed `expected` size -> (bytes, o)."""
    _crc = _u32(data, o)
    nch = _u32(data, o + 4)
    o += 8
    out = bytearray()
    for _ in range(nch):
        want = min(8192, expected - len(out))
        csz = _u32(data, o)
        o += 4
        chunk = data[o:o + csz]
        o += csz
        if csz == want:
            dec = chunk                                   # stored uncompressed
        elif use_zlib:
            dec = zlib.decompress(chunk)
        else:
            dec = mpq.explode(chunk)
        out += dec
    return bytes(out), o


def _parse_header(hdr):
    engine = hdr[0x00]
    frames = _u32(hdr, 0x01)
    title = _strip_colors(_cstr(hdr, 0x18, 28))
    map_w, map_h = struct.unpack_from('<HH', hdr, 0x34)
    game_type = hdr[0x5C] if len(hdr) > 0x5C else 0
    map_name = _strip_colors(_cstr(hdr, 0x61, 32))
    players = []
    colors = [_u32(hdr, 0x251 + i * 4) for i in range(8)] if len(hdr) >= 0x271 else [0] * 8
    for i in range(12):
        po = 0xA1 + i * 36
        pid = _u32(hdr, po)                                # struct +0: map slot number
        storm_id = _u32(hdr, po + 4)                       # struct +4: command-stream id
        ptype = hdr[po + 8]
        race = hdr[po + 9]
        team = hdr[po + 10]
        name = _cstr(hdr, po + 11, 25)
        if not name:
            continue                                      # empty slot
        p = Player(slot=i, pid=pid, storm_id=storm_id, type=ptype, race=race,
                   team=team, name=name, color=colors[pid] if 0 <= pid < 8 else 0)
        players.append(p)
    return engine, frames, title, map_name, map_w, map_h, game_type, players


def parse(data):
    """Parse replay bytes into a Replay (header + raw command stream + CHK)."""
    if data[12:16] not in (b'reRS', b'seRS'):
        raise ValueError('not a .rep (magic %r at +12)' % data[12:16])
    use_zlib = data[12:16] == b'seRS'
    o = 0
    _magic, o = _unpack_section(data, o, 4, use_zlib)
    if use_zlib:
        o += 4                                            # modern: total-size u32
    hdr, o = _unpack_section(data, o, 633, use_zlib)
    szb, o = _unpack_section(data, o, 4, use_zlib)
    cmds, o = _unpack_section(data, o, _u32(szb, 0), use_zlib)
    szb2, o = _unpack_section(data, o, 4, use_zlib)
    chk, o = _unpack_section(data, o, _u32(szb2, 0), use_zlib)

    engine, frames, title, map_name, map_w, map_h, game_type, players = _parse_header(hdr)
    return Replay(remastered=use_zlib, engine=engine, frames=frames, title=title,
                  map_name=map_name, map_w=map_w, map_h=map_h, game_type=game_type,
                  players=players, header=hdr, commands=cmds, chk=chk,
                  parsed_to=o, file_size=len(data))


def load(path):
    with open(path, 'rb') as fh:
        return parse(fh.read())


if __name__ == '__main__':
    for path in sys.argv[1:]:
        r = load(path)
        print('%s  [%s]' % (os.path.basename(path), 'SC:R' if r.remastered else 'classic'))
        print('  %s  %d frames (%s)  map=%r  cmds=%dB chk=%dB  parsed %d/%d'
              % (r.title, r.frames, r.frame_to_time(r.frames), r.map_name,
                 len(r.commands), len(r.chk), r.parsed_to, r.file_size))
        for p in r.players:
            print('    slot%d P%d %-8s %-8s %r' %
                  (p.slot, p.pid, p.race_name, p.type_name, p.name))
