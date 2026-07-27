"""StarCraft campaign AI toolkit (read-only analyzer).

Reads scripts\\aiscript.bin and scripts\\bwscript.bin - the AI script tables and
their opcode bytecode - and (later) links them to campaign missions via CHK
triggers. Same discipline as the asset side: the on-disk *structure* is measured
against the real files (see tools/ai/ai_bin.py), and every claim has a test.

Provenance note: unlike the media codecs, the AI opcode *semantics* have no
published normative spec - they come from community reverse-engineering
(BWAPI / BWScriptEmulator). So ai_opcodes.py is borrowed FORMAT DATA (attributed,
like the StormLib / RFC tables), not an independent derivation. The file
*structure* here, by contrast, is measured first-hand.
"""
