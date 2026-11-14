#!/usr/bin/env python3
"""Talking-head short editor: a one-speaker vertical recording in, a finished Reel/Short out.

The editor writes the judgment (edit-spec.json); this script does the mechanics, so every
edit follows the craft floor and the project's BRAND.md (references/craft-floor.md): phrase-level cuts in real
silence, one slow push carried across jump cuts (no cut zooms unless the spec allows them),
full-frame cutaways over the joins, calm word-timed captions, a hook title, ducked music beds,
a held and faded ending, and a mastered mix.

Usage (run from the video project folder):
  python3 talking_head.py plan   edit-spec.json            -> edit-plan.json
  python3 talking_head.py render edit-plan.json [--draft]  -> renders/<name>.mp4
Needs: ffmpeg with libass, numpy, opencv-python-headless (<5).
See ../references/talking-head-spec.md for every spec field.
"""
import json, math, os, re, subprocess, sys
import numpy as np

SR = 48000
OUT_W, OUT_H = 1080, 1920
WORK_W, WORK_H = 1620, 2880          # source is scaled to this once; punch-ins crop from it
SIZES = {'W': 1.0, 'M': 1.2, 'T': 1.42}


def ff(*a, **kw):
    return subprocess.run(['ffmpeg', '-v', 'error', '-y', *a], check=True, **kw)


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=r_frame_rate,nb_frames:format=duration', '-of', 'json', path],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    n, d = j['streams'][0]['r_frame_rate'].split('/')
    return float(n) / float(d), float(j['format']['duration'])


# ---------------------------------------------------------------- plan

def load_words(path):
    d = json.load(open(path))
    ws = d['words'] if isinstance(d, dict) else d
    return [dict(text=w['text'], start=float(w['start']), end=float(w['end']))
            for w in ws if w.get('type', 'word') == 'word']


def find_phrase(words, phrase, after=0.0):
    """Source start time of an exact phrase (case and punctuation ignored)."""
    norm = lambda s: re.sub(r"[^a-z0-9' ]", '', s.lower().replace('-', ' ')).split()
    target = norm(phrase)
    toks = [(norm(w['text']), i) for i, w in enumerate(words)]
    flat = [(t, i) for ts, i in toks for t in ts]
    for k in range(len(flat) - len(target) + 1):
        if [t for t, _ in flat[k:k + len(target)]] == target and words[flat[k][1]]['start'] >= after:
            return flat[k][1]
    sys.exit(f'phrase not found in transcript: "{phrase}"')


def voice_env(wav, hop=0.005):
    x = np.abs(wav).mean(axis=1) if wav.ndim == 2 else np.abs(wav)
    n = int(SR * hop)
    m = len(x) // n
    return np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(axis=1) + 1e-12), hop


def read_audio(src):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', src, '-vn', '-ac', '2', '-ar', str(SR),
                          '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def quietest(env, hop, lo, hi):
    """Time of the quietest 20 ms inside [lo, hi]."""
    a, b = int(lo / hop), max(int(lo / hop) + 1, int(hi / hop))
    seg = np.convolve(env[a:b], np.ones(4) / 4, mode='same') if b - a > 4 else env[a:b]
    return (a + int(np.argmin(seg))) * hop


def detect_faces(src, fps_sample=2):
    import cv2
    cc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    w, h = 540, 960
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', src, '-vf', f'fps={fps_sample},scale={w}:{h},format=gray',
                          '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    out, i = [], 0
    while True:
        buf = p.stdout.read(w * h)
        if len(buf) < w * h:
            break
        g = np.frombuffer(buf, np.uint8).reshape(h, w)
        fs = cc.detectMultiScale(g, 1.1, 5, minSize=(60, 60))
        if len(fs):
            x, y, fw, fh = max(fs, key=lambda r: r[2] * r[3])
            out.append([i / fps_sample, (x + fw / 2) / w, (y + fh / 2) / h, fw / w])
        i += 1
    p.wait()
    return out


def clip_cuts(path, cache):
    """Shot changes inside a stock or AI clip (many generated clips hold several shots).
    Threshold 3 on a small copy: dark AI clips hide real cuts from the default threshold."""
    key = os.path.abspath(path)
    if key not in cache:
        r = subprocess.run(['ffmpeg', '-v', 'info', '-i', path, '-vf', 'scale=320:-1,scdet=threshold=3',
                            '-an', '-f', 'null', '-'], capture_output=True, text=True)
        cache[key] = [float(x) for x in re.findall(r'lavfi\.scd\.time: ([\d.]+)', r.stderr)]
    return cache[key]


def clip_len(path):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                                capture_output=True, text=True).stdout.strip() or 0)


