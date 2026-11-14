#!/usr/bin/env python3
"""Run a whole batch of reels with one command: assemble, compose, render, gate, deliver.

usage: reel_batch.py <batch.json> [--only r02,r05] [--force] [--stop-on-fail]

batch.json (paths are relative to the batch file):
  {
    "takes": "takes/", "transcripts": "tx/", "out": "reels/",
    "preset": "presets/client.json",
    "prepare": ["python3 tools/cutout.py {reel}"],          optional, after assembly
    "compose": "python3 tools/build.py {reel}",             optional, writes {reel}/out/index.html
    "render": "npx hyperframes render -o {render} -q high --quiet",   run inside {reel}/out
    "deliver": false,                                       true hands passing reels to scripts/deliver.py
    "gate_args": [],                                        extra first_pass_gate.py options
    "reels": [{"id": "r02", "name": "agencies", "version": "v1",
               "cut": {"pieces": [...]}, "script": "optional exact words"}]
  }

Each reel goes through the steps in order and stops at its first failure; the others carry on.
A step is skipped when its output is newer than its inputs, so a re-run only redoes what changed.
Without "compose" the assembled base.mp4 is the render. The gate always runs, with the words the
cut was meant to say (or "script"), the edit sheet if the composer wrote {reel}/edit.json, and
the composition. Nothing is delivered on a failed gate.

Writes <out>/batch-status.json and prints one line per reel. Exit code 1 if any reel failed.
"""
import argparse, json, os, shlex, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
ASSEMBLE = os.path.join(HERE, 'assemble_takes.py')
GATE = os.path.join(ROOT, '.claude', 'skills', 'edit-qc', 'scripts', 'first_pass_gate.py')
DELIVER = os.path.join(ROOT, 'scripts', 'deliver.py')


def newer(target, *sources):
    if not os.path.exists(target): return False
    t = os.path.getmtime(target)
    return all(not os.path.exists(s) or os.path.getmtime(s) <= t for s in sources)


def sh(cmd, cwd, log):
    with open(log, 'a', encoding='utf-8') as f:
        f.write(f'\n$ {cmd if isinstance(cmd, str) else " ".join(cmd)}\n'); f.flush()
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), stdout=f, stderr=subprocess.STDOUT)
    return r.returncode


