# /avo.motion Command

Add motion graphics or overlays on an approved cut (HyperFrames default).

**Skill:** [`agent-skills/avo-pipeline/references/motion.md`](../../agent-skills/avo-pipeline/references/motion.md)

---

## Usage

```
/avo.motion
Provider: my-channel
rawDir: /path/to/footage
Pull the cursor logo and spin it in a liquid glass card
Logo: /path/to/logo.png
```

Natural-language **intent** line is required (what to build).

---

## Role

Run stage 4–5: motion proof (~720p) → watch-skill LOOP → human approval → promote. HyperFrames first; Remotion only when justified ([`docs/remotion-decision-guide.md`](../../docs/remotion-decision-guide.md)).

---

## Instructions

1. Confirm edit-proof (or clean master) is **user-approved** unless user explicitly waives.
2. Parse motion intent + optional `Logo` / asset paths.
3. Create `edit/animations/slot_<id>/`; spawn parallel sub-agents for multiple slots.
4. Use **talking-head-recut** / **embedded-captions** skills when overlays or captions are requested.
5. Render motion proof to `edit/preview/motion-proof.mp4`.
6. Run `/avo.watch` workflow; wait for approval before full-res composite.

---

## Examples

```text
/avo.motion
Provider: tech-first-look
rawDir: /videos/gadget-a
Use the OpenAI logo from /assets/openai-logo.svg and make it melt into the verdict card
```

```text
/avo.motion
Provider: my-channel
rawDir: /videos/demo
Spin providers/my-channel/logo in a liquid glass lower third during the spec readout
```
