import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const script = join(root, 'scripts/engine-sync.mjs');
const run = (cwd, ...args) => spawnSync(process.execPath, [script, ...args], { cwd, encoding: 'utf8' });
const hasGit = !spawnSync('git', ['--version']).error;

test('a pack repo pulls the engine in and notices local edits', { skip: !hasGit && 'git not installed' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'engine-sync-'));
  try {
    const engine = join(dir, 'engine'), pack = join(dir, 'pack');
    for (const d of [join(engine, 'scripts'), join(engine, '.agents/skills'), pack]) mkdirSync(d, { recursive: true });
    writeFileSync(join(engine, 'scripts/tool.py'), 'print("v1")\n');
    writeFileSync(join(engine, 'README.md'), 'engine readme\n');
    writeFileSync(join(engine, '.agents/skills/mirror.md'), 'generated\n');
    const git = (...a) => spawnSync('git', ['-C', engine, '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', ...a], { encoding: 'utf8' });
    git('init', '-q'); git('add', '-A');
    assert.equal(git('commit', '-qm', 'one').status, 0);

    assert.match(run(pack, '--check').stdout, /No engine\.json/);
    writeFileSync(join(pack, 'engine.json'), JSON.stringify({ keep: ['README.md'] }));
    writeFileSync(join(pack, 'README.md'), 'pack readme\n');
    assert.equal(run(pack, '--check').status, 1, 'no lock yet');

    const first = run(pack, engine);
    assert.equal(first.status, 0, first.stderr);
    assert.equal(readFileSync(join(pack, 'scripts/tool.py'), 'utf8'), 'print("v1")\n');
    assert.equal(readFileSync(join(pack, 'README.md'), 'utf8'), 'pack readme\n', 'kept files stay');
    assert.ok(!existsSync(join(pack, '.agents')), 'mirrors are not copied');
    assert.equal(run(pack, '--check').status, 0);

    writeFileSync(join(pack, 'scripts/tool.py'), 'print("local edit")\n');
    const drift = run(pack, '--check');
    assert.equal(drift.status, 1);
    assert.match(drift.stderr, /edited here: scripts\/tool\.py/);

    writeFileSync(join(engine, 'scripts/tool.py'), 'print("v2")\n');
    git('commit', '-qam', 'two');
    assert.match(run(pack, engine).stdout, /1 updated/);
    assert.equal(readFileSync(join(pack, 'scripts/tool.py'), 'utf8'), 'print("v2")\n');
    assert.equal(run(pack, '--check').status, 0);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
