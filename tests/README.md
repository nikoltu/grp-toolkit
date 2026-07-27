# Verification scripts

Every "N / N" claim in this project has a script here that re-proves it against
the real archives. **If a script and a comment disagree, the script is right and
the comment is stale.**

They are not unit tests — they run against actual game installs and compare
against independent sources. Run from this directory:

```powershell
py test_casc_and_shared.py      # ~1 min
py test_wav_vs_casc.py 300      # ~3 min  (argument = how many files)
py test_smk_corpus.py           # ~2 min
py test_vp8_headers.py          # ~4 min
py test_vp8_pixels.py           # ~9 min  (decodes every VP8 keyframe)
py test_vp8_video.py --maxpix 40000   # inter frames, small clips (~4 min)
py test_vp9_headers.py          # ~6 min  (VP9 uncompressed header, corpus)
py test_vp9_pixels.py           # ~6 min  (VP9 key-frame reconstruction, lf==0)
py test_vp9_seq.py              # ~4 min  (VP9 inter sequences vs PyAV; pip install av)
py test_webm_corpus.py          # ~8 min  (reads every .webm)
py ai/test_ai_disasm.py         # ~2 sec  (AI-script disasm coverage over the corpus)
py ai/test_chk_links.py         # ~5 sec  (campaign CHK -> AI-script links resolve)
py ai/test_ai_semantics.py      # ~3 sec  (CFG + semantic model over every script)
py ai/test_ai_roundtrip.py      # ~4 sec  (decode->encode byte-identical + reloc)
py ai/test_ai_scaler.py         # ~5 sec  (difficulty scaler is layout-safe)
py ai/test_ai_runtime.py        # ~4 sec  (AITR trace aligns to static disasm)
py ai/test_ai_gen.py            # ~3 sec  (bot generator: standalone disasm-clean + merge keeps stock)
py ai/test_briefing.py          # ~4 sec  (campaign MBRF briefing timeline: 64 missions, 421 lines)
py ai/test_mission_actions.py   # ~4 sec  (campaign trigger unit-commands: 2641, Move/Patrol/Attack)
py ai/test_mission_analyzer.py  # ~5 sec  (full per-mission report: briefing+commands+AI+heroes JSON)
py ai/test_mission_bot.py       # ~5 sec  (per-mission bot behaviour from AI bytecode: build/train/attack)
py ai/test_walkthrough.py       # ~5 sec  (script<->community-walkthrough cross-reference, 18/19 confirmed)
py ai/test_mission_spec.py      # ~5 sec  (per-mission spec: win/lose conditions + ownership transfer)
py ai/test_trigger_corpus.py    # ~5 sec  (full campaign trigger corpus: 1850 triggers, 13 cond + 47 act types, 0 unknown)
py ai/test_build_orders.py      # ~2 sec  (22 pro build orders compile to disasm-clean bots)
py test_mpq_writer.py           # ~2 sec  (MPQ writer: build -> read-back byte-identical)
py test_mod_pack.py             # ~2 sec  (mod packager: zip overlay + data.mpq + manifest)
py test_dat.py                  # ~2 sec  (units/weapons.dat: layout anchors + edit round-trip)
py test_combat.py               # ~2 sec  (damage oracle: weapon resolve incl. turret + factor model)
py test_tbl.py                  # ~2 sec  (string table read/write: byte-identical + extended parts)
py rep/test_rep_canonical.py    # ~2 sec  (stable replay command dump: 9 replays, 136k lines)
py test_grp_writer.py           # ~2 sec  (GRP writer: pixel round-trip, real + synthetic)
py test_dat_chain.py            # ~2 sec  (graphics chain flingy/sprites/images -> GRP name)
py test_anim_inventory.py       # ~11 sec (SC:R HD .anim inventory: all 3510 parse + tiers/layers)
py test_dxt.py                  # <1 sec  (DXT1/3/5 decode: synthetic hand-computed blocks)
py test_player_colors.py        # <1 sec  (teamcolor mask tint: hand-computed, 8 players)
py test_anim_composite.py       # ~2 sec  (HD 7-layer composite: byte-exact ops + real-frame anchors)
py test_sd_hd_bridge.py         # ~6 sec  (SD GRP <-> HD anim: 214/214 frame counts equal)
py test_oracle_harness.py       # ~4 sec  (golden regression + determinism + patch asset-diff)
py rep/test_rep.py              # ~3 sec  (replay decode: container + 136k commands + build-order semantics)
py test_dxt.py                  # ~1 sec  (DXT1/3/5 decode vs hand-computed blocks)
py iscript/test_iscript.py      # ~2 sec  (iscript.bin container + disasm coverage)
py iscript/test_iscript_asm.py  # ~3 sec  (iscript assembler round-trip + relocation)
py iscript/test_iscript_gen.py  # ~2 sec  (iscript text assembler: text -> merge, non-destructive)
```

