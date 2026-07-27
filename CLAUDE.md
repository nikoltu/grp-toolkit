# CLAUDE.md — StarCraft / SC:R asset toolkit

> Bootstrap for continuing this project. Read §0–§3 before touching anything;
> §4 is the accumulated format knowledge (the reason this project has value) and
> §7 the extended reference. **This file is the single handover doc** — `docs/`
> was consolidated here and deleted (2026-07-27). **Status: the toolkit is DONE**
> — every container/format decodes byte-exact, the full editor suite + browser app
> ship, and the engine oracle-pack (§7.9) is complete on the toolkit side; every
> claim is re-proven by a script in `tests/`. Deferred by choice
> (not blocked): CHK trigger editor / mission-clone, HD DXT encoder (lossy).

---

## 0. Two rules that override everything else

**Respond to the user (V) in Lithuanian.** V is a developer (PHP → C#/Unity,
game-porting background) who also runs an OpenBW Android port in a parallel
Claude Code session. Documents for V are in Lithuanian; code comments and commit
messages in English.

**Measure, never assume.** "Done" means verified against V's real files, with a
number attached. If you have not seen the bytes, say so. A decoder that consumes
a file without erroring is *not* evidence that you understood the format —
see the times that exact mistake was made, §5.

Every such number is re-runnable: **`tests/`** holds one
script per claim. Run them before trusting anything written here; if a script
and a document disagree, the script is right. Start a session by running
`py tests/test_casc_and_shared.py` — it is the fastest way to confirm the
installs are where this file says they are.

---

## 1. Goal

Read, decode and view every StarCraft and StarCraft: Remastered asset container
and media format, with **no third-party libraries** — no StormLib, no CascLib,
no libvpx. Two reasons:

1. **A catalogue/viewer** for V's own files.
2. **A reference oracle** for the OpenBW engine: an independent second
   implementation that its output can be diffed against, so "the engine renders
   this correctly" becomes a byte comparison instead of an opinion.

Reason 2 is why independence matters more than convenience — see §3.

## 2. Environment

- Windows. Python via the Store alias is broken → **use `py`**, not `python3`.
- C++: no system compiler; **MSYS2 g++ is at `C:\msys64\ucrt64\bin\g++.exe`**.
  Build static, otherwise the exe cannot find MSYS2 DLLs:
  `g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude src/grp2png.cpp -o grp2png`
- No `node` on this machine. To test browser JS, load
  `sc-asset-browser.html` in the preview pane and use `javascript_tool`.
  **The preview pane caches aggressively**: if edits do not show up, copy the
  file to a new name, open that, and check `preview_list` for the new `tabId` —
  `javascript_tool` keeps targeting the old tab otherwise.
- **`sc-asset-browser.html` is a BUILT artifact — edit `src/`, not the file.**
  It is assembled from readable pieces by `py tools/build_html.py`:
  `src/app.template.html` (shell) + `src/app.css` + `src/app.js` +
  `src/data/listfile.txt` (the 10 626-name builtin, ~67 % of the old monolith).
  The split is byte-lossless (`--extract` splits, `build` splices;
  `--check`/`tests/test_build_html.py` assert `build == the committed file` to the
  byte). Workflow: edit a `src/` file → `py tools/build_html.py` → the shipped
  single file stays self-contained for `file://`. Never hand-edit the 700 KB
  output; a rebuild would clobber it.
- Sources:
  - Brood War 1.16.1 — `C:\Git\Starcraft BroodWar  v1.1.61` (note: **two spaces**
    before `v`; always quote the path)
  - SC:R — `C:\Git\StarCraft Remastered` (CASC under `data\data`)
- **Spec text for the codec table generators** (not committed; the scratchpad
  copies vanish between sessions, so re-fetch when regenerating tables or when
  writing a new VP9 stage). `curl.exe` needs `--ssl-no-revoke` here; extract
  with the MSYS2 poppler at `/mingw64/bin/pdftotext`:
  - **VP8 / RFC 6386** → `tools/gen_vp8_tables.py`. Fetch:
    `curl.exe -sSL --ssl-no-revoke -o rfc6386.txt https://www.rfc-editor.org/rfc/rfc6386.txt`
  - **VP9 spec v0.6** (PDF) → `tools/gen_vp9_tables.py`, and the source for the
    VP9 decode process (partition/mode/token/intra/transform syntax). Fetch +
    extract with `-raw` (keeps the `f(n)` descriptor column inline, which
    `-layout` scrambles):
    `curl.exe -sSL --ssl-no-revoke -o vp9.pdf https://storage.googleapis.com/downloads.webmproject.org/docs/vp9/vp9-bitstream-specification-v0.6-20160331-draft.pdf`
    then `/mingw64/bin/pdftotext -raw vp9.pdf vp9raw.txt`
  - **Do not read another decoder's source** (libvpx, OxideAV, dav1d, …) — the
    whole value is independence (§6). The published spec/RFC is the only source.

## 3. What exists

### Python tools (stdlib only)

