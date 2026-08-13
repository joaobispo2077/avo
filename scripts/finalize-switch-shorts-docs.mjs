import fs from "node:fs";
import path from "node:path";

const root = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE/edit/shorts/switch-comparison-shorts-proofs";
const write = (name, body) => fs.writeFileSync(path.join(root, name), `${body.trim()}\n`);

write("BRIEF.md", `
---
workflow: general-video
flow: automation
storyboard: no
message: "Choose the Nintendo Switch that fits the viewer's real use and budget."
destination: youtube-shorts-tiktok
aspect: "9:16"
language: pt-BR
audience: Brazilian Nintendo buyers
length: "24.7-58.5 seconds per Short"
provider: bishop
---

# Switch Comparison Shorts

## Intent

Create ten vertical Shorts cut from the approved long-form Switch Lite vs OLED vs Switch 2 master. Shorts 02, 04, and 06 use the approved PC gameplay attention insert below the Switch footage. The other seven use a clean product-first vertical composition.

The original argument and qualifiers remain intact. Playback is accelerated only to 1.15× or 1.2× while speech stays intelligible.

## Assets

- Approved source master: edit/masters/20260731-switch-comparison-master-v009-conclusion-fix-candidate.mp4
- Final-master word transcript: edit/transcripts/20260731-switch-comparison-master-v009-conclusion-fix-candidate.json
- Approved attention insert: H:/bishop/pcrecordings/2025-10-30 12-20-11.mkv
- Insert audio: PCSHOP only, stream 0:a:0. MICSHOP and PLACASHOP excluded.
- Bishop design tokens: providers/bishop/DESIGN.md and providers/bishop/brand/palette.json.

## Customizations

- Burned, punchy PT-BR captions on the middle rail.
- Caption phrases normally contain 1-5 displayed words.
- One emphasized word per phrase and one earned apex phrase per Short.
- Primary colors: #F7F9FC, #16181F, #371960, and #19D8FF.
- Motion density Level 2-3.
- Maximum duration: 60 seconds.

## Approval and delivery gate

The user approved deterministic visual proofs before high-quality rendering. Only QC-passed exports are promoted to the delivery master set.

## Risks

- Price claims carry a 2026 date label.
- Personal battery observations are not presented as universal specs.
- Gameplay is decorative, not evidence.
- PCSHOP game audio may have Content ID risk and remains a human publishing review item.
`);

write("DESIGN.md", `
# Design — Switch Comparison Shorts

## Animation diagnosis

- Primary format: vertical product-comparison Short.
- Secondary format: gameplay pattern interrupt on Shorts 02, 04, and 06.
- Viewer: Brazilian Nintendo buyer deciding between Lite, OLED, and Switch 2 on mobile.
- Promise: reach a useful buying decision quickly without changing the review's meaning.
- Package: ten Shorts; three split-screen interruptions and seven clean product-first edits.
- Canvas: 1080 × 1920 at 30 fps, with captions on a centered rail.
- Density: Level 3 for Shorts 02, 04, and 06; Level 2 for the other seven.
- Audio: narration primary; split Shorts use PCSHOP-only gameplay audio at a supporting level.
- Rights: user-provided product footage and gameplay. Gameplay is illustrative, not evidence of Switch performance.
- Framework: HyperFrames for deterministic, seekable captions and renders. Remotion rejected because no React/data-variant infrastructure is needed.

## Visual system

- Ink: #16181F
- White: #F7F9FC
- Bishop purple: #371960
- Accent cyan: #19D8FF
- Caption rail: centered, high-contrast rounded panel.
- Emphasis: one cyan or purple keyword per burst; one large apex phrase per Short.
- Safe area: critical text between y=300 and y=1580 and at least 72 px from side edges.
`);

write("ANIMATION-SOURCE-LOG.md", `
# Animation Source Log

| Asset | Purpose | Rights basis | Treatment |
|---|---|---|---|
| 20260731-switch-comparison-master-v009-conclusion-fix-candidate.mp4 | Approved Switch comparison master | User-provided / Bishop production | Excerpts retimed to 1.15× or 1.2×; no claim reordering |
| 2025-10-30 12-20-11.mkv | Attention reset for Shorts 02, 04, and 06 | User-provided recording | Video plus PCSHOP stream 0:a:0 only; MICSHOP and PLACASHOP excluded |
| Inter / system sans-serif | Captions and labels | System/browser font fallback | Deterministic cached font use |

Gameplay is explicitly illustrative and is not presented as footage captured on a Nintendo Switch model.
`);

