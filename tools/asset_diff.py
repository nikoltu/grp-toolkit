#!/usr/bin/env python3
"""Patch asset-diff: what assets changed between two StarCraft installs.

When SC:R (or BW) ships a patch, the engine port needs to know which assets
actually moved - a graphics change means re-checking the HD pipeline, a DAT
change means re-reading the balance tables. This diffs two installs by CONTENT and
reports added / removed / changed names, so a patch review is a list, not a guess.

CASC is exact and cheap here: the root file already maps every name to its CKey,
and a CKey IS the content hash (MD5 of the file). So two installs agree on a file
iff they list the same CKey for it - no decoding, no reading the blobs. Name-set
difference gives added/removed. (MPQ has no exposed content hash, so the MPQ mode
reads + sha-256s each file; slower, same result shape.)

    py asset_diff.py --casc <OLD_SCR> <NEW_SCR>
    py asset_diff.py --mpq  <OLD_BW>  <NEW_BW>

No third-party libraries. Reuses casc.py / mpq.py.
"""
import os
import sys
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def casc_index(install_root):
    """{name: ckey_hex} for every named file in a CASC install (content identity)."""
    import casc
    st = casc.NamedStorage(os.path.join(install_root, 'data', 'data'),
                           install_root=install_root)
    if not st.root:
        raise SystemExit('no build config/root under %s' % install_root)
    return dict(st.root)                                 # name(lower) -> ckey hex


def mpq_index(install_root, names=None):
    """{name: sha256} for an MPQ chain. Reads each file (no content hash in MPQ).
    `names` limits the set; default is the chain's resolved listfile."""
    import mpq
    ch = mpq.MpqChain(install_root)
    idx = {}
    for nm in (names if names is not None else ch.names()):
        try:
            idx[nm.lower()] = hashlib.sha256(ch.read(nm)).hexdigest()
        except Exception:                                # noqa: BLE001
            continue
    return idx


def diff_index(old, new):
    """Diff two {name: hash} maps. Returns a dict with added / removed / changed
    (sorted name lists) and same (count)."""
    ok, nk = set(old), set(new)
    added = sorted(nk - ok)
    removed = sorted(ok - nk)
    changed = sorted(k for k in (ok & nk) if old[k] != new[k])
    same = len(ok & nk) - len(changed)
    return {'added': added, 'removed': removed, 'changed': changed, 'same': same}


def summarize(d, top=40):
    lines = ['%d changed, %d added, %d removed, %d unchanged'
             % (len(d['changed']), len(d['added']), len(d['removed']), d['same'])]
    for kind in ('changed', 'added', 'removed'):
        for nm in d[kind][:top]:
            lines.append('  %-9s %s' % (kind.upper(), nm))
        if len(d[kind]) > top:
            lines.append('  ...        (+%d more %s)' % (len(d[kind]) - top, kind))
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Diff two installs by asset content.')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--casc', action='store_true', help='two SC:R install roots')
    mode.add_argument('--mpq', action='store_true', help='two BW install roots')
    ap.add_argument('old')
    ap.add_argument('new')
    args = ap.parse_args()
    if args.casc:
        old, new = casc_index(args.old), casc_index(args.new)
    else:
        old, new = mpq_index(args.old), mpq_index(args.new)
    print(summarize(diff_index(old, new)))
