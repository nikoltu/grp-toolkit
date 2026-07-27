#!/usr/bin/env python3
"""AISI export: an AI script's decoded instruction stream as neutral JSON.

Mirrors the asset side's philosophy of a UI-free intermediate format (like the
GRPI / ARGB dumps): the disassembly with raw opcode values, addresses and
resolved argument meanings, and NOTHING interpreted beyond that. Higher-level
views (CFG, semantic timeline) are built from this, not baked into it.

    py ai_export.py <BW_install_dir> <SCRIPT_ID>     # one script -> stdout
    py ai_export.py <BW_install_dir> --all           # every script -> summary
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import ai_disasm
from ai_opcodes import OPCODES

# unit/tech/upgrade arg types resolve their value against stat_txt.tbl via the
# .dat name indices; for the read-only slice we keep the raw value and just tag
# the semantic type so downstream can resolve it.
_NAMEABLE = {'unit', 'building', 'military', 'gg_military', 'ag_military',
             'ga_military', 'aa_military', 'upgrade', 'technology'}


def script_name(entry, tbl=None):
    """The editor-visible name via stat_txt.tbl (string_id is 1-based)."""
    if tbl is None or not entry.string_id:
        return None
    return tbl.text(entry.string_id - 1)


def instruction_json(ins, data):
    args = []
    for a in ins.args:
        d = {'type': a.type}
        if a.type == 'address':
            d['target'] = a.value
        elif a.type == 'string':
            end = data.find(b'\x00', a.value)
            d['value'] = data[a.value:end].decode('latin1')
        else:
            d['value'] = a.value
            if a.type in _NAMEABLE:
                d['semantic'] = a.type
        args.append(d)
    return {'address': ins.address, 'opcode': ins.opcode, 'name': ins.name,
            'control_flow': ins.control_flow, 'args': args, 'size': ins.size}


def script_to_aisi(ai_file, entry, tbl=None):
    """AISI dict for one script: table metadata + reachable instructions
    (control-flow order-independent; sorted by address)."""
    ok, info = ai_disasm.trace_reachable(ai_file.data, entry.offset,
                                         ai_file.table_offset)
    starts = sorted(info['instr_starts'])
    ins_list = [ai_disasm.decode_one(ai_file.data, p) for p in starts]
    return {
        'script_id': entry.fourcc,
        'source': ai_file.source,
        'entry_offset': entry.offset,
        'string_id': entry.string_id,
        'name': script_name(entry, tbl),
        'flags': {
            'raw': entry.flags,
            'requires_location': entry.requires_location,
            'broodwar_only': entry.broodwar_only,
            'staredit_hidden': entry.staredit_hidden,
        },
        'decode_ok': ok,
        'decode_error': None if ok else info.get('error'),
        'instruction_count': len(ins_list),
        'instructions': [instruction_json(i, ai_file.data) for i in ins_list],
    }


def _load(base):
    import mpq
    import ai_bin
    import tbl as tblmod
    files = ai_bin.load_from_chain(mpq.MpqChain(base))
    try:
        tbl = tblmod.load(mpq.MpqChain(base).read('rez\\stat_txt.tbl'))
    except Exception:
        tbl = None
    return files, tbl


if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    target = sys.argv[2] if len(sys.argv) > 2 else '--all'
    files, tbl = _load(base)
    if target == '--all':
        for source, f in sorted(files.items()):
            used = [e for e in f.entries if e.used]
            names = sum(1 for e in used if script_name(e, tbl))
            print('%-14s %d scripts, %d named' % (source, len(used), names))
            for e in used[:3]:
                a = script_to_aisi(f, e, tbl)
                print('   %-6s %-32s %d instr flags=0x%x' %
                      (a['script_id'], a['name'], a['instruction_count'],
                       a['flags']['raw']))
    else:
        for source, f in files.items():
            e = f.by_id().get(target)
            if e:
                print(json.dumps(script_to_aisi(f, e, tbl), indent=2))
                break
        else:
            print('script %r not found' % target, file=sys.stderr)
            sys.exit(1)