| Tool | Does |
|---|---|
| `tools/mpq.py` | MPQ reader: crypt tables, hash/block tables, per-file keys, zlib, PKWARE explode, uncompressed, **and WAVE audio** (Huffman+ADPCM). `MpqChain` applies `patch_rt > BrooDat > StarDat` precedence. `--palettes` pulls the real palettes. |
| `tools/mpq_wave.py` | StormLib Huffman + IMA ADPCM. **The one place with borrowed data** — see §6. |
| `tools/mpq_writer.py` | MPQ **writer** (the mod-packaging export side): builds a BW-compatible archive from `{name: bytes}` → a `patch_rt.mpq` the engine applies over StarDat/BrooDat. Uncompressed single-block storage (flags = EXISTS, no sector table) — the same format BW's own portraits use, so retail Storm.dll reads it. Oracle: write → read-back with `mpq.py` byte-identical (`tests/test_mpq_writer.py`, 7/7). |
| `tools/mod_pack.py` | **Mod packager** for the OpenBW-Android launcher's overlay system (its `docs/MOD-ARCHITECTURE.md`): builds a `.zip` → `files/mods/<id>/` with `mod.json` (exact launcher schema) + loose `data/<path>` overrides (default) or `data.mpq` (via mpq_writer). Overlay, NOT injection — the engine's loose loader checks `files/mods/<id>/data/<path>` before the MPQ chain. Deterministic zip; optional pre-flight validation with our readers. Oracle: pack → read-back byte-identical, 6/6 (`tests/test_mod_pack.py`). |
| `tools/casc.py` | CASC: `name → root → CKey → encoding → EKey → .idx → data.### → BLTE`. |
| `tools/anim.py` | **SC:R `.anim` reader** (HD asset side): header (scale→SD/HD2/HD, type), 10-slot layer-name table, entry table (frameCount/refId/w/h/frameTableOffset), TexRef table (ddsOffset/size + DXT FourCC sniff), frame records. Structure only, no DXT pixel decode (that's C++ `dxt.hpp` / the browser). Independent of the C++/JS readers. |
| `tools/anim_inventory.py` | **HD asset inventory + validator** for the OpenBW HD engine: scans every `.anim` in a CASC install, maps tier/type/layers/DXT/refId-sharing/resolution and FLAGS anomalies. Measured: **3510 anims, all parse, 0 anomalies** — HD 1754 / HD2 1754 / SD 2; the standard 7-layer set dominates (3504) but the tool surfaces the edge cases (1- and 2-layer files, 999-entry outliers, 6 refId-shared, mixed DXT1/DXT5) so the engine handles every variant. `--json` for a CI diff. Oracle `tests/test_anim_inventory.py` (4/4). |
| `tools/dxt.py` | **DXT1/DXT3/DXT5 decoder + DDS reader** — the HD texture pixel oracle. Decode is deterministic (565→888 bit-replication, 1/3 & 2/3 interpolation, DXT5 alpha ramp), rounding matches JS `Math.round`, so **byte-identical to the browser's `ddsToImageData`** (confirmed on a real `.anim` layer, sha-equal). Verified by synthetic hand-computed blocks (`tests/test_dxt.py`, 5/5). |
| `tools/anim_render.py` | Decode a `.anim` layer's DDS atlas → golden RGBA PNG (`tools/png.py` writer), or crop one frame via the frame records. Per-LAYER so the DXT decode is isolated from the engine's compositing shader. The reference image the HD engine diffs its texture pipeline against. |
| `tools/anim_composite.py` | **HD layer composite** (one step past `anim_render`): combines the 7 `.anim` layers into a FINAL RGBA frame like the sprite shader — `diffuse → teamcolor src-over (player tint) → additive emissive`. Every OPERATION is byte-exact (src_over/add on hand-computed pixels; `diffuse`-only == `anim_render` diffuse crop; teamcolor tint == `player_colors`; determinism) — see oracle `tests/test_anim_composite.py` (5/5). The layer RECIPE (which layers/order) is the documented reference until V supplies the engine's exact blend; `bright/normal/specular/ao_depth` are lighting inputs, decoded but not baked into the flat reference. Browser twin = the anim viewer's **★ Kompozitas** layer option, sha-verified byte-identical to this. |
| `tools/sd_hd_bridge.py` | **SD↔HD asset bridge**: pairs a unit's classic SD GRP (via the DAT graphics chain) with its SC:R HD `.anim` (`anim/main_%03d.anim`, index = images.dat image id). MEASURED: over every unit resolving both, **SD and HD frame counts are EQUAL — 214/214, 0 mismatches** → frame i is the same logical frame in both tiers (the engine pairs art without remapping `playfram`). Scale is the tier (HD=×4 nominal; per-frame w-ratio varies because SD/HD trim transparency independently, so NO clean placement multiplier is claimed). 14 units have no `main_` HD anim (hero/alt image ids, tileset doodads, resource chunks) — reported, never silently matched. Oracle `tests/test_sd_hd_bridge.py` (4/4). Browser: HD-anim line in the DAT editor's graphics chain. |
| `tools/golden.py` | **Golden-frame regression harness + determinism checker** (engine oracle). GOLDEN: decode a declared asset list to final bytes → `{label: sha256}` manifest; re-run and diff (`changed`/`new`/`gone`) — a decoder change that alters one pixel shows up. DETERMINISM: decode each target N× and assert byte-identical (catches ordering/uninit/random leaks — a desync is a decoder that is not a pure function of its input). Shared DECODERS registry (grp/anim_layer/composite/tbl). Oracle `tests/test_oracle_harness.py` (with asset_diff, 3/3; 7 targets deterministic). |
| `tools/asset_diff.py` | **Patch asset-diff**: what changed between two installs. CASC is exact + cheap — the root maps each name to its CKey and a CKey IS the content hash, so two installs agree on a file iff they list the same CKey (no decode); name-set diff gives added/removed. MPQ mode sha-256s each read file. Turns a patch review into a list (changed/added/removed), so the engine knows which assets to re-check. Oracle `tests/test_oracle_harness.py` (identity + one-CKey-edit sensitivity over 52 498 CASC names). |
| `tools/player_colors.py` | **Player-colour reference.** Measured: the `.anim` `teamcolor` layer is a **grayscale MASK** (r==g==b; white = full player colour). `apply_team_color(mask, rgb)` = `playerColour × mask/255`, mask as alpha (byte-exact tint); dumps P1–P8 reference PNGs. The mask decode + formula are byte-exact; the 8 player-colour RGBs are the standard BW set (overridable). Oracle `tests/test_player_colors.py` (4/4). |
| `tools/grp.py` | **Classic GRP reader + writer** (the graphics-mod export side). RLE skip/run/literal + frame dedup. Inverses in PIXELS: `decode(encode(frames))` reproduces the index grids exactly (`tests/test_grp_writer.py`, 8/8 incl. real wirefram/cmdicons + synthetic edge cases). Byte-identity vs Blizzard NOT claimed (RLE split is a compression choice); size measured (wirefram 95% of orig). Browser twin = **Sprite importeris**, byte-identical to this. |
| `tools/extract.py` | **Extract-to-disk CLI**: pull raw asset bytes out of a BW install (`--bw`, MPQ chain) or SC:R (`--scr`, CASC) — `py extract.py --bw <dir> scripts\aiscript.bin -o out.bin`. Built for the OpenBW session, whose need was "get the exact bytes the engine loaded onto disk, then point a disassembler at a pc". |
| `tools/tbl.py` | **`.tbl` string-table reader + writer** (the string-mod side; used everywhere for names — stat_txt, images.tbl, sfxdata). READ API unchanged (`text(i)` = display name up to first NUL, 0-based). WRITE: unedited → `to_bytes()` re-serialises in **offset order, byte-identical** (stat_txt/sfxdata/images, verified — a real writer round-trip); edited → index-order content-deduped (valid `.tbl`, semantic round-trip, byte-identity vs Blizzard not claimed — the GRP-writer honesty). **MEASURED trap:** a stat_txt entry is NOT just text-to-first-NUL — 274/1547 carry extra NUL-separated parts (tooltip/hotkey) up to the next offset; `raw[i]` keeps the full slice, `set_text()` edits only the name and preserves the tail (read-to-first-NUL would drop 3801 bytes on rewrite). Oracle `tests/test_tbl.py` (4/4). Browser twin = **TBL editorius**, byte-identical to this. |
| `tools/combat.py` | **Combat (damage) reference oracle** — the independent second implementation of BW damage for the engine to diff against. `CombatModel` resolves a unit's real weapon(s) from `units.dat`/`weapons.dat` (**following the `subunit1` turret** for Siege Tank/Goliath — measured Siege→Arclite 30 Explosive, Goliath→Twin Autocannons 12 + Hellfire 10) and computes `effective = (damage+bonus·upg − armor, clamp≥0) × sizefactor% × hits`. **Two provenance tiers, kept apart:** every numeric INPUT is byte-read from the .dat (Marine 6, Zealot 8×2, Firebat 8×3 — pinned by the oracle); the damage-type×size FACTOR table (Normal 100/100/100, Concussive 100/50/25, Explosive 50/75/100 S/M/L; shields 100% + ignore armor; buildings=Large) is the documented Compendium mechanic, checked by reproducing its worked examples. `breakdown()` exposes every intermediate so an engine mismatch localises to one step; the armor→factor ORDER + BW fixed-point rounding/min-damage floor are flagged as the one thing the diff still confirms. Emits `assets/combat_reference.json` (factor table + ability energy costs) and, via `--fixture`, `assets/combat_fixture.json` — the **concrete per-unit effective-damage matrix** (size S/M/L/Shields × armor 0–3 × upgrade 0–3) that the engine's `combatcheck` diffs against (the engine-oracle deliverable; see §7.9). Oracle `tests/test_combat.py` (5/5): inputs byte-exact, factor table reproduces the mechanic, multi-hit armor per-hit (Firebat vs 1-armor = (8−1)×3=21, not 23), determinism + committed-JSON match, **fixture deterministic + spot values + committed match**. |
| `tools/rep/` | **Replay (`.rep`) toolkit** — decode a game's whole player-input stream (what the OpenBW session replays through the engine; this is the independent interpretation it diffs against). `rep_read` cracks the container (sections of PKWARE-imploded [classic `reRS`] or zlib [SC:R `seRS`] chunks) + the 633-B header (frames/players/races/map). `rep_commands` disassembles the frame-block command stream (`u32 frame, u8 len, [player,cmd,args]`) — **argument sizes MEASURED by a tiling solve over ~107 k blocks, then matched the community table byte-for-byte**; the solve caught two memory traps (0x2f is Lift-Off not Tech, 0x35 Building-Morph not Stim). `rep_actions` → per-player build order / units / tech / upgrades / APM+EAPM / who-left, plus the full text command log. Commands attribute by **storm id** (header struct +4), NOT the display pid. Oracle `tests/rep/test_rep.py` (4/4): 9 real replays, **136 313 commands, every block consumed exactly, 0 unknown ids**; every producing player opens on their race's worker (Drone/SCV/Probe). Names borrowed from screp (attributed); sizes independently measured. `rep_transcode` **down-converts a SC:R (`seRS`) replay to a classic 1.16.1 (`reRS`) one** — re-containers with uncompressed chunks (no PKWARE compressor needed) + remaps the `_121` commands to classic with 4-byte→2-byte unit-tag truncation (measured: tag high-16 ~always 0). Self-oracle: transcode → re-read with the classic reader → **logical commands identical** (build orders/units/tech preserved, 4/4 SC:R replays). Real BW playback is V's to test (no BW runtime here). `rep_canonical` emits a **stable, byte-diffable command dump** (`f<frame> p<storm_id> <cmd_id> <name> <args-hex>`, reRS + seRS) — the reference the engine's replay parser diffs against, attacking the engine's open SC:R-seRS-loader + multi-slot-desync items (see §7.9; oracle `tests/rep/test_rep_canonical.py` 3/3, 9 replays / 136 313 lines). |
| `tools/smk.py` | Full Smacker SMK2/SMK4 decoder → PNG frames or sheet. |
| `tools/webm.py` | WebM/Matroska container + VP9 uncompressed header & superframe split. **No pixel decoding.** |
| `tools/vp9.py` | VP9 **headers** (stages 1+2): superframe, uncompressed header (both profiles, stateful), and the compressed header — bool decoder (§9.2) + the full probability-update model. From VP9 spec v0.6. Portraits: 1073 files / 12 210 frames, 0 errors; compressed-header padding oracle exact. No pixels yet. |
| `tools/vp9_tables.py` | VP9 constants — **generated**, never hand-edited. `tools/gen_vp9_tables.py` cuts 46 tables (scans, quant lookups, coef/mode probs, pareto, token trees) out of the spec text and asserts each one's shape. |
| `tools/vp9_decode.py` | VP9 **key-frame entropy decode** (stage 3a): partition tree + intra modes + coefficient tokens, all the entropy contexts. Verified by the tile padding oracle — 1073/1073 portrait key frames, both profiles. No pixels yet (intra prediction + inverse transforms are 3b). |
| `tools/vp9_inter.py` | VP9 **stage 5 Phase A — inter-frame entropy**: inter mode-info, `find_mv_refs`, MV decode, non-kf contexts, compound, 4 frame-context tracking (no §9.4 adaptation — `frame_parallel=1`). `decode_clip_padding()` runs the tile padding oracle over a whole clip. |
| `tools/vp9_inter_pixels.py` | VP9 **stage 5 Phase B — inter pixels**: 8-tap sub-pixel motion compensation (§8.5.2.4), MV clamp/scale, compound averaging, reconstruction (reuses `vp9_pixels`), reference-frame store, general loop filter with ref/mode deltas. **Byte-exact vs ffmpeg libvpx (PyAV), both profiles: 4:2:0 (profile-0) and 4:4:4 (profile-1 sRGB) — the whole portrait inter corpus, 1073/1073 clips, 0 diffs.** Oracle: `pip install av`; test `tests/test_vp9_seq.py --all`. |
| `tools/vp9_pixels.py` | VP9 **key-frame decoder — pixels + loop filter** (stages 3b + 4): intra prediction (10 modes), dequant, inverse DCT/ADST/WHT (4×4–32×32) + 2D transform, reconstruction (§8.5.1/8.6/8.7), then the loop filter (§8.8: filter mask, narrow/wide filters, per-edge strength). `decode_keyframe()` → reconstructed, deblocked planes. **Byte-exact vs the browser's libvpx: the whole portrait key-frame corpus, 1073/1073** (1045 profile-1 4:4:4 sRGB via I444, 28 profile-0 4:2:0 via NV12; 514 loop-filtered). Also reused by the inter decoder (stage 5) for intra prediction + reconstruction. |
| `tools/vp8.py` | VP8 boolean entropy decoder + keyframe header (RFC 6386). Stages (a)+(b). |
| `tools/vp8_decode.py` | VP8 **full decoder** — stages (c)+(d)+(e). Intra + inter: modes, coefficients, dequant, inverse WHT/DCT, 14 intra modes, motion vectors, 6-tap sub-pixel prediction, reference frames, and the normal loop filter. `VP8Decoder` decodes a sequence; `decode_video()` yields every frame. |
| `tools/vp8_tables.py` | The VP8 constants — **generated**, never hand-edited. `tools/gen_vp8_tables.py` cuts 19 tables out of the RFC text and asserts each one's length against the shape the spec declares. |

### C++ (header-only decoders, no deps)

`include/scgrp/{dxt,image,grp,anim,dump}.hpp`, `src/grp2png.cpp` (CLI),
`src/viewer.cpp` (SDL2). `grp2png --dump-idx` / `--dump-argb` emit the
comparison artefacts described in §7.5.

### Browser app

`sc-asset-browser.html` — single self-contained file, works from `file://`.
Folder / MPQ / CASC browsing, all decoders, an embedded StarCraft listfile
(10 626 names — the union of the toolkit's original list and the community
`Starcraft BW.txt`; measured to name 5665 files in V's 1.16.1 install, +253
over the original), authentic palettes pulled straight from an open archive, a
**wireframe colour tester** (now per-part damage, see §4), `.grpi` export,
Smacker playback, WebM playback (the browser's native VP8/VP9 — SC:R has 2126
portrait `.webm` "talking heads" that play here) + frame export, and audio with
a waveform.

The header carries a **light/dark theme toggle** (🌙/☀; CSS-variable driven —
`:root` dark + `:root[data-theme=light]` + a `prefers-color-scheme` first-paint
fallback; persists to `localStorage`, else follows the OS) and a **command
palette** (⌘K button / Ctrl+⌘+K) that fuzzy-searches every tool and opens it from
any view — the palette reads the same `#toolsDD .ti[data-open]` list the dropdown
uses, so a new tool appears in both automatically. The layout is responsive
(`@media` 900/640 px: columns stack, the file tree hides on the narrowest).
A single header **🛠 Įrankiai** dropdown opens eight full-screen tools (the old
per-tool button row was consolidated into this menu so tools stay reachable from
any view, not just the welcome dashboard; the welcome cards trigger the same
hidden buttons). Each tool mirrors a Python module, no server: **Wireframe
testeris**, **Campaign analizatorius** (AI-script disasm + semantic
fingerprint + interactive difficulty scaler + a mission analyzer that
AUTO-LISTS every campaign mission in the open MPQ — no manual tree navigation —
and for each shows the 🎙 briefing dialogue timeline (speaker/portrait/text/wav/
duration, JS twin of `briefing.py`) + 🎯 unit commands from triggers
(Move/Patrol/Attack/Create/Give, JS twin of `mission_actions.py`) + player→script→
location AI linkage; JS mirrors `chk.py`/`ai_scaler.py`, verified byte-identical
to Python (zerg01 briefing + terran02 commands). Also **🤖 bot behaviour +
📖 walkthrough cross-reference** per mission: the linked AI scripts' bytecode is
aggregated into what the enemy builds/trains/attacks with (JS twin of
`mission_bot.py`, sha-verified), then cross-referenced against curated community
walkthrough FACTS (`assets/campaign_walkthroughs.json`, enemy faction/units/attack
pattern/objective + source URLs — facts only, attributed) — two INDEPENDENT
sources of "what does the enemy do": bytecode + human guide. Agreement confirms
the analysis (Desperate Alliance / Revolution / Egression / First Strike: every
walkthrough unit confirmed by the script), and discrepancies are informative
(Trump Card: script fields Guardians the guide glossed, the guide's Delta-Squadron
Wraiths have no AI attack wave = trigger/defensive). Python twins `mission_bot.py`
+ `walkthrough.py`, oracles `tests/ai/test_mission_bot.py` (3/3, 64 missions) +
`tests/ai/test_walkthrough.py` (4/4, 18/19 units corroborated)), a dedicated
**🗺️ Kampanijų misijos** menu/card (opens the analyzer filtered to the mission
list only — V's "find missions without walking the tree"), and **HUD
editorius** (drag + resize all 17 HUD v2 elements from the HUD-v2 layout spec (§7.8),
grouped bar/unit-inner/strip/top, each mapped to its `ui.h` function → output is
regenerated `hud2_*` **C++ function bodies** + normalized-rect JSON, export
`hud2-layout.txt`), and **Mod Builder** (packs editor outputs into a launcher
`.zip` — contents at the ROOT: `mod.json` + loose `data/<path>`, extracted to
`files/mods/<zip-filename>/` by the OpenBW-Android launcher, which derives the id
from the ZIP NAME and ignores `mod.json` id/priority; manifest holds only
engine-read fields name/version/type/author/description. In-browser JS AI
assembler emits scaled `aiscript.bin`; also arbitrary file overrides. Pure-JS
STORED zip with CRC32, pre-flight validation with the JS decoders — browser twin
of `tools/mod_pack.py`. **Note:** the engine does NOT yet read
`wireframe-colors.json` — that export has no consumer until an engine reader is
added, so the Mod Builder flags it.), and **Botų kūrėjas** (training-bot
generator, browser twin of `tools/ai/ai_gen.py`: a tactic table — one step per
line, `:label` jump targets, `#` comments — compiles through a symbolic
label-assembler to a **byte-exact, disasm-clean `aiscript.bin`**; live in-browser
oracle re-parses and traces every build. 4 templates (rush/defence/adaptive/
economic) covering the adaptation opcodes `enemyowns_jump`/`enemyresources_jump`/
`resources_jump`/`time_jump`/`random_jump`/`if_dif`. Merge mode keeps all 293
stock scripts byte-identical; feeds the compiled `.bin` straight into the Mod
Builder as a `type:bot` mod (`data/scripts/aiscript.bin` + a manifest whose
name/description come from the loaded build order). Unit/building IDs are NUMERIC
— a name→id map depends on the install's `stat_txt.tbl`/`units.dat`, so it stays
a UI-layer concern, not baked into the generator; the JS emits the exact same
bytes as Python, sha-verified. Also a **build-order library**: 22 pro build
orders transcribed from V's Miro cards (`assets/build_orders.json`) selectable
from a dropdown — each shows a spec panel (aggression/economy, description, build
steps, counters, notable maps) and compiles to a disasm-clean bot via the
MEASURED name→id map (`assets/unit_ids.json`, cut from stat_txt by
`tools/gen_unit_ids.py`; `tools/ai/build_orders.py` is the Python twin, oracle
`tests/ai/test_build_orders.py` = 22 cards / 222 rows resolved, all compile)), and **DAT editorius** (browser twin of
`tools/dat.py`: edits `units.dat`/`weapons.dat` as struct-of-arrays — HP/shield
shown as real values, 1/256 fixed-point stored ×256; a searchable entity list
named via `stat_txt.tbl`; per-field grid with changed-marks + stock column, a
"visi laukai" toggle; feeds the edited `.dat` into the Mod Builder as
`data/arr/<name>`. Field table generated from the Python spec so the SoA layout
is identical, round-trip byte-exact; the four measured anchors and subset
addressing are verified in-browser), and **TBL editorius** (browser twin of
`tools/tbl.py`: edits string tables — stat_txt/images/sfxdata/gluall — as a
searchable entry list; `set_text` changes only a display name and **preserves the
extended NUL-separated tooltip/hotkey bytes** (flagged per entry), unedited files
re-serialise byte-identically, edited feed into the Mod Builder as `data/<path>`.
Byte-identical to `tbl.py`, sha-verified in-browser [synthetic incl. extended
parts → same INPUT round-trip + same edited bytes as Python]), and **Sprite importeris** (SD graphics-mod
front end, browser twin of `tools/grp.py`: import PNG frames → quantize each
pixel to the nearest palette index (alpha 0 → transparent index 0; unit palette
from `tunit.pcx` or any loaded `.pal/.wpe/.pcx`) → encode a classic RLE GRP with
frame dedup → preview by decoding it back (the pixel round-trip) → download or
push into the Mod Builder as a `data/unit/…` override. The JS GRP writer is
byte-identical to `grp.py`, sha-verified), and **iscript peržiūra** (browser twin
of `tools/iscript/`: loads `scripts\iscript.bin`, lists all 398 animation scripts,
disassembles each header's animations — playfram/wait/goto/imgol/playsnd — and
runs the coverage oracle in-browser (398 scripts / 1833 anims / 9763 opcodes / 0
desync, verified identical to Python). A viewer, not yet an editor).
`.scm/.scx` and `scenario.chk` open directly (map = MPQ; CHK → Campaign
Analyzer). Two reference views: **📖 Kampanijų walkthrough** (a spreadsheet — one
row per campaign mission, columns objectives/WIN/LOSE/transfer/heroes/enemy-attack/
AI/cmd/briefing from the oracle spec+briefing+bot; click a row → full mission in
the analyzer; **⬇ CSV export**) and **🧾 Žinynas: cheatai** (wiki-style table of the
public SC/BW single-player cheat codes, twin of `assets/cheats.json`).

`assets/listfiles/` holds the source lists: `Starcraft_BW.txt`,
`Starcraft_II.txt`, and `blizzard-listfiles.zip` (many other Blizzard games,
kept for future tooling — this app decodes only StarCraft, so they are just raw
name lists to it). The app's "Atverti failus" button loads any `.txt` listfile
at runtime. **Note:** the app's WebM playback uses the browser's own codec, not
`tools/vp8_decode.py` — that decoder is the independent oracle for the OpenBW
session, not a playback path.

### Handover (for the OpenBW session)

`docs/` was consolidated into this file (2026-07-27) and deleted — this CLAUDE.md
is the single handover doc. What used to be separate now lives here:
- **Status / what's done** → §0 header + the tool table (§3). The toolkit is DONE.
- **Everything measured about the assets** → §4 + §7.1–7.4, 7.10.
- **GRPI/ARGB dump spec + why we do not share code** → §7.5 (+ §1 reason 2, §6).
- **`wireframe-colors.json` schema + engine-reader spec** → §7.6–7.7.
- **HUD v2 layout** → §7.8. **Engine oracle-pack (the byte-exact diff surface)** → §7.9.
- The engine's own audit + SC2-suitability autopsy live in the engine repo
  (`openbw-android/docs/TOOLKIT-INTEGRATION-MODERNIZATION.md`, `openbw-android/sc2/`).

---

## 4. Format reference — all measured, do not re-derive

### Classic GRP
```
u16 frameCount, u16 canvasW, u16 canvasH
frameCount × { u8 x, u8 y, u8 w, u8 h, u32 dataOffset }
per frame: u16 line offset per row (relative to dataOffset), then RLE:
  b >= 0x80 → skip (b-0x80) transparent px
  b >= 0x40 → run  (b-0x40) copies of the next byte
  else      → copy b literal bytes
```
Pixels are palette indices; index 0 is transparent.

**Not every `.grp` is RLE.** `game\icons.grp` holds flat uncompressed bitmaps,
one byte per pixel, no row table. Discriminator: frame 1's `dataOffset` equals
`frame0.dataOffset + w0*h0`. Measured: 12 frames, 0–10 are 14×14, 11 is 53×14,
and **frames 7, 8, 9 are byte-identical**.

Silent row clamping (runs longer than the frame width) is correct for a game but
wrong for an oracle — `IndexFrame.flags` reports it instead.

### DDS GRP (`_dds.grp`, SC:R)
```
12-byte header: u32 fileSize (self-referential — the format sniff),
                u16 frameCount, u16 flags (0x1002), u32 unused
frameCount × { u16 w, u16 h, u32 ddsSize } + ddsSize bytes of DXT1/DXT5 DDS
              + u32 trailer (observed 0; absent at EOF is normal)
```
**There are no per-frame x/y offsets** — measured zero across 627 frames.
Placement comes from the caller (icon box, wireframe cell).

### ANIM (`.anim`, SC:R)
```
"ANIM", u8 scale (1=SD 2=HD2 4=full HD), u8 type, u16, u16 layerCount, u16 entryCount
0x0C  layer name table, 10 slots × 32 B
0x14C entry table × 12: u16 frameCount, u16 refId, u16 w, u16 h, u32 frameTableOffset
then TexRef × 12: u32 ddsOffset, u32 ddsSize, u16 w, u16 h
frame record × 16: u16 atlasX, atlasY, i16 xoff, yoff, u16 w, h, u32 flags
```
Byte 4 is **scale, not a version**. `refId != 0xffff` means the sprite borrows
another file's texture. The standard sprite is `scale=2` (HD2) or `4` (HD),
`entryCount=1`, 7 layers (`diffuse, bright, teamcolor, emissive, normal,
specular, ao_depth`). **Whole-corpus inventory** (`tools/anim_inventory.py` over
SC:R CASC): **3510 `.anim`, all parse, 0 anomalies** — HD 1754 / HD2 1754 / SD 2;
3504 use the 7-layer set, but the tail matters for a robust engine: a few 1- and
2-layer files, 6 refId-shared textures, 2 files with `entryCount=999`, type 1 vs
2, and layers mixing DXT1 (opaque) + DXT5 (alpha). 2221 distinct atlas
resolutions (8×8 … 432×440+). Two more measured facts for an HD renderer:
`ddsOffset == 0` on a layer means the texture is **refId-shared** (lives in
another `.anim`, follow the entry's refId) — not that the layer is absent; many
HD files carry only diffuse in-file. And the **`teamcolor` layer is a grayscale
mask** (r==g==b; white = full player colour) the shader tints with the owner's
colour — `tools/player_colors.py` decodes it byte-exact and applies the 8 player
colours as a reference. DXT decode itself is `tools/dxt.py`, byte-identical to
the browser's `ddsToImageData`.

### HD naming + SD↔HD bridge
A unit's HD anim is **`anim/main_%03d.anim`** where the index is the unit's
`images.dat` image id — the SAME id the SD graphics chain resolves
(`units.flingy → flingy.sprite → sprites.image`). HD2 tier lives at
`HD2/anim/main_%03d.anim`. So ONE image id names both the SD GRP and the HD anim;
no separate HD lookup table. **Frame correspondence is 1:1**: over every unit
resolving both, the SD GRP frame count equals the HD anim frame count — measured
**214/214, 0 mismatches** — so `playfram N` addresses frame N in either tier and
the engine swaps art without remapping. Scale is the tier (SD 1 / HD2 2 / HD 4);
the per-frame width ratio is only ~4× on average (measured mean ~4.2, spread
3.1–8.4) because the SD RLE and the HD atlas trim transparent margins
independently — so **no clean per-pixel placement multiplier**, the 1:1 frame
index is the reliable bridge. 14 units resolve an SD GRP but no `main_` HD anim
(hero/alt image ids like img246 marine, `thingy\` tileset doodads, neutral
resource chunks) — SC:R renders those through a different anim. `tools/sd_hd_bridge.py`,
oracle `tests/test_sd_hd_bridge.py` (4/4).

### HD layer composite
The 7 layers composite to the final sprite as `diffuse → teamcolor src-over
(player tint, `player_colors`) → additive emissive`, integer math, deterministic.
Each OP is byte-exact (`tools/anim_composite.py`, oracle 5/5); the browser twin
(anim viewer ★ Kompozitas) is sha-identical. The layer RECIPE is the documented
reference until V's engine blend lands — `bright/normal/specular/ao_depth` are
lighting inputs, decoded but not baked into the flat 2D reference.

### Wireframes — the important one
SD `wirefram.grp` has 228 frames = 228 unit types, so **frame index = unit id**.
Only these indices appear: `192/193` (structure), `208–211` (Terran/Protoss
bands), `216–219` (Zerg) — plus exactly **one stray 215 pixel** (frame 107,
x=9, y=24).

The four indices are **four separate regions** whose spatial character differs
per race (measured via 4-neighbour mixing and radius from the silhouette centre):

| | Mixing | Shape |
|---|---|---|
| Terran/Protoss `208–211` | 1.5–18 %, radii non-monotonic | **body parts** (scattered regions) |
| Zerg `216–219` | 24–59 %, radius grows monotonically | **nested shells** (concentric) |

**They recolour PER PART, and the LOOK differs by shape** (V confirmed against a
retail Drone wireframe; earlier tries were wrong — one flat colour, a quartile
drain, a 3-stage that dropped the orange tones):

- **Zerg** nested shells recolour as a **smooth gradient down the full 9-entry
  ramp** — green core → yellow → **orange/amber** → red outer, the organic
  layered look. Model per shell (`depth` 0 = inner … 1 = outer):
  `k = round(8 − depth·5 − (1−hp/100)·6)`, clamped 0–8. Even at full HP it is a
  gradient (green core, warm outer edge — and the outer shells have the largest
  pixel area, so a healthy Drone still reads mostly warm with a green core). As
  HP drops the whole gradient slides toward red.
- **Terran / Protoss** scattered body parts use **three crisp stages**
  green(8)/yellow(7)/red(2): `t = hpf − depth(1−hpf)`; `t>0.66→green,
  t>0.33→yellow, else red`. A gradient on scattered parts looks random, so
  stages are right here; V confirmed Terran/Protoss look correct.

`twire.pcx` measured: 24-entry strip = HP {green, yellow, orange×3, red×4,
black} + a 7-entry blue shield ramp + a 4-entry purple energy ramp — so the
9-shade HP ramp the gradient walks is authentic. Both models live behind the
tester's mode toggle (`solid`/`window` kept for comparison).

HD `wirefram.dds.grp`: 228 frames, all 1024×128 DXT5 = 8 cells of 128×128.
**Cell roles are not positional** — classify by saturation (mask = low sat).
Terran: 4 masks then coloured cells; Zerg/Protoss: 6 masks; Probe: 7 masks, no
coloured cell. The masks are **nested shells**, and their *role* is by radius,
measured on the real atlas (`_audit_hd.py` style):
- **Terran** 4 masks = 4 HP shells.
- **Zerg** 6 masks = **all 6 HP shells** (radii 12→43 px, monotonic inner→outer)
  — NOT 4 HP + 2 structure. Colouring only 4 (the earlier bug) left the two
  outer shells dark.
- **Protoss** 6 masks = **4 inner HP shells + the 2 OUTERMOST = the shield**
  (radii ~40 px, the outer shell; SD equivalent is 192/193). The shield masks
  take the blue shield ramp, not a dark "structure" colour — mapping them to
  structure is what hid the Protoss shield entirely.
Model: sort masks by radius, colour HP shell *i* of *N* by the 3-stage HP model
at depth `i/(N-1)` (outer first), and the shield shell by `shield_ramp`. So the
per-race mask count is handled without a fixed 4-band assumption.

### PCX
Standard. 8-bit with a VGA palette in the trailer (last 769 bytes, marker
`0x0C`); RLE `(b&0xC0)==0xC0` → run of `b&0x3F`. 24-bit (3-plane) handled.

### MPQ
- `"MPQ\x1A"` header, possibly at a 512-aligned offset. StormLib crypt table
  (seed `0x00100001`), `(hash table)` / `(block table)` decryption.
- Keys: `ENCRYPTED (0x10000)` → `HashString(baseName, FILE_KEY 0x300)`;
  `FIX_KEY (0x20000)` → `key = (key + blockOffset) ^ fileSize`. Sector offset
  table uses `key-1`, sector *i* uses `key+i`.
- Compression byte: `0x02` zlib, `0x08` PKWARE, `0x41`/`0x81` WAVE.
  `IMPLODE (0x100)` = whole file PKWARE.
- **PKWARE explode:** the canonical-Huffman decode **inverts each bit**
  (`code |= bits(1) ^ 1`). That was the bug that broke the first attempt.
- **Uncompressed files (flags `0x80000000`) have NO sector offset table** — the
  payload is raw at the block offset. This hid all 519 portraits, in *both* the
  Python and JS readers, because the same author wrote both.
- Audio: sector 0 is PKWARE, the rest `0x41` (mono) / `0x81` (stereo).

### CASC
`name → root → CKey → encoding → EKey → .idx → data.### → BLTE`.
- `.idx` v7: entries at `0x28`, each `EKey[9] + offset[5 BE] + size[4 LE]`;
  `fileIdx = packed >> 30`, `offset = packed & (2^30-1)`.
- `data.###` blob: 30-byte header (EKey stored **reversed**), then BLTE.
- BLTE: `"BLTE"`, u32 **big-endian** headerSize, chunks `'N'` raw, `'Z'` zlib,
  `'F'` recursive, `'E'` encrypted (needs a TACT key — unhandled).
- root (SC:R) is **plain text**, `path|CKey` lines. It *is* the listfile.

### Smacker
```
"SMK2"|"SMK4", u32 w, h, frames, i32 rate, u32 flags, u32 audioSize[7] @24,
u32 treesSize @52, u32 {mmap,mclr,full,type}Size @56, u32 audioRate[7] @72,
u32 @100, u32 frameSize[frames] @104, u8 frameType[frames], trees
```
Four Huffman books, 4×4 block modes MONO/FULL/SKIP/FILL. Two rules that cost
the most to find:
1. a 16-bit book has its **own leading present-bit** before the two 8-bit
   sub-books;
2. the **3-slot MRU cache resets every frame** — carrying it over decodes fine
   for a while and then silently diverges.

The tree section is padded to a 512-byte boundary, so `treesSize` exceeds what
the books consume. Useful check: a frame must consume **no more** than its
`frameSize` (0–3 bytes less is padding).

### WebM
EBML/Matroska. Full corpus: 2578 names, 2483 present (the 95 missing are
`locales/` for non-English) → **1850 VP9 + 633 VP8**. Resolutions run from
60×56 portraits to 1920×1080 cinematics. `sd/portrait/` is the original SMK
re-encoded — 60×56, 10 blocks, 10 fps, matching the `.smk` exactly.

**`BlockGroup` (0xA0) must be walked as a master element.** Files that wrap
`Block` (0xA1) in a BlockGroup instead of using a bare `SimpleBlock` otherwise
parse to **zero frames** — which looks like a broken file, not a broken parser.
That hid 115 VP8 files, in both the Python and JS readers.

### VP8 (RFC 6386)
Constants live in `tools/vp8_tables.py`, generated — regenerate with
`py tools/gen_vp8_tables.py rfc6386.txt -o tools/vp8_tables.py`. Four things
that cost time:

- **The RFC contradicts itself on block-type numbering.** §13.3's prose says
  `0` = Y-after-Y2, `1` = Y2, `2` = chroma, `3` = Y-without-Y2; the pseudo-code
  a few pages later numbers Y2 as `0`. The reference decoder agrees with the
  prose, so the prose wins.
- **Compare decoders in I420, never RGB.** An RGB comparison also measures
  colour conversion and chroma interpolation. It reported mean error 2.9 on a
  frame that was in fact byte-exact.
- **Container keyframe flags are not usable for VP8 here.** Files wrapping
  `Block` in a `BlockGroup` carry no such flag; read the 3-byte frame tag.
- **Partition slack is a free correctness oracle.** Each residual partition
  must be consumed to exactly its declared length; one mis-read token shifts
  everything after it. Measured: 633/633 files, slack 0.
- **The normal loop filter's integer form is unambiguous; the prose form is
  not.** The RFC gives §15.2–15.3 twice — once as prose with `u2s`/`s2u`
  round-trips, once as the reference decoder's `filter_common`/`filter_mb_edge`
  working directly in unsigned space with two saturations. Port the latter.
  Corpus is all `filter_type == 0` (normal), sharpness 0. Full keyframe
  (intra + filter) is 633/633 byte-exact vs libvpx, 490 of them filtered.
- **The `hev_threshold` is the one place dixie is wrong and the prose is
  right.** dixie collapses it to `(level>=15)+(level>=40)`; RFC §15.4 gives a
  *separate* inter-frame table (`>=15`→1, `>=20`→2, `>=40`→3). They agree for
  key frames — which is why 633/633 keyframes passed with the dixie form — but
  differ for inter frames at level 15..39, and libvpx follows the prose. This
  only surfaced on split-MB edges of an inter frame, as a ±1 on the p1/q1
  pixels the filter touches only when high-edge-variance is *false*.
- **Reference sampling by edge-clamping is exactly the two dixie paths in one.**
  dixie reads references directly when the MV stays inside and calls
  `build_mc_border` (edge replication) when it doesn't. Clamping every
  reference coordinate to the macroblock-padded frame gives the border case,
  and never triggers for the inside case — so one clamped `sample()` matches
  both without the `need_mc_border` bookkeeping.
- **Inter frames carry no dimensions.** Only keyframes have width/height; an
  inter frame inherits them. Reading its "dimensions" gives the padded MB size
  and crops 12 rows of macroblock padding into the comparison.

### VP9 (spec v0.6)
Stage 1 only — `tools/vp9.py` parses the superframe index and the full
uncompressed header (both profiles, key/intra/inter). Things measured/learned:

- **SC:R portrait heads are VP9, not VP8.** `sd/portrait` (60×56) and
  `hd2/portrait` (448×480, 224×240) are all VP9; only `carbot/portrait` is VP8.
  So a native SC:R-heads decoder needs VP9. (The 1998 originals are `.smk`.)
- **Mostly profile 1, sRGB (`color_space=7`), 4:4:4** — RGB, not YUV, and no
  chroma subsampling. Some profile-0 (YUV 4:2:0). Every clip is keyframe +
  inter frames, so pixels will need the inter path too (no keyframe shortcut).
- **The parser must be stateful**: an inter frame's size can come from a
  reference (`frame_size_with_refs`), so ref-frame dimensions carry across
  frames.
- **`smk/` cinematics have a container problem, not a VP9 one.** ~86 files hand
  out block offsets whose bytes aren't VP9 frames (`cn/smk/zerg2.webm` reports
  20 614 "frames"). Not lacing (verified type 0); left as a webm.py follow-up.
  Portraits are unaffected: 12 210/12 210 clean.
- Extract the many probability/scan/quant tables from the spec text
  mechanically (planned `tools/gen_vp9_tables.py`), never by hand — same rule
  as VP8.
- **`init_bool` reads a marker bool (prob 128, must be 0)** before any syntax
  (§9.2.1). Miss it and every later read is one bool off — small inter headers
  survive by luck, keyframe coef updates don't. Resolved by the padding oracle.
- **The compressed-header padding oracle needs no default prob tables:**
  `diff_update_prob`'s bit count is independent of the prob value, so "is
  everything after the syntax zero padding?" verifies the whole structure
  without the tables. Those come in with pixels (stage 3).
- **The tile padding oracle verifies the whole key-frame entropy decode**
  (partition + modes + tokens) without any pixels: each tile is a whole number
  of bytes and must end on zero padding (§9.2.3); intra prediction and inverse
  transforms read no bits. Unlike the header oracle, this one needs the real
  prob *values* (tree renormalisation depends on them). 1073/1073 portrait
  key frames clean.
- **tx_size context uses a neighbour's tx size only if it was NOT skipped**
  (§9.3.2). Using it unconditionally desynced on frames with skipped
  neighbours — surfaced first on the larger 224x240 heads, and looked like two
  bugs (HD profile-1 + all profile-0) but was one.

Stages **3b — pixels** and **4 — loop filter** (`tools/vp9_pixels.py`, spec
§8.5.1/8.6/8.7 then §8.8): intra prediction (10 modes), dequant, inverse
DCT/ADST/WHT + 2D transform, reconstruction, then the deblocking loop filter.
**Byte-exact vs the browser's libvpx: the whole portrait key-frame corpus,
1073/1073** (514 of them loop-filtered). What the verification cost:

- **Verify reconstruction on the `lf==0` subset first, add the filter second.**
  559 of 1073 portrait key frames have `loop_filter_level==0`; for those
  libvpx's filter is a no-op, so reconstruction is directly comparable before
  the filter exists (559/559) — exactly how VP8 intra was validated first. The
  loop filter then closed the other 514 → 1073/1073.
- **The `CurrFrame` buffer must be superblock-aligned, not `MiCols*8`.** VP9
  partitions cover whole 64×64 superblocks, so a 32×32 transform whose top-left
  is on-screen can straddle the frame edge and write into off-screen rows
  (`>= MiRows*8`). Those samples are never read (prediction clamps) nor output
  (cropped), but the buffer must hold them. Sized to `MiCols*8` it crashed only
  on frames with such a straddling block — invisible across all 559 `lf==0`
  frames, hit by exactly two (`statin`) once the whole corpus ran.
- **The key-frame loop filter is much simpler than the general case:** every
  block is intra (`ref=INTRA_FRAME`, `modeType=0`) and segmentation is off, so
  the filter level is a single value for the whole frame, and a tx/block edge
  always applies (no `skip` gate needed). `MiSizes` is the one extra per-cell
  array the filter needs beyond what 3a already stores.

Stage **5 — inter frames** (`vp9_inter.py` entropy + `vp9_inter_pixels.py`
pixels) — **COMPLETE and byte-exact** vs ffmpeg libvpx (PyAV), both profiles:
the whole inter pipeline — entropy, 8-tap motion compensation, compound,
reconstruction, loop filter with ref/mode deltas — matches over full sequences,
4:2:0 (profile-0) *and* 4:4:4 (profile-1 sRGB): **1073/1073 clips, 0 diffs**
(`tests/test_vp9_seq.py --all`). What the build cost:

- **Inter frames inherit the colour config; they never re-signal it.** VP9
  reads `color_config` (bit depth, colour space, chroma subsampling) only on key
  and intra-only frames — an inter frame carries it forward from the sequence
  (spec 7.2 / 6.2). The header parser was leaving `subsampling` unset on inter
  frames, so the decoder defaulted to 4:2:0 and decoded every 4:4:4 inter frame's
  chroma at half resolution → total entropy desync. Invisible on profile-0 (4:2:0
  *is* the default) and on the 60×56 profile-0 heads; it only bit the 224×240
  profile-1 4:4:4 clips. `VP9HeaderParser` now persists bit_depth / color_space /
  subsampling across the sequence and fills them into every inter frame's header.
  This is the same class of trap as mistake #8 below: a "clean" split (all 4:4:4
  fail) that was really about a field only 4:4:4 frames depend on.
- **A stateful parser reused across clips leaks its colour config.** While
  hunting the above, an ad-hoc classification script created *one*
  `VP9HeaderParser` and ran every clip through it; the carried subsampling from
  clip N mislabelled clip N+1's profile, which sent the whole diagnosis down a
  "these are all 4:4:4" false trail (they weren't). The decode paths make a
  fresh parser per clip; debug scripts must too.

- **Backward probability adaptation (§9.4) is not needed here.** All 11137
  portrait inter frames have `frame_parallel_decoding_mode == 1`, which disables
  §9.4. Instead, track the 4 frame contexts: each frame loads
  `frame_context[idx]`, applies the compressed-header forward updates, decodes,
  and (if `refresh_frame_context`) saves back; a key frame resets all four to
  defaults. Measured too: compound *is* used (`reference_mode` SELECT 8466 /
  SINGLE 2665 / COMPOUND 6), `allow_high_precision_mv` is always on, interp is
  SWITCHABLE 8461 / fixed 2676.
- **PyAV (ffmpeg's VP9 decoder, `pip install av`) is the local oracle** — no
  browser needed. It outputs shown frames only (hidden altref frames are
  skipped), each in its native format: `yuv420p` for 4:2:0, `gbrp` (planar RGB,
  G/B/R = the CS_RGB Y/U/V planes) for the sRGB 4:4:4 heads. Compare plane-for-
  plane with NO reformat — reformatting a gbrp frame to yuv420p is lossy and
  invents ±1 diffs everywhere. Test: `tests/test_vp9_seq.py`.
- **Portrait basenames collide across folders — always look them up by full
  path.** `pick(basename)` grabbing the first sorted match derailed the 4:4:4
  debug repeatedly (a "4:2:0 nadfid00" and a "4:4:4 nadfid00" both exist; the
  "size correlation" was really profile, confounded because every 448×480 clip
  is profile-0).
- **Compare in the codec's native buffer, never RGB.** WebCodecs hands profile-1
  4:4:4 back as **I444** and profile-0 4:2:0 as **NV12** (semi-planar — the UV
  plane is interleaved, split it into U/V). Requesting an RGBA `copyTo` would
  add a lossy YUV→RGB step. Plane-for-plane, the RGB-vs-YUV plane semantics of
  `color_space=7` cancel out — the decoder writes the same bytes libvpx does.
- **Chrome's `codedWidth` is a padded alignment surface, not the frame size**
  (a 224-wide frame reports 288; height unchanged). Same trap as VP8's odd-dim
  rounding, just bigger. Crop with `copyTo`'s real per-plane `stride`; gating on
  `codedWidth == width` rejects everything.
- **Portrait basenames collide across folders** — `nadfid00.webm` is a 60×56
  VP9 in `sd/portrait`, a 224×240 VP9 in `hd2/portrait`, and a 448×480 VP8 in
  `carbot/portrait`. A debug lookup by basename grabs the wrong file; the export
  ships the exact bytes it decoded, so the oracle was unaffected.
- The inverse-transform butterfly indices (§8.7.1.3 IDCT, §8.7.1.6–8 ADST) are
  error-prone; a cheap pre-check before the browser is pure maths, no decoder:
  a DC-only input must invert to a **flat block** (holds for DCT, not for the
  shifted lossless WHT), the transform must be **linear** to rounding, and an
  impulse must map to its **cosine** frequency.

### Data tables
`units.dat` = **19 876 B exactly**, struct-of-arrays, 228 units. Key offsets:
`hitpoints` 3156 (u32, **1/256 fixed point** — display value is `hp >> 8`),
`ready_sound` 9312 (u16 ×106), `portrait` 14404, `group_flags` **16684**
(bit 1 Zerg, 2 Terran, 4 Protoss → 66 T / 58 Z / 55 P / 49 neutral).

**Unit names are NOT `unit_map_string_index`** (that field is zero everywhere) —
they are `stat_txt.tbl[unit_id + 1]`.

`tools/dat.py` reads/writes `units.dat` + `weapons.dat` with the full SoA field
table. The **whole units.dat layout is verified**, not just the anchors: the 59
arrays' cumulative offsets hit all four anchors above *and* close at exactly
19 876 B (a wrong width/count anywhere would shift a later anchor or miss the
total). `weapons.dat` = **5 460 B** = 130 weapons × 24 arrays (u16 label, u32
graphics, u16 damage_amount/damage_bonus, u8 damage_factor/weapon_cooldown, u32
min/max_range, …) closing at exactly 42 B/weapon. Reduced-count fields: sound
fields are ×106 (real units 0–105), infestation/addon_h/addon_v are ×96
(buildings 106–201) — addressed with the right base index. Oracle
`tests/test_dat.py` (5/5): layout+anchors, semantics (Marine 40 / SCV 60 HP),
byte-identical round-trip, single-edit isolation, subset addressing.

### Combat / damage (measured inputs + documented factor model)
A unit's attack is its `units.dat.ground_weapon`/`air_weapon` (index into
`weapons.dat`) with `max_ground_hits`/`max_air_hits` shots per attack — **but
turret units carry no weapon on the base id**: Siege Tank (`ground_weapon=130`
= none, `subunit1=6`) and Goliath (`subunit1=4`) hold their weapons on the
subunit, so `combat.py` follows `subunit1` when the base has none (measured:
Siege→Arclite Cannon 30 Explosive, Goliath→Twin Autocannons 12 Normal ground +
Hellfire Missile Pack 10 Explosive air). Sentinels: `ground/air_weapon==130` =
no weapon, `subunit1==228` = no subunit.

Damage per attack = `(damage_amount + damage_bonus·upgrade − effective_armor,
clamp ≥0) × sizefactor% × hits`. **Armor is subtracted PER HIT**, so multi-hit
weapons (Firebat 3, Zealot/Goliath-air 2) lose more to it — Firebat 8×3 vs a
1-armor Small target = `(8−1)×3 = 21`, not `24−1`. The **damage-type × target-
size factor** (documented Compendium mechanic, `assets/combat_reference.json`):

| type \ size | Small | Medium | Large |
|---|---|---|---|
| Normal | 100 | 100 | 100 |
| Concussive | 100 | 50 | 25 |
| Explosive | 50 | 75 | 100 |

Plasma shields take the full (100%) factor and ignore armor; buildings count as
Large (their `unit_size` is already stored Large). `Independent`/`IgnoreArmor`
weapon types deal 100% to every size; `IgnoreArmor` also skips the armor step.
The numeric inputs are byte-facts from the .dat; the factor table + the
armor→factor ORDER and BW's fixed-point rounding / minimum-damage floor are the
documented model, flagged in `combat.py` as the one thing the engine diff still
confirms (a fully-absorbed hit reads 0 here). Oracle `tests/test_combat.py`
(4/4). This is a reference oracle only — no browser UI yet.

**The graphics chain** — what a unit's picture is: `units.dat.flingy →
flingy.dat.sprite → sprites.dat.image → images.dat.grp_file → images.tbl`
(the .grp filename). `dat.py` reads all three (`flingy.dat` 209×15 = 3135;
`sprites.dat` 517 sprites = 3229, with health-bar/selection-circle fields on only
the 387 unit sprites 130–516; `images.dat` 999×38 = 37962) and `graphics_chain()`
walks it. The whole chain is verified END TO END (`tests/test_dat_chain.py`, 4/4):
each layout closes at its exact size AND known units resolve to the real name —
**Marine → `terran\marine.grp`, SCV → `terran\SCV.grp`, Zealot →
`protoss\zealot.grp`, Zergling → `zerg\zergling.grp`** — which also pins the
**1-based** `images.tbl` indexing (grp_file N → `images.tbl[N-1]`; the tbl holds
929 names). This is the reskin path: the browser DAT editor shows a unit's chain +
its GRP path and a 🎨 button that opens the Sprite importer at that path (import
new art → `data/unit/…` override, no DAT edit needed), plus a grp_file retarget
that ships `images.dat`.

**iscript.bin** — the animation-script VM (what `images.dat.iscript_id` points
to). Structure MEASURED: `u16@0` → id table of `{u16 iscriptId, u16 headerOffset}`
terminated by `0xffff` (398 entries; every distinct images.dat.iscript_id
resolves). Each header: `"SCPE"` + `u8 type` + 3 pad + `ENTRY_TYPES[type]` × u16
animation offsets (0 = absent); the 28 animation slots are Init/Death/GndAttkInit/
…/Enable. Bytecode: 69 opcodes (playfram/wait/goto/imgol/imgul/playsnd/…), args
little-endian; the `sounds` arg (playsndrand/attackmelee) is a 1-byte count + that
many u16 soundids; `goto`=jump, `end`/`return`=terminate, `call`/`*condjmp`=
call/cond-jump. `tools/iscript/` (`iscript_bin`, `iscript_opcodes` GENERATED from
PyMS by `gen_iscript_opcodes.py`, `iscript_disasm`, `iscript_asm`). **Coverage
oracle `tests/iscript/test_iscript.py` (3/3): 398 scripts / 1833 anims / 9763
opcodes, 0 desync** — every opcode valid, every jump on a boundary. `iscript_asm`
is the exact inverse + a relocating reassembler: opcode/header/id-table round-trip
**byte-identical** and `reassemble()` relocates all label + animation offsets,
re-parsing clean with every animation's opcode sequence preserved
(`test_iscript_asm.py`, 4/4). Browser twin = **iscript editorius** (in-place,
same-size arg edits — click a value; layout-safe like the AI scaler — then ship
`data/scripts/iscript.bin`), verified identical to Python. `iscript_gen` is the
**text assembler** (the compile side, like ai_gen for aiscript): a small text
format (`.header id=N type=T`, `Anim -> label`, `.code`, labelled opcode blocks)
→ assemble one entry → `merge_text` appends it and repoints that id's id-table
slot, keeping every stock script byte-identical (only the u16@0 pointer changes).
Oracle `test_iscript_gen.py` (4/4): merge clean, non-destructive, intent + the
variable `playsndrand` decode preserved. The browser **✎ Teksto asembleris**
panel (generate text from a script, edit, compile+merge, live coverage check) is
byte-identical to Python (sha-verified).

`sfxdata.dat` = 10 296 B = 1144 × 9 (tbl index u32 @0, priority @4576,
flags @5720, lengthAdjust @6864, minVolume @9152). String table is
**`arr\sfxdata.tbl`**, not `rez\`. `portdata.dat` = 1320 B = 110 × 12.

### SD assets are identical between BW and SC:R
Verified by SHA-256: `wirefram.grp`, `cmdicons.grp`, `icons.grp`, `twire.pcx`,
`tunit.pcx`, `units.dat`, `badlands.wpe` all match. Only `stat_txt.tbl` differs
(MPQ 1547 strings vs CASC 1539) and `tconsole.pcx` is absent from CASC.

### This install's CASC completeness
52 498 names, **all decoded**; 21 161 (40.3 %) resolve to local bytes. Everything
missing is `locales/` for non-English languages — `locales/enus` is complete and
**graphics are 100 %**. It is a normal single-language install. CascView needs
the install root (where `.build.info` lives), not `data\data`.

### Where campaign missions live (measured — no single archive has everything)
A campaign lister must read a CHAIN, not one archive. **BW**: original campaigns
(`campaign\terran|zerg|protoss\<mission>\staredit\scenario.chk`) are in
**StarCraft.mpq** (601 MB), Brood War ones (`campaign\exp{race}\…`) in
**BroodWar.mpq** (571 MB); but `aiscript.bin`/`stat_txt.tbl`/`*.dat` are in
**StarDat/BrooDat/patch_rt** — so no single `.mpq` holds both the scripts and the
maps. `MpqChain` (Python) handles this; the browser now has an equivalent MPQ
chain (`mpqChainRead` over every loaded `.mpq`). **SC:R CASC**: `aiscript.bin`,
`stat_txt.tbl` sit at the same `scripts/`,`rez/` paths, but campaign chks are
under **`locales/enus/assets/campaign/<folder>/<mission>/staredit/scenario.chk`**
(68 enus), NOT `campaign\…`. The browser probes both path forms.

### CHK triggers, conditions + the mission spec sheet
`chk.py` parses TRIG **conditions** (16 × 20 B, `condType@+15`, `comparison@+14`,
player@+4/qty@+8/unit@+12) alongside actions. `mission_spec.py` turns a mission
into the engine's **bug-diff reference**: objectives text (MBRF act 4 / TRIG act
12), WIN/LOSE trigger conditions (triggers carrying Victory=act 1 / Defeat=act 2),
ownership transfer (`give_units`=48, `set_alliance`=57, `create_props`=11, **rescue
OWNR** = owner byte 3), pre-placed roster, heroes, AI attack. A campaign bug =
divergence between this ENCODED truth and the engine's OBSERVED behaviour.
MEASURED, and it corrected a wrong model of Revolution (terran05): the Antigan
base becomes player-**controlled** via the RESCUE owner (player 2) +
CreateUnitWithProperties — **0 SetAllianceStatus, 0 GiveUnits** → control transfer,
NOT an alliance (V confirmed). Terran "Rebel Yell" file→mission map (SPRP internal
names differ from retail titles): terran01 Wasteland … terran06 Norad II ("New
Year's Day"), **terran07 "Biting the Bullet" + terran10 "Operation Silent Scream"
are CUT/beta** (in the MPQ, not the retail sequence), terran08 Trump Card, terran09
Big Push, terran11 New Gettysburg, terran12 Hammer Falls (Ion Cannon unit
pre-placed). Oracle `tests/ai/test_mission_spec.py` (4/4); browser **📋 Spec sheet**.
`trigger_corpus.py` goes further — the WHOLE trigger set of every mission (all
conditions + actions, resolved, IF/DO) + the campaign type vocabulary. MEASURED
over the campaign: **1850 triggers, 2767 conditions, 9666 actions; 13 condition
types + 47 action types, 0 unknown** — the `COND_TYPES`/`TRIGGER_ACTIONS` tables
cover it end-to-end (the CHK analogue of the AI-disasm boundary oracle). Snapshot
in `assets/campaign_trigger_survey.json`; oracle `tests/ai/test_trigger_corpus.py`
(4/4); browser **🔧 Visi triggeriai (IF/DO)** in the mission view.

### Replay (`.rep`) format — measured
A `.rep` is the players' INPUT (command) stream, not game state; the full board
comes only from replaying it through the engine (that is the OpenBW session's job;
`tools/rep/` is the independent command decode it diffs against).
- **Container**: a sequence of SECTIONS, each `u32 crc, u32 nChunks, nChunks×(u32
  compressedSize, bytes)`; each chunk expands to `min(8192, remaining)` of the
  section's known size (stored raw when compressedSize == that). Order: magic(4)
  `reRS`/`seRS`, header(633), size(4)=cmdLen, commands(cmdLen), size(4)=mapLen,
  map/CHK(mapLen). **`reRS`** (classic 1.16) chunks are PKWARE-imploded
  (`mpq.explode`); **`seRS`** (SC:R) chunks are zlib AND one extra u32 (total size)
  sits after the magic; SC:R also appends unparsed trailer sections. Measured: 5
  classic parse to exact EOF, 4 SC:R to the trailer.
- **Command stream**: frame-blocks `u32 frame, u8 blockLen, blockLen bytes`; a
  command = `u8 player, u8 cmdId, args`, many per block (same frame). Frames rise
  monotonically; every block + the whole section consume exactly (the coverage
  oracle). Arg sizes were solved from the tiling constraint, not guessed.
- **Select is variable**: classic `0x09/0a/0b` = 1 + n×**2**-byte tags; SC:R
  `0x63/64/65` = 1 + n×**4**-byte tags (the `_121` commands `0x60-0x65` are SC:R's
  extended right-click/select set, present even in `reRS` files from modern
  clients). `build 0x0c` = order,u16 x,u16 y,**u16 unit@+5**; `train 0x1f`/`morph
  0x23` = u16 unit; `tech 0x30`/`upgrade 0x32` = u8 id.
- **Player attribution is by STORM id** (player struct +4), not the display pid
  (+0): commands tag the storm id, and mixing them up swaps who did what (it made
  a Zerg look Protoss until fixed). Struct: +0 pid, +4 storm id, +8 type(2=human),
  +9 race(0 Z/1 T/2 P), +10 team, +11 name[25]. `leave_game 0x57` frame = who left
  first ≈ the loser.

---

## 5. Mistakes worth remembering

Several times the bytes were read correctly (or the parse ran) and the
*meaning* was wrong:

1. `.anim` "version 0x0204" was two separate bytes, `scale` and `type`.
2. `_dds.grp` "frame x/y offsets" were a u32 trailer plus header padding. The
   stride coincidentally matched, so the file parsed to the byte — and the model
   was still wrong.
3. HD wireframe cell roles are not positional; "last cell is the art" silently
   painted over the actual artwork.
4. VP8 `B_VL_PRED`: nine of the ten subblock prediction layouts were copied
   from the spec and one was written from memory of "the pattern". It was the
   only wrong one. The decoder still parsed every file perfectly — prediction
   errors do not desync the bitstream, so nothing complained until pixels were
   compared against libvpx.
5. VP8 inter `hev_threshold`: followed the reference decoder (dixie) instead of
   the RFC prose, which agree for key frames but not inter frames. Every frame
   still decoded and every partition still ended on its boundary — the error
   was a ±1 on a handful of loop-filtered pixels, invisible until the per-frame
   pixel diff against libvpx. Two independent implementations agreeing (dixie
   and my port of it) is worth nothing when both copy the same mistake; the
   browser's libvpx was the genuinely independent oracle.
6. VP9 `tx_size` context: written from memory instead of read from the spec.
   The spec (§9.3.2) uses a neighbour's transform size only if that neighbour
   was *not* skipped; I used it unconditionally. This one DID desync — the tile
   padding oracle caught it — but it first looked like two separate bugs (all
   HD profile-1 frames + all profile-0 frames) when it was one. Two lessons:
   read the spec, don't guess a context; and a clean partition of failures
   ("all 4:2:0") can be a false lead — the real split was "has skipped
   neighbours", which correlated with frame size, not subsampling.
7. VP9 reconstruction buffer sized to `MiCols*8` instead of the
   superblock-aligned size. VP9 partitions cover whole 64×64 superblocks, so a
   32×32 transform whose top-left is on-screen can write into the off-screen
   remainder — samples that are never read or output but must exist. It crashed
   only on the two frames (`statin`) that actually had such a straddling block,
   after running clean through all 559 `lf==0` frames and looking done. A whole
   test subset passing is not the same as the code being right; the corpus that
   exercises the rare path is.
8. VP9 inter-frame colour config: an inter frame does not re-signal chroma
   subsampling — it inherits it from the sequence's last `color_config` (spec
   7.2). The parser left `subsampling` unset on inter frames, the decoder
   defaulted to 4:2:0, and every 4:4:4 inter frame's chroma was decoded at half
   resolution → full entropy desync. All 4:2:0 clips (and the 60×56 profile-0
   heads) passed because 4:2:0 *is* the default, so the failure looked like a
   clean "4:4:4-only chroma-book" bug — the same false-split lesson as #6. The
   real fault was a field only 4:4:4 frames read differently, not the chroma
   token path (which was already correct). Two follow-on lessons: the padding
   oracle localised it (chroma plane came back half-width) once I stopped
   theorising and *measured the plane dimensions*; and a stateful parser reused
   across clips leaks its colour config, which briefly mislabelled every clip's
   profile and sent the diagnosis down a false trail — debug scripts need a
   fresh parser per clip, exactly as the decode paths do.

The antidote: make a **falsifiable prediction** from the data and check it.
Deriving that `units.dat` must be 19 876 bytes and finding exactly that is
evidence; "it parsed" is not.

And one about independence, now seen **three times**: the uncompressed-MPQ bug,
and the `BlockGroup` bug, each lived in **both** the Python and JS readers,
because the same author wrote both. Two implementations are only worth something
when they come from different heads — which is exactly why
the independence rule (§1 reason 2, §6, §7.5) forbids sharing code with the engine.

A related habit that keeps paying off: when a file yields *nothing* — zero
frames, zero blocks, an empty list — suspect the reader before the file.

## 6. Provenance

Everything here is written without reference to other decoders, **except**
`tools/mpq_wave.py` and its JS twin: the nine 258-byte Huffman weight tables and
the ADPCM step tables are format data that cannot be derived, taken from
[StormLib](https://github.com/ladislav-zezula/StormLib) (MIT, © 1999–2013
Ladislav Zezula). The algorithm was written from the structure. That decoder is
therefore not an independent check of StormLib — but it does not need to be:
SC:R ships the same audio uncompressed under `sd/sound/`, and **1123/1123
comparable files match byte for byte** through a chain that shares nothing with
StormLib.

The same reasoning already applied to the PKWARE `blast` tables in `tools/mpq.py`.

`tools/vp8_tables.py` is the same category but a cleaner case: the tables come
from **RFC 6386 itself**, the published normative specification of the format,
and they are extracted from its text by a script rather than transcribed, so
the provenance is checkable and a typo is impossible. The decoding algorithms
in `tools/vp8_decode.py` are written from the spec's prose. That decoder is
therefore not independent of the RFC — nothing could be — but it *is*
independent of libvpx, which is what makes the 633/633 byte-exact comparison
against the browser's libvpx worth something.

---

## 7. Extended reference (migrated from the deleted `docs/`)

> `docs/` was consolidated into this file on 2026-07-27 (single-doc handover) and
> deleted. Everything below was measured; §4 has the primary format knowledge,
> this section holds the longer tables/specs that used to live in `docs/`.

### 7.1 `units.dat` full field-offset table (SoA, closes at 19 876 B)
The 4 anchors in §4 (hitpoints@3156, ready_sound@9312, portrait@14404,
group_flags@16684) sit inside this complete layout (offset = byte, ×N = element
count if not 228):
```
flingy@0  turret_unit_type@228  subunit2@684  infestation@1140(×96,bld)
construction_animation@1332  unit_direction@2244  has_shield@2472
shield_points@2700  hitpoints@3156  elevation_level@4068  sublabel@4524
ground_weapon@5892  air_weapon@6348  flags@7032  sight_range@8172  armor@8856
ready_sound@9312(×106)  first_what@9524  last_what@9980  first_pissed@10436(×106)
last_pissed@10648(×106)  first_yes@10860(×106)  last_yes@11072(×106)
placement_size@11284(×2)  addon_position@12196(×96×2)  dimensions@12580(×4)
portrait@14404  mineral_cost@14860  gas_cost@15316  build_time@15772
group_flags@16684  supply_provided@16912  supply_required@17140
build_score@17824  destroy_score@18280  unit_map_string_index@18736
is_broodwar@19192  staredit_availability_flags@19420
```
HP spot values: Marine 40, SCV 60, Ghost 45, Zergling 35, Probe 20HP/20shield,
Zealot 100/60, Command Center 1500. **`shield_points` is garbage (100) when
`has_shield==0`.** `unit_map_string_index` is 0 everywhere (unit names come from
`stat_txt.tbl[id+1]`, §4). `sfxdata.dat` flag bits: `0x01 preload, 0x02
unitSpeech, 0x10 oneAtATime, 0x20 neverPreempt` (`sfxdata.tbl` 31 985 B/1127).
`portdata.dat` (1320 B = 110×12): `0 u32[110] idle(Fid) index`, `440 u32[110]
talk(Tlk) index`, `880/990/1100/1210 u8[110]` idle/talk A/B counts (meaning
unconfirmed); `portdata.tbl` 3319 B/187; portrait range 0–105 + 22×0xFFFF.

### 7.2 Dialog `.bin` format + console/remap PCX (1.16.1 UI geometry)
The console command-card geometry lives in **`rez\statbtnn.bin`** (double `n`,
1212 B, from patch_rt.mpq). `statbtn.bin`/`statupgr.bin`/`statgame.bin` do NOT
exist. 86-B records (1204/86 = 14), chained via +0:
```
+0  u32 next-offset (0=end)   +4  i16×4 x0,y0,x1,y1   +12 u16×2 w,h
+20 u32 string-offset   +24 u32 flags   +32 u16 control-ID   +68 u32 first-child
```
Entry 0 = dialog 144×126 @(496,354) (bottom-right of 640×480). Entries 1–9 = the
3×3 command card, IDs 1–9, x0∈{9,55,101}, y0∈{4,44,84}, **step 46×40**. Other
bins: `statdata.bin` 4997, `gluChat.bin` 7214, `gluScore.bin` 5417, `minimap.bin`
438, `statport.bin` 269 (29 total). Console/remap PCX: `tconsole.pcx` 37 577 B
640×480, `NConsole.pcx` 31 705 640×480, `tunit.pcx` 1018 128×1 (16 players×8),
`twire.pcx` 920 24×1, `tselect.pcx` 919, `thpbar.pcx` 913 19×1, `tminimap.pcx`
913 16×1. `game\ticon.pcx` does NOT exist in 1.16.1 — the cmd-icon palette is
`unit\cmdbtns\ticon.pcx` (993 B).

### 7.3 SC:R UI-as-data + localization
SC:R has **zero dialog `.bin`** — the console is DDS under `/consoles/`, **10
themes** (terran/protoss/zerg/bc2018/war3spoils/sc_20thanniversary/krc_gold/
krc_silver/neutral/bc2017), file set console_left/center/right/apm/time.dds +
conover/pbrempt/pbrfull/cmdbtns(.dds).grp/dlg(.dds).grp; SD uses one
`console.dds`. UI dialogs are **`.ui.json`** = decompiled Win32 resources, **1920
files** (128 × 14 langs + 128 in `sd/rez/`); schema `{type,name,rect:[x,y,w,h],
style,children:[{type,content,id,rect,flags}]}` where `content` is a KEY resolved
via `locales/<loc>/assets/rez/rc3.json` (978 entries). **No graphics are
localized** (0 pcx/dds/grp/anim under any `locales/`). `stat_txt` three forms:
MPQ 40 398 B/1547, CASC 40 290/1539, JSON 189 029/1551 (` * `
double-escaped). Per-lang name counts: dede 4257, itit 4216, eses 4213, frfr
4207, enus 1649. CASC per-type completeness: `.grp` 1260/1260, `.anim`
3510/3510, `.dds` 1704/1704, `.pcx` 313/313; the internal `(listfile)` names only
**939** files (why the app ships a 10 626-name union listfile).

### 7.4 `aiscript.bin` / `bwscript.bin` binary format (the AI-script VM data)
Distinct from `iscript.bin` (§4). `scripts\aiscript.bin` = 62 050 B, table@0xe00e,
**16-B records** `id[4] + offset[4] + string_id[4] + flags[4]`, 293 slots (137
with code, 156 unused offset==0). `scripts\bwscript.bin` = 26 458 B, table@0x6276,
**8-B records** `id[4] + offset[4]`, 156 slots, no names. `u32@0` = offset to the
end-of-file record table, terminated by a null-id record. `string_id` = 1-based
`stat_txt` index (1048–1539). `flags` distribution `{7:157,3:75,1:24,5:18,2:16,
0:3}` (bits, unconfirmed: `0x01 requires_location, 0x02 staredit_hidden, 0x04
broodwar_only`). Opcodes 1 byte, values 0..113 (**114 opcodes**); `address` args
are ABSOLUTE file offsets; the body is a CFG (goto=0, stop=36, return=65 end
blocks; unreachable bytes between blocks → trace reachability, not linear scan).
Corpus oracle: aiscript 137 scripts/15 319 instr/937 targets/0 bad; bwscript
156/7628/131/0. **CHK TRIG** (§4 has the condition side): a trigger is 2400 B = 16
conditions ×20 B then **64 actions ×32 B @+320**; action struct `+0 u32 location
(1-based MRGN), +4 u32 string_id, +8 u32 wav_string_id, +12 u32 time, +16 u32
player/group, +20 u32 script_fourcc, +24 u16 unit_type, +26 u8 action_id (15=Run
AI Script, 16=…At Location), +27 rest`. MBRF reuses 2400/32-B with different ids.

### 7.5 GRPI / ARGB reference-dump binary spec (cross-check a 2nd decoder)
Neutral artefacts (`grp2png --dump-idx`/`--dump-argb`; engine twin
`aidump grpidx`/`argbdump`) compared with `fc /b`/hash. **The rationale for NOT
sharing decoder code with the engine is the whole point** (independence, §1/§6):
the two implementations must come from different heads.
- **GRPI** (16-B header LE): `0x00 "GRPI", 0x04 u16 ver=1, 0x06 u16 frameCount,
  0x08 u16 canvasW, 0x0A u16 canvasH, 0x0C u32 reserved=0`. Per frame: `u16 offX,
  offY, w, h, flags, reserved` then `u8[w*h]` indices top-to-bottom (index 0 =
  transparent, dumped BEFORE palette). Flag bits: `0 row-overflow-clamped,
  1 dataOffset-past-EOF (empty), 2 row-short-of-width, 3 read-as-flat`.
- **ARGB** (16-B header): `0x00 "ARGB", 0x04 u16 ver=1, 0x06 u16 reserved, 0x08
  u32 w, 0x0C u32 h` then `w*h × u32 LE 0xAARRGGBB`, mip 0 only, transparent
  pixels NOT zeroed. Compare the DXT atlas BEFORE downscale (stage 1 = DDS→ARGB
  byte-exact; stage 2 = downscale policy, kept separable).

### 7.6 Authentic `twire.pcx` hex (engine wireframe constants)
Band colours (indices SD 208–211 / 216–219): yellow `0xfcfc38`, green `0x10fc18`,
orange `0xf88c14`, red `0xc81818`. Blue shield ramp (7): `0c48cc 0c48cc 083498
083498 042064 042064 001034`. 24-entry map: `0..2` yellow/green/black, `3..9`
blue shield, `10..13` red, `14..17` purple (`88409c 88409c 683078 481c50`),
`18..20` orange (`f88c14 e85014 a0541c`), `21..23` black.

### 7.7 `wireframe-colors.json` schema + shield model + engine-reader rules
§4 has the Zerg-gradient and T/P-stage HP models; the shield + schema:
- **Shield:** `hi = floor(shield% · (n−1) / 100)`, n = `shield_ramp.length`;
  `color = shield_ramp[floor(hi/2)]`. HD = the 2 outermost-radius mask cells; SD =
  indices 192/193. **192/193 are used by ALL races** (base layer): non-Protoss get
  `structure` colours, Protoss gets the shield ramp.
- **Schema (v2):** `ramps.hp` (9 dead→healthy), `hp_alt_tp` (9), `shield` (7 blue),
  `structure.index192/index193`, `hd_line`, `ramp_semantics`; `races.{terran,
  protoss,zerg}` with `sd_hp_indices / sd_base|sd_shield / hd_mask_count / hp_model
  / uses_shield`; `models.{gradient(grad:5,shift:6), stages([8,7,2])}`,
  `shield_model`, `hd_mask_assignment`, `heatmap`, `engine_reader`,
  `mask_colors_override`.
- **Engine-reader validation:** missing file = NOT an error (fall back to
  hardcoded); if `ramps.hp` ≠ 9 or `shield` ≠ 7 → reject the whole file and log,
  never half-apply. Race from `group_flags@16684`; HP% and shield% are the only
  runtime inputs. HD mask assignment: sort MASK cells by opaque-pixel radius;
  Protoss (>4 masks) → 2 largest-radius = shield, else all = HP; `depth =
  rank/(N−1)`. Measured shell radii: Zergling 8.6→9.1→12.9→16.8 px, Drone
  8.1→12.3→15.2→17.3; `wirefram.dds.grp` = 29 916 344 B; mask saturation <~25.

### 7.8 HUD v2 layout (source spec for the browser HUD editor)
`ui_legacy=false` → HUD v2 (`draw_hud2()` `ui.h:7846`); `true` → legacy
`tconsole.pcx` 640×480. Zoom-invariant px via `hud_h_px/hud_w_px` (`ui.h:3458`).
**Master dimensions (the layout "handles"):** `hud2_bar_h()` = screen_height·24%,
clamp [96 px, 32%] (most panels are squares of side = bar_h); `hud2_edge()` =
width·4%, min 12 px; `hud2_margin()` ≈ 4 px; `hud2_groups_row_h()` = bar_h·15%;
`hud2_inner(r)` = r−3 px. Bottom-bar panels L→R (with `ui.h` lines):
`hud2_minimap_panel`(:3466, square@edge), `hud2_unit_panel`(:3499),
`hud2_portrait_panel`(:3468, w=bar_h·55%), `hud2_menu_panel`(:3469),
`hud2_card_panel`(:3467, square@right−edge). Util row `hud2_util_cell`(:3543)=PING/
IDLE/ARMY h30px; groups `hud2_groups_strip`(:3521) cell=row/11; queue
`hud2_queue_strip`(:3530). Unit-display internals (`draw_hud2_unit_display`:8130,
pad=6): wireframe `hud2_wireframe_box`(:3504)=PH·79% (≤PW·2/5); production
`production_slot_rects`(:8048) icon=regionH·60% clamp[14,44] max 5; cargo
`cargo_slot_rect`(:7994) up to 8; card cell `hud2_card_cell`(:8576) g=side/20,
cell=(side−4g)/3; resources `draw_hud2_resources`(:8525) frames `f_min=0,
f_gas=1+race, f_sup=4+race` from icons.grp. Rule: every `*_hit()`/`*_area()` calls
the SAME geometry fn as the draw. Editor output = normalized rects
`{anchor,x,y,w,h,…fracs}`. Constraints: bar_h floor 96 px, edge floor 12 px,
wireframe ≥16 px, production [14,44]; panels must not overlap (unit_panel uses
margin·3 gaps).

### 7.9 Engine oracle-pack (the byte-exact diff surface for the engine)
Independent second-implementation oracles the OpenBW engine diffs against
(NOT shared algorithm code — different heads). **Toolkit side 100 % ready**; only
the engine-side C++ (`combatcheck`/`repcheck` + wiring) remains, which is the
engine session's job.

| Oracle | Toolkit command | Committed fixture | Engine diff-point |
|---|---|---|---|
| media (VP9/VP8/WebM/DXT/CASC/YUV) | `*_gen_oracle.py` | — | `tools/*_check.sh` (wired) |
| AI-VM runtime | `ai_disasm` + `run_compare.py` | — | `aistep.cpp` (wired) |
| campaign CHK/triggers | `mission_analyzer.py`,`chk.py` | `campaign_trigger_survey.json` | `trigcheck.cpp` (wired) |
| **damage** | `combat.py --fixture` | `assets/combat_fixture.json` | `combatcheck.cpp` (new) |
| **replay cmd stream (+seRS)** | `rep/rep_canonical.py` | — | `repcheck` (new) |
| asset regression + determinism | `golden.py check/determinism` | `assets/golden_manifest.json` | asset-side gate |
| SC:R patch diff | `asset_diff.py --casc a b` | — | patch workflow |

Combat fixture = per-unit effective-damage matrix (size S/M/L/Shields × armor 0–3
× upgrade 0–3); it pins the armor→factor order + fixed-point/min-damage floor the
model flags as unconfirmed. `rep_canonical` = stable `f<frame> p<storm> <cmd_id>
<name> <args-hex>` dump (reRS + seRS) — the reference for the engine's open SC:R
seRS loader + multi-slot desync items. Oracles: `test_combat.py` 5/5,
`test_rep_canonical.py` 3/3 (9 replays/136 313 lines), `test_oracle_harness.py`
4/4 (golden self-consistency + tamper + determinism + committed-manifest match).
The engine's determinism gate is `aidump replay = 2740293492` + `campaign 66/0`
(host) / `33/0` (tablet) — sacred; grp-toolkit is the *asset/decode* oracle beside it.

### 7.10 Corpus subcounts (evidence)
SD-identity byte sizes (BW == SC:R by SHA): `wirefram.grp` 306 897, `cmdicons.grp`
230 008, `twire.pcx` 920, `tunit.pcx` 1018, `units.dat` 19 876, `badlands.wpe`
1024, `icons.grp` 2608. WebM/VP tree: `sd` 609, `hd2` 569, `carbot` 563,
`portrait` 535 (60×56 → 1920×1080; 89 cinematics @1920×1080); VP9 whole-corpus
1764/1850 clean (86 `smk/` container-anomalous, portraits unaffected). Sound
census: 397 files / 7735 sectors (sector 0 always 0x08 PKWARE, 7169×0x41,
198×0x81); MPQ WAVE 1123/1123 byte-match vs CASC PCM (1123/1127 sizes; 4 unpaired).
Portraits: SMK 519 files (all SMK2 60×56, 10 fps, 6–25 frames); SC:R WebM
`portrait/` 535@448×480, `sd/portrait/` 535@60×56, `hd2/portrait/` 528@224×240,
`carbot/portrait/` 528@448×480.
