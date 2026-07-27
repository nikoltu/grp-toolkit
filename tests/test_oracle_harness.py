"""Oracle for the engine-support harness (golden.py + asset_diff.py).

These tools ARE oracles, so this proves the oracles themselves behave:

  1. GOLDEN self-consistency. A manifest checked against itself is all-match; a
     tampered entry reports `changed`; a dropped target reports `gone`; an unseen
     target reports `new`. (The regression net fires on exactly the real events.)
  2. DETERMINISM. Every default target decodes byte-identically across repeated
     runs (the decoders are pure functions of their input).
  3. ASSET-DIFF identity + sensitivity. A CASC install diffed against itself has
     zero changed/added/removed; a synthetic one-CKey edit surfaces as exactly
     one `changed`; a dropped/added name surfaces as `removed`/`added`.

    py test_oracle_harness.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import BW, SCR, need, report                 # noqa: E402
import golden                                             # noqa: E402
import asset_diff                                         # noqa: E402


def main():
    need(BW, 'Brood War install')
    need(SCR, 'SC:R install')
    ctx = golden.make_ctx(BW, SCR)
    targets = golden.default_targets()

    ok = total = 0
    bad = []

    # 1. golden self-consistency + tamper detection
    total += 1
    m = golden.manifest(targets, ctx)
    if any(v.startswith('ERR') for v in m.values()):
        bad.append('manifest errors %s' % [k for k, v in m.items() if v.startswith('ERR')][:2])
    res, changed = golden.check_golden(targets, m, ctx)
    self_match = changed == 0 and all(s == 'match' for _, s in res)
    tampered = dict(m)
    first = sorted(tampered)[0]
    tampered[first] = 'deadbeef'
    _, ch_t = golden.check_golden(targets, tampered, ctx)
    dropped = {k: v for k, v in list(m.items())[1:]}     # golden missing target 0 -> 'new'
    res_d, _ = golden.check_golden(targets, dropped, ctx)
    has_new = any(s == 'new' for _, s in res_d)
    extra = dict(m); extra['grp:unit\\ghost.grp'] = 'x'  # golden has an asset we no longer decode
    res_e, _ = golden.check_golden(targets, extra, ctx)
    has_gone = any(s == 'gone' for _, s in res_e)
    if self_match and ch_t == 1 and has_new and has_gone:
        ok += 1
    else:
        bad.append('golden self=%s tamper=%d new=%s gone=%s'
                   % (self_match, ch_t, has_new, has_gone))

    # 2. determinism over the default targets
    total += 1
    det = golden.check_determinism(targets, ctx)
    stable = sum(1 for _, s in det if s)
    if stable == len(det):
        ok += 1
    else:
        bad.append('unstable %s' % [k for k, s in det if s is not True][:2])

    # 3. asset-diff identity + sensitivity
    total += 1
    idx = asset_diff.casc_index(SCR)
    ident = asset_diff.diff_index(idx, idx)
    identity_ok = not ident['changed'] and not ident['added'] and not ident['removed']
    # synthetic edit: change one ckey, drop one name, add one name
    keys = sorted(idx)
    edited = dict(idx)
    edited[keys[0]] = 'ff' * 16
    del edited[keys[1]]
    edited['fake/added_asset.dds'] = 'ab' * 16
    d = asset_diff.diff_index(idx, edited)
    sens_ok = (keys[0] in d['changed'] and len(d['changed']) == 1
               and keys[1] in d['removed'] and 'fake/added_asset.dds' in d['added'])
    if identity_ok and sens_ok:
        ok += 1
    else:
        bad.append('diff identity=%s sens=%s' % (identity_ok, sens_ok))

    # 4. committed golden manifest matches a fresh decode (the engine's stable
    #    cross-impl diff target stays current). Compare only entries non-ERR in both.
    total += 1
    import json
    mpath = os.path.join(os.path.dirname(__file__), '..', 'assets', 'golden_manifest.json')
    if os.path.exists(mpath):
        committed = json.load(open(mpath))
        fresh = golden.manifest(targets, ctx)
        comparable = [k for k in committed
                      if not committed[k].startswith('ERR')
                      and k in fresh and not fresh[k].startswith('ERR')]
        mism = [k for k in comparable if committed[k] != fresh[k]]
        if comparable and not mism:
            ok += 1
        else:
            bad.append('committed manifest: %d comparable, mism=%s' % (len(comparable), mism[:2]))
    else:
        bad.append('assets/golden_manifest.json missing')

    rc = report('oracle harness: golden+diff+manifest', ok, total,
                '(%d targets, %d casc names; bad=%s)'
                % (len(targets), len(idx), bad[:2] if bad else 'none'))
    sys.exit(rc)


if __name__ == '__main__':
    main()
