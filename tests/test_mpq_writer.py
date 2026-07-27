"""Oracle for the MPQ writer: build → read back → byte-identical.

Builds an MPQ from a set of files (including real assets pulled from BW so the
sizes/contents are representative), reads every one back with the INDEPENDENT
reader tools/mpq.py, and requires each to come out byte-for-byte identical. A
wrong hash slot, table encryption, or block-table field would make a file fail
to resolve or read wrong. The listfile must also enumerate exactly the inputs.

(The ultimate check — retail Storm.dll loading the archive — is manual; this
proves the writer and our own reader agree, which is the automatable half.)

    py test_mpq_writer.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
from common import BW, need, report      # noqa: E402
import mpq                               # noqa: E402
import mpq_writer                        # noqa: E402


def main():
    scratch = os.path.join(os.path.dirname(__file__), '_mpq_writer_test.mpq')
    files = {
        'scripts\\test.txt': b'hello world' * 100,
        'small.bin': bytes(range(256)),
        'empty.dat': b'',
        'nested\\path\\file.dat': os.urandom(5000),
    }
    # add a couple of real BW assets if available (representative sizes)
    if os.path.isdir(BW):
        try:
            ch = mpq.MpqChain(BW)
            for nm in ['scripts\\aiscript.bin', 'game\\twire.pcx']:
                try:
                    files[nm] = ch.read(nm)
                except Exception:
                    pass
        except Exception:
            pass

    mpq_writer.write_mpq(scratch, files)
    ok = total = 0
    bad = []
    try:
        arc = mpq.Mpq(scratch)
        for name, want in files.items():
            total += 1
            try:
                got = arc.read(name)
            except Exception as e:                # noqa: BLE001
                bad.append('%s: read error %s' % (name, e))
                continue
            if got == want:
                ok += 1
            else:
                bad.append('%s: %d vs %d bytes' % (name, len(got), len(want)))
        # listfile round-trips
        total += 1
        lf = set(arc.listfile())
        if all(n in lf for n in files) and '(listfile)' in lf:
            ok += 1
        else:
            bad.append('listfile mismatch: %s' % (set(files) - lf))
    finally:
        try:
            arc.f.close()
        except Exception:
            pass
        try:
            os.remove(scratch)
        except OSError:
            pass

    rc = report('mpq: write -> read-back byte-identical', ok, total,
                '(%d files; bad=%s)' % (len(files), bad[:4] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
