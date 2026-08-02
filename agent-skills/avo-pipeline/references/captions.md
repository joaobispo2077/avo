# /avo.captions reference

Dedicated caption stage. Distinct from `/avo.motion` (graphics cards, lower-thirds, slots).

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Edit proof or motion composite **human-approved** (approval gate passed)
- [ ] Transcript available and aligned to timeline (from `/avo.transcribe` or trim stage)

**Block** if edit/motion not approved — do not burn captions on unapproved picture.

## Hard Rule #1 (filter order)

1. Complete motion overlays / graphics first (`/avo.motion` or approved composite).
2. Apply caption burn-in **last** in the filter chain.
3. Preserve 30 ms audio fades at cuts (workflow Hard Rule #2).

## Parse args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Resolves `providers/<name>/` |
| `rawDir` | yes | Workflow root; outputs under `edit/` |
| `identity:` | yes | e.g. `anchor`, `documentary`, `keynote`, `terminal` |
| `Footage:` | optional | Infer from latest approved composite if omitted |
| `from` / `to` | optional | Limit caption pass to window |
| `--preview` | optional | Stay on 360p/720p proof |

Also accept `--identity NAME` (see [`arguments.md`](arguments.md)).

## Load skills

1. **`embedded-captions`** — identity, verbatim ASR, burn-in doctrine
2. **`captions-overlay`** — when repo `.agents/skills/captions-overlay/` present
3. **`youtube-format-playbooks`** — when format-specific caption density applies

**Identity catalog:** embedded-captions `CATALOG.md` (install via HyperFrames skills). Common IDs:

| Identity | When |
| -------- | ---- |
| `anchor` | Clean YouTube, product/review |
| `documentary` | Calm, factual, low hype |
| `keynote` | Bright launch / stage |
| `terminal` | Spec readouts, code-like |
| `nightcity` / `scoreboard` | Gaming (verify rights/posture) |

## Manifest

Record in `avo.project.json` when present:

```json
"captions": {
  "identity": "anchor",
  "burnedIn": true
}
```

See [`docs/templates/avo.project.example.json`](../../../docs/templates/avo.project.example.json).

## Workflow

1. Confirm overlays complete (or user explicitly skips motion).
2. Select identity; document choice in project notes or manifest.
3. Align captions to final transcript; verify names, terms, specialist vocabulary.
4. Render proof → `<rawDir>/edit/preview/captions-proof.mp4` (or project convention).
5. Run watch-skill LOOP on caption proof when substantial.
6. Fill `edit/review/<checkpoint>/approval-gate.md`; **wait for human approval**.
7. Promote to master path only after approval.

## Caption QC

- [ ] Readable on mobile/TV; high contrast; inside safe areas
- [ ] Not occluding faces, UI, product details, evidence
- [ ] Names/terms match glossary and final transcript
- [ ] No conflict with YouTube selectable captions strategy (document if both)
- [ ] Burn-in is last filter stage (verify composite order)

## Related

- Motion overlays: [`motion.md`](motion.md)
- Full master QC: [`deliver.md`](deliver.md)
- Scoped window QC: [`audit.md`](audit.md)