def plan(spec_path):
    spec = json.load(open(spec_path))
    root = os.path.dirname(os.path.abspath(spec_path))
    P = lambda p: os.path.join(root, p)
    src = P(spec['source'])
    fps, dur = probe(src)
    words = load_words(P(spec['transcript']))
    calm_from = words[find_phrase(words, spec['calm_from'])]['start'] if spec.get('calm_from') else 1e9
    calm_to = words[find_phrase(words, spec['calm_to'], calm_from)]['start'] if spec.get('calm_to') else 1e9
    is_calm = lambda t: calm_from <= t < calm_to

    # 1. reviewed drops (retakes, false starts) by phrase, never by guess
    dropped = set()
    for d in spec.get('drops', []):
        i = find_phrase(words, d['phrase'], d.get('after', 0))
        n = len(d['phrase'].split())
        dropped.update(range(i, i + n))
    if spec.get('selects'):
        # a short cut: keep only these spans, in source order, each from one phrase to another
        chosen = set()
        for r in spec['selects']:
            i = find_phrase(words, r['from'], r.get('after', 0))
            j = find_phrase(words, r['to'], words[i]['start']) + len(r['to'].split()) - 1
            chosen.update(range(i, j + 1))
        dropped.update(set(range(len(words))) - chosen)
    kept = [w for i, w in enumerate(words) if i not in dropped]
    if spec.get('end_phrase'):
        j = find_phrase(kept, spec['end_phrase'])
        kept = kept[:j + len(spec['end_phrase'].split())]

    # 2. phrase-level cuts placed in the quietest part of each long pause
    audio = read_audio(src)
    env, hop = voice_env(audio)
    pause = spec.get('max_pause', 0.26)
    calm_pause = spec.get('calm_max_pause', 0.55)
    segs = []                                   # source seconds [a, b)
    a = max(0.0, kept[0]['start'] - spec.get('head', 0.12))
    for w, nx in zip(kept, kept[1:]):
        gap = nx['start'] - w['end']
        limit = calm_pause if is_calm(nx['start']) else pause
        forced = words.index(nx) - words.index(w) > 1          # a drop sits between them
        if gap > limit or forced:
            keep_gap = min(gap, limit)
            tail = max(0.09, keep_gap * 0.6)                   # transcripts end words before the sound dies
            head = max(0.06, keep_gap - tail)
            out_t = quietest(env, hop, w['end'] + 0.06, min(nx['start'] - 0.05, w['end'] + tail + 0.08))
            in_t = quietest(env, hop, max(out_t + 0.02, nx['start'] - head - 0.06), nx['start'] - 0.03)
            if in_t - out_t > 0.04:
                segs.append([a, out_t]); a = in_t
    # the ending holds about a second after the last word (stopping short of any next word), then fades
    nxt = [w for w in words if w['start'] > kept[-1]['end']]
    hold_to = kept[-1]['end'] + spec.get('end_hold', 1.0)
    if nxt:
        hold_to = min(hold_to, nxt[0]['start'] - 0.12)
    segs.append([a, min(dur, max(kept[-1]['end'] + spec.get('tail', 0.45), hold_to))])
    # snap to whole frames, so picture and sound cut on the same instant
    fsegs = []
    for s, e in segs:
        fa, fb = int(round(s * fps)), int(round(e * fps))
        if fb > fa:
            fsegs.append([fa, fb])

    def to_out(t):
        acc = 0
        for fa, fb in fsegs:
            if t < fa / fps:
                return acc / fps
            if t <= fb / fps:
                return (acc + (t * fps - fa)) / fps
            acc += fb - fa
        return acc / fps
    total = sum(fb - fa for fa, fb in fsegs) / fps
    # if the source has no room for the full hold, pad the end (music only, under the closing cutaway)
    last_o = sum(fb - fa for fa, fb in fsegs[:-1]) / fps + (kept[-1]['end'] - fsegs[-1][0] / fps)
    pad = round(max(0.0, spec.get('end_hold', 0) + spec.get('end_fade', 0) * 0.5 - (total - last_o)), 3) if spec.get('end_hold') else 0.0
    total += pad
    joins = []
    acc = 0
    for fa, fb in fsegs[:-1]:
        acc += fb - fa
        joins.append(acc / fps)
    for w in kept:
        w['o_start'], w['o_end'] = to_out(w['start']), to_out(w['end'])

    # 3. graphics anchored to words
    def anchor(phrase, after=0):
        i = find_phrase(kept, phrase, after)
        return i, kept[i]['o_start']
    emph = {e.lower() for e in spec.get('emphasis', [])}
    slams = []
    for s in spec.get('slams', []):
        i, t = anchor(s['phrase'], s.get('after', 0))
        n = len(s['phrase'].split())
        end = kept[i + n - 1]['o_end']
        slams.append(dict(text=s['text'], start=max(0, t - 0.07), end=max(end + 0.35, t + s.get('hold', 0.95)),
                          sub=s.get('sub')))
    chips = []
    for c in spec.get('sections', []):
        i, t = anchor(c['phrase'], c.get('after', 0))
        chips.append(dict(text=c['text'], start=max(0, t - 0.1), end=t + c.get('hold', 2.8)))
    cta = None
    if spec.get('cta'):
        i, t = anchor(spec['cta']['phrase'])
        cta = dict(text=spec['cta']['text'], start=t - 0.1, end=total)
    hook = dict(spec['hook'], start=0.0, end=spec['hook'].get('hold', 3.0)) if spec.get('hook') else None

    # 4. shots
    faces = detect_faces(src) if not os.path.exists(P('cache/faces.json')) else json.load(open(P('cache/faces.json')))
    os.makedirs(P('cache'), exist_ok=True)
    json.dump(faces, open(P('cache/faces.json'), 'w'))
    fa_arr = np.array(faces, dtype=float).reshape(-1, 4)   # (t, x, y, w); empty when no face is found
    calm_o = (to_out(calm_from) if calm_from < 1e9 else 1e9, to_out(calm_to) if calm_to < 1e9 else 1e9)
    in_calm = lambda t: calm_o[0] <= t < calm_o[1]
    if not spec.get('cut_zooms'):
        # one framing and one slow push-in, carried across every jump cut (a zoom that resets
        # at a cut pops); it restarts only while a full-frame cutaway hides the speaker
        mv = dict(base=1.04, rate=0.0025, cap=0.06); mv.update(spec.get('push', {}))
        spans = [(out_to_src(0, fsegs, fps), out_to_src(total, fsegs, fps))]
        keep_src = np.zeros(len(fa_arr), bool)
        for fa_, fb_ in fsegs:
            keep_src |= (fa_arr[:, 0] >= fa_ / fps) & (fa_arr[:, 0] <= fb_ / fps)
        sel = fa_arr[keep_src] if len(fa_arr) else []
        fx, fy = (float(np.median(sel[:, 1])), float(np.median(sel[:, 2]))) if len(sel) else (0.5, 0.36)
        cover = []
        for r in spec.get('broll', []):
            if r.get('layout', 'full') == 'full':
                i_, t_ = anchor(r['phrase'], r.get('after', 0))
                st_ = max(0.0, t_ - r.get('lead', 0.12))
                cover.append((st_, min(total, st_ + r.get('dur', 2.2))))
        b = sorted({0.0, total} | {y for x, y in cover if 0 < y < total})
        shots = [dict(start=round(x, 4), end=round(y, 4), size='P', zoom=mv['base'], face=[round(fx, 4), round(fy, 4)],
                      push=mv['rate'], cap=mv['cap'], linear=True) for x, y in zip(b, b[1:]) if y - x >= 1 / fps]
        punch_at = []
    else:
        shots = None
    bounds = {0.0, total} | set(joins) if shots is None else set()
    # emphasis words and slams pull a punch-in onto the word
    if shots is None:
        punch_at = [w['o_start'] - 0.04 for w in kept
                    if re.sub(r'[^a-z]', '', w['text'].lower()) in emph and not in_calm(w['o_start'])]
        punch_at += [s['start'] for s in slams]
        for t in punch_at:
            if all(abs(t - b) > 0.9 for b in bounds):
                bounds.add(t)
        b = sorted(bounds)
    max_len = spec.get('max_shot', 3.4)
    calm_max = spec.get('calm_max_shot', 7.0)
    word_edges = sorted({w['o_start'] - 0.03 for w in kept})
    changed = shots is None
    while changed:
        changed = False
        for x, y in zip(b, b[1:]):
            lim = calm_max if in_calm(x) else max_len
            if y - x > lim:
                target = x + (y - x) / 2 if y - x < 2 * lim else x + lim * 0.7
                cands = [e for e in word_edges if x + 1.2 < e < y - 1.2]
                if cands:
                    b.append(min(cands, key=lambda e: abs(e - target)))
                    b.sort(); changed = True
                    break
    legacy = shots is None
    shots, prev = (shots or []), None
    cycle = ['T', 'M', 'W', 'M']
    ci = 0
    for x, y in zip(b, b[1:]) if legacy else []:
        if y - x < 1 / fps:
            continue
        if x == 0.0:
            size = spec.get('hook_shot', 'W')
        elif cta and x >= cta['start'] - 0.3:
            size = 'W' if prev != 'W' else 'M'
        elif hook and x < hook['end']:
            size = 'W'                          # the hook title needs headroom
        elif any(abs(x - p) < 0.06 for p in punch_at):
            size = 'T' if prev != 'T' else 'M'
        elif in_calm(x):
            size = 'M' if prev == 'T' else 'T'
        else:
            size = cycle[ci % 4]
            ci += 1
            if size == prev:
                size = cycle[ci % 4]; ci += 1
        # median face in this shot's source span
        s_lo, s_hi = out_to_src(x, fsegs, fps), out_to_src(y, fsegs, fps)
        sel = fa_arr[(fa_arr[:, 0] >= s_lo - 0.5) & (fa_arr[:, 0] <= s_hi + 0.5)] if len(fa_arr) else []
        fx, fy = (float(np.median(sel[:, 1])), float(np.median(sel[:, 2]))) if len(sel) else (0.5, 0.36)
        push = (0.07 if in_calm(x) else 0.035) * (1 if len(shots) % 3 else -0.6)
        if size == 'W' and prev == 'W':
            push = -0.12    # back-to-back wides: start 12% in and pull out, so the join still reads as a cut
        shots.append(dict(start=round(x, 4), end=round(y, 4), size=size, zoom=SIZES[size],
                          face=[round(fx, 4), round(fy, 4)], push=push))
        prev = size

    # 5. captions: 1-3 word chunks on phrase boundaries
    caps, cur = [], []
    def flush():
        if cur:
            caps.append(dict(words=[dict(t=w['text'], s=w['o_start'], e=w['o_end']) for w in cur],
                             calm=in_calm(cur[0]['o_start'])))
            cur.clear()
    for w, nx in zip(kept, kept[1:] + [None]):
        if cur and len(' '.join(c['text'] for c in cur + [w])) > 15:
            flush()
        cur.append(w)
        txt = ' '.join(c['text'] for c in cur)
        if (nx is None or re.search(r'[.,?!;:]$', w['text']) or len(cur) >= 3 or len(txt) >= 11
                or nx['o_start'] - w['o_end'] > 0.3):
            flush()
    for c, nx in zip(caps, caps[1:] + [None]):
        c['start'] = max(0, c['words'][0]['s'] - 2 / fps)
        end = c['words'][-1]['e'] + 0.4
        c['end'] = min(end, nx['words'][0]['s'] - 2 / fps) if nx else end

    # 6. sound cues (effects follow visible events, not every cut)
    sfx = []
    if not spec.get('sfx', False):
        hook_sfx = None
    if spec.get('sfx', False) and hook:
        sfx.append(dict(kind='boom', t=0.0, db=-13))
    for s in slams if spec.get('sfx', False) else []:
        sfx.append(dict(kind='hit', t=s['start'] + 0.07, db=-15))
    for c in chips if spec.get('sfx', False) else []:
        sfx.append(dict(kind='whoosh', t=c['start'] - 0.12, db=-21))
    if calm_from < 1e9 and spec.get('sfx', False):
        sfx.append(dict(kind='swell', t=calm_o[0], db=-26))
    if cta and spec.get('sfx', False):
        sfx.append(dict(kind='pop', t=cta['start'] + 0.1, db=-20))

    # 7. b-roll cutaways and music beds, anchored to words
    broll = []
    cc_path = P('cache/clip-cuts-v2.json')
    cc = json.load(open(cc_path)) if os.path.exists(cc_path) else {}
    for r in spec.get('broll', []):
        i, t = anchor(r['phrase'], r.get('after', 0))
        st = max(0.0, t - r.get('lead', 0.12))
        # a cutaway must not contain the clip's own shot change: that reads as a double cut
        d_ = r.get('dur', 2.2); cin = r.get('in', 0.0)
        inside = [c for c in clip_cuts(P(r['file']), cc) if cin + 0.05 < c < cin + d_ + 0.05]
        if inside:
            c0 = inside[0]
            later = [c for c in clip_cuts(P(r['file']), cc) if c > c0 + 0.05]
            room_after = (later[0] if later else clip_len(P(r['file']))) - c0
            if c0 - d_ - 0.1 >= 0 and c0 - cin < room_after:
                new_in = round(c0 - d_ - 0.1, 2)
            elif room_after >= d_ + 0.1:
                new_in = round(c0 + 0.1, 2)
            else:
                new_in = round(max(0.0, c0 - d_ - 0.1), 2)
            print(f"note: {os.path.basename(r['file'])} has a shot change at {c0:.2f}s inside {cin:.2f}-{cin + d_:.2f}; "
                  f"using in={new_in}")
            r = dict(r, **{'in': new_in})
        broll.append(dict(file=P(r['file']), start=round(st, 4), end=round(min(total, st + r.get('dur', 2.2)), 4),
                          src_in=r.get('in', 0.0), layout=r.get('layout', 'full'), push=r.get('push', 0.06),
                          x=r.get('x', 0.5), y=r.get('y', 0.5), fade=r.get('fade', 0.0), gamma=r.get('gamma', 1.0)))
    json.dump(cc, open(cc_path, 'w'))
    music = []
    for m in spec.get('music', []):
        st = 0.0 if m.get('from', 'start') == 'start' else anchor(m['from'])[1] - m.get('lead', 0.3)
        en = total if m.get('to', 'end') == 'end' else anchor(m['to'])[1]
        music.append(dict(file=P(m['file']), start=round(max(0, st), 4), end=round(en, 4), src_in=m.get('in', 0.0),
                          under=m.get('under', 12), fade=m.get('fade', 0.6)))

    planned = dict(source=src, fps=fps, total=round(total, 4), segments=fsegs, joins=joins, broll=broll, music=music,
                   end_fade=spec.get('end_fade', 1.0), pad=pad, grain=spec.get('grain', 0), shots=shots, captions=caps, slams=slams, chips=chips, cta=cta, hook=hook, sfx=sfx,
                   emphasis=sorted(emph), look=spec.get('look', {}), name=spec.get('name', 'edit'), grade=spec.get('grade', True),
                   words=[dict(t=w['text'], s=round(w['o_start'], 3), e=round(w['o_end'], 3)) for w in kept])
    outp = P(f"{spec.get('name', 'edit')}.plan.json")
    json.dump(planned, open(outp, 'w'), indent=1)
    lens = [s['end'] - s['start'] for s in shots]
    print(f'plan: {total:.2f}s from {dur:.2f}s, {len(fsegs)} segments, {len(shots)} shots '
          f'(median {np.median(lens):.2f}s, longest {max(lens):.2f}s), {len(caps)} captions, '
          f'{len(slams)} slams, {len(chips)} chips -> {outp}')


