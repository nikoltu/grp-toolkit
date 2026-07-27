"""Threaded static file server for the browser-based tests.

The stock `python -m http.server` is single-threaded and drops requests when
vp8-oracle.html fetches hundreds of files back to back. This serves the repo
root with a thread pool so the oracle runs cleanly. Used by .claude/launch.json.
"""
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8731), Handler).serve_forever()
