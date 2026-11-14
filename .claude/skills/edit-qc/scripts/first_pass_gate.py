#!/usr/bin/env python3
"""First-pass gate: measured checks on ANY rendered video, whichever tool made it.

    python3 first_pass_gate.py <render.mp4> [--preset presets/<name>.json] [--edit edit.json]
            [--expect script.txt] [--transcript words.json] [--composition index.html]
            [--out qa/] [--no-asr] [--json]

Needs only the render. Everything else sharpens a check:
  --preset       look and delivery rules for this client or style (see presets/README.md)
  --edit         neutral edit sheet {joins:[s], words:[{text,start,end}], overlays:[{id,anchor,start}]}
  --expect       the words that should be heard, as plain text
  --transcript   word timings of the render from any provider ([{text,start,end}] or {words:[...]})
  --composition  HyperFrames index.html to lint for colours and grading

Each check exists because a real review note asked for it:
  specs      size and frame rate match the preset; picture and sound the same length
  loudness   integrated loudness on target, true peak under the ceiling
  opening    speech starts at once; no black or dead first half second
  glitches   one-frame flashes and black frames
  freeze     a frozen face ("still frame before the end card")
  cuts       every cut measured on the picture: a small zoom or sideways hop reads as a glitch;
             a punch-in must be big enough to look deliberate
  cut-audio  sound right at each cut: a loud cut is inside a word ("297", "ads" clipped)
  words      speech-to-text of the render: every expected word heard, no weak word beside a cut
  tone       each stretch between cuts keeps the same bass-to-voice balance ("bassy splice")
  headroom   the face sits where the preset says, on every shot ("too much headroom")
  overlays   each overlay arrives with its word, never late (needs --edit)
  ending     last word finished, a hold after it, sound does not stop dead
  look       composition colours stay inside the preset palette, no grade on footage

FAIL blocks delivery. WARN must be looked at. NOT RUN means do that check another way.
Every FAIL and WARN writes a frame strip to <out>/flags/. Numbers are evidence, not taste.
"""
import difflib, json, os, re, subprocess, sys
import numpy as np

ZW, ZH = 360, 640
DEFAULT = {
    "name": "default",
    "format": {"width": 1080, "height": 1920, "fps": [24, 25, 30, 60]},
    "audio": {"lufs": -14, "lufs_tolerance": 1.0, "true_peak_max": -1.0},
    "cuts": {"allow_punch": True, "min_punch": 0.05, "max_drift": 0.015, "max_hop": 0.012},
    "framing": {"eye_line": [0.24, 0.42], "min_face_width": 0.16, "max_off_centre": 0.14},
    "overlays": {"lead_max": 0.25, "late_max": 0.06},
    "ending": {"hold_min": 0.5, "hold_max": 1.6, "mode": "hold"},
    "look": {"palette": [], "banned_hues": [], "allow_grade": False},
}


def merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def probe(path):
    j = json.loads(run(['ffprobe', '-v', 'error', '-show_entries',
                        'stream=codec_type,width,height,r_frame_rate,duration', '-of', 'json', path], text=True).stdout)
    v = next(s for s in j['streams'] if s['codec_type'] == 'video')
    a = next((s for s in j['streams'] if s['codec_type'] == 'audio'), None)
    n, d = v['r_frame_rate'].split('/')
    return dict(w=v['width'], h=v['height'], fps=float(n) / float(d), vdur=float(v.get('duration') or 0),
                adur=float(a['duration']) if a and a.get('duration') else None)


def gray_frames(path, fps):
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vf', f'fps={fps},scale={ZW}:{ZH},format=gray',
                          '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    raw = p.stdout.read(); p.wait()
    return np.frombuffer(raw, np.uint8).reshape(-1, ZH, ZW)


def audio(path, sr=16000):
    raw = run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']).stdout
    return np.frombuffer(raw, np.float32)


