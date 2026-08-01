# Multi-provider patterns

Use when one human brand publishes to multiple **format families**. AVO learns
per provider slug — split when QC, captions, pacing, or motion rules diverge.

## Pattern A — One YouTube channel, long + Shorts

```text
providers/yt-acme-long-videos/
  kind: youtube
  scope: "16:9 long-form, chapters, slower pacing"
  media.rawRoot: /footage/acme/long

providers/yt-acme-short-videos/
  kind: shorts
  scope: "9:16 clips, hook-first, no chapter cards"
  media.rawRoot: /footage/acme/shorts
```

**Share:** palette tokens, logo files, display name prefix  
**Keep separate:** slug, scope, `kind`, raw roots, DESIGN.md motion/caption sections, ai-memory

## Pattern B — Same brand, different platforms

```text
providers/acme-youtube/     kind: youtube
providers/acme-tiktok/      kind: tiktok
providers/acme-instagram/   kind: instagram
```

Each platform gets its own safe zones, playbook, and learndown. Copy brand colors;
rewrite caption and pacing sections per platform.

## Pattern C — One provider, mixed durations (OK when rules match)

Single slug when:

- Same aspect ratio and caption spec
- Same pacing playbook (e.g. 8–20 min tutorials)
- Same motion density and thumbnail grammar

Example: `providers/bishop/` for all standard YouTube uploads on one channel.

## Anti-patterns

| Don't | Why |
| --- | --- |
| One slug for YouTube + TikTok | Safe zones and retention rules conflict |
| One slug for long-form + Shorts | Learndown poisons cut decisions |
| Duplicate slug with different raw roots | Slug must be unique; use `--raw-dir` per video instead |
| Put footage inside `providers/` | Media is always external |

## Forking brand from an existing provider

1. Copy `brand/palette.json` and relevant `DESIGN.md` sections
2. New slug + new `avo.provider.json` (new scaffolder run)
3. Rewrite **scope**, **kind**, caption/motion sections for the new format
4. Point `media.rawRoot` at a dedicated external folder
