#!/usr/bin/env python3
"""Transcode a Remastered (`seRS`) replay down to a classic 1.16.1 (`reRS`) one.

Why it is possible (MEASURED, see the notes below): the container difference is
mechanical, and the only command-stream difference that matters is the SC:R "121"
input set (0x60-0x65), which is the classic command with a 4-byte unit tag instead
of a 2-byte one - and those tags' high 16 bits are ~always 0 (measured: 11625/
11625 right-click/unload targets and >99.9% of select tags), so a `& 0xFFFF`
down-convert is lossless in practice.

What it does:
  * CONTAINER: rebuild as `reRS` with each section stored UNCOMPRESSED (a chunk is
    kept raw when its compressed size equals its output size - so no PKWARE
    *compressor* is needed, only the explode the toolkit already has). Drops the
    modern total-size u32 and the SC:R trailer sections (skins/MMR), which 1.16.1
    has no concept of.
  * COMMANDS: 0x60->0x14, 0x61->0x15, 0x62->0x29, 0x63/64/65->0x09/0a/0b, each with
    its 4-byte unit tag(s) truncated to 2 bytes; every other command copied as-is;
    frame-block grouping and frame numbers preserved.

HONEST LIMITS: this cannot be checked against a real 1.16.1 client here (no BW
runtime). The self-oracle (tests/rep/test_rep.py) proves the OUTPUT re-reads with
the CLASSIC reader to the exact same logical commands (same frames, same produced
units), which is structural correctness - actual in-game playback is V's to test.
Whether BW's unit-tag scheme matches SC:R's low-16 is the one thing only a live
game can confirm; if a select misfires, the tag encoding is where to look.

No third-party libraries. Reuses rep_read + rep_commands.
"""
import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rep_read
import rep_commands as RC

# 121 command id -> classic id
REMAP = {0x60: 0x14, 0x61: 0x15, 0x62: 0x29, 0x63: 0x09, 0x64: 0x0A, 0x65: 0x0B}
CLASSIC_ID = 0x2B7E7EA7                      # replay id inside the magic section


def _u16(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def _u32(v):
    return struct.pack('<I', v & 0xFFFFFFFF)


def _low16_of_u32(b, o):
    return struct.unpack_from('<I', b, o)[0] & 0xFFFF


def transcode_command(c):
    """Re-encode one Command as classic bytes: player, id, args."""
    p = bytes([c.player])
    cid = c.cmd_id
    a = c.args
    if cid in (0x63, 0x64, 0x65):                       # select_121 -> classic select
        n = a[0]
        out = bytearray([n])
        for i in range(n):
            out += _u16(struct.unpack_from('<I', a, 1 + i * 4)[0] & 0xFFFF)
        return p + bytes([REMAP[cid]]) + bytes(out)
    if cid == 0x60:                                     # right_click_121 -> 0x14
        # x2 y2 target4 type2 queued1  ->  x2 y2 target2 type2 queued1
        return p + b'\x14' + a[0:4] + _u16(_low16_of_u32(a, 4)) + a[8:11]
    if cid == 0x61:                                     # targeted_order_121 -> 0x15
        # x2 y2 target4 type2 queued1 order1 -> x2 y2 target2 type2 queued1 order1
        return p + b'\x15' + a[0:4] + _u16(_low16_of_u32(a, 4)) + a[8:12]
    if cid == 0x62:                                     # unload_121 -> 0x29 unload
        return p + b'\x29' + _u16(_low16_of_u32(a, 0))
    return p + bytes([cid]) + a                         # already classic: copy


def transcode_commands(commands):
    """Rebuild the whole command section in classic form (block grouping kept)."""
    out = bytearray()
    for frame, cmds in RC.decode_blocks(commands):
        body = bytearray()
        for c in cmds:
            body += transcode_command(c)
        # a block body is at most 255 bytes; split if a frame somehow exceeds it
        for i in range(0, max(len(body), 1), 255):
            chunk = body[i:i + 255]
            out += _u32(frame) + bytes([len(chunk)]) + chunk
            if not body:
                break
    return bytes(out)


def _emit_section(payload, crc=0):
    """One classic section: u32 crc, u32 nChunks, nChunks x (u32 csz, raw bytes).
    Stored uncompressed (csz == output size), so no compressor is needed."""
    out = bytearray()
    out += _u32(crc)
    n = len(payload)
    nch = max(1, (n + 8191) // 8192)
    out += _u32(nch)
    o = 0
    for _ in range(nch):
        want = min(8192, n - o)
        out += _u32(want) + payload[o:o + want]          # csz == want -> stored raw
        o += want
    return bytes(out)


def transcode(seRS_bytes):
    """seRS replay bytes -> reRS replay bytes."""
    r = rep_read.parse(seRS_bytes)
    if not r.remastered:
        return seRS_bytes                                # already classic
    new_cmds = transcode_commands(r.commands)
    out = bytearray()
    # magic section: data is the string "reRS" (lands at file offset 12); the crc
    # slot carries the classic replay id 0x2b7e7ea7, exactly as retail 1.16 writes it.
    out += _emit_section(b'reRS', crc=CLASSIC_ID)
    out += _emit_section(r.header)                       # 633-byte header (same format)
    out += _emit_section(_u32(len(new_cmds)))
    out += _emit_section(new_cmds)
    out += _emit_section(_u32(len(r.chk)))
    out += _emit_section(r.chk)
    return bytes(out)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Transcode SC:R .rep -> classic 1.16.1 .rep')
    ap.add_argument('input')
    ap.add_argument('-o', '--out', help='output .rep (default: <input>.116.rep)')
    args = ap.parse_args()
    data = open(args.input, 'rb').read()
    out = transcode(data)
    dst = args.out or (os.path.splitext(args.input)[0] + '.116.rep')
    with open(dst, 'wb') as fh:
        fh.write(out)
    # self-check: re-read the result with the classic reader
    rr = rep_read.parse(out)
    cmds, consumed = RC.decode(rr.commands)
    print('%s -> %s  (%s, %d B -> %d B)'
          % (os.path.basename(args.input), os.path.basename(dst),
             'reRS' if not rr.remastered else 'seRS', len(data), len(out)))
    print('  re-read: %d frames, %d commands, consumed %d/%d %s'
          % (rr.frames, len(cmds), consumed, len(rr.commands),
             'OK' if consumed == len(rr.commands) else 'SHORT'))
