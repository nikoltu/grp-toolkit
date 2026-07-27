#!/usr/bin/env python3
"""MPQ (Mo'PaQ) reader for StarCraft / Brood War 1.16.1 archives.

No dependencies beyond the stdlib. Implements the pieces the 1998 archives
actually use: the StormLib crypt table, filename hashing, hash/block table
decryption, per-file key derivation (ENCRYPTED / FIX_KEY), sector tables,
zlib, and PKWARE DCL "explode".

Chain loading follows the engine's precedence: Patch_rt > BrooDat > StarDat
(plus the CD archives StarCraft.mpq / BroodWar.mpq when present), so a name
resolves to the same bytes the game would load.

    from mpq import MpqChain
    c = MpqChain(r"C:\\Git\\Starcraft BroodWar  v1.1.61")
    pal = c.read(r"tileset\\badlands.wpe")

CLI:
    py tools/mpq.py <dir_or_mpq> --list [substr]
    py tools/mpq.py <dir_or_mpq> --extract <internal\\path> -o out.bin
    py tools/mpq.py <dir_or_mpq> --palettes <outdir>
"""
import os, sys, glob, struct, zlib, argparse

# ---------------------------------------------------------------- crypt table
def _make_crypt_table():
    t = [0] * 0x500
    seed = 0x00100001
    for i in range(0x100):
        idx = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            a = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            b = seed & 0xFFFF
            t[idx] = (a | b) & 0xFFFFFFFF
            idx += 0x100
    return t

_T = _make_crypt_table()
_OFF = {'hash': 0, 'nameA': 0x100, 'nameB': 0x200, 'key': 0x300}


