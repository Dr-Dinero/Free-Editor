# Presets

A preset is one small JSON file that holds everything a client or style has decided: frame size,
loudness, whether cuts may punch in, where the face sits, how the video ends, which colours are
allowed. The renderer reads it to build the video and the first-pass gate reads the same file to
check it, so a decision is written once and enforced on every video after that.

```sh
npm run gate -- renders/reel-07.mp4 --preset presets/bold-ads.json --expect reel-07.txt
```

Only write what differs from `default.json`; everything else is inherited.

| Key | What it decides |
| --- | --- |
| `format` | Frame size and allowed frame rates. |
| `audio.lufs`, `true_peak_max` | Loudness target and ceiling. `music_under_voice_db` is the mix rule for the renderer. |
| `cuts.allow_punch` | `false` means no zoom at a cut, ever (calm styles). |
| `cuts.min_punch` | A punch-in smaller than this reads as a glitch and fails. |
| `cuts.max_hop` | How far the subject may jump sideways or up at a same-shot cut before it must be covered. |
| `framing.eye_line` | Where the eyes sit, as a share of frame height from the top. Fixes "too much headroom". |
| `overlays.late_max` | An overlay may arrive at most this long after its word. Late overlays fail. |
| `overlays.zone` | Where graphics live (`centre` by default). |
| `ending.mode` | `hold` (hold, then fade) or `endcard` (the end card arrives when speaking stops; no frozen frame). |
| `look.palette` | Allowed accent colours. Anything else in the composition fails. |
| `look.banned_hues` | Hue ranges in degrees that must never appear, for example `[[200, 290]]` for "no blue or purple". |
| `look.allow_grade` | `false` means the footage is never colour graded. |
| `style` | Fonts, caption position and motion words for the renderer. The gate ignores these. |

## Turning a review note into a rule

When a reviewer says something twice, it belongs here, not in a chat. "Banner too small" becomes a
minimum size in the style's template; "no blue" becomes `banned_hues`; "too much headroom" becomes
`framing.eye_line`. See `docs/FIRST-PASS-RULES.md`.
