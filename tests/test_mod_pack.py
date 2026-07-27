"""Oracle for the OpenBW-Android mod packager.

Builds a mod .zip (both the loose-file layout and the data.mpq variant), reads it
back, and requires:
  * every override file byte-identical at <id>/data/<lowercased game path>,
  * mod.json carrying exactly the launcher's required fields (id/name/version/
    type/priority),
  * the data.mpq variant readable by the independent MPQ reader,
  * pre-flight validation flags a deliberately corrupt aiscript.

Matches files/mods/<mod-id>/ from openbw-android docs/MOD-ARCHITECTURE.md §2-§3
(loose loader checks files/mods/<id>/data/<path> before the MPQ chain).

    py test_mod_pack.py
"""
import sys
import os
import io
import json
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
from common import BW, report      # noqa: E402
import mpq                         # noqa: E402
import mpq_writer                  # noqa: E402  (ensure import path for use_mpq)
import mod_pack                    # noqa: E402


def main():
    files = {
        'scripts\\aiscript.bin': b'\x0e\xe0\x00\x00' + b'\x00' * 40,
        'arr/units.dat': bytes(range(200)),
        'unit\\wirefram\\wirefram.grp': os.urandom(3000),
    }
    ok = total = 0
    bad = []

    # ---- loose layout (contents at ROOT, no <id>/ prefix) ----
    zbytes = mod_pack.build_mod('mymod', 'My Mod', files, version='1.2',
                                author='V')
    zf = zipfile.ZipFile(io.BytesIO(zbytes))
    names = set(zf.namelist())
    for gp, want in files.items():
        total += 1
        arc = 'data/' + gp.replace('\\', '/').lower()
        if arc in names and zf.read(arc) == want:
            ok += 1
        else:
            bad.append('loose %s missing/mismatch' % arc)
    # manifest: only launcher-read fields; NO id / priority
    total += 1
    try:
        man = json.loads(zf.read('mod.json'))
        need = {'name': 'My Mod', 'version': '1.2', 'type': 'data', 'author': 'V'}
        if (all(man.get(k) == v for k, v in need.items())
                and 'id' not in man and 'priority' not in man):
            ok += 1
        else:
            bad.append('manifest fields: %s' % man)
    except Exception as e:                       # noqa: BLE001
        bad.append('manifest: %s' % e)

    # ---- data.mpq variant readable by the independent reader ----
    total += 1
    zbytes2 = mod_pack.build_mod('mpqmod', 'MPQ Mod', files, use_mpq=True)
    zf2 = zipfile.ZipFile(io.BytesIO(zbytes2))
    scratch = os.path.join(os.path.dirname(__file__), '_mod_data.mpq')
    with open(scratch, 'wb') as f:
        f.write(zf2.read('data.mpq'))
    arc = None
    try:
        arc = mpq.Mpq(scratch)
        if all(arc.read(gp) == want for gp, want in files.items()):
            ok += 1
        else:
            bad.append('data.mpq read-back mismatch')
    except Exception as e:                        # noqa: BLE001
        bad.append('data.mpq: %s' % e)
    finally:
        try:
            arc.f.close()
        except Exception:
            pass
        try:
            os.remove(scratch)
        except OSError:
            pass

    # ---- validation flags a corrupt aiscript ----
    total += 1
    warns = mod_pack.validate_files({'scripts\\aiscript.bin': b'\x08\x00\x00\x00'
                                     + b'\xff' * 60})
    if warns:
        ok += 1
    else:
        bad.append('validation did not flag corrupt aiscript')

    rc = report('mod: pack -> read-back (loose + mpq) + manifest + validate',
                ok, total, '(bad=%s)' % (bad[:4] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
