# /avo.chapters reference

YouTube chapter markers from the **final-file transcript** and user-approved structure.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Final-file transcript under `<rawDir>/edit/transcripts/` (from exported master — not rough cut or EDL alone)
- [ ] Approved master exists or user confirms chapter structure from final program

**Stop** if only rough-cut transcript — run `/avo.deliver` final-file transcript step first.

## Parse args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Channel / brand |
| `rawDir` | yes | Workflow root |
| `Transcript:` | optional | Default: latest matching master basename in `edit/transcripts/` |
| `--preview` | optional | Draft titles only; do not write delivery file until user approves |

## Workflow

1. Locate final-file transcript (`edit/transcripts/<master-basename>.txt`).
2. Derive chapter boundaries from structure (sections, topic shifts, user-supplied anchors).
3. **User approval required** on titles and boundaries before final write.
4. Format lines as YouTube chapters: `HH:MM:SS Title` (minimum segment length sanity — avoid spammy micro-chapters).
5. **First chapter must start at `0:00`.**
6. Write to `<rawDir>/edit/delivery/chapters.txt`.

## Warnings

- **Shorts profile** or masters under ~3 minutes: warn that chapters may not apply; document in delivery manifest.
- Very short masters: prefer no chapters over misleading structure.

## Output example

```text
0:00 Introduction
2:15 Setup and diagnosis
8:40 Main demonstration
15:02 Conclusion
```

## Related

- Deliver: [`deliver.md`](deliver.md)
- Delivery manifest: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
