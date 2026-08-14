# Cut process reference

CMap cuts always point directly to fingerprinted brute/raw source timestamps.
BMap cues always use the exact effective approved CMap output clock. A CMap
change stales BMap and requires deterministic rebase; raw/semantic anchors are
rebase hints only.

## Source-first rule

1. Log user notes in **source time** on the main camera file (`blocked_source_ranges`).
2. When the user reports a problem on a **proof render**, convert with  
   `python -m avo.edl_timeline map <edl.json> <seconds> --from output`  
   before editing ranges.
3. Split `ranges` at `final_cut_start` / `final_cut_end` (word-boundary pad).
4. Commit the new raw-based CMap revision and render its generated cut output.
5. Only after exact CMap approval, author overlay/SFX timing in BMap
   **`cmap-output`** time. Preserve raw/transcript anchors only as rebase hints.

## Required artifacts (before human review)

| File | Purpose |
| --- | --- |
| `edit/timeline/cmap.json` | Raw-only immutable cuts and timestamp diffs |
| `edit/timeline/bmap.json` | Beats on the exact approved CMap output |
| `edit/edl.json` | Generated renderer projection; never editorial authority |

Generate docs:

```bash
python -m avo.edl_timeline write-docs edit/edl.json
```

## Agent pre-human gate (blocking)

Before writing `approval-gate.md` or asking the creator to watch:

1. **Canonical lineage/projection validation** — CMap is raw-only, BMap basis is the exact approved cut, and generated EDL hash is current.
2. **Transcript read** — cut edges land on pauses/word gaps; privacy spans do not
   remove requested speech; note source times in the review package.
3. **`/avo.watch` (watch-skill)** on the proof with `--timestamps` at:
   - every range join (±2s),
   - every `blocked_source_ranges` mapped B-window,
   - every overlay `start_in_output`.
4. Fix → re-render → repeat until watch-skill + transcript checks pass.

High watch-skill confidence **does not** skip this gate and **does not** replace
human approval (workflow §4b).

## Common failure (this project)

Applying privacy cut at uncut **10:30–10:46** after removing **08:05–08:28**
cut the wrong speech (Xbox line) and left the wife segment at **B ~09:51–10:07**.
Always remap privacy cuts from the **current** proof timeline.

## Canonical CMap rule

CMap is the sole cut authority. Every revision is an immutable snapshot plus
stable-ID timestamp diff, and every kept segment points directly to a
fingerprinted brute/raw source in `raw-source` time. Review proxies are locators
only and require verified raw mapping. Never base a new CMap on a trimmed,
synchronized, rendered, or previously approved output.

`edit/edl.json`, cut-map Markdown, and proofs are generated projections. CMap
approval binds the exact revision hash and generated cut-output fingerprint.
A changed raw or sync fingerprint stales CMap and all descendants.