write("ANIMATION-EDITLOG.md", `
# Animation Edit Log

## Approved proof pass

- Short 02 established the split-screen Switch/gameplay format with centered captions and PCSHOP-only support audio.
- Short 10 established the clean product-first vertical format.
- The user approved the proof composition and caption system before high-quality rendering.

## Ten-Short delivery pass v001

- 01 — Lite used price/value — 58.53 s — clean.
- 02 — Protect your finances — 42.63 s — split / PCSHOP.
- 03 — OLED price — 41.90 s — clean.
- 04 — Switch 2 price shock — 48.23 s — split / PCSHOP.
- 05 — Switch 2 games at R$ 450-500 — 44.13 s — clean.
- 06 — Lite portability/specs — 46.00 s — split / PCSHOP.
- 07 — OLED hybrid/dock advantage — 47.50 s — clean.
- 08 — Switch 2 battery observation — 57.60 s — clean.
- 09 — Buy for the game library — 49.53 s — clean.
- 10 — Which Switch is for you? — 24.67 s — clean.
- Rendered through HyperFrames at 1080 × 1920, 30 fps.
- All projects passed lint/runtime/motion/contrast checks with zero errors and warnings.
- Fresh final-file PT-BR word transcripts and SRT sidecars generated after export.
`);

write("FINAL-QC.md", `
# Final QC — Switch Comparison Shorts v001

Status: PASS

## Technical

- Ten masters: H.264/AAC, 1080 × 1920, 30 fps, 48 kHz stereo.
- Durations: 24.67-58.53 seconds.
- HyperFrames artifact validation: PASS on every render.
- Project checks: zero errors and warnings; caption contrast passes WCAG AA.
- Blackdetect: no black-frame events at 0.15 s / 10% threshold.
- Freezedetect on split Shorts 02, 04, and 06: no freezes longer than 1 second.
- Integrated loudness: -18.7 to -15.1 LUFS.
- True peak: -3.0 to -2.5 dBFS; no clipping.

## Editorial and visual

- Contact-sheet review passed at opening, midpoint, and closing frames for all ten.
- Punchy PT-BR captions stay on the middle rail and remain mobile-readable.
- Gameplay appears only in Shorts 02, 04, and 06, exactly 30% of the set.
- Gameplay is an illustrative attention reset, not product evidence.
- Insert audio mapping is PCSHOP 0:a:0 only; MICSHOP and PLACASHOP are excluded.
- No claim reordering or manufactured conclusion.

## Transcript gate

- Fresh ASR generated from every exported master.
- Ten normalized word-level JSON files and ten SRT sidecars delivered.
- Zero music/noise tokens after review.
- Product and retail terms corrected, including OLX, bundle, dock, cupom, and Donkey Kong Bananza.
- Whisper clock drift on Shorts 04 and 09 normalized to exact final duration; all timestamps finish inside their master.

## Evidence

- qc/summary.tsv
- qc/final-render-contact-sheet.jpg
- qc/blackdetect/
- qc/freezedetect/
- qc/loudness/
- qc/transcript-quality.json
- delivery/SHA256SUMS.txt
`);

write("DELIVERY-MANIFEST.md", `
# Delivery Manifest — Switch Comparison Shorts v001

Delivery directory: edit/shorts/switch-comparison-shorts-proofs/delivery/

| Short | Master | Duration | Layout |
|---|---|---:|---|
| 01 | 20260809-switch-comparison-short-01-master-v001.mp4 | 58.53 s | Clean |
| 02 | 20260809-switch-comparison-short-02-master-v001.mp4 | 42.63 s | Split / PCSHOP |
| 03 | 20260809-switch-comparison-short-03-master-v001.mp4 | 41.90 s | Clean |
| 04 | 20260809-switch-comparison-short-04-master-v001.mp4 | 48.23 s | Split / PCSHOP |
| 05 | 20260809-switch-comparison-short-05-master-v001.mp4 | 44.13 s | Clean |
| 06 | 20260809-switch-comparison-short-06-master-v001.mp4 | 46.00 s | Split / PCSHOP |
| 07 | 20260809-switch-comparison-short-07-master-v001.mp4 | 47.50 s | Clean |
| 08 | 20260809-switch-comparison-short-08-master-v001.mp4 | 57.60 s | Clean |
| 09 | 20260809-switch-comparison-short-09-master-v001.mp4 | 49.53 s | Clean |
| 10 | 20260809-switch-comparison-short-10-master-v001.mp4 | 24.67 s | Clean |

## Sidecars

For every master, edit/transcripts/ contains a reviewed word-level PT-BR JSON file and a YouTube-ready PT-BR SRT file under the same master basename.

## Integrity and review

- Master hashes: delivery/SHA256SUMS.txt
- QC record: FINAL-QC.md
- Visual evidence: qc/final-render-contact-sheet.jpg
- Provenance: ANIMATION-SOURCE-LOG.md
- Editorial decisions: ANIMATION-EDITLOG.md
`);

console.log("Finalized Switch Shorts delivery documentation.");
