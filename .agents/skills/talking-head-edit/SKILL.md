---
name: talking-head-edit
description: Edit a one-speaker vertical talking-head recording into a finished Reel or Short with phrase cuts in silence, one slow push, b-roll over every jump cut, calm word-timed captions, a hook title, ducked music, and a held, faded ending. Use for sermons, teachings, testimonies, podcast clips, and direct-to-camera talks.
---

# Talking-head edit

The editor makes the judgment calls in `edit-spec.json`; `scripts/talking_head.py` does the
mechanics so every edit clears the same floor. Use `short-form-edit` with HyperFrames instead when
the cut needs screen recordings or designed scenes.

## Before you start

1. Read the project's `BRAND.md` (copy the root `BRAND.md` template into the project if it has
   none and ask the user to fill the blanks or accept the defaults). Before editing, say which
   BRAND.md or craft-floor rule each style choice comes from. Never invent a house style.
2. Read `references/craft-floor.md` and, if any designed moment is planned,
   `references/motion-rules.md`.
3. Get a word-level transcript of the original recording (see `docs/TOOLS-AND-API-KEYS.md`).
   Every edit decision anchors to an exact transcript phrase, never a guessed time.

## Steps

1. **Pick the moments.** Read the whole transcript. Rank 3 to 5 real, timestamped moments
   (exact quote and time). Choose the strongest true hook (a surprising line, a tension, a
   reversal) and the payoff. Main cut under 90 s; a long talk gets a main cut plus a teaser.
2. **Review retakes.** List every false start, retake, and stutter with the reason before
   cutting. Intentional repetition is not a mistake.
3. **Write `edit-spec.json`** (`references/talking-head-spec.md`): selects, drops, hook, emphasis
   words, CTA, b-roll anchored to the lines they illustrate, music beds, and `look` values from
   BRAND.md.
4. **Plan:** `python3 <skill>/scripts/talking_head.py plan edit-spec.json`. Read the summary line
   and add cutaways until no join is left uncovered.
5. **Draft:** `python3 <skill>/scripts/talking_head.py render <name>.plan.json --draft`. Look at a
   contact sheet of the draft (one frame every 0.5 s) before the final render.
6. **Final render**, then run `edit-qc` on the encoded file and fix every FAIL.
7. Write `NOTES.md` in the project: render path, what was cut and why (one line each), b-roll and
   music sources and licenses, and the timestamps a person should still watch and listen to.

Use paid credits (AI b-roll generation, voiceover, stock downloads) only when the user has approved
that spend. Otherwise list the idea in NOTES.md.

## Needs

FFmpeg with libass, Python 3 with `numpy` and `opencv-python-headless<5`, and the brand fonts
installed. The `setup-editor` skill checks all of these.
