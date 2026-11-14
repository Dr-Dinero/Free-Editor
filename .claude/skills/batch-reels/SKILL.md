---
name: batch-reels
description: Mass-produce Reels, Shorts, and ads from recorded takes (hooks, bodies, calls to action) with reusable word-anchored overlay pieces, one command per batch, and the first-pass gate on every render. Use for a batch of 5 or more videos built from mix-and-match takes, or when the same takes are recut into many versions.
---

# Batch reels

One reel is a list of takes. One batch is a list of reels. The whole batch runs from one
command, and no reel reaches a person before the first-pass gate has passed it.

Use `talking-head-edit` for one recording cut into one video. Use this when takes are
recorded separately and combined: 5 hooks x 10 bodies x 5 calls to action.

## What you prepare

```
batch/
  batch.json          the list of reels (below)
  takes/H3.mp4        one file per take, any size or aspect
  tx/H3.json          {"words": [{"text", "start", "end"}]} per take
  pieces/B1/          overlays written once per take (optional, for a composer)
```

Transcribe every take once (`docs/TOOLS-AND-API-KEYS.md`). Read each transcript, pick the word
range to keep, and note retakes: when a line was said twice, keep the clean one with `from`,
`to` and `drop`.

```json
{
  "takes": "takes", "transcripts": "tx", "out": "reels",
  "preset": "presets/client.json",
  "compose": "python3 tools/build.py {reel}",
  "deliver": true,
  "reels": [
    {"id": "r02", "name": "agencies",
     "cut": {"pieces": [{"clip": "H3", "from": 0, "to": 10},
                        {"clip": "B1", "from": 0, "to": 111, "drop": [96, 97]},
                        {"clip": "C4", "from": 0, "to": 24}]}}
  ]
}
```

## Run it

```
python3 .claude/skills/batch-reels/scripts/reel_batch.py batch/batch.json
```

Per reel: assemble the takes, run the composer if there is one, render, run the gate, and
deliver if it passed. A failed reel stops at its step and the rest carry on. Run the same
command again after a fix; finished steps are skipped. `--only r02,r05` limits the run.

Read the printed table, then `reels/batch-status.json`. Fix what stopped. Do not open,
describe, or upload a reel that did not pass.

## What the assembler guarantees

`scripts/assemble_takes.py` makes `base.mp4`, `edl.json`, `words.json` and `expect.txt`.

- **No clipped words.** Transcript word times end early on soft endings ("ads", "297"). Every
  cut walks out from the word until the voice has actually stopped, then leaves a little air.
- **Tight cuts are reported.** When there is no silence between a kept word and a removed one,
  the cut is listed as `TIGHT CUT` with the word. Listen to each one. Fix it with `in`/`out`
  on the piece, a different word range, or another take.
- **A live ending.** The 0.8 s after the last word is the real footage that follows, not one
  frame held still. If the take ends too soon the report says how long a frame is held; pick a
  take with room, or cover the hold with an end card.
- **Framing.** The picture is cropped to the frame, never squeezed. With OpenCV installed the
  crop follows the face and zooms just enough to bring the eye line into the preset's
  `framing.eye_line` band. The measured face width per take is saved for the composer.
- **Level.** Every take is brought to the same loudness before the join.

## Writing a composer

A composer turns a reel folder into a HyperFrames project at `{reel}/out/`. It is where the
style lives, so it belongs to the style or client, not to this skill. Two helpers in
`scripts/piece_timing.py` keep it from repeating known mistakes:

- **`Timing.fill()`** resolves `{{W:B1:10-0.05}}` anchors in a piece's HTML and JS to seconds on
  the edited timeline, and records each anchored overlay. Pieces never hold seconds, so a
  recut cannot leave an overlay behind. `write_sheet()` saves `edit.json`, which lets the gate
  fail any overlay that lands more than a few frames after its word.
- **`camera_scales()`** picks the zoom at each cut from the measured face sizes, so the face
  changes size by at least the preset's `cuts.min_punch` at every cut. A fixed list of scales
  cannot do this: two takes are never framed alike, and the leftover 2 to 5 % reads as a glitch.

Other rules for a composer: overlays stay in the middle of the frame; captions come from
`words.json`; the end card starts when speaking stops; no colour grade on the footage; music
sits 18 to 22 dB under the voice.

## Usage

The batch command is the whole job. Do not run reels one by one in chat, do not paste render
logs into the conversation, and keep one batch per thread (`docs/SCALE.md`).
