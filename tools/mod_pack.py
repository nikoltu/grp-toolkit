#!/usr/bin/env python3
"""Mod packager for the OpenBW-Android launcher's overlay mod system
(docs/MOD-ARCHITECTURE.md in that repo). Produces a .zip the launcher imports to
``files/mods/<mod-id>/`` — NOT an injection into the original MPQs. The engine's
loose-file loader checks ``files/mods/<id>/data/<path>`` BEFORE the MPQ chain, so
the mod's fragments override the base game by path, highest priority first.

Zip layout produced (contents at the ROOT — the launcher's unzipMod extracts
straight into ``files/mods/<id>/`` and derives ``<id>`` from the ZIP FILENAME,
not from mod.json; verified against openbw-android SetupActivity.java:3368/3181):
    mod.json                       # manifest (only launcher-read fields)
    data/<game-path>               # loose override files (default)
    data.mpq                       # instead, if use_mpq=True (via mpq_writer)
    toolkit-provenance.json        # our extra metadata (unknown fields are ignored)

So `mod_id` here is just the intended zip *filename* (write_mod names the file
``<mod_id>.zip``); it is NOT written into mod.json and NOT used as a folder
prefix. `files` maps a game path (e.g. ``scripts\\aiscript.bin``) to bytes,
normalised to lowercase forward-slash under ``data/`` — the exact path the engine
requests (bwgame load_data_file; the loose loader tries original case AND
lowercase). The zip is deterministic (sorted entries, fixed 1980 timestamps).

Oracle: build → read the zip back → every override file byte-identical and at the
expected ``<id>/data/<path>``; mod.json carries the required fields
(tests/test_mod_pack.py). Ties the whole toolkit together: ai_asm bytecode,
wireframe-colors.json and hud layouts pack straight into a launcher-ready mod.
"""
import io
import json
import zipfile


def _norm(path):
    """Game path -> loose overlay path: backslash->slash, strip leading slashes,
    lowercase (Android loose files are case-sensitive; the engine requests
    lowercase forward-slash, per the architecture doc)."""
    return path.replace('\\', '/').lstrip('/').lower()


def make_manifest(name, version='1.0', type='data', author=None,
                  description=None, depends=None, executable=False):
    """mod.json with ONLY the fields the launcher's readModJson actually reads
    (name, type, version, author, description, depends[], executable). All are
    optional; `id` and `priority` are NOT stored — the engine takes id from the
    zip/folder name and priority from the --mods activation order."""
    m = {'name': name, 'version': str(version), 'type': type}
    if author:
        m['author'] = author
    if description:
        m['description'] = description
    if depends:
        m['depends'] = list(depends)
    if executable:
        m['executable'] = True
    return m


def _zi(name):
    zi = zipfile.ZipInfo(name)                 # date_time defaults to 1980-01-01
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    return zi


def build_mod(mod_id, name, files, version='1.0', mod_type='data',
              author=None, description=None, use_mpq=False, provenance=None):
    """Return the mod .zip as bytes. Contents sit at the ROOT (no <id>/ prefix).

    mod_id is only the intended zip filename (used by write_mod and provenance).
    files: {game_path: bytes}. use_mpq=True packs them into data.mpq via the MPQ
    writer instead of loose data/<path>."""
    manifest = make_manifest(name, version, mod_type, author, description)
    entries = {}                               # arcname -> bytes (sorted at write)
    if use_mpq:
        import mpq_writer
        entries['data.mpq'] = mpq_writer.build_mpq(
            {p.replace('/', '\\'): b for p, b in files.items()})
    else:
        for p, b in files.items():
            entries['data/' + _norm(p)] = b
    entries['mod.json'] = json.dumps(manifest, indent=2,
                                     sort_keys=True).encode('utf-8')
    prov = {'generator': 'grp-toolkit mod_pack', 'intended_id': mod_id,
            'storage': 'mpq' if use_mpq else 'loose',
            'overrides': sorted(_norm(p) for p in files)}
    if provenance:
        prov.update(provenance)
    entries['toolkit-provenance.json'] = json.dumps(
        prov, indent=2, sort_keys=True).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for arc in sorted(entries):
            zf.writestr(_zi(arc), entries[arc])
    return buf.getvalue()


def write_mod(path, mod_id, name, files, **kw):
    with open(path, 'wb') as f:
        f.write(build_mod(mod_id, name, files, **kw))


# ---- optional pre-flight validation with our own readers ----
def validate_files(files):
    """Best-effort sanity check of known asset types before packing; returns a
    list of warning strings (empty = all good). A broken aiscript or GRP is
    caught here instead of shipping. Unknown types are skipped."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    warns = []
    for path, data in files.items():
        low = path.replace('\\', '/').lower()
        try:
            if low.endswith(('aiscript.bin', 'bwscript.bin')):
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ai'))
                import ai_bin
                import ai_disasm
                f = ai_bin.parse(data, ai_bin.BWSCRIPT if 'bw' in low
                                 else ai_bin.AISCRIPT)
                for e in f.entries:
                    if not e.used:
                        continue
                    ok, info = ai_disasm.trace_reachable(f.data, e.offset,
                                                         f.table_offset)
                    if not ok:
                        warns.append('%s: script %s does not decode (%s)'
                                     % (path, e.fourcc, info.get('error')))
                        break
            elif low.endswith('.grp'):
                import struct
                fc, w, h = struct.unpack_from('<HHH', data, 0)
                if not (0 < fc < 10000 and 0 < w <= 800 and 0 < h <= 800):
                    warns.append('%s: implausible GRP header %dx%d f%d'
                                 % (path, w, h, fc))
        except Exception as e:                  # noqa: BLE001
            warns.append('%s: validation error %s' % (path, e))
    return warns


if __name__ == '__main__':
    import sys
    import os
    if len(sys.argv) < 4:
        print('usage: mod_pack.py <mod-id> <out.zip> <game_path=localfile> ...')
        print('  e.g. mod_pack.py mymod mymod.zip scripts\\\\aiscript.bin=edited.bin')
        sys.exit(1)
    mod_id, out = sys.argv[1], sys.argv[2]
    files = {}
    for arg in sys.argv[3:]:
        gp, lf = arg.split('=', 1)
        files[gp] = open(lf, 'rb').read()
    for w in validate_files(files):
        print('WARN', w)
    write_mod(out, mod_id, mod_id, files)
    print('wrote %s (%d files, %d bytes)' % (out, len(files), os.path.getsize(out)))
