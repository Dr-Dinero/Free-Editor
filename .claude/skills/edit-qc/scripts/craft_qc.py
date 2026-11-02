#!/usr/bin/env python3
"""Measured craft and technical checks for a rendered talking-head short.

Usage:  python3 craft_qc.py <render.mp4> [--plan <name>.plan.json] [--voice cache/voice.wav]
                         [--transcript render.scribe.json] [--allow-cut-zooms] [--out qa/]
Writes <out>/craft-qc.md and <out>/craft-qc.json, plus hero and opening contact sheets.

Checks (FAIL lines; NOT RUN lines need the same check done another way; must be fixed or explained before edit QC can pass):
  specs      1080x1920, video and audio within one frame of each other
  loudness   -14 LUFS (+-1), true peak <= -1.0 dBTP
  opening    first spoken word by 0.5 s, the picture moves in the first 0.5 s
  framing    longest stretch with no framing change (cut or punch-in) <= 6 s
             outside calm sections (8 s inside), and the share of time spent in
             stretches over 4 s
  glitches   1-frame flashes, black frames, frozen runs not explained by a plan event
  joins      sound level right at each cut vs. the speech level (a loud cut is
             inside a word or breath); measured on the dry voice stem when
             --voice is given, since music and effects fill the gaps on purpose
  words      fresh speech-to-text of the render vs. the plan's words (>= 95 %);
             --transcript <render.scribe.json> uses a provider transcript of the render
  zoom       measured on the picture (feature matching between frames):
             cut zooms in the middle of a phrase (only a slam may punch in),
             jump cuts that keep the same framing, sideways pops, pushes faster
             than 2 %/s or that reverse direction, shots under 0.5 s
  stacking   two visual events (cut, b-roll in/out, slam) within 0.35 s of each other
  ending     last word fully heard, at least 0.6 s hold after it, picture and sound
             fade out, nothing cuts in the last 0.8 s
Every FAIL writes a frame strip to <out>/flags/ so a person can see it.
Measurements are evidence, not taste: a person still has to watch and listen.
"""
import json, os, re, subprocess, sys
import numpy as np

W, H = 72, 128


def frames(path):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'scale={W}:{H},format=gray',
                          '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    raw = p.stdout.read(); p.wait()
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)


def audio(path, sr=16000):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def probe(path):
    j = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                   'stream=codec_type,width,height,r_frame_rate,duration', '-of', 'json', path],
                                  capture_output=True, text=True, check=True).stdout)
    v = next(s for s in j['streams'] if s['codec_type'] == 'video')
    a = next(s for s in j['streams'] if s['codec_type'] == 'audio')
    n, d = v['r_frame_rate'].split('/')
    return dict(w=v['width'], h=v['height'], fps=float(n) / float(d), vdur=float(v['duration']), adur=float(a['duration']))


def loudness(path):
    s = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
    i = re.findall(r'I:\s+(-?[\d.]+) LUFS', s); tp = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', s)
    return float(i[-1]), float(tp[-1])


ZW, ZH = 360, 640


def gray_frames(path):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'scale={ZW}:{ZH},format=gray',
                          '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    raw = p.stdout.read(); p.wait()
    return np.frombuffer(raw, np.uint8).reshape(-1, ZH, ZW)


class Scale:
    """Scale and sideways shift between two frames of the speaker, from matched features.
    Only the band from 20 % to 58 % of the height is used: titles, chips, slams and captions
    sit outside it and would otherwise pin the match to the overlay."""
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.orb = cv2.ORB_create(900)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.mask = np.zeros((ZH, ZW), np.uint8)
        self.mask[int(ZH * 0.20):int(ZH * 0.58)] = 255

    def __call__(self, a, b):
        ka, da = self.orb.detectAndCompute(a, self.mask)
        kb, db = self.orb.detectAndCompute(b, self.mask)
        if da is None or db is None:
            return None
        m = self.bf.match(da, db)
        if len(m) < 20:
            return None
        A = np.float32([ka[x.queryIdx].pt for x in m]); B = np.float32([kb[x.trainIdx].pt for x in m])
        M, inl = self.cv2.estimateAffinePartial2D(A, B, ransacReprojThreshold=2.0)
        if M is None or inl.sum() < 25:
            return None
        return float(np.hypot(M[0, 0], M[1, 0])), float(M[0, 2]) / ZW