def one(reel, B, base, force):
    rid = reel['id']; version = reel.get('version', 'v1')
    d = os.path.join(base, B.get('out', 'reels'), rid); os.makedirs(d, exist_ok=True)
    log = os.path.join(d, 'batch.log')
    P = lambda p: os.path.join(base, p)
    q = shlex.quote
    render = os.path.join(d, f'{rid}-{version}.mp4')
    fill = lambda s: s.replace('{reel}', q(d)).replace('{render}', q(render)).replace('{id}', rid)
    st = {'id': rid, 'name': reel.get('name', ''), 'render': render, 'step': 'assemble', 'ok': False}

    cut = os.path.join(d, 'cut.json')
    want = json.dumps(reel['cut'], sort_keys=True) if isinstance(reel['cut'], dict) else open(P(reel['cut'])).read()
    if not os.path.exists(cut) or open(cut).read() != want: open(cut, 'w').write(want)
    base_mp4 = os.path.join(d, 'base.mp4')
    preset = P(B['preset']) if B.get('preset') else None
    if force or not newer(base_mp4, cut, *( [preset] if preset else [])):
        cmd = [sys.executable, ASSEMBLE, cut, d, '--takes', P(B['takes']), '--transcripts', P(B['transcripts'])]
        if preset: cmd += ['--preset', preset]
        if sh(cmd, base, log) != 0: return st
    edl = json.load(open(os.path.join(d, 'edl.json')))
    st['tight_cuts'] = len(edl.get('tight_cuts', [])); st['held_frame_s'] = edl.get('held_frame_s', 0)

    if B.get('compose'):
        index = os.path.join(d, 'out', 'index.html')
        if force or not newer(render, base_mp4):
            for step, cmds in (('prepare', B.get('prepare', [])), ('compose', [B['compose']])):
                st['step'] = step
                for c in cmds:
                    if sh(fill(c), base, log) != 0: return st
            if not os.path.exists(index): st['step'] = 'compose'; st['why'] = 'no out/index.html'; return st
            st['step'] = 'render'
            if sh(fill(B.get('render', 'npx hyperframes render -o {render} -q high --quiet')), os.path.join(d, 'out'), log) != 0: return st
        if not os.path.exists(render): st['step'] = 'render'; return st
    else:
        render = st['render'] = base_mp4

    st['step'] = 'gate'
    qa = os.path.join(d, 'qa'); verdict = os.path.join(qa, 'first-pass.json')
    if force or not newer(verdict, render):
        expect = os.path.join(d, 'expect.txt')
        if reel.get('script'): open(expect, 'w', encoding='utf-8').write(reel['script'] + '\n')
        cmd = [sys.executable, GATE, render, '--out', qa, '--expect', expect]
        cmd += B.get('gate_args', [])
        if preset: cmd += ['--preset', preset]
        sheet = os.path.join(d, 'edit.json')
        if not os.path.exists(sheet):       # the cut's joins still sharpen the cut checks
            json.dump({'joins': edl.get('joins', []), 'words': json.load(open(os.path.join(d, 'words.json')))}, open(sheet, 'w'))
        cmd += ['--edit', sheet]
        if os.path.exists(os.path.join(d, 'out', 'index.html')): cmd += ['--composition', os.path.join(d, 'out', 'index.html')]
        sh(cmd, base, log)
    if not os.path.exists(verdict): st['why'] = 'gate did not run'; return st
    g = json.load(open(verdict))
    st['gate'] = g.get('verdict')
    st['fails'] = [c.get('check', '') for c in g.get('checks', []) if c.get('result') == 'FAIL']
    if st['gate'] == 'FAIL': return st

    if B.get('deliver'):
        st['step'] = 'deliver'
        out = os.path.join(base, B.get('deliver_to', 'deliver'))
        name = f"{rid}-{reel['name']}" if reel.get('name') else rid
        if not any(f.startswith(f'{name}-{version}') for f in (os.listdir(out) if os.path.isdir(out) else [])):
            if sh([sys.executable, DELIVER, render, '--id', name, '--version', version, '--out', out, '--gate', verdict], base, log) != 0: return st
    st['ok'] = True; st['step'] = 'done'
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('batch'); ap.add_argument('--only'); ap.add_argument('--force', action='store_true')
    ap.add_argument('--stop-on-fail', action='store_true')
    a = ap.parse_args()
    B = json.load(open(a.batch, encoding='utf-8')); base = os.path.dirname(os.path.abspath(a.batch))
    only = set(a.only.split(',')) if a.only else None
    results, t0 = [], time.time()
    for reel in B['reels']:
        if only and reel['id'] not in only: continue
        t = time.time()
        st = one(reel, B, base, a.force); st['seconds'] = round(time.time() - t, 1)
        results.append(st)
        extra = ''
        if st.get('fails'): extra = ' fails: ' + ', '.join(st['fails'])
        if st.get('tight_cuts'): extra += f" tight cuts: {st['tight_cuts']}"
        if st.get('held_frame_s', 0) > 0.1: extra += f" held end frame: {st['held_frame_s']}s"
        print(f"{st['id']:<8} {'PASS' if st['ok'] else 'STOPPED at ' + st['step']:<22} {st['seconds']:>6}s{extra}", flush=True)
        if a.stop_on_fail and not st['ok']: break
    out = os.path.join(base, B.get('out', 'reels')); os.makedirs(out, exist_ok=True)
    json.dump({'reels': results, 'seconds': round(time.time() - t0, 1)}, open(os.path.join(out, 'batch-status.json'), 'w'), indent=1)
    bad = [r for r in results if not r['ok']]
    print(f"{len(results) - len(bad)} of {len(results)} passed. Logs: <out>/<id>/batch.log")
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