`test_vp8_pixels.py --export` additionally writes `tests/_vp8cmp/` (~16 MB,
one `keyframes.bin` + a `manifest.json` of SHA-256 hashes; deleted afterwards,
regenerate when needed) for the browser half of that check — see below.
`test_vp8_video.py --export` writes `tests/_vp8vid/` the same way but with every
frame of every clip, for `vp8-video-oracle.html`. The pure-Python inter decoder
is slow (6-tap motion compensation per 4x4), so `--maxpix WH` skips clips above
a pixel budget to keep a run tractable; the whole 33 080-frame corpus is a long
background run.

Each prints one `PASS`/`FAIL` line and exits non-zero on failure; exit code 77
means a required install was not found.

Paths come from `tests/common.py` and can be overridden:
`SC_BW_DIR`, `SCR_DIR`.

## What each one actually proves

| Script | Claim | Why the check is meaningful |
|---|---|---|
| `test_casc_and_shared.py` | 52 498 names, 21 161 reachable, graphics 100 %; SD assets byte-identical between BW and SC:R | Any unreachable file **outside** `locales/` would mean a real gap, not a language pack |
| `test_wav_vs_casc.py` | MPQ Huffman+ADPCM output == SC:R `sd/sound/` bytes | The oracle shares no code with the decoder: MPQ crypto→Huffman→ADPCM vs CASC `.idx`→BLTE→encoding→root |
| `test_smk_corpus.py` | 519 portraits, 5 369 frames decode, none all-black | A drifting MRU cache overruns the file and throws on the last frame |
| `test_vp8_headers.py` | 633 VP8 keyframes, dimensions match the container, no field out of spec range | A wrong bool decoder cannot keep hundreds of files inside legal ranges by luck |
| `test_vp8_pixels.py` | 633 keyframes decode; every residual partition ends **exactly** on its declared boundary | An arithmetic decoder that mis-reads one token is shifted for everything after it, so the endpoint is a statement about all of them |
| `vp8-oracle.html` | all 633 keyframes (490 loop-filtered) are byte-identical to libvpx | Compared in I420, the codec's own colour space — an RGB comparison also measures colour conversion and hides the answer |
| `test_vp8_video.py` | every frame of every sampled clip decodes; each frame's partition ends on its boundary | Inter frames chain — a wrong motion vector or reference-frame update drifts within a few frames |
| `test_vp9_headers.py` | every VP9 portrait frame's headers are in range and end on zero padding, and every key frame's partition + intra modes + coefficient tokens decode to zero tile padding | The portrait heads are VP9; stages 1-3a of a VP9 decoder. A wrong bit offset or context leaves non-zero data unread — 1073/1073 key frames clean |
| `test_vp9_pixels.py` | every VP9 portrait key frame reconstructs and deblocks (intra prediction + dequant + inverse transforms + loop filter); `vp9-oracle.html` proves the whole corpus is byte-identical to libvpx | Stages 3b + 4 turn 3a's coefficients into deblocked pixels. All 1073 key frames match (514 loop-filtered), plane-for-plane in the native buffer (I444 / NV12), never RGB. Reconstruction was validated first on the 559 `lf==0` frames, then the loop filter closed the rest |
| `vp8-video-oracle.html` | each frame of the sampled clips is byte-identical to libvpx, in order | Decoding a long sequence frame-for-frame is what actually exercises motion compensation and reference management |
| `test_webm_corpus.py` | Whole corpus parses; **zero blocks counts as failure** | That is exactly how the `BlockGroup` bug hid — an empty result looked like an empty file |
| `ai/test_ai_disasm.py` | Every AI script (137 aiscript + 156 bwscript) decodes via control-flow; **every jump/call target lands exactly on an instruction boundary** (0 bad / ~1068) | One wrong opcode-argument size shifts everything after it and drops a jump off a boundary — the AI equivalent of VP8 partition slack. 0 unknown opcodes corpus-wide |
| `ai/test_chk_links.py` | Every campaign map's "Run AI Script" trigger action resolves its FourCC in the script table (67/67 over 210 maps) | A wrong action-struct field offset or endianness would make ids fail to resolve — full resolution proves the CHK action layout |
| `ai/test_ai_semantics.py` | CFG builds for every script; every edge target is a real block; the semantic plan's counted instructions never exceed the reachable set (293/293) | Inherits the disasm oracle; proves the CFG + semantic model are self-consistent over the whole corpus |
| `ai/test_ai_roundtrip.py` | decode → encode (no changes) → **byte-identical** for every instruction + the entry table; plus relocation re-decodes identically (2/2) | The encoder is the exact inverse of the decoder — an editor built on it cannot silently corrupt an unedited script |
| `ai/test_ai_scaler.py` | The difficulty scaler (brutal profile) is **layout-safe**: every scaled script re-decodes to the same opcode sequence with jumps intact (293/293) | Scaling changes only counts/durations, never sizes or addresses, so it cannot move an instruction or break a jump — proven, not assumed |
| `ai/test_ai_runtime.py` | A simulated AITR runtime trace aligns to the static disassembly: every pc is a known instruction with a matching opcode (293/293, 18003 events) | The comparator that will consume real OpenBW engine logs is proven correct; a genuine static-vs-runtime divergence would surface as a mismatch |
| `ai/test_briefing.py` | The mission-briefing analyzer parses every campaign MBRF section and builds a well-formed dialogue timeline: all 64 missions carry a briefing, all 421 Transmission lines resolve to a non-empty text + .wav + positive duration, and speakers attribute to named units incl. heroes (Raynor/Stukov/Schezar) — a wrong action-field offset would give empty strings, zero durations, or wrong speakers (3/3) | Proves the byte-derived briefing timeline (who speaks, which portrait, what line, which wav, how long) matches the original, so the engine port can diff its briefing playback against it |
| `ai/test_mission_actions.py` | Classifying every campaign mission's TRIG actions yields well-formed per-unit commands: 2641 commands over 64 missions, Order actions decode to all three real order types (Move/Patrol/Attack), and every command's unit + Order/Move target resolve to real names/locations — a wrong action-field offset would give junk order types or empty targets (3/3) | The byte-derived reference for what a mission's triggers command units to do, so the engine port can diff its trigger interpretation against the original |
| `ai/test_ai_gen.py` | The generator's output passes the SAME oracle the real files do: a Tactic-built bot is disasm-clean and every emitted instruction re-encodes byte-identically (generate→disasm→re-encode is a fixed point); merging it into the stock `aiscript.bin` leaves the whole original code region byte-identical, every stock script still traces clean, the bot is reachable, and the table round-trips (8/8) | Proves a shipped `data/scripts/aiscript.bin` override keeps all 293 stock scripts and only adds bots — and that the compiler is the exact inverse of the disassembler, so a generated bot cannot silently be malformed |
| `ai/test_build_orders.py` | All 22 pro build orders (from V's Miro cards, `assets/build_orders.json`) parse with the required fields, every producible row (222) resolves through the measured name→id map (`assets/unit_ids.json`), and each compiles to an aiscript that is disasm-clean and re-encodes byte-identically (3/3) | Proves the build-order library is not just data but real compilable bots — and that the measured stat_txt name map covers the whole corpus |
| `test_grp_writer.py` | The GRP writer is a PIXEL inverse of the reader: for real GRPs (wirefram, cmdicons) and a battery of synthetic edge cases (fully transparent row, run > 0x3F, transparent gap > 0x7F, pure literal, single-pixel width), `decode(encode(frames))` reproduces the exact index grids (8/8); the re-encoded size vs the original is reported | Proves a modded sprite round-trips losslessly through our encoder — the guarantee that matters, since the game reads any valid RLE. Byte-identity vs Blizzard is not claimed (compression choice), and the size ratio measures the gap |
| `iscript/test_iscript.py` | iscript.bin's id table parses and every distinct images.dat.iscript_id resolves to an entry; tracing every animation of every header decodes the whole corpus with no desync (398 scripts, 1833 anims, 9763 opcodes — every opcode valid, every goto/call/condjmp target on a boundary); all header types are known (3/3) | One wrong opcode argument size shifts everything after it and drops a jump off a boundary — a clean trace of the whole animation corpus verifies the borrowed opcode/arg-size table end to end, the iscript analogue of the AI disasm oracle |
| `iscript/test_iscript_gen.py` | The text assembler compiles an iscript entry from text and merges it into the real iscript.bin: the merged file traces clean, every stock byte from offset 2 to the old id-table is untouched (an unedited stock script disassembles identically), and the edited id's animation decodes back to exactly the authored opcodes — including the variable `playsndrand` count + soundids (4/4) | Proves authoring/editing an animation is non-destructive (all stock scripts survive) and faithful (text round-trips to the intended bytecode), the iscript analogue of ai_gen |
| `iscript/test_iscript_asm.py` | The iscript encoder is the exact inverse of the decoder: every reachable opcode, every SCPE header, and the id-table region re-encode **byte-identically**; and the relocating `reassemble()` produces a new iscript.bin that re-parses clean with every animation's opcode sequence preserved after all label + animation offsets are remapped (4/4) | An editor built on it cannot corrupt an unedited script, and the reassembler can safely relocate code when opcode sizes change — the iscript analogue of the AI Stage-4 acceptance test |
| `test_dxt.py` | The DXT1/DXT3/DXT5 decoder produces the hand-computed RGBA for synthetic blocks: the 565→888 bit-replication expansion, the 4-colour 1/3 & 2/3 interpolation, DXT1's 1-bit-alpha (transparent) mode, and DXT5's alpha ramp, plus a DDS header parse (5/5). Separately confirmed byte-identical to the browser's `ddsToImageData` on a real `.anim` layer | Decode is deterministic, so this is a byte-exact pixel reference the HD engine can diff its texture pipeline against; matching two independent implementations (Python + the app) rules out a shared bug |
| `test_dxt.py` | The DXT1/DXT3/DXT5 decoder reproduces hand-computed RGBA for synthetic blocks: the 565→888 bit-replication, the 1/3 & 2/3 colour interpolation, DXT1's 1-bit-alpha mode, and DXT5's alpha ramp, with round-half-up matching JS `Math.round` (5/5) | DXT decode is the deterministic HD-texture reference; matching hand-derived values (and, separately, the browser's `ddsToImageData` byte-for-byte on real files) proves the engine can diff its texture pipeline against our PNGs |
| `test_player_colors.py` | The teamcolor tint is exact: mask 255 reproduces the player colour, mask 0 is transparent, and fractional weights round half-up (`playerColour × mask/255`, mask as alpha) for the standard 8 players (4/4) | The measured teamcolor layer is a grayscale mask; a byte-exact tint formula lets the engine verify its player-colour shader against per-player reference images |
| `test_anim_inventory.py` | Every one of the 3510 SC:R `.anim` files parses (a wrong field offset would desync/crash); both HD and HD2 tiers are present in bulk with the documented scale→tier mapping; the canonical 7-layer set dominates with DXT1/DXT5 formats; and the inventory captures the variation (non-7-layer files, entry-count outliers) the engine must handle (4/4) | The HD-engine robustness oracle: it proves the independent `.anim` reader covers the whole corpus and surfaces every ANIM variant, so nothing surprises the renderer at runtime |
| `test_dat_chain.py` | The graphics DAT chain (flingy/sprites/images.dat) closes at its exact sizes AND resolves END TO END: following units.dat.flingy → flingy.sprite → sprites.image → images.grp_file → images.tbl lands on the real .grp name for Marine/SCV/Zealot/Zergling; round-trip byte-identical and a grp_file edit touches only 4 bytes (4/4) | No single field offset could pass the full-chain resolution by luck — it verifies three layouts at once and pins the 1-based images.tbl indexing, the foundation for reskinning a unit's sprite |
| `test_dat.py` | The units/weapons.dat SoA field table closes exactly (arrays sum to 19876 / 5460) and hits all four measured offset anchors; known values decode (Marine 40 / SCV 60 HP, 1/256 fixed point); parse→to_bytes() is byte-identical and a single edit touches only that field's bytes; subset fields address the right 106/96 base (5/5) | A wrong width or count anywhere shifts a later anchor or misses the total, so a clean run is a statement about the whole layout — and the editor is proven unable to corrupt an untouched field |
| `test_combat.py` | A unit's resolved weapon is byte-exact incl. the turret subunit (Siege→Arclite 30 Explosive, Goliath→Twin Autocannons 12 + Hellfire 10; Marine 6, Zealot 8×2, Firebat 8×3); the size-factor table reproduces the documented mechanic (Dragoon Explosive 20 → 10/15/19 vs S/M/L); armor is per-hit (Firebat vs 1-armor = (8−1)×3=21, and ×25% vs Large = 5.25); determinism + the committed combat_reference.json matches the code (4/4) | The numeric inputs are falsifiable against the real .dat while the factor model is checked by the Compendium's own examples — an independent combat number the OpenBW engine diffs against, with the armor→factor order flagged as the one step the diff still confirms |
| `test_tbl.py` | The .tbl writer re-serialises stat_txt/sfxdata/images byte-identically when unedited (offset-order rebuild, not "return the original"); stat_txt's 274 extended entries keep their NUL-separated tooltip/hotkey bytes (raw longer than the display name); names decode (Marine=Terran Marine, id 106=Command Center); set_text changes only the name AND keeps the extended tail, append adds one, and parse→to_bytes round-trips (4/4) | Reading only to the first NUL would silently drop 3801 bytes on a rewrite and corrupt stat_txt — the byte-identical claim proves the full-slice model loses nothing, so the string editor is safe to ship an edited .tbl |
| `test_sd_hd_bridge.py` | Every unit's HD anim is `anim/main_<imageid>.anim` (the id its SD chain resolves), and over every unit resolving both an SD GRP and a `main_` HD anim the frame counts are EQUAL — 214/214, 0 mismatches; Marine/SCV/Zealot/Probe map to their real GRP + expected anim + HD tier; the 14 no-HD units are reported not matched (4/4) | Two unrelated asset pipelines render the same unit; equal frame counts across the whole resolved corpus is the proof the engine can pair SD frame i with HD frame i without a remap — one wrong image-id convention would break the counts |
| `test_anim_composite.py` | The HD layer composite is built from proven ops: src_over + additive emissive on hand-computed pixels; a diffuse-only composite of a real frame == `anim_render`'s diffuse crop byte-for-byte; the teamcolor contribution == `player_colors` exactly on masked-transparent pixels; determinism (5/5) | The shader RECIPE is a documented reference, but every OPERATion it composes is byte-exact — so locking the engine's real blend later is a pure diff, and the browser ★ Kompozitas twin is sha-identical to this |
| `test_oracle_harness.py` | Golden self-consistency + tamper detection (a manifest checks all-match against itself; a changed/dropped/extra entry surfaces as changed/new/gone), determinism over 7 pixel-decoder targets, and asset-diff identity + one-CKey-edit sensitivity over 52 498 CASC names (3/3) | These tools ARE the engine's regression net and desync check, so the oracles themselves are proven to fire on exactly the real events and stay silent otherwise |
| `ai/test_mission_bot.py` | Every campaign mission yields a JSON-serialisable bot-behaviour profile from its AI scripts' bytecode; the 54 attack-running missions have non-empty attack compositions; every build/train/attack unit resolves to a stat_txt name with a positive count; known missions field the right sets (terran05 Marine/Vulture/Wraith, protoss01 Zergling/Hydralisk) (3/3, 64 missions) | The objective record of what a mission's enemy does, straight from bytecode — a wrong opcode-arg read would give unnamed units or empty compositions; this is the ground truth the walkthrough is checked against |
| `ai/test_walkthrough.py` | Name normalisation makes script + guide names comparable; every curated mission is well-formed and resolves to a real mission; across the set the walkthrough's enemy units are 18/19 confirmed by the script's attack composition (two independent sources agreeing), ≥3 missions fully confirmed; discrepancies (terran07) are reported not hidden (4/4) | A high script↔guide corroboration ratio is a genuine oracle — the bytecode and a human walkthrough are unrelated sources — and the reported discrepancies (trigger-spawned / defensive units) are themselves useful signal |
| `ai/test_trigger_corpus.py` | Over every campaign mission, every trigger's conditions AND actions resolve to a KNOWN type — 0 unknown condition-type bytes and 0 unknown action ids across 64 missions / 1850 triggers / 2767 conditions / 9666 actions; the campaign vocabulary is the expected set (Bring/Switch/Command… conditions; SetSwitch/CreateUnit/RunAIScript/GiveUnits/Victory/Defeat… actions); Revolution's full IF/DO renders (Defeat + RunAIScript + no GiveUnits); deterministic (4/4) | A wrong condition offset or a missing table entry would surface as an unknown type across the corpus — this is the CHK analogue of the AI-disasm boundary oracle, proving the COND_TYPES + TRIGGER_ACTIONS tables cover the entire campaign so the trigger reference is complete |
| `ai/test_mission_spec.py` | Every campaign mission yields a JSON spec with win/lose triggers whose conditions parse to KNOWN types (0 unknown over 64 missions); the win/lose vocabulary is real (Command/Bring/CountdownTimer/Switch); Revolution's Antigan takeover measures set_alliance==0, give_units==0, rescue_players∋2, create_props>0; Desperate Alliance is the survive-timer mission (4/4) | A wrong condition offset would give junk types across 64 missions; the Revolution check pins the actual ownership-transfer mechanic (rescue OWNR, not alliance) that an engine bug would get wrong — the spec is the campaign bug-diff reference |
| `rep/test_rep.py` | Over 9 real replays (5 classic + 4 SC:R): every container parses (classic to exact EOF), the command stream decodes with EVERY frame-block consumed to its length and the whole section to its end (136 313 commands, 0 unknown ids), each producing player's build order opens on their race's worker (Drone/SCV/Probe), parse+analyse is deterministic, AND each SC:R replay transcodes to classic reRS that re-reads to the IDENTICAL logical commands (5/5) | The consumption oracle proves the measured command-size table over ~150k commands (one wrong size desyncs a block); the worker-opening check proves the unit-type decode AND the storm-id player mapping are right against the real game; the transcode check proves the seRS→reRS down-convert preserves every build/train/tech command, not just that it parses |

## Expected results as of 2026-07-24

```
PASS    casc: gaps only in locales/        1 / 1
PASS    shared: SD assets identical        9 / 9
PASS    wav: MPQ decode == CASC bytes   1123 / 1123
PASS    smk: portraits decode            519 / 519      (5369 frames)
PASS    vp8: header + bool decoder       633 / 633
PASS    vp8: intra decode + partitions   633 / 633   (every partition ended exactly on its boundary)
PASS    vp8: video decode + partitions    29 / 29     (977 frames, --maxpix 40000)
PASS    vp9: portrait header (uncomp+comp) 1 / 1      (1073 files, 12210 frames; 0 bad)
PASS    vp9: keyframe entropy (part+modes+tokens) 1073 / 1073   (tile padding == 0)
PASS    vp9: keyframe pixels decode     1073 / 1073   (reconstruction + loop filter ran; byte-exactness in browser)
PASS    vp9: inter sequence vs PyAV     1073 / 1073   (--all; whole inter corpus byte-exact, 4:2:0 + 4:4:4)
PASS    webm: container over corpus     2483 / 2483     (1850 VP9 + 633 VP8)
PASS    ai: disasm coverage (targets on boundary) 2 / 2   (293 scripts, 0 unknown opcodes)
PASS    ai: CHK links resolve in script table    674 / 674 (274 maps incl. main campaigns)
PASS    ai: CFG + semantics over corpus          293 / 293 (183 campaign, 1285 waves, 472 loops)
PASS    ai: no-op round-trip byte-identical         2 / 2   (15746 + 7787 instr + table + reloc)
PASS    ai: scaler is layout-safe (brutal)       293 / 293 (6719 value changes)
PASS    ai: runtime trace aligns to static       293 / 293 (18003 trace events)
PASS    ai: generator (standalone + merge)         8 / 8   (bot disasm-clean; stock kept byte-identical)
PASS    ai: build-order library compiles           3 / 3   (22 cards, 222 rows resolved, all compile + round-trip)
PASS    briefing: campaign MBRF timeline           3 / 3   (64 missions, 421 lines, 0 malformed, 23 speakers)
PASS    mission: unit-command classify             3 / 3   (64 missions, 2641 commands, Move/Patrol/Attack)
PASS    mission: full analyzer report              3 / 3   (64 missions, 37 hero flag, 17 heroes, JSON)
PASS    dat: units/weapons layout + edit round-trip 5 / 5   (4 anchors, Marine/SCV HP, subset, isolated edit)
PASS    grp: writer pixel round-trip               8 / 8   (real wirefram/cmdicons + synthetic edge cases)
PASS    dat: graphics chain (flingy/sprites/images) 4 / 4   (Marine->terran\marine.grp; 929 tbl names)
PASS    anim: HD inventory + reader coverage        4 / 4   (3510 anims; HD 1754 / HD2 1754 / SD 2; 0 anomalies)
PASS    dxt: DXT1/3/5 decode (synthetic)            5 / 5   (byte-identical to browser ddsToImageData)
PASS    player colours: teamcolor tint (synthetic)  4 / 4   (grayscale mask x 8 player colours)
PASS    dxt: DXT1/3/5 decode (synthetic)            5 / 5   (byte-exact vs browser ddsToImageData confirmed)
PASS    iscript: container + disasm coverage       3 / 3   (398 scripts, 1833 anims, 9763 opcodes, 0 desync)
PASS    iscript: assembler round-trip + relocation 4 / 4   (9763 opcodes + 398 headers + id-table byte-identical)
PASS    iscript: text assembler + merge            4 / 4   (text -> merge clean, stock byte-identical, intent kept)
PASS    mpq: write -> read-back byte-identical      7 / 7
PASS    mod: pack -> read-back (loose + mpq)        6 / 6

vp8-oracle.html:        PASS  633 / 633 keyframes byte-identical to libvpx
vp8-video-oracle.html:  PASS  58 / 58 clips, 1941 frames byte-identical to libvpx
vp9-oracle.html:        PASS  1073 / 1073 keyframes byte-identical to libvpx (1045 profile-1 4:4:4, 28 profile-0 4:2:0; 514 loop-filtered)
```

The video-oracle number is a representative sample (`--maxpix 120000`, 58
clips, 1941 frames) covering every inter mode and the delta-enabled loop
filter, not the whole 33 080-frame corpus — that is a long background run,
limited by the pure-Python decoder's speed, not by any known gap.

## The checks that need a browser

`vp8-oracle.html` compares the VP8 decoder against the browser's own libvpx
through WebCodecs. It is the strongest evidence in the project after the audio
comparison, and it is the reason stages (c)+(d) are called done rather than
written — all 633 keyframes, 490 of them loop-filtered:

```powershell
py tests/test_vp8_pixels.py --export      # writes tests/_vp8cmp/keyframes.bin
py tests/_serve.py                        # threaded static server on :8731
#   then open http://localhost:8731/tests/vp8-oracle.html
```

Three things worth knowing before trusting a result here:

* **Compare in I420, never RGB.** The first attempt compared RGB and reported
  a mean error of 2.9 with max 255, which looked like a serious bug. It was
  colour conversion and chroma interpolation. An RGB comparison measures three
  things at once and answers none of them.
* **One fetch, not two per file.** The export bundles every keyframe into one
  `keyframes.bin` and ships only a SHA-256 of the Python I420 in the manifest;
  the page decodes, hashes libvpx's output the same way, and compares digests.
  An earlier version fetched two files per frame and was crippled by the
  preview proxy dropping requests — 15 minutes and flaky instead of 3 seconds.
* **libvpx rounds an odd coded dimension up by one** (three files are 790x1159,
  reported as 790x1160) for 4:2:0 chroma. The page crops to the declared size
  before hashing; a disagreement larger than one pixel is treated as a real
  bug.

`vp8-video-oracle.html` is the same idea for inter frames: it feeds each clip's
frames to libvpx as an `EncodedVideoChunk` sequence and compares every output
frame's I420 hash to the Python decoder's, in order. Export with
`py tests/test_vp8_video.py --export --maxpix 40000` (or a larger budget /
longer run), then open it the same way. Inter frames inherit the keyframe's
dimensions — reading an inter frame's "size" gives the macroblock-padded height
and silently crops padding into the comparison; the decoder handles this, but
it is the kind of thing that reads as a decode bug when it is a harness bug.

`vp9-oracle.html` is the VP9 equivalent, for stage 3b (key-frame pixels):

```powershell
py tests/test_vp9_pixels.py --export      # writes tests/_vp9cmp/keyframes.bin
py tests/_serve.py                        # threaded static server on :8731
#   then open http://localhost:8731/tests/vp9-oracle.html
```

Four things worth knowing, most learned the hard way:

* **The whole key-frame corpus is compared, filter included** (1073/1073, 514
  loop-filtered). Reconstruction was first validated in isolation on the 559
  `loop_filter_level == 0` frames (`--lf0-only`) — for those libvpx's filter is
  a no-op — the same tactic that validated VP8 intra before its loop filter;
  the loop filter then closed the remaining 514.
* **Compare in the native buffer, never RGB.** The page reads `frame.format`
  and copies with no conversion: profile-1 4:4:4 comes back as **I444**,
  profile-0 4:2:0 as **NV12** (semi-planar — the UV plane is interleaved and
  must be split into U and V). A `copyTo({format:'RGBA'})` would add a lossy
  YUV→RGB step and destroy the byte comparison.
* **Do not trust `codedWidth`.** Chrome's decoded surface is padded to an
  alignment wider than the display size (a 224-wide frame reports 288); the
  image is top-left and the real per-plane `stride` from `copyTo` crops it
  correctly. Gating on `codedWidth == width` rejected every frame.
* **Portrait basenames collide across folders.** `nadfid00.webm` exists in
  `sd/portrait` (60x56 VP9), `hd2/portrait` (224x240 VP9) and `carbot/portrait`
  (448x480 VP8). The manifest ships the exact bytes it decoded, but a debug
  script that looks a name up by basename can grab the wrong file.

## Not covered here

The browser app's decoders are ported from the Python ones and were checked by
comparing SHA-256 of the output for a real input (Smacker clip, WAVE sector,
GRPI dump). There is no automated runner for that — it needs a browser. The
procedure, and the preview-pane caching trap that makes it awkward, are in
[../CLAUDE.md](../CLAUDE.md) §2.
