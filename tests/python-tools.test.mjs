import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.platform === 'win32' ? 'py' : 'python3';
const scripts = [
  '.claude/skills/talking-head-edit/scripts/talking_head.py',
  '.claude/skills/edit-qc/scripts/craft_qc.py',
  '.claude/skills/edit-qc/scripts/first_pass_gate.py',
  'scripts/deliver.py',
];
const hasPython = !spawnSync(python, ['--version']).error;

test('talking-head renderer and craft QC compile', { skip: !hasPython && 'Python 3 not installed' }, () => {
  for (const script of scripts) {
    const result = spawnSync(python, ['-c', 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())', join(root, script)], { encoding: 'utf8' });
    assert.equal(result.status, 0, `${script}\n${result.stderr}`);
  }
});

test('codex mirrors carry the editor skills', () => {
  const result = spawnSync(process.execPath, [join(root, 'scripts/sync-codex-skills.mjs'), '--check'], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  for (const skill of ['talking-head-edit', 'edit-qc', 'setup-editor']) {
    assert.ok(existsSync(join(root, '.agents/skills', skill, 'SKILL.md')), skill);
  }
});