def out_to_src(t, fsegs, fps):
    acc = 0
    for fa, fb in fsegs:
        n = fb - fa
        if t * fps <= acc + n:
            return (fa + t * fps - acc) / fps
        acc += n
    return fsegs[-1][1] / fps


# ---------------------------------------------------------------- render: captions (ASS)

def ass_time(t):
    t = max(0, t)
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f'{int(h)}:{int(m):02d}:{s:05.2f}'


def ass_color(hexrgb, alpha=0):
    h = hexrgb.lstrip('#')
    return f'&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}'


def clean(t):
    t = t.replace('--', '').replace('"', '').replace('“', '').replace('”', '')
    return re.sub(r'[.,;:]+$', '', t)


def build_ass(p, path, look):
    gold, white = ass_color(look['accent']), ass_color(look.get('text', '#FFFFFF'))
    black = ass_color('#000000')
    font = look['font']
    tfont = look.get('title_font', font)
    cap_y = look['caption_y']
    calm_look = look.get('motion', 'calm') == 'calm'
    case = (lambda t: t) if look.get('case') == 'as-spoken' else (lambda t: t.upper())
    up = lambda t: t if look.get('case') == 'as-spoken' else t.upper()
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{look['caption_px']},{white},{white},{black},{ass_color('#000000', 0x60)},-1,0,0,0,100,100,1,0,1,{look.get('outline', 7)},{look.get('shadow', 4)},5,60,60,0,1
Style: Title,{tfont},{look.get('title_px', 84)},{white},{white},{black},{ass_color('#000000', 0x50)},-1,0,0,0,100,100,{look.get('title_spacing', 1)},0,1,{look.get('outline', 7)},5,5,60,60,0,1
Style: Big,{tfont},{look.get('big_px', 132)},{gold},{gold},{black},{ass_color('#000000', 0x50)},-1,0,0,0,100,100,1,0,1,{look.get('outline', 9)},6,5,60,60,0,1
Style: Rule,{font},10,{gold},{gold},{gold},{gold},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Chip,{font},60,{white},{white},{ass_color('#0B0B0F', 0x30)},{ass_color('#000000', 0x80)},-1,0,0,0,100,100,4,0,3,18,0,5,60,60,0,1
Style: Slam,{font},190,{gold},{gold},{black},{ass_color('#000000', 0x40)},-1,0,0,0,100,100,2,0,1,11,7,5,40,40,0,1
Style: Box,{font},10,{black},{black},{black},{black},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    add = lambda layer, a, b, style, text: ev.append(f'Dialogue: {layer},{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{text}')
    slam_win = [(s['start'], s['end']) for s in p['slams']]
    covered = lambda a, b: any(a < y and b > x for x, y in slam_win)
    emph = set(p['emphasis'])
    for c in p['captions']:
        a, b = c['start'], c['end']
        # captions step aside while a slam owns the frame
        for x, y in slam_win:
            if a < y and b > x:
                if a >= x:
                    a = y
                else:
                    b = x
        if b - a < 0.08:
            continue
        parts, lit = [], False
        for w in c['words']:
            t = case(clean(w['t']))
            key = re.sub(r'[^a-z]', '', w['t'].lower())
            if key in emph and not (calm_look and lit):      # calm look: one accent word per line
                parts.append(f'{{\\c{gold}}}{t}{{\\c{white}}}'); lit = True
            else:
                parts.append(t)
        txt = ' '.join(parts)
        on_split = any(r['layout'] != 'full' and a < r['end'] and b > r['start'] for r in p.get('broll') or [])
        y_cap = BROLL_TOP_H if on_split else cap_y
        if calm_look:      # fade, soften and rise a few pixels: no bounce
            add(5, a, b, 'Cap', f'{{\\move(540,{y_cap + 10},540,{y_cap},0,180)\\fad(140,90)\\blur3\\t(0,180,\\blur0.6)}}{txt}')
        else:
            anim = '{\\fad(110,0)\\blur0.6}' if c['calm'] else '{\\fscx82\\fscy82\\t(0,90,\\fscx104\\fscy104)\\t(90,150,\\fscx100\\fscy100)}'
            add(5, a, b, 'Cap', f'{{\\pos(540,{y_cap})}}{anim}{txt}')
    if p['hook'] and calm_look:
        h, y = p['hook'], look['title_y']
        add(6, h['start'], h['end'], 'Title', f"{{\\move(540,{y + 14},540,{y},0,450)\\fad(300,400)}}{h['line1']}")
        add(6, h['start'] + 0.15, h['end'], 'Rule', f"{{\\p1\\pos(450,{y + 52})\\fad(300,400)}}m 0 0 l 180 0 180 4 0 4")
        add(6, h['start'] + 0.25, h['end'], 'Big', f"{{\\move(540,{y + 128},540,{y + 114},0,450)\\fad(300,400)}}{h['line2']}")
    elif p['hook']:
        h = p['hook']
        add(6, h['start'], h['end'], 'Title', f"{{\\pos(540,{look['title_y']})\\fad(0,180)}}{h['line1']}")
        add(6, h['start'], h['end'], 'Big', f"{{\\pos(540,{look['title_y'] + 118})\\fad(0,180)}}{h['line2']}")
    for c in p['chips']:
        add(6, c['start'], c['end'], 'Chip',
            f"{{\\move(540,{look['chip_y'] - 40},540,{look['chip_y']},0,220)\\fad(200,250)}}{c['text']}")
    if p['cta'] and calm_look:
        c, y = p['cta'], look['cta_y']
        add(6, c['start'], c['end'], 'Title', f"{{\\move(540,{y + 12},540,{y},0,400)\\fs{int(look.get('title_px', 84) * 0.6)}\\fad(300,0)}}Comment")
        add(6, c['start'] + 0.2, c['end'], 'Big', f"{{\\move(540,{y + 110},540,{y + 98},0,450)\\fs{int(look.get('big_px', 132) * 0.72)}\\fad(350,0)}}{c['text']}")
    elif p['cta']:
        c = p['cta']
        add(6, c['start'], c['end'], 'Chip', f"{{\\pos(540,{look['cta_y']})\\fad(200,0)}}COMMENT")
        add(6, c['start'] + 0.15, c['end'], 'Big',
            f"{{\\pos(540,{look['cta_y'] + 125})\\fscx64\\fscy64\\fad(150,0)\\t(0,160,\\fscx72\\fscy72)}}{c['text']}")
    for s in p['slams']:
        dim = f'{{\\p1\\pos(0,0)\\1a&H58&\\fad(90,140)}}m 0 0 l {OUT_W} 0 {OUT_W} {OUT_H} 0 {OUT_H}'
        add(3, s['start'], s['end'], 'Box', dim)
        y = look['slam_y']
        fs = int(min(190, 930 / (0.72 * max(1, len(s['text'])))))
        add(4, s['start'], s['end'], 'Slam',
            f"{{\\pos(540,{y})\\fs{fs}\\fscx130\\fscy130\\t(0,110,\\fscx100\\fscy100)\\fad(0,140)}}{s['text']}")
        if s.get('sub'):
            add(4, s['start'] + 0.12, s['end'], 'Title', f"{{\\pos(540,{y + 150})\\fad(120,140)}}{s['sub']}")
    open(path, 'w').write(hdr + '\n'.join(ev) + '\n')