def hash_string(s, kind):
    """StormLib string hash. Forward slashes normalise to backslashes."""
    s1, s2 = 0x7FED7FED, 0xEEEEEEEE
    off = _OFF[kind]
    for ch in s.upper():
        c = ord(ch)
        if c == 47:            # '/' -> '\'
            c = 92
        s1 = (_T[off + c] ^ ((s1 + s2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        s2 = (c + s1 + s2 + ((s2 << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    return s1


def decrypt_words(words, key):
    """In-place decryption of a u32 list."""
    k = key & 0xFFFFFFFF
    s2 = 0xEEEEEEEE
    for i in range(len(words)):
        s2 = (s2 + _T[0x400 + (k & 0xFF)]) & 0xFFFFFFFF
        v = (words[i] ^ ((k + s2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        words[i] = v
        k = (((~k & 0xFFFFFFFF) << 0x15) + 0x11111111 | (k >> 0x0B)) & 0xFFFFFFFF
        s2 = (v + s2 + ((s2 << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    return words


# ------------------------------------------------------- PKWARE DCL "explode"
# Canonical Huffman with an inverted bit per step (`code |= bits(1) ^ 1`) --
# that inversion is the whole trick; without it the first symbol already
# decodes wrong.
_MAXBITS = 13
_LITLEN = [11,124,8,7,28,7,188,13,76,4,10,8,12,10,12,10,8,23,8,9,7,6,7,8,7,6,
           55,8,23,24,12,11,7,9,11,12,6,7,22,5,7,24,6,11,9,6,7,22,7,11,38,7,9,
           8,25,11,8,11,9,12,8,12,5,38,5,38,5,11,7,5,6,21,6,10,53,8,7,24,10,27,
           44,253,253,253,252,252,252,13,12,45,12,45,12,61,12,45,44,173]
_LENLEN = [2,35,36,53,38,23]
_DISTLEN = [2,20,53,230,247,151,248]
_CBASE = [3,2,4,5,6,7,8,9,10,12,16,24,40,72,136,264]
_CEXTRA = [0,0,0,0,0,0,0,0,1,2,3,4,5,6,7,8]


def _build(rep):
    lengths = []
    for e in rep:
        num, ln = (e >> 4) + 1, e & 0xF
        lengths.extend([ln] * num)
    count = [0] * (_MAXBITS + 1)
    for L in lengths:
        count[L] += 1
    offs = [0] * (_MAXBITS + 2)
    for L in range(1, _MAXBITS + 1):
        offs[L + 1] = offs[L] + count[L]
    symbol = [0] * len(lengths)
    for i, L in enumerate(lengths):
        if L:
            symbol[offs[L]] = i
            offs[L] += 1
    return count, symbol


_LITC, _LENC, _DISTC = _build(_LITLEN), _build(_LENLEN), _build(_DISTLEN)


def explode(data):
    ip = [0]
    bitbuf = [0]
    bitcnt = [0]

    def bits(need):
        val = bitbuf[0]
        while bitcnt[0] < need:
            val |= (data[ip[0]] if ip[0] < len(data) else 0) << bitcnt[0]
            ip[0] += 1
            bitcnt[0] += 8
        bitbuf[0] = val >> need
        bitcnt[0] -= need
        return val & ((1 << need) - 1)

    def decode(h):
        count, symbol = h
        code = first = index = 0
        length = 1
        while True:
            code |= bits(1) ^ 1          # the inversion
            c = count[length]
            if code < first + c:
                return symbol[index + (code - first)]
            index += c
            first = (first + c) << 1
            code <<= 1
            length += 1
            if length > _MAXBITS:
                raise ValueError('explode: bad huffman code')

    litcode = data[ip[0]]; ip[0] += 1
    dictbits = data[ip[0]]; ip[0] += 1
    out = bytearray()
    while True:
        if bits(1):
            sym = decode(_LENC)
            length = _CBASE[sym] + bits(_CEXTRA[sym])
            if length == 519:
                break
            sb = 2 if length == 2 else dictbits
            dist = (decode(_DISTC) << sb) + bits(sb) + 1
            frm = len(out) - dist
            if frm < 0:
                raise ValueError('explode: distance before start')
            for i in range(length):
                out.append(out[frm + i])
        else:
            out.append(decode(_LITC) if litcode else bits(8))
        if ip[0] >= len(data) and bitcnt[0] < 1:
            break
    return bytes(out)


# ------------------------------------------------------------------- archive
FLAG_IMPLODE   = 0x00000100
FLAG_COMPRESS  = 0x00000200
FLAG_ENCRYPTED = 0x00010000
FLAG_FIX_KEY   = 0x00020000
FLAG_SINGLE    = 0x01000000
FLAG_EXISTS    = 0x80000000


class Mpq:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        self.f.seek(0, 2)
        self.filesize = self.f.tell()
        self.base = self._find_header()
        if self.base is None:
            raise ValueError('no MPQ signature in %s' % path)
        self.f.seek(self.base)
        hdr = self.f.read(32)
        self.format_ver = struct.unpack_from('<H', hdr, 12)[0]
        self.sector_size = 512 << struct.unpack_from('<H', hdr, 14)[0]
        htp = self.base + struct.unpack_from('<I', hdr, 16)[0]
        btp = self.base + struct.unpack_from('<I', hdr, 20)[0]
        self.hts = struct.unpack_from('<I', hdr, 24)[0]
        self.bts = struct.unpack_from('<I', hdr, 28)[0]
        self.hash_table = self._read_table(htp, self.hts * 4, '(hash table)')
        self.block_table = self._read_table(btp, self.bts * 4, '(block table)')

    def _find_header(self):
        o = 0
        while o + 4 <= self.filesize:
            self.f.seek(o)
            if self.f.read(4) == b'MPQ\x1a':
                return o
            o += 512
        return None

    def _read_table(self, pos, nwords, keyname):
        self.f.seek(pos)
        raw = self.f.read(nwords * 4)
        words = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
        return decrypt_words(words, hash_string(keyname, 'key'))

    def find(self, name):
        """Return the block index for name, or -1."""
        if self.hts == 0:
            return -1
        start = hash_string(name, 'hash') % self.hts
        a, b = hash_string(name, 'nameA'), hash_string(name, 'nameB')
        for i in range(self.hts):
            e = (start + i) % self.hts
            o = e * 4
            bi = self.hash_table[o + 3]
            if bi == 0xFFFFFFFF:
                return -1
            if self.hash_table[o] == a and self.hash_table[o + 1] == b and bi != 0xFFFFFFFE:
                return bi
        return -1

    def exists(self, name):
        return self.find(name) >= 0

    def read(self, name):
        bi = self.find(name)
        if bi < 0:
            raise KeyError(name)
        o = bi * 4
        block_offset = self.block_table[o]
        packed_size = self.block_table[o + 1]
        fsize = self.block_table[o + 2]
        flags = self.block_table[o + 3]
        if not (flags & FLAG_EXISTS):
            raise KeyError('%s: no EXISTS flag' % name)
        pos = self.base + block_offset

        enc = bool(flags & FLAG_ENCRYPTED)
        comp = bool(flags & (FLAG_COMPRESS | FLAG_IMPLODE))
        key = 0
        if enc:
            key = hash_string(name.replace('/', '\\').split('\\')[-1], 'key')
            if flags & FLAG_FIX_KEY:
                key = ((key + block_offset) ^ fsize) & 0xFFFFFFFF

        def decrypt_bytes(buf, k):
            if not enc:
                return buf
            n = len(buf) // 4
            if n == 0:
                return buf
            words = list(struct.unpack('<%dI' % n, buf[:n * 4]))
            decrypt_words(words, k)
            return struct.pack('<%dI' % n, *words) + buf[n * 4:]

        def decomp(buf, out_size):
            if not comp or len(buf) >= out_size:
                return buf[:out_size]
            if flags & FLAG_IMPLODE:
                return explode(buf)[:out_size]
            method, body = buf[0], buf[1:]
            if method & 0x02:
                return zlib.decompress(body)[:out_size]
            if method & 0x08:
                return explode(body)[:out_size]
            if method & 0xC1:                       # WAVE: Huffman and/or ADPCM
                from mpq_wave import wave_decompress
                return wave_decompress(body, out_size, method)
            if method == 0:
                return body[:out_size]
            raise ValueError('%s: unsupported compression 0x%02x' % (name, method))

        if flags & FLAG_SINGLE:
            self.f.seek(pos)
            return decomp(decrypt_bytes(self.f.read(packed_size), key), fsize)

        # An uncompressed file (no COMPRESS/IMPLODE) has NO sector offset table
        # -- the payload sits raw at the block offset. Parsing a table anyway
        # reads garbage lengths; this is what broke every portrait .smk, which
        # are all stored with flags 0x80000000 (EXISTS only).
        if not comp:
            self.f.seek(pos)
            raw = self.f.read(fsize)
            if not enc:
                return raw
            out = bytearray()
            for i in range((fsize + self.sector_size - 1) // self.sector_size):
                chunk = bytearray(raw[i * self.sector_size:(i + 1) * self.sector_size])
                out += decrypt_bytes(bytes(chunk), (key + i) & 0xFFFFFFFF)
            return bytes(out[:fsize])

        nsec = (fsize + self.sector_size - 1) // self.sector_size
        self.f.seek(pos)
        sot_raw = self.f.read((nsec + 1) * 4)
        sot = list(struct.unpack('<%dI' % (nsec + 1), sot_raw))
        if enc:
            decrypt_words(sot, (key - 1) & 0xFFFFFFFF)
        out = bytearray()
        for i in range(nsec):
            self.f.seek(pos + sot[i])
            chunk = self.f.read(sot[i + 1] - sot[i])
            this_size = min(self.sector_size, fsize - i * self.sector_size)
            out += decomp(decrypt_bytes(chunk, (key + i) & 0xFFFFFFFF), this_size)
        return bytes(out[:fsize])

    def listfile(self):
        try:
            txt = self.read('(listfile)').decode('latin-1')
        except Exception:
            return []
        return [l.strip() for l in txt.replace('\r', '\n').split('\n') if l.strip()]


# StarCraft load order: later entries win, matching the engine's
# Patch_rt > BrooDat > StarDat precedence.
CHAIN_ORDER = ['StarCraft.mpq', 'BroodWar.mpq', 'StarDat.mpq', 'BrooDat.mpq', 'patch_rt.mpq']


class MpqChain:
    def __init__(self, path):
        self.archives = []
        if os.path.isfile(path):
            self.archives.append(Mpq(path))
        else:
            present = {f.lower(): f for f in os.listdir(path)}
            for want in CHAIN_ORDER:
                real = present.get(want.lower())
                if real:
                    self.archives.append(Mpq(os.path.join(path, real)))
        if not self.archives:
            raise ValueError('no MPQ archives under %s' % path)
        # highest precedence first
        self.archives.reverse()

    def read(self, name):
        name = name.replace('/', '\\')
        for a in self.archives:
            if a.exists(name):
                return a.read(name)
        raise KeyError(name)

    def exists(self, name):
        name = name.replace('/', '\\')
        return any(a.exists(name) for a in self.archives)

    def names(self):
        seen, out = set(), []
        for a in self.archives:
            for n in a.listfile():
                k = n.lower()
                if k not in seen:
                    seen.add(k)
                    out.append(n)
        return out

    def which(self, name):
        name = name.replace('/', '\\')
        for a in self.archives:
            if a.exists(name):
                return os.path.basename(a.path)
        return None


# ------------------------------------------------------------------ palettes
# The real palettes the engine uses, so decoded indices can finally be given
# authentic colour instead of debug hues.
PALETTE_FILES = [
    'unit\\cmdbtns\\ticon.pcx',   # command-icon palette (PCX trailer)
    'game\\tunit.pcx',            # 16 players x 8 team-colour entries
    'game\\twire.pcx',            # wireframe damage/shield ramps
    'game\\tselect.pcx',
    'game\\thpbar.pcx',
    'game\\tminimap.pcx',
    'game\\icons.grp',
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', help='directory holding the MPQs, or one .mpq')
    ap.add_argument('--list', nargs='?', const='', metavar='SUBSTR')
    ap.add_argument('--extract', metavar='INTERNAL\\PATH')
    ap.add_argument('--palettes', metavar='OUTDIR')
    ap.add_argument('-o', '--out')
    a = ap.parse_args()

    c = MpqChain(a.path)
    print('archives (highest precedence first): %s'
          % ', '.join(os.path.basename(x.path) for x in c.archives), file=sys.stderr)

    if a.list is not None:
        names = c.names()
        sub = a.list.lower()
        hits = [n for n in names if sub in n.lower()]
        print('%d names, %d matching' % (len(names), len(hits)), file=sys.stderr)
        for n in hits:
            print(n)
        return

    if a.extract:
        data = c.read(a.extract)
        out = a.out or os.path.basename(a.extract.replace('\\', '/'))
        with open(out, 'wb') as f:
            f.write(data)
        print('wrote %d bytes for %s (from %s)' % (len(data), a.extract, c.which(a.extract)))
        return

    if a.palettes:
        os.makedirs(a.palettes, exist_ok=True)
        for name in PALETTE_FILES:
            try:
                data = c.read(name)
            except Exception as e:
                print('  MISS %-32s %s' % (name, e))
                continue
            out = os.path.join(a.palettes, os.path.basename(name.replace('\\', '/')))
            with open(out, 'wb') as f:
                f.write(data)
            print('  ok   %-32s %7d B  (%s)' % (name, len(data), c.which(name)))
        # every tileset palette too
        for ts in ['badlands', 'platform', 'install', 'ashworld',
                   'jungle', 'desert', 'ice', 'twilight']:
            n = 'tileset\\%s.wpe' % ts
            try:
                data = c.read(n)
            except Exception:
                continue
            with open(os.path.join(a.palettes, '%s.wpe' % ts), 'wb') as f:
                f.write(data)
            print('  ok   %-32s %7d B' % (n, len(data)))
        return

    ap.print_help()


if __name__ == '__main__':
    main()
