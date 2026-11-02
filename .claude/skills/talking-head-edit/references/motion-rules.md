# Motion graphics and 3D: hard rules

These rules come from a rejected edit. Every automated check passed on it, and it still looked
cheap. Read them before adding any designed moment.

## What went wrong

| What was built | Why it failed |
| --- | --- |
| A "sea serpent" coded from a bent tube with a tiny head | It read as a garden hose. Programmer art, not a creature. |
| A cross from a flat extruded plank with a moving light spot | It looked like old WordArt 3D. |
| Flat, untextured CGI cut between real 4K footage and photoreal stock | The style clash broke the world; viewers saw "cheap computer graphic" at once. |
| The 3D barely moved over 8 s | Static 3D looks like a screensaver, not a shot. |
| A dark shape on a dark background, nothing touching the water | Unreadable on a phone and physically fake. |
| The threat shown literally as a monster | Literal monsters look corny or AI. Implying the threat works better. |
| Four 3D moments, one reused, one held about 8 s under the CTA with tiny text | Overuse, reuse, and a dead ending. |

## Rules

1. **The default is no 3D.** Add a designed moment only when it clearly beats real or photoreal
   footage for that line. If unsure, use b-roll.
2. **Never build creatures, people, animals, or realistic objects from code primitives** (tubes,
   cones, extruded shapes in three.js, WebGL, or Canvas). Anything that must look real comes from
   photoreal video: the creator's own footage or AI generations, or licensed stock.
3. Code-made motion is only for honestly graphic things: kinetic type, light leaks, dust, paper or
   glass cards, a quote or reference card, a rule drawing on. Build those with HyperFrames
   (`hyperframes-video-beats`, `style-library`).
4. **Freeze-frame test:** put one frame of the shot between the frames before and after it. If a
   stranger can tell in one second that it is a cheap graphic, or the light, color, or grain do not
   match, cut it.
5. Imply threats; never show them literally (no monsters, glowing eyes, horns, generic flames).
6. No clip-art symbols: a plain object spinning on a dark gradient is banned.
7. **At most 1 or 2 designed moments per short, each 2.5 s or less.** Never reuse an asset in one
   video. Never hold a graphic under the CTA; the speaker's face carries the CTA.
8. It moves the whole time: a real eased camera move of 0.8 s or more, the subject acting. A slow
   drift alone is not a shot.
9. Readable on a phone: the subject reads as a silhouette at thumbnail size; any text is 60 px or
   more at 1080x1920, held 1.5 s or more, and never overlaps the subject or the captions.
10. **Storyboard first:** for each moment write the exact transcript phrase, length, what is on
    screen, the motion, the camera, and why it beats b-roll. Render a contact sheet (a frame every
    0.5 s) and look at it before cutting it in.
11. If it can't look premium with the tools at hand, say so and use footage. Don't ship "good
    enough" 3D.
