#!/usr/bin/env python3
"""Assemble one reel's base video from recorded takes (hook, body, call to action, ...).

usage: assemble_takes.py <cut.json> <out dir> --takes <dir> --transcripts <dir>
                         [--preset presets/x.json] [--tail 0.8] [--no-reframe]

cut.json   {"pieces": [{"clip": "H3", "from": 0, "to": 10, "drop": [4, 5],
                        "in": 1.20, "out": 6.85, "filters": "highpass=f=110"}],
            "ending": "live"}
           from/to are word indexes in the take's transcript, inclusive. drop removes words.
           in/out (seconds in the take) override a cut point. filters is extra audio filtering
           for that take. ending is "live" (default) or "hold".
takes      <clip>.mp4 (or .mov/.mkv/.webm) per take, any size or aspect.
transcripts  <clip>.json with {"words": [{"text", "start", "end"}]}.

Writes base.mp4, edl.json, words.json (the words on the edited timeline) and expect.txt (the
words the render must say, for the first-pass gate's --expect).

What this gets right that a cut at the transcript's word times does not:
- A cut never lands at the transcript's word end. Word times end early on soft endings ("s",
  "t", numbers), so each cut walks out from the word until the voice has actually stopped.
- A cut that has no silence to land in is reported as tight instead of shipped quietly.
- The ending is real footage after the last word, not one frame held still.
- The picture is cropped to the frame, never squeezed, and the crop follows the face so the
  eye line sits where the preset says.
"""
import argparse, json, math, os, subprocess, sys

MAXGAP, KEEP_AFTER, KEEP_BEFORE = 0.40, 0.14, 0.10   # pauses longer than MAXGAP are tightened
PAD_AFTER, PAD_BEFORE = 0.05, 0.04                   # air kept past the voice at a piece edge
QUIET_RUN = 5                                        # 50 ms below the threshold counts as silence
EXTS = ('.mp4', '.mov', '.mkv', '.webm', '.m4v')


def die(msg):
    print(f'assemble_takes: {msg}', file=sys.stderr); sys.exit(2)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


