# First-pass rules

Every rule here came from a real review note that cost a revision round. Each one is either
checked by a machine before delivery or built into how a renderer must behave, so the reviewer
never has to say it twice. When a new note comes up twice, add it here and to the gate or preset.

Run before anyone sees a render:

```sh
npm run gate -- renders/<name>.mp4 --preset presets/<style>.json --expect <script>.txt
npm run deliver -- renders/<name>.mp4 --id <video-id> --version v1
```

`deliver` refuses a render whose gate failed.

## Cuts and words

| Review note | Rule | Enforced by |
| --- | --- | --- |
| "It doesn't say 297", "there should be an S" | A cut never lands inside a word. End a piece where the sound is actually quiet, not where the transcript says the word ends: word timings can be off by half a second, and "s", "t" and "f" endings are quiet and get shaved. Keep 60 ms of real room after the last sound. | gate `words` (speech-to-text of the render against the script), `cut-audio` |
| "Wrong price" | Numbers, names and prices in the render must match the script exactly. | gate `words` with `--expect` |
| "Little glitch in how you frame him" | A zoom change at a cut is either zero or big enough to be a choice (preset `cuts.min_punch`). 1 to 5 percent reads as a glitch. Calm styles allow none. | gate `cuts` |
| "The jump cut could be better" | When the subject hops at a same-shot cut, cover it with b-roll or an overlay, or punch in. | gate `cuts` |
| "Glitch at 26 to 27" | Never stack three picture changes inside 0.6 s. | gate `cuts` |
| "Audio is bassy at the splice" | Pieces recorded at different times are matched in level and tone before joining. Level every piece to the same loudness; fix boom with a gentle low cut, never a heavy match EQ. | gate `tone`, `loudness` |

## Framing

| Review note | Rule | Enforced by |
| --- | --- | --- |
| "Too much headroom" | Reframe every source so the eyes sit inside the preset's `framing.eye_line` band. Measure the face; never scale a 4K take straight to the frame. All pieces of one video share the same eye line. | gate `headroom` |
| "The cropping could be better" | Never crop tighter than the preset allows, and never off centre. | gate `headroom` |

## Overlays and graphics

| Review note | Rule | Enforced by |
| --- | --- | --- |
| "The overlay comes in late" | An overlay lands on its word: at most 0.25 s early, never more than 0.06 s late. Anchor to a word, not to a guessed time. | gate `overlays` (needs the edit sheet), `validate-beat-sync` |
| "Don't bring the graphic up and down" | A list or count stays on screen and builds (one, two, three). It does not leave and re-enter for each item. | renderer rule, reviewer |
| "A real five seconds" | A countdown or timer on screen runs at real speed and matches the words. | renderer rule |
| "Keep graphics in the middle" | Overlays live in the centre zone, clear of platform buttons and captions. | preset `overlays.zone` |
| "Logo cropped", "banner too small" | Logos and banners are whole templates with fixed safe margins and a minimum size. Use the template, do not rebuild it per video. | style templates |
| "Don't reuse that chart" | A designed graphic belongs to one video. Reuse the template, not the content. | reviewer |
| "Wrong colours" | Only preset palette colours appear. Banned hues never appear. | gate `look` with `--composition` |
| "Never colour grade" | Footage is not graded unless the preset says so. | gate `look` |

## Endings

| Review note | Rule | Enforced by |
| --- | --- | --- |
| "Frozen frame before the end screen" | Never pad the end by repeating the last frame. Use real footage for the hold, or bring the end card in the moment speaking stops (`ending.mode: endcard`). | gate `freeze`, `ending` |
| "It cut off at the end" | The last word is fully heard, then a hold, then sound fades. | gate `ending` |
| "Don't cut back to the face between animations" | In an animated-story style, once the animation starts it runs animation to animation until the end card. | preset `style`, reviewer |

## Delivery

| Review note | Rule | Enforced by |
| --- | --- | --- |
| "The file isn't on my computer" | A delivery is not done until the file is where the person looks for it, with a checksum that matches. | `deliver` join script |
| "Checksum mismatch" | Ship the rendered bytes. Never remux or re-encode on the way. | `deliver` |
| "Which version is this" | Every version has its own filename (`-v2`). Nothing is overwritten. | `deliver` |
| "I can't watch it here" | Every version gets a small review copy. | `deliver` |

## Before the first render of any batch

1. One video is finished, gated, and approved before the other 24 are rendered.
2. The approved look is saved as a preset and a template, and the batch reads from them.
3. Say which pack or preset each style choice comes from. Never invent a house style.
4. Never label a speaker, state a price, or spell a name from a guess.
