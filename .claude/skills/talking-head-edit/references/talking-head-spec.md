# edit-spec.json for talking_head.py

The editor writes the judgment calls here; `scripts/talking_head.py` turns them into the
cut, the shots, the captions, the graphics, and the mix. Every anchor is an exact phrase from
the transcript, so a new transcript or a changed cut re-times everything.

```json
{
  "name": "my-short-v1",                       // render file name (renders/<name>.mp4)
  "source": "source/raw.mp4",             // the original recording, never a proxy
  "transcript": "transcripts/raw.scribe.json",
  "drops": [                                // reviewed retakes and false starts, with the reason
    {"phrase": "so you're soul tyling--", "why": "retake; clean take follows"},
    {"phrase": "Knowing that,", "after": 176, "why": "restart"}   // after: source seconds, to pick the right repeat
  ],
  "end_phrase": "follow for more.",         // optional: end the cut on this phrase
  "selects": [                              // optional short cut: keep only these spans (source order)
    {"from": "Did you know", "to": "in the night."}
  ],
  "max_pause": 0.26,                        // longest pause kept between phrases (teaching)
  "calm_from": "Father, I thank you",       // optional calm section (prayer, testimony):
  "calm_to": "go into the comment section", //   longer pauses and shots, soft captions, a swell in
  "calm_max_pause": 0.6,
  "max_shot": 3.4, "calm_max_shot": 7.0,    // longest shot before a punch-in is added
  "hook": {"line1": "IS SLEEP PARALYSIS", "line2": "JUST SLEEP?", "hold": 3.0},
  "hook_shot": "W",                         // legacy cut_zooms mode only
  "sections": [],                           // legacy only: section chips are off in the calm default; use only if BRAND.md asks
  "slams": [],                              // legacy only: dim-and-slam words are off in the calm default; use only if BRAND.md asks
  "emphasis": ["sleep", "paralysis", "free"],   // accent-colored caption words; punch-ins outside calm
  "cta": {"phrase": "go into the comment section", "text": "\"I AM FREE\\NINDEED\""},
  "look": {"accent": "#C9A45C"},          // optional overrides from BRAND.md
  "broll": [                                // licensed stock cutaways, anchored to the line they illustrate
    {"phrase": "It's demons", "file": "broll/354476068.mp4", "in": 1.0, "dur": 1.7,
     "layout": "full",                      // full: replaces the frame; top: clip above, speaker below
     "x": 0.18, "y": 0.5}                   // crop focus in the clip (0 left/top, 1 right/bottom)
  ],
  "push": {"base": 1.04, "rate": 0.0025, "cap": 0.06},  // one slow push, carried across jump cuts
  "cut_zooms": false,                       // true only when the brand allows punch-in cuts (legacy W/M/T)
  "end_hold": 1.0, "end_fade": 1.0,         // hold after the last word, then fade picture and sound
  "grain": 5, "sfx": false,                 // film grain; synthetic hits only if the brand wants them
  // broll entries also take "lead" (s before the phrase), "fade" (s), "gamma" (lift dark clips)
  // default look: {"font": "Figtree ExtraBold", "title_font": "Libre Caslon Text", "accent": "#C9A45C",
  //   "text": "#F4EFE6", "caption_px": 80, "case": "as-spoken", "motion": "calm"}; copy BRAND.md values here
  "music": [                                // licensed beds; ducked under speech, up 4 dB in gaps
    {"file": "music/signs.wav", "from": "start", "to": "Father, I thank you", "in": 0.0, "under": 12, "fade": 0.8},
    {"file": "music/breath-of-awe.wav", "from": "Father, I thank you", "lead": 0.6, "to": "end", "in": 6.4}
  ]
}
```

Run from the video project folder:

```sh
python3 ../../.claude/skills/talking-head-edit/scripts/talking_head.py plan edit-spec.json
python3 ../../.claude/skills/talking-head-edit/scripts/talking_head.py render <name>.plan.json --draft
python3 ../../.claude/skills/talking-head-edit/scripts/talking_head.py render <name>.plan.json
python3 ../../.claude/skills/edit-qc/scripts/craft_qc.py renders/<name>.mp4 --plan <name>.plan.json --voice cache/voice.wav --out qa
```

Jump cuts: every join must sit under a full-frame cutaway (start 0.25 s or more before, end 0.25 s
or more after); list the uncovered joins after `plan` and add cutaways until there are none.

B-roll: pick clips by looking at a per-second contact sheet of each one, set `in` to the moment
that carries the meaning (the cuffs hitting the ground, the light flaring), and set `x` so the
subject survives the vertical crop. Keep cutaways 1.3 to 2.6 s, off slams, and spaced so the
speaker stays the anchor. Captions move to the seam on a `top` split. Music: one bed per act
(teaching, prayer) changing at the turn; `under` is dB below speech while the speaker talks.

`plan` writes `<name>.plan.json` (frame-exact keep segments, shots, captions, graphics, sound
cues, and the retimed words) and caches face positions in `cache/faces.json`. Read the plan's
summary line: shot count, median and longest shot. `render` decodes only the kept frames of the
original once, crops each shot from it, burns captions and graphics with libass, builds the
voice from the same frame-exact segments with 6 ms fades, adds effects only when `sfx` is on, and
masters to -14 LUFS / -1.5 dBTP. A 3-minute 4K source takes about 5 minutes on 4 cores.

Needs ffmpeg with libass, Python 3 with numpy and `opencv-python-headless<5` (4.x keeps the
face detector), the Figtree and Libre Caslon Text fonts (free from Google Fonts; any installed font works through `look.font`), and for craft QC,
faster-whisper (or Scribe on the render when the model download is blocked). `render` also
writes the dry voice stem to `cache/voice.wav`; pass it to craft QC with `--voice` so the joins
check is not fooled by music in the gaps.

Slams, chips, and the CTA are only words the speaker says. The script refuses an anchor
phrase it cannot find in the transcript.