class Take:
    """One recorded take: its file, size, words and a 10 ms loudness envelope in dB."""

    def __init__(self, clip, takes, transcripts):
        self.clip = clip
        self.path = next((os.path.join(takes, clip + e) for e in EXTS if os.path.exists(os.path.join(takes, clip + e))), None)
        if not self.path: die(f'no take file for {clip} in {takes}')
        tx = os.path.join(transcripts, clip + '.json')
        if not os.path.exists(tx): die(f'no transcript for {clip} in {transcripts}')
        self.words = json.load(open(tx, encoding='utf-8'))['words']
        info = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                               'stream=width,height:format=duration', '-of', 'json', self.path], text=True).stdout or '{}')
        st = (info.get('streams') or [{}])[0]
        self.w, self.h = int(st.get('width', 0)), int(st.get('height', 0))
        self.dur = float(info.get('format', {}).get('duration', 0))
        if not self.w or not self.dur: die(f'cannot read {self.path}')
        raw = run(['ffmpeg', '-nostdin', '-v', 'error', '-i', self.path, '-ac', '1', '-ar', '16000', '-f', 's16le', '-']).stdout
        import array
        s = array.array('h'); s.frombytes(raw[:len(raw) // 2 * 2])
        self.env = []
        for i in range(0, len(s) - 160, 160):
            rms = math.sqrt(sum(x * x for x in s[i:i + 160]) / 160)
            self.env.append(20 * math.log10(max(rms, 1.0) / 32768))
        if not self.env: die(f'{clip} has no audio')
        ordered = sorted(self.env)
        self.floor = ordered[int(len(ordered) * 0.05)]
        self.speech = ordered[int(len(ordered) * 0.75)]
        # Silence is close to the room floor and well under the voice; soft consonants are not.
        self.thr = min(self.floor + 6.0, self.speech - 12.0) if self.speech - self.floor > 14 else self.floor + 3.0
        self._lufs = None
        self.crop = None

    def _idx(self, t):
        return max(0, min(len(self.env) - 1, int(round(t * 100))))

    def speech_end(self, t, limit):
        """First moment at or after t where the voice has stopped, or None if it never does before limit."""
        i, last = self._idx(t), self._idx(limit)
        run_len = 0
        for k in range(i, last + 1):
            run_len = run_len + 1 if self.env[k] < self.thr else 0
            if run_len >= QUIET_RUN: return (k - run_len + 1) / 100
        return None

    def speech_start(self, t, limit):
        """Last moment at or before t where the voice has not started yet, or None."""
        i, first = self._idx(t), self._idx(limit)
        run_len = 0
        for k in range(i, first - 1, -1):
            run_len = run_len + 1 if self.env[k] < self.thr else 0
            if run_len >= QUIET_RUN: return (k + run_len) / 100
        return None

    def quietest(self, a, b):
        i0, i1 = self._idx(a), self._idx(b)
        if i1 <= i0: return (a + b) / 2
        k = min(range(i0, i1 + 1), key=lambda j: self.env[j])
        return k / 100 + 0.005

    def cut_after(self, k, pad):
        """Where to cut after word k: past the end of the voice, before the next word in the take."""
        w = self.words[k]
        nxt = next((x for x in self.words[k + 1:] if x.get('start') is not None), None)
        limit = min(self.dur, nxt['start'] - 0.02 if nxt else w['end'] + 0.6)
        limit = max(limit, w['end'])
        e = self.speech_end(w['end'], limit)
        if e is None: return self.quietest(w['end'], limit), True
        return min(e + pad, limit), False

    def cut_before(self, k, pad):
        w = self.words[k]
        prev = next((x for x in reversed(self.words[:k]) if x.get('end') is not None), None)
        limit = max(0.0, prev['end'] + 0.02 if prev else w['start'] - 0.4)
        limit = min(limit, w['start'])
        s = self.speech_start(w['start'], limit)
        if s is None: return self.quietest(limit, w['start']), True
        return max(s - pad, limit), False

    def lufs(self):
        if self._lufs is None:
            r = run(['ffmpeg', '-nostdin', '-i', self.path, '-af', 'ebur128', '-f', 'null', '-'], text=True).stderr
            try: self._lufs = float(r.split('Integrated loudness:')[1].split('I:')[1].split('LUFS')[0])
            except (IndexError, ValueError): self._lufs = -23.0
        return self._lufs


def plan(cut, takes):
    """Returns segments, words on the edited timeline, the spoken duration and the tight cuts."""
    segs, words, tight, t = [], [], [], 0.0
    for p in cut['pieces']:
        T = takes[p['clip']]
        drop = set(p.get('drop', []))
        keep = [k for k, x in enumerate(T.words) if p['from'] <= k <= p['to'] and x.get('start') is not None and k not in drop]
        if not keep: die(f"{p['clip']}: no words between {p['from']} and {p['to']}")
        start, t0 = (p['in'], False) if 'in' in p else T.cut_before(keep[0], PAD_BEFORE)
        end, t1 = (p['out'], False) if 'out' in p else T.cut_after(keep[-1], PAD_AFTER)
        if t0: tight.append({'clip': p['clip'], 'word': keep[0], 'side': 'in'})
        if t1: tight.append({'clip': p['clip'], 'word': keep[-1], 'side': 'out'})
        cuts = [start]
        for a, b in zip(keep, keep[1:]):
            wa, wb = T.words[a], T.words[b]
            if wb['start'] - wa['end'] <= MAXGAP and b == a + 1: continue
            left, ta = T.cut_after(a, KEEP_AFTER)
            right, tb = T.cut_before(b, KEEP_BEFORE)
            if right - left < 0.08: continue          # nothing worth removing once the voice is protected
            if ta: tight.append({'clip': p['clip'], 'word': a, 'side': 'out'})
            if tb: tight.append({'clip': p['clip'], 'word': b, 'side': 'in'})
            cuts += [left, right]
        cuts.append(end)
        for s0, s1 in zip(cuts[::2], cuts[1::2]):
            segs.append({'clip': p['clip'], 'in': round(s0, 3), 'out': round(s1, 3), 'at': round(t, 3)})
            for k in keep:
                x = T.words[k]
                mid = (x['start'] + x['end']) / 2
                if s0 <= mid < s1:
                    words.append({'text': x['text'], 'start': round(max(x['start'], s0) - s0 + t, 3),
                                  'end': round(min(x['end'], s1) - s0 + t, 3), 'clip': p['clip'], 'i': k})
            t += s1 - s0
    return segs, words, round(t, 3), tight


def reframe(T, segs, out_w, out_h, band, enabled):
    """Pick one 9:16 crop per take. Centred when no face tool is present; otherwise the crop follows
    the face across and zooms in just enough to bring the eye line down into the preset's band."""
    aspect = out_w / out_h
    ch = min(T.h, T.w / aspect); cw = ch * aspect
    x0, y0 = (T.w - cw) / 2, (T.h - ch) / 2
    note = {'method': 'centre'}
    if enabled:
        try:
            import cv2, numpy as np
        except ImportError:
            cv2 = None
            note['why'] = 'OpenCV not installed (pip install -r requirements.txt)'
        if cv2 is not None:
            used = [s for s in segs if s['clip'] == T.clip]
            a, b = min(s['in'] for s in used), max(s['out'] for s in used)
            sw = 480; sh = int(round(T.h * sw / T.w / 2) * 2)
            casc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            boxes = []
            for j in range(9):
                ts = a + (b - a) * (j + 0.5) / 9
                raw = run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{ts:.3f}', '-i', T.path, '-frames:v', '1',
                           '-vf', f'scale={sw}:{sh}', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']).stdout
                if len(raw) < sw * sh: continue
                g = np.frombuffer(raw[:sw * sh], np.uint8).reshape(sh, sw)
                found = casc.detectMultiScale(g, 1.1, 5, minSize=(sw // 12, sw // 12))
                if len(found): boxes.append(max(found, key=lambda f: f[2] * f[3]))
            if len(boxes) >= 3:
                k = T.w / sw
                fx, fy, fw, fh = [float(np.median([bx[i] for bx in boxes])) * k for i in range(4)]
                eye, cx = fy + 0.40 * fh, fx + fw / 2
                lo, hi = band
                target = (lo + hi) / 2
                before = (eye - y0) / ch
                if before > hi:                      # too much headroom: crop in from the top
                    ch2 = min(ch, (T.h - eye) / (1 - target), eye / target)
                    ch2 = max(ch2, ch / 1.35)        # never zoom more than 35 %
                    ch = ch2; cw = ch * aspect
                    y0 = min(max(eye - target * ch, 0), T.h - ch)
                x0 = min(max(cx - cw / 2, 0), T.w - cw)
                note = {'method': 'face', 'eye_line_before': round(before, 3), 'eye_line': round((eye - y0) / ch, 3),
                        'zoom': round(min(T.h, T.w / aspect) / ch, 3), 'face_w': round(fw / cw, 4)}
                if before < lo: note['warning'] = 'face sits high in the take; cropping cannot add headroom'
                if ch < out_h * 0.75: note['warning'] = f'crop is {int(ch)} px tall, upscaled to {out_h}'
            else:
                note['why'] = 'no face found'
    ev = lambda v: int(v // 2 * 2)
    T.crop = (ev(cw), ev(ch), ev(x0), ev(y0))
    note['crop'] = list(T.crop)
    return note


def render(segs, takes, cut, out_dir, spoken, tail, fmt, lufs):
    out_w, out_h, fps = fmt
    last = segs[-1]; TL = takes[last['clip']]
    live = 0.0
    if cut.get('ending', 'live') == 'live':
        live = max(0.0, min(tail, TL.dur - last['out'] - 0.05))
    held = round(tail - live, 3)
    ins, fc = [], []
    for i, s in enumerate(segs):
        T = takes[s['clip']]
        d = s['out'] - s['in']
        dv = d + (live if i == len(segs) - 1 else 0)
        ins += ['-ss', f"{s['in']:.3f}", '-t', f'{dv + 0.1:.3f}', '-i', T.path]
        cw, ch, x0, y0 = T.crop
        fo = 0.06 if i == len(segs) - 1 else 0.015
        piece = next(p for p in cut['pieces'] if p['clip'] == s['clip'])
        extra = (',' + piece['filters']) if piece.get('filters') else ''
        gain = max(-20.0, min(30.0, -16.0 - T.lufs()))
        fc.append(f'[{i}:v]crop={cw}:{ch}:{x0}:{y0},scale={out_w}:{out_h}:flags=lanczos,setsar=1,fps={fps},'
                  f'trim=duration={dv:.3f},setpts=PTS-STARTPTS[v{i}]')
        fc.append(f'[{i}:a]aresample=48000,atrim=duration={d:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.012,'
                  f'afade=t=out:st={max(0, d - fo):.3f}:d={fo}{extra},volume={gain:.1f}dB[a{i}]')
    fc.append(''.join(f'[v{i}]' for i in range(len(segs))) + f'concat=n={len(segs)}:v=1:a=0[v1]')
    fc.append(''.join(f'[a{i}]' for i in range(len(segs))) + f'concat=n={len(segs)}:v=0:a=1[a1]')
    fc.append(f'[v1]tpad=stop_mode=clone:stop_duration={held}[v]' if held > 0 else '[v1]null[v]')
    fc.append(f'[a1]apad=whole_dur={spoken + tail:.3f},highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=80,'
              f'loudnorm=I={lufs}:TP=-1.5:LRA=7,aresample=48000[a]')
    base = os.path.join(out_dir, 'base.mp4')
    r = run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *ins, '-filter_complex', ';'.join(fc), '-map', '[v]', '-map', '[a]',
             '-t', f'{spoken + tail:.3f}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-movflags', '+faststart', base], text=True)
    if r.returncode != 0: die(f'ffmpeg failed:\n{r.stderr[-1500:]}')
    return held


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cut'); ap.add_argument('out')
    ap.add_argument('--takes', required=True); ap.add_argument('--transcripts', required=True)
    ap.add_argument('--preset'); ap.add_argument('--tail', type=float, default=0.8)
    ap.add_argument('--no-reframe', action='store_true')
    ap.add_argument('--plan-only', action='store_true', help='write edl.json and words.json, render nothing')
    a = ap.parse_args()
    cut = json.load(open(a.cut, encoding='utf-8'))
    preset = json.load(open(a.preset, encoding='utf-8')) if a.preset else {}
    f = preset.get('format', {})
    fps = f.get('fps', 30); fps = 30 if isinstance(fps, list) and 30 in fps else (fps[0] if isinstance(fps, list) else fps)
    fmt = (f.get('width', 1080), f.get('height', 1920), fps)
    band = preset.get('framing', {}).get('eye_line', [0.24, 0.42])
    lufs = preset.get('audio', {}).get('lufs', -14)
    os.makedirs(a.out, exist_ok=True)

    takes = {}
    for p in cut['pieces']:
        if p['clip'] not in takes: takes[p['clip']] = Take(p['clip'], a.takes, a.transcripts)
    segs, words, spoken, tight = plan(cut, takes)
    frames = {c: reframe(T, segs, fmt[0], fmt[1], band, not a.no_reframe) for c, T in takes.items()}
    held = 0.0
    if not a.plan_only:
        held = render(segs, takes, cut, a.out, spoken, a.tail, fmt, lufs)
    edl = {'segments': segs, 'spoken': spoken, 'duration': round(spoken + a.tail, 3), 'tail': a.tail,
           'held_frame_s': held, 'tight_cuts': tight, 'reframe': frames,
           'joins': [s['at'] for s in segs[1:]]}
    json.dump(edl, open(os.path.join(a.out, 'edl.json'), 'w'), indent=1)
    json.dump(words, open(os.path.join(a.out, 'words.json'), 'w'))
    open(os.path.join(a.out, 'expect.txt'), 'w', encoding='utf-8').write(' '.join(w['text'] for w in words) + '\n')
    print(f"duration {edl['duration']}  segments {len(segs)}  words {len(words)}")
    for c, n in frames.items():
        if n.get('warning') or n.get('why'): print(f"  framing {c}: {n.get('warning') or n.get('why')}")
    for t in tight:
        w = takes[t['clip']].words[t['word']]
        print(f"  TIGHT CUT {t['clip']} word {t['word']} \"{w['text']}\" ({t['side']}): no silence to cut in. "
              f"Listen to it, or set \"{t['side']}\" in the cut, or use another take.")
    if held > 0.1: print(f'  ENDING holds one frame for {held}s: the take ends {held}s too soon for a live ending.')
    sys.exit(3 if (tight or held > 0.1) and not a.plan_only and os.environ.get('ASSEMBLE_STRICT') else 0)


if __name__ == '__main__':
    main()