# ---------------------------------------------------------------- render: sound

def synth(kind, db):
    rng = np.random.default_rng(len(kind) * 7919)
    if kind == 'boom':
        n = int(SR * 0.9); t = np.arange(n) / SR
        f = 38 + 55 * np.exp(-t * 9)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.5)
        x += lowpass(rng.standard_normal(n), 900) * np.exp(-t * 40) * 0.5
    elif kind == 'hit':
        n = int(SR * 0.5); t = np.arange(n) / SR
        f = 55 + 70 * np.exp(-t * 25)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
        x += highpass(rng.standard_normal(n), 2500) * np.exp(-t * 90) * 0.35
    elif kind == 'whoosh':
        n = int(SR * 0.55); t = np.arange(n) / SR
        env = np.sin(np.pi * np.clip(t / 0.55, 0, 1)) ** 2
        x = bandsweep(rng.standard_normal(n), 400, 3000) * env
        pan = np.linspace(-0.7, 0.7, n)
        x = x / (np.abs(x).max() + 1e-9) * 10 ** (db / 20)
        return np.stack([x * np.sqrt((1 - pan) / 2), x * np.sqrt((1 + pan) / 2)], 1)
    elif kind == 'swell':
        n = int(SR * 2.8); t = np.arange(n) / SR
        env = (t / 2.8) ** 2 * np.minimum(1, (2.8 - t) / 0.25)
        x = lowpass(rng.standard_normal(n), 600) * 0.6
        x += 0.5 * np.sin(2 * np.pi * 110 * t) + 0.3 * np.sin(2 * np.pi * 164.8 * t)
        x *= env
    elif kind == 'pop':
        n = int(SR * 0.16); t = np.arange(n) / SR
        f = 700 + 500 * (t / 0.16)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 30)
    else:
        raise ValueError(kind)
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (db / 20)
    return np.stack([x, x], 1)


