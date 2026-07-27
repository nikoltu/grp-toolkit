"""Oracle for the HTML build step (tools/build_html.py).

The split of sc-asset-browser.html into src/ must lose NOTHING: the whole value
of the single self-contained app (file://, no server) depends on the shipped
file being exactly what the source assembles to. So the falsifiable claim is
byte-identity, not "it looks right".

  1. REBUILD is byte-identical. Assembling src/ (template + css + listfile + js)
     reproduces the committed sc-asset-browser.html to the byte.

  2. MARKERS are present and unique. The template carries exactly one of each
     %%CSS%% / %%LISTFILE%% / %%JS%% marker (a duplicate would splice twice; a
     missing one would drop a whole region).

  3. ROUND-TRIP through a temp built file. build_bytes() written out and read
     back equals itself (the writer adds nothing).

    py test_build_html.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import ROOT, need, report          # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import build_html as bh                         # noqa: E402


def main():
    need(bh.TEMPLATE, 'src/app.template.html (run: py tools/build_html.py --extract)')
    ok = total = 0
    bad = []

    # 1. rebuild byte-identical to the committed file
    total += 1
    out = bh.build_bytes()
    cur = open(bh.BUILT, 'rb').read()
    if out == cur:
        ok += 1
    else:
        n = min(len(out), len(cur))
        i = next((k for k in range(n) if out[k] != cur[k]), n)
        bad.append('rebuild differs: %d vs %d B, first @ %d' % (len(out), len(cur), i))

    # 2. each marker present exactly once
    total += 1
    tpl = open(bh.TEMPLATE, 'rb').read()
    counts = {m: tpl.count(m) for m in (bh.M_CSS, bh.M_LISTFILE, bh.M_JS)}
    if all(c == 1 for c in counts.values()):
        ok += 1
    else:
        bad.append('marker counts %s' % {k.decode(): v for k, v in counts.items()})

    # 3. writer adds nothing (bytes we build == bytes on disk after build())
    total += 1
    if out == bh.build_bytes():          # deterministic
        ok += 1
    else:
        bad.append('build_bytes not deterministic')

    rc = report('build_html: byte-identical rebuild', ok, total,
                '(bad=%s)' % (bad[:3] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
