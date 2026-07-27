"""Assemble the single self-contained sc-asset-browser.html from readable source
pieces in src/ -- and split an existing built file back into those pieces.

WHY: the shipped app must stay ONE file that works from file:// with no server
(CLAUDE.md 2). But 67% of it was an embedded 10 626-name listfile drowning the
~4 300 lines of actual code in every editor/grep/diff. This build step keeps the
dev tree readable (template + css + js + data) while the shipped artifact stays
self-contained.

The extraction is byte-lossless: `--extract` slices the current file by its tag
boundaries into src/, and `build` splices them back. The oracle
(tests/test_build_html.py) asserts build(extract(x)) == x byte-for-byte, so the
split provably loses nothing before any source edit is made.

Layout:
    src/app.template.html   the shell, with %%CSS%% %%LISTFILE%% %%JS%% markers
    src/app.css             contents of <style>...</style>
    src/data/listfile.txt   contents of the builtin listfile <script>
    src/app.js              contents of the main <script>...</script>

Everything is handled as BYTES (no decode) so newlines / non-ASCII (Lithuanian,
Korean unit names) round-trip exactly.

    py tools/build_html.py --extract      # one-time bootstrap from the built file
    py tools/build_html.py                # rebuild sc-asset-browser.html from src/
    py tools/build_html.py --check        # rebuild to memory, diff vs the built file
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT = os.path.join(ROOT, 'sc-asset-browser.html')
SRC = os.path.join(ROOT, 'src')
TEMPLATE = os.path.join(SRC, 'app.template.html')
CSS = os.path.join(SRC, 'app.css')
JS = os.path.join(SRC, 'app.js')
LISTFILE = os.path.join(SRC, 'data', 'listfile.txt')

# Byte boundaries. Each region's CONTENT is what sits between the open marker's
# end and the close marker's start; the markers themselves stay in the template.
CSS_OPEN = b'<style>'
CSS_CLOSE = b'</style>'
LF_OPEN = b'<script type="text/plain" id="builtinListfile">'
JS_OPEN = b'<script>'
SCRIPT_CLOSE = b'</script>'

M_CSS = b'%%CSS%%'
M_LISTFILE = b'%%LISTFILE%%'
M_JS = b'%%JS%%'


def _span(hay, open_tok, close_tok, start=0):
    """Return (content_start, content_end, region_start, region_end) for the text
    between open_tok and the first close_tok after it, searching from `start`."""
    o = hay.index(open_tok, start)
    cstart = o + len(open_tok)
    cend = hay.index(close_tok, cstart)
    return cstart, cend, o, cend + len(close_tok)


def extract():
    html = open(BUILT, 'rb').read()
    # CSS
    css_s, css_e, _, _ = _span(html, CSS_OPEN, CSS_CLOSE)
    # builtin listfile <script type=text/plain ...> ... </script>
    lf_s, lf_e, lf_o, _ = _span(html, LF_OPEN, SCRIPT_CLOSE, start=css_e)
    # main <script> ... </script>  (first <script> after the listfile block)
    js_s, js_e, _, _ = _span(html, JS_OPEN, SCRIPT_CLOSE, start=lf_e)

    css = html[css_s:css_e]
    listfile = html[lf_s:lf_e]
    js = html[js_s:js_e]

    # Build the template: replace each content span with its marker, back to front
    # so earlier offsets stay valid.
    tpl = html
    tpl = tpl[:js_s] + M_JS + tpl[js_e:]
    tpl = tpl[:lf_s] + M_LISTFILE + tpl[lf_e:]
    tpl = tpl[:css_s] + M_CSS + tpl[css_e:]

    os.makedirs(os.path.dirname(LISTFILE), exist_ok=True)
    open(TEMPLATE, 'wb').write(tpl)
    open(CSS, 'wb').write(css)
    open(LISTFILE, 'wb').write(listfile)
    open(JS, 'wb').write(js)
    print('extracted: template %d B, css %d B, listfile %d B, js %d B'
          % (len(tpl), len(css), len(listfile), len(js)))


def build_bytes():
    tpl = open(TEMPLATE, 'rb').read()
    css = open(CSS, 'rb').read()
    listfile = open(LISTFILE, 'rb').read()
    js = open(JS, 'rb').read()
    for marker, name in ((M_CSS, 'CSS'), (M_LISTFILE, 'LISTFILE'), (M_JS, 'JS')):
        if marker not in tpl:
            raise SystemExit('template is missing marker %s' % name)
    out = tpl.replace(M_CSS, css).replace(M_LISTFILE, listfile).replace(M_JS, js)
    return out


def build():
    out = build_bytes()
    open(BUILT, 'wb').write(out)
    print('built %s (%d B)' % (os.path.basename(BUILT), len(out)))


def check():
    out = build_bytes()
    cur = open(BUILT, 'rb').read()
    if out == cur:
        print('OK: rebuild is byte-identical to %s (%d B)'
              % (os.path.basename(BUILT), len(out)))
        return 0
    # first differing offset, for diagnosis
    n = min(len(out), len(cur))
    i = next((k for k in range(n) if out[k] != cur[k]), n)
    print('DIFF: rebuild %d B vs built %d B; first diff @ %d' % (len(out), len(cur), i))
    print('  built : ...%r' % cur[max(0, i - 20):i + 20])
    print('  rebuilt: ...%r' % out[max(0, i - 20):i + 20])
    return 1


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == '--extract':
        extract()
    elif arg == '--check':
        sys.exit(check())
    else:
        build()