def lowpass(x, fc):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / np.sqrt(1 + (f / fc) ** 4), len(x))


def highpass(x, fc):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / np.sqrt(1 + (fc / np.maximum(f, 1)) ** 4), len(x))


def bandsweep(x, f0, f1, blocks=24):
    out = np.zeros_like(x); n = len(x) // blocks
    for k in range(blocks):
        fc = f0 * (f1 / f0) ** (k / (blocks - 1))
        seg = x[k * n:(k + 1) * n + 256]
        y = highpass(lowpass(seg, fc * 1.6), fc / 1.6)[:n]
        out[k * n:k * n + len(y)] = y
    return out


def build_audio(p, path):
    fps = p['fps']
    src = read_audio(p['source'])
    pieces = []
    fade = int(SR * 0.006)
    ramp = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
    for fa, fb in p['segments']:
        a, b = int(round(fa / fps * SR)), int(round(fb / fps * SR))
        x = src[a:b].copy()
        x[:fade] *= ramp[:, None]; x[-fade:] *= ramp[::-1][:, None]
        pieces.append(x)
    voice = np.concatenate(pieces)
    n_total = int(round((sum(fb - fa for fa, fb in p['segments']) / fps + p.get('pad', 0)) * SR))
    voice = np.pad(voice, ((0, max(0, n_total - len(voice))), (0, 0)))[:n_total]
    # level the voice so effect levels mean something (speech RMS near -20 dBFS before master)
    env, hop = voice_env(voice)
    speech = np.median(env[env > np.percentile(env, 40)])
    voice *= 10 ** (-20 / 20) / (speech + 1e-9)
    write_wav(os.path.join(os.path.dirname(path), 'voice.wav'), voice)   # dry voice stem for craft QC joins
    mix = voice.copy()
    # music beds sit `under` dB below speech while the speaker talks and come up 4 dB in the gaps
    talk = np.convolve((env > speech * 0.25).astype(float), np.ones(60) / 60, mode='same')   # ~300 ms smoothing
    talk = np.clip(np.repeat(talk, int(SR * hop))[:len(mix)], 0, 1)
    talk = np.pad(talk, (0, len(mix) - len(talk)), mode='edge')
    for m in p.get('music') or []:
        x = read_audio(m['file'])
        x = x[int(m['src_in'] * SR):]
        a, b = int(m['start'] * SR), int(m['end'] * SR)
        n = min(b - a, len(x), len(mix) - a, len(talk) - a)
        x = x[:n].copy()
        rms = np.sqrt((x ** 2).mean()) + 1e-9
        x *= 10 ** ((-20 - m['under']) / 20) / rms
        f = int(m['fade'] * SR)
        if f and n > 2 * f:
            x[:f] *= np.linspace(0, 1, f)[:, None]; x[-f:] *= np.linspace(1, 0, f)[:, None]
        duck = 10 ** ((4 * (1 - talk[a:a + n])) / 20)
        mix[a:a + n] += x * duck[:, None]
    for c in p['sfx']:
        s = synth(c['kind'], c['db'])
        at = int(c['t'] * SR) - (len(s) if c['kind'] == 'swell' else 0)
        at = max(0, at)
        end = min(len(mix), at + len(s))
        mix[at:end] += s[:end - at]
    ef = int(SR * max(0.1, p.get('end_fade', 0.1)))
    mix[-ef:] *= np.linspace(1, 0, ef)[:, None]
    tmp = path + '.pre.wav'
    write_wav(tmp, mix)
    # two-pass loudness: -14 LUFS; aim TP at -2.0 so the AAC encode stays under -1.5 dBTP
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', tmp, '-af', 'loudnorm=I=-14:TP=-2.0:LRA=11:print_format=json',
                        '-f', 'null', '-'], capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rindex('{'):])
    af = (f"loudnorm=I=-14:TP=-2.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
          f"aresample={SR}")
    ff('-i', tmp, '-af', af, '-c:a', 'pcm_s24le', path)
    os.remove(tmp)


