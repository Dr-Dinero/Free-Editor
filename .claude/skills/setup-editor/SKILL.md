---
name: setup-editor
description: Walk a new user through installing and configuring this editor on their computer, one step at a time, checking each tool and asking only for the services they choose. Use on first run, when the user says "set me up" or "install", or when a check says a tool is missing.
---

# Guided setup

The user may never have used a terminal. Go one step at a time: say what the step is for in one
sentence, run the check yourself, and only ask them to do something when a check fails. Never
print a key's value. Never put keys anywhere but `.env`.

## 1. Check the machine

Run `npm run setup` from the repo root. It checks Node 22+, FFmpeg, ffprobe, Python 3 with numpy
and OpenCV, and creates `.env` if it is missing. For each missing item, give the one install line
for their system:

| Tool | macOS (Homebrew) | Windows (winget) | Linux (Debian/Ubuntu) |
| --- | --- | --- | --- |
| Node 22+ | `brew install node` | `winget install OpenJS.NodeJS.LTS` | from nodejs.org or `nvm install 22` |
| FFmpeg | `brew install ffmpeg` | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |
| Python 3 | `brew install python` | `winget install Python.Python.3.12` | `sudo apt install python3 python3-pip` |
| Python packages | `python3 -m pip install -r requirements.txt` | same, with `py -m pip` | same |
| Chrome | install Google Chrome | install Google Chrome | `sudo apt install chromium` |

If Homebrew is missing on a Mac, point them to https://brew.sh. After installs, they may need to
open a new terminal. Then run `npm ci`, `npm run setup` again, and `npm test`.

## 2. Fonts

The calm default look uses Figtree and Libre Caslon Text (free, Google Fonts). Ask them to install
both, or the fonts named in their `BRAND.md`. Check with `fc-list | grep -i figtree` (macOS/Linux)
or by opening the font in Windows.

## 3. Transcription (pick one)

Ask which they want, and recommend the first that fits:

- **ElevenLabs Scribe** (best word timing, paid per minute): create a key with speech-to-text
  access at https://elevenlabs.io/app/settings/api-keys, and have them paste it into `.env` as
  `ELEVENLABS_API_KEY=` themselves. Test with `npm run transcribe -- <short clip>`.
- **OpenAI Whisper API**: `OPENAI_API_KEY` in `.env`.
- **Local Whisper** (free, slower, no account): `python3 -m pip install faster-whisper`.

## 4. Power tools (recommended, free)

Say in one sentence what they buy: captions that land on the word, cleaner silence cuts,
face-following vertical crops, shot detection, voice cleanup, even loudness, ducked music, cover
cut-outs. They add a 4-6 GB install, so ask first. If yes:

```
python3 -m venv .venv && . .venv/bin/activate      # Windows: py -m venv .venv; .venv\Scripts\activate
python3 -m pip install -r requirements-power.txt
npm run tools -- check
```

Every line of `check` should say `ok`. The first run of each tool downloads its model; see
`docs/POWER-TOOLS.md` for what each command does and where it sits in an edit.

## 5. Optional sources (ask, don't assume)

- **B-roll and music:** their own footage folder; a stock account they already pay for (Storyblocks,
  Artgrid, Pexels for free); a licensed music library (Epidemic Sound, Artlist, or YouTube Audio
  Library for free). If their Claude has connectors for these, check with them that they are
  connected; otherwise they download clips into the project's `broll/` and `music/` folders.
- **AI video for b-roll** (Higgsfield, Kie.ai, others): only with their own credits and approval.
- **Google Drive** for raw footage: if their Claude has the Google Drive connector, use it;
  otherwise they drop files into `video-projects/<slug>/source/`.

## 6. Brand

Copy `BRAND.md` from the repo root into their first project, then fill it with them in a short
conversation: colors, fonts, caption case, energy (calm or high energy), what they never want. If
they skip it, the calm defaults apply.

## 7. First run

`npm run new-video -- my-first-video`, put a short talking-head clip in its `source/` folder, then
use `talking-head-edit`. Finish by telling them in one short paragraph what is installed, which
services they chose, and what to say next time ("edit the video in my-first-video").
