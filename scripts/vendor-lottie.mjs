#!/usr/bin/env node
// Copy the local GSAP and lottie-web players into a HyperFrames project's assets/ folder,
// so a composition that uses Lottie renders offline and deterministically.
//   npm run lottie:vendor -- <project-dir>
import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dir = resolve(process.argv[2] || '.');
const files = [
  ['node_modules/gsap/dist/gsap.min.js', 'gsap.min.js'],
  ['node_modules/lottie-web/build/player/lottie_light.min.js', 'lottie_light.min.js'],
];
mkdirSync(join(dir, 'assets'), { recursive: true });
for (const [from, to] of files) {
  const src = join(root, from);
  if (!existsSync(src)) { console.error(`missing ${from}: run npm ci`); process.exit(1); }
  copyFileSync(src, join(dir, 'assets', to));
  console.log(`assets/${to}`);
}
