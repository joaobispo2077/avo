# /avo.grade reference

**Creative grade pass** using repo `grade.py` — ffmpeg presets per segment.

## Boundary vs `/avo.color`

| Command | Purpose |
| ------- | ------- |
| **`/avo.grade`** | Apply or document creative grade during edit (`grade.py` presets / custom filter) |
| **`/avo.color`** | Pre-deliver **checklist QC** — evidence integrity, no grade engine |

Run grade during edit; run color QC before deliver on approved master.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Segment extracts or working timeline paths documented

## Workflow

1. Choose preset or documented custom filter chain — preserve evidence/product color intent.
2. Grade per-segment before overlay composite when using pipeline render path.
3. Record preset, filter, and reviewer notes in `<rawDir>/edit/review/grade-notes.md` (optional manifest row).

## Helper

- `grade.py <in> -o <out>` — see [`SKILL.md`](../../../SKILL.md) Helpers section

## Handoff

- [`color.md`](color.md) — evidence QC on approved master (not a substitute for grade)
- [`deliver.md`](deliver.md) — master QC

## Related

- AGENTS.md visual clarity — do not misrepresent evidence via grade
