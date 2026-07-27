#!/usr/bin/env python3
"""Extract one or more files from a StarCraft install to disk.

The toolkit reads containers in memory; this is the missing CLI for when another
tool - or the parallel OpenBW session - needs the RAW BYTES of a specific asset
on disk to point its own code at. The motivating case: pull the exact
scripts\\aiscript.bin the engine loaded, then disassemble a pc offset in it
(see ai/ai_disasm.py --at).

  # Brood War MPQ chain (patch_rt > BrooDat > StarDat)
  py extract.py --bw "C:\\Git\\Starcraft BroodWar  v1.1.61" scripts\\aiscript.bin
  py extract.py --bw <dir> scripts\\aiscript.bin -o aiscript.bin
  py extract.py --bw <dir> arr\\units.dat arr\\weapons.dat -d out

  # SC:R CASC (pass the INSTALL ROOT, the folder with .build.info)
  py extract.py --scr "C:\\Git\\StarCraft Remastered" anim\\main_menu.anim -o mm.anim

Game paths use the backslash convention; quote or double them on the shell.
Output: -o NAME for a single file, or -d DIR to write each under its basename
(default: current directory).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _read_bw(install, name):
    import mpq
    return mpq.MpqChain(install).read(name)


def _read_scr(install, name):
    import casc
    data_dir = os.path.join(install, 'data', 'data')
    st = casc.NamedStorage(data_dir, install_root=install)
    return st.read_name(name)


def main():
    ap = argparse.ArgumentParser(
        description='Extract files from a StarCraft install to disk.')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--bw', metavar='DIR', help='Brood War install (MPQ chain)')
    g.add_argument('--scr', metavar='DIR', help='SC:R install root (CASC)')
    ap.add_argument('paths', nargs='+',
                    help='game paths, e.g. scripts\\aiscript.bin')
    ap.add_argument('-o', metavar='FILE', help='output file (single path only)')
    ap.add_argument('-d', metavar='DIR',
                    help='output directory (basename per file)')
    args = ap.parse_args()

    if args.o and len(args.paths) > 1:
        ap.error('-o takes a single path; use -d for multiple files')

    reader = ((lambda n: _read_bw(args.bw, n)) if args.bw
              else (lambda n: _read_scr(args.scr, n)))
    if args.d:
        os.makedirs(args.d, exist_ok=True)

    rc = 0
    for p in args.paths:
        try:
            data = reader(p)
        except Exception as e:                       # noqa: BLE001
            print('FAIL  %s: %s' % (p, e))
            rc = 1
            continue
        out = args.o or os.path.join(args.d or '.',
                                     os.path.basename(p.replace('\\', '/')))
        with open(out, 'wb') as f:
            f.write(data)
        print('OK    %s -> %s  (%d B)' % (p, out, len(data)))
    sys.exit(rc)


if __name__ == '__main__':
    main()
