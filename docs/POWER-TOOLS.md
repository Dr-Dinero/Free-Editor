# Power tools

Optional, free, open-source tools that raise the floor on every edit. One command runs each:
`npm run tools -- <command>`. Install the Python ones with
`python3 -m pip install -r requirements-power.txt` (a virtual environment is recommended; PyTorch
makes it a 4-6 GB install). Lottie comes with `npm ci`. Check what is installed with
`npm run tools -- check`.

| Command | Tool (license) | What it fixes | Output |
| --- | --- | --- | --- |
| `align` | [WhisperX](https://github.com/m-bain/whisperX) (BSD-2) | Captions drifting off the spoken word. Aligns each word to the audio with a phoneme model; `--transcript` re-times an existing Scribe or whisper.cpp transcript instead of re-transcribing. | `{ words: [{text,start,end,score}] }`, the kit's transcript shape |
| `speech` | [Silero VAD](https://github.com/snakers4/silero-vad) (MIT) | Silence cuts that clip a first or last syllable. Finds real speech, not loudness. | speech regions and gaps |
| `scenes` | [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) (BSD-3) | Clips that start or end mid-shot in multicam podcasts, sermons, and streams. | shot list |
| `reframe` | [MediaPipe](https://github.com/google-ai-edge/mediapipe) (Apache-2.0) | A fixed 9:16 crop that loses a moving speaker. Tracks the face, holds still inside a dead zone, eases when they move. `--render` writes the cropped video. | crop path JSON (+ video) |
| `clean-voice` | [Demucs](https://github.com/facebookresearch/demucs) (MIT) | Room music, crowd noise, or a band under the preacher. Separates the voice stem. | voice WAV |
| `loudness` | [ffmpeg-normalize](https://github.com/slhck/ffmpeg-normalize) (MIT) | Uploads at different volumes. Two-pass EBU R128 to -14 LUFS, -1 dBTP, video copied. | normalized media |
| `duck` | FFmpeg sidechain (LGPL/GPL build) | Music fighting the voice. Bed sits 18 dB under, then dips further while words are spoken. | mixed video |
| `cutout` | [rembg](https://github.com/danielgatis/rembg) (MIT) | Covers that are a face on a flat card. Cuts the subject out so text can sit behind them or they can be placed into a symbolic scene. | transparent PNG |
| Lottie | [lottie-web](https://github.com/airbnb/lottie-web) (MIT) | Hand-coded graphics that look homemade. Plays After Effects animations exported as Lottie JSON, frame-accurate in HyperFrames. | see below |

## Where each one sits in an edit

1. Transcribe (Scribe, whisper.cpp, or `align` alone), then `align --transcript` so every caption
   word sits on its sound. Low-score words are listed: check those by ear.
2. `speech` before `cut-silences`: cut inside the gaps it reports, never inside a region.
3. `scenes` on multicam or streamed sources before choosing clip ranges.
4. `reframe` for horizontal sources going vertical. Review the crop path on a contact sheet;
   a centre crop is fine when the speaker barely moves.
5. `clean-voice` only when the source has music or noise under the voice; compare by ear first.
6. Render, then `duck` the music bed and finish with `loudness`. Run `npm run qc` on the result.
7. Covers: pick a frame, `cutout` the subject, compose the scene and title.

## Lottie in HyperFrames

Template: `style-templates/lottie-overlay/` (centred gold check that draws on, then a label).

- Inline the animation as a script (`window.NAME = {...}`), not a fetch, so it loads synchronously.
- HyperFrames has a built-in Lottie adapter that seeks every animation to the composition's
  absolute time, so an animation could only ever start at 0 s. The template keeps a private
  handle (`const LOTTIE = window.lottie; window.lottie = undefined;`) and drives the frame from the
  GSAP timeline through a property setter, so each beat starts on its word. Do not use `onUpdate`
  to seek Lottie: timeline seeks suppress callbacks and the frames come out wrong.
- Copy the players into a project with `npm run lottie:vendor -- <project-dir>`.
- Animations from LottieFiles and similar sites carry their own license (often the Lottie Simple
  License, which allows commercial use but not resale of the file itself). Record the source and
  license of every animation in the project's `LICENSES.md`, and never ship a bought or downloaded
  animation inside a public repo.

## Model downloads

The first run of `align`, `clean-voice`, `cutout`, and `reframe` downloads model weights (from
huggingface.co, download.pytorch.org, dl.fbaipublicfiles.com, github.com, and
storage.googleapis.com). On a locked-down network, allow those hosts first. Weights are cached
in your user folder; nothing is uploaded.

## Known setup snags

- WhisperX pins its own PyTorch version (2.8 for WhisperX 3.8). Install it in its own virtual
  environment so it doesn't downgrade PyTorch for other projects.
- WhisperX fetches NLTK's `punkt_tab` tokenizer on first use. Behind a corporate proxy, run once
  with `NLTK_ALLOW_PROXIED_URLOPEN=1`.
- MediaPipe on a headless Linux server needs `sudo apt install libegl1 libgles2`.
- Demucs weights come from dl.fbaipublicfiles.com. If that host serves a bad certificate, wait
  and retry; never turn certificate checks off.
