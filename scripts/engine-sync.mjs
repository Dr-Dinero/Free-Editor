#!/usr/bin/env node
// Keep a pack repo (client presets, brand packs, private skills) on one engine.
//
// The engine is this repository. A pack repo holds an engine.json and pulls the engine's files
// in with this script, so there is one place to fix a tool and no second copy to drift.
//
//   node scripts/engine-sync.mjs <engine checkout>   copy the engine in and write engine.lock
//   node scripts/engine-sync.mjs --check             offline: fail if an engine file was edited here
//
// engine.json in the pack repo:
//   { "source": "<engine repo URL>", "keep": ["README.md", "presets/clients/", ...] }
// "keep" lists paths the pack owns even though the engine has a file of the same name. An entry
// ending in "/" covers a whole folder. Everything the engine does not ship is the pack's already.
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const args = process.argv.slice(2);
const check = args.includes('--check');
const flag = name => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };
const root = resolve(flag('--root') || process.cwd());
const from = args.find((a, i) => !a.startsWith('--') && args[i - 1] !== '--root');
const configPath = join(root, 'engine.json');
const lockPath = join(root, 'engine.lock');
const sha = path => createHash('sha256').update(readFileSync(path)).digest('hex');
const die = message => { console.error(message); process.exit(1); };
// The lock is plain text in sha256sum layout: "# commit <sha>", then "<checksum>  <path>" lines.
function readLock() {
  const lock = { commit: '', files: {} };
  for (const line of readFileSync(lockPath, 'utf8').split('\n')) {
    if (line.startsWith('# commit ')) lock.commit = line.slice(9).trim();
    else if (/^[0-9a-f]{64}  /.test(line)) lock.files[line.slice(66)] = line.slice(0, 64);
  }
  return lock;
}

if (!existsSync(configPath)) {
  console.log('No engine.json here. This is the engine itself, or a repo that does not track one.');
  process.exit(0);
}
const config = JSON.parse(readFileSync(configPath, 'utf8'));
// Mirrors are rebuilt by `npm run sync:skills`, and these two files belong to the pack.
const keep = [...(config.keep || []), '.agents/', 'engine.json', 'engine.lock'];
const kept = path => keep.some(k => (k.endsWith('/') ? path.startsWith(k) : path === k));

if (check) {
  if (!existsSync(lockPath)) die('engine.lock is missing. Run: npm run engine:sync -- <engine checkout>');
  const lock = readLock();
  const bad = [];
  for (const [path, hash] of Object.entries(lock.files)) {
    if (kept(path)) continue;
    const here = join(root, path);
    if (!existsSync(here)) bad.push(`missing: ${path}`);
    else if (sha(here) !== hash) bad.push(`edited here: ${path}`);
  }
  if (bad.length) {
    console.error(bad.join('\n'));
    die(`${bad.length} engine file(s) differ from engine ${String(lock.commit).slice(0, 7)}. Make the change in the engine repo and sync, or add the path to "keep" in engine.json if this repo should own it.`);
  }
  console.log(`Engine files match ${String(lock.commit).slice(0, 7)} (${Object.keys(lock.files).length} files).`);
  process.exit(0);
}

if (!from) die('Usage: node scripts/engine-sync.mjs <engine checkout>   or   --check');
const engine = resolve(from);
const git = (...a) => spawnSync('git', ['-C', engine, ...a], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
const listed = git('ls-files', '-z');
if (listed.status !== 0) die(`Not a git checkout: ${engine}`);
if (git('status', '--porcelain').stdout.trim()) console.warn('Warning: the engine checkout has uncommitted changes; they are copied too.');
const commit = git('rev-parse', 'HEAD').stdout.trim();
const previous = existsSync(lockPath) ? readLock().files : {};

const files = {};
let added = 0, updated = 0, same = 0;
for (const path of listed.stdout.split('\0').filter(Boolean).sort()) {
  if (kept(path)) continue;
  const source = join(engine, path);
  if (!existsSync(source)) continue;
  const dest = join(root, path);
  const hash = sha(source);
  files[path] = hash;
  if (!existsSync(dest)) added++;
  else if (sha(dest) === hash) { same++; continue; }
  else updated++;
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(source, dest);
}
const dropped = Object.keys(previous).filter(path => !(path in files) && !kept(path) && existsSync(join(root, path)));
writeFileSync(lockPath, [`# source ${config.source || 'unknown'}`, `# commit ${commit}`,
  ...Object.entries(files).map(([path, hash]) => `${hash}  ${path}`)].join('\n') + '\n');
console.log(`Engine ${commit.slice(0, 7)}: ${added} added, ${updated} updated, ${same} unchanged.`);
if (dropped.length) console.log(`No longer in the engine (delete here if unused):\n  ${dropped.join('\n  ')}`);
console.log('Next: npm run sync:skills, then npm test.');
