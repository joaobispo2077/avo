# Audio-sync protocol (short-form)

**Rule:** ALL composition timing lives in **edited-time**. Never mix original-time transcript anchors with edited audio duration.

Adapted from student-kit `short-form-video` — required for every 9:16 retime or new build.

---

## Why

If audio is edited (retakes/pauses removed), source transcript timestamps no longer match the edited file. Scene `data-start` values authored in original-time fire late — the #1 sync bug in short-form.

---

## Procedure

### 1. Establish edited master

- Cut audio/video to final VO → save as `assets/<name>-edit.mp4`
- Measure duration:

```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 assets/<name>-edit.mp4
```

- Set root `data-duration` to this value (seconds)

### 2. Transcribe edited audio only

```bash
npx hyperframes transcribe assets/<name>-edit.mp4 --model small.en --json
```

Or use AVO `/avo.transcribe` on the edited file — not the camera original.

### 3. Map scene starts (edited-time)

| Scene | Label | data-start | data-duration | Rationale |
| ----- | ----- | ---------- | ------------- | --------- |
| 1 | hook | 0.0 | 4.2 | Opening line complete |
| 2 | proof | 4.2 | 5.8 | Transition word "because" |
| … | | | | |

Face-mode transition times in the main timeline **also use edited-time**.

### 4. Captions retime (if reusing old transcript)

Use a `shift(originalTime)` function in captions composition to map word timestamps → edited-time. Keeps transcript JSON untouched.

See [`captions-integration.md`](captions-integration.md) — implementation lives in `embedded-captions` skill.

### 5. Scene-internal offsets stay local

Inside `compositions/sceneN.html`, GSAP anchors are **0-based from scene start**. If parent `data-start` is correct in edited-time, internal offsets usually unchanged — unless a scene **straddles a cut** (adjust parent duration + internals).

---

## Verification

1. `ffprobe` original vs edit — note total cut time
2. Draft render
3. Extract frames at **spoken-word** timestamps where overlay must appear
4. If visual is >200ms early/late — fix `data-start` or face-mode array, re-render

---

## Footage pipeline note

`/avo.shorts` phase 1 (`trim.md`) produces the edited master before motion. HyperFrames slot work must read duration from that approved edit — not the camera original.

---

## Forbidden

- Mixing original-time scene starts with `-edit.mp4` audio
- Using wall-clock or `AnalyserNode` during render (non-deterministic)
- Guessing scene boundaries without transcript alignment
