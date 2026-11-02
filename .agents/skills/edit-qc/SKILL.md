---
name: edit-qc
description: Check a rendered edit before anyone sees it, with measured craft checks (zoom pops, uncovered jump cuts, stacked events, loudness, joins, words, glitches, ending) and then a real watch and listen, ending in PASS or a numbered fix list. Use after every draft or final render.
---

# Edit QC

You review the encoded render, not the plan. Lint results never prove visual quality, and a
measured PASS is evidence, not taste.

## 1. Measure

```sh
python3 <skill>/scripts/craft_qc.py renders/<name>.mp4 --plan <name>.plan.json \
  --voice cache/voice.wav --transcript <render>.scribe.json --out qa
```

`--voice` is the dry voice stem `talking_head.py` writes, so music in the gaps does not hide a
pop. `--transcript` is a provider transcript of the render (ElevenLabs Scribe, Whisper, or other);
without one the words check reports NOT RUN and must be done another way. For edits made without
`talking_head.py`, drop `--plan` and `--voice`.

Any FAIL is a FAIL here. Open every strip in `qa/flags/` before writing a verdict.

## 2. Watch and listen

On a phone-sized frame, with sound:

- **Craft floor** (`../talking-head-edit/references/craft-floor.md`): every jump cut covered, no
  cut zooms, captions big, word-timed, and never over the mouth, hook title on frame 1, CTA on
  screen when said. A technically clean but static, subtitled cut FAILS.
- **Hook:** the first 3 s are the hook, with no slow intro or dead air.
- **Truth:** no cut changes what someone meant; quotes stay in context.
- **Audio:** every join, with no pops, clicks, or clipped words; the last 0.5 s; even levels
  between voice and music.
- **Picture:** every cutaway in and out, hero frames, every transition: no black flashes, cropped
  faces, overflow, or unreadable text; captions match speech.
- **Designed moments:** the freeze-frame test in `../talking-head-edit/references/motion-rules.md`.
- **Sync:** lips match audio at the start, middle, and end.
- **Format:** resolution, aspect ratio, and duration fit the platform.
- **Ending:** 1 s hold after the last word, then picture and sound fade.

## 3. Report

Write `qa/edit-qc.md`:

```
Verdict: PASS            (or FAIL)
Render checked: <path>
Evidence: <craft_qc results, frames looked at, timestamps listened to>
Fixes:                   (FAIL only, numbered, each with a timestamp and the expected result)
1. 0:12.4 pop at the join after "listen"; trim to the silent point and fade 6 ms.
```

Never fix the edit inside QC, and never pass with an open problem.
