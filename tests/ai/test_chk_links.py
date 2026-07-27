"""Corpus oracle for the CHK -> AI-script mission linkage.

Over every .scm/.scx in the install's maps folder, extracts each "Run AI Script
[At Location]" trigger action and resolves its script FourCC against the
aiscript.bin / bwscript.bin tables. The check: EVERY referenced script id must
exist in the tables. A wrong FourCC field offset or endianness in the action
struct would make ids fail to resolve, so full resolution is a statement about
the whole action layout.

Measured 2026-07 (BW 1.16.1): 210 maps scanned, 8 with AI triggers, 67 AI-script
links, 67/67 resolve. (The main Blizzard campaigns live in campaign MPQs, not as
loose maps; only bonus campaigns like Enslavers are on disk - what is present is
fully covered.)

    py test_chk_links.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'ai'))
from common import BW, need, report      # noqa: E402
import campaign_index                    # noqa: E402
import chk_ai_links                      # noqa: E402


def main():
    need(BW, 'Brood War install')
    need(os.path.join(BW, 'maps'), 'maps folder')
    tables = chk_ai_links.load_ai_tables(BW)
    if not tables:
        print('SKIP: AI script tables not found')
        sys.exit(77)
    import mpq
    missions, usage, stats = campaign_index.build_index(
        BW, tables, mpq_chain=mpq.MpqChain(BW))
    if stats['links'] == 0:
        print('SKIP: no AI-script triggers found in any map')
        sys.exit(77)
    extra = ('(%d maps, %d with AI, %d shared scripts; unresolved=%s)'
             % (stats['maps_scanned'], stats['maps_with_ai'],
                sum(1 for s in usage if len(usage[s]) > 1),
                stats['unresolved'][:5] if stats['unresolved'] else 'none'))
    rc = report('ai: CHK links resolve in script table',
                stats['resolved'], stats['links'], extra)
    sys.exit(rc)


if __name__ == '__main__':
    main()
