#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { existsSync, copyFileSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let missing = false;
for (const [command, args] of [['node', ['--version']], ['ffmpeg', ['-version']], ['ffprobe', ['-version']]]) {
  const result = spawnSync(command, args, { encoding: 'utf8', windowsHide: true });
  if (result.error || result.status !== 0) { console.error(`${command}: missing from PATH`); missing = true; }
  else console.log((result.stdout || result.stderr).split(/\r?\n/)[0]);
}
const python = process.platform === 'win32' ? 'py' : 'python3';
const py = spawnSync(python, ['-c', 'import numpy, cv2; print("Python", __import__("sys").version.split()[0], "numpy", numpy.__version__, "OpenCV", cv2.__version__)'], { encoding: 'utf8', windowsHide: true });
if (py.error || py.status !== 0) { console.error(`Python 3 with numpy and OpenCV: missing. Install Python 3, then run: ${python} -m pip install -r requirements.txt`); missing = true; }
else console.log(py.stdout.trim());
const libass = spawnSync('ffmpeg', ['-hide_banner', '-filters'], { encoding: 'utf8', windowsHide: true });
if (!libass.error && !/\bass\b/.test(libass.stdout || '')) { console.error('ffmpeg: built without libass (needed to burn captions). Install a full FFmpeg build.'); missing = true; }
if (Number(process.versions.node.split('.')[0]) < 22) { console.error('Node 22+ required.'); missing = true; }
if (!existsSync(join(root, '.env'))) { copyFileSync(join(root, '.env.example'), join(root, '.env')); console.log('Created local .env. Fill only the keys your chosen services need.'); }
else console.log('Existing .env preserved.');
const power = spawnSync(python, [join(root, 'scripts', 'power_tools.py'), 'check'], { encoding: 'utf8', windowsHide: true });
if (power.status === 0) console.log('Power tools: all installed (npm run tools -- check).');
else console.log('Power tools (optional): not all installed. See docs/POWER-TOOLS.md, then pip install -r requirements-power.txt.');
console.log('Service setup and alternatives: docs/TOOLS-AND-API-KEYS.md');
console.log('Next: npx hyperframes doctor (Chrome diagnostics), then npm run demo.');
console.log('New here? Ask your assistant to run the setup-editor skill; it walks you through every step.');
process.exitCode = missing ? 1 : 0;
