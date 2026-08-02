# /avo.rights Command

Rights and source audit stage before deliver. Wraps `rights-source-audit` — inventories SOURCE-LOG, disclosure, reused content, privacy, and AI assets.

**Skill:** [`agent-skills/avo-pipeline/references/rights.md`](../../agent-skills/avo-pipeline/references/rights.md)

---

## Usage

```
/avo.rights
Provider: my-channel
rawDir: /path/to/footage
```

Optional: `Footage:` path · `--early` (post-trim clip-heavy formats)

---

## Role

Explicit release-blocking rights QC **before** `/avo.deliver`. Produces `<rawDir>/edit/review/rights-audit.md` and closes SOURCE-LOG gaps.

---

## Instructions

1. Parse `Provider`, `rawDir`, optional `--early`.
2. Load [`rights.md`](../../agent-skills/avo-pipeline/references/rights.md) and skill **`rights-source-audit`**.
3. Inventory third-party assets, music/SFX, clips, AI media, sponsorship evidence.
4. Write audit from [`docs/templates/review/rights-audit.md`](../../docs/templates/review/rights-audit.md).
5. **FAIL** with numbered blockers if SOURCE-LOG or disclosure gaps remain.
6. Recommend `/avo.audio-qc` then `/avo.deliver`.

---

## Example

```text
/avo.rights --early
Provider: my-channel
The footage is at C:/Videos/react-edit
```

Use `--early` after trim proof for react, news, or documentary clip-heavy formats.
