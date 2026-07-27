"""Shared setup for the verification scripts.

Every claim in this project has a script here that re-proves it against the
real archives. If a number in the docs and a number here disagree, the script
is right and the doc is stale.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

# Override with env vars if the installs move.
BW = os.environ.get('SC_BW_DIR', r'C:\Git\Starcraft BroodWar  v1.1.61')
SCR = os.environ.get('SCR_DIR', r'C:\Git\StarCraft Remastered')
CASC_DATA = os.path.join(SCR, 'data', 'data')


def need(path, what):
    if not os.path.exists(path):
        print('SKIP: %s not found (%s)' % (what, path))
        sys.exit(77)
    return path


def report(name, ok, total, extra=''):
    """One line a human and a future session can both read."""
    verdict = 'PASS' if ok == total and total > 0 else 'FAIL'
    print('%-7s %-34s %d / %d %s' % (verdict, name, ok, total, extra))
    return 0 if verdict == 'PASS' else 1