def loudness(path):
    s = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-'], text=True).stderr
    i = re.findall(r'I:\s+(-?[\d.]+) LUFS', s); tp = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', s)
    return (float(i[-1]), float(tp[-1])) if i and tp else (None, None)


def envelope(x, win=160):
    return 20 * np.log10(np.sqrt(np.convolve(x ** 2, np.ones(win) / win, mode='same')) + 1e-9)


def band(x, lo, hi, sr=16000):
    """Crude FFT band-pass, good enough for level comparisons."""
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / sr)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x)).astype(np.float32)


def strip(video, t, path, n=10, span=None):
    vf = f'scale=200:-1,tile={n}x1' if span is None else f'fps={n / span:.3f},scale=200:-1,tile={n}x1'
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', f'{max(0, t - (0.17 if span is None else 0)):.3f}', '-i', video,
         '-vf', vf, '-frames:v', '1', path])


class Picture:
    """Scale and shift of the subject between two frames, from matched features in the face band."""
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.orb = cv2.ORB_create(900)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.mask = np.zeros((ZH, ZW), np.uint8)
        self.mask[int(ZH * 0.12):int(ZH * 0.60)] = 255
        self.face = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    def move(self, a, b):
        ka, da = self.orb.detectAndCompute(a, self.mask)
        kb, db = self.orb.detectAndCompute(b, self.mask)
        if da is None or db is None:
            return None
        m = self.bf.match(da, db)
        if len(m) < 25:
            return None
        A = np.float32([ka[x.queryIdx].pt for x in m]); B = np.float32([kb[x.trainIdx].pt for x in m])
        M, inl = self.cv2.estimateAffinePartial2D(A, B, ransacReprojThreshold=2.0)
        if M is None or inl.sum() < 25 or inl.sum() < 0.3 * len(m):
            return None
        return float(np.hypot(M[0, 0], M[1, 0])), float(M[0, 2]) / ZW, float(M[1, 2]) / ZH

    def faces(self, g):
        f = self.face.detectMultiScale(g, 1.1, 5, minSize=(40, 40))
        return max(f, key=lambda r: r[2] * r[3]) if len(f) else None


def load_words(path):
    j = json.load(open(path))
    ws = j['words'] if isinstance(j, dict) else j
    out = []
    for w in ws:
        if w.get('type', 'word') != 'word':
            continue
        t = w.get('text', w.get('word', w.get('t', '')))
        s = w.get('start', w.get('s')); e = w.get('end', w.get('e'))
        if t and s is not None:
            out.append(dict(text=t.strip(), start=float(s), end=float(e if e is not None else s), p=w.get('probability', w.get('p'))))
    return out


def asr(a16):
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get('GATE_WHISPER', 'small.en'), compute_type='int8')
    segs, _ = m.transcribe(a16, language='en', word_timestamps=True, vad_filter=True)
    return [dict(text=w.word.strip(), start=w.start, end=w.end, p=w.probability) for s in segs for w in s.words]


NUM = {'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8',
       'nine': '9', 'ten': '10'}


def norm(text):
    """Words for comparison: lower case, digits kept as digits, small number words turned to digits."""
    toks = re.findall(r"[a-z']+|\d+", text.lower().replace(',', '').replace('-', ' '))
    return [NUM.get(t, t) for t in toks]


SAME = {'wanna': 'want to', 'gonna': 'going to', 'gotta': 'got to', 'kinda': 'kind of', 'cause': 'because', 'ok': 'okay',
        "'em": 'them', 'til': 'until', 'alright': 'all right'}
NUMISH = {'thousand', 'hundred', 'million', 'dollars', 'dollar', 'bucks', 'percent', 'k', 'and', 'a', 'or'}


