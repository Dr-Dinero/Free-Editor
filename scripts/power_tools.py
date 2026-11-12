#!/usr/bin/env python3
"""Free Editor power tools: one command per job, all free and open source.

    npm run tools -- align   <media> [--transcript t.json] -o words.json
    npm run tools -- speech  <media> -o speech.json
    npm run tools -- scenes  <media> -o scenes.json
    npm run tools -- reframe <media> -o track.json [--render out.mp4]
    npm run tools -- clean-voice <media> -o voice.wav
    npm run tools -- loudness <media> -o out.mp4 [--lufs -14]
    npm run tools -- duck    <video> <music> -o out.mp4 [--under 18]
    npm run tools -- cutout  <image> -o subject.png
    npm run tools -- check

Each tool is imported only when its command runs, so a missing optional package
breaks only that command. Install them with:
    python3 -m pip install -r requirements-power.txt

Licenses: WhisperX BSD-2, Silero VAD MIT, PySceneDetect BSD-3, MediaPipe Apache-2,
Demucs MIT, ffmpeg-normalize MIT, rembg MIT. See docs/POWER-TOOLS.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

CACHE = Path(os.environ.get('FREE_EDITOR_CACHE', Path.home() / '.cache' / 'free-editor'))


def die(msg):
    sys.exit(f'power-tools: {msg}')


def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        die(f'command failed ({r.returncode}): {" ".join(map(str, cmd[:6]))} ...')
    return r


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                          'stream=codec_type,width,height,r_frame_rate:format=duration',
                          '-of', 'json', str(path)], capture_output=True, text=True)
    if out.returncode:
        die(f'cannot read {path}')
    d = json.loads(out.stdout)
    v = next((s for s in d['streams'] if s['codec_type'] == 'video'), None)
    info = {'duration': float(d['format'].get('duration', 0))}
    if v:
        n, m = v['r_frame_rate'].split('/')
        info.update(width=int(v['width']), height=int(v['height']), fps=float(n) / float(m or 1))
    return info


def wav16k(media, tmp):
    """Mono 16 kHz WAV, the input every speech model here expects."""
    out = Path(tmp) / 'audio16k.wav'
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(media), '-vn', '-ac', '1', '-ar', '16000', str(out)])
    return out


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1))
    print(f'wrote {path}')


# --- align: word timestamps that sit on the audio (WhisperX) -----------------

def cmd_align(a):
    import whisperx  # BSD-2
    import nltk  # WhisperX splits sentences with NLTK's punkt tokenizer; fetch it once
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        nltk.download('punkt_tab', quiet=True)
    device = 'cuda' if _cuda() else 'cpu'
    with tempfile.TemporaryDirectory() as tmp:
        audio = whisperx.load_audio(str(wav16k(a.media, tmp)))
    if a.transcript:
        # Re-time an existing transcript (Scribe, whisper.cpp, edited text) instead of re-transcribing.
        src = json.load(open(a.transcript))
        ws = src['words'] if isinstance(src, dict) else src
        ws = [w for w in ws if w.get('type', 'word') == 'word']
        segments, cur = [], []
        for w in ws:  # group into ~sentence segments; alignment works per segment
            cur.append(w)
            if w['text'].rstrip().endswith(('.', '?', '!')) or len(cur) >= 30:
                segments.append(cur)
                cur = []
        if cur:
            segments.append(cur)
        segs = [{'start': float(s[0]['start']), 'end': float(s[-1]['end']),
                 'text': ' '.join(w['text'].strip() for w in s)} for s in segments]
        lang = a.language or 'en'
    else:
        model = whisperx.load_model(a.model, device, compute_type='int8' if device == 'cpu' else 'float16',
                                    language=a.language)
        res = model.transcribe(audio, batch_size=8)
        segs, lang = res['segments'], res.get('language', a.language or 'en')
    align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
    out = whisperx.align(segs, align_model, meta, audio, device, return_char_alignments=False)
    words, last = [], 0.0
    for seg in out['segments']:
        for w in seg.get('words', []):
            if 'start' not in w:  # numbers/symbols the aligner could not place: borrow neighbours
                w['start'], w['end'] = last, last + 0.05
            words.append({'type': 'word', 'text': w['word'], 'start': round(w['start'], 3),
                          'end': round(w['end'], 3), 'score': round(w.get('score', 0), 3)})
            last = w['end']
    write_json(a.out, {'language': lang, 'source': 'whisperx', 'words': words})
    low = sum(1 for w in words if w['score'] < 0.4)
    print(f'{len(words)} words aligned; {low} low-confidence (check those captions by ear)')


def _cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


# --- speech: where speech really is (Silero VAD) ------------------------------

def cmd_speech(a):
    from silero_vad import load_silero_vad, read_audio, get_speech_timestamps  # MIT
    model = load_silero_vad()
    with tempfile.TemporaryDirectory() as tmp:
        wav = read_audio(str(wav16k(a.media, tmp)), sampling_rate=16000)
    ts = get_speech_timestamps(wav, model, sampling_rate=16000, return_seconds=True,
                               threshold=a.threshold, min_silence_duration_ms=a.min_silence,
                               speech_pad_ms=a.pad)
    regions = [{'start': round(t['start'], 3), 'end': round(t['end'], 3)} for t in ts]
    gaps = [{'start': regions[i]['end'], 'end': regions[i + 1]['start'],
             'length': round(regions[i + 1]['start'] - regions[i]['end'], 3)}
            for i in range(len(regions) - 1)]
    write_json(a.out, {'source': 'silero-vad', 'pad_ms': a.pad, 'speech': regions, 'gaps': gaps})
    print(f'{len(regions)} speech regions, {sum(g["length"] for g in gaps):.1f}s of gaps')


# --- scenes: shot changes (PySceneDetect) -------------------------------------

def cmd_scenes(a):
    from scenedetect import detect, AdaptiveDetector, ContentDetector  # BSD-3
    det = AdaptiveDetector() if a.adaptive else ContentDetector(threshold=a.threshold)
    scenes = detect(str(a.media), det, show_progress=False)
    cuts = [{'start': round(s.get_seconds(), 3), 'end': round(e.get_seconds(), 3)} for s, e in scenes]
    if not cuts:
        cuts = [{'start': 0.0, 'end': round(probe(a.media)['duration'], 3)}]
    write_json(a.out, {'source': 'pyscenedetect', 'shots': cuts})
    print(f'{len(cuts)} shots')


# --- reframe: keep the face centred in a 9:16 crop (MediaPipe) ----------------

FACE_MODEL = ('https://storage.googleapis.com/mediapipe-models/face_detector/'
              'blaze_face_short_range/float16/1/blaze_face_short_range.tflite')


def _face_model():
    path = CACHE / 'blaze_face_short_range.tflite'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print('downloading MediaPipe face model (230 KB, Apache-2)')
        urllib.request.urlretrieve(FACE_MODEL, path)
    return path


def cmd_reframe(a):
    import cv2
    import mediapipe as mp  # Apache-2
    from mediapipe.tasks.python import vision, BaseOptions
    info = probe(a.media)
    W, H = info['width'], info['height']
    cw = min(W, int(round(H * a.aspect / 2)) * 2)
    ch = min(H, int(round(cw / a.aspect / 2)) * 2)
    det = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(_face_model())), min_detection_confidence=0.5))
    cap = cv2.VideoCapture(str(a.media))
    step = max(1, int(round(info['fps'] / a.sample_fps)))
    raw, i = [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            _, frame = cap.retrieve()
            # The detector sees a 128 px square, so a face in a wide frame is tiny. Scan
            # overlapping square tiles across the frame and keep the most confident face.
            side = min(W, H)
            n = max(1, -(-max(W, H) * 2 // side) - 1)
            best, t = None, i / info['fps']
            for k in range(n):
                off = 0 if n == 1 else round(k * (max(W, H) - side) / (n - 1))
                x0, y0 = (off, 0) if W >= H else (0, off)
                tile = cv2.resize(frame[y0:y0 + side, x0:x0 + side], (384, 384))
                img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(tile, cv2.COLOR_BGR2RGB))
                for f in det.detect(img).detections:
                    score = f.categories[0].score if f.categories else 0
                    if best is None or score > best[0]:
                        b, sc = f.bounding_box, side / 384
                        best = (score, x0 + (b.origin_x + b.width / 2) * sc, y0 + (b.origin_y + b.height / 2) * sc)
            if best:
                raw.append((t, best[1], best[2]))
            else:
                raw.append((t, None, None))
        i += 1
    cap.release()
    det.close()
    seen = [r for r in raw if r[1] is not None]
    if not seen:
        die('no face found; use a fixed centre crop instead')
    # Calm camera: fill gaps, then only move when the face leaves a dead zone, eased.
    cx, cy, path = seen[0][1], seen[0][2], []
    dead = cw * a.dead_zone
    tx = cx
    for t, fx, fy in raw:
        if fx is not None and abs(fx - tx) > dead:
            tx = fx
        cx += (tx - cx) * a.smooth
        x = min(max(cx - cw / 2, 0), W - cw)
        y = min(max((fy or cy) - ch * a.eye_line, 0), H - ch) if ch < H else 0
        path.append({'t': round(t, 3), 'x': int(x) // 2 * 2, 'y': int(y) // 2 * 2})
    write_json(a.out, {'source': 'mediapipe', 'crop_w': cw, 'crop_h': ch, 'src_w': W, 'src_h': H,
                       'faces_found': len(seen), 'samples': len(raw), 'path': path})
    if a.render:
        cmds = Path(a.out).with_suffix('.sendcmd')
        cmds.write_text(''.join(f"{p['t']} crop x {p['x']}, crop y {p['y']};\n" for p in path))
        x0, y0 = path[0]['x'], path[0]['y']
        vf = (f"sendcmd=f='{cmds}',crop={cw}:{ch}:{x0}:{y0},scale={a.out_w}:-2:flags=lanczos")
        run(['ffmpeg', '-v', 'error', '-y', '-i', str(a.media), '-vf', vf, '-c:v', 'libx264',
             '-crf', '17', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-c:a', 'copy', str(a.render)])
        print(f'wrote {a.render}')


# --- clean-voice: lift the voice out of music and room noise (Demucs) ---------

def cmd_clean_voice(a):
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'in.wav'
        run(['ffmpeg', '-v', 'error', '-y', '-i', str(a.media), '-vn', '-ac', '2', '-ar', '44100', str(wav)])
        run([sys.executable, '-m', 'demucs', '--two-stems', 'vocals', '-n', a.model,
             '-o', tmp, '--filename', '{stem}.{ext}', str(wav)])
        vocals = next(Path(tmp).rglob('vocals.wav'))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(vocals, a.out)
    print(f'wrote {a.out} (voice only; compare against the original before using it)')


# --- loudness: every upload at the same level (ffmpeg-normalize) --------------

def cmd_loudness(a):
    exe = shutil.which('ffmpeg-normalize') or die('ffmpeg-normalize missing: pip install ffmpeg-normalize')
    cmd = [exe, str(a.media), '-o', str(a.out), '-f', '-nt', 'ebu', '-t', str(a.lufs), '-tp', str(a.peak),
           '-lrt', '11', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000']
    if probe(a.media).get('width'):
        cmd += ['-c:v', 'copy']
    run(cmd)
    print(f'wrote {a.out} at {a.lufs} LUFS integrated, {a.peak} dBTP peak')


# --- duck: music that dips under the voice (FFmpeg sidechain) -----------------

def cmd_duck(a):
    dur = probe(a.video)['duration']
    fade = min(1.5, dur / 4)
    fc = (f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{dur},volume=-{a.under}dB,"
          f"afade=t=in:d=0.6,afade=t=out:st={dur - fade}:d={fade}[m];"
          f"[0:a]asplit=2[v][key];"
          f"[m][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350:makeup=1[md];"
          f"[v][md]amix=inputs=2:duration=first:normalize=0[a]")
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(a.video), '-i', str(a.music), '-filter_complex', fc,
         '-map', '0:v?', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', str(a.out)])
    print(f'wrote {a.out}: music {a.under} dB under, ducking further while speaking')


# --- cutout: subject on transparent background for covers (rembg) -------------

def cmd_cutout(a):
    from rembg import remove, new_session  # MIT
    from PIL import Image
    img = Image.open(a.image).convert('RGB')
    out = remove(img, session=new_session(a.model), alpha_matting=a.matting)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    out.save(a.out)
    print(f'wrote {a.out}')


# --- check --------------------------------------------------------------------

def cmd_check(_):
    rows = [('whisperx', 'align'), ('silero_vad', 'speech'), ('scenedetect', 'scenes'),
            ('mediapipe', 'reframe'), ('demucs', 'clean-voice'), ('rembg', 'cutout')]
    bad = 0
    for mod, cmd in rows:
        try:
            m = __import__(mod)
            print(f'ok   {cmd:12} {mod} {getattr(m, "__version__", "")}')
        except Exception as e:
            bad += 1
            print(f'MISS {cmd:12} {mod}: {type(e).__name__}')
    for exe, cmd in [('ffmpeg-normalize', 'loudness'), ('ffmpeg', 'duck')]:
        ok = shutil.which(exe)
        bad += not ok
        print(f'{"ok  " if ok else "MISS"} {cmd:12} {exe}')
    lottie = Path(__file__).resolve().parent.parent / 'node_modules/lottie-web/build/player/lottie.min.js'
    print(f'{"ok  " if lottie.exists() else "MISS"} {"lottie":12} lottie-web (npm ci)')
    bad += not lottie.exists()
    sys.exit(1 if bad else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('align', help='word timestamps on the audio (WhisperX)')
    s.add_argument('media'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--transcript', help='re-time this transcript instead of transcribing')
    s.add_argument('--model', default='small.en'); s.add_argument('--language')
    s.set_defaults(fn=cmd_align)

    s = sub.add_parser('speech', help='speech regions and gaps (Silero VAD)')
    s.add_argument('media'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--threshold', type=float, default=0.5)
    s.add_argument('--min-silence', type=int, default=250, help='ms')
    s.add_argument('--pad', type=int, default=80, help='ms kept either side of speech')
    s.set_defaults(fn=cmd_speech)

    s = sub.add_parser('scenes', help='shot boundaries (PySceneDetect)')
    s.add_argument('media'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--threshold', type=float, default=27.0); s.add_argument('--adaptive', action='store_true')
    s.set_defaults(fn=cmd_scenes)

    s = sub.add_parser('reframe', help='face-following vertical crop (MediaPipe)')
    s.add_argument('media'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--render', help='also write the reframed video here')
    s.add_argument('--aspect', type=float, default=9 / 16)
    s.add_argument('--sample-fps', type=float, default=6)
    s.add_argument('--dead-zone', type=float, default=0.12, help='fraction of crop width the face may drift')
    s.add_argument('--smooth', type=float, default=0.15, help='0-1, lower is calmer')
    s.add_argument('--eye-line', type=float, default=0.38, help='face centre height in the crop')
    s.add_argument('--out-w', type=int, default=1080)
    s.set_defaults(fn=cmd_reframe)

    s = sub.add_parser('clean-voice', help='voice-only stem (Demucs)')
    s.add_argument('media'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--model', default='htdemucs')
    s.set_defaults(fn=cmd_clean_voice)

    s = sub.add_parser('loudness', help='EBU R128 loudness (ffmpeg-normalize)')
    s.add_argument('media'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--lufs', type=float, default=-14); s.add_argument('--peak', type=float, default=-1)
    s.set_defaults(fn=cmd_loudness)

    s = sub.add_parser('duck', help='music bed ducked under the voice (FFmpeg)')
    s.add_argument('video'); s.add_argument('music'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--under', type=float, default=18, help='dB below the voice before ducking')
    s.set_defaults(fn=cmd_duck)

    s = sub.add_parser('cutout', help='subject cut-out PNG (rembg)')
    s.add_argument('image'); s.add_argument('-o', '--out', required=True)
    s.add_argument('--model', default='u2net_human_seg', help='or isnet-general-use, birefnet-portrait')
    s.add_argument('--matting', action='store_true', help='finer hair edges, slower')
    s.set_defaults(fn=cmd_cutout)

    sub.add_parser('check', help='which tools are installed').set_defaults(fn=cmd_check)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
