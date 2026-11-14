import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, statSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.platform === 'win32' ? 'py' : 'python3';
const scripts = join(root, '.claude/skills/batch-reels/scripts');
const hasFfmpeg = !spawnSync('ffmpeg', ['-version']).error && !spawnSync(python, ['--version']).error;
const hasNumpy = hasFfmpeg && !spawnSync(python, ['-c', 'import numpy']).status;
const dir = mkdtempSync(join(tmpdir(), 'reels-'));
const takes = join(dir, 'takes'), tx = join(dir, 'tx');

// One landscape take. "leads" ends in a soft tail the transcript misses (it says 1.00, the voice
// runs to 1.25). "um" is a word to drop. "now" runs straight into "call" with no silence.
function makeTake() {
  mkdirSync(takes, { recursive: true }); mkdirSync(tx, { recursive: true });
  const voice = "0.5*sin(2*PI*220*t)*(between(t,0.5,1.0)+between(t,1.9,2.3)+between(t,3.0,4.0))+0.03*sin(2*PI*3000*t)*between(t,1.0,1.25)+0.0008*sin(2*PI*90*t)";
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=30:d=6', '-f', 'lavfi', '-i', `aevalsrc='${voice}':s=48000:d=6`,
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', join(takes, 'A.mp4')], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  writeFileSync(join(tx, 'A.json'), JSON.stringify({ words: [
    { text: 'leads', start: 0.5, end: 1.0 }, { text: 'um', start: 1.9, end: 2.3 },
    { text: 'now', start: 3.0, end: 3.5 }, { text: 'call', start: 3.5, end: 4.0 }] }));
}

test('cuts keep the soft end of a word, flag a cut with no silence, and end on live footage', { skip: !hasFfmpeg && 'needs Python 3 and ffmpeg' }, () => {
  makeTake();
  const cut = join(dir, 'cut.json'), out = join(dir, 'one');
  writeFileSync(cut, JSON.stringify({ pieces: [{ clip: 'A', from: 0, to: 2, drop: [1] }] }));
  const r = spawnSync(python, [join(scripts, 'assemble_takes.py'), cut, out, '--takes', takes, '--transcripts', tx, '--no-reframe'], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const edl = JSON.parse(readFileSync(join(out, 'edl.json'), 'utf8'));
  assert.equal(edl.segments.length, 2, 'the dropped word is cut out');
  assert.ok(edl.segments[0].out >= 1.24 && edl.segments[0].out < 1.9, `first cut at ${edl.segments[0].out} keeps the soft tail and stops before "um"`);
  assert.ok(edl.segments[1].in > 2.3 && edl.segments[1].in <= 3.0, 'second piece starts after "um"');
  assert.deepEqual(edl.tight_cuts.map((t) => [t.word, t.side]), [[2, 'out']], 'the cut between "now" and "call" has no silence');
  assert.match(r.stdout, /TIGHT CUT A word 2 "now"/);
  assert.equal(edl.held_frame_s, 0, 'the take is long enough for a live ending');
  assert.equal(readFileSync(join(out, 'expect.txt'), 'utf8').trim(), 'leads now');
  const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration', '-of', 'csv=p=0', join(out, 'base.mp4')], { encoding: 'utf8' }).stdout.trim().split(/\s+/);
  assert.equal(probe[0], '1080,1920', 'landscape take is cropped to the frame');
  assert.ok(Math.abs(Number(probe[1]) - edl.duration) < 0.12, `duration ${probe[1]} vs ${edl.duration}`);
  const hashes = spawnSync('ffmpeg', ['-v', 'error', '-ss', String(edl.duration - 0.5), '-i', join(out, 'base.mp4'), '-an', '-f', 'framemd5', '-'], { encoding: 'utf8' }).stdout
    .split('\n').filter((l) => l && !l.startsWith('#')).map((l) => l.split(',').pop().trim());
  assert.ok(new Set(hashes).size > hashes.length / 2, 'the last half second is moving footage, not one held frame');
});

test('a take that ends at the last word reports the held frame', { skip: !hasFfmpeg && 'needs Python 3 and ffmpeg' }, () => {
  const cut = join(dir, 'cut2.json'), out = join(dir, 'two');
  writeFileSync(cut, JSON.stringify({ pieces: [{ clip: 'A', from: 0, to: 0, out: 5.9 }] }));
  const r = spawnSync(python, [join(scripts, 'assemble_takes.py'), cut, out, '--takes', takes, '--transcripts', tx, '--no-reframe', '--plan-only'], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const r2 = spawnSync(python, [join(scripts, 'assemble_takes.py'), cut, out, '--takes', takes, '--transcripts', tx, '--no-reframe'], { encoding: 'utf8' });
  assert.match(r2.stdout, /ENDING holds one frame/);
});

test('overlay anchors resolve to the edited timeline and land in the edit sheet', { skip: !hasFfmpeg && 'needs Python 3' }, () => {
  const words = join(dir, 'words.json'), piece = join(dir, 'piece.html');
  writeFileSync(words, JSON.stringify([{ clip: 'B1', i: 3, text: 'trust', start: 1.2, end: 1.5 }]));
  writeFileSync(piece, '<div id="late" class="clip" data-start="{{W:B1:3+0.7}}" data-duration="1"></div>');
  const r = spawnSync(python, [join(scripts, 'piece_timing.py'), words, '10', piece], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout).overlays, [{ id: 'late', word: 'trust', anchor: 1.2, start: 1.9 }]);
});

test('the batch runner assembles, gates, and skips finished work on a re-run', { skip: !hasNumpy && 'needs Python 3 with numpy, and ffmpeg' }, () => {
  const batch = join(dir, 'batch.json');
  writeFileSync(batch, JSON.stringify({ takes: 'takes', transcripts: 'tx', out: 'reels', gate_args: ['--no-asr'],
    reels: [{ id: 'r01', cut: { pieces: [{ clip: 'A', from: 0, to: 3, drop: [1] }] } }, { id: 'r02', cut: { pieces: [{ clip: 'missing', from: 0, to: 1 }] } }] }));
  const r = spawnSync(python, [join(scripts, 'reel_batch.py'), batch], { encoding: 'utf8' });
  const status = JSON.parse(readFileSync(join(dir, 'reels/batch-status.json'), 'utf8'));
  assert.equal(r.status, 1, 'a batch with a failed reel exits 1');
  assert.ok(['PASS', 'WARN', 'FAIL'].includes(status.reels[0].gate), r.stdout + r.stderr);
  assert.equal(status.reels[1].step, 'assemble', 'one bad reel does not stop the others');
  const before = statSync(join(dir, 'reels/r01/base.mp4')).mtimeMs;
  spawnSync(python, [join(scripts, 'reel_batch.py'), batch, '--only', 'r01'], { encoding: 'utf8' });
  assert.equal(statSync(join(dir, 'reels/r01/base.mp4')).mtimeMs, before, 'finished steps are not redone');
});