def write_wav(path, x):
    x = np.clip(x, -1, 1).astype(np.float32)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '2', '-i', '-',
                    '-c:a', 'pcm_f32le', path], input=x.tobytes(), check=True)


# ---------------------------------------------------------------- render: picture

def ease(u):
    return u * u * (3 - 2 * u)


def shot_at(shots, t):
    for s in shots:
        if s['start'] <= t < s['end']:
            return s
    return shots[-1]


# Calm default look (references/craft-floor.md); BRAND.md values go in the spec's "look".
# A wrapper that imports this module may replace DEFAULT_LOOK with its own house look.
DEFAULT_LOOK = dict(font='Figtree ExtraBold', title_font='Libre Caslon Text', accent='#C9A45C',
                    text='#F4EFE6', caption_px=80, case='as-spoken', motion='calm', caption_y=1300,
                    title_y=205, chip_y=215, cta_y=190, slam_y=1190)
BROLL_TOP_H = 880     # split layout: b-roll above, speaker below


def open_broll(b, fps):
    w, h = (OUT_W, OUT_H) if b['layout'] == 'full' else (OUT_W, BROLL_TOP_H)
    pw, ph = int(w * (1 + b['push'])) // 2 * 2, int(h * (1 + b['push'])) // 2 * 2
    vf = (f'fps={fps:.6f},scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph}:(iw-{pw})*{b.get("x", 0.5)}:(ih-{ph})*{b.get("y", 0.5)},'
          f'eq=contrast=1.04:saturation=0.9:brightness=-0.03:gamma={b.get("gamma", 1.0)},format=rgb24')
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', str(b['src_in']), '-i', b['file'], '-an', '-vf', vf,
                             '-f', 'rawvideo', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return dict(proc=proc, w=w, h=h, pw=pw, ph=ph, last=None)


