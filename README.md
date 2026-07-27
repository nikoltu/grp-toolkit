# grp-toolkit

A dependency-free toolkit for reading, decoding, viewing, and editing the asset
containers and media formats of a classic real-time-strategy game and its modern
remaster. Every decoder is written from a published specification or measured
directly from real files — **no third-party libraries** — and is verified
byte-for-byte against an independent reference.

## What it does

- **Archives.** Decodes two generations of proprietary asset containers — a
  legacy hash-indexed format (with per-file compression and encryption) and a
  modern content-addressed store — resolving names to raw bytes.
- **Graphics.** Decodes the sprite stack: indexed-palette sprite archives,
  block-compressed (S3TC/DXT) HD texture sprites, and layered HD sprite atlases
  with per-layer composition and team-colour tinting.
- **Media.** Decodes the video stack — open web video (VP8 / VP9 in WebM) and a
  legacy full-motion-video codec — to raw frames, plus compressed audio to PCM.
- **Data.** Reads and writes the data stack — struct-of-arrays game-data tables,
  string tables, map/scenario files, and animation/AI script bytecode — each with
  a byte-exact round-trip, so edits produce valid files.
- **Replays.** Decodes the player-input stream (both container generations) into
  a readable, per-player command log, and down-converts between them.
- **Modding.** Editors for data tables, string tables, sprites, and scripts that
  package edits into an overlay mod bundle.

## How it's built

- **Python** (standard library only) — the reference decoders and command-line
  tools.
- **C++** (header-only, no dependencies) — a second, independently written
  decoder set plus an SDL2 viewer.
- **A single self-contained HTML page** — a browser application that runs from
  `file://` with no server, mirrors every decoder, and hosts the editors.

## Why byte-exact

The toolkit doubles as an **independent reference oracle** for a separate engine
reimplementation. Two implementations written from different sources, diffed
byte-for-byte, turn "the engine decodes this correctly" into a checkable fact
rather than an opinion. The video decoders match reference libraries across the
full asset corpus with zero differences.

## Verification

Every claim in this repository is backed by a runnable check under `tests/` — one
script per claim, run against real files. If a script and a comment ever
disagree, the script is authoritative. The checks are not unit tests: they run
against an actual game install and compare against independent sources (a
reference library, or the same asset shipped uncompressed in the other archive
generation), so a passing run is a byte-for-byte statement about real data.

Run them from the `tests/` directory:

```powershell
py test_casc_and_shared.py     # archives resolve; shared assets byte-identical across generations
py test_wav_vs_casc.py 300     # audio decoder output == the uncompressed copies
py test_smk_corpus.py          # legacy FMV decoder over the whole portrait corpus
py test_vp8_pixels.py          # VP8 key frames vs a reference library
py test_vp9_pixels.py          # VP9 key frames reconstruct + deblock
py test_dat.py                 # data-table read/write byte-identical round-trip
py test_combat.py              # independent damage-calculation reference
py rep/test_rep.py             # replay decode: container + full command stream
# …and one script per remaining decoder/editor (see the tests/ directory).
```

Each prints a single `PASS`/`FAIL` line and exits non-zero on failure; exit code
`77` means a required install was not found. Install paths come from
`tests/common.py` and can be overridden with the `SC_BW_DIR` / `SCR_DIR`
environment variables.

## License

Released under the **MIT License** — see [`LICENSE`](LICENSE).

## Third-party notices

All decoding *algorithms* are written from published specifications or measured
from files. A few small pieces of **format data** (constant tables that cannot be
derived) are reused, each under a permissive license, with thanks:

- **StormLib** (© 1999–2013 Ladislav Zezula) — *MIT.* Compression Huffman weight
  tables and ADPCM step tables used by the audio decoder.
- **PyMS** (© poiuy_qwert and contributors) — *MIT.* The animation/AI script
  opcode tables (extracted mechanically and coverage-verified).
- **screp** (© András Belicza / icza) — *Apache-2.0.* Replay command names.
- **blast / zlib** (© Mark Adler) — *zlib license.* Archive decompression tables.
- **RFC 6386 (VP8)** and the **VP9 bitstream specification** — the video decoder
  constant tables are extracted from these public specifications.

Each borrowed table is flagged at its point of use in the source.

## No affiliation

This is an independent, clean-room interoperability toolkit. It is **not
affiliated with, endorsed by, or associated with any game publisher**, and it
bundles **no copyrighted game assets** — the tools read files from an
installation you already own; nothing is redistributed. All trademarks are the
property of their respective owners.