def same_words(x, y):
    """True when two word runs say the same thing written differently ("green side"/"greenside", "$3,000"/"three thousand dollars")."""
    ex = lambda ws: ''.join(SAME.get(w, w) for w in ws).replace(' ', '').replace("'", '')
    if ex(x) == ex(y):
        return True
    dx, dy = [w for w in x if w.isdigit()], [w for w in y if w.isdigit()]
    rest = lambda ws: [w for w in ws if not w.isdigit() and w not in NUMISH]
    if (dx or dy) and not rest(x) and not rest(y):
        lead = lambda ds: [d.rstrip('0') or '0' for d in ds if d.strip('0')]
        return not dx or not dy or lead(dx) == lead(dy)
    return False


def hue(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 0.12 or mx < 0.15:
        return None            # grey, black or white: always allowed
    d = mx - mn
    h = ((g - b) / d % 6) if mx == r else ((b - r) / d + 2) if mx == g else ((r - g) / d + 4)
    return h * 60


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0 if args else 1)
    video = args[0]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    out = opt('--out', os.path.join(os.path.dirname(os.path.abspath(video)), 'qa'))
    flags = os.path.join(out, 'flags'); os.makedirs(flags, exist_ok=True)
    P = merge(DEFAULT, json.load(open(opt('--preset'))) if opt('--preset') else {})
    edit = json.load(open(opt('--edit'))) if opt('--edit') else {}
    rows = []

    def row(name, result, detail):
        rows.append(dict(check=name, result=result, detail=detail))

    def verdict(name, fails, warns, ok):
        row(name, 'FAIL' if fails else 'WARN' if warns else 'PASS',
            '; '.join((fails + warns)[:10]) + (f' (+{len(fails + warns) - 10} more)' if len(fails + warns) > 10 else '')
            if fails or warns else ok)

    def flag(kind, t, **kw):
        strip(video, t, os.path.join(flags, f'{kind}_{t:07.2f}.jpg'), **kw)

    # ---- specs, loudness
    sp = probe(video); fps = sp['fps']
    F = P['format']
    bad = []
    if (sp['w'], sp['h']) != (F['width'], F['height']):
        bad.append(f"{sp['w']}x{sp['h']} is not {F['width']}x{F['height']}")
    if not any(abs(fps - f) < 0.05 for f in F['fps']):
        bad.append(f'{fps:.2f} fps not allowed')
    if sp['adur'] is None:
        bad.append('no audio track')
    elif abs(sp['vdur'] - sp['adur']) > 1.5 / fps:
        bad.append(f"picture {sp['vdur']:.2f}s but sound {sp['adur']:.2f}s")
    verdict('specs', bad, [], f"{sp['w']}x{sp['h']} {fps:.2f} fps, {sp['vdur']:.2f}s")
    if sp['adur'] is None:
        finish(rows, video, out, args); return
    I, TP = loudness(video)
    A = P['audio']
    bad = []
    if I is None:
        bad.append('could not measure loudness')
    else:
        if abs(I - A['lufs']) > A['lufs_tolerance']:
            bad.append(f"{I:.1f} LUFS, target {A['lufs']} (+-{A['lufs_tolerance']})")
        if TP > A['true_peak_max']:
            bad.append(f"true peak {TP:.1f} dBTP over {A['true_peak_max']}")
    verdict('loudness', bad, [], f'{I} LUFS, true peak {TP} dBTP')

    # ---- decode
    G = gray_frames(video, fps)
    n = len(G); total = n / fps
    S = G[:, ::5, ::5].astype(np.float32)                       # 72x128 for frame differences
    d = np.abs(np.diff(S, axis=0)).mean(axis=(1, 2))
    a16 = audio(video)
    db = envelope(a16)
    speech = float(np.percentile(db, 75))
    spike = lambda i: d[i] > 1.8 * max(1.0, float(np.median(np.r_[d[max(0, i - 3):i], d[i + 1:i + 4]])))
    cuts = [i + 1 for i in range(len(d)) if d[i] > 6 and spike(i)]
    cuts = [c for k, c in enumerate(cuts) if k == 0 or c - cuts[k - 1] > 1]
    try:
        pic = Picture()
    except Exception as e:
        pic = None
        row('setup', 'NOT RUN', f'OpenCV missing ({type(e).__name__}): cuts, freeze and headroom were not measured')

    # ---- opening, glitches
    first = float(np.argmax(db > speech - 12) / 16000)
    bright = S.mean(axis=(1, 2))
    bad = []
    if first > 0.5:
        bad.append(f'first speech at {first:.2f}s (limit 0.5 s)')
    if bright[0] < 10:
        bad.append('first frame is black')
    verdict('opening', bad, [], f'speech starts at {first:.2f}s, first frame has a picture')
    bad = []
    for i in range(1, len(d) - 1):
        if d[i - 1] > 18 and d[i] > 18 and np.abs(S[i + 1] - S[i - 1]).mean() < 0.35 * d[i]:
            bad.append(f'one-frame flash at {i / fps:.2f}s'); flag('flash', i / fps)
    for i in np.where(bright < 6)[0]:
        if 0 < i < n - int(1.2 * fps) and (i == 0 or bright[i - 1] >= 6):
            bad.append(f'black frame at {i / fps:.2f}s'); flag('black', i / fps)
    verdict('glitches', bad, [], 'no one-frame flashes or black frames')

    # ---- freeze: a face that stops moving
    if pic:
        bad = []
        cells = np.abs(np.diff(S, axis=0)).reshape(n - 1, 8, 16, 6, 12).mean(axis=(2, 4))      # 8x6 grid of 16x12 cells
        still = (cells < 0.35).mean(axis=(1, 2)) > 0.9
        i = 0
        while i < len(still):
            if still[i]:
                j = i
                while j < len(still) and still[j]:
                    j += 1
                if j - i >= int(0.27 * fps) and pic.faces(G[i]) is not None:
                    bad.append(f'face frozen for {(j - i) / fps:.2f}s from {i / fps:.2f}s')
                    flag('freeze', i / fps, span=max(0.5, (j - i) / fps + 0.3))
                i = j
            else:
                i += 1
        verdict('freeze', bad, [], 'no frozen face')

    # ---- cuts on the picture
    joins = sorted(set([c / fps for c in cuts] + [float(j) for j in edit.get('joins', [])]))
    if pic:
        C = P['cuts']; bad, warn, kinds = [], [], {'punch': 0, 'clean': 0, 'new shot': 0}
        for c in cuts:
            if c + 2 >= n or c < 2:
                continue
            m = pic.move(G[c - 1], G[c])
            if not m:
                kinds['new shot'] += 1; continue
            s, dx, dy = m
            t = c / fps
            # the speaker's own motion right after the cut is not the editor's fault
            after = pic.move(G[c], G[c + 1]) or (1, 0, 0)
            zoom = abs(s - 1); hop = max(abs(dx), abs(dy)); own = max(abs(after[1]), abs(after[2]))
            if not C['allow_punch'] and zoom > C['max_drift']:
                bad.append(f'{t:.2f}s cut zoom x{s:.2f}: this preset allows no zoom at cuts')
                flag('cut', t)
            elif C['max_drift'] < zoom < C['min_punch']:
                bad.append(f'{t:.2f}s zoom snaps x{s:.2f}: too small to look deliberate (punch in {C["min_punch"]:.0%} or more, or match the framing)')
                flag('cut', t)
            elif zoom >= C['min_punch'] and s < 1 and zoom < 0.12:
                warn.append(f'{t:.2f}s framing pulls back x{s:.2f} at the cut: check it does not read as a hop')
                flag('cut', t)
            elif zoom >= C['min_punch']:
                kinds['punch'] += 1
            elif hop > C['max_hop'] + 2 * own:
                (bad if hop > 2.5 * C['max_hop'] else warn).append(f'{t:.2f}s jump cut hops {hop:.1%} of the frame: cover it or punch in')
                flag('cut', t)
            else:
                kinds['clean'] += 1
        for i in range(len(cuts) - 2):
            if (cuts[i + 2] - cuts[i]) / fps < 0.6:
                bad.append(f'{cuts[i] / fps:.2f}s three picture changes inside {(cuts[i + 2] - cuts[i]) / fps:.2f}s read as a glitch')
                flag('flurry', cuts[i] / fps, span=1.0)
        verdict('cuts', bad, warn, f"{len(cuts)} cuts: {kinds['punch']} punch-ins, {kinds['clean']} clean, {kinds['new shot']} new shots")

    # ---- sound at each cut
    # A splice inside speech leaves a short, shallow dip with full voice on both sides. No dip at all means the
    # sound was never cut there (a picture-only punch), which is fine. A deep dip is a cut in a real gap.
    known = [float(j) for j in edit.get('joins', [])]
    tight = []
    for t in joins:
        k = int(t * 16000)
        if k < 1600 or k > len(db) - 1600:
            continue
        L = db[k - 960:k - 400].max(); R = db[k + 400:k + 960].max()
        m = db[k - 320:k + 320].min()
        low = db[k - 1600:k + 1600] < speech - 8
        i = 1600 - 320 + int(np.argmin(db[k - 320:k + 320])); a_ = b_ = i
        while a_ > 0 and low[a_ - 1]: a_ -= 1
        while b_ < len(low) - 1 and low[b_ + 1]: b_ += 1
        gap = (b_ - a_) / 16000 if low[i] else 0.0
        is_known = any(abs(t - j) < 0.02 for j in known)
        spliced = min(L, R) - m >= 4 or is_known
        if L > speech - 4 and R > speech - 4 and spliced and (gap > 0 or is_known) and gap < 0.045:
            tight.append((t, f'{t:.2f}s cut lands inside speech (full voice both sides, gap {gap * 1000:.0f} ms)'))
        elif is_known and (L > speech - 4 or R > speech - 4) and gap < 0.03:
            tight.append((t, f'{t:.2f}s cut clips the {"end" if L > R else "start"} of a word'))
    for t, _ in tight[:12]:
        flag('cutaudio', t)

    # ---- words
    heard = None
    try:
        if opt('--transcript'):
            heard = load_words(opt('--transcript'))
        elif '--no-asr' not in args:
            heard = asr(a16)
            json.dump(heard, open(os.path.join(out, 'heard-words.json'), 'w'))
    except Exception as e:
        row('words', 'NOT RUN', f'speech-to-text unavailable ({type(e).__name__}); pass --transcript with word timings of the render')
    if heard is None and not any(r['check'] == 'words' for r in rows):
        row('words', 'NOT RUN', 'no transcript of the render; pass --transcript or install faster-whisper')
    if heard is not None:
        bad, warn = [], []
        want_text = open(opt('--expect')).read() if opt('--expect') else ' '.join(w['text'] for w in edit.get('words', []))
        if want_text.strip():
            want = norm(want_text); got = norm(' '.join(w['text'] for w in heard))
            sm = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
            ratio = sum(b.size for b in sm.get_matching_blocks()) / max(1, len(want))
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op in ('replace', 'delete'):
                    x, y = want[i1:i2], got[j1:j2]
                    if same_words(x, y):
                        continue
                    bad.append(f'expected "{" ".join(x)}" but heard "{" ".join(y) or "nothing"}"')
            ok = f'{ratio:.1%} of the expected words heard'
        else:
            ok = f'{len(heard)} words heard (no script given, so only weak words beside cuts are checked)'
        weak = [w for w in heard if w.get('p') is not None and w['p'] < 0.45]
        for w in weak:
            if any(-0.12 <= j - w['end'] <= 0.25 or -0.25 <= j - w['start'] <= 0.12 for j in joins):
                warn.append(f'"{w["text"]}" at {w["start"]:.2f}s is unclear right beside a cut')
                flag('word', w['start'])
        # a tight cut is a listen-here warning; with an unclear word beside it, it is a clipped word
        for t, msg in tight:
            (bad if any(-0.35 <= t - w['start'] <= 0.6 for w in weak) else warn).append(msg)
        tight = []
        verdict('words', bad, warn, ok)

    if tight:
        verdict('cut-audio', [], [m for _, m in tight], '')
    else:
        row('cut-audio', 'PASS', f'{len(joins)} cuts checked for sound; tight ones are listed under words' if heard is not None else f'{len(joins)} cuts, none inside speech')

    # ---- tone between cuts
    lo, mid = envelope(band(a16, 80, 250), 1600), envelope(band(a16, 500, 4000), 1600)
    edges = [0.0] + [j for j in joins if 0.3 < j < total - 0.3] + [total]
    segs = []
    for a, b in zip(edges, edges[1:]):
        ia, ib = int(a * 16000), int(b * 16000)
        voiced = db[ia:ib] > speech - 6
        if voiced.sum() > 1.0 * 16000:
            segs.append((a, b, float(np.median(lo[ia:ib][voiced]) - np.median(mid[ia:ib][voiced]))))
    warn = []
    if len(segs) >= 3:
        med = float(np.median([s[2] for s in segs]))
        for (a, b, v), (a2, b2, v2) in zip(segs, segs[1:]):
            if abs(v2 - v) > 6 and abs(v2 - med) > 5:
                warn.append(f'voice turns {"bassier" if v2 > v else "thinner"} by {abs(v2 - v):.0f} dB at {a2:.2f}s')
    verdict('tone', [], warn, f'{len(segs)} stretches keep the same bass-to-voice balance')

    # ---- headroom
    if pic:
        Fr = P['framing']; bad, seen, eyes = [], 0, []
        shots = [0] + cuts + [n]
        for a, b in zip(shots, shots[1:]):
            if b - a < int(0.4 * fps):
                continue
            got = [f for f in (pic.faces(G[i]) for i in np.linspace(a + 2, b - 3, 3).astype(int)) if f is not None]
            if not got:
                continue
            seen += 1
            x, y, w, h = np.median(np.array(got), axis=0)
            eye = (y + 0.40 * h) / ZH; cx = (x + w / 2) / ZW
            eyes.append(eye)
            msg = None
            if eye > Fr['eye_line'][1]:
                msg = f'too much headroom (eyes {eye:.0%} down the frame, limit {Fr["eye_line"][1]:.0%})'
            elif eye < Fr['eye_line'][0]:
                msg = f'head too close to the top (eyes {eye:.0%} down)'
            elif w / ZW < Fr['min_face_width']:
                msg = f'subject too small (face {w / ZW:.0%} of the width)'
            elif abs(cx - 0.5) > Fr['max_off_centre']:
                msg = f'subject off centre by {abs(cx - 0.5):.0%}'
            if msg:
                bad.append(f'{a / fps:.2f}s {msg}')
                if len(bad) <= 6:
                    flag('framing', a / fps + 0.2)
        if not seen:
            row('headroom', 'NOT RUN', 'no face found')
        else:
            spread = max(eyes) - min(eyes)
            warn = [f'eye line wanders {spread:.0%} of the frame between shots'] if spread > 0.10 and not bad else []
            verdict('headroom', bad if len(bad) > max(1, 0.15 * seen) else [], warn + (bad if len(bad) <= max(1, 0.15 * seen) else []),
                    f'{seen} shots, eyes {np.median(eyes):.0%} down the frame')

    # ---- overlays against their words
    ov = edit.get('overlays') or []
    if ov:
        O = P['overlays']; bad = []
        for o in ov:
            if o.get('anchor') is None:
                continue
            late = o['start'] - o['anchor']
            if late > O['late_max']:
                bad.append(f"{o.get('id', 'overlay')} arrives {late:.2f}s after its word at {o['anchor']:.2f}s")
            elif -late > O['lead_max']:
                bad.append(f"{o.get('id', 'overlay')} arrives {-late:.2f}s before its word at {o['anchor']:.2f}s")
        verdict('overlays', bad, [], f'{len(ov)} overlays land with their words')
    else:
        row('overlays', 'NOT RUN', 'no --edit sheet with overlays; check each overlay lands on its word by eye')

    # ---- ending
    E = P['ending']; bad, warn = [], []
    last_loud = np.where(db > speech - 12)[0]
    last = heard[-1]['end'] if heard else (last_loud[-1] / 16000 if len(last_loud) else 0)
    if len(last_loud):
        last = max(last, min(total, last_loud[-1] / 16000)) if heard and last_loud[-1] / 16000 - last < 0.35 else last
    hold = total - last
    tail = db[-800:].max() if len(db) > 800 else -90
    if hold < E['hold_min']:
        bad.append(f'only {hold:.2f}s after the last word (need {E["hold_min"]}s)')
    if E['mode'] != 'endcard' and hold > E['hold_max']:
        warn.append(f'{hold:.2f}s of nothing after the last word')
    if tail > speech - 18:
        bad.append('sound stops dead at the end instead of fading')
    verdict('ending', bad, warn, f'{hold:.2f}s hold after the last word, sound fades')
    if bad or warn:
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-sseof', '-2', '-i', video, '-vf', 'fps=6,scale=200:-1,tile=12x1',
             '-frames:v', '1', os.path.join(flags, 'ending.jpg')])

    # ---- look: colours and grade in the composition source
    if opt('--composition'):
        src = open(opt('--composition')).read()
        L = P['look']; bad = []
        cols = {c.lower() for c in re.findall(r'#([0-9a-fA-F]{6})\b', src)}
        allowed = {c.lower().lstrip('#') for c in L['palette']}
        for c in sorted(cols):
            h = hue(c)
            if h is None:
                continue
            if any(a <= h <= b for a, b in L['banned_hues']):
                bad.append(f'#{c} is a banned colour for this preset')
            elif allowed and c not in allowed and not any(hue(a) is not None and min(abs(h - hue(a)), 360 - abs(h - hue(a))) < 14 for a in allowed):
                bad.append(f'#{c} is outside the preset palette')
        if not L['allow_grade']:
            for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', src):
                if re.search(r'video|#cam|#stage|footage', sel) and re.search(r'filter\s*:[^;]*(contrast|saturate|sepia|grayscale|hue-rotate|brightness)', body):
                    bad.append(f'colour grade on footage in "{sel.strip()[:40]}"')
        verdict('look', bad, [], f'{len(cols)} colours, all inside the preset; no grade on footage')

    finish(rows, video, out, args)


def finish(rows, video, out, args):
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', video, '-vf', 'fps=1/3,scale=216:-1,tile=8x4', '-frames:v', '1',
         os.path.join(out, 'sheet.jpg')])
    fails = [r for r in rows if r['result'] == 'FAIL']; warns = [r for r in rows if r['result'] == 'WARN']
    head = 'FAIL' if fails else 'PASS WITH WARNINGS' if warns else 'PASS'
    md = [f'# First-pass gate: {head}', '', f'Render: `{video}`', '', '| Check | Result | Detail |', '| --- | --- | --- |']
    md += [f"| {r['check']} | {r['result']} | {r['detail']} |" for r in rows]
    md += ['', 'Frame strips for every FAIL and WARN are in `flags/`. Contact sheet: `sheet.jpg`.',
           'A pass here does not replace watching and listening once.']
    open(os.path.join(out, 'first-pass.md'), 'w').write('\n'.join(md) + '\n')
    json.dump(dict(verdict=head, render=video, checks=rows), open(os.path.join(out, 'first-pass.json'), 'w'), indent=1)
    print(json.dumps(dict(verdict=head, checks=rows)) if '--json' in args else '\n'.join(md))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
