# /avo.talking-head reference

**Orchestrator** for talking-head / interview **graphic overlay packaging**. Distinct from [`captions.md`](captions.md) (verbatim subtitles) and [`shorts.md`](shorts.md) (Shorts shelf).

## Preconditions

- [ ] `provider` + `rawDir` + `Footage:` declared
- [ ] Existing clip plays in full — **no re-timing or recut** unless user explicitly requests trim first

## Phase 0 — Route check

| User wants | Route |
| ---------- | ----- |
| Graphic cards, lower-thirds, data callouts | This command → `talking-head-recut` |
| Spoken-word subtitles only | [`captions.md`](captions.md) |
| Single motion sting | [`motion.md`](motion.md) |

## Workflow phases

| Phase | Action | Reference |
| ----- | ------ | --------- |
| 0 | Confirm overlay vs captions intent | this table |
| 1 | Transcript aligned (`/avo.transcribe` if missing) | [`transcribe.md`](transcribe.md) |
| 2 | Load **`talking-head-recut`** — design cards synced to transcript | `.agents/skills/talking-head-recut/SKILL.md` |
| 3 | watch-skill LOOP + **human approval gate** | [`watch.md`](watch.md) |
| 4 | Optional [`captions.md`](captions.md) if burn-in also needed | after overlays approved |
| 5 | [`rights.md`](rights.md) | required before deliver |
| 6 | [`audio-qc.md`](audio-qc.md) + [`deliver.md`](deliver.md) | master QC |

## Flags

| Flag | Meaning |
| ---- | ------- |
| `--preview` | 360p/720p proofs until approved |
| `--skip-motion` | Stop after edit/transcript — rarely used here |

## Related

- Motion graphics one-off: `.agents/skills/motion-graphics/`
- Args: [`arguments.md`](arguments.md)
