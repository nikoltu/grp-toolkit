#!/usr/bin/env python3
"""Mission-briefing analyzer - turn a CHK's MBRF section into an ordered dialogue
timeline: who speaks, which portrait, what line, which .wav, for how long, and
when the portrait goes speaking -> idle.

The briefing is a SEQUENCE of actions (chk.py parses MBRF into chk.briefings in
order). This walks them maintaining two things: a CLOCK (advanced by the `time`
of Wait/PlayWAV/Transmission) and the CURRENT PORTRAIT (set by ShowPortrait,
cleared by HidePortrait). A Transmission is a spoken line - it is attributed to
the current portrait and marks that portrait "speaking" for `dur_ms`, then idle.

Output is a normalized structure the HD/engine port can DIFF its own briefing
playback against (same wav at the same t_ms, same portrait, same duration) - a
byte-derived oracle for debugging the campaign briefing code.
"""
import chk as chk_mod


def _portrait_state_spans(events):
    """From the timeline, derive (portrait_unit, show_ms, speak spans, hide_ms):
    when each portrait appears, the [start,end] of each spoken line, and when it
    hides - i.e. the speaking<->idle transitions."""
    spans = []
    cur = None
    for e in events:
        if e['action'] == 'ShowPortrait':
            cur = {'portrait_unit': e.get('portrait_unit'),
                   'portrait_name': e.get('portrait_name'),
                   'show_ms': e['t_ms'], 'speaking': [], 'hide_ms': None}
            spans.append(cur)
        elif e['action'] == 'Transmission' and cur is not None:
            cur['speaking'].append((e['t_ms'], e['end_ms']))
        elif e['action'] == 'HidePortrait' and cur is not None:
            cur['hide_ms'] = e['t_ms']
            cur = None
    return spans


def analyze(chk, unit_name=None):
    """Return a list (one per MBRF trigger) of {events, n_lines, total_ms,
    speakers, portraits}. `unit_name`: optional callable id -> str."""
    result = []
    for br in chk.briefings:
        clock = 0
        current_portrait = None
        events = []
        for act in br.actions:
            name = chk_mod.BRIEFING_ACTIONS.get(act.action_id, 'act%d' % act.action_id)
            ev = {'t_ms': clock, 'action': name, 'action_id': act.action_id}
            if act.action_id == 5:                      # ShowPortrait
                current_portrait = act.unit_type
                ev['portrait_unit'] = act.unit_type
                if unit_name:
                    ev['portrait_name'] = unit_name(act.unit_type)
            elif act.action_id == 6:                    # HidePortrait
                ev['portrait_unit'] = current_portrait
                current_portrait = None
            elif act.action_id == 8:                    # Transmission (spoken line)
                ev['speaker_unit'] = current_portrait
                if unit_name and current_portrait is not None:
                    ev['speaker_name'] = unit_name(current_portrait)
                ev['text'] = chk.string(act.string)
                ev['wav'] = chk.string(act.wav)
                ev['dur_ms'] = act.time
                ev['end_ms'] = clock + act.time
            elif act.action_id in (3, 4):               # TextMessage / Objectives
                ev['text'] = chk.string(act.string)
                if act.time:
                    ev['dur_ms'] = act.time
            elif act.action_id == 2:                    # PlayWAV
                ev['wav'] = chk.string(act.wav)
                ev['dur_ms'] = act.time
            elif act.action_id == 1:                    # Wait
                ev['dur_ms'] = act.time
            events.append(ev)
            if act.action_id in chk_mod.BRIEFING_TIMED:
                clock += act.time

        lines = [e for e in events if e['action'] == 'Transmission']
        speakers = {}
        for e in lines:
            key = e.get('speaker_name') or ('unit %s' % e.get('speaker_unit'))
            speakers[key] = speakers.get(key, 0) + 1
        result.append({'events': events, 'n_lines': len(lines),
                       'total_ms': clock, 'speakers': speakers,
                       'portraits': _portrait_state_spans(events)})
    return result


def _fmt_ms(ms):
    return '%d:%05.2f' % (ms // 60000, (ms % 60000) / 1000.0)


if __name__ == '__main__':
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import mpq
    import tbl
    base = sys.argv[1] if len(sys.argv) > 1 \
        else r'C:\Git\Starcraft BroodWar  v1.1.61'
    mission = sys.argv[2] if len(sys.argv) > 2 \
        else 'campaign\\zerg\\zerg01\\staredit\\scenario.chk'
    ch = mpq.MpqChain(base)
    stat = tbl.load(ch.read('rez\\stat_txt.tbl'))

    def uname(uid):
        # unit name = stat_txt.tbl[uid+1] (1-based) == stat.text(uid) (0-based)
        return stat.text(uid) or ('unit %d' % uid)

    chk = chk_mod.parse(ch.read(mission))
    for bi, b in enumerate(analyze(chk, uname)):
        print('== briefing %d: %d lines, %s total, speakers=%s =='
              % (bi, b['n_lines'], _fmt_ms(b['total_ms']), b['speakers']))
        for e in b['events']:
            extra = ''
            if e['action'] == 'Transmission':
                extra = ' [%s] %r  wav=%s' % (e.get('speaker_name', '?'),
                                              e['text'][:48], e['wav'].split('\\')[-1])
            elif e['action'] == 'ShowPortrait':
                extra = ' portrait=%s' % e.get('portrait_name')
            elif e.get('text'):
                extra = ' %r' % e['text'][:48]
            print('  %s  %-22s%s' % (_fmt_ms(e['t_ms']), e['action'], extra))
