# Producing at scale without burning usage

An AI editor costs money in two ways: model usage, and the reviewer's time. Both follow the same
rule. Decide once, write it down as a file, and let scripts repeat it.

## Where usage goes

Every step an agent takes resends the whole conversation so far. A thread that has done 300 steps
and holds 300,000 tokens of history pays for 300,000 tokens on step 301, even if that step is one
ffmpeg command. One long thread that edits several videos, tweaks, re-renders and rebuilds tools
can pass 100 million tokens while writing almost nothing new.

## Rules

1. **One job per conversation.** One video, or one batch run. Close it when it is delivered. Start
   revisions of a different video somewhere fresh.
2. **Scripts do the repeats, the agent does the judgement.** Cutting, rendering, checking,
   packaging and delivering are commands in this repo. An agent that types ffmpeg by hand for each
   video is spending 50 steps where one would do.
3. **A batch is one command and one report.** Render N videos from N small spec files with one
   call, gate them all, and read one table of results. Only open the frames the gate flags.
4. **Never rebuild what is in the repo.** If a tool was written for a job and worked, it is merged
   into the repo the same day. A tool that lives only in one conversation gets rewritten by the
   next one.
5. **Decisions live in presets, not in chat.** A style that was approved is a preset plus a
   template. The next video reads it instead of re-deriving it from old messages.
6. **Do not look at pictures to answer a measurable question.** Loudness, cut positions, framing,
   colours and word accuracy are numbers. Use the gate. Images are large; spend them on taste.
7. **Change the smallest thing.** A caption fix re-renders the caption layer over the cached base
   cut. A price change swaps one overlay. Keep the base cut, cutouts and transcripts cached per
   video so a revision is seconds, not a full render.
8. **Transcribe once.** Word timings are saved beside the source and reused by every later job.
9. **Nothing runs on a timer unless someone asked for a timer.** An hourly check that finds
   nothing still costs a run. Trigger on request, or on a new file arriving.
10. **Files move once.** Render where the footage is when possible. When a file must cross
    machines, use `deliver` so it is split, verified and named once.

## What a per-video run should look like

```
spec (pieces, script, preset)            written by the agent, reviewed once per batch
  -> cut       (cached base video + word timings + edit sheet)
  -> overlays  (template + preset + edit sheet)
  -> render
  -> gate      (FAIL stops here, with frame strips)
  -> deliver   (versioned file, review copy, checksum)
```

Five commands, no hand-typed media commands, no images unless something is flagged.
