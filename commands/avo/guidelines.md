# /avo.guidelines Command

Load editorial guidelines for a platform or discipline before editing.

**Skill:** [`agent-skills/avo-pipeline/references/guidelines.md`](../../agent-skills/avo-pipeline/references/guidelines.md)

---

## Usage

```
/avo.guidelines --youtube
/avo.guidelines --eq
/avo.guidelines --tiktok
/avo.guidelines --shorts
```

Exactly **one** flag required. Combine with `Provider:` when diagnosing a channel.

---

## Role

Format diagnosis and playbook loading. **Does not** transcribe, cut, or render. Use before strategy conversation on a new video.

---

## Instructions

1. Parse flag → read matching reference slice (see guidelines router).
2. State format diagnosis: primary format, viewer promise, pacing density, risks.
3. Apply rules from [`AGENTS.md`](../../AGENTS.md); load repo skills when installed (`youtube-format-selection`, `audio-post-production`, etc.).
4. Output a short checklist the user can approve before `/avo.pipeline` or `/avo.trim`.

---

## Examples

```text
/avo.guidelines --youtube
Provider: my-gaming-channel
rawDir: /videos/review-001
```

```text
/avo.guidelines --eq
rawDir: /podcast/ep42
Footage: /podcast/ep42/raw/dialogue.wav
```