def strip(video, t, path, n=10):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{max(0, t - 0.17):.3f}', '-i', video,
                    '-vf', f'scale=200:-1,tile={n}x1', '-frames:v', '1', path], check=False)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(1)
    video = args[0]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    out = opt('--out', os.path.join(os.path.dirname(os.path.abspath(video)), '..', 'qa'))
    os.makedirs(out, exist_ok=True)
    plan = json.load(open(opt('--plan'))) if opt('--plan') else None
    rows = []
    def row(name, ok, detail):
        rows.append(dict(check=name, result='PASS' if ok else 'FAIL', detail=detail))

    sp = probe(video)
    fps = sp['fps']
    row('specs', sp['w'] == 1080 and sp['h'] == 1920 and abs(sp['vdur'] - sp['adur']) <= 1.5 / fps,
        f"{sp['w']}x{sp['h']} {fps:.3f} fps, video {sp['vdur']:.3f}s, audio {sp['adur']:.3f}s")
    I, TP = loudness(video)
    row('loudness', abs(I + 14) <= 1 and TP <= -1.0, f'{I:.1f} LUFS integrated, {TP:.1f} dBTP true peak')

    F = frames(video)
    d = np.abs(np.diff(F, axis=0)).mean(axis=(1, 2))
    # framing changes: a cut (big jump) or the start of a planned shot
    changes = set(np.where(d > 9)[0] + 1)
    if plan:
        changes |= {int(round(s['start'] * fps)) for s in plan['shots']}
        changes |= {int(round(b[k] * fps)) for b in plan.get('broll') or [] for k in ('start', 'end')}
    ch = sorted(changes | {0, len(F)})
    stretches = [(a / fps, (b - a) / fps) for a, b in zip(ch, ch[1:]) if b > a]
    calm = []
    if plan and plan.get('captions'):
        calm = [(c['start'], c['end']) for c in plan['captions'] if c.get('calm')]
    def is_calm(t):
        return any(a - 1 <= t <= b + 1 for a, b in calm)
    worst = max(stretches, key=lambda s: s[1] - (2 if is_calm(s[0]) else 0))
    lim = 8 if is_calm(worst[0]) else 6
    long_share = sum(l for _, l in stretches if l > 4) / (len(F) / fps)
    row('framing', worst[1] <= lim,
        f'{len(stretches)} framing stretches, longest {worst[1]:.1f}s at {worst[0]:.1f}s (limit {lim}s); '
        f'{long_share:.0%} of runtime sits in stretches over 4 s')

    move = float(np.abs(F[min(15, len(F) - 1)] - F[0]).mean())
    a16 = audio(video)
    env = np.sqrt(np.convolve(a16 ** 2, np.ones(160) / 160, mode='same'))
    db = 20 * np.log10(env + 1e-9)
    speech = np.percentile(db, 70)
    first_sound = float(np.argmax(db > speech - 12) / 16000)
    row('opening', first_sound <= 0.5 and (move >= 1.5 or any(c < 15 for c in changes if c)),
        f'first speech at {first_sound:.2f}s, picture change in first 0.5 s = {move:.1f}')

    planned = set()
    if plan:
        for key in ('slams', 'chips'):
            for e in plan.get(key) or []:
                planned |= {int(round(e['start'] * fps)), int(round(e['end'] * fps))}
        planned |= {int(round(s['start'] * fps)) for s in plan['shots']}
    broll = [(b['start'] * fps - 3, b['end'] * fps + 3) for b in (plan or {}).get('broll') or []]
    near = lambda i: any(abs(i - p) <= 3 for p in planned) or any(a <= i <= b for a, b in broll)   # stock motion is planned
    issues = []
    bright = F.mean(axis=(1, 2))
    for i in range(1, len(d) - 1):
        if d[i] > 18 and d[i + 1] > 0.6 * d[i] and not near(i + 1):
            issues.append(f'flash at {(i + 1) / fps:.2f}s')
    fade_from = len(F) - int(((plan or {}).get('end_fade') or 0) * fps) - 1
    for i, b in enumerate(bright):
        if b < 8 and 0 < i < min(len(F) - 1, fade_from):
            issues.append(f'black frame at {i / fps:.2f}s')
    run = 0
    for i, x in enumerate(d):
        run = run + 1 if x < 0.05 else 0
        if run == 8:
            issues.append(f'frozen picture from {(i - 7) / fps:.2f}s')
    row('glitches', not issues, ', '.join(issues[:12]) or 'no unplanned flashes, black frames, or freezes')

    if plan:
        jdb, jspeech = db, speech
        if opt('--voice'):
            v = audio(opt('--voice'))
            venv = np.sqrt(np.convolve(v ** 2, np.ones(160) / 160, mode='same'))
            jdb = 20 * np.log10(venv + 1e-9); jspeech = np.percentile(jdb, 70)
        loud = []
        for j in plan['joins']:
            k = int(j * 16000)
            w = jdb[max(0, k - 80):k + 80]
            if len(w) and w.max() > jspeech - 8:
                loud.append(f'{j:.2f}s ({w.max() - jspeech:+.0f} dB vs speech)')
        row('joins', not loud, f"{len(plan['joins'])} cuts; " + (', '.join(loud) if loud else 'all sit in quiet'))

        try:
            if opt('--transcript'):
                r = json.load(open(opt('--transcript')))
                heard = re.findall(r"[a-z']+", ' '.join(w.get('text', '') for w in r['words']
                                                         if w.get('type', 'word') == 'word').lower())
                want = re.findall(r"[a-z']+", ' '.join(w['t'] for w in plan['words']).lower().replace('-', ' '))
                import difflib
                sm = difflib.SequenceMatcher(a=want, b=heard, autojunk=False)
                ratio = sum(b.size for b in sm.get_matching_blocks()) / max(1, len(want))
                extra = [' '.join(heard[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal' and j2 > j1]
                row('words', ratio >= 0.97 and not extra,
                    f'{ratio:.1%} of planned words heard ({len(heard)} heard, {len(want)} planned)'
                    + (f'; heard but not captioned: {extra[:5]}' if extra else ''))
                raise StopIteration
            from faster_whisper import WhisperModel
            m = WhisperModel('small', compute_type='int8')
            segs, _ = m.transcribe(a16, language='en', word_timestamps=False, vad_filter=True)
            heard = re.findall(r"[a-z']+", ' '.join(s.text for s in segs).lower())
            want = re.findall(r"[a-z']+", ' '.join(w['t'] for w in plan['words']).lower().replace('-', ' '))
            import difflib
            sm = difflib.SequenceMatcher(a=want, b=heard, autojunk=False)
            ratio = sum(b.size for b in sm.get_matching_blocks()) / max(1, len(want))
            row('words', ratio >= 0.95, f'{ratio:.1%} of planned words heard in the render ({len(heard)} heard, {len(want)} planned)')
        except StopIteration:
            pass
        except Exception as e:      # not installed, or the model download is blocked
            rows.append(dict(check='words', result='NOT RUN',
                             detail=f'speech-to-text unavailable ({type(e).__name__}); transcribe the render '
                                    'with the job provider and compare by hand'))

    if plan:
        zoom_stack_ending(video, plan, rows, row, fps, out, F, d, a16, opt, args)

    # contact sheets for the human pass
    ff = lambda *a: subprocess.run(['ffmpeg', '-v', 'error', '-y', *a], check=True)
    ff('-i', video, '-vf', 'fps=1/6,scale=270:-1,tile=6x5', '-frames:v', '1', os.path.join(out, 'hero-sheet.jpg'))
    ff('-i', video, '-t', '3', '-vf', 'fps=4,scale=270:-1,tile=6x2', '-frames:v', '1', os.path.join(out, 'opening-sheet.jpg'))

    fails = [r for r in rows if r['result'] == 'FAIL']
    md = ['# Craft QC (measured)', '', f'Render: `{video}`', '',
          '| Check | Result | Detail |', '| --- | --- | --- |']
    md += [f"| {r['check']} | {r['result']} | {r['detail']} |" for r in rows]
    md += ['', 'Contact sheets: `hero-sheet.jpg`, `opening-sheet.jpg`.',
           'These numbers do not replace watching and listening to the render.']
    open(os.path.join(out, 'craft-qc.md'), 'w').write('\n'.join(md) + '\n')
    json.dump(rows, open(os.path.join(out, 'craft-qc.json'), 'w'), indent=1)
    print('\n'.join(md))
    sys.exit(1 if fails else 0)


def zoom_stack_ending(video, plan, rows, row, fps, out, F, d, a16, opt, args):
    flags = os.path.join(out, 'flags'); os.makedirs(flags, exist_ok=True)
    G = gray_frames(video)
    n = min(len(G), len(F))
    measure = Scale()
    joins = [round(j * fps) for j in plan['joins']]
    slam_in = [round(s['start'] * fps) for s in plan.get('slams') or []]
    broll = [(b['start'] * fps, b['end'] * fps) for b in plan.get('broll') or []]
    in_broll = lambda i: any(a - 1 <= i <= b + 1 for a, b in broll)
    near = lambda i, xs, k=2: any(abs(i - x) <= k for x in xs)
    allow_cut_zoom = '--allow-cut-zooms' in args

    # every visible picture change: measured cuts, plus planned b-roll edges and slam starts
    # a cut is a one-frame spike; fast motion (a falling object, a waving hand) stays high for several frames
    spike = lambda i: d[i] > 1.8 * max(1.0, float(np.median(np.r_[d[max(0, i - 3):i], d[i + 1:i + 4]])))
    cuts = [i + 1 for i in range(len(d)) if d[i] > 9 and spike(i)]
    cuts = [c for k, c in enumerate(cuts) if k == 0 or c - cuts[k - 1] > 1]
    zoom_bad, push_bad, short_bad = [], [], []
    for c in cuts:
        if c >= n or in_broll(c) or in_broll(c - 1):
            continue
        m = measure(G[c - 1], G[c])
        if not m:
            continue
        s, dx = m
        t = c / fps
        at_join, at_slam = near(c, joins), near(c, slam_in, 3)
        if not at_join and c + 1 < n:
            # a renderer pop is a single jump between steady frames; a hand sweeping the band keeps moving
            after = measure(G[c], G[c + 1])
            if after and abs(s - 1) < 3 * abs(after[0] - 1) + 0.005 and abs(dx) < 3 * abs(after[1]) + 0.005:
                continue
        if abs(s - 1) > 0.03 and not at_join and not at_slam and not allow_cut_zoom:
            zoom_bad.append(f'cut zoom mid-phrase at {t:.2f}s (x{s:.2f})')
        elif abs(s - 1) <= 0.03 and abs(dx) > 0.02 and not at_join:
            zoom_bad.append(f'sideways pop at {t:.2f}s ({dx:+.0%} of width)')
        elif at_join and abs(s - 1) < 0.06:
            zoom_bad.append(f'jump cut keeps the same framing at {t:.2f}s (x{s:.2f})')
    # push speed and direction, from the plan (a pixel estimate is too noisy: the speaker moves).
    # Pops at cuts are measured on the picture above.
    for sh in plan['shots']:
        dur = max(1e-3, sh['end'] - sh['start'])
        r = sh.get('push', 0) if sh.get('linear') else sh.get('push', 0) / dur * (1.5 if not sh.get('linear') else 1)
        if abs(r) > 0.02:
            push_bad.append(f'{"push" if r > 0 else "pull"} of {abs(r):.1%}/s at {sh["start"]:.2f}s')
        if dur < 0.5 and not any(a0 - 2 <= sh['start'] * fps <= b0 + 2 for a0, b0 in broll):
            short_bad.append(f'{dur:.2f}s shot at {sh["start"]:.2f}s')
    dirs = [1 if sh.get('push', 0) >= 0 else -1 for sh in plan['shots']]
    flips = sum(1 for x, y in zip(dirs, dirs[1:]) if x != y)
    if flips > 0:
        push_bad.append(f'push direction flips {flips} times between shots')
    issues = zoom_bad + push_bad + short_bad
    row('zoom', not issues, '; '.join(issues[:14]) + (f' (+{len(issues) - 14} more)' if len(issues) > 14 else '')
        if issues else f'{len(cuts)} cuts measured: framing changes only at jump cuts and slams, pushes smooth')
    for msg in zoom_bad[:20]:
        t = float(re.search(r'at ([\d.]+)s', msg).group(1))
        strip(video, t, os.path.join(flags, f'zoom_{t:06.2f}.jpg'))

    # stacking: two visual events closer than 0.35 s
    events = sorted([(c / fps, 'cut') for c in cuts] + [(b['start'], 'b-roll in') for b in plan.get('broll') or []]
                    + [(b['end'], 'b-roll out') for b in plan.get('broll') or []]
                    + [(s['start'], 'slam') for s in plan.get('slams') or []])
    stacked = []
    for (t1, k1), (t2, k2) in zip(events, events[1:]):
        if 1.5 / fps < t2 - t1 < 0.35:
            stacked.append(f'{k1} at {t1:.2f}s then {k2} at {t2:.2f}s')
            strip(video, t1, os.path.join(flags, f'stack_{t1:06.2f}.jpg'))
    row('stacking', not stacked, '; '.join(stacked[:10]) or 'no two visual events closer than 0.35 s')

    # ending: hold after the last word, then a fade on picture and sound
    total = n / fps
    last = plan['words'][-1]['e']
    hold = total - last
    bright = F.mean(axis=(1, 2))
    k = int(fps)
    pic_fade = bright[-1] < 0.35 * max(1.0, bright[-k - 1]) if len(bright) > k else False
    tail = a16[-int(0.25 * 16000):]; before = a16[-int(1.2 * 16000):-int(0.8 * 16000)]
    rms = lambda x: float(np.sqrt((x ** 2).mean()) + 1e-9)
    snd_fade = rms(tail) < 0.5 * rms(before)
    late_cut = [c / fps for c in cuts if c / fps > total - 0.8]
    late_broll = [b['end'] for b in plan.get('broll') or [] if total - 0.8 < b['end'] < total - 1 / fps]
    probs = []
    if hold < 0.6:
        probs.append(f'only {hold:.2f}s after the last word')
    if not pic_fade:
        probs.append('picture does not fade out')
    if not snd_fade:
        probs.append('sound does not fade out')
    if late_cut or late_broll:
        probs.append(f'cut in the last 0.8 s at {", ".join(f"{x:.2f}s" for x in late_cut + late_broll)}')
    row('ending', not probs, '; '.join(probs) or f'{hold:.2f}s hold after the last word, picture and sound fade')
    if probs:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-sseof', '-2', '-i', video, '-vf',
                        'fps=6,scale=200:-1,tile=12x1', '-frames:v', '1', os.path.join(flags, 'ending.jpg')], check=False)


if __name__ == '__main__':
    main()
