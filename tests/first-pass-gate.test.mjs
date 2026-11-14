import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.platform === 'win32' ? 'py' : 'python3';
const gate = join(root, '.claude/skills/edit-qc/scripts/first_pass_gate.py');
const deliver = join(root, 'scripts/deliver.py');
const ready = !spawnSync(python, ['-c', 'import numpy']).status && !spawnSync('ffmpeg', ['-version']).error;
const skip = !ready && 'needs Python 3 with numpy, and ffmpeg';
const dir = mkdtempSync(join(tmpdir(), 'gate-'));
const preset = join(dir, 'preset.json');
writeFileSync(preset, JSON.stringify({ format: { width: 180, height: 320, fps: [30] }, look: { banned_hues: [[200, 290]] } }));

function clip(name, { size = '180x320', volume = '0.5', black = false } = {}) {
  const out = join(dir, name);
  const fade = black ? ",drawbox=enable='between(t,1,1.1)':color=black:t=fill" : '';
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', `testsrc2=s=${size}:r=30:d=3`, '-f', 'lavfi', '-i', 'anoisesrc=d=3:c=pink:a=0.5',
    '-vf', `format=yuv420p${fade}`, '-af', `volume=${volume},afade=t=out:st=2.6:d=0.4`, '-c:v', 'libx264', '-c:a', 'aac', '-shortest', out], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  return out;
}
function run(video, extra = []) {
  const r = spawnSync(python, [gate, video, '--preset', preset, '--no-asr', '--json', '--out', join(dir, 'qa-' + Math.random().toString(36).slice(2)), ...extra], { encoding: 'utf8' });
  const j = JSON.parse(r.stdout);
  return { status: r.status, verdict: j.verdict, by: Object.fromEntries(j.checks.map((c) => [c.check, c])) };
}

test('gate fails a wrong frame size and a black frame', { skip }, () => {
  const wrong = run(clip('wrong.mp4', { size: '320x180' }));
  assert.equal(wrong.by.specs.result, 'FAIL');
  assert.equal(wrong.status, 1);
  const black = run(clip('black.mp4', { black: true }));
  assert.equal(black.by.glitches.result, 'FAIL');
});

test('gate fails quiet audio', { skip }, () => {
  assert.equal(run(clip('quiet.mp4', { volume: '0.01' })).by.loudness.result, 'FAIL');
});

test('gate catches a wrong number and passes spelling differences', { skip }, () => {
  const v = clip('words.mp4');
  const heard = join(dir, 'heard.json'); const script = join(dir, 'script.txt');
  const words = (t) => t.split(' ').map((text, i) => ({ text, start: i * 0.2, end: i * 0.2 + 0.15 }));
  writeFileSync(script, 'at Green Side we start for $297 a month then two or three thousand dollars on ads');
  writeFileSync(heard, JSON.stringify(words('at Greenside we start for $200 a month then $2,000 or $3,000 on app')));
  const bad = run(v, ['--transcript', heard, '--expect', script]).by.words;
  assert.equal(bad.result, 'FAIL');
  assert.match(bad.detail, /297/); assert.match(bad.detail, /ads/);
  assert.doesNotMatch(bad.detail, /green/i); assert.doesNotMatch(bad.detail, /thousand/);
  writeFileSync(heard, JSON.stringify(words('at Greenside we start for $297 a month then $2,000 or $3,000 on ads')));
  assert.equal(run(v, ['--transcript', heard, '--expect', script]).by.words.result, 'PASS');
});

test('gate fails a late overlay and a banned colour', { skip }, () => {
  const v = clip('edit.mp4');
  const edit = join(dir, 'edit.json'); const comp = join(dir, 'index.html');
  writeFileSync(edit, JSON.stringify({ overlays: [{ id: 'price', anchor: 1.0, start: 1.4 }, { id: 'ok', anchor: 2.0, start: 1.95 }] }));
  writeFileSync(comp, '<style>.a{color:#3b5bff}.b{color:#ff3b4f}#cam video{filter:contrast(1.2) saturate(1.3)}</style>');
  const r = run(v, ['--edit', edit, '--composition', comp]);
  assert.equal(r.by.overlays.result, 'FAIL'); assert.match(r.by.overlays.detail, /price/); assert.doesNotMatch(r.by.overlays.detail, /ok arrives/);
  assert.equal(r.by.look.result, 'FAIL'); assert.match(r.by.look.detail, /3b5bff/); assert.match(r.by.look.detail, /grade/);
  assert.doesNotMatch(r.by.look.detail, /ff3b4f/);
});

test('deliver refuses a failed gate, never overwrites, and parts join back to the same bytes', { skip }, () => {
  const v = clip('final.mp4');
  const out = join(dir, 'deliver');
  const d = (extra) => spawnSync(python, [deliver, v, '--id', 'reel-07', '--version', 'v1', '--out', out, '--part-mb', '0.02', ...extra], { encoding: 'utf8' });
  const gateFile = join(dir, 'fp.json');
  assert.notEqual(d([]).status, 0, 'no gate result');
  writeFileSync(gateFile, JSON.stringify({ verdict: 'FAIL', render: v, checks: [{ check: 'words', result: 'FAIL', detail: 'x' }] }));
  assert.match(d(['--gate', gateFile]).stderr, /blocked/);
  writeFileSync(gateFile, JSON.stringify({ verdict: 'PASS', render: v, checks: [] }));
  const ok = d(['--gate', gateFile]);
  assert.equal(ok.status, 0, ok.stderr);
  const m = JSON.parse(ok.stdout);
  assert.ok(m.parts.length > 1);
  assert.match(d(['--gate', gateFile]).stderr, /already exists/);
  const j = spawnSync('sh', [join(out, 'reel-07', m.join)], { encoding: 'utf8' });
  assert.equal(j.status, 0, j.stdout + j.stderr);
  assert.ok(readFileSync(join(out, 'reel-07', m.file)).equals(readFileSync(v)));
  assert.ok(existsSync(join(out, 'reel-07', m.review_copy)));
});
