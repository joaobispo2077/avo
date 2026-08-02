# /avo.captions Command

Dedicated caption stage: identity selection, burn-in order, and caption QC. Does not replace `/avo.motion` for graphics cards.

**Skill:** [`agent-skills/avo-pipeline/references/captions.md`](../../agent-skills/avo-pipeline/references/captions.md)

---

## Usage

```
/avo.captions
Provider: my-channel
rawDir: /path/to/footage
identity: anchor
```

Optional: `Footage:` path · `from:` / `to:` window · `--preview`

---

## Role

Apply embedded captions **after** motion overlays (Hard Rule #1: subtitles last). Load `embedded-captions` doctrine, proof at preview resolution, human approval gate before promotion.

---

## Instructions

1. Parse `Provider`, `rawDir`, `identity:` (required).
2. Block if edit or motion composite is not human-approved.
3. Follow [`captions.md`](../../agent-skills/avo-pipeline/references/captions.md) filter-order contract.
4. Default to **360p/720p preview** until user approves promotion.
5. Do **not** start HyperFrames slot work unless user explicitly requests motion.

---

## Example

```text
/avo.captions
Provider: my-channel
The footage is at C:/Videos/review
identity: anchor
```

Common identities: `anchor`, `documentary`, `keynote`, `terminal` — see embedded-captions `CATALOG.md`.
