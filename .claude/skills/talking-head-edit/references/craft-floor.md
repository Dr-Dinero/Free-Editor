# Craft floor for talking-head Reels and Shorts

This is the minimum a one-speaker vertical edit must clear before anyone reviews it. It came
from real rejected edits, so each rule names the failure it prevents. Where the project's
`BRAND.md` says something different, `BRAND.md` wins.

What went wrong before:

- **"Edited horribly":** one locked-off shot (up to 51 s with no framing change) with small boxed
  subtitles, no hook text, and no structure. It passed every technical check. Clean is not edited.
- **"Doesn't match the brand":** the next attempt invented its own style (cut zooms, bouncing yellow
  caps, dim-and-slam words, synthetic hits). It looked glitchy and clipped the ending. Never invent
  a house style; follow `BRAND.md`, and say which rule each style choice comes from.

## Picture

- **No cut zooms.** One framing (never tighter than mid-chest to head, eyes about a third down)
  and one slow push carried across every jump cut: about 0.25 %/s, at most +6 %. A zoom that
  resets at a cut pops. The push restarts only while a full-frame cutaway hides the speaker.
  `talking_head.py` does this unless the spec sets `"cut_zooms": true` (only if BRAND.md allows it).
- **B-roll covers every jump cut.** Each join sits under a full-frame cutaway that starts at least
  0.25 s before it and ends at least 0.25 s after. Aim for about 20 to 25 cutaways a minute at
  1.3 to 2.6 s each. Literal clips that show what is said; no generic sky, clouds, or space in the
  hook. Source priority: the creator's own footage or AI generations, then licensed stock. Log every
  clip's source and license.
- **Hard cuts into b-roll.** Short dissolves read as ghosted double exposures.
- AI-generated clips often hold several shots. Scan each clip at a low scene-detection threshold
  (dark clips hide cuts) and use a window with no internal cut or camera jolt.
- Brighten dark clips (`gamma`) so they read on a phone; set the crop focus (`x`, `y`) so the
  subject survives 9:16. Each cutaway may push gently (1.00 to 1.07).
- No sideways frame jumps. No two visual events (cut, cutaway, title) closer than 0.35 s.
- Face in frame 1. A light grade, a soft vignette, and about 5 % film grain over the whole piece.

## Words on screen

- Captions always on: 1 to 4 words, word-timed, about 80 px at 1080 wide, bold, warm white with a
  soft shadow, at most one accent word per line in the brand accent color, in the speaker's own case
  (not all caps unless BRAND.md says so). They fade and rise a few pixels; nothing bounces or shakes.
- Captions match the words actually heard; check them against a transcript of the render.
- Hook title on frame 1: a few words in the title font, a thin accent rule, a calm fade.
- Exactly one CTA, on screen when it is said, in the speaker's exact words. Check what is already
  burned into the footage first; never double a CTA or a banner.
- Nothing over the face or mouth. Keep text out of the top 8 %, bottom 20 %, and right 12 %
  (platform UI).

## Sound

- Cut only in real silence, with 6 ms fades. Never cut into a word edge.
- Licensed music, one bed per act (tense under the hook and problem, hopeful from the turn, warm
  under a closing or prayer), 18 to 22 dB under the voice, ducked under speech, crossfaded at
  section changes. No synthetic whooshes or hits unless BRAND.md asks for them.
- Master to -14 LUFS integrated, true peak at or below -1.5 dBTP, measured on the encoded file.

## Pacing and the ending

- Hook within 1.5 s. 30 to 60 s by default; the main cut stays under 90 s. A long talk becomes a
  main cut plus an optional 30 to 50 s teaser.
- Remove pauses over about 0.4 s in teaching (up to about 0.65 s in calm sections).
- Keep the setup and payoff that make the message true. No cut may change what someone meant.
- The ending holds about 1 s after the last word, then fades picture and sound over 1 s. No cut in
  the last 0.8 s. Never end on a hard stop 0.4 s after the last word.
- A requested re-edit must look materially different from the version it replaces.

## Designed moments and 3D

Read `motion-rules.md` before adding any motion graphic or 3D shot. The default is none.

## QC

`edit-qc` runs `craft_qc.py` on the encoded render (zoom pops, cut zooms, sideways pops, push
speed, stacked events, the ending, joins, glitches, loudness, words). Every FAIL writes a frame
strip to `qa/flags/`. Then a person watches every cutaway in and out, the hook, and the ending, and
listens to every join. A pass is evidence, not taste.
