# Free Editor

A free AI video editor you run with **Claude Code** or **Codex** on your own computer. Give it a
raw talking-head recording (a sermon, a teaching, a testimony, a podcast clip) and it cuts a
finished vertical Reel or Short: tight phrase cuts, b-roll over every jump cut, calm word-timed
captions, a hook title, a music bed under the voice, and a clean ending. Then it checks its own
work with measured craft QC before you ever see it.

Built on [Nate Herk's Herk Edit Kit](https://github.com/nateherkai/herk-edit-kit) (MIT), with a
talking-head renderer, a craft QC gate, guided setup, and editing rules learned from real
rejected edits. This repo only edits. It does not post, schedule, write titles, or make covers.

## Quick start: let your assistant set it up

1. Install [Git](https://git-scm.com/downloads) and either
   [Claude Code](https://claude.com/claude-code) or Codex.
2. Clone this repo and open the folder in your assistant:

   ```sh
   git clone https://github.com/Dr-Dinero/Free-Editor.git
   cd Free-Editor
   claude
   ```

3. Say: **"Set me up."** The `setup-editor` skill checks your computer, tells you exactly what to
   install for Mac, Windows, or Linux, asks which transcription service you want (including a free
   local option), and helps you fill in your brand.
4. Say: **"Edit the video at [path to your recording] into a Reel."**

## What's inside

| Skill | What it does |
| --- | --- |
| `setup-editor` | Guided install and service choices, one step at a time |
| `talking-head-edit` | Raw one-speaker recording to a finished 9:16 Reel or Short |
| `edit-qc` | Measured checks on the encoded render, then a watch and listen, PASS or a numbered fix list |
| `edit-video` | Full long-form edit: transcription, silence and mistake cuts, story, graphics |
| `cut-silences`, `cut-mistakes` | Dead air, retakes, false starts, stutters |
| `short-form-edit` | Reels and ads with screen recordings or designed scenes |
| `video-storytelling`, `hyperframes-video-beats`, `style-library` | Story structure, overlay beats, 400+ motion-graphics cards |
| `motion-showreel`, `make-a-video`, `website-to-hyperframes` | Motion-design pieces from a brief |
| `hyperframes`, `hyperframes-cli`, `gsap`, `hyperframes-registry` | The HTML-to-video engine underneath |

### The craft floor

Every talking-head edit clears these by default (see
[craft-floor.md](.claude/skills/talking-head-edit/references/craft-floor.md)):

- No cut zooms. One slow push carried across cuts, and a cutaway over every jump cut.
- Captions on, 1 to 4 words, word-timed, one accent word, never over the face or platform UI.
- Hook within 1.5 s; main cut under 90 s; 1 s hold and fade at the end.
- Cuts only in real silence; music 18 to 22 dB under the voice; -14 LUFS.
- No cheap 3D: designed moments are rare, storyboarded, and must pass a freeze-frame test
  ([motion-rules.md](.claude/skills/talking-head-edit/references/motion-rules.md)).

### Craft QC

`npm run qc -- renders/my-short.mp4 --plan my-short.plan.json --voice cache/voice.wav --out qa`

Any render, from any tool, goes through the first-pass gate before delivery:

`npm run gate -- renders/my-short.mp4 --preset presets/calm-teaching.json --expect script.txt`

`npm run deliver -- renders/my-short.mp4 --id my-short --version v1`

The rules behind the gate are in `docs/FIRST-PASS-RULES.md`; presets are explained in `presets/README.md`.
measures zoom pops, uncovered jump cuts, sideways pops, push speed, stacked events, loudness, audio
joins, glitches, spoken words, and the ending, and saves a frame strip of every failure. A pass is
evidence, not taste; you still watch it.

### Your brand

`npm run new-video -- my-video` copies [BRAND.md](BRAND.md) into the project. Fill in your fonts,
colors, caption style, energy, and what you never want. Leave it blank and the calm defaults apply
(warm white captions, one muted gold accent word, serif hook title, no bouncing).

## Manual install

Install Node.js **22+**, FFmpeg (with ffprobe and libass), Python 3, and Chrome or Chromium. Then:

```sh
npm ci
python3 -m pip install -r requirements.txt
npm run setup
npm test
```

`npm run setup` checks every tool and creates `.env` for the API keys of services you choose. You
only need a key for paid transcription (ElevenLabs Scribe or the OpenAI Whisper API); local Whisper
is free. See the [tools and API-key guide](docs/TOOLS-AND-API-KEYS.md) and
[setup troubleshooting](docs/SETUP.md).

## Render the demo

```sh
npm run demo
cd video-projects/demo
npx hyperframes lint
npx hyperframes preview
npx hyperframes render --quality draft --output renders/demo.mp4
```

## More

| Resource | Start here |
| --- | --- |
| Full edit, step by step | [Workflow](docs/WORKFLOW.md) |
| Prompt recipes | [Prompts](docs/PROMPTS.md) |
| Nate's editing playbook | [Editing playbook](docs/EDITING-PLAYBOOK.md) |
| Short-form walkthrough | [Short form](docs/SHORT-FORM.md) |
| Motion vocabulary | [MOTION_PHILOSOPHY.md](MOTION_PHILOSOPHY.md) |
| Card library | [Library guide](style-library/GUIDE.md) |
| Release checks | [Verification](docs/VERIFICATION.md) |
| Third-party resources | [Notices](THIRD_PARTY_NOTICES.md) |

Your footage, transcripts, renders, and `.env` stay on your computer: `video-projects/` and media
files are gitignored. Only publish a video you have the rights to, and log the license of every
b-roll clip and music track you use.
