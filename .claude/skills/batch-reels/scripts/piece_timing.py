#!/usr/bin/env python3
"""Word-anchored timing for reusable overlay pieces, and the edit sheet the gate checks.

A piece is the set of overlays written once for one recorded take. Its HTML and JS never hold
seconds; they hold anchors that are resolved after the cut is known:

    {{W:B1:10}}            start of word 10 of take B1 on the edited timeline
    {{E:B1:25}}            end of that word
    {{W:B1:10-0.05}}       arithmetic is allowed: + - * / ( ) and numbers
    {{DUR}}  {{CTA_AT}}    the reel's duration and where the call to action starts

Composer use:
    from piece_timing import Timing
    t = Timing(words, duration, cta_at)
    html = t.fill(piece_html)          # replaces every {{...}}
    t.write_sheet(reel_dir, joins)     # edit.json for first_pass_gate.py --edit

The sheet records, for every element that had an id and a data-start anchored to a word, when
it starts and when its word is spoken, so the gate can fail an overlay that arrives late.

usage: piece_timing.py <words.json> <duration> <piece.html> [...]    prints the edit sheet
"""
import json, os, re, sys

TOKEN = re.compile(r'([WE]):([A-Za-z0-9_]+):(\d+)')
EXPR = re.compile(r'\{\{(.+?)\}\}')
TAG = re.compile(r'<[a-zA-Z][^<>]*>')


class Timing:
    def __init__(self, words, duration, cta_at=None):
        self.words = {(w['clip'], int(w['i'])): w for w in words}
        self.all = words
        self.duration = duration
        self.cta_at = duration if cta_at is None else cta_at
        self.overlays = []

    def word(self, clip, i):
        try: return self.words[(clip, int(i))]
        except KeyError: raise SystemExit(f'piece_timing: word {i} of {clip} is not in this cut (dropped or out of range)')

    def value(self, expr):
        e = TOKEN.sub(lambda m: str(self.word(m.group(2), m.group(3))['start' if m.group(1) == 'W' else 'end']), expr)
        e = e.replace('DUR', str(self.duration)).replace('CTA_AT', str(self.cta_at))
        if not re.fullmatch(r'[-+*/(). 0-9]+', e): raise SystemExit(f'piece_timing: cannot read "{expr}"')
        return float(eval(e, {'__builtins__': {}}, {}))

    def fill(self, text):
        """Resolve every {{...}} and remember the overlays that are anchored to a word."""
        for tag in TAG.findall(text):
            m_id = re.search(r'\bid="([^"]+)"', tag)
            m_start = re.search(r'data-start="\{\{(.+?)\}\}"', tag)
            if not (m_id and m_start): continue
            anchor = TOKEN.search(m_start.group(1))
            if not anchor: continue
            w = self.word(anchor.group(2), anchor.group(3))
            self.overlays.append({'id': m_id.group(1), 'word': w['text'],
                                  'anchor': w['start'] if anchor.group(1) == 'W' else w['end'],
                                  'start': round(self.value(m_start.group(1)), 3)})
        return EXPR.sub(lambda m: f'{self.value(m.group(1)):.3f}', text)

    def sheet(self, joins=()):
        return {'joins': list(joins), 'words': [{'text': w['text'], 'start': w['start'], 'end': w['end']} for w in self.all],
                'overlays': sorted(self.overlays, key=lambda o: o['start'])}

    def write_sheet(self, reel_dir, joins=()):
        path = os.path.join(reel_dir, 'edit.json')
        json.dump(self.sheet(joins), open(path, 'w'), indent=1)
        return path


def camera_scales(edl, min_punch=0.06, push=0.03, lo=1.0, hi=1.2, until=None):
    """Camera scale at every cut, chosen from what the viewer sees, not from a fixed list.

    Two takes are never framed the same, so a fixed list of scales gives cuts where the face
    changes size by 2 to 5 %: too small to look deliberate, big enough to read as a glitch.
    Here each cut changes the face's size on screen by at least min_punch (in or out,
    whichever keeps the scale inside lo..hi), using the face width assemble_takes.py measured
    for each take. `push` is the slow push the composer adds across each shot.
    Returns [[time, scale, apparent change]], starting with [0, lo, 1].
    """
    faces = {c: n.get('face_w') for c, n in edl.get('reframe', {}).items()}
    segs = [s for s in edl['segments'] if until is None or s['at'] < until]
    out, scale = [[0.0, lo, 1.0]], lo
    for prev, cur in zip(segs, segs[1:]):
        fa, fb = faces.get(prev['clip']) or 1.0, faces.get(cur['clip']) or 1.0
        seen = (scale + push) * fa                       # face size at the end of the outgoing shot
        step = 1 + min_punch + 0.02
        options = [seen * step / fb, seen / step / fb]   # punch in, pull back
        fits = [o for o in options if lo <= o <= hi]
        if fits: scale = min(fits, key=lambda o: abs(o - (lo + hi) / 2))
        else:    scale = min(max(min(options, key=lambda o: min(abs(o - lo), abs(o - hi))), lo), hi)
        out.append([cur['at'], round(scale, 4), round(scale * fb / seen, 4)])
    return out


if __name__ == '__main__':
    if len(sys.argv) < 4: print(__doc__); sys.exit(1)
    t = Timing(json.load(open(sys.argv[1])), float(sys.argv[2]))
    for p in sys.argv[3:]: t.fill(open(p, encoding='utf-8').read())
    print(json.dumps(t.sheet(), indent=1))