def composite_broll(p, t, frame, readers, fps):
    import cv2
    for k, b in enumerate(p.get('broll') or []):
        if not (b['start'] <= t < b['end']):
            if k in readers and t >= b['end']:
                readers.pop(k)['proc'].terminate()
            continue
        r = readers.get(k) or readers.setdefault(k, open_broll(b, fps))
        buf = r['proc'].stdout.read(r['pw'] * r['ph'] * 3)
        img = np.frombuffer(buf, np.uint8).reshape(r['ph'], r['pw'], 3) if len(buf) == r['pw'] * r['ph'] * 3 else r['last']
        if img is None:
            continue
        r['last'] = img
        u = (t - b['start']) / max(0.01, b['end'] - b['start'])
        z = 1 + b['push'] * u                # a gentle push-in across the clip (1.00 -> 1.0 + push)
        cw, ch = r['pw'] / z, r['ph'] / z
        x0, y0 = (r['pw'] - cw) / 2, (r['ph'] - ch) / 2
        kx = r['w'] / cw
        M = np.float32([[kx, 0, -x0 * kx], [0, kx, -y0 * kx]])
        tile = cv2.warpAffine(img, M, (r['w'], r['h']), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        frame = frame.copy()
        if b['layout'] == 'full':
            f = b.get('fade', 0)
            k_in, k_out = (t - b['start']) / f if f else 1, (b['end'] - t) / f if f else 1
            al = min(1.0, k_in, k_out)
            if b.get('first') and t - b['start'] < f:
                al = 1.0      # never dissolve from the speaker at a join: only edges away from cuts fade
            frame[:] = tile if al >= 1 else (tile * al + frame * (1 - al)).astype(np.uint8)
        else:
            top = int(0.36 * OUT_H) - (OUT_H - r['h']) // 2 + 60      # keep the face in the lower panel
            top = min(max(0, top), r['h'])
            frame[r['h']:] = frame[top:top + OUT_H - r['h']].copy()
            frame[:r['h']] = tile
            frame[r['h'] - 3:r['h'] + 3] = 0          # a thin dark seam
    return frame


def render(plan_path, draft=False):
    import cv2
    p = json.load(open(plan_path))
    root = os.path.dirname(os.path.abspath(plan_path))
    fps = p['fps']
    os.makedirs(os.path.join(root, 'renders'), exist_ok=True)
    os.makedirs(os.path.join(root, 'cache'), exist_ok=True)
    look = dict(DEFAULT_LOOK)
    look.update(p.get('look', {}))
    ass = os.path.join(root, 'cache', 'captions.ass')
    build_ass(p, ass, look)
    wav = os.path.join(root, 'cache', 'mix.wav')
    build_audio(p, wav)

    sel = '+'.join(f'between(n,{fa},{fb - 1})' for fa, fb in p['segments'])
    dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', p['source'], '-vf',
                            f"select='{sel}',scale={WORK_W}:{WORK_H}:flags=area,format=rgb24",
                            '-fps_mode', 'passthrough', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    grade = 'eq=contrast=1.06:saturation=1.07:gamma=0.98,vignette=angle=0.42,' if p.get('grade', True) else ''
    if p.get('grain', 0):
        grade += f"noise=alls={p['grain']}:allf=t,"
    ef = p.get('end_fade', 0)
    total_t = sum(fb - fa for fa, fb in p['segments']) / fps + p.get('pad', 0)
    fade_v = f",fade=t=out:st={total_t - ef:.3f}:d={ef:.3f}" if ef else ''
    out = os.path.join(root, 'renders', f"{p['name']}{'-draft' if draft else ''}.mp4")
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                            '-s', f'{OUT_W}x{OUT_H}', '-r', f'{fps:.6f}', '-i', '-', '-i', wav,
                            '-vf', f"{grade}ass={ass}{fade_v},format=yuv420p",
                            '-c:v', 'libx264', '-preset', 'veryfast' if draft else 'medium',
                            '-crf', '23' if draft else '17', '-c:a', 'aac', '-b:a', '256k', '-ar', str(SR),
                            '-movflags', '+faststart', '-shortest', out], stdin=subprocess.PIPE)
    readers = {}
    fsize = WORK_W * WORK_H * 3
    n_src = sum(fb - fa for fa, fb in p['segments'])
    n_total = n_src + int(round(p.get('pad', 0) * fps))
    img = None
    for i in range(n_total):
        if i < n_src:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                print(f'warning: source ran out at output frame {i}/{n_src}')
                break
            img = np.frombuffer(buf, np.uint8).reshape(WORK_H, WORK_W, 3)
        # past the source (end pad) the last frame stays under the closing cutaway
        t = i / fps
        s = shot_at(p['shots'], t)
        u = ease(min(1, max(0, (t - s['start']) / max(0.001, s['end'] - s['start']))))
        if s.get('linear'):      # constant-speed push, capped, carried through jump cuts
            z = s['zoom'] * (1 + min(s['cap'], s['push'] * (t - s['start'])))
        else:
            z = s['zoom'] * (1 + s['push'] * u if s['push'] > 0 else 1 - s['push'] * (1 - u))
        cw, ch = WORK_W / z, WORK_H / z
        fx, fy = s['face'][0] * WORK_W, s['face'][1] * WORK_H
        x0 = min(max(0, fx - 0.5 * cw), WORK_W - cw)
        y0 = min(max(0, fy - 0.36 * ch), WORK_H - ch)
        k = OUT_W / cw
        M = np.float32([[k, 0, -x0 * k], [0, k, -y0 * k]])
        frame = cv2.warpAffine(img, M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR if k >= 0.75 else cv2.INTER_AREA,
                               borderMode=cv2.BORDER_REPLICATE)
        frame = composite_broll(p, t, frame, readers, fps)
        enc.stdin.write(frame.tobytes())
        if i % 600 == 0:
            print(f'  frame {i}/{n_total}', flush=True)
    enc.stdin.close(); enc.wait(); dec.terminate()
    print(f'render: {out}')
    return out


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 3 or argv[1] not in ('plan', 'render'):
        print(__doc__); sys.exit(1)
    if argv[1] == 'plan':
        plan(argv[2])
    else:
        render(argv[2], draft='--draft' in argv)


if __name__ == '__main__':
    main()
