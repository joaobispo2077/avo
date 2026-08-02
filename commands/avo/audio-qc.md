# /avo.audio-qc Command

Loudness and delivery audio QC on the **approved master export**. Distinct from `/avo.sound` (mix/restoration).

**Skill:** [`agent-skills/avo-pipeline/references/audio-qc.md`](../../agent-skills/avo-pipeline/references/audio-qc.md)

---

## Usage

```
/avo.audio-qc
Provider: my-channel
rawDir: /path/to/footage
Footage: edit/masters/20260801-slug-master-v001.mp4
```

Optional: upload candidate path for post-encode true-peak re-check

---

## Role

Measure integrated loudness and true peak; document method and channel target; produce `<rawDir>/edit/review/audio-qc.md` before `/avo.deliver`.

---

## Instructions

1. Parse `Provider`, `rawDir`, optional `Footage:` (master path).
2. **Stop** if only rough cut exists — require approved master under `edit/masters/` or documented final path.
3. Load [`audio-qc.md`](../../agent-skills/avo-pipeline/references/audio-qc.md) and skill **`loudness-and-audio-delivery-qc`**.
4. Measure loudness + true peak; record standard/settings — no universal YouTube LUFS claim.
5. Write QC from [`docs/templates/review/audio-qc.md`](../../docs/templates/review/audio-qc.md).
6. Hand off to `/avo.deliver`.

---

## Example

```text
/avo.audio-qc
Provider: my-channel
The footage is at C:/Videos/my-edit
Footage: edit/masters/20260801-demo-master-v001.mp4
```
