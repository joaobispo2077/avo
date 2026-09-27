# YouTube Editing System

## Philosophy

The edit must fulfill the title/thumbnail promise, preserve meaning, make the
content understandable, maintain appropriate momentum, support the creator's
identity, respect viewer time, and comply with rights, disclosure, safety,
privacy, accessibility, and platform requirements.

There is no universal YouTube style. Editing density is chosen after format
diagnosis.

## Common Workflow

1. Intake and diagnosis: read the brief, inspect repo/media, diagnose format,
   promise, audience, risks, urgency, and brand language.
2. Ingest and preservation: verify media completeness, preserve originals,
   sync audio, create proxies only when useful, and log sources.
3. Transcript and story map: verify transcript, mark claims, beats, disclosures,
   payoffs, and evidence before detailed polish.
4. Radio edit/content cut: build the strongest audio-led version first for
   speech-led formats; preserve context and cadence.
5. Assembly/rough cut: add essential evidence, visuals, chapter flow, and flag
   missing assets.
6. Retention and clarity pass: diagnose slow/confusing sections and add only
   motivated pattern interruptions, graphics, examples, or B-roll.
7. Fine cut and visual language: refine cuts, J/L cuts, B-roll, graphics,
   transitions, typography, thumbnail frames, and end-screen space.
8. Audio post: clean dialogue, balance speakers, mix music/SFX, check sync,
   levels, peaks, channel routing, and device playback.
9. Color and finishing: normalize cameras, preserve evidence/product/UI colors,
   and avoid destructive looks.
10. Captions, chapters, and packaging: verify captions, chapters, thumbnail
    candidates, title promise, and end-screen support.
11. Rights, disclosure, and policy audit: complete `SOURCE-LOG.md`, review
    reused content, sponsorship, AI disclosure, made-for-kids, privacy, safety,
    harassment, and advertiser-friendly issues.
12. Master QC and delivery: export immutable version, run QC, update
    `EDITLOG.md`, and deliver master/captions/thumbnails/derivatives.

## Review Gates

1. Editorial diagnosis approved.
2. Assembly approved.
3. Rough cut approved.
4. Fine cut approved.
5. Picture lock approved.
6. Audio and color approved.
7. Captions and rights approved.
8. Master QC passed.

Do not skip to polish while structure is unresolved.

## Version Naming

Use immutable names:

```text
YYYYMMDD-video-slug-stage-v001
```

Examples:

```text
20260719-switch-2-travel-review-rough-v003
20260719-switch-2-travel-review-picture-lock-v009
20260719-switch-2-travel-review-master-v010
```

Never use `final-final` or overwrite approved review exports.

## Project Organization

Preserve existing sensible structure. If creating one, separate admin,
script/research, source media, project files, graphics, music/SFX, proxies,
review exports, masters, captions, thumbnails, rights evidence, and docs.

Generated AVO session outputs belong in the footage folder's `edit/`.

## Hybrid Formats

Hybrid videos must identify which playbook controls each section. Do not blend
formats in ways that weaken integrity requirements. Example: a news opening
must keep evidence labeling even if the middle becomes talking-head commentary.

## Analytics Learning Loop

Use YouTube Analytics after publication as evidence for iteration. Review intro
performance, key moments, dips, spikes, top moments, AVD, APV, CTR by traffic
source, traffic mix, new/casual/regular viewer behavior when available,
end-screen performance, chapters, and comments. Classify likely causes and
compare against similar videos before proposing edits or packaging tests.

## Canonical proof construction and custom code

Editorial decisions live in CMap, BMap, Tracks, Animation, SyncMap, the
iteration ledger, and the immutable ProofPlan. Proofs are always rebuilt from
original or admitted generated sources. A previous proof, preview, proxy,
master, or delivery file may be compared but cannot become picture or audio
input, even after copying, renaming, cropping, re-encoding, or extracting audio.

Use built-in capabilities first, then compatible provider components. A
video-specific script or HyperFrames component is an allowed escape hatch only
for the unsupported custom delta. It must be registered, fingerprinted,
parameterized by the ProofPlan, reproducible to its declared level, and unable
to choose sources, reinterpret timing, rebuild the mix, or bypass review.

Iteration history is cumulative. The next candidate preserves all still-active
approvals and regressions across earlier revisions, not merely the latest proof.
Creator scope additions and preference refinements remain distinct from
correctness defects and may be multi-causal when the evidence supports it.
