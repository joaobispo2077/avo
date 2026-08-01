# Audio Post Production System

This repository treats audio as an editorial and technical system, not a final
polish pass. Follow `AGENTS.md` first; this document expands the audio workflow
for YouTube projects.

## Required Diagnosis

Before editing audio, record or infer:

- Format and viewer intent.
- Speech, music, gameplay/source audio, ambience, and SFX priority.
- All source tracks, sample rates, frame rates, channel layouts, and sync method.
- Noise, clipping, hum, plosives, reverb, mouth noise, phase, drift, and missing
  room-tone risks.
- Rights, disclosure, AI/synthetic audio, privacy, safety, and reused-content
  risks.
- Delivery target, channel loudness target, and review gate.

## Default Workflow

1. Preserve and inventory originals.
2. Sync external and system audio before creative cutting.
3. Verify drift across long recordings and multicamera or gameplay sections.
4. Select the cleanest dialogue anchor and document rejected tracks.
5. Gain-stage and clip-level before restoration or compression.
6. Repair defects conservatively.
7. EQ for clarity and translation.
8. De-ess, compress, level, and limit only as needed.
9. Mix dialogue, source audio, music, SFX, and ambience according to the format.
10. Measure loudness/true peak and document the method.
11. Export and QC the encoded candidate, not only the timeline.

## Restoration Principles

Use waveform and spectral views to identify the problem before choosing a tool.
Use noise prints only from clean noise-only sections. Prefer targeted fixes over
global processing. Stop or reduce processing when artifacts become more
distracting than the original defect.

## Mix Hierarchy

Speech-led videos prioritize intelligible dialogue. Music-led videos prioritize
the performance. Gameplay and tutorials balance commentary with useful source
audio. Documentary/news/evidence-led videos require sound design that supports
clarity without implying unsupported facts.

## Measurement And Targets

Use ITU-R BS.1770/EBU R 128-style terminology when measuring loudness, but do
not describe a single LUFS number as an official YouTube requirement. Record the
internal channel target, integrated loudness, loudness range when useful, true
peak, meter standard/settings, and whether measurement was done pre- or
post-encode.

## Logs

Use `AUDIO-EDITLOG.md` for audio decisions, versions, reviews, and QC. Use
`AUDIO-SOURCE-LOG.md` or `SOURCE-LOG.md` for third-party music, SFX, stems,
samples, loops, ambience, voice models, generated music, and evidence.

## Release Blockers

- Dialogue is unintelligible for the target format.
- External audio is out of sync or drifts.
- Cleanup artifacts distract or change perceived meaning.
- Music/SFX mask speech or imply unsupported facts/emotion.
- Clipping, pops, unexpected mutes, doubled audio, or wrong channel mapping.
- Missing audio rights evidence or unresolved Content ID/reused-content risk.
- Misleading AI/synthetic audio or missing disclosure review.
- No documented loudness/peak measurement for final delivery.
