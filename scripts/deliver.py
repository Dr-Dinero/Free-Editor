#!/usr/bin/env python3
"""Package a finished render for hand-off: gate check, unique name, review copy, safe-size parts.

    python3 scripts/deliver.py <render.mp4> --id reel-07 --version v2 [--out deliver/]
            [--gate qa/first-pass.json] [--no-gate "reason"] [--part-mb 9] [--proxy-mb 20] [--dest "Movies/Client/reels"]

What it guarantees:
  - nothing ships that failed the first-pass gate (or the reason is written down)
  - every version gets its own filename, and an existing file is never overwritten
  - the delivered bytes are the rendered bytes: no re-encode, no remux, so checksums match
  - a file too big for one transfer is split into parts with a manifest and a join script that
    verifies the checksum after joining
  - a small review copy is made for web review pages
Writes <out>/<id>/<id>-<version>.mp4 (or .partNN files), review copy, join.sh and delivery.json.
"""
import hashlib, json, os, shutil, subprocess, sys, time


def digest(path, algo):
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0 if a else 1)
    src = a[0]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    vid, ver = opt('--id'), opt('--version')
    if not vid or not ver:
        sys.exit('deliver: --id and --version are required (for example --id reel-07 --version v2)')
    gate = opt('--gate', os.path.join(os.path.dirname(os.path.abspath(src)), 'qa', 'first-pass.json'))
    verdict = None
    if opt('--no-gate'):
        verdict = 'SKIPPED: ' + opt('--no-gate')
    elif not os.path.exists(gate):
        sys.exit(f'deliver: no gate result at {gate}. Run `npm run gate -- {src}` first, or pass --no-gate "<reason>".')
    else:
        g = json.load(open(gate))
        if os.path.abspath(g.get('render', src)) != os.path.abspath(src) and os.path.basename(g.get('render', '')) != os.path.basename(src):
            sys.exit(f"deliver: {gate} is the gate result for {g.get('render')}, not for this render. Run the gate on this file.")
        if os.path.getmtime(gate) < os.path.getmtime(src):
            sys.exit('deliver: the render is newer than its gate result. Run the gate again.')
        verdict = g['verdict']
        if verdict == 'FAIL':
            fails = [c['check'] + ': ' + c['detail'] for c in g['checks'] if c['result'] == 'FAIL']
            sys.exit('deliver: blocked, the first-pass gate failed:\n  ' + '\n  '.join(fails))
    out = os.path.join(opt('--out', 'deliver'), vid); os.makedirs(out, exist_ok=True)
    name = f'{vid}-{ver}.mp4'
    final = os.path.join(out, name)
    if os.path.exists(final) or os.path.exists(final + '.part00'):
        sys.exit(f'deliver: {name} already exists. Use a new --version; delivered files are never overwritten.')
    shutil.copyfile(src, final)
    size = os.path.getsize(final); md5 = digest(final, 'md5'); sha = digest(final, 'sha256')

    # review copy for web review pages
    limit = float(opt('--proxy-mb', 20)) * 1024 * 1024
    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration',
                         '-of', 'json', final], capture_output=True, text=True)
    info = json.loads(pr.stdout or '{}'); st = (info.get('streams') or [{}])[0]
    dur = float(info.get('format', {}).get('duration') or 0)
    vertical = st.get('height', 1) >= st.get('width', 1)
    proxy = os.path.join(out, f'{vid}__{ver}__review.mp4')
    kbps = max(250, min(1400, int(limit * 8 * 0.9 / max(dur, 1) / 1000) - 64))
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', final, '-vf', ('scale=540:-2' if vertical else 'scale=854:-2') + ',fps=30',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '27', '-maxrate', f'{kbps}k', '-bufsize', f'{2 * kbps}k',
                        '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', proxy], capture_output=True, text=True)
    if r.returncode or not os.path.exists(proxy):
        proxy = None

    # parts for transfers with a size cap
    part = int(float(opt('--part-mb', 9)) * 1024 * 1024)
    parts = []
    if size > part:
        with open(final, 'rb') as f:
            i = 0
            while True:
                buf = f.read(part)
                if not buf:
                    break
                p = f'{name}.part{i:02d}'
                open(os.path.join(out, p), 'wb').write(buf)
                parts.append(dict(file=p, bytes=len(buf), md5=hashlib.md5(buf).hexdigest())); i += 1
        os.remove(final)
        open(os.path.join(out, f'join-{vid}-{ver}.sh'), 'w').write(f'''#!/bin/sh
# Joins the parts of {name} and checks the result is byte-for-byte the rendered file.
set -e
cd "$(dirname "$0")"
cat {' '.join(p['file'] for p in parts)} > "{name}.joining"
sum=$( (md5 -q "{name}.joining" 2>/dev/null) || md5sum "{name}.joining" | cut -d" " -f1 )
if [ "$sum" != "{md5}" ]; then echo "CHECKSUM MISMATCH for {name}: got $sum, want {md5}. Copy the parts again."; exit 1; fi
mv "{name}.joining" "{name}"
echo "OK {name} ({size} bytes, md5 {md5})"
''')
    manifest = dict(id=vid, version=ver, file=name, bytes=size, md5=md5, sha256=sha, seconds=round(dur, 2), gate=verdict,
                    parts=parts, join=f'join-{vid}-{ver}.sh' if parts else None,
                    review_copy=os.path.basename(proxy) if proxy else None,
                    review_copy_bytes=os.path.getsize(proxy) if proxy else None,
                    desk_row=dict(v=ver, file=name, path=(opt('--dest', '').rstrip('/') + '/' + name).lstrip('/')),
                    at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(manifest, open(os.path.join(out, f'delivery-{vid}-{ver}.json'), 'w'), indent=1)
    print(json.dumps(manifest, indent=1))


if __name__ == '__main__':
    main()
