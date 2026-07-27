# Listfiles (MPQ name lists)

MPQ archives store files by a hash of their name, not the name itself, so a
"listfile" — a plain-text list of candidate paths — is what lets a reader
enumerate an archive. (CASC needs no external listfile: the SC:R root already
carries every path. This is an MPQ-only concern.)

## What is here

`blizzard-listfiles.zip` — a large collection of community listfiles for many
Blizzard games (StarCraft, Diablo I/II/III, Warcraft II/III, World of Warcraft
1x–8x, and a couple of others). Kept for possible future tooling on those
games; **the SC asset browser only decodes StarCraft formats, so the non-SC
lists are of no use to it** — they are stored here as raw name lists, nothing
more. Total ~275 MB uncompressed, hence kept zipped.

`Starcraft_BW.txt`, `Starcraft_II.txt` — extracted for direct use (the app's
"Atverti failus" button loads a `.txt` listfile at runtime).

## How it relates to the app's built-in listfile

`sc-asset-browser.html` embeds a StarCraft listfile so MPQs open with no extra
step. That embedded list is the **union** of the toolkit's original list and
`Starcraft_BW.txt`. Measured against V's Brood War 1.16.1 install:

| listfile | files it names in that archive |
|---|---|
| toolkit original | 5412 |
| `Starcraft_BW.txt` alone | 5415 |
| **union (now embedded)** | **5665** |

So merging the community list added **253** browsable files the original
missed (mostly audio and a few `portrait\static` / `portrait\ukhadchunk`
`.smk`), while the original contributed ~250 the community list lacked. Neither
is a superset of the other; the union is.

Most of `Starcraft_BW.txt`'s 10 510 names do **not** resolve in this specific
install — they cover other versions/regions — which is fine: the app only ever
lists names that actually hash to an entry in the open archive.

## Provenance

Community-maintained listfiles (Zezula's MPQ tooling ecosystem and similar).
They are name lists only — no game data — and are used exactly as an MPQ
listfile is meant to be used.
